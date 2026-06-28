"""Stage 6 (thin): diagnose where understanding breaks down.

Deterministic heuristics first classify the per-concept results into the five gap types
(foundational, depth, overconfidence, breadth, speed) using thresholds from the heuristics
config. Then ``interpret_gaps`` gives a semantic read of *why* each gap exists, as
hypotheses with confidence. The result is a flat GapProfile (one entry per concept+gap_type,
B1). Reading gaps *inside the dependency map* is Phase 3 — Phase 1 is flat (dependency
context is empty here).
"""

from __future__ import annotations

from . import ids, store
from .models import (
    GapClassification,
    GapEntry,
    GapProfile,
    GapStatus,
    Reference,
    RefKind,
)
from .wrapper import run_call

_DEPTH_OK = 0.8  # at/above this correct_rate a concept is not flagged for depth (thin proxy)
_DET_CONFIDENCE = 0.5  # deterministic pre-classification is a modest prior


def _classify(rollup, item_responses, confidence, items, thresholds) -> list[GapClassification]:
    found_below = thresholds.get("foundational", {}).get("easy_band_correct_rate_below", 0.5)
    breadth_spread = thresholds.get("breadth", {}).get("per_concept_correct_rate_spread_above", 0.4)

    # map item -> concepts (for the overconfidence / felt-lucky signal)
    item_concepts = {it.id: it.concept_ids for it in items}
    lucky_correct: set[str] = set()
    for r in item_responses:
        if r.felt_lucky_flag and r.correct:
            for cid in item_concepts.get(r.item_id, []):
                lucky_correct.add(cid)

    out: list[GapClassification] = []
    for cid, stats in rollup.items():
        cr = stats.get("correct_rate", 0.0)
        gaps: list[str] = []
        if cr < found_below:
            gaps.append("foundational")
        elif cr < _DEPTH_OK:
            gaps.append("depth")
        if stats.get("blanks", 0) > 0:
            gaps.append("speed")
        self_conf = confidence.get(cid)
        if cid in lucky_correct or (self_conf is not None and self_conf >= 0.7 and cr < 0.6):
            gaps.append("overconfidence")
        if gaps:
            out.append(GapClassification(concept_id=cid, gap_types=gaps, confidence=_DET_CONFIDENCE))

    # breadth is a global signal: if performance is uneven across concepts, flag the weakest
    rates = [s.get("correct_rate", 0.0) for s in rollup.values()]
    if len(rates) >= 2 and (max(rates) - min(rates)) > breadth_spread:
        weakest = min(rollup, key=lambda c: rollup[c].get("correct_rate", 0.0))
        existing = next((g for g in out if g.concept_id == weakest), None)
        if existing:
            if "breadth" not in existing.gap_types:
                existing.gap_types.append("breadth")
        else:
            out.append(GapClassification(concept_id=weakest, gap_types=["breadth"], confidence=_DET_CONFIDENCE))
    return out


def _augment_rollup(rollup, classification, confidence, name_by_id) -> dict:
    """Per-concept context for interpret_gaps, keyed by concept name for readability."""
    det = {g.concept_id: g.gap_types for g in classification}
    augmented = {}
    for cid, stats in rollup.items():
        name = name_by_id.get(cid, cid)
        augmented[name] = {
            **stats,
            "self_confidence": confidence.get(cid),
            "deterministic_gap_types": det.get(cid, []),
        }
    return augmented


def diagnose(subject: str, *, root=None, client=None, learner_id: str = store.DEFAULT_LEARNER) -> dict:
    state = store.load_learner(learner_id, root=root)
    if not state.diagnostic_results:
        raise ValueError("no diagnostic results; run `administer` first")
    result = state.diagnostic_results[-1]

    concepts = store.load_concepts(subject, root=root)
    by_id = {c.id: c for c in concepts}
    by_name = {c.name: c.id for c in concepts}
    name_by_id = {c.id: c.name for c in concepts}
    confidence = state.intake.per_topic_confidence if state.intake else {}
    thresholds = store.load_heuristics(root=root).gap_thresholds
    gap_vocab = store.load_heuristics(root=root).gap_types
    items = store.load_items(subject, root=root)

    classification = _classify(
        result.per_concept_rollup, result.item_responses, confidence, items, thresholds
    )
    result.gap_classification = classification  # mutate the stored result

    interp = run_call(
        "interpret_gaps",
        {
            "per_concept_rollup": _augment_rollup(
                result.per_concept_rollup, classification, confidence, name_by_id
            ),
            "dependency_context": {},  # flat in Phase 1; dependency map is Phase 3
            "gap_types": gap_vocab,
        },
        root=root,
        client=client,
        phase="Stage 6: interpret_gaps",
    )

    def resolve(value: str) -> str:
        if value in by_id:
            return value
        if value in by_name:
            return by_name[value]
        return store.concept_id(value)

    entries: list[GapEntry] = []
    for g in interp.get("gaps", []):
        cid = resolve(g["concept"])
        entries.append(
            GapEntry(
                concept_id=cid,
                gap_type=g["gap_type"],
                severity=g.get("severity"),
                status=GapStatus.hypothesis,
                evidence_refs=[Reference(kind=RefKind.concept, ref=cid)],
            )
        )

    profile = GapProfile(learner_id=learner_id, entries=entries, updated_at=ids.utcnow())
    state.gap_profile = profile
    store.save_learner(state, root=root)
    return {"gap_profile": profile, "classification": classification}
