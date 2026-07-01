"""Stage 8 (thin): compose the study plan, and the FR-G2 steer control.

Deterministic code owns the structure — which topics (the confirmed gaps), the source links,
and the ordered item sequence per topic (foundational -> depth -> synthesis). Claude
``compose_plan`` writes the human-facing prose over that structure. The result is a
``StudyPlan`` saved to learner state plus a rendered markdown one-pager (FR-F1/F2/F4). The
spacing engine and honest time math are Phase 4, so time is allocated only roughly here.

``steer`` is the FR-G2 control: after seeing the diagnostic the user can ask for more like
these, fewer, or a shift in focus, and we recompose a follow-up batch accordingly.
"""

from __future__ import annotations

from collections import defaultdict

from . import diagnostic as diagnostic_mod
from . import store, timebudget as timebudget_mod
from .models import ConstraintResolution, PlanTopic, Reference, RefKind, StudyPlan
from .wrapper import run_call

PLAN_DOC = "study-plan.md"


def _item_sequences(concept_ids, items) -> dict[str, list[str]]:
    """Item ids per concept (foundational->synthesis ordering is refined in Phase 4)."""
    by_concept: dict[str, list[str]] = defaultdict(list)
    for it in items:
        for cid in it.concept_ids:
            if cid in concept_ids:
                by_concept[cid].append(it.id)
    return by_concept


def compose(
    subject: str,
    *,
    root=None,
    client=None,
    learner_id: str = store.DEFAULT_LEARNER,
    resolution: ConstraintResolution | str | None = None,
) -> dict:
    state = store.load_learner(learner_id, subject=subject, root=root)
    concepts = store.load_concepts(subject, root=root)
    by_id = {c.id: c for c in concepts}
    by_name = {c.name: c.id for c in concepts}
    name_by_id = {c.id: c.name for c in concepts}
    items = store.load_items(subject, root=root)
    item_by_id = {it.id: it for it in items}

    # Topics = the concepts with confirmed/hypothesized gaps; fall back to all concepts.
    gapped = []
    if state.gap_profile and state.gap_profile.entries:
        seen = set()
        for e in state.gap_profile.entries:
            if e.concept_id not in seen:
                seen.add(e.concept_id)
                gapped.append(e.concept_id)
    else:
        gapped = [c.id for c in concepts]

    sequences = _item_sequences(set(gapped), items)
    constraints = {}
    if state.intake:
        constraints = {
            "exam_format": state.intake.exam_format,
            "total_study_time": state.intake.total_study_time,
            "daily_availability": state.intake.daily_availability,
        }

    content = run_call(
        "compose_plan",
        {
            "gap_profile": state.gap_profile.model_dump(mode="json") if state.gap_profile else {},
            "item_sequences": {name_by_id.get(cid, cid): sequences.get(cid, []) for cid in gapped},
            "constraints": constraints,
        },
        root=root,
        client=client,
        phase="Stage 8: compose_plan",
    )

    # Honest time-to-comprehensive (Stage 8): estimate from the practice load + spacing model,
    # compare to available time, and surface the gap. The deterministic engine owns this math.
    gap_types_by_concept: dict[str, list[str]] = defaultdict(list)
    if state.gap_profile:
        for e in state.gap_profile.entries:
            gap_types_by_concept[e.concept_id].append(e.gap_type)
    est_topics = [
        {
            "concept_id": cid,
            "name": name_by_id.get(cid, cid),
            "item_formats": [
                item_by_id[i].format.value for i in sequences.get(cid, []) if i in item_by_id
            ],
            "gap_types": gap_types_by_concept.get(cid, []),
        }
        for cid in gapped
    ]
    estimate = timebudget_mod.estimate(est_topics)
    available = state.intake.total_study_time if state.intake else None
    budget = timebudget_mod.reconcile(estimate["total_hours"], available)
    hours_by_concept = {t["concept_id"]: t["hours"] for t in estimate["per_topic"]}

    topics = []
    prose_by_concept = {}
    for t in content.get("topics", []):
        cid = t["concept"] if t["concept"] in by_id else by_name.get(t["concept"], store.concept_id(t["concept"]))
        prose_by_concept[cid] = t
    for cid in gapped:
        concept = by_id.get(cid)
        source_links = list(concept.source_refs) if concept else []
        hrs = hours_by_concept.get(cid)
        topics.append(
            PlanTopic(
                concept_id=cid,
                time_block=f"{hrs}h" if hrs else None,
                source_links=source_links,
                item_sequence=sequences.get(cid, []),
                review_schedule=[],
            )
        )

    resolved = ConstraintResolution(resolution) if resolution else None
    plan = StudyPlan(
        learner_id=learner_id,
        topics=topics,
        total_time_estimate=estimate["total_hours"],
        constraint_resolution=resolved,
        version="v1",
    )
    state.study_plan = plan
    store.save_learner(state, subject=subject, root=root)

    markdown = _render_markdown(
        subject, plan, content, prose_by_concept, name_by_id, budget,
        root=root, learner_id=learner_id,
    )
    return {
        "study_plan": plan,
        "markdown": markdown,
        "markdown_path": store.doc_path(learner_id, subject, PLAN_DOC, root=root),
        "overview": content.get("overview", ""),
        "budget": budget,
    }


def _render_markdown(subject, plan, content, prose_by_concept, name_by_id, budget, *, root, learner_id):
    lines = [f"# Study plan — {subject}", ""]
    if content.get("overview"):
        lines += [content["overview"], ""]
    if budget:
        lines.append(f"**Time check:** {budget['message']}")
        if plan.constraint_resolution:
            lines.append(f"_Resolution: {plan.constraint_resolution.value}._")
        lines.append("")
    for topic in plan.topics:
        name = name_by_id.get(topic.concept_id, topic.concept_id)
        prose = prose_by_concept.get(topic.concept_id, {})
        lines.append(f"## {name}" + (f"  ({topic.time_block})" if topic.time_block else ""))
        if prose.get("summary"):
            lines.append(prose["summary"])
        if prose.get("rationale"):
            lines.append(f"\n_Why:_ {prose['rationale']}")
        if topic.source_links:
            refs = ", ".join(
                f"{r.kind.value}:{r.ref}" + (f" ({r.locator})" if r.locator else "")
                for r in topic.source_links
            )
            lines.append(f"\n_Sources:_ {refs}")
        lines.append(f"\n_Practice ({len(topic.item_sequence)} items):_ foundational → depth → synthesis")
        lines.append("")
    markdown = "\n".join(lines)
    store.put_doc(learner_id, subject, PLAN_DOC, markdown, root=root)
    return markdown


def steer(
    subject: str,
    *,
    action: str,
    focus: list[str] | None = None,
    root=None,
    client=None,
    learner_id: str = store.DEFAULT_LEARNER,
) -> dict:
    """FR-G2: recompose a follow-up diagnostic batch (more / fewer / shift focus)."""
    batch = int(store.load_heuristics(root=root).sampling_rules.get("adaptive_batch_size", 4))
    if action == "more":
        size = batch
    elif action == "fewer":
        size = max(1, batch // 2)
    elif action == "shift":
        size = batch
        if not focus:
            raise ValueError("steer --shift requires a focus topic")
    else:
        raise ValueError(f"unknown steer action {action!r}")
    result = diagnostic_mod.compose(
        subject, root=root, client=client, learner_id=learner_id, size=size, focus=focus
    )
    result["action"] = action
    return result
