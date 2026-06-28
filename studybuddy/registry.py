"""The prompt registry (decision A5).

Templates live at ``prompts/<task>/<version>.json`` and each task has an
``prompts/<task>/index.json`` whose ``current`` field names the active default version.
The wrapper resolves a template by ``(task, version)``, defaulting to ``current``.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import paths
from .models import PromptTask, PromptTemplate


class TemplateNotFound(Exception):
    """Raised when a requested template (task/version) is not in the registry."""


def _task_str(task: PromptTask | str) -> str:
    return task.value if isinstance(task, PromptTask) else str(task)


def task_dir(task: PromptTask | str, *, root: str | Path | None = None) -> Path:
    return paths.knowledge_root(root) / "prompts" / _task_str(task)


def current_version(task: PromptTask | str, *, root: str | Path | None = None) -> str:
    """Read the active default version from the task's index.json."""
    index = task_dir(task, root=root) / "index.json"
    if not index.exists():
        raise TemplateNotFound(f"no registry index for task {_task_str(task)!r} at {index}")
    data = json.loads(index.read_text())
    version = data.get("current")
    if not version:
        raise TemplateNotFound(f"index.json for task {_task_str(task)!r} has no 'current' version")
    return version


def load_template(
    task: PromptTask | str,
    version: str = "current",
    *,
    root: str | Path | None = None,
) -> PromptTemplate:
    """Load and validate a registered template."""
    if version == "current":
        version = current_version(task, root=root)
    path = task_dir(task, root=root) / f"{version}.json"
    if not path.exists():
        raise TemplateNotFound(f"no template for task {_task_str(task)!r} version {version!r} at {path}")
    return PromptTemplate.model_validate_json(path.read_text())
