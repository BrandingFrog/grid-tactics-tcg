"""Deterministic heuristic policy for server-controlled preview players.

The policy only ranks actions supplied by :func:`legal_actions`; rules and
resolution remain the engine's responsibility.  It deliberately stays small
and bounded, but accounts for immediate material, combat retaliation, action
payments, spell usefulness, and board advancement.  Stable legal-order tie
breaking keeps AI-vs-AI previews reproducible and avoids touching engine or
stdlib random state.
"""

from __future__ import annotations

from collections.abc import Sequence

from grid_tactics.actions import Action
from grid_tactics.card_library import CardLibrary
from grid_tactics.cards import is_dark_mage
from grid_tactics.enums import (
    ActionType,
    CardType,
    EffectType,
    PlayerSide,
    TargetType,
    TriggerType,
    TurnPhase,
)
from grid_tactics.game_state import GameState
from grid_tactics.legal_actions import effective_mana_cost
from grid_tactics.minion import BURN_DAMAGE
from grid_tactics.types import GRID_ROWS, MAX_HAND_SIZE, MAX_MANA_CAP

_WIN_SCORE = 1_000_000.0
_IMPOSSIBLE = -1_000_000.0


def _effective_attack(minion, library: CardLibrary) -> int:
    try:
        return (library.get_by_id(minion.card_numeric_id).attack or 0) + minion.attack_bonus
    except (KeyError, TypeError):
        return minion.attack_bonus


def _card_value(card_def) -> float:
    """Approximate persistent/hand material without reading hidden zones."""
    if card_def.card_type == CardType.MINION:
        value = (card_def.attack or 0) * 0.65 + (card_def.health or 0) * 0.45
        value += (card_def.attack_range or 0) * 3.0
        for effect in card_def.effects or ():
            if effect.effect_type in (EffectType.DRAW, EffectType.TUTOR):
                value += effect.amount * 4.0
            elif effect.effect_type == EffectType.REVIVE:
                value += effect.amount * 5.0
            elif effect.effect_type in (EffectType.DESTROY, EffectType.PROMOTE):
                value += 6.0
            elif effect.effect_type in (
                EffectType.BURN,
                EffectType.APPLY_BURNING,
                EffectType.BURN_BONUS,
            ):
                value += 3.0
            elif effect.effect_type in (
                EffectType.BUFF_ATTACK,
                EffectType.BUFF_HEALTH,
                EffectType.DARK_MATTER_BUFF,
                EffectType.GRANT_DARK_MATTER,
            ):
                value += max(1, effect.amount) * 2.0
        if card_def.activated_ability is not None:
            value += 3.0
        return value

    value = max(3.0, card_def.mana_cost * 1.4)
    for effect in card_def.effects or ():
        if effect.effect_type == EffectType.DESTROY:
            value += 8.0
        elif effect.effect_type == EffectType.DAMAGE:
            value += max(1, effect.amount) * 0.8
        elif effect.effect_type in (EffectType.DRAW, EffectType.TUTOR):
            value += max(1, effect.amount) * 4.0
        elif effect.effect_type == EffectType.REVIVE:
            value += max(1, effect.amount) * 6.0
        elif effect.effect_type == EffectType.GRANT_DARK_MATTER:
            value += max(1, effect.amount) * 2.0
    return value


def _minion_value(minion, library: CardLibrary) -> float:
    try:
        card_def = library.get_by_id(minion.card_numeric_id)
        value = _effective_attack(minion, library) * 0.65
        value += max(0, minion.current_health) * 0.45
        value += (card_def.attack_range or 0) * 3.0
        value += min(6.0, max(0.0, _card_value(card_def) * 0.12))
        if minion.is_burning:
            value -= min(BURN_DAMAGE, max(0, minion.current_health)) * 0.5
        return max(0.0, value)
    except KeyError:
        return float(max(0, minion.current_health))


def _decision_player_idx(state: GameState) -> int:
    if state.pending_death_target is not None:
        return state.pending_death_target.owner_idx
    for idx in (
        state.pending_trigger_picker_idx,
        state.pending_revive_player_idx,
        state.pending_conjure_deploy_player_idx,
        state.pending_tutor_player_idx,
    ):
        if idx is not None:
            return idx
    if state.phase == TurnPhase.REACT and state.react_player_idx is not None:
        return state.react_player_idx
    return state.active_player_idx


def _advancement(position: tuple[int, int], side: PlayerSide) -> int:
    return position[0] if side == PlayerSide.PLAYER_1 else GRID_ROWS - 1 - position[0]


def _position_value(position, side: PlayerSide, card_def) -> float:
    if position is None:
        return 0.0
    advance = _advancement(position, side)
    centre = 2 - abs(position[1] - 2)
    if (card_def.attack_range or 0) > 0:
        return -advance * 5.0 + centre * 0.25
    return advance * 4.0 + centre * 0.25


def _matches_effect_filter(card_def, effect) -> bool:
    checks: list[bool] = []
    if effect.target_tribe:
        wanted = effect.target_tribe.strip().lower()
        if wanted == "dark mage":
            checks.append(is_dark_mage(card_def))
        else:
            checks.append(wanted in (card_def.tribe or "").lower().split())
    if effect.target_element:
        actual = card_def.element.name.lower() if card_def.element is not None else ""
        checks.append(actual == effect.target_element.strip().lower())
    return any(checks) if checks else True


def _effect_targets(
    state: GameState,
    library: CardLibrary,
    effect,
    owner_side: PlayerSide,
    action: Action,
) -> list:
    living = [m for m in state.minions if m.current_health > 0]
    if effect.target == TargetType.SINGLE_TARGET:
        return [
            m
            for m in living
            if action.target_pos is not None and m.position == action.target_pos
        ]
    if effect.target == TargetType.ALL_ENEMIES:
        candidates = [m for m in living if m.owner != owner_side]
    elif effect.target == TargetType.ALL_ALLIES:
        candidates = [m for m in living if m.owner == owner_side]
    elif effect.target == TargetType.ALL_MINIONS:
        candidates = living
    elif effect.target == TargetType.ADJACENT and action.position is not None:
        row, col = action.position
        candidates = [
            m for m in living
            if abs(m.position[0] - row) + abs(m.position[1] - col) == 1
        ]
        if effect.effect_type == EffectType.BURN:
            candidates = [m for m in candidates if m.owner != owner_side]
    else:
        candidates = []
    return [
        m for m in candidates
        if _matches_effect_filter(library.get_by_id(m.card_numeric_id), effect)
    ]


def _friendly_dark_mages(
    state: GameState,
    library: CardLibrary,
    side: PlayerSide,
    *,
    excluded_minion_id: int | None = None,
) -> int:
    return sum(
        1
        for m in state.minions
        if m.current_health > 0
        and m.owner == side
        and m.instance_id != excluded_minion_id
        and is_dark_mage(library.get_by_id(m.card_numeric_id))
    )


def _scaled_amount(effect, dm: int, mage_count: int, destroyed_attack: int) -> int:
    if effect.scale_with in ("dark_matter", "player_dark_matter"):
        return effect.amount + dm
    if effect.scale_with in ("destroyed_attack", "sacrificed_attack"):
        return effect.amount + destroyed_attack
    if effect.scale_with in (
        "destroyed_attack_plus_dm",
        "sacrificed_attack_plus_dm",
    ):
        return effect.amount + destroyed_attack + dm
    if effect.scale_with == "dark_mages":
        return effect.amount * mage_count
    return effect.amount


def _tutor_value(card_def, player, library: CardLibrary, amount: int) -> float:
    matches = []
    for numeric_id in player.deck:
        candidate = library.get_by_id(numeric_id)
        if card_def.tutor_matches(candidate):
            matches.append(_card_value(candidate))
    matches.sort(reverse=True)
    # The played card leaves hand before its tutor resolves, normally
    # opening one slot.  Mandatory excess picks overdraw into Exhaust and
    # should not be valued like cards retained in hand.
    room_after_play = max(0, MAX_HAND_SIZE - max(0, len(player.hand) - 1))
    return sum(matches[: min(amount, room_after_play)]) * 0.55


def _revive_value(card_def, player, library: CardLibrary, amount: int) -> float:
    values = []
    for numeric_id in player.grave:
        candidate = library.get_by_id(numeric_id)
        if candidate.card_type != CardType.MINION:
            continue
        if card_def.revive_card_id and candidate.card_id != card_def.revive_card_id:
            continue
        values.append(_card_value(candidate))
    values.sort(reverse=True)
    return sum(values[:amount]) * 0.7


def _effects_value(
    state: GameState,
    library: CardLibrary,
    player_idx: int,
    card_def,
    action: Action,
    triggers: set[TriggerType],
    *,
    effects: Sequence | None = None,
    destroyed_attack_override: int | None = None,
    allow_hidden_zones: bool = True,
) -> float:
    player = state.players[player_idx]
    side = player.side
    destroyed = state.get_minion(action.destroyed_minion_id)
    destroyed_attack = (
        destroyed_attack_override
        if destroyed_attack_override is not None
        else _effective_attack(destroyed, library) if destroyed is not None else 0
    )
    mage_count = _friendly_dark_mages(
        state,
        library,
        side,
        excluded_minion_id=action.destroyed_minion_id,
    )
    dm = player.dark_matter
    value = 0.0
    burned: set[int] = set()

    selected = effects if effects is not None else card_def.effects or ()
    for effect in selected:
        if effect.trigger not in triggers:
            continue
        amount = _scaled_amount(effect, dm, mage_count, destroyed_attack)

        if effect.effect_type == EffectType.GRANT_DARK_MATTER:
            gained = amount
            dm += max(0, gained)
            # Dark Matter is persistent archetype fuel.  The weight also
            # captures deliberate discard synergies such as Stash paying
            # for Shady Trade Deal while firing its ON_DISCARD gain.
            value += max(0, gained) * 9.0
            continue
        if effect.effect_type == EffectType.DRAW:
            room = max(0, MAX_HAND_SIZE - max(0, len(player.hand) - 1))
            value += min(amount, len(player.deck), room) * 7.0
            continue
        if effect.effect_type == EffectType.TUTOR:
            if allow_hidden_zones:
                value += _tutor_value(card_def, player, library, amount)
            else:
                room = max(0, MAX_HAND_SIZE - max(0, len(player.hand) - 1))
                value += min(amount, len(player.deck), room) * 6.0
            continue
        if effect.effect_type == EffectType.REVIVE:
            value += _revive_value(card_def, player, library, amount)
            continue
        if effect.effect_type == EffectType.CONJURE:
            value += max(0, amount) * 8.0
            continue

        targets = _effect_targets(state, library, effect, side, action)
        if effect.target == TargetType.OPPONENT_PLAYER:
            if effect.effect_type == EffectType.DAMAGE:
                opponent = state.players[1 - player_idx]
                if amount >= opponent.hp:
                    value += _WIN_SCORE
                else:
                    value += max(0, amount) * 2.5
            continue
        if effect.target in (TargetType.SELF_OWNER, TargetType.OWNER_PLAYER):
            if effect.effect_type == EffectType.DAMAGE:
                value -= max(0, amount) * 2.5
            elif effect.effect_type == EffectType.HEAL:
                value += min(max(0, amount), max(0, 100 - player.hp)) * 0.8
            elif effect.effect_type in (
                EffectType.BUFF_ATTACK,
                EffectType.BUFF_HEALTH,
                EffectType.DARK_MATTER_BUFF,
            ):
                value += max(0, amount) * 0.8
            elif effect.effect_type in (EffectType.BURN, EffectType.APPLY_BURNING):
                value -= BURN_DAMAGE + 2.0
            continue

        for target in targets:
            friendly = target.owner == side
            sign = 1.0 if friendly else -1.0
            if effect.effect_type == EffectType.DAMAGE:
                damage = min(max(0, amount), target.current_health)
                delta = damage * 1.2
                if amount >= target.current_health and amount > 0:
                    delta += _minion_value(target, library)
                value += -delta if friendly else delta
            elif effect.effect_type == EffectType.DESTROY:
                target_value = _minion_value(target, library)
                value += -target_value if friendly else target_value
            elif effect.effect_type == EffectType.HEAL:
                target_def = library.get_by_id(target.card_numeric_id)
                missing = max(
                    0,
                    (target_def.health or 0) + target.max_health_bonus - target.current_health,
                )
                value += sign * min(max(0, amount), missing) * 0.8
            elif effect.effect_type in (
                EffectType.BUFF_ATTACK,
                EffectType.BUFF_HEALTH,
                EffectType.DARK_MATTER_BUFF,
            ):
                value += sign * max(0, amount) * 0.8
            elif effect.effect_type in (EffectType.BURN, EffectType.APPLY_BURNING):
                if target.instance_id not in burned and not target.is_burning:
                    value += (-1.0 if friendly else 1.0) * (BURN_DAMAGE + 2.0)
                    burned.add(target.instance_id)
            elif effect.effect_type == EffectType.CLEANSE and friendly:
                if target.is_burning or target.attack_bonus < 0 or target.max_health_bonus < 0:
                    value += 5.0
    return value


def _discard_payment_value(
    state: GameState,
    library: CardLibrary,
    player_idx: int,
    action: Action,
) -> float:
    player = state.players[player_idx]
    cost = 0.0
    indices = action.discard_card_indices or (
        (action.discard_card_index,) if action.discard_card_index is not None else ()
    )
    for idx in indices:
        if idx is None or not 0 <= idx < len(player.hand):
            continue
        discarded = library.get_by_id(player.hand[idx])
        cost += _card_value(discarded)
        on_discard = [e for e in discarded.effects or () if e.trigger == TriggerType.ON_DISCARD]
        if on_discard:
            cost -= _effects_value(
                state,
                library,
                player_idx,
                discarded,
                Action(action_type=ActionType.PLAY_CARD),
                {TriggerType.ON_DISCARD},
                effects=on_discard,
            )
    return cost


def _play_score(
    state: GameState,
    library: CardLibrary,
    player_idx: int,
    action: Action,
    *,
    from_exhaust: bool = False,
) -> float:
    player = state.players[player_idx]
    zone = player.exhaust if from_exhaust else player.hand
    if action.card_index is None or not 0 <= action.card_index < len(zone):
        return _IMPOSSIBLE
    card_def = library.get_by_id(zone[action.card_index])

    hp_cost = card_def.hp_cost or 0
    if hp_cost >= player.hp and hp_cost > 0:
        return _IMPOSSIBLE
    mana_cost = effective_mana_cost(card_def, state, player_idx, library)
    if from_exhaust:
        mana_cost = max(0, mana_cost - (card_def.exhaust_play_discount or 0))
    if card_def.alt_cost_discard and action.discard_card_indices:
        mana_cost = 0

    score = -mana_cost * 1.5 - hp_cost * 3.0
    score -= _discard_payment_value(state, library, player_idx, action)
    if action.destroyed_minion_id is not None:
        destroyed = state.get_minion(action.destroyed_minion_id)
        if destroyed is not None:
            score -= _minion_value(destroyed, library)

    if card_def.card_type == CardType.MINION:
        score += _card_value(card_def)
        score += _position_value(action.position, player.side, card_def)
        score += _effects_value(
            state,
            library,
            player_idx,
            card_def,
            action,
            {TriggerType.ON_PLAY, TriggerType.ON_SUMMON},
        )
        return score

    score += _effects_value(
        state,
        library,
        player_idx,
        card_def,
        action,
        {TriggerType.ON_PLAY},
    )
    return score


def _attack_score(state: GameState, library: CardLibrary, action: Action) -> float:
    attacker = state.get_minion(action.minion_id)
    defender = state.get_minion(action.target_id)
    if attacker is None or defender is None:
        return _IMPOSSIBLE
    attacker_def = library.get_by_id(attacker.card_numeric_id)
    defender_def = library.get_by_id(defender.card_numeric_id)
    attack = _effective_attack(attacker, library)
    retaliation = _effective_attack(defender, library)
    distance = abs(attacker.position[0] - defender.position[0]) + abs(
        attacker.position[1] - defender.position[1]
    )
    atk_range = attacker_def.attack_range or 0
    def_range = defender_def.attack_range or 0
    defender_reaches = (def_range == 0 and distance <= 1) or (
        def_range > 0 and distance <= def_range
    )
    first_strike = atk_range < def_range and defender_reaches
    defender_dies = attack >= defender.current_health
    attacker_takes = 0 if not defender_reaches or (first_strike and defender_dies) else retaliation
    attacker_dies = attacker_takes >= attacker.current_health and attacker_takes > 0

    score = min(attack, defender.current_health) * 1.2 + 2.0
    if defender_dies:
        score += _minion_value(defender, library)
    if attacker_dies:
        score -= _minion_value(attacker, library) * 1.15
    elif attacker_takes:
        score -= min(attacker_takes, attacker.current_health) * 0.3
    for effect in attacker_def.effects or ():
        if effect.trigger == TriggerType.ON_ATTACK:
            if (
                effect.effect_type in (EffectType.BURN, EffectType.APPLY_BURNING)
                and not defender.is_burning
            ):
                score += BURN_DAMAGE + 2.0
            elif effect.effect_type == EffectType.DAMAGE:
                score += max(0, effect.amount)
    return score


def _sacrifice_score(state: GameState, library: CardLibrary, action: Action) -> float:
    minion = state.get_minion(action.minion_id)
    if minion is None:
        return _IMPOSSIBLE
    damage = _effective_attack(minion, library)
    opponent = state.players[1 - state.active_player_idx]
    if damage > 0 and damage >= opponent.hp:
        return _WIN_SCORE + damage
    score = damage * 2.5 - _minion_value(minion, library) * 0.75
    card_def = library.get_by_id(minion.card_numeric_id)
    player = state.players[state.active_player_idx]
    for effect in card_def.effects or ():
        if effect.trigger == TriggerType.ON_SACRIFICE:
            if effect.effect_type == EffectType.REVIVE:
                score += _revive_value(
                    card_def,
                    player,
                    library,
                    effect.amount,
                )
            elif effect.effect_type == EffectType.DRAW:
                score += min(effect.amount, len(player.deck)) * 7.0
    return score


def _move_score(state: GameState, library: CardLibrary, action: Action) -> float:
    minion = state.get_minion(action.minion_id)
    if minion is None or action.position is None:
        return _IMPOSSIBLE
    card_def = library.get_by_id(minion.card_numeric_id)
    old = _advancement(minion.position, minion.owner)
    new = _advancement(action.position, minion.owner)
    progress = new - old
    if (card_def.attack_range or 0) > 0:
        score = progress * 2.0 - new * 1.5
    else:
        score = progress * 15.0
    score += (2 - abs(action.position[1] - 2)) * 0.25
    if new == GRID_ROWS - 1:
        damage = _effective_attack(minion, library)
        opponent_idx = 1 - state.active_player_idx
        score += damage * 2.0
        if damage > 0 and damage >= state.players[opponent_idx].hp:
            score += _WIN_SCORE * 0.5
    if any(
        effect.trigger == TriggerType.ON_MOVE
        and effect.effect_type == EffectType.RALLY_FORWARD
        for effect in card_def.effects or ()
    ):
        matching_allies = sum(
            1
            for other in state.minions
            if other.owner == minion.owner
            and other.instance_id != minion.instance_id
            and other.card_numeric_id == minion.card_numeric_id
        )
        score += matching_allies * 3.0
    return score


def _ability_score(
    state: GameState,
    library: CardLibrary,
    player_idx: int,
    action: Action,
) -> float:
    source = state.get_minion(action.minion_id)
    if source is None:
        return _IMPOSSIBLE
    source_def = library.get_by_id(source.card_numeric_id)
    ability = source_def.activated_ability
    if ability is None:
        return _IMPOSSIBLE
    player = state.players[player_idx]
    side = player.side
    score = -ability.mana_cost * 1.5

    if ability.effect_type == "conjure_rat_and_buff":
        summon_id = ability.summon_card_id or "rat"
        try:
            numeric_id = library.get_numeric_id(summon_id)
            if numeric_id in player.deck:
                score += _card_value(library.get_by_id(numeric_id)) * 0.8
        except KeyError:
            pass
        magnitude = 1 + player.dark_matter
        rats = 0
        for minion in state.minions:
            if minion.owner != side or minion.instance_id == source.instance_id:
                continue
            card_def = library.get_by_id(minion.card_numeric_id)
            if card_def.card_id == "rat" or "rat" in (card_def.tribe or "").lower().split():
                rats += 1
        score += rats * magnitude * 1.3
        return score

    if ability.effect_type == "dark_matter_buff":
        target = next(
            (
                m
                for m in state.minions
                if action.target_pos is not None and m.position == action.target_pos
            ),
            None,
        )
        if target is None or target.owner != side or player.dark_matter <= 0:
            return -1.0 + score
        return score + player.dark_matter * 1.5 + _minion_value(target, library) * 0.05

    if ability.effect_type == "summon_token" and ability.summon_card_id:
        try:
            return score + _card_value(library.get_by_card_id(ability.summon_card_id))
        except KeyError:
            return _IMPOSSIBLE
    return score


def _transform_score(state: GameState, library: CardLibrary, action: Action) -> float:
    minion = state.get_minion(action.minion_id)
    if minion is None or action.transform_target is None:
        return _IMPOSSIBLE
    source = library.get_by_id(minion.card_numeric_id)
    try:
        target = library.get_by_card_id(action.transform_target)
    except KeyError:
        return _IMPOSSIBLE
    cost = next(
        (
            mana
            for card_id, mana in source.transform_options
            if card_id == action.transform_target
        ),
        0,
    )
    return _card_value(target) - _minion_value(minion, library) - cost * 1.5


def _rest_score(state: GameState, player_idx: int) -> float:
    player = state.players[player_idx]
    available_slots = max(0, MAX_HAND_SIZE - len(player.hand))
    useful_draws = min(state.fortune_ante, len(player.deck), available_slots)
    draw = useful_draws * 7.0
    mana = 4.0 if player.current_mana < MAX_MANA_CAP else 0.0
    # REST banks every point, but at a full bank it wastes next turn's AP
    # regeneration, so prefer a useful primary action there.
    overflow_cost = 6.0 if player.action_points >= 3 else 0.0
    return draw + mana - overflow_cost


def _trigger_score(state: GameState, library: CardLibrary, action: Action) -> float:
    picker = state.pending_trigger_picker_idx
    if picker is None or action.card_index is None:
        return _IMPOSSIBLE
    queue = (
        state.pending_trigger_queue_turn
        if picker == state.active_player_idx
        else state.pending_trigger_queue_other
    )
    if not 0 <= action.card_index < len(queue):
        return _IMPOSSIBLE
    trigger = queue[action.card_index]
    try:
        card_def = library.get_by_id(trigger.source_card_numeric_id)
        effect = card_def.effects[trigger.effect_idx]
    except (KeyError, IndexError):
        return 0.0
    score = _card_value(card_def) * 0.05
    if effect.effect_type in (EffectType.DAMAGE, EffectType.DESTROY, EffectType.REVIVE):
        score += 5.0 + effect.amount
    elif effect.effect_type in (EffectType.DRAW, EffectType.TUTOR, EffectType.GRANT_DARK_MATTER):
        score += 3.0 + effect.amount
    return score


def _modal_score(
    state: GameState,
    library: CardLibrary,
    player_idx: int,
    action: Action,
) -> float:
    player = state.players[player_idx]
    side = player.side
    if action.action_type == ActionType.TUTOR_SELECT:
        try:
            deck_idx = state.pending_tutor_matches[action.card_index]
            return _card_value(library.get_by_id(player.deck[deck_idx]))
        except (IndexError, TypeError, KeyError):
            return _IMPOSSIBLE
    if action.action_type == ActionType.REVIVE_PLACE:
        try:
            card_def = library.get_by_id(player.grave[action.card_index])
            return _card_value(card_def) + _position_value(action.position, side, card_def)
        except (IndexError, TypeError, KeyError):
            return _IMPOSSIBLE
    if action.action_type == ActionType.CONJURE_DEPLOY:
        try:
            card_def = library.get_by_id(state.pending_conjure_deploy_card)
            return _card_value(card_def) + _position_value(action.position, side, card_def)
        except (TypeError, KeyError):
            return _IMPOSSIBLE
    if action.action_type == ActionType.DEATH_TARGET_PICK:
        target = next(
            (
                m
                for m in state.minions
                if action.target_pos is not None and m.position == action.target_pos
            ),
            None,
        )
        if target is None:
            return _IMPOSSIBLE
        return _minion_value(target, library) * (1.0 if target.owner != side else -1.0)
    if action.action_type == ActionType.TRIGGER_PICK:
        return _trigger_score(state, library, action)
    if action.action_type in (
        ActionType.DECLINE_TUTOR,
        ActionType.DECLINE_CONJURE,
        ActionType.DECLINE_REVIVE,
        ActionType.DECLINE_TRIGGER,
    ):
        return -100.0
    return _IMPOSSIBLE


def _pending_stack_entry(state: GameState, library: CardLibrary):
    if not state.react_stack:
        return None
    entry = state.react_stack[-1]
    numeric_id = getattr(entry, "card_numeric_id", None)
    if numeric_id is None:
        return None
    try:
        return entry, library.get_by_id(numeric_id)
    except KeyError:
        return None


def _react_score(
    state: GameState,
    library: CardLibrary,
    player_idx: int,
    action: Action,
) -> float:
    if action.action_type == ActionType.PASS:
        return 0.0
    player = state.players[player_idx]
    if action.card_index is None or not 0 <= action.card_index < len(player.hand):
        return _IMPOSSIBLE
    card_def = library.get_by_id(player.hand[action.card_index])
    mana_cost = (
        card_def.react_mana_cost
        if card_def.react_mana_cost is not None
        else card_def.mana_cost
    )
    react_effects = (
        (card_def.react_effect,)
        if card_def.react_effect is not None
        else card_def.effects
    )
    if any(effect.effect_type == EffectType.NEGATE for effect in react_effects or ()):
        pending_entry = _pending_stack_entry(state, library)
        if pending_entry is None:
            return -1.0
        entry, pending = pending_entry
        caster_idx = getattr(entry, "player_idx", 1 - player_idx)
        target_pos = getattr(entry, "target_pos", None)
        dynamic = _effects_value(
            state,
            library,
            caster_idx,
            pending,
            Action(action_type=ActionType.PLAY_CARD, target_pos=target_pos),
            {TriggerType.ON_PLAY},
            destroyed_attack_override=getattr(entry, "destroyed_attack", 0),
            allow_hidden_zones=False,
        )
        threat = pending.mana_cost * 2.0 + _card_value(pending) * 0.35
        threat += max(0.0, dynamic)
        return threat - mana_cost * 2.0 - 6.0
    value = _effects_value(
        state,
        library,
        player_idx,
        card_def,
        action,
        {TriggerType.ON_PLAY},
        effects=react_effects,
    )
    if card_def.react_effect and card_def.react_effect.effect_type == EffectType.DEPLOY_SELF:
        value += _card_value(card_def) + _position_value(
            action.target_pos,
            player.side,
            card_def,
        )
    return value - mana_cost * 1.5 - 1.0


def _main_score(
    state: GameState,
    library: CardLibrary,
    player_idx: int,
    action: Action,
) -> float:
    if action.action_type == ActionType.PLAY_CARD:
        return _play_score(state, library, player_idx, action)
    if action.action_type == ActionType.PLAY_FROM_EXHAUST:
        return _play_score(state, library, player_idx, action, from_exhaust=True)
    if action.action_type == ActionType.ATTACK:
        return _attack_score(state, library, action)
    if action.action_type == ActionType.SACRIFICE:
        return _sacrifice_score(state, library, action)
    if action.action_type == ActionType.MOVE:
        return _move_score(state, library, action)
    if action.action_type == ActionType.ACTIVATE_ABILITY:
        return _ability_score(state, library, player_idx, action)
    if action.action_type == ActionType.TRANSFORM:
        return _transform_score(state, library, action)
    if action.action_type == ActionType.DRAW:
        return _rest_score(state, player_idx)
    if action.action_type == ActionType.DECLINE_POST_MOVE_ATTACK:
        return 0.0
    if action.action_type == ActionType.PASS:
        return -1.0
    return _modal_score(state, library, player_idx, action)


def _best(actions: Sequence[Action], scorer) -> tuple[Action, float]:
    best_action = actions[0]
    best_score = scorer(best_action)
    for action in actions[1:]:
        score = scorer(action)
        if score > best_score:
            best_action = action
            best_score = score
    return best_action, best_score


def pick_preview_action(
    state: GameState,
    library: CardLibrary,
    legal: Sequence[Action],
) -> Action | None:
    """Return the highest-value supplied legal action, or ``None`` if empty."""
    actions = list(legal)
    if not actions:
        return None
    player_idx = _decision_player_idx(state)

    modal_types = {
        ActionType.TUTOR_SELECT,
        ActionType.CONJURE_DEPLOY,
        ActionType.DEATH_TARGET_PICK,
        ActionType.REVIVE_PLACE,
        ActionType.TRIGGER_PICK,
        ActionType.DECLINE_TUTOR,
        ActionType.DECLINE_CONJURE,
        ActionType.DECLINE_REVIVE,
        ActionType.DECLINE_TRIGGER,
    }
    if any(action.action_type in modal_types for action in actions):
        return _best(
            actions,
            lambda action: _modal_score(state, library, player_idx, action),
        )[0]

    if state.phase == TurnPhase.REACT:
        return _best(
            actions,
            lambda action: _react_score(state, library, player_idx, action),
        )[0]

    # MAGIC now competes normally for the shared action bank.
    return _best(
        actions,
        lambda action: _main_score(state, library, player_idx, action),
    )[0]
