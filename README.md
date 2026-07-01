# StudyBuddy — the engine behind [inleto.com](https://inleto.com)

An adaptive study platform. It ingests course and exam material, runs an intelligent
diagnostic to find where understanding **actually breaks down** (not just where the score
dipped), and produces an adaptive, source-linked study plan with spaced, interleaved
practice. **Claude is the semantic engine; a deterministic pipeline scopes and drives it.**

The design is authoritative and lives in [`docs/`](docs/) — read it before building.
`CLAUDE.md` states the standing rules. Every decision made while building (where the docs
were silent) is recorded in [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Quickstart — local, single user (no accounts, plain files)

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest                                  # 166 tests, fully offline

# try the whole flow with zero API cost:
STUDYBUDDY_OFFLINE=1 python -m studybuddy serve
# live (uses your Anthropic key; Haiku keeps it cheap):
cp .env.example .env                    # set ANTHROPIC_API_KEY, STUDYBUDDY_MODEL
python -m studybuddy serve
```

Windows: `.\run-cheap.ps1` does the live-cheap setup in one command.

## Platform mode — multi-user (Supabase Postgres + Auth)

Accounts, per-user data isolation enforced by Postgres row-level security, same engine:

```sh
pip install -e ".[platform]"
export STUDYBUDDY_BACKEND=supabase
export SUPABASE_URL=https://<ref>.supabase.co
export SUPABASE_ANON_KEY=<anon key>
export FLASK_SECRET_KEY=<long random string>
gunicorn "studybuddy.web:create_app()" --bind 0.0.0.0:8000
```

Schema + RLS migrations live in the Supabase project (see DECISIONS §R). Deployment is one
Render Blueprint (`render.yaml`); the landing page (`site/`) deploys to GitHub Pages.
The knowledge-layer *product* (prompt registry, heuristics, run log, proposals) stays as
git files on the server; only per-user data lives in the database.

## The knowledge layer is the product

Behavior lives in versioned, human-readable artifacts under git, not buried in code:

| Directory | Holds |
|-----------|-------|
| `concepts/` | The concept model per subject: topic hierarchy + dependency graph |
| `items/` | The item bank: every question (retrieved/adapted/generated) with provenance, answer key, calibration |
| `prompts/` | The prompt registry: one versioned template per Claude call + `index.json` naming the default |
| `heuristics/` | Difficulty scale, gap thresholds, weighting, sampling + stopping rules — data, not code |
| `runs/` | Append-only run log + raw input/output blobs — the evidence surface |
| `learner/` | Per-(learner, subject) state: intake, results, gap profile, plan, spacing schedule |
| `proposals/` | The human-gated inbox: the system proposes changes to its own foundations; you decide |

## How the pipeline thinks

1. **Ingest** — extract topics and harvest the *real* questions from your material
   (retrieval-first; generation is the last resort, always verified).
2. **Diagnose** — a short test, read inside the prerequisite map: a miss downstream points
   to the concept upstream. Gap types: foundational, depth, overconfidence, breadth, speed.
3. **Adapt** — short strategic batches (weakest gap, shaky boundary, verify a strength)
   until the gap profile is confident enough, with a hard stopping rule.
4. **Plan** — source-linked topics with honest time math (what comprehensive costs vs. the
   hours you have; you choose compress or extend).
5. **Study** — SM-2 spaced + interleaved practice in-system; every answer accrues item
   calibration automatically.
6. **Improve** — the system generates evidence-backed proposals about its own prompts,
   difficulty scale, and dependency map; a human gate (with a philosophy test that can veto
   even an accepted proposal) applies them.

Every Claude call goes through one validated wrapper: versioned template + structured input
→ strict-JSON output validated against the call's schema → one retry on malformed → a run-log
entry, every time.
