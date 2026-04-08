"""Deck code encoder / decoder.

Cross-platform compact deck serialization shared with the JS client in
``src/grid_tactics/server/static/game.js``.

Two formats supported:

- ``GT2:<base64url of bytes>`` — **preferred**. Payload is raw bytes
  ``[stable_id, count, stable_id, count, ...]`` where each pair is 2
  bytes (uint8, uint8). Compact: ~40 chars for a 30-card deck.
  Requires every card JSON to have a permanent ``stable_id`` field.
- ``GT1:<base64url of JSON>`` — legacy. Payload is a JSON list of
  ``[card_id, count]`` pairs. Kept for backwards compat; new exports
  always use GT2.

Example GT2::

    >>> encode_deck_code({"fire_imp": 2, "rat": 2}, id_lookup={"fire_imp": 10, "rat": 23})
    'GT2:CgIXAg'
    >>> decode_deck_code('GT2:CgIXAg', reverse_lookup={10: "fire_imp", 23: "rat"})
    {'fire_imp': 2, 'rat': 2}
"""

from __future__ import annotations

import base64
import json
from typing import Dict, Mapping, Optional

DECK_CODE_PREFIX_V2 = "GT2:"
DECK_CODE_PREFIX_V1 = "GT1:"


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def encode_deck_code(
    deck: Dict[str, int],
    id_lookup: Optional[Mapping[str, int]] = None,
) -> str:
    """Encode a ``{card_id: count}`` mapping as a GT2 deck code.

    Args:
        deck: mapping of card_id → positive count.
        id_lookup: mapping card_id → stable_id. If omitted, the function
            loads ``CardLibrary.from_directory("data/cards")`` — convenient
            for scripts but allocates I/O per call; pass explicitly in hot
            paths.

    Returns:
        A ``GT2:...`` deck code string.

    Raises:
        ValueError: if a card_id in the deck has no stable_id, or any
            count is out of uint8 range (1–255).
    """
    if id_lookup is None:
        id_lookup = _default_stable_id_map()
    entries = []
    for cid, n in deck.items():
        n = int(n)
        if n <= 0:
            continue
        if n > 255:
            raise ValueError(f"count {n} for {cid!r} exceeds uint8 range")
        if cid not in id_lookup:
            raise ValueError(f"no stable_id for card_id {cid!r}")
        sid = int(id_lookup[cid])
        if sid <= 0 or sid > 255:
            raise ValueError(f"stable_id {sid} for {cid!r} out of uint8 range")
        entries.append((sid, n))
    entries.sort()  # stable byte order for reproducible codes
    payload = bytes(b for e in entries for b in e)
    return DECK_CODE_PREFIX_V2 + _b64url_encode(payload)


def decode_deck_code(
    code: str,
    reverse_lookup: Optional[Mapping[int, str]] = None,
) -> Dict[str, int]:
    """Decode a GT1 or GT2 deck code back to ``{card_id: count}``.

    Args:
        code: ``GT2:...`` or ``GT1:...`` string.
        reverse_lookup: mapping stable_id → card_id for GT2 decoding.
            If omitted (and the code is GT2), the function loads
            ``CardLibrary.from_directory("data/cards")``.

    Returns:
        Mapping of card_id → count.

    Raises:
        ValueError: on malformed codes, unknown prefixes, or stable_ids
            that don't resolve to a known card.
    """
    if not isinstance(code, str) or not code:
        raise ValueError("Empty deck code")
    code = code.strip()

    if code.startswith(DECK_CODE_PREFIX_V2):
        return _decode_v2(code[len(DECK_CODE_PREFIX_V2):], reverse_lookup)
    if code.startswith(DECK_CODE_PREFIX_V1):
        return _decode_v1(code[len(DECK_CODE_PREFIX_V1):])
    raise ValueError(
        f"Invalid deck code — must start with {DECK_CODE_PREFIX_V2!r} or {DECK_CODE_PREFIX_V1!r}"
    )


def _decode_v2(
    b64: str, reverse_lookup: Optional[Mapping[int, str]]
) -> Dict[str, int]:
    try:
        payload = _b64url_decode(b64)
    except Exception as exc:
        raise ValueError(f"Invalid base64 in deck code: {exc}") from exc
    if len(payload) % 2 != 0:
        raise ValueError("GT2 payload length must be even (stable_id, count pairs)")
    if reverse_lookup is None:
        reverse_lookup = _default_reverse_map()
    out: Dict[str, int] = {}
    for i in range(0, len(payload), 2):
        sid = payload[i]
        count = payload[i + 1]
        if sid == 0 or count == 0:
            continue
        if sid not in reverse_lookup:
            raise ValueError(f"Unknown stable_id {sid} in deck code")
        cid = reverse_lookup[sid]
        out[cid] = out.get(cid, 0) + count
    return out


def _decode_v1(b64: str) -> Dict[str, int]:
    try:
        payload = _b64url_decode(b64)
    except Exception as exc:
        raise ValueError(f"Invalid base64 in deck code: {exc}") from exc
    try:
        entries = json.loads(payload.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Invalid JSON in deck code: {exc}") from exc
    if not isinstance(entries, list):
        raise ValueError("GT1 payload must be a list of [card_id, count] pairs")
    out: Dict[str, int] = {}
    for entry in entries:
        if (
            not isinstance(entry, (list, tuple))
            or len(entry) != 2
            or not isinstance(entry[0], str)
            or not isinstance(entry[1], int)
            or entry[1] <= 0
        ):
            raise ValueError(f"Malformed entry in deck code: {entry!r}")
        cid, count = entry[0], int(entry[1])
        out[cid] = out.get(cid, 0) + count
    return out


# ---- lazy defaults (only triggered when no explicit lookup is passed) -----


def _load_library_defaults():
    from pathlib import Path
    from grid_tactics.card_library import CardLibrary
    lib = CardLibrary.from_directory(Path("data/cards"))
    forward: Dict[str, int] = {}
    reverse: Dict[int, str] = {}
    for cid, cdef in lib._cards.items():  # type: ignore[attr-defined]
        if getattr(cdef, "stable_id", 0):
            forward[cid] = cdef.stable_id
            reverse[cdef.stable_id] = cid
    return forward, reverse


def _default_stable_id_map() -> Mapping[str, int]:
    return _load_library_defaults()[0]


def _default_reverse_map() -> Mapping[int, str]:
    return _load_library_defaults()[1]
