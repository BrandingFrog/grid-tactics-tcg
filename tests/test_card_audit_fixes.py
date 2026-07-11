"""Regression tests for the 2026-07 card-audit engine/server bug-fix lane.

Each test class pins one CONFIRMED finding from the per-card audit:

  1.  Ratical Resurrection — completing (or declining) the revive modal must
      advance the turn via the shared resume tail, not hand the caster a
      free second action.
  2.  Ratical Resurrection — _enter_pending_revive skips the modal entirely
      when the caster's deploy zone has no empty cell.
  3.  To The Ratmobile — magic-cast tutor emits EVT_PENDING_MODAL_OPENED /
      EVT_PENDING_MODAL_RESOLVED so the client eventQueue gate engages.
  4.  Blue/Red Diodebot — on-summon tutor emits the same modal event pair,
      and resolving it does NOT open a third AFTER_ACTION react window.
  5.  Dark Matter Battery — a dead source's scale_with="dark_matter" trigger
      fizzles instead of falling through to the player-pool scaling path.
  6.  Eclipse Shade — the loader rejects BURN effects whose `amount` differs
      from the engine's BURN_DAMAGE constant (dead data guard).
  7.  Furryroach — the March sweep emits one EVT_MINION_MOVED per marched
      ally so the client animates the swarm advance.
  8.  Gargoyle Sorceress — scale_with="player_dark_matter" reads the OWNER's
      total DM pool (and the placement multiplier applies after scaling).
  9.  Giant Rat — `unique` is enforced at play time (legal_actions AND the
      resolver validation guard).
  10. Grave Caller — targeted activated abilities are excluded from the RL
      action mask (the 25-slot block cannot encode a target).
  11. Grave Caller / Reanimated Bones — TRANSFORM resets dark_matter_stacks
      (full "fresh minion" reset, matching the tensor engine).
  12. Reanimated Bones — TRANSFORM emits EVT_MINION_TRANSFORMED so the
      client eventQueue can animate the swap.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from grid_tactics.actions import (
    decline_revive_action,
    decline_tutor_action,
    move_action,
    pass_action,
    play_card_action,
    revive_place_action,
    transform_action,
    tutor_select_action,
)
from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.card_loader import CardLoader
from grid_tactics.action_resolver import (
    _enter_pending_revive,
    resolve_action,
)
from grid_tactics.effect_resolver import resolve_effect
from grid_tactics.engine_events import (
    EVT_MINION_MOVED,
    EVT_MINION_TRANSFORMED,
    EVT_PENDING_MODAL_OPENED,
    EVT_PENDING_MODAL_RESOLVED,
    EventStream,
)
from grid_tactics.enums import (
    ActionType,
    PlayerSide,
    ReactContext,
    TurnPhase,
)
from grid_tactics.game_state import GameState
from grid_tactics.legal_actions import legal_actions
from grid_tactics.minion import BURN_DAMAGE, MinionInstance
from grid_tactics.player import Player
from grid_tactics.types import STARTING_HP


@pytest.fixture(scope="module")
def library():
    """The real card library from data/cards."""
    return CardLibrary.from_directory(Path("data/cards"))


def _make_state(
    minions=(),
    p1_hand=(), p2_hand=(),
    p1_deck=(), p2_deck=(),
    p1_grave=(), p2_grave=(),
    p1_mana=10, p2_mana=10,
    **kwargs,
):
    """Build a minimal ACTION-phase GameState with the given minions placed."""
    board = Board.empty()
    for m in minions:
        board = board.place(m.position[0], m.position[1], m.instance_id)
    next_id = max((m.instance_id for m in minions), default=-1) + 1
    p1 = Player(
        side=PlayerSide.PLAYER_1, hp=STARTING_HP,
        current_mana=p1_mana, max_mana=10,
        hand=tuple(p1_hand), deck=tuple(p1_deck), grave=tuple(p1_grave),
    )
    p2 = Player(
        side=PlayerSide.PLAYER_2, hp=STARTING_HP,
        current_mana=p2_mana, max_mana=10,
        hand=tuple(p2_hand), deck=tuple(p2_deck), grave=tuple(p2_grave),
    )
    return GameState(
        board=board,
        players=(p1, p2),
        active_player_idx=0,
        phase=TurnPhase.ACTION,
        turn_number=1,
        seed=42,
        minions=tuple(minions),
        next_minion_id=next_id,
        **kwargs,
    )


def _pass_until_action(state, library, collector=None, max_steps=30):
    """Drive PASS actions through every react window / drain until the
    state machine lands back in an ACTION phase (or the game ends)."""
    steps = 0
    while state.phase != TurnPhase.ACTION and not state.is_game_over:
        state = resolve_action(
            state, pass_action(), library, event_collector=collector,
        )
        steps += 1
        assert steps < max_steps, "pass-driver did not reach ACTION phase"
    return state


# ---------------------------------------------------------------------------
# 1. Ratical Resurrection: revive modal completion must advance the turn
# ---------------------------------------------------------------------------


class TestRaticalResurrectionTurnAdvance:
    def _cast_and_open_modal(self, library):
        """Play Ratical Resurrection with 3 rats in grave; PASS the react
        window; return the state with the revive modal open."""
        ratical = library.get_numeric_id("ratical_resurrection")
        rat = library.get_numeric_id("rat")
        state = _make_state(p1_hand=(ratical,), p1_grave=(rat, rat, rat))
        state = resolve_action(state, play_card_action(card_index=0), library)
        assert state.phase == TurnPhase.REACT
        state = resolve_action(state, pass_action(), library)
        assert state.pending_revive_player_idx == 0
        assert state.pending_revive_remaining == 3
        return state

    def test_full_revive_chain_opens_after_action_window(self, library):
        state = self._cast_and_open_modal(library)
        # Place all three rats (melee — any P1 row cell).
        for pos in ((0, 0), (0, 1), (1, 2)):
            state = resolve_action(state, revive_place_action(pos), library)
        assert state.pending_revive_player_idx is None
        alive = [m for m in state.minions if m.is_alive]
        assert len(alive) == 3
        # The caster must NOT retain the ACTION phase: the resume tail
        # opens the AFTER_ACTION react window for the opponent.
        assert state.phase == TurnPhase.REACT
        assert state.react_context == ReactContext.AFTER_ACTION
        assert state.react_player_idx == 1
        # A second main-phase action by the caster is rejected outright.
        with pytest.raises(ValueError):
            resolve_action(
                state,
                move_action(minion_id=alive[0].instance_id, position=(2, 0)),
                library,
            )

    def test_turn_advances_to_opponent_after_revive(self, library):
        state = self._cast_and_open_modal(library)
        for pos in ((0, 0), (0, 1), (1, 2)):
            state = resolve_action(state, revive_place_action(pos), library)
        state = _pass_until_action(state, library)
        assert not state.is_game_over
        assert state.active_player_idx == 1
        assert state.turn_number == 2

    def test_decline_revive_also_advances(self, library):
        state = self._cast_and_open_modal(library)
        state = resolve_action(state, decline_revive_action(), library)
        assert state.pending_revive_player_idx is None
        assert state.phase == TurnPhase.REACT
        assert state.react_context == ReactContext.AFTER_ACTION
        state = _pass_until_action(state, library)
        assert state.active_player_idx == 1
        assert state.turn_number == 2

    def test_mid_chain_placement_keeps_modal_open(self, library):
        state = self._cast_and_open_modal(library)
        state = resolve_action(state, revive_place_action((0, 0)), library)
        assert state.pending_revive_player_idx == 0
        assert state.pending_revive_remaining == 2
        # Only REVIVE_PLACE / DECLINE_REVIVE legal mid-chain.
        kinds = {a.action_type for a in legal_actions(state, library)}
        assert kinds <= {ActionType.REVIVE_PLACE, ActionType.DECLINE_REVIVE}


# ---------------------------------------------------------------------------
# 2. Ratical Resurrection: full deploy zone skips the modal
# ---------------------------------------------------------------------------


class TestEnterPendingReviveFullZone:
    def test_full_deploy_zone_does_not_enter_modal(self, library):
        rat = library.get_numeric_id("rat")
        # Fill EVERY P1 deploy cell (rows 0-1) with friendly rats.
        minions = [
            MinionInstance(
                instance_id=i, card_numeric_id=rat,
                owner=PlayerSide.PLAYER_1, position=(i // 5, i % 5),
                current_health=10,
            )
            for i in range(10)
        ]
        state = _make_state(minions, p1_grave=(rat, rat, rat))
        card_def = library.get_by_card_id("ratical_resurrection")
        result = _enter_pending_revive(
            state, card_def, PlayerSide.PLAYER_1, library,
        )
        assert result.pending_revive_player_idx is None
        assert result.pending_revive_remaining == 0

    def test_one_empty_cell_still_enters_modal(self, library):
        rat = library.get_numeric_id("rat")
        minions = [
            MinionInstance(
                instance_id=i, card_numeric_id=rat,
                owner=PlayerSide.PLAYER_1, position=(i // 5, i % 5),
                current_health=10,
            )
            for i in range(9)  # (1, 4) left empty
        ]
        state = _make_state(minions, p1_grave=(rat,))
        card_def = library.get_by_card_id("ratical_resurrection")
        result = _enter_pending_revive(
            state, card_def, PlayerSide.PLAYER_1, library,
        )
        assert result.pending_revive_player_idx == 0
        assert result.pending_revive_remaining == 1


# ---------------------------------------------------------------------------
# 3. To The Ratmobile: magic-cast tutor emits the modal event pair
# ---------------------------------------------------------------------------


class TestRatmobileTutorModalEvents:
    def test_modal_opened_and_resolved_events(self, library):
        ratmobile = library.get_numeric_id("to_the_ratmobile")
        rat = library.get_numeric_id("rat")
        state = _make_state(p1_hand=(ratmobile,), p1_deck=(rat, rat))
        stream = EventStream(next_seq=0)
        state = resolve_action(
            state, play_card_action(card_index=0), library,
            event_collector=stream,
        )
        state = resolve_action(
            state, pass_action(), library, event_collector=stream,
        )
        assert state.pending_tutor_player_idx == 0
        opened = [
            e for e in stream.events
            if e.type == EVT_PENDING_MODAL_OPENED
            and e.payload.get("modal_kind") == "tutor_select"
        ]
        assert len(opened) == 1, (
            "magic-cast tutor must emit EVT_PENDING_MODAL_OPENED"
        )
        assert opened[0].requires_decision is True

        # Multi-pick (amount=2): first select keeps the modal open — no
        # RESOLVED event yet.
        state = resolve_action(
            state, tutor_select_action(0), library, event_collector=stream,
        )
        assert state.pending_tutor_player_idx == 0
        assert not [
            e for e in stream.events if e.type == EVT_PENDING_MODAL_RESOLVED
        ]
        # Second select clears the modal and emits RESOLVED.
        state = resolve_action(
            state, tutor_select_action(0), library, event_collector=stream,
        )
        assert state.pending_tutor_player_idx is None
        resolved = [
            e for e in stream.events
            if e.type == EVT_PENDING_MODAL_RESOLVED
            and e.payload.get("modal_kind") == "tutor_select"
        ]
        assert len(resolved) == 1
        # Both rats reached the hand.
        assert list(state.players[0].hand).count(rat) == 2

    def test_decline_tutor_illegal_with_matches_then_select_resolves(self, library):
        """Mandatory tutoring (2026-07-03): DECLINE_TUTOR raises while a
        match remains; the mandatory TUTOR_SELECT then emits RESOLVED."""
        ratmobile = library.get_numeric_id("to_the_ratmobile")
        rat = library.get_numeric_id("rat")
        state = _make_state(p1_hand=(ratmobile,), p1_deck=(rat,))
        stream = EventStream(next_seq=0)
        state = resolve_action(
            state, play_card_action(card_index=0), library,
            event_collector=stream,
        )
        state = resolve_action(
            state, pass_action(), library, event_collector=stream,
        )
        assert state.pending_tutor_player_idx == 0
        with pytest.raises(ValueError, match="mandatory tutoring"):
            resolve_action(
                state, decline_tutor_action(), library, event_collector=stream,
            )
        state = resolve_action(
            state, tutor_select_action(0), library, event_collector=stream,
        )
        assert state.pending_tutor_player_idx is None
        resolved = [
            e for e in stream.events
            if e.type == EVT_PENDING_MODAL_RESOLVED
            and e.payload.get("modal_kind") == "tutor_select"
        ]
        assert len(resolved) == 1


# ---------------------------------------------------------------------------
# 4. Blue/Red Diodebot: on-summon tutor events + no third react window
# ---------------------------------------------------------------------------


class TestDiodebotSummonTutor:
    def _deploy_and_open_tutor(self, library, stream):
        blue = library.get_numeric_id("blue_diodebot")
        red = library.get_numeric_id("red_diodebot")
        state = _make_state(p1_hand=(blue,), p1_deck=(red,))
        state = resolve_action(
            state, play_card_action(card_index=0, position=(1, 0)), library,
            event_collector=stream,
        )
        assert state.react_context == ReactContext.AFTER_SUMMON_DECLARATION
        state = resolve_action(
            state, pass_action(), library, event_collector=stream,
        )  # Window A
        state = resolve_action(
            state, pass_action(), library, event_collector=stream,
        )  # Window B — summon effect resolves, tutor opens
        assert state.pending_tutor_player_idx == 0
        return state

    def test_summon_tutor_emits_modal_opened(self, library):
        stream = EventStream(next_seq=0)
        self._deploy_and_open_tutor(library, stream)
        opened = [
            e for e in stream.events
            if e.type == EVT_PENDING_MODAL_OPENED
            and e.payload.get("modal_kind") == "tutor_select"
        ]
        assert len(opened) == 1, (
            "on-summon tutor must emit EVT_PENDING_MODAL_OPENED"
        )
        assert opened[0].requires_decision is True

    def test_tutor_select_does_not_open_third_react_window(self, library):
        stream = EventStream(next_seq=0)
        state = self._deploy_and_open_tutor(library, stream)
        state = resolve_action(
            state, tutor_select_action(0), library, event_collector=stream,
        )
        # The summon already produced its two react windows (declaration +
        # effect). Resolving the tutor must NOT open an AFTER_ACTION window
        # — it routes straight to the end-of-turn flow.
        assert state.react_context != ReactContext.AFTER_ACTION
        resolved = [
            e for e in stream.events
            if e.type == EVT_PENDING_MODAL_RESOLVED
            and e.payload.get("modal_kind") == "tutor_select"
        ]
        assert len(resolved) == 1
        # Turn still advances cleanly to the opponent.
        state = _pass_until_action(state, library, collector=stream)
        assert state.active_player_idx == 1

    def test_decline_tutor_illegal_during_summon_tutor(self, library):
        """Mandatory tutoring (2026-07-03): the on-summon Diodebot tutor
        cannot be declined while its match remains; the mandatory pick
        still routes to Decay without a third react window."""
        stream = EventStream(next_seq=0)
        state = self._deploy_and_open_tutor(library, stream)
        with pytest.raises(ValueError, match="mandatory tutoring"):
            resolve_action(
                state, decline_tutor_action(), library, event_collector=stream,
            )
        state = resolve_action(
            state, tutor_select_action(0), library, event_collector=stream,
        )
        assert state.react_context != ReactContext.AFTER_ACTION
        state = _pass_until_action(state, library, collector=stream)
        assert state.active_player_idx == 1


# ---------------------------------------------------------------------------
# 5. Dark Matter Battery: dead source fizzles (no player-pool fallthrough)
# ---------------------------------------------------------------------------


class TestDeadBatterySourceFizzles:
    def test_dead_battery_trigger_fizzles(self, library):
        """DM pool redesign 2026-07: the scale reads the OWNER's pool, but
        a queued trigger whose SOURCE minion died must still fizzle."""
        battery_id = library.get_numeric_id("dark_matter_battery")
        dead_battery = MinionInstance(
            instance_id=1, card_numeric_id=battery_id,
            owner=PlayerSide.PLAYER_1, position=(0, 0),
            current_health=0,
        )
        state = _make_state(())
        # Fat pool that must NOT be dealt by a dead source.
        state = replace(
            state,
            minions=(dead_battery,),
            players=(
                replace(state.players[0], dark_matter=7),
                state.players[1],
            ),
        )
        effect = library.get_by_card_id("dark_matter_battery").effects[0]
        result = resolve_effect(
            state, effect, dead_battery.position, PlayerSide.PLAYER_1,
            library, source_minion_id=dead_battery.instance_id,
        )
        assert result is state, "dead-source DM trigger must fizzle"
        assert result.players[1].hp == STARTING_HP

    def test_live_battery_deals_pool_damage(self, library):
        """DM pool redesign 2026-07: Battery's Decay damage = owner's pool."""
        battery_id = library.get_numeric_id("dark_matter_battery")
        battery = MinionInstance(
            instance_id=1, card_numeric_id=battery_id,
            owner=PlayerSide.PLAYER_1, position=(0, 0),
            current_health=20,
        )
        state = _make_state((battery,))
        state = replace(
            state,
            players=(
                replace(state.players[0], dark_matter=3),
                state.players[1],
            ),
        )
        effect = library.get_by_card_id("dark_matter_battery").effects[0]
        result = resolve_effect(
            state, effect, battery.position, PlayerSide.PLAYER_1,
            library, source_minion_id=battery.instance_id,
        )
        assert result.players[1].hp == STARTING_HP - 3


# ---------------------------------------------------------------------------
# 6. Eclipse Shade: loader rejects BURN amounts that differ from BURN_DAMAGE
# ---------------------------------------------------------------------------


class TestBurnAmountLoaderValidation:
    def _burn_effect(self, amount):
        return {
            "type": "burn",
            "trigger": "on_summon",
            "target": "self_owner",
            "amount": amount,
        }

    def test_mismatched_burn_amount_rejected(self):
        with pytest.raises(ValueError, match="BURN_DAMAGE"):
            CardLoader._parse_single_effect(
                self._burn_effect(3), "test_card", "effects[0]"
            )

    @pytest.mark.parametrize("amount", [0, BURN_DAMAGE])
    def test_documented_amounts_accepted(self, amount):
        eff = CardLoader._parse_single_effect(
            self._burn_effect(amount), "test_card", "effects[0]"
        )
        assert eff is not None

    def test_eclipse_shade_card_loads(self, library):
        # The shipped card must satisfy its own validation.
        assert library.get_by_card_id("eclipse_shade") is not None


# ---------------------------------------------------------------------------
# 7. Furryroach: March sweep emits EVT_MINION_MOVED per marched ally
# ---------------------------------------------------------------------------


class TestMarchSweepEvents:
    def test_march_emits_move_event_per_ally(self, library):
        roach_id = library.get_numeric_id("furryroach")
        mover = MinionInstance(
            instance_id=1, card_numeric_id=roach_id,
            owner=PlayerSide.PLAYER_1, position=(1, 0), current_health=10,
        )
        ally_a = MinionInstance(
            instance_id=2, card_numeric_id=roach_id,
            owner=PlayerSide.PLAYER_1, position=(0, 1), current_health=10,
        )
        ally_b = MinionInstance(
            instance_id=3, card_numeric_id=roach_id,
            owner=PlayerSide.PLAYER_1, position=(0, 2), current_health=10,
        )
        state = _make_state((mover, ally_a, ally_b))
        stream = EventStream(next_seq=0)
        state = resolve_action(
            state,
            move_action(minion_id=mover.instance_id, position=(2, 0)),
            library,
            event_collector=stream,
        )
        moves = [e for e in stream.events if e.type == EVT_MINION_MOVED]
        assert len(moves) == 3, "1 acting move + 2 marched allies"
        # The acting minion's event comes first, then the sweep.
        assert moves[0].payload["instance_id"] == mover.instance_id
        march_events = {
            e.payload["instance_id"]: e for e in moves[1:]
        }
        assert set(march_events) == {ally_a.instance_id, ally_b.instance_id}
        assert march_events[ally_a.instance_id].payload["from"] == [0, 1]
        assert march_events[ally_a.instance_id].payload["to"] == [1, 1]
        assert march_events[ally_a.instance_id].payload["cause"] == "march"
        # Board state matches the events.
        moved_a = state.get_minion(ally_a.instance_id)
        moved_b = state.get_minion(ally_b.instance_id)
        assert moved_a.position == (1, 1)
        assert moved_b.position == (1, 2)


# ---------------------------------------------------------------------------
# 8. Gargoyle Sorceress: player_dark_matter pool scaling
# ---------------------------------------------------------------------------


class TestGargoylePlayerDmScaling:
    def _setup(self, library, with_dark_ranged_behind):
        gargoyle_id = library.get_numeric_id("gargoyle_sorceress")
        rat_id = library.get_numeric_id("rat")
        gargoyle = MinionInstance(
            instance_id=1, card_numeric_id=gargoyle_id,
            owner=PlayerSide.PLAYER_1, position=(1, 2),
            current_health=50,
        )
        ally = MinionInstance(
            instance_id=2, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_1, position=(0, 4),
            current_health=10,
        )
        minions = [gargoyle, ally]
        if with_dark_ranged_behind:
            blaster_id = library.get_numeric_id("shadow_blaster")
            minions.append(MinionInstance(
                instance_id=3, card_numeric_id=blaster_id,
                owner=PlayerSide.PLAYER_1, position=(0, 2),
                current_health=10,
            ))
        state = _make_state(minions)
        # DM pool redesign 2026-07: the buff reads the PLAYER's pool.
        state = replace(
            state,
            players=(
                replace(state.players[0], dark_matter=4),
                state.players[1],
            ),
        )
        return state, gargoyle

    def test_buffs_scale_with_owner_pool(self, library):
        state, gargoyle = self._setup(library, with_dark_ranged_behind=False)
        card = library.get_by_card_id("gargoyle_sorceress")
        for effect in card.effects:
            state = resolve_effect(
                state, effect, gargoyle.position, PlayerSide.PLAYER_1,
                library, source_minion_id=gargoyle.instance_id,
            )
        buffed = state.get_minion(gargoyle.instance_id)
        assert buffed.attack_bonus == 4, (
            "on_summon buff must equal the owner's total DM pool"
        )
        assert buffed.current_health == 50 + 4

    def test_placement_condition_triples_pool_buff(self, library):
        state, gargoyle = self._setup(library, with_dark_ranged_behind=True)
        card = library.get_by_card_id("gargoyle_sorceress")
        for effect in card.effects:
            state = resolve_effect(
                state, effect, gargoyle.position, PlayerSide.PLAYER_1,
                library, source_minion_id=gargoyle.instance_id,
            )
        buffed = state.get_minion(gargoyle.instance_id)
        assert buffed.attack_bonus == 12, "pool DM x3 with dark ranged behind"
        assert buffed.current_health == 50 + 12


# ---------------------------------------------------------------------------
# 9. Giant Rat: unique enforced at play time
# ---------------------------------------------------------------------------


class TestGiantRatUniqueEnforcement:
    def test_second_copy_not_enumerated_while_one_alive(self, library):
        giant_id = library.get_numeric_id("giant_rat")
        alive_giant = MinionInstance(
            instance_id=1, card_numeric_id=giant_id,
            owner=PlayerSide.PLAYER_1, position=(0, 2), current_health=30,
        )
        state = _make_state((alive_giant,), p1_hand=(giant_id,))
        plays = [
            a for a in legal_actions(state, library)
            if a.action_type == ActionType.PLAY_CARD and a.card_index == 0
        ]
        assert plays == [], "unique card must not be playable while alive"

    def test_resolver_rejects_out_of_band_second_copy(self, library):
        giant_id = library.get_numeric_id("giant_rat")
        alive_giant = MinionInstance(
            instance_id=1, card_numeric_id=giant_id,
            owner=PlayerSide.PLAYER_1, position=(0, 2), current_health=30,
        )
        state = _make_state((alive_giant,), p1_hand=(giant_id,))
        with pytest.raises(ValueError, match="[Uu]nique"):
            resolve_action(
                state,
                play_card_action(card_index=0, position=(0, 0)),
                library,
            )

    def test_playable_again_after_copy_dies(self, library):
        giant_id = library.get_numeric_id("giant_rat")
        dead_giant = MinionInstance(
            instance_id=1, card_numeric_id=giant_id,
            owner=PlayerSide.PLAYER_1, position=(0, 2), current_health=0,
        )
        state = _make_state((), p1_hand=(giant_id,))
        state = replace(state, minions=(dead_giant,), next_minion_id=2)
        plays = [
            a for a in legal_actions(state, library)
            if a.action_type == ActionType.PLAY_CARD and a.card_index == 0
        ]
        assert plays, "dead copy must not block replaying a unique card"

    def test_enemy_copy_does_not_block(self, library):
        giant_id = library.get_numeric_id("giant_rat")
        enemy_giant = MinionInstance(
            instance_id=1, card_numeric_id=giant_id,
            owner=PlayerSide.PLAYER_2, position=(4, 2), current_health=30,
        )
        state = _make_state((enemy_giant,), p1_hand=(giant_id,))
        plays = [
            a for a in legal_actions(state, library)
            if a.action_type == ActionType.PLAY_CARD and a.card_index == 0
        ]
        assert plays, "unique is per-player — enemy copy must not block"


# ---------------------------------------------------------------------------
# 10. Grave Caller: targeted activated abilities excluded from the RL mask
# ---------------------------------------------------------------------------


class TestActivatedAbilityRlMask:
    def test_targeted_ability_excluded_from_mask(self, library):
        action_space = pytest.importorskip("grid_tactics.rl.action_space")
        gc_id = library.get_numeric_id("grave_caller")
        rat_id = library.get_numeric_id("rat")
        caller = MinionInstance(
            instance_id=1, card_numeric_id=gc_id,
            owner=PlayerSide.PLAYER_1, position=(0, 0), current_health=13,
        )
        target = MinionInstance(
            instance_id=2, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_1, position=(1, 1), current_health=10,
        )
        state = _make_state((caller, target))
        # legal_actions DOES enumerate the targeted ability...
        targeted = [
            a for a in legal_actions(state, library)
            if a.action_type == ActionType.ACTIVATE_ABILITY
        ]
        assert targeted and all(a.target_pos is not None for a in targeted)
        # ...but the mask must exclude the whole ACTIVATE block for it.
        encoder = action_space.ActionEncoder()
        mask = action_space.build_action_mask(state, library, encoder)
        block = mask[
            action_space.ACTIVATE_BASE:
            action_space.ACTIVATE_BASE + 25
        ]
        assert not block.any(), (
            "targeted activated abilities are unrepresentable in the "
            "25-slot block and must be masked out"
        )

    def test_untargeted_ability_still_masked_in(self, library):
        action_space = pytest.importorskip("grid_tactics.rl.action_space")
        ratchanter_id = library.get_numeric_id("ratchanter")
        rat_id = library.get_numeric_id("rat")
        chanter = MinionInstance(
            instance_id=1, card_numeric_id=ratchanter_id,
            owner=PlayerSide.PLAYER_1, position=(1, 3), current_health=10,
        )
        state = _make_state((chanter,), p1_deck=(rat_id,))
        encoder = action_space.ActionEncoder()
        mask = action_space.build_action_mask(state, library, encoder)
        slot = action_space.ACTIVATE_BASE + (1 * 5 + 3)
        assert mask[slot], "untargeted ability must stay in the mask"
        decoded = encoder.decode(slot, state, library)
        assert decoded.action_type == ActionType.ACTIVATE_ABILITY
        assert decoded.minion_id == chanter.instance_id
        assert decoded.target_pos is None

    def test_tutor_matches_beyond_hand_size_masked_out(self, library):
        """TUTOR_SELECT encodes as PLAY_CARD_BASE + idx*25; match index 10+
        would collide with the MOVE block and decode as an illegal MOVE.
        A Rat-heavy deck (To The Ratmobile) can produce >10 matches."""
        action_space = pytest.importorskip("grid_tactics.rl.action_space")
        rat_id = library.get_numeric_id("rat")
        state = _make_state(p1_deck=(rat_id,) * 12)
        state = replace(
            state,
            pending_tutor_player_idx=0,
            pending_tutor_matches=tuple(range(12)),
            pending_tutor_remaining=1,
        )
        # legal_actions offers all 12 picks (UI path is unconstrained)...
        picks = [
            a for a in legal_actions(state, library)
            if a.action_type == ActionType.TUTOR_SELECT
        ]
        assert len(picks) == 12
        # ...but the RL mask keeps only the representable first 10.
        encoder = action_space.ActionEncoder()
        mask = action_space.build_action_mask(state, library, encoder)
        for idx in range(10):
            assert mask[action_space.PLAY_CARD_BASE + idx * 25]
        # Slots 10/11 would land at MOVE_BASE / MOVE_BASE+25 — must be off.
        assert not mask[action_space.MOVE_BASE]
        assert not mask[action_space.MOVE_BASE + 25]
        # Every masked-in slot must decode to a legal tutor action.
        for slot in [action_space.PLAY_CARD_BASE + i * 25 for i in range(10)]:
            decoded = encoder.decode(slot, state, library)
            assert decoded.action_type == ActionType.TUTOR_SELECT
        # DECLINE_TUTOR (slot 1001) is masked OUT — mandatory tutoring
        # (2026-07-03): declining is illegal while matches remain.
        assert not mask[action_space.PASS_IDX]

    def test_transform_actions_excluded_from_mask(self, library):
        """TRANSFORM has no slot block; encode() raises ValueError, which
        used to crash build_action_mask whenever a transformable minion
        (Reanimated Bones) was on board with enough mana."""
        action_space = pytest.importorskip("grid_tactics.rl.action_space")
        bones_id = library.get_numeric_id("reanimated_bones")
        bones = MinionInstance(
            instance_id=1, card_numeric_id=bones_id,
            owner=PlayerSide.PLAYER_1, position=(0, 1), current_health=5,
        )
        state = _make_state((bones,), p1_mana=5)
        # legal_actions offers transforms (server/UI path)...
        assert any(
            a.action_type == ActionType.TRANSFORM
            for a in legal_actions(state, library)
        )
        # ...and building the RL mask must not crash.
        encoder = action_space.ActionEncoder()
        mask = action_space.build_action_mask(state, library, encoder)
        assert mask.any()


# ---------------------------------------------------------------------------
# 11 + 12. TRANSFORM: full stat reset (incl. DM) + EVT_MINION_TRANSFORMED
# ---------------------------------------------------------------------------


class TestTransformResetAndEvent:
    def test_transform_resets_dark_matter_and_emits_event(self, library):
        bones_id = library.get_numeric_id("reanimated_bones")
        gc_id = library.get_numeric_id("grave_caller")
        gc_def = library.get_by_card_id("grave_caller")
        bones = MinionInstance(
            instance_id=1, card_numeric_id=bones_id,
            owner=PlayerSide.PLAYER_1, position=(0, 1),
            current_health=3, attack_bonus=5, max_health_bonus=2,
            is_burning=True, dark_matter_stacks=2,
        )
        state = _make_state((bones,), p1_mana=3)
        stream = EventStream(next_seq=0)
        state = resolve_action(
            state,
            transform_action(minion_id=1, transform_target="grave_caller"),
            library,
            event_collector=stream,
        )
        after = state.get_minion(1)
        assert after.card_numeric_id == gc_id
        assert after.current_health == gc_def.health
        assert after.attack_bonus == 0
        assert after.max_health_bonus == 0
        assert after.is_burning is False
        assert after.dark_matter_stacks == 0, (
            "TRANSFORM must reset DM stacks (fresh-minion ruling, "
            "tensor-engine parity)"
        )
        assert state.players[0].current_mana == 0

        events = [
            e for e in stream.events if e.type == EVT_MINION_TRANSFORMED
        ]
        assert len(events) == 1, "TRANSFORM must emit a board event"
        payload = events[0].payload
        assert payload["instance_id"] == 1
        assert payload["from_card_numeric_id"] == bones_id
        assert payload["to_card_numeric_id"] == gc_id
        assert payload["position"] == [0, 1]
        assert payload["new_hp"] == gc_def.health

    def test_transform_fires_new_forms_on_summon_effects(self, library):
        """Transform-as-summon (user 2026-07-10): transforming counts as
        summoning the new form — its ON_SUMMON effects fire inline.
        Reanimated Bones → Grave Caller grants +1 Dark Matter (the
        Dark-Mage-family 'Summon: Dark Matter +1')."""
        bones_id = library.get_numeric_id("reanimated_bones")
        bones = MinionInstance(
            instance_id=1, card_numeric_id=bones_id,
            owner=PlayerSide.PLAYER_1, position=(0, 1),
            current_health=5,
        )
        state = _make_state((bones,), p1_mana=5)
        dm_before = state.players[0].dark_matter
        state = resolve_action(
            state,
            transform_action(minion_id=1, transform_target="grave_caller"),
            library,
        )
        assert state.players[0].dark_matter == dm_before + 1, (
            "transforming into Grave Caller must grant +1 Dark Matter"
        )

    def test_transform_not_enumerated_when_unaffordable(self, library):
        bones_id = library.get_numeric_id("reanimated_bones")
        bones = MinionInstance(
            instance_id=1, card_numeric_id=bones_id,
            owner=PlayerSide.PLAYER_1, position=(0, 1), current_health=5,
        )
        state = _make_state((bones,), p1_mana=1)
        transforms = [
            a for a in legal_actions(state, library)
            if a.action_type == ActionType.TRANSFORM
        ]
        assert transforms == [], "cheapest transform costs 2 — none legal at 1 mana"
        # At 3 mana, pyre_archer (2) and grave_caller (3) become legal.
        state = _make_state((bones,), p1_mana=3)
        targets = {
            a.transform_target for a in legal_actions(state, library)
            if a.action_type == ActionType.TRANSFORM
        }
        assert targets == {"pyre_archer", "grave_caller"}


class TestGeneralizedRevivePick:
    """Generalized revive (user 2026-07-11): REVIVE_PLACE carries the
    picked GRAVE index — 'like conjure or tutor, supports anything but
    limited by the card text'. Ratical Resurrection's filter is exact
    ('rat'), so non-rat grave cards must never be pickable."""

    def test_pick_by_grave_index_skips_nonmatching_cards(self, library):
        ratical = library.get_numeric_id("ratical_resurrection")
        rat = library.get_numeric_id("rat")
        giant = library.get_numeric_id("giant_rat")
        # Grave: [giant, rat, giant, rat] — only indices 1 and 3 pickable.
        state = _make_state(
            p1_hand=(ratical,), p1_grave=(giant, rat, giant, rat),
        )
        state = resolve_action(state, play_card_action(card_index=0), library)
        state = resolve_action(state, pass_action(), library)
        assert state.pending_revive_player_idx == 0
        # amount 3 capped by 2 matching rats.
        assert state.pending_revive_remaining == 2

        from grid_tactics.legal_actions import revive_grave_matches
        assert revive_grave_matches(state, library) == (1, 3)

        legal = legal_actions(state, library)
        picks = {a.card_index for a in legal
                 if a.action_type == ActionType.REVIVE_PLACE}
        # Every matching grave index is a legal pick (client fans may
        # reference any copy); non-matching indices are absent.
        assert picks == {1, 3}

        # Explicit pick by grave index resolves that entry.
        state = resolve_action(
            state, revive_place_action((0, 0), card_index=1), library,
        )
        p1 = state.players[0]
        # The cast Ratical Resurrection itself also went to the grave.
        assert list(p1.grave) == [giant, giant, rat, ratical]
        assert any(m.card_numeric_id == rat for m in state.minions)
        # Still pending — one more rat pickable (now at index 2).
        assert state.pending_revive_player_idx == 0
        assert revive_grave_matches(state, library) == (2,)

    def test_wrong_grave_index_rejected(self, library):
        ratical = library.get_numeric_id("ratical_resurrection")
        rat = library.get_numeric_id("rat")
        giant = library.get_numeric_id("giant_rat")
        state = _make_state(p1_hand=(ratical,), p1_grave=(giant, rat))
        state = resolve_action(state, play_card_action(card_index=0), library)
        state = resolve_action(state, pass_action(), library)
        with pytest.raises(ValueError):
            # Index 0 is the Giant Rat — not a valid pick for filter 'rat'.
            resolve_action(
                state, revive_place_action((0, 0), card_index=0), library,
            )
