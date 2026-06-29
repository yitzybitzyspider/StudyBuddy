from studybuddy import calibration, ids
from studybuddy.models import Item, ItemFormat, Provenance, ProvenanceOrigin


def _item():
    return Item(
        id=ids.ulid_id("item"),
        concept_ids=["concept_x"],
        format=ItemFormat.numeric,
        stem="q",
        answer_key="1",
        provenance=Provenance(origin=ProvenanceOrigin.retrieved),
    )


def test_single_update_correct():
    it = _item()
    calibration.update(it, True, confidence_k=4)
    c = it.calibration
    assert c.times_seen == 1
    assert c.correct_rate == 1.0
    assert c.observed_difficulty == 0.0
    assert c.confidence == 1 / 5
    assert c.updated_at is not None
    assert c.discrimination is None  # honestly deferred (§9)


def test_running_correct_rate_and_difficulty():
    it = _item()
    for correct in [True, False, True, True]:
        calibration.update(it, correct)
    assert it.calibration.times_seen == 4
    assert abs(it.calibration.correct_rate - 0.75) < 1e-9
    assert abs(it.calibration.observed_difficulty - 0.25) < 1e-9


def test_confidence_saturates_with_exposure():
    it = _item()
    early = None
    for n in range(1, 21):
        calibration.update(it, True, confidence_k=4)
        if n == 1:
            early = it.calibration.confidence
    assert early < it.calibration.confidence  # grows
    assert it.calibration.confidence > 0.8  # saturates upward
