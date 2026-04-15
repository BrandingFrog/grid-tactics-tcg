"""React stack -- LIFO react window with chaining and resolution.

Implements the react window mechanic (D-04 through D-07):
  - After a main-phase action, opponent gets a react opportunity
  - React cards chain: after a react, the other player can counter-react
  - Stack resolves LIFO (last react played resolves first)
  - Passing closes that player's chain and resolves the stack

Entry points:
  - handle_react_action(): Handle PLAY_REACT or PASS during react window
  - resolve_react_stack(): Resolve stack LIFO and advance turn
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

from grid_tactics.actions import Action
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import ActionType, CardType, EffectType, TriggerType, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.minion import BURN_DAMAGE, MinionInstance
from grid_tactics.types import AUTO_DRAW_ENABLED, MAX_REACT_STACK_DEPTH


@dataclass(frozen=True, slots=True)
class ReactEntry:
    """A single entry on the react stack.

    Tracks who played it, which card, and the optional target position
    for single-target react effects.
    """

    player_idx: int                              # who played this react
    card_index: int                              # which card from hand (at time of play)
    card_numeric_id: int                         # card definition ID for effect lookup
    target_pos: Optional[tuple[int, int]] = None  # for single-target react effects


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _replace_player(
    players: tuple,
    idx: int,
    new_player,
) -> tuple:
    """Return a new players tuple with one player replaced."""
    if idx == 0:
        return (new_player, players[1])
    return (players[0], new_player)


def tick_status_effects(state: GameState, library: CardLibrary) -> GameState:
    """Tick per-minion status effects at the start of the active player's turn.

    Boolean burn semantics (locked):
    - Who ticks: minions OWNED BY the newly-active player that have
      `is_burning == True`. A burning minion takes one tick per full
      turn cycle (when their owner becomes active again).
    - When ticks: Called from `resolve_react_stack` AFTER the active
      player flip, BEFORE the PASSIVE pipeline and mana regen for the
      new active player. So a minion that gets the burn aura applied
      this turn will take its first tick on the owner's NEXT turn.
    - Damage: BURN_DAMAGE per tick (5).
    - Persistence: is_burning is NOT cleared by ticking. It persists
      until the minion dies.
    - Death: If current_health <= 0 after burn damage, route through
      the existing death-cleanup path used by combat.
    - Order: Iterate minions in (row, col) order for determinism.
    """
    from dataclasses import replace as _replace

    active_side = state.players[state.active_player_idx].side

    # Snapshot in (row, col) order for determinism
    ordered = sorted(state.minions, key=lambda m: (m.position[0], m.position[1]))

    new_minions_by_id: dict[int, MinionInstance] = {}
    for m in ordered:
        if not m.is_burning:
            continue
        if m.owner != active_side:
            continue
        new_minions_by_id[m.instance_id] = _replace(
            m,
            current_health=m.current_health - BURN_DAMAGE,
        )

    if not new_minions_by_id:
        return state

    new_minions = tuple(
        new_minions_by_id.get(m.instance_id, m) for m in state.minions
    )
    state = _replace(state, minions=new_minions)

    # Route any newly-dead minions through the standard death-cleanup path
    # so on-death effects (and game-over checks) fire.
    from grid_tactics.action_resolver import _check_game_over, _cleanup_dead_minions
    state = _cleanup_dead_minions(state, library)
    state = _check_game_over(state)
    return state


def _fire_passive_effects(
    state: GameState, library: CardLibrary,
) -> GameState:
    """Fire PASSIVE-trigger effects on every minion currently on the board.

    Called once per turn flip from `resolve_react_stack`, after status ticks
    but before the new active player draws/regens. Iteration order is
    (row, col) for determinism.

    Handles, among others:
      - Emberplague Rat's burn aura (BURN, target=ADJACENT)
      - Fallen Paladin's passive_heal (PASSIVE_HEAL, target=SELF_OWNER)

    Newly-dead minions (e.g. from a future damaging passive) are routed
    through the standard cleanup path.
    """
    from grid_tactics.effect_resolver import resolve_effect
    from grid_tactics.action_resolver import (
        _check_game_over, _cleanup_dead_minions,
    )

    active_side = state.players[state.active_player_idx].side

    ordered_ids = [
        m.instance_id
        for m in sorted(state.minions, key=lambda m: (m.position[0], m.position[1]))
    ]
    for inst_id in ordered_ids:
        m = state.get_minion(inst_id)
        if m is None:
            continue  # died from a previous passive earlier in this pass
        card_def = library.get_by_id(m.card_numeric_id)
        for effect in card_def.effects:
            if effect.trigger != TriggerType.PASSIVE:
                continue
            # Heal-aura semantics: PASSIVE_HEAL ticks once per full turn
            # cycle, gated to the OWNER becoming active. Burn-aura
            # (EffectType.BURN) still fires every turn flip so adjacent
            # enemies get refreshed regardless of whose turn it is.
            if effect.effect_type == EffectType.PASSIVE_HEAL and m.owner != active_side:
                continue
            state = resolve_effect(
                state, effect, m.position, m.owner, library, target_pos=None,
            )

    state = _cleanup_dead_minions(state, library)
    state = _check_game_over(state)
    return state


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def handle_react_action(
    state: GameState, action: Action, library: CardLibrary,
) -> GameState:
    """Handle an action during the react window.

    Valid actions during REACT phase:
      - PASS: resolve the stack LIFO and advance the turn
      - PLAY_REACT: push a react card onto the stack, switch to counter-react

    Args:
        state: Current game state (must be in REACT phase).
        action: The action to apply (PASS or PLAY_REACT).
        library: CardLibrary for card definition lookups.

    Returns:
        New GameState after handling the react action.

    Raises:
        ValueError: If the action is invalid during REACT phase.
    """
    if action.action_type == ActionType.PASS:
        return resolve_react_stack(state, library)

    if action.action_type == ActionType.PLAY_REACT:
        return _play_react(state, action, library)

    raise ValueError(
        f"Invalid action type {action.action_type.name} during REACT phase. "
        f"Only PASS and PLAY_REACT are allowed."
    )


def _play_react(
    state: GameState, action: Action, library: CardLibrary,
) -> GameState:
    """Process a PLAY_REACT action: validate, spend mana, push to stack, switch player.

    Validates:
      - Card is react-eligible (CardType.REACT or is_multi_purpose)
      - Sufficient mana (mana_cost for React, react_mana_cost for multi-purpose)
      - Stack depth < MAX_REACT_STACK_DEPTH
    """
    # Validate stack depth
    if len(state.react_stack) >= MAX_REACT_STACK_DEPTH:
        raise ValueError(
            f"React stack depth at maximum ({MAX_REACT_STACK_DEPTH}). "
            f"Cannot play more react cards."
        )

    react_idx = state.react_player_idx
    player = state.players[react_idx]

    # Get card from hand
    if action.card_index is None or action.card_index < 0 or action.card_index >= len(player.hand):
        raise ValueError(f"Invalid card_index: {action.card_index}")

    card_numeric_id = player.hand[action.card_index]
    card_def = library.get_by_id(card_numeric_id)

    # Determine if card is react-eligible and the appropriate cost
    if card_def.card_type == CardType.REACT:
        mana_cost = card_def.mana_cost
    elif card_def.is_multi_purpose:
        mana_cost = card_def.react_mana_cost
    elif (card_def.card_type == CardType.MAGIC
          and card_def.react_condition is not None
          and card_def.react_mana_cost is not None):
        # Magic+react multi-purpose
        mana_cost = card_def.react_mana_cost
    else:
        raise ValueError(
            f"Card '{card_def.card_id}' ({card_def.card_type.name}) is not react-eligible. "
            f"Only REACT cards and multi-purpose cards can be played during react window."
        )

    # Validate mana
    if player.current_mana < mana_cost:
        raise ValueError(
            f"Insufficient mana: have {player.current_mana}, need {mana_cost}"
        )

    # Spend mana and discard card from hand to graveyard
    new_player = player.spend_mana(mana_cost)
    new_player = new_player.discard_from_hand(card_numeric_id)
    new_players = _replace_player(state.players, react_idx, new_player)

    # Create ReactEntry and push onto stack
    entry = ReactEntry(
        player_idx=react_idx,
        card_index=action.card_index,
        card_numeric_id=card_numeric_id,
        target_pos=action.target_pos,
    )
    new_stack = state.react_stack + (entry,)

    # Switch react_player_idx to other player (counter-react opportunity, D-05)
    new_react_player_idx = 1 - react_idx

    return replace(
        state,
        players=new_players,
        react_stack=new_stack,
        react_player_idx=new_react_player_idx,
    )


def resolve_react_stack(
    state: GameState, library: CardLibrary,
) -> GameState:
    """Resolve the react stack LIFO and advance the turn.

    Iterates over the stack in reverse order (LIFO, D-06).
    For each entry:
      - REACT cards: resolve all ON_PLAY effects
      - Multi-purpose cards: resolve the react_effect only

    After resolution:
      - Clean up dead minions
      - Clear react state
      - Advance turn (flip active player, increment turn_number)
      - Regenerate mana for the new active player
    """
    from grid_tactics.effect_resolver import resolve_effect

    # Resolve stack LIFO (D-06)
    # Track negated entries -- a NEGATE effect cancels the next entry in the stack
    negated_indices: set[int] = set()

    stack_list = list(reversed(state.react_stack))
    for i, entry in enumerate(stack_list):
        # Skip if this entry was negated by a previous NEGATE
        if i in negated_indices:
            continue

        card_def = library.get_by_id(entry.card_numeric_id)
        caster_owner = state.players[entry.player_idx].side

        if card_def.card_type == CardType.REACT:
            # Check if this react has NEGATE effects
            has_negate = any(
                e.effect_type == EffectType.NEGATE
                for e in card_def.effects
            )
            if has_negate:
                # NEGATE cancels the next entry in the stack (the action being countered)
                if i + 1 < len(stack_list):
                    negated_indices.add(i + 1)
                # Non-negate effects on the same card still resolve
                for effect in card_def.effects:
                    if effect.trigger == TriggerType.ON_PLAY and effect.effect_type != EffectType.NEGATE:
                        state = resolve_effect(
                            state, effect, (0, 0), caster_owner, library,
                            entry.target_pos,
                        )
            else:
                # Normal react -- resolve all ON_PLAY effects
                for effect in card_def.effects:
                    if effect.trigger == TriggerType.ON_PLAY:
                        state = resolve_effect(
                            state, effect, (0, 0), caster_owner, library,
                            entry.target_pos,
                        )
        elif card_def.is_multi_purpose:
            # Resolve the react_effect only for multi-purpose cards
            if card_def.react_effect is not None:
                if card_def.react_effect.effect_type == EffectType.DEPLOY_SELF:
                    # DEPLOY_SELF: deploy this minion to the board at target_pos
                    if entry.target_pos is not None:
                        from grid_tactics.minion import MinionInstance
                        new_minion = MinionInstance(
                            instance_id=state.next_minion_id,
                            card_numeric_id=entry.card_numeric_id,
                            owner=state.players[entry.player_idx].side,
                            position=entry.target_pos,
                            current_health=card_def.health,
                        )
                        new_board = state.board.place(
                            entry.target_pos[0], entry.target_pos[1],
                            new_minion.instance_id,
                        )
                        state = replace(
                            state,
                            board=new_board,
                            minions=state.minions + (new_minion,),
                            next_minion_id=state.next_minion_id + 1,
                        )
                else:
                    state = resolve_effect(
                        state, card_def.react_effect, (0, 0), caster_owner, library,
                        entry.target_pos,
                    )
        elif (card_def.card_type == CardType.MAGIC
              and card_def.react_condition is not None):
            # Magic+react: resolve ON_PLAY effects (same as pure react cards)
            for effect in card_def.effects:
                if effect.trigger == TriggerType.ON_PLAY:
                    state = resolve_effect(
                        state, effect, (0, 0), caster_owner, library,
                        entry.target_pos,
                    )

    # Clean up dead minions after react resolution
    from grid_tactics.action_resolver import _cleanup_dead_minions, _check_game_over
    state = _cleanup_dead_minions(state, library)

    # Win/draw detection after react resolution (Phase 4)
    state = _check_game_over(state)
    if state.is_game_over:
        # Game is over -- clear react state but don't advance turn
        return replace(
            state,
            react_stack=(),
            react_player_idx=None,
            pending_action=None,
        )

    # If the cleanup opened a death-trigger modal, defer turn advancement
    # until the dying minion's owner resolves the pick. The modal is
    # driven by resolve_action's pending_death_target gate; once drained,
    # it re-enters the turn-advance tail inline (see action_resolver.py).
    if state.pending_death_target is not None:
        return state

    # Advance turn: flip active player, increment turn number, clear react state
    new_active_idx = 1 - state.active_player_idx
    state = replace(
        state,
        react_stack=(),
        react_player_idx=None,
        pending_action=None,
        phase=TurnPhase.ACTION,
        active_player_idx=new_active_idx,
        turn_number=state.turn_number + 1,
    )

    # Phase 14.3: tick per-minion status effects (burning) AFTER turn flip
    # but BEFORE mana regen / draw for the new active player.
    state = tick_status_effects(state, library)
    if state.is_game_over:
        return state

    # Fire PASSIVE-trigger effects for every minion on the board (e.g.
    # Emberplague Rat's burn aura, Fallen Paladin's passive_heal). One pass
    # per turn flip, processed in (row, col) order for determinism.
    state = _fire_passive_effects(state, library)
    if state.is_game_over:
        return state

    # Regenerate mana for the new active player at turn start.
    # Skip on turn 2: P2's first action must start at STARTING_MANA to
    # match P1's first action (turn 1). Regen applies from turn 3 onward.
    if state.turn_number > 2:
        new_active_player = state.players[new_active_idx].regenerate_mana()
        new_players = _replace_player(state.players, new_active_idx, new_active_player)
        state = replace(state, players=new_players)

    # Auto-draw for the new active player at turn start (only if enabled)
    if AUTO_DRAW_ENABLED:
        active_player = state.players[new_active_idx]
        if active_player.deck:
            drawn_player, _card_id = active_player.draw_card()
            new_players = _replace_player(state.players, new_active_idx, drawn_player)
            state = replace(state, players=new_players)

    return state
