"""Calibration accrual (Track A): item stats sharpen with every answer.

Observations write back automatically with no human gate (philosophy §8). With a single
user we accrue only what we can compute honestly (philosophy §9):

- ``times_seen``        — count of answers recorded for the item
- ``correct_rate``      — running fraction correct
- ``observed_difficulty`` — a 0–1 proxy = 1 − correct_rate
- ``confidence``        — how much to trust these stats, saturating with times_seen
- ``updated_at``        — last accrual time

``discrimination`` is deliberately left ``None``. True discrimination (how well an item
separates strong from weak learners) is a *cross-respondent* statistic; with one learner it
cannot be computed without faking rigor, so we don't (philosophy §9). It is revisited when
the data supports it (multi-user, NFR-2).
"""

from __future__ import annotations

from . import ids
from .models import Item

DEFAULT_CONFIDENCE_K = 4.0


def update(item: Item, correct: bool, *, confidence_k: float = DEFAULT_CONFIDENCE_K) -> None:
    """Accrue one answer's evidence into the item's calibration (in place)."""
    cal = item.calibration
    prev_seen = cal.times_seen
    prev_correct = (cal.correct_rate or 0.0) * prev_seen
    cal.times_seen = prev_seen + 1
    cal.correct_rate = (prev_correct + (1.0 if correct else 0.0)) / cal.times_seen
    cal.observed_difficulty = 1.0 - cal.correct_rate
    cal.confidence = cal.times_seen / (cal.times_seen + confidence_k)
    cal.updated_at = ids.utcnow()
