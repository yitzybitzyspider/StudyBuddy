"""The real auth provider: Supabase Auth, email + password (platform Loop 29).

Thin translation between supabase-py's auth client and the provider interface the app is
written against (see web/auth.py). One module-level client per process, used ONLY for auth
operations — data access goes through the storage backend with the user's own JWT.

Email confirmation: if the Supabase project has "Confirm email" enabled (the default),
``sign_up`` returns a user but no session; we surface that as a friendly "check your email"
message. Disable confirmations in the dashboard (Authentication → Sign In / Up → Email) for
instant local signups.
"""

from __future__ import annotations

import os

from .auth import AuthError


def _client():
    try:
        from supabase import ClientOptions, create_client
    except ImportError as e:  # pragma: no cover - import guard
        raise AuthError(
            'platform mode needs the supabase package: pip install -e ".[platform]"'
        ) from e

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_ANON_KEY")
    if not url or not key:
        raise AuthError("set SUPABASE_URL and SUPABASE_ANON_KEY for platform mode")
    return create_client(
        url, key, options=ClientOptions(auto_refresh_token=False, persist_session=False)
    )


def _session_dict(res) -> dict:
    session, user = res.session, res.user
    return {
        "user_id": user.id,
        "email": user.email,
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "expires_at": session.expires_at,
    }


class SupabaseAuth:
    enabled = True

    def __init__(self, client=None):
        self.client = client if client is not None else _client()

    def _auth_error(self, exc) -> AuthError:
        msg = getattr(exc, "message", None) or str(exc)
        return AuthError(msg)

    def sign_up(self, email: str, password: str) -> dict:
        try:
            res = self.client.auth.sign_up({"email": email, "password": password})
        except Exception as e:
            raise self._auth_error(e) from e
        if res.session is None:
            # project has email confirmations on: account created, no session yet
            raise AuthError(
                "Account created — check your email to confirm it, then sign in."
            )
        return _session_dict(res)

    def sign_in(self, email: str, password: str) -> dict:
        try:
            res = self.client.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
        except Exception as e:
            raise self._auth_error(e) from e
        return _session_dict(res)

    def refresh(self, refresh_token: str) -> dict:
        try:
            res = self.client.auth.refresh_session(refresh_token)
        except Exception as e:
            raise self._auth_error(e) from e
        return _session_dict(res)
