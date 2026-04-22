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
from grid_tactics.engine_events import (
    EVT_FIZZLE,
    EVT_MINION_HP_CHANGE,
    EVT_PENDING_MODAL_OPENED,
    EVT_PHASE_CHANGED,
    EVT_REACT_WINDOW_CLOSED,
    EVT_REACT_WINDOW_OPENED,
    EVT_TRIGGER_BLIP,
    EVT_TURN_FLIPPED,
    EventStream,
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
from grid_tactics.game_state import GameState, PendingTrigger
from grid_tactics.minion import BURN_DAMAGE, MinionInstance
from grid_tactics.phase_contracts import assert_phase_contract
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


def tick_status_effects(
    state: GameState,
    library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
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
    assert_phase_contract(state, "status:burn")
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

    # Phase 14.8-03a: emit one EVT_MINION_HP_CHANGE per burn tick.
    # contract_source matches the assert_phase_contract above.
    if event_collector is not None:
        for inst_id, new_minion in new_minions_by_id.items():
            event_collector.collect(
                EVT_MINION_HP_CHANGE,
                "status:burn",
                {
                    "instance_id": inst_id,
                    "new_hp": new_minion.current_health,
                    "delta": -total_burn,
                    "owner_idx": 0 if new_minion.owner == PlayerSide.PLAYER_1 else 1,
                    "position": list(new_minion.position),
                    "cause": "burn",
                },
            )

    # Route any newly-dead minions through the standard death-cleanup path
    # so on-death effects (and game-over checks) fire.
    from grid_tactics.action_resolver import _check_game_over, _cleanup_dead_minions
    state = _cleanup_dead_minions(state, library, event_collector=event_collector)
    state = _check_game_over(state, event_collector=event_collector)
    return state


# Phase 14.8-05: _fire_passive_effects was DELETED. It was a no-op since
# Phase 14.7-03 (no card JSON carried trigger='passive' after the three
# ex-passive minions — Fallen Paladin, Emberplague Rat, Dark Matter Battery
# — migrated to on_start_of_turn / on_end_of_turn). The invariant test
# `test_no_card_uses_passive_trigger` in tests/test_phase_contract_invariants.py
# guards against re-introducing PASSIVE triggers.


# ---------------------------------------------------------------------------
# Phase 14.7-03: ON_START_OF_TURN / ON_END_OF_TURN trigger firing
# ---------------------------------------------------------------------------


def _has_triggers_for(
    state: GameState, library: CardLibrary, trigger: TriggerType,
) -> bool:
    """Return True if any minion owned by the active player has an effect with ``trigger``.

    Used by enter_start_of_turn / enter_end_of_turn to decide whether to
    open a REACT window or shortcut directly to the next phase.
    """
    active_side = state.players[state.active_player_idx].side
    for m in state.minions:
        if m.owner != active_side or m.current_health <= 0:
            continue
        card_def = library.get_by_id(m.card_numeric_id)
        for effect in card_def.effects:
            if effect.trigger == trigger:
                return True
    return False


def _enqueue_turn_phase_triggers(
    state: GameState, library: CardLibrary, trigger: TriggerType, trigger_kind: str,
) -> GameState:
    """Collect simultaneous trigger effects for the active player's turn phase and enqueue them.

    Phase 14.7-05: Instead of resolving ON_START_OF_TURN / ON_END_OF_TURN
    effects inline in (row, col) order (pre-14.7-05 behavior), this helper
    enqueues every matching (minion, effect) pair into
    pending_trigger_queue_turn (for minions owned by the active player)
    or pending_trigger_queue_other (for minions owned by the non-active
    player — reserved; currently start/end triggers only fire for the
    TURN player's minions per §7.1, so other-queue stays empty for
    start/end. The other-queue wiring is still present for future
    on-summon-by-opponent / on-death scenarios reused in 14.7-05b).

    Fires AFTER the caller has bookended the phase transition
    (enter_start_of_turn has already set phase=START_OF_TURN and ticked
    burns). This helper DOES NOT resolve effects or open react windows —
    ``drain_pending_trigger_queue`` below handles ordering + modal picker.

    Ownership rule: only the TURN player's minions enqueue for
    start/end-of-turn triggers. An enemy minion's Start: trigger fires
    at ITS owner's next turn start — spec §7.1.
    """
    assert_phase_contract(state, "system:enqueue_triggers")
    active_side = state.players[state.active_player_idx].side

    turn_triggers: list[PendingTrigger] = []
    other_triggers: list[PendingTrigger] = []

    # Iterate minions in (row, col) order so the UNORDERED queue still has
    # deterministic pre-pick order (the picker modal surfaces the queue
    # order; we want it stable across runs for the same state).
    ordered = sorted(state.minions, key=lambda m: (m.position[0], m.position[1]))
    for m in ordered:
        if m.current_health <= 0:
            continue
        # Start/end triggers only fire for the TURN player's minions.
        if m.owner != active_side:
            continue
        card_def = library.get_by_id(m.card_numeric_id)
        for eff_idx, effect in enumerate(card_def.effects):
            if effect.trigger != trigger:
                continue
            owner_idx = 0 if m.owner == PlayerSide.PLAYER_1 else 1
            pt = PendingTrigger(
                trigger_kind=trigger_kind,
                source_minion_id=m.instance_id,
                source_card_numeric_id=m.card_numeric_id,
                effect_idx=eff_idx,
                owner_idx=owner_idx,
                captured_position=m.position,
                target_pos=None,
            )
            if owner_idx == state.active_player_idx:
                turn_triggers.append(pt)
            else:
                other_triggers.append(pt)

    if not turn_triggers and not other_triggers:
        return state

    # Append to existing queues so a re-drain triggered by a cascading
    # phase transition doesn't clobber in-flight entries.
    state = replace(
        state,
        pending_trigger_queue_turn=state.pending_trigger_queue_turn + tuple(turn_triggers),
        pending_trigger_queue_other=state.pending_trigger_queue_other + tuple(other_triggers),
    )
    return state


def fire_start_of_turn_triggers(
    state: GameState,
    library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Enqueue ON_START_OF_TURN triggers into the priority queue + drain.

    Phase 14.7-05: Replaces the old inline (row, col) loop. Each matching
    (minion, effect) pair enqueues a PendingTrigger; then
    ``drain_pending_trigger_queue`` auto-resolves singletons or opens a
    modal picker for 2+ simultaneous triggers on the same owner's side.

    Each trigger resolution (auto or picked) opens its own REACT window
    tagged with ReactContext.AFTER_START_TRIGGER (spec §7.5 step 3). The
    window's closing leads back through resolve_react_stack's drain-
    recheck hook which re-calls drain_pending_trigger_queue if entries
    remain.

    Fizzle (14.7-06) is not yet implemented — captured_position preserves
    SELF_OWNER targeting even if the source minion has since moved/died.
    """
    assert_phase_contract(state, "trigger:on_start_of_turn")
    state = _enqueue_turn_phase_triggers(
        state, library, TriggerType.ON_START_OF_TURN, "start_of_turn",
    )
    if (
        not state.pending_trigger_queue_turn
        and not state.pending_trigger_queue_other
    ):
        return state
    return drain_pending_trigger_queue(
        state, library, event_collector=event_collector,
    )


def fire_end_of_turn_triggers(
    state: GameState,
    library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Enqueue ON_END_OF_TURN triggers into the priority queue + drain.

    Same machinery as fire_start_of_turn_triggers, but tags entries as
    trigger_kind="end_of_turn" which drives ReactContext.BEFORE_END_OF_TURN
    on the per-resolution react window.
    """
    assert_phase_contract(state, "trigger:on_end_of_turn")
    state = _enqueue_turn_phase_triggers(
        state, library, TriggerType.ON_END_OF_TURN, "end_of_turn",
    )
    if (
        not state.pending_trigger_queue_turn
        and not state.pending_trigger_queue_other
    ):
        return state
    return drain_pending_trigger_queue(
        state, library, event_collector=event_collector,
    )


# ---------------------------------------------------------------------------
# Phase 14.7-05: priority-queue drain + per-trigger react window opener
# ---------------------------------------------------------------------------


def drain_pending_trigger_queue(
    state: GameState,
    library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Drain the pending-trigger queues in priority order.

    Spec §7.2: the turn player's queue drains fully before the other
    player's queue begins. Within each queue:
      - >=2 entries → set pending_trigger_picker_idx so the UI opens the
        modal card-picker (client reuses renderDeckBuilderCard). Control
        returns to the caller; the picker's owner must submit a
        TRIGGER_PICK or DECLINE_TRIGGER action next.
      - exactly 1 entry → auto-resolve via
        _resolve_trigger_and_open_react_window (no modal needed).
      - 0 entries → advance to the other queue (if any) or exit.

    Each auto-resolve or picked-resolve opens its OWN react window per
    spec §7.5 step 3. The window's close re-enters this function via
    resolve_react_stack's drain-recheck hook (see Step 3 of Task 2).

    If the picker modal is already open (picker_idx set), this function
    is a no-op — we wait for TRIGGER_PICK / DECLINE_TRIGGER to make
    progress.
    """
    assert_phase_contract(state, "system:drain_triggers")
    # If picker modal is already open, do not auto-advance — wait for
    # TRIGGER_PICK / DECLINE_TRIGGER from the picker owner.
    if state.pending_trigger_picker_idx is not None:
        return state

    # Short-circuit if the game has ended (e.g. a trigger killed a player).
    if state.is_game_over:
        return state

    turn_q = state.pending_trigger_queue_turn
    other_q = state.pending_trigger_queue_other
    active_idx = state.active_player_idx
    other_idx = 1 - active_idx

    # Turn queue drains first (priority).
    if len(turn_q) >= 2:
        # Phase 14.8-03a: trigger picker modal opens — gates eventQueue.
        new_state = replace(state, pending_trigger_picker_idx=active_idx)
        if event_collector is not None:
            event_collector.collect(
                EVT_PENDING_MODAL_OPENED,
                "system:drain_triggers",
                {
                    "modal_kind": "trigger_pick",
                    "owner_idx": active_idx,
                    "options_count": len(turn_q),
                },
                requires_decision=True,
            )
        return new_state
    if len(turn_q) == 1:
        return _resolve_trigger_and_open_react_window(
            state, turn_q[0], is_turn_queue=True, library=library,
            event_collector=event_collector,
        )
    if len(other_q) >= 2:
        new_state = replace(state, pending_trigger_picker_idx=other_idx)
        if event_collector is not None:
            event_collector.collect(
                EVT_PENDING_MODAL_OPENED,
                "system:drain_triggers",
                {
                    "modal_kind": "trigger_pick",
                    "owner_idx": other_idx,
                    "options_count": len(other_q),
                },
                requires_decision=True,
            )
        return new_state
    if len(other_q) == 1:
        return _resolve_trigger_and_open_react_window(
            state, other_q[0], is_turn_queue=False, library=library,
            event_collector=event_collector,
        )

    # Both queues empty — drain complete, nothing to do.
    return state


def _resolve_trigger_and_open_react_window(
    state: GameState,
    trigger: PendingTrigger,
    is_turn_queue: bool,
    library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Resolve one queued trigger and open a REACT window for it (spec §7.5 step 3).

    Steps:
      1. Look up the card_def + effect by (source_card_numeric_id, effect_idx).
      2. For ``trigger_kind == "on_death"`` effects that need a click-target
         modal (DESTROY/SINGLE_TARGET, PROMOTE with 2+ candidates), pop the
         trigger and hand off to the existing ``pending_death_target`` modal
         machinery. The DEATH_TARGET_PICK handler in action_resolver will
         resume the drain (chain-reaction cleanup + AFTER_DEATH_EFFECT
         react window) after the owner picks.
      3. Otherwise resolve the effect via resolve_effect, using
         captured_position as the source (SELF_OWNER / position-relative
         targeting works even if the source minion has moved/died — true
         fizzle in 14.7-06).
      4. Clean up any newly-dead minions and check game over.
      5. Pop the resolved trigger from the appropriate queue.
      6. Open a REACT window tagged with the trigger_kind's ReactContext.
         The window's react_return_phase is preserved from the prior
         state.react_return_phase so the phase-dispatch block in
         resolve_react_stack returns to the correct phase when both
         queues finally empty.

    Returns state with phase=REACT (or game-over / unchanged if the
    effect ended the game, or pending_death_target set if a click-target
    modal is open).
    """
    # Phase 14.8-01/02: derive contract_source from the trigger_kind string.
    # PendingTrigger.trigger_kind uses short labels ("start_of_turn",
    # "end_of_turn") that map to the long-form TriggerType names used by
    # PHASE_CONTRACTS keys ("on_start_of_turn", "on_end_of_turn"). The
    # plan-01 short-form tag "trigger:end_of_turn" was a miss — corrected
    # in plan 14.8-02 via this lookup so the contract source matches the
    # PHASE_CONTRACTS key. on_death and on_summon_effect are already
    # long-form so they pass through unchanged.
    _TRIGGER_KIND_TO_SOURCE = {
        "start_of_turn": "trigger:on_start_of_turn",
        "end_of_turn": "trigger:on_end_of_turn",
        "on_death": "trigger:on_death",
        "on_summon_effect": "trigger:on_summon",
    }
    _trigger_source = _TRIGGER_KIND_TO_SOURCE.get(
        trigger.trigger_kind, f"trigger:{trigger.trigger_kind}"
    )
    assert_phase_contract(state, _trigger_source)
    from grid_tactics.effect_resolver import (
        resolve_effect,
        _death_effect_needs_modal,
        _count_promote_candidates,
    )
    from grid_tactics import action_resolver as _ar
    from grid_tactics.action_resolver import _cleanup_dead_minions, _check_game_over
    from grid_tactics.game_state import PendingDeathTarget

    card_def = library.get_by_id(trigger.source_card_numeric_id)
    if trigger.effect_idx < 0 or trigger.effect_idx >= len(card_def.effects):
        # Defensive: effect index out of range — drop the trigger silently.
        if is_turn_queue:
            state = replace(
                state,
                pending_trigger_queue_turn=state.pending_trigger_queue_turn[1:],
            )
        else:
            state = replace(
                state,
                pending_trigger_queue_other=state.pending_trigger_queue_other[1:],
            )
        return drain_pending_trigger_queue(state, library)

    effect = card_def.effects[trigger.effect_idx]
    caster_owner = PlayerSide.PLAYER_1 if trigger.owner_idx == 0 else PlayerSide.PLAYER_2

    # Phase 14.7-05b: Death-effect click-target modal dispatch.
    # DESTROY/SINGLE_TARGET (Lasercannon) and PROMOTE/SELF_OWNER with 2+
    # candidates (Giant Rat when multiple Rats exist) need the owner to
    # pick a target. Pop the trigger, open the modal, and return — the
    # DEATH_TARGET_PICK handler in action_resolver resumes the flow.
    if (
        trigger.trigger_kind == "on_death"
        and trigger.source_minion_id is not None
    ):
        # DESTROY/SINGLE_TARGET: open modal if any enemy minion is alive.
        if _death_effect_needs_modal(effect):
            has_target = any(
                m.owner != caster_owner and m.is_alive for m in state.minions
            )
            if has_target:
                target = PendingDeathTarget(
                    card_numeric_id=trigger.source_card_numeric_id,
                    owner_idx=trigger.owner_idx,
                    dying_instance_id=trigger.source_minion_id,
                    effect_idx=trigger.effect_idx,
                    filter="enemy_minion",
                )
                # Pop the trigger BEFORE setting the modal so the resume
                # path doesn't double-process this entry.
                if is_turn_queue:
                    state = replace(
                        state,
                        pending_trigger_queue_turn=state.pending_trigger_queue_turn[1:],
                        pending_death_target=target,
                    )
                else:
                    state = replace(
                        state,
                        pending_trigger_queue_other=state.pending_trigger_queue_other[1:],
                        pending_death_target=target,
                    )
                return state
            # No valid target → silent no-op, fall through to pop + open
            # the AFTER_DEATH_EFFECT react window (no effect resolved).
            if is_turn_queue:
                state = replace(
                    state,
                    pending_trigger_queue_turn=state.pending_trigger_queue_turn[1:],
                )
            else:
                state = replace(
                    state,
                    pending_trigger_queue_other=state.pending_trigger_queue_other[1:],
                )
            rc = ReactContext.AFTER_DEATH_EFFECT
            default_return = state.react_return_phase or TurnPhase.ACTION
            new_return_phase = state.react_return_phase or default_return
            # Phase 14.8-05: last_trigger_blip field DELETED — the blip
            # payload now flows exclusively via EVT_TRIGGER_BLIP in the
            # event stream (plan 14.8-03a). Emit one for the dead-air
            # AFTER_DEATH_EFFECT window so the client still gets a blip
            # cue even though no effect resolved.
            if event_collector is not None:
                event_collector.collect(
                    EVT_TRIGGER_BLIP,
                    _trigger_source,
                    _build_trigger_blip_payload(trigger, effect),
                )
            return replace(
                state,
                phase=TurnPhase.REACT,
                react_player_idx=1 - state.active_player_idx,
                react_context=rc,
                react_return_phase=new_return_phase,
                react_stack=(),
            )

        # PROMOTE with 2+ candidates also opens the modal.
        if effect.effect_type == EffectType.PROMOTE:
            candidate_count = _count_promote_candidates(
                state,
                trigger.source_card_numeric_id,
                caster_owner,
                library,
            )
            if candidate_count >= 2:
                target = PendingDeathTarget(
                    card_numeric_id=trigger.source_card_numeric_id,
                    owner_idx=trigger.owner_idx,
                    dying_instance_id=trigger.source_minion_id,
                    effect_idx=trigger.effect_idx,
                    filter="friendly_promote",
                )
                if is_turn_queue:
                    state = replace(
                        state,
                        pending_trigger_queue_turn=state.pending_trigger_queue_turn[1:],
                        pending_death_target=target,
                    )
                else:
                    state = replace(
                        state,
                        pending_trigger_queue_other=state.pending_trigger_queue_other[1:],
                        pending_death_target=target,
                    )
                return state
            # 0 or 1 candidate → auto-resolve inline.
            from grid_tactics.effect_resolver import _apply_promote_on_death
            state = _apply_promote_on_death(
                state,
                trigger.source_card_numeric_id,
                caster_owner,
                library,
            )
            # Enqueue-only cleanup: chain-reaction deaths from the
            # promote (rare) enqueue without starting a nested drain.
            # The drain-recheck hook in resolve_react_stack continues
            # the drain after the window we open below closes.
            _ar._cleanup_skip_drain = True
            try:
                state = _cleanup_dead_minions(state, library)
            finally:
                _ar._cleanup_skip_drain = False
            state = _check_game_over(state)
            if state.is_game_over:
                return state
            # If chain-cleanup opened a picker modal or death-target
            # modal, defer — the flow will resume after those clear.
            if (
                state.pending_death_target is not None
                or state.pending_trigger_picker_idx is not None
            ):
                # Pop our entry before deferring.
                if is_turn_queue:
                    state = replace(
                        state,
                        pending_trigger_queue_turn=state.pending_trigger_queue_turn[1:],
                    )
                else:
                    state = replace(
                        state,
                        pending_trigger_queue_other=state.pending_trigger_queue_other[1:],
                    )
                return state
            # Pop + open AFTER_DEATH_EFFECT react window.
            if is_turn_queue:
                state = replace(
                    state,
                    pending_trigger_queue_turn=state.pending_trigger_queue_turn[1:],
                )
            else:
                state = replace(
                    state,
                    pending_trigger_queue_other=state.pending_trigger_queue_other[1:],
                )
            rc = ReactContext.AFTER_DEATH_EFFECT
            default_return = state.react_return_phase or TurnPhase.ACTION
            new_return_phase = state.react_return_phase or default_return
            # Phase 14.8-05: last_trigger_blip field DELETED — emit the
            # PROMOTE auto-resolve blip via EVT_TRIGGER_BLIP instead.
            if event_collector is not None:
                event_collector.collect(
                    EVT_TRIGGER_BLIP,
                    _trigger_source,
                    _build_trigger_blip_payload(trigger, effect),
                )
            return replace(
                state,
                phase=TurnPhase.REACT,
                react_player_idx=1 - state.active_player_idx,
                react_context=rc,
                react_return_phase=new_return_phase,
                react_stack=(),
            )

    # Phase 14.7-06: Fizzle check.
    # Pass source_minion_id through ONLY for trigger kinds where the source
    # is expected to still be alive at resolution time — start/end/on_summon.
    # For on_death triggers, the source IS dead by definition (that's why
    # the trigger fired); the fizzle gate for those kinds only validates
    # the TARGET (SINGLE_TARGET target_pos must still be a live minion).
    # Capture the pre-resolve state so the caller can detect a silent
    # fizzle (state identity unchanged) and skip the react-window open.
    if trigger.trigger_kind == "on_death":
        fizzle_source_id: Optional[int] = None
    else:
        fizzle_source_id = trigger.source_minion_id
    prev_state = state
    state = resolve_effect(
        state, effect, trigger.captured_position, caster_owner, library,
        trigger.target_pos,
        source_minion_id=fizzle_source_id,
        contract_source=_trigger_source,
        event_collector=event_collector,
    )
    fizzled = state is prev_state

    # On fizzle, skip the react-window open and just pop the resolved
    # trigger to advance the drain. No dead-air prompt for a no-op
    # effect (spec §7.3 / §7.5 step 3).
    if fizzled:
        # Phase 14.8-03a: emit EVT_FIZZLE so the client can optionally
        # show a puff or skip the visual entirely. contract_source is
        # the original trigger source.
        if event_collector is not None:
            event_collector.collect(
                EVT_FIZZLE,
                _trigger_source,
                {
                    "trigger_kind": trigger.trigger_kind,
                    "source_minion_id": trigger.source_minion_id,
                    "source_card_numeric_id": trigger.source_card_numeric_id,
                    "reason": "target_invalid_at_resolve_time",
                },
            )
        if is_turn_queue:
            state = replace(
                state,
                pending_trigger_queue_turn=state.pending_trigger_queue_turn[1:],
            )
        else:
            state = replace(
                state,
                pending_trigger_queue_other=state.pending_trigger_queue_other[1:],
            )
        # Continue the drain — next entry (if any) auto-resolves or opens
        # the picker modal.
        return drain_pending_trigger_queue(
            state, library, event_collector=event_collector,
        )

    # Enqueue-only cleanup: chain-reaction deaths from this resolution
    # enqueue PendingTriggers WITHOUT triggering a nested drain, so the
    # outer resolver pops its entry first. The drain-recheck hook in
    # resolve_react_stack takes over once the AFTER_DEATH_EFFECT window
    # we open below closes.
    _ar._cleanup_skip_drain = True
    try:
        state = _cleanup_dead_minions(state, library)
    finally:
        _ar._cleanup_skip_drain = False
    state = _check_game_over(state)
    if state.is_game_over:
        return state

    # Chain-cleanup may have opened its own modal / picker — defer.
    if (
        state.pending_death_target is not None
        or state.pending_trigger_picker_idx is not None
    ):
        # Pop our resolved entry before deferring so drain-recheck picks
        # up cleanly.
        if is_turn_queue:
            state = replace(
                state,
                pending_trigger_queue_turn=state.pending_trigger_queue_turn[1:],
            )
        else:
            state = replace(
                state,
                pending_trigger_queue_other=state.pending_trigger_queue_other[1:],
            )
        return state

    # Pop the resolved trigger from the appropriate queue.
    if is_turn_queue:
        state = replace(
            state,
            pending_trigger_queue_turn=state.pending_trigger_queue_turn[1:],
        )
    else:
        state = replace(
            state,
            pending_trigger_queue_other=state.pending_trigger_queue_other[1:],
        )

    # Pick the ReactContext tag for this trigger_kind.
    if trigger.trigger_kind == "start_of_turn":
        rc = ReactContext.AFTER_START_TRIGGER
        # If return_phase not already set by an outer caller, inherit
        # START_OF_TURN so the final phase-dispatch returns to ACTION.
        default_return = TurnPhase.START_OF_TURN
    elif trigger.trigger_kind == "end_of_turn":
        rc = ReactContext.BEFORE_END_OF_TURN
        default_return = TurnPhase.END_OF_TURN
    elif trigger.trigger_kind == "on_death":
        rc = ReactContext.AFTER_DEATH_EFFECT
        default_return = state.react_return_phase or TurnPhase.ACTION
    else:
        rc = ReactContext.AFTER_ACTION
        default_return = state.react_return_phase or TurnPhase.ACTION

    # Preserve an existing react_return_phase if one is already in flight
    # (e.g. we're nested inside an outer drain that originated from
    # START_OF_TURN). Otherwise use the trigger-kind default.
    new_return_phase = state.react_return_phase or default_return

    # Phase 14.8-05: trigger-blip animation payload flows exclusively
    # through EVT_TRIGGER_BLIP in the event stream — the legacy
    # last_trigger_blip field was deleted. Client consumes via the
    # playTriggerBlip slot handler (game.js) which drives the
    # source-tile pulse → center icon → optional target-tile pulse
    # animation via _fireTriggerBlipAnimation.
    blip_payload = _build_trigger_blip_payload(trigger, effect)

    # Emit EVT_TRIGGER_BLIP + EVT_REACT_WINDOW_OPENED so the client's
    # eventQueue gets both the animation cue and the spell-stage open
    # signal. The client's playReactWindowOpened (plan 14.8-05) consumes
    # the preceding trigger_blip's originator to slam the source minion's
    # card onto the spell stage LEFT slot.
    if event_collector is not None:
        event_collector.collect(
            EVT_TRIGGER_BLIP,
            _trigger_source,
            blip_payload,
        )
        event_collector.collect(
            EVT_REACT_WINDOW_OPENED,
            "system:enter_react",
            {
                "react_context": rc.name if rc else None,
                "react_player_idx": 1 - state.active_player_idx,
                "return_phase": new_return_phase.name if new_return_phase else None,
            },
        )

    return replace(
        state,
        phase=TurnPhase.REACT,
        react_player_idx=1 - state.active_player_idx,
        react_context=rc,
        react_return_phase=new_return_phase,
        # Ensure react_stack is empty for the new window (the drain pops
        # from the queues, not from the react stack).
        react_stack=(),
    )


def _build_trigger_blip_payload(trigger: PendingTrigger, effect) -> dict:
    """Construct the Phase 14.7-09 trigger-blip payload.

    Carries enough info for the client to animate source-tile pulse +
    center glyph + optional target-tile pulse. Schema must match the
    shape consumed by ``_fireTriggerBlipAnimation`` in game.js. Kept
    pure (no state access) so it's trivially testable and round-trips
    through ``GameState.to_dict`` / ``from_dict`` without loss.
    """
    effect_kind = getattr(effect.effect_type, "name", str(effect.effect_type)).lower()
    target_pos_list = (
        [int(trigger.target_pos[0]), int(trigger.target_pos[1])]
        if trigger.target_pos is not None else None
    )
    return {
        "trigger_kind": trigger.trigger_kind,
        "source_minion_id": trigger.source_minion_id,
        "source_position": [
            int(trigger.captured_position[0]),
            int(trigger.captured_position[1]),
        ],
        "target_position": target_pos_list,
        "effect_kind": effect_kind,
    }


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
    state: GameState,
    library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Advance to the next player's turn (outgoing player's end-of-turn tail).

    Phase 14.7-03: redistributed so that tick_status_effects (and the
    legacy _fire_passive_effects, now DELETED in Phase 14.8-05) now run
    INSIDE ``enter_start_of_turn`` for the newly-active player. This
    helper is now strictly the turn-flip tail:
    discard bookkeeping, flip active_player_idx / turn_number, regen,
    auto-draw. Phase is set to ACTION as a transient value — the chaining
    call in ``close_end_react_and_advance_turn`` (and ``enter_end_of_turn``
    shortcut path) will invoke ``enter_start_of_turn`` next which sets
    phase=START_OF_TURN and fires burn tick + Start triggers.

    Order:
      1. Flip ``discarded_this_turn`` -> ``discarded_last_turn`` for the
         outgoing player and clear this-turn for them.
      2. Flip ``active_player_idx`` and increment ``turn_number``.
      3. Mana regen for new active player (suppressed on turn 2).
      4. Auto-draw for new active player (if AUTO_DRAW_ENABLED and deck
         non-empty).

    Rule-1 bug fix captured here: the old inline resolve_react_stack tail
    did NOT flip ``discarded_this_turn`` -> ``discarded_last_turn`` for
    the outgoing player — only the pending_death_target resume path in
    action_resolver.py did. Centralizing here fixes that gap silently.
    """
    assert_phase_contract(state, "system:turn_flip")
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
    # (enter_start_of_turn will reset phase to START_OF_TURN when called.)
    new_active_idx = 1 - old_active_idx
    prev_turn = state.turn_number
    state = replace(
        state,
        phase=TurnPhase.ACTION,
        active_player_idx=new_active_idx,
        turn_number=state.turn_number + 1,
    )

    # Phase 14.8-03a: emit EVT_TURN_FLIPPED — drives the turn banner on
    # the client (replaces the synthesized turn-number diff in
    # applyStateFrame once plan 04a/b lands).
    if event_collector is not None:
        event_collector.collect(
            EVT_TURN_FLIPPED,
            "system:turn_flip",
            {
                "prev_turn": prev_turn,
                "new_turn": state.turn_number,
                "new_active_idx": new_active_idx,
            },
        )

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
    state: GameState,
    library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Enter START_OF_TURN phase for ``state.active_player_idx``.

    Phase 14.7-03: tick burns, fire ON_START_OF_TURN triggers, then
    either open a REACT window (if any Start triggers exist) or
    shortcut directly to ACTION. The "shortcut when no triggers"
    behavior preserves snappy dead-air turns and keeps pre-14.7 test
    expectations intact — opening an empty react window around no
    actual triggered effects would stall direct resolve_react_stack
    callers in unit tests.

    Policy: the REACT window opens only if the active player has at
    least one minion with an ON_START_OF_TURN effect. 14.7-07 will
    extend the opening condition to account for opponent react cards
    that match OPPONENT_START_OF_TURN even when no triggers fire.
    """
    assert_phase_contract(state, "system:enter_start_of_turn")
    prev_phase = state.phase
    # 1. Transition to START_OF_TURN phase (even if we shortcut later).
    state = replace(state, phase=TurnPhase.START_OF_TURN)
    if event_collector is not None:
        event_collector.collect(
            EVT_PHASE_CHANGED,
            "system:enter_start_of_turn",
            {
                "prev": prev_phase.name if prev_phase else None,
                "new": TurnPhase.START_OF_TURN.name,
            },
        )

    # 2. Tick burns for the active player's burning minions.
    state = tick_status_effects(state, library, event_collector=event_collector)
    if state.is_game_over:
        return state

    # 3. Fire ON_START_OF_TURN triggers (if any).
    had_triggers = _has_triggers_for(state, library, TriggerType.ON_START_OF_TURN)
    if had_triggers:
        state = fire_start_of_turn_triggers(
            state, library, event_collector=event_collector,
        )
        if state.is_game_over:
            return state

    # 4. Open react window if triggers fired; else shortcut to ACTION.
    if had_triggers:
        state = replace(
            state,
            phase=TurnPhase.REACT,
            react_player_idx=1 - state.active_player_idx,  # opponent reacts
            react_context=ReactContext.AFTER_START_TRIGGER,
            react_return_phase=TurnPhase.START_OF_TURN,
        )
        return state

    # No Start triggers → shortcut straight to ACTION.
    # Phase 14.8-03a per orchestrator decision #3: emit
    # EVT_REACT_WINDOW_OPENED + EVT_REACT_WINDOW_CLOSED on the shortcut
    # path too for symmetry. Client (plan 04a/b) treats zero-duration
    # shortcuts as instant.
    if event_collector is not None:
        event_collector.collect(
            EVT_REACT_WINDOW_OPENED,
            "system:enter_react",
            {
                "react_context": ReactContext.AFTER_START_TRIGGER.name,
                "react_player_idx": 1 - state.active_player_idx,
                "shortcut": True,
            },
            animation_duration_ms=0,
        )
        event_collector.collect(
            EVT_REACT_WINDOW_CLOSED,
            "system:close_react_window",
            {
                "return_phase": TurnPhase.ACTION.name,
                "shortcut": True,
            },
            animation_duration_ms=0,
        )
        event_collector.collect(
            EVT_PHASE_CHANGED,
            "system:enter_start_of_turn",
            {
                "prev": TurnPhase.START_OF_TURN.name,
                "new": TurnPhase.ACTION.name,
            },
        )
    return replace(state, phase=TurnPhase.ACTION)


def enter_end_of_turn(
    state: GameState,
    library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Enter END_OF_TURN phase for ``state.active_player_idx``.

    Phase 14.7-03: fire ON_END_OF_TURN triggers, then either open a
    REACT window (if any End triggers fired) or shortcut directly to
    ``close_end_react_and_advance_turn`` which flips the active player
    and enters the new player's START_OF_TURN.

    Policy: the REACT window opens only if the active player has at
    least one minion with an ON_END_OF_TURN effect. 14.7-07 will extend
    the opening condition to account for opponent react cards that
    match OPPONENT_END_OF_TURN even when no triggers fire.
    """
    assert_phase_contract(state, "system:enter_end_of_turn")
    prev_phase = state.phase
    # 1. Transition to END_OF_TURN phase (even if we shortcut later).
    state = replace(state, phase=TurnPhase.END_OF_TURN)
    if event_collector is not None:
        event_collector.collect(
            EVT_PHASE_CHANGED,
            "system:enter_end_of_turn",
            {
                "prev": prev_phase.name if prev_phase else None,
                "new": TurnPhase.END_OF_TURN.name,
            },
        )

    # 2. Fire ON_END_OF_TURN triggers (if any).
    had_triggers = _has_triggers_for(state, library, TriggerType.ON_END_OF_TURN)
    if had_triggers:
        state = fire_end_of_turn_triggers(
            state, library, event_collector=event_collector,
        )
        if state.is_game_over:
            return state

    # 3. Open react window if triggers fired; else shortcut to turn-advance.
    if had_triggers:
        state = replace(
            state,
            phase=TurnPhase.REACT,
            react_player_idx=1 - state.active_player_idx,  # opponent reacts
            react_context=ReactContext.BEFORE_END_OF_TURN,
            react_return_phase=TurnPhase.END_OF_TURN,
        )
        return state

    # No End triggers → advance turn directly.
    # Phase 14.8-03a per orchestrator decision #3: emit react_window_opened
    # + react_window_closed for symmetry on the shortcut path too.
    if event_collector is not None:
        event_collector.collect(
            EVT_REACT_WINDOW_OPENED,
            "system:enter_react",
            {
                "react_context": ReactContext.BEFORE_END_OF_TURN.name,
                "react_player_idx": 1 - state.active_player_idx,
                "shortcut": True,
            },
            animation_duration_ms=0,
        )
        event_collector.collect(
            EVT_REACT_WINDOW_CLOSED,
            "system:close_react_window",
            {
                "return_phase": TurnPhase.END_OF_TURN.name,
                "shortcut": True,
            },
            animation_duration_ms=0,
        )
    state = _close_end_of_turn_and_flip(
        state, library, event_collector=event_collector,
    )
    if state.is_game_over:
        return state
    return enter_start_of_turn(
        state, library, event_collector=event_collector,
    )


def close_start_react_and_enter_action(
    state: GameState,
    library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """After a START_OF_TURN react window PASS-PASSes, enter ACTION.

    Clears react bookkeeping and sets phase=ACTION. No turn flip — the
    turn player still owns their ACTION phase.
    """
    assert_phase_contract(state, "system:close_react_window")
    if event_collector is not None:
        event_collector.collect(
            EVT_REACT_WINDOW_CLOSED,
            "system:close_react_window",
            {"return_phase": TurnPhase.ACTION.name},
        )
        event_collector.collect(
            EVT_PHASE_CHANGED,
            "system:close_react_window",
            {"prev": state.phase.name if state.phase else None,
             "new": TurnPhase.ACTION.name},
        )
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
    state: GameState,
    library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """After an END_OF_TURN (or legacy after-action) react window PASS-PASSes, advance turn.

    Clears react bookkeeping, runs the end-of-turn tail for the current
    active player, and enters the NEW active player's START_OF_TURN.
    """
    assert_phase_contract(state, "system:close_react_window")
    if event_collector is not None:
        event_collector.collect(
            EVT_REACT_WINDOW_CLOSED,
            "system:close_react_window",
            {"return_phase": "turn_flip"},
        )
    state = replace(
        state,
        react_stack=(),
        react_player_idx=None,
        pending_action=None,
        react_context=None,
        react_return_phase=None,
    )
    state = _close_end_of_turn_and_flip(
        state, library, event_collector=event_collector,
    )
    if state.is_game_over:
        return state
    return enter_start_of_turn(
        state, library, event_collector=event_collector,
    )


def advance_to_next_turn(
    state: GameState, library: CardLibrary,
) -> GameState:
    """Test helper: drive PASS/auto-transitions until the next ACTION phase.

    Walks the post-action state machine (REACT → END_OF_TURN → flip →
    START_OF_TURN → ACTION) issuing PASS actions against open REACT
    windows and calling the transition helpers directly for START/END
    placeholders. Stops when phase=ACTION for the new active player (or
    the game ends).

    Used by unit tests that need a full turn cycle without going through
    events.py's server-side auto-PASS loop. Mirrors the safety cap the
    server uses (AUTO_ADVANCE_MAX=50) so a wedge raises instead of
    infinite-looping.
    """
    start_turn = state.turn_number
    safety = 0
    while (
        state.turn_number == start_turn
        and not state.is_game_over
    ):
        safety += 1
        if safety > 50:
            raise RuntimeError(
                "advance_to_next_turn safety exceeded (>50 iterations)"
            )
        if state.phase == TurnPhase.REACT:
            state = handle_react_action(state, Action(action_type=ActionType.PASS), library)
        elif state.phase == TurnPhase.START_OF_TURN:
            state = enter_start_of_turn(state, library)
        elif state.phase == TurnPhase.END_OF_TURN:
            state = enter_end_of_turn(state, library)
        else:
            # ACTION phase reached without a turn flip → caller needs to
            # submit an action; there's nothing more we can drive here.
            return state
    return state


# ---------------------------------------------------------------------------
# Phase 14.7-04: Summon compound-window originator resolvers
# ---------------------------------------------------------------------------
#
# Minion summons open two sequential react windows (spec §4.2):
#
#   Window A (AFTER_SUMMON_DECLARATION):
#     Opens when _deploy_minion pushes a summon_declaration originator.
#     A NEGATE on this originator destroys the entire summon AND forfeits
#     the costs (mana/discard/destroy-ally) — harsh by design.
#
#   Window B (AFTER_SUMMON_EFFECT):
#     Opens by resolve_summon_declaration_originator AFTER the minion
#     lands, ONLY if the minion has ON_SUMMON effects. A NEGATE here
#     cancels the effects only — the minion stays on the board.
#
# A minion with NO ON_SUMMON effects opens only Window A (no dead-air
# Window B). Gargoyle Sorceress's two ON_SUMMON buffs resolve under a
# SINGLE Window B.
#
# Implementation uses the same originator-push pattern established in
# 14.7-01's magic_cast flow (no pending_sub_actions field — compound
# windows are implemented via stack-pushing originators).


def resolve_summon_declaration_originator(
    state: GameState,
    entry: ReactEntry,
    library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Window A resolved WITHOUT negate → land the minion on the board.

    Called from resolve_react_stack's LIFO loop when it encounters a
    summon_declaration originator that was not negated. The negation skip
    happens in the caller's ``negated_indices`` check.

    If the minion has any ON_SUMMON effects, push a summon_effect
    originator onto the stack and set the state to REACT /
    AFTER_SUMMON_EFFECT — the outer resolve_react_stack's early-return
    check detects this and hands control back to the caller so Window B
    opens naturally for the opponent. The old Window A entries have
    already been consumed by the LIFO loop at this point, so the stack
    is RESET (not appended) to contain only the new summon_effect entry.

    If the cell is no longer empty (rare edge case: another effect placed
    a minion there during the react chain), the summon fizzles silently.
    Proper spec §7 fizzle rule lands in 14.7-06.
    """
    # Phase 14.8-02 disposition (smoking-gun #1 from 14.8-01): Window A
    # resolves during REACT (the originator was pushed from action:play_card
    # and is now being drained from the react stack via LIFO). The
    # initiating action:play_card contract was already satisfied at push
    # time; the actual mutation here (landing the minion) is engine-driven
    # by the drain step, so it gets a SYSTEM source. Re-tagged from
    # action:play_card → system:resolve_summon_declaration to match the
    # new PHASE_CONTRACTS entry that allows REACT (the only legal phase
    # for a Window A resolution).
    assert_phase_contract(state, "system:resolve_summon_declaration")
    from grid_tactics.minion import MinionInstance

    card_def = library.get_by_id(entry.card_numeric_id)
    owner_side = state.players[entry.player_idx].side
    pos = entry.target_pos
    if pos is None:
        return state

    row, col = pos
    # Edge case: cell occupied mid-chain → summon fizzles silently (no
    # refund). Proper fizzle handling lands in 14.7-06.
    if state.board.get(row, col) is not None:
        return state

    minion = MinionInstance(
        instance_id=state.next_minion_id,
        card_numeric_id=entry.card_numeric_id,
        owner=owner_side,
        position=pos,
        current_health=card_def.health,
        from_deck=True,
    )
    new_board = state.board.place(row, col, minion.instance_id)
    state = replace(
        state,
        board=new_board,
        minions=state.minions + (minion,),
        next_minion_id=state.next_minion_id + 1,
    )

    # Phase 14.8-03a: emit EVT_MINION_SUMMONED — fired AFTER the minion
    # actually lands (post Window A negate window). Plan-04a's animation
    # path uses this for the deploy-from-hand → board-tile animation.
    if event_collector is not None:
        from grid_tactics.engine_events import EVT_MINION_SUMMONED
        event_collector.collect(
            EVT_MINION_SUMMONED,
            "system:resolve_summon_declaration",
            {
                "instance_id": minion.instance_id,
                "card_numeric_id": entry.card_numeric_id,
                "owner_idx": entry.player_idx,
                "position": list(pos),
            },
        )

    # Collect ON_SUMMON effects; if none, skip Window B entirely.
    on_summon_indices = [
        i for i, e in enumerate(card_def.effects)
        if e.trigger == TriggerType.ON_SUMMON
    ]
    if not on_summon_indices:
        return state

    # Build effect_payload for Window B. Summon: triggers don't take the
    # action's target_pos (they're minion-self triggers, so target_pos=None).
    effects_payload = tuple(
        (i, None, int(owner_side)) for i in on_summon_indices
    )
    effect_originator = ReactEntry(
        player_idx=entry.player_idx,
        card_index=-1,
        card_numeric_id=entry.card_numeric_id,
        target_pos=None,
        is_originator=True,
        origin_kind="summon_effect",
        source_minion_id=minion.instance_id,
        effect_payload=effects_payload,
    )
    # RESET stack (not append): the LIFO loop has already consumed the
    # Window A entries. Window B starts with a fresh single-entry stack.
    return replace(
        state,
        react_stack=(effect_originator,),
        phase=TurnPhase.REACT,
        react_player_idx=1 - state.active_player_idx,
        react_context=ReactContext.AFTER_SUMMON_EFFECT,
        react_return_phase=TurnPhase.ACTION,
    )


def resolve_summon_effect_originator(
    state: GameState,
    entry: ReactEntry,
    library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Window B resolved WITHOUT negate → fire the minion's ON_SUMMON effects.

    Same dispatch pattern as the magic_cast originator (14.7-01): TUTOR /
    REVIVE route through their pending-entry shims; all other effects
    dispatch through resolve_effect. Multiple ON_SUMMON effects (e.g.
    Gargoyle Sorceress's buff_attack + buff_health) resolve in-order under
    the one window.

    Source position for resolve_effect is the minion's current board
    position (so placement_condition / self_owner targeting works). If the
    source minion died between declaration and effect resolution (rare
    edge — e.g. an on-summon aura killed it) the effect still fires from
    a sentinel (0, 0) position. True fizzle logic lands in 14.7-06.
    """
    assert_phase_contract(state, "trigger:on_summon")
    from grid_tactics.effect_resolver import resolve_effect, _enter_pending_tutor
    from grid_tactics.action_resolver import _enter_pending_revive

    card_def = library.get_by_id(entry.card_numeric_id)
    caster_owner = state.players[entry.player_idx].side

    source_pos: tuple[int, int] = (0, 0)
    if entry.source_minion_id is not None:
        src = state.get_minion(entry.source_minion_id)
        if src is not None:
            source_pos = src.position

    for (effect_idx, _target_pos_raw, _caster_owner_int) in (entry.effect_payload or ()):
        if effect_idx < 0 or effect_idx >= len(card_def.effects):
            continue
        effect = card_def.effects[effect_idx]
        if effect.effect_type == EffectType.TUTOR:
            state = _enter_pending_tutor(
                state, card_def, caster_owner, library,
                amount=max(1, effect.amount or 1),
            )
        elif effect.effect_type == EffectType.REVIVE:
            state = _enter_pending_revive(state, card_def, caster_owner, library)
        else:
            # Phase 14.7-06: pass source_minion_id so fizzle gate validates
            # source liveness for ADJACENT / SELF_OWNER on_summon effects.
            # A mid-chain effect (e.g. negate counter-react) that killed
            # the just-landed minion should cause subsequent per-minion
            # ON_SUMMON effects to fizzle silently.
            state = resolve_effect(
                state, effect, source_pos, caster_owner, library, target_pos=None,
                source_minion_id=entry.source_minion_id,
                contract_source="trigger:on_summon",
                event_collector=event_collector,
            )
    return state


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def handle_react_action(
    state: GameState,
    action: Action,
    library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
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
        assert_phase_contract(state, "action:pass_react")
        return resolve_react_stack(
            state, library, event_collector=event_collector,
        )

    if action.action_type == ActionType.PLAY_REACT:
        assert_phase_contract(state, "action:play_react")
        return _play_react(
            state, action, library, event_collector=event_collector,
        )

    raise ValueError(
        f"Invalid action type {action.action_type.name} during REACT phase. "
        f"Only PASS and PLAY_REACT are allowed."
    )


def _play_react(
    state: GameState,
    action: Action,
    library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
) -> GameState:
    """Process a PLAY_REACT action: validate, spend mana, push to stack, switch player.

    Validates:
      - Card is react-eligible (CardType.REACT or is_multi_purpose)
      - Sufficient mana (mana_cost for React, react_mana_cost for multi-purpose)
      - Stack depth < MAX_REACT_STACK_DEPTH
    """
    assert_phase_contract(state, "action:play_react")
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
    prev_mana = player.current_mana
    new_player = player.spend_mana(mana_cost)
    new_player = new_player.discard_from_hand(card_numeric_id)
    new_players = _replace_player(state.players, react_idx, new_player)

    # Phase 14.8-03a: import event constants lazily so we don't bloat module
    # import time. The kwarg is opt-in so emission only fires for callers
    # that supplied an event_collector.
    if event_collector is not None:
        from grid_tactics.engine_events import (
            EVT_CARD_PLAYED, EVT_MANA_CHANGE,
        )
        event_collector.collect(
            EVT_CARD_PLAYED,
            "action:play_react",
            {
                "card_numeric_id": card_numeric_id,
                "card_index": action.card_index,
                "owner_idx": react_idx,
                "target_pos": list(action.target_pos) if action.target_pos else None,
                "is_react": True,
            },
        )
        if mana_cost > 0:
            event_collector.collect(
                EVT_MANA_CHANGE,
                "action:play_react",
                {
                    "player_idx": react_idx,
                    "prev": prev_mana,
                    "new": prev_mana - mana_cost,
                    "delta": -mana_cost,
                },
            )

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
    # Phase 14.8-05c: intentionally NO EVT_REACT_WINDOW_OPENED emit here.
    # A counter-react extends the SAME react window (the react_stack
    # grows but the window semantics are unchanged — there's still one
    # AFTER_ACTION window with one matching react_window_closed at the
    # end). Emitting a new opened event creates a phantom window that
    # never gets closed (only ONE close event fires when the stack
    # ultimately resolves LIFO). The client handles counter-react chain
    # extension in playCardPlayed (is_react=True branch) instead.


def resolve_react_stack(
    state: GameState,
    library: CardLibrary,
    *,
    event_collector: Optional[EventStream] = None,
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
    assert_phase_contract(state, "action:pass_react")
    from grid_tactics.effect_resolver import resolve_effect

    # Snapshot the pre-resolution stack so the 14.7-04 compound-window
    # early-return check can detect when a helper (e.g.
    # resolve_summon_declaration_originator) replaced the stack with a
    # fresh Window B entry. If state.react_stack is unchanged after the
    # LIFO loop, resolution completed normally and we proceed to the
    # return_phase dispatch. If it was replaced with a new originator,
    # return early so the new react window opens for the opponent.
    _pre_resolution_stack = state.react_stack

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
                        contract_source="trigger:on_play",
                    )
            continue  # originator handled; skip the card_type dispatch below

        # Phase 14.7-04: Summon compound windows — dispatch declaration
        # (Window A: land the minion + maybe open Window B) and effect
        # (Window B: fire ON_SUMMON effects).
        if entry.is_originator and entry.origin_kind == "summon_declaration":
            state = resolve_summon_declaration_originator(
                state, entry, library, event_collector=event_collector,
            )
            continue

        if entry.is_originator and entry.origin_kind == "summon_effect":
            state = resolve_summon_effect_originator(
                state, entry, library, event_collector=event_collector,
            )
            continue

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
                            contract_source="trigger:on_play",
                        )
            else:
                # Normal react -- resolve all ON_PLAY effects
                for effect in card_def.effects:
                    if effect.trigger == TriggerType.ON_PLAY:
                        state = resolve_effect(
                            state, effect, (0, 0), caster_owner, library,
                            entry.target_pos,
                            contract_source="trigger:on_play",
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
                        contract_source="trigger:on_play",
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
                    contract_source="trigger:on_play",
                )
            else:
                for effect in card_def.effects:
                    if effect.trigger == TriggerType.ON_PLAY:
                        state = resolve_effect(
                            state, effect, (0, 0), caster_owner, library,
                            entry.target_pos,
                            contract_source="trigger:on_play",
                        )

    # Clean up dead minions after react resolution.
    # Phase 14.7-05b: snapshot the state IDENTITY before cleanup so we
    # can detect whether cleanup+drain actually opened a NEW death-
    # trigger react window (a truly no-op cleanup returns the same
    # object, so identity-equality distinguishes "cleanup did nothing"
    # from "cleanup replaced state with a fresh death-trigger window").
    from grid_tactics.action_resolver import _cleanup_dead_minions, _check_game_over
    _pre_cleanup_state = state
    state = _cleanup_dead_minions(state, library, event_collector=event_collector)

    # Win/draw detection after react resolution (Phase 4)
    state = _check_game_over(state, event_collector=event_collector)
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

    # Phase 14.7-05b: If cleanup opened the trigger-picker modal (the
    # dying minion's owner has 2+ simultaneous on_death effects to
    # order), defer. The TRIGGER_PICK / DECLINE_TRIGGER handlers in
    # action_resolver resume the drain.
    if state.pending_trigger_picker_idx is not None:
        return state

    # Phase 14.7-05b: If cleanup mutated state into a FRESH
    # AFTER_DEATH_EFFECT react window (identity mismatch with pre-cleanup
    # state AND post-cleanup context is AFTER_DEATH_EFFECT), respect
    # it — don't fall through to the dispatch below which would advance
    # turn prematurely. The post-death react window's close re-enters
    # resolve_react_stack, where the drain-recheck hook continues the
    # queue drain.
    if (
        state is not _pre_cleanup_state
        and state.phase == TurnPhase.REACT
        and state.react_context == ReactContext.AFTER_DEATH_EFFECT
    ):
        return state

    # Phase 14.7-04: compound-window hand-off. If a summon_declaration
    # originator just landed a minion with ON_SUMMON effects, the helper
    # RESET the react stack to a fresh summon_effect originator and set
    # phase=REACT. Detect this by comparing against the pre-resolution
    # snapshot: a stack-identity change + at least one originator means a
    # new window is open for the opponent. Return state as-is so the new
    # window takes over — do NOT clear the stack or advance turn.
    if (
        state.react_stack is not _pre_resolution_stack
        and state.phase == TurnPhase.REACT
        and state.react_stack
        and any(getattr(e, "is_originator", False) for e in state.react_stack)
    ):
        return state

    # Phase 14.7-04: Pending-modal hand-off. When an originator (magic_cast
    # or summon_effect) fires a TUTOR or REVIVE effect during stack
    # resolution, the effect opens a pending modal (pending_tutor /
    # pending_revive) that the CASTER must resolve before the turn
    # advances. Legacy behavior (pre-14.7-01) entered these modals INSIDE
    # the action handler (before the react window opened) so they never
    # appeared during react-stack resolution. With deferred resolution,
    # they can. Close the react window but keep the turn in ACTION for
    # the modal owner — resolve_action's pending_tutor / pending_revive
    # gates will route TUTOR_SELECT / REVIVE_PLACE from the owner. After
    # the modal clears, the turn advances via that gate's resume logic.
    if (
        state.pending_tutor_player_idx is not None
        or state.pending_revive_player_idx is not None
    ):
        return replace(
            state,
            phase=TurnPhase.ACTION,
            react_stack=(),
            react_player_idx=None,
            pending_action=None,
            react_context=None,
            react_return_phase=None,
        )

    # Phase 14.7-05: Drain-recheck.
    #
    # If a trigger resolution left entries in the pending_trigger queues
    # (because we're mid-way through a multi-trigger drain), re-enter the
    # drain BEFORE the return_phase dispatch flips the active player or
    # advances phase. This is the critical ordering constraint captured
    # in the plan's "Warning 8" fix:
    #
    #   LIFO loop runs → cleanup → is_game_over → DRAIN-RECHECK (here) →
    #   return_phase dispatch (next block)
    #
    # Without the recheck, the dispatch could close the react window for
    # trigger #1 and immediately advance to END_OF_TURN, leaving trigger
    # #2 stranded in pending_trigger_queue_turn until the NEXT time the
    # queue is touched — a silent correctness bug. The
    # test_two_triggers_second_fires_after_first regression test in
    # tests/test_react_stack.py asserts this ordering.
    if (
        state.pending_trigger_queue_turn
        or state.pending_trigger_queue_other
    ):
        # Clear react bookkeeping from the closing window; the drain will
        # open a NEW window (with its own context) for the next trigger.
        state = replace(
            state,
            react_stack=(),
            react_player_idx=None,
            pending_action=None,
            react_context=None,
            # react_return_phase is preserved — the final-drain exit needs
            # to know where to transition when both queues finally empty.
        )
        return drain_pending_trigger_queue(
            state, library, event_collector=event_collector,
        )

    # Phase 14.7-02: Dispatch on ``react_return_phase`` — where did we
    # come from? Pre-14.7 callers didn't set this field so it's None,
    # which we treat as the legacy after-action path (return ACTION ->
    # enter END_OF_TURN).
    return_phase = state.react_return_phase or TurnPhase.ACTION

    if return_phase == TurnPhase.ACTION:
        # Phase 14.7-08: If the closing react window was the POST-MOVE
        # window (i.e. pending_post_move_attacker_id is still set), return
        # to ACTION instead of advancing to END_OF_TURN. The melee caster
        # still owes us their ATTACK or DECLINE_POST_MOVE_ATTACK sub-action
        # — per spec v2 §4.1 the melee chain has TWO independent react
        # windows, and this is the gap between them. Clear the react
        # bookkeeping for the closing window but keep pending intact.
        if state.pending_post_move_attacker_id is not None:
            return replace(
                state,
                phase=TurnPhase.ACTION,
                react_stack=(),
                react_player_idx=None,
                pending_action=None,
                react_context=None,
                react_return_phase=None,
            )

        # Phase 14.7-03: after-action react window closed → enter
        # END_OF_TURN (fires End triggers + opens end react window if any
        # End triggers exist; otherwise shortcuts to turn-advance). This
        # replaces the pre-14.7-03 direct call to
        # close_end_react_and_advance_turn. For plans with no End
        # triggers (the majority today) enter_end_of_turn shortcuts so
        # behavior is byte-identical to the old flow.
        # First, clear the react bookkeeping for the closing window.
        if event_collector is not None:
            event_collector.collect(
                EVT_REACT_WINDOW_CLOSED,
                "system:close_react_window",
                {"return_phase": "end_of_turn_transition"},
            )
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
    elif return_phase == TurnPhase.START_OF_TURN:
        # 14.7-03: after a start-of-turn react window, enter ACTION.
        return close_start_react_and_enter_action(
            state, library, event_collector=event_collector,
        )
    elif return_phase == TurnPhase.END_OF_TURN:
        # 14.7-03: after an end-of-turn react window, advance turn.
        return close_end_react_and_advance_turn(
            state, library, event_collector=event_collector,
        )
    else:
        # Shouldn't happen — default to turn advance for safety.
        return close_end_react_and_advance_turn(
            state, library, event_collector=event_collector,
        )
