"""Action resolver -- validates and applies all main-phase action types.

Main entry point: resolve_action(state, action, library) -> GameState

Handles the 5 main-phase action types:
  - PASS:      No-op, transitions to react window
  - DRAW:      Moves top card from deck to hand
  - MOVE:      Moves minion to adjacent empty cell
  - PLAY_CARD: Deploys minion or casts magic
  - ATTACK:    Simultaneous damage exchange (D-01)

After every action:
  1. Dead minion cleanup (D-02): removes minions with health <= 0
  2. Phase transition to REACT (D-13): opponent gets react window
"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

from grid_tactics.actions import Action
from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.cards import CardDefinition
from grid_tactics.effect_resolver import resolve_effects_for_trigger
from grid_tactics.engine_events import (
    EVT_ATTACK_RESOLVED,
    EVT_CARD_BURNED,
    EVT_CARD_DISCARDED,
    EVT_CARD_DRAWN,
    EVT_CARD_PLAYED,
    EVT_GAME_OVER,
    EVT_MANA_CHANGE,
    EVT_MINION_DIED,
    EVT_MINION_HP_CHANGE,
    EVT_MINION_MOVED,
    EVT_MINION_SUMMONED,
    EVT_MINION_TRANSFORMED,
    EVT_PENDING_MODAL_OPENED,
    EVT_PENDING_MODAL_RESOLVED,
    EVT_PHASE_CHANGED,
    EVT_MINION_SACRIFICED,
    EVT_PLAYER_HP_CHANGE,
    EVT_REACT_WINDOW_OPENED,
    EventStream,
    EVT_PASS_DECLARED,
)
from grid_tactics.enums import (
    ActionType,
    CardType,
    EffectType,
    PlayerSide,
    ReactContext,
    TriggerType,
    TurnPhase,
)
from grid_tactics.game_state import GameState
from grid_tactics.minion import MinionInstance
from grid_tactics.phase_contracts import assert_phase_contract
from grid_tactics.player import Player
from grid_tactics.types import (
    BACK_ROW_P1,
    BACK_ROW_P2,
    GRID_ROWS,
    MAX_MANA_CAP,
    PLAYER_1_ROWS,
    PLAYER_2_ROWS,
    manual_draw_variant,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _replace_player(
    players: tuple[Player, Player],
    idx: int,
    new_player: Player,
) -> tuple[Player, Player]:
    """Return a new players tuple with one player replaced."""
    if idx == 0:
        return (new_player, players[1])
    return (players[0], new_player)


def _emit_after_action_react_window_opened(
    state: GameState,
    event_collector: Optional[EventStream],
) -> None:
    """Emit EVT_REACT_WINDOW_OPENED for an action-triggered react window.

    Phase 14.8-05c fix: action_resolver.py's inline REACT transitions
    (magic cast originator, summon declaration, post-move-attack, generic
    after-action, conjure deploy, tutor resolve) all mutated state.phase
    = REACT without emitting the event. The client's eventQueue needs
    that event to open the spell stage, so without it the react window
    is visually invisible — the paladin-heal scenario "worked" only
    because react_stack.py emits on BEFORE_END_OF_TURN, but the Acidic
    Rain 3-deep chain broke because no emission happens at all.

    Call this right before returning a state whose phase is REACT due to
    an ACTION-phase transition.
    """
    if event_collector is None:
        return
    if state.phase != TurnPhase.REACT:
        return
    ctx = state.react_context.name if state.react_context is not None else None
    return_phase = (
        state.react_return_phase.name
        if state.react_return_phase is not None
        else TurnPhase.ACTION.name
    )
    event_collector.collect(
        EVT_REACT_WINDOW_OPENED,
        "system:enter_react",
        {
            "react_context": ctx,
            "react_player_idx": state.react_player_idx,
            "return_phase": return_phase,
        },
    )


def _replace_minion(
    minions: tuple[MinionInstance, ...],
    instance_id: int,
    new_minion: MinionInstance,
) -> tuple[MinionInstance, ...]:
    """Return a new minions tuple with one minion replaced by instance_id."""
    return tuple(
        new_minion if m.instance_id == instance_id else m
        for m in minions
    )


def _get_active_side(state: GameState) -> PlayerSide:
    """Return the PlayerSide of the active player."""
    return state.players[state.active_player_idx].side


def _is_orthogonal(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """Return True if positions share a row or column (orthogonal alignment)."""
    return a[0] == b[0] or a[1] == b[1]


def _can_attack(
    attacker: MinionInstance,
    defender: MinionInstance,
    attacker_card: CardDefinition,
) -> bool:
    """Check if attacker can reach defender based on attack range (D-03).

    Melee (range=0): orthogonally adjacent (manhattan == 1).
    Ranged (range>=1): star-shaped footprint --
        orthogonal arm: same row/col AND manhattan <= range + 1
        diagonal arm:  |dr| == |dc| AND 1 <= chebyshev <= range

    Range 1 -> 8 ortho + 4 diag = 12 tiles.
    Range 2 -> 12 ortho + 8 diag = 20 tiles.
    """
    a_pos = attacker.position
    d_pos = defender.position
    dr = abs(a_pos[0] - d_pos[0])
    dc = abs(a_pos[1] - d_pos[1])
    manhattan = dr + dc
    chebyshev = dr if dr > dc else dc
    attack_range = attacker_card.attack_range

    if attack_range == 0:
        # Melee: orthogonal adjacent only
        return manhattan == 1 and _is_orthogonal(a_pos, d_pos)
    else:
        orthogonal_in_range = _is_orthogonal(a_pos, d_pos) and manhattan <= attack_range + 1
        on_diagonal = dr == dc and dr >= 1 and chebyshev <= attack_range
        return orthogonal_in_range or on_diagonal


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------


def _apply_pass(
    state: GameState,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Apply PASS action — FREE (turn-structure redesign 2026-07).

    PASS no longer deals fatigue damage: fatigue now exists ONLY for
    empty-deck turn-start draws (see react_stack._close_end_of_turn_and_flip,
    which uses GameState.fatigue_counts as the escalating 10/20/30 counter).

    Handshake tracking: consecutive ACTION-phase passes across BOTH players
    are counted in GameState.consecutive_passes (react-window passes do NOT
    count — they route through handle_react_action, never here). When this
    PASS lands while the counter is already >= 1 (the opponent's
    immediately-previous action was also PASS), a Handshake occurs:
    handshake_pending is set (paid out at the end of this turn in
    _close_end_of_turn_and_flip) and the counter resets to 0 so Handshakes
    cannot chain off a single pass pair.
    """
    assert_phase_contract(state, "action:pass_action")
    # Rest rework (user 2026-07-10 v2): under the variant, PASS is a REST —
    # the passer gains +1 mana (capped) AND draws a card (overdraw-burns on
    # a full hand; empty deck simply skips the draw — never fatigue). The
    # dispatch site's generic mana-diff emitter surfaces the EVT_MANA_CHANGE;
    # the draw event is emitted here (it needs the card identity).
    if manual_draw_variant():
        passer_idx = state.active_player_idx
        passer = state.players[passer_idx]
        if passer.current_mana < MAX_MANA_CAP:
            passer = replace(passer, current_mana=passer.current_mana + 1)
        if passer.deck:
            passer, _rest_card_id, _rest_burned = passer.draw_card_with_overdraw()
            if event_collector is not None:
                event_collector.collect(
                    EVT_CARD_BURNED if _rest_burned else EVT_CARD_DRAWN,
                    "action:pass_action",
                    {
                        "player_idx": passer_idx,
                        "source": "rest",
                        # view_filter redacts the identity for the opponent
                        # on non-burn draws (same contract as every draw).
                        "card_numeric_id": _rest_card_id,
                    },
                )
        state = replace(
            state,
            players=_replace_player(state.players, passer_idx, passer),
        )
    new_count = state.consecutive_passes + 1
    if new_count >= 2:
        # Handshake! Reset the streak — no chaining.
        return replace(
            state,
            consecutive_passes=0,
            handshake_pending=True,
        )
    return replace(state, consecutive_passes=new_count)


def _apply_draw(
    state: GameState,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Apply DRAW action. Moves top card from deck to hand.

    Manual-draw variant (user 2026-07-10): DRAW is a legal main-phase
    action again. A full hand overdraw-burns the drawn card to the
    Exhaust Pile (revealed) like every other draw path.

    Raises ValueError if the active player's deck is empty.
    """
    assert_phase_contract(state, "action:draw")
    drawer_idx = state.active_player_idx
    player = state.players[drawer_idx]
    if not player.deck:
        raise ValueError("Cannot draw from empty deck")
    new_player, card_id, burned = player.draw_card_with_overdraw()
    new_players = _replace_player(state.players, drawer_idx, new_player)
    state = replace(state, players=new_players)
    if event_collector is not None:
        event_collector.collect(
            EVT_CARD_BURNED if burned else EVT_CARD_DRAWN,
            "action:draw",
            {
                "player_idx": drawer_idx,
                "source": "draw_action",
                # view_filter redacts the identity for the opponent on
                # non-burn draws; the drawer's client animates deck→hand.
                "card_numeric_id": card_id,
            },
        )
    return state


def _apply_move(
    state: GameState,
    action: Action,
    library: CardLibrary = None,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Apply MOVE action. Moves minion forward one cell in its lane.

    Validates:
      - Minion exists and belongs to active player
      - Target position is forward-only in the same column (lane-locked)
      - Target cell is empty

    2026-07 card-audit fix (Furryroach): emits EVT_MINION_MOVED for the
    acting minion BEFORE the ON_MOVE trigger dispatch (previously the
    dispatch site emitted it after, so March-sweep events would have
    preceded the mover's own event), and threads ``event_collector``
    into the ON_MOVE dispatch so March advances emit per-ally
    EVT_MINION_MOVED events too.
    """
    assert_phase_contract(state, "action:move")
    active_side = _get_active_side(state)

    # Find the minion
    minion = state.get_minion(action.minion_id)
    if minion is None:
        raise ValueError(f"Minion {action.minion_id} not found")
    if minion.owner != active_side:
        raise ValueError(
            f"Cannot move opponent's minion (belongs to {minion.owner.name})"
        )

    target_pos = action.position
    if target_pos is None:
        raise ValueError("Move action requires a target position")

    # Lane-locked: must stay in the same column
    src_row, src_col = minion.position
    tgt_row, tgt_col = target_pos
    if tgt_col != src_col:
        raise ValueError(
            f"Lane-locked: cannot move laterally from col {src_col} to col {tgt_col}"
        )

    # Forward-only: P1 moves down (+1 row), P2 moves up (-1 row).
    # LEAP minions may move multiple tiles forward in the same column when
    # the immediate forward tile is blocked. We delegate the geometry check
    # to the legal-actions enumerator (legal_actions.py) and just verify
    # here that the target row is in the forward direction and reachable.
    delta = 1 if active_side == PlayerSide.PLAYER_1 else -1
    if (tgt_row - src_row) * delta <= 0:
        raise ValueError(
            f"Forward-only: {active_side.name} at row {src_row} must move "
            f"forward (delta={delta}), not to row {tgt_row}"
        )
    # Single-step is always allowed when target is empty (handled below).
    # Multi-step (leap) requires a LEAP effect on the minion's card AND the
    # immediate forward tile to be blocked.
    if abs(tgt_row - src_row) > 1:
        if library is None:
            raise ValueError("Multi-tile move requires library for LEAP validation")
        from grid_tactics.enums import EffectType as _ET
        minion_card = library.get_by_id(minion.card_numeric_id)
        leap_amount = 0
        for eff in minion_card.effects:
            if eff.effect_type == _ET.LEAP:
                leap_amount = max(leap_amount, eff.amount or 1)
        if leap_amount <= 0:
            raise ValueError(
                f"Minion {minion.instance_id} has no LEAP -- cannot multi-step move"
            )
        # Verify the immediate forward tile is occupied (precondition for leap)
        first_step_row = src_row + delta
        if state.board.get(first_step_row, src_col) is None:
            raise ValueError("LEAP only legal when the forward tile is blocked")
        # Leap distance cap: jumping N enemies lands N+1 tiles away; the
        # card ruling caps N at leap_amount (Rathopper: 1 enemy, 2 tiles).
        if abs(tgt_row - src_row) > 1 + leap_amount:
            raise ValueError("LEAP target row exceeds leap distance")
        # Phase 14.8 bugfix: every jumped tile must hold a live ENEMY —
        # per data/GLOSSARY.md Leap jumps over a blocking enemy to the
        # next available tile and CANNOT leap allies. Previously only the
        # first tile was checked (and not for ownership), so a
        # hand-crafted action could leap an ally blocker or skip an
        # unverified intermediate tile.
        step_row = src_row + delta
        while step_row != tgt_row:
            occupant_id = state.board.get(step_row, src_col)
            if occupant_id is None:
                raise ValueError(
                    "LEAP requires every jumped tile to be enemy-occupied"
                )
            occupant = state.get_minion(occupant_id)
            if occupant is None or occupant.owner == active_side:
                raise ValueError("LEAP cannot jump over ally minions")
            step_row += delta

    # Check target cell is empty
    if state.board.get(target_pos[0], target_pos[1]) is not None:
        raise ValueError(
            f"Cell {target_pos} is occupied"
        )

    # Update board: remove from old position, place at new position
    new_board = state.board.remove(minion.position[0], minion.position[1])
    new_board = new_board.place(target_pos[0], target_pos[1], minion.instance_id)

    # Update minion position
    new_minion = replace(minion, position=target_pos)
    new_minions = _replace_minion(state.minions, minion.instance_id, new_minion)
    state = replace(state, board=new_board, minions=new_minions)

    # Emit the acting minion's move event BEFORE the ON_MOVE dispatch so
    # any March-sweep events it spawns come after it in seq order.
    if event_collector is not None:
        event_collector.collect(
            EVT_MINION_MOVED,
            "action:move",
            {
                "instance_id": minion.instance_id,
                "from": [src_row, src_col],
                "to": list(target_pos),
                "owner_idx": state.active_player_idx,
            },
        )

    # ON_MOVE trigger: fire any effects with trigger=ON_MOVE on this minion
    # (e.g. Furryroach's march_forward). Mirrors tensor engine behaviour.
    # Must happen AFTER the position update so the March sweep sees the new
    # location (and the mover is correctly excluded from the sweep).
    if library is not None:
        state = resolve_effects_for_trigger(
            state, TriggerType.ON_MOVE, new_minion, library,
            contract_source="trigger:on_move",
            event_collector=event_collector,
        )

    # Phase 14.1 / 14.7-08: For melee (range=0) minions, if there is at least
    # one in-range enemy from the new tile, enter pending-post-move-attack
    # state AND open a post-move REACT window (14.7-08 supersedes 14.1's
    # single-window semantics per spec v2 §4.1 — the melee chain now opens
    # TWO independent react windows, one after the move and one after the
    # optional attack).
    if library is not None:
        attacker_card = library.get_by_id(new_minion.card_numeric_id)
        if attacker_card.attack_range == 0 and _has_any_attack_target(state, new_minion, library):
            state = replace(state, pending_post_move_attacker_id=new_minion.instance_id)

    return state


def _has_any_attack_target(
    state: GameState, attacker_minion: MinionInstance, library: CardLibrary,
) -> bool:
    """Return True if attacker has at least one in-range enemy from current tile."""
    attacker_card = library.get_by_id(attacker_minion.card_numeric_id)
    for m in state.minions:
        if m.owner == attacker_minion.owner:
            continue
        if _can_attack(attacker_minion, m, attacker_card):
            return True
    return False


def _apply_play_card(
    state: GameState, action: Action, library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Apply PLAY_CARD action. Deploys a minion or casts magic.

    Validates:
      - Card exists in hand at card_index
      - Sufficient mana
      - Deployment zone (D-08: melee any friendly row, D-09: ranged back row only)
      - React cards cannot be played during ACTION phase
    """
    assert_phase_contract(state, "action:play_card")
    active_idx = state.active_player_idx
    player = state.players[active_idx]
    active_side = player.side

    # Get card from hand
    if action.card_index is None or action.card_index < 0 or action.card_index >= len(player.hand):
        raise ValueError(f"Invalid card_index: {action.card_index}")
    card_numeric_id = player.hand[action.card_index]
    card_def = library.get_by_id(card_numeric_id)

    # React cards cannot be played in ACTION phase
    if card_def.card_type == CardType.REACT:
        raise ValueError("React cards cannot be played during ACTION phase")

    # Unique enforcement (2026-07 card-audit fix, Giant Rat): a unique
    # minion cannot be played while a live copy owned by the same player
    # is on the board. Mirrors the tensor-engine gate; also enforced in
    # legal_actions so the UI / RL mask never offers it, but re-checked
    # here so out-of-band resolve_action callers are rejected too.
    if card_def.card_type == CardType.MINION and card_def.unique:
        for m in state.minions:
            if (
                m.owner == active_side
                and m.is_alive
                and m.card_numeric_id == card_numeric_id
            ):
                raise ValueError(
                    f"Card '{card_def.card_id}' is Unique — a copy is "
                    f"already alive on your board"
                )

    # Check mana (with cost reduction)
    from grid_tactics.legal_actions import effective_mana_cost
    eff_cost = effective_mana_cost(card_def, state, state.active_player_idx)
    if player.current_mana < eff_cost:
        raise ValueError(
            f"Insufficient mana: have {player.current_mana}, need {eff_cost}"
        )

    # HP cost: caster takes damage to their own life total before the card
    # resolves. Enforced in legal_actions; re-checked here as defence.
    if card_def.hp_cost is not None:
        if player.hp < card_def.hp_cost:
            raise ValueError(
                f"Insufficient HP: have {player.hp}, need {card_def.hp_cost}"
            )
        player = replace(player, hp=player.hp - card_def.hp_cost)

    # Phase 14.5 pile semantics:
    #   - MINION plays are removed from hand and placed on the board; the card
    #     only enters grave if/when the minion dies (and only if it was
    #     from_deck=True — tokens vanish).
    #   - MAGIC plays are one-shots and route to grave immediately via
    #     discard_from_hand (the card is "played").
    new_player = player.spend_mana(eff_cost)
    if card_def.card_type == CardType.MINION:
        new_player = new_player.remove_from_hand(card_numeric_id)
    else:
        new_player = new_player.discard_from_hand(card_numeric_id)

    # Discard cost: exhaust card(s) of the required tribe from hand. This is
    # a DISCARD (hand → Exhaust Pile), NOT a SACRIFICE (board-crossing win
    # move). Prefer the user's explicit pick list (discard_card_indices),
    # fall back to the legacy single-index field, and finally auto-pick the
    # first tribe match. Indices reference the ORIGINAL hand (before the
    # played card was removed) to stay stable across the intermediate
    # remove_from_hand call.
    if card_def.discard_cost_tribe:
        discard_needed = card_def.discard_cost_count
        pick_indices = list(action.discard_card_indices or ())
        if not pick_indices and action.discard_card_index is not None:
            pick_indices = [action.discard_card_index]
        for _discard_i in range(discard_needed):
            discard_id = None
            if _discard_i < len(pick_indices):
                pick_idx = pick_indices[_discard_i]
                if 0 <= pick_idx < len(player.hand):
                    candidate_id = player.hand[pick_idx]
                    cand_def = library.get_by_id(candidate_id)
                    tribe_match = (card_def.discard_cost_tribe == "any"
                                   or card_def.discard_cost_tribe in (cand_def.tribe or "").split())
                    if tribe_match and candidate_id in new_player.hand:
                        discard_id = candidate_id
            if discard_id is None:
                # Fallback: auto-pick first matching card
                for hand_card_id in new_player.hand:
                    if card_def.discard_cost_tribe == "any":
                        discard_id = hand_card_id
                        break
                    hand_card_def = library.get_by_id(hand_card_id)
                    if card_def.discard_cost_tribe in (hand_card_def.tribe or "").split():
                        discard_id = hand_card_id
                        break
            if discard_id is None:
                raise ValueError(
                    f"No {card_def.discard_cost_tribe} card in hand to discard"
                )
            # Discard: send from hand to exhaust pile.
            new_player = new_player.exhaust_from_hand(discard_id)
            # 2026-07-08 timing audit (F2): a paid discard cost previously
            # emitted NOTHING — the card vanished from hand at drain end.
            # Emit EVT_CARD_BURNED with source='discard_cost' per card so
            # the client can play a hand→exhaust fly at the causal beat.
            if event_collector is not None:
                event_collector.collect(
                    EVT_CARD_BURNED,
                    "action:play_card",
                    {
                        "player_idx": active_idx,
                        "card_numeric_id": discard_id,
                        "source": "discard_cost",
                    },
                )
            # Fire ON_DISCARD effects on the discarded card
            discarded_def = library.get_by_id(discard_id)
            discard_effects = [e for e in discarded_def.effects if e.trigger == TriggerType.ON_DISCARD]
            if discard_effects:
                # Temporarily commit player state so effects can read board
                tmp_players = _replace_player(state.players, active_idx, new_player)
                tmp_state = replace(state, players=tmp_players)
                from grid_tactics.effect_resolver import resolve_effect
                for eff in discard_effects:
                    tmp_state = resolve_effect(
                        tmp_state, eff, (0, 0), active_side, library,
                        contract_source="trigger:on_discard",
                        event_collector=event_collector,
                    )
                # Pull updated state back (effects may have changed minions)
                state = tmp_state
                new_player = state.players[active_idx]

    new_players = _replace_player(state.players, active_idx, new_player)
    state = replace(state, players=new_players)

    if card_def.card_type == CardType.MINION:
        return _deploy_minion(state, action, card_def, card_numeric_id, active_side, library)
    elif card_def.card_type == CardType.MAGIC:
        return _cast_magic(
            state, action, card_def, card_numeric_id, active_side, library,
            event_collector=event_collector,
        )
    else:
        raise ValueError(f"Cannot play card type {card_def.card_type.name} during ACTION phase")


def _deploy_minion(
    state: GameState,
    action: Action,
    card_def: CardDefinition,
    card_numeric_id: int,
    active_side: PlayerSide,
    library: CardLibrary,
) -> GameState:
    """Push a summon_declaration originator onto the react stack (Phase 14.7-04).

    Deployment becomes a compound two-window event (spec §4.2):
      * Window A (AFTER_SUMMON_DECLARATION): opens here immediately after
        validation. Opponent may negate the summon itself — a successful
        NEGATE destroys the entire summon and the costs are FORFEIT (mana,
        discard, and destroy-ally do NOT refund — harsh by design).
      * Window B (AFTER_SUMMON_EFFECT): opened only after Window A resolves
        WITHOUT negation, by ``resolve_summon_declaration_originator``
        (react_stack.py). Window B covers the minion's ON_SUMMON effects;
        a NEGATE there cancels the effects only — the minion stays on the
        board.

    Validation (deploy zone + occupancy) still runs here so an illegal
    target raises BEFORE any cost is paid. Once validation passes we push
    a ``summon_declaration`` originator entry onto the react stack; the
    minion is NOT placed on the board at this call site. It lands later
    (during stack resolution) via ``resolve_summon_declaration_originator``
    — OR never, if Window A negates.

    D-08: Melee (range=0) can deploy to any empty cell in friendly rows.
    D-09: Ranged (range>=1) must deploy to back row only.

    Cost semantics: ``_apply_play_card`` already spent mana + handled the
    discard/HP cost BEFORE invoking _deploy_minion, so the summon_declaration
    originator only needs to remember the deployment position + card.
    """
    assert_phase_contract(state, "action:play_card")
    deploy_pos = action.position
    if deploy_pos is None:
        raise ValueError("Minion deployment requires a position")

    row, col = deploy_pos

    # Validate deployment zone
    if active_side == PlayerSide.PLAYER_1:
        friendly_rows = PLAYER_1_ROWS
        back_row = BACK_ROW_P1
    else:
        friendly_rows = PLAYER_2_ROWS
        back_row = BACK_ROW_P2

    if card_def.attack_range == 0:
        # Melee: any friendly row
        if row not in friendly_rows:
            raise ValueError(
                f"Melee minion must deploy to friendly rows {friendly_rows}, got row {row}"
            )
    else:
        # Ranged: back row only
        if row != back_row:
            raise ValueError(
                f"Ranged minion must deploy to back row {back_row}, got row {row}"
            )

    # Check cell is empty (minion doesn't land yet — this just rejects
    # illegal targets before the cost becomes forfeit to Window A).
    if state.board.get(row, col) is not None:
        raise ValueError(f"Cell ({row}, {col}) is occupied")

    # Push summon_declaration originator onto the react stack.
    # card_index=-1: the card has already been removed from hand by the
    # caller (see _apply_play_card). source_minion_id=None: the minion
    # doesn't exist yet — it is created in resolve_summon_declaration_originator.
    from grid_tactics.react_stack import ReactEntry
    originator = ReactEntry(
        player_idx=state.active_player_idx,
        card_index=-1,
        card_numeric_id=card_numeric_id,
        target_pos=tuple(deploy_pos),
        is_originator=True,
        origin_kind="summon_declaration",
        source_minion_id=None,
        effect_payload=None,  # no effects at declaration stage
    )
    new_stack = state.react_stack + (originator,)
    return replace(
        state,
        react_stack=new_stack,
        react_player_idx=1 - state.active_player_idx,
        phase=TurnPhase.REACT,
        react_context=ReactContext.AFTER_SUMMON_DECLARATION,
        react_return_phase=TurnPhase.ACTION,
    )


def _enter_pending_revive(
    state: GameState,
    card_def: CardDefinition,
    active_side: PlayerSide,
    library: CardLibrary,
) -> GameState:
    """Enter pending_revive state so the player can choose deploy positions.

    Checks that the grave has at least one matching card and there's at
    least one empty deploy cell. Sets pending_revive fields on the state;
    actual placement happens in _apply_revive_place.
    """
    revive_id = card_def.revive_card_id
    if not revive_id:
        return state

    revive_def = library.get_by_card_id(revive_id)
    if revive_def is None:
        return state

    revive_numeric_id = library.get_numeric_id(revive_id)

    amount = 0
    for eff in card_def.effects:
        if eff.effect_type == EffectType.REVIVE:
            amount = eff.amount
            break
    if amount <= 0:
        return state

    player_idx = 0 if active_side == PlayerSide.PLAYER_1 else 1
    player = state.players[player_idx]

    # Check grave has matching cards
    grave_count = sum(1 for cid in player.grave if cid == revive_numeric_id)
    if grave_count == 0:
        return state

    # Check at least one empty deploy cell exists (2026-07 card-audit
    # fix: the docstring promised this check but it was never
    # implemented — a full deploy zone forced the player through a
    # modal whose only legal action was DECLINE_REVIVE). Deploy rows
    # mirror legal_actions._pending_revive_actions: melee (range 0)
    # may use any own-side row, ranged only the back row.
    if player_idx == 0:
        deploy_rows = (
            PLAYER_1_ROWS if revive_def.attack_range == 0 else (BACK_ROW_P1,)
        )
    else:
        deploy_rows = (
            PLAYER_2_ROWS if revive_def.attack_range == 0 else (BACK_ROW_P2,)
        )
    has_empty_cell = any(
        state.board.get(r, c) is None
        for r in deploy_rows
        for c in range(5)
    )
    if not has_empty_cell:
        return state

    # Cap at available grave copies
    actual_amount = min(amount, grave_count)

    return replace(
        state,
        pending_revive_player_idx=player_idx,
        pending_revive_card_id=revive_id,
        pending_revive_remaining=actual_amount,
    )


def _apply_revive_place(
    state: GameState,
    action: Action,
    library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Place one revived minion from grave to the board at action.position.

    Removes one matching card from grave, creates a MinionInstance,
    decrements pending_revive_remaining. If remaining hits 0 or no more
    grave copies, clears the pending state.

    2026-07-08 timing audit (F4): emits EVT_MINION_SUMMONED with
    source='revive' — this creation path previously rendered silently
    on the final-state snapshot.
    """
    assert_phase_contract(state, "action:revive_place")
    player_idx = state.pending_revive_player_idx
    card_id = state.pending_revive_card_id
    remaining = state.pending_revive_remaining

    if player_idx is None or card_id is None or remaining <= 0:
        raise ValueError("No pending revive to place")

    pos = action.position
    if pos is None:
        raise ValueError("REVIVE_PLACE requires a position")

    row, col = pos
    if state.board.get(row, col) is not None:
        raise ValueError(f"Cell ({row}, {col}) is occupied")

    revive_def = library.get_by_card_id(card_id)
    revive_numeric_id = library.get_numeric_id(card_id)
    active_side = PlayerSide.PLAYER_1 if player_idx == 0 else PlayerSide.PLAYER_2
    player = state.players[player_idx]

    # Remove one copy from grave
    grave = list(player.grave)
    try:
        grave.remove(revive_numeric_id)
    except ValueError:
        raise ValueError(f"No {card_id} in grave to revive")

    # Create minion
    minion = MinionInstance(
        instance_id=state.next_minion_id,
        card_numeric_id=revive_numeric_id,
        owner=active_side,
        position=pos,
        current_health=revive_def.health,
    )
    new_board = state.board.place(row, col, minion.instance_id)

    # 2026-07-08 timing audit (F4): summon event for the revive path so
    # the client's playMinionSummoned animates it (grave → board).
    if event_collector is not None:
        event_collector.collect(
            EVT_MINION_SUMMONED,
            "action:revive_place",
            {
                "instance_id": minion.instance_id,
                "card_numeric_id": revive_numeric_id,
                "owner_idx": player_idx,
                "position": list(pos),
                "source": "revive",
            },
        )

    # Update player grave
    new_player = replace(player, grave=tuple(grave))
    players = list(state.players)
    players[player_idx] = new_player

    new_remaining = remaining - 1
    # Check if more copies exist in grave for continued placement
    more_in_grave = revive_numeric_id in grave  # grave already has one removed

    if new_remaining <= 0 or not more_in_grave:
        # Done — clear pending
        return replace(
            state,
            board=new_board,
            minions=state.minions + (minion,),
            next_minion_id=state.next_minion_id + 1,
            players=tuple(players),
            pending_revive_player_idx=None,
            pending_revive_card_id=None,
            pending_revive_remaining=0,
        )
    else:
        # More to place
        return replace(
            state,
            board=new_board,
            minions=state.minions + (minion,),
            next_minion_id=state.next_minion_id + 1,
            players=tuple(players),
            pending_revive_remaining=new_remaining,
        )


def _resume_after_pending_revive(
    state: GameState,
    action: Action,
    library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Resume the post-action flow after the pending_revive modal clears.

    2026-07 card-audit fix (Ratical Resurrection): REVIVE_PLACE /
    DECLINE_REVIVE previously returned the raw state with
    phase=ACTION and the CASTER still active — the caster got a free
    second action and the turn never advanced. This runs the same
    resume tail as the pending-tutor gate: stash pending_action, clean
    up dead minions, check game over, defer on any newly-opened modal,
    then open the AFTER_ACTION react window whose close routes through
    close_end_react_and_advance_turn.
    """
    state = replace(state, pending_action=action)
    state = _cleanup_dead_minions(state, library, event_collector=event_collector)
    state = _check_game_over(state, event_collector=event_collector)
    if state.is_game_over:
        return state
    if state.pending_death_target is not None:
        return state
    if state.pending_trigger_picker_idx is not None:
        return state
    if state.phase == TurnPhase.REACT:
        _emit_after_action_react_window_opened(state, event_collector)
        return state
    state = replace(
        state,
        phase=TurnPhase.REACT,
        react_player_idx=1 - state.active_player_idx,
        react_context=ReactContext.AFTER_ACTION,
        # Preserve an in-flight react_return_phase (e.g. END_OF_TURN when
        # the revive was react-played on a Decay window) — same rule as
        # the pending-tutor resume.
        react_return_phase=state.react_return_phase or TurnPhase.ACTION,
    )
    _emit_after_action_react_window_opened(state, event_collector)
    return state


# ---------------------------------------------------------------------------
# Phase 14.7-05: TRIGGER_PICK / DECLINE_TRIGGER handlers
# ---------------------------------------------------------------------------


def _apply_trigger_pick(
    state: GameState, pick_idx: int, library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Pick one queued trigger (by queue index) and resolve it.

    Phase 14.7-05: When pending_trigger_picker_idx is set and the picker
    owner submits TRIGGER_PICK with card_index=queue_idx, this handler:
      1. Removes the picked entry from the owner's queue.
      2. Clears pending_trigger_picker_idx so the modal closes.
      3. Resolves the picked trigger via
         _resolve_trigger_and_open_react_window, which opens its own
         REACT window. The window's close re-enters drain via the
         drain-recheck hook in resolve_react_stack.

    Works for both turn-queue (picker_idx == active_player_idx) and
    other-queue (picker_idx == other_idx) — the is_turn_queue flag is
    derived from the picker's identity.
    """
    assert_phase_contract(state, "action:trigger_pick")
    from grid_tactics.react_stack import (
        _resolve_trigger_and_open_react_window,
        resume_after_trigger_drain,
    )

    picker = state.pending_trigger_picker_idx
    if picker is None:
        raise ValueError("TRIGGER_PICK submitted with no picker open")

    is_turn_queue = (picker == state.active_player_idx)
    q = (
        state.pending_trigger_queue_turn
        if is_turn_queue
        else state.pending_trigger_queue_other
    )
    if pick_idx < 0 or pick_idx >= len(q):
        raise ValueError(
            f"Invalid TRIGGER_PICK index {pick_idx} for queue of length {len(q)}"
        )

    picked = q[pick_idx]
    # Move the picked entry to the front of the queue so the shared helper
    # _resolve_trigger_and_open_react_window (which pops index 0 after
    # resolving) handles removal in exactly one place. This keeps the
    # auto-resolve path (singleton in queue) and the picked-resolve path
    # (2+ entries, picker chose one) symmetric — both funnel through the
    # same pop-and-open logic.
    reordered = (picked,) + q[:pick_idx] + q[pick_idx + 1:]
    if is_turn_queue:
        state = replace(state, pending_trigger_queue_turn=reordered)
    else:
        state = replace(state, pending_trigger_queue_other=reordered)

    # Close the picker modal — _resolve_trigger_and_open_react_window
    # opens its own REACT window, and the drain-recheck hook re-opens the
    # modal if the queue still has 2+ entries after this resolution.
    state = replace(state, pending_trigger_picker_idx=None)

    state = _resolve_trigger_and_open_react_window(
        state, picked, is_turn_queue=is_turn_queue, library=library,
        event_collector=event_collector,
    )
    # Phase 14.8 bugfix: if the picked (final) trigger fizzled and the
    # drain exhausted without opening a window/modal, resume the phase
    # flow the interrupted context still owes (see
    # resume_after_trigger_drain) instead of returning a state with no
    # react window / a wedged REACT phase.
    return resume_after_trigger_drain(
        state, library, event_collector=event_collector,
    )


def _apply_decline_trigger(
    state: GameState, library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Decline the remaining triggers in the picker owner's queue.

    Phase 14.7-05: DECLINE_TRIGGER clears ALL remaining entries in the
    picker owner's queue (they fizzle silently — no effects fire, no
    react windows open). The other-queue drain continues normally via
    drain_pending_trigger_queue.

    This is the "skip" escape hatch for situations where resolving more
    triggers is undesirable (e.g. a cascading heal that would push past
    lethal). Spec §7.3 grants the owner this option — the fizzled
    effects simply don't happen.
    """
    assert_phase_contract(state, "action:decline_trigger")
    from grid_tactics.react_stack import (
        drain_pending_trigger_queue,
        resume_after_trigger_drain,
    )

    picker = state.pending_trigger_picker_idx
    if picker is None:
        raise ValueError("DECLINE_TRIGGER submitted with no picker open")

    is_turn_queue = (picker == state.active_player_idx)
    if is_turn_queue:
        state = replace(
            state,
            pending_trigger_queue_turn=(),
            pending_trigger_picker_idx=None,
        )
    else:
        state = replace(
            state,
            pending_trigger_queue_other=(),
            pending_trigger_picker_idx=None,
        )

    # Re-enter drain — the other queue (if any) continues from where it
    # left off; otherwise we fall through to whatever phase transition
    # the prior react_return_phase encodes.
    state = drain_pending_trigger_queue(
        state, library, event_collector=event_collector,
    )
    # Phase 14.8 bugfix: drain_pending_trigger_queue performs NO phase
    # transition when both queues are empty — the comment above described
    # dispatch logic that did not exist. Resume the interrupted flow
    # (deferred after-action react window / react_return_phase dispatch)
    # so DECLINE_TRIGGER can neither skip the opponent's react window nor
    # strand the game in phase=REACT with react_player_idx=None.
    return resume_after_trigger_drain(
        state, library, event_collector=event_collector,
    )


def _cast_magic(
    state: GameState,
    action: Action,
    card_def: CardDefinition,
    card_numeric_id: int,
    active_side: PlayerSide,
    library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Cast a magic card (Phase 14.7-01 deferred resolution).

    Flow:
      1. Resolve costs IMMEDIATELY (per spec §4.2 — mana/HP/discard already
         handled by the caller; destroy-ally cost handled here).
      2. Capture the card's ON_PLAY effects into an "originator" ReactEntry
         and push it to the BOTTOM of the react stack.
      3. Transition to REACT phase so the opponent gets the first react
         opportunity. The originator's effects resolve LIFO when the stack
         drains; a Prohibition (or other NEGATE) played on top of the
         originator cancels the cast entirely.

    The card itself has already been removed from hand (discarded to grave)
    by the caller (_apply_play_card), so the card_index on the originator
    is -1 to signal "no hand reference".
    """
    assert_phase_contract(state, "action:play_card")
    # Destroy-ally cost: remove a friendly minion from the board before
    # effects resolve. Distinct from the board-crossing SACRIFICE action.
    # Captures destroyed_attack / destroyed_dm for scale_with effects at
    # originator resolution time.
    destroyed_attack = 0
    destroyed_dm = 0
    if card_def.destroy_ally_cost:
        # Defense in depth (mirrors the mana re-check): the cost is
        # mandatory — a missing/invalid destroyed_minion_id must not let
        # the spell cast for free.
        destroyed_minion = (
            state.get_minion(action.destroyed_minion_id)
            if action.destroyed_minion_id is not None
            else None
        )
        if (
            destroyed_minion is None
            or destroyed_minion.owner != active_side
            or not destroyed_minion.is_alive
        ):
            raise ValueError(
                f"Card '{card_def.card_id}' requires destroying a friendly "
                f"minion (destroy_ally_cost); destroyed_minion_id="
                f"{action.destroyed_minion_id} is missing or invalid"
            )
        destroyed_def = library.get_by_id(destroyed_minion.card_numeric_id)
        destroyed_attack = destroyed_def.attack + destroyed_minion.attack_bonus
        # Dark Matter pool redesign 2026-07: minions no longer carry DM.
        # ReactEntry.destroyed_dm is deprecated (kept at 0 for wire/save
        # compat); the DM half of scale_with="destroyed_attack_plus_dm"
        # now reads the CASTER PLAYER's pool at resolution time in
        # react_stack.resolve_react_stack.
        destroyed_dm = 0

        # Phase 14.8 bugfix: route the destroyed ally through the STANDARD
        # death pipeline instead of deleting it from the board directly.
        # Direct deletion skipped the minion's ON_DEATH triggers (Giant
        # Rat's promote, White Lasercannon's destroy) and never emitted
        # EVT_MINION_DIED. Zero its health and run _cleanup_dead_minions
        # in enqueue-only mode (_cleanup_skip_drain) so the on_death
        # PendingTriggers queue up WITHOUT opening a react window here —
        # the magic-cast originator pushed below must own the react
        # stack. The drain-recheck hook in resolve_react_stack picks the
        # queued triggers up after the cast's react window closes (the
        # cost stands even if the cast itself is negated).
        dying = replace(destroyed_minion, current_health=0)
        state = replace(
            state,
            minions=_replace_minion(
                state.minions, destroyed_minion.instance_id, dying,
            ),
        )
        global _cleanup_skip_drain
        _prev_skip = _cleanup_skip_drain
        _cleanup_skip_drain = True
        try:
            state = _cleanup_dead_minions(
                state, library, event_collector=event_collector,
            )
        finally:
            _cleanup_skip_drain = _prev_skip

    # Build captured-effect payload from ON_PLAY effects. Each entry:
    # (effect_idx, target_pos_tuple_or_None, caster_owner_int). Using
    # tuple-of-tuples keeps the frozen dataclass hashable-friendly.
    effects_payload: list[tuple] = []
    for eff_idx, effect in enumerate(card_def.effects):
        if effect.trigger != TriggerType.ON_PLAY:
            continue
        target_pos = tuple(action.target_pos) if action.target_pos is not None else None
        effects_payload.append((eff_idx, target_pos, int(active_side)))

    # Push cast_mode originator onto the react stack and enter REACT phase.
    # card_index=-1 because the card has already been discarded from hand.
    from grid_tactics.react_stack import ReactEntry
    originator = ReactEntry(
        player_idx=state.active_player_idx,
        card_index=-1,
        card_numeric_id=card_numeric_id,
        target_pos=tuple(action.target_pos) if action.target_pos is not None else None,
        is_originator=True,
        origin_kind="magic_cast",
        source_minion_id=None,
        effect_payload=tuple(effects_payload),
        destroyed_attack=destroyed_attack,
        destroyed_dm=destroyed_dm,
    )
    new_stack = state.react_stack + (originator,)
    return replace(
        state,
        react_stack=new_stack,
        react_player_idx=1 - state.active_player_idx,
        phase=TurnPhase.REACT,
        # Phase 14.7-02: tag the REACT window as "after an ACTION" so
        # resolve_react_stack returns to ACTION-phase turn advance.
        react_context=ReactContext.AFTER_ACTION,
        react_return_phase=TurnPhase.ACTION,
    )


def _apply_sacrifice(
    state: GameState, action: Action, library: CardLibrary,
) -> GameState:
    """Apply SACRIFICE action. Remove minion from board and deal damage to opponent.

    Validates:
      - Minion exists and belongs to active player
      - Minion is on opponent's back row (P1 minion at row 4, P2 minion at row 0)

    After validation:
      1. Look up card definition for base attack
      2. Calculate effective attack (base + attack_bonus)
      3. Remove minion from board and minions tuple
      4. Add minion's card to owner's grave
      5. Deal effective attack as damage to opponent
    """
    assert_phase_contract(state, "action:sacrifice")
    active_side = _get_active_side(state)

    # Find the minion
    minion = state.get_minion(action.minion_id)
    if minion is None:
        raise ValueError(f"Minion {action.minion_id} not found")
    if minion.owner != active_side:
        raise ValueError(
            f"Cannot sacrifice opponent's minion (belongs to {minion.owner.name})"
        )

    # Validate minion is on opponent's back row OR is a valid Leap sacrifice
    row = minion.position[0]
    on_back_row = (
        (active_side == PlayerSide.PLAYER_1 and row == BACK_ROW_P2)
        or (active_side == PlayerSide.PLAYER_2 and row == BACK_ROW_P1)
    )
    if not on_back_row:
        # Check for Leap sacrifice: all tiles ahead to back row are enemy-occupied
        card_def_check = library.get_by_id(minion.card_numeric_id)
        has_leap = any(e.effect_type == EffectType.LEAP for e in card_def_check.effects)
        if not has_leap:
            raise ValueError(
                f"Minion must be on opponent's back row to sacrifice, got row {row}"
            )
        # Verify path is fully enemy-blocked
        delta = 1 if active_side == PlayerSide.PLAYER_1 else -1
        check_row = row + delta
        all_enemy = True
        while 0 <= check_row < GRID_ROWS:
            occupant = next(
                (m for m in state.minions if m.position == (check_row, minion.position[1])),
                None,
            )
            if occupant is None or occupant.owner == active_side:
                all_enemy = False
                break
            check_row += delta
        if not all_enemy:
            raise ValueError(
                f"Leap sacrifice requires all tiles ahead to be enemy-occupied"
            )

    # Look up card definition for base attack
    card_def = library.get_by_id(minion.card_numeric_id)
    effective_attack = card_def.attack + minion.attack_bonus

    # Remove minion from board
    new_board = state.board.remove(minion.position[0], minion.position[1])

    # Remove minion from minions tuple
    new_minions = tuple(m for m in state.minions if m.instance_id != minion.instance_id)

    # Add card to owner's grave (tokens vanish silently — Phase 14.5).
    owner_idx = int(minion.owner)
    owner_player = state.players[owner_idx]
    if minion.from_deck:
        new_owner = replace(owner_player, grave=owner_player.grave + (minion.card_numeric_id,))
        new_players = _replace_player(state.players, owner_idx, new_owner)
    else:
        new_players = state.players

    # Deal damage to opponent
    opponent_idx = 1 - state.active_player_idx
    opponent = new_players[opponent_idx]
    new_opponent = opponent.take_damage(effective_attack)
    new_players = _replace_player(new_players, opponent_idx, new_opponent)

    return replace(state, board=new_board, minions=new_minions, players=new_players)


def _apply_transform(
    state: GameState, action: Action, library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Apply TRANSFORM action: convert a board minion into a different card form.

    Validates:
      - Minion exists and belongs to active player
      - Source card has transform_options containing the requested transform_target
      - Active player has enough mana for the transform cost

    Effect:
      - Spends mana
      - Replaces the minion's card_numeric_id with the target form
      - Resets current_health to the new form's max HP
      - Resets attack_bonus to 0
      - Transform-as-summon (user 2026-07-10): the NEW form's ON_SUMMON
        effects fire inline right after the swap — transforming into a
        card counts as summoning it (e.g. Reanimated Bones → Grave
        Caller grants +1 Dark Matter). Inline (no Window-B react window
        of its own): the transform action already gets the standard
        AFTER_ACTION react window around the whole action.
    """
    assert_phase_contract(state, "action:transform")
    active_side = _get_active_side(state)
    active_idx = state.active_player_idx

    minion = state.get_minion(action.minion_id)
    if minion is None:
        raise ValueError(f"Minion {action.minion_id} not found")
    if minion.owner != active_side:
        raise ValueError(
            f"Cannot transform opponent's minion (belongs to {minion.owner.name})"
        )

    source_card = library.get_by_id(minion.card_numeric_id)
    if not source_card.transform_options:
        raise ValueError(f"Minion {source_card.card_id} has no transform options")

    if action.transform_target is None:
        raise ValueError("TRANSFORM action missing transform_target")

    # Find the target in the source's transform_options
    matched_cost = None
    for target_card_id, mana_cost in source_card.transform_options:
        if target_card_id == action.transform_target:
            matched_cost = mana_cost
            break
    if matched_cost is None:
        raise ValueError(
            f"{source_card.card_id} cannot transform into {action.transform_target}"
        )

    # Mana check
    player = state.players[active_idx]
    if player.current_mana < matched_cost:
        raise ValueError(
            f"Insufficient mana to transform: have {player.current_mana}, need {matched_cost}"
        )

    # Look up target card
    try:
        target_numeric_id = library.get_numeric_id(action.transform_target)
    except KeyError:
        raise ValueError(f"Transform target card '{action.transform_target}' not in library")
    target_card = library.get_by_id(target_numeric_id)

    # Spend mana
    new_player = player.spend_mana(matched_cost)
    new_players = _replace_player(state.players, active_idx, new_player)

    # Replace minion stats — full reset: new card, fresh HP, clear all
    # buffs/status. 2026-07 card-audit fix: dark_matter_stacks is reset
    # too — the "completely fresh minion" ruling (and the tensor engine)
    # both zero DM on transform; the Python engine previously carried it
    # over.
    new_minion = replace(
        minion,
        card_numeric_id=target_numeric_id,
        current_health=target_card.health,
        attack_bonus=0,
        max_health_bonus=0,
        is_burning=False,
        burn_scope="owner",
        dark_matter_stacks=0,
    )
    new_minions = _replace_minion(state.minions, minion.instance_id, new_minion)

    state = replace(state, players=new_players, minions=new_minions)

    # Transform-as-summon (user 2026-07-10): fire the new form's ON_SUMMON
    # effects. Dispatch mirrors resolve_summon_declaration_effects (Window
    # B) — TUTOR/REVIVE route through their pending shims (no current
    # transform target uses them, but future ones behave identically);
    # everything else goes through resolve_effect.
    on_summon_effects = [
        e for e in target_card.effects if e.trigger == TriggerType.ON_SUMMON
    ]
    if on_summon_effects:
        from grid_tactics.effect_resolver import (
            _enter_pending_tutor,
            resolve_effect,
        )

        caster_owner = state.players[active_idx].side
        for effect in on_summon_effects:
            if effect.effect_type == EffectType.TUTOR:
                state = _enter_pending_tutor(
                    state, target_card, caster_owner, library,
                    amount=max(1, effect.amount or 1),
                    event_collector=event_collector,
                    origin="summon_effect",
                    contract_source="action:transform",
                )
            elif effect.effect_type == EffectType.REVIVE:
                state = _enter_pending_revive(
                    state, target_card, caster_owner, library,
                )
            else:
                state = resolve_effect(
                    state, effect, new_minion.position, caster_owner,
                    library, target_pos=None,
                    source_minion_id=minion.instance_id,
                    contract_source="action:transform",
                    event_collector=event_collector,
                )

    return state


def _apply_activate_ability(
    state: GameState, action: Action, library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Apply ACTIVATE_ABILITY: pay mana, resolve effect, counts as turn action.

    Supported effect types:
      - ``summon_token`` with target ``own_side_empty``: summon a fresh
        MinionInstance at ``action.target_pos`` (legacy shape).
      - ``conjure_rat_and_buff`` with target ``none`` (Ratchanter rework):
        stacking flat buff. Applies +(1 + owning player's Dark Matter
        pool) to every living friendly Rat's attack, max-HP bonus AND
        current HP (pool redesign 2026-07).
        Then, if the caster's deck contains any card with card_id ``rat``,
        enters the Phase 14.2 pending_tutor state so the player selects
        one to add to hand. If the deck has zero matches, the conjure is
        skipped silently and control returns directly to the react flow.
    """
    assert_phase_contract(state, "action:activate_ability")
    active_idx = state.active_player_idx
    active_side = _get_active_side(state)
    player = state.players[active_idx]

    minion = state.get_minion(action.minion_id)
    if minion is None:
        raise ValueError(f"Minion {action.minion_id} not found")
    if minion.owner != active_side:
        raise ValueError("Cannot activate opponent's minion ability")

    card_def = library.get_by_id(minion.card_numeric_id)
    ability = card_def.activated_ability
    if ability is None:
        raise ValueError(f"{card_def.card_id} has no activated ability")

    if player.current_mana < ability.mana_cost:
        raise ValueError(
            f"Insufficient mana: have {player.current_mana}, need {ability.mana_cost}"
        )

    target_pos = action.target_pos

    # Validate target tile per ability.target rule
    if ability.target == "own_side_empty":
        if target_pos is None:
            raise ValueError("ACTIVATE_ABILITY requires a target_pos")
        own_rows = PLAYER_1_ROWS if active_side == PlayerSide.PLAYER_1 else PLAYER_2_ROWS
        if target_pos[0] not in own_rows:
            raise ValueError(
                f"Target {target_pos} not on activator's own side"
            )
        if state.board.get(target_pos[0], target_pos[1]) is not None:
            raise ValueError(f"Target tile {target_pos} is occupied")
    elif ability.target == "single_target":
        # Targeted ability — must have a target_pos with a minion on it
        if target_pos is None:
            raise ValueError("ACTIVATE_ABILITY with single_target requires a target_pos")
        if state.board.get(target_pos[0], target_pos[1]) is None:
            raise ValueError(f"No minion at target tile {target_pos}")
    elif ability.target == "none":
        # Untargeted self-ability; target_pos must be None (ignored if set).
        pass
    else:
        raise ValueError(f"Unsupported activated_ability target '{ability.target}'")

    # Spend mana
    new_player = player.spend_mana(ability.mana_cost)
    new_players = _replace_player(state.players, active_idx, new_player)
    state = replace(state, players=new_players)

    # Resolve effect
    if ability.effect_type == "summon_token":
        if not ability.summon_card_id:
            raise ValueError("summon_token ability missing summon_card_id")
        try:
            token_numeric_id = library.get_numeric_id(ability.summon_card_id)
        except KeyError:
            raise ValueError(
                f"summon_token target '{ability.summon_card_id}' not in library"
            )
        token_def = library.get_by_id(token_numeric_id)
        # Phase 14.5: tokens spawned by activated abilities are NOT from the
        # caster's deck — they vanish on death (no grave entry).
        token = MinionInstance(
            instance_id=state.next_minion_id,
            card_numeric_id=token_numeric_id,
            owner=active_side,
            position=target_pos,
            current_health=token_def.health,
            from_deck=False,
        )
        new_board = state.board.place(target_pos[0], target_pos[1], token.instance_id)
        new_minions = state.minions + (token,)
        state = replace(
            state,
            board=new_board,
            minions=new_minions,
            next_minion_id=state.next_minion_id + 1,
        )
        # 2026-07-08 timing audit (F4): ability-token summons previously
        # rendered silently on the final snapshot — emit the board event.
        if event_collector is not None:
            event_collector.collect(
                EVT_MINION_SUMMONED,
                "action:activate_ability",
                {
                    "instance_id": token.instance_id,
                    "card_numeric_id": token_numeric_id,
                    "owner_idx": active_idx,
                    "position": list(target_pos),
                    "source": "ability",
                },
            )
    elif ability.effect_type == "conjure_rat_and_buff":
        state = _apply_conjure_rat_and_buff(
            state, active_idx, active_side, minion, ability, library,
            event_collector=event_collector,
        )
    elif ability.effect_type == "dark_matter_buff":
        # Dispatch through standard effect resolver with scale_with
        from grid_tactics.cards import EffectDefinition
        from grid_tactics.enums import TriggerType as _TT, TargetType as _TGT
        from grid_tactics.effect_resolver import resolve_effect
        buff_effect = EffectDefinition(
            effect_type=EffectType.BUFF_ATTACK,
            trigger=_TT.ON_PLAY,
            target=_TGT.SINGLE_TARGET,
            amount=0,
            scale_with="dark_matter",
        )
        state = resolve_effect(
            state, buff_effect, minion.position, active_side, library,
            target_pos=target_pos,
            contract_source="action:activate_ability",
            event_collector=event_collector,
        )
    else:
        raise ValueError(f"Unsupported activated_ability effect_type '{ability.effect_type}'")

    return state


def _is_rat_card(card_def) -> bool:
    """Match anything the user calls a "rat": card_id 'rat' OR tribe contains 'Rat'.

    Tribe match is case-insensitive and handles composite tribes like
    'Mage/Rat' so Ratchanter itself is NOT buffed (it matches via tribe
    but we explicitly exclude the caster in the buff loop). Common Rat,
    Giant Rat, Rathopper, Emberplague Rat, Furryroach all count.
    """
    if card_def.card_id == "rat":
        return True
    if not card_def.tribe:
        return False
    parts = [p.strip().lower() for p in card_def.tribe.split()]
    return "rat" in parts


def _apply_conjure_rat_and_buff(
    state: GameState,
    active_idx: int,
    active_side: PlayerSide,
    caster: MinionInstance,
    ability,
    library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Rework v2: flat stacking buff + optional tutor-from-deck.

    Step 1 (buff, unconditional): for every living friendly minion
    matching _is_rat_card EXCEPT the caster itself, add
    ``1 + owning player's Dark Matter pool`` to ``attack_bonus``,
    ``max_health_bonus`` AND ``current_health`` so the extra HP is
    usable right away (Dark Matter pool redesign 2026-07 — the old
    caster-own-stacks scaling is gone; minions never hold DM).

    Step 2 (conjure, conditional): scan the caster's deck for card_id
    ``rat``. If >=1 matches, enter pending_tutor state with those deck
    indices so the caller resolves via TUTOR_SELECT / DECLINE_TUTOR.
    Zero matches -> no pending state, no prompt.
    """
    magnitude = 1 + state.players[active_idx].dark_matter

    # ---- Step 1: buff friendly rats on board --------------------------
    new_minions_list = list(state.minions)
    for i, m in enumerate(new_minions_list):
        if m.instance_id == caster.instance_id:
            continue
        if m.owner != active_side:
            continue
        if m.current_health <= 0:
            continue
        cd = library.get_by_id(m.card_numeric_id)
        if not _is_rat_card(cd):
            continue
        new_minions_list[i] = replace(
            m,
            attack_bonus=m.attack_bonus + magnitude,
            max_health_bonus=m.max_health_bonus + magnitude,
            current_health=m.current_health + magnitude,
        )
        # 2026-07-08 timing audit (F4): per-rat buff previously rendered
        # silently — emit the HP delta so badges tick at the causal beat.
        if event_collector is not None:
            event_collector.collect(
                EVT_MINION_HP_CHANGE,
                "action:activate_ability",
                {
                    "instance_id": m.instance_id,
                    "new_hp": m.current_health + magnitude,
                    "delta": magnitude,
                    "owner_idx": active_idx,
                    "position": list(m.position),
                    "cause": "buff",
                },
            )
    state = replace(state, minions=tuple(new_minions_list))

    # ---- Step 2: pending_tutor for common rat from deck ---------------
    summon_card_id = ability.summon_card_id or "rat"
    try:
        rat_numeric_id = library.get_numeric_id(summon_card_id)
    except KeyError:
        return state

    caster_player = state.players[active_idx]
    matches = tuple(
        i for i, cid in enumerate(caster_player.deck) if cid == rat_numeric_id
    )
    if not matches:
        return state

    # Mutex defense -- no other pending state should be active.
    assert state.pending_tutor_player_idx is None
    assert state.pending_post_move_attacker_id is None

    # 2026-07-08 timing audit (F4): Ratchanter's conjure pick sets
    # pending_tutor DIRECTLY (bypassing _enter_pending_tutor, whose
    # filter-based match computation doesn't fit the summon_card_id
    # match) — emit EVT_PENDING_MODAL_OPENED here so the client's
    # eventQueue gates on the modal like every other tutor.
    if event_collector is not None:
        event_collector.collect(
            EVT_PENDING_MODAL_OPENED,
            "action:activate_ability",
            {
                "modal_kind": "tutor_select",
                "owner_idx": active_idx,
                "options_count": len(matches),
                "remaining": 1,
            },
            requires_decision=True,
        )

    return replace(
        state,
        pending_tutor_player_idx=active_idx,
        pending_tutor_matches=matches,
        pending_tutor_is_conjure=True,
    )


def _apply_attack(
    state: GameState, action: Action, library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Apply ATTACK action. Simultaneous damage exchange (D-01).

    Validates:
      - Attacker belongs to active player
      - Defender belongs to opponent
      - Attack range is valid per D-03

    After damage: triggers ON_ATTACK for attacker, ON_DAMAGED for both (if damaged).
    Dead minion cleanup happens in resolve_action after this returns.
    """
    assert_phase_contract(state, "action:attack")
    active_side = _get_active_side(state)

    # Find attacker and defender
    attacker = state.get_minion(action.minion_id)
    if attacker is None:
        raise ValueError(f"Attacker minion {action.minion_id} not found")
    if attacker.owner != active_side:
        raise ValueError(
            f"Cannot attack with opponent's minion (belongs to {attacker.owner.name})"
        )

    defender = state.get_minion(action.target_id)
    if defender is None:
        raise ValueError(f"Defender minion {action.target_id} not found")
    if defender.owner == active_side:
        raise ValueError("Cannot attack your own minion")

    # Validate range
    attacker_card = library.get_by_id(attacker.card_numeric_id)
    if not _can_attack(attacker, defender, attacker_card):
        raise ValueError(
            f"Target is out of attack range "
            f"(attacker at {attacker.position}, defender at {defender.position}, "
            f"range={attacker_card.attack_range})"
        )

    # Calculate effective attack values
    defender_card = library.get_by_id(defender.card_numeric_id)
    attacker_effective = attacker_card.attack + attacker.attack_bonus
    defender_effective = defender_card.attack + defender.attack_bonus

    # Range combat: shorter range at current distance = first strike
    dist = Board.manhattan_distance(attacker.position, defender.position)
    atk_range = attacker_card.attack_range or 0
    def_range = defender_card.attack_range or 0

    # Can defender retaliate at this distance?
    def_can_reach = (def_range == 0 and dist <= 1) or (def_range > 0 and dist <= def_range)

    # First strike: attacker has strictly shorter range = faster/closer unit
    attacker_strikes_first = atk_range < def_range and def_can_reach

    if not def_can_reach:
        # Defender can't reach: attacker hits, no retaliation
        new_defender = replace(defender, current_health=defender.current_health - attacker_effective)
        new_minions = _replace_minion(state.minions, attacker.instance_id, attacker)
        new_minions = _replace_minion(new_minions, defender.instance_id, new_defender)
    elif attacker_strikes_first:
        # Attacker hits first, defender retaliates if alive
        new_defender = replace(defender, current_health=defender.current_health - attacker_effective)
        if new_defender.current_health > 0:
            new_attacker = replace(attacker, current_health=attacker.current_health - defender_effective)
        else:
            new_attacker = attacker  # defender died, no retaliation
        new_minions = _replace_minion(state.minions, attacker.instance_id, new_attacker)
        new_minions = _replace_minion(new_minions, new_defender.instance_id, new_defender)
    else:
        # Simultaneous damage
        new_attacker = replace(attacker, current_health=attacker.current_health - defender_effective)
        new_defender = replace(defender, current_health=defender.current_health - attacker_effective)
        new_minions = _replace_minion(state.minions, attacker.instance_id, new_attacker)
        new_minions = _replace_minion(new_minions, defender.instance_id, new_defender)

    state = replace(state, minions=new_minions)

    # Trigger ON_ATTACK effects for attacker
    # Need to refresh attacker reference from state.
    # Pass defender.position as target_pos so SINGLE_TARGET on_attack effects
    # (e.g. Pyre Archer's burn) land on the attacked minion.
    updated_attacker = state.get_minion(attacker.instance_id)
    if updated_attacker is not None:
        state = resolve_effects_for_trigger(
            state, TriggerType.ON_ATTACK, updated_attacker, library,
            target_pos=defender.position,
            contract_source="trigger:on_attack",
            event_collector=event_collector,
        )

    # Trigger ON_DAMAGED for both if they took damage
    if defender_effective > 0:
        updated_attacker = state.get_minion(attacker.instance_id)
        if updated_attacker is not None:
            state = resolve_effects_for_trigger(
                state, TriggerType.ON_DAMAGED, updated_attacker, library,
                contract_source="trigger:on_damaged",
                event_collector=event_collector,
            )
    if attacker_effective > 0:
        updated_defender = state.get_minion(defender.instance_id)
        if updated_defender is not None:
            state = resolve_effects_for_trigger(
                state, TriggerType.ON_DAMAGED, updated_defender, library,
                contract_source="trigger:on_damaged",
                event_collector=event_collector,
            )

    return state


def _apply_attack_with_event(
    state: GameState,
    action: Action,
    library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Run ``_apply_attack`` and emit EVT_ATTACK_RESOLVED.

    2026-07-08 timing audit (F4): shared by the main ATTACK dispatch and
    the post-move-attack gate — the latter previously emitted NOTHING, so
    post-move melee attacks were invisible to the client eventQueue.
    """
    _atk_id = action.minion_id
    _def_id: Optional[int] = None
    _atk_hp_before = 0
    _def_hp_before = 0
    if _atk_id is not None:
        _src_atk = state.get_minion(_atk_id)
        if _src_atk is not None:
            _atk_hp_before = _src_atk.current_health
    # Defender: prefer the explicit target_id (what _apply_attack uses),
    # fall back to a position scan for callers that only set target_pos.
    if action.target_id is not None:
        _src_def = state.get_minion(action.target_id)
        if _src_def is not None:
            _def_id = _src_def.instance_id
            _def_hp_before = _src_def.current_health
    elif action.target_pos is not None:
        for _m in state.minions:
            if _m.position == action.target_pos and _m.is_alive:
                _def_id = _m.instance_id
                _def_hp_before = _m.current_health
                break
    _def_pos = None
    if action.target_pos is not None:
        _def_pos = list(action.target_pos)
    elif _def_id is not None:
        _d = state.get_minion(_def_id)
        if _d is not None:
            _def_pos = list(_d.position)

    state = _apply_attack(
        state, action, library, event_collector=event_collector,
    )

    if event_collector is not None:
        _atk_after = state.get_minion(_atk_id) if _atk_id is not None else None
        _def_after = state.get_minion(_def_id) if _def_id is not None else None
        event_collector.collect(
            EVT_ATTACK_RESOLVED,
            "action:attack",
            {
                "attacker_id": _atk_id,
                "defender_id": _def_id,
                "target_pos": _def_pos,
                "attacker_hp_before": _atk_hp_before,
                "attacker_hp_after": _atk_after.current_health if _atk_after else 0,
                "defender_hp_before": _def_hp_before,
                "defender_hp_after": _def_after.current_health if _def_after else 0,
                "attacker_killed": _atk_after is None or not _atk_after.is_alive,
                "defender_killed": _def_after is None or not _def_after.is_alive,
            },
        )
    return state


# ---------------------------------------------------------------------------
# Dead minion cleanup (D-02)
# ---------------------------------------------------------------------------


_CHAIN_DEATH_SAFETY_LIMIT = 16

# Phase 14.7-05b: reentrancy guard for _cleanup_dead_minions. When set,
# the cleanup enqueues on_death PendingTriggers but SKIPS calling
# drain_pending_trigger_queue. Used by
# _resolve_trigger_and_open_react_window's in-resolution cleanup path so
# chain-reaction deaths don't spin up a nested drain / picker modal
# that conflicts with the outer resolver's queue pop. See the
# _resolve_trigger_and_open_react_window docstring for the rationale.
_cleanup_skip_drain: bool = False


# Phase 14.8-05: the legacy death-cleanup path
# (_enqueue_dead_minions_and_cleanup_zones + _drain_pending_death_queue) was
# DELETED. It was superseded by _cleanup_dead_minions in 14.7-05b which
# routes on_death effects through the PendingTrigger priority queue. The
# GameState.pending_death_queue field and PendingDeathWork dataclass were
# also deleted at the same time — nothing consumes them anymore.


def _cleanup_dead_minions(
    state: GameState,
    library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Remove dead minions (health <= 0) and enqueue on_death effects into
    the turn-player-first priority queue (Phase 14.7-05b).

    Flow (post 14.7-05b):
      1. Collect all currently-dead minions (current_health <= 0).
      2. For each dead minion, for each ON_DEATH effect on its card_def,
         build a ``PendingTrigger(trigger_kind="on_death", ...)``. Split
         by owner: turn player's deaths → ``pending_trigger_queue_turn``,
         other player's → ``pending_trigger_queue_other``. Spec §7.2:
         the turn player's death-triggers resolve BEFORE the other
         player's, mirroring start/end-of-turn priority.
      3. Remove the dead minions from the board + minions tuple, and
         add their ``card_numeric_id`` to the owner's grave (Phase 14.5:
         tokens with ``from_deck=False`` vanish silently).
      4. If no trigger is currently being resolved (neither queue has an
         entry at the front claimed by an outer resolver), call
         ``drain_pending_trigger_queue`` to advance. When called from
         INSIDE ``_resolve_trigger_and_open_react_window``'s
         resolve_effect → cleanup chain, the drain is SKIPPED so the
         outer resolver can pop its own entry first; the outer
         drain-recheck hook in resolve_react_stack then picks up the
         newly-enqueued entries at the next window close.

    Chain reactions: newly-dead minions from an on_death effect's
    resolution append to the queues in-place. The drain-recheck hook
    in resolve_react_stack re-enters drain after each AFTER_DEATH_EFFECT
    react window closes, so chain entries fire in turn-player-first
    order just like initial simultaneous deaths.

    Idempotent: if ``pending_death_target`` is still set from a previous
    call, this function is a no-op — we wait for DEATH_TARGET_PICK.
    Same for ``pending_trigger_picker_idx``.
    """
    assert_phase_contract(state, "system:cleanup_dead_minions")
    # If a single-target modal is still pending, don't touch the queues —
    # wait for the caller to submit DEATH_TARGET_PICK.
    if state.pending_death_target is not None:
        return state

    # If the trigger-picker modal is already open (from a prior drain in
    # progress), don't touch the queues — wait for TRIGGER_PICK /
    # DECLINE_TRIGGER from the picker's owner.
    if state.pending_trigger_picker_idx is not None:
        return state

    from grid_tactics.game_state import PendingTrigger
    from grid_tactics.react_stack import drain_pending_trigger_queue

    dead_minions = [m for m in state.minions if not m.is_alive]
    if not dead_minions:
        return state

    active_side = state.players[state.active_player_idx].side

    # 1-2. Build PendingTrigger entries for each dead minion's on_death
    # effects, split by owner.
    turn_triggers: list[PendingTrigger] = []
    other_triggers: list[PendingTrigger] = []

    # Sort dead minions for deterministic enqueue order within each side
    # (instance_id ascending = play order). This mirrors the stable
    # per-owner ordering the start/end-of-turn enqueuer uses.
    ordered = sorted(dead_minions, key=lambda m: m.instance_id)

    for m in ordered:
        try:
            card_def = library.get_by_id(m.card_numeric_id)
        except KeyError:
            continue
        owner_idx = 0 if m.owner == PlayerSide.PLAYER_1 else 1
        for eff_idx, effect in enumerate(card_def.effects):
            if effect.trigger != TriggerType.ON_DEATH:
                continue
            pt = PendingTrigger(
                trigger_kind="on_death",
                # Source minion will be dead at resolution time — the
                # captured_position + source_card_numeric_id carry the
                # context the drain helper needs. 14.7-06 will turn
                # source_minion_id lookups into fizzle checks.
                source_minion_id=m.instance_id,
                source_card_numeric_id=m.card_numeric_id,
                effect_idx=eff_idx,
                owner_idx=owner_idx,
                captured_position=m.position,
                target_pos=None,
            )
            if m.owner == active_side:
                turn_triggers.append(pt)
            else:
                other_triggers.append(pt)

    # 3. Remove dead minions from board, minions tuple, and add cards to
    # graves. Tokens (from_deck=False) vanish silently per 14.5.
    new_board = state.board
    for m in dead_minions:
        new_board = new_board.remove(m.position[0], m.position[1])

    dead_ids = {m.instance_id for m in dead_minions}
    alive_minions = tuple(m for m in state.minions if m.instance_id not in dead_ids)

    new_players = state.players
    for m in dead_minions:
        if not m.from_deck:
            continue
        player_idx = int(m.owner)
        player = new_players[player_idx]
        new_player = replace(player, grave=player.grave + (m.card_numeric_id,))
        new_players = _replace_player(new_players, player_idx, new_player)

    state = replace(
        state,
        board=new_board,
        minions=alive_minions,
        players=new_players,
    )

    # Phase 14.8-03a: emit one EVT_MINION_DIED per dead minion, in
    # instance_id order so replay matches enqueue order.
    if event_collector is not None:
        for m in ordered:
            event_collector.collect(
                EVT_MINION_DIED,
                "system:cleanup_dead_minions",
                {
                    "instance_id": m.instance_id,
                    "card_numeric_id": m.card_numeric_id,
                    "owner_idx": 0 if m.owner == PlayerSide.PLAYER_1 else 1,
                    "position": list(m.position),
                    "from_deck": m.from_deck,
                },
            )

    # 4. Merge new triggers into existing queues (append preserves any
    # in-flight start/end entries that were already queued).
    if not turn_triggers and not other_triggers:
        return state

    state = replace(
        state,
        pending_trigger_queue_turn=state.pending_trigger_queue_turn + tuple(turn_triggers),
        pending_trigger_queue_other=state.pending_trigger_queue_other + tuple(other_triggers),
    )

    # Skip the drain if another resolution is in progress (chain-reaction
    # path from inside _resolve_trigger_and_open_react_window). The outer
    # resolver pops its entry + the drain-recheck hook picks up the new
    # entries.
    if _cleanup_skip_drain:
        return state

    return drain_pending_trigger_queue(
        state, library, event_collector=event_collector,
    )


# ---------------------------------------------------------------------------
# Win/draw detection (Phase 4)
# ---------------------------------------------------------------------------


def _check_game_over(
    state: GameState,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Check if the game is over (any player dead) and set winner/is_game_over.

    Called after dead minion cleanup and after react stack resolution.
    - Both dead: draw (is_game_over=True, winner=None)
    - P1 dead: P2 wins
    - P2 dead: P1 wins
    - Neither dead: no change
    """
    assert_phase_contract(state, "system:check_game_over")
    p1_alive = state.players[0].is_alive
    p2_alive = state.players[1].is_alive

    if p1_alive and p2_alive:
        return state

    if not p1_alive and not p2_alive:
        # Draw: both dead simultaneously
        new_state = replace(state, is_game_over=True, winner=None)
        winner = None
        reason = "both_players_dead"
    elif not p1_alive:
        new_state = replace(state, is_game_over=True, winner=PlayerSide.PLAYER_2)
        winner = 1
        reason = "p1_hp_zero"
    else:
        new_state = replace(state, is_game_over=True, winner=PlayerSide.PLAYER_1)
        winner = 0
        reason = "p2_hp_zero"

    # Phase 14.8-03a: emit EVT_GAME_OVER. Client-side modal handles
    # its own timing (animation_duration_ms=0 by default).
    if event_collector is not None:
        event_collector.collect(
            EVT_GAME_OVER,
            "system:check_game_over",
            {"winner": winner, "reason": reason},
        )
    return new_state


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_action(
    state: GameState,
    action: Action,
    library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Validate and apply a single action, returning a new GameState.

    This is the single entry point for ALL actions. Dispatches based on phase:
      - ACTION phase: main-phase handlers (play card, move, attack, draw, pass)
      - REACT phase: delegates to handle_react_action from react_stack.py

    Flow (ACTION phase):
      1. Dispatch to action handler
      2. Clean up dead minions (D-02)
      3. Transition to REACT phase (D-13)

    Flow (REACT phase):
      Delegates entirely to handle_react_action (PLAY_REACT or PASS).

    Args:
        state: Current game state.
        action: The action to apply.
        library: CardLibrary for card definition lookups.

    Returns:
        New GameState after action processing.

    Raises:
        ValueError: If the action is invalid (wrong phase, illegal action, etc.).
    """
    # Phase 14.8-05: the Phase 14.7-09 last_trigger_blip field DELETION was
    # completed here — the per-frame clear-at-top-of-resolve_action logic
    # is gone because the field itself is gone. Trigger blips now flow
    # through EVT_TRIGGER_BLIP in the event stream (plan 14.8-03a), which
    # the client's eventQueue plays through a dedicated slot handler
    # (playTriggerBlip in game.js).

    # Pending death-target gate (phase-agnostic): while a death-triggered
    # modal is open, the ONLY legal action is DEATH_TARGET_PICK from the
    # dying minion's owner. This gate must run BEFORE the REACT-phase
    # dispatch so that deaths produced during react-stack resolution can
    # be handled without routing through handle_react_action.
    if state.pending_death_target is not None:
        if action.action_type != ActionType.DEATH_TARGET_PICK:
            raise ValueError(
                "Pending death target: only DEATH_TARGET_PICK is legal"
            )
        if action.target_pos is None:
            raise ValueError("DEATH_TARGET_PICK requires a target_pos")
        from grid_tactics.effect_resolver import apply_death_target_pick
        state = apply_death_target_pick(state, action.target_pos, library)
        # Phase 14.8-03a: emit pending-modal resolved event for the
        # death-target modal that was open before this action.
        if event_collector is not None:
            event_collector.collect(
                EVT_PENDING_MODAL_RESOLVED,
                "action:death_target_pick",
                {
                    "modal_kind": "death_target_pick",
                    "picked_position": list(action.target_pos),
                },
            )
        # Phase 14.7-05b: chain-reaction deaths (the DESTROY may have
        # killed another minion with its own on_death effect) enqueue
        # via _cleanup_dead_minions into the priority queue.
        state = _cleanup_dead_minions(state, library, event_collector=event_collector)
        state = _check_game_over(state, event_collector=event_collector)
        if state.is_game_over:
            return state
        # If ANOTHER modal is now pending (chain-reaction DESTROY), defer.
        if state.pending_death_target is not None:
            return state
        # If drain opened a trigger picker modal, defer — the UI now needs
        # the owner to pick a resolution order.
        if state.pending_trigger_picker_idx is not None:
            return state
        # If drain auto-resolved a subsequent trigger and opened its own
        # react window, respect it. Phase 14.8 bugfix: only a LIVE window
        # (react_player_idx set) counts — a drain-recheck that tore down
        # its window before deferring to this modal leaves phase=REACT
        # with react_player_idx=None, which must fall through to the
        # fresh AFTER_DEATH_EFFECT window open below.
        if state.phase == TurnPhase.REACT and state.react_player_idx is not None:
            return state

        # The death-effect we just resolved (via the modal pick) needs
        # its own AFTER_DEATH_EFFECT react window. Open it and let the
        # drain-recheck hook in resolve_react_stack continue the drain
        # after the window closes.
        #
        # react_return_phase preserved if already set (we may be nested
        # inside an outer start/end-of-turn drain). Otherwise default to
        # ACTION for the legacy path (the pending_action captured before
        # cleanup drives the close_end_react_and_advance_turn tail).
        default_return = state.react_return_phase or TurnPhase.ACTION
        return replace(
            state,
            phase=TurnPhase.REACT,
            react_player_idx=1 - state.active_player_idx,
            react_context=ReactContext.AFTER_DEATH_EFFECT,
            react_return_phase=default_return,
            react_stack=(),
        )

    # Pending revive-place gate — runs before REACT delegation so the player
    # can place revived minions even when the state is technically in REACT
    # (the react window is deferred until revive completes).
    # 2026-07 card-audit fix: when the LAST placement (or a decline)
    # clears the pending state, run the shared resume tail so the react
    # window opens and the turn advances (previously the caster kept the
    # ACTION phase and got a free second action).
    if state.pending_revive_player_idx is not None:
        if action.action_type == ActionType.REVIVE_PLACE:
            state = _apply_revive_place(
                state, action, library, event_collector=event_collector,
            )
            if state.pending_revive_player_idx is not None:
                # Mid-chain — more placements to make; keep the modal open.
                return state
            return _resume_after_pending_revive(
                state, action, library, event_collector=event_collector,
            )
        elif action.action_type == ActionType.DECLINE_REVIVE:
            assert_phase_contract(state, "action:decline_revive")
            state = replace(
                state,
                pending_revive_player_idx=None,
                pending_revive_card_id=None,
                pending_revive_remaining=0,
            )
            return _resume_after_pending_revive(
                state, action, library, event_collector=event_collector,
            )
        else:
            raise ValueError(
                "Pending revive: must REVIVE_PLACE or DECLINE_REVIVE"
            )

    # Phase 14.7-05: pending_trigger_picker gate.
    # When drain_pending_trigger_queue has opened the modal card-picker
    # (pending_trigger_picker_idx is set), the ONLY legal actions are
    # TRIGGER_PICK (from the picker owner, with card_index=queue_idx) or
    # DECLINE_TRIGGER (skips the rest of the picker's queue).
    #
    # This gate MUST run before the REACT-phase dispatch: during the
    # modal the phase may still be REACT (a prior trigger's window just
    # closed) or may have been set by drain to an intermediate phase —
    # either way, normal react-handler enumeration isn't valid here.
    # Mirrors the pending_tutor / pending_conjure_deploy pattern.
    if state.pending_trigger_picker_idx is not None:
        if action.action_type == ActionType.TRIGGER_PICK:
            if action.card_index is None:
                raise ValueError(
                    "TRIGGER_PICK requires card_index (queue index)"
                )
            return _apply_trigger_pick(
                state, action.card_index, library,
                event_collector=event_collector,
            )
        if action.action_type == ActionType.DECLINE_TRIGGER:
            return _apply_decline_trigger(
                state, library, event_collector=event_collector,
            )
        raise ValueError(
            "Pending trigger picker: only TRIGGER_PICK or DECLINE_TRIGGER are legal"
        )

    # REACT phase: delegate to react handler
    if state.phase == TurnPhase.REACT:
        from grid_tactics.react_stack import handle_react_action
        return handle_react_action(
            state, action, library, event_collector=event_collector,
        )

    # Validate ACTION phase
    if state.phase != TurnPhase.ACTION:
        raise ValueError(
            f"Cannot resolve action in phase {state.phase.name}, expected ACTION"
        )

    # Not in pending death target: DEATH_TARGET_PICK is illegal
    if action.action_type == ActionType.DEATH_TARGET_PICK:
        raise ValueError(
            "DEATH_TARGET_PICK only legal during pending_death_target state"
        )

    # Phase 14.6: pending-conjure-deploy gate.
    # After TUTOR_SELECT resolves during a conjure flow, the player must pick
    # a deployment tile (CONJURE_DEPLOY) or decline (DECLINE_CONJURE -> to hand).
    if state.pending_conjure_deploy_card is not None:
        assert state.pending_tutor_player_idx is None, (
            "pending_conjure_deploy and pending_tutor cannot coexist"
        )
        deployer_idx = state.pending_conjure_deploy_player_idx
        deployer_side = state.players[deployer_idx].side
        if action.action_type == ActionType.CONJURE_DEPLOY:
            assert_phase_contract(state, "action:conjure_deploy")
            target_pos = action.position
            if target_pos is None:
                raise ValueError("CONJURE_DEPLOY requires a position")
            own_rows = PLAYER_1_ROWS if deployer_side == PlayerSide.PLAYER_1 else PLAYER_2_ROWS
            if target_pos[0] not in own_rows:
                raise ValueError(f"CONJURE_DEPLOY target {target_pos} not on deployer's side")
            if state.board.get(target_pos[0], target_pos[1]) is not None:
                raise ValueError(f"CONJURE_DEPLOY target {target_pos} is occupied")

            card_numeric_id = state.pending_conjure_deploy_card
            card_def = library.get_by_id(card_numeric_id)
            new_minion = MinionInstance(
                instance_id=state.next_minion_id,
                card_numeric_id=card_numeric_id,
                owner=deployer_side,
                position=target_pos,
                current_health=card_def.health,
                from_deck=True,
            )
            new_board = state.board.place(target_pos[0], target_pos[1], new_minion.instance_id)
            new_minions = state.minions + (new_minion,)
            state = replace(
                state,
                board=new_board,
                minions=new_minions,
                next_minion_id=state.next_minion_id + 1,
                pending_conjure_deploy_card=None,
                pending_conjure_deploy_player_idx=None,
            )
            # 2026-07-08 timing audit (F4): conjure-deploy summons
            # previously rendered silently — emit the board event so
            # playMinionSummoned animates the landing.
            if event_collector is not None:
                event_collector.collect(
                    EVT_MINION_SUMMONED,
                    "action:conjure_deploy",
                    {
                        "instance_id": new_minion.instance_id,
                        "card_numeric_id": card_numeric_id,
                        "owner_idx": deployer_idx,
                        "position": list(target_pos),
                        "source": "conjure_deploy",
                    },
                )
        elif action.action_type == ActionType.DECLINE_CONJURE:
            assert_phase_contract(state, "action:decline_conjure")
            # Decline deployment — card goes to hand instead. Overdraw
            # rule (2026-07): a full hand burns it to the exhaust pile.
            card_numeric_id = state.pending_conjure_deploy_card
            deployer = state.players[deployer_idx]
            new_deployer, _burned = deployer.add_to_hand_with_overdraw(
                card_numeric_id,
            )
            # 2026-07-08 timing audit (F2): non-burn branch previously
            # emitted nothing — the declined card appeared in hand only
            # at drain end. Emit EVT_CARD_DRAWN so the hand add renders
            # at its causal beat (view_filter redacts identity for the
            # opponent; burns are public).
            if event_collector is not None:
                event_collector.collect(
                    EVT_CARD_BURNED if _burned else EVT_CARD_DRAWN,
                    "action:decline_conjure",
                    {
                        "player_idx": deployer_idx,
                        "card_numeric_id": card_numeric_id,
                        "source": "decline_conjure",
                    },
                )
            new_players = _replace_player(state.players, deployer_idx, new_deployer)
            state = replace(
                state,
                players=new_players,
                pending_conjure_deploy_card=None,
                pending_conjure_deploy_player_idx=None,
            )
        else:
            raise ValueError(
                "Pending conjure deploy: must CONJURE_DEPLOY or DECLINE_CONJURE"
            )

        # React window fires after conjure deployment resolves.
        # Record pending_action before cleanup so a death modal can defer.
        # 2026-07-08 timing audit (F4): thread event_collector so deaths /
        # game-over on this resume path reach the client.
        state = replace(state, pending_action=action)
        state = _cleanup_dead_minions(state, library, event_collector=event_collector)
        state = _check_game_over(state, event_collector=event_collector)
        if state.is_game_over:
            return state
        if state.pending_death_target is not None:
            return state
        # Phase 14.7-05b: cleanup may have enqueued on_death triggers; if
        # drain opened a picker modal or a new react window, respect it.
        if state.pending_trigger_picker_idx is not None:
            return state
        if state.phase == TurnPhase.REACT:
            _emit_after_action_react_window_opened(state, event_collector)
            return state
        state = replace(
            state,
            phase=TurnPhase.REACT,
            react_player_idx=1 - state.active_player_idx,
            # Phase 14.7-02: after-action react window (conjure deploy).
            react_context=ReactContext.AFTER_ACTION,
            react_return_phase=TurnPhase.ACTION,
        )
        _emit_after_action_react_window_opened(state, event_collector)
        return state

    # Not in pending conjure deploy: CONJURE_DEPLOY / DECLINE_CONJURE are illegal
    if action.action_type in (ActionType.CONJURE_DEPLOY, ActionType.DECLINE_CONJURE):
        raise ValueError(
            f"{action.action_type.name} only legal during pending_conjure_deploy state"
        )

    # Phase 14.2: pending-tutor gate.
    # If a card with TUTOR on_play just played and matches exist in deck, the
    # caster MUST TUTOR_SELECT (with index into pending_tutor_matches) or
    # DECLINE_TUTOR. Anything else is illegal. The single react window for
    # the original play fires AFTER the pending clears.
    if state.pending_tutor_player_idx is not None:
        # Mutex defense
        assert state.pending_post_move_attacker_id is None, (
            "pending_tutor and pending_post_move_attacker cannot coexist"
        )
        is_conjure = state.pending_tutor_is_conjure
        # 2026-07 card-audit fix (Red Diodebot): capture WHERE the tutor
        # was opened from BEFORE the pending state clears. A tutor fired
        # by an on_summon effect (Window B) must NOT open a third
        # AFTER_ACTION react window on resume — it routes straight to
        # the Decay phase, matching the no-match summon path.
        _tutor_origin = state.pending_tutor_origin
        if action.action_type == ActionType.TUTOR_SELECT:
            assert_phase_contract(state, "action:tutor_select")
            match_idx = action.card_index  # reuse card_index payload
            if match_idx is None or match_idx < 0 or match_idx >= len(state.pending_tutor_matches):
                raise ValueError(
                    f"TUTOR_SELECT: invalid match index {match_idx}; "
                    f"have {len(state.pending_tutor_matches)} matches"
                )
            deck_idx = state.pending_tutor_matches[match_idx]
            caster_idx = state.pending_tutor_player_idx
            caster = state.players[caster_idx]
            if deck_idx < 0 or deck_idx >= len(caster.deck):
                raise ValueError(
                    f"TUTOR_SELECT: stale deck index {deck_idx} (deck size {len(caster.deck)})"
                )
            chosen_card = caster.deck[deck_idx]
            new_deck = caster.deck[:deck_idx] + caster.deck[deck_idx + 1:]

            if is_conjure:
                # Phase 14.6: conjure-to-field — remove from deck, enter
                # pending_conjure_deploy so player picks a tile next.
                new_caster = replace(caster, deck=new_deck)
                new_players = _replace_player(state.players, caster_idx, new_caster)
                state = replace(
                    state,
                    players=new_players,
                    pending_tutor_player_idx=None,
                    pending_tutor_matches=(),
                    pending_tutor_is_conjure=False,
                    pending_tutor_origin=None,
                    pending_conjure_deploy_card=chosen_card,
                    pending_conjure_deploy_player_idx=caster_idx,
                )
            else:
                # Standard tutor: add to hand. Turn-structure redesign
                # 2026-07: overdraw-burns — a full hand (MAX_HAND_SIZE)
                # sends the tutored card to the exhaust pile (revealed)
                # instead of fizzling, for consistency with all other
                # draw paths.
                # Multi-pick support (e.g. To The Ratmobile amount=2):
                # decrement pending_tutor_remaining; if still >0 re-enter
                # pending state with the remaining matches (indices shifted
                # for the removed deck slot) so the player picks again.
                new_caster = replace(caster, deck=new_deck)
                new_caster, _burned = new_caster.add_to_hand_with_overdraw(
                    chosen_card,
                )
                # 2026-07-08 timing audit (F2): non-burn branch previously
                # emitted nothing — the tutored card appeared in hand only
                # at drain end. Emit EVT_CARD_DRAWN so the hand add renders
                # at its causal beat (view_filter redacts identity for the
                # opponent; burns are public).
                if event_collector is not None:
                    event_collector.collect(
                        EVT_CARD_BURNED if _burned else EVT_CARD_DRAWN,
                        "action:tutor_select",
                        {
                            "player_idx": caster_idx,
                            "card_numeric_id": chosen_card,
                            "source": "tutor",
                        },
                    )
                new_players = _replace_player(state.players, caster_idx, new_caster)
                remaining = max(0, state.pending_tutor_remaining - 1)
                if remaining <= 0:
                    state = replace(
                        state,
                        players=new_players,
                        pending_tutor_player_idx=None,
                        pending_tutor_matches=(),
                        pending_tutor_is_conjure=False,
                        pending_tutor_remaining=0,
                        pending_tutor_origin=None,
                    )
                else:
                    # Recompute matches against the NEW deck using the same
                    # tutor filter as the original card. Look the card up
                    # via the currently-resolving action's context — we keep
                    # pending_tutor_is_conjure unchanged since the filter is
                    # the same card.
                    from grid_tactics.effect_resolver import _recompute_tutor_matches
                    new_matches = _recompute_tutor_matches(
                        new_caster.deck,
                        state.pending_tutor_matches,
                        deck_idx,
                        library,
                    )
                    if not new_matches:
                        # No further matches — close the modal early.
                        state = replace(
                            state,
                            players=new_players,
                            pending_tutor_player_idx=None,
                            pending_tutor_matches=(),
                            pending_tutor_is_conjure=False,
                            pending_tutor_remaining=0,
                            pending_tutor_origin=None,
                        )
                    else:
                        remaining = min(remaining, len(new_matches))
                        state = replace(
                            state,
                            players=new_players,
                            pending_tutor_matches=tuple(new_matches),
                            pending_tutor_remaining=remaining,
                        )
                        # Stay in pending_tutor — return without advancing
                        # to react window; caller will re-enter on next
                        # TUTOR_SELECT / DECLINE_TUTOR.
                        return state
        elif action.action_type == ActionType.DECLINE_TUTOR:
            assert_phase_contract(state, "action:decline_tutor")
            # Mandatory tutoring (user-decided 2026-07-03): declining is
            # only legal when ZERO matches remain. A full hand does NOT
            # exempt the pick — the tutored card overdraw-burns to the
            # Exhaust Pile revealed. Mirrors _pending_tutor_actions in
            # legal_actions.py; this raise is the runtime backstop.
            # Conjure deck-picks (pending_tutor_is_conjure — Ratchanter)
            # are exempt: their decline semantics are unchanged by design.
            if state.pending_tutor_matches and not state.pending_tutor_is_conjure:
                raise ValueError(
                    "DECLINE_TUTOR illegal: mandatory tutoring — "
                    f"{len(state.pending_tutor_matches)} matching pick(s) "
                    "remain; must TUTOR_SELECT"
                )
            state = replace(
                state,
                pending_tutor_player_idx=None,
                pending_tutor_matches=(),
                pending_tutor_is_conjure=False,
                pending_tutor_remaining=0,
                pending_tutor_origin=None,
            )
        else:
            raise ValueError(
                "Pending tutor: must TUTOR_SELECT or DECLINE_TUTOR"
            )

        # 2026-07 card-audit fix: pair the EVT_PENDING_MODAL_OPENED that
        # _enter_pending_tutor emitted with a RESOLVED event once the
        # pending state clears, so the client's eventQueue gate releases.
        # (Mirrors the death_target_pick pattern above.) Mid-chain multi-
        # picks return early before this point and keep the modal open.
        if state.pending_tutor_player_idx is None and event_collector is not None:
            event_collector.collect(
                EVT_PENDING_MODAL_RESOLVED,
                (
                    "action:decline_tutor"
                    if action.action_type == ActionType.DECLINE_TUTOR
                    else "action:tutor_select"
                ),
                {"modal_kind": "tutor_select"},
            )

        # If we just entered pending_conjure_deploy, defer the react window.
        if state.pending_conjure_deploy_card is not None:
            return state

        # Single react window for the original on_play fires now.
        # 2026-07-08 timing audit (F4): thread event_collector so deaths /
        # game-over on this resume path reach the client.
        state = replace(state, pending_action=action)
        state = _cleanup_dead_minions(state, library, event_collector=event_collector)
        state = _check_game_over(state, event_collector=event_collector)
        if state.is_game_over:
            return state
        if state.pending_death_target is not None:
            return state
        # Phase 14.7-05b: cleanup may have enqueued on_death triggers; if
        # drain opened a picker modal or a new react window, respect it.
        if state.pending_trigger_picker_idx is not None:
            return state
        if state.phase == TurnPhase.REACT:
            _emit_after_action_react_window_opened(state, event_collector)
            return state
        # 2026-07 card-audit fix (Red Diodebot): a tutor opened by an
        # on_summon effect already had its react window (Window B —
        # AFTER_SUMMON_EFFECT). Opening another AFTER_ACTION window here
        # gave the opponent a THIRD react window that the no-match path
        # never opens. Route straight to the Decay phase instead,
        # matching the summon flow when the tutor finds no match.
        if _tutor_origin == "summon_effect":
            from grid_tactics.react_stack import enter_end_of_turn
            state = replace(
                state,
                react_stack=(),
                react_player_idx=None,
                pending_action=None,
                react_context=None,
                react_return_phase=None,
            )
            return enter_end_of_turn(
                state, library, event_collector=event_collector,
            )
        state = replace(
            state,
            phase=TurnPhase.REACT,
            react_player_idx=1 - state.active_player_idx,
            # Phase 14.7-02: after-action react window (tutor resolve).
            # Phase 14.8 bugfix: preserve an in-flight react_return_phase
            # (e.g. END_OF_TURN when the tutor was react-played on the
            # BEFORE_END_OF_TURN window — Tree Wyrm) so the window close
            # returns to the right phase instead of re-entering
            # END_OF_TURN and double-firing end-of-turn triggers.
            react_context=ReactContext.AFTER_ACTION,
            react_return_phase=state.react_return_phase or TurnPhase.ACTION,
        )
        _emit_after_action_react_window_opened(state, event_collector)
        return state

    # Not in pending tutor: TUTOR_SELECT / DECLINE_TUTOR are illegal
    if action.action_type in (ActionType.TUTOR_SELECT, ActionType.DECLINE_TUTOR):
        raise ValueError(
            f"{action.action_type.name} only legal during pending_tutor state"
        )

    # Pending revive-place gate (defense in depth — the phase-agnostic
    # gate earlier in this function normally catches these first).
    # Player picks a deploy cell for each revived minion, or declines.
    if state.pending_revive_player_idx is not None:
        if action.action_type == ActionType.REVIVE_PLACE:
            state = _apply_revive_place(
                state, action, library, event_collector=event_collector,
            )
            if state.pending_revive_player_idx is not None:
                return state
            return _resume_after_pending_revive(
                state, action, library, event_collector=event_collector,
            )
        elif action.action_type == ActionType.DECLINE_REVIVE:
            assert_phase_contract(state, "action:decline_revive")
            state = replace(
                state,
                pending_revive_player_idx=None,
                pending_revive_card_id=None,
                pending_revive_remaining=0,
            )
            return _resume_after_pending_revive(
                state, action, library, event_collector=event_collector,
            )
        else:
            raise ValueError(
                "Pending revive: must REVIVE_PLACE or DECLINE_REVIVE"
            )

    # Not in pending revive: REVIVE_PLACE / DECLINE_REVIVE are illegal
    if action.action_type in (ActionType.REVIVE_PLACE, ActionType.DECLINE_REVIVE):
        raise ValueError(
            f"{action.action_type.name} only legal during pending_revive state"
        )

    # Phase 14.1: pending-post-move-attack gate.
    # If a melee minion just moved and has in-range targets, the player MUST
    # either ATTACK with that minion or DECLINE_POST_MOVE_ATTACK. Anything
    # else is illegal. The combined move+attack/decline counts as ONE
    # logical action, so the react window only fires after this resolves.
    if state.pending_post_move_attacker_id is not None:
        pending_id = state.pending_post_move_attacker_id
        is_decline = action.action_type == ActionType.DECLINE_POST_MOVE_ATTACK
        if action.action_type == ActionType.ATTACK:
            if action.minion_id != pending_id:
                raise ValueError(
                    "Pending post-move attack: must ATTACK with the moved minion or DECLINE"
                )
            # 2026-07-08 timing audit (F4): route through the shared
            # emit wrapper — this gate previously emitted NO
            # attack_resolved at all, making post-move attacks invisible.
            state = _apply_attack_with_event(
                state, action, library, event_collector=event_collector,
            )
            state = replace(state, pending_post_move_attacker_id=None)
        elif is_decline:
            assert_phase_contract(state, "action:decline_post_move_attack")
            state = replace(state, pending_post_move_attacker_id=None)
        else:
            raise ValueError(
                "Pending post-move attack: must ATTACK with the moved minion or DECLINE"
            )

        # Dead minion cleanup + game-over check.
        # Phase 14.8 bugfix: thread event_collector through so trigger
        # blips / HP changes / deaths on this path reach the client.
        state = replace(state, pending_action=action)
        state = _cleanup_dead_minions(state, library, event_collector=event_collector)
        state = _check_game_over(state, event_collector=event_collector)
        if state.is_game_over:
            return state
        if state.pending_death_target is not None:
            return state
        # Phase 14.7-05b: cleanup may have enqueued on_death triggers; if
        # drain opened a picker modal or a new react window, respect it.
        if state.pending_trigger_picker_idx is not None:
            return state
        if state.phase == TurnPhase.REACT:
            return state

        # Phase 14.7-08: DECLINE means "no second action" → no second react
        # window. The post-move react window already opened (and closed)
        # around the move itself. Advance directly to END_OF_TURN.
        # Phase 14.8 bugfix: pass event_collector — this path previously
        # dropped it, so EVT_PHASE_CHANGED / EVT_REACT_WINDOW_OPENED for
        # the end-of-turn window never reached the client.
        if is_decline:
            from grid_tactics.react_stack import enter_end_of_turn
            return enter_end_of_turn(
                state, library, event_collector=event_collector,
            )

        # ATTACK sub-action resolved — open its own (second) react window.
        # This is the SECOND of the two react windows mandated by spec v2
        # §4.1 (the first fired around the MOVE itself).
        state = replace(
            state,
            phase=TurnPhase.REACT,
            react_player_idx=1 - state.active_player_idx,
            # Phase 14.7-02: after-action react window (melee post-attack).
            react_context=ReactContext.AFTER_ACTION,
            react_return_phase=TurnPhase.ACTION,
        )
        # 2026-07-08 timing audit (F5): this window previously opened
        # WITHOUT an event — the game looked frozen waiting on an
        # invisible react window.
        _emit_after_action_react_window_opened(state, event_collector)
        return state

    # Not in pending state: DECLINE is illegal
    if action.action_type == ActionType.DECLINE_POST_MOVE_ATTACK:
        raise ValueError("DECLINE_POST_MOVE_ATTACK only legal in pending post-move state")

    # Phase 14.8-03a: snapshot pre-action mana / hp / grave so we can
    # emit MANA_CHANGE / PLAYER_HP_CHANGE / CARD_DISCARDED diffs after
    # the handler runs. Cheap (tuple-of-ints + tuple-len).
    _prev_mana = tuple(p.current_mana for p in state.players) if event_collector else None
    _prev_hp = tuple(p.hp for p in state.players) if event_collector else None
    _prev_grave_lens = tuple(len(p.grave) for p in state.players) if event_collector else None
    # 2026-07-08 timing audit (F4 dedup): remember where this action's
    # events start so the post-handler HP diff can skip deltas the
    # handlers already emitted causally (inline effect emissions).
    _events_start = len(event_collector.events) if event_collector else 0

    # Turn-structure redesign 2026-07: any non-PASS main-phase action
    # breaks the consecutive-pass streak (Handshake tracking).
    if action.action_type != ActionType.PASS and state.consecutive_passes != 0:
        state = replace(state, consecutive_passes=0)

    # Dispatch to action handler
    if action.action_type == ActionType.PASS:
        _passer_idx = state.active_player_idx
        state = _apply_pass(state, event_collector=event_collector)
        # 2026-07-08: surface the pass on the wire. streak==1 means an
        # unanswered Handshake offer (client shows the palm-up flag);
        # streak==0 with handshake_pending means this pass COMPLETED the
        # Handshake (EVT_HANDSHAKE follows at payout).
        if event_collector is not None:
            event_collector.collect(
                EVT_PASS_DECLARED,
                "action:pass_action",
                {
                    "player_idx": _passer_idx,
                    "streak": state.consecutive_passes,
                    "handshake_pending": state.handshake_pending,
                },
            )
    elif action.action_type == ActionType.DRAW:
        # Manual-draw variant (user 2026-07-10): _apply_draw emits its own
        # EVT_CARD_DRAWN / EVT_CARD_BURNED with the card identity so the
        # client can animate the deck → hand transition.
        state = _apply_draw(state, event_collector=event_collector)
    elif action.action_type == ActionType.MOVE:
        # 2026-07 card-audit fix (Furryroach): EVT_MINION_MOVED for the
        # acting minion is now emitted INSIDE _apply_move (before the
        # ON_MOVE trigger dispatch) so March-sweep events sequence after
        # the mover's own event instead of before it.
        state = _apply_move(
            state, action, library, event_collector=event_collector,
        )
    elif action.action_type == ActionType.PLAY_CARD:
        # Emit EVT_CARD_PLAYED before dispatching so the event seq comes
        # BEFORE any inner trigger / summon events the handler emits.
        if event_collector is not None:
            _player = state.players[state.active_player_idx]
            _card_idx = action.card_index
            _played_card_id: Optional[int] = None
            if _card_idx is not None and 0 <= _card_idx < len(_player.hand):
                _played_card_id = _player.hand[_card_idx]
            event_collector.collect(
                EVT_CARD_PLAYED,
                "action:play_card",
                {
                    "card_numeric_id": _played_card_id,
                    "card_index": _card_idx,
                    "owner_idx": state.active_player_idx,
                    "target_pos": list(action.target_pos) if action.target_pos else None,
                    "position": list(action.position) if action.position else None,
                },
            )
        state = _apply_play_card(
            state, action, library, event_collector=event_collector,
        )
    elif action.action_type == ActionType.ATTACK:
        # 2026-07-08 timing audit (F4): capture + EVT_ATTACK_RESOLVED
        # emission moved into _apply_attack_with_event, shared with the
        # post-move-attack gate.
        state = _apply_attack_with_event(
            state, action, library, event_collector=event_collector,
        )
    elif action.action_type == ActionType.SACRIFICE:
        # Snapshot the minion pre-removal so the event carries its tile.
        _pre_sac = (
            state.get_minion(action.minion_id)
            if action.minion_id is not None else None
        )
        state = _apply_sacrifice(state, action, library)
        # 2026-07 fix: emit a board event so the client can play the
        # sacrifice-transcend animation — the old deriveAnimationJob wiring
        # was deleted in Phase 14.8-05 and SACRIFICE rendered silently.
        if event_collector is not None and _pre_sac is not None:
            _sac_card = library.get_by_id(_pre_sac.card_numeric_id)
            event_collector.collect(
                EVT_MINION_SACRIFICED,
                "action:sacrifice",
                {
                    "instance_id": _pre_sac.instance_id,
                    "card_numeric_id": _pre_sac.card_numeric_id,
                    "position": list(_pre_sac.position),
                    "owner_idx": int(_pre_sac.owner),
                    "damage": _sac_card.attack + _pre_sac.attack_bonus,
                },
            )
    elif action.action_type == ActionType.TRANSFORM:
        # Snapshot the pre-transform card so the event carries the swap.
        _pre_transform = (
            state.get_minion(action.minion_id)
            if action.minion_id is not None else None
        )
        state = _apply_transform(
            state, action, library, event_collector=event_collector,
        )
        # 2026-07 card-audit fix (Reanimated Bones): emit a board event
        # for the swap so the client eventQueue can animate it — since
        # Phase 14.8-05 removed state_update, a TRANSFORM previously
        # rendered silently on the final snapshot commit.
        if event_collector is not None and _pre_transform is not None:
            _post_transform = state.get_minion(action.minion_id)
            event_collector.collect(
                EVT_MINION_TRANSFORMED,
                "action:transform",
                {
                    "instance_id": _pre_transform.instance_id,
                    "from_card_numeric_id": _pre_transform.card_numeric_id,
                    "to_card_numeric_id": (
                        _post_transform.card_numeric_id
                        if _post_transform else None
                    ),
                    "position": list(_pre_transform.position),
                    "owner_idx": int(_pre_transform.owner),
                    "new_hp": (
                        _post_transform.current_health
                        if _post_transform else None
                    ),
                },
            )
    elif action.action_type == ActionType.ACTIVATE_ABILITY:
        # 2026-07-08 timing audit (F4): thread the collector so the token
        # summon / rat buffs / pending-tutor modal emit at their beats.
        state = _apply_activate_ability(
            state, action, library, event_collector=event_collector,
        )
    else:
        raise ValueError(f"Unsupported action type for main phase: {action.action_type}")

    # Phase 14.8-03a: emit mana / hp diff events for any side that
    # changed. 2026-07-08 timing audit (F4 dedup): the HP diff skips
    # deltas the handlers already emitted causally during this action
    # (inline _apply_effect_to_player emissions) so the client never
    # renders the same HP change twice.
    if event_collector is not None and _prev_mana is not None and _prev_hp is not None:
        _emitted_hp = {
            (e.payload.get("player_idx"), e.payload.get("new"))
            for e in event_collector.events[_events_start:]
            if e.type == EVT_PLAYER_HP_CHANGE
        }
        for _idx, (_pm, _ph) in enumerate(zip(_prev_mana, _prev_hp)):
            _now_mana = state.players[_idx].current_mana
            _now_hp = state.players[_idx].hp
            if _now_mana != _pm:
                event_collector.collect(
                    EVT_MANA_CHANGE,
                    f"action:{action.action_type.name.lower()}",
                    {
                        "player_idx": _idx,
                        "prev": _pm,
                        "new": _now_mana,
                        "delta": _now_mana - _pm,
                    },
                )
            if _now_hp != _ph and (_idx, _now_hp) not in _emitted_hp:
                event_collector.collect(
                    EVT_PLAYER_HP_CHANGE,
                    f"action:{action.action_type.name.lower()}",
                    {
                        "player_idx": _idx,
                        "prev": _ph,
                        "new": _now_hp,
                        "delta": _now_hp - _ph,
                    },
                )

    # Snapshot post-handler grave lengths so the post-cleanup diff below
    # can distinguish action-window adds (magic-to-grave) from
    # death-sourced adds (2026-07-08 timing audit F8).
    _post_action_grave_lens = (
        tuple(len(p.grave) for p in state.players) if event_collector else None
    )

    # Record the pending_action BEFORE cleanup so that a death modal can
    # defer the react window without losing the triggering action.
    state = replace(state, pending_action=action)

    # Dead minion cleanup (D-02)
    state = _cleanup_dead_minions(state, library, event_collector=event_collector)

    # 2026-07-08 timing audit (F8): the CARD_DISCARDED grave diff now runs
    # AFTER _cleanup_dead_minions so death-sourced grave adds emit at the
    # death beat (tagged cause='death') instead of never. Action-window
    # adds (magic-played-to-grave) keep the legacy payload shape.
    # 2026-07-08 timing audit (F10g): SACRIFICE grave adds are EXCLUDED
    # from the action-window diff — EVT_MINION_SACRIFICED already drives
    # the transcend animation and a discard beat would render over it.
    if (
        event_collector is not None
        and _prev_grave_lens is not None
        and _post_action_grave_lens is not None
    ):
        for _idx, _prev_len in enumerate(_prev_grave_lens):
            _now_grave = state.players[_idx].grave
            _post_len = _post_action_grave_lens[_idx]
            if action.action_type != ActionType.SACRIFICE:
                for _card_id in _now_grave[_prev_len:_post_len]:
                    event_collector.collect(
                        EVT_CARD_DISCARDED,
                        f"action:{action.action_type.name.lower()}",
                        {
                            "player_idx": _idx,
                            "card_numeric_id": _card_id,
                        },
                    )
            for _card_id in _now_grave[_post_len:]:
                event_collector.collect(
                    EVT_CARD_DISCARDED,
                    "system:cleanup_dead_minions",
                    {
                        "player_idx": _idx,
                        "card_numeric_id": _card_id,
                        "cause": "death",
                    },
                )

    # Win/draw detection (Phase 4) -- after cleanup, before react transition
    state = _check_game_over(state, event_collector=event_collector)
    if state.is_game_over:
        return state

    # If a death-trigger modal was opened during cleanup, defer the react
    # window until the dying minion's owner picks a target. pending_action
    # is already stashed on state so the banner text is correct when the
    # window eventually opens.
    if state.pending_death_target is not None:
        return state

    # Phase 14.7-05b: If the death-trigger priority drain opened the
    # trigger-picker modal (the owner must choose which of their
    # simultaneous on_death effects resolves next), defer.
    if state.pending_trigger_picker_idx is not None:
        return state

    # Phase 14.7-08: If MOVE entered pending-post-move-attack state, open
    # the post-move REACT window here (spec v2 §4.1: melee opens TWO
    # independent react windows, one after the move and one after the
    # optional attack). The pending_post_move_attacker_id survives the
    # react window; when resolve_react_stack's AFTER_ACTION dispatch
    # closes the window, it returns to ACTION (not END_OF_TURN) because
    # the pending flag is still set, so the player can choose ATTACK or
    # DECLINE_POST_MOVE_ATTACK next. This SUPERSEDES Phase 14.1's
    # combined-single-react-window semantic per key_user_decisions #1.
    if state.pending_post_move_attacker_id is not None:
        state = replace(
            state,
            phase=TurnPhase.REACT,
            react_player_idx=1 - state.active_player_idx,
            react_context=ReactContext.AFTER_ACTION,
            react_return_phase=TurnPhase.ACTION,
        )
        _emit_after_action_react_window_opened(state, event_collector)
        return state

    # Phase 14.2: If PLAY_CARD on_play entered pending_tutor state, defer
    # the react window until TUTOR_SELECT/DECLINE_TUTOR clears it. One react
    # window per logical card play.
    if state.pending_tutor_player_idx is not None:
        return state

    # If revive-place is pending, defer the react window until
    # REVIVE_PLACE/DECLINE_REVIVE clears it.
    if state.pending_revive_player_idx is not None:
        return state

    # Phase 14.6: If conjure-deploy is pending, defer the react window until
    # CONJURE_DEPLOY/DECLINE_CONJURE clears it.
    if state.pending_conjure_deploy_card is not None:
        return state

    # Phase 14.7-01 / 14.7-04: originator-pattern handlers (_cast_magic and
    # _deploy_minion) set their own REACT phase + react_context inline
    # (AFTER_ACTION for magic, AFTER_SUMMON_DECLARATION for minion summon)
    # and push their originator onto the stack BEFORE returning. Respect
    # that — only emit the generic AFTER_ACTION transition for actions
    # that didn't already arrange their own react window.
    if state.phase == TurnPhase.REACT:
        # Phase 14.8-05c: the inline transition (magic cast / summon
        # declaration) bypassed _handle_after_action's generic emit below,
        # so emit here so the client's eventQueue opens the spell stage.
        _emit_after_action_react_window_opened(state, event_collector)
        return state

    # Transition to REACT phase (D-13)
    # Phase 14.7-02: tag the REACT window as "after an ACTION" so
    # resolve_react_stack's react_return_phase dispatch sends it back
    # through close_end_react_and_advance_turn (legacy path).
    state = replace(
        state,
        phase=TurnPhase.REACT,
        react_player_idx=1 - state.active_player_idx,
        react_context=ReactContext.AFTER_ACTION,
        react_return_phase=TurnPhase.ACTION,
    )
    _emit_after_action_react_window_opened(state, event_collector)

    return state
