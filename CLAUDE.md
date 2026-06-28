# CLAUDE.md

## Project
A personal-first adaptive study system. It ingests course and exam material, runs an intelligent diagnostic to find where understanding actually breaks down, and produces an adaptive, source-linked study plan. Claude is the semantic engine; a deterministic pipeline scopes and drives it.

## Source of truth (read these)
The design lives in `docs/`. Treat them as authoritative, in this priority order:

1. `docs/study-system-design-philosophy.md`: the why and the governing principles. Highest authority. When anything is ambiguous, this decides.
2. `docs/study-system-requirements.md`: what the system must do.
3. `docs/study-system-spec.md`: architecture, data model, pipeline stages, and the Claude-call contracts.
4. `docs/study-system-flowcharts.md`: the pipeline and the self-improvement loop, as diagrams.
5. `docs/study-system-build-plan.md`: the execution order. Build in this order.

At the start of a build session, read the philosophy and the build plan, plus the spec sections relevant to the current task.

## Standing rules
- Retrieve before you generate. Pull real questions from the uploaded material and web search first, adapt them second, and generate from scratch only to fill genuine gaps.
- One scoped Claude call per job. Never dump everything at the model and hope.
- Deterministic code decides what to ask and how much. Claude decides meaning and produces the artifact. Keep that boundary clean.
- Every Claude call takes structured input and returns strict JSON, validated against the call's schema, with a retry on malformed output, and it writes a run-log entry.
- The knowledge layer is plain text and JSON under git, and it is the product. Behavior lives in the concept model, prompt registry, heuristics config, and item bank, not buried in code. The app must be rebuildable from these.
- Self-improvement runs on two tracks. Observations (item calibration, concept-map confidence, the run log) write back automatically. Any change to the foundational docs goes through a human gate: propose it into the proposals inbox, never edit it silently. A proposal that does not honor the design principles is rejected even when the local metric looks good.

## Working method
- Follow the build plan phase by phase. Do not jump ahead.
- One task per loop. Get it working, then stop so it can be committed.
- Use plan mode for any non-trivial change. Propose the plan and wait for approval before editing.
- Do not build the out-of-scope items: multi-user, accounts, downloads, token budgeting, gamification, or lecture transcription.

## Start here
Begin at Phase 0 of the build plan: initialize the knowledge-layer directories, define the data model, and build the validated Claude-call wrapper. Then proceed to the Phase 1 walking skeleton, the thin end-to-end slice that gets you a usable study plan from a real exam.
