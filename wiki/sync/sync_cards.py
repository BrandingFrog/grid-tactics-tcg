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

# React condition map — matches game.js condMap (int keys from card JSON)
_REACT_CONDITION_TEXT: dict[int, str] = {
    0: "Magic or React",
    1: "Summon",
    2: "Attack",
    3: "Magic or React",
    4: "Any action",
    5: "Wood", 6: "Fire", 7: "Earth",
    8: "Water", 9: "Metal", 10: "Dark",
    11: "Light",
    12: "Sacrifice",
    13: "Discard",
    14: "End of turn",
}
# Also support string keys (some card JSONs use strings)
_REACT_CONDITION_TEXT_STR: dict[str, str] = {
    "opponent_plays_magic": "Magic or React",
    "opponent_plays_minion": "Summon",
    "opponent_attacks": "Attack",
    "opponent_plays_react": "Magic or React",
    "opponent_sacrifices": "Sacrifice",
    "opponent_discards": "Discard",
    "opponent_plays_light": "Light",
    "any_action": "Any action",
    "opponent_ends_turn": "End of turn",
}


# ---------------------------------------------------------------------------
# Effect templates
# ---------------------------------------------------------------------------

# Trigger -> prefix text (matches game.js triggerMap)
# Supports both int keys (from tensor engine) and string keys (from card JSON)
_TRIGGER_PREFIX: dict[int | str, str] = {
    0: "[[Summon]]", "on_play": "[[Summon]]",
    1: "[[Death]]", "on_death": "[[Death]]",
    2: "[[Attack]]", "on_attack": "[[Attack]]",
    3: "[[Damaged]]", "on_damaged": "[[Damaged]]",
    4: "[[Move]]", "on_move": "[[Move]]",
    5: "[[End]]", "passive": "[[End]]",
    6: "[[Discarded]]", "on_discard": "[[Discarded]]",
    7: "Passive", "aura": "Passive",
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
        ab_type = str(ability.get("effect_type", ""))
        if ab_type.startswith("conjure"):
            kws.add("Conjure")
        if "dark_matter" in ab_type:
            kws.add("Dark Matter")

    # Discard cost
    if card.get("discard_cost_tribe") or card.get("summon_sacrifice_tribe"):
        kws.add("Cost")
        kws.add("Discard")

    # Cost reduction
    if card.get("cost_reduction"):
        kws.add("Cost")
        kws.add("Dark Matter")

    # Destroy-ally cost (legacy key sacrifice_ally_cost accepted too).
    if card.get("destroy_ally_cost") or card.get("sacrifice_ally_cost"):
        kws.add("Cost")
        kws.add("Destroy")

    # Play condition
    if card.get("play_condition") == "discarded_last_turn":
        kws.add("Discarded")

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
            kws.add("End of Turn")
        if trigger == "on_discard":
            kws.add("Discarded")

        # scale_with
        if eff.get("scale_with") == "dark_matter":
            kws.add("Dark Matter")

        # Effect type keywords
        _EFFECT_KW: dict[str, str] = {
            "burn": "Burn",
            "heal": "Heal",
            "damage": "Deal",
            "destroy": "Destroy",
            "negate": "Negate",
            "leap": "Leap",
            "rally_forward": "Rally",
            "deploy_self": "Summon",
            "grant_dark_matter": "Dark Matter",
            "dark_matter_buff": "Dark Matter",
            "buff_attack": "Buff",
            "buff_health": "Buff",
            "revive": "Revive",
            "draw": "Draw",
            "burn_bonus": "Burn",
        }
        if eff_type in _EFFECT_KW:
            kws.add(_EFFECT_KW[eff_type])
        # Aura trigger → Passive keyword
        if trigger in (7, "aura"):
            kws.add("Passive")

    # React effect (separate from effects array)
    react_eff = card.get("react_effect")
    if react_eff:
        eff_type = react_eff.get("type", "")
        _REACT_EFF_KW: dict[str, str] = {
            "deploy_self": "Summon",
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

    # Discard cost
    discard_tribe = card.get("discard_cost_tribe") or card.get("summon_sacrifice_tribe", "")
    if discard_tribe:
        sac_count = card.get("discard_cost_count") or card.get("summon_sacrifice_count", 1)
        if discard_tribe == "any":
            count_text = f"{sac_count} cards" if sac_count > 1 else "a card"
            parts.append(f"[[Cost]]: [[Discard]] {count_text}")
        else:
            count_text = f"{sac_count} " if sac_count > 1 else ""
            plural = "s" if sac_count > 1 else ""
            parts.append(f"[[Cost]]: [[Discard]] any {count_text}[[{discard_tribe}]]{plural}")

    # Destroy-ally cost (legacy key sacrifice_ally_cost accepted too).
    if card.get("destroy_ally_cost") or card.get("sacrifice_ally_cost"):
        parts.append("[[Cost]]: [[Destroy]] an ally")

    # HP cost — caster takes damage to own life on play
    hp_cost = card.get("hp_cost")
    if hp_cost:
        parts.append(f"[[Cost]]: [[Deal]] {hp_cost}🤍 to own face")

    # Play condition
    if card.get("play_condition") == "discarded_last_turn":
        parts.append("[[Cost]]: [[Discard]] last turn")

    # Unique tag
    if card.get("unique"):
        parts.append("[[Unique]]")

    # Cost reduction
    if card.get("cost_reduction") == "dark_matter":
        parts.append("[[Cost]]: Reduce mana cost by ([[Dark Matter]])")

    # Standard effects — skip for pure react cards (their effects render in react section)
    is_minion = card.get("card_type", "") == "minion"
    render_effects = effects if card.get("card_type", "") != "react" else []
    # Coalesce sibling burn + target=all_minions effects that only differ in
    # target_tribe/target_element into a single clause with _tribes/_elements
    # arrays. The per-branch renderer reads these arrays below.
    def _coalesce_burn_all(effs):
        out = []
        bucket = None
        for e in effs:
            is_burn_all = e.get("type") == "burn" and e.get("target") in (6, "all_minions")
            if is_burn_all:
                if bucket is None or bucket.get("trigger") != e.get("trigger"):
                    bucket = {**e, "_tribes": [], "_elements": []}
                    out.append(bucket)
                t = e.get("target_tribe")
                el = e.get("target_element")
                if t and t not in bucket["_tribes"]:
                    bucket["_tribes"].append(t)
                if el and el not in bucket["_elements"]:
                    bucket["_elements"].append(el)
            else:
                bucket = None
                out.append(e)
        return out
    render_effects = _coalesce_burn_all(render_effects)
    for eff in render_effects:
        trigger_idx = eff.get("trigger", 0)
        trigger = _TRIGGER_PREFIX.get(trigger_idx, "")
        # on_play trigger only shows "Summon" for minions
        if trigger_idx in (0, "on_play") and not is_minion:
            trigger = ""
        pfx = f"{trigger}: " if trigger else ""
        amount = eff.get("amount", 0)
        eff_type = eff.get("type", "")
        target = eff.get("target", 0)

        if eff_type == "damage":
            scale = eff.get("scale_with")
            if scale == "dark_matter":
                desc = f"{pfx}Deal ([[Dark Matter]]) damage" if amount == 0 else f"{pfx}Deal {amount} + ([[Dark Matter]]) damage"
            elif scale in ("destroyed_attack", "destroyed_attack_plus_dm",
                           "sacrificed_attack", "sacrificed_attack_plus_dm"):
                dm_part = " + ([[Dark Matter]])" if "dm" in scale else ""
                desc = f"{pfx}Deal destroyed ally's 🗡️{dm_part} as damage"
            else:
                desc = f"{pfx}Deal {amount} damage"
            if target in (1, "all", "all_enemies"):
                desc += " to all enemies"
            elif target in (0, "single", "single_target"):
                desc += " to target"
            elif target in (4, "opponent_player"):
                desc += " to face"
        elif eff_type == "heal":
            desc = f"{pfx}[[Heal]] {amount}"
        elif eff_type in ("buff_attack", "buff_health"):
            scale = eff.get("scale_with", "")
            tribe = eff.get("target_tribe", "")
            tribe_text = "Dark Mages" if tribe == "Mage" else (tribe + "s" if tribe else "allies")
            icon = "🗡️" if eff_type == "buff_attack" else "🤍"
            if scale == "dark_matter":
                other = "buff_health" if eff_type == "buff_attack" else "buff_attack"
                has_pair = any(e.get("type") == other and e.get("scale_with") == "dark_matter" and e.get("target") == eff.get("target") for e in render_effects)
                if eff_type == "buff_attack" and has_pair:
                    desc = f"{pfx}Gain ([[Dark Matter]])🗡️🤍"
                    # Placement condition modifier
                    pcond = eff.get("placement_condition")
                    mult = eff.get("condition_multiplier", 1)
                    if pcond == "front_of_dark_ranged" and mult > 1:
                        desc += f". ×{mult} if placed in front of a [[Dark]] [[Ranged]] ally"
                elif eff_type == "buff_health" and has_pair:
                    continue
                else:
                    desc = f"{pfx}Ally {tribe_text} gain ([[Dark Matter]]){icon}"
            else:
                desc = f"{pfx}+{amount}{icon}"
        elif eff_type == "negate":
            desc = f"{pfx}[[Negate]]"
        elif eff_type == "deploy_self":
            desc = f"{pfx}[[Summon]]"
        elif eff_type == "rally_forward":
            card_name = card.get("name", "this unit")
            desc = f"Move: [[Rally]] friendly {card_name}"
        elif eff_type == "promote":
            target_id = card.get("promote_target", "")
            if target_id:
                promote_tribe = card.get("tribe") or _wikilink(target_id, name_map)
                desc = f"{pfx}[[Promote]] any {promote_tribe} to {card.get('name', '?')}"
            else:
                desc = f"{pfx}[[Promote]]"
        elif eff_type == "tutor":
            target_id = card.get("tutor_target", "")
            count = amount if amount > 1 else 0
            count_text = f"{count} " if count else ""
            if isinstance(target_id, dict):
                # Selector-based tutor (e.g. {"tribe": "Rat"})
                tribe = target_id.get("tribe", "")
                plural = "s" if count > 1 else ""
                target_link = f"[[{tribe}]]{plural}" if tribe else "cards"
            elif target_id:
                target_link = _wikilink(target_id, name_map)
            else:
                target_link = "a card"
            desc = f"{pfx}[[Tutor]] {count_text}{target_link}"
        elif eff_type == "destroy":
            desc = f"{pfx}[[Destroy]] target"
        elif eff_type == "burn":
            burn_target_map = {
                0: " target", 1: " all enemies", 2: " adjacent enemies", 3: " self",
                "single": " target", "single_target": " target",
                "all": " all enemies", "all_enemies": " all enemies",
                "adjacent": " adjacent enemies",
                "self": " self", "self_owner": " self",
            }
            if target in (6, "all_minions"):
                tribes = eff.get("_tribes") or ([eff["target_tribe"]] if eff.get("target_tribe") else [])
                elements = eff.get("_elements") or ([eff["target_element"]] if eff.get("target_element") else [])
                tribe_parts = [f"[[{t}]]s" for t in tribes]
                elem_parts = [f"[[{el.capitalize()}]]" for el in elements]
                joined = tribe_parts + elem_parts
                if not joined:
                    burn_target = " all minions"
                elif len(joined) == 1:
                    burn_target = f" all {joined[0]}"
                else:
                    burn_target = f" all {', '.join(joined[:-1])} and {joined[-1]}"
                if elements:
                    burn_target += " minions"
            else:
                burn_target = burn_target_map.get(target, "")
            desc = f"{pfx}[[Burn]]{burn_target}"
        elif eff_type == "grant_dark_matter":
            tribe = eff.get("target_tribe", "")
            tribe_text = "Dark Mage" if tribe == "Mage" else (tribe or "ally")
            target_val = eff.get("target", 0)
            if target_val in (5, "all_allies"):
                desc = f"{pfx}[[Dark Matter]] +{amount} per ally {tribe_text}"
            else:
                desc = f"{pfx}[[Dark Matter]] +{amount}"
        elif eff_type == "dark_matter_buff":
            desc = f"Active: Target gains ([[Dark Matter]])🗡️"
        elif eff_type == "passive_heal":
            desc = f"[[End]]: [[Heal]] {amount}"
        elif eff_type == "leap":
            desc = "[[Move]]: [[Leap]]"
        elif eff_type == "revive":
            revive_id = eff.get("revive_card_id", "")
            revive_link = _wikilink(revive_id, name_map) if revive_id else "a card"
            up_to = f"up to {amount} " if amount > 1 else ""
            desc = f"{pfx}[[Revive]] {up_to}{revive_link}"
        elif eff_type == "draw":
            count_text = f"{amount} cards" if amount > 1 else "1 card"
            desc = f"{pfx}[[Draw]] {count_text}"
        elif eff_type == "burn_bonus":
            desc = f"Passive: [[Burn]] +{amount}"
        else:
            desc = f"{pfx}Effect"
        parts.append(desc)

    # React effect is now rendered in the react condition section below.

    # Activated ability
    ability = card.get("activated_ability")
    if ability:
        cost = ability.get("mana_cost", 0)
        effect_type = ability.get("effect_type", "")
        if effect_type == "conjure_rat_and_buff":
            rat_link = _wikilink(ability.get("summon_card_id", "rat"), name_map)
            text = f"'''[[Active]] ({cost}):''' [[Conjure]] {rat_link} from deck. Ally Rats on board +1🗡️/+1🤍 (+[[Dark Matter]] × 1)."
        elif effect_type == "summon_token" and ability.get("summon_card_id"):
            text = f"'''[[Active]] ({cost}):''' [[Conjure|Summon]] {_wikilink(ability['summon_card_id'], name_map)}."
        elif effect_type == "dark_matter_buff":
            cost_text = f" ({cost})" if cost > 0 else ""
            text = f"'''[[Active]]{cost_text}:''' Target gains ([[Dark Matter]])🗡️."
        else:
            name = ability.get("name", "activate")
            text = f"'''[[Active]] ({cost}):''' {name}."
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

    # React condition — pure react cards show it in the main rules text
    # (the card type badge already says REACT). Multi-purpose cards (minion
    # or magic + react) get a dedicated REACT section in the Card template
    # and must NOT duplicate the react line here — see card_to_wikitext.
    react_cond = card.get("react_condition")
    if react_cond is not None and card.get("card_type", "") == "react":
        cond_text = _REACT_CONDITION_TEXT.get(react_cond) or _REACT_CONDITION_TEXT_STR.get(str(react_cond), "Any action")
        extra = " while no allies" if card.get("react_requires_no_friendly_minions") else ""
        # Build effect text after ▶
        react_effect = card.get("react_effect")
        if react_effect and react_effect.get("type") == "deploy_self":
            effect_text = " ▶ [[Summon]]"
        elif react_effect and react_effect.get("type") == "draw":
            amt = react_effect.get("amount", 1)
            effect_text = f" ▶ [[Draw]] {amt} card" + ("s" if amt > 1 else "")
        elif not react_effect and effects:
            # Pure react: effects array is the react effect
            effect_parts = []
            for eff in effects:
                eff_type = eff.get("type", "")
                if eff_type == "negate":
                    effect_parts.append("[[Negate]]")
                elif eff_type == "grant_dark_matter":
                    tribe = eff.get("target_tribe", "")
                    tribe_text = "Dark Mage" if tribe == "Mage" else (tribe or "ally")
                    effect_parts.append(f"[[Dark Matter]] +{eff.get('amount', 1)} per ally {tribe_text}")
                else:
                    effect_parts.append(eff_type)
            effect_text = " ▶ " + ". ".join(effect_parts) if effect_parts else ""
        else:
            effect_text = ""
        parts.append(f"{cond_text}{extra}{effect_text}")

    cost_parts = [p for p in parts if p.startswith("[[Cost]]")]
    other_parts = [p for p in parts if not p.startswith("[[Cost]]")]
    if cost_parts and other_parts:
        return ". ".join(cost_parts) + ".<br>" + ". ".join(other_parts)
    return ". ".join(parts)


def card_to_wikitext(
    card: dict,
    name_map: dict[str, str] | None = None,
    art_exists: bool = True,
    last_changed_patch: str | None = None,
    history_entries: list[dict] | None = None,
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
    history_entries:
        Optional list of history dicts for ``build_history_section()``.
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
        tribe_parts = tribe.split()
        fields["tribe"] = " ".join(tribe_parts)  # raw for SMW

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
        # Pre-generate SMW keyword annotations (replaces #arraymap in template)
        fields["keyword_annotations"] = "".join(
            f"[[Keyword::{kw}| ]]" for kw in keywords
        )

    # Pre-split tribe annotations so "Mage Rat" becomes two separate Tribe properties
    if tribe:
        fields["tribe_annotations"] = "".join(
            f"[[Tribe::{t}| ]]" for t in tribe.split()
        )

    # Build metadata table rows (Tribe, Range, Keywords) as pre-rendered wikitext
    # This avoids {{#if:0}} issues and conditional row breakage in the template
    _cell_style = 'style="padding:4px 10px; background:#222;"'
    meta_rows = []
    if tribe:
        tribe_links = "<br/>".join(f"[[{t}]]" for t in tribe.split())
        meta_rows.append(f'{{{{!}}}}-\n{{{{!}}}} colspan="3" {_cell_style} {{{{!}}}} <span style="color:#888; font-size:0.85em;">Tribe</span> <span style="float:right;">{tribe_links}</span>')
    if is_minion and card.get("range") is not None:
        range_val = "[[Melee]]" if card.get("range") == 0 else f"[[Ranged|Range {card.get('range')}]]"
        meta_rows.append(f'{{{{!}}}}-\n{{{{!}}}} colspan="3" {_cell_style} {{{{!}}}} <span style="color:#888; font-size:0.85em;">Range</span> <span style="float:right;">{range_val}</span>')
    # Keywords row removed — keywords are linked inline in effect text instead
    if meta_rows:
        fields["meta_rows"] = "\n".join(meta_rows)

    # React section for multi-purpose cards (minion+react or magic+react).
    # Pure REACT cards render their react info in rules_text, not here.
    react_cond = card.get("react_condition")
    if react_cond is not None and card_type != "react":
        cond_text = _REACT_CONDITION_TEXT.get(react_cond) or _REACT_CONDITION_TEXT_STR.get(str(react_cond), "Any action")
        extra = " while no allies" if card.get("react_requires_no_friendly_minions") else ""
        react_effect = card.get("react_effect")
        if react_effect and react_effect.get("type") == "deploy_self":
            effect_text = " ▶ [[Summon]]"
        elif react_effect and react_effect.get("type") == "draw":
            amt = react_effect.get("amount", 1)
            effect_text = f" ▶ [[Draw]] {amt} card" + ("s" if amt > 1 else "")
        elif not react_effect and card.get("effects"):
            # Magic+react (shared effects like Illicit Stones)
            card_effects = card.get("effects", [])
            effect_parts = []
            for eff in card_effects:
                eff_type = eff.get("type", "")
                if eff_type == "grant_dark_matter":
                    t = eff.get("target_tribe", "")
                    t_text = "Dark Mage" if t == "Mage" else (t or "ally")
                    effect_parts.append(f"[[Dark Matter]] +{eff.get('amount', 1)} per ally {t_text}")
                elif eff_type == "negate":
                    effect_parts.append("[[Negate]]")
                else:
                    effect_parts.append(eff_type)
            effect_text = " ▶ " + ". ".join(effect_parts) if effect_parts else ""
        else:
            effect_text = ""
        fields["react_rules"] = f"{cond_text}{extra}{effect_text}"
        react_cost = card.get("react_mana_cost", 0)
        fields["react_cost"] = str(react_cost)

    # Art
    if art_exists:
        card_id = card.get("card_id", "")
        if card_id:
            fields["art"] = f"{card_id}.png"

    # Patch version
    fields["patch"] = get_version()

    # Last changed patch (set by caller when history tracking is active)
    if last_changed_patch:
        fields["last_changed_patch"] = last_changed_patch

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

    result = "\n".join(lines)

    # Standard card page sections
    result += "\n\n== Gallery =="
    result += "\n\n== Tips =="
    tips = card.get("tips", [])
    if tips:
        for t in tips:
            result += f"\n* {t}"
    result += "\n\n== Rulings =="
    rulings = card.get("rulings", [])
    if rulings:
        for r in rulings:
            result += f"\n* {r}"
    result += "\n\n== Trivia =="

    # Append history section (auto-generated from patch tracking)
    if history_entries:
        from sync.card_history import build_history_section

        history_text = build_history_section(history_entries)
        if history_text:
            result += "\n\n" + history_text
    else:
        result += "\n\n== History =="

    return result
