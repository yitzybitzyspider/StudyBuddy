"""Locating the knowledge-layer root.

The pipeline reads templates from ``prompts/`` and writes the run log to ``runs/`` etc., so
every component needs the knowledge-layer root. Resolution order:

1. an explicit path passed by the caller (tests pass a tmp dir here),
2. the ``STUDYBUDDY_HOME`` environment variable,
3. walking up from the current directory to the repo that holds the knowledge layer.
"""

from __future__ import annotations

import os
from pathlib import Path

# The directories that make up the knowledge layer (decision A2).
KNOWLEDGE_DIRS = ("concepts", "items", "prompts", "heuristics", "runs", "learner")

# Markers that identify the repo root when walking up.
_ROOT_MARKERS = ("prompts", "runs", "docs")


def knowledge_root(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Return the knowledge-layer root directory."""
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get("STUDYBUDDY_HOME")
    if env:
        return Path(env)
    cur = Path.cwd().resolve()
    for d in (cur, *cur.parents):
        if all((d / marker).is_dir() for marker in _ROOT_MARKERS):
            return d
    return cur
