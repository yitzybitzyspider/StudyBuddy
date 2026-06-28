"""Tests for the CLI harness. Claude I/O is mocked via cmd_run_call's client param."""

import argparse
import json

import pytest

from studybuddy import cli
from studybuddy.runlog import RunLog


def test_init_creates_layer_and_seeds(tmp_path, capsys):
    rc = cli.main(["init", "--root", str(tmp_path)])
    assert rc == 0
    for d in ("concepts", "items", "prompts", "heuristics", "runs", "learner"):
        assert (tmp_path / d).is_dir()
    assert (tmp_path / "runs" / "blobs").is_dir()
    assert (tmp_path / "prompts" / "extract_structure" / "v1.json").exists()
    assert (tmp_path / "heuristics" / "config.json").exists()
    assert "Knowledge layer ready" in capsys.readouterr().out


def test_init_is_idempotent(tmp_path):
    assert cli.main(["init", "--root", str(tmp_path)]) == 0
    assert cli.main(["init", "--root", str(tmp_path)]) == 0  # second run does not error


def test_show_runlog_empty(tmp_path, capsys):
    cli.main(["init", "--root", str(tmp_path)])
    rc = cli.main(["show-runlog", "--root", str(tmp_path)])
    assert rc == 0
    assert "(run log is empty)" in capsys.readouterr().out


def test_run_call_with_mocked_client(tmp_path, capsys, fake_client):
    cli.main(["init", "--root", str(tmp_path)])
    capsys.readouterr()  # drain the init output so we parse only run-call's JSON
    input_file = tmp_path / "in.json"
    input_file.write_text(json.dumps({"material_text": "NPV ...", "subject": "finance"}))

    args = argparse.Namespace(
        root=str(tmp_path),
        task="extract_structure",
        input=str(input_file),
        version="current",
        model=None,
        phase=None,
    )
    client = fake_client(outputs=['{"concepts": [{"name": "Net Present Value"}]}'])
    rc = cli.cmd_run_call(args, client=client)
    assert rc == 0

    out = json.loads(capsys.readouterr().out)
    assert out["concepts"][0]["name"] == "Net Present Value"

    # The run was logged, and show-runlog now lists it.
    assert len(RunLog(tmp_path).read_all()) == 1
    cli.main(["show-runlog", "--root", str(tmp_path)])
    assert "extract_structure" in capsys.readouterr().out


def test_run_call_bad_input_file(tmp_path, capsys):
    cli.main(["init", "--root", str(tmp_path)])
    args = argparse.Namespace(
        root=str(tmp_path), task="extract_structure",
        input=str(tmp_path / "missing.json"),
        version="current", model=None, phase=None,
    )
    assert cli.cmd_run_call(args) == 1
    assert "could not read input" in capsys.readouterr().err


def test_invalid_task_rejected(tmp_path):
    with pytest.raises(SystemExit):
        cli.main(["run-call", "not_a_task", "-i", "x.json", "--root", str(tmp_path)])
