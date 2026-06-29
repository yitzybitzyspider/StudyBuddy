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


def test_material_aware_depth_when_only_hard_band_breaks(tmp_path, fake_client):
    """Easy items right, hard items wrong on the same concept -> depth, not foundational."""
    from studybuddy.models import (
        Calibration, Item, ItemFormat, ItemResponse, Provenance, ProvenanceOrigin,
    )

    for d in ("prompts", "heuristics", "runs", "runs/blobs", "concepts", "items", "learner"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    seed.seed_knowledge_layer(root=tmp_path)
    store.save_concepts(
        "finance", [Concept(id="concept_npv", subject="finance", name="NPV")], root=tmp_path
    )

    def _it(diff):
        return Item(
            id=ids.ulid_id("item"), concept_ids=["concept_npv"], format=ItemFormat.numeric,
            stem="q", answer_key="1", provenance=Provenance(origin=ProvenanceOrigin.retrieved),
            calibration=Calibration(observed_difficulty=diff),
        )

    easy1, easy2 = _it(0.1), _it(0.1)   # band easy
    hard1, hard2 = _it(0.95), _it(0.95)  # band hard
    store.save_items("finance", [easy1, easy2, hard1, hard2], root=tmp_path)

    responses = [
        ItemResponse(item_id=easy1.id, response="1", correct=True),
        ItemResponse(item_id=easy2.id, response="1", correct=True),
        ItemResponse(item_id=hard1.id, response="x", correct=False),
        ItemResponse(item_id=hard2.id, response="x", correct=False),
    ]
    result = DiagnosticResult(
        id=ids.ulid_id("diag"), learner_id=store.DEFAULT_LEARNER, item_responses=responses,
        per_concept_rollup={"concept_npv": {"seen": 4, "correct": 2, "correct_rate": 0.5, "blanks": 0}},
        generated_at=ids.utcnow(),
    )
    store.save_learner(
        LearnerState(learner_id=store.DEFAULT_LEARNER, diagnostic_results=[result]), root=tmp_path
    )

    client = fake_client(outputs=[INTERP_OUT])
    out = diagnose.diagnose("finance", root=tmp_path, client=client)
    cls = {c.concept_id: c.gap_types for c in out["classification"]}
    # aggregate cr is 0.5 (would be "foundational" the old way); band-aware says depth
    assert "depth" in cls["concept_npv"]
    assert "foundational" not in cls["concept_npv"]


def test_gap_confidence_accrues_and_status_confirms_across_batches(tmp_path, fake_client):
    from studybuddy.models import GapEntry, GapProfile, GapStatus

    _setup(tmp_path, {"concept_npv": {"seen": 4, "correct": 1, "correct_rate": 0.25, "blanks": 0}})
    # seed a prior hypothesis for the same concept+gap_type at 0.5
    state = store.load_learner(root=tmp_path)
    state.gap_profile = GapProfile(
        learner_id=store.DEFAULT_LEARNER,
        entries=[GapEntry(concept_id="concept_npv", gap_type="foundational", confidence=0.5)],
        updated_at=ids.utcnow(),
    )
    store.save_learner(state, root=tmp_path)

    # interp returns the same gap at 0.7 -> noisy-OR 0.5 + 0.5*0.7 = 0.85, status confirmed
    client = fake_client(outputs=[INTERP_OUT.replace('"NPV"', '"concept_npv"')])
    result = diagnose.diagnose("finance", root=tmp_path, client=client)
    entry = next(e for e in result["gap_profile"].entries if e.concept_id == "concept_npv")
    assert abs(entry.confidence - 0.85) < 1e-9
    assert entry.status is GapStatus.confirmed


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
