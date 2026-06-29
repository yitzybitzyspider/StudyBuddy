"""Bootstrap the prompt registry and heuristics config (Phase 0, Loop 4).

This writes the v1 of every Claude-call template and the v1 heuristics config into the
knowledge layer. It is **idempotent and non-clobbering**: a file that already exists is
left untouched, so hand edits and later versions are never overwritten. Pass ``force=True``
only to regenerate from scratch.

The output JSON files are the product (the prompt registry and heuristics live under git).
This module is just the reproducible way to lay down their v1, so the system can be rebuilt
from a known-good baseline. Bodies are intentionally concise Phase-0 stubs; prompt
engineering deepens as each stage is built (Phase 1+). Every heuristic number is a
calibration placeholder, moved later only via ratified promotion (philosophy §8).
"""

from __future__ import annotations

import json
from pathlib import Path

from . import paths
from .models import (
    DEFAULT_GAP_TYPES,
    HeuristicsConfig,
    PromptTask,
    PromptTemplate,
)

# Shared JSON-Schema fragments ---------------------------------------------------------

_ITEM_FORMATS = ["mc", "numeric", "short", "essay", "application"]

REFERENCE_SCHEMA = {
    "type": "object",
    "required": ["kind", "ref"],
    "properties": {
        "kind": {"enum": ["material", "web", "item", "run", "prompt", "concept"]},
        "ref": {"type": "string"},
        "locator": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}

# The item shape Claude returns (harvest/adapt/generate). Deterministic code stamps id,
# provenance, and calibration afterward, so they are not part of the model's output.
ITEM_OUT_SCHEMA = {
    "type": "object",
    "required": ["stem", "format", "answer_key", "concept_names"],
    "properties": {
        "stem": {"type": "string"},
        "format": {"enum": _ITEM_FORMATS},
        "options": {"type": "array", "items": {"type": "string"}},
        "answer_key": {},  # any type, by format
        "rationale": {"type": "string"},
        "concept_names": {"type": "array", "items": {"type": "string"}},
        "source": REFERENCE_SCHEMA,
        "grading_spec": {"type": "object"},
    },
    "additionalProperties": False,
}


def _templates() -> list[PromptTemplate]:
    """The nine scoped Claude-call templates (spec §5), at version v1."""
    return [
        PromptTemplate(
            id=PromptTask.extract_structure.value,
            task=PromptTask.extract_structure,
            version="v1",
            input_schema={
                "type": "object",
                "required": ["material_text", "subject"],
                "properties": {
                    "material_text": {"type": "string"},
                    "subject": {"type": "string"},
                    "material_id": {"type": ["string", "null"]},
                },
                "additionalProperties": True,
            },
            output_schema={
                "type": "object",
                "required": ["concepts"],
                "properties": {
                    "concepts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["name"],
                            "properties": {
                                "name": {"type": "string"},
                                "parent": {"type": ["string", "null"]},
                                "source_refs": {"type": "array", "items": REFERENCE_SCHEMA},
                                "difficulty_prior": {"type": ["number", "null"]},
                            },
                            "additionalProperties": False,
                        },
                    }
                },
                "additionalProperties": False,
            },
            body=(
                "Read the course/exam material and extract the concepts it covers. Return one "
                "entry per concept with its name and, where the material makes it clear, its "
                "parent concept and a source pointer (page/section). Cover the material as taught; "
                "do not invent topics it does not contain."
            ),
        ),
        PromptTemplate(
            id=PromptTask.harvest_items.value,
            task=PromptTask.harvest_items,
            version="v1",
            input_schema={
                "type": "object",
                "required": ["material_text", "subject"],
                "properties": {
                    "material_text": {"type": "string"},
                    "subject": {"type": "string"},
                    "concept_names": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": True,
            },
            output_schema={
                "type": "object",
                "required": ["items"],
                "properties": {"items": {"type": "array", "items": ITEM_OUT_SCHEMA}},
                "additionalProperties": False,
            },
            body=(
                "Retrieval-first: extract the REAL questions and answers already present in this "
                "material (worked examples, problem sets, past-exam questions), each tagged to the "
                "concept(s) it tests, with its answer key. Do not invent new questions here — only "
                "report what the material actually contains, with a source pointer."
            ),
        ),
        PromptTemplate(
            id=PromptTask.build_dependency_map.value,
            task=PromptTask.build_dependency_map,
            version="v1",
            input_schema={
                "type": "object",
                "required": ["concepts"],
                "properties": {
                    "concepts": {"type": "array", "items": {"type": "object"}},
                    "sampled_items": {"type": "array", "items": {"type": "object"}},
                },
                "additionalProperties": True,
            },
            output_schema={
                "type": "object",
                "required": ["edges"],
                "properties": {
                    "edges": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["from_concept", "to_concept", "relation", "confidence"],
                            "properties": {
                                "from_concept": {"type": "string"},
                                "to_concept": {"type": "string"},
                                "relation": {"enum": ["depends_on", "prereq_of"]},
                                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            },
                            "additionalProperties": False,
                        },
                    }
                },
                "additionalProperties": False,
            },
            body=(
                "Given the concepts (and some sample questions for context), identify the "
                "prerequisite structure: which concept must be understood before another. Return "
                "directed edges with a confidence in [0,1]. Only assert an edge you have real "
                "evidence for; lower the confidence when unsure."
            ),
        ),
        PromptTemplate(
            id=PromptTask.adapt_item.value,
            task=PromptTask.adapt_item,
            version="v1",
            input_schema={
                "type": "object",
                "required": ["source_item", "target_concept", "target_format"],
                "properties": {
                    "source_item": {"type": "object"},
                    "target_concept": {"type": "string"},
                    "target_difficulty": {"type": ["number", "null"]},
                    "target_format": {"enum": _ITEM_FORMATS},
                },
                "additionalProperties": True,
            },
            output_schema=ITEM_OUT_SCHEMA,
            body=(
                "Adapt the given real question to the target concept, difficulty, and format — for "
                "example reuse its structure with new numbers or context. Stay as close to the "
                "vetted original as the target allows. Return the adapted item with a correct "
                "answer key."
            ),
        ),
        PromptTemplate(
            id=PromptTask.generate_item.value,
            task=PromptTask.generate_item,
            version="v1",
            input_schema={
                "type": "object",
                "required": ["concept", "format"],
                "properties": {
                    "concept": {"type": "string"},
                    "difficulty": {"type": ["number", "null"]},
                    "format": {"enum": _ITEM_FORMATS},
                    "source_context": {"type": "string"},
                },
                "additionalProperties": True,
            },
            output_schema=ITEM_OUT_SCHEMA,
            body=(
                "Generate a fresh question for the given concept, difficulty, and format, grounded "
                "in the supplied source context. This is the last resort, used only to fill a gap "
                "where no real or adaptable question exists. Return the item with a correct, "
                "unambiguous answer key."
            ),
        ),
        PromptTemplate(
            id=PromptTask.verify_item.value,
            task=PromptTask.verify_item,
            version="v1",
            input_schema={
                "type": "object",
                "required": ["item", "intended_concept"],
                "properties": {
                    "item": {"type": "object"},
                    "intended_concept": {"type": "string"},
                },
                "additionalProperties": True,
            },
            output_schema={
                "type": "object",
                "required": [
                    "tests_intended_concept",
                    "answer_key_correct",
                    "unambiguous",
                    "verdict",
                ],
                "properties": {
                    "tests_intended_concept": {"type": "boolean"},
                    "answer_key_correct": {"type": "boolean"},
                    "unambiguous": {"type": "boolean"},
                    "verdict": {"enum": ["pass", "fail"]},
                    "issues": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
            body=(
                "Verify this adapted/generated item: does it actually test the intended concept, is "
                "the answer key correct, and is the item unambiguous? Answer each judgment, give an "
                "overall pass/fail verdict, and list any issues. Fail if any judgment is false."
            ),
        ),
        PromptTemplate(
            id=PromptTask.grade_response.value,
            task=PromptTask.grade_response,
            version="v1",
            input_schema={
                "type": "object",
                "required": ["response", "grading_spec"],
                "properties": {
                    "response": {"type": "string"},
                    "grading_spec": {"type": "object"},
                    "stem": {"type": ["string", "null"]},
                },
                "additionalProperties": True,
            },
            output_schema={
                "type": "object",
                "required": ["score", "reasoning", "missed_facets"],
                "properties": {
                    # Floor only; the per-rubric ceiling (grading_spec.max_score) is a runtime
                    # value, clamped by the deterministic grading step in Stage 5 (Phase 1).
                    "score": {"type": "number", "minimum": 0},
                    "reasoning": {"type": "string"},
                    "missed_facets": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
            body=(
                "Grade the open-ended response against its grading spec. Return a numeric score, the "
                "reasoning behind it, and the specific concept facets the response missed. Be "
                "concrete about what was and was not demonstrated."
            ),
        ),
        PromptTemplate(
            id=PromptTask.interpret_gaps.value,
            task=PromptTask.interpret_gaps,
            version="v1",
            input_schema={
                "type": "object",
                "required": ["per_concept_rollup"],
                "properties": {
                    "per_concept_rollup": {"type": "object"},
                    "dependency_context": {"type": "object"},
                    "gap_types": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": True,
            },
            output_schema={
                "type": "object",
                "required": ["gaps"],
                "properties": {
                    "gaps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["concept", "gap_type", "confidence"],
                            "properties": {
                                "concept": {"type": "string"},
                                "gap_type": {"type": "string"},
                                "severity": {"type": ["number", "null"]},
                                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                                "rationale": {"type": "string"},
                            },
                            "additionalProperties": False,
                        },
                    }
                },
                "additionalProperties": False,
            },
            body=(
                "Read the per-concept results within the dependency structure and explain WHERE "
                "understanding breaks down, not just where the score dipped. A miss downstream often "
                "points to a missing prerequisite upstream. Return gap hypotheses (one per "
                "concept+gap_type) with a confidence; a concept may have more than one gap type."
            ),
        ),
        PromptTemplate(
            id=PromptTask.compose_plan.value,
            task=PromptTask.compose_plan,
            version="v1",
            input_schema={
                "type": "object",
                "required": ["gap_profile", "item_sequences"],
                "properties": {
                    "gap_profile": {"type": "object"},
                    "item_sequences": {"type": "object"},
                    "constraints": {"type": "object"},
                },
                "additionalProperties": True,
            },
            output_schema={
                "type": "object",
                "required": ["topics"],
                "properties": {
                    "overview": {"type": "string"},
                    "topics": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["concept", "summary"],
                            "properties": {
                                "concept": {"type": "string"},
                                "summary": {"type": "string"},
                                "source_links": {"type": "array", "items": REFERENCE_SCHEMA},
                                "item_sequence": {"type": "array", "items": {"type": "string"}},
                                "rationale": {"type": "string"},
                            },
                            "additionalProperties": False,
                        },
                    },
                },
                "additionalProperties": False,
            },
            body=(
                "Write the human-facing, topic-by-topic study plan over the confirmed gaps. For each "
                "topic give a short summary of what to study and why, the source links, and the "
                "ordered item sequence (foundational → depth → synthesis). The deterministic engine "
                "owns the schedule and time math; write only the content."
            ),
        ),
        PromptTemplate(
            id=PromptTask.assess_standardization.value,
            task=PromptTask.assess_standardization,
            version="v1",
            input_schema={
                "type": "object",
                "required": ["subject"],
                "properties": {
                    "subject": {"type": "string"},
                    "concept_names": {"type": "array", "items": {"type": "string"}},
                    "sample_text": {"type": "string"},
                },
                "additionalProperties": True,
            },
            output_schema={
                "type": "object",
                "required": ["standardization", "query_terms"],
                "properties": {
                    "standardization": {"enum": ["low", "medium", "high"]},
                    "query_terms": {"type": "array", "items": {"type": "string"}},
                    "rationale": {"type": "string"},
                },
                "additionalProperties": False,
            },
            body=(
                "Judge how STANDARDIZED this exam is, from the subject and question style. "
                "high = a public standardized test with lots of practice material online; "
                "low = a professor-specific exam where the best source might be a forum thread. "
                "Return the level plus a few good web search query terms for finding similar real "
                "questions, and a one-line rationale."
            ),
        ),
        PromptTemplate(
            id=PromptTask.harvest_web.value,
            task=PromptTask.harvest_web,
            version="v1",
            input_schema={
                "type": "object",
                "required": ["subject", "query_terms"],
                "properties": {
                    "subject": {"type": "string"},
                    "query_terms": {"type": "array", "items": {"type": "string"}},
                    "concept_names": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": True,
            },
            output_schema={
                "type": "object",
                "required": ["items"],
                "properties": {"items": {"type": "array", "items": ITEM_OUT_SCHEMA}},
                "additionalProperties": False,
            },
            body=(
                "Use web search to find REAL practice/exam questions on these topics, then return "
                "them as items tagged to the concept(s) they test, each with its answer key and a "
                "source pointer (kind 'web', ref = the page URL). Prefer real, vetted questions "
                "(textbook problem sets, past exams, reputable practice sites) over anything you "
                "invent. Only include questions you actually found, with their source."
            ),
        ),
    ]


def _heuristics() -> HeuristicsConfig:
    """The v1 heuristics config. Every number is a calibration placeholder (spec §7)."""
    return HeuristicsConfig(
        version="v1",
        difficulty_scale={
            "kind": "integer",
            "min": 1,
            "max": 5,
            "bands": {"easy": [1, 2], "medium": [3], "hard": [4, 5]},
            "_note": "placeholder; granularity is an open question (spec §7)",
        },
        gap_types=list(DEFAULT_GAP_TYPES),  # B2: gap-type vocabulary as data
        gap_thresholds={
            "foundational": {"easy_band_correct_rate_below": 0.5},
            "depth": {"easy_medium_correct_rate_at_least": 0.8, "hard_correct_rate_below": 0.5},
            "overconfidence": {"harder_correct_while_easier_missed": True, "use_felt_lucky_flag": True},
            "breadth": {"per_concept_correct_rate_spread_above": 0.4},
            "speed": {"flag_blanks": True, "time_spent_below_format_floor": True},
            "_note": "placeholders; tune via ratified promotion (philosophy §8)",
        },
        weighting_coeffs={
            "self_assessment": 0.33,
            "structural_inference": 0.34,
            "difficulty_prior": 0.33,
            "_note": "FR-C2 three-signal blend; start ~equal, calibrate later",
        },
        sampling_rules={
            "diagnostic_size": 20,
            "item_mix": {
                "declared_weakness": 0.4,
                "declared_strength_stress_test": 0.3,
                "hidden_gap_probe": 0.3,
            },
            "retrieval_order": ["retrieve", "adapt", "generate", "verify"],
            "adaptive_batch_size": 4,
            "_note": "diagnostic_size ~20 is spec-named (FR-C1); proportions/batch size are placeholders",
        },
        stopping_rule={
            "gap_confidence_target": 0.8,
            "max_adaptive_batches": 4,
            "_note": "placeholder stopping rule; confidence target is an open question (spec §7)",
        },
        calibration={
            "confidence_k": 4,
            "_note": "Track A: confidence saturates with times_seen via k. discrimination is "
            "deferred (cross-respondent stat; not computable for one user, philosophy §9).",
        },
        dependency={
            "edge_confidence_min": 0.6,
            "_note": "Stage 2: a fresh edge below this confidence is held for the Phase-5 "
            "proposals inbox rather than written into the concept model. Confidence on "
            "existing edges accrues (noisy-OR) toward 1 with repeated evidence.",
        },
    )


def seed_knowledge_layer(
    root: str | Path | None = None, *, force: bool = False
) -> dict[str, list[str]]:
    """Write v1 templates + heuristics config. Non-clobbering unless force=True.

    Returns a summary of what was written vs skipped.
    """
    base = paths.knowledge_root(root)
    written: list[str] = []
    skipped: list[str] = []

    for template in _templates():
        task_dir = base / "prompts" / template.task.value
        task_dir.mkdir(parents=True, exist_ok=True)
        version_file = task_dir / f"{template.version}.json"
        if version_file.exists() and not force:
            skipped.append(str(version_file.relative_to(base)))
        else:
            version_file.write_text(
                json.dumps(template.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            written.append(str(version_file.relative_to(base)))

        index_file = task_dir / "index.json"
        if index_file.exists() and not force:
            skipped.append(str(index_file.relative_to(base)))
        else:
            index_file.write_text(
                json.dumps({"task": template.task.value, "current": template.version}, indent=2, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )
            written.append(str(index_file.relative_to(base)))

    heuristics_file = base / "heuristics" / "config.json"
    heuristics_file.parent.mkdir(parents=True, exist_ok=True)
    if heuristics_file.exists() and not force:
        skipped.append(str(heuristics_file.relative_to(base)))
    else:
        heuristics_file.write_text(
            json.dumps(_heuristics().model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        written.append(str(heuristics_file.relative_to(base)))

    return {"written": written, "skipped": skipped}
