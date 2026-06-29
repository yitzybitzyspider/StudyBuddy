"""The StudyBuddy data model (spec section 3), as Pydantic v2 models.

These models *are* the schema for the knowledge layer's records. They serialize cleanly to
the plain JSON we keep under git (decision A2). Every model forbids unknown fields so the
schema stays the source of truth and drift is caught early.

Where the spec was contradictory or silent, the reconciliations from ``docs/DECISIONS.md``
are applied here (B1-B7); each is marked with its decision id in a comment.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------------------
# Enumerations (structural / contract-level closed sets).
#
# Note: gap *types* are deliberately NOT an enum here. Per decision B2 the allowed gap
# types are tunable data living in the heuristics config (HeuristicsConfig.gap_types), so
# they can evolve through ratified promotion without a code change. Gap-type fields below
# are typed as plain ``str`` and validated against the config at the orchestration layer.
# DEFAULT_GAP_TYPES is the seed set used to initialize the heuristics config in Loop 4.
# --------------------------------------------------------------------------------------

DEFAULT_GAP_TYPES: tuple[str, ...] = (
    "foundational",
    "depth",
    "overconfidence",
    "breadth",
    "speed",
)


class MaterialType(str, Enum):
    syllabus = "syllabus"
    textbook = "textbook"
    section = "section"
    notes = "notes"
    objectives = "objectives"
    recording = "recording"
    exam = "exam"  # B8: a past exam is a first-class input (FR-A2); spec §3 enum omitted it


class ItemFormat(str, Enum):
    mc = "mc"
    numeric = "numeric"
    short = "short"
    essay = "essay"
    application = "application"


class ProvenanceOrigin(str, Enum):
    retrieved = "retrieved"
    adapted = "adapted"
    generated = "generated"


class DependencyRelation(str, Enum):
    depends_on = "depends_on"
    prereq_of = "prereq_of"


class GapStatus(str, Enum):  # B3: a single status enum, no separate boolean
    hypothesis = "hypothesis"
    confirmed = "confirmed"
    resolved = "resolved"


class ConstraintResolution(str, Enum):
    compress = "compress"
    extend = "extend"


class Disposition(str, Enum):
    accepted = "accepted"
    edited = "edited"
    rejected = "rejected"


class ValidationStatus(str, Enum):
    valid = "valid"
    malformed = "malformed"  # non-JSON or fails schema validation


class RefKind(str, Enum):
    material = "material"
    web = "web"
    item = "item"
    run = "run"
    prompt = "prompt"
    concept = "concept"


class PromptTask(str, Enum):
    """The nine scoped Claude jobs (spec section 5). The registry holds exactly these."""

    extract_structure = "extract_structure"
    harvest_items = "harvest_items"
    build_dependency_map = "build_dependency_map"
    adapt_item = "adapt_item"
    generate_item = "generate_item"
    verify_item = "verify_item"
    grade_response = "grade_response"
    interpret_gaps = "interpret_gaps"
    compose_plan = "compose_plan"
    # Phase 2 web-search sourcing (realized via Claude's web_search tool).
    assess_standardization = "assess_standardization"
    harvest_web = "harvest_web"


# --------------------------------------------------------------------------------------
# Base model: strict by default.
# --------------------------------------------------------------------------------------


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------------------
# Shared value objects.
# --------------------------------------------------------------------------------------


class Reference(_Base):
    """The one canonical pointer shape used everywhere (decision A6).

    Every source link, evidence ref, item provenance source, and run-log pointer is a
    Reference, so traceability (philosophy section 11, NFR-3) is uniform and renderable.
    """

    kind: RefKind
    ref: str  # an entity id, a file path, or a URL
    locator: Optional[str] = None  # e.g. a page or section within ``ref``


# --------------------------------------------------------------------------------------
# Material (spec 3).
# --------------------------------------------------------------------------------------


class Material(_Base):
    id: str
    type: MaterialType
    source: str
    raw_ref: str  # pointer to stored raw content (file path / blob ref)
    ingested_at: datetime
    extracted_concepts: list[str] = Field(default_factory=list)  # Concept ids
    harvested_items: list[str] = Field(default_factory=list)  # Item ids


# --------------------------------------------------------------------------------------
# Concept (spec 3).
# --------------------------------------------------------------------------------------


class DependencyEdge(_Base):
    other_concept_id: str
    relation: DependencyRelation
    confidence: float = Field(ge=0.0, le=1.0)


class Concept(_Base):
    id: str
    subject: str
    name: str
    parent_id: Optional[str] = None
    dependency_edges: list[DependencyEdge] = Field(default_factory=list)
    source_refs: list[Reference] = Field(default_factory=list)
    difficulty_prior: Optional[float] = None


# --------------------------------------------------------------------------------------
# Item (spec 3).
# --------------------------------------------------------------------------------------


class Provenance(_Base):
    origin: ProvenanceOrigin
    source: Optional[Reference] = None  # where a retrieved/adapted item came from


class Calibration(_Base):
    """Accruing stats, auto-updated on every answer (Track A; no human gate)."""

    times_seen: int = 0
    correct_rate: Optional[float] = None
    observed_difficulty: Optional[float] = None
    discrimination: Optional[float] = None
    confidence: Optional[float] = None
    updated_at: Optional[datetime] = None


class GradingSpec(_Base):
    """B5 stub. The real open-ended rubric format is deferred (spec section 7)."""

    rubric_text: Optional[str] = None
    max_score: float = 1.0
    facets: list[str] = Field(default_factory=list)


class Item(_Base):
    id: str
    concept_ids: list[str]
    format: ItemFormat
    stem: str
    options: Optional[list[str]] = None  # present only for applicable formats
    answer_key: Any  # str or structured, by format
    rationale: Optional[str] = None
    provenance: Provenance
    grading_spec: GradingSpec = Field(default_factory=GradingSpec)
    # Decision C: store template id + version together so a generated item traces to an
    # exact PromptTemplate. Both are None unless the item was generated.
    template_id: Optional[str] = None
    template_version: Optional[str] = None
    calibration: Calibration = Field(default_factory=Calibration)


# --------------------------------------------------------------------------------------
# DiagnosticResult (spec 3).
# --------------------------------------------------------------------------------------


class ItemResponse(_Base):
    item_id: str
    response: Any
    correct: Optional[bool] = None
    time_spent: Optional[float] = None  # seconds
    felt_lucky_flag: bool = False  # self-reported lucky guess (overconfidence signal)


class GapClassification(_Base):
    concept_id: str
    gap_types: list[str] = Field(default_factory=list)  # B1: multiple allowed per concept
    confidence: float = Field(ge=0.0, le=1.0)


class DiagnosticResult(_Base):
    id: str
    learner_id: str
    item_responses: list[ItemResponse] = Field(default_factory=list)
    per_concept_rollup: dict[str, Any] = Field(default_factory=dict)  # shape unspecified
    gap_classification: list[GapClassification] = Field(default_factory=list)
    generated_at: datetime


# --------------------------------------------------------------------------------------
# GapProfile (spec 3) — B1: one entry per (concept_id, gap_type).
# --------------------------------------------------------------------------------------


class GapEntry(_Base):
    concept_id: str
    gap_type: str  # singular; a concept may appear in several entries (B1)
    severity: Optional[float] = None
    evidence_refs: list[Reference] = Field(default_factory=list)
    status: GapStatus = GapStatus.hypothesis


class GapProfile(_Base):
    learner_id: str
    entries: list[GapEntry] = Field(default_factory=list)
    updated_at: datetime


# --------------------------------------------------------------------------------------
# StudyPlan (spec 3). Spacing/time fields are filled by the deterministic engine (Phase 4),
# so they are optional here to allow the Phase 1 thin plan.
# --------------------------------------------------------------------------------------


class PlanTopic(_Base):
    concept_id: str
    time_block: Optional[str] = None  # deterministic engine fills (Phase 4)
    source_links: list[Reference] = Field(default_factory=list)
    item_sequence: list[str] = Field(default_factory=list)  # Item ids, foundational->synthesis
    review_schedule: list[Any] = Field(default_factory=list)  # spacing entries (Phase 4)


class StudyPlan(_Base):
    learner_id: str
    topics: list[PlanTopic] = Field(default_factory=list)
    total_time_estimate: Optional[float] = None  # hours; precise math in Phase 4
    constraint_resolution: Optional[ConstraintResolution] = None
    version: str


# --------------------------------------------------------------------------------------
# PromptTemplate (spec 3) — the unit stored in the prompt registry.
# --------------------------------------------------------------------------------------


class PromptExample(_Base):
    input: Any
    output: Any


class PromptTemplate(_Base):
    id: str
    task: PromptTask
    version: str
    input_schema: dict[str, Any]  # JSON Schema
    output_schema: dict[str, Any]  # JSON Schema; the wrapper validates output against this
    body: str
    examples: list[PromptExample] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)  # acceptance_rate, ...


# --------------------------------------------------------------------------------------
# HeuristicsConfig (spec 3) — tunable data, never hardcoded. gap_types added per B2.
# Concrete numbers are seeded in Loop 4 and are calibration placeholders (spec section 7).
# --------------------------------------------------------------------------------------


class HeuristicsConfig(_Base):
    version: str
    difficulty_scale: dict[str, Any]
    gap_types: list[str]  # B2: the gap-type vocabulary as data
    gap_thresholds: dict[str, Any]
    weighting_coeffs: dict[str, Any]
    sampling_rules: dict[str, Any]
    stopping_rule: dict[str, Any]
    # Track-A calibration knobs (Phase 2). Defaulted so older config files still load.
    calibration: dict[str, Any] = Field(default_factory=lambda: {"confidence_k": 4})
    # Stage-2 dependency-map knobs (Phase 3). Defaulted so older config files still load.
    dependency: dict[str, Any] = Field(
        default_factory=lambda: {"edge_confidence_min": 0.6}
    )


# --------------------------------------------------------------------------------------
# RunLogEntry (spec 3) — appended by the wrapper on every call (decision A4).
# --------------------------------------------------------------------------------------


class RunLogEntry(_Base):
    id: str
    phase: str  # pipeline stage or call name
    template_version: Optional[str] = None  # absent for non-Claude deterministic steps
    template_id: Optional[str] = None
    input_ref: str  # path to the stored structured input blob
    raw_output_ref: Optional[str] = None  # path to the stored raw model output blob
    validation_status: ValidationStatus
    disposition: Disposition
    human_override: Optional[Any] = None
    ts: datetime


# --------------------------------------------------------------------------------------
# LearnerState (B4) — spec 3 omits it though everything references learner_id.
# --------------------------------------------------------------------------------------


class Intake(_Base):
    """The Stage 3 intake interview result (FR-A6)."""

    exam_format: Optional[str] = None
    total_study_time: Optional[float] = None  # total hours available
    daily_availability: Optional[float] = None  # hours per day
    baseline: Optional[str] = None
    per_topic_confidence: dict[str, float] = Field(default_factory=dict)  # concept_id -> 0..1


class LearnerState(_Base):
    learner_id: str
    intake: Optional[Intake] = None
    diagnostic_results: list[DiagnosticResult] = Field(default_factory=list)
    gap_profile: Optional[GapProfile] = None
    study_plan: Optional[StudyPlan] = None
    progress: dict[str, Any] = Field(default_factory=dict)
    spacing_schedule: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------------------
# Entity registry — the top-level records the knowledge layer persists.
# --------------------------------------------------------------------------------------

ENTITIES: dict[str, type[_Base]] = {
    "Material": Material,
    "Concept": Concept,
    "Item": Item,
    "DiagnosticResult": DiagnosticResult,
    "GapProfile": GapProfile,
    "StudyPlan": StudyPlan,
    "PromptTemplate": PromptTemplate,
    "HeuristicsConfig": HeuristicsConfig,
    "RunLogEntry": RunLogEntry,
    "LearnerState": LearnerState,
}

__all__ = [
    "DEFAULT_GAP_TYPES",
    "MaterialType",
    "ItemFormat",
    "ProvenanceOrigin",
    "DependencyRelation",
    "GapStatus",
    "ConstraintResolution",
    "Disposition",
    "ValidationStatus",
    "RefKind",
    "PromptTask",
    "Reference",
    "Material",
    "DependencyEdge",
    "Concept",
    "Provenance",
    "Calibration",
    "GradingSpec",
    "Item",
    "ItemResponse",
    "GapClassification",
    "DiagnosticResult",
    "GapEntry",
    "GapProfile",
    "PlanTopic",
    "StudyPlan",
    "PromptExample",
    "PromptTemplate",
    "HeuristicsConfig",
    "RunLogEntry",
    "Intake",
    "LearnerState",
    "ENTITIES",
]
