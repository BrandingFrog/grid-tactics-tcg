"""Supabase-backed deck & user persistence, keyed by Discord ID.

Optional cloud sync for logged-in players (user 2026-07-08). Degrades
gracefully: with no Supabase env configured (or the client library
missing), available() is False and every call is a safe no-op / empty
result, so guest play and the local-storage deck flow are unaffected.

Tables (run scripts/supabase_decks.sql once in the Supabase SQL editor):
  gt_users(discord_id text pk, username, display_name, avatar_url, updated_at)
  gt_decks(discord_id text, slot int, name text, cards jsonb, updated_at,
           primary key(discord_id, slot))
"""
from __future__ import annotations

import os
from typing import List, Optional

_client = None
_init_tried = False
_last_error = None  # DIAG (temp 2026-07-09): last swallowed exception


def last_error():
    return _last_error


def _env_url() -> str:
    return os.environ.get("SUPABASE_URL", "").strip()


def _env_key() -> str:
    # Prefer the service/secret key for server-side writes; fall back to anon.
    return (
        os.environ.get("SUPABASE_SECRET_KEY", "").strip()
        or os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
        or os.environ.get("SUPABASE_ANON_KEY", "").strip()
    )


def _get_client():
    """Lazily create (and cache) the Supabase client. None if unconfigured."""
    global _client, _init_tried
    if _client is not None:
        return _client
    if _init_tried:
        return None
    _init_tried = True
    url, key = _env_url(), _env_key()
    if not url or not key:
        return None
    try:
        import httpx
        from postgrest import SyncPostgrestClient

        # Force HTTP/1.1 (user 2026-07-09): Railway's egress resets Supabase's
        # HTTP/2 streams (RemoteProtocolError: StreamReset), so the full
        # supabase client fails every write there while working locally.
        # deck_store only does table ops (pure PostgREST), so a direct
        # postgrest client over HTTP/1.1 is sufficient and reliable.
        _client = SyncPostgrestClient(
            url.rstrip("/") + "/rest/v1",
            headers={"apikey": key, "Authorization": "Bearer " + key},
            http_client=httpx.Client(http2=False, timeout=30),
        )
    except Exception as e:
        global _last_error
        _last_error = "create_client: " + type(e).__name__ + ": " + str(e)
        _client = None
    return _client


def available() -> bool:
    """True when cloud deck sync is usable."""
    return _get_client() is not None


def upsert_user(user: dict) -> None:
    """Record/refresh a logged-in user's profile row (best-effort)."""
    sb = _get_client()
    if sb is None or not user:
        return
    try:
        sb.table("gt_users").upsert(
            {
                "discord_id": user.get("discord_id"),
                "username": user.get("username", ""),
                "display_name": user.get("display_name", ""),
                "avatar_url": user.get("avatar_url", ""),
            }
        ).execute()
    except Exception as e:
        global _last_error
        _last_error = 'upsert_user: ' + type(e).__name__ + ': ' + str(e)


def get_decks(discord_id: str) -> List[dict]:
    """All saved deck slots for a user, ordered by slot.

    Returns [{slot, name, cards}] — [] on any failure / not-configured.
    """
    sb = _get_client()
    if sb is None or not discord_id:
        return []
    try:
        res = (
            sb.table("gt_decks")
            .select("slot,name,cards")
            .eq("discord_id", discord_id)
            .order("slot")
            .execute()
        )
        rows = res.data or []
        return [
            {
                "slot": int(r.get("slot", 0)),
                "name": r.get("name", ""),
                "cards": r.get("cards", {}) or {},
            }
            for r in rows
        ]
    except Exception:
        return []


def save_deck(discord_id: str, slot: int, name: str, cards: dict) -> bool:
    """Upsert one deck slot. Returns True on success."""
    sb = _get_client()
    if sb is None or not discord_id:
        return False
    try:
        sb.table("gt_decks").upsert(
            {
                "discord_id": discord_id,
                "slot": int(slot),
                "name": name or f"Deck {int(slot) + 1}",
                "cards": cards or {},
            }
        ).execute()
        return True
    except Exception as e:
        global _last_error
        _last_error = 'save_deck: ' + type(e).__name__ + ': ' + str(e)
        return False


def delete_deck(discord_id: str, slot: int) -> bool:
    """Delete one deck slot. Returns True on success."""
    sb = _get_client()
    if sb is None or not discord_id:
        return False
    try:
        sb.table("gt_decks").delete().eq("discord_id", discord_id).eq(
            "slot", int(slot)
        ).execute()
        return True
    except Exception:
        return False


def replace_all(discord_id: str, slots: List[dict]) -> bool:
    """Bulk-import a list of {slot?, name, cards} — used by the first-login
    'upload my local decks' migration. Missing slots are auto-numbered.
    """
    sb = _get_client()
    if sb is None or not discord_id or not slots:
        return False
    ok = True
    for i, s in enumerate(slots):
        slot = int(s.get("slot", i))
        if not save_deck(discord_id, slot, s.get("name", ""), s.get("cards", {})):
            ok = False
    return ok
