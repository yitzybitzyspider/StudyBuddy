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

## 2026-06-28 — Phase 1 walking skeleton

### E. Persistence & pipeline decisions

| # | Decision | Choice | Grounding |
|---|----------|--------|-----------|
| E1 | Persistence layout | Subject-scoped JSON: `concepts/<subject>.json`, `items/<subject>.json` (item bank), `materials/<subject>.json` (+ `materials/raw/<id>.txt` for raw text). Learner-scoped: `learner/<lid>/state.json`, `learner/<lid>/diagnostic.json`. Single default learner `learner_default`. | A2 (files under git); NFR-2 (learner_id keeps multi-user open) |
| E2 | Interaction model (Phase 1) | **File-based**: `compose-diagnostic` and `intake` emit editable JSON; the user fills answers; `administer`/`intake --answers` read them back. The friendly in-system UI is Phase 4. | build-plan (CLI first, UI later); user choice |
| E3 | Ingestion inputs | `.txt`/`.md` read directly; PDF via a thin `pypdf` text pass. | build-plan ("pasted or PDF"); FR-A1/A2 |
| E4 | Subject provisioning | `--subject` at ingest stamps `Concept.subject` and the file partition (resolves the spec gap that Material carries no subject). | spec §3 gap; FR-B1 |
| E5 | Concept linking | Items reference concepts by `concept_id = slug_id("concept", name)`; deterministic code maps harvested/diagnostic `concept_names` → ids within the subject. Each concept also gets a `Reference(material)` backref. | NFR-3; philosophy §11 |
| E6 | Calibration (early slice) | Administering updates each served item's `times_seen` and `correct_rate` (Track A auto-accrual). Full calibration (discrimination, etc.) is Phase 2. | build-plan rule 2 (cheap high-leverage early) |

### B8. Data-model reconciliation: `MaterialType.exam`

Spec §3's `Material.type` enum (syllabus, textbook, section, notes, objectives, recording)
omits **exam**, but FR-A2 makes a past exam a first-class, strongly-preferred input that
`harvest_items` pulls real questions from. Added `exam` to `MaterialType`. Recorded here, not
silently changed in the spec (philosophy §8).

### F. Web UI (Phase 4, pulled forward)

A minimal **Flask** web UI (`studybuddy/web/`, `studybuddy serve`) was built ahead of the
planned phase order, at the user's request, to test the live system in a browser. It is a
**thin presentation layer only** — it calls the existing pipeline functions (ingest, intake,
diagnostic, administer, diagnose, plan, steer) and adds no pipeline logic. Optional dependency
(`pip install -e ".[web]"`). Honors `STUDYBUDDY_OFFLINE` like the CLI. The deeper Phase-4 work
(spacing engine, honest time math, in-system execution loop) and Phases 2–3 remain as planned.

## 2026-06-29 — Phase 2 sourcing & calibration

### G. Calibration & sourcing decisions (Track A)

| # | Decision | Choice | Grounding |
|---|----------|--------|-----------|
| G1 | Calibration accrual | Each answer accrues `times_seen`, `correct_rate`, `observed_difficulty` (= 1 − correct_rate), and `confidence` (saturates with exposure via `calibration.confidence_k` in the heuristics config). All Track A (auto, no sign-off). | philosophy §8 (auto-accrual track); build-plan Phase 2 |
| G2 | Discrimination deferred | `Item.calibration.discrimination` stays `null`. True discrimination is a cross-respondent statistic; with one learner it can't be computed without faking rigor, so we don't. Revisit under multi-user (NFR-2). | philosophy §9 (honesty over false rigor) |
| G3 | Sourcing order | The diagnostic composer fills gaps **retrieve → adapt → generate → verify**: reuse a real item, `adapt_item` (new numbers/context) when one exists for the concept, `generate_item` only when nothing is adaptable; `verify_item` gates everything adapted/generated. | philosophy §4 (retrieve before generate) |
| G4 | Acceptance metrics | Each verify outcome accrues into the template version's `metrics` (attempts, accepts, `acceptance_rate`) via `registry.record_acceptance` — Track A (auto). It never flips the `current` default; promoting a version stays Track B (human-gated). | philosophy §8 (two tracks) |
| G5 | Web-search harvesting | Realized via Claude's **server-side `web_search` tool** (`web_search_20260209`), not a separate search API/account — same `ANTHROPIC_API_KEY`. The wrapper gained an optional `tools=[...]` param and a bounded `pause_turn` continuation loop; strict-JSON output + run-log are unchanged. Two new templates registered (registry → 11): `assess_standardization` (subject/material → `{standardization, query_terms[], rationale}`) and `harvest_web` (`{subject, query_terms, concept_names}` + the tool → real questions as items, `provenance.origin=retrieved`, `source=Reference(kind=web, ref=URL)`). Driver `websearch.web_harvest` sizes breadth to standardization (low→1 / medium→2 / high→3 searches). **Opt-in** (cost control): never auto-run by `ingest`; only the `harvest-web` CLI command or the topics-page UI button. | philosophy §4 (retrieve before generate); spec framed web search as deterministic sourcing — this is the chosen implementation; build-plan Phase 2 |

## 2026-06-29 — Phase 3 diagnostic intelligence

### H. Dependency map (Stage 2)

| # | Decision | Choice | Grounding |
|---|----------|--------|-----------|
| H1 | Edge merge policy | The concept model is refined by **accruing confidence, never overwriting** (spec §Stage-2). Re-confirming an existing `(from, to, relation)` edge raises its confidence via **noisy-OR** (`merged = old + (1−old)·new`), monotonically toward 1; it never decreases and never duplicates. | spec §Stage-2 ("merge by accruing confidence rather than overwriting") |
| H2 | Weak-edge gate | A **fresh** edge whose single-call confidence is below `heuristics.dependency.edge_confidence_min` (default 0.6) is **not** written into the concept model; it is appended to `proposals/dependency-inbox.jsonl` for the Phase-5 human gate. Re-confirming an **existing** edge always accrues regardless of the call's confidence (evidence is evidence). | spec §Stage-2 ("route low-confidence new edges to the proposals inbox"); philosophy §8 (human gate) |
| H3 | Edge sanity | Only edges between **known, distinct** concepts are kept; self-loops and edges naming an unknown concept are dropped (the call can hallucinate a name). Direction stored on the `from` concept as `DependencyEdge(other_concept_id=to, relation, confidence)`. | philosophy §9 (no faked rigor); A6 |
| H4 | Proposals-inbox stub | The Phase-5 inbox/gate is not built yet, so low-confidence edges are **held** (append-only JSONL under `proposals/`) rather than silently dropped or auto-applied. The Phase-5 engine will consume this file. | build-plan Phase 5; philosophy §8 |
| H5 | Dependency-aware diagnosis (Stage 6) | `interpret_gaps` now receives a real `dependency_context`: per tested concept, its prerequisites (both edge directions normalized — `depends_on` and `prereq_of` resolve to "what sits below X"), each with edge confidence and the learner's correct_rate on that prerequisite (null if untested). This lets a downstream miss be read as an upstream prerequisite gap. `dependency_context` stays schema-optional (empty when the map has no edges yet), superseding the Phase-1 placeholder `{}` (closes the C0 "becomes required in Phase 3" note pragmatically — populated, not required). | spec §Stage-6 ("interpreted inside the dependency map"); C0 |

### I. Adaptive sampling & gap accrual (Stage 7)

| # | Decision | Choice | Grounding |
|---|----------|--------|-----------|
| I1 | GapEntry gains `confidence` | `GapEntry` now carries a `confidence` (optional), populated from `interpret_gaps`, so the stopping rule has a real quantity to test. Was dropped in Phase 1. | spec §Stage-7 (stopping rule on gap-profile confidence) |
| I2 | Gap accrual across batches | `diagnose` merges the fresh gap read with the prior profile: a re-observed `(concept, gap_type)` **accrues** confidence (noisy-OR) and becomes `confirmed`; a prior gap whose concept was re-tested but did not resurface becomes `resolved`; a prior gap for an untested concept carries forward unchanged; a new gap enters as `hypothesis`. This is the Stage-7 "GapProfile status transitions" writeback. | spec §Stage-7; philosophy §8 (auto-accrual) |
| I3 | Stopping rule | `sampling.stopping_status` fires when there are no open (non-resolved) gaps, when **every** open gap is at/above `stopping_rule.gap_confidence_target` (0.8), or when `max_adaptive_batches` (4) is reached. The batch cap guarantees termination (philosophy §9 — no unbounded loop pretending at rigor). | spec §Stage-7; heuristics config |
| I4 | Strategic batch selection | `sampling.select_focus` picks, in priority order: the **weakest** open gap (lowest confidence), a **boundary** prerequisite that is itself shaky (via the Stage-2 dependency edges), and one **strength** to verify (a concept scored ≥0.8 this batch). Deterministic; sourcing/grading reuse Stages 4–6. File-based loop (E2): `sample` composes the next batch, the user answers + administers + diagnoses, then calls `sample` again. | spec §Stage-7 (weakest / boundary / verification) |

### J. Material-aware gap heuristics (Stage 6)

| # | Decision | Choice | Grounding |
|---|----------|--------|-----------|
| J1 | Band-aware classification | `_classify` now buckets a concept's answered items by **difficulty band** (the `difficulty_scale.bands` from the heuristics config) and applies the band-aware threshold rules already seeded but previously unused: `foundational` when the **easy**-band correct_rate is below `foundational.easy_band_correct_rate_below`; `depth` when **easy/medium** is solid (≥ `depth.easy_medium_correct_rate_at_least`) but **hard** breaks (< `depth.hard_correct_rate_below`). A multi-step concept can now surface foundational *and* depth from the same diagnostic (B1), instead of one averaged verdict. | build-plan Phase 3 ("material-aware … one step foundational, another depth"); spec §Stage-6 |
| J2 | Per-item difficulty source | An item's 1–5 difficulty is taken from, in order: its **calibrated** `observed_difficulty` (Track A), else the concept's `difficulty_prior`, else a per-format proxy. Falls back to the aggregate `correct_rate` rule when a concept's banded data is too thin (e.g. a single item / single band), preserving Phase-1 behavior. | philosophy §9 (use real signal where it exists, don't fake it); G1 |

## 2026-06-29 — Phase 4 plan & execution

### K. Spacing & interleaving engine (Stage 8/9)

| # | Decision | Choice | Grounding |
|---|----------|--------|-----------|
| K1 | SM-2 scheduler | `studybuddy/spacing.py` implements a standard SM-2 review card per item `{ease, interval, repetitions, due, last_quality, reviews}`. Interval grows 1→6→`round(interval·ease)` on passes; a lapse (quality < 3) resets reps and interval to 1; ease updates by the SM-2 formula floored at 1.3. **Fully deterministic — no Claude call touches scheduling.** | build-plan Phase 4 ("SM-2 style is a fine basis"); spec §Stage-8 (engine owns spacing) |
| K2 | Honest quality mapping | A graded answer maps to SM-2 quality: confident-correct = 5, correct-but-felt-lucky = 3 (passes but returns sooner), wrong = 2, blank = 0. The felt-lucky signal feeds spacing as well as the overconfidence gap. | philosophy §9; FR-C |
| K3 | Schedule is git JSON | Cards live on `LearnerState.spacing_schedule` (keyed by item id), ISO-8601 UTC due dates — plain JSON under git like every other artifact. | A2 |
| K4 | Accrue from day one | `administer` updates the spacing schedule for each answered item (Track A, alongside calibration), so review data banks from the first diagnostic, before the Stage-9 execution loop exists. `now` is injected for deterministic tests. | build-plan rule 2 (cheap, high-leverage early); philosophy §8 |
| K5 | Interleaving | `interleave` greedily reorders a due set so consecutive items avoid repeating a concept where possible, falling back to original order when unavoidable — spacing *and* interleaving, both deterministic (FR-F). | requirements FR-F |

### L. Time-budget reality check (Stage 8)

| # | Decision | Choice | Grounding |
|---|----------|--------|-----------|
| L1 | Honest time-to-comprehensive | `timebudget.estimate` computes hours per topic = (items × avg minutes-by-format × repetitions-to-comprehensive), where reps derive from SM-2 reaching its third growing interval, scaled by the topic's heaviest gap type. Empty topics fall back to a default item count. Every coefficient is a **stated assumption** returned in the result — rough by nature, honest by surfacing. | build-plan Phase 4; philosophy §9 |
| L2 | Surface the gap, don't hide it | `reconcile` compares needed vs available (from intake) and returns a plain-language gap with status `fits` / `over` / `unknown`. `plan.compose` now sets `total_time_estimate` to the **needed** hours (not the available figure) and writes the time check into the plan one-pager. | spec §Stage-8 ("surface the honest gap") |
| L3 | Compress or extend, user-chosen | When over budget, the user resolves with `--compress` / `--extend` (CLI) or the plan-page buttons (web); the choice is recorded on `StudyPlan.constraint_resolution`. The gap stays visible either way — resolution records intent, it does not paper over the math. | spec §Stage-8; FR-F (let the user choose) |

### M. In-system execution loop (Stage 9)

| # | Decision | Choice | Grounding |
|---|----------|--------|-----------|
| M1 | Sessions are spaced + interleaved | `execute.next_session` serves **due reviews first** (from the spacing schedule), then fills with **new** items (plan sequences, then the bank) the learner hasn't seen, and interleaves so consecutive items avoid the same concept. No downloads — practice happens in-system (FR-G1). | spec §Stage-9; build-plan Phase 4 |
| M2 | Grade once, reused | The single-item grader was extracted from `administer` (`grade_item`) and shared by Stage 5 and Stage 9, so objective/open-ended grading lives in one place. | DRY; spec §Stage-5/9 |
| M3 | Record → reschedule → track | `execute.record_session` grades each answer, accrues calibration, **reschedules** the item via the spacing engine (Track A), and updates `LearnerState.progress` (`reviewed_total`, `sessions`, per-concept seen/correct, `last_session_at`). File-based loop (E2), CLI `study` / `record-session`, and a web Study page (step 5). | spec §Stage-9 ("track progress and reschedule"); philosophy §8 |

## 2026-06-29 — Phase 5 self-improvement loop

### N. Proposals generator & inbox (Loop 23)

| # | Decision | Choice | Grounding |
|---|----------|--------|-----------|
| N1 | New artifact: `Proposal` | A `Proposal {id, kind, subject, summary, rationale, evidence_refs[], change, status, created_at, decided_at, decision_note}` is added as a first-class knowledge-layer entity (spec §3 named the inbox but no entity). Stored as a diffable list at `proposals/inbox.json`. | spec §2.2 / §ratified-promotion; philosophy §8 |
| N2 | Three evidence sources | The generator proposes: **promote_prompt_version** (a non-current template whose `acceptance_rate` beats current by ≥0.1 over ≥5 attempts), **add_dependency_edge** (an edge recurring ≥2× in `proposals/dependency-inbox.jsonl` from H4), **recalibrate_difficulty** (a concept whose items' calibrated observed-difficulty band disagrees with its `difficulty_prior`, ≥3 items each seen ≥3×). Each carries `evidence_refs` and a concrete `change` dict. Thresholds are stated assumptions. | spec §ratified-promotion (the three named examples); philosophy §11 (cite evidence) |
| N3 | Generate-only, never apply | `proposals.generate` only **writes** proposals (idempotent against open ones by `(kind, change)` signature). It never mutates a doc/config/registry — applying is the human-gated Loop 24. | philosophy §8 (never self-corrupting) |

### D. Deferred (not built in Phase 0, per the build plan)

The **proposals engine (Phase 5)** remains — the capstone self-improvement loop with the
human-gated proposals inbox (it will consume `proposals/dependency-inbox.jsonl` from H4).
Already built since Phase 0: web-search harvesting (Phase 2, G5), the dependency map (Phase 3,
H), dependency-aware diagnosis + adaptive sampling (Phase 3, I/J), the spacing engine, honest
time math, and the in-system execution loop (Phase 4, K/L/M), plus the web UI (F). Out of scope entirely: multi-user,
accounts, downloads, token budgeting, gamification, lecture transcription.
