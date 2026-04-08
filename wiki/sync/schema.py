"""
Source of truth for the Grid Tactics Wiki SMW property schema.

Every property that any downstream sync script writes MUST be declared here.
Running ``python -m sync.bootstrap_schema`` turns this list into live
``Property:`` pages on the wiki; running ``python -m sync.verify_schema``
asserts the wiki matches this file.

Naming convention: CamelCase (SMW community convention), which diverges from
the roadmap's snake_case suggestions — documented in 01-03-SUMMARY.md.

Types: see https://www.semantic-mediawiki.org/wiki/Help:List_of_datatypes
    Text, Number, Page, Date, Boolean, Code, URL
"""

from __future__ import annotations

from typing import Any, Sequence, TypedDict


class PropertySpec(TypedDict, total=False):
    name: str
    type: str
    description: str
    allowed_values: Sequence[Any]


# ---------------------------------------------------------------------------
# Core card properties
# ---------------------------------------------------------------------------

PROPERTIES: list[PropertySpec] = [
    {
        "name": "Name",
        "type": "Text",
        "description": "the display name of a Grid Tactics card",
    },
    {
        "name": "StableId",
        "type": "Text",
        "description": "the stable card_id string from data/cards/*.json (never changes across patches)",
    },
    {
        "name": "CardType",
        "type": "Page",
        "description": "the card's type category (Minion, Magic, React, or Multi)",
        "allowed_values": ["Minion", "Magic", "React", "Multi"],
    },
    {
        "name": "Element",
        "type": "Page",
        "description": "the elemental affinity of a card",
        "allowed_values": [
            "Wood",
            "Fire",
            "Earth",
            "Water",
            "Metal",
            "Dark",
            "Light",
            "Neutral",
        ],
    },
    {
        "name": "Tribe",
        "type": "Page",
        "description": "the creature tribe of a minion (open enum: Rat, Golem, etc.)",
    },
    {
        "name": "Cost",
        "type": "Number",
        "description": "the mana cost to play a card (0-10)",
        "allowed_values": list(range(0, 11)),
    },
    {
        "name": "Attack",
        "type": "Number",
        "description": "a minion's attack power",
    },
    {
        "name": "HP",
        "type": "Number",
        "description": "a minion's starting hit points",
    },
    {
        "name": "Range",
        "type": "Number",
        "description": "the attack range of a minion in grid tiles",
    },
    {
        "name": "RulesText",
        "type": "Text",
        "description": "the mechanical rules text printed on a card",
    },
    {
        "name": "Keyword",
        "type": "Page",
        "description": "a gameplay keyword attached to a card (multi-valued via #arraymap)",
    },
    {
        "name": "Artist",
        "type": "Text",
        "description": "the credited artist of the card illustration",
    },
    {
        "name": "ArtFile",
        "type": "Page",
        "description": "the File: page holding the card illustration",
    },
    {
        "name": "FlavorText",
        "type": "Text",
        "description": "the flavor text quote printed on a card",
    },
    {
        "name": "FirstPatch",
        "type": "Text",
        "description": "the patch version in which this card first appeared",
    },
    {
        "name": "LastChangedPatch",
        "type": "Text",
        "description": "the most recent patch version in which this card was modified",
    },
    {
        "name": "LastModified",
        "type": "Date",
        "description": "the timestamp of the last sync update for this card",
    },
    {
        "name": "SourceFile",
        "type": "Text",
        "description": "the canonical JSON source path for this card (e.g. data/cards/ratchanter.json)",
    },
    {
        "name": "Deckable",
        "type": "Boolean",
        "description": "whether the card may be included in a constructed deck",
    },
    {
        "name": "HasEffect",
        "type": "Page",
        "description": "links a card to an effect subobject describing a trigger/condition/action",
    },
]


# ---------------------------------------------------------------------------
# Effect subobject schema (used on subobjects attached via HasEffect)
# ---------------------------------------------------------------------------

EFFECT_SUBPROPERTIES: list[PropertySpec] = [
    {
        "name": "EffectTrigger",
        "type": "Text",
        "description": "the trigger that fires an effect (open enum, to be tightened in Phase 3)",
    },
    {
        "name": "EffectCondition",
        "type": "Text",
        "description": "an optional condition gating whether an effect resolves",
    },
    {
        "name": "EffectAction",
        "type": "Text",
        "description": "the action an effect performs when it resolves",
    },
    {
        "name": "EffectAmount",
        "type": "Number",
        "description": "the numeric magnitude associated with an effect (damage, heal, draw count, ...)",
    },
    {
        "name": "EffectText",
        "type": "Text",
        "description": "the human-readable description of an effect",
    },
]


# ---------------------------------------------------------------------------
# Wikitext rendering helper
# ---------------------------------------------------------------------------


def property_wikitext(
    name: str,
    smw_type: str,
    description: str,
    allowed_values: Sequence[Any] | None = None,
) -> str:
    """Build the canonical wikitext body for a ``Property:<name>`` page.

    The output is deterministic (stable ordering, fixed line endings) so that
    ``bootstrap_schema.py`` can detect "already up to date" via exact string
    equality against ``page.text()``.
    """
    lines = [
        f"This property stores {description}.",
        "",
        f"[[Has type::{smw_type}]]",
    ]
    if allowed_values:
        for value in allowed_values:
            lines.append(f"[[Allows value::{value}]]")
    # Trailing newline keeps diffs clean against MediaWiki's stored text.
    return "\n".join(lines) + "\n"


__all__ = [
    "PROPERTIES",
    "EFFECT_SUBPROPERTIES",
    "PropertySpec",
    "property_wikitext",
]
