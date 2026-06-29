"""Stage 9 in-system execution-loop tests (Phase 4, Loop 22)."""

import json
from datetime import datetime, timedelta

from studybuddy import execute, ids, seed, store
from studybuddy.models import (
    Concept,
    Item,
    ItemFormat,
    LearnerState,
    Provenance,
    ProvenanceOrigin,
)

NOW = datetime(2026, 6, 29, 12, 0, 0)


def _setup(tmp_path):
    for d in ("prompts", "heuristics", "runs", "runs/blobs", "concepts", "items", "learner"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    seed.seed_knowledge_layer(root=tmp_path)
    a = Concept(id="c_a", subject="finance", name="A")
    b = Concept(id="c_b", subject="finance", name="B")
    store.save_concepts("finance", [a, b], root=tmp_path)


def _item(cid, key="1"):
    return Item(
        id=ids.ulid_id("item"), concept_ids=[cid], format=ItemFormat.numeric,
        stem=f"q {cid}", answer_key=key, provenance=Provenance(origin=ProvenanceOrigin.retrieved),
    )


def test_session_pulls_new_items_when_nothing_due(tmp_path):
    _setup(tmp_path)
    items = [_item("c_a"), _item("c_a"), _item("c_b"), _item("c_b")]
    store.save_items("finance", items, root=tmp_path)
    store.save_learner(LearnerState(learner_id=store.DEFAULT_LEARNER), root=tmp_path)

    result = execute.next_session("finance", root=tmp_path, size=4, now=NOW)
    assert len(result["item_ids"]) == 4
    assert result["due_count"] == 0 and result["new_count"] == 4

    # interleaved: no two adjacent share a concept (2x A, 2x B is fully interleavable)
    by_id = {i.id: i for i in items}
    concepts = [by_id[i].concept_ids[0] for i in result["item_ids"]]
    assert all(concepts[i] != concepts[i + 1] for i in range(len(concepts) - 1))


def test_record_session_grades_reschedules_and_tracks_progress(tmp_path):
    _setup(tmp_path)
    it = _item("c_a", key="42")
    store.save_items("finance", [it], root=tmp_path)
    store.save_learner(LearnerState(learner_id=store.DEFAULT_LEARNER), root=tmp_path)

    execute.next_session("finance", root=tmp_path, size=1, now=NOW)
    # answer it correctly
    path = store.learner_file(store.DEFAULT_LEARNER, execute.SESSION_NAME, root=tmp_path)
    data = json.loads(path.read_text())
    data["questions"][0]["response"] = "42"
    path.write_text(json.dumps(data))

    result = execute.record_session("finance", root=tmp_path, now=NOW)
    assert result["answered"] == 1 and result["correct"] == 1 and result["rescheduled"] == 1

    state = store.load_learner(root=tmp_path)
    # spacing card created + scheduled into the future
    card = state.spacing_schedule[it.id]
    assert card["interval"] == 1 and card["due"] == (NOW + timedelta(days=1)).isoformat()
    # progress tracked
    assert state.progress["reviewed_total"] == 1 and state.progress["sessions"] == 1
    assert state.progress["by_concept"]["c_a"] == {"seen": 1, "correct": 1}
    # calibration accrued on the item
    assert store.load_items("finance", root=tmp_path)[0].calibration.times_seen == 1


def test_due_reviews_come_before_new_items(tmp_path):
    _setup(tmp_path)
    due_item, new_item = _item("c_a"), _item("c_b")
    store.save_items("finance", [due_item, new_item], root=tmp_path)
    state = LearnerState(learner_id=store.DEFAULT_LEARNER)
    # make due_item overdue
    from studybuddy import spacing
    spacing.update_schedule(state, due_item.id, 5, now=NOW - timedelta(days=10))
    store.save_learner(state, root=tmp_path)

    result = execute.next_session("finance", root=tmp_path, size=1, now=NOW)
    assert result["item_ids"] == [due_item.id]  # the due review wins the single slot
    assert result["due_count"] == 1
