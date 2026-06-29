"""Phase 5: the self-improvement proposals generator (Loop 23).

The system improves its own foundational artifacts only through evidence-backed proposals
that a human accepts or rejects — it never edits them unsupervised (philosophy §8). This
module *generates* proposals from accrued data; the gate (Loop 24) applies accepted ones and
the philosophy test (Loop 25) guards the gate.

Three evidence sources, each producing a structured, citable proposal:

  1. **Promote a prompt version** — a non-current template version whose ``acceptance_rate``
     beats the current default by a margin, with enough attempts to be real.
  2. **Add a dependency edge** — an edge held in ``proposals/dependency-inbox.jsonl`` (Loop
     16) that has recurred enough times to be worth confirming into the concept model.
  3. **Recalibrate difficulty** — a concept whose items' *observed* difficulty band (from
     calibration) consistently disagrees with its labeled ``difficulty_prior``.

Each proposal carries ``evidence_refs`` (run-log / calibration / concept pointers) and a
concrete ``change`` dict the gate knows how to apply. Generation is idempotent: a proposal
whose ``(kind, change-signature)`` already sits open in the inbox is not duplicated.
"""

from __future__ import annotations

import json
from collections import defaultdict

from . import ids, philosophy, registry, store
from .models import (
    DependencyEdge,
    DependencyRelation,
    Proposal,
    ProposalKind,
    ProposalStatus,
    Reference,
    RefKind,
)

# Tunables (stated assumptions; could themselves migrate to the heuristics config later).
_PROMOTE_MIN_ATTEMPTS = 5
_PROMOTE_MARGIN = 0.1
_EDGE_MIN_OCCURRENCES = 2
_RECAL_MIN_TIMES_SEEN = 3
_RECAL_MIN_ITEMS = 3


def _signature(kind: ProposalKind, change: dict) -> str:
    return json.dumps({"kind": kind.value, "change": change}, sort_keys=True, default=str)


def _band_of(difficulty, bands) -> str | None:
    for name, rng in (bands or {}).items():
        if isinstance(rng, list) and len(rng) == 2 and rng[0] <= difficulty <= rng[1]:
            return name
    return None


def _prompt_promotions(root) -> list[tuple[ProposalKind, str, str, list[Reference], dict]]:
    out = []
    prompts_dir = store.paths.knowledge_root(root) / "prompts"
    for task in sorted(prompts_dir.glob("*")) if prompts_dir.is_dir() else []:
        if not task.is_dir():
            continue
        name = task.name
        try:
            current = registry.current_version(name, root=root)
        except registry.TemplateNotFound:
            continue
        best = None
        for v in registry.list_versions(name, root=root):
            tpl = registry.load_template(name, v, root=root)
            m = tpl.metrics or {}
            rate, attempts = m.get("acceptance_rate"), int(m.get("attempts") or 0)
            if rate is None or attempts < _PROMOTE_MIN_ATTEMPTS:
                continue
            if best is None or rate > best[1]:
                best = (v, rate, attempts)
        if not best:
            continue
        cur_tpl = registry.load_template(name, current, root=root)
        cur_rate = (cur_tpl.metrics or {}).get("acceptance_rate")
        v, rate, attempts = best
        if v != current and (cur_rate is None or rate - cur_rate >= _PROMOTE_MARGIN):
            change = {"task": name, "from_version": current, "to_version": v}
            summary = f"Promote {name} {v} to default (acceptance {rate:.0%} over {attempts} attempts)"
            refs = [Reference(kind=RefKind.prompt, ref=f"{name}/{v}")]
            out.append((ProposalKind.promote_prompt_version, name, summary, refs, change))
    return out


def _dependency_edges(root):
    path = store.paths.knowledge_root(root) / "proposals" / "dependency-inbox.jsonl"
    if not path.exists():
        return []
    agg: dict[tuple, dict] = defaultdict(lambda: {"count": 0, "confidence": 0.0})
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = (rec.get("subject"), rec.get("from_concept"), rec.get("to_concept"), rec.get("relation"))
        agg[key]["count"] += 1
        agg[key]["confidence"] = max(agg[key]["confidence"], float(rec.get("confidence") or 0.0))

    out = []
    for (subject, frm, to, relation), stats in agg.items():
        if not (subject and frm and to and relation) or stats["count"] < _EDGE_MIN_OCCURRENCES:
            continue
        change = {"subject": subject, "from_concept": frm, "to_concept": to,
                  "relation": relation, "confidence": round(stats["confidence"], 4)}
        summary = (f"Add dependency edge {frm} {relation} {to} "
                   f"(seen {stats['count']}x, confidence {stats['confidence']:.2f})")
        refs = [Reference(kind=RefKind.concept, ref=frm), Reference(kind=RefKind.concept, ref=to)]
        out.append((ProposalKind.add_dependency_edge, subject, summary, refs, change))
    return out


def _difficulty_recalibrations(subject, root):
    out = []
    bands = (store.load_heuristics(root=root).difficulty_scale or {}).get("bands", {})
    concepts = {c.id: c for c in store.load_concepts(subject, root=root)}
    items = store.load_items(subject, root=root)
    per_concept: dict[str, list[float]] = defaultdict(list)
    for it in items:
        od = it.calibration.observed_difficulty
        if od is None or it.calibration.times_seen < _RECAL_MIN_TIMES_SEEN:
            continue
        for cid in it.concept_ids:
            per_concept[cid].append(od)
    for cid, ods in per_concept.items():
        concept = concepts.get(cid)
        if concept is None or concept.difficulty_prior is None or len(ods) < _RECAL_MIN_ITEMS:
            continue
        observed = 1 + 4 * (sum(ods) / len(ods))  # 0..1 mean -> 1..5
        prior_band = _band_of(round(concept.difficulty_prior), bands)
        observed_band = _band_of(round(observed), bands)
        if observed_band and prior_band and observed_band != prior_band:
            change = {"subject": subject, "concept_id": cid,
                      "from_difficulty": concept.difficulty_prior, "to_difficulty": round(observed, 2)}
            summary = (f"Recalibrate '{concept.name}' difficulty "
                       f"{prior_band}→{observed_band} (observed ~{observed:.1f} over {len(ods)} items)")
            refs = [Reference(kind=RefKind.concept, ref=cid)]
            out.append((ProposalKind.recalibrate_difficulty, subject, summary, refs, change))
    return out


def generate(subject: str | None = None, *, root=None) -> list[Proposal]:
    """Generate proposals from accrued evidence and append new ones to the inbox.

    Returns only the **newly added** proposals (idempotent against open ones).
    """
    existing = store.load_proposals(root=root)
    open_sigs = {
        _signature(p.kind, p.change) for p in existing if p.status is ProposalStatus.open
    }

    candidates = []
    candidates += _prompt_promotions(root)
    candidates += _dependency_edges(root)
    if subject:
        candidates += _difficulty_recalibrations(subject, root)

    now = ids.utcnow()
    new: list[Proposal] = []
    for kind, subj, summary, refs, change in candidates:
        sig = _signature(kind, change)
        if sig in open_sigs:
            continue
        open_sigs.add(sig)
        new.append(
            Proposal(
                id=ids.ulid_id("prop"),
                kind=kind,
                subject=subj,
                summary=summary,
                rationale=summary,
                evidence_refs=refs,
                change=change,
                status=ProposalStatus.open,
                created_at=now,
            )
        )
    if new:
        store.save_proposals(existing + new, root=root)
    return new


# --------------------------------------------------------------------------------------
# The human gate (Loop 24): accept (apply + changelog) or reject (record, learn from it).
# --------------------------------------------------------------------------------------


class ProposalError(Exception):
    """The proposal could not be found or applied."""


def _changelog(root, entry: dict) -> None:
    path = store.paths.knowledge_root(root) / "proposals" / "changelog.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def _apply(proposal: Proposal, *, root) -> None:
    """Version the relevant artifact forward. Each branch is a Track-B mutation."""
    change = proposal.change
    if proposal.kind is ProposalKind.promote_prompt_version:
        registry.set_current(change["task"], change["to_version"], root=root)

    elif proposal.kind is ProposalKind.add_dependency_edge:
        subject = change["subject"]
        concepts = store.load_concepts(subject, root=root)
        by_id = {c.id: c for c in concepts}
        src = by_id.get(change["from_concept"])
        if src is None or change["to_concept"] not in by_id:
            raise ProposalError("dependency edge references a concept not in the subject")
        relation = DependencyRelation(change["relation"])
        conf = float(change.get("confidence") or 0.0)
        existing = next(
            (e for e in src.dependency_edges
             if e.other_concept_id == change["to_concept"] and e.relation is relation),
            None,
        )
        if existing is not None:
            existing.confidence = existing.confidence + (1 - existing.confidence) * conf
        else:
            src.dependency_edges.append(
                DependencyEdge(other_concept_id=change["to_concept"], relation=relation, confidence=conf)
            )
        store.save_concepts(subject, list(by_id.values()), root=root)

    elif proposal.kind is ProposalKind.recalibrate_difficulty:
        subject = change["subject"]
        concepts = store.load_concepts(subject, root=root)
        found = False
        for c in concepts:
            if c.id == change["concept_id"]:
                c.difficulty_prior = float(change["to_difficulty"])
                found = True
        if not found:
            raise ProposalError("recalibration references a concept not in the subject")
        store.save_concepts(subject, concepts, root=root)
    else:  # pragma: no cover - enum is closed
        raise ProposalError(f"don't know how to apply {proposal.kind}")


def decide(proposal_id: str, accept: bool, *, note: str | None = None, root=None) -> Proposal:
    """Accept (apply + changelog) or reject (record) a proposal — the human gate (Track B).

    Accepting applies the change and versions the artifact forward with a changelog entry.
    Rejecting records the decision; the proposal stays in the inbox so it can be learned from.
    """
    proposals = store.load_proposals(root=root)
    target = next((p for p in proposals if p.id == proposal_id), None)
    if target is None:
        raise ProposalError(f"no proposal {proposal_id!r} in the inbox")
    if target.status is not ProposalStatus.open:
        raise ProposalError(f"proposal {proposal_id!r} already {target.status.value}")

    if accept:
        # The philosophy test is the gate's floor: a principle violation overrides the metric
        # and the human's accept (philosophy §8 — never self-corrupting). It is not bypassable.
        verdict = philosophy.check(target, root=root)
        if not verdict["ok"]:
            target.status = ProposalStatus.rejected
            reason = "; ".join(verdict["violations"])
            target.decision_note = (
                f"rejected by the philosophy gate: {reason}"
                + (f" — (reviewer note: {note})" if note else "")
            )
            target.decided_at = ids.utcnow()
            store.save_proposals(proposals, root=root)
            return target
        _apply(target, root=root)
        target.status = ProposalStatus.accepted
        target.decision_note = note
        _changelog(root, {
            "proposal_id": target.id, "kind": target.kind.value, "subject": target.subject,
            "change": target.change, "summary": target.summary, "note": note,
            "applied_at": ids.utcnow().isoformat(),
        })
    else:
        target.status = ProposalStatus.rejected
        target.decision_note = note

    target.decided_at = ids.utcnow()
    store.save_proposals(proposals, root=root)
    return target
