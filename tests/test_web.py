"""End-to-end web UI test driven through Flask's test client in offline mode."""

import io
import json

import pytest

pytest.importorskip("flask")

from studybuddy import store  # noqa: E402
from studybuddy import diagnostic as diagnostic_mod  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDYBUDDY_OFFLINE", "1")  # canned responses, no key
    from studybuddy.web import create_app

    app = create_app(root=tmp_path)
    app.config.update(TESTING=True)
    return app.test_client(), tmp_path


def test_full_flow_through_the_browser(client):
    c, root = client

    # home + create subject
    assert c.get("/").status_code == 200
    r = c.post("/subject", data={"subject": "Finance"})
    assert r.status_code == 302 and "/s/finance" in r.headers["Location"]

    # ingest a file -> redirects straight to intake (built from what was extracted)
    r = c.post(
        "/s/finance/ingest",
        data={"type": "textbook", "material": (io.BytesIO("chapter text — µ, ½, “smart quotes”".encode("utf-8")), "ch5.md")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 302 and "/s/finance/intake" in r.headers["Location"]
    assert store.load_concepts("finance", root=root)

    # intake page shows the extracted topics
    r = c.get("/s/finance/intake")
    assert r.status_code == 200 and b"Net Present Value" in r.data

    # intake
    r = c.post("/s/finance/intake", data={"exam_format": "closed book", "total_study_time_hours": "20"})
    assert r.status_code == 302
    assert store.load_learner(subject="finance", root=root).intake is not None

    # compose + take the diagnostic
    r = c.post("/s/finance/compose", data={"size": "3"})
    assert r.status_code == 302
    assert c.get("/s/finance/diagnostic").status_code == 200

    answers = json.loads(
        store.doc_path(store.DEFAULT_LEARNER, "finance", diagnostic_mod.ANSWERS_NAME, root=root).read_text()
    )
    form = {f"resp_{q['item_id']}": "an answer" for q in answers["questions"]}
    r = c.post("/s/finance/diagnostic", data=form)
    assert r.status_code == 200 and b"correct" in r.data

    # diagnose -> plan
    r = c.post("/s/finance/diagnose")
    assert r.status_code == 302
    r = c.get("/s/finance/plan")
    assert r.status_code == 200
    assert b"Study plan" in r.data
    assert store.load_learner(subject="finance", root=root).study_plan is not None


def test_ingest_rejects_bad_file_type(client):
    c, _ = client
    c.post("/subject", data={"subject": "finance"})
    r = c.post(
        "/s/finance/ingest",
        data={"type": "textbook", "material": (io.BytesIO(b"x"), "bad.exe")},
        content_type="multipart/form-data",
    )
    assert b"Unsupported file type" in r.data


def test_plan_before_diagnosis_shows_hint(client):
    c, _ = client
    c.post("/subject", data={"subject": "finance"})
    r = c.get("/s/finance/plan")
    assert b"diagnosis first" in r.data
