"""Stage 1 (thin): ingest and harvest.

Read material files (.txt/.md/.pdf), store a Material record, then run two scoped Claude
calls through the validated wrapper: ``extract_structure`` to get the concepts the material
covers (flat for now; the dependency map is Stage 2 / Phase 3) and ``harvest_items`` to pull
the REAL questions already in the material, tagged to those concepts (retrieval-first;
web search is Phase 2). Everything is persisted to the subject-scoped knowledge layer.
"""

from __future__ import annotations

from pathlib import Path

from . import ids, store
from .models import (
    Concept,
    GradingSpec,
    Item,
    ItemFormat,
    Material,
    MaterialType,
    Provenance,
    ProvenanceOrigin,
    Reference,
    RefKind,
)
from .wrapper import run_call


def read_material_text(path: Path) -> str:
    """Extract plain text from a .txt/.md file or a PDF (thin pypdf pass)."""
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    return path.read_text(encoding="utf-8")


def _concepts_from(struct: dict, subject: str, material: Material) -> list[Concept]:
    concepts: list[Concept] = []
    for c in struct.get("concepts", []):
        parent = c.get("parent")
        refs = [Reference.model_validate(r) for r in (c.get("source_refs") or [])]
        if not any(r.kind is RefKind.material and r.ref == material.id for r in refs):
            refs.append(Reference(kind=RefKind.material, ref=material.id))
        concepts.append(
            Concept(
                id=store.concept_id(c["name"]),
                subject=subject,
                name=c["name"],
                parent_id=store.concept_id(parent) if parent else None,
                source_refs=refs,
                difficulty_prior=c.get("difficulty_prior"),
            )
        )
    return concepts


def _items_from(harvest: dict, material: Material) -> list[Item]:
    items: list[Item] = []
    for it in harvest.get("items", []):
        gs = it.get("grading_spec") or {}
        known = {k: gs[k] for k in ("rubric_text", "max_score", "facets") if k in gs}
        src_locator = (it.get("source") or {}).get("locator")
        items.append(
            Item(
                id=ids.ulid_id("item"),
                concept_ids=[store.concept_id(n) for n in it.get("concept_names", [])],
                format=ItemFormat(it["format"]),
                stem=it["stem"],
                options=it.get("options"),
                answer_key=it["answer_key"],
                rationale=it.get("rationale"),
                provenance=Provenance(
                    origin=ProvenanceOrigin.retrieved,
                    source=Reference(kind=RefKind.material, ref=material.id, locator=src_locator),
                ),
                grading_spec=GradingSpec(**known),
            )
        )
    return items


def ingest(
    subject: str,
    files: list[str],
    *,
    material_type: MaterialType = MaterialType.section,
    root=None,
    client=None,
) -> dict:
    """Ingest one or more material files into ``subject``. Additive: new material merges
    into the existing concepts and item bank, it never replaces them."""
    store.ensure_subject(subject, root=root)
    summary = {"materials": 0, "concepts": 0, "items": 0, "files": []}
    for f in files:
        path = Path(f)
        text = read_material_text(path)

        material_id = ids.ulid_id("material")
        raw_ref = store.save_material_raw(material_id, text, subject=subject, root=root)
        material = Material(
            id=material_id,
            type=material_type,
            source=path.name,
            raw_ref=raw_ref,
            ingested_at=ids.utcnow(),
        )

        struct = run_call(
            "extract_structure",
            {"material_text": text, "subject": subject, "material_id": material.id},
            root=root,
            client=client,
            phase="Stage 1: extract_structure",
        )
        concepts = _concepts_from(struct, subject, material)
        material.extracted_concepts = [c.id for c in concepts]
        store.merge_concepts(subject, concepts, root=root)

        harvest = run_call(
            "harvest_items",
            {
                "material_text": text,
                "subject": subject,
                "concept_names": [c.name for c in concepts],
            },
            root=root,
            client=client,
            phase="Stage 1: harvest_items",
        )
        items = _items_from(harvest, material)
        material.harvested_items = [i.id for i in items]
        store.add_items(subject, items, root=root)

        store.add_material(subject, material, root=root)

        summary["materials"] += 1
        summary["concepts"] += len(concepts)
        summary["items"] += len(items)
        summary["files"].append(path.name)
    return summary
