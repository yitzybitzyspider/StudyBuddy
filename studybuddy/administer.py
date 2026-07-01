"""Stage 5 (thin): administer and grade.

Read the filled answers file, grade each response, and record a DiagnosticResult. Objective
formats (mc, numeric) auto-grade deterministically; open-ended formats (short, essay,
application) go through ``grade_response`` against the item's grading spec. Feedback is
returned as a batch after every answer is graded (FR-C5). Each served item's calibration
(times_seen, correct_rate) is updated — the safe auto-accrual track (decision E6).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from . import calibration as calibration_mod
from . import diagnostic as diagnostic_mod
from . import ids, spacing as spacing_mod, store
from .models import DiagnosticResult, Item, ItemFormat, ItemResponse
from .wrapper import run_call

_OBJECTIVE = {ItemFormat.mc, ItemFormat.numeric}
_OPEN_PASS_FRACTION = 0.6  # open-ended counts "correct" at >= 60% of max score (thin)


def _norm(value) -> str:
    return str(value).strip().lower()


def _is_blank(response) -> bool:
    return response is None or (isinstance(response, str) and not response.strip())


def _auto_grade(item: Item, response) -> bool:
    if item.format is ItemFormat.numeric:
        try:
            return abs(float(response) - float(item.answer_key)) <= 1e-6
        except (TypeError, ValueError):
            return _norm(response) == _norm(item.answer_key)
    return _norm(response) == _norm(item.answer_key)  # mc: option text/letter match


def grade_item(item: Item, response, *, root=None, client=None) -> tuple[bool, bool, dict]:
    """Grade one answered item. Returns (correct, blank, feedback_entry).

    Shared by Stage 5 (administer) and Stage 9 (execute): objective formats auto-grade,
    open-ended go through ``grade_response``. No persistence here — callers own writeback.
    """
    blank = _is_blank(response)
    entry = {"item_id": item.id, "format": item.format.value, "stem": item.stem}
    if blank:
        entry.update(correct=False, blank=True, correct_answer=item.answer_key)
        return False, True, entry
    if item.format in _OBJECTIVE:
        correct = _auto_grade(item, response)
        entry.update(correct=correct, correct_answer=item.answer_key)
        return correct, False, entry
    graded = run_call(
        "grade_response",
        {
            "response": str(response),
            "grading_spec": item.grading_spec.model_dump(mode="json"),
            "stem": item.stem,
        },
        root=root,
        client=client,
        phase="Stage 5: grade_response",
    )
    max_score = item.grading_spec.max_score or 1.0
    correct = graded["score"] >= _OPEN_PASS_FRACTION * max_score
    entry.update(
        correct=correct,
        score=graded["score"],
        reasoning=graded.get("reasoning"),
        missed_facets=graded.get("missed_facets", []),
    )
    return correct, False, entry


def administer(
    subject: str,
    *,
    answers: dict | None = None,
    answers_path=None,
    root=None,
    client=None,
    learner_id: str = store.DEFAULT_LEARNER,
) -> dict:
    """Grade a filled diagnostic. Answers come in-memory (web), from a file path (CLI
    --answers), or from the stored working doc (default)."""
    if answers is not None:
        data = answers
    elif answers_path is not None:
        data = json.loads(Path(answers_path).read_text(encoding="utf-8"))
    else:
        data = store.get_doc(learner_id, subject, diagnostic_mod.ANSWERS_NAME, root=root)
        if data is None:
            raise FileNotFoundError("no filled diagnostic answers found; run compose first")

    bank = {i.id: i for i in store.load_items(subject, root=root)}
    diag = store.load_diagnostic(learner_id, subject=subject, root=root) or {}
    confidence_k = float(store.load_heuristics(root=root).calibration.get("confidence_k", 4))

    responses: list[ItemResponse] = []
    feedback: list[dict] = []
    qualities: list[tuple[str, int]] = []  # (item_id, SM-2 quality) for the spacing engine
    rollup: dict[str, dict] = defaultdict(lambda: {"seen": 0, "correct": 0, "blanks": 0})

    for q in data.get("questions", []):
        item = bank.get(q["item_id"])
        if item is None:
            continue
        response = q.get("response")
        felt_lucky = bool(q.get("felt_lucky", False))
        time_spent = q.get("time_spent")
        correct, blank, entry = grade_item(item, response, root=root, client=client)

        responses.append(
            ItemResponse(
                item_id=item.id,
                response=response,
                correct=correct,
                time_spent=time_spent,
                felt_lucky_flag=felt_lucky,
            )
        )
        feedback.append(entry)
        calibration_mod.update(item, correct, confidence_k=confidence_k)
        qualities.append(
            (item.id, spacing_mod.quality_from_outcome(correct, blank=blank, felt_lucky=felt_lucky))
        )
        for cid in item.concept_ids:
            r = rollup[cid]
            r["seen"] += 1
            r["correct"] += 1 if correct else 0
            r["blanks"] += 1 if blank else 0

    for r in rollup.values():
        r["correct_rate"] = r["correct"] / r["seen"] if r["seen"] else 0.0

    result = DiagnosticResult(
        id=ids.ulid_id("diag"),
        learner_id=learner_id,
        item_responses=responses,
        per_concept_rollup=dict(rollup),
        generated_at=ids.utcnow(),
    )

    state = store.load_learner(learner_id, subject=subject, root=root)
    state.diagnostic_results.append(result)
    now = ids.utcnow()  # spacing accrual (Track A): schedule each answered item for review
    for item_id, quality in qualities:
        spacing_mod.update_schedule(state, item_id, quality, now=now)
    store.save_learner(state, subject=subject, root=root)
    store.save_items(subject, list(bank.values()), root=root)  # persist calibration updates

    if diag:
        diag["diagnostic_result_id"] = result.id
        store.save_diagnostic(learner_id, diag, subject=subject, root=root)

    correct_count = sum(1 for f in feedback if f["correct"])
    return {
        "result": result,
        "feedback": feedback,
        "answered": len(feedback),
        "correct": correct_count,
    }
