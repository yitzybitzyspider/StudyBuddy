"""Loop 28: SupabaseBackend against an in-memory fake PostgREST client (offline)."""

import itertools

import pytest

from studybuddy import ids, store, usercontext
from studybuddy.models import (
    Concept,
    Item,
    ItemFormat,
    LearnerState,
    Material,
    MaterialType,
    Provenance,
    ProvenanceOrigin,
)
from studybuddy.storage.supa import SupabaseBackend

_uuid = itertools.count(1)


class _Query:
    def __init__(self, table, op, payload=None, on_conflict=None):
        self.table, self.op, self.payload, self.on_conflict = table, op, payload, on_conflict
        self.filters = []

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def _match(self, row):
        return all(row.get(c) == v for c, v in self.filters)

    def execute(self):
        rows = self.table.rows
        if self.op == "select":
            data = [dict(r) for r in rows if self._match(r)]
        elif self.op == "delete":
            self.table.rows = [r for r in rows if not self._match(r)]
            data = []
        elif self.op == "insert":
            for rec in self.payload if isinstance(self.payload, list) else [self.payload]:
                self.table._add(dict(rec))
            data = []
        elif self.op == "upsert":
            keys = [k.strip() for k in (self.on_conflict or "").split(",") if k.strip()]
            rec = dict(self.payload)
            for r in rows:
                if keys and all(r.get(k) == rec.get(k) for k in keys):
                    r.update(rec)
                    break
            else:
                self.table._add(rec)
            data = []
        else:  # pragma: no cover
            raise AssertionError(self.op)

        class R:  # mimic postgrest response
            pass

        resp = R()
        resp.data = data
        return resp


class _Table:
    def __init__(self, name):
        self.name, self.rows = name, []

    def _add(self, rec):
        if self.name == "subjects" and "id" not in rec:
            rec["id"] = f"uuid-{next(_uuid)}"
        self.rows.append(rec)

    def select(self, cols="*"):
        return _Query(self, "select")

    def insert(self, payload):
        return _Query(self, "insert", payload)

    def upsert(self, payload, on_conflict=None):
        return _Query(self, "upsert", payload, on_conflict)

    def delete(self):
        return _Query(self, "delete")


class FakeSupabase:
    def __init__(self):
        self.tables = {}

    def table(self, name):
        return self.tables.setdefault(name, _Table(name))


@pytest.fixture
def backend():
    return SupabaseBackend("user_a", "token", client=FakeSupabase())


def _item():
    return Item(
        id=ids.ulid_id("item"), concept_ids=["concept_npv"], format=ItemFormat.numeric,
        stem="q", answer_key="1", provenance=Provenance(origin=ProvenanceOrigin.retrieved),
    )


def test_subjects_ensure_and_list(backend):
    assert backend.list_subjects() == []
    backend.ensure_subject("finance", "Finance 101")
    backend.ensure_subject("finance")  # idempotent (upsert on user_id,slug)
    backend.ensure_subject("stats")
    assert backend.list_subjects() == ["finance", "stats"]


def test_concepts_roundtrip_whole_list(backend):
    c1 = Concept(id="concept_npv", subject="finance", name="NPV")
    c2 = Concept(id="concept_disc", subject="finance", name="Discounting")
    backend.save_concepts("finance", [c1, c2])
    assert {c.id for c in backend.load_concepts("finance")} == {"concept_npv", "concept_disc"}
    backend.save_concepts("finance", [c1])  # whole-list replace
    assert [c.id for c in backend.load_concepts("finance")] == ["concept_npv"]


def test_items_roundtrip(backend):
    it = _item()
    backend.save_items("finance", [it])
    loaded = backend.load_items("finance")
    assert len(loaded) == 1 and loaded[0].id == it.id


def test_material_raw_then_record(backend):
    """save_material_raw stubs the row; add_material fills the payload on the same key."""
    ref = backend.save_material_raw("finance", "material_1", "raw exam text µσ")
    assert ref == "db:material_1"
    assert backend.load_materials("finance") == []  # stub row is not a Material yet
    m = Material(id="material_1", type=MaterialType.exam, source="e.md",
                 raw_ref=ref, ingested_at=ids.utcnow())
    backend.add_material("finance", m)
    mats = backend.load_materials("finance")
    assert len(mats) == 1 and mats[0].raw_ref == "db:material_1"
    assert backend.load_material_raw("finance", ref) == "raw exam text µσ"


def test_learner_state_upsert_per_subject(backend):
    assert backend.load_learner("ignored", "finance").learner_id == "user_a"
    st = LearnerState(learner_id="user_a", progress={"n": 1})
    backend.save_learner("ignored", "finance", st)
    st.progress = {"n": 2}
    backend.save_learner("ignored", "finance", st)  # upsert, not duplicate
    assert backend.load_learner("x", "finance").progress == {"n": 2}
    table = backend.client.tables["learner_state"]
    assert len(table.rows) == 1


def test_docs_json_and_text(backend):
    backend.put_doc("x", "finance", "d.json", {"a": 1})
    backend.put_doc("x", "finance", "plan.md", "# md")
    assert backend.get_doc("x", "finance", "d.json") == {"a": 1}
    assert backend.get_doc("x", "finance", "plan.md") == "# md"
    backend.put_doc("x", "finance", "d.json", {"a": 2})  # upsert
    assert backend.get_doc("x", "finance", "d.json") == {"a": 2}
    backend.delete_doc("x", "finance", "d.json")
    assert backend.get_doc("x", "finance", "d.json") is None


def test_writes_stamp_user_id(backend):
    backend.save_concepts("finance", [Concept(id="c", subject="finance", name="C")])
    rows = backend.client.tables["concepts"].rows
    assert rows and all(r["user_id"] == "user_a" for r in rows)


def test_store_facade_dispatches_to_supabase(tmp_path, monkeypatch):
    """env=supabase + a user context routes through SupabaseBackend; without a context the
    facade stays local (CLI/test safety)."""
    import studybuddy.storage.supa as supa_mod

    made = {}

    def fake_backend(user_id, token):
        made["args"] = (user_id, token)
        return SupabaseBackend(user_id, token, client=FakeSupabase())

    monkeypatch.setenv("STUDYBUDDY_BACKEND", "supabase")
    monkeypatch.setattr(supa_mod, "SupabaseBackend", fake_backend)

    # no user context -> local backend (files under tmp_path)
    store.ensure_subject("localsub", root=tmp_path)
    assert (tmp_path / "concepts" / "localsub.json").exists()

    # with a user context -> supabase backend
    token = usercontext.set_user("user_9", "jwt-9")
    try:
        store.ensure_subject("cloudsub", root=tmp_path)
    finally:
        usercontext.reset_user(token)
    assert made["args"] == ("user_9", "jwt-9")
    assert not (tmp_path / "concepts" / "cloudsub.json").exists()
