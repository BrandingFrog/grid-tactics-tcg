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
from grid_tactics.enums import ActionType, CardType, EffectType, PlayerSide, TriggerType, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.minion import BURN_DAMAGE, MinionInstance
from grid_tactics.types import AUTO_DRAW_ENABLED, MAX_REACT_STACK_DEPTH


@dataclass(frozen=True, slots=True)
class ReactEntry:
    """A single entry on the react stack.

    Tracks who played it, which card, and the optional target position
    for single-target react effects.

    Phase 14.7-01: Originator fields support deferred magic resolution.
    When a magic card is CAST, its cost resolves immediately but its
    ON_PLAY effects are captured as an "originator" entry at the bottom
    of the react stack. The chain then resolves LIFO so a NEGATE played
    on top of the originator can cancel the cast entirely.

    Fields:
        is_originator: True when this entry represents a pending
            magic-cast (or future summon/start-of-turn declaration)
            whose effects have NOT yet resolved. Regular reactions
            played via _play_react stay at the default False.
        origin_kind: Classifies the originator type. Currently only
            "magic_cast". Future: "summon_declaration",
            "start_of_turn", etc.
        source_minion_id: Reserved for future origin_kinds that refer
            to a specific minion (e.g. a summon declaration or an
            on-death trigger). Always None for magic_cast.
        effect_payload: Captured ON_PLAY effect tuple for a magic_cast
            originator. Each entry is (effect_idx, target_pos, caster_owner_int).
            Tuple-of-tuples to keep the dataclass hashable-friendly.
        destroyed_attack: Captured at cast time from the destroy-ally
            cost (if any). Used by `scale_with` effects at resolution.
        destroyed_dm: Dark-matter stacks captured at cast time from the
            destroy-ally cost. Used by scale_with=destroyed_attack_plus_dm.
    """

    player_idx: int                              # who played this react
    card_index: int                              # which card from hand (at time of play)
    card_numeric_id: int                         # card definition ID for effect lookup
    target_pos: Optional[tuple[int, int]] = None  # for single-target react effects

    # Phase 14.7-01: Originator fields (all default-valued for backward compat)
    is_originator: bool = False
    origin_kind: Optional[str] = None            # "magic_cast" | (future: "summon_declaration", ...)
    source_minion_id: Optional[int] = None       # future: origin-minion id
    effect_payload: Optional[tuple] = None       # tuple of (effect_idx, target_pos, caster_owner_int)
    destroyed_attack: int = 0                    # captured for scale_with at cast time
    destroyed_dm: int = 0                        # captured for scale_with at cast time


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

    # Calculate burn bonus from opponent's aura minions (BURN_BONUS effect)
    from grid_tactics.enums import EffectType, TriggerType
    opponent_side = PlayerSide.PLAYER_1 if active_side == PlayerSide.PLAYER_2 else PlayerSide.PLAYER_2
    burn_bonus = 0
    for m in state.minions:
        if m.owner != opponent_side or m.current_health <= 0:
            continue
        card_def = library.get_by_id(m.card_numeric_id)
        for eff in card_def.effects:
            if eff.effect_type == EffectType.BURN_BONUS and eff.trigger == TriggerType.AURA:
                burn_bonus += eff.amount

    total_burn = BURN_DAMAGE + burn_bonus

    new_minions_by_id: dict[int, MinionInstance] = {}
    for m in ordered:
        if not m.is_burning:
            continue
        if m.owner != active_side:
            continue
        new_minions_by_id[m.instance_id] = _replace(
            m,
            current_health=m.current_health - total_burn,
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
# Phase 14.7-02: Turn-phase transition helpers
# ---------------------------------------------------------------------------
#
# The 3-phase turn model (START_OF_TURN -> ACTION -> END_OF_TURN) is wired
# here. Each helper is a pure GameState -> GameState transition. The state
# machine looks like:
#
#   enter_start_of_turn(state)
#       |  (14.7-03 will fire ON_START_OF_TURN triggers + open REACT)
#       v
#   close_start_react_and_enter_action(state)   <- PASS-PASS exit
#       |
#       v
#   [ACTION phase — player plays actions, each opens a REACT window with
#    react_context=AFTER_ACTION / react_return_phase=ACTION]
#       |
#       v
#   resolve_react_stack(state)  [return_phase == ACTION legacy path]
#       -> close_end_react_and_advance_turn(state)
#       |
#       v
#   enter_end_of_turn(state)
#       |  (14.7-03 will fire ON_END_OF_TURN triggers + open REACT)
#       v
#   close_end_react_and_advance_turn(state)     <- PASS-PASS exit
#       -> _close_end_of_turn_and_flip(state)
#       -> enter_start_of_turn(new active player)
#
# For 14.7-02 the new phases are PLACEHOLDER: enter_start_of_turn and
# enter_end_of_turn currently pass straight through (no triggers, no react
# window). 14.7-03 will hook trigger firing + REACT opening into both.


def _close_end_of_turn_and_flip(
    state: GameState, library: CardLibrary,
) -> GameState:
    """Advance to the next player's turn (outgoing player's end-of-turn tail).

    This is the byte-identical turn-advance tail that used to live inline
    at the bottom of ``resolve_react_stack``. Split out so that both the
    main react-stack path and future 14.7-03 end-of-turn trigger paths
    share one implementation.

    Order (preserved from the pre-14.7 resolve_react_stack tail):
      1. Flip ``discarded_this_turn`` -> ``discarded_last_turn`` for the
         outgoing player and clear this-turn for them.
      2. Flip ``active_player_idx`` and increment ``turn_number``; set
         ``phase=ACTION`` (14.7-03 will change this to START_OF_TURN).
      3. ``tick_status_effects`` — burn ticks for new active player's
         minions.
      4. ``_fire_passive_effects`` — PASSIVE-triggered effects for every
         minion in (row, col) order.
      5. Mana regen for new active player (suppressed on turn 2).
      6. Auto-draw for new active player (if AUTO_DRAW_ENABLED and deck
         non-empty).

    14.7-03 will redistribute (3)-(4) into ``enter_start_of_turn`` and any
    end-of-turn-side passive will move to ``enter_end_of_turn``. For now
    this helper keeps all behavior in one place.

    Rule-1 bug fix captured here: the old inline resolve_react_stack tail
    did NOT flip ``discarded_this_turn`` -> ``discarded_last_turn`` for
    the outgoing player — only the pending_death_target resume path in
    action_resolver.py did. Centralizing here fixes that gap silently;
    the only play-condition that reads ``discarded_last_turn`` is
    Prohibition which was unaffected because it's played as a react on
    the opponent's turn.
    """
    # Flip discard tracking for the outgoing player BEFORE the
    # active-player flip.
    old_active_idx = state.active_player_idx
    old_player = state.players[old_active_idx]
    updated_old = replace(
        old_player,
        discarded_last_turn=old_player.discarded_this_turn,
        discarded_this_turn=False,
    )
    state = replace(
        state,
        players=_replace_player(state.players, old_active_idx, updated_old),
    )

    # Advance turn: flip active player, increment turn number, phase=ACTION.
    new_active_idx = 1 - old_active_idx
    state = replace(
        state,
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


def enter_start_of_turn(
    state: GameState, library: CardLibrary,
) -> GameState:
    """Enter START_OF_TURN phase for ``state.active_player_idx``.

    14.7-02: placeholder. 14.7-03 will fire ON_START_OF_TURN triggered
    effects and open a REACT window (react_context=AFTER_START_TRIGGER,
    react_return_phase=START_OF_TURN). For now we immediately pass
    through to ACTION so no observable behavior changes.
    """
    # Placeholder: immediately transition to ACTION. 14.7-03 will insert
    # trigger firing + react-window opening between here and ACTION.
    return replace(state, phase=TurnPhase.ACTION)


def enter_end_of_turn(
    state: GameState, library: CardLibrary,
) -> GameState:
    """Enter END_OF_TURN phase for ``state.active_player_idx``.

    14.7-02: placeholder. 14.7-03 will fire ON_END_OF_TURN triggered
    effects and open a REACT window (react_context=BEFORE_END_OF_TURN,
    react_return_phase=END_OF_TURN). For now we immediately perform the
    turn-advance tail and enter the next player's START_OF_TURN.
    """
    # Placeholder: immediately run the end-of-turn tail + enter new turn.
    # 14.7-03 will insert trigger firing + react-window opening BEFORE
    # _close_end_of_turn_and_flip.
    state = _close_end_of_turn_and_flip(state, library)
    if state.is_game_over:
        return state
    return enter_start_of_turn(state, library)


def close_start_react_and_enter_action(
    state: GameState, library: CardLibrary,
) -> GameState:
    """After a START_OF_TURN react window PASS-PASSes, enter ACTION.

    Clears react bookkeeping and sets phase=ACTION. No turn flip — the
    turn player still owns their ACTION phase.
    """
    return replace(
        state,
        phase=TurnPhase.ACTION,
        react_stack=(),
        react_player_idx=None,
        pending_action=None,
        react_context=None,
        react_return_phase=None,
    )


def close_end_react_and_advance_turn(
    state: GameState, library: CardLibrary,
) -> GameState:
    """After an END_OF_TURN (or legacy after-action) react window PASS-PASSes, advance turn.

    Clears react bookkeeping, runs the end-of-turn tail for the current
    active player, and enters the NEW active player's START_OF_TURN.
    """
    state = replace(
        state,
        react_stack=(),
        react_player_idx=None,
        pending_action=None,
        react_context=None,
        react_return_phase=None,
    )
    state = _close_end_of_turn_and_flip(state, library)
    if state.is_game_over:
        return state
    return enter_start_of_turn(state, library)


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

        # Phase 14.7-01: Originator branch — magic_cast originators carry
        # their captured ON_PLAY effect payload. Resolve each effect via
        # the same dispatch the old _cast_magic inline loop used.
        if entry.is_originator and entry.origin_kind == "magic_cast":
            for (effect_idx, target_pos_raw, _caster_owner_int) in (entry.effect_payload or ()):
                if effect_idx < 0 or effect_idx >= len(card_def.effects):
                    continue
                effect = card_def.effects[effect_idx]
                tp = tuple(target_pos_raw) if target_pos_raw is not None else None
                # Re-apply scale_with bonus captured at cast time
                resolved_effect = effect
                if effect.scale_with in ("destroyed_attack", "destroyed_attack_plus_dm"):
                    if effect.scale_with == "destroyed_attack_plus_dm":
                        bonus = entry.destroyed_attack + entry.destroyed_dm
                    else:
                        bonus = entry.destroyed_attack
                    if bonus > 0:
                        resolved_effect = replace(effect, amount=(effect.amount or 0) + bonus)
                # Dispatch TUTOR/REVIVE to pending-entry shims (same routing as
                # the old _cast_magic inline path).
                if resolved_effect.effect_type == EffectType.TUTOR:
                    from grid_tactics.effect_resolver import _enter_pending_tutor
                    state = _enter_pending_tutor(
                        state, card_def, caster_owner, library,
                        amount=max(1, resolved_effect.amount or 1),
                    )
                elif resolved_effect.effect_type == EffectType.REVIVE:
                    from grid_tactics.action_resolver import _enter_pending_revive
                    state = _enter_pending_revive(
                        state, card_def, caster_owner, library,
                    )
                else:
                    state = resolve_effect(
                        state, resolved_effect, (0, 0), caster_owner, library, tp,
                    )
            continue  # originator handled; skip the card_type dispatch below

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
            # Magic+react: if the card carries a distinct react_effect, resolve
            # only that (e.g. Acidic Rain's draw-a-card react). Otherwise fall
            # back to the card's ON_PLAY effects (e.g. Illicit Stones shares).
            if card_def.react_effect is not None:
                state = resolve_effect(
                    state, card_def.react_effect, (0, 0), caster_owner, library,
                    entry.target_pos,
                )
            else:
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

    # Phase 14.7-02: Dispatch on ``react_return_phase`` — where did we
    # come from? Pre-14.7 callers didn't set this field so it's None,
    # which we treat as the legacy after-action path (return ACTION ->
    # advance turn).
    return_phase = state.react_return_phase or TurnPhase.ACTION

    if return_phase == TurnPhase.ACTION:
        # Legacy after-action react window closed — advance turn.
        return close_end_react_and_advance_turn(state, library)
    elif return_phase == TurnPhase.START_OF_TURN:
        # 14.7-03: after a start-of-turn react window, enter ACTION.
        return close_start_react_and_enter_action(state, library)
    elif return_phase == TurnPhase.END_OF_TURN:
        # 14.7-03: after an end-of-turn react window, advance turn.
        return close_end_react_and_advance_turn(state, library)
    else:
        # Shouldn't happen — default to turn advance for safety.
        return close_end_react_and_advance_turn(state, library)
