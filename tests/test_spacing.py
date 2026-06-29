"""Stage 8/9 spacing engine tests (Phase 4, Loop 20)."""

from datetime import datetime, timedelta

from studybuddy import spacing
from studybuddy.models import LearnerState

NOW = datetime(2026, 6, 29, 12, 0, 0)


def test_quality_mapping_is_honest():
    assert spacing.quality_from_outcome(True) == 5
    assert spacing.quality_from_outcome(True, felt_lucky=True) == 3  # passes but shaky
    assert spacing.quality_from_outcome(False) == 2
    assert spacing.quality_from_outcome(False, blank=True) == 0


def test_successful_reviews_grow_the_interval():
    card = spacing.new_card(NOW)
    card = spacing.review(card, 5, now=NOW)
    assert card["interval"] == 1 and card["repetitions"] == 1
    card = spacing.review(card, 5, now=NOW)
    assert card["interval"] == 6 and card["repetitions"] == 2
    prev_ease = card["ease"]  # SM-2 grows the interval using the ease *before* this review
    card = spacing.review(card, 5, now=NOW)
    assert card["interval"] == round(6 * prev_ease) and card["repetitions"] == 3
    # due date is now + interval days
    assert card["due"] == (NOW + timedelta(days=card["interval"])).isoformat()


def test_lapse_resets_interval_and_reps():
    card = spacing.new_card(NOW)
    for _ in range(3):
        card = spacing.review(card, 5, now=NOW)
    card = spacing.review(card, 2, now=NOW)  # a miss
    assert card["interval"] == 1 and card["repetitions"] == 0


def test_ease_floors_at_minimum():
    card = spacing.new_card(NOW)
    card = spacing.review(card, 5, now=NOW)
    for _ in range(10):
        card = spacing.review(card, 3, now=NOW)  # repeated low-but-passing pushes ease down
    assert card["ease"] >= spacing.MIN_EASE


def test_update_schedule_and_due_items():
    state = LearnerState(learner_id="l")
    spacing.update_schedule(state, "item_a", 5, now=NOW)   # due in 1 day
    spacing.update_schedule(state, "item_b", 2, now=NOW)   # lapse, due in 1 day too

    # nothing due right now
    assert spacing.due_items(state, now=NOW) == []
    # both due a day later, soonest-due first (stable by date)
    later = NOW + timedelta(days=2)
    assert set(spacing.due_items(state, now=later)) == {"item_a", "item_b"}


def test_interleave_avoids_consecutive_same_concept():
    concept = {"a1": "A", "a2": "A", "b1": "B", "b2": "B"}
    order = spacing.interleave(["a1", "a2", "b1", "b2"], lambda i: concept[i])
    # no two adjacent share a concept
    assert all(concept[order[i]] != concept[order[i + 1]] for i in range(len(order) - 1))


def test_interleave_falls_back_when_unavoidable():
    concept = {"a1": "A", "a2": "A"}
    order = spacing.interleave(["a1", "a2"], lambda i: concept[i])
    assert order == ["a1", "a2"]  # only one concept: keep order, no crash
