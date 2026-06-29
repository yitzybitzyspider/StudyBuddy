"""Phase 5: the philosophy test in the gate (Loop 25).

The gate's last word is not the local metric — it is the design philosophy. "A proposal that
does not honor the design principles is rejected even when the local metric looks good"
(build-plan Phase 5; philosophy §8 *self-improving, never self-corrupting*). This module
encodes machine-checkable guards for the structured proposal kinds and returns the specific
principle each violation offends. ``proposals.decide`` runs it before applying an accept; any
violation turns the accept into a principled rejection.

The checks are deliberately conservative: they catch changes that would corrupt the knowledge
layer or fake a rigor the inputs don't support, not every imaginable bad idea. Human judgment
still owns the rest of the gate — this is the floor, not the ceiling.
"""

from __future__ import annotations

from . import registry, store
from .models import ProposalKind


def _check_recalibrate(change, *, root) -> list[str]:
    violations = []
    scale = store.load_heuristics(root=root).difficulty_scale or {}
    lo, hi = scale.get("min"), scale.get("max")
    to = change.get("to_difficulty")
    if to is None:
        return ["recalibration has no target difficulty (§9: no faked rigor)"]
    if lo is not None and hi is not None and not (lo <= to <= hi):
        violations.append(
            f"target difficulty {to} is outside the difficulty scale [{lo}, {hi}] "
            "(§9: honor the scale, don't invent values)"
        )
    return violations


def _check_dependency_edge(change, *, root) -> list[str]:
    violations = []
    frm, to = change.get("from_concept"), change.get("to_concept")
    conf = change.get("confidence")
    if frm == to:
        violations.append("a concept cannot depend on itself (§9: no spurious structure)")
    if conf is None or not (0.0 <= float(conf) <= 1.0):
        violations.append("edge confidence must be in [0, 1] (§9: honest confidence)")
    # Adding an edge that directly contradicts an existing confident opposite edge would
    # corrupt the living concept model (§8: never self-corrupting).
    subject = change.get("subject")
    if subject and to and frm:
        by_id = {c.id: c for c in store.load_concepts(subject, root=root)}
        target = by_id.get(to)
        if target is not None:
            for e in target.dependency_edges:
                if e.other_concept_id == frm and e.confidence >= 0.7:
                    violations.append(
                        f"contradicts an existing confident edge {to}→{frm} "
                        "(§8: never self-corrupting)"
                    )
    return violations


def _check_promote(change, *, root) -> list[str]:
    violations = []
    task, to_v = change.get("task"), change.get("to_version")
    try:
        target = registry.load_template(task, to_v, root=root)
    except registry.TemplateNotFound:
        return [f"target version {task}/{to_v} is not in the registry (§2: docs are the product)"]
    # Promotion must not weaken the strict-JSON output contract (CLAUDE.md: strict JSON in/out).
    schema = target.output_schema or {}
    if not isinstance(schema, dict) or not schema.get("type"):
        violations.append(
            "promoted version has no typed output schema — would weaken the strict-JSON "
            "contract (standing rule: strict JSON in and out)"
        )
    return violations


_CHECKS = {
    ProposalKind.recalibrate_difficulty: _check_recalibrate,
    ProposalKind.add_dependency_edge: _check_dependency_edge,
    ProposalKind.promote_prompt_version: _check_promote,
}


def check(proposal, *, root=None) -> dict:
    """Return ``{"ok": bool, "violations": [str]}`` for a proposal against the principles."""
    fn = _CHECKS.get(proposal.kind)
    violations = fn(proposal.change, root=root) if fn else []
    return {"ok": not violations, "violations": violations}
