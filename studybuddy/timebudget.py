"""Stage 8: the time-budget reality check (Phase 4, Loop 21).

The plan is only honest if it owns up to whether it actually fits the time available. This
module computes a realistic **time-to-comprehensive** from the practice load and the spacing
model, compares it to the learner's available hours, and surfaces the gap plainly. The user
then chooses to **compress** (trim to fit) or **extend** (keep the full plan, move the date).

Deterministic only — no Claude call. The estimate is rough by nature; honesty (philosophy §9)
means surfacing the assumptions, not pretending at precision. Every coefficient here is a
stated assumption, tunable later through ratified promotion.
"""

from __future__ import annotations

from .models import ConstraintResolution

# Average minutes for one attempt at an item, by format (a stated assumption).
FORMAT_MINUTES = {"mc": 1.5, "numeric": 3.0, "short": 4.0, "essay": 8.0, "application": 6.0}
_DEFAULT_MINUTES = 3.0

# Successful repetitions to reach "comprehensive", scaled by the heaviest gap on the topic.
# Derived from SM-2 reaching its third growing interval; foundational gaps need more reps.
_BASE_REPS = 3.0
_GAP_REP_MULTIPLIER = {
    "foundational": 1.6,
    "depth": 1.3,
    "breadth": 1.2,
    "overconfidence": 1.1,
    "speed": 1.0,
}
_DEFAULT_ITEMS_PER_TOPIC = 5  # when a topic has no banked practice items yet


def _topic_minutes(item_formats: list[str], gap_types: list[str]) -> float:
    n = len(item_formats) or _DEFAULT_ITEMS_PER_TOPIC
    avg = (
        sum(FORMAT_MINUTES.get(f, _DEFAULT_MINUTES) for f in item_formats) / len(item_formats)
        if item_formats else _DEFAULT_MINUTES
    )
    reps = _BASE_REPS * max((_GAP_REP_MULTIPLIER.get(g, 1.0) for g in gap_types), default=1.0)
    return n * avg * reps


def estimate(topics: list[dict]) -> dict:
    """Realistic time-to-comprehensive over the plan's topics.

    Each topic is ``{concept_id, name, item_formats: [str], gap_types: [str]}``. Returns
    per-topic hours, the total, and the assumptions used.
    """
    per_topic = []
    total_minutes = 0.0
    for t in topics:
        minutes = _topic_minutes(t.get("item_formats", []), t.get("gap_types", []))
        total_minutes += minutes
        per_topic.append(
            {
                "concept_id": t.get("concept_id"),
                "name": t.get("name"),
                "hours": round(minutes / 60.0, 2),
                "items": len(t.get("item_formats", [])) or _DEFAULT_ITEMS_PER_TOPIC,
            }
        )
    return {
        "total_hours": round(total_minutes / 60.0, 2),
        "per_topic": per_topic,
        "assumptions": {
            "format_minutes": FORMAT_MINUTES,
            "base_reps": _BASE_REPS,
            "gap_rep_multiplier": _GAP_REP_MULTIPLIER,
            "default_items_per_topic": _DEFAULT_ITEMS_PER_TOPIC,
            "_note": "rough estimate; coefficients are stated assumptions (philosophy §9)",
        },
    }


def reconcile(needed_hours: float, available_hours: float | None) -> dict:
    """Compare needed vs available and surface the honest gap."""
    if available_hours is None:
        return {
            "needed_hours": needed_hours, "available_hours": None,
            "gap_hours": None, "status": "unknown",
            "message": f"Estimated ~{needed_hours:.1f} h to comprehensive; available time "
                       "not set (run intake).",
        }
    gap = round(needed_hours - available_hours, 2)
    if gap <= 0:
        msg = (f"~{needed_hours:.1f} h needed, {available_hours:.1f} h available — it fits, "
               f"with {abs(gap):.1f} h to spare.")
        status = "fits"
    else:
        msg = (f"~{needed_hours:.1f} h needed but only {available_hours:.1f} h available — "
               f"short by {gap:.1f} h. Choose to compress (trim scope) or extend (more time).")
        status = "over"
    return {
        "needed_hours": needed_hours, "available_hours": available_hours,
        "gap_hours": gap, "status": status, "message": msg,
    }


def apply_resolution(plan, resolution: ConstraintResolution) -> None:
    """Record the user's compress/extend choice on the plan (the honest gap stays visible)."""
    plan.constraint_resolution = resolution
