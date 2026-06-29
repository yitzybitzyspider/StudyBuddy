"""Stage 8 time-budget reality-check tests (Phase 4, Loop 21)."""

from studybuddy import timebudget
from studybuddy.models import ConstraintResolution, StudyPlan


def test_estimate_scales_with_items_and_gap_type():
    light = timebudget.estimate([
        {"concept_id": "c1", "name": "C1", "item_formats": ["mc", "mc"], "gap_types": ["speed"]},
    ])
    heavy = timebudget.estimate([
        {"concept_id": "c2", "name": "C2", "item_formats": ["essay", "essay"],
         "gap_types": ["foundational"]},
    ])
    assert heavy["total_hours"] > light["total_hours"]
    assert light["per_topic"][0]["items"] == 2
    assert "format_minutes" in light["assumptions"]


def test_empty_topic_uses_default_item_count():
    est = timebudget.estimate([
        {"concept_id": "c", "name": "C", "item_formats": [], "gap_types": []},
    ])
    assert est["per_topic"][0]["items"] == timebudget._DEFAULT_ITEMS_PER_TOPIC
    assert est["total_hours"] > 0


def test_reconcile_fits():
    r = timebudget.reconcile(5.0, 10.0)
    assert r["status"] == "fits" and r["gap_hours"] == -5.0
    assert "to spare" in r["message"]


def test_reconcile_over():
    r = timebudget.reconcile(12.0, 8.0)
    assert r["status"] == "over" and r["gap_hours"] == 4.0
    assert "short by" in r["message"]


def test_reconcile_unknown_available():
    r = timebudget.reconcile(5.0, None)
    assert r["status"] == "unknown" and r["gap_hours"] is None


def test_apply_resolution_records_choice():
    plan = StudyPlan(learner_id="l", version="v1")
    timebudget.apply_resolution(plan, ConstraintResolution.compress)
    assert plan.constraint_resolution is ConstraintResolution.compress
