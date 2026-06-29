"""Round-trip and invariant tests for the data model.

Every top-level entity must survive a JSON round-trip unchanged (it is persisted as JSON
under git), unknown fields must be rejected, and the doc reconciliations (B1-B5) must hold.
"""

import pytest
from pydantic import ValidationError

from studybuddy import ids, models as m


def _one_of_each() -> dict[str, m._Base]:
    """A representative populated instance of every top-level entity."""
    ref_mat = m.Reference(kind=m.RefKind.material, ref="material_x", locator="p. 12")

    material = m.Material(
        id=ids.ulid_id("material"),
        type=m.MaterialType.textbook,
        source="Brealey & Myers, Ch. 5",
        raw_ref="materials/blobs/ch5.txt",
        ingested_at=ids.utcnow(),
        extracted_concepts=["concept_npv"],
        harvested_items=["item_001"],
    )

    concept = m.Concept(
        id=ids.slug_id("concept", "Net Present Value"),
        subject="corporate-finance",
        name="Net Present Value",
        parent_id="concept_time-value-of-money",
        dependency_edges=[
            m.DependencyEdge(
                other_concept_id="concept_time-value-of-money",
                relation=m.DependencyRelation.depends_on,
                confidence=0.7,
            )
        ],
        source_refs=[ref_mat],
        difficulty_prior=3.0,
    )

    item = m.Item(
        id=ids.ulid_id("item"),
        concept_ids=["concept_npv"],
        format=m.ItemFormat.numeric,
        stem="Compute the NPV of the following cash flows...",
        answer_key="1234.56",
        rationale="Discount each flow at the WACC and sum.",
        provenance=m.Provenance(origin=m.ProvenanceOrigin.retrieved, source=ref_mat),
        grading_spec=m.GradingSpec(rubric_text="exact match +/- 0.5", max_score=1.0),
    )

    generated_item = m.Item(
        id=ids.ulid_id("item"),
        concept_ids=["concept_npv"],
        format=m.ItemFormat.short,
        stem="Explain why NPV beats payback period.",
        answer_key={"key_points": ["time value", "all cash flows"]},
        provenance=m.Provenance(origin=m.ProvenanceOrigin.generated),
        template_id="generate_item",
        template_version="v1",
    )

    diag = m.DiagnosticResult(
        id=ids.ulid_id("diag"),
        learner_id="learner_default",
        item_responses=[
            m.ItemResponse(item_id=item.id, response="1234.56", correct=True, time_spent=42.0),
            m.ItemResponse(
                item_id=generated_item.id, response="...", correct=False, felt_lucky_flag=True
            ),
        ],
        per_concept_rollup={"concept_npv": {"correct_rate": 0.5}},
        gap_classification=[
            # B1: a concept may carry multiple gap types at once.
            m.GapClassification(
                concept_id="concept_npv", gap_types=["depth", "speed"], confidence=0.6
            )
        ],
        generated_at=ids.utcnow(),
    )

    gap_profile = m.GapProfile(
        learner_id="learner_default",
        entries=[
            # B1: one entry per (concept_id, gap_type); same concept appears twice.
            m.GapEntry(concept_id="concept_npv", gap_type="depth", severity=0.6),
            m.GapEntry(
                concept_id="concept_npv",
                gap_type="speed",
                status=m.GapStatus.confirmed,
                evidence_refs=[m.Reference(kind=m.RefKind.item, ref=item.id)],
            ),
        ],
        updated_at=ids.utcnow(),
    )

    plan = m.StudyPlan(
        learner_id="learner_default",
        topics=[
            m.PlanTopic(
                concept_id="concept_npv",
                source_links=[ref_mat],
                item_sequence=[item.id, generated_item.id],
            )
        ],
        version="v1",
    )

    template = m.PromptTemplate(
        id="extract_structure",
        task=m.PromptTask.extract_structure,
        version="v1",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        body="Extract a flat topic list from the material.",
        examples=[m.PromptExample(input={"material": "..."}, output={"topics": []})],
        metrics={"acceptance_rate": None},
    )

    heuristics = m.HeuristicsConfig(
        version="v1",
        difficulty_scale={"min": 1, "max": 5},
        gap_types=list(m.DEFAULT_GAP_TYPES),
        gap_thresholds={"foundational": {"easy_correct_rate_below": 0.5}},
        weighting_coeffs={"self_assessment": 0.33},
        sampling_rules={"diagnostic_size": 20},
        stopping_rule={"gap_confidence_target": 0.8},
    )

    run = m.RunLogEntry(
        id=ids.ulid_id("run"),
        phase="extract_structure",
        template_id="extract_structure",
        template_version="v1",
        input_ref="runs/blobs/run_x.in.json",
        raw_output_ref="runs/blobs/run_x.out.json",
        validation_status=m.ValidationStatus.valid,
        disposition=m.Disposition.accepted,
        ts=ids.utcnow(),
    )

    learner = m.LearnerState(
        learner_id="learner_default",
        intake=m.Intake(
            exam_format="closed-book, 3h",
            total_study_time=40.0,
            daily_availability=3.0,
            baseline="took intro finance two years ago",
            per_topic_confidence={"concept_npv": 0.4},
        ),
        diagnostic_results=[diag],
        gap_profile=gap_profile,
        study_plan=plan,
    )

    return {
        "Material": material,
        "Concept": concept,
        "Item": item,
        "GeneratedItem": generated_item,
        "DiagnosticResult": diag,
        "GapProfile": gap_profile,
        "StudyPlan": plan,
        "PromptTemplate": template,
        "HeuristicsConfig": heuristics,
        "RunLogEntry": run,
        "LearnerState": learner,
    }


@pytest.mark.parametrize("name,obj", list(_one_of_each().items()))
def test_json_round_trip(name, obj):
    """model -> JSON -> model is identity (the records live as JSON under git)."""
    restored = type(obj).model_validate_json(obj.model_dump_json())
    assert restored == obj


def test_entities_registry_complete():
    # Nine from spec section 3 + LearnerState (B4) + Proposal (Phase 5).
    assert set(m.ENTITIES) == {
        "Material",
        "Concept",
        "Item",
        "DiagnosticResult",
        "GapProfile",
        "StudyPlan",
        "PromptTemplate",
        "HeuristicsConfig",
        "RunLogEntry",
        "LearnerState",
        "Proposal",
    }


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        m.Concept(
            id="concept_x",
            subject="s",
            name="X",
            not_a_real_field=True,  # type: ignore[call-arg]
        )


def test_enum_values_validated():
    with pytest.raises(ValidationError):
        m.Item(
            id="item_x",
            concept_ids=["concept_x"],
            format="multiple_choice",  # not a valid ItemFormat  # type: ignore[arg-type]
            stem="...",
            answer_key="a",
            provenance=m.Provenance(origin=m.ProvenanceOrigin.retrieved),
        )


def test_confidence_bounds_enforced():
    with pytest.raises(ValidationError):
        m.DependencyEdge(
            other_concept_id="c", relation=m.DependencyRelation.depends_on, confidence=1.5
        )


def test_gap_status_defaults_to_hypothesis():
    entry = m.GapEntry(concept_id="concept_x", gap_type="depth")
    assert entry.status is m.GapStatus.hypothesis


def test_each_entity_exports_json_schema():
    # Needed in Loop 4 (schemas stored in prompts/) — confirm every model can emit one.
    for model in m.ENTITIES.values():
        schema = model.model_json_schema()
        assert schema["type"] == "object"
