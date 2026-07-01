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
    state = store.load_learner(subject="finance", root=tmp_path)
    assert state.learner_id == store.DEFAULT_LEARNER
    assert state.intake is None


def test_learner_state_round_trip(tmp_path):
    state = LearnerState(learner_id="learner_default", progress={"done": 1})
    store.save_learner(state, subject="finance", root=tmp_path)
    assert store.load_learner(subject="finance", root=tmp_path).progress == {"done": 1}


def test_diagnostic_working_file(tmp_path):
    assert store.load_diagnostic(subject="finance", root=tmp_path) is None
    store.save_diagnostic("learner_default", {"items": [1, 2, 3]}, subject="finance", root=tmp_path)
    assert store.load_diagnostic(subject="finance", root=tmp_path) == {"items": [1, 2, 3]}


def test_learner_state_is_per_subject(tmp_path):
    from studybuddy.models import LearnerState

    a = LearnerState(learner_id=store.DEFAULT_LEARNER, progress={"subject": "a"})
    b = LearnerState(learner_id=store.DEFAULT_LEARNER, progress={"subject": "b"})
    store.save_learner(a, subject="alpha", root=tmp_path)
    store.save_learner(b, subject="beta", root=tmp_path)
    # the two subjects do not clobber each other (the pre-Loop-26 bug)
    assert store.load_learner(subject="alpha", root=tmp_path).progress == {"subject": "a"}
    assert store.load_learner(subject="beta", root=tmp_path).progress == {"subject": "b"}


def test_legacy_global_learner_state_is_read_as_fallback(tmp_path):
    import json as _json

    legacy = tmp_path / "learner" / store.DEFAULT_LEARNER / "state.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(_json.dumps({"learner_id": store.DEFAULT_LEARNER, "progress": {"old": 1}}))
    # no per-subject state yet -> legacy is read
    assert store.load_learner(subject="finance", root=tmp_path).progress == {"old": 1}
    # a write goes to the new per-subject path and wins on the next read
    state = store.load_learner(subject="finance", root=tmp_path)
    state.progress = {"new": 2}
    store.save_learner(state, subject="finance", root=tmp_path)
    assert store.load_learner(subject="finance", root=tmp_path).progress == {"new": 2}
    assert (tmp_path / "learner" / store.DEFAULT_LEARNER / "finance" / "state.json").exists()


def test_doc_api_roundtrip_json_and_text(tmp_path):
    lid = store.DEFAULT_LEARNER
    assert store.get_doc(lid, "finance", "x.json", root=tmp_path) is None
    store.put_doc(lid, "finance", "x.json", {"a": 1}, root=tmp_path)
    assert store.get_doc(lid, "finance", "x.json", root=tmp_path) == {"a": 1}
    store.put_doc(lid, "finance", "plan.md", "# hello", root=tmp_path)
    assert store.get_doc(lid, "finance", "plan.md", root=tmp_path) == "# hello"
    store.delete_doc(lid, "finance", "x.json", root=tmp_path)
    assert store.get_doc(lid, "finance", "x.json", root=tmp_path) is None
    # doc_path points inside the per-subject docs dir (local backend)
    p = store.doc_path(lid, "finance", "plan.md", root=tmp_path)
    assert p is not None and p.exists() and "finance" in str(p)


def test_legacy_flat_doc_is_read_as_fallback(tmp_path):
    import json as _json

    lid = store.DEFAULT_LEARNER
    legacy = tmp_path / "learner" / lid / "diagnostic.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(_json.dumps({"item_ids": ["item_1"]}))
    assert store.load_diagnostic(lid, subject="finance", root=tmp_path) == {"item_ids": ["item_1"]}


def test_list_subjects_and_ensure_subject(tmp_path):
    assert store.list_subjects(root=tmp_path) == []
    store.ensure_subject("finance", root=tmp_path)
    store.ensure_subject("stats", root=tmp_path)
    assert store.list_subjects(root=tmp_path) == ["finance", "stats"]
    # ensure is idempotent and non-clobbering
    store.save_concepts("finance", [_concept("NPV")], root=tmp_path)
    store.ensure_subject("finance", root=tmp_path)
    assert len(store.load_concepts("finance", root=tmp_path)) == 1
