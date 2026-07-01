"""Auth for the web platform (Loop 27: the seam; Loop 29: the real Supabase provider).

The app is written against a tiny provider interface so local mode needs no accounts at all
and tests exercise the full login flow without any network:

- ``NoopAuth``      — local single-user mode: auth disabled, no login pages enforced.
- ``FakeAuth``      — in-memory provider for tests (and demos): real session flow, no network.
- ``SupabaseAuth``  — the real thing (Supabase Auth, email+password), added in Loop 29.

Session material lives in the server-side-signed Flask session cookie under ``session["sb"]``:
``{user_id, email, access_token, refresh_token, expires_at}``.
"""

from __future__ import annotations

import os
import time
from functools import wraps

from flask import (
    Blueprint,
    current_app,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .. import usercontext

SESSION_KEY = "sb"
_REFRESH_SLACK_S = 60  # refresh when the access token is within this many seconds of expiry


class AuthError(Exception):
    """Sign-in/sign-up failed for a user-facing reason (bad credentials, taken email...)."""


class NoopAuth:
    """Local single-user mode: no accounts, no login, storage stays local."""

    enabled = False

    def sign_up(self, email: str, password: str) -> dict:  # pragma: no cover - unused
        raise AuthError("accounts are disabled in local mode")

    def sign_in(self, email: str, password: str) -> dict:  # pragma: no cover - unused
        raise AuthError("accounts are disabled in local mode")

    def refresh(self, refresh_token: str) -> dict:  # pragma: no cover - unused
        raise AuthError("accounts are disabled in local mode")


class FakeAuth:
    """In-memory provider: the full session flow with zero network (tests/demos)."""

    enabled = True

    def __init__(self) -> None:
        self._users: dict[str, dict] = {}  # email -> {user_id, password}
        self._refresh: dict[str, str] = {}  # refresh_token -> email
        self._counter = 0

    def _session_for(self, email: str) -> dict:
        self._counter += 1
        user = self._users[email]
        refresh_token = f"fake-refresh-{self._counter}"
        self._refresh[refresh_token] = email
        return {
            "user_id": user["user_id"],
            "email": email,
            "access_token": f"fake-access-{self._counter}",
            "refresh_token": refresh_token,
            "expires_at": int(time.time()) + 3600,
        }

    def sign_up(self, email: str, password: str) -> dict:
        if email in self._users:
            raise AuthError("an account with that email already exists")
        if len(password) < 6:
            raise AuthError("password must be at least 6 characters")
        self._users[email] = {"user_id": f"user_{len(self._users) + 1}", "password": password}
        return self._session_for(email)

    def sign_in(self, email: str, password: str) -> dict:
        user = self._users.get(email)
        if user is None or user["password"] != password:
            raise AuthError("wrong email or password")
        return self._session_for(email)

    def refresh(self, refresh_token: str) -> dict:
        email = self._refresh.pop(refresh_token, None)
        if email is None:
            raise AuthError("session expired; sign in again")
        return self._session_for(email)


def default_provider():
    """Pick the provider from the environment (Supabase in platform mode, Noop locally)."""
    if os.environ.get("STUDYBUDDY_BACKEND") == "supabase":
        from .supabase_auth import SupabaseAuth  # Loop 29

        return SupabaseAuth()
    return NoopAuth()


def _provider():
    return current_app.extensions["studybuddy_auth"]


# --- blueprint ---------------------------------------------------------------------------

bp = Blueprint("auth", __name__)


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "GET":
        return render_template("signup.html", error=None)
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    if not email or not password:
        return render_template("signup.html", error="Email and password are required."), 400
    try:
        session[SESSION_KEY] = _provider().sign_up(email, password)
    except AuthError as e:
        return render_template("signup.html", error=str(e)), 400
    return redirect(url_for("index"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html", error=None)
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    try:
        session[SESSION_KEY] = _provider().sign_in(email, password)
    except AuthError as e:
        return render_template("login.html", error=str(e)), 401
    return redirect(url_for("index"))


@bp.post("/logout")
def logout():
    session.pop(SESSION_KEY, None)
    return redirect(url_for("auth.login"))


# --- request wiring ------------------------------------------------------------------------

_OPEN_ENDPOINTS = {"auth.login", "auth.signup", "static", "healthz"}


def install(app, provider) -> None:
    """Register the provider, blueprint, and per-request user-context wiring on the app."""
    app.extensions["studybuddy_auth"] = provider
    app.register_blueprint(bp)

    @app.before_request
    def _before():  # set the acting user for this request; enforce login in platform mode
        g._sb_ctx_token = None
        if not provider.enabled:
            return None
        sb = session.get(SESSION_KEY)
        if sb:
            # refresh shortly before expiry so RLS'd calls never carry a stale JWT
            if (sb.get("expires_at") or 0) - time.time() < _REFRESH_SLACK_S:
                try:
                    sb = provider.refresh(sb["refresh_token"])
                    session[SESSION_KEY] = sb
                except AuthError:
                    session.pop(SESSION_KEY, None)
                    return redirect(url_for("auth.login"))
            g._sb_ctx_token = usercontext.set_user(
                sb["user_id"], sb.get("access_token"), sb.get("email")
            )
            return None
        if request.endpoint in _OPEN_ENDPOINTS or request.endpoint is None:
            return None
        return redirect(url_for("auth.login"))

    @app.teardown_request
    def _teardown(exc):  # never leak a user context into a recycled thread
        token = getattr(g, "_sb_ctx_token", None)
        if token is not None:
            usercontext.reset_user(token)
            g._sb_ctx_token = None


def login_required(view):
    """Explicit guard for extra-sensitive views (the before_request already gates all)."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        provider = _provider()
        if provider.enabled and not session.get(SESSION_KEY):
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped
