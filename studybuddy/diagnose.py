"""Stage 6: diagnose where understanding breaks down.

Deterministic heuristics first classify the per-concept results into the five gap types
(foundational, depth, overconfidence, breadth, speed) using thresholds from the heuristics
config. Then ``interpret_gaps`` gives a semantic read of *why* each gap exists, as
hypotheses with confidence. The result is a flat GapProfile (one entry per concept+gap_type,
B1).

Phase 3 (Loop 17): the interpretation now reads **inside the dependency map**. Each concept's
prerequisites (from the Stage-2 concept model) and how the learner scored on them are handed
to ``interpret_gaps`` as ``dependency_context``, so a downstream miss can be read as an
upstream prerequisite gap rather than a local one.
"""

from __future__ import annotations

from collections import defaultdict

from . import ids, store
from .models import (
    DependencyRelation,
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

# Fallback per-format difficulty (1–5) when an item has no observed difficulty or prior.
_FORMAT_DIFFICULTY = {"mc": 2, "numeric": 3, "short": 3, "essay": 4, "application": 4}


def _item_difficulty(item, concept) -> int:
    """A 1–5 difficulty for an item: observed (calibrated) > concept prior > format proxy."""
    od = item.calibration.observed_difficulty
    if od is not None:
        return int(round(1 + 4 * max(0.0, min(1.0, od))))  # 0..1 -> 1..5
    if concept is not None and concept.difficulty_prior is not None:
        return int(round(max(1.0, min(5.0, concept.difficulty_prior))))
    return _FORMAT_DIFFICULTY.get(item.format.value, 3)


def _band_of(difficulty: int, bands: dict) -> str:
    for name, rng in bands.items():
        if isinstance(rng, list) and len(rng) == 2 and rng[0] <= difficulty <= rng[1]:
            return name
    return "medium"


def _rate(hits: list[bool]):
    return sum(1 for h in hits if h) / len(hits) if hits else None


def _classify(
    rollup, item_responses, confidence, items, thresholds, bands, concept_by_id
) -> list[GapClassification]:
    found_below = thresholds.get("foundational", {}).get("easy_band_correct_rate_below", 0.5)
    depth_cfg = thresholds.get("depth", {})
    depth_at_least = depth_cfg.get("easy_medium_correct_rate_at_least", 0.8)
    hard_below = depth_cfg.get("hard_correct_rate_below", 0.5)
    breadth_spread = thresholds.get("breadth", {}).get("per_concept_correct_rate_spread_above", 0.4)

    item_by_id = {it.id: it for it in items}
    item_concepts = {it.id: it.concept_ids for it in items}
    lucky_correct: set[str] = set()
    for r in item_responses:
        if r.felt_lucky_flag and r.correct:
            for cid in item_concepts.get(r.item_id, []):
                lucky_correct.add(cid)

    # Material-aware buckets: per concept, the per-difficulty-band hit lists, so a multi-step
    # concept can show a foundational *and* a depth gap (one step easy-and-broken, one
    # hard-and-broken) rather than a single averaged verdict.
    band_hits: dict[str, dict[str, list[bool]]] = defaultdict(lambda: defaultdict(list))
    for r in item_responses:
        it = item_by_id.get(r.item_id)
        if it is None:
            continue
        for cid in it.concept_ids:
            band = _band_of(_item_difficulty(it, concept_by_id.get(cid)), bands)
            band_hits[cid][band].append(bool(r.correct))

    out: list[GapClassification] = []
    for cid, stats in rollup.items():
        cr = stats.get("correct_rate", 0.0)
        gaps: list[str] = []
        cbands = band_hits.get(cid)
        classified = False
        if cbands:  # material-aware: judge by which difficulty step broke
            easy_rate = _rate(cbands.get("easy", []))
            easy_med_rate = _rate(cbands.get("easy", []) + cbands.get("medium", []))
            hard_rate = _rate(cbands.get("hard", []))
            if easy_rate is not None and easy_rate < found_below:
                gaps.append("foundational")
                classified = True
            if (easy_med_rate is not None and easy_med_rate >= depth_at_least
                    and hard_rate is not None and hard_rate < hard_below):
                gaps.append("depth")
                classified = True
        if not classified:  # aggregate fallback (thin / single-band data)
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


def _prereq_map(concepts) -> dict[str, dict[str, float]]:
    """concept_id -> {prerequisite_concept_id: edge_confidence}.

    Normalizes both edge directions: ``A depends_on B`` and ``A prereq_of B`` both mean B
    sits below A, so B is a prerequisite of A. Keeps the highest confidence per pair.
    """
    prereq: dict[str, dict[str, float]] = defaultdict(dict)

    def note(dependent: str, prerequisite: str, conf: float) -> None:
        cur = prereq[dependent].get(prerequisite)
        if cur is None or conf > cur:
            prereq[dependent][prerequisite] = conf

    for c in concepts:
        for e in c.dependency_edges:
            if e.relation is DependencyRelation.depends_on:
                note(c.id, e.other_concept_id, e.confidence)
            elif e.relation is DependencyRelation.prereq_of:
                note(e.other_concept_id, c.id, e.confidence)
    return prereq


def _dependency_context(concepts, rollup, name_by_id) -> dict:
    """Per-concept prerequisite structure + how the learner scored on each prerequisite.

    Keyed by concept name (readable for the model). Only concepts present in this
    diagnostic's rollup are included; a prerequisite's correct_rate is null if it was not
    exercised in this diagnostic.
    """
    prereq = _prereq_map(concepts)
    context: dict = {}
    for cid in rollup:
        edges = prereq.get(cid)
        if not edges:
            continue
        depends_on = []
        for pid, conf in edges.items():
            pstats = rollup.get(pid) or {}
            depends_on.append(
                {
                    "concept": name_by_id.get(pid, pid),
                    "edge_confidence": round(conf, 4),
                    "prerequisite_correct_rate": pstats.get("correct_rate"),
                    "prerequisite_tested": pid in rollup,
                }
            )
        if depends_on:
            context[name_by_id.get(cid, cid)] = {"depends_on": depends_on}
    return context


def _noisy_or(old, new) -> float:
    o = old or 0.0
    n = new if new is not None else 0.5
    return o + (1.0 - o) * n


def _merge_gap_entries(prior, fresh, rollup) -> list[GapEntry]:
    """Accrue gap hypotheses across adaptive batches and transition their status (Stage 7).

    - A gap re-observed this batch **accrues** confidence (noisy-OR) and becomes ``confirmed``.
    - A prior gap whose concept was **re-tested** this batch but did **not** resurface is
      treated as ``resolved`` (the follow-up evidence contradicted it).
    - A prior gap whose concept was **not** tested this batch carries forward unchanged.
    - A brand-new gap enters as a ``hypothesis``.
    """
    by_key = {(e.concept_id, e.gap_type): e for e in prior}
    fresh_keys = {(e.concept_id, e.gap_type) for e in fresh}
    tested = set(rollup.keys())
    out: list[GapEntry] = []

    for e in fresh:
        key = (e.concept_id, e.gap_type)
        old = by_key.get(key)
        if old is not None:
            out.append(
                GapEntry(
                    concept_id=e.concept_id,
                    gap_type=e.gap_type,
                    severity=e.severity if e.severity is not None else old.severity,
                    confidence=_noisy_or(old.confidence, e.confidence),
                    evidence_refs=old.evidence_refs or e.evidence_refs,
                    status=GapStatus.confirmed,
                )
            )
        else:
            out.append(e)

    # carry forward / resolve prior gaps not re-observed this batch
    for key, old in by_key.items():
        if key in fresh_keys:
            continue
        cid, _ = key
        if cid in tested:
            out.append(old.model_copy(update={"status": GapStatus.resolved}))
        else:
            out.append(old)  # untested this batch — leave as-is
    return out


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
    heuristics = store.load_heuristics(root=root)
    thresholds = heuristics.gap_thresholds
    gap_vocab = heuristics.gap_types
    bands = (heuristics.difficulty_scale or {}).get("bands", {}) or {}
    items = store.load_items(subject, root=root)

    classification = _classify(
        result.per_concept_rollup, result.item_responses, confidence, items, thresholds,
        bands, by_id,
    )
    result.gap_classification = classification  # mutate the stored result

    interp = run_call(
        "interpret_gaps",
        {
            "per_concept_rollup": _augment_rollup(
                result.per_concept_rollup, classification, confidence, name_by_id
            ),
            "dependency_context": _dependency_context(
                concepts, result.per_concept_rollup, name_by_id
            ),
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

    fresh: list[GapEntry] = []
    for g in interp.get("gaps", []):
        cid = resolve(g["concept"])
        fresh.append(
            GapEntry(
                concept_id=cid,
                gap_type=g["gap_type"],
                severity=g.get("severity"),
                confidence=g.get("confidence"),
                status=GapStatus.hypothesis,
                evidence_refs=[Reference(kind=RefKind.concept, ref=cid)],
            )
        )

    prior = state.gap_profile.entries if state.gap_profile else []
    entries = _merge_gap_entries(prior, fresh, result.per_concept_rollup)

    profile = GapProfile(learner_id=learner_id, entries=entries, updated_at=ids.utcnow())
    state.gap_profile = profile
    store.save_learner(state, root=root)
    return {"gap_profile": profile, "classification": classification}
