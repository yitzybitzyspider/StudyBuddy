"""Stage 3 (thin): intake interview.

Deterministic and file-based (decision E2). First present the extracted topics back to the
user (FR-A5) and emit an editable template asking the five things intake must capture
(FR-A6): exam format, total study time, daily availability, rough baseline, and per-topic
confidence. The user fills it in; we read it back into ``LearnerState.intake``. No Claude
call — the optional "light Claude pass" of spec §3 is scoped out (decision B6).
"""

from __future__ import annotations

import json
from pathlib import Path

from . import store
from .models import Intake

TEMPLATE_NAME = "intake.template.json"


def build_template(subject: str, *, root=None, learner_id=store.DEFAULT_LEARNER):
    concepts = store.load_concepts(subject, root=root)
    template = {
        "_instructions": (
            "Fill in the fields below, then run: "
            f"studybuddy intake --subject {subject} --answers <this file>. "
            "Set per_topic_confidence values to 0.0-1.0 (leave null to skip a topic)."
        ),
        "subject": subject,
        "exam_format": "",
        "total_study_time_hours": None,
        "daily_availability_hours": None,
        "baseline": "",
        "per_topic_confidence": {c.name: None for c in sorted(concepts, key=lambda x: x.name)},
    }
    store.put_doc(learner_id, subject, TEMPLATE_NAME, template, root=root)
    return store.doc_path(learner_id, subject, TEMPLATE_NAME, root=root)


def ingest_answers(
    subject: str,
    answers_path=None,
    *,
    answers: dict | None = None,
    root=None,
    learner_id=store.DEFAULT_LEARNER,
) -> Intake:
    """Read filled intake answers (a dict, or a JSON file path) into learner state."""
    if answers is None:
        if answers_path is None:
            raise ValueError("provide answers or answers_path")
        answers = json.loads(Path(answers_path).read_text(encoding="utf-8"))
    confidence = {
        store.concept_id(name): float(value)
        for name, value in (answers.get("per_topic_confidence") or {}).items()
        if value is not None
    }
    intake = Intake(
        exam_format=(answers.get("exam_format") or None),
        total_study_time=answers.get("total_study_time_hours"),
        daily_availability=answers.get("daily_availability_hours"),
        baseline=(answers.get("baseline") or None),
        per_topic_confidence=confidence,
    )
    state = store.load_learner(learner_id, subject=subject, root=root)
    state.intake = intake
    store.save_learner(state, subject=subject, root=root)
    return intake
