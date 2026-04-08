"""Deck code encoder / decoder.

Cross-platform format shared with the JS client in
`src/grid_tactics/server/static/game.js`.

Format: ``GT1:<base64url of JSON [[card_id, count], ...]>``

The payload is a JSON array of ``[card_id, count]`` pairs, sorted by
card_id for stable round-trips. base64url (RFC 4648 §5) so the code
is URL-safe and shell-safe. No padding.

Example:
    >>> encode_deck_code({"rat": 2, "fire_imp": 2})
    'GT1:W1siZmlyZV9pbXAiLDJdLFsicmF0IiwyXV0'
    >>> decode_deck_code('GT1:W1siZmlyZV9pbXAiLDJdLFsicmF0IiwyXV0')
    {'fire_imp': 2, 'rat': 2}
"""

from __future__ import annotations

import base64
import json
from typing import Dict

DECK_CODE_PREFIX = "GT1:"


def encode_deck_code(deck: Dict[str, int]) -> str:
    """Encode a ``{card_id: count}`` mapping as a deck code string.

    Args:
        deck: mapping of card_id → positive int count. Entries with
            zero or negative counts are skipped.

    Returns:
        A deck code string like ``GT1:<base64url>``.
    """
    entries = sorted(
        ((cid, int(n)) for cid, n in deck.items() if int(n) > 0),
        key=lambda e: e[0],
    )
    payload = json.dumps(entries, separators=(",", ":")).encode("utf-8")
    b64 = base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
    return DECK_CODE_PREFIX + b64


def decode_deck_code(code: str) -> Dict[str, int]:
    """Decode a ``GT1:`` deck code string back to ``{card_id: count}``.

    Args:
        code: deck code string, must start with ``GT1:``.

    Returns:
        Mapping of card_id → count.

    Raises:
        ValueError: if the code is malformed, missing the prefix, or
            decodes to an unexpected structure.
    """
    if not isinstance(code, str) or not code:
        raise ValueError("Empty deck code")
    code = code.strip()
    if not code.startswith(DECK_CODE_PREFIX):
        raise ValueError(
            f"Invalid deck code — must start with {DECK_CODE_PREFIX!r}"
        )
    b64 = code[len(DECK_CODE_PREFIX) :]
    # Re-pad for urlsafe_b64decode
    pad = "=" * (-len(b64) % 4)
    try:
        payload = base64.urlsafe_b64decode(b64 + pad)
    except Exception as exc:
        raise ValueError(f"Invalid base64 in deck code: {exc}") from exc
    try:
        entries = json.loads(payload.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Invalid JSON in deck code: {exc}") from exc
    if not isinstance(entries, list):
        raise ValueError("Deck code payload must be a list of [card_id, count] pairs")
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
