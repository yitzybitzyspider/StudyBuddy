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


def record_acceptance(
    task: PromptTask | str, version: str, accepted: bool, *, root: str | Path | None = None
) -> None:
    """Track A: accrue a verify outcome into a template version's metrics (attempts,
    accepts, acceptance_rate). Updates the metric only — it never changes the `current`
    default (that promotion is Track B, human-gated)."""
    path = task_dir(task, root=root) / f"{version}.json"
    if not path.exists():
        return
    data = json.loads(path.read_text())
    metrics = data.get("metrics") or {}
    metrics["attempts"] = int(metrics.get("attempts") or 0) + 1
    metrics["accepts"] = int(metrics.get("accepts") or 0) + (1 if accepted else 0)
    metrics["acceptance_rate"] = metrics["accepts"] / metrics["attempts"]
    data["metrics"] = metrics
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


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
