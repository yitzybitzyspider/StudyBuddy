"""Local-file storage backend — the original knowledge-layer layout (decision A2).

Layout (per-subject learner state is new in Loop 26; the legacy global layout is still
read as a fallback so existing data keeps working):

    concepts/<subject>.json                     list[Concept]
    items/<subject>.json                        list[Item]
    materials/<subject>.json                    list[Material]
    materials/raw/<id>.txt                      raw ingested text
    learner/<lid>/<subject>/state.json          LearnerState   (canonical)
    learner/<lid>/<subject>/docs/<name>         working docs (.json or text)
    learner/<lid>/state.json                    LEGACY read-only fallback
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from ..models import Concept, Item, LearnerState, Material
from .base import Doc


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _dump_list(models: Iterable[Any]) -> list[dict]:
    return [m.model_dump(mode="json") for m in models]


class LocalBackend:
    """Plain JSON under the knowledge root. Single-learner by default; no auth concept."""

    def __init__(self, root: Path):
        self.root = Path(root)

    # -- subjects ----------------------------------------------------------------------

    def list_subjects(self) -> list[str]:
        d = self.root / "concepts"
        if not d.is_dir():
            return []
        return sorted(p.stem for p in d.glob("*.json"))

    def ensure_subject(self, subject: str, name: str | None = None) -> None:
        path = self._subject_path("concepts", subject)
        if not path.exists():
            _write_json(path, [])

    # -- subject-scoped artifacts --------------------------------------------------------

    def _subject_path(self, kind: str, subject: str) -> Path:
        return self.root / kind / f"{subject}.json"

    def load_concepts(self, subject: str) -> list[Concept]:
        raw = _read_json(self._subject_path("concepts", subject)) or []
        return [Concept.model_validate(c) for c in raw]

    def save_concepts(self, subject: str, concepts: list[Concept]) -> None:
        _write_json(self._subject_path("concepts", subject), _dump_list(concepts))

    def load_items(self, subject: str) -> list[Item]:
        raw = _read_json(self._subject_path("items", subject)) or []
        return [Item.model_validate(i) for i in raw]

    def save_items(self, subject: str, items: list[Item]) -> None:
        _write_json(self._subject_path("items", subject), _dump_list(items))

    def load_materials(self, subject: str) -> list[Material]:
        raw = _read_json(self._subject_path("materials", subject)) or []
        return [Material.model_validate(m) for m in raw]

    def add_material(self, subject: str, material: Material) -> None:
        materials = self.load_materials(subject)
        materials.append(material)
        _write_json(self._subject_path("materials", subject), _dump_list(materials))

    def save_material_raw(self, subject: str, material_id: str, text: str) -> str:
        path = self.root / "materials" / "raw" / f"{material_id}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return str(path.relative_to(self.root))

    def load_material_raw(self, subject: str, raw_ref: str) -> str:
        return (self.root / raw_ref).read_text(encoding="utf-8")

    # -- learner state -------------------------------------------------------------------

    def _learner_dir(self, learner_id: str, subject: str) -> Path:
        return self.root / "learner" / learner_id / subject

    def load_learner(self, learner_id: str, subject: str) -> LearnerState:
        raw = _read_json(self._learner_dir(learner_id, subject) / "state.json")
        if raw is None:  # legacy global layout (pre-Loop-26): read-only fallback
            raw = _read_json(self.root / "learner" / learner_id / "state.json")
        if raw is None:
            return LearnerState(learner_id=learner_id)
        return LearnerState.model_validate(raw)

    def save_learner(self, learner_id: str, subject: str, state: LearnerState) -> None:
        _write_json(self._learner_dir(learner_id, subject) / "state.json",
                    state.model_dump(mode="json"))

    # -- working docs ---------------------------------------------------------------------

    def _doc_path(self, learner_id: str, subject: str, name: str) -> Path:
        return self._learner_dir(learner_id, subject) / "docs" / name

    def get_doc(self, learner_id: str, subject: str, name: str) -> Doc | None:
        path = self._doc_path(learner_id, subject, name)
        if not path.exists():  # legacy flat layout fallback (learner/<lid>/<name>)
            path = self.root / "learner" / learner_id / name
            if not path.exists():
                return None
        text = path.read_text(encoding="utf-8")
        if name.endswith(".json"):
            return json.loads(text)
        return text

    def put_doc(self, learner_id: str, subject: str, name: str, payload: Doc) -> None:
        path = self._doc_path(learner_id, subject, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, str):
            path.write_text(payload, encoding="utf-8")
        else:
            _write_json(path, payload)

    def delete_doc(self, learner_id: str, subject: str, name: str) -> None:
        path = self._doc_path(learner_id, subject, name)
        if path.exists():
            path.unlink()

    def doc_path(self, learner_id: str, subject: str, name: str) -> Path:
        """Local-only: the on-disk path of a working doc (for CLI 'edit this file' flows)."""
        return self._doc_path(learner_id, subject, name)
