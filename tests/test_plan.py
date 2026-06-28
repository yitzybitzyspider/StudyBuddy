"""Stage 8 plan + FR-G2 steer tests."""

import json

from studybuddy import ids, plan, seed, store
from studybuddy.models import (
    Concept,
    GapEntry,
    GapProfile,
    Item,
    ItemFormat,
    LearnerState,
    Provenance,
    ProvenanceOrigin,
    Reference,
    RefKind,
)
from studybuddy.runlog import RunLog

COMPOSE_OUT = json.dumps(
    {
        "overview": "Rebuild NPV from the ground up.",
        "topics": [
            {
                "concept": "Net Present Value",
                "summary": "Review discounting, then NPV decision rule.",
                "rationale": "foundational misses",
                "item_sequence": [],
                "source_links": [],
            }
        ],
    }
)


def _seed_layer(tmp_path):
    for d in ("prompts", "heuristics", "runs", "runs/blobs", "concepts", "items", "learner"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    seed.seed_knowledge_layer(root=tmp_path)


def _npv_item(concept_id="concept_net-present-value"):
    return Item(
        id=ids.ulid_id("item"),
        concept_ids=[concept_id],
        format=ItemFormat.numeric,
        stem="Compute NPV",
        answer_key="1",
        provenance=Provenance(origin=ProvenanceOrigin.retrieved),
    )


def test_compose_plan_writes_structured_plan_and_markdown(tmp_path, fake_client):
    _seed_layer(tmp_path)
    npv = Concept(
        id="concept_net-present-value", subject="finance", name="Net Present Value",
        source_refs=[Reference(kind=RefKind.material, ref="material_1", locator="p.5")],
    )
    store.save_concepts("finance", [npv], root=tmp_path)
    item = _npv_item()
    store.save_items("finance", [item], root=tmp_path)
    store.save_learner(
        LearnerState(
            learner_id=store.DEFAULT_LEARNER,
            gap_profile=GapProfile(
                learner_id=store.DEFAULT_LEARNER,
                entries=[GapEntry(concept_id=npv.id, gap_type="foundational")],
                updated_at=ids.utcnow(),
            ),
        ),
        root=tmp_path,
    )

    client = fake_client(outputs=[COMPOSE_OUT])
    result = plan.compose("finance", root=tmp_path, client=client)
    sp = result["study_plan"]

    assert len(sp.topics) == 1
    topic = sp.topics[0]
    assert topic.concept_id == npv.id
    assert topic.item_sequence == [item.id]               # deterministic sequence
    assert topic.source_links[0].ref == "material_1"      # traceability (FR-F4)

    md = result["markdown_path"].read_text()
    assert "Net Present Value" in md and "Rebuild NPV" in md
    assert store.load_learner(root=tmp_path).study_plan is not None
    assert [e.phase for e in RunLog(tmp_path).read_all()] == ["Stage 8: compose_plan"]


def _seed_with_bank(tmp_path):
    _seed_layer(tmp_path)
    npv = Concept(id="concept_net-present-value", subject="finance", name="Net Present Value")
    disc = Concept(id="concept_discounting", subject="finance", name="Discounting")
    store.save_concepts("finance", [npv, disc], root=tmp_path)
    store.save_items(
        "finance",
        [_npv_item(), _npv_item(), _npv_item(), _npv_item(), _npv_item("concept_discounting")],
        root=tmp_path,
    )


def test_steer_more_recomposes_a_batch(tmp_path):
    _seed_with_bank(tmp_path)
    result = plan.steer("finance", action="more", root=tmp_path)  # bank covers it, no client
    assert result["action"] == "more"
    assert len(result["diagnostic"].item_ids) == 4  # adaptive_batch_size default
    assert result["generated"] == 0


def test_steer_shift_focuses_on_one_topic(tmp_path):
    _seed_with_bank(tmp_path)
    result = plan.steer("finance", action="shift", focus=["Net Present Value"], root=tmp_path)
    items = {i.id: i for i in store.load_items("finance", root=tmp_path)}
    chosen_concepts = {items[i].concept_ids[0] for i in result["diagnostic"].item_ids}
    assert chosen_concepts == {"concept_net-present-value"}  # only the focused topic


def test_steer_shift_unknown_topic_raises(tmp_path):
    _seed_with_bank(tmp_path)
    try:
        plan.steer("finance", action="shift", focus=["Nonexistent"], root=tmp_path)
        assert False, "expected ValueError"
    except ValueError:
        pass
