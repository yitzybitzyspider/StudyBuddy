"""Stage 6 diagnose tests."""

import json

from studybuddy import diagnose, ids, seed, store
from studybuddy.models import (
    Concept,
    DependencyEdge,
    DependencyRelation,
    DiagnosticResult,
    Intake,
    LearnerState,
)
from studybuddy.runlog import RunLog

INTERP_OUT = json.dumps(
    {
        "gaps": [
            {"concept": "NPV", "gap_type": "foundational", "severity": 0.8, "confidence": 0.7,
             "rationale": "missed the basics"},
        ]
    }
)


def _setup(tmp_path, rollup, confidence=None):
    for d in ("prompts", "heuristics", "runs", "runs/blobs", "concepts", "items", "learner"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    seed.seed_knowledge_layer(root=tmp_path)
    store.save_concepts(
        "finance", [Concept(id="concept_npv", subject="finance", name="NPV")], root=tmp_path
    )
    result = DiagnosticResult(
        id=ids.ulid_id("diag"),
        learner_id=store.DEFAULT_LEARNER,
        item_responses=[],
        per_concept_rollup=rollup,
        generated_at=ids.utcnow(),
    )
    intake = Intake(per_topic_confidence=confidence) if confidence else None
    store.save_learner(
        LearnerState(learner_id=store.DEFAULT_LEARNER, intake=intake, diagnostic_results=[result]),
        root=tmp_path,
    )


def test_deterministic_classification_foundational_and_speed(tmp_path, fake_client):
    _setup(tmp_path, {"concept_npv": {"seen": 4, "correct": 1, "correct_rate": 0.25, "blanks": 1}})
    client = fake_client(outputs=[INTERP_OUT])
    result = diagnose.diagnose("finance", root=tmp_path, client=client)

    cls = {c.concept_id: c.gap_types for c in result["classification"]}
    assert "foundational" in cls["concept_npv"]  # cr 0.25 < 0.5
    assert "speed" in cls["concept_npv"]          # a blank was left

    # interpret_gaps output becomes the GapProfile (concept name -> id)
    profile = result["gap_profile"]
    assert [(e.concept_id, e.gap_type) for e in profile.entries] == [("concept_npv", "foundational")]
    assert profile.entries[0].evidence_refs[0].ref == "concept_npv"
    assert [e.phase for e in RunLog(tmp_path).read_all()] == ["Stage 6: interpret_gaps"]

    # the stored DiagnosticResult got its gap_classification filled
    assert store.load_learner(root=tmp_path).diagnostic_results[-1].gap_classification


def test_depth_gap_for_partial_mastery(tmp_path, fake_client):
    _setup(tmp_path, {"concept_npv": {"seen": 4, "correct": 3, "correct_rate": 0.7, "blanks": 0}})
    client = fake_client(outputs=[INTERP_OUT])
    result = diagnose.diagnose("finance", root=tmp_path, client=client)
    cls = {c.concept_id: c.gap_types for c in result["classification"]}
    assert cls["concept_npv"] == ["depth"]  # 0.5 <= 0.7 < 0.8, no blanks


def test_overconfidence_from_high_self_rating_low_score(tmp_path, fake_client):
    _setup(
        tmp_path,
        {"concept_npv": {"seen": 4, "correct": 2, "correct_rate": 0.5, "blanks": 0}},
        confidence={"concept_npv": 0.9},
    )
    client = fake_client(outputs=[INTERP_OUT])
    result = diagnose.diagnose("finance", root=tmp_path, client=client)
    cls = {c.concept_id: c.gap_types for c in result["classification"]}
    assert "overconfidence" in cls["concept_npv"]  # self 0.9 but cr 0.5 < 0.6


def test_dependency_context_passed_to_interpret_gaps(tmp_path, fake_client):
    # NPV depends_on Discounting; both tested, Discounting weak -> upstream signal
    _setup(
        tmp_path,
        {
            "concept_npv": {"seen": 4, "correct": 1, "correct_rate": 0.25, "blanks": 0},
            "concept_discounting": {"seen": 4, "correct": 1, "correct_rate": 0.25, "blanks": 0},
        },
    )
    concepts = [
        Concept(
            id="concept_npv", subject="finance", name="NPV",
            dependency_edges=[DependencyEdge(
                other_concept_id="concept_discounting",
                relation=DependencyRelation.depends_on, confidence=0.9)],
        ),
        Concept(id="concept_discounting", subject="finance", name="Discounting"),
    ]
    store.save_concepts("finance", concepts, root=tmp_path)

    client = fake_client(outputs=[INTERP_OUT])
    diagnose.diagnose("finance", root=tmp_path, client=client)

    # the interpret_gaps user message carries the prerequisite structure
    user_msg = client.messages.calls[0]["messages"][0]["content"]
    payload = json.loads(user_msg.split("INPUT:\n", 1)[1])
    ctx = payload["dependency_context"]
    assert "NPV" in ctx
    dep = ctx["NPV"]["depends_on"][0]
    assert dep["concept"] == "Discounting"
    assert dep["edge_confidence"] == 0.9
    assert dep["prerequisite_correct_rate"] == 0.25
    assert dep["prerequisite_tested"] is True


def test_no_results_raises(tmp_path):
    for d in ("prompts", "heuristics", "runs", "concepts", "learner"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    seed.seed_knowledge_layer(root=tmp_path)
    store.save_concepts("finance", [], root=tmp_path)
    try:
        diagnose.diagnose("finance", root=tmp_path)
        assert False, "expected ValueError"
    except ValueError:
        pass
