"""Stage 2 dependency-map build/merge tests (Phase 3, Loop 16)."""

import json

from studybuddy import depmap, ids, seed, store
from studybuddy.models import (
    Concept,
    DependencyEdge,
    DependencyRelation,
    Item,
    ItemFormat,
    Provenance,
    ProvenanceOrigin,
)


def _edges_out(*edges):
    return json.dumps({"edges": list(edges)})


def _setup(tmp_path):
    for d in ("prompts", "heuristics", "runs", "runs/blobs", "concepts", "items", "proposals"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    seed.seed_knowledge_layer(root=tmp_path)
    tvm = Concept(id=store.concept_id("Time Value of Money"), subject="finance", name="Time Value of Money")
    disc = Concept(id=store.concept_id("Discounting"), subject="finance", name="Discounting")
    npv = Concept(id=store.concept_id("Net Present Value"), subject="finance", name="Net Present Value")
    store.save_concepts("finance", [tvm, disc, npv], root=tmp_path)
    return tvm, disc, npv


def test_confident_edge_is_added_to_concept_model(tmp_path, fake_client):
    tvm, disc, npv = _setup(tmp_path)
    client = fake_client(outputs=[_edges_out(
        {"from_concept": "Discounting", "to_concept": "Time Value of Money",
         "relation": "depends_on", "confidence": 0.85},
    )])
    result = depmap.build("finance", root=tmp_path, client=client)
    assert result["added"] == 1 and result["held"] == 0

    concepts = {c.id: c for c in store.load_concepts("finance", root=tmp_path)}
    edges = concepts[disc.id].dependency_edges
    assert len(edges) == 1
    assert edges[0].other_concept_id == tvm.id
    assert edges[0].relation is DependencyRelation.depends_on
    assert edges[0].confidence == 0.85


def test_weak_fresh_edge_is_held_for_proposals_inbox(tmp_path, fake_client):
    tvm, disc, npv = _setup(tmp_path)
    client = fake_client(outputs=[_edges_out(
        {"from_concept": "Net Present Value", "to_concept": "Discounting",
         "relation": "depends_on", "confidence": 0.4},  # below the 0.6 default
    )])
    result = depmap.build("finance", root=tmp_path, client=client)
    assert result["added"] == 0 and result["held"] == 1

    concepts = {c.id: c for c in store.load_concepts("finance", root=tmp_path)}
    assert concepts[npv.id].dependency_edges == []  # not written into the model

    inbox = (tmp_path / "proposals" / "dependency-inbox.jsonl").read_text().strip().splitlines()
    assert len(inbox) == 1
    rec = json.loads(inbox[0])
    assert rec["from_concept"] == npv.id and rec["confidence"] == 0.4


def test_reconfirming_an_edge_accrues_confidence(tmp_path, fake_client):
    tvm, disc, npv = _setup(tmp_path)
    # pre-existing edge at 0.5
    concepts = store.load_concepts("finance", root=tmp_path)
    for c in concepts:
        if c.id == disc.id:
            c.dependency_edges.append(
                DependencyEdge(other_concept_id=tvm.id, relation=DependencyRelation.depends_on, confidence=0.5)
            )
    store.save_concepts("finance", concepts, root=tmp_path)

    client = fake_client(outputs=[_edges_out(
        {"from_concept": "Discounting", "to_concept": "Time Value of Money",
         "relation": "depends_on", "confidence": 0.5},
    )])
    result = depmap.build("finance", root=tmp_path, client=client)
    assert result["accrued"] == 1 and result["added"] == 0

    concepts = {c.id: c for c in store.load_concepts("finance", root=tmp_path)}
    edges = concepts[disc.id].dependency_edges
    assert len(edges) == 1  # not duplicated
    # noisy-OR: 0.5 + 0.5*0.5 = 0.75, and strictly greater than before
    assert abs(edges[0].confidence - 0.75) < 1e-9


def test_edges_between_unknown_or_identical_concepts_are_skipped(tmp_path, fake_client):
    _setup(tmp_path)
    client = fake_client(outputs=[_edges_out(
        {"from_concept": "Discounting", "to_concept": "Discounting",
         "relation": "depends_on", "confidence": 0.9},  # self-loop
        {"from_concept": "Astrology", "to_concept": "Discounting",
         "relation": "depends_on", "confidence": 0.9},  # unknown concept
    )])
    result = depmap.build("finance", root=tmp_path, client=client)
    assert result["added"] == 0 and result["accrued"] == 0 and result["held"] == 0


def test_offline_mode_builds_the_map(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDYBUDDY_OFFLINE", "1")
    _setup(tmp_path)
    result = depmap.build("finance", root=tmp_path)  # canned build_dependency_map output
    # canned edges: Discounting->TVM (0.8), NPV->Discounting (0.85); both >= 0.6
    assert result["added"] == 2
