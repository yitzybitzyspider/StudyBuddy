"""Stage 4 compose-diagnostic tests."""

import json

from studybuddy import diagnostic, ids, seed, store
from studybuddy.models import (
    Concept,
    Intake,
    Item,
    ItemFormat,
    LearnerState,
    Provenance,
    ProvenanceOrigin,
)
from studybuddy.runlog import RunLog

GEN_OUT = json.dumps(
    {
        "stem": "Define net present value.",
        "format": "short",
        "answer_key": "PV of future cash flows minus the initial outlay",
        "concept_names": ["Net Present Value"],
    }
)
VERIFY_PASS = json.dumps(
    {
        "tests_intended_concept": True,
        "answer_key_correct": True,
        "unambiguous": True,
        "verdict": "pass",
    }
)
VERIFY_FAIL = json.dumps(
    {
        "tests_intended_concept": False,
        "answer_key_correct": True,
        "unambiguous": True,
        "verdict": "fail",
        "issues": ["off concept"],
    }
)


def _bank_item(concept_id, fmt=ItemFormat.numeric):
    return Item(
        id=ids.ulid_id("item"),
        concept_ids=[concept_id],
        format=fmt,
        stem=f"Q about {concept_id}",
        answer_key="42",
        provenance=Provenance(origin=ProvenanceOrigin.retrieved),
    )


def _setup_subject(tmp_path, with_bank=True, confidence=None):
    npv = Concept(id=store.concept_id("Net Present Value"), subject="finance", name="Net Present Value")
    disc = Concept(id=store.concept_id("Discounting"), subject="finance", name="Discounting")
    store.save_concepts("finance", [npv, disc], root=tmp_path)
    if with_bank:
        store.save_items(
            "finance",
            [_bank_item(npv.id), _bank_item(npv.id), _bank_item(disc.id)],
            root=tmp_path,
        )
    if confidence is not None:
        store.save_learner(
            LearnerState(learner_id=store.DEFAULT_LEARNER, intake=Intake(per_topic_confidence=confidence)),
            root=tmp_path,
        )
    return npv, disc


def test_compose_retrieval_first_no_generation(tmp_path):
    npv, disc = _setup_subject(
        tmp_path, confidence={"concept_net-present-value": 0.2, "concept_discounting": 0.9}
    )
    result = diagnostic.compose("finance", root=tmp_path, size=2)  # no client needed
    diag = result["diagnostic"]

    assert len(diag.item_ids) == 2
    assert result["retrieved"] == 2 and result["generated"] == 0
    # weakest concept (NPV, low confidence) is sampled first
    chosen_concepts = {
        i.concept_ids[0] for i in store.load_items("finance", root=tmp_path) if i.id in diag.item_ids
    }
    assert npv.id in chosen_concepts

    # answers template written with one question per item
    answers = json.loads(result["answers_path"].read_text())
    assert len(answers["questions"]) == 2
    assert all("response" in q for q in answers["questions"])
    # working diagnostic persisted
    assert store.load_diagnostic(root=tmp_path)["item_ids"] == diag.item_ids


def test_compose_generates_to_fill_and_verifies(tmp_path, fake_client):
    for d in ("prompts", "heuristics", "runs", "runs/blobs"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    seed.seed_knowledge_layer(root=tmp_path)
    _setup_subject(tmp_path, with_bank=False)

    # empty bank + size 1 -> one generate+verify(pass)
    client = fake_client(outputs=[GEN_OUT, VERIFY_PASS])
    result = diagnostic.compose("finance", root=tmp_path, client=client, size=1)
    assert result["retrieved"] == 0 and result["generated"] == 1

    bank = store.load_items("finance", root=tmp_path)
    assert len(bank) == 1
    assert bank[0].provenance.origin is ProvenanceOrigin.generated
    assert bank[0].template_id == "generate_item"

    phases = [e.phase for e in RunLog(tmp_path).read_all()]
    assert phases == ["Stage 4: generate_item", "Stage 4: verify_item"]


def test_generation_gate_rejects_failed_verification(tmp_path, fake_client):
    for d in ("prompts", "heuristics", "runs", "runs/blobs"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    seed.seed_knowledge_layer(root=tmp_path)
    _setup_subject(tmp_path, with_bank=False)

    # first generated item fails verify, second passes
    client = fake_client(outputs=[GEN_OUT, VERIFY_FAIL, GEN_OUT, VERIFY_PASS])
    result = diagnostic.compose("finance", root=tmp_path, client=client, size=1)
    assert result["generated"] == 1  # only the verified one is kept
    assert client.call_count == 4  # two generate+verify rounds
