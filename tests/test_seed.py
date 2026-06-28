"""Tests for the registry + heuristics seed."""

import json

import jsonschema
import pytest

from studybuddy import registry, seed, wrapper
from studybuddy.models import DEFAULT_GAP_TYPES, HeuristicsConfig, PromptTask


def _seed(tmp_path):
    for d in ("prompts", "heuristics", "runs", "runs/blobs"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return seed.seed_knowledge_layer(root=tmp_path)


def test_seeds_all_nine_templates(tmp_path):
    _seed(tmp_path)
    for task in PromptTask:
        tmpl = registry.load_template(task, root=tmp_path)
        assert tmpl.task is task
        assert tmpl.version == "v1"
        assert registry.current_version(task, root=tmp_path) == "v1"
        # Output contract must be a non-trivial JSON Schema and itself be valid.
        assert tmpl.output_schema.get("type") == "object"
        jsonschema.Draft202012Validator.check_schema(tmpl.output_schema)
        jsonschema.Draft202012Validator.check_schema(tmpl.input_schema)


def test_exactly_nine_tasks_registered(tmp_path):
    _seed(tmp_path)
    task_dirs = sorted(p.name for p in (tmp_path / "prompts").iterdir() if p.is_dir())
    assert task_dirs == sorted(t.value for t in PromptTask)


def test_heuristics_config_valid(tmp_path):
    _seed(tmp_path)
    cfg = HeuristicsConfig.model_validate_json(
        (tmp_path / "heuristics" / "config.json").read_text()
    )
    assert cfg.version == "v1"
    assert cfg.gap_types == list(DEFAULT_GAP_TYPES)  # B2
    assert cfg.sampling_rules["diagnostic_size"] == 20  # FR-C1
    assert cfg.stopping_rule["gap_confidence_target"] == 0.8


def test_seed_is_idempotent_and_non_clobbering(tmp_path):
    first = _seed(tmp_path)
    assert first["written"] and not first["skipped"]

    # Hand-edit a template, then re-seed: the edit must survive.
    edited = tmp_path / "prompts" / "extract_structure" / "v1.json"
    data = json.loads(edited.read_text())
    data["body"] = "HAND EDITED"
    edited.write_text(json.dumps(data))

    second = seed.seed_knowledge_layer(root=tmp_path)
    assert not second["written"]  # nothing rewritten
    assert second["skipped"]
    assert json.loads(edited.read_text())["body"] == "HAND EDITED"


def test_force_regenerates(tmp_path):
    _seed(tmp_path)
    edited = tmp_path / "prompts" / "extract_structure" / "v1.json"
    edited.write_text('{"body": "HAND EDITED"}')
    seed.seed_knowledge_layer(root=tmp_path, force=True)
    assert json.loads(edited.read_text())["body"] != "HAND EDITED"


def test_wrapper_runs_against_seeded_template(tmp_path, fake_client):
    """End-to-end through the real seeded grade_response schema (mocked client)."""
    _seed(tmp_path)
    valid_output = '{"score": 0.8, "reasoning": "mostly right", "missed_facets": ["units"]}'
    client = fake_client(outputs=[valid_output])
    result = wrapper.run_call(
        "grade_response",
        {"response": "answer", "grading_spec": {"max_score": 1}},
        root=tmp_path,
        client=client,
    )
    assert result["score"] == 0.8

    # And a schema-violating output is rejected after the retry.
    bad = fake_client(outputs=['{"score": "high"}', '{"score": "still bad"}'])
    with pytest.raises(wrapper.OutputValidationError):
        wrapper.run_call(
            "grade_response",
            {"response": "answer", "grading_spec": {}},
            root=tmp_path,
            client=bad,
        )
