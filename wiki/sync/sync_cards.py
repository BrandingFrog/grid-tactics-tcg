"""
Pure-function card JSON to wikitext conversion.

Transforms ``data/cards/*.json`` into ``{{Card ... }}`` template invocations
suitable for uploading to the Grid Tactics wiki.  All functions are pure
(no wiki connection required) so they can be unit-tested offline.

Usage::

    from pathlib import Path
    from sync.sync_cards import card_to_wikitext, build_card_name_map

    name_map = build_card_name_map(Path("../data/cards"))
    card = json.loads(Path("../data/cards/minion_ratchanter.json").read_text())
    print(card_to_wikitext(card, name_map))
"""

from __future__ import annotations

import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Repo layout helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_VERSION_PATH = _REPO_ROOT / "src" / "grid_tactics" / "server" / "static" / "VERSION.json"

# ---------------------------------------------------------------------------
# React condition human-readable labels
# ---------------------------------------------------------------------------

_REACT_CONDITION_TEXT: dict[str, str] = {
    "opponent_plays_magic": "When opponent plays a magic card: ",
    "opponent_plays_minion": "When opponent plays a minion: ",
    "opponent_attacks": "When opponent attacks: ",
    "opponent_sacrifices": "When opponent sacrifices: ",
    "opponent_plays_light": "When opponent plays a light card: ",
}


# ---------------------------------------------------------------------------
# Effect templates
# ---------------------------------------------------------------------------

EFFECT_TEMPLATES: dict[str, str] = {
    "damage": "Deal {amount} damage to a target.",
    "heal": "Restore {amount} HP.",
    "burn": "Apply {amount} burn damage over time.",
    "negate": "Negate the target spell.",
    "destroy": "Destroy a target minion.",
    "leap": "Leap {amount} spaces forward.",
    "rally_forward": "Push all friendly minions forward {amount} space(s).",
    "deploy_self": "Deploy this card to the board.",
    "grant_dark_matter": "Grant Dark Matter to a target.",
    "buff_health": "Grant +{amount} HP to a target.",
    "dark_matter_buff": "Buff a minion with Dark Matter (+{amount}).",
    "passive_heal": "Passively heal for {amount} each turn.",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_version() -> str:
    """Read version string from VERSION.json, falling back to ``"0.4.2"``."""
    try:
        data = json.loads(_VERSION_PATH.read_text(encoding="utf-8"))
        return data.get("version", "0.4.2")
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return "0.4.2"


def build_card_name_map(cards_dir: Path) -> dict[str, str]:
    """Return ``{card_id: display_name}`` for every JSON in *cards_dir*."""
    name_map: dict[str, str] = {}
    for path in sorted(cards_dir.glob("*.json")):
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
            name_map[card["card_id"]] = card["name"]
        except (json.JSONDecodeError, KeyError):
            continue
    return name_map


def derive_keywords(card: dict) -> list[str]:
    """Derive keyword list from card JSON structure (never hard-coded per card).

    Returns a sorted, deduplicated list of keyword strings.
    """
    kws: set[str] = set()
    card_type = card.get("card_type", "")
    effects = card.get("effects", [])

    # React
    if card_type == "react" or card.get("react_condition"):
        kws.add("React")

    # Unique
    if card.get("unique"):
        kws.add("Unique")

    # Range (minions only)
    if card_type == "minion" and "range" in card:
        if card["range"] > 0:
            kws.add("Ranged")
        else:
            kws.add("Melee")

    # Cross-link mechanics
    if card.get("tutor_target"):
        kws.add("Tutor")
    if card.get("transform_options"):
        kws.add("Transform")
    if card.get("promote_target"):
        kws.add("Promote")

    # Activated ability
    if card.get("activated_ability"):
        kws.add("Active")
        ability = card["activated_ability"]
        if str(ability.get("effect_type", "")).startswith("conjure"):
            kws.add("Conjure")

    # Sacrifice tribe
    if card.get("summon_sacrifice_tribe"):
        kws.add("Sacrifice")

    # Effect-derived keywords
    for eff in effects:
        eff_type = eff.get("type", "")
        trigger = eff.get("trigger", "")

        # Trigger-based keywords (minion only for on_play -> Summon)
        if trigger == "on_play" and card_type == "minion":
            kws.add("Summon")
        if trigger == "on_death":
            kws.add("Death")
        if trigger == "passive":
            kws.add("Passive")

        # Effect type keywords
        _EFFECT_KW: dict[str, str] = {
            "burn": "Burn",
            "heal": "Heal",
            "damage": "Deal",
            "destroy": "Destroy",
            "negate": "Negate",
            "leap": "Leap",
            "rally_forward": "Rally",
            "deploy_self": "Deploy",
            "grant_dark_matter": "Dark Matter",
        }
        if eff_type in _EFFECT_KW:
            kws.add(_EFFECT_KW[eff_type])

    # React effect (separate from effects array)
    react_eff = card.get("react_effect")
    if react_eff:
        eff_type = react_eff.get("type", "")
        _REACT_EFF_KW: dict[str, str] = {
            "deploy_self": "Deploy",
            "damage": "Deal",
            "heal": "Heal",
        }
        if eff_type in _REACT_EFF_KW:
            kws.add(_REACT_EFF_KW[eff_type])

    return sorted(kws)


def _wikilink(card_id: str, name_map: dict[str, str] | None) -> str:
    """Format a card_id as a ``[[Card:Name|Name]]`` wikilink."""
    if name_map and card_id in name_map:
        display = name_map[card_id]
        return f"[[Card:{display}|{display}]]"
    # Fallback: title-case the card_id
    display = card_id.replace("_", " ").title()
    return f"[[Card:{display}|{display}]]"


def build_rules_text(card: dict, name_map: dict[str, str] | None = None) -> str:
    """Synthesize human-readable rules text from card JSON fields.

    Combines effects, activated abilities, transform options, tutor/promote
    targets, and react conditions into a single rules string.
    """
    parts: list[str] = []
    effects = card.get("effects", [])

    # React condition prefix
    react_cond = card.get("react_condition", "")
    prefix = ""
    if react_cond:
        prefix = _REACT_CONDITION_TEXT.get(react_cond, f"React ({react_cond}): ")

    # Standard effects
    for eff in effects:
        eff_type = eff.get("type", "")
        amount = eff.get("amount", 0)

        if eff_type == "promote":
            # Special: promote uses promote_target
            target_id = card.get("promote_target", "")
            target_link = _wikilink(target_id, name_map) if target_id else "a new form"
            parts.append(f"On death: promote to {target_link}.")
        elif eff_type == "tutor":
            # Special: tutor uses tutor_target
            target_id = card.get("tutor_target", "")
            target_link = _wikilink(target_id, name_map) if target_id else "a card"
            parts.append(
                f"On play: search your deck for {target_link} and add it to your hand."
            )
        elif eff_type in EFFECT_TEMPLATES:
            text = EFFECT_TEMPLATES[eff_type].format(amount=amount)
            parts.append(text)

    # React effect (separate field from effects array)
    react_eff = card.get("react_effect")
    if react_eff:
        eff_type = react_eff.get("type", "")
        amount = react_eff.get("amount", 0)
        if eff_type in EFFECT_TEMPLATES:
            parts.append(EFFECT_TEMPLATES[eff_type].format(amount=amount))

    # Activated ability
    ability = card.get("activated_ability")
    if ability:
        cost = ability.get("mana_cost", 0)
        name = ability.get("name", "activate")
        text = f"'''Active:''' Pay {cost} mana to {name}."
        summon_id = ability.get("summon_card_id")
        if summon_id:
            text += f" Summons {_wikilink(summon_id, name_map)}."
        parts.append(text)

    # Transform options
    transform_opts = card.get("transform_options")
    if transform_opts:
        options: list[str] = []
        for opt in transform_opts:
            target_id = opt.get("target", "")
            cost = opt.get("mana_cost", 0)
            target_link = _wikilink(target_id, name_map)
            options.append(f"Pay {cost} mana -> {target_link}")
        parts.append(f"'''Transform:''' {', '.join(options)}.")

    # Combine with prefix
    body = " ".join(parts)
    if prefix and body:
        return prefix + body
    return body


def card_to_wikitext(
    card: dict,
    name_map: dict[str, str] | None = None,
    art_exists: bool = True,
) -> str:
    """Build a complete ``{{Card ... }}`` template invocation from card JSON.

    Parameters
    ----------
    card:
        Parsed card JSON dict (from ``data/cards/*.json``).
    name_map:
        Optional ``{card_id: display_name}`` mapping for cross-link wikilinks.
    art_exists:
        If ``False``, omit the ``art`` field so Template:Card falls back to
        ``CardBack.png``.
    """
    card_type = card.get("card_type", "")
    is_minion = card_type == "minion"

    fields: dict[str, str] = {}

    # Name
    fields["name"] = card.get("name", "")

    # Type (capitalize)
    fields["type"] = card_type.capitalize()

    # Element (capitalize)
    element = card.get("element", "")
    if element:
        fields["element"] = element.capitalize()

    # Tribe
    tribe = card.get("tribe", "")
    if tribe:
        fields["tribe"] = tribe

    # Cost
    cost = card.get("mana_cost")
    if cost is not None:
        fields["cost"] = str(cost)

    # Minion-only stats
    if is_minion:
        attack = card.get("attack")
        if attack is not None:
            fields["attack"] = str(attack)
        health = card.get("health")
        if health is not None:
            fields["hp"] = str(health)
        r = card.get("range")
        if r is not None:
            fields["range"] = str(r)

    # Rules text
    rules = build_rules_text(card, name_map)
    if rules:
        fields["rules"] = rules

    # Flavor text (British -> American spelling key)
    flavor = card.get("flavour_text", "")
    if flavor:
        fields["flavor"] = flavor

    # Keywords
    keywords = derive_keywords(card)
    if keywords:
        fields["keywords"] = ", ".join(keywords)

    # Art
    if art_exists:
        card_id = card.get("card_id", "")
        if card_id:
            fields["art"] = f"{card_id}.png"

    # Patch version
    fields["patch"] = get_version()

    # Stable ID
    stable_id = card.get("card_id", "")
    if stable_id:
        fields["stable_id"] = stable_id

    # Deckable
    deckable = card.get("deckable", True)
    fields["deckable"] = "true" if deckable else "false"

    # Build wikitext
    lines = ["{{Card"]
    for key, value in fields.items():
        if value:  # skip empty strings
            lines.append(f"| {key:9s}= {value}")
    lines.append("}}")

    return "\n".join(lines)
