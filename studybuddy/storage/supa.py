"""Supabase storage backend (platform Loop 28).

Per-user rows in Postgres, isolated by RLS: every request carries the signed-in user's JWT
(``postgrest.auth(access_token)``), so ``auth.uid()`` resolves and the owner-only policies
do the enforcement. The backend still stamps ``user_id`` explicitly on every write — belt
and suspenders; RLS ``with check`` would reject a mismatch anyway.

Semantics mirror :class:`~studybuddy.storage.local.LocalBackend` exactly (whole-list
load/save), so the engine cannot tell the backends apart. Raw material text lives in a
``raw_text`` column (exams are small text); its ``raw_ref`` sentinel is ``db:<material_id>``.

Construction is per request (the web layer's user context provides the token); a tiny
slug→uuid subject cache lives for the life of the instance only.
"""

from __future__ import annotations

import os
from typing import Any

from ..models import Concept, Item, LearnerState, Material
from .base import Doc


class SupabaseConfigError(RuntimeError):
    """SUPABASE_URL / SUPABASE_ANON_KEY missing while STUDYBUDDY_BACKEND=supabase."""


def _make_client(access_token: str):
    try:
        from supabase import ClientOptions, create_client
    except ImportError as e:  # pragma: no cover - import guard
        raise SupabaseConfigError(
            "platform mode needs the supabase package: pip install -e \".[platform]\""
        ) from e

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_ANON_KEY")
    if not url or not key:
        raise SupabaseConfigError(
            "set SUPABASE_URL and SUPABASE_ANON_KEY for STUDYBUDDY_BACKEND=supabase"
        )
    client = create_client(
        url, key, options=ClientOptions(auto_refresh_token=False, persist_session=False)
    )
    client.postgrest.auth(access_token)  # every PostgREST call carries the user JWT (RLS)
    return client


class SupabaseBackend:
    def __init__(self, user_id: str, access_token: str, client: Any | None = None):
        self.user_id = user_id
        self.client = client if client is not None else _make_client(access_token)
        self._subject_ids: dict[str, str] = {}  # slug -> uuid, per-request cache

    def _t(self, table: str):
        return self.client.table(table)

    # -- subjects ----------------------------------------------------------------------

    def list_subjects(self) -> list[str]:
        rows = self._t("subjects").select("slug").eq("user_id", self.user_id).execute().data
        return sorted(r["slug"] for r in rows)

    def ensure_subject(self, subject: str, name: str | None = None) -> None:
        self._t("subjects").upsert(
            {"user_id": self.user_id, "slug": subject, "name": name or subject},
            on_conflict="user_id,slug",
        ).execute()
        self._subject_ids.pop(subject, None)

    def _subject_id(self, subject: str) -> str:
        cached = self._subject_ids.get(subject)
        if cached:
            return cached
        rows = (
            self._t("subjects").select("id")
            .eq("user_id", self.user_id).eq("slug", subject)
            .execute().data
        )
        if not rows:  # auto-provision, mirroring the local backend's lazy file creation
            self.ensure_subject(subject)
            rows = (
                self._t("subjects").select("id")
                .eq("user_id", self.user_id).eq("slug", subject)
                .execute().data
            )
        sid = rows[0]["id"]
        self._subject_ids[subject] = sid
        return sid

    # -- entity tables (whole-list semantics) ---------------------------------------------

    def _load_payloads(self, table: str, subject: str) -> list[dict]:
        sid = self._subject_id(subject)
        rows = self._t(table).select("payload").eq("subject_id", sid).execute().data
        return [r["payload"] for r in rows]

    def _replace_all(self, table: str, id_col: str, subject: str, entries: list[tuple[str, dict]]) -> None:
        sid = self._subject_id(subject)
        self._t(table).delete().eq("subject_id", sid).execute()
        if entries:
            self._t(table).insert(
                [
                    {"user_id": self.user_id, "subject_id": sid, id_col: eid, "payload": payload}
                    for eid, payload in entries
                ]
            ).execute()

    def load_concepts(self, subject: str) -> list[Concept]:
        return [Concept.model_validate(p) for p in self._load_payloads("concepts", subject)]

    def save_concepts(self, subject: str, concepts: list[Concept]) -> None:
        self._replace_all(
            "concepts", "concept_id", subject,
            [(c.id, c.model_dump(mode="json")) for c in concepts],
        )

    def load_items(self, subject: str) -> list[Item]:
        return [Item.model_validate(p) for p in self._load_payloads("items", subject)]

    def save_items(self, subject: str, items: list[Item]) -> None:
        self._replace_all(
            "items", "item_id", subject,
            [(i.id, i.model_dump(mode="json")) for i in items],
        )

    # -- materials ---------------------------------------------------------------------

    def load_materials(self, subject: str) -> list[Material]:
        sid = self._subject_id(subject)
        rows = self._t("materials").select("payload").eq("subject_id", sid).execute().data
        # skip raw-only stub rows (payload {}) written by save_material_raw before ingest
        # finished assembling the Material record
        return [Material.model_validate(r["payload"]) for r in rows if r["payload"]]

    def add_material(self, subject: str, material: Material) -> None:
        sid = self._subject_id(subject)
        self._t("materials").upsert(
            {
                "user_id": self.user_id,
                "subject_id": sid,
                "material_id": material.id,
                "payload": material.model_dump(mode="json"),
            },
            on_conflict="subject_id,material_id",
        ).execute()

    def save_material_raw(self, subject: str, material_id: str, text: str) -> str:
        # Raw text arrives before the Material record (ingest order); stub the row now,
        # add_material fills the payload on the same key.
        sid = self._subject_id(subject)
        self._t("materials").upsert(
            {
                "user_id": self.user_id,
                "subject_id": sid,
                "material_id": material_id,
                "payload": {},
                "raw_text": text,
            },
            on_conflict="subject_id,material_id",
        ).execute()
        return f"db:{material_id}"

    def load_material_raw(self, subject: str, raw_ref: str) -> str:
        if not raw_ref.startswith("db:"):
            raise KeyError(f"not a database raw_ref: {raw_ref!r}")
        sid = self._subject_id(subject)
        rows = (
            self._t("materials").select("raw_text")
            .eq("subject_id", sid).eq("material_id", raw_ref[3:])
            .execute().data
        )
        if not rows or rows[0]["raw_text"] is None:
            raise KeyError(f"no raw text for {raw_ref!r}")
        return rows[0]["raw_text"]

    # -- learner state -------------------------------------------------------------------

    def load_learner(self, learner_id: str, subject: str) -> LearnerState:
        # learner_id is the user in platform mode; identity comes from the JWT/RLS.
        sid = self._subject_id(subject)
        rows = (
            self._t("learner_state").select("payload")
            .eq("user_id", self.user_id).eq("subject_id", sid)
            .execute().data
        )
        if not rows:
            return LearnerState(learner_id=self.user_id)
        return LearnerState.model_validate(rows[0]["payload"])

    def save_learner(self, learner_id: str, subject: str, state: LearnerState) -> None:
        sid = self._subject_id(subject)
        self._t("learner_state").upsert(
            {
                "user_id": self.user_id,
                "subject_id": sid,
                "payload": state.model_dump(mode="json"),
            },
            on_conflict="user_id,subject_id",
        ).execute()

    # -- working docs ---------------------------------------------------------------------

    def get_doc(self, learner_id: str, subject: str, name: str) -> Doc | None:
        sid = self._subject_id(subject)
        rows = (
            self._t("learner_docs").select("payload,text_payload")
            .eq("user_id", self.user_id).eq("subject_id", sid).eq("name", name)
            .execute().data
        )
        if not rows:
            return None
        row = rows[0]
        return row["payload"] if row["payload"] is not None else row["text_payload"]

    def put_doc(self, learner_id: str, subject: str, name: str, payload: Doc) -> None:
        sid = self._subject_id(subject)
        record: dict[str, Any] = {
            "user_id": self.user_id,
            "subject_id": sid,
            "name": name,
            "payload": None,
            "text_payload": None,
        }
        if isinstance(payload, str):
            record["text_payload"] = payload
        else:
            record["payload"] = payload
        self._t("learner_docs").upsert(record, on_conflict="user_id,subject_id,name").execute()

    def delete_doc(self, learner_id: str, subject: str, name: str) -> None:
        sid = self._subject_id(subject)
        (
            self._t("learner_docs").delete()
            .eq("user_id", self.user_id).eq("subject_id", sid).eq("name", name)
            .execute()
        )
