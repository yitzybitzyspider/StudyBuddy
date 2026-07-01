"""The storage-backend protocol (Loop 26).

Whole-list load/save semantics deliberately mirror the original file behavior — at personal
scale (hundreds of items) that is simpler and safer than row-level diffing, and it keeps the
two backends trivially equivalent. ``merge_concepts``/``add_items`` live in the facade as
load→merge→save so neither backend duplicates merge logic.

Working docs are the editable artifacts of a cycle (the active diagnostic, an answers file
in progress, a study session, the plan one-pager). They are ``dict`` (JSON) or ``str``
(markdown/text) payloads addressed by ``(learner_id, subject, name)``.
"""

from __future__ import annotations

from typing import Protocol, Union

from ..models import Concept, Item, LearnerState, Material

Doc = Union[dict, str]


class StorageBackend(Protocol):
    # -- subjects ----------------------------------------------------------------------
    def list_subjects(self) -> list[str]: ...

    def ensure_subject(self, subject: str, name: str | None = None) -> None: ...

    # -- subject-scoped artifacts --------------------------------------------------------
    def load_concepts(self, subject: str) -> list[Concept]: ...

    def save_concepts(self, subject: str, concepts: list[Concept]) -> None: ...

    def load_items(self, subject: str) -> list[Item]: ...

    def save_items(self, subject: str, items: list[Item]) -> None: ...

    def load_materials(self, subject: str) -> list[Material]: ...

    def add_material(self, subject: str, material: Material) -> None: ...

    def delete_material(self, subject: str, material_id: str) -> None: ...

    def save_material_raw(self, subject: str, material_id: str, text: str) -> str: ...

    def load_material_raw(self, subject: str, raw_ref: str) -> str: ...

    # -- learner state, per (learner, subject) -------------------------------------------
    def load_learner(self, learner_id: str, subject: str) -> LearnerState: ...

    def save_learner(self, learner_id: str, subject: str, state: LearnerState) -> None: ...

    # -- working docs ---------------------------------------------------------------------
    def get_doc(self, learner_id: str, subject: str, name: str) -> Doc | None: ...

    def put_doc(self, learner_id: str, subject: str, name: str, payload: Doc) -> None: ...

    def delete_doc(self, learner_id: str, subject: str, name: str) -> None: ...
