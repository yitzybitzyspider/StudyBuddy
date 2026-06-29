"""Offline-mode tests: canned outputs are schema-valid and routing works."""

import json

import jsonschema

from studybuddy import registry, seed, wrapper
from studybuddy.models import PromptTask
from studybuddy.offline import OfflineClient
from studybuddy.wrapper import _system_prompt


def _seed(tmp_path):
    for d in ("prompts", "heuristics", "runs", "runs/blobs"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    seed.seed_knowledge_layer(root=tmp_path)


def test_every_canned_output_matches_its_schema(tmp_path):
    _seed(tmp_path)
    client = OfflineClient()
    for task in PromptTask:
        tmpl = registry.load_template(task, root=tmp_path)
        resp = client.messages.create(system=_system_prompt(tmpl), messages=[])
        output = json.loads(resp.content[0].text)
        jsonschema.validate(output, tmpl.output_schema)  # raises if invalid


def test_env_var_routes_to_offline_client(tmp_path, monkeypatch):
    _seed(tmp_path)
    monkeypatch.setenv("STUDYBUDDY_OFFLINE", "1")
    # client=None -> wrapper resolves the offline client from the env var
    result = wrapper.run_call(
        "extract_structure",
        {"material_text": "...", "subject": "finance"},
        root=tmp_path,
        client=None,
    )
    assert any(c["name"] == "Net Present Value" for c in result["concepts"])
