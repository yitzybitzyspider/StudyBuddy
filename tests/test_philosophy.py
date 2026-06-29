"""Phase 5 philosophy-gate tests (Loop 25)."""

import json

from studybuddy import ids, philosophy, proposals, store
from studybuddy.models import (
    Concept,
    DependencyEdge,
    DependencyRelation,
    Proposal,
    ProposalKind,
    ProposalStatus,
)
from tests.test_proposals import _seed


def _prop(kind, change):
    return Proposal(id=ids.ulid_id("prop"), kind=kind, summary="s", rationale="r",
                    change=change, created_at=ids.utcnow())


def test_difficulty_out_of_scale_is_rejected(tmp_path):
    _seed(tmp_path)
    p = _prop(ProposalKind.recalibrate_difficulty,
              {"subject": "finance", "concept_id": "c", "to_difficulty": 99})
    verdict = philosophy.check(p, root=tmp_path)
    assert not verdict["ok"] and "difficulty scale" in verdict["violations"][0]


def test_self_dependency_edge_is_rejected(tmp_path):
    _seed(tmp_path)
    p = _prop(ProposalKind.add_dependency_edge,
              {"subject": "finance", "from_concept": "c", "to_concept": "c",
               "relation": "depends_on", "confidence": 0.9})
    assert not philosophy.check(p, root=tmp_path)["ok"]


def test_contradicting_confident_edge_is_rejected(tmp_path):
    _seed(tmp_path)
    # existing confident A->B; proposing B->A contradicts it
    a = Concept(id="a", subject="finance", name="A",
                dependency_edges=[DependencyEdge(other_concept_id="b",
                                                 relation=DependencyRelation.depends_on, confidence=0.9)])
    b = Concept(id="b", subject="finance", name="B")
    store.save_concepts("finance", [a, b], root=tmp_path)
    p = _prop(ProposalKind.add_dependency_edge,
              {"subject": "finance", "from_concept": "b", "to_concept": "a",
               "relation": "depends_on", "confidence": 0.8})
    verdict = philosophy.check(p, root=tmp_path)
    assert not verdict["ok"] and "never self-corrupting" in verdict["violations"][0]


def test_clean_proposal_passes(tmp_path):
    _seed(tmp_path)
    store.save_concepts("finance", [
        Concept(id="a", subject="finance", name="A"), Concept(id="b", subject="finance", name="B"),
    ], root=tmp_path)
    p = _prop(ProposalKind.add_dependency_edge,
              {"subject": "finance", "from_concept": "a", "to_concept": "b",
               "relation": "depends_on", "confidence": 0.8})
    assert philosophy.check(p, root=tmp_path)["ok"]


def test_gate_blocks_accept_even_when_metric_looks_good(tmp_path):
    """A proposal that violates a principle is rejected by decide() despite being accepted."""
    _seed(tmp_path)
    store.save_concepts("finance", [Concept(id="c", subject="finance", name="C")], root=tmp_path)
    # craft an out-of-scale recalibration straight into the inbox
    bad = _prop(ProposalKind.recalibrate_difficulty,
                {"subject": "finance", "concept_id": "c", "to_difficulty": 99})
    store.save_proposals([bad], root=tmp_path)

    decided = proposals.decide(bad.id, True, note="looks great", root=tmp_path)
    assert decided.status is ProposalStatus.rejected
    assert "philosophy gate" in decided.decision_note
    # the concept was NOT mutated, and no changelog entry was written
    assert store.load_concepts("finance", root=tmp_path)[0].difficulty_prior is None
    assert not (tmp_path / "proposals" / "changelog.jsonl").exists()
