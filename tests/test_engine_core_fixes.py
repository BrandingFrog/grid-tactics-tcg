"""Regression tests for the Phase 14.8 engine-core bug sweep.

Covers (one test class per confirmed finding):
  1. Drain-exhaustion wedge: a react-window close whose trigger drain
     exhausts (last trigger fizzles) must dispatch react_return_phase
     instead of stranding the game in phase=REACT / react_player_idx=None.
  2. React stack is cleared when resolution is interrupted by a death
     modal — consumed entries must NOT re-resolve (double effects).
  3. The turn-phase entry helper respects react windows / modals opened
     by the burn tick and the turn flow is preserved. (2026-07: the
     burn tick moved from enter_start_of_turn to the Decay phase —
     enter_end_of_turn — so these tests exercise it at its new home.)
  4. DECLINE_TRIGGER during an ACTION-phase death drain opens the
     deferred after-action react window (no free second action).
  5. event_collector is threaded through decline-post-move-attack and
     trigger-pick/decline paths.
  6. Feed the Shadow's destroy-ally cost runs the standard death
     pipeline (ON_DEATH triggers fire, EVT_MINION_DIED emitted).
  7. Rathopper LEAP: enumerator and resolver agree — one enemy blocker
     max, never over allies, never over unverified tiles.
  8. Tree Wyrm's react tutors (TUTOR react_effect dispatches through
     the pending-tutor shim instead of silently no-oping).
"""

from pathlib import Path

import pytest

from grid_tactics.actions import (
    Action,
    move_action,
    pass_action,
    play_react_action,
)
from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.engine_events import (
    EVT_MINION_DIED,
    EVT_PHASE_CHANGED,
    EVT_REACT_WINDOW_OPENED,
    EventStream,
)
from grid_tactics.enums import (
    ActionType,
    PlayerSide,
    ReactContext,
    TurnPhase,
)
from grid_tactics.game_state import GameState, PendingTrigger
from grid_tactics.legal_actions import legal_actions
from grid_tactics.minion import MinionInstance
from grid_tactics.player import Player
from grid_tactics.react_stack import (
    ReactEntry,
    enter_end_of_turn,
    enter_start_of_turn,
    handle_react_action,
)
from grid_tactics.action_resolver import resolve_action
from grid_tactics.types import STARTING_HP


@pytest.fixture(scope="module")
def library():
    return CardLibrary.from_directory(Path("data/cards"))


def _player(side, hand=(), deck=(), grave=(), mana=5):
    return Player(
        side=side,
        hp=STARTING_HP,
        current_mana=mana,
        max_mana=max(mana, 5),
        hand=tuple(hand),
        deck=tuple(deck),
        grave=tuple(grave),
    )


def _state_with_minions(minions, players, **kwargs):
    """Build a GameState with the given minions placed on the board."""
    board = Board.empty()
    for m in minions:
        board = board.place(m.position[0], m.position[1], m.instance_id)
    defaults = dict(
        board=board,
        players=players,
        active_player_idx=0,
        phase=TurnPhase.ACTION,
        turn_number=5,
        seed=1,
        minions=tuple(minions),
        next_minion_id=max((m.instance_id for m in minions), default=0) + 1,
    )
    defaults.update(kwargs)
    return GameState(**defaults)


def _drain_to_next_action_phase(state, library, cap=12):
    """PASS through react windows until an ACTION phase is reached."""
    for _ in range(cap):
        if state.is_game_over or state.phase == TurnPhase.ACTION:
            return state
        if state.phase == TurnPhase.REACT:
            state = resolve_action(state, pass_action(), library)
        else:
            from grid_tactics.react_stack import (
                enter_end_of_turn as _eeot,
                enter_start_of_turn as _esot,
            )
            if state.phase == TurnPhase.START_OF_TURN:
                state = _esot(state, library)
            else:
                state = _eeot(state, library)
    raise AssertionError("did not reach ACTION phase within cap")


# ---------------------------------------------------------------------------
# Finding 1: drain-exhaustion wedge (phase=REACT, react_player_idx=None)
# ---------------------------------------------------------------------------


class TestDrainExhaustionWedge:
    def test_fizzling_final_trigger_after_react_pass_does_not_wedge(self, library):
        """A queued end-of-turn trigger whose source minion is dead fizzles
        during the drain-recheck after a BEFORE_END_OF_TURN PASS. The game
        must dispatch react_return_phase (advance the turn) instead of
        wedging in phase=REACT with react_player_idx=None."""
        ember_id = library.get_numeric_id("emberplague_rat")
        p1 = _player(PlayerSide.PLAYER_1)
        p2 = _player(PlayerSide.PLAYER_2)
        fizzler = PendingTrigger(
            trigger_kind="end_of_turn",
            source_minion_id=999,  # does not exist → ADJACENT fizzle
            source_card_numeric_id=ember_id,
            effect_idx=0,
            owner_idx=0,
            captured_position=(2, 2),
            target_pos=None,
        )
        state = _state_with_minions(
            [],
            (p1, p2),
            phase=TurnPhase.REACT,
            react_player_idx=1,
            react_context=ReactContext.BEFORE_END_OF_TURN,
            react_return_phase=TurnPhase.END_OF_TURN,
            react_stack=(),
            pending_trigger_queue_turn=(fizzler,),
        )

        result = handle_react_action(state, pass_action(), library)

        # No wedge: phase=REACT implies a live react player.
        assert not (
            result.phase == TurnPhase.REACT
            and result.react_player_idx is None
        ), "wedged: phase=REACT with react_player_idx=None"
        # legal_actions must not crash on the resulting state.
        legal_actions(result, library)
        # END_OF_TURN return phase → the turn actually advanced.
        assert result.active_player_idx == 1
        assert result.turn_number == state.turn_number + 1

    def test_decline_trigger_on_drain_recheck_picker_does_not_wedge(self, library):
        """DECLINE_TRIGGER when the picker was opened from the drain-recheck
        path (react bookkeeping already cleared, phase=REACT) must dispatch
        react_return_phase instead of returning the wedged state."""
        giant_id = library.get_numeric_id("giant_rat")
        p1 = _player(PlayerSide.PLAYER_1)
        p2 = _player(PlayerSide.PLAYER_2)
        trig = PendingTrigger(
            trigger_kind="on_death",
            source_minion_id=50,
            source_card_numeric_id=giant_id,
            effect_idx=0,
            owner_idx=0,
            captured_position=(1, 1),
            target_pos=None,
        )
        # Wedge-shaped state: drain-recheck tore down the window
        # (react_player_idx=None) and opened the picker for two triggers.
        state = _state_with_minions(
            [],
            (p1, p2),
            phase=TurnPhase.REACT,
            react_player_idx=None,
            react_return_phase=TurnPhase.END_OF_TURN,
            react_stack=(),
            pending_trigger_queue_turn=(trig, trig),
            pending_trigger_picker_idx=0,
        )

        result = resolve_action(
            state, Action(action_type=ActionType.DECLINE_TRIGGER), library,
        )

        assert not (
            result.phase == TurnPhase.REACT
            and result.react_player_idx is None
        ), "wedged: phase=REACT with react_player_idx=None"
        legal_actions(result, library)
        # END_OF_TURN return phase → turn advanced.
        assert result.active_player_idx == 1


# ---------------------------------------------------------------------------
# Finding 2: consumed react stack cleared before death-modal interrupt
# ---------------------------------------------------------------------------


class TestConsumedStackClearedOnDeathModal:
    def _build_barrage_state(self, library):
        barrage_id = library.get_numeric_id("dark_matter_barrage")
        laser_id = library.get_numeric_id("rgb_lasercannon")
        wyrm_id = library.get_numeric_id("tree_wyrm")
        rat_id = library.get_numeric_id("rat")

        p1 = _player(PlayerSide.PLAYER_1)
        p2 = _player(PlayerSide.PLAYER_2)

        # P1's rat — the eventual death-modal target. NOT at (0,0) (the
        # magic caster sentinel cell).
        p1_rat = MinionInstance(
            instance_id=1, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_1, position=(1, 1), current_health=5,
        )
        # P2's Lasercannon dies to the 5-damage barrage.
        laser = MinionInstance(
            instance_id=2, card_numeric_id=laser_id,
            owner=PlayerSide.PLAYER_2, position=(3, 2), current_health=5,
        )
        # P2's Tree Wyrm survives — the double-resolution detector.
        wyrm = MinionInstance(
            instance_id=3, card_numeric_id=wyrm_id,
            owner=PlayerSide.PLAYER_2, position=(3, 3), current_health=33,
        )
        originator = ReactEntry(
            player_idx=0, card_index=-1, card_numeric_id=barrage_id,
            is_originator=True, origin_kind="magic_cast",
            effect_payload=((0, None, int(PlayerSide.PLAYER_1)),),
        )
        return _state_with_minions(
            [p1_rat, laser, wyrm],
            (p1, p2),
            phase=TurnPhase.REACT,
            react_player_idx=1,
            react_context=ReactContext.AFTER_ACTION,
            react_return_phase=TurnPhase.ACTION,
            react_stack=(originator,),
        )

    def test_stack_cleared_when_death_modal_interrupts(self, library):
        state = self._build_barrage_state(library)
        result = handle_react_action(state, pass_action(), library)

        # The barrage killed the Lasercannon → its DESTROY on_death needs
        # a target modal, interrupting resolution.
        assert result.pending_death_target is not None
        # THE FIX: the consumed originator must be gone from the stack.
        assert result.react_stack == ()

    def test_no_double_resolution_after_death_target_pick(self, library):
        state = self._build_barrage_state(library)
        state = handle_react_action(state, pass_action(), library)
        assert state.pending_death_target is not None

        wyrm = next(m for m in state.minions if m.instance_id == 3)
        assert wyrm.current_health == 28  # 33 - 5, barrage applied ONCE

        # P2 (Lasercannon owner) destroys P1's rat via the modal.
        state = resolve_action(
            state,
            Action(action_type=ActionType.DEATH_TARGET_PICK, target_pos=(1, 1)),
            library,
        )
        # Drain the remaining react windows until the next ACTION phase.
        state = _drain_to_next_action_phase(state, library)

        wyrm = next(
            (m for m in state.minions if m.instance_id == 3), None,
        )
        assert wyrm is not None, "surviving wyrm was killed by a re-resolve"
        assert wyrm.current_health == 28, (
            "barrage payload re-resolved after the death modal — "
            f"wyrm at {wyrm.current_health}, expected 28"
        )


# ---------------------------------------------------------------------------
# Finding 3: burn-tick interrupts (RELOCATED 2026-07: the burn tick moved
# from enter_start_of_turn to the Decay phase — enter_end_of_turn — per
# the turn-structure redesign. The interrupt machinery under test is the
# same; it now guards the end-of-turn tick.)
# ---------------------------------------------------------------------------


class TestBurnTickInterruptsDecayPhase:
    def test_burn_death_react_window_not_clobbered_and_turn_advances(self, library):
        """Burning Giant Rat dies in its owner's Decay phase → its promote
        auto-resolves and opens an AFTER_DEATH_EFFECT react window that
        enter_end_of_turn must NOT clobber; the window's close must
        advance the turn (react_return_phase=END_OF_TURN), never hand
        the owner a free second action."""
        giant_id = library.get_numeric_id("giant_rat")
        rat_id = library.get_numeric_id("rat")
        p1 = _player(PlayerSide.PLAYER_1)
        p2 = _player(PlayerSide.PLAYER_2)

        giant = MinionInstance(
            instance_id=1, card_numeric_id=giant_id,
            owner=PlayerSide.PLAYER_2, position=(3, 2),
            current_health=3, is_burning=True,
        )
        promote_fodder = MinionInstance(
            instance_id=2, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_2, position=(4, 1), current_health=5,
        )
        state = _state_with_minions(
            [giant, promote_fodder],
            (p1, p2),
            active_player_idx=1,
            phase=TurnPhase.ACTION,  # transient pre-end value
        )
        start_turn = state.turn_number

        state = enter_end_of_turn(state, library)

        # The AFTER_DEATH_EFFECT react window must survive.
        assert state.phase == TurnPhase.REACT
        assert state.react_player_idx == 0
        assert state.react_context == ReactContext.AFTER_DEATH_EFFECT
        # And its close must route through the turn advance (END_OF_TURN),
        # never back to the owner's ACTION (free second action).
        assert state.react_return_phase == TurnPhase.END_OF_TURN
        # Promote resolved: the fodder rat became a Giant Rat.
        promoted = next(m for m in state.minions if m.instance_id != 1)
        assert promoted.card_numeric_id == giant_id

        # Opponent passes the window: the turn advances to them.
        state = resolve_action(state, pass_action(), library)
        state = _drain_to_next_action_phase(state, library)
        assert state.phase == TurnPhase.ACTION
        assert state.turn_number == start_turn + 1
        assert state.active_player_idx == 0, "turn did not advance after Decay"

    def test_burn_death_modal_hand_off_preserves_flow(self, library):
        """Burning RGB Lasercannon dies in the Decay phase → death-target
        modal must survive (hand-off in ACTION phase, not clobbered), and
        after the pick + react window the turn advances normally."""
        laser_id = library.get_numeric_id("rgb_lasercannon")
        rat_id = library.get_numeric_id("rat")
        p1 = _player(PlayerSide.PLAYER_1)
        p2 = _player(PlayerSide.PLAYER_2)

        laser = MinionInstance(
            instance_id=1, card_numeric_id=laser_id,
            owner=PlayerSide.PLAYER_2, position=(3, 2),
            current_health=5, is_burning=True,
        )
        enemy = MinionInstance(
            instance_id=2, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_1, position=(1, 1), current_health=5,
        )
        state = _state_with_minions(
            [laser, enemy],
            (p1, p2),
            active_player_idx=1,
            phase=TurnPhase.ACTION,
        )
        start_turn = state.turn_number

        state = enter_end_of_turn(state, library)

        assert state.pending_death_target is not None
        assert state.pending_death_target.owner_idx == 1
        assert state.react_return_phase == TurnPhase.END_OF_TURN

        # Owner picks the enemy rat; the AFTER_DEATH_EFFECT window opens.
        state = resolve_action(
            state,
            Action(action_type=ActionType.DEATH_TARGET_PICK, target_pos=(1, 1)),
            library,
        )
        assert state.phase == TurnPhase.REACT
        assert state.react_return_phase == TurnPhase.END_OF_TURN

        state = resolve_action(state, pass_action(), library)
        state = _drain_to_next_action_phase(state, library)
        assert state.phase == TurnPhase.ACTION
        assert state.turn_number == start_turn + 1
        assert state.active_player_idx == 0, "turn did not advance after Decay"

    def test_burn_death_interrupt_defers_but_does_not_skip_decay_triggers(
        self, library,
    ):
        """Turn-structure fixup 2026-07: a burn-tick death that opens a
        react window must DEFER the remaining Decay work, not skip it.
        After the death window closes, the owner's ON_END_OF_TURN
        triggers (here: Emberplague Rat's adjacent burn) still fire and
        the flow still ends with a normal turn advance — previously the
        interrupt skipped every Decay trigger for the turn."""
        giant_id = library.get_numeric_id("giant_rat")
        rat_id = library.get_numeric_id("rat")
        ember_id = library.get_numeric_id("emberplague_rat")
        p1 = _player(PlayerSide.PLAYER_1)
        p2 = _player(PlayerSide.PLAYER_2)

        burning_giant = MinionInstance(
            instance_id=1, card_numeric_id=giant_id,
            owner=PlayerSide.PLAYER_2, position=(3, 2),
            current_health=3, is_burning=True,
        )
        promote_fodder = MinionInstance(
            instance_id=2, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_2, position=(4, 1), current_health=5,
        )
        ember = MinionInstance(
            instance_id=3, card_numeric_id=ember_id,
            owner=PlayerSide.PLAYER_2, position=(0, 4), current_health=10,
        )
        enemy_adjacent = MinionInstance(
            instance_id=4, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_1, position=(1, 4), current_health=5,
        )
        state = _state_with_minions(
            [burning_giant, promote_fodder, ember, enemy_adjacent],
            (p1, p2),
            active_player_idx=1,
            phase=TurnPhase.ACTION,
        )
        start_turn = state.turn_number

        state = enter_end_of_turn(state, library)

        # Burn death interrupt: react window open, Decay work deferred.
        assert state.phase == TurnPhase.REACT
        assert state.react_context == ReactContext.AFTER_DEATH_EFFECT
        assert state.decay_resume_pending is True
        # The Decay trigger has NOT fired yet (deferred, not early).
        assert state.get_minion(4).is_burning is False

        # PASS through the death window: the Decay phase must RESUME
        # (Emberplague's ON_END_OF_TURN burn fires) BEFORE any turn flip.
        for _ in range(12):
            if state.phase != TurnPhase.REACT:
                break
            state = resolve_action(state, pass_action(), library)
            if state.get_minion(4) is not None and state.get_minion(4).is_burning:
                break
            assert state.turn_number == start_turn, (
                "turn flipped before the deferred Decay triggers fired"
            )
        assert state.get_minion(4).is_burning is True, (
            "Emberplague Rat's Decay trigger was skipped by the burn-death interrupt"
        )
        assert state.decay_resume_pending is False

        # And the flow still ends with a normal turn advance.
        state = _drain_to_next_action_phase(state, library)
        assert state.phase == TurnPhase.ACTION
        assert state.turn_number == start_turn + 1
        assert state.active_player_idx == 0, "turn did not advance after Decay"


# ---------------------------------------------------------------------------
# Finding 4: DECLINE_TRIGGER during ACTION-phase death drain
# ---------------------------------------------------------------------------


class TestDeclineTriggerOpensDeferredReactWindow:
    def test_decline_opens_after_action_window_no_free_action(self, library):
        giant_id = library.get_numeric_id("giant_rat")
        p1 = _player(PlayerSide.PLAYER_1)
        p2 = _player(PlayerSide.PLAYER_2)
        trig = PendingTrigger(
            trigger_kind="on_death",
            source_minion_id=60,
            source_card_numeric_id=giant_id,
            effect_idx=0,
            owner_idx=1,
            captured_position=(3, 3),
            target_pos=None,
        )
        # ACTION-phase death drain deferred the after-action react window
        # and opened the picker for the NON-active player's two triggers.
        state = _state_with_minions(
            [],
            (p1, p2),
            phase=TurnPhase.ACTION,
            active_player_idx=0,
            pending_action=pass_action(),
            pending_trigger_queue_other=(trig, trig),
            pending_trigger_picker_idx=1,
        )

        result = resolve_action(
            state, Action(action_type=ActionType.DECLINE_TRIGGER), library,
        )

        # The deferred after-action react window MUST open — previously
        # the state stayed in ACTION with no window, granting the active
        # player a second full action.
        assert result.phase == TurnPhase.REACT
        assert result.react_player_idx == 1
        assert result.react_context == ReactContext.AFTER_ACTION
        assert result.active_player_idx == 0
        assert result.pending_trigger_picker_idx is None
        assert result.pending_trigger_queue_other == ()


# ---------------------------------------------------------------------------
# Finding 5: event_collector threading
# ---------------------------------------------------------------------------


class TestEventCollectorThreading:
    def test_decline_post_move_attack_emits_engine_events(self, library):
        rat_id = library.get_numeric_id("rat")
        p1 = _player(PlayerSide.PLAYER_1)
        p2 = _player(PlayerSide.PLAYER_2)
        mover = MinionInstance(
            instance_id=1, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_1, position=(2, 2), current_health=5,
        )
        enemy = MinionInstance(
            instance_id=2, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_2, position=(3, 2), current_health=5,
        )
        state = _state_with_minions(
            [mover, enemy],
            (p1, p2),
            phase=TurnPhase.ACTION,
            pending_post_move_attacker_id=1,
        )

        stream = EventStream()
        result = resolve_action(
            state,
            Action(action_type=ActionType.DECLINE_POST_MOVE_ATTACK),
            library,
            event_collector=stream,
        )

        types = [ev.type for ev in stream.events]
        assert EVT_PHASE_CHANGED in types, (
            "enter_end_of_turn ran without the event collector — "
            "phase-change events dropped"
        )
        # 2026-07-08 timing audit (F6): the react player holds no playable
        # end-of-turn react, so the PASS-only Decay window is SHORTCUT —
        # the zero-duration open/close pair is still emitted (collector
        # threading intact) but the turn flips directly.
        assert EVT_REACT_WINDOW_OPENED in types
        opened = [
            ev for ev in stream.events if ev.type == EVT_REACT_WINDOW_OPENED
        ]
        assert any(ev.payload.get("shortcut") for ev in opened)
        assert result.phase == TurnPhase.ACTION
        assert result.active_player_idx == 1  # turn flipped

    def test_decline_trigger_emits_react_window_opened(self, library):
        giant_id = library.get_numeric_id("giant_rat")
        p1 = _player(PlayerSide.PLAYER_1)
        p2 = _player(PlayerSide.PLAYER_2)
        trig = PendingTrigger(
            trigger_kind="on_death",
            source_minion_id=60,
            source_card_numeric_id=giant_id,
            effect_idx=0,
            owner_idx=1,
            captured_position=(3, 3),
            target_pos=None,
        )
        state = _state_with_minions(
            [],
            (p1, p2),
            phase=TurnPhase.ACTION,
            active_player_idx=0,
            pending_action=pass_action(),
            pending_trigger_queue_other=(trig, trig),
            pending_trigger_picker_idx=1,
        )

        stream = EventStream()
        result = resolve_action(
            state,
            Action(action_type=ActionType.DECLINE_TRIGGER),
            library,
            event_collector=stream,
        )
        assert result.phase == TurnPhase.REACT
        types = [ev.type for ev in stream.events]
        assert EVT_REACT_WINDOW_OPENED in types


# ---------------------------------------------------------------------------
# Finding 6: Feed the Shadow destroy-ally cost runs the death pipeline
# ---------------------------------------------------------------------------


class TestFeedTheShadowDeathPipeline:
    def test_fed_giant_rat_fires_on_death_and_emits_minion_died(self, library):
        feed_id = library.get_numeric_id("feed_the_shadow")
        giant_id = library.get_numeric_id("giant_rat")
        rat_id = library.get_numeric_id("rat")

        p1 = _player(PlayerSide.PLAYER_1, hand=(feed_id,), mana=5)
        p2 = _player(PlayerSide.PLAYER_2)

        giant = MinionInstance(
            instance_id=1, card_numeric_id=giant_id,
            owner=PlayerSide.PLAYER_1, position=(1, 1), current_health=30,
        )
        fodder = MinionInstance(
            instance_id=2, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_1, position=(1, 3), current_health=5,
        )
        enemy = MinionInstance(
            instance_id=3, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_2, position=(3, 2), current_health=5,
        )
        state = _state_with_minions([giant, fodder, enemy], (p1, p2))

        # Use the enumerator's own action shape (destroyed_minion_id set).
        actions = [
            a for a in legal_actions(state, library)
            if a.action_type == ActionType.PLAY_CARD
            and a.card_index == 0
            and a.destroyed_minion_id == 1
            and a.target_pos == (3, 2)
        ]
        assert actions, "no legal Feed the Shadow action feeding the Giant Rat"

        stream = EventStream()
        state = resolve_action(state, actions[0], library, event_collector=stream)

        # The fed Giant Rat went through the standard death pipeline:
        died = [
            ev for ev in stream.events
            if ev.type == EVT_MINION_DIED and ev.payload.get("instance_id") == 1
        ]
        assert died, "EVT_MINION_DIED not emitted for the fed minion"
        assert all(m.instance_id != 1 for m in state.minions)
        assert giant_id in state.players[0].grave
        # Its ON_DEATH promote is queued for the drain-recheck.
        assert any(
            t.trigger_kind == "on_death" and t.source_minion_id == 1
            for t in state.pending_trigger_queue_turn
        ), "fed minion's ON_DEATH trigger was not enqueued"

        # Opponent passes the cast's react window → the spell resolves
        # (damage = fed attack 30 kills the enemy rat) and the queued
        # promote fires via the drain-recheck.
        state = resolve_action(state, pass_action(), library)
        promoted = next(
            (m for m in state.minions
             if m.owner == PlayerSide.PLAYER_1 and m.card_numeric_id == giant_id),
            None,
        )
        assert promoted is not None, (
            "Giant Rat's promote never fired for the Feed the Shadow cost"
        )

    def test_missing_destroyed_minion_id_raises(self, library):
        feed_id = library.get_numeric_id("feed_the_shadow")
        rat_id = library.get_numeric_id("rat")
        p1 = _player(PlayerSide.PLAYER_1, hand=(feed_id,), mana=5)
        p2 = _player(PlayerSide.PLAYER_2)
        ally = MinionInstance(
            instance_id=1, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_1, position=(1, 1), current_health=5,
        )
        enemy = MinionInstance(
            instance_id=2, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_2, position=(3, 2), current_health=5,
        )
        state = _state_with_minions([ally, enemy], (p1, p2))
        bad = Action(
            action_type=ActionType.PLAY_CARD,
            card_index=0,
            target_pos=(3, 2),
            destroyed_minion_id=None,
        )
        with pytest.raises(ValueError, match="destroy"):
            resolve_action(state, bad, library)


# ---------------------------------------------------------------------------
# Finding 7: LEAP enumerator/resolver contract
# ---------------------------------------------------------------------------


class TestLeapContract:
    def _hopper_state(self, library, enemy_rows, ally_rows=()):
        hopper_id = library.get_numeric_id("rathopper")
        rat_id = library.get_numeric_id("rat")
        p1 = _player(PlayerSide.PLAYER_1)
        p2 = _player(PlayerSide.PLAYER_2)
        minions = [
            MinionInstance(
                instance_id=1, card_numeric_id=hopper_id,
                owner=PlayerSide.PLAYER_1, position=(1, 2), current_health=13,
            )
        ]
        iid = 2
        for r in enemy_rows:
            minions.append(MinionInstance(
                instance_id=iid, card_numeric_id=rat_id,
                owner=PlayerSide.PLAYER_2, position=(r, 2), current_health=5,
            ))
            iid += 1
        for r in ally_rows:
            minions.append(MinionInstance(
                instance_id=iid, card_numeric_id=rat_id,
                owner=PlayerSide.PLAYER_1, position=(r, 2), current_health=5,
            ))
            iid += 1
        return _state_with_minions(minions, (p1, p2))

    def test_two_stacked_enemies_no_three_tile_leap(self, library):
        state = self._hopper_state(library, enemy_rows=(2, 3))
        moves = [
            a for a in legal_actions(state, library)
            if a.action_type == ActionType.MOVE and a.minion_id == 1
        ]
        # Rathopper (leap amount=1) cannot clear two enemies — no move.
        assert moves == [], f"illegal 2-enemy leap enumerated: {moves}"

    def test_single_enemy_leap_enumerated_and_resolves(self, library):
        state = self._hopper_state(library, enemy_rows=(2,))
        moves = [
            a for a in legal_actions(state, library)
            if a.action_type == ActionType.MOVE and a.minion_id == 1
        ]
        assert len(moves) == 1
        assert moves[0].position == (3, 2)
        # Enumerator/resolver contract: the enumerated move resolves.
        result = resolve_action(state, moves[0], library)
        hopper = next(m for m in result.minions if m.instance_id == 1)
        assert hopper.position == (3, 2)

    def test_every_enumerated_move_resolves_without_valueerror(self, library):
        """Contract sweep: any MOVE the enumerator emits must resolve."""
        for enemy_rows in [(2,), (2, 3), (2, 4)]:
            state = self._hopper_state(library, enemy_rows=enemy_rows)
            for a in legal_actions(state, library):
                if a.action_type != ActionType.MOVE:
                    continue
                resolve_action(state, a, library)  # must not raise

    def test_resolver_rejects_ally_leap(self, library):
        state = self._hopper_state(library, enemy_rows=(), ally_rows=(2,))
        # Not enumerated…
        moves = [
            a for a in legal_actions(state, library)
            if a.action_type == ActionType.MOVE and a.minion_id == 1
        ]
        assert all(a.position != (3, 2) for a in moves)
        # …and the resolver rejects the hand-crafted leap over an ally.
        with pytest.raises(ValueError):
            resolve_action(state, move_action(minion_id=1, position=(3, 2)), library)


# ---------------------------------------------------------------------------
# Finding 8: Tree Wyrm react tutor
# ---------------------------------------------------------------------------


class TestTreeWyrmReactTutor:
    def test_react_play_opens_pending_tutor_and_delivers_cards(self, library):
        wyrm_id = library.get_numeric_id("tree_wyrm")
        rat_id = library.get_numeric_id("rat")

        p1 = _player(PlayerSide.PLAYER_1)
        p2 = _player(
            PlayerSide.PLAYER_2,
            hand=(wyrm_id,),
            deck=(wyrm_id, rat_id, wyrm_id),
            mana=1,
        )
        # BEFORE_END_OF_TURN window: P1 is ending their turn, P2 reacts.
        state = _state_with_minions(
            [],
            (p1, p2),
            phase=TurnPhase.REACT,
            active_player_idx=0,
            react_player_idx=1,
            react_context=ReactContext.BEFORE_END_OF_TURN,
            react_return_phase=TurnPhase.END_OF_TURN,
            react_stack=(),
        )
        start_turn = state.turn_number

        # P2 react-plays Tree Wyrm (1 mana, discard from hand).
        state = resolve_action(state, play_react_action(card_index=0), library)
        assert state.react_player_idx == 0  # counter-react opportunity
        # P1 passes → stack resolves → tutor modal must open for P2.
        state = resolve_action(state, pass_action(), library)

        assert state.pending_tutor_player_idx == 1, (
            "Tree Wyrm's react tutor was a silent no-op — pending_tutor "
            "never opened (player paid 1 mana + the card for nothing)"
        )
        assert state.pending_tutor_remaining == 2
        assert len(state.pending_tutor_matches) == 2
        # The turn-flow bookmark survives the modal hand-off.
        assert state.react_return_phase == TurnPhase.END_OF_TURN

        # Pick both Tree Wyrms.
        state = resolve_action(
            state, Action(action_type=ActionType.TUTOR_SELECT, card_index=0), library,
        )
        assert state.pending_tutor_player_idx == 1  # one pick remaining
        state = resolve_action(
            state, Action(action_type=ActionType.TUTOR_SELECT, card_index=0), library,
        )
        assert state.pending_tutor_player_idx is None

        p2_after = state.players[1]
        assert p2_after.hand.count(wyrm_id) == 2, "tutored cards not in hand"
        assert p2_after.deck == (rat_id,)
        assert p2_after.grave.count(wyrm_id) == 1  # the react-played copy
        assert p2_after.current_mana == 0

        # The post-tutor react window returns to END_OF_TURN — the turn
        # advances without re-firing end-of-turn triggers.
        assert state.phase == TurnPhase.REACT
        assert state.react_return_phase == TurnPhase.END_OF_TURN
        state = resolve_action(state, pass_action(), library)
        assert state.turn_number == start_turn + 1
        assert state.active_player_idx == 1
