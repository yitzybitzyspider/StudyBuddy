"""Stage 2: build and refine the concept dependency map (Phase 3, Loop 16).

Claude ``build_dependency_map`` proposes prerequisite edges between concepts (with a
confidence each); deterministic code owns how they are *merged* into the living concept
model. Two rules straight from spec §Stage-2 and philosophy §8:

  - **Accrue, never overwrite.** Re-confirming an existing edge raises its confidence
    (noisy-OR: ``merged = old + (1-old)*new``) toward 1 rather than replacing it, so the
    map gets surer with evidence instead of thrashing on the latest call.
  - **Hold weak new edges for the human gate.** A *fresh* edge whose confidence is below
    ``heuristics.dependency.edge_confidence_min`` is not written into the concept model;
    it is appended to the Phase-5 proposals inbox (``proposals/dependency-inbox.jsonl``)
    to be accepted or rejected later. (Re-confirming an *existing* edge always accrues,
    regardless of the single call's confidence.)

The dependency map is what makes Stage 6 diagnosis read a downstream miss as an upstream
prerequisite gap (Loop 17).
"""

from __future__ import annotations

import json

from . import store
from .models import DependencyEdge, DependencyRelation

_SAMPLE_ITEMS = 40  # cap the items handed to the call as context (keep it scoped)
_INBOX = "proposals/dependency-inbox.jsonl"


def _noisy_or(old: float, new: float) -> float:
    """Accrue confidence toward 1 with repeated evidence (never decreases)."""
    return old + (1.0 - old) * new


def _hold_for_proposals(root, records: list[dict]) -> None:
    from . import paths

    path = paths.knowledge_root(root) / _INBOX
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def build(subject: str, *, root=None, client=None) -> dict:
    """Run ``build_dependency_map`` and merge edges into ``subject``'s concept model.

    Returns ``{added, accrued, held, edges}`` — newly written edges, accrued (re-confirmed)
    edges, and weak fresh edges held for the proposals inbox.
    """
    concepts = store.load_concepts(subject, root=root)
    if not concepts:
        raise ValueError(f"no concepts for subject {subject!r}; run `ingest` first")
    by_id = {c.id: c for c in concepts}
    name_to_id = {c.name.lower(): c.id for c in concepts}

    def resolve(value: str) -> str | None:
        if value in by_id:
            return value
        return name_to_id.get(value.lower())

    items = store.load_items(subject, root=root)[:_SAMPLE_ITEMS]
    out = run_call_depmap(subject, concepts, items, root=root, client=client)

    min_conf = float(store.load_heuristics(root=root).dependency.get("edge_confidence_min", 0.6))
    added = accrued = 0
    held: list[dict] = []

    for edge in out.get("edges", []):
        from_id = resolve(edge.get("from_concept", ""))
        to_id = resolve(edge.get("to_concept", ""))
        if not from_id or not to_id or from_id == to_id:
            continue  # only assert edges between known, distinct concepts
        try:
            relation = DependencyRelation(edge["relation"])
        except (KeyError, ValueError):
            continue
        conf = float(edge.get("confidence", 0.0))
        conf = min(max(conf, 0.0), 1.0)

        concept = by_id[from_id]
        existing = next(
            (e for e in concept.dependency_edges
             if e.other_concept_id == to_id and e.relation is relation),
            None,
        )
        if existing is not None:  # re-confirmation: accrue (always)
            existing.confidence = _noisy_or(existing.confidence, conf)
            accrued += 1
        elif conf >= min_conf:  # confident enough to enter the map
            concept.dependency_edges.append(
                DependencyEdge(other_concept_id=to_id, relation=relation, confidence=conf)
            )
            added += 1
        else:  # weak + fresh: hold for the human gate (Phase 5)
            held.append(
                {"subject": subject, "from_concept": from_id, "to_concept": to_id,
                 "relation": relation.value, "confidence": conf}
            )

    store.save_concepts(subject, list(by_id.values()), root=root)
    if held:
        _hold_for_proposals(root, held)

    return {"added": added, "accrued": accrued, "held": len(held), "edges": out.get("edges", [])}


def run_call_depmap(subject, concepts, items, *, root, client):
    """The single scoped Claude call. Separated so tests can target the merge logic alone."""
    from .wrapper import run_call

    return run_call(
        "build_dependency_map",
        {
            "concepts": [
                {"name": c.name, "parent": c.parent_id, "difficulty_prior": c.difficulty_prior}
                for c in concepts
            ],
            "sampled_items": [
                {"stem": it.stem, "concept_names": it.concept_ids} for it in items
            ],
        },
        root=root,
        client=client,
        phase="Stage 2: build_dependency_map",
    )
