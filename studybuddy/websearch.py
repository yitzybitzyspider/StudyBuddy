"""Phase 2, Loop 15: web-search harvesting via Claude's server-side ``web_search`` tool.

Deterministic driver for pulling additional REAL questions off the web into the item bank.
It is **opt-in** (cost control): the live ``web_search`` tool spends API budget, so it is
never run automatically by ``ingest`` — only by an explicit ``harvest-web`` command or the
UI button.

The flow keeps the clean boundary (CLAUDE.md): deterministic code decides *what* to search
and *how much*, Claude decides *meaning* and produces the items.

    1. read the subject's concepts + a sample of material
    2. ``assess_standardization`` — how standardized is this exam, and what to search for
    3. size the search breadth to that level (low -> 1 search, high -> 3)
    4. ``harvest_web`` with the ``web_search`` server tool -> real questions as items
    5. persist new items with web provenance, tagged to the subject's concepts

Every Claude call still returns strict JSON validated against its schema (the wrapper's
``pause_turn`` continuation loop handles the server tool's iteration pauses).
"""

from __future__ import annotations

import os

from . import ids, store
from .models import (
    GradingSpec,
    Item,
    ItemFormat,
    Provenance,
    ProvenanceOrigin,
    Reference,
    RefKind,
)
from .wrapper import run_call

# Anthropic server-side web-search tool (Opus 4.6+; no beta header).
_WEB_SEARCH_TYPE = "web_search_20260209"

# The web-search tool only runs on a capable model (Opus 4.6+), so this one call can override
# the cheap default (STUDYBUDDY_MODEL) without forcing the whole pipeline onto a pricier model.
# Set STUDYBUDDY_WEBSEARCH_MODEL to pick it; None means inherit the wrapper's default.
_DEFAULT_WEBSEARCH_MODEL = "claude-opus-4-6"


def _websearch_model() -> str | None:
    return os.environ.get("STUDYBUDDY_WEBSEARCH_MODEL") or _DEFAULT_WEBSEARCH_MODEL

# Standardization -> how many web searches the harvest may run. More standardized exams have
# more good public practice material, so a wider search pays off; bespoke exams do not.
_BREADTH = {"low": 1, "medium": 2, "high": 3}

# How much material text to sample into the standardization judgment (keep the call cheap).
_SAMPLE_CHARS = 4000


def _sample_material(subject: str, *, root) -> str:
    """A short slice of the subject's raw material, for the standardization judgment."""
    chunks: list[str] = []
    for material in store.load_materials(subject, root=root):
        if not material.raw_ref:
            continue
        try:
            chunks.append(store.load_material_raw(material.raw_ref, subject=subject, root=root))
        except (OSError, KeyError):
            continue
        if sum(len(c) for c in chunks) >= _SAMPLE_CHARS:
            break
    return "\n\n".join(chunks)[:_SAMPLE_CHARS]


def _item_from_web(it: dict, concept_id_by_name: dict[str, str]) -> Item:
    gs = it.get("grading_spec") or {}
    known = {k: gs[k] for k in ("rubric_text", "max_score", "facets") if k in gs}
    concept_ids = [
        concept_id_by_name.get(n.lower(), store.concept_id(n))
        for n in it.get("concept_names", [])
    ]
    src = it.get("source") or {}
    source = Reference(
        kind=RefKind.web,
        ref=src.get("ref") or "web",
        locator=src.get("locator"),
    )
    return Item(
        id=ids.ulid_id("item"),
        concept_ids=concept_ids,
        format=ItemFormat(it["format"]),
        stem=it["stem"],
        options=it.get("options"),
        answer_key=it["answer_key"],
        rationale=it.get("rationale"),
        provenance=Provenance(origin=ProvenanceOrigin.retrieved, source=source),
        grading_spec=GradingSpec(**known),
    )


def web_harvest(subject: str, *, root=None, client=None) -> dict:
    """Pull additional real questions from the web into ``subject``'s item bank.

    Opt-in and cost-bearing (runs Claude's live ``web_search`` tool). Returns a summary
    ``{standardization, searches, items, item_ids}``.
    """
    concepts = store.load_concepts(subject, root=root)
    if not concepts:
        raise ValueError(f"no concepts for subject {subject!r}; run `ingest` first")
    concept_names = [c.name for c in concepts]
    concept_id_by_name = {c.name.lower(): c.id for c in concepts}

    assessment = run_call(
        "assess_standardization",
        {
            "subject": subject,
            "concept_names": concept_names,
            "sample_text": _sample_material(subject, root=root),
        },
        root=root,
        client=client,
        phase="Stage 2: assess_standardization",
    )
    level = assessment.get("standardization", "medium")
    query_terms = assessment.get("query_terms") or concept_names[:5]
    breadth = _BREADTH.get(level, 2)

    harvest = run_call(
        "harvest_web",
        {
            "subject": subject,
            "query_terms": query_terms,
            "concept_names": concept_names,
        },
        root=root,
        client=client,
        model=_websearch_model(),
        phase="Stage 2: harvest_web",
        tools=[{"type": _WEB_SEARCH_TYPE, "name": "web_search", "max_uses": breadth}],
    )
    new_items = [_item_from_web(it, concept_id_by_name) for it in harvest.get("items", [])]
    if new_items:
        store.add_items(subject, new_items, root=root)

    return {
        "standardization": level,
        "searches": breadth,
        "items": len(new_items),
        "item_ids": [i.id for i in new_items],
    }
