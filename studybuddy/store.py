"""Knowledge-layer persistence facade (Loop 26: backend-routed).

Typed load/save for the artifacts the pipeline reads and writes. The engine calls these
functions; a :mod:`studybuddy.storage` backend does the actual persistence:

- ``LocalBackend`` (default): plain JSON under git, the original layout (decision A2).
- ``SupabaseBackend`` (``STUDYBUDDY_BACKEND=supabase`` + a user context): per-user rows in
  Postgres with RLS — the multi-user platform mode (DECISIONS §R).

The knowledge-layer *product* stays local no matter what: heuristics, the prompt registry,
the run log, and proposals never route to a database. Learner state is per
``(learner, subject)`` — a subject's gap profile/plan/schedule never clobbers another's.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from . import ids, paths
from .models import Concept, HeuristicsConfig, Item, LearnerState, Material, Proposal
from .storage.base import Doc
from .storage.local import LocalBackend

DEFAULT_LEARNER = "learner_default"

# Working-doc names (the editable artifacts of a cycle).
DIAGNOSTIC_DOC = "diagnostic.json"


def _backend(root=None) -> LocalBackend:
    """Resolve the storage backend. Loop 27/28 add user-context + Supabase dispatch here."""
    return LocalBackend(paths.knowledge_root(root))


def current_learner() -> str:
    """The learner id for the current context: the signed-in user's id in platform mode,
    the single default learner otherwise."""
    from . import usercontext

    return usercontext.get_user_id() or DEFAULT_LEARNER


def concept_id(name: str) -> str:
    """The stable concept id for a concept name (used to link items <-> concepts)."""
    return ids.slug_id("concept", name)


def load_heuristics(*, root=None) -> HeuristicsConfig:
    """Load the deterministic heuristics config (product artifact: always local/git)."""
    path = paths.knowledge_root(root) / "heuristics" / "config.json"
    if not path.exists():
        raise FileNotFoundError("heuristics/config.json not found; run `studybuddy init`")
    return HeuristicsConfig.model_validate(json.loads(path.read_text(encoding="utf-8")))


# --- subjects ---------------------------------------------------------------------------


def list_subjects(*, root=None) -> list[str]:
    return _backend(root).list_subjects()


def ensure_subject(subject: str, name: str | None = None, *, root=None) -> None:
    _backend(root).ensure_subject(subject, name)


# --- subject-scoped artifacts ---------------------------------------------------------


def load_concepts(subject: str, *, root=None) -> list[Concept]:
    return _backend(root).load_concepts(subject)


def save_concepts(subject: str, concepts: Iterable[Concept], *, root=None) -> None:
    _backend(root).save_concepts(subject, list(concepts))


def merge_concepts(subject: str, new: Iterable[Concept], *, root=None) -> list[Concept]:
    """Add/replace concepts by id, preserving existing ones. Returns the merged list."""
    backend = _backend(root)
    by_id = {c.id: c for c in backend.load_concepts(subject)}
    for c in new:
        by_id[c.id] = c
    merged = list(by_id.values())
    backend.save_concepts(subject, merged)
    return merged


def load_items(subject: str, *, root=None) -> list[Item]:
    return _backend(root).load_items(subject)


def save_items(subject: str, items: Iterable[Item], *, root=None) -> None:
    _backend(root).save_items(subject, list(items))


def add_items(subject: str, new: Iterable[Item], *, root=None) -> list[Item]:
    """Append items to the bank (ids are unique ULIDs). Returns the full bank."""
    backend = _backend(root)
    by_id = {i.id: i for i in backend.load_items(subject)}
    for i in new:
        by_id[i.id] = i
    merged = list(by_id.values())
    backend.save_items(subject, merged)
    return merged


def load_materials(subject: str, *, root=None) -> list[Material]:
    return _backend(root).load_materials(subject)


def add_material(subject: str, material: Material, *, root=None) -> None:
    _backend(root).add_material(subject, material)


def save_material_raw(material_id: str, text: str, *, subject: str, root=None) -> str:
    """Persist raw ingested text; returns the backend-meaningful raw_ref."""
    return _backend(root).save_material_raw(subject, material_id, text)


def load_material_raw(raw_ref: str, *, subject: str, root=None) -> str:
    return _backend(root).load_material_raw(subject, raw_ref)


# --- learner state (per learner, per subject) -------------------------------------------


def load_learner(
    learner_id: str = DEFAULT_LEARNER, *, subject: str, root=None
) -> LearnerState:
    return _backend(root).load_learner(learner_id, subject)


def save_learner(state: LearnerState, *, subject: str, root=None) -> None:
    _backend(root).save_learner(state.learner_id, subject, state)


# --- working docs (active diagnostic, answers-in-progress, session, plan one-pager) ------


def get_doc(learner_id: str, subject: str, name: str, *, root=None) -> Doc | None:
    return _backend(root).get_doc(learner_id, subject, name)


def put_doc(learner_id: str, subject: str, name: str, payload: Doc, *, root=None) -> None:
    _backend(root).put_doc(learner_id, subject, name, payload)


def delete_doc(learner_id: str, subject: str, name: str, *, root=None) -> None:
    _backend(root).delete_doc(learner_id, subject, name)


def doc_path(learner_id: str, subject: str, name: str, *, root=None) -> Path | None:
    """The on-disk path of a working doc, when the backend has one (local only).

    CLI flows print this so the user can edit the file; DB-backed modes return None and
    interaction happens in the web UI instead.
    """
    backend = _backend(root)
    getter = getattr(backend, "doc_path", None)
    return getter(learner_id, subject, name) if getter else None


# --- active diagnostic cycle (a working doc; modeled in diagnostic.py) -------------------


def save_diagnostic(learner_id: str, diagnostic: dict, *, subject: str, root=None) -> None:
    put_doc(learner_id, subject, DIAGNOSTIC_DOC, diagnostic, root=root)


def load_diagnostic(
    learner_id: str = DEFAULT_LEARNER, *, subject: str, root=None
) -> dict | None:
    doc = get_doc(learner_id, subject, DIAGNOSTIC_DOC, root=root)
    return doc if isinstance(doc, dict) else None


# --- proposals inbox (Phase 5; product artifact: always local, human-gated) --------------


def _proposals_path(root) -> Path:
    return paths.knowledge_root(root) / "proposals" / "inbox.json"


def load_proposals(*, root=None) -> list[Proposal]:
    path = _proposals_path(root)
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Proposal.model_validate(p) for p in raw]


def save_proposals(proposals: Iterable[Proposal], *, root=None) -> None:
    path = _proposals_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [p.model_dump(mode="json") for p in proposals]
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
