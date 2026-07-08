"""Discord OAuth2 login (user 2026-07-08).

Optional sign-in: guests keep playing anonymously (name + localStorage
decks). Logging in with Discord stores {id, username, avatar} in a signed
Flask session cookie so the avatar becomes the player's PFP and decks sync
to Supabase (see deck_store.py).

The whole feature is gated on DISCORD_CLIENT_ID + DISCORD_CLIENT_SECRET
being present in the environment — with neither set, discord_enabled() is
False, the routes 404-guard, and the client hides the login button. The
client secret lives ONLY in the environment, never in code.
"""
from __future__ import annotations

import os
import secrets
from typing import Optional

import requests
from flask import Flask, redirect, request, session, url_for

DISCORD_API = "https://discord.com/api"
AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
TOKEN_URL = f"{DISCORD_API}/oauth2/token"
USER_URL = f"{DISCORD_API}/users/@me"
OAUTH_SCOPE = "identify"
_SESSION_KEY = "discord_user"
_STATE_KEY = "discord_oauth_state"


def _client_id() -> str:
    return os.environ.get("DISCORD_CLIENT_ID", "").strip()


def _client_secret() -> str:
    return os.environ.get("DISCORD_CLIENT_SECRET", "").strip()


def discord_enabled() -> bool:
    """True only when both OAuth credentials are configured."""
    return bool(_client_id() and _client_secret())


def _redirect_uri() -> str:
    """The callback URL Discord redirects back to.

    Prefer an explicit env value (must EXACTLY match a redirect URI
    registered in the Discord app); otherwise derive from the request so
    localhost dev works without extra config.
    """
    explicit = os.environ.get("DISCORD_REDIRECT_URI", "").strip()
    if explicit:
        return explicit
    root = request.url_root  # e.g. http://localhost:5055/
    return root.rstrip("/") + "/auth/discord/callback"


def _avatar_url(user: dict) -> str:
    """CDN URL for the user's avatar, or a default embed avatar."""
    uid = str(user.get("id", ""))
    avatar = user.get("avatar")
    if avatar:
        ext = "gif" if str(avatar).startswith("a_") else "png"
        return f"https://cdn.discordapp.com/avatars/{uid}/{avatar}.{ext}?size=128"
    # Default avatar (new-username scheme): (id >> 22) % 6
    try:
        idx = (int(uid) >> 22) % 6
    except (ValueError, TypeError):
        idx = 0
    return f"https://cdn.discordapp.com/embed/avatars/{idx}.png"


def current_user() -> Optional[dict]:
    """The logged-in user dict, or None. Shape:
    {discord_id, username, display_name, avatar_url}.
    """
    u = session.get(_SESSION_KEY)
    return u if isinstance(u, dict) else None


def register_auth(app: Flask) -> None:
    """Register the Discord OAuth routes on the Flask app."""

    @app.route("/auth/discord/login")
    def discord_login():
        if not discord_enabled():
            return ("Discord login is not configured.", 404)
        state = secrets.token_urlsafe(24)
        session[_STATE_KEY] = state
        # Remember where to bounce the user back to after login.
        session["post_login_redirect"] = request.args.get("next", "/")
        params = {
            "client_id": _client_id(),
            "redirect_uri": _redirect_uri(),
            "response_type": "code",
            "scope": OAUTH_SCOPE,
            "state": state,
            "prompt": "none",
        }
        query = "&".join(
            f"{k}={requests.utils.quote(str(v), safe='')}" for k, v in params.items()
        )
        return redirect(f"{AUTHORIZE_URL}?{query}")

    @app.route("/auth/discord/callback")
    def discord_callback():
        if not discord_enabled():
            return ("Discord login is not configured.", 404)
        # CSRF: the state must match what we issued.
        expected = session.pop(_STATE_KEY, None)
        got = request.args.get("state")
        if not expected or got != expected:
            return redirect("/?login=state_error")
        code = request.args.get("code")
        if not code:
            return redirect("/?login=denied")
        try:
            token_resp = requests.post(
                TOKEN_URL,
                data={
                    "client_id": _client_id(),
                    "client_secret": _client_secret(),
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": _redirect_uri(),
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )
            token_resp.raise_for_status()
            access_token = token_resp.json().get("access_token")
            if not access_token:
                return redirect("/?login=token_error")
            user_resp = requests.get(
                USER_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
            user_resp.raise_for_status()
            u = user_resp.json()
        except requests.RequestException:
            return redirect("/?login=network_error")

        display = u.get("global_name") or u.get("username") or "Player"
        session[_SESSION_KEY] = {
            "discord_id": str(u.get("id", "")),
            "username": u.get("username", ""),
            "display_name": display,
            "avatar_url": _avatar_url(u),
        }
        session.permanent = True
        dest = session.pop("post_login_redirect", "/") or "/"
        # Only allow local redirects.
        if not dest.startswith("/"):
            dest = "/"
        return redirect(dest + ("?login=ok" if "?" not in dest else "&login=ok"))

    @app.route("/auth/discord/logout", methods=["POST", "GET"])
    def discord_logout():
        session.pop(_SESSION_KEY, None)
        session.pop(_STATE_KEY, None)
        return redirect("/?logout=ok")
