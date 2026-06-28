"""Tests for the validated Claude-call wrapper, registry, and run log.

All Claude I/O is mocked. These cover the contract: validate output against the call's
schema, retry exactly once on malformed output, and append a RunLogEntry on every path.
"""

import json

import pytest

from studybuddy import registry, wrapper
from studybuddy.models import Disposition, ValidationStatus
from studybuddy.runlog import RunLog


# --- registry -------------------------------------------------------------------------


def test_registry_resolves_current_version(kroot):
    tmpl = registry.load_template("extract_structure", root=kroot)
    assert tmpl.id == "extract_structure"
    assert tmpl.version == "v1"
    assert registry.current_version("extract_structure", root=kroot) == "v1"


def test_registry_missing_task_raises(kroot):
    with pytest.raises(registry.TemplateNotFound):
        registry.load_template("harvest_items", root=kroot)


def test_registry_missing_version_raises(kroot):
    with pytest.raises(registry.TemplateNotFound):
        registry.load_template("extract_structure", version="v99", root=kroot)


# --- happy path -----------------------------------------------------------------------


def test_happy_path_returns_validated_and_logs(kroot, fake_client):
    client = fake_client(outputs=['{"topics": ["a", "b"]}'])
    result = wrapper.run_call("extract_structure", {"material": "..."}, root=kroot, client=client)

    assert result == {"topics": ["a", "b"]}
    assert client.call_count == 1

    entries = RunLog(kroot).read_all()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.validation_status is ValidationStatus.valid
    assert entry.disposition is Disposition.accepted
    assert entry.template_id == "extract_structure"
    assert entry.template_version == "v1"
    assert entry.phase == "extract_structure"


def test_blobs_written_and_referenced(kroot, fake_client):
    client = fake_client(outputs=['{"topics": []}'])
    wrapper.run_call("extract_structure", {"material": "src text"}, root=kroot, client=client)

    entry = RunLog(kroot).read_all()[0]
    in_path = kroot / entry.input_ref
    out_path = kroot / entry.raw_output_ref
    assert in_path.exists() and out_path.exists()
    assert json.loads(in_path.read_text()) == {"material": "src text"}
    assert "topics" in out_path.read_text()


def test_strips_code_fences(kroot, fake_client):
    client = fake_client(outputs=['```json\n{"topics": ["x"]}\n```'])
    result = wrapper.run_call("extract_structure", {}, root=kroot, client=client)
    assert result == {"topics": ["x"]}
    assert client.call_count == 1  # not a retry; fence-stripping handled it


def test_extracts_json_embedded_in_prose(kroot, fake_client):
    client = fake_client(outputs=['Sure! Here it is: {"topics": ["y"]} Hope that helps.'])
    result = wrapper.run_call("extract_structure", {}, root=kroot, client=client)
    assert result == {"topics": ["y"]}


# --- retry behaviour (decision A7) ----------------------------------------------------


def test_retries_once_on_non_json_then_succeeds(kroot, fake_client):
    client = fake_client(outputs=["not json at all", '{"topics": []}'])
    result = wrapper.run_call("extract_structure", {}, root=kroot, client=client)

    assert result == {"topics": []}
    assert client.call_count == 2  # one retry
    entry = RunLog(kroot).read_all()[0]
    assert entry.validation_status is ValidationStatus.valid
    assert entry.disposition is Disposition.accepted


def test_retries_once_on_schema_violation_then_succeeds(kroot, fake_client):
    # First output is valid JSON but missing the required 'topics' key.
    client = fake_client(outputs=['{"wrong": 1}', '{"topics": ["ok"]}'])
    result = wrapper.run_call("extract_structure", {}, root=kroot, client=client)
    assert result == {"topics": ["ok"]}
    assert client.call_count == 2


def test_gives_up_after_one_retry_and_logs_rejected(kroot, fake_client):
    client = fake_client(outputs=["nope", "still nope"])
    with pytest.raises(wrapper.OutputValidationError):
        wrapper.run_call("extract_structure", {}, root=kroot, client=client)

    assert client.call_count == 2  # initial + one retry, then give up
    entries = RunLog(kroot).read_all()
    assert len(entries) == 1  # still exactly one entry on the failure path
    assert entries[0].validation_status is ValidationStatus.malformed
    assert entries[0].disposition is Disposition.rejected
    assert entries[0].raw_output_ref is not None  # the last bad output was kept


def test_retry_shows_prior_output_to_model(kroot, fake_client):
    client = fake_client(outputs=["bad", '{"topics": []}'])
    wrapper.run_call("extract_structure", {}, root=kroot, client=client)
    # Second API call must include the rejected assistant turn + a correction user turn.
    second_call_messages = client.messages.calls[1]["messages"]
    roles = [m["role"] for m in second_call_messages]
    assert roles == ["user", "assistant", "user"]
    assert second_call_messages[1]["content"] == "bad"


# --- API failure path -----------------------------------------------------------------


def test_api_error_is_logged_and_raised(kroot, fake_client):
    client = fake_client(fail_with=RuntimeError("boom"))
    with pytest.raises(wrapper.ClaudeCallError):
        wrapper.run_call("extract_structure", {}, root=kroot, client=client)

    entries = RunLog(kroot).read_all()
    assert len(entries) == 1
    assert entries[0].disposition is Disposition.rejected
    assert entries[0].raw_output_ref is None  # no output was produced


def test_phase_override_recorded(kroot, fake_client):
    client = fake_client(outputs=['{"topics": []}'])
    wrapper.run_call("extract_structure", {}, root=kroot, client=client, phase="Stage 1")
    assert RunLog(kroot).read_all()[0].phase == "Stage 1"


# --- review regressions ---------------------------------------------------------------


def test_empty_output_retries_cleanly_without_empty_assistant_turn(kroot, fake_client):
    """Empty first output must not thread an (API-rejected) empty assistant message."""
    client = fake_client(outputs=["", '{"topics": []}'])
    result = wrapper.run_call("extract_structure", {}, root=kroot, client=client)
    assert result == {"topics": []}
    assert client.call_count == 2
    # The retry folds the correction into a single user turn (no empty assistant turn).
    retry_messages = client.messages.calls[1]["messages"]
    assert [m["role"] for m in retry_messages] == ["user"]
    assert "not valid" in retry_messages[0]["content"]


def test_empty_output_twice_is_validation_error_not_api_error(kroot, fake_client):
    client = fake_client(outputs=["", "   \n  "])
    with pytest.raises(wrapper.OutputValidationError):
        wrapper.run_call("extract_structure", {}, root=kroot, client=client)
    assert RunLog(kroot).read_all()[0].disposition is Disposition.rejected


def test_extracts_second_json_fence_when_first_is_not_json(kroot, fake_client):
    out = '```js\n{ a: 1 }\n```\n```json\n{"topics": ["z"]}\n```'
    client = fake_client(outputs=[out])
    result = wrapper.run_call("extract_structure", {}, root=kroot, client=client)
    assert result == {"topics": ["z"]}
    assert client.call_count == 1  # extracted without burning the retry


def test_extracts_json_past_leading_prose_bracket(kroot, fake_client):
    out = 'I think the set {a, b} is neat. Here is the answer: {"topics": ["p"]}'
    client = fake_client(outputs=[out])
    result = wrapper.run_call("extract_structure", {}, root=kroot, client=client)
    assert result == {"topics": ["p"]}


def test_input_validation_fails_fast_before_any_api_call(kroot, fake_client):
    client = fake_client(outputs=['{"topics": []}'])
    # kroot's template input_schema requires an object; a list violates it.
    with pytest.raises(wrapper.InputValidationError):
        wrapper.run_call("extract_structure", ["not", "an", "object"], root=kroot, client=client)
    assert client.call_count == 0  # never called Claude
    assert RunLog(kroot).read_all() == []  # and wrote no run-log entry


def test_api_error_after_malformed_attempt_preserves_output(kroot):
    from types import SimpleNamespace

    class GarbageThenError:
        def __init__(self):
            self.messages = self
            self.calls = []
            self._n = 0

        def create(self, **kwargs):
            self.calls.append(kwargs)
            self._n += 1
            if self._n == 1:
                return SimpleNamespace(content=[SimpleNamespace(text="garbage not json")])
            raise RuntimeError("network boom")

    client = GarbageThenError()
    with pytest.raises(wrapper.ClaudeCallError):
        wrapper.run_call("extract_structure", {}, root=kroot, client=client)

    entry = RunLog(kroot).read_all()[0]
    assert entry.raw_output_ref is not None  # attempt-1 output was not dropped
    assert "garbage" in (kroot / entry.raw_output_ref).read_text()
