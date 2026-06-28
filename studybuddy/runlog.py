"""The append-only run log (decision A4).

Every Claude call appends one ``RunLogEntry`` to ``runs/runlog.jsonl`` (one JSON object
per line, cheap and diff-friendly). The raw structured input and raw model output are
written as separate blobs under ``runs/blobs/`` and referenced by relative path, so the
log stays small and whole prompts stay out of it.

This is the evidence surface the Phase 5 self-improvement loop will read; it exists from
Phase 0 on purpose (build-plan rule 2).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import paths
from .models import RunLogEntry


class RunLog:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = paths.knowledge_root(root)
        self.runs_dir = self.root / "runs"
        self.blobs_dir = self.runs_dir / "blobs"
        self.logfile = self.runs_dir / "runlog.jsonl"

    def write_blob(self, run_id: str, suffix: str, content: Any) -> str:
        """Persist a raw payload and return its path relative to the knowledge root."""
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        path = self.blobs_dir / f"{run_id}.{suffix}.json"
        if isinstance(content, str):
            text = content
        else:
            text = json.dumps(content, indent=2, ensure_ascii=False, default=str)
        path.write_text(text, encoding="utf-8")
        return str(path.relative_to(self.root))

    def append(self, entry: RunLogEntry) -> None:
        """Append one entry to the JSONL log (creating it if needed)."""
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        with self.logfile.open("a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")

    def read_all(self) -> list[RunLogEntry]:
        if not self.logfile.exists():
            return []
        entries = []
        for line in self.logfile.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                entries.append(RunLogEntry.model_validate_json(line))
        return entries
