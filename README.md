# StudyBuddy

A personal-first adaptive study system. It ingests course and exam material, runs an
intelligent diagnostic to find where understanding actually breaks down, and produces an
adaptive, source-linked study plan. **Claude is the semantic engine; a deterministic
pipeline scopes and drives it.**

The design is authoritative and lives in [`docs/`](docs/) — read it before building.
`CLAUDE.md` states the standing rules. Decisions made while building (where the docs are
silent) are recorded in [`docs/DECISIONS.md`](docs/DECISIONS.md).

## The knowledge layer is the product

Behavior lives in versioned, human-readable artifacts under git, not buried in code. The
app is rebuildable from these directories:

| Directory | Holds |
|-----------|-------|
| `concepts/` | The concept model per subject (`<subject>.json`): topic hierarchy + dependency graph |
| `items/` | The item bank: every question (retrieved/adapted/generated) with provenance, answer key, calibration |
| `prompts/` | The prompt registry: one versioned template per Claude call (`<task>/<version>.json` + `index.json`) |
| `heuristics/` | The heuristics config: difficulty scale, gap thresholds, weighting, sampling + stopping rules — data, not code |
| `runs/` | Append-only run log (`runlog.jsonl`) + raw input/output blobs (`blobs/`) — the evidence surface |
| `learner/` | Learner state: intake, diagnostic results, gap profile, study plan, progress, spacing schedule |
| `proposals/` | Reserved (Phase 5): the human-gated proposals inbox for evolving foundational artifacts |

## Code

The pipeline is a small Python package (`studybuddy/`), UI-agnostic, driven by a CLI
harness. Every Claude call goes through one validated wrapper: versioned template +
structured input → API → strict-JSON output validated against the call's schema → one
retry on malformed → a `RunLogEntry` appended every time.

## Setup

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # then set ANTHROPIC_API_KEY
pytest
```

## Build status

Built in the order set by [`docs/study-system-build-plan.md`](docs/study-system-build-plan.md).
Currently in **Phase 0** (foundation: knowledge layer + validated Claude-call wrapper).
