# Adaptive Study System: Requirements (v1)

*Working title. Personal-use build first, architected so other users can run it later.*

## 1. Purpose

A study tool that ingests course and exam material, runs an intelligent diagnostic to find where a student's understanding actually breaks down, and produces an adaptive, source-linked study plan grounded in learning science. Claude supplies the semantic intelligence. A deterministic scaffolding layer structures the work, makes the decisions repeatable, and keeps Claude's calls scoped and efficient.

The first user is you, studying for Haas exams. Everything is built for a single motivated user who can give the system real feedback, then generalized later.

## 2. Core architectural principle

The system is not "send everything to Claude and hope." It is a deterministic pipeline that does the thinking about *what to ask*, then hands Claude tightly scoped jobs and consumes structured output.

Responsibilities split as follows.

Deterministic layer owns:
- Orchestration and sequencing of every phase
- The intake interview logic and branching
- The heuristic framework for interpreting diagnostic results (gap types, weighting rules)
- Adaptive sampling decisions (how many questions next, on what, when to stop)
- Time and effort budgeting math
- Spacing and interleaving rules for the study plan
- The input and output contract for every Claude call

Claude layer owns:
- Reading messy source material and extracting the concept hierarchy
- Building the material-specific concept dependency map
- Generating questions that test a given concept at a given difficulty and format
- Judging whether a generated question actually tests the intended concept
- Analyzing answer patterns semantically inside the deterministic framework
- Writing the human-readable study plan content

The contract is explicit: deterministic code decides *what* and *how much*, Claude decides the *meaning* and produces the artifact. This is what keeps the system intelligent, consistent, and cheap.

## 3. Scope

In scope for v1:
- Single-user, local-first, runs through an in-system interface (no downloads, no accounts)
- All listed input types and exam formats
- Always-on web search, sized to how standardized the exam is
- Intake interview, concept mapping, diagnostic, adaptive follow-up, study plan
- Topic-by-topic study plan with time blocks, source links, question sequences, and review cycles

Explicitly out of scope for v1 (deferred, not cut):
- Multi-user, accounts, authentication for other people
- Downloads and exports of any kind
- Token-budget optimization as a hard constraint (architecture stays token-aware, but no per-user budgeting yet)
- Gamification and performance incentives
- Lecture-recording transcription (accept it as a possible input later, deprioritize for now)
- Edge-case "in the weeds" question handling

## 4. Functional requirements

### A. Input and intake
- **FR-A1:** Accept any mix of material: syllabus, learning objectives or outcomes, textbook, textbook sections, lecture notes, and optionally lecture recordings. More material always allowed, none of it individually required.
- **FR-A2:** Accept an optional past exam, ideally with questions, answers, and explanations. Strongly preferred but not required.
- **FR-A3:** Always run a web search for supplementary and similar questions. Scale the effort to how standardized the exam appears: broad for standardized tests with public material, light for professor-specific exams where the best source may be a forum thread. Infer standardization from the syllabus and the style of the questions.
- **FR-A4:** Run a short, smart intake interview rather than a long form. Ask only what is needed and infer the rest.
- **FR-A5:** Before asking what the user is weak on, extract the topic structure from the material and present it back, so the user chooses from concrete topics and subtopics instead of answering "what don't you know" blind.
- **FR-A6:** Intake must capture, by asking or inferring: final exam format (essays, multiple choice, numerical, mixed), total study time available, daily availability, rough baseline, and per-topic confidence.

### B. Material processing and concept mapping
- **FR-B1:** Normalize all inputs into a single topic hierarchy (chapters, subsections, concepts).
- **FR-B2:** Build a material-specific concept dependency map capturing which concepts gate which others. Finance example: time value of money, then discounting mechanics, then company analysis, then synthesis into a valuation model.
- **FR-B3:** Keep every concept linkable back to its source material (textbook pages, lecture notes, any handbook allowed in the exam), so the plan and questions can reference the original.

### C. Diagnostic engine
- **FR-C1:** Start with an initial diagnostic batch of roughly twenty questions, then narrow and refocus through adaptive sampling.
- **FR-C2:** Weight the diagnostic using three signals together: the user's self-assessment, the system's inference from material structure, and typical difficulty patterns for the subject. Do not take self-assessment at face value, and do not ignore it. People partially know their own gaps.
- **FR-C3:** Compose the diagnostic as a deliberate mix: harder questions on declared weaknesses, confidence stress-tests on declared strengths, and probes for gaps the user did not flag. Actively test what the user thinks they know to confirm or disprove it.
- **FR-C4:** Handle format mismatch. If the real exam is, say, two long essays, do not only drill essays. Break the skill into components (multiple choice, short answer, numerical, application) and build back up to the full format, because the best way to learn a format is often not to practice only that format.
- **FR-C5:** Deliver diagnostic feedback in a batch after all questions are answered, not after each question, to preserve a true test-like read of actual knowledge.

### D. Diagnostic analysis (deterministic heuristics, material-aware)
- **FR-D1:** Before generating any follow-up, run a deterministic breakdown of results into gap types. Starting set: foundational gap (multiple easy questions wrong on a topic), depth gap (easy and medium right, hard wrong), overconfidence (a harder question right where easy ones on the same concept were missed, or a likely lucky guess), breadth gap (uneven across topics), speed gap (blanks or rushing).
- **FR-D2:** Interpret every gap inside the concept dependency map. A miss at a dependent layer points back to the prerequisite. Failures applying DCF point to rebuilding discounting before application, not just "redo DCF."
- **FR-D3:** Make the heuristics material-specific. Some material has multi-step concepts where one step is foundational and another is depth, and the breakdown must reflect that structure rather than a generic template.
- **FR-D4:** As follow-up answers come in, re-run the analysis. Confirm or contradict the prior diagnosis and update the weights accordingly.

### E. Adaptive sampling
- **FR-E1:** Do not generate the full study guide up front. After the diagnostic, generate only the next small, strategic batch needed to prove or disprove the current theory of where the gaps are.
- **FR-E2:** Choose that batch intelligently, not by uniform small increments. Target the weakest area, the boundary between two shaky concepts, and verification of something the user got right. Sampling should be statistically considered, not just "a few more each time."
- **FR-E3:** Repeat until the system is confident it has located the gaps, then unlock the fuller study sequence.

### F. Study plan generation
- **FR-F1:** Organize the plan topic by topic, since that is how students refer back to material.
- **FR-F2:** For each topic, provide suggested time blocks, links to the relevant source material, a question sequence that moves foundational to depth to synthesis, and review cycles.
- **FR-F3:** Sequence using spaced repetition and interleaving: do not drill the same concept twice in a row, mix related concepts, and space reviews over time.
- **FR-F4:** For every generated question, return which source pages or sections support it.

### G. In-session experience and feedback loop
- **FR-G1:** Everything runs inside the system. The experience must be usable and friendly first. No downloads in v1.
- **FR-G2 (priority):** After each batch, give the user an immediate control to ask for more questions like these, fewer, or a shift in focus. You do not always know what you do not know until you try, and trying teaches you about yourself. This control also gives the system permission to override the initial self-assessment when the evidence contradicts it.

### H. Time and effort estimation
- **FR-H1:** From total time, daily availability, material scope, and exam format, compute a realistic time-to-comprehensive using spacing and retention principles. An Anki-style spaced-repetition model is a reasonable basis.
- **FR-H2:** Be honest about the result. If they have 56 hours and comprehensive coverage needs roughly 80, say so, and let them choose which constraint to relax: compress the material or extend the window. Set expectations up front, not halfway through.
- **FR-H3:** Let the time reality feed back into formatting: how many questions, which to ask, and how much depth the plan can realistically include.

## 5. Non-functional requirements
- **NFR-1:** Token-aware by design. The deterministic scaffolding exists partly so Claude is asked to do one bounded thing at a time rather than five things at once.
- **NFR-2:** Modular enough that the single-user core can later support multiple users without a rewrite.
- **NFR-3:** Source-linkability is a first-class property throughout, not an afterthought.
- **NFR-4:** Determinism where it counts. The same inputs and answers should drive the same structural decisions, with Claude supplying the semantic content inside that structure.

## 6. Open questions for the spec phase
- The exact adaptive sampling algorithm and its stopping rule (what "confident enough" means quantitatively).
- The precise difficulty scale and how difficulty is assigned to each question and concept.
- How lecture recordings are handled if included (transcribe up front, or defer).
- The concrete data structures and schemas for material, concept map, question, diagnostic result, and study plan.
- The full heuristic ruleset for gap classification per material type.

## 7. Next step
Move to the spec: the data structures and schemas, the input and output contract for each Claude call, and the heuristic framework in concrete form. Then flowcharts, then build in Claude Code.
