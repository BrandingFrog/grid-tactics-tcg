"""Tests for the 2026-07 turn-structure redesign (Python engine lane).

Covers, one class per numbered work item:
  1. Constants: MAX_HAND_SIZE=10 shared in types, AUTO_DRAW_ENABLED
     deleted, MAX_REACT_STACK_DEPTH raised to 100 (pure failsafe).
  2. Turn start: unconditional draw AFTER mana regen; empty deck →
     escalating fatigue (10/20/30 per player); full hand → the drawn
     card overdraw-burns to the exhaust pile.
  3. DRAW removed from legal actions (slot stays reserved); PASS is
     FREE — no fatigue damage on pass.
  4. Handshake: pass-after-pass across players → both players +1 mana
     at that turn's end (full mana → draw instead; overdraw-burns;
     empty deck → nothing). Counter resets — no chaining. React-window
     passes do NOT count.
  5. Overdraw-burn on ALL draw paths (Player helpers + DRAW effect +
     tutor-to-hand).
  6. Burn tick moved to the Decay phase (owner's end of turn) with
     per-card scoping (owner / opponent / every); Fallen Paladin heals
     at Rally (start), Emberplague / Dark Matter Battery decay at end.
  7. March rename: MARCH / MARCH_FORWARD enum aliases load, card-loader
     accepts the "march_forward" effect key.
"""

from pathlib import Path

import pytest

import grid_tactics.types as gt_types
import grid_tactics.roguelike_events as roguelike_events
from grid_tactics.actions import Action, move_action, pass_action
from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.card_loader import CardLoader
from grid_tactics.cards import EffectDefinition
from grid_tactics.effect_resolver import _resolve_self_owner
from grid_tactics.enums import (
    ActionType,
    EffectType,
    PlayerSide,
    TargetType,
    TriggerType,
    TurnPhase,
)
from grid_tactics.game_state import GameState
from grid_tactics.legal_actions import legal_actions
from grid_tactics.minion import MinionInstance
from grid_tactics.player import Player
from grid_tactics.action_resolver import resolve_action
from grid_tactics.types import (
    MAX_HAND_SIZE,
    MAX_MANA_CAP,
    MAX_REACT_STACK_DEPTH,
    STARTING_HP,
)


@pytest.fixture(scope="module")
def library():
    return CardLibrary.from_directory(Path("data/cards"))


@pytest.fixture(autouse=True)
def isolate_turn_structure_from_fortune_rounds(monkeypatch):
    """These tests exercise phase mechanics, not the Fortune interruption."""
    monkeypatch.setattr(roguelike_events, "ROGUELIKE_EVENT_INTERVAL", 10_000)


def _player(side, hand=(), deck=(), grave=(), mana=5, hp=STARTING_HP):
    return Player(
        side=side,
        hp=hp,
        current_mana=mana,
        max_mana=max(mana, 5),
        hand=tuple(hand),
        deck=tuple(deck),
        grave=tuple(grave),
    )


def _state_with_minions(minions, players, **kwargs):
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


def _drain_to_next_action_phase(state, library, cap=16):
    """PASS through react windows / phase helpers until an ACTION phase."""
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


def _pass_full_turn(state, library):
    """Active player PASSes their action, then drain to the next ACTION."""
    state = resolve_action(state, pass_action(), library)
    return _drain_to_next_action_phase(state, library)


# ---------------------------------------------------------------------------
# 1. Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_max_hand_size_shared_constant(self):
        assert MAX_HAND_SIZE == 10
        # rl modules re-use the shared constant (no bare literal 10s).
        from grid_tactics.rl import action_space, observation
        assert action_space.MAX_HAND_SIZE is MAX_HAND_SIZE
        assert observation.MAX_HAND_SIZE is MAX_HAND_SIZE

    def test_auto_draw_flag_deleted(self):
        assert not hasattr(gt_types, "AUTO_DRAW_ENABLED"), (
            "AUTO_DRAW_ENABLED must be deleted — the turn-start draw is "
            "unconditional now"
        )

    def test_react_stack_depth_is_pure_failsafe(self):
        assert MAX_REACT_STACK_DEPTH == 100


# ---------------------------------------------------------------------------
# 2. Turn start: draw + mana, fatigue, overdraw
# ---------------------------------------------------------------------------


class TestTurnStartDrawAndMana:
    def test_flip_regens_mana_then_draws(self, library):
        rat_id = library.get_numeric_id("rat")
        p1 = _player(PlayerSide.PLAYER_1, deck=(rat_id,) * 5, mana=3)
        p2 = _player(PlayerSide.PLAYER_2, deck=(rat_id,) * 5, mana=3)
        state = _state_with_minions([], (p1, p2))

        state = _pass_full_turn(state, library)

        assert state.active_player_idx == 1
        new_p2 = state.players[1]
        assert new_p2.current_mana == 4, "turn-start +1 mana missing"
        assert len(new_p2.hand) == 1, "unconditional turn-start draw missing"
        assert len(new_p2.deck) == 4

    def test_full_hand_turn_start_draw_burns_to_exhaust(self, library):
        rat_id = library.get_numeric_id("rat")
        giant_id = library.get_numeric_id("giant_rat")
        p1 = _player(PlayerSide.PLAYER_1, deck=(rat_id,) * 3)
        p2 = _player(
            PlayerSide.PLAYER_2,
            hand=(rat_id,) * MAX_HAND_SIZE,
            deck=(giant_id, rat_id),
        )
        state = _state_with_minions([], (p1, p2))

        state = _pass_full_turn(state, library)

        new_p2 = state.players[1]
        assert len(new_p2.hand) == MAX_HAND_SIZE  # unchanged
        assert new_p2.exhaust == (giant_id,), (
            "overdrawn card must burn to the exhaust pile (revealed), "
            "not fizzle"
        )
        assert new_p2.deck == (rat_id,)

    def test_empty_deck_fatigue_escalates_per_player(self, library):
        p1 = _player(PlayerSide.PLAYER_1, deck=())
        p2 = _player(PlayerSide.PLAYER_2, deck=())
        state = _state_with_minions([], (p1, p2))

        # P1 pass → flip → P2 fatigue #1 (10 dmg)
        state = _pass_full_turn(state, library)
        assert state.players[1].hp == STARTING_HP - 10
        assert state.fatigue_counts == (0, 1)

        # P2 pass → flip → P1 fatigue #1 (10 dmg)
        state = _pass_full_turn(state, library)
        assert state.players[0].hp == STARTING_HP - 10
        assert state.fatigue_counts == (1, 1)

        # P1 pass → flip → P2 fatigue #2 escalates (20 dmg → 30 total)
        state = _pass_full_turn(state, library)
        assert state.players[1].hp == STARTING_HP - 30
        assert state.fatigue_counts == (1, 2)

    def test_fatigue_can_be_lethal(self, library):
        p1 = _player(PlayerSide.PLAYER_1, deck=())
        p2 = _player(PlayerSide.PLAYER_2, deck=(), hp=10)
        state = _state_with_minions([], (p1, p2))

        state = resolve_action(state, pass_action(), library)
        # Drain: the flip's fatigue kills P2 → game over.
        for _ in range(16):
            if state.is_game_over:
                break
            assert state.phase == TurnPhase.REACT
            state = resolve_action(state, pass_action(), library)
        assert state.is_game_over
        assert state.winner == PlayerSide.PLAYER_1


# ---------------------------------------------------------------------------
# 3. DRAW removed; PASS free
# ---------------------------------------------------------------------------


class TestDrawRemovedPassFree:
    def test_draw_never_legal(self, library):
        rat_id = library.get_numeric_id("rat")
        p1 = _player(PlayerSide.PLAYER_1, hand=(rat_id,), deck=(rat_id,) * 5)
        p2 = _player(PlayerSide.PLAYER_2, deck=(rat_id,) * 5)
        state = _state_with_minions([], (p1, p2))

        actions = legal_actions(state, library)
        assert all(a.action_type != ActionType.DRAW for a in actions), (
            "DRAW must be removed from legal actions (slot 1000 stays "
            "reserved, never legal)"
        )
        # PASS is still always legal.
        assert any(a.action_type == ActionType.PASS for a in actions)

    def test_pass_is_free_no_fatigue(self, library):
        rat_id = library.get_numeric_id("rat")
        p1 = _player(PlayerSide.PLAYER_1, deck=(rat_id,) * 5)
        p2 = _player(PlayerSide.PLAYER_2, deck=(rat_id,) * 5)
        state = _state_with_minions([], (p1, p2))

        result = resolve_action(state, pass_action(), library)

        assert result.players[0].hp == STARTING_HP, "PASS must be FREE"
        assert result.fatigue_counts == (0, 0), (
            "fatigue_counts must not move on PASS — fatigue now exists "
            "only for empty-deck turn-start draws"
        )


# ---------------------------------------------------------------------------
# 4. Handshake
# ---------------------------------------------------------------------------


class TestHandshake:
    def test_pass_after_pass_pays_both_players_mana(self, library):
        rat_id = library.get_numeric_id("rat")
        p1 = _player(PlayerSide.PLAYER_1, deck=(rat_id,) * 8, mana=3)
        p2 = _player(PlayerSide.PLAYER_2, deck=(rat_id,) * 8, mana=3)
        state = _state_with_minions([], (p1, p2))

        # P1 passes (streak 1) → P2's turn.
        state = _pass_full_turn(state, library)
        assert state.consecutive_passes == 1
        assert not state.handshake_pending

        # P2 passes → Handshake detected immediately, counter reset.
        state = resolve_action(state, pass_action(), library)
        assert state.handshake_pending
        assert state.consecutive_passes == 0

        # Drain through the turn end: payout happens at end of P2's turn.
        state = _drain_to_next_action_phase(state, library)
        assert state.active_player_idx == 0
        assert not state.handshake_pending

        # P1: 3 +1 handshake +1 turn-start regen = 5.
        assert state.players[0].current_mana == 5
        # P2: 3 +1 regen (their turn start) +1 handshake = 5.
        assert state.players[1].current_mana == 5

    def test_full_mana_player_draws_instead(self, library):
        rat_id = library.get_numeric_id("rat")
        p1 = _player(PlayerSide.PLAYER_1, deck=(rat_id,) * 8, mana=3)
        p2 = _player(
            PlayerSide.PLAYER_2, deck=(rat_id,) * 8, mana=MAX_MANA_CAP,
        )
        state = _state_with_minions([], (p1, p2))

        state = _pass_full_turn(state, library)          # P1 pass
        p2_hand_before = len(state.players[1].hand)      # after turn-start draw
        state = resolve_action(state, pass_action(), library)  # P2 pass
        assert state.handshake_pending
        state = _drain_to_next_action_phase(state, library)

        new_p2 = state.players[1]
        assert new_p2.current_mana == MAX_MANA_CAP
        assert len(new_p2.hand) == p2_hand_before + 1, (
            "full-mana player must DRAW instead of gaining mana"
        )
        assert state.players[0].current_mana == 5  # 3 +1 handshake +1 regen

    def test_full_mana_empty_deck_no_payout_no_fatigue_from_handshake(self, library):
        rat_id = library.get_numeric_id("rat")
        p1 = _player(PlayerSide.PLAYER_1, deck=(rat_id,) * 8, mana=3)
        p2 = _player(PlayerSide.PLAYER_2, deck=(), mana=MAX_MANA_CAP)
        state = _state_with_minions([], (p1, p2))

        state = _pass_full_turn(state, library)  # P1 pass → P2 turn-start fatigue 10
        assert state.players[1].hp == STARTING_HP - 10
        state = resolve_action(state, pass_action(), library)  # P2 pass → handshake
        state = _drain_to_next_action_phase(state, library)

        # Handshake gave P2 NOTHING (full mana + empty deck) and crucially
        # NO extra fatigue — the only damage is the turn-start fatigue.
        assert state.players[1].hp == STARTING_HP - 10
        assert state.players[1].current_mana == MAX_MANA_CAP
        assert state.players[0].current_mana == 5

    def test_react_window_pass_does_not_count(self, library):
        rat_id = library.get_numeric_id("rat")
        p1 = _player(PlayerSide.PLAYER_1, deck=(rat_id,) * 8)
        p2 = _player(PlayerSide.PLAYER_2, deck=(rat_id,) * 8)
        state = _state_with_minions([], (p1, p2))

        # P1's ACTION pass = streak 1. The drain to P2's ACTION phase
        # involves multiple REACT-window passes — none of them may bump
        # the streak to 2 (that would be a phantom Handshake).
        state = _pass_full_turn(state, library)
        assert state.consecutive_passes == 1
        assert not state.handshake_pending

    def test_non_pass_action_resets_streak(self, library):
        rat_id = library.get_numeric_id("rat")
        p1 = _player(PlayerSide.PLAYER_1, deck=(rat_id,) * 8)
        p2 = _player(PlayerSide.PLAYER_2, deck=(rat_id,) * 8)
        mover = MinionInstance(
            instance_id=1, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_2, position=(3, 2), current_health=5,
        )
        state = _state_with_minions([mover], (p1, p2))

        state = _pass_full_turn(state, library)  # P1 pass, streak 1
        assert state.consecutive_passes == 1

        # P2 moves instead of passing → streak resets, no handshake.
        state = resolve_action(
            state, move_action(minion_id=1, position=(2, 2)), library,
        )
        assert state.consecutive_passes == 0
        assert not state.handshake_pending

    def test_no_chaining_after_handshake(self, library):
        rat_id = library.get_numeric_id("rat")
        p1 = _player(PlayerSide.PLAYER_1, deck=(rat_id,) * 10, mana=3)
        p2 = _player(PlayerSide.PLAYER_2, deck=(rat_id,) * 10, mana=3)
        state = _state_with_minions([], (p1, p2))

        state = _pass_full_turn(state, library)                 # P1 pass
        state = resolve_action(state, pass_action(), library)   # P2 pass → handshake
        state = _drain_to_next_action_phase(state, library)     # payout + flip
        assert not state.handshake_pending
        assert state.consecutive_passes == 0

        # The NEXT single pass must not re-trigger a Handshake — it
        # needs a fresh pair.
        state = resolve_action(state, pass_action(), library)   # P1 pass
        assert state.consecutive_passes == 1
        assert not state.handshake_pending


# ---------------------------------------------------------------------------
# 5. Overdraw-burn on all draw paths
# ---------------------------------------------------------------------------


class TestOverdrawBurn:
    def test_player_draw_helper_burns_on_full_hand(self):
        p = _player(PlayerSide.PLAYER_1, hand=(1,) * MAX_HAND_SIZE, deck=(7, 8))
        new_p, card_id, burned = p.draw_card_with_overdraw()
        assert burned
        assert card_id == 7
        assert new_p.exhaust == (7,)
        assert len(new_p.hand) == MAX_HAND_SIZE
        assert new_p.deck == (8,)
        assert not new_p.discarded_this_turn  # a burn is NOT a discard cost

    def test_player_draw_helper_normal_when_room(self):
        p = _player(PlayerSide.PLAYER_1, hand=(1,), deck=(7, 8))
        new_p, card_id, burned = p.draw_card_with_overdraw()
        assert not burned
        assert new_p.hand == (1, 7)
        assert new_p.exhaust == ()

    def test_add_to_hand_helper_burns_on_full_hand(self):
        p = _player(PlayerSide.PLAYER_1, hand=(1,) * MAX_HAND_SIZE)
        new_p, burned = p.add_to_hand_with_overdraw(9)
        assert burned
        assert new_p.exhaust == (9,)
        assert len(new_p.hand) == MAX_HAND_SIZE

    def test_draw_effect_burns_on_full_hand(self, library):
        rat_id = library.get_numeric_id("rat")
        p1 = _player(
            PlayerSide.PLAYER_1,
            hand=(rat_id,) * MAX_HAND_SIZE,
            deck=(rat_id, rat_id),
        )
        p2 = _player(PlayerSide.PLAYER_2)
        state = _state_with_minions([], (p1, p2))
        effect = EffectDefinition(
            effect_type=EffectType.DRAW,
            trigger=TriggerType.ON_PLAY,
            target=TargetType.SELF_OWNER,
            amount=1,
        )
        result = _resolve_self_owner(
            state, effect, (0, 0), PlayerSide.PLAYER_1, library,
        )
        new_p1 = result.players[0]
        assert len(new_p1.hand) == MAX_HAND_SIZE
        assert new_p1.exhaust == (rat_id,)
        assert len(new_p1.deck) == 1

    def test_tutor_to_hand_burns_on_full_hand(self, library):
        rat_id = library.get_numeric_id("rat")
        giant_id = library.get_numeric_id("giant_rat")
        p1 = _player(
            PlayerSide.PLAYER_1,
            hand=(rat_id,) * MAX_HAND_SIZE,
            deck=(giant_id, rat_id),
        )
        p2 = _player(PlayerSide.PLAYER_2)
        state = _state_with_minions(
            [],
            (p1, p2),
            pending_tutor_player_idx=0,
            pending_tutor_matches=(0,),
            pending_tutor_remaining=1,
        )
        result = resolve_action(
            state,
            Action(action_type=ActionType.TUTOR_SELECT, card_index=0),
            library,
        )
        new_p1 = result.players[0]
        assert giant_id not in new_p1.deck
        assert len(new_p1.hand) == MAX_HAND_SIZE
        assert new_p1.exhaust == (giant_id,), (
            "tutor-to-hand must overdraw-burn on a full hand for "
            "consistency with every other draw path"
        )


# ---------------------------------------------------------------------------
# 6. Burn tick in the Decay phase, with scoping
# ---------------------------------------------------------------------------


class TestBurnDecayPhase:
    def _burning_state(self, library, scope, hp=19):
        rat_id = library.get_numeric_id("rat")
        burning = MinionInstance(
            instance_id=1, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_1, position=(1, 1),
            current_health=hp, is_burning=True, burn_scope=scope,
        )
        p1 = _player(PlayerSide.PLAYER_1, deck=(rat_id,) * 8)
        p2 = _player(PlayerSide.PLAYER_2, deck=(rat_id,) * 8)
        return _state_with_minions([burning], (p1, p2))

    def _hp(self, state):
        m = next((m for m in state.minions if m.instance_id == 1), None)
        return m.current_health if m is not None else None

    def test_owner_scope_ticks_at_owner_decay_not_start(self, library):
        state = self._burning_state(library, "owner")
        # P1 (owner) passes: the tick lands in P1's DECAY phase.
        state = _pass_full_turn(state, library)
        assert self._hp(state) == 14, "burn must tick in the owner's Decay phase"
        # P2 passes: NO tick in the opponent's Decay for owner scope,
        # and NO tick at P1's next turn start (the old location).
        state = _pass_full_turn(state, library)
        assert state.active_player_idx == 0
        assert self._hp(state) == 14, (
            "owner-scoped burn ticked outside the owner's Decay phase"
        )

    def test_every_scope_ticks_in_both_decays(self, library):
        state = self._burning_state(library, "every")
        state = _pass_full_turn(state, library)   # P1 decay: -5
        assert self._hp(state) == 14
        state = _pass_full_turn(state, library)   # P2 decay: -5
        assert self._hp(state) == 9

    def test_opponent_scope_ticks_only_in_opponent_decay(self, library):
        state = self._burning_state(library, "opponent")
        state = _pass_full_turn(state, library)   # P1 (owner) decay: no tick
        assert self._hp(state) == 19
        state = _pass_full_turn(state, library)   # P2 decay: tick
        assert self._hp(state) == 14

    def test_rally_and_decay_card_assignments(self, library):
        """Spec verification: positive once-per-turn effects at Rally
        (start), negative at Decay (end)."""
        paladin = library.get_by_id(library.get_numeric_id("fallen_paladin"))
        heal = next(
            e for e in paladin.effects
            if e.effect_type == EffectType.PASSIVE_HEAL
        )
        assert heal.trigger == TriggerType.ON_START_OF_TURN, (
            "Fallen Paladin's heal is POSITIVE — it belongs in the Rally "
            "phase (on_start_of_turn)"
        )

        for card_id in ("emberplague_rat", "dark_matter_battery"):
            card = library.get_by_id(library.get_numeric_id(card_id))
            assert any(
                e.trigger == TriggerType.ON_END_OF_TURN for e in card.effects
            ), f"{card_id}'s negative effect belongs in the Decay phase"

    def test_paladin_heals_at_rally(self, library):
        """Integration: a damaged Fallen Paladin heals at the START of its
        owner's turn (Rally), before the owner acts."""
        rat_id = library.get_numeric_id("rat")
        paladin_id = library.get_numeric_id("fallen_paladin")
        paladin = MinionInstance(
            instance_id=1, card_numeric_id=paladin_id,
            owner=PlayerSide.PLAYER_2, position=(3, 2), current_health=30,
        )
        p1 = _player(PlayerSide.PLAYER_1, deck=(rat_id,) * 6)
        p2 = _player(PlayerSide.PLAYER_2, deck=(rat_id,) * 6)
        state = _state_with_minions([paladin], (p1, p2))

        # P1 passes; when P2's turn begins their Rally triggers fire.
        state = _pass_full_turn(state, library)
        assert state.active_player_idx == 1
        healed = next(m for m in state.minions if m.instance_id == 1)
        assert healed.current_health == 32, (
            "Fallen Paladin must heal +2 in its owner's Rally phase"
        )


# ---------------------------------------------------------------------------
# 7. March rename (engine side)
# ---------------------------------------------------------------------------


class TestMarchRename:
    def test_enum_aliases(self):
        assert EffectType["MARCH_FORWARD"] is EffectType.RALLY_FORWARD
        assert EffectType["MARCH"] is EffectType.RALLY_FORWARD

    def test_card_loader_accepts_march_forward(self):
        effect = CardLoader._parse_single_effect(
            {
                "type": "march_forward",
                "trigger": "on_move",
                "target": "self_owner",
                "amount": 1,
            },
            "test_card",
            "effects[0]",
        )
        assert effect.effect_type == EffectType.RALLY_FORWARD

    def test_card_loader_still_accepts_legacy_rally_forward(self):
        effect = CardLoader._parse_single_effect(
            {
                "type": "rally_forward",
                "trigger": "on_move",
                "target": "self_owner",
                "amount": 1,
            },
            "test_card",
            "effects[0]",
        )
        assert effect.effect_type == EffectType.RALLY_FORWARD


# ---------------------------------------------------------------------------
# Double-tutor chain no longer crashes (latent bug surfaced by the new
# rules in random rollouts — two Tree Wyrm reacts in one LIFO chain)
# ---------------------------------------------------------------------------


class TestDoubleTutorChain:
    def test_same_player_same_filter_merges_remaining(self, library):
        from grid_tactics.effect_resolver import _enter_pending_tutor
        wyrm_id = library.get_numeric_id("tree_wyrm")
        rat_id = library.get_numeric_id("rat")
        wyrm_def = library.get_by_id(wyrm_id)
        p1 = _player(
            PlayerSide.PLAYER_1, deck=(wyrm_id, rat_id, wyrm_id, wyrm_id),
        )
        p2 = _player(PlayerSide.PLAYER_2)
        state = _state_with_minions([], (p1, p2))

        state = _enter_pending_tutor(
            state, wyrm_def, PlayerSide.PLAYER_1, library, amount=2,
        )
        assert state.pending_tutor_player_idx == 0
        assert state.pending_tutor_remaining == 2

        # Second tutor in the same chain: merges (no crash, more picks).
        state = _enter_pending_tutor(
            state, wyrm_def, PlayerSide.PLAYER_1, library, amount=2,
        )
        assert state.pending_tutor_player_idx == 0
        assert state.pending_tutor_remaining == 3  # capped at 3 matches

    def test_other_player_tutor_fizzles_instead_of_crashing(self, library):
        from grid_tactics.effect_resolver import _enter_pending_tutor
        wyrm_id = library.get_numeric_id("tree_wyrm")
        wyrm_def = library.get_by_id(wyrm_id)
        p1 = _player(PlayerSide.PLAYER_1, deck=(wyrm_id, wyrm_id))
        p2 = _player(PlayerSide.PLAYER_2, deck=(wyrm_id,))
        state = _state_with_minions([], (p1, p2))

        state = _enter_pending_tutor(
            state, wyrm_def, PlayerSide.PLAYER_1, library, amount=1,
        )
        assert state.pending_tutor_player_idx == 0

        # A tutor for the OTHER player while the slot is occupied
        # fizzles silently (previously: engine-crashing assert).
        after = _enter_pending_tutor(
            state, wyrm_def, PlayerSide.PLAYER_2, library, amount=1,
        )
        assert after.pending_tutor_player_idx == 0
        assert after.pending_tutor_matches == state.pending_tutor_matches


# ---------------------------------------------------------------------------
# Serialization round-trip for the new state fields
# ---------------------------------------------------------------------------


class TestSerializationRoundTrip:
    def test_handshake_and_burn_scope_round_trip(self, library):
        rat_id = library.get_numeric_id("rat")
        burning = MinionInstance(
            instance_id=1, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_1, position=(1, 1),
            current_health=9, is_burning=True, burn_scope="every",
        )
        p1 = _player(PlayerSide.PLAYER_1, deck=(rat_id,))
        p2 = _player(PlayerSide.PLAYER_2)
        state = _state_with_minions(
            [burning], (p1, p2),
            consecutive_passes=1,
            handshake_pending=True,
        )
        restored = GameState.from_dict(state.to_dict())
        assert restored.consecutive_passes == 1
        assert restored.handshake_pending is True
        assert restored.minions[0].burn_scope == "every"

    def test_legacy_dict_defaults(self, library):
        """Old saved dicts without the new keys load with safe defaults."""
        p1 = _player(PlayerSide.PLAYER_1)
        p2 = _player(PlayerSide.PLAYER_2)
        state = _state_with_minions([], (p1, p2))
        d = state.to_dict()
        d.pop("consecutive_passes")
        d.pop("handshake_pending")
        restored = GameState.from_dict(d)
        assert restored.consecutive_passes == 0
        assert restored.handshake_pending is False
