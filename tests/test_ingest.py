"""Stage 1 ingest tests: real seeded schemas, mocked Claude outputs."""

import argparse
import json

from studybuddy import cli, ingest, seed, store
from studybuddy.models import ProvenanceOrigin, RefKind
from studybuddy.runlog import RunLog

EXTRACT_OUT = json.dumps(
    {
        "concepts": [
            {"name": "Net Present Value", "parent": None, "difficulty_prior": 3},
            {"name": "Discounting", "parent": "Net Present Value"},
        ]
    }
)
HARVEST_OUT = json.dumps(
    {
        "items": [
            {
                "stem": "Compute the NPV of these cash flows.",
                "format": "numeric",
                "answer_key": "1234.56",
                "concept_names": ["Net Present Value"],
                "rationale": "Discount and sum.",
                "grading_spec": {"max_score": 1},
            }
        ]
    }
)


def _seed(tmp_path):
    for d in ("concepts", "items", "prompts", "heuristics", "runs", "runs/blobs", "learner", "materials"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    seed.seed_knowledge_layer(root=tmp_path)


def test_read_material_text_txt_and_md(tmp_path):
    f = tmp_path / "notes.md"
    f.write_text("# Heading\nbody text")
    assert "body text" in ingest.read_material_text(f)


def test_ingest_persists_concepts_items_material(tmp_path, fake_client):
    _seed(tmp_path)
    material_file = tmp_path / "ch5.txt"
    material_file.write_text("Net present value and discounting ...")
    client = fake_client(outputs=[EXTRACT_OUT, HARVEST_OUT])

    summary = ingest.ingest(
        "finance", [str(material_file)], root=tmp_path, client=client, material_type=ingest.MaterialType.textbook
    )
    assert summary == {
        "materials": 1,
        "concepts": 2,
        "items": 1,
        "files": ["ch5.txt"],
    }

    concepts = store.load_concepts("finance", root=tmp_path)
    assert {c.name for c in concepts} == {"Net Present Value", "Discounting"}
    # parent linkage by slug
    disc = next(c for c in concepts if c.name == "Discounting")
    assert disc.parent_id == "concept_net-present-value"
    # every concept carries a material backref (traceability)
    npv = next(c for c in concepts if c.name == "Net Present Value")
    assert any(r.kind is RefKind.material for r in npv.source_refs)

    items = store.load_items("finance", root=tmp_path)
    assert len(items) == 1
    item = items[0]
    assert item.provenance.origin is ProvenanceOrigin.retrieved
    assert item.provenance.source.kind is RefKind.material
    assert item.concept_ids == ["concept_net-present-value"]  # name -> id link

    materials = store.load_materials("finance", root=tmp_path)
    assert len(materials) == 1
    assert (tmp_path / materials[0].raw_ref).exists()
    assert materials[0].extracted_concepts and materials[0].harvested_items

    # both Claude calls were logged
    phases = [e.phase for e in RunLog(tmp_path).read_all()]
    assert phases == ["Stage 1: extract_structure", "Stage 1: harvest_items"]


def test_cli_ingest_and_show_topics(tmp_path, capsys, fake_client):
    _seed(tmp_path)
    material_file = tmp_path / "ch5.txt"
    material_file.write_text("content")
    client = fake_client(outputs=[EXTRACT_OUT, HARVEST_OUT])

    args = argparse.Namespace(
        root=str(tmp_path), subject="finance", type="textbook", files=[str(material_file)]
    )
    assert cli.cmd_ingest(args, client=client) == 0
    assert "concepts: 2" in capsys.readouterr().out

    assert cli.cmd_show_topics(argparse.Namespace(root=str(tmp_path), subject="finance")) == 0
    out = capsys.readouterr().out
    assert "Net Present Value" in out and "Discounting" in out
