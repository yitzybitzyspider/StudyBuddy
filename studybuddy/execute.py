"""Stage 9: the in-system execution loop (Phase 4, Loop 22).

Study happens *inside* the system — no downloads. A session serves spaced and interleaved
items (due reviews first, then new learning to fill), the learner answers, and the engine
grades, **reschedules** each item through the spacing engine, and tracks progress. Everything
is deterministic except the open-ended grading call (reused from Stage 5).

File-based interaction (decision E2), mirroring the diagnostic: ``next_session`` writes an
editable answers file; the learner fills it; ``record_session`` grades and reschedules.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import administer as administer_mod
from . import calibration as calibration_mod
from . import ids, spacing as spacing_mod, store

SESSION_NAME = "session.answers.json"
_DEFAULT_SIZE = 10


def _concept_of(item) -> str:
    return item.concept_ids[0] if item.concept_ids else ""


def _plan_item_order(state) -> list[str]:
    """Item ids drawn from the plan's per-topic sequences (foundational → synthesis)."""
    order: list[str] = []
    if state.study_plan:
        for topic in state.study_plan.topics:
            order.extend(topic.item_sequence)
    return order


def next_session(
    subject: str, *, root=None, learner_id: str = store.DEFAULT_LEARNER,
    size: int | None = None, now=None,
) -> dict:
    """Assemble the next study session: due reviews first, then new items, interleaved."""
    state = store.load_learner(learner_id, root=root)
    items = store.load_items(subject, root=root)
    item_by_id = {it.id: it for it in items}
    now = now or ids.utcnow()
    size = size or _DEFAULT_SIZE

    due = [iid for iid in spacing_mod.due_items(state, now=now) if iid in item_by_id]
    chosen = list(due)

    if len(chosen) < size:  # fill with new learning the learner has not seen yet
        seen = set(state.spacing_schedule or {}) | set(chosen)
        fill_pool = _plan_item_order(state) + [it.id for it in items]
        for iid in fill_pool:
            if len(chosen) >= size:
                break
            if iid in item_by_id and iid not in seen:
                chosen.append(iid)
                seen.add(iid)

    chosen = chosen[:size]
    ordered = spacing_mod.interleave(chosen, lambda i: _concept_of(item_by_id[i]))

    concepts = {c.id: c.name for c in store.load_concepts(subject, root=root)}
    questions = []
    for iid in ordered:
        it = item_by_id[iid]
        questions.append(
            {
                "item_id": it.id,
                "concept": concepts.get(_concept_of(it), _concept_of(it)),
                "format": it.format.value,
                "stem": it.stem,
                "options": it.options,
                "response": "",
                "felt_lucky": False,
                "time_spent": None,
                "review": iid in due,  # True = a spaced review, False = new learning
            }
        )
    payload = {
        "_instructions": (
            "Answer every question, then run: studybuddy record-session "
            f"--subject {subject}"
        ),
        "subject": subject,
        "questions": questions,
    }
    path = store.learner_file(learner_id, SESSION_NAME, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "session_path": path, "item_ids": ordered,
        "due_count": len(due), "new_count": len(chosen) - len(due),
    }


def record_session(
    subject: str, *, answers_path=None, root=None, client=None,
    learner_id: str = store.DEFAULT_LEARNER, now=None,
) -> dict:
    """Grade a completed session, reschedule each item, and track progress."""
    if answers_path is None:
        answers_path = store.learner_file(learner_id, SESSION_NAME, root=root)
    data = json.loads(Path(answers_path).read_text(encoding="utf-8"))
    bank = {i.id: i for i in store.load_items(subject, root=root)}
    state = store.load_learner(learner_id, root=root)
    confidence_k = float(store.load_heuristics(root=root).calibration.get("confidence_k", 4))
    now = now or ids.utcnow()

    feedback: list[dict] = []
    correct_count = 0
    progress = state.progress or {}
    by_concept = progress.get("by_concept") or {}

    for q in data.get("questions", []):
        item = bank.get(q["item_id"])
        if item is None:
            continue
        response = q.get("response")
        felt_lucky = bool(q.get("felt_lucky", False))
        correct, blank, entry = administer_mod.grade_item(item, response, root=root, client=client)
        feedback.append(entry)
        correct_count += 1 if correct else 0

        calibration_mod.update(item, correct, confidence_k=confidence_k)
        quality = spacing_mod.quality_from_outcome(correct, blank=blank, felt_lucky=felt_lucky)
        spacing_mod.update_schedule(state, item.id, quality, now=now)
        for cid in item.concept_ids:
            c = by_concept.setdefault(cid, {"seen": 0, "correct": 0})
            c["seen"] += 1
            c["correct"] += 1 if correct else 0

    answered = len(feedback)
    progress["by_concept"] = by_concept
    progress["reviewed_total"] = int(progress.get("reviewed_total", 0)) + answered
    progress["sessions"] = int(progress.get("sessions", 0)) + 1
    progress["last_session_at"] = now.isoformat()
    state.progress = progress

    store.save_learner(state, root=root)
    store.save_items(subject, list(bank.values()), root=root)  # persist calibration

    upcoming = spacing_mod.due_items(state, now=now)
    return {
        "answered": answered,
        "correct": correct_count,
        "feedback": feedback,
        "rescheduled": answered,
        "due_now": len(upcoming),
    }
