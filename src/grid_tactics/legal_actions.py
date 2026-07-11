"""Legal action enumeration -- returns all valid actions from any game state.

Main entry point: legal_actions(state, library) -> tuple[Action, ...]

During ACTION phase, enumerates:
  - PLAY_CARD: minion deployment (D-08 melee, D-09 ranged), magic targeting
  - MOVE: all orthogonal adjacent empty cells for owned minions
  - ATTACK: all valid targets in range (D-03) for owned minions
  - DRAW: if deck is non-empty
  - PASS: always (D-16)

During REACT phase, enumerates:
  - PLAY_REACT: react-eligible cards (CardType.REACT or is_multi_purpose)
  - PASS: always

This is critical for Phase 5 RL action masking -- legal_actions() provides the
boolean mask that prevents the agent from selecting invalid actions (D-19).
"""

from __future__ import annotations

from typing import Optional

from grid_tactics.action_resolver import _can_attack, _is_orthogonal
from grid_tactics.actions import (
    Action,
    attack_action,
    conjure_deploy_action,
    death_target_pick_action,
    decline_conjure_action,
    decline_post_move_attack_action,
    decline_trigger_action,
    decline_tutor_action,
    decline_revive_action,
    draw_action,
    move_action,
    pass_action,
    play_card_action,
    play_react_action,
    revive_place_action,
    sacrifice_action,
    transform_action,
    trigger_pick_action,
    tutor_select_action,
)
from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import (
    ActionType, CardType, EffectType, Element, PlayerSide, ReactCondition,
    ReactContext, TargetType, TriggerType, TurnPhase,
)
from grid_tactics.game_state import GameState
from grid_tactics.types import (
    BACK_ROW_P1,
    BACK_ROW_P2,
    GRID_COLS,
    GRID_ROWS,
    MAX_REACT_STACK_DEPTH,
    PLAYER_1_ROWS,
    PLAYER_2_ROWS,
    manual_draw_variant,
)


def effective_mana_cost(
    card_def, state: GameState, player_idx: int, library=None,
) -> int:
    """Compute effective mana cost after cost reductions (e.g. dark_matter).

    Returns max(0, base_cost - reduction). Dark Matter pool redesign
    2026-07: cost_reduction="dark_matter" (Erebus) subtracts the PLAYER's
    Dark Matter pool (Player.dark_matter). Reading the pool does NOT
    consume it.
    """
    cost = card_def.mana_cost
    if card_def.cost_reduction == "dark_matter":
        cost = max(0, cost - state.players[player_idx].dark_matter)
    elif card_def.cost_reduction == "wyrms_discarded":
        # Light Wyrm (2026-07-11): -1 per Wyrm-tribe card in the player's
        # Exhaust Pile (discards go there) — INCLUDING copies of itself.
        if library is not None:
            wyrms = 0
            for cid in state.players[player_idx].exhaust:
                try:
                    if "Wyrm" in (library.get_by_id(cid).tribe or "").split():
                        wyrms += 1
                except KeyError:
                    continue
            cost = max(0, cost - wyrms)
    elif card_def.cost_reduction == "behind_on_board":
        # Comeback discount (Metal Wyrm 2026-07-11): fixed reduction while
        # the opponent has a living minion and the player has none.
        my_side = state.players[player_idx].side
        i_have = any(
            m.owner == my_side and m.current_health > 0 for m in state.minions
        )
        opp_has = any(
            m.owner != my_side and m.current_health > 0 for m in state.minions
        )
        if opp_has and not i_have:
            cost = max(0, cost - (card_def.cost_reduction_amount or 0))
    return cost


def legal_actions(
    state: GameState, library: CardLibrary,
) -> tuple[Action, ...]:
    """Return all valid actions for the current game state.

    Never includes illegal actions. PASS is always present (D-16).

    Args:
        state: Current game state.
        library: CardLibrary for card definition lookups.

    Returns:
        Tuple of all valid Action instances.
    """
    # Game is over -- no actions allowed
    if state.is_game_over:
        return ()

    # Pending death-target (phase-agnostic): while a death-triggered modal
    # is open, the only legal action is DEATH_TARGET_PICK targeting an
    # eligible minion per the filter. This gate must come BEFORE every
    # other pending/phase gate so cleanup-triggered modals are handled
    # correctly regardless of whether the death happened during ACTION or
    # REACT phase.
    if state.pending_death_target is not None:
        return _pending_death_target_actions(state, library)

    # Phase 14.7-05: pending_trigger_picker (phase-agnostic): while the
    # priority-queue modal is open, the ONLY legal actions are
    # TRIGGER_PICK (one per entry in the picker owner's queue) and
    # DECLINE_TRIGGER (skip remaining). Overrides normal phase-based
    # enumeration — mirrors the pending_tutor pattern. This gate must
    # come BEFORE the REACT-phase enumeration so the reacting player
    # sees an empty legal-action set (they can't interact while the
    # caster is picking).
    if state.pending_trigger_picker_idx is not None:
        return _pending_trigger_picker_actions(state, library)

    # Pending revive-place: player must pick a deploy cell for each revived
    # minion or DECLINE_REVIVE to stop early.
    if state.pending_revive_player_idx is not None:
        return _pending_revive_actions(state, library)

    # Mutex: the two pending flavours must never coexist. Loud assert (defense
    # in depth on top of the asserts in _enter_pending_tutor / action_resolver).
    assert not (
        state.pending_tutor_player_idx is not None
        and state.pending_post_move_attacker_id is not None
    ), "pending_tutor and pending_post_move_attacker cannot coexist"

    # Phase 14.6: while pending_conjure_deploy is set, the ONLY legal actions
    # are CONJURE_DEPLOY (one per valid empty tile on deployer's side) and
    # DECLINE_CONJURE (card goes to hand instead). Slot reinterpretation:
    #   - CONJURE_DEPLOY reuses PLAY_CARD slots [0:250] with card_index=0,
    #     position = deploy tile. The encoder/decoder disambiguate using
    #     state.pending_conjure_deploy_card.
    #   - DECLINE_CONJURE reuses slot 1001 (PASS).
    if state.pending_conjure_deploy_card is not None:
        return _pending_conjure_deploy_actions(state, library)

    # Phase 14.2: while pending_tutor is set, the ONLY legal actions are
    # TUTOR_SELECT (one per match index in state.pending_tutor_matches) and
    # DECLINE_TUTOR. Slot reinterpretation in the integer action space:
    #   - TUTOR_SELECT reuses PLAY_CARD slots [0:n] (the encoder writes the
    #     match index on Action.card_index, then PLAY_CARD_BASE + match_idx*25)
    #     -- regular PLAY_CARD is illegal here so the channel is free.
    #   - DECLINE_TUTOR reuses slot 1001 (PASS); the encoder/decoder
    #     disambiguate using state.pending_tutor_player_idx, mirroring the
    #     14.1 DECLINE_POST_MOVE_ATTACK trick.
    # The action_resolver layer enforces the same restriction at runtime; this
    # branch keeps RL agents (and the human UI) from selecting illegal slots.
    if state.pending_tutor_player_idx is not None:
        return _pending_tutor_actions(state)

    # Phase 14.1 / 14.7-08: while a melee minion is mid-move-attack (pending)
    # AND we are in ACTION phase, the only legal actions are ATTACK from the
    # pending attacker against an in-range enemy, or DECLINE_POST_MOVE_ATTACK.
    # Slot 1001 (PASS) is reinterpreted as DECLINE in this state by the
    # action encoder. PLAY_CARD, MOVE, SACRIFICE, DRAW, regular PASS and
    # REACT are all illegal here.
    #
    # 14.7-08 tightening: the pending flag now survives the post-move REACT
    # window. While phase==REACT, the reacting player's legal actions are
    # the usual react-phase set (PASS + any legal react cards); the ATTACK
    # / DECLINE sub-action choice only becomes legal after the window
    # closes and we return to ACTION with pending still set. Gate the
    # pending enumeration on phase==ACTION so REACT enumeration is not
    # shadowed.
    if (
        state.pending_post_move_attacker_id is not None
        and state.phase == TurnPhase.ACTION
    ):
        return _pending_post_move_attack_actions(state, library)

    if state.phase == TurnPhase.ACTION:
        return _action_phase_actions(state, library)
    elif state.phase == TurnPhase.REACT:
        return _react_phase_actions(state, library)
    elif state.phase == TurnPhase.START_OF_TURN or state.phase == TurnPhase.END_OF_TURN:
        # Phase 14.7-02: START/END phases are empty and auto-advance via
        # the server's submit_action loop (events.py). Returning an empty
        # tuple signals the caller to call enter_start_of_turn /
        # enter_end_of_turn to transition out. 14.7-03 will populate these
        # phases with ON_START_OF_TURN / ON_END_OF_TURN triggers and REACT
        # windows; for now they auto-transition with no observable effects.
        return ()
    else:
        # Unknown phase -- return only PASS as safe fallback
        return (pass_action(),)


# ---------------------------------------------------------------------------
# ACTION phase enumeration
# ---------------------------------------------------------------------------


def _action_phase_actions(
    state: GameState, library: CardLibrary,
) -> tuple[Action, ...]:
    """Enumerate all valid actions during the ACTION phase."""
    actions: list[Action] = []
    player = state.active_player
    player_side = player.side

    # PLAY_CARD enumeration
    for idx, card_numeric_id in enumerate(player.hand):
        card_def = library.get_by_id(card_numeric_id)

        # Play condition check (e.g. "discarded_last_turn")
        if card_def.play_condition == "discarded_last_turn" and not player.discarded_last_turn:
            continue

        # Unique keyword (2026-07 card-audit fix, Giant Rat): a unique
        # minion cannot be played while a live copy owned by this player
        # is already on the board. Mirrors the tensor engine's play gate;
        # action_resolver re-validates for out-of-band callers.
        if card_def.unique and any(
            m.owner == player_side
            and m.is_alive
            and m.card_numeric_id == card_numeric_id
            for m in state.minions
        ):
            continue

        # Alternate discard cost (Dark Wyrm, user 2026-07-11): the card can
        # be played EITHER for its mana cost (no discards) OR for 0 mana by
        # discarding alt_cost_discard OTHER hand cards. Enumerate both
        # modes; the mana gate below only blocks the mana mode.
        alt_combos: list[tuple[int, ...]] = []
        if card_def.alt_cost_discard:
            _alt_others = [j for j in range(len(player.hand)) if j != idx]
            if len(_alt_others) >= card_def.alt_cost_discard:
                import itertools as _itertools
                alt_combos = [
                    tuple(c)
                    for c in _itertools.combinations(
                        _alt_others, card_def.alt_cost_discard,
                    )
                ]

        # Check mana (D-11), with cost reduction
        eff_cost = effective_mana_cost(card_def, state, state.active_player_idx, library)
        _mana_mode_ok = player.current_mana >= eff_cost
        if not _mana_mode_ok and not alt_combos:
            continue

        # HP cost — caster must have at least hp_cost HP to self-damage
        # when playing the card. Strictly >= so playing can reduce them
        # to exactly 0 (which ends the game).
        if card_def.hp_cost is not None and player.hp < card_def.hp_cost:
            continue

        # Summon sacrifice check: enumerate every valid *combination* of
        # hand-card picks. For discard_cost_count=1 each combo is a single
        # index; for count>1 each combo is a tuple of distinct picks. The
        # action carries them as both `discard_card_index` (= combo[0], for
        # back-compat) and `discard_card_indices` (the full tuple).
        sacrifice_combos: list[Optional[tuple[int, ...]]] = [None]
        if card_def.discard_cost_tribe:
            candidates: list[int] = []
            for j in range(len(player.hand)):
                if j == idx:
                    continue
                if card_def.discard_cost_tribe == "any":
                    candidates.append(j)
                else:
                    hand_card = library.get_by_id(player.hand[j])
                    if card_def.discard_cost_tribe in (hand_card.tribe or "").split():
                        candidates.append(j)
            sac_needed = card_def.discard_cost_count
            if len(candidates) < sac_needed:
                continue  # not enough sacrifice cards -> can't play
            import itertools as _itertools
            sacrifice_combos = [tuple(c) for c in _itertools.combinations(candidates, sac_needed)]

        # Alternate discard cost: the None entry is the pay-mana mode (only
        # when affordable); each combo is a 0-mana discard mode.
        if card_def.alt_cost_discard:
            sacrifice_combos = ([None] if _mana_mode_ok else []) + alt_combos

        for sac_combo in sacrifice_combos:
            sac_idx = sac_combo[0] if sac_combo else None
            sac_indices = sac_combo if sac_combo else ()
            if card_def.card_type == CardType.MINION:
                deploy_positions = _valid_deploy_positions(state, card_def, player_side)
                for pos in deploy_positions:
                    # Check if card has ON_PLAY effects with SINGLE_TARGET
                    has_single_target_on_play = any(
                        e.trigger == TriggerType.ON_PLAY and e.target == TargetType.SINGLE_TARGET
                        for e in card_def.effects
                    )
                    if has_single_target_on_play:
                        # Enumerate target positions (enemy minions)
                        enemy_positions = _get_enemy_minion_positions(state, player_side)
                        if enemy_positions:
                            for target_pos in enemy_positions:
                                actions.append(Action(
                                    action_type=ActionType.PLAY_CARD,
                                    card_index=idx, position=pos, target_pos=target_pos,
                                    discard_card_index=sac_idx,
                                    discard_card_indices=sac_indices,
                                ))
                        else:
                            actions.append(Action(
                                action_type=ActionType.PLAY_CARD,
                                card_index=idx, position=pos,
                                discard_card_index=sac_idx,
                                discard_card_indices=sac_indices,
                            ))
                    else:
                        actions.append(Action(
                            action_type=ActionType.PLAY_CARD,
                            card_index=idx, position=pos,
                            discard_card_index=sac_idx,
                            discard_card_indices=sac_indices,
                        ))

            elif card_def.card_type == CardType.MAGIC:
                # Check if any ON_PLAY effect has SINGLE_TARGET
                has_single_target = any(
                    e.trigger == TriggerType.ON_PLAY and e.target == TargetType.SINGLE_TARGET
                    for e in card_def.effects
                )

                # Sacrifice ally cost: enumerate ally minion choices
                ally_choices: list[Optional[int]] = [None]
                if card_def.destroy_ally_cost:
                    friendly = [m for m in state.minions if m.owner == player_side and m.current_health > 0]
                    if not friendly:
                        continue  # can't play without an ally to sacrifice
                    ally_choices = [m.instance_id for m in friendly]

                for destroy_ally_id in ally_choices:
                    if has_single_target:
                        enemy_positions = _get_enemy_minion_positions(state, player_side)
                        # Water Wyrm (2026-07-11): magic-untargetable minions
                        # are not valid MAGIC targets. With every enemy
                        # untargetable the magic is simply unplayable.
                        enemy_positions = [
                            pos for pos in enemy_positions
                            if not _magic_untargetable_at(state, library, pos)
                        ]
                        for target_pos in enemy_positions:
                            actions.append(Action(
                                action_type=ActionType.PLAY_CARD,
                                card_index=idx, target_pos=target_pos,
                                discard_card_index=sac_idx,
                                discard_card_indices=sac_indices,
                                destroyed_minion_id=destroy_ally_id,
                            ))
                    else:
                        actions.append(Action(
                            action_type=ActionType.PLAY_CARD,
                            card_index=idx,
                            discard_card_index=sac_idx,
                            discard_card_indices=sac_indices,
                            destroyed_minion_id=destroy_ally_id,
                        ))

        # Skip CardType.REACT during ACTION phase

    # MOVE enumeration (forward only in lane)
    owned_minions = state.get_minions_for_side(player_side)
    _leap_sacrifice_ids: set[int] = set()  # Leap minions that can sacrifice (all tiles ahead enemy-occupied)
    for minion in owned_minions:
        row, col = minion.position
        # Forward: P1 moves down (+1 row), P2 moves up (-1 row)
        delta = 1 if player_side == PlayerSide.PLAYER_1 else -1
        fwd_row = row + delta
        if 0 <= fwd_row < GRID_ROWS:
            if state.board.get(fwd_row, col) is None:
                actions.append(move_action(
                    minion_id=minion.instance_id, position=(fwd_row, col),
                ))
            else:
                # LEAP: if the forward tile is blocked by an ENEMY, the minion
                # can jump over enemy blockers to the next empty tile. Cannot
                # leap over allies. If every tile from here to the opponent's
                # back row is enemy-occupied, Leap enables sacrifice.
                blocker = next(
                    (m for m in state.minions if m.position == (fwd_row, col)),
                    None,
                )
                # Can only leap over enemies, not allies
                if blocker is not None and blocker.owner == player_side:
                    continue  # ally blocking — no leap
                minion_card = library.get_by_id(minion.card_numeric_id)
                leap_amount = 0
                for eff in minion_card.effects:
                    if eff.effect_type == EffectType.LEAP:
                        leap_amount = max(leap_amount, eff.amount or 1)
                if leap_amount > 0:
                    # Walk forward over consecutive ENEMY blockers — at most
                    # leap_amount of them — landing on the first empty tile.
                    # Phase 14.8 bugfix: the old walk started PAST the first
                    # blocker and took leap_amount ADDITIONAL steps, so it
                    # enumerated jumps over leap_amount+1 enemies (3 tiles
                    # for Rathopper) that _apply_move then rejected with
                    # ValueError. Per the card ruling, jumping N enemies
                    # lands N+1 tiles away with N capped at leap_amount.
                    landing_row = fwd_row
                    enemies_jumped = 0
                    can_land = False
                    while 0 <= landing_row < GRID_ROWS:
                        occupant = next(
                            (m for m in state.minions if m.position == (landing_row, col)),
                            None,
                        )
                        if occupant is None:
                            can_land = True  # empty tile — land here
                            break
                        if occupant.owner == player_side:
                            break  # ally — can't leap over
                        enemies_jumped += 1
                        if enemies_jumped > leap_amount:
                            break  # too many enemies to clear
                        landing_row += delta
                    if can_land and state.board.get(landing_row, col) is None:
                        actions.append(move_action(
                            minion_id=minion.instance_id,
                            position=(landing_row, col),
                        ))

                    # Leap sacrifice check: scan ALL tiles ahead (no step limit).
                    # If every tile from here to the back row is enemy-occupied,
                    # the minion leaps over all of them and sacrifices.
                    scan_row = fwd_row
                    all_enemy_to_end = True
                    while 0 <= scan_row < GRID_ROWS:
                        occ = next(
                            (m for m in state.minions if m.position == (scan_row, col)),
                            None,
                        )
                        if occ is None or occ.owner == player_side:
                            all_enemy_to_end = False
                            break
                        scan_row += delta
                    if all_enemy_to_end:
                        _leap_sacrifice_ids.add(minion.instance_id)

    # ATTACK enumeration
    # General rule: a minion with effective attack <= 0 cannot attack.
    # Effective attack = card_def.attack + minion.attack_bonus.
    for minion in owned_minions:
        card_def = library.get_by_id(minion.card_numeric_id)
        effective_attack = card_def.attack + minion.attack_bonus
        if effective_attack <= 0:
            continue
        for enemy in state.minions:
            if enemy.owner != player_side:
                if _can_attack(minion, enemy, card_def):
                    actions.append(attack_action(
                        minion_id=minion.instance_id,
                        target_id=enemy.instance_id,
                    ))

    # SACRIFICE enumeration (Phase 4)
    # Minions on opponent's back row can be sacrificed.
    # Leap minions whose entire forward path is enemy-occupied can also sacrifice.
    for minion in owned_minions:
        row = minion.position[0]
        if player_side == PlayerSide.PLAYER_1 and row == BACK_ROW_P2:
            actions.append(sacrifice_action(minion_id=minion.instance_id))
        elif player_side == PlayerSide.PLAYER_2 and row == BACK_ROW_P1:
            actions.append(sacrifice_action(minion_id=minion.instance_id))
        elif minion.instance_id in _leap_sacrifice_ids:
            actions.append(sacrifice_action(minion_id=minion.instance_id))

    # TRANSFORM enumeration: minions with transform_options can transform on the board
    # for the listed mana cost into the target card form.
    for minion in owned_minions:
        card_def = library.get_by_id(minion.card_numeric_id)
        if not card_def.transform_options:
            continue
        for target_card_id, mana_cost in card_def.transform_options:
            if player.current_mana >= mana_cost:
                actions.append(transform_action(
                    minion_id=minion.instance_id,
                    transform_target=target_card_id,
                ))

    # ACTIVATED ABILITY enumeration: minions with an activated_ability whose
    # owner can pay the cost and has at least one valid target tile.
    for minion in owned_minions:
        card_def = library.get_by_id(minion.card_numeric_id)
        ability = card_def.activated_ability
        if ability is None:
            continue
        if player.current_mana < ability.mana_cost:
            continue
        if ability.target == "own_side_empty":
            own_rows = PLAYER_1_ROWS if player_side == PlayerSide.PLAYER_1 else PLAYER_2_ROWS
            for r in own_rows:
                for c in range(GRID_COLS):
                    if state.board.get(r, c) is None:
                        actions.append(Action(
                            action_type=ActionType.ACTIVATE_ABILITY,
                            minion_id=minion.instance_id,
                            target_pos=(r, c),
                        ))
        elif ability.target == "single_target":
            # Targeted ability — one action per valid target minion on board
            for target_m in state.minions:
                if target_m.current_health > 0:
                    actions.append(Action(
                        action_type=ActionType.ACTIVATE_ABILITY,
                        minion_id=minion.instance_id,
                        target_pos=target_m.position,
                    ))
        elif ability.target == "none":
            # Untargeted self-ability — emit exactly one action.
            actions.append(Action(
                action_type=ActionType.ACTIVATE_ABILITY,
                minion_id=minion.instance_id,
                target_pos=None,
            ))

    # Light Wyrm (2026-07-11): playable_from_exhaust cards may be summoned
    # straight out of the Exhaust Pile for effective cost minus
    # exhaust_play_discount. One action per (unique exhaust card, tile);
    # card_index carries the EXHAUST index.
    seen_exhaust_nids: set[int] = set()
    for ex_idx, ex_nid in enumerate(player.exhaust):
        if ex_nid in seen_exhaust_nids:
            continue  # copies are interchangeable
        try:
            ex_def = library.get_by_id(ex_nid)
        except KeyError:
            continue
        if not ex_def.playable_from_exhaust or ex_def.card_type != CardType.MINION:
            continue
        seen_exhaust_nids.add(ex_nid)
        ex_cost = max(
            0,
            effective_mana_cost(ex_def, state, state.active_player_idx, library)
            - (ex_def.exhaust_play_discount or 0),
        )
        if player.current_mana < ex_cost:
            continue
        for pos in _valid_deploy_positions(state, ex_def, player_side):
            actions.append(Action(
                action_type=ActionType.PLAY_FROM_EXHAUST,
                card_index=ex_idx,
                position=pos,
            ))

    # Turn-structure redesign 2026-07: DRAW is REMOVED as an action under
    # the standard rules (slot 1000 reserved).
    #
    # Variant v4.2 (user 2026-07-11): the DRAW slot is the REST action —
    # +1 mana AND +1 draw, consuming the turn action (see _apply_draw).
    # REST and PASS are mutually exclusive: REST is the skip until a MAGIC
    # is cast this turn, after which it transforms into a plain PASS (no
    # mana+draw skip on the free action a magic hands back). An empty deck
    # still leaves REST legal — the mana half is unconditional.
    if manual_draw_variant():
        if state.magic_cast_this_turn:
            actions.append(pass_action())
        else:
            actions.append(draw_action())
    else:
        # PASS is always legal during the action phase (D-16, CLAUDE.md)
        # under the standard rules — players can voluntarily skip.
        actions.append(pass_action())

    return tuple(actions)


# ---------------------------------------------------------------------------
# Pending tutor enumeration (Phase 14.2)
# ---------------------------------------------------------------------------


def _pending_tutor_actions(state: GameState) -> tuple[Action, ...]:
    """Enumerate the only-legal actions while pending_tutor is set.

    Legal:
      - TUTOR_SELECT(match_idx) for each ``match_idx in [0, len(matches))``
      - DECLINE_TUTOR (encoded on slot 1001 by the encoder) when zero
        matches remain, OR when this pending state is a conjure deck-pick
        (``pending_tutor_is_conjure``) — conjure decline semantics are
        unchanged by design.

    Mandatory tutoring (user-decided 2026-07-03): when a TUTOR modal opens
    WITH matches, the player MUST pick — declining is only legal at ZERO
    matches. In practice ``_enter_pending_tutor`` never enters the pending
    state with zero matches (it auto-resolves), so the zero-match
    DECLINE_TUTOR branch here is a defensive escape hatch that keeps the
    game from wedging if a zero-match pending state ever materialises. A
    full hand does NOT exempt the pick: the tutored card overdraw-burns to
    the Exhaust Pile revealed (Player.add_to_hand_with_overdraw).

    Conjure exemption: Ratchanter's conjure ability enters this SAME
    pending state with ``pending_tutor_is_conjure=True``. Mandatory
    tutoring applies to tutors ONLY — a conjure deck-pick may still be
    declined (DECLINE_TUTOR leaves the card in the deck).

    Mutually exclusive with the 14.1 pending-post-move-attack state (asserted
    upstream in ``legal_actions``).
    """
    actions: list[Action] = [
        tutor_select_action(match_index=i)
        for i in range(len(state.pending_tutor_matches))
    ]
    if not actions or state.pending_tutor_is_conjure:
        actions.append(decline_tutor_action())
    return tuple(actions)


# ---------------------------------------------------------------------------
# Pending trigger picker enumeration (Phase 14.7-05)
# ---------------------------------------------------------------------------


def _pending_trigger_picker_actions(
    state: GameState, library: CardLibrary,
) -> tuple[Action, ...]:
    """Enumerate the only-legal actions while the trigger picker modal is open.

    Phase 14.7-05: When ``pending_trigger_picker_idx`` is set, the picker
    owner's legal actions are TRIGGER_PICK(queue_idx) for each entry in
    THEIR queue (turn queue if picker == active_player_idx else other
    queue) plus DECLINE_TRIGGER to fizzle the rest.

    The reacting player (non-picker) has NO legal actions here — the
    server waits on the picker owner. Returning an empty tuple for the
    non-picker keeps the client's legal-action masking correct.
    """
    picker = state.pending_trigger_picker_idx
    if picker is None:
        return ()
    is_turn_queue = (picker == state.active_player_idx)
    q = (
        state.pending_trigger_queue_turn
        if is_turn_queue
        else state.pending_trigger_queue_other
    )
    actions: list[Action] = [
        trigger_pick_action(queue_idx=i) for i in range(len(q))
    ]
    actions.append(decline_trigger_action())
    return tuple(actions)


# ---------------------------------------------------------------------------
# Pending revive enumeration
# ---------------------------------------------------------------------------


def revive_grave_matches(state: GameState, library: CardLibrary) -> tuple[int, ...]:
    """Grave indices revivable under the pending revive's card-text filter.

    Generalized revive (user 2026-07-11): mirrors the tutor/conjure pick.
    Eligibility: MINION cards only, then the exact-card filter
    (``pending_revive_card_id``) and/or tribe filter
    (``pending_revive_tribe``); both None = any minion in the grave.
    Shared by legal_actions, the resolver's validation, and the server's
    per-viewer enrichment so all three agree on the pickable set.
    """
    player_idx = state.pending_revive_player_idx
    if player_idx is None:
        return ()
    exact = state.pending_revive_card_id
    tribe = state.pending_revive_tribe
    exclude = state.pending_revive_exclude_card_id
    out: list[int] = []
    for i, cid in enumerate(state.players[player_idx].grave):
        try:
            cd = library.get_by_id(cid)
        except KeyError:
            continue
        if cd.card_type != CardType.MINION:
            continue
        if exact and cd.card_id != exact:
            continue
        if tribe and tribe not in (cd.tribe or "").split():
            continue
        if exclude and cd.card_id == exclude:
            continue  # Earth Wyrm: no sacrifice-revive self-loops
        out.append(i)
    return tuple(out)


def _pending_revive_actions(state: GameState, library: CardLibrary) -> tuple[Action, ...]:
    """Enumerate legal actions while pending_revive is set.

    Legal:
      - REVIVE_PLACE(card_index=<grave idx>, position) for each pickable
        grave card (one representative grave index per unique card — the
        copies are interchangeable) x each empty cell in that card's
        deploy zone (melee: any own row; ranged: back row only)
      - DECLINE_REVIVE to stop placing early
    """
    player_idx = state.pending_revive_player_idx
    if player_idx is None:
        return (decline_revive_action(),)

    matches = revive_grave_matches(state, library)
    if not matches:
        return (decline_revive_action(),)

    from grid_tactics.types import PLAYER_1_ROWS, PLAYER_2_ROWS, BACK_ROW_P1, BACK_ROW_P2
    player = state.players[player_idx]

    actions: list[Action] = []
    for grave_idx in matches:
        nid = player.grave[grave_idx]
        # Every match index is a legal pick (copies included) — the client
        # fan may reference ANY of them, so no representative dedupe here.
        revive_def = library.get_by_id(nid)
        if player_idx == 0:
            deploy_rows = PLAYER_1_ROWS if revive_def.attack_range == 0 else (BACK_ROW_P1,)
        else:
            deploy_rows = PLAYER_2_ROWS if revive_def.attack_range == 0 else (BACK_ROW_P2,)
        for r in deploy_rows:
            for c in range(5):
                if state.board.get(r, c) is None:
                    actions.append(revive_place_action(
                        position=(r, c), card_index=grave_idx,
                    ))

    actions.append(decline_revive_action())
    return tuple(actions)


# ---------------------------------------------------------------------------
# Pending death-target enumeration (death-triggered modal)
# ---------------------------------------------------------------------------


def _pending_death_target_actions(
    state: GameState, library: CardLibrary,
) -> tuple[Action, ...]:
    """Enumerate legal DEATH_TARGET_PICK actions while a death modal is open.

    Filters:
      - ``enemy_minion`` — pick an alive enemy of the dying minion's owner
        (e.g. Lasercannon destroy).
      - ``friendly_promote`` — pick a friendly alive minion whose card_id
        matches the dying card's promote_target (e.g. Giant Rat promote
        when 2+ ally Rats are on board).

    If no eligible targets exist (shouldn't happen in practice because
    resolve_death_effects_or_enter_modal checks this and falls through to
    no-op), returns an empty tuple — the caller should handle that.
    """
    target = state.pending_death_target
    if target is None:
        return ()

    owner_side = PlayerSide(target.owner_idx)
    actions: list[Action] = []

    if target.filter == "enemy_minion":
        for m in state.minions:
            if m.owner == owner_side:
                continue
            if not m.is_alive:
                continue
            actions.append(death_target_pick_action(target_pos=m.position))
    elif target.filter == "friendly_promote":
        dying_def = library.get_by_id(target.card_numeric_id)
        promote_card_id = dying_def.promote_target
        if promote_card_id:
            promote_numeric_id = library.get_numeric_id(promote_card_id)
            for m in state.minions:
                if m.owner != owner_side:
                    continue
                if not m.is_alive:
                    continue
                if m.card_numeric_id != promote_numeric_id:
                    continue
                actions.append(death_target_pick_action(target_pos=m.position))
    else:
        raise ValueError(
            f"Unknown pending_death_target filter: {target.filter}"
        )

    return tuple(actions)


# ---------------------------------------------------------------------------
# Pending conjure deploy enumeration (Phase 14.6)
# ---------------------------------------------------------------------------


def _pending_conjure_deploy_actions(
    state: GameState, library: CardLibrary,
) -> tuple[Action, ...]:
    """Enumerate the only-legal actions while pending_conjure_deploy is set.

    Legal:
      - CONJURE_DEPLOY(position) for each valid empty tile on deployer's side
      - DECLINE_CONJURE (card goes to hand) ONLY when zero deploy tiles
        exist — conjure must deploy (user 2026-07-10; the to-hand escape
        was removed, kept solely as the no-tile fallback so the pending
        state can never wedge).

    The conjured card uses standard deploy rules (melee = any friendly tile,
    ranged = back row only).
    """
    deployer_idx = state.pending_conjure_deploy_player_idx
    deployer_side = state.players[deployer_idx].side
    card_numeric_id = state.pending_conjure_deploy_card
    card_def = library.get_by_id(card_numeric_id)

    deploy_positions = _valid_deploy_positions(state, card_def, deployer_side)

    actions: list[Action] = [
        conjure_deploy_action(position=pos)
        for pos in deploy_positions
    ]
    if not actions:
        actions.append(decline_conjure_action())
    return tuple(actions)


# ---------------------------------------------------------------------------
# Pending post-move attack enumeration (Phase 14.1)
# ---------------------------------------------------------------------------


def _pending_post_move_attack_actions(
    state: GameState, library: CardLibrary,
) -> tuple[Action, ...]:
    """Enumerate the only-legal actions while a post-move attack is pending.

    Legal:
      - ATTACK from the pending attacker against any in-range enemy minion
      - DECLINE_POST_MOVE_ATTACK (encoded on slot 1001 by the encoder)

    Slot 1001 dual meaning: in non-pending state slot 1001 is PASS; in
    pending state the action encoder maps slot 1001 to
    DECLINE_POST_MOVE_ATTACK. The action_resolver dispatches based on
    ``state.pending_post_move_attacker_id``.
    """
    actions: list[Action] = []
    attacker = state.get_minion(state.pending_post_move_attacker_id)
    if attacker is None:
        # Defensive: pending references a missing minion -> only decline
        return (decline_post_move_attack_action(),)

    attacker_card = library.get_by_id(attacker.card_numeric_id)
    if attacker_card.attack + attacker.attack_bonus <= 0:
        return (decline_post_move_attack_action(),)
    for enemy in state.minions:
        if enemy.owner == attacker.owner:
            continue
        if _can_attack(attacker, enemy, attacker_card):
            actions.append(attack_action(
                minion_id=attacker.instance_id,
                target_id=enemy.instance_id,
            ))

    # DECLINE is always legal in pending state (escape hatch)
    actions.append(decline_post_move_attack_action())
    return tuple(actions)


# ---------------------------------------------------------------------------
# REACT phase enumeration
# ---------------------------------------------------------------------------


def _check_react_condition(
    condition: ReactCondition, state: GameState, library: CardLibrary,
) -> bool:
    """Check if a react card's condition is met by the current react window.

    Phase 14.7-07: Primary dispatch is now on ``state.react_context``. Three
    new conditions (OPPONENT_SUMMONS_MINION, OPPONENT_START_OF_TURN,
    OPPONENT_END_OF_TURN) are gated strictly on the context tag — they
    match ONLY during the react window that context opened. Legacy
    conditions (OPPONENT_PLAYS_MAGIC, OPPONENT_PLAYS_MINION, element
    conditions, etc.) keep their pre-14.7 behavior: they check the
    react_stack's most-recent entry and/or the pending_action. The
    legacy conditions are also gated away from non-AFTER_ACTION /
    non-summon windows so a stray START_OF_TURN trigger window can't
    accidentally match (e.g.) an OPPONENT_PLAYS_MAGIC.

    Dispatch table (context → which conditions may match):
      - AFTER_ACTION: OPPONENT_PLAYS_MAGIC, OPPONENT_PLAYS_MINION,
        OPPONENT_ATTACKS, OPPONENT_SACRIFICES, OPPONENT_PLAYS_REACT,
        OPPONENT_DISCARDS, OPPONENT_ENDS_TURN, element conditions,
        ANY_ACTION.
      - AFTER_SUMMON_DECLARATION / AFTER_SUMMON_EFFECT:
        OPPONENT_SUMMONS_MINION, OPPONENT_PLAYS_MINION (back-compat),
        element conditions (match the summon's element),
        OPPONENT_PLAYS_REACT (once a react sits on top), ANY_ACTION.
      - AFTER_START_TRIGGER: OPPONENT_START_OF_TURN,
        OPPONENT_PLAYS_REACT (once a react sits on top), ANY_ACTION.
      - BEFORE_END_OF_TURN: OPPONENT_END_OF_TURN,
        OPPONENT_PLAYS_REACT (once a react sits on top), ANY_ACTION.
      - AFTER_DEATH_EFFECT: OPPONENT_PLAYS_REACT, ANY_ACTION (no other
        conditions match today; future death-trigger conditions land here).
      - None (legacy/unset): fall back to pending_action inspection.
    """
    ctx = state.react_context

    # ANY_ACTION short-circuit — always legal in any open window.
    if condition == ReactCondition.ANY_ACTION:
        return True

    # OPPONENT_TUTORS (2026-07-09): fires in any post-action / post-summon
    # react window once the active (turn-owning) player has tutored this turn.
    # The flag is set when their tutor MODAL opens (effect_resolver), which
    # resolves BEFORE the react window opens — so a summoned tutor (Diodebot,
    # a summon window) or a magic tutor (AFTER_ACTION) both surface here.
    # Start/End/Death windows are their own trigger semantics and excluded.
    if condition == ReactCondition.OPPONENT_TUTORS:
        if ctx in (
            ReactContext.AFTER_ACTION,
            ReactContext.AFTER_SUMMON_DECLARATION,
            ReactContext.AFTER_SUMMON_EFFECT,
            None,
        ):
            return state.players[state.active_player_idx].tutored_this_turn
        return False

    # ------------- 14.7-07: context-tagged conditions -------------
    # These are driven purely by react_context and fire even during
    # counter-react chains inside the same window. They're checked
    # BEFORE the counter-react branch so a chained react doesn't
    # mask the window's underlying trigger semantics.
    if condition == ReactCondition.OPPONENT_SUMMONS_MINION:
        # Fires during either summon window (declaration or effect).
        return ctx in (
            ReactContext.AFTER_SUMMON_DECLARATION,
            ReactContext.AFTER_SUMMON_EFFECT,
        )

    if condition == ReactCondition.OPPONENT_START_OF_TURN:
        return ctx == ReactContext.AFTER_START_TRIGGER

    if condition == ReactCondition.OPPONENT_END_OF_TURN:
        return ctx == ReactContext.BEFORE_END_OF_TURN

    # Phase 14.8-05c: legacy OPPONENT_ENDS_TURN (added pre-3-phase-turn)
    # used to fire on any opponent action (semantic: "every action ended
    # the opponent's turn" because there was 1 action per turn). With
    # the Start → Action → End structure, end-of-turn reacts must wait
    # for the BEFORE_END_OF_TURN window so all automatic end-of-turn
    # effects resolve first. Treat ENDS_TURN as a synonym of
    # END_OF_TURN for the new semantic. Two cards use this condition:
    # Acidic Rain (multi-purpose magic) and Tree Wyrm (multi-purpose
    # minion); both should only fire at end-of-turn, not after every
    # opponent action.
    if condition == ReactCondition.OPPONENT_ENDS_TURN:
        return ctx == ReactContext.BEFORE_END_OF_TURN

    # ---------------- Counter-react (react-on-react) ----------------
    # If a non-originator react sits on top of the stack, the player is
    # counter-reacting. OPPONENT_PLAYS_REACT matches in ANY context.
    # OPPONENT_PLAYS_MAGIC also matches here (a react card is magic-like
    # for the purposes of Prohibition — preserves pre-14.7 behavior).
    if state.react_stack:
        top = state.react_stack[-1]
        is_counter_react = not getattr(top, "is_originator", False)
        if is_counter_react:
            if condition == ReactCondition.OPPONENT_PLAYS_REACT:
                return True
            if condition == ReactCondition.OPPONENT_PLAYS_MAGIC:
                top_card = library.get_by_id(top.card_numeric_id)
                return top_card.card_type in (CardType.MAGIC, CardType.REACT)
            # Element-based counter-reacts: check the top react's element.
            _ELEM = {
                ReactCondition.OPPONENT_PLAYS_WOOD: Element.WOOD,
                ReactCondition.OPPONENT_PLAYS_FIRE: Element.FIRE,
                ReactCondition.OPPONENT_PLAYS_EARTH: Element.EARTH,
                ReactCondition.OPPONENT_PLAYS_WATER: Element.WATER,
                ReactCondition.OPPONENT_PLAYS_METAL: Element.METAL,
                ReactCondition.OPPONENT_PLAYS_DARK: Element.DARK,
                ReactCondition.OPPONENT_PLAYS_LIGHT: Element.LIGHT,
            }
            if condition in _ELEM:
                top_card = library.get_by_id(top.card_numeric_id)
                return top_card.element == _ELEM[condition]
            # All other conditions do not match a counter-react entry.
            return False

    # ------------- Summon-window legacy / element matching -------------
    # If we're in a summon window, gate element conditions + legacy
    # OPPONENT_PLAYS_MINION against the summon originator on the stack.
    if ctx in (
        ReactContext.AFTER_SUMMON_DECLARATION,
        ReactContext.AFTER_SUMMON_EFFECT,
    ):
        if condition == ReactCondition.OPPONENT_PLAYS_MINION:
            return True  # back-compat alias for OPPONENT_SUMMONS_MINION
        # Element conditions: match the summoned minion's element.
        _ELEM_CONDITIONS = {
            ReactCondition.OPPONENT_PLAYS_WOOD: Element.WOOD,
            ReactCondition.OPPONENT_PLAYS_FIRE: Element.FIRE,
            ReactCondition.OPPONENT_PLAYS_EARTH: Element.EARTH,
            ReactCondition.OPPONENT_PLAYS_WATER: Element.WATER,
            ReactCondition.OPPONENT_PLAYS_METAL: Element.METAL,
            ReactCondition.OPPONENT_PLAYS_DARK: Element.DARK,
            ReactCondition.OPPONENT_PLAYS_LIGHT: Element.LIGHT,
        }
        if condition in _ELEM_CONDITIONS:
            required_elem = _ELEM_CONDITIONS[condition]
            # Find the summon originator on the stack.
            for entry in state.react_stack:
                if getattr(entry, "is_originator", False) and getattr(
                    entry, "origin_kind", None
                ) in ("summon_declaration", "summon_effect"):
                    card_def = library.get_by_id(entry.card_numeric_id)
                    return card_def.element == required_elem
            return False
        # OPPONENT_PLAYS_MAGIC / OPPONENT_ATTACKS / etc. do NOT match a
        # summon window — spec §4.2 separates cast from summon.
        return False

    # ------------- Start/End/Death windows: no match for legacy -------------
    # During start-of-turn / end-of-turn / death-effect windows, legacy
    # action-based conditions don't apply (only the 14.7-07 context
    # conditions + ANY_ACTION + OPPONENT_PLAYS_REACT match, which were
    # already handled above).
    if ctx in (
        ReactContext.AFTER_START_TRIGGER,
        ReactContext.BEFORE_END_OF_TURN,
        ReactContext.AFTER_DEATH_EFFECT,
    ):
        return False

    # ------------- AFTER_ACTION / legacy fall-through -------------
    # ctx is either AFTER_ACTION or None (pre-14.7 call sites). Use the
    # magic-cast originator check first for OPPONENT_PLAYS_MAGIC; fall back
    # to pending_action inspection for everything else. This preserves the
    # 14.7-01 deferred-magic originator flow and the pre-14.7 pending_action
    # flow simultaneously.

    # OPPONENT_PLAYS_MAGIC: check for a magic_cast originator on the stack
    # (14.7-01 deferred-magic flow). Also preserves pre-14.7 fall-through
    # to pending_action when no originator is present (e.g. a test that
    # manually sets pending_action without a stack entry).
    if condition == ReactCondition.OPPONENT_PLAYS_MAGIC:
        for entry in state.react_stack:
            if getattr(entry, "is_originator", False) and getattr(
                entry, "origin_kind", None
            ) == "magic_cast":
                return True
        pending = state.pending_action
        if pending is None:
            return False
        if pending.action_type == ActionType.PLAY_CARD and pending.card_index is not None:
            acting_player = state.players[state.active_player_idx]
            if acting_player.grave:
                last_played_id = acting_player.grave[-1]
                card_def = library.get_by_id(last_played_id)
                return card_def.card_type == CardType.MAGIC
        return False

    # Pending-action-based conditions (MOVE / ATTACK / SACRIFICE / etc.)
    pending = state.pending_action
    if pending is None:
        return False

    if condition == ReactCondition.OPPONENT_PLAYS_MINION:
        # Legacy signal: PLAY_CARD with a position means a minion was deployed.
        # Under 14.7-04 this path is rarely hit (summon routes to
        # AFTER_SUMMON_DECLARATION above) but kept for back-compat with
        # any test or future non-compound path.
        if pending.action_type == ActionType.PLAY_CARD:
            return pending.position is not None
        return False

    if condition == ReactCondition.OPPONENT_ATTACKS:
        return pending.action_type == ActionType.ATTACK

    if condition == ReactCondition.OPPONENT_SACRIFICES:
        return pending.action_type == ActionType.SACRIFICE

    if condition == ReactCondition.OPPONENT_PLAYS_REACT:
        # No non-originator react on stack means nothing to counter-react
        return False

    # Phase 14.8-05c: OPPONENT_ENDS_TURN now gates on BEFORE_END_OF_TURN
    # context (handled in the upper context-tagged section). Pre-3-phase
    # behaviour was "always true on any opponent action"; with the new
    # Start → Action → End structure that fires too eagerly. The check
    # is in the context block above; if we got here, the context didn't
    # match and the condition fails.

    # Element-based conditions against pending PLAY_CARD (pre-14.7 flow)
    _ELEM_CONDITIONS = {
        ReactCondition.OPPONENT_PLAYS_WOOD: Element.WOOD,
        ReactCondition.OPPONENT_PLAYS_FIRE: Element.FIRE,
        ReactCondition.OPPONENT_PLAYS_EARTH: Element.EARTH,
        ReactCondition.OPPONENT_PLAYS_WATER: Element.WATER,
        ReactCondition.OPPONENT_PLAYS_METAL: Element.METAL,
        ReactCondition.OPPONENT_PLAYS_DARK: Element.DARK,
        ReactCondition.OPPONENT_PLAYS_LIGHT: Element.LIGHT,
    }
    if condition in _ELEM_CONDITIONS:
        required_elem = _ELEM_CONDITIONS[condition]
        if pending.action_type == ActionType.PLAY_CARD:
            acting_player = state.players[state.active_player_idx]
            if acting_player.grave:
                last_played_id = acting_player.grave[-1]
                card_def = library.get_by_id(last_played_id)
                return card_def.element == required_elem
            if pending.position is not None and state.minions:
                for m in state.minions:
                    if m.position == pending.position:
                        card_def = library.get_by_id(m.card_numeric_id)
                        return card_def.element == required_elem
        # Also check a magic_cast originator's element (14.7-01 deferred magic)
        for entry in state.react_stack:
            if getattr(entry, "is_originator", False) and getattr(
                entry, "origin_kind", None
            ) == "magic_cast":
                card_def = library.get_by_id(entry.card_numeric_id)
                return card_def.element == required_elem
        return False

    if condition == ReactCondition.OPPONENT_DISCARDS:
        acting_player = state.players[state.active_player_idx]
        return acting_player.discarded_this_turn

    return False


def _react_phase_actions(
    state: GameState, library: CardLibrary,
) -> tuple[Action, ...]:
    """Enumerate all valid actions during the REACT phase.

    React cards are only legal if their react_condition matches the
    pending action or last react on the stack.

    Phase 14.7-01: After this plan, ``state.react_stack[0]`` may be a
    magic_cast originator (is_originator=True, origin_kind="magic_cast").
    The enumeration below is unaffected — we read the reacting player's
    hand, and ``_check_react_condition`` treats the stack's most-recent
    entry uniformly (an originator's card_def is a MAGIC card, so
    OPPONENT_PLAYS_MAGIC matches it exactly as it matched a pending
    PLAY_CARD of a magic before deferred resolution).
    """
    actions: list[Action] = []
    react_player = state.players[state.react_player_idx]
    react_side = react_player.side

    # If stack is at max depth, only PASS is legal
    if len(state.react_stack) >= MAX_REACT_STACK_DEPTH:
        return (pass_action(),)

    for idx, card_numeric_id in enumerate(react_player.hand):
        card_def = library.get_by_id(card_numeric_id)

        if card_def.card_type == CardType.REACT:
            # Check condition matches the triggering action
            if card_def.react_condition is None:
                continue  # Shouldn't happen (validation catches this), but safety
            if not _check_react_condition(card_def.react_condition, state, library):
                continue  # Condition not met -- this react can't be played now

            if react_player.current_mana >= card_def.mana_cost:
                # NEGATE effects don't need a target (they cancel the triggering action)
                has_negate = any(
                    e.effect_type.name == "NEGATE"
                    for e in card_def.effects
                )
                if has_negate:
                    actions.append(play_react_action(card_index=idx))
                    continue

                # Check for single-target effects
                has_single_target = any(
                    e.target == TargetType.SINGLE_TARGET
                    for e in card_def.effects
                )
                if has_single_target:
                    enemy_positions = _get_enemy_minion_positions(state, react_side)
                    friendly_positions = _get_friendly_minion_positions(state, react_side)
                    all_target_positions = list(set(enemy_positions + friendly_positions))
                    for target_pos in all_target_positions:
                        actions.append(play_react_action(
                            card_index=idx, target_pos=target_pos,
                        ))
                    if not all_target_positions:
                        # No targets but card is playable (area effects, etc)
                        actions.append(play_react_action(card_index=idx))
                else:
                    actions.append(play_react_action(card_index=idx))

        elif card_def.is_multi_purpose:
            # Check condition if multi-purpose card has one
            if card_def.react_condition is not None:
                if not _check_react_condition(card_def.react_condition, state, library):
                    continue

            # Surgefed Sparkbot's gate: react mode is only available while
            # the react player controls NO live friendly minions. Mirrors
            # the resolver-side check in react_stack._play_react so the
            # enumerator never offers an action the resolver rejects.
            if card_def.react_requires_no_friendly_minions and any(
                m.owner == react_side and m.current_health > 0
                for m in state.minions
            ):
                continue

            if react_player.current_mana >= card_def.react_mana_cost:
                # DEPLOY_SELF: react deploys this minion to the board at discount
                if (card_def.react_effect is not None
                        and card_def.react_effect.effect_type == EffectType.DEPLOY_SELF):
                    deploy_positions = _valid_deploy_positions(state, card_def, react_side)
                    for pos in deploy_positions:
                        actions.append(play_react_action(
                            card_index=idx, target_pos=pos,
                        ))
                elif (card_def.react_effect is not None
                        and card_def.react_effect.target == TargetType.SINGLE_TARGET):
                    enemy_positions = _get_enemy_minion_positions(state, react_side)
                    friendly_positions = _get_friendly_minion_positions(state, react_side)
                    all_target_positions = list(set(enemy_positions + friendly_positions))
                    for target_pos in all_target_positions:
                        actions.append(play_react_action(
                            card_index=idx, target_pos=target_pos,
                        ))
                    if not all_target_positions:
                        actions.append(play_react_action(card_index=idx))
                else:
                    actions.append(play_react_action(card_index=idx))

        elif (card_def.card_type == CardType.MAGIC
              and card_def.react_condition is not None
              and card_def.react_mana_cost is not None):
            # Magic+react multi-purpose: plays its regular effects as a react
            if not _check_react_condition(card_def.react_condition, state, library):
                continue
            if react_player.current_mana >= card_def.react_mana_cost:
                actions.append(play_react_action(card_index=idx))

    # PASS always legal
    actions.append(pass_action())

    return tuple(actions)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_deploy_positions(state, card_def, side):
    """Return valid empty deploy positions for a minion card.

    D-08: Melee (range=0) -> any empty cell in friendly rows.
    D-09: Ranged (range>=1) -> only empty cells in back row.
    """
    if card_def.attack_range == 0:
        # Melee: all friendly rows
        rows = PLAYER_1_ROWS if side.value == 0 else PLAYER_2_ROWS
    else:
        # Ranged: back row only
        back_row = BACK_ROW_P1 if side.value == 0 else BACK_ROW_P2
        rows = (back_row,)

    positions = []
    for row in rows:
        for col in range(GRID_COLS):
            if state.board.get(row, col) is None:
                positions.append((row, col))
    return positions


def _magic_untargetable_at(state, library, pos) -> bool:
    """True when the minion at ``pos`` carries magic_untargetable (Water
    Wyrm 2026-07-11 — magic cards cannot pick it as a SINGLE_TARGET)."""
    for m in state.minions:
        if tuple(m.position) == tuple(pos) and m.current_health > 0:
            try:
                return bool(library.get_by_id(m.card_numeric_id).magic_untargetable)
            except KeyError:
                return False
    return False


def _get_enemy_minion_positions(state, player_side):
    """Return positions of all enemy minions on the board."""
    return [
        m.position for m in state.minions
        if m.owner != player_side
    ]


def _get_friendly_minion_positions(state, player_side):
    """Return positions of all friendly minions on the board."""
    return [
        m.position for m in state.minions
        if m.owner == player_side
    ]
