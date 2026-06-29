"""Knowledge-layer persistence (Phase 1).

Typed load/save for the artifacts the pipeline reads and writes. Everything is plain JSON
under git (decision A2), partitioned by subject for the shared artifacts and by learner for
learner state. There is no database and no ORM — just Pydantic models and files.

Layout:
    concepts/<subject>.json       list[Concept]
    items/<subject>.json          list[Item]               (the item bank)
    materials/<subject>.json      list[Material]
    materials/raw/<id>.txt        raw ingested text (Material.raw_ref points here)
    learner/<lid>/state.json      LearnerState
    learner/<lid>/diagnostic.json the active diagnostic cycle (working file)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from . import ids, paths
from .models import Concept, HeuristicsConfig, Item, LearnerState, Material, Proposal

DEFAULT_LEARNER = "learner_default"


def concept_id(name: str) -> str:
    """The stable concept id for a concept name (used to link items <-> concepts)."""
    return ids.slug_id("concept", name)


def load_heuristics(*, root=None) -> HeuristicsConfig:
    """Load the deterministic heuristics config (seeded in Phase 0)."""
    raw = _read_json(paths.knowledge_root(root) / "heuristics" / "config.json")
    if raw is None:
        raise FileNotFoundError("heuristics/config.json not found; run `studybuddy init`")
    return HeuristicsConfig.model_validate(raw)


# --- low-level json -------------------------------------------------------------------


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _dump_list(models: Iterable[Any]) -> list[dict]:
    return [m.model_dump(mode="json") for m in models]


# --- subject-scoped artifacts ---------------------------------------------------------


def _subject_path(kind: str, subject: str, *, root) -> Path:
    return paths.knowledge_root(root) / kind / f"{subject}.json"


def load_concepts(subject: str, *, root=None) -> list[Concept]:
    raw = _read_json(_subject_path("concepts", subject, root=root)) or []
    return [Concept.model_validate(c) for c in raw]


def save_concepts(subject: str, concepts: Iterable[Concept], *, root=None) -> None:
    _write_json(_subject_path("concepts", subject, root=root), _dump_list(concepts))


def merge_concepts(subject: str, new: Iterable[Concept], *, root=None) -> list[Concept]:
    """Add/replace concepts by id, preserving existing ones. Returns the merged list."""
    by_id = {c.id: c for c in load_concepts(subject, root=root)}
    for c in new:
        by_id[c.id] = c
    merged = list(by_id.values())
    save_concepts(subject, merged, root=root)
    return merged


def load_items(subject: str, *, root=None) -> list[Item]:
    raw = _read_json(_subject_path("items", subject, root=root)) or []
    return [Item.model_validate(i) for i in raw]


def save_items(subject: str, items: Iterable[Item], *, root=None) -> None:
    _write_json(_subject_path("items", subject, root=root), _dump_list(items))


def add_items(subject: str, new: Iterable[Item], *, root=None) -> list[Item]:
    """Append items to the bank (ids are unique ULIDs). Returns the full bank."""
    existing = load_items(subject, root=root)
    by_id = {i.id: i for i in existing}
    for i in new:
        by_id[i.id] = i
    merged = list(by_id.values())
    save_items(subject, merged, root=root)
    return merged


def load_materials(subject: str, *, root=None) -> list[Material]:
    raw = _read_json(_subject_path("materials", subject, root=root)) or []
    return [Material.model_validate(m) for m in raw]


def add_material(subject: str, material: Material, *, root=None) -> None:
    materials = load_materials(subject, root=root)
    materials.append(material)
    _write_json(_subject_path("materials", subject, root=root), _dump_list(materials))


def save_material_raw(material_id: str, text: str, *, root=None) -> str:
    """Persist raw ingested text and return its path relative to the knowledge root."""
    base = paths.knowledge_root(root)
    path = base / "materials" / "raw" / f"{material_id}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path.relative_to(base))


# --- learner state --------------------------------------------------------------------


def _learner_dir(learner_id: str, *, root) -> Path:
    return paths.knowledge_root(root) / "learner" / learner_id


def load_learner(learner_id: str = DEFAULT_LEARNER, *, root=None) -> LearnerState:
    raw = _read_json(_learner_dir(learner_id, root=root) / "state.json")
    if raw is None:
        return LearnerState(learner_id=learner_id)
    return LearnerState.model_validate(raw)


def save_learner(state: LearnerState, *, root=None) -> None:
    path = _learner_dir(state.learner_id, root=root) / "state.json"
    _write_json(path, state.model_dump(mode="json"))


# --- active diagnostic cycle (a working dict; modeled in diagnostic.py) ----------------


def save_diagnostic(learner_id: str, diagnostic: dict, *, root=None) -> None:
    _write_json(_learner_dir(learner_id, root=root) / "diagnostic.json", diagnostic)


def load_diagnostic(learner_id: str = DEFAULT_LEARNER, *, root=None) -> dict | None:
    return _read_json(_learner_dir(learner_id, root=root) / "diagnostic.json")


def learner_file(learner_id: str, name: str, *, root=None) -> Path:
    """Path to an auxiliary learner file (e.g. an editable answers template)."""
    return _learner_dir(learner_id, root=root) / name


# --- proposals inbox (Phase 5; human-gated, Track B) ----------------------------------


def _proposals_path(root) -> Path:
    return paths.knowledge_root(root) / "proposals" / "inbox.json"


def load_proposals(*, root=None) -> list[Proposal]:
    raw = _read_json(_proposals_path(root)) or []
    return [Proposal.model_validate(p) for p in raw]


def save_proposals(proposals: Iterable[Proposal], *, root=None) -> None:
    _write_json(_proposals_path(root), _dump_list(proposals))
