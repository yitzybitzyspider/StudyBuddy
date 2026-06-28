from studybuddy import ids, store
from studybuddy.models import (
    Concept,
    Item,
    ItemFormat,
    LearnerState,
    Provenance,
    ProvenanceOrigin,
)


def _concept(name, subject="finance"):
    return Concept(id=store.concept_id(name), subject=subject, name=name)


def _item(name="x"):
    return Item(
        id=ids.ulid_id("item"),
        concept_ids=[store.concept_id("Net Present Value")],
        format=ItemFormat.numeric,
        stem="Compute NPV",
        answer_key="1",
        provenance=Provenance(origin=ProvenanceOrigin.retrieved),
    )


def test_concept_id_is_stable_slug():
    assert store.concept_id("Net Present Value") == "concept_net-present-value"


def test_concepts_round_trip_and_merge(tmp_path):
    store.save_concepts("finance", [_concept("Net Present Value")], root=tmp_path)
    loaded = store.load_concepts("finance", root=tmp_path)
    assert [c.name for c in loaded] == ["Net Present Value"]

    # merge adds a new one and replaces an existing id without dropping others
    merged = store.merge_concepts(
        "finance", [_concept("Discounting"), _concept("Net Present Value")], root=tmp_path
    )
    assert {c.id for c in merged} == {"concept_net-present-value", "concept_discounting"}


def test_items_append(tmp_path):
    store.add_items("finance", [_item()], root=tmp_path)
    store.add_items("finance", [_item()], root=tmp_path)
    assert len(store.load_items("finance", root=tmp_path)) == 2


def test_learner_state_defaults_when_missing(tmp_path):
    state = store.load_learner(root=tmp_path)
    assert state.learner_id == store.DEFAULT_LEARNER
    assert state.intake is None


def test_learner_state_round_trip(tmp_path):
    state = LearnerState(learner_id="learner_default", progress={"done": 1})
    store.save_learner(state, root=tmp_path)
    assert store.load_learner(root=tmp_path).progress == {"done": 1}


def test_diagnostic_working_file(tmp_path):
    assert store.load_diagnostic(root=tmp_path) is None
    store.save_diagnostic("learner_default", {"items": [1, 2, 3]}, root=tmp_path)
    assert store.load_diagnostic(root=tmp_path) == {"items": [1, 2, 3]}
