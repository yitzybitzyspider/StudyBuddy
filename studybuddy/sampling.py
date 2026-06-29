"""Stage 7: adaptive sampling — the next strategic batch and the stopping rule (Loop 18).

After a diagnostic round (Stages 4→5→6), the system does not just keep asking uniformly. It
chooses the **next small strategic batch** aimed where signal is thin, and it **stops** once
the gap profile is confident enough. Deterministic code owns both decisions (the
Claude-vs-code boundary); sourcing/grading/interpretation reuse Stages 4–6 unchanged.

The loop is file-based (decision E2), so one call composes the next focused batch; the user
answers and runs ``administer`` + ``diagnose``; then they call this again. The stopping rule
is the terminal check, and ``max_adaptive_batches`` guarantees termination.

Batch strategy (spec §Stage-7), in priority order:
  1. **Weakest area** — the open gap with the lowest confidence (most unresolved).
  2. **Boundary between two shaky concepts** — a dependency edge whose both endpoints are
     weak, to localize whether the break is upstream or downstream.
  3. **Verify a strength** — re-test a concept the learner got right, to confirm it is solid
     rather than lucky.
"""

from __future__ import annotations

from . import diagnostic as diagnostic_mod
from . import store
from .models import DependencyRelation, GapStatus

_STRONG = 0.8  # correct_rate at/above which a concept is a candidate "verify a strength" probe


def stopping_status(state, heuristics) -> dict:
    """Evaluate the stopping rule against the current gap profile.

    Stops when there are no open gaps, when every open gap is at/above the confidence
    target, or when the adaptive-batch cap is reached.
    """
    rule = heuristics.stopping_rule
    target = float(rule.get("gap_confidence_target", 0.8))
    max_batches = int(rule.get("max_adaptive_batches", 4))
    batches_done = len(state.diagnostic_results)

    profile = state.gap_profile
    open_entries = [
        e for e in (profile.entries if profile else []) if e.status is not GapStatus.resolved
    ]
    low = [e for e in open_entries if (e.confidence or 0.0) < target]

    if not open_entries:
        return _status(True, "no open gaps to narrow", target, batches_done, max_batches, [])
    if not low:
        return _status(True, "all open gaps at/above the confidence target", target,
                       batches_done, max_batches, [])
    if batches_done >= max_batches:
        return _status(True, "reached the adaptive-batch cap", target,
                       batches_done, max_batches, low)
    return _status(False, "open gaps below the confidence target", target,
                   batches_done, max_batches, low)


def _status(stop, reason, target, batches_done, max_batches, low):
    return {
        "stop": stop,
        "reason": reason,
        "target": target,
        "batches_done": batches_done,
        "max_batches": max_batches,
        "low_confidence_gaps": [(e.concept_id, e.gap_type, e.confidence) for e in low],
    }


def select_focus(state, concepts) -> list[str]:
    """Pick the concept ids for the next strategic batch (weakest, boundary, verify)."""
    profile = state.gap_profile
    rollup = state.diagnostic_results[-1].per_concept_rollup if state.diagnostic_results else {}
    by_id = {c.id: c for c in concepts}
    focus: list[str] = []

    def add(cid):
        if cid and cid in by_id and cid not in focus:
            focus.append(cid)

    # 1. weakest area: the open gap with the lowest confidence
    open_entries = [
        e for e in (profile.entries if profile else []) if e.status is not GapStatus.resolved
    ]
    if open_entries:
        weakest = min(open_entries, key=lambda e: (e.confidence or 0.0))
        add(weakest.concept_id)

        # 2. boundary: a prerequisite of a shaky concept that is itself shaky
        shaky = {e.concept_id for e in open_entries}
        for e in open_entries:
            concept = by_id.get(e.concept_id)
            if not concept:
                continue
            for edge in concept.dependency_edges:
                if edge.relation is DependencyRelation.depends_on and edge.other_concept_id in shaky:
                    add(edge.other_concept_id)
                    break
            if len(focus) >= 2:
                break

    # 3. verify a strength: a concept scored strong this batch, to confirm it is not luck
    strengths = sorted(
        (cid for cid, s in rollup.items() if (s.get("correct_rate") or 0.0) >= _STRONG),
        key=lambda cid: rollup[cid].get("correct_rate", 0.0), reverse=True,
    )
    for cid in strengths:
        if cid not in focus:
            add(cid)
            break

    return focus


def next_batch(subject: str, *, root=None, client=None, learner_id: str = store.DEFAULT_LEARNER) -> dict:
    """Compose the next strategic batch, unless the stopping rule has fired.

    Returns ``{composed, status, focus, ...}``. When ``composed`` is False the loop is done
    (``status['reason']`` says why). When True, the usual answers file is written for the
    user to fill (then administer + diagnose, then call again).
    """
    state = store.load_learner(learner_id, root=root)
    heuristics = store.load_heuristics(root=root)
    if not state.diagnostic_results:
        raise ValueError("no diagnostic yet; compose + administer + diagnose a first round first")

    status = stopping_status(state, heuristics)
    if status["stop"]:
        return {"composed": False, "status": status, "focus": []}

    concepts = store.load_concepts(subject, root=root)
    focus_ids = select_focus(state, concepts)
    name_by_id = {c.id: c.name for c in concepts}
    focus_names = [name_by_id.get(cid, cid) for cid in focus_ids] or None

    batch = int(heuristics.sampling_rules.get("adaptive_batch_size", 4))
    result = diagnostic_mod.compose(
        subject, root=root, client=client, learner_id=learner_id, size=batch, focus=focus_names,
    )
    result.update({"composed": True, "status": status, "focus": focus_ids})
    return result
