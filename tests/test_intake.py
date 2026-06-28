import argparse
import json

from studybuddy import cli, intake, store
from studybuddy.models import Concept


def _subject_with_topics(tmp_path):
    store.save_concepts(
        "finance",
        [
            Concept(id=store.concept_id("Net Present Value"), subject="finance", name="Net Present Value"),
            Concept(id=store.concept_id("Discounting"), subject="finance", name="Discounting"),
        ],
        root=tmp_path,
    )


def test_build_template_lists_topics_and_questions(tmp_path):
    _subject_with_topics(tmp_path)
    path = intake.build_template("finance", root=tmp_path)
    data = json.loads(path.read_text())
    assert set(data["per_topic_confidence"]) == {"Net Present Value", "Discounting"}
    assert data["per_topic_confidence"]["Net Present Value"] is None
    for field in ("exam_format", "total_study_time_hours", "daily_availability_hours", "baseline"):
        assert field in data


def test_ingest_answers_maps_to_learner_state(tmp_path):
    _subject_with_topics(tmp_path)
    answers = tmp_path / "ans.json"
    answers.write_text(
        json.dumps(
            {
                "exam_format": "closed-book, 3h",
                "total_study_time_hours": 40,
                "daily_availability_hours": 3,
                "baseline": "rusty",
                "per_topic_confidence": {"Net Present Value": 0.4, "Discounting": None},
            }
        )
    )
    result = intake.ingest_answers("finance", answers, root=tmp_path)
    assert result.exam_format == "closed-book, 3h"
    assert result.total_study_time == 40
    # names mapped to concept ids; None entries skipped
    assert result.per_topic_confidence == {"concept_net-present-value": 0.4}

    persisted = store.load_learner(root=tmp_path).intake
    assert persisted is not None and persisted.baseline == "rusty"


def test_cli_intake_template_then_ingest(tmp_path, capsys):
    _subject_with_topics(tmp_path)
    base = argparse.Namespace(root=str(tmp_path), subject="finance", learner=store.DEFAULT_LEARNER, answers=None)
    assert cli.cmd_intake(base) == 0
    assert "Wrote intake template" in capsys.readouterr().out

    template_path = store.learner_file(store.DEFAULT_LEARNER, intake.TEMPLATE_NAME, root=tmp_path)
    data = json.loads(template_path.read_text())
    data["exam_format"] = "mixed"
    data["per_topic_confidence"]["Discounting"] = 0.7
    template_path.write_text(json.dumps(data))

    ingest_args = argparse.Namespace(
        root=str(tmp_path), subject="finance", learner=store.DEFAULT_LEARNER, answers=str(template_path)
    )
    assert cli.cmd_intake(ingest_args) == 0
    assert "Intake captured" in capsys.readouterr().out
    assert store.load_learner(root=tmp_path).intake.exam_format == "mixed"
