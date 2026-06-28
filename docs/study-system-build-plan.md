# Adaptive Study System: Build Plan (v1)

*The doc that turns the philosophy, requirements, spec, and flowcharts into executable work for Claude Code. The order matters more than the list. Read the sequencing logic first.*

## How to drive this with Claude Code

- Keep the four knowledge-layer docs (philosophy, requirements, spec, flowcharts) plus a short `CLAUDE.md` in context for every session, so the agent builds against the source of truth.
- One task per loop. Get it working, commit, then move on. Committing every working state makes rollback free when a session goes sideways.
- Use plan mode before any non-trivial change, review the diff, then accept.
- Start a fresh session per phase to avoid context drift, and re-load the docs at the top of each.
- Suggested starting stack: a Python backend for the pipeline (the Anthropic SDK, mature PDF and text parsing, easy JSON and file handling), the knowledge layer as JSON and markdown under git, driven first by a small CLI harness and later by a minimal local web UI as a thin layer on top. This is a starting suggestion, not a constraint; Claude Code can swap it.

## The sequencing logic (read this before the tasks)

Four rules govern the order, and all four come straight from the design philosophy.

1. **Thin vertical slice first.** Build the dumbest possible version of every stage end to end before deepening any one of them, so you reach a working personal tool fast and let real use decide what to improve. This is Principle 12.
2. **Cheap, high-leverage things go early even when simple.** Run logging, the more, less, or shift control, and calibration accrual are cheap to add and you want their data and their leverage from day one.
3. **Hard, data-hungry things go late.** Real adaptive sampling, dependency-aware diagnosis, and the self-improvement proposals engine all need the skeleton working and real answer data to exist first. Building them early would mean faking a rigor the inputs cannot yet support, which Principle 9 forbids.
4. **Lean on the human in the loop the whole way.** Until a piece is automated well, your judgment covers the gap on purpose. This is Principle 7.

## Phase 0: Foundation, the knowledge layer and the glue

The knowledge layer is the product and the validated Claude-call wrapper is the most-reused piece of infrastructure in the system. Build these once and build them right.

- [ ] Initialize the repo and git. Create the knowledge-layer directories (`concepts/`, `items/`, `prompts/`, `heuristics/`, `runs/`, `learner/`) and place the four docs at the top.
- [ ] Write a `CLAUDE.md` that points the agent at the four docs and states the standing rules: retrieval-first, one scoped Claude call per job, the deterministic-versus-Claude boundary, and strict JSON in and out.
- [ ] Define the data model as types or schemas from spec section 3 (Material, Concept, Item, DiagnosticResult, GapProfile, StudyPlan, PromptTemplate, HeuristicsConfig, RunLogEntry).
- [ ] Build the Claude-call wrapper: it takes a versioned template plus structured input, calls the API, validates the output JSON against that call's output schema, retries on malformed output, and appends a RunLogEntry every time. Every stage depends on this.
- [ ] Stand up the prompt registry (versioned template files) and the heuristics config as a data file with sensible default numbers (difficulty scale, gap thresholds, weighting coefficients, a placeholder stopping rule).
- [ ] Build a small CLI harness to invoke pipeline steps. The pipeline is UI-agnostic, so the UI comes later.

Milestone: you can call Claude through the validated wrapper, get schema-checked JSON back, and every call is logged. The knowledge layer exists in git.

## Phase 1: Walking skeleton, the thin end-to-end slice

The smallest thing that produces real evidence. Every step here is the dumbest version that works. This is the milestone that matters most, because once it exists, everything after it is earned by using it.

- [ ] Ingest, thin (Stage 1): accept a pasted or PDF past exam and a textbook chapter, and run `extract_structure` to get a flat topic list. Defer the dependency map.
- [ ] Harvest, thin (Stage 1): run `harvest_items` on the uploaded exam and chapter to pull the real questions and answers already in them, tagged to topics. Defer web search to Phase 2.
- [ ] Intake, thin (Stage 3): show the topic list back, then ask the five questions (exam format, total time, daily availability, baseline, per-topic confidence).
- [ ] Compose diagnostic, thin (Stage 4): a crude weighted pull of about twenty items, retrieval-first from harvested items, with `generate_item` and `verify_item` only to fill gaps, and a basic mix of confidence stress-tests and hidden-gap probes.
- [ ] Administer and grade (Stage 5): serve the twenty, give feedback in a batch after all answers, auto-grade the objective items, and use `grade_response` for the open-ended ones.
- [ ] Diagnose, thin (Stage 6): run a basic gap classification (foundational, depth, overconfidence, breadth, speed) plus `interpret_gaps`, producing a flat gap profile with no dependency map yet.
- [ ] Plan, thin (Stage 8): use `compose_plan` to produce a topic-by-topic one-pager with source links and a foundational to depth to synthesis sequence. Defer the spacing engine and the time math; allocate roughly for now.
- [ ] more, less, or shift control (FR-G2): after the diagnostic, let yourself ask for more like this, fewer, or a shift in focus, and regenerate accordingly. It is cheap and central to the philosophy, so it goes in now.

Milestone: you can run a full cycle on a real Haas exam and get a usable study plan you can steer. You have a working personal tool.

## Phase 2: Sourcing and calibration, retrieval-first in full

Now that the loop works, make question sourcing strong and start banking the calibration data that compounds. This is Principle 4 and the automatic track of Principle 8.

- [ ] Add web search to harvesting (Stage 1), sized to how standardized the exam is, inferred from the syllabus and the question style.
- [ ] Build the item bank properly: provenance on every item (retrieved, adapted, or generated, plus source), concept tags, answer key, grading spec.
- [ ] Wire calibration accrual (Track A): every answer updates the item's times_seen, correct_rate, observed_difficulty, discrimination, and confidence, automatically and with no sign-off.
- [ ] Strengthen `adapt_item` so real questions get reused with new numbers and context, route everything adapted or generated through `verify_item`, and track the acceptance rate per template version.

Milestone: the diagnostic and practice pull mostly real, vetted questions, and the item bank gets sharper every session.

## Phase 3: Diagnostic intelligence, the dependency map and adaptive sampling

The genuinely hard, data-hungry part, deliberately placed after the skeleton works and after some calibration data exists.

- [ ] Build the concept dependency map (Stage 2, `build_dependency_map`), merging by accruing confidence, with low-confidence edges held for the proposals inbox built in Phase 5.
- [ ] Rewire gap interpretation (Stage 6) to read inside the dependency map, so a downstream miss points to the upstream prerequisite.
- [ ] Build real adaptive sampling (Stage 7): the next-small-batch logic (weakest area, the boundary between two shaky concepts, and verification of something gotten right), statistically considered rather than uniform, with a stopping rule against a gap-profile confidence threshold, looping back to Stages 5 and 6 until it fires.
- [ ] Make the gap heuristics material-aware, for multi-step concepts where one step is foundational and another is depth.

Milestone: the system narrows in on where your understanding actually breaks down, not just where your score dipped, and stops when it has enough signal.

## Phase 4: Plan and execution, the spacing engine and the in-system loop

Turn the one-pager into a real, livable study experience, and add the honest time math.

- [ ] Build the spacing and interleaving engine (SM-2 style) and the review scheduler.
- [ ] Build the time-budget reality check (Stage 8): compute a realistic time-to-comprehensive, compare it to available time, surface the honest gap, and let yourself choose to compress or extend.
- [ ] Build the in-system execution loop (Stage 9): serve spaced and interleaved items, track progress, and reschedule, all in-system with no downloads.
- [ ] Put the minimal local web UI on top of the pipeline. The pipeline already exists, so the UI is a thin, disposable presentation layer. Make it usable and friendly.

Milestone: you study inside the system day to day, and it manages spacing, sequencing, and your timeline honestly.

## Phase 5: Self-improvement loop, the proposals inbox and ratified promotion

The capstone. It comes last because it needs accrued data to propose from. The logging that feeds it started back in Phase 0.

- [ ] Build the proposals generator: evidence-backed suggestions to evolve the foundational docs (recalibrate the difficulty scale, promote a prompt version, add a dependency edge), each citing its run-log and calibration evidence.
- [ ] Build the proposals inbox and the accept-or-reject gate. Accepted proposals version the relevant artifact forward with a changelog entry; rejected ones stay in the run log so you can learn from them.
- [ ] Wire the philosophy test into the gate: a proposal that does not honor the design principles is rejected even when the local metric looks good.

Milestone: the system improves its own foundational docs through evidence plus your sign-off, and you can rebuild the whole thing from a known-good version at any time.

## What to deliberately not build yet

Straight from the spec's out-of-scope list, held back on purpose: multi-user, accounts, and authentication; downloads and exports; token-budget enforcement (stay token-aware through scoped calls, but do not build budgeting); gamification and incentives; lecture-recording transcription.

## The bar that matters

The definition of a working personal version is the end of Phase 1: paste a real exam and a chapter, take a diagnostic, get a usable topic-by-topic plan with source links, and steer it with more, less, or shift. Reach that, then let using it decide what comes next.
