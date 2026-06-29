"""Stage 8/9 spacing & interleaving engine (Phase 4, Loop 20).

A small, honest SM-2 scheduler. Each practiced item carries a review *card* — ease factor,
current interval (days), repetition count, and a due date — updated from how the answer went.
Deterministic code owns this entirely (no Claude call): the engine decides *when* an item
comes back; Claude never touches scheduling.

SM-2 (Wozniak), with the standard quality scale 0–5:
  - quality < 3 is a lapse: repetitions reset, interval back to 1 day.
  - quality >= 3 passes: interval grows 1 -> 6 -> round(interval * ease).
  - ease updates by `ease += 0.1 - (5-q)*(0.08 + (5-q)*0.02)`, floored at 1.3.

The cards live on ``LearnerState.spacing_schedule`` (keyed by item id), so the schedule is
plain JSON under git like everything else. Times are stored as ISO-8601 UTC strings.

Interleaving (FR-F): ``due_items`` returns cards ordered by due date, and ``interleave``
reorders a due set so consecutive items avoid repeating the same concept where possible —
spacing *and* interleaving, both deterministic.
"""

from __future__ import annotations

from datetime import datetime, timedelta

DEFAULT_EASE = 2.5
MIN_EASE = 1.3


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def new_card(now: datetime) -> dict:
    """A fresh review card, due immediately."""
    return {
        "ease": DEFAULT_EASE,
        "interval": 0,        # days; 0 = never successfully reviewed yet
        "repetitions": 0,
        "due": _iso(now),
        "last_quality": None,
        "reviews": 0,
    }


def quality_from_outcome(correct: bool, *, blank: bool = False, felt_lucky: bool = False) -> int:
    """Map a graded answer to an SM-2 quality (0–5), honestly.

    A confident correct answer is a 5; a correct-but-felt-lucky answer only passes at 3
    (shaky, should come back sooner); a wrong answer is 2; a blank is 0.
    """
    if blank:
        return 0
    if not correct:
        return 2
    return 3 if felt_lucky else 5


def review(card: dict, quality: int, *, now: datetime) -> dict:
    """Apply one SM-2 review to a card and return the updated card (does not mutate input)."""
    ease = float(card.get("ease", DEFAULT_EASE))
    interval = int(card.get("interval", 0))
    reps = int(card.get("repetitions", 0))
    q = max(0, min(5, int(quality)))

    if q < 3:  # lapse
        reps = 0
        interval = 1
    else:
        if reps == 0:
            interval = 1
        elif reps == 1:
            interval = 6
        else:
            interval = max(1, round(interval * ease))
        reps += 1
        ease = ease + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
        ease = max(MIN_EASE, ease)

    return {
        "ease": round(ease, 4),
        "interval": interval,
        "repetitions": reps,
        "due": _iso(now + timedelta(days=interval)),
        "last_quality": q,
        "reviews": int(card.get("reviews", 0)) + 1,
    }


def update_schedule(state, item_id: str, quality: int, *, now: datetime) -> dict:
    """Update (or create) the card for ``item_id`` on the learner's spacing schedule."""
    schedule = state.spacing_schedule or {}
    card = schedule.get(item_id) or new_card(now)
    card = review(card, quality, now=now)
    schedule[item_id] = card
    state.spacing_schedule = schedule
    return card


def _parse(due: str) -> datetime:
    try:
        return datetime.fromisoformat(due)
    except (TypeError, ValueError):
        return datetime.min


def due_items(state, *, now: datetime) -> list[str]:
    """Item ids whose card is due at/before ``now``, soonest-due first."""
    schedule = state.spacing_schedule or {}
    due = [(iid, _parse(c.get("due", "")), c) for iid, c in schedule.items()]
    due = [(iid, d) for iid, d, c in due if d <= now]
    due.sort(key=lambda t: t[1])
    return [iid for iid, _ in due]


def interleave(item_ids: list[str], concept_of) -> list[str]:
    """Reorder so consecutive items avoid repeating a concept where possible (FR-F).

    ``concept_of`` maps an item id to its primary concept id. Greedy: at each step pick the
    earliest remaining item whose concept differs from the one just placed; fall back to the
    earliest remaining when every candidate shares it.
    """
    remaining = list(item_ids)
    out: list[str] = []
    last_concept = None
    while remaining:
        pick = next((i for i in remaining if concept_of(i) != last_concept), remaining[0])
        out.append(pick)
        last_concept = concept_of(pick)
        remaining.remove(pick)
    return out
