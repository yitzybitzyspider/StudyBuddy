"""Shared fixtures: a temp knowledge layer + a fake Anthropic client."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def kroot(tmp_path: Path) -> Path:
    """A temporary knowledge-layer root with one registered template.

    The template's output_schema requires a top-level object with a 'topics' array, so
    tests can drive the wrapper's parse/validate/retry paths deterministically.
    """
    for d in ("concepts", "items", "prompts", "heuristics", "runs", "runs/blobs", "learner"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    task_dir = tmp_path / "prompts" / "extract_structure"
    task_dir.mkdir(parents=True, exist_ok=True)
    template = {
        "id": "extract_structure",
        "task": "extract_structure",
        "version": "v1",
        "input_schema": {"type": "object"},
        "output_schema": {
            "type": "object",
            "required": ["topics"],
            "properties": {"topics": {"type": "array"}},
            "additionalProperties": True,
        },
        "body": "Extract a flat topic list from the material.",
        "examples": [],
        "metrics": {},
    }
    (task_dir / "v1.json").write_text(json.dumps(template, indent=2))
    (task_dir / "index.json").write_text(json.dumps({"current": "v1"}))
    return tmp_path


class FakeMessages:
    def __init__(self, outputs, fail_with=None):
        self._outputs = list(outputs)
        self._fail_with = fail_with
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._fail_with is not None:
            raise self._fail_with
        text = self._outputs.pop(0)
        return SimpleNamespace(content=[SimpleNamespace(text=text)])


class FakeClient:
    """Stands in for anthropic.Anthropic(); returns queued outputs in order."""

    def __init__(self, outputs=(), fail_with=None):
        self.messages = FakeMessages(outputs, fail_with=fail_with)

    @property
    def call_count(self):
        return len(self.messages.calls)


@pytest.fixture
def fake_client():
    return FakeClient
