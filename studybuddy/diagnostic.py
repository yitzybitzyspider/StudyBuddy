"""Stage 4 (thin): compose the diagnostic.

Deterministic code decides WHAT to ask: ~20 items (size from the heuristics config), ordered
to reflect the FR-C3 mix — harder probes on declared weaknesses, stress-tests on declared
strengths, and probes for topics the user did not rate (hidden gaps). Sourcing is
retrieval-first (philosophy §4): reuse the real harvested items in the bank, and only
``generate_item`` (gated by ``verify_item``) to fill what the bank cannot cover. (adapt_item
is strengthened in Phase 2; full adaptive weighting is Phase 3.)

The composed diagnostic is saved as the active cycle, and an editable answers file is written
for the user to fill (file-based interaction, decision E2).
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime

from pydantic import BaseModel

from . import ids, registry, store
from .models import (
    Concept,
    GradingSpec,
    Item,
    ItemFormat,
    Provenance,
    ProvenanceOrigin,
)
from .wrapper import run_call

ANSWERS_NAME = "diagnostic.answers.json"
_COMPONENT_FORMATS = ["mc", "short", "numeric"]  # build back up to the exam format (FR-C4)


class Diagnostic(BaseModel):
    id: str
    subject: str
    learner_id: str
    item_ids: list[str]
    created_at: datetime
    retrieved: int
    generated: int


def _priority(concept: Concept, confidence: dict[str, float]):
    """Sort key: declared weaknesses first, then hidden gaps, then declared strengths."""
    cf = confidence.get(concept.id)
    if cf is None:
        return (1, 0.0)  # hidden gap (unrated)
    return (0, cf) if cf < 0.5 else (2, cf)  # weakness (low) first; strength last


def _difficulty_for(concept: Concept, confidence: dict[str, float]) -> int:
    cf = confidence.get(concept.id)
    if cf is None:
        return 3  # hidden-gap probe: medium
    return 4  # harder on declared weaknesses, and stress-test declared strengths (FR-C3)


def _item_from_generated(gen: dict, concept: Concept, template_version: str) -> Item:
    gs = gen.get("grading_spec") or {}
    known = {k: gs[k] for k in ("rubric_text", "max_score", "facets") if k in gs}
    return Item(
        id=ids.ulid_id("item"),
        concept_ids=[concept.id],
        format=ItemFormat(gen["format"]),
        stem=gen["stem"],
        options=gen.get("options"),
        answer_key=gen["answer_key"],
        rationale=gen.get("rationale"),
        provenance=Provenance(origin=ProvenanceOrigin.generated),
        template_id="generate_item",
        template_version=template_version,
        grading_spec=GradingSpec(**known),
    )


def _write_answers_file(diagnostic: Diagnostic, items: list[Item], name_by_id, *, root, learner_id):
    by_id = {i.id: i for i in items}
    questions = []
    for iid in diagnostic.item_ids:
        it = by_id[iid]
        concept_name = name_by_id.get(it.concept_ids[0], it.concept_ids[0]) if it.concept_ids else ""
        questions.append(
            {
                "item_id": it.id,
                "concept": concept_name,
                "format": it.format.value,
                "stem": it.stem,
                "options": it.options,
                "response": "",
                "felt_lucky": False,
                "time_spent": None,
            }
        )
    payload = {
        "_instructions": (
            "Answer every question: put your answer in 'response' (for mc, the chosen option "
            "text or letter). Set felt_lucky=true if you guessed; time_spent is optional seconds. "
            f"Then run: studybuddy administer --subject {diagnostic.subject} --answers <this file>"
        ),
        "diagnostic_id": diagnostic.id,
        "subject": diagnostic.subject,
        "questions": questions,
    }
    path = store.learner_file(learner_id, ANSWERS_NAME, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def compose(
    subject: str,
    *,
    root=None,
    client=None,
    learner_id: str = store.DEFAULT_LEARNER,
    size: int | None = None,
    focus: list[str] | None = None,
) -> dict:
    concepts = store.load_concepts(subject, root=root)
    if not concepts:
        raise ValueError(f"no concepts for subject {subject!r}; run `ingest` first")
    bank = store.load_items(subject, root=root)
    state = store.load_learner(learner_id, root=root)
    confidence = state.intake.per_topic_confidence if state.intake else {}
    target = size or int(store.load_heuristics(root=root).sampling_rules.get("diagnostic_size", 20))

    ordered = sorted(concepts, key=lambda c: _priority(c, confidence))
    if focus:  # FR-G2 shift: restrict composition to the chosen topic(s)
        wanted = {f for f in focus} | {store.concept_id(f) for f in focus}
        ordered = [c for c in ordered if c.id in wanted or c.name in wanted]
        if not ordered:
            raise ValueError(f"focus {focus!r} matched no concepts in subject {subject!r}")

    # Retrieval-first: round-robin one bank item per concept (weakest first) until target.
    queues: dict[str, list[Item]] = defaultdict(list)
    for it in bank:
        for cid in it.concept_ids:
            queues[cid].append(it)
    used: set[str] = set()
    chosen: list[Item] = []
    progress = True
    while len(chosen) < target and progress:
        progress = False
        for c in ordered:
            if len(chosen) >= target:
                break
            while queues[c.id]:
                it = queues[c.id].pop(0)
                if it.id not in used:
                    used.add(it.id)
                    chosen.append(it)
                    progress = True
                    break
    retrieved = len(chosen)

    # Generation pass: fill the remainder, gated by verify_item. Bounded to avoid runaway.
    new_items: list[Item] = []
    if len(chosen) < target:
        gen_version = registry.current_version("generate_item", root=root)
        attempts = 0
        max_attempts = (target - len(chosen)) * 3 + len(ordered)
        ci = 0
        while len(chosen) < target and attempts < max_attempts:
            concept = ordered[ci % len(ordered)]
            ci += 1
            attempts += 1
            gen = run_call(
                "generate_item",
                {
                    "concept": concept.name,
                    "difficulty": _difficulty_for(concept, confidence),
                    "format": _COMPONENT_FORMATS[attempts % len(_COMPONENT_FORMATS)],
                    "source_context": f"Concept: {concept.name} (subject: {subject})",
                },
                root=root,
                client=client,
                phase="Stage 4: generate_item",
            )
            verdict = run_call(
                "verify_item",
                {"item": gen, "intended_concept": concept.name},
                root=root,
                client=client,
                phase="Stage 4: verify_item",
            )
            if verdict.get("verdict") == "pass":
                item = _item_from_generated(gen, concept, gen_version)
                new_items.append(item)
                chosen.append(item)

    if new_items:
        store.add_items(subject, new_items, root=root)

    diagnostic = Diagnostic(
        id=ids.ulid_id("diag"),
        subject=subject,
        learner_id=learner_id,
        item_ids=[it.id for it in chosen],
        created_at=ids.utcnow(),
        retrieved=retrieved,
        generated=len(new_items),
    )
    store.save_diagnostic(learner_id, diagnostic.model_dump(mode="json"), root=root)

    name_by_id = {c.id: c.name for c in concepts}
    answers_path = _write_answers_file(
        diagnostic, chosen, name_by_id, root=root, learner_id=learner_id
    )

    return {
        "diagnostic": diagnostic,
        "answers_path": answers_path,
        "retrieved": retrieved,
        "generated": len(new_items),
    }
