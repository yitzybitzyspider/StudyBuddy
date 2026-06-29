"""Phase 2, Loop 15: web-search harvesting tests (mocked/offline client)."""

import json
from types import SimpleNamespace

from studybuddy import seed, store, websearch
from studybuddy.models import Concept, ProvenanceOrigin, RefKind

ASSESS_HIGH = json.dumps(
    {"standardization": "high", "query_terms": ["npv practice"], "rationale": "standardized"}
)
ASSESS_LOW = json.dumps(
    {"standardization": "low", "query_terms": ["prof exam"], "rationale": "bespoke"}
)
WEB_ITEMS = json.dumps(
    {
        "items": [
            {
                "stem": "PV of $1,100 in a year at 8%?",
                "format": "numeric",
                "answer_key": "1018.52",
                "concept_names": ["Discounting"],
                "source": {"kind": "web", "ref": "https://example.com/q1"},
            }
        ]
    }
)


def _setup(tmp_path):
    for d in ("prompts", "heuristics", "runs", "runs/blobs", "materials", "items", "concepts"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    seed.seed_knowledge_layer(root=tmp_path)
    disc = Concept(id=store.concept_id("Discounting"), subject="finance", name="Discounting")
    store.save_concepts("finance", [disc], root=tmp_path)
    return disc


def test_web_harvest_persists_items_with_web_provenance(tmp_path, fake_client):
    disc = _setup(tmp_path)
    client = fake_client(outputs=[ASSESS_HIGH, WEB_ITEMS])
    result = websearch.web_harvest("finance", root=tmp_path, client=client)

    assert result["items"] == 1
    assert result["standardization"] == "high"
    assert result["searches"] == 3  # high -> 3 searches

    bank = store.load_items("finance", root=tmp_path)
    assert len(bank) == 1
    item = bank[0]
    assert item.provenance.origin is ProvenanceOrigin.retrieved
    assert item.provenance.source.kind is RefKind.web
    assert item.provenance.source.ref == "https://example.com/q1"
    assert disc.id in item.concept_ids  # tagged back to the subject's concept


def test_breadth_scales_with_standardization(tmp_path, fake_client):
    _setup(tmp_path)
    client = fake_client(outputs=[ASSESS_LOW, WEB_ITEMS])
    result = websearch.web_harvest("finance", root=tmp_path, client=client)
    assert result["searches"] == 1  # low -> 1 search


def test_web_search_tool_is_passed_to_harvest_call(tmp_path, fake_client):
    _setup(tmp_path)
    client = fake_client(outputs=[ASSESS_HIGH, WEB_ITEMS])
    websearch.web_harvest("finance", root=tmp_path, client=client)
    # the second create() call (harvest_web) carries the server tool
    harvest_call = client.messages.calls[1]
    tools = harvest_call.get("tools")
    assert tools and tools[0]["type"] == "web_search_20260209"
    assert tools[0]["max_uses"] == 3
    # the standardization call carries no tools
    assert not client.messages.calls[0].get("tools")


class _PausingMessages:
    """First harvest response pauses (server tool), then completes."""

    def __init__(self, assess, final):
        self._assess = assess
        self._final = final
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if "tools" not in kwargs:  # assess_standardization
            return SimpleNamespace(
                content=[SimpleNamespace(text=self._assess)], stop_reason="end_turn"
            )
        if len([c for c in self.calls if "tools" in c]) == 1:  # first harvest turn: pause
            return SimpleNamespace(
                content=[SimpleNamespace(text="", type="server_tool_use")],
                stop_reason="pause_turn",
            )
        return SimpleNamespace(content=[SimpleNamespace(text=self._final)], stop_reason="end_turn")


def test_pause_turn_continuation_completes(tmp_path):
    _setup(tmp_path)
    client = SimpleNamespace(messages=_PausingMessages(ASSESS_HIGH, WEB_ITEMS))
    result = websearch.web_harvest("finance", root=tmp_path, client=client)
    assert result["items"] == 1
    # one assess + two harvest turns (pause then continue)
    assert len(client.messages.calls) == 3


def test_offline_mode_runs_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDYBUDDY_OFFLINE", "1")
    _setup(tmp_path)
    result = websearch.web_harvest("finance", root=tmp_path)  # default offline client
    assert result["items"] >= 1
    bank = store.load_items("finance", root=tmp_path)
    assert all(i.provenance.source.kind is RefKind.web for i in bank)
