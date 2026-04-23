"""POST /api/bug-report — accept a player report, file a Trello card.

Wired into the Flask app via register_bug_report(app). Reads three env
vars at request time (so missing config returns a 500 with a clear
message rather than crashing app boot):

  TRELLO_API_KEY  — power-up API key
  TRELLO_TOKEN    — user-authorised access token
  TRELLO_LIST_ID  — destination list (the "Inbox" column on the bugs board)

Request JSON shape:
{
  "title":       str,        # required, 1-200 chars
  "description": str,        # required, 1-4000 chars
  "severity":    str,        # one of: cosmetic | annoying | broken
  "screen":      str,        # duel | sandbox | tests
  "url":         str,        # window.location.href at submit time
  "browser":     str,        # navigator.userAgent
  "version":     str,        # app patch version (from VERSION.json)
  "game_state":  obj | None, # full GameState JSON if available
  "events":      list,       # last N engine events (already truncated client-side)
  "console":     list        # last N console errors / warnings
}

Server response:
  200: { "ok": true, "card_url": "https://trello.com/c/..." }
  4xx/5xx: { "ok": false, "error": "<message>" }

The card description gets a compact summary; the full game_state +
events go on as a JSON file attachment so the description stays
readable and below Trello's 16K char limit.
"""
from __future__ import annotations

import io
import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

from flask import Flask, Response, jsonify, request

TRELLO_API = "https://api.trello.com/1"
SEVERITY_LABELS = {
    "cosmetic": "Cosmetic",
    "annoying": "Annoying",
    "broken": "Broken",
}


def register_bug_report(app: Flask) -> None:
    @app.route("/api/bug-report", methods=["POST"])
    def post_bug_report() -> tuple[Response, int] | Response:
        cfg = _load_config()
        if cfg is None:
            return jsonify(ok=False, error="Trello not configured on this server"), 500

        payload = request.get_json(silent=True) or {}
        title = (payload.get("title") or "").strip()
        description = (payload.get("description") or "").strip()
        if not title or not description:
            return jsonify(ok=False, error="title and description are required"), 400

        severity = (payload.get("severity") or "annoying").lower()
        sev_label = SEVERITY_LABELS.get(severity, "Annoying")

        meta_lines = [
            f"**Severity:** {sev_label}",
            f"**Screen:** {payload.get('screen') or 'unknown'}",
            f"**URL:** {payload.get('url') or 'unknown'}",
            f"**Version:** {payload.get('version') or 'unknown'}",
            f"**Browser:** `{(payload.get('browser') or 'unknown')[:200]}`",
        ]
        events = payload.get("events") or []
        if events:
            meta_lines.append(f"**Events captured:** {len(events)}")
        if payload.get("game_state"):
            meta_lines.append("**Game state:** attached as `state.json`")

        body = "## Description\n\n" + description[:4000] + "\n\n---\n\n" + "\n".join(meta_lines)

        try:
            card = _create_card(cfg, title[:200], body)
        except _TrelloError as e:
            return jsonify(ok=False, error=f"Trello card creation failed: {e}"), 502

        try:
            _attach_state(cfg, card["id"], payload)
        except _TrelloError:
            pass

        return jsonify(ok=True, card_url=card.get("shortUrl") or card.get("url"))


# ----- internals ----------------------------------------------------------


class _TrelloError(RuntimeError):
    pass


def _load_config() -> dict[str, str] | None:
    key = os.environ.get("TRELLO_API_KEY")
    token = os.environ.get("TRELLO_TOKEN")
    list_id = os.environ.get("TRELLO_LIST_ID")
    if not (key and token and list_id):
        return None
    return {"key": key, "token": token, "list_id": list_id}


def _create_card(cfg: dict[str, str], name: str, desc: str) -> dict[str, Any]:
    params = {
        "name": name,
        "desc": desc,
        "idList": cfg["list_id"],
        "key": cfg["key"],
        "token": cfg["token"],
    }
    url = TRELLO_API + "/cards"
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise _TrelloError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:200]}") from e
    except urllib.error.URLError as e:
        raise _TrelloError(str(e)) from e


def _attach_state(cfg: dict[str, str], card_id: str, payload: dict[str, Any]) -> None:
    blob = json.dumps(
        {
            "game_state": payload.get("game_state"),
            "events": payload.get("events") or [],
            "console": payload.get("console") or [],
        },
        indent=2,
        default=str,
    ).encode()
    boundary = "----grid-tactics-bug-" + uuid.uuid4().hex
    body = _multipart(boundary, "state.json", "application/json", blob)
    url = (
        f"{TRELLO_API}/cards/{card_id}/attachments"
        f"?key={urllib.parse.quote(cfg['key'])}&token={urllib.parse.quote(cfg['token'])}"
    )
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        raise _TrelloError(str(e)) from e


def _multipart(boundary: str, filename: str, content_type: str, blob: bytes) -> bytes:
    buf = io.BytesIO()
    buf.write(f"--{boundary}\r\n".encode())
    buf.write(
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
    )
    buf.write(f"Content-Type: {content_type}\r\n\r\n".encode())
    buf.write(blob)
    buf.write(f"\r\n--{boundary}--\r\n".encode())
    return buf.getvalue()


# Ensure mimetypes knows the types we use for attachment metadata.
mimetypes.add_type("application/json", ".json")
