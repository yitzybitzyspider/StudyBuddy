# Adaptive Study System: Flowcharts (v1)

*Diagrams as code, in Mermaid, to match the plain-text, version-controlled philosophy of the knowledge layer. Renders in GitHub, VS Code, Claude Code, or any Mermaid-aware viewer. The detailed narrative for each stage lives in the spec; these are the visual skeleton.*

## 1. The pipeline (Stages 1 to 9)

Solid arrows are the main flow. Dotted arrows are writes back to the knowledge layer. The arrow from Stage 7 back to Stage 5 is the adaptive cycle, carrying your more / less / shift control, and it runs until the system is confident before it moves on to the plan.

```mermaid
flowchart TD
    INP["Inputs: syllabus, textbook, sections,<br/>notes, objectives, optional past exam"]
    WS["Web search<br/>(sized to how standardized the exam is)"]

    S1["Stage 1 · Ingest and Harvest<br/>calls: extract_structure, harvest_items<br/>pulls REAL questions into the item bank"]
    S2["Stage 2 · Build / Refine Concept Model<br/>call: build_dependency_map"]
    S3["Stage 3 · Intake Interview<br/>show topics back · ask format, time, confidence"]
    S4["Stage 4 · Compose Diagnostic (about 20)<br/>weighted mix · retrieval-first:<br/>pull, then adapt, then generate, then verify"]
    S5["Stage 5 · Administer and Grade<br/>batch feedback · auto-grade + grade_response"]
    S6["Stage 6 · Diagnose<br/>heuristics + interpret_gaps to gap hypotheses"]
    S7["Stage 7 · Adaptive Sampling<br/>next small, strategic batch"]
    S8["Stage 8 · Time Budget and Plan<br/>honest time math · compose_plan"]
    S9["Stage 9 · Execute and Feedback<br/>spaced + interleaved · all in-system"]

    KL[("Knowledge Layer<br/>writes back at every stage")]

    INP --> S1
    WS --> S1
    S1 --> S2 --> S3 --> S4 --> S5 --> S6 --> S7
    S7 -->|"confident enough → build plan"| S8 --> S9
    S7 -->|"loop · more / less / shift<br/>until confident"| S5

    S1 -.-> KL
    S4 -.-> KL
    S5 -.-> KL
    S6 -.-> KL
    S7 -.-> KL
    S9 -.-> KL
```

## 2. The knowledge-layer feedback loop

This is the self-improvement design. Track A is observations, which write to the knowledge layer automatically because they are facts, not design changes. Track B is changes to the foundational docs, which only land after you accept them. The arrow at the bottom closes the loop: the docs rebuild the runtime through Claude Code, which is why the app is disposable and the knowledge layer is the product.

```mermaid
flowchart TD
    RT["Runtime · the pipeline<br/>(Stages 1 to 9)"]

    OBS["Track A · Observations<br/>item difficulty, concept-map confidence, run log<br/>(automatic, no sign-off)"]
    PROP["Track B · Evidence-backed proposals<br/>recalibrate difficulty scale, promote a prompt version,<br/>add a dependency edge"]

    GATE{"You review<br/>accept or reject"}

    KL[("Knowledge Layer<br/>concept model · item bank · prompt registry ·<br/>heuristics config · run log · learner state")]

    DISCARD["Rejected<br/>(kept in the run log so you can learn from it)"]

    CC["Rebuild via Claude Code"]

    RT -->|"automatic"| OBS
    RT -->|"needs your sign-off"| PROP
    OBS -->|"write freely"| KL
    PROP --> GATE
    GATE -->|"accept · version the doc forward"| KL
    GATE -->|"reject"| DISCARD
    KL --> CC --> RT
```

## 3. How to read the two together

The first diagram is what the system does for a single study session, start to finish. The second is what the system does to itself over many sessions. The link between them is the dotted writeback arrows in diagram one, which are exactly the inputs that feed Track A and Track B in diagram two. Run the pipeline, it sharpens the knowledge layer, the knowledge layer makes the next run smarter, and once in a while it asks your permission to change how it fundamentally works.

## 4. Next step

The todo list and build plan for Claude Code: the order to build the pieces in, what to stub first, and how to sequence it so you have a working personal version early and layer the harder calibration in later.
