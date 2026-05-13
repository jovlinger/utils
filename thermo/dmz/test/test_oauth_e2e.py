"""OAuth end-to-end tests: full login/callback/access/rejection cycle.

The Google IdP is mocked so tests run without network access or real credentials.
The test exercises DMZ's own routing and session logic only — we are not testing
Google.

Flow under test:
  1. Unauthenticated browser GET /ui/context  → 302 toward /login
  2. GET /login                               → 302 toward accounts.google.com
  3. Fake IdP callback GET /authorize         → DMZ exchanges code for userinfo
     (mocked: no real network call)
  4. DMZ sets session cookie, **302** from ``/authorize`` to the public HTML UI root (never ``/ui/context`` in ``Location``);
     session must encode the authenticated email
  5. Repeat GET /ui/context with live session → 200 with zone payload
  6. GET /ui/context with forged session      → 302 back to /login (rejected)
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse

import pytest
from flask import redirect

from app import app

_OAUTH_E2E_EMAIL = "oauth-e2e-test@gmail.com"
_OAUTH_E2E_PATTERN = r"^oauth-e2e-test@gmail\.com$"

_FAKE_USERINFO: Dict[str, Any] = {
    "email": _OAUTH_E2E_EMAIL,
    "name": "Test User",
    "sub": "fake-google-sub-12345",
}


def _make_oauth_mock() -> MagicMock:
    """
    Minimal mock for ``app.oauth``.

    - ``authorize_redirect`` → immediate 302 to a fake Google URL (no network).
    - ``authorize_access_token`` → returns fake userinfo for the allowlisted test address.
    """
    m = MagicMock()
    m.google.authorize_redirect.side_effect = lambda *a, **kw: redirect(
        "https://accounts.google.com/o/oauth2/auth?client_id=fake&state=FAKESTATE"
    )
    m.google.authorize_access_token.return_value = {"userinfo": _FAKE_USERINFO}
    return m


def test_oauth_e2e_full_flow(
    dmz_ctx: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Steps 1–5: unauthenticated access triggers the IdP redirect chain;
    after the faked callback the session grants access to /ui/context."""
    monkeypatch.setenv("ALLOWED_EMAIL_PATTERN", _OAUTH_E2E_PATTERN)
    monkeypatch.delenv("ALLOWED_EMAIL", raising=False)
    monkeypatch.delenv("THERMO_UI_PUBLIC_ORIGIN", raising=False)
    with patch("app._oauth_enabled", True), patch("app.oauth", _make_oauth_mock(), create=True):
        with app.test_client() as c:
            # Step 1: unauthenticated browser GET → redirect to /login
            r1 = c.get("/ui/context", headers={"Accept": "text/html,*/*"})
            assert r1.status_code == 302, r1.get_data(as_text=True)
            assert "/login" in r1.headers["Location"]

            # Step 2: GET /login → redirect to Google IdP
            r2 = c.get("/login")
            assert r2.status_code == 302, r2.get_data(as_text=True)
            assert "accounts.google.com" in r2.headers["Location"]

            # Step 3: fake IdP callback — DMZ receives code, exchanges for token
            r3 = c.get("/authorize?code=FAKECODE&state=FAKESTATE")
            assert r3.status_code == 302, r3.get_data(as_text=True)

            # Step 4: session + single 302 from /authorize to public HTML UI root
            with c.session_transaction() as sess:
                user: Dict[str, Any] = sess.get("user") or {}
                assert user.get("email") == _OAUTH_E2E_EMAIL.lower(), (
                    f"Session user email mismatch: {user}"
                )
            loc3 = (r3.headers.get("Location") or "").strip()
            assert "/ui/context" not in loc3, loc3
            assert loc3.endswith("/"), loc3
            assert urlparse(loc3).hostname is not None, loc3

            # Step 5: same client (session cookie carried automatically) → 200
            r5 = c.get("/ui/context")
            assert r5.status_code == 200, r5.get_data(as_text=True)
            body: Dict[str, Any] = r5.get_json() or {}
            assert "zones" in body, f"Expected 'zones' key in /ui/context response: {body}"


def test_oauth_callback_rejects_email_not_on_allowlist(
    dmz_ctx: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Google returns a valid gmail.com address that does not match the allowlist regex."""
    monkeypatch.setenv("ALLOWED_EMAIL_PATTERN", r"^only-this@gmail\.com$")
    monkeypatch.delenv("ALLOWED_EMAIL", raising=False)
    m = MagicMock()
    m.google.authorize_access_token.return_value = {
        "userinfo": {"email": "other@gmail.com", "sub": "x"}
    }
    with patch("app._oauth_enabled", True), patch("app.oauth", m, create=True):
        with app.test_client() as c:
            r = c.get("/authorize?code=FAKECODE&state=FAKESTATE")
            assert r.status_code == 403, r.get_data(as_text=True)
            assert "allowlist" in (r.get_json() or {}).get("error", "").lower()


def test_oauth_e2e_forged_session_rejected(dmz_ctx: object) -> None:
    """Step 6: a plausible-looking but unsigned session cookie must not grant access."""
    with patch("app._oauth_enabled", True):
        with app.test_client() as c:
            # Base64-looking payload with a garbage HMAC — Flask will reject the signature
            # and treat the session as empty.
            c.set_cookie(
                "session",
                "eyJ1c2VyIjp7ImVtYWlsIjoidGVzdEBnbWFpbC5jb20ifX0.INVALIDSIGNATURE",
            )
            r = c.get("/ui/context", headers={"Accept": "text/html,*/*"})
            assert r.status_code == 302, r.get_data(as_text=True)
            assert "/login" in r.headers["Location"], (
                f"Forged session should redirect to /login, got: {r.headers['Location']}"
            )
