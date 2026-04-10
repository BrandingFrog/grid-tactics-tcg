"""Pure-function builders for card history sections and deprecated card wikitext.

No wiki connection needed. These functions produce wikitext strings from
structured data, suitable for inclusion in card pages.

Usage::

    from sync.card_history import (
        build_history_section,
        build_deprecated_wikitext,
        extract_history_section,
    )

    entries = [
        {"version": "0.5.0", "date": "2026-04-09", "change_type": "changed",
         "changed_fields": ["attack", "health"]},
        {"version": "0.4.2", "date": "2026-04-08", "change_type": "added",
         "changed_fields": []},
    ]
    print(build_history_section(entries))
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


_FIELD_LABELS: dict[str, str] = {
    "mana_cost": "Mana cost",
    "attack": "Attack",
    "health": "Health",
    "card_type": "Type",
    "element": "Element",
    "tribe": "Tribe",
    "range": "Range",
    "summon_sacrifice_tribe": "Sacrifice tribe",
    "summon_sacrifice_count": "Sacrifice count",
    "unique": "Unique",
    "deckable": "Deckable",
    "tutor_target": "Tutor target",
    "promote_target": "Promote target",
    "flavour_text": "Flavor text",
    "react_condition": "React condition",
    "react_mana_cost": "React cost",
}


_FIELD_DEFAULTS: dict[str, object] = {
    "summon_sacrifice_count": 1,
    "unique": False,
    "deckable": True,
}


def _format_value(field: str, value: object) -> str:
    """Format a card field value for display in patch notes."""
    if value is None:
        default = _FIELD_DEFAULTS.get(field)
        if default is not None:
            value = default
        else:
            return "none"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        if not value:
            return "none"
        # Effects array — summarize trigger:type pairs
        if value and isinstance(value[0], dict) and "type" in value[0]:
            parts = []
            for eff in value:
                trigger = eff.get("trigger", "")
                etype = eff.get("type", "")
                amount = eff.get("amount", "")
                label = f"{trigger}:{etype}" if trigger else etype
                if amount:
                    label += f"({amount})"
                parts.append(label)
            return ", ".join(parts)
        return str(value)
    return str(value)


def build_history_section(history_entries: list[dict]) -> str:
    """Build a ``== History ==`` wikitext section from structured entries.

    Parameters
    ----------
    history_entries:
        List of dicts with keys: ``version`` (str), ``date`` (str),
        ``change_type`` (Literal["added", "changed", "removed"]),
        ``changed_fields`` (list[str], empty for added/removed).
        Optionally ``old_values`` and ``new_values`` dicts for detailed diffs.

    Returns
    -------
    str
        Wikitext for the history section, or empty string if no entries.
    """
    if not history_entries:
        return ""

    # Sort newest-first by version (reverse lexicographic)
    sorted_entries = sorted(
        history_entries,
        key=lambda e: e["version"],
        reverse=True,
    )

    lines: list[str] = ["== History =="]
    for entry in sorted_entries:
        version = entry["version"]
        date = entry["date"]
        change_type = entry["change_type"]
        changed_fields = entry.get("changed_fields", [])
        old_values = entry.get("old_values", {})
        new_values = entry.get("new_values", {})

        lines.append(f"; [[Patch:{version}|{version}]] ({date})")

        if change_type == "added":
            lines.append(": Card added.")
        elif change_type == "removed":
            lines.append(": Card removed.")
        elif change_type == "changed":
            old_rules = entry.get("old_rules", "")
            new_rules = entry.get("new_rules", "")
            if old_rules and new_rules and old_rules != new_rules:
                lines.append(f": {old_rules} → {new_rules}")
            elif new_rules:
                lines.append(f": {new_rules}")
            else:
                # Legacy entries without rules text
                readable = [
                    _FIELD_LABELS.get(f, f.replace("_", " ").capitalize())
                    for f in changed_fields
                ]
                lines.append(f": Changed: {', '.join(readable)}")

    return "\n".join(lines)


def build_deprecated_wikitext(
    card_name: str,
    last_patch: str,
    original_card_wikitext: str,
) -> str:
    """Wrap a card page's wikitext with a deprecated marker.

    Used when a card is removed from ``data/cards/`` -- the wiki page is
    preserved with the deprecated banner instead of being deleted.

    Parameters
    ----------
    card_name:
        Display name of the card (for future reference; not emitted directly).
    last_patch:
        The patch version in which the card was removed.
    original_card_wikitext:
        The full wikitext of the card page (``{{Card ... }}`` invocation and
        any history section).

    Returns
    -------
    str
        Wikitext starting with ``{{DeprecatedCard|patch=...}}``, then the
        original card template, then ``[[Category:Deprecated]]``.
    """
    parts: list[str] = [
        f"{{{{DeprecatedCard|patch={last_patch}}}}}",
        original_card_wikitext,
        "[[Category:Deprecated]]",
    ]
    return "\n".join(parts)


def extract_history_section(page_text: str) -> tuple[str, list[dict]]:
    """Parse an existing card page to extract its ``== History ==`` section.

    Parameters
    ----------
    page_text:
        Full wikitext of a card page.

    Returns
    -------
    tuple[str, list[dict]]
        A tuple of (page_text_without_history, parsed_entries).
        ``parsed_entries`` is a list of dicts with keys: ``version``,
        ``date``, ``change_type``, ``changed_fields``.
        If no history section exists, returns ``(original_text, [])``.
    """
    # Find the == History == header
    history_match = re.search(r"^== History ==\s*$", page_text, re.MULTILINE)
    if not history_match:
        return (page_text, [])

    # Split into body (before history) and history section
    body = page_text[: history_match.start()].rstrip()
    history_text = page_text[history_match.start() :]

    # Parse history entries from definition-list lines
    entries: list[dict] = []

    # Match ; [[Patch:X.Y.Z|X.Y.Z]] (YYYY-MM-DD) followed by : description
    entry_pattern = re.compile(
        r"^;\s*\[\[Patch:([^|]+)\|[^\]]+\]\]\s*\(([^)]+)\)\s*$",
        re.MULTILINE,
    )
    desc_pattern = re.compile(r"^:\s*(.+)$", re.MULTILINE)

    # Find all ; lines (version headers)
    header_matches = list(entry_pattern.finditer(history_text))
    desc_matches = list(desc_pattern.finditer(history_text))

    for i, header in enumerate(header_matches):
        version = header.group(1)
        date = header.group(2)

        # Find the corresponding : line (the next desc after this header)
        desc_text = ""
        for dm in desc_matches:
            if dm.start() > header.end():
                desc_text = dm.group(1).strip()
                desc_matches.remove(dm)
                break

        # Parse description into change_type and changed_fields
        if desc_text == "Card added.":
            change_type = "added"
            changed_fields: list[str] = []
        elif desc_text == "Card removed.":
            change_type = "removed"
            changed_fields = []
        elif desc_text.startswith("Changed:"):
            change_type = "changed"
            fields_str = desc_text[len("Changed:") :].strip()
            changed_fields = [f.strip() for f in fields_str.split(",")]
        else:
            # Unknown format -- treat as "changed" with raw description
            change_type = "changed"
            changed_fields = [desc_text] if desc_text else []

        entries.append({
            "version": version,
            "date": date,
            "change_type": change_type,
            "changed_fields": changed_fields,
        })

    return (body, entries)
