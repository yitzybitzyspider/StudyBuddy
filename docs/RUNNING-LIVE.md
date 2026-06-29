# Running StudyBuddy: safe testing + the live API key

There are two ways to run the pipeline. **Start with offline mode** — it needs no API key,
makes no network calls, and costs nothing, so it's the safe way to test the whole system.
Switch to a live key only when you want real Claude output.

> **Never put an API key in a file that gets committed, or paste it into a chat/issue/PR.**
> The app reads the key only from the environment variable `ANTHROPIC_API_KEY`. `.env` is
> already git-ignored. If a key is ever exposed, disable or roll it in the Console immediately.

---

## A. Offline self-test (no key, no network)

`STUDYBUDDY_OFFLINE=1` makes every Claude call return a canned, schema-valid response, so the
full deterministic pipeline runs end to end and produces real artifacts.

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

export STUDYBUDDY_OFFLINE=1            # <-- no API key needed; nothing leaves the machine

studybuddy init
studybuddy ingest --subject finance --type textbook examples/finance-chapter.md
studybuddy ingest --subject finance --type exam      examples/finance-exam.md
studybuddy show-topics --subject finance

# intake: write the template, fill a couple of fields, then ingest it
studybuddy intake --subject finance
#   -> edit learner/learner_default/intake.template.json (set exam_format, hours, confidences)
studybuddy intake --subject finance --answers learner/learner_default/intake.template.json

# diagnostic: compose, fill in your answers, then grade
studybuddy compose-diagnostic --subject finance --size 5
#   -> edit learner/learner_default/diagnostic.answers.json (put answers in each "response")
studybuddy administer --subject finance
studybuddy diagnose --subject finance
studybuddy plan --subject finance

cat learner/learner_default/study-plan.md     # the deliverable
studybuddy show-runlog                         # every call, schema-checked + logged
```

You can also steer a follow-up batch: `studybuddy steer --subject finance --more`
(or `--fewer`, or `--shift "Net Present Value"`).

Nothing in offline mode touches the network or the key — it's purely for exercising the
plumbing. The questions/answers are a fixed finance example, not real Claude output.

---

## B. Live run (real Claude) — with the key kept disabled until you need it

Keep the key **disabled by default** in the Anthropic Console and only enable it for the
duration of a run. That's your on/off approval gate.

1. **In the Console** (Settings → API keys): keep the key **Disabled**. Optionally put it in
   a Workspace with a low spend limit as a second guardrail.
2. **When you want to run live**, enable the key, then in your shell (not in any file):

   ```sh
   unset STUDYBUDDY_OFFLINE                 # turn offline mode OFF
   export ANTHROPIC_API_KEY=sk-ant-...      # paste in the terminal only; never commit it
   ```

   The proxy/base URL (`ANTHROPIC_BASE_URL`) is already configured in this environment, so no
   other setup is needed.
3. **Run the same sequence** as section A (without `STUDYBUDDY_OFFLINE`). Start with one call
   to confirm connectivity:

   ```sh
   studybuddy run-call extract_structure -i examples/extract_structure.input.json
   studybuddy show-runlog
   ```

4. **When you're done**, disable the key again in the Console, and clear it from the shell:

   ```sh
   unset ANTHROPIC_API_KEY
   ```

---

## C. Web UI (browser, full flow)

A local web app over the same pipeline. Run it on your own machine:

```sh
git pull
pip install -e ".[web]"
export ANTHROPIC_API_KEY=sk-ant-...     # live;  or:  export STUDYBUDDY_OFFLINE=1  (no key)
studybuddy serve                         # -> http://127.0.0.1:5000
```

Then in the browser: create a subject → upload an exam/chapter → intake → compose & take the
diagnostic → read your plan, with more / fewer / shift steering. With `STUDYBUDDY_OFFLINE=1`
you can click through the entire UI without a key (canned responses); with `ANTHROPIC_API_KEY`
set it's fully live. `studybuddy serve --port 8000 --root /path/to/knowledge-layer` to change
the port or location.

---

### Notes on credentials

- The SDK reads, in order: `ANTHROPIC_API_KEY` (sent as `x-api-key`), then
  `ANTHROPIC_AUTH_TOKEN` (an OAuth bearer token), then an `ant auth login` profile. Set **one**
  — setting both `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` makes the API reject the request.
- A plain `sk-ant-...` API key is the simplest path. (OAuth bearer tokens additionally need an
  `anthropic-beta: oauth-2025-04-20` header on `/v1/messages`, which the SDK does not add for you.)
- The Admin API `GET /v1/organizations/api_keys/{id}` returns **metadata only** (name, status,
  workspace) — it never returns the secret value, so it can't be used to fetch a usable key.
