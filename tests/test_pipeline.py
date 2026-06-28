"""End-to-end Phase 1 walking skeleton: ingest -> intake -> compose -> administer ->
diagnose -> plan, with every Claude call mocked (queued in call order)."""

import json

from studybuddy import administer, diagnose, diagnostic, ingest, intake, plan, seed, store
from studybuddy.runlog import RunLog

EXTRACT = json.dumps({"concepts": [{"name": "Net Present Value"}]})
HARVEST = json.dumps(
    {
        "items": [
            {"stem": "NPV of [100] at 10%?", "format": "numeric", "answer_key": "42",
             "concept_names": ["Net Present Value"]},
            {"stem": "NPV of [50] at 5%?", "format": "numeric", "answer_key": "7",
             "concept_names": ["Net Present Value"]},
        ]
    }
)
INTERP = json.dumps(
    {"gaps": [{"concept": "Net Present Value", "gap_type": "foundational", "severity": 0.7, "confidence": 0.6}]}
)
COMPOSE = json.dumps(
    {
        "overview": "Focus on NPV fundamentals.",
        "topics": [
            {"concept": "Net Present Value", "summary": "Rebuild discounting then NPV.",
             "rationale": "foundational gap", "item_sequence": [], "source_links": []}
        ],
    }
)


def test_full_cycle(tmp_path, fake_client):
    for d in ("prompts", "heuristics", "runs", "runs/blobs", "concepts", "items", "materials", "learner"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    seed.seed_knowledge_layer(root=tmp_path)

    material = tmp_path / "ch5.txt"
    material.write_text("Net present value and discounting...")

    # one client threaded through every stage; outputs consumed in call order
    client = fake_client(outputs=[EXTRACT, HARVEST, INTERP, COMPOSE])

    # Stage 1
    ingest.ingest("finance", [str(material)], root=tmp_path, client=client, material_type=ingest.MaterialType.textbook)
    assert len(store.load_concepts("finance", root=tmp_path)) == 1
    assert len(store.load_items("finance", root=tmp_path)) == 2

    # Stage 3 (no Claude)
    template = intake.build_template("finance", root=tmp_path)
    data = json.loads(template.read_text())
    data["exam_format"] = "numerical"
    data["total_study_time_hours"] = 20
    template.write_text(json.dumps(data))
    intake.ingest_answers("finance", template, root=tmp_path)

    # Stage 4 (retrieval-first; both items real, no generation)
    compose_result = diagnostic.compose("finance", root=tmp_path, client=client, size=2)
    assert compose_result["generated"] == 0

    # fill the answers file: one right, one wrong -> a real gap
    answers_path = compose_result["answers_path"]
    answers = json.loads(answers_path.read_text())
    answers["questions"][0]["response"] = "42"  # correct
    answers["questions"][1]["response"] = "0"   # wrong
    answers_path.write_text(json.dumps(answers))

    # Stage 5 (numeric auto-grade, no Claude)
    admin = administer.administer("finance", answers_path=answers_path, root=tmp_path, client=client)
    assert admin["answered"] == 2 and admin["correct"] == 1

    # Stage 6
    diag = diagnose.diagnose("finance", root=tmp_path, client=client)
    assert any(e.gap_type == "foundational" for e in diag["gap_profile"].entries)

    # Stage 8
    plan_result = plan.compose("finance", root=tmp_path, client=client)
    sp = plan_result["study_plan"]
    assert sp.topics and sp.topics[0].concept_id == "concept_net-present-value"
    assert sp.topics[0].source_links  # traceability survived the whole pipeline
    md = plan_result["markdown_path"].read_text()
    assert "Net Present Value" in md

    # every stage that calls Claude logged exactly one entry, in pipeline order
    phases = [e.phase for e in RunLog(tmp_path).read_all()]
    assert phases == [
        "Stage 1: extract_structure",
        "Stage 1: harvest_items",
        "Stage 6: interpret_gaps",
        "Stage 8: compose_plan",
    ]

    # learner state holds the full record
    state = store.load_learner(root=tmp_path)
    assert state.intake and state.diagnostic_results and state.gap_profile and state.study_plan
