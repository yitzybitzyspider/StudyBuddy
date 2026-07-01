"""The per-request user context (platform Loop 27).

A contextvar carrying who is acting (user id) and their access token, set by the web layer
per request and read by the storage facade (backend dispatch) and the wrapper (run-log
attribution). CLI and tests never set it, so everything falls back to the local single-user
behavior.

Hygiene matters: the setter returns the reset token and the web layer MUST reset in
``teardown_request`` — a recycled server thread must never leak one user's context into the
next request.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class UserCtx:
    user_id: str
    access_token: Optional[str] = None
    email: Optional[str] = None


_current: ContextVar[Optional[UserCtx]] = ContextVar("studybuddy_user", default=None)


def set_user(user_id: str, access_token: str | None = None, email: str | None = None):
    """Set the acting user for this context. Returns the reset token for teardown."""
    return _current.set(UserCtx(user_id=user_id, access_token=access_token, email=email))


def reset_user(token) -> None:
    _current.reset(token)


def get_user() -> UserCtx | None:
    return _current.get()


def get_user_id() -> str | None:
    ctx = _current.get()
    return ctx.user_id if ctx else None
