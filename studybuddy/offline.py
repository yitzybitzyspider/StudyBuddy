"""Offline mode: a fake Claude client for testing the pipeline without a key.

Set ``STUDYBUDDY_OFFLINE=1`` and every Claude call returns a canned, schema-valid response
instead of hitting the API. This exercises the full deterministic pipeline (ingest → intake
→ compose → administer → diagnose → plan) end to end with **no network and no API key**, so
you can smoke-test the system safely. It is a testing aid, not part of the product — real
runs use the validated wrapper against Claude.

The canned outputs are anchored on a small, coherent corporate-finance example so the
produced study plan reads sensibly.
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace
from typing import Any

_TASK_RE = re.compile(r"performing the '([a-z_]+)' job")

# Canned, schema-valid outputs per Claude call. Anchored on one finance example.
_CANNED: dict[str, dict] = {
    "extract_structure": {
        "concepts": [
            {"name": "Time Value of Money", "parent": None, "difficulty_prior": 2},
            {"name": "Discounting", "parent": "Time Value of Money", "difficulty_prior": 3},
            {"name": "Net Present Value", "parent": "Discounting", "difficulty_prior": 4},
            {"name": "Internal Rate of Return", "parent": "Net Present Value", "difficulty_prior": 4},
        ]
    },
    "harvest_items": {
        "items": [
            {
                "stem": "A project costs $1,000 today and returns $1,200 in one year. "
                "At a 10% discount rate, what is its NPV?",
                "format": "numeric",
                "answer_key": "90.91",
                "concept_names": ["Net Present Value"],
                "rationale": "NPV = -1000 + 1200/1.1 = 90.91.",
            },
            {
                "stem": "Which statement about the internal rate of return (IRR) is true?",
                "format": "mc",
                "options": [
                    "It is the discount rate that makes NPV zero",
                    "It is always greater than the discount rate",
                    "It ignores the time value of money",
                    "It equals the payback period",
                ],
                "answer_key": "It is the discount rate that makes NPV zero",
                "concept_names": ["Internal Rate of Return"],
            },
            {
                "stem": "In one sentence, explain the time value of money.",
                "format": "short",
                "answer_key": "A dollar today is worth more than a dollar in the future "
                "because it can be invested to earn a return.",
                "concept_names": ["Time Value of Money"],
            },
        ]
    },
    "build_dependency_map": {
        "edges": [
            {"from_concept": "Discounting", "to_concept": "Time Value of Money",
             "relation": "depends_on", "confidence": 0.8},
            {"from_concept": "Net Present Value", "to_concept": "Discounting",
             "relation": "depends_on", "confidence": 0.85},
        ]
    },
    "adapt_item": {
        "stem": "A project costs $2,000 today and returns $2,500 in one year. "
        "At a 12% discount rate, what is its NPV?",
        "format": "numeric",
        "answer_key": "232.14",
        "concept_names": ["Net Present Value"],
        "rationale": "NPV = -2000 + 2500/1.12 = 232.14.",
    },
    "generate_item": {
        "stem": "Discount $500 received in 2 years at 8% per year. What is its present value?",
        "format": "numeric",
        "answer_key": "428.67",
        "concept_names": ["Discounting"],
        "rationale": "PV = 500 / 1.08^2 = 428.67.",
    },
    "assess_standardization": {
        "standardization": "high",
        "query_terms": [
            "net present value practice problem",
            "discounted cash flow exam question",
            "IRR vs NPV multiple choice",
        ],
        "rationale": "Corporate-finance valuation is highly standardized; canonical NPV/IRR "
        "questions are abundant online.",
    },
    "harvest_web": {
        "items": [
            {
                "stem": "An investment pays $1,100 one year from now. At an 8% discount rate, "
                "what is its present value?",
                "format": "numeric",
                "answer_key": "1018.52",
                "concept_names": ["Discounting"],
                "rationale": "PV = 1100 / 1.08 = 1018.52.",
            },
            {
                "stem": "A project has NPV of $0 at a 14% discount rate. What does 14% represent?",
                "format": "mc",
                "options": [
                    "The project's internal rate of return",
                    "The project's payback period",
                    "The risk-free rate",
                    "The project's accounting rate of return",
                ],
                "answer_key": "The project's internal rate of return",
                "concept_names": ["Internal Rate of Return"],
            },
        ]
    },
    "verify_item": {
        "tests_intended_concept": True,
        "answer_key_correct": True,
        "unambiguous": True,
        "verdict": "pass",
    },
    "grade_response": {
        "score": 0.7,
        "reasoning": "Captures the core idea but omits that the value comes from the "
        "opportunity to earn a return.",
        "missed_facets": ["opportunity cost"],
    },
    "interpret_gaps": {
        "gaps": [
            {"concept": "Discounting", "gap_type": "foundational", "severity": 0.8,
             "confidence": 0.8, "rationale": "Shaky discounting fundamentals; errors propagate."},
            {"concept": "Net Present Value", "gap_type": "depth", "severity": 0.6,
             "confidence": 0.7, "rationale": "Sets up NPV but slips on the discounting arithmetic."},
        ]
    },
    "compose_plan": {
        "overview": "Rebuild discounting fundamentals first, then layer NPV and IRR on top.",
        "topics": [
            {
                "concept": "Discounting",
                "summary": "Drill present-value arithmetic until it is automatic: PV = FV / (1+r)^n.",
                "rationale": "Foundational gap; everything downstream depends on it.",
                "item_sequence": [],
                "source_links": [],
            },
            {
                "concept": "Net Present Value",
                "summary": "Practice full NPV setups with several cash flows, then the accept/reject rule.",
                "rationale": "Depth gap that resolves once discounting is solid.",
                "item_sequence": [],
                "source_links": [],
            },
        ],
    },
}


class _Messages:
    def create(self, *, system: str = "", messages: Any = None, **kwargs: Any) -> Any:
        match = _TASK_RE.search(system or "")
        task = match.group(1) if match else None
        payload = _CANNED.get(task, {})
        return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(payload))])


class OfflineClient:
    """Drop-in stand-in for anthropic.Anthropic() that never touches the network."""

    def __init__(self) -> None:
        self.messages = _Messages()
