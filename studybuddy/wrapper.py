"""The single validated Claude-call wrapper — the most-reused piece of the system.

Every Claude call in the pipeline goes through ``run_call``. It is the defended boundary
between deterministic code (which decides *what* to ask) and Claude (which decides
*meaning*). The wrapper itself does exactly one mechanical job per call:

    versioned template + structured input
      -> assemble prompt -> call the API
      -> parse + validate output JSON against the call's output_schema
      -> ONE retry on malformed output (decision A7)
      -> append a RunLogEntry every time (decision A4)
      -> return the validated object, or raise on final failure.

It never decides what to ask or how much — that is the orchestration layer's job.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import jsonschema

from . import ids
from .models import Disposition, PromptTask, PromptTemplate, RunLogEntry, ValidationStatus
from .registry import load_template
from .runlog import RunLog

# One retry on malformed output (decision A7): one initial attempt + one retry.
MAX_RETRIES = 1
# Harvesting/plan calls can emit many items; 4096 truncates a full exam. 16000 is the
# recommended non-streaming ceiling (streaming would be needed above that).
DEFAULT_MAX_TOKENS = 16000


def _default_model() -> str:
    return os.environ.get("STUDYBUDDY_MODEL", "claude-opus-4-8")


class ClaudeCallError(Exception):
    """The API call failed (transport/auth) and could not produce any output."""


class InputValidationError(ClaudeCallError):
    """The structured input did not conform to the call's input_schema (caught before spend)."""


class OutputValidationError(ClaudeCallError):
    """Claude's output was not valid JSON or failed schema validation after the retry."""


# --------------------------------------------------------------------------------------
# Prompt assembly
# --------------------------------------------------------------------------------------


def _system_prompt(template: PromptTemplate) -> str:
    return (
        f"You are a scoped component of the StudyBuddy pipeline performing the "
        f"'{template.task.value}' job. Do only this job.\n\n"
        "Return STRICT JSON only: a single JSON value that conforms EXACTLY to the JSON "
        "Schema below. No prose, no explanation, no markdown, no code fences.\n\n"
        "OUTPUT JSON SCHEMA:\n" + json.dumps(template.output_schema)
    )


def _user_content(template: PromptTemplate, structured_input: Any) -> str:
    parts = [template.body.strip()]
    for ex in template.examples:
        parts.append(
            "EXAMPLE INPUT:\n"
            + json.dumps(ex.input, ensure_ascii=False)
            + "\nEXAMPLE OUTPUT:\n"
            + json.dumps(ex.output, ensure_ascii=False)
        )
    parts.append("INPUT:\n" + json.dumps(structured_input, ensure_ascii=False, default=str))
    return "\n\n".join(parts)


def _text_of(response: Any) -> str:
    """Concatenate the text blocks of an Anthropic Messages response."""
    parts = []
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if text is None and isinstance(block, dict):
            text = block.get("text")
        if text:
            parts.append(text)
    return "".join(parts)


def _correction(prior_error: Exception | None) -> str:
    return (
        f"That response was not valid: {prior_error}. "
        "Return ONLY a single JSON value conforming to the schema — no prose, no code fences."
    )


_MAX_PAUSE_TURNS = 4  # server-tool (e.g. web_search) continuation cap


def _create(client, model, max_tokens, system, messages, tools):
    kwargs: dict[str, Any] = dict(model=model, max_tokens=max_tokens, system=system, messages=messages)
    if tools:
        kwargs["tools"] = tools
    return client.messages.create(**kwargs)


def _call_api(
    client: Any,
    model: str,
    max_tokens: int,
    template: PromptTemplate,
    structured_input: Any,
    prior_raw: str | None,
    prior_error: Exception | None,
    tools: list | None = None,
) -> str:
    user = _user_content(template, structured_input)
    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
    if prior_error is not None:
        # This is a retry. Show Claude its rejected output only if it is non-empty — the API
        # rejects empty/whitespace assistant content — otherwise fold the correction into the
        # single user turn so we never send an invalid empty assistant message.
        if prior_raw is not None and prior_raw.strip():
            messages.append({"role": "assistant", "content": prior_raw})
            messages.append({"role": "user", "content": _correction(prior_error)})
        else:
            messages = [{"role": "user", "content": user + "\n\n" + _correction(prior_error)}]
    system = _system_prompt(template)
    response = _create(client, model, max_tokens, system, messages, tools)
    # Server tools (web_search) may pause when they hit their iteration limit; re-send the
    # assistant turn to continue until the model finishes (bounded).
    pauses = 0
    while getattr(response, "stop_reason", None) == "pause_turn" and pauses < _MAX_PAUSE_TURNS:
        pauses += 1
        messages = messages + [{"role": "assistant", "content": response.content}]
        response = _create(client, model, max_tokens, system, messages, tools)
    return _text_of(response)


# --------------------------------------------------------------------------------------
# Output parsing + validation
# --------------------------------------------------------------------------------------

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _matching_close(text: str, start: int, open_ch: str, close_ch: str) -> int | None:
    """Index of the bracket that closes the one at ``start``, ignoring brackets in strings."""
    depth = 0
    in_str = False
    escape = False
    for j in range(start, len(text)):
        c = text[j]
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return j
    return None


def _iter_json_spans(text: str):
    """Yield each balanced {...} / [...] span in order, skipping brackets inside strings."""
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in "{[":
            end = _matching_close(text, i, ch, "}" if ch == "{" else "]")
            if end is not None:
                yield text[i : end + 1]
                i = end + 1
                continue
        i += 1


def _extract_json(raw: str) -> Any:
    """Tolerantly extract a JSON value from raw model text.

    Tries, in order: the whole string, then each code-fenced block, then each balanced
    bracket span. The model is told to emit bare JSON, but real outputs sometimes add a
    fence or surrounding prose, so we try every candidate rather than commit to the first.
    """
    raw = raw.strip()
    if not raw:
        raise json.JSONDecodeError("empty output", "", 0)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    for match in _FENCE.finditer(raw):
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            continue
    for span in _iter_json_spans(raw):
        try:
            return json.loads(span)
        except json.JSONDecodeError:
            continue
    raise json.JSONDecodeError("no JSON value found in output", raw, 0)


def _parse_and_validate(raw: str, output_schema: dict[str, Any]) -> Any:
    try:
        data = _extract_json(raw)
    except json.JSONDecodeError as e:
        raise OutputValidationError(f"output was not valid JSON: {e}") from e
    try:
        jsonschema.validate(data, output_schema)
    except jsonschema.ValidationError as e:
        raise OutputValidationError(f"output failed schema validation: {e.message}") from e
    return data


# --------------------------------------------------------------------------------------
# The wrapper
# --------------------------------------------------------------------------------------


def _make_entry(
    run_id: str,
    phase: str,
    template: PromptTemplate,
    input_ref: str,
    raw_output_ref: str | None,
    status: ValidationStatus,
    disposition: Disposition,
) -> RunLogEntry:
    return RunLogEntry(
        id=run_id,
        phase=phase,
        template_id=template.id,
        template_version=template.version,
        input_ref=input_ref,
        raw_output_ref=raw_output_ref,
        validation_status=status,
        disposition=disposition,
        ts=ids.utcnow(),
    )


def run_call(
    task: PromptTask | str,
    structured_input: Any,
    *,
    version: str = "current",
    root: str | Path | None = None,
    client: Any | None = None,
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    phase: str | None = None,
    tools: list | None = None,
) -> Any:
    """Run one scoped Claude call and return its validated JSON output.

    Appends exactly one RunLogEntry on every path (success, validation failure, or API
    error). Raises OutputValidationError if the output is still invalid after the retry,
    or ClaudeCallError if the API call itself fails.
    """
    template = load_template(task, version, root=root)
    runlog = RunLog(root)
    if client is None:
        client = _default_client()
    model = model or _default_model()
    phase = phase or template.task.value

    # Validate the orchestrator's structured input against the call's input_schema before any
    # API spend. Input is owned by deterministic code, so a failure is a hard error with no
    # retry (decision A1): fail fast, do not call Claude, do not write a run-log entry.
    try:
        jsonschema.validate(structured_input, template.input_schema)
    except jsonschema.ValidationError as e:
        raise InputValidationError(
            f"input to {phase} failed its input_schema: {e.message}"
        ) from e

    run_id = ids.ulid_id("run")
    input_ref = runlog.write_blob(run_id, "in", structured_input)

    raw: str | None = None
    validated: Any = None
    val_error: Exception | None = None

    try:
        for attempt in range(MAX_RETRIES + 1):
            raw = _call_api(
                client, model, max_tokens, template, structured_input, raw, val_error, tools
            )
            try:
                validated = _parse_and_validate(raw, template.output_schema)
                val_error = None
                break
            except OutputValidationError as e:
                val_error = e
    except Exception as api_err:  # API/transport failure: log (keeping any prior output), raise.
        raw_output_ref = None
        if raw is not None:  # a malformed earlier attempt still produced output worth keeping
            try:
                raw_output_ref = runlog.write_blob(run_id, "out", raw)
            except Exception:
                raw_output_ref = None  # never let a blob-write mask the original API error
        runlog.append(
            _make_entry(
                run_id, phase, template, input_ref, raw_output_ref,
                ValidationStatus.malformed, Disposition.rejected,
            )
        )
        raise ClaudeCallError(f"Claude API call failed for {phase}: {api_err}") from api_err

    raw_output_ref = runlog.write_blob(run_id, "out", raw) if raw is not None else None
    status = ValidationStatus.valid if validated is not None else ValidationStatus.malformed
    disposition = Disposition.accepted if validated is not None else Disposition.rejected
    runlog.append(
        _make_entry(run_id, phase, template, input_ref, raw_output_ref, status, disposition)
    )

    if validated is None:
        raise OutputValidationError(
            f"{phase} returned invalid output after {MAX_RETRIES + 1} attempts: {val_error}"
        )
    return validated


def _default_client() -> Any:
    # Offline test mode: no network, no API key. See studybuddy/offline.py.
    if os.environ.get("STUDYBUDDY_OFFLINE"):
        from .offline import OfflineClient

        return OfflineClient()
    import anthropic

    return anthropic.Anthropic()
