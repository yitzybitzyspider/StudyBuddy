"""Flask routes for the StudyBuddy web UI.

Guided flow: pick a subject -> ingest material -> intake -> compose & take the diagnostic ->
results -> diagnose -> plan (with more/fewer/shift steer). Every pipeline call is the same
function the CLI uses; this layer only marshals form data and renders templates.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from flask import (
    Flask,
    abort,
    current_app,
    redirect,
    render_template,
    request,
    url_for,
)

from .. import administer as administer_mod
from .. import diagnose as diagnose_mod
from .. import diagnostic as diagnostic_mod
from .. import execute as execute_mod
from .. import ingest as ingest_mod
from .. import intake as intake_mod
from .. import paths, plan as plan_mod, seed, store
from .. import websearch as websearch_mod
from ..models import MaterialType
from ..wrapper import ClaudeCallError

ALLOWED_SUFFIXES = {".txt", ".md", ".pdf"}


# --- small helpers --------------------------------------------------------------------


def _root() -> Path:
    return Path(current_app.config["SB_ROOT"])


def _learner() -> str:
    return store.current_learner()


def _subject_status(subject: str) -> dict:
    root = _root()
    concepts = store.load_concepts(subject, root=root)
    learner = store.load_learner(_learner(), subject=subject, root=root)
    diag = store.load_diagnostic(_learner(), subject=subject, root=root)
    return {
        "topics": len(concepts),
        "items": len(store.load_items(subject, root=root)),
        "has_intake": learner.intake is not None,
        "has_diagnostic": bool(diag),
        "graded": bool(learner.diagnostic_results),
        "has_gaps": learner.gap_profile is not None,
        "has_plan": learner.study_plan is not None,
    }


def _course_summary(subject: str) -> dict:
    """Everything the dashboard/course pages show for one course, in one read."""
    from .. import ids as ids_mod
    from .. import sampling as sampling_mod
    from .. import spacing as spacing_mod

    root = _root()
    learner = store.load_learner(_learner(), subject=subject, root=root)
    status = _subject_status(subject)

    by_concept = (learner.progress or {}).get("by_concept") or {}
    seen = sum(c.get("seen", 0) for c in by_concept.values())
    correct = sum(c.get("correct", 0) for c in by_concept.values())
    # fold in diagnostic results for mastery when no study sessions yet
    for r in learner.diagnostic_results:
        for s in r.per_concept_rollup.values():
            seen += s.get("seen", 0)
            correct += s.get("correct", 0)
    mastery = round(100 * correct / seen) if seen else None

    due = len(spacing_mod.due_items(learner, now=ids_mod.utcnow()))
    open_gaps = 0
    sampling_open = False
    if learner.gap_profile:
        from ..models import GapStatus

        open_gaps = sum(
            1 for e in learner.gap_profile.entries if e.status is not GapStatus.resolved
        )
        if learner.diagnostic_results:
            heur = store.load_heuristics(root=root)
            sampling_open = not sampling_mod.stopping_status(learner, heur)["stop"]

    # the one thing to do next (deterministic — the pipeline's own ordering)
    if status["topics"] == 0:
        action = ("Upload your first material", "materials_view",
                  "Add a past exam, chapter, or notes — topics and real questions come from it.")
    elif not status["has_intake"]:
        action = ("Set up your intake", "intake_view",
                  "Your exam format, hours, and per-topic confidence shape the whole plan.")
    elif not status["graded"]:
        action = ("Take your diagnostic", "diagnostic_view",
                  "A short test that finds where understanding actually breaks down.")
    elif sampling_open:
        action = ("Continue adaptive testing", "diagnostic_view",
                  "Your gaps aren't confirmed yet — a short focused batch narrows them.")
    elif not status["has_plan"]:
        action = ("Build your study plan", "plan_view",
                  "Turn the confirmed gaps into a source-linked, time-honest plan.")
    elif due:
        action = (f"Study — {due} review{'s' if due != 1 else ''} due", "study_view",
                  "Spaced reviews are back; a session keeps the schedule honest.")
    else:
        action = ("Study new material", "study_view",
                  "Nothing due — pull new practice from your plan.")

    return {
        **status,
        "subject": subject,
        "mastery": mastery,
        "due": due,
        "open_gaps": open_gaps,
        "action_label": action[0],
        "action_endpoint": action[1],
        "action_note": action[2],
    }


def _markdown_to_html(text: str) -> str:
    """Tiny, safe-enough markdown render for the plan one-pager (headings, bold, italics)."""
    from markupsafe import escape

    out: list[str] = []
    for raw in text.splitlines():
        line = escape(raw)
        if raw.startswith("# "):
            out.append(f"<h2>{line[2:]}</h2>")
        elif raw.startswith("## "):
            out.append(f"<h3>{line[3:]}</h3>")
        elif not raw.strip():
            out.append("")
        else:
            line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", str(line))
            line = re.sub(r"_(.+?)_", r"<em>\1</em>", line)
            out.append(f"<p>{line}</p>")
    return "\n".join(out)


def _topic_rows(concepts):
    """Flatten the concept hierarchy into (depth, name) rows for rendering."""
    ids = {c.id for c in concepts}
    by_parent: dict = {}
    for c in concepts:
        key = c.parent_id if c.parent_id in ids else None
        by_parent.setdefault(key, []).append(c)
    rows: list[tuple[int, str]] = []

    def walk(parent, depth):
        for c in sorted(by_parent.get(parent, []), key=lambda x: x.name):
            rows.append((depth, c.name))
            walk(c.id, depth + 1)

    walk(None, 0)
    return rows


def _err(message: str, subject: str | None = None, code: int = 200):
    hint = (
        "If this was a live Claude call, make sure ANTHROPIC_API_KEY is set in the shell that "
        "started the server — or set STUDYBUDDY_OFFLINE=1 to try the flow without a key."
    )
    return render_template("error.html", message=message, hint=hint, subject=subject), code


# --- app factory ----------------------------------------------------------------------


def create_app(root=None, auth_provider=None) -> Flask:
    import os
    import secrets

    from . import auth as auth_mod

    app = Flask(__name__)
    resolved = paths.knowledge_root(root)
    for d in paths.KNOWLEDGE_DIRS:
        (resolved / d).mkdir(parents=True, exist_ok=True)
    (resolved / "runs" / "blobs").mkdir(parents=True, exist_ok=True)
    seed.seed_knowledge_layer(root=resolved)  # idempotent
    app.config["SB_ROOT"] = str(resolved)
    # Signs the session cookie. In platform mode a stable key is REQUIRED — multi-worker
    # servers with per-process random keys would invalidate sessions on every other request.
    platform_mode = os.environ.get("STUDYBUDDY_BACKEND") == "supabase"
    secret = os.environ.get("FLASK_SECRET_KEY")
    if platform_mode and not secret:
        raise RuntimeError(
            "platform mode (STUDYBUDDY_BACKEND=supabase) requires FLASK_SECRET_KEY — "
            "set it to a long random string"
        )
    app.secret_key = secret or secrets.token_hex(32)
    if platform_mode:
        # Behind a TLS-terminating proxy (Render/Railway/Fly): trust X-Forwarded-* so
        # url_for/redirects generate https URLs and the client IP is real.
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
        app.config.update(
            SESSION_COOKIE_SECURE=True,
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE="Lax",
        )
    app.jinja_env.filters["md"] = _markdown_to_html

    @app.get("/healthz")
    def healthz():  # host health checks (open endpoint)
        return {"ok": True}

    app.jinja_env.globals["offline"] = bool(os.environ.get("STUDYBUDDY_OFFLINE"))
    provider = auth_provider or auth_mod.default_provider()
    auth_mod.install(app, provider)
    app.jinja_env.globals["auth_enabled"] = provider.enabled

    # Catch-all: turn any unhandled exception into the friendly error page (with the real
    # message) instead of a raw 500, and keep the traceback in the server log.
    @app.errorhandler(Exception)
    def _on_error(exc):
        from werkzeug.exceptions import HTTPException

        if isinstance(exc, HTTPException):
            return exc
        current_app.logger.exception("unhandled error")
        subject = (request.view_args or {}).get("subject")
        return _err(f"Something went wrong: {exc}", subject, code=500)

    # -- subject picker ----------------------------------------------------------------

    @app.get("/")
    def index():
        subjects = store.list_subjects(root=_root())
        courses = [_course_summary(s) for s in subjects]
        due_total = sum(c["due"] for c in courses)
        return render_template("index.html", courses=courses, due_total=due_total)

    @app.post("/subject")
    def create_subject():
        raw_name = request.form.get("subject", "")
        name = store.ids.slugify(raw_name)
        if not name:
            return _err("Please enter a subject name.")
        store.ensure_subject(name, raw_name.strip() or name, root=_root())
        return redirect(url_for("subject_home", subject=name))

    @app.get("/s/<subject>")
    def subject_home(subject):
        return render_template(
            "subject.html", subject=subject, course=_course_summary(subject)
        )

    # -- materials tab -------------------------------------------------------------------

    @app.get("/s/<subject>/materials")
    def materials_view(subject):
        materials = store.load_materials(subject, root=_root())
        return render_template(
            "materials.html", subject=subject, materials=materials,
            status=_subject_status(subject),
        )

    @app.get("/s/<subject>/materials/<material_id>/raw")
    def material_raw_view(subject, material_id):
        materials = {m.id: m for m in store.load_materials(subject, root=_root())}
        m = materials.get(material_id)
        if m is None:
            return _err("Material not found.", subject)
        try:
            text = store.load_material_raw(m.raw_ref, subject=subject, root=_root())
        except (OSError, KeyError):
            text = "(raw text unavailable)"
        return render_template("material_raw.html", subject=subject, material=m, text=text)

    @app.post("/s/<subject>/materials/<material_id>/delete")
    def material_delete_view(subject, material_id):
        store.delete_material(subject, material_id, root=_root())
        return redirect(url_for("materials_view", subject=subject))

    # -- Stage 1: ingest ---------------------------------------------------------------

    @app.route("/s/<subject>/ingest", methods=["GET", "POST"])
    def ingest_view(subject):
        if request.method == "GET":
            return render_template("ingest.html", subject=subject, status=_subject_status(subject))
        files = request.files.getlist("material")
        mtype = request.form.get("type", "section")
        saved: list[str] = []
        # per-request temp dir: uploads are transient input to ingest(); the durable copy is
        # persisted by save_material_raw through the storage backend
        updir = Path(tempfile.mkdtemp(prefix="sb-upload-"))
        for f in files:
            if not f or not f.filename:
                continue
            suffix = Path(f.filename).suffix.lower()
            if suffix not in ALLOWED_SUFFIXES:
                return _err(f"Unsupported file type {suffix!r}. Use .txt, .md, or .pdf.", subject)
            dest = updir / Path(f.filename).name
            f.save(dest)
            saved.append(str(dest))
        if not saved:
            return _err("No files uploaded.", subject)
        try:
            summary = ingest_mod.ingest(
                subject, saved, material_type=MaterialType(mtype), root=_root()
            )
        except ClaudeCallError as e:
            return _err(f"Ingestion failed: {e}", subject)
        # Intake immediately follows ingest, built from what was just extracted. (Ingest is
        # additive — the counts reflect everything merged so far, not just this upload.)
        return redirect(url_for("intake_view", subject=subject,
                                added_concepts=summary["concepts"], added_items=summary["items"]))

    @app.get("/s/<subject>/topics")
    def topics_view(subject):
        return render_template(
            "topics.html", subject=subject, summary=None,
            rows=_topic_rows(store.load_concepts(subject, root=_root())),
            status=_subject_status(subject),
        )

    @app.post("/s/<subject>/harvest-web")
    def harvest_web_view(subject):
        try:
            result = websearch_mod.web_harvest(subject, root=_root())
        except (ValueError, ClaudeCallError) as e:
            return _err(f"Web harvest failed: {e}", subject)
        return render_template(
            "topics.html", subject=subject, summary=None, harvest=result,
            rows=_topic_rows(store.load_concepts(subject, root=_root())),
            status=_subject_status(subject),
        )

    # -- Stage 3: intake ---------------------------------------------------------------

    @app.route("/s/<subject>/intake", methods=["GET", "POST"])
    def intake_view(subject):
        concepts = store.load_concepts(subject, root=_root())
        if request.method == "GET":
            return render_template(
                "intake.html", subject=subject, concepts=concepts,
                rows=_topic_rows(concepts), status=_subject_status(subject),
                added_concepts=request.args.get("added_concepts"),
                added_items=request.args.get("added_items"),
            )
        confidence = {}
        for c in concepts:
            v = request.form.get(f"conf_{c.id}", "")
            if v not in ("", "unrated"):
                confidence[c.name] = float(v)
        answers = {
            "subject": subject,
            "exam_format": request.form.get("exam_format", ""),
            "total_study_time_hours": _num(request.form.get("total_study_time_hours")),
            "daily_availability_hours": _num(request.form.get("daily_availability_hours")),
            "baseline": request.form.get("baseline", ""),
            "per_topic_confidence": confidence,
        }
        intake_mod.ingest_answers(subject, answers=answers, root=_root())
        return redirect(url_for("subject_home", subject=subject))

    # -- Stage 4/5: compose, take, grade -----------------------------------------------

    @app.post("/s/<subject>/compose")
    def compose_view(subject):
        size = _num(request.form.get("size")) or None
        try:
            diagnostic_mod.compose(subject, root=_root(), size=int(size) if size else None)
        except (ValueError, ClaudeCallError) as e:
            return _err(f"Could not compose the diagnostic: {e}", subject)
        return redirect(url_for("diagnostic_view", subject=subject))

    @app.route("/s/<subject>/diagnostic", methods=["GET", "POST"])
    def diagnostic_view(subject):
        data = store.get_doc(_learner(), subject, diagnostic_mod.ANSWERS_NAME, root=_root())
        if not isinstance(data, dict):
            # nothing composed yet -> the setup screen (compose posts to compose_view)
            return render_template(
                "test_setup.html", subject=subject, status=_subject_status(subject)
            )
        if request.method == "GET":
            return render_template("diagnostic.html", subject=subject, questions=data["questions"])
        for q in data["questions"]:
            q["response"] = request.form.get(f"resp_{q['item_id']}", "")
            q["felt_lucky"] = request.form.get(f"lucky_{q['item_id']}") == "on"
            t = _num(request.form.get(f"time_{q['item_id']}"))
            if t:
                q["time_spent"] = t
        store.put_doc(_learner(), subject, diagnostic_mod.ANSWERS_NAME, data, root=_root())
        try:
            result = administer_mod.administer(subject, answers=data, root=_root())
        except ClaudeCallError as e:
            return _err(f"Grading failed: {e}", subject)
        # the answered cycle is done; a fresh visit to Test offers the setup screen again
        store.delete_doc(_learner(), subject, diagnostic_mod.ANSWERS_NAME, root=_root())
        return render_template(
            "results.html", subject=subject, result=result, status=_subject_status(subject)
        )

    # -- Stage 6/8: diagnose + plan ----------------------------------------------------

    @app.post("/s/<subject>/diagnose")
    def diagnose_view(subject):
        try:
            diagnose_mod.diagnose(subject, root=_root())
        except (ValueError, ClaudeCallError) as e:
            return _err(f"Diagnosis failed: {e}", subject)
        return redirect(url_for("gaps_view", subject=subject))

    @app.get("/s/<subject>/gaps")
    def gaps_view(subject):
        from .. import sampling as sampling_mod
        from ..models import GapStatus

        root = _root()
        learner = store.load_learner(_learner(), subject=subject, root=root)
        if learner.gap_profile is None:
            return _err("No diagnosis yet — take the test first.", subject)
        concepts = {c.id: c for c in store.load_concepts(subject, root=root)}
        # upstream-prerequisite callouts: a gap whose concept depends on another gapped concept
        gapped_ids = {e.concept_id for e in learner.gap_profile.entries
                      if e.status is not GapStatus.resolved}
        upstream = {}
        for cid in gapped_ids:
            c = concepts.get(cid)
            if not c:
                continue
            for edge in c.dependency_edges:
                if edge.other_concept_id in gapped_ids:
                    upstream[cid] = concepts[edge.other_concept_id].name
                    break
        status = sampling_mod.stopping_status(learner, store.load_heuristics(root=root))
        return render_template(
            "gaps.html", subject=subject, entries=learner.gap_profile.entries,
            names={cid: c.name for cid, c in concepts.items()}, upstream=upstream,
            sampling=status, GapStatus=GapStatus,
        )

    @app.post("/s/<subject>/adaptive")
    def adaptive_view(subject):
        from .. import sampling as sampling_mod

        try:
            result = sampling_mod.next_batch(subject, root=_root(), learner_id=_learner())
        except (ValueError, ClaudeCallError) as e:
            return _err(f"Could not compose the next batch: {e}", subject)
        if not result["composed"]:
            return redirect(url_for("gaps_view", subject=subject))
        return redirect(url_for("diagnostic_view", subject=subject))

    @app.get("/s/<subject>/plan")
    def plan_view(subject):
        learner = store.load_learner(_learner(), subject=subject, root=_root())
        if learner.gap_profile is None:
            return _err("Run the diagnosis first.", subject)
        resolution = request.args.get("resolve")  # compress | extend (Stage 8)
        if resolution not in (None, "compress", "extend"):
            resolution = None
        try:
            result = plan_mod.compose(subject, root=_root(), resolution=resolution)
        except (ValueError, ClaudeCallError) as e:
            return _err(f"Plan generation failed: {e}", subject)
        return render_template(
            "plan.html", subject=subject, markdown=result["markdown"],
            gaps=learner.gap_profile.entries, budget=result.get("budget"),
        )

    @app.route("/s/<subject>/study", methods=["GET", "POST"])
    def study_view(subject):
        if request.method == "POST" and request.form.get("answers"):
            data = store.get_doc(_learner(), subject, execute_mod.SESSION_NAME, root=_root())
            if not isinstance(data, dict):
                return _err("No study session in progress. Start one first.", subject)
            for q in data["questions"]:
                q["response"] = request.form.get(f"resp_{q['item_id']}", "")
                q["felt_lucky"] = request.form.get(f"lucky_{q['item_id']}") == "on"
            store.put_doc(_learner(), subject, execute_mod.SESSION_NAME, data, root=_root())
            try:
                result = execute_mod.record_session(subject, answers=data, root=_root())
            except ClaudeCallError as e:
                return _err(f"Recording the session failed: {e}", subject)
            return render_template("session_done.html", subject=subject, result=result)
        # GET (or compose a fresh session)
        info = execute_mod.next_session(subject, root=_root())
        if not info["item_ids"]:
            return render_template("session_done.html", subject=subject, result=None)
        return render_template(
            "session.html", subject=subject, questions=info["session"]["questions"],
            due_count=info["due_count"], new_count=info["new_count"],
        )

    @app.post("/s/<subject>/steer")
    def steer_view(subject):
        action = request.form.get("action", "more")
        focus = request.form.get("focus") or None
        try:
            plan_mod.steer(
                subject, action=action, focus=[focus] if focus else None, root=_root()
            )
        except (ValueError, ClaudeCallError) as e:
            return _err(f"Steer failed: {e}", subject)
        return redirect(url_for("diagnostic_view", subject=subject))

    return app


def _num(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None
