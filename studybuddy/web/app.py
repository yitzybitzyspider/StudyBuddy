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


def _subject_status(subject: str) -> dict:
    root = _root()
    concepts = store.load_concepts(subject, root=root)
    learner = store.load_learner(root=root)
    diag = store.load_diagnostic(root=root)
    return {
        "topics": len(concepts),
        "items": len(store.load_items(subject, root=root)),
        "has_intake": learner.intake is not None,
        "has_diagnostic": bool(diag),
        "graded": bool(learner.diagnostic_results),
        "has_gaps": learner.gap_profile is not None,
        "has_plan": learner.study_plan is not None,
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


def create_app(root=None) -> Flask:
    app = Flask(__name__)
    resolved = paths.knowledge_root(root)
    for d in paths.KNOWLEDGE_DIRS:
        (resolved / d).mkdir(parents=True, exist_ok=True)
    (resolved / "runs" / "blobs").mkdir(parents=True, exist_ok=True)
    (resolved / "materials" / "uploads").mkdir(parents=True, exist_ok=True)
    seed.seed_knowledge_layer(root=resolved)  # idempotent
    app.config["SB_ROOT"] = str(resolved)
    app.jinja_env.filters["md"] = _markdown_to_html
    import os

    app.jinja_env.globals["offline"] = bool(os.environ.get("STUDYBUDDY_OFFLINE"))

    # -- subject picker ----------------------------------------------------------------

    @app.get("/")
    def index():
        root = _root()
        subjects = sorted(p.stem for p in (root / "concepts").glob("*.json"))
        return render_template("index.html", subjects=subjects)

    @app.post("/subject")
    def create_subject():
        name = store.ids.slugify(request.form.get("subject", ""))
        if not name:
            return _err("Please enter a subject name.")
        return redirect(url_for("subject_home", subject=name))

    @app.get("/s/<subject>")
    def subject_home(subject):
        return render_template(
            "subject.html", subject=subject, status=_subject_status(subject)
        )

    # -- Stage 1: ingest ---------------------------------------------------------------

    @app.route("/s/<subject>/ingest", methods=["GET", "POST"])
    def ingest_view(subject):
        if request.method == "GET":
            return render_template("ingest.html", subject=subject, status=_subject_status(subject))
        files = request.files.getlist("material")
        mtype = request.form.get("type", "section")
        saved: list[str] = []
        updir = _root() / "materials" / "uploads"
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
        return render_template(
            "topics.html", subject=subject, summary=summary,
            rows=_topic_rows(store.load_concepts(subject, root=_root())),
            status=_subject_status(subject),
        )

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
            return render_template("intake.html", subject=subject, concepts=concepts)
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
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
            json.dump(answers, tf)
            tmp = tf.name
        intake_mod.ingest_answers(subject, tmp, root=_root())
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
        answers_path = store.learner_file(
            store.DEFAULT_LEARNER, diagnostic_mod.ANSWERS_NAME, root=_root()
        )
        if not answers_path.exists():
            return _err("No diagnostic composed yet. Compose one first.", subject)
        data = json.loads(answers_path.read_text())
        if request.method == "GET":
            return render_template("diagnostic.html", subject=subject, questions=data["questions"])
        for q in data["questions"]:
            q["response"] = request.form.get(f"resp_{q['item_id']}", "")
            q["felt_lucky"] = request.form.get(f"lucky_{q['item_id']}") == "on"
        answers_path.write_text(json.dumps(data, indent=2))
        try:
            result = administer_mod.administer(subject, answers_path=answers_path, root=_root())
        except ClaudeCallError as e:
            return _err(f"Grading failed: {e}", subject)
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
        return redirect(url_for("plan_view", subject=subject))

    @app.get("/s/<subject>/plan")
    def plan_view(subject):
        learner = store.load_learner(root=_root())
        if learner.gap_profile is None:
            return _err("Run the diagnosis first.", subject)
        try:
            result = plan_mod.compose(subject, root=_root())
        except (ValueError, ClaudeCallError) as e:
            return _err(f"Plan generation failed: {e}", subject)
        markdown = result["markdown_path"].read_text()
        return render_template(
            "plan.html", subject=subject, markdown=markdown,
            gaps=learner.gap_profile.entries,
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
