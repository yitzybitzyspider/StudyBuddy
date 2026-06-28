# Build Decisions & Changelog

This file records decisions made while building StudyBuddy **where the design docs are
silent, ambiguous, or contradictory**. It is the running changelog for the knowledge
layer's structure.

Per design philosophy §8 (*self-improving, never self-corrupting*) and §2 (*the docs are
the product*), the authoritative design docs under `docs/study-system-*.md` are **not
edited silently**. Where building forced a choice the docs didn't make, the choice is
implemented in code/schemas and recorded here, with the doc section it derives from and
its status. Anything that should eventually fold back into the design docs is a candidate
for the Phase 5 proposals inbox, through the human gate — not a silent doc edit.

---

## 2026-06-28 — Phase 0 foundation

### A. Foundational implementation decisions (docs silent / left open)

| # | Decision | Choice | Grounding |
|---|----------|--------|-----------|
| A1 | Language & validation | Python 3.11+. **Pydantic v2** is the source of truth for the data-model entities; the **per-call contracts** are JSON Schema stored in `prompts/` (entity-shaped ones exported from the Pydantic models, verdict/score-shaped ones hand-authored). The wrapper validates BOTH halves of the contract with the **`jsonschema`** validator: the orchestrator's structured **input** against `input_schema` (fail-fast before any API spend, no retry — input is owned by deterministic code), and Claude's **output** against `output_schema` (one retry on malformed, then raise). Plain-text JSON Schema keeps contracts diffable. | build-plan suggested stack (Python); spec §5/§6 (call takes structured input, returns strict JSON validated against the schema); CLAUDE.md standing rules; philosophy §2 |
| A2 | Storage | Local JSON + Markdown under git. No database, no DB-shaped abstraction layer. Multi-user-later (NFR-2) is served by `learner_id` + one directory per learner, not a DB. | spec §7 (local files + git is the v1 default); philosophy §2, §12 |
| A3 | ID scheme | Human-readable prefixed slugs for **curated** artifacts (e.g. `concept_time-value-of-money`, prompt task ids); time-sortable **ULIDs** for **high-volume append-only** records (items, runs, diagnostic results). | philosophy §2 (diffability for curated artifacts); build-plan rule 2 (cheap append-only logging) |
| A4 | Run-log encoding | Append-only **JSONL** at `runs/runlog.jsonl`. Raw inputs/outputs are written as blobs at `runs/blobs/<id>.{in,out}.json` and referenced by `input_ref` / `raw_output_ref`, keeping the log small and diff-friendly. | spec §2.1 (append-only run log); spec §3 (RunLogEntry refs) |
| A5 | Prompt-registry layout | `prompts/<task>/<version>.json` per template + `prompts/<task>/index.json` whose `current` field names the active default. The wrapper resolves a template by `(task, version)`, defaulting to `current`. A manifest field (not a symlink) keeps it git-diffable and portable. | spec §2.2 (ratified promotion "promote vN to default"); philosophy §2 |
| A6 | Canonical reference shape | One reusable `Reference {kind: material\|web\|item\|run\|prompt\|concept, ref, locator}` used by every `source_refs` / `source_links` / `evidence_refs` / item provenance / run-log pointer. (`concept` is included because concept source-refs and gap evidence point at concepts.) | NFR-3 (source-linkability); philosophy §11 (everything traces to source) |
| A7 | Retry policy | Exactly **one** retry on malformed/invalid output. On a second failure the wrapper logs `validation_status=malformed, disposition=rejected` and raises to the orchestrator — no silent best-effort. | spec §5/§6 ("a retry on malformed output", singular); philosophy §9 (honesty over false rigor) |

### B. Doc reconciliations (interpretation of the design — human gate, not silent edits)

The design docs remain untouched. These are how the **schemas/code** resolve points the
docs leave contradictory or unspecified. Flagged here for sign-off; revisit via the
proposals inbox if any should become canonical in the docs.

| # | Issue in the docs | Resolution | Grounding |
|---|-------------------|------------|-----------|
| B1 | **Contradiction:** `DiagnosticResult.gap_classification[]` uses `gap_types[]` (plural) but `GapProfile.entries[]` uses `gap_type` (singular). | A concept may carry **multiple** gap types. `DiagnosticResult` keeps the per-concept `gap_types[]` array; `GapProfile` stores **one entry per `(concept_id, gap_type)`** pair. | philosophy §5 (a concept can break down in more than one way) |
| B2 | The allowed gap types are not enumerated in spec §3. | Enum `{foundational, depth, overconfidence, breadth, speed}`, stored in the **heuristics config** (not hardcoded) so it can evolve via ratified promotion. | requirements FR-D1; spec §7 (heuristics are tunable data) |
| B3 | `GapProfile` entry `status` text reads ambiguously ("hypothesis, confirmed, or resolved" plus a stray "confirmed"). | A **single** enum `status ∈ {hypothesis, confirmed, resolved}`. No separate boolean. | spec Stage 6/7 lifecycle language |
| B4 | **Gap:** `LearnerState` is referenced by every `learner_id` foreign key and named in spec §2.1, but has **no field list** in spec §3. | Add it as a first-class entity: `{learner_id, intake, diagnostic_results[], gap_profile, study_plan, progress, spacing_schedule}`, with an `intake` sub-schema from FR-A6 `{exam_format, total_study_time, daily_availability, baseline, per_topic_confidence}`. One directory per learner under `learner/`. | spec §2.1; requirements FR-A6; NFR-2 |
| B5 | `Item.grading_spec` shape and the open-ended grading rubric format are undefined (open question, spec §7). | Minimal flexible stub `{rubric_text, max_score, facets[]}`. The real rubric format is deferred until `grade_response` is built (Phase 1, Stage 5). | spec §7 (explicit open question) |
| B6 | Stage 3 mentions an optional unschematized "light Claude pass" to phrase follow-ups, outside the nine named contracts. | **Scoped out.** The registry stays at the nine contracts. No Claude call may bypass the validated wrapper (CLAUDE.md standing rules); if intake phrasing is ever added it must become a real registered template. | spec §5 (nine contracts); CLAUDE.md |
| B7 | build-plan says "place the four docs at the top"; there are five docs, now under `docs/`. spec §2.1 also lists requirements/spec as knowledge-layer artifacts. | Keep all five docs under `docs/` (CLAUDE.md binds those paths). Do **not** duplicate `requirements.md`/`spec.md` into the knowledge layer; `docs/` **is** the human-edited slice of the knowledge layer. | CLAUDE.md (authoritative paths); philosophy §2 (don't fork the product) |

### C0. Phase-0 schema notes (from the foundation review)

- **`interpret_gaps.dependency_context` is optional, not required.** Spec §5 frames its input
  as "per-concept rollup plus dependency context." But the dependency map is a Stage 2 / Phase 3
  artifact (deferred, see §D), and the Phase 1 diagnosis is flat with no dependency map, so the
  v1 template requires only `per_concept_rollup`. It becomes required when the dependency map
  lands (Phase 3).
- **`grade_response.score` has a floor (`minimum: 0`) but no static ceiling.** The per-rubric
  maximum (`grading_spec.max_score`) is a runtime value JSON Schema cannot reference statically;
  the deterministic Stage 5 grading step (Phase 1) clamps/validates the score against it.

### C. Provenance & traceability detail

- Generated items store provenance as `{template_id, template_version}` **together**, so an
  item traces to an exact `PromptTemplate` even if version strings repeat across tasks
  (spec §3 stored only a bare `template_version`). Derives from philosophy §11.

### D. Deferred (not built in Phase 0, per the build plan)

Dependency map (Stage 2 / Phase 3), adaptive sampling (Phase 3), spacing engine & time
math (Phase 4), in-system execution loop (Phase 4), web UI (Phase 4), web-search
harvesting (Phase 2), the proposals engine (Phase 5). Out of scope entirely: multi-user,
accounts, downloads, token budgeting, gamification, lecture transcription.
