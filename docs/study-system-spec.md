# Adaptive Study System: Technical Spec (v1)

*Builds on the requirements doc. Adds one new architectural pillar: a self-improving, living-docs knowledge layer (Section 2). Everything else turns the requirements into concrete data structures, pipeline stages, and Claude-call contracts. Where this spec and the requirements doc disagree, this spec wins, since it is the more detailed source of truth.*

## 1. System shape: four layers

The central idea, and the thing that makes the system both self-improving and rebuildable, is an inversion: the running app is downstream of the docs. The docs are primary. Behavior lives in versioned, human-readable artifacts (concept models, prompt templates, a calibrated item bank, heuristic config), not buried in code. The app reads from those artifacts and writes structured feedback back to them.

1. **Knowledge layer (durable, versioned, self-improving).** The source of truth. Specs, concept models, prompt templates, the calibrated item bank, heuristic config, learner state, and an append-only run log. Plain text and JSON under version control. This is what "the fundamental docs improving themselves" refers to, and it is the product. The app is disposable.
2. **Orchestration layer (deterministic).** The pipeline. Reads from the knowledge layer, sequences phases, makes every what and how-much decision, validates Claude's output, and writes feedback back to the knowledge layer.
3. **Intelligence layer (Claude, scoped calls).** Bounded semantic jobs. Each call is a contract: structured input, strict structured output. Retrieval-first means generation is a fallback here, not the default.
4. **Experience layer (runtime).** The in-system interface the user works through. Holds little state of its own, derives from the knowledge layer.

## 2. The self-improving knowledge layer

This is the new pillar. It is what lets the system get better as you use it and gives you a healthy way to rebuild and learn from it.

### 2.1 The artifacts (each is a versioned file with its own changelog)

- **`requirements.md`, `spec.md`** — design source of truth, mostly human-edited.
- **Concept model** (`concepts/<subject>.json`) — the topic hierarchy plus the dependency graph. Living: nodes and edges get added and their confidence refined as material is ingested and as diagnostics confirm prerequisite relationships.
- **Item bank** (`items/`) — every question, whether retrieved, adapted, or generated, as a record carrying provenance, concept tags, format, answer key, grading spec, and accruing calibration stats. This is the asset that compounds. A real textbook problem with a vetted answer and a growing track record is worth far more than a freshly invented one.
- **Prompt registry** (`prompts/`) — every Claude-call template, versioned, each with its input and output contract and its few-shot examples. Improvements are diffable, so you can see exactly what changed and why it worked.
- **Heuristics config** (`heuristics/`) — the difficulty scale, gap-classification thresholds, weighting coefficients, sampling rules, and stopping rule, all expressed as data rather than hardcoded, so they can be tuned and versioned.
- **Run log** (`runs/`) — append-only record of every pipeline run and every Claude call: inputs, the template version used, raw output, validation result, whether the output was accepted, edited, or rejected, and any human override. This is the "things I can learn from it" surface.
- **Learner state** (`learner/`) — diagnostic results, gap profile, study plan, progress, and the spacing schedule.

### 2.2 How the docs improve themselves: two mechanisms, deliberately separated

This separation is the most important design decision in the system. A system that silently rewrites its own foundational docs drifts into incoherence. So improvement runs on two tracks.

- **Automatic accrual (no human in the loop).** Runtime facts write back continuously and safely. Every answer updates an item's calibration stats (times seen, correct rate, observed difficulty, discrimination). Concept-map edge confidence updates as evidence accumulates. The run log appends. These are observations, not design changes, so they are safe to apply automatically.
- **Ratified promotion (human in the loop).** The system never edits its own design docs unsupervised. Instead it *proposes* evidence-backed changes into a proposals inbox, and you accept or reject. Examples: "items tagged capital structure consistently score far harder than their labels, propose recalibrating the difficulty scale," or "prompt template v4 produced 30 percent fewer rejected questions, propose promoting it to default," or "diagnostics repeatedly show concept X failing whenever Y is shaky, propose adding a dependency edge Y to X." Accepted proposals version the relevant artifact forward with a changelog entry.

The reason for the split: auto-accrual keeps the system learning fast where the data is trustworthy, while ratification keeps the foundational docs trustworthy and rebuildable. You can always reconstruct the system from a known-good version, and the changelogs plus run log give you a narrated history of what changed and why.

### 2.3 Rebuild story

Everything in the knowledge layer is git-tracked plain text and JSON. To rebuild, point Claude Code at the current knowledge layer and regenerate the runtime. Because behavior lives in the concept model, prompt registry, heuristics config, and item bank rather than in code, a rebuild reconstitutes the same system. The app is replaceable, the knowledge layer is not.

## 3. Data model (entities and key fields)

- **Material:** id, type (syllabus, textbook, section, notes, objectives, recording), source, raw_ref, ingested_at, extracted_concepts[], harvested_items[].
- **Concept:** id, subject, name, parent_id, dependency_edges[] (each: other_concept_id, relation depends_on or prereq_of, confidence), source_refs[] (page or section pointers), difficulty_prior.
- **Item (question):** id, concept_ids[], format (mc, numeric, short, essay, application), stem, options (if applicable), answer_key, rationale, provenance (retrieved, adapted, or generated, plus source ref), grading_spec, template_version (if generated), calibration {times_seen, correct_rate, observed_difficulty, discrimination, confidence, updated_at}.
- **DiagnosticResult:** id, learner_id, item_responses[] (item_id, response, correct, time_spent, felt_lucky_flag), per_concept_rollup, gap_classification[] (concept_id, gap_types[], confidence), generated_at.
- **GapProfile:** learner_id, entries[] (concept_id, gap_type, severity, evidence_refs[], status hypothesis, confirmed, or resolved), updated_at.
- **StudyPlan:** learner_id, topics[] (concept_id, time_block, source_links[], item_sequence[] ordered foundational to depth to synthesis, review_schedule[]), total_time_estimate, constraint_resolution (compress or extend), version.
- **PromptTemplate:** id, task, version, input_schema, output_schema, body, examples[], metrics {acceptance_rate, ...}.
- **HeuristicsConfig:** version, difficulty_scale, gap_thresholds, weighting_coeffs, sampling_rules, stopping_rule.
- **RunLogEntry:** id, phase, template_version, input_ref, raw_output_ref, validation_status, disposition (accepted, edited, rejected), human_override, ts.

## 4. The pipeline (deterministic orchestration, stage by stage)

Each stage names what deterministic code does, which Claude calls fire, and what gets written back to the knowledge layer.

**Stage 1, Ingest and harvest.** Deterministic: accept inputs, route by type, store Material records. Claude `extract_structure` (raw material in, candidate concept hierarchy out) and `harvest_items` (material in, the real questions and answers already present in that material out, tagged to concepts). Always run a web search, sized to standardization inferred from the syllabus and question style, to pull additional real items. Writeback: Material, candidate Concepts, retrieved Items with provenance. This stage populates the item bank with real questions before anything is generated.

**Stage 2, Build and refine concept model.** Claude `build_dependency_map` (candidate concepts plus sampled items in, dependency edges with confidence out). Deterministic: merge into the existing concept model by accruing confidence rather than overwriting, and route low-confidence new edges to the proposals inbox. Writeback: concept model.

**Stage 3, Intake interview.** Deterministic: present the extracted topic structure back to the user, then ask scoped, branching questions for exam format, total study time, daily availability, baseline, and per-topic confidence. A light Claude pass may phrase follow-ups. Writeback: learner state.

**Stage 4, Compose the diagnostic.** Deterministic: compute weighting from the three signals (self-assessment, structural inference, difficulty priors), decide the item mix (hard on declared weaknesses, confidence stress-tests on declared strengths, hidden-gap probes), and the format mix (component formats building toward the real exam format). Source items retrieval-first: pull real items matching the needed concept, difficulty, and format; `adapt_item` when coverage is partial; `generate_item` only to fill holes; `verify_item` on anything adapted or generated. Writeback: new Items with provenance, the assembled diagnostic of roughly twenty questions.

**Stage 5, Administer and grade.** Deterministic: serve items, collect responses, record time and the felt-lucky flag, and give feedback in a batch after all questions are answered. Objective formats auto-grade; open-ended uses `grade_response` against the grading spec (score, reasoning, and which concept facets were missed). Writeback: DiagnosticResult; item calibration stats auto-update.

**Stage 6, Diagnose.** Deterministic: run the gap-classification heuristics, interpreted inside the dependency map so a miss at a dependent layer points back to the prerequisite, using material-aware thresholds from the heuristics config. Claude `interpret_gaps` (structured per-concept rollup plus dependency context in, a semantic read of why each gap exists, as hypotheses with confidence, out). Writeback: GapProfile entries as hypotheses.

**Stage 7, Adaptive sampling.** Deterministic: choose the next small strategic batch (weakest area, the boundary between two shaky concepts, and verification of something gotten right), statistically considered rather than uniform increments, and apply the stopping rule against a confidence threshold on the gap profile. Source and verify items as in Stage 4, administer and grade as in Stage 5, then re-run Stage 6 to confirm or contradict and update weights. Loop until the stopping rule fires. After each batch, the FR-G2 control lets the user ask for more, fewer, or a shift in focus, and that input overrides priors. Writeback: GapProfile status transitions, calibration accrual.

**Stage 8, Time budget and plan.** Deterministic: compute a realistic time-to-comprehensive with a spacing and retention model (SM-2 style is a fine basis), compare against available time, surface the honest gap, and let the user choose to compress or extend. The deterministic engine owns the spacing and interleaving schedule; Claude `compose_plan` writes the human-facing topic content with source links and review cadence. Writeback: StudyPlan.

**Stage 9, Execute and feedback.** Deterministic: run the plan in-system with no downloads, serve spaced and interleaved items, track progress, and reschedule through the spacing engine. Continuous writeback: item calibration, learner progress, run log.

## 5. Claude-call contracts (the scoped jobs)

Every call is bounded, takes structured input, and must return strict JSON validated against a schema, with a retry on malformed output. Templates live versioned in the prompt registry. Retrieval-first means adapt, generate, and verify are fallbacks, not the main path.

- **extract_structure:** material chunk in, candidate concept hierarchy out.
- **harvest_items:** material chunk in, real questions and answers found in it, tagged to concepts, out.
- **build_dependency_map:** concepts plus sampled items in, dependency edges with confidence out.
- **adapt_item:** one real item plus a target concept, difficulty, and format in, an adapted item out.
- **generate_item:** one concept, one difficulty, one format, plus source context in, a fresh item out.
- **verify_item:** an item in, a verdict on whether it tests the intended concept, whether the key is correct, and whether it is unambiguous, out.
- **grade_response:** an open-ended response plus its grading spec in, a score with reasoning and missed facets out.
- **interpret_gaps:** per-concept rollup plus dependency context in, gap hypotheses with confidence out.
- **compose_plan:** confirmed gap profile plus sourced item sequences and constraints in, the human-facing topic-by-topic plan content out.

## 6. Output validation and the verification tax

Every Claude output is JSON checked against its schema, with reject-and-retry on malformed output. For items specifically, the `verify_item` gate checks concept fit, key correctness, and ambiguity. Retrieved items mostly skip this gate because they arrive already vetted, which is exactly where retrieval-first pays off: less to verify, fewer wrong answer keys, lower cost.

## 7. Open questions carried into the build

- Concrete numbers: difficulty-scale granularity, gap thresholds, weighting coefficients, and the stopping-rule confidence target. Start with sensible defaults and let calibration data move them through ratified promotion.
- Storage and runtime: local files plus git is the v1 default; a database can come later if the item bank outgrows it.
- The open-ended grading rubric format.
- Where exactly the line sits between safe auto-accrual and changes that require ratification.

## 8. Next step

Flowcharts. Render the pipeline (Stages 1 through 9) and, separately, the knowledge-layer feedback loops (auto-accrual versus the ratified-promotion proposals inbox), since those two diagrams together are the system. After that, the todo list and build plan for Claude Code.
