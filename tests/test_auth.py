"""Loop 27: user-context plumbing + the auth seam (all offline, FakeAuth)."""

import pytest

pytest.importorskip("flask")

from studybuddy import usercontext  # noqa: E402
from studybuddy.web.auth import AuthError, FakeAuth  # noqa: E402


@pytest.fixture
def auth_app(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDYBUDDY_OFFLINE", "1")
    from studybuddy.web import create_app

    app = create_app(root=tmp_path, auth_provider=FakeAuth())
    app.config.update(TESTING=True)
    return app.test_client()


def test_local_mode_needs_no_login(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDYBUDDY_OFFLINE", "1")
    from studybuddy.web import create_app

    c = create_app(root=tmp_path).test_client()  # NoopAuth by default
    assert c.get("/").status_code == 200  # no redirect to /login


def test_platform_mode_redirects_anonymous_to_login(auth_app):
    r = auth_app.get("/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_signup_login_logout_flow(auth_app):
    c = auth_app
    # signup creates the account and signs in
    r = c.post("/signup", data={"email": "a@x.com", "password": "secret1"})
    assert r.status_code == 302
    assert c.get("/").status_code == 200
    # logout drops the session
    c.post("/logout")
    assert c.get("/").status_code == 302
    # login with wrong password fails with a friendly page
    r = c.post("/login", data={"email": "a@x.com", "password": "nope"})
    assert r.status_code == 401 and b"wrong email or password" in r.data
    # correct login works
    r = c.post("/login", data={"email": "a@x.com", "password": "secret1"})
    assert r.status_code == 302
    assert c.get("/").status_code == 200


def test_duplicate_signup_rejected(auth_app):
    auth_app.post("/signup", data={"email": "a@x.com", "password": "secret1"})
    r = auth_app.post("/signup", data={"email": "a@x.com", "password": "other66"})
    assert r.status_code == 400 and b"already exists" in r.data


def test_user_context_set_during_request_and_reset_after(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDYBUDDY_OFFLINE", "1")
    from studybuddy import store
    from studybuddy.web import create_app

    app = create_app(root=tmp_path, auth_provider=FakeAuth())
    app.config.update(TESTING=True)

    seen = {}

    @app.get("/whoami")
    def whoami():
        seen["ctx"] = usercontext.get_user()
        return store.current_learner()

    c = app.test_client()
    c.post("/signup", data={"email": "a@x.com", "password": "secret1"})
    body = c.get("/whoami").data.decode()
    assert body == "user_1"  # current_learner is the signed-in user id
    assert seen["ctx"].user_id == "user_1" and seen["ctx"].email == "a@x.com"
    assert usercontext.get_user() is None  # reset after the request (no leakage)


def test_expired_session_refreshes_transparently(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDYBUDDY_OFFLINE", "1")
    from studybuddy.web import create_app
    from studybuddy.web.auth import SESSION_KEY

    provider = FakeAuth()
    app = create_app(root=tmp_path, auth_provider=provider)
    app.config.update(TESTING=True)
    c = app.test_client()
    c.post("/signup", data={"email": "a@x.com", "password": "secret1"})
    # force the stored session to look expired (reassign: nested mutation isn't persisted)
    with c.session_transaction() as s:
        old_access = s[SESSION_KEY]["access_token"]
        s[SESSION_KEY] = {**s[SESSION_KEY], "expires_at": 0}
    assert c.get("/").status_code == 200  # refreshed, not bounced to login
    with c.session_transaction() as s:
        assert s[SESSION_KEY]["access_token"] != old_access


def test_fake_auth_refresh_rotates_and_rejects_reuse():
    p = FakeAuth()
    sess = p.sign_up("a@x.com", "secret1")
    new = p.refresh(sess["refresh_token"])
    assert new["access_token"] != sess["access_token"]
    with pytest.raises(AuthError):
        p.refresh(sess["refresh_token"])  # single-use refresh tokens


def test_runlog_entries_carry_user_id(tmp_path, monkeypatch):
    """The wrapper stamps the acting user into every run-log entry."""
    monkeypatch.setenv("STUDYBUDDY_OFFLINE", "1")
    from studybuddy import ingest, seed
    from studybuddy.runlog import RunLog

    for d in ("prompts", "heuristics", "runs", "runs/blobs", "concepts", "items", "materials"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    seed.seed_knowledge_layer(root=tmp_path)
    (tmp_path / "m.md").write_text("NPV text")

    token = usercontext.set_user("user_42", "tok")
    try:
        ingest.ingest("finance", [str(tmp_path / "m.md")], root=tmp_path)
    finally:
        usercontext.reset_user(token)

    entries = RunLog(tmp_path).read_all()
    assert entries and all(e.user_id == "user_42" for e in entries)
