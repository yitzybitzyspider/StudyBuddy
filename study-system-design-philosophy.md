# Adaptive Study System: Design Philosophy (v1)

*This sits above the requirements and the spec. The requirements say what the system does, the spec says how, and this says why and according to what beliefs. It is the most durable layer in the knowledge stack and should change the least. Consult it when the requirements are silent, when a tradeoff has no obvious answer, and when judging whether a self-improvement proposal belongs. When the other docs do not settle a decision, this one does.*

## 1. The hard part moved upstream

AI has driven the cost of producing code toward zero, which relocates the whole challenge to knowing exactly what to build and being able to judge whether what got built is right. Treat code as cheap and replaceable, and spend the saved effort on clarity, scope, and taste. Typing is not where this project is won or lost.

## 2. The docs are the product, the app is disposable

Behavior lives in versioned, human-readable artifacts: the concept model, the prompt registry, the heuristics config, the item bank. It is not buried in code. You should be able to point Claude Code at the knowledge layer and reconstitute the running system at any time. The source of truth is text under version control, not the binary that happens to be running.

## 3. Deterministic scaffolding, semantic intelligence

A deterministic pipeline decides what to ask and how much. Claude decides meaning and produces the artifact. The boundary between the two is explicit and defended, because the failure mode on both sides is real: hardcode the meaning and it is brittle, hand the model the structure and it is inconsistent and expensive. Never dump everything at the model and hope.

## 4. Retrieve before you generate

Most exam material is not novel. Real questions already exist in the uploaded textbook's own problem sets, in past exams, and across the web, and they arrive better calibrated and with vetted answers. Pull real things first, adapt them second, and generate from scratch only to fill genuine gaps. Generation is the fallback, not the default, and treating it that way buys both quality and trust.

## 5. Diagnose understanding, not scores

The question is never just what the student got wrong. It is where their understanding actually breaks down. Reverse-engineer difficulty, stress-test stated confidence, and hunt for the gap between what someone thinks they know and what they do. Read every miss inside the dependency structure, because a failure downstream usually points to a missing prerequisite upstream.

## 6. Learn by the evidence, not by the shape of the test

The format of the exam is not the right format for learning it. Break a skill into components, drill them with the methods the research supports (spacing, interleaving, retrieval practice, varied formats), and build back up to the real exam format only at the end. Cover the whole material, not just the slice the exam happens to sample, because the exam is a sample and comprehension is the target.

## 7. The human in the loop is a feature, not a crutch

Building this for one motivated user is what makes an otherwise hard problem tractable, and the design leans into that on purpose. The more, less, or shift control, the choice between compressing material and extending the timeline, and the ratification of proposals all deliberately substitute human judgment for automation that would otherwise need data and rigor we do not have. Design around the person rather than trying to engineer them out.

## 8. Self-improving, never self-corrupting

The system gets better as it is used, but on two separate tracks. Observations accrue automatically because they are facts. Any change to the foundational docs passes through a human gate, because unsupervised self-editing drifts into incoherence. The system proposes, you dispose, and the docs only ever move forward through evidence plus your sign-off.

## 9. Honesty over false rigor

Do not perform a precision the inputs cannot support. With a single user and freshly minted questions, the statistically pure approach is not available, so the system says so rather than dressing up a guess as a measurement. The same honesty governs what the user sees: if the timeline does not fit the material, tell them plainly and let them choose, instead of handing over a plan that quietly cannot work.

## 10. Scope every unit of work to the smallest thing that earns its keep

Ask Claude for one bounded job at a time, not five at once. Do not build the whole study guide to test a hypothesis. Build the three questions that prove or disprove it. This is partly about cost, but mostly about refusing wasteful work and keeping every step verifiable.

## 11. Everything traces to its source

Every concept, question, and plan item points back to the page or the notes it came from. Traceability is a first-class property, not an afterthought, because it is what lets you verify a generated question, follow a gap back to the material, and trust the system enough to study from it.

## 12. Evidence picks the next move

Ship something usable and rough before it is complete, put it in front of a real user, and let what actually happens decide what to build next. Scope is the constraint, not effort, and the smallest version that produces real evidence beats a larger one that produces none. Build for yourself now in a way that can generalize later, without over-building for users who do not yet exist.

## How this document changes

The philosophy is the slowest-moving layer in the stack. It should change rarely and only with deliberate intent, because everything else is judged against it, including the system's own proposals to improve itself. When a self-improvement proposal arrives, the first question is whether it honors these principles. If it does not, the answer is no, even when the local metrics look good.
