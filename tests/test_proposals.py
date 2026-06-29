"""Phase 5 proposals-generator tests (Loop 23)."""

import json

from studybuddy import ids, proposals, registry, seed, store
from studybuddy.models import (
    Calibration,
    Concept,
    Item,
    ItemFormat,
    ProposalKind,
    ProposalStatus,
    Provenance,
    ProvenanceOrigin,
)


def _seed(tmp_path):
    for d in ("prompts", "heuristics", "runs", "runs/blobs", "concepts", "items", "proposals"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    seed.seed_knowledge_layer(root=tmp_path)


def test_promote_prompt_version_proposal(tmp_path):
    _seed(tmp_path)
    # add a v2 of generate_item with a strong acceptance record; current stays v1 (no record)
    tpl = registry.load_template("generate_item", "v1", root=tmp_path)
    v2 = tpl.model_copy(update={"version": "v2", "metrics": {
        "attempts": 10, "accepts": 9, "acceptance_rate": 0.9}})
    (tmp_path / "prompts" / "generate_item" / "v2.json").write_text(
        v2.model_dump_json(indent=2)
    )

    new = proposals.generate(root=tmp_path)
    promo = [p for p in new if p.kind is ProposalKind.promote_prompt_version]
    assert len(promo) == 1
    assert promo[0].change == {"task": "generate_item", "from_version": "v1", "to_version": "v2"}
    assert promo[0].evidence_refs[0].ref == "generate_item/v2"


def test_add_dependency_edge_proposal_from_inbox(tmp_path):
    _seed(tmp_path)
    inbox = tmp_path / "proposals" / "dependency-inbox.jsonl"
    rec = {"subject": "finance", "from_concept": "concept_npv", "to_concept": "concept_disc",
           "relation": "depends_on", "confidence": 0.4}
    inbox.write_text("\n".join(json.dumps(rec) for _ in range(2)) + "\n")  # seen twice

    new = proposals.generate(root=tmp_path)
    edges = [p for p in new if p.kind is ProposalKind.add_dependency_edge]
    assert len(edges) == 1
    assert edges[0].change["from_concept"] == "concept_npv"


def test_single_occurrence_edge_is_not_proposed(tmp_path):
    _seed(tmp_path)
    inbox = tmp_path / "proposals" / "dependency-inbox.jsonl"
    inbox.write_text(json.dumps(
        {"subject": "finance", "from_concept": "a", "to_concept": "b",
         "relation": "depends_on", "confidence": 0.4}) + "\n")
    new = proposals.generate(root=tmp_path)
    assert not [p for p in new if p.kind is ProposalKind.add_dependency_edge]


def test_difficulty_recalibration_proposal(tmp_path):
    _seed(tmp_path)
    # concept labeled easy (prior 2) but items observed hard (~0.9 -> ~4.6, hard band)
    npv = Concept(id="concept_npv", subject="finance", name="NPV", difficulty_prior=2)
    store.save_concepts("finance", [npv], root=tmp_path)
    items = [
        Item(id=ids.ulid_id("item"), concept_ids=["concept_npv"], format=ItemFormat.numeric,
             stem="q", answer_key="1", provenance=Provenance(origin=ProvenanceOrigin.retrieved),
             calibration=Calibration(observed_difficulty=0.9, times_seen=4))
        for _ in range(3)
    ]
    store.save_items("finance", items, root=tmp_path)

    new = proposals.generate("finance", root=tmp_path)
    recal = [p for p in new if p.kind is ProposalKind.recalibrate_difficulty]
    assert len(recal) == 1
    assert recal[0].change["concept_id"] == "concept_npv"


def test_generation_is_idempotent(tmp_path):
    _seed(tmp_path)
    inbox = tmp_path / "proposals" / "dependency-inbox.jsonl"
    rec = {"subject": "finance", "from_concept": "a", "to_concept": "b",
           "relation": "depends_on", "confidence": 0.4}
    inbox.write_text("\n".join(json.dumps(rec) for _ in range(2)) + "\n")

    first = proposals.generate(root=tmp_path)
    second = proposals.generate(root=tmp_path)  # same evidence, already open
    assert len(first) == 1 and second == []
    assert len(store.load_proposals(root=tmp_path)) == 1
