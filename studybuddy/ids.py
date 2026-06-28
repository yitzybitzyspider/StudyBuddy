"""ID generation and timestamps (decision A3).

Two schemes, by design:

- **Curated, human-edited artifacts** (concepts, prompt templates) get human-readable
  prefixed slugs so the knowledge layer stays diffable: ``concept_time-value-of-money``.
- **High-volume append-only records** (items, run-log entries, diagnostic results) get
  time-sortable ULIDs so they sort by creation and never collide: ``item_01J9Z...``.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from ulid import ULID

__all__ = ["slugify", "slug_id", "ulid_id", "new_ulid", "utcnow"]

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Lowercase, hyphenate, and trim a string into a URL/filename-safe slug."""
    return _NON_SLUG.sub("-", text.strip().lower()).strip("-")


def slug_id(prefix: str, text: str) -> str:
    """A stable, human-readable id for a curated artifact, e.g. ``concept_<slug>``."""
    slug = slugify(text)
    if not slug:
        raise ValueError(f"cannot build a slug id from empty text: {text!r}")
    return f"{prefix}_{slug}"


def new_ulid() -> str:
    """A fresh ULID string (time-sortable, collision-resistant)."""
    return str(ULID())


def ulid_id(prefix: str) -> str:
    """A prefixed ULID for a high-volume record, e.g. ``item_<ulid>``."""
    return f"{prefix}_{new_ulid()}"


def utcnow() -> datetime:
    """Timezone-aware current UTC time, for all ``*_at`` / ``ts`` fields."""
    return datetime.now(timezone.utc)
