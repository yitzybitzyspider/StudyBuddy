"""Stage 5 administer + grade tests."""

import json

from studybuddy import administer, ids, seed, store
from studybuddy.models import (
    Concept,
    GradingSpec,
    Item,
    ItemFormat,
    Provenance,
    ProvenanceOrigin,
)
from studybuddy.runlog import RunLog

GRADE_OUT = json.dumps({"score": 0.8, "reasoning": "solid", "missed_facets": ["units"]})


def _item(fmt, answer_key, *, concept="concept_npv", grading=None):
    return Item(
        id=ids.ulid_id("item"),
        concept_ids=[concept],
        format=fmt,
        stem=f"Question ({fmt.value})",
        answer_key=answer_key,
        provenance=Provenance(origin=ProvenanceOrigin.retrieved),
        grading_spec=grading or GradingSpec(),
    )


def _setup(tmp_path):
    for d in ("prompts", "heuristics", "runs", "runs/blobs", "items", "concepts", "learner"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    seed.seed_knowledge_layer(root=tmp_path)
    store.save_concepts(
        "finance", [Concept(id="concept_npv", subject="finance", name="NPV")], root=tmp_path
    )
    mc = _item(ItemFormat.mc, "B")
    num = _item(ItemFormat.numeric, "42")
    short = _item(ItemFormat.short, "n/a", grading=GradingSpec(max_score=1.0))
    store.save_items("finance", [mc, num, short], root=tmp_path)
    return mc, num, short


def _answers_file(tmp_path, entries):
    path = tmp_path / "answers.json"
    path.write_text(json.dumps({"subject": "finance", "questions": entries}))
    return path


def test_grades_objective_and_open_ended(tmp_path, fake_client):
    mc, num, short = _setup(tmp_path)
    answers = _answers_file(
        tmp_path,
        [
            {"item_id": mc.id, "response": "B"},                       # correct
            {"item_id": num.id, "response": "10"},                     # wrong (ans 42)
            {"item_id": short.id, "response": "an explanation", "felt_lucky": True},  # graded
        ],
    )
    client = fake_client(outputs=[GRADE_OUT])
    result = administer.administer("finance", answers_path=answers, root=tmp_path, client=client)

    assert result["answered"] == 3
    assert result["correct"] == 2  # mc + short(0.8>=0.6); numeric wrong

    by_item = {r.item_id: r for r in result["result"].item_responses}
    assert by_item[mc.id].correct is True
    assert by_item[num.id].correct is False
    assert by_item[short.id].correct is True and by_item[short.id].felt_lucky_flag is True

    # only the open-ended item hit Claude
    assert [e.phase for e in RunLog(tmp_path).read_all()] == ["Stage 5: grade_response"]

    # rollup + calibration accrual
    rollup = result["result"].per_concept_rollup["concept_npv"]
    assert rollup["seen"] == 3 and rollup["correct"] == 2
    assert all(i.calibration.times_seen == 1 for i in store.load_items("finance", root=tmp_path))


def test_blank_response_is_incorrect_and_flagged(tmp_path):
    mc, num, short = _setup(tmp_path)
    answers = _answers_file(tmp_path, [{"item_id": num.id, "response": "   "}])
    result = administer.administer("finance", answers_path=answers, root=tmp_path)
    assert result["correct"] == 0
    assert result["feedback"][0]["blank"] is True
    assert result["result"].per_concept_rollup["concept_npv"]["blanks"] == 1


def test_result_appended_to_learner_state(tmp_path, fake_client):
    mc, num, short = _setup(tmp_path)
    answers = _answers_file(tmp_path, [{"item_id": mc.id, "response": "B"}])
    administer.administer("finance", answers_path=answers, root=tmp_path)
    state = store.load_learner(root=tmp_path)
    assert len(state.diagnostic_results) == 1
