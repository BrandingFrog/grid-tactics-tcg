"""Heuristic policy for the Game Preview dummy seat (user 2026-07-10).

Deliberately NOT smart — just goal-directed enough that a solo preview
feels like a game instead of a punching bag: it resolves pending picks
(so modal states never stall the drain), sometimes plays reacts, and on
its turn works through: free magic casts (variant: a MAGIC doesn't
consume the action) > sacrifice > attack (prefers kills) > development
(most expensive of play/transform, with placement + targeting
heuristics) > activated abilities > move (most advanced landing) > REST.
Win condition is HP depletion, so damage and board presence ARE
"towards the goal".

Effect-aware since 2026-07-11 (user "improve the ai to use effects"):
- casts magic with real targeting (damage/burn/destroy at the beefiest
  enemy, heals at the most damaged ally, buffs at the strongest ally);
- uses TRANSFORM (Reanimated Bones) and ACTIVATE_ABILITY (Ratchanter's
  conjure, Dark Matter buffs) instead of ignoring those action types;
- deploys melee minions on the most advanced legal row and ranged
  minions on the back row;
- prefers the cheapest discard payment (mana mode over alt-cost mode).

Pure function of (state, library, legal_actions); uses stdlib random
(server-side only — never touches the deterministic engine RNG).
"""

from __future__ import annotations

import random
from typing import Optional, Sequence

from grid_tactics.actions import Action, pass_action
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import ActionType, CardType, EffectType, PlayerSide, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.types import manual_draw_variant

# Probability the dummy answers with a legal react instead of passing the
# window — high enough that the human sees the react/spell-stage flow in
# previews, low enough that it doesn't burn every card immediately.
REACT_PLAY_CHANCE = 0.5

_ENEMY_SEEKING = {EffectType.DAMAGE, EffectType.BURN, EffectType.DESTROY}
_ALLY_SEEKING = {
    EffectType.HEAL,
    EffectType.BUFF_ATTACK,
    EffectType.BUFF_HEALTH,
    EffectType.DARK_MATTER_BUFF,
}


def _effective_attack(minion, library: CardLibrary) -> int:
    try:
        return library.get_by_id(minion.card_numeric_id).attack + minion.attack_bonus
    except Exception:
        return minion.attack_bonus


def _minions_by_pos(state: GameState, side: PlayerSide, *, enemy: bool) -> dict:
    out = {}
    for m in state.minions:
        if m.current_health <= 0:
            continue
        if enemy == (m.owner != side):
            out[tuple(m.position)] = m
    return out


def _pick_targeted(
    actions: Sequence[Action],
    card_def,
    state: GameState,
    library: CardLibrary,
    my_side: PlayerSide,
) -> Action:
    """Choose among same-card play actions by where the effects want to
    land: damage-like at the beefiest enemy, heals at the most damaged
    ally, buffs at the strongest ally. Untargeted actions pass through."""
    eff_types = {e.effect_type for e in (card_def.effects or ())}
    wants_enemy = bool(eff_types & _ENEMY_SEEKING)
    wants_ally = not wants_enemy and bool(eff_types & _ALLY_SEEKING)
    if not (wants_enemy or wants_ally):
        return random.choice(list(actions))

    lookup = _minions_by_pos(state, my_side, enemy=wants_enemy)

    def score(a: Action) -> float:
        pos = a.target_pos
        m = lookup.get(tuple(pos)) if pos is not None else None
        if m is None:
            return -1.0
        if wants_enemy:
            # Remove the biggest threat.
            return _effective_attack(m, library)
        if EffectType.HEAL in eff_types:
            # Most damaged ally benefits most.
            try:
                missing = library.get_by_id(m.card_numeric_id).health \
                    + m.max_health_bonus - m.current_health
            except Exception:
                missing = 0
            return missing
        # Buffs: pump the strongest body.
        return _effective_attack(m, library)

    best = max(score(a) for a in actions)
    return random.choice([a for a in actions if score(a) == best])


def _pick_deploy(
    actions: Sequence[Action],
    card_def,
    my_side: PlayerSide,
) -> Action:
    """Minion placement: melee wants the most advanced legal row (saves
    forward moves), ranged wants the back row (stays out of reach)."""
    placed = [a for a in actions if a.position is not None]
    if not placed:
        return random.choice(list(actions))
    # P1 advances downward (increasing row), P2 upward (decreasing).
    advancing = 1 if my_side == PlayerSide.PLAYER_1 else -1
    ranged = (getattr(card_def, "range", 0) or 0) > 0
    direction = -advancing if ranged else advancing

    def row_score(a: Action) -> int:
        return a.position[0] * direction

    best = max(row_score(a) for a in placed)
    return random.choice([a for a in placed if row_score(a) == best])


def pick_preview_action(
    state: GameState,
    library: CardLibrary,
    legal: Sequence[Action],
) -> Optional[Action]:
    """Pick the dummy's next action from ``legal``. Returns None only for
    an empty legal set (caller falls back to its PASS failsafe)."""
    legal = list(legal)
    if not legal:
        return None

    by_type: dict[ActionType, list[Action]] = {}
    for a in legal:
        by_type.setdefault(a.action_type, []).append(a)

    def any_of(*types: ActionType) -> Optional[Action]:
        for t in types:
            if t in by_type:
                return random.choice(by_type[t])
        return None

    # --- Pending modal states: MUST resolve or the drain stalls ---------
    picked = any_of(
        ActionType.TUTOR_SELECT,
        ActionType.CONJURE_DEPLOY,
        ActionType.DEATH_TARGET_PICK,
        ActionType.REVIVE_PLACE,
        ActionType.TRIGGER_PICK,
    )
    if picked is not None:
        return picked

    # --- React windows: sometimes answer, else pass ---------------------
    if state.phase == TurnPhase.REACT:
        reacts = by_type.get(ActionType.PLAY_REACT)
        if reacts and random.random() < REACT_PLAY_CHANCE:
            return random.choice(reacts)
        if ActionType.PASS in by_type:
            return pass_action()
        return random.choice(legal)

    active_idx = state.active_player_idx
    player = state.players[active_idx]
    my_side = player.side

    def _play_def(a: Action):
        try:
            return library.get_by_id(player.hand[a.card_index])
        except Exception:
            return None

    plays = by_type.get(ActionType.PLAY_CARD, [])

    # --- Free-value magic (variant: a MAGIC cast hands the action back) --
    # Cast the most expensive affordable magic with real targeting BEFORE
    # spending the turn action — pure upside under the v4 rules.
    if manual_draw_variant():
        magic: dict[int, list[Action]] = {}
        for a in plays:
            d = _play_def(a)
            if d is not None and d.card_type == CardType.MAGIC:
                magic.setdefault(a.card_index, []).append(a)
        if magic:
            best_idx = max(
                magic, key=lambda i: getattr(_play_def(magic[i][0]), "mana_cost", 0),
            )
            return _pick_targeted(
                magic[best_idx], _play_def(magic[best_idx][0]),
                state, library, my_side,
            )

    # --- Damage first ----------------------------------------------------
    # Sacrifice hits the enemy player directly — always take it.
    if ActionType.SACRIFICE in by_type:
        return random.choice(by_type[ActionType.SACRIFICE])

    # Attack: prefer kills (biggest threat first), then the hardest hit.
    attacks = by_type.get(ActionType.ATTACK)
    if attacks:
        def atk_score(a: Action) -> float:
            attacker = state.get_minion(a.minion_id)
            target = state.get_minion(a.target_id)
            if attacker is None or target is None:
                return 0.0
            my_atk = _effective_attack(attacker, library)
            kills = my_atk >= target.current_health
            s = float(min(my_atk, target.current_health))
            if kills:
                # Killing outranks chip damage; among kills, remove the
                # biggest threat.
                s += 1000.0 + _effective_attack(target, library)
            return s

        best = max(atk_score(a) for a in attacks)
        return random.choice([a for a in attacks if atk_score(a) == best])

    # --- Development: most expensive of play / transform -----------------
    # (transform actions are only enumerated when affordable)
    candidates: list[tuple[int, str, object]] = []  # (cost, kind, payload)
    if plays:
        by_card: dict[int, list[Action]] = {}
        for a in plays:
            by_card.setdefault(a.card_index, []).append(a)
        for idx, acts in by_card.items():
            d = _play_def(acts[0])
            if d is None:
                continue
            # Prefer the cheapest payment: mana mode over alt-cost mode,
            # fewest cost-discards otherwise.
            min_discards = min(len(a.discard_card_indices or ()) for a in acts)
            acts = [
                a for a in acts
                if len(a.discard_card_indices or ()) == min_discards
            ]
            candidates.append((d.mana_cost, "play", (acts, d)))
    for a in by_type.get(ActionType.TRANSFORM, ()):
        cost = 0
        m = state.get_minion(a.minion_id)
        if m is not None:
            try:
                opts = library.get_by_id(m.card_numeric_id).transform_options or ()
                cost = next(
                    (mc for tid, mc in opts if tid == a.transform_target), 0,
                )
            except Exception:
                cost = 0
        candidates.append((cost, "transform", a))
    if candidates:
        best_cost = max(c[0] for c in candidates)
        _, kind, payload = random.choice(
            [c for c in candidates if c[0] == best_cost],
        )
        if kind == "transform":
            return payload
        acts, d = payload
        if d.card_type == CardType.MINION:
            return _pick_deploy(acts, d, my_side)
        return _pick_targeted(acts, d, state, library, my_side)

    # --- Activated abilities (Ratchanter's conjure, DM buffs) ------------
    abilities = by_type.get(ActionType.ACTIVATE_ABILITY)
    if abilities:
        # Targeted abilities (e.g. dark_matter_buff) want the strongest
        # friendly body; untargeted ones are all equivalent.
        ally_at = _minions_by_pos(state, my_side, enemy=False)

        def ab_score(a: Action) -> float:
            if a.target_pos is None:
                return 0.0
            m = ally_at.get(tuple(a.target_pos))
            return _effective_attack(m, library) if m is not None else -1.0

        best = max(ab_score(a) for a in abilities)
        return random.choice([a for a in abilities if ab_score(a) == best])

    # Advance the board — prefer the move that lands most advanced.
    moves = by_type.get(ActionType.MOVE)
    if moves:
        advancing = 1 if my_side == PlayerSide.PLAYER_1 else -1

        def move_score(a: Action) -> int:
            return (a.position[0] * advancing) if a.position is not None else -99

        best = max(move_score(a) for a in moves)
        return random.choice([a for a in moves if move_score(a) == best])

    # Variant v4 (2026-07-11): REST (the DRAW slot) beats a dead PASS —
    # +1 mana and +1 draw for the same action.
    if ActionType.DRAW in by_type:
        return by_type[ActionType.DRAW][0]

    # Declines for pending flavours where nothing above applied.
    picked = any_of(
        ActionType.DECLINE_POST_MOVE_ATTACK,
        ActionType.DECLINE_TUTOR,
        ActionType.DECLINE_CONJURE,
        ActionType.DECLINE_REVIVE,
        ActionType.DECLINE_TRIGGER,
    )
    if picked is not None:
        return picked

    if ActionType.PASS in by_type:
        return pass_action()
    return random.choice(legal)
