"""Stage 7 adaptive sampling + stopping-rule tests (Phase 3, Loop 18)."""

from studybuddy import ids, sampling, seed, store
from studybuddy.models import (
    Concept,
    DependencyEdge,
    DependencyRelation,
    DiagnosticResult,
    GapEntry,
    GapProfile,
    GapStatus,
    Intake,
    Item,
    ItemFormat,
    LearnerState,
    Provenance,
    ProvenanceOrigin,
)


def _heur(tmp_path):
    for d in ("prompts", "heuristics", "runs", "runs/blobs", "concepts", "items", "learner"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    seed.seed_knowledge_layer(root=tmp_path)
    return store.load_heuristics(root=tmp_path)


def _state(entries, n_results=1, rollup=None):
    results = [
        DiagnosticResult(
            id=ids.ulid_id("diag"), learner_id=store.DEFAULT_LEARNER,
            per_concept_rollup=rollup or {}, generated_at=ids.utcnow(),
        )
        for _ in range(n_results)
    ]
    profile = GapProfile(
        learner_id=store.DEFAULT_LEARNER, entries=entries, updated_at=ids.utcnow()
    )
    return LearnerState(
        learner_id=store.DEFAULT_LEARNER, diagnostic_results=results, gap_profile=profile
    )


def _gap(cid, conf, status=GapStatus.hypothesis, gtype="foundational"):
    return GapEntry(concept_id=cid, gap_type=gtype, confidence=conf, status=status)


def test_stops_when_all_gaps_above_target(tmp_path):
    heur = _heur(tmp_path)  # target 0.8
    state = _state([_gap("c1", 0.9), _gap("c2", 0.85)])
    status = sampling.stopping_status(state, heur)
    assert status["stop"] and "confidence target" in status["reason"]


def test_stops_when_no_open_gaps(tmp_path):
    heur = _heur(tmp_path)
    state = _state([_gap("c1", 0.4, status=GapStatus.resolved)])
    status = sampling.stopping_status(state, heur)
    assert status["stop"] and "no open gaps" in status["reason"]


def test_continues_when_a_gap_is_below_target(tmp_path):
    heur = _heur(tmp_path)
    state = _state([_gap("c1", 0.5)])
    status = sampling.stopping_status(state, heur)
    assert not status["stop"]
    assert status["low_confidence_gaps"][0][0] == "c1"


def test_stops_at_batch_cap_even_if_low_confidence(tmp_path):
    heur = _heur(tmp_path)  # max_adaptive_batches 4
    state = _state([_gap("c1", 0.3)], n_results=4)
    status = sampling.stopping_status(state, heur)
    assert status["stop"] and "cap" in status["reason"]


def test_select_focus_weakest_then_boundary_then_strength(tmp_path):
    _heur(tmp_path)
    concepts = [
        Concept(id="c_npv", subject="f", name="NPV",
                dependency_edges=[DependencyEdge(other_concept_id="c_disc",
                                                 relation=DependencyRelation.depends_on, confidence=0.9)]),
        Concept(id="c_disc", subject="f", name="Discounting"),
        Concept(id="c_tvm", subject="f", name="TVM"),
    ]
    rollup = {"c_tvm": {"correct_rate": 0.9}}  # a strength to verify
    state = _state(
        [_gap("c_npv", 0.4), _gap("c_disc", 0.5)], rollup=rollup
    )
    focus = sampling.select_focus(state, concepts)
    assert focus[0] == "c_npv"          # weakest (lowest confidence)
    assert "c_disc" in focus            # boundary prerequisite, also shaky
    assert focus[-1] == "c_tvm"         # verify the strength


def test_next_batch_composes_when_open(tmp_path, fake_client):
    _heur(tmp_path)
    concept = Concept(id=store.concept_id("NPV"), subject="finance", name="NPV")
    store.save_concepts("finance", [concept], root=tmp_path)
    store.save_items(
        "finance",
        [Item(id=ids.ulid_id("item"), concept_ids=[concept.id], format=ItemFormat.numeric,
              stem="q", answer_key="1", provenance=Provenance(origin=ProvenanceOrigin.retrieved))
         for _ in range(6)],
        root=tmp_path,
    )
    store.save_learner(_state([_gap(concept.id, 0.5)]), root=tmp_path)

    result = sampling.next_batch("finance", root=tmp_path, client=fake_client(outputs=[]))
    assert result["composed"] is True
    assert result["focus"] == [concept.id]
    assert result["diagnostic"].item_ids  # a batch was assembled


def test_next_batch_stops_and_does_not_compose(tmp_path, fake_client):
    _heur(tmp_path)
    store.save_concepts("finance", [Concept(id="c1", subject="finance", name="C1")], root=tmp_path)
    store.save_learner(_state([_gap("c1", 0.95)]), root=tmp_path)
    result = sampling.next_batch("finance", root=tmp_path, client=fake_client(outputs=[]))
    assert result["composed"] is False
    assert result["status"]["stop"] is True
