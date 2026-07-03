"""Regression tests for the card-effects bugfix lane.

Covers four confirmed findings:
  1. Magic-card scale_with="dark_matter" mistook any minion sitting on the
     sentinel cell (0,0) for the caster — corrupting Matter of Time,
     Dark Matter Barrage and Dark Matter Stash.
  2. tutor_target tribe selector used exact string equality, so composite
     tribes never matched ({"tribe": "Rat"} excluded Ratchanter "Mage Rat").
  3. _play_react never validated react_condition or
     react_requires_no_friendly_minions; DEPLOY_SELF react never validated
     the landing cell.
  4. Card JSON rulings contradicted the implemented Gargoyle placement
     condition and Dark Matter Stash scaling.
"""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from grid_tactics.actions import (
    Action,
    pass_action,
    play_react_action,
)
from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.cards import CardDefinition, EffectDefinition
from grid_tactics.effect_resolver import resolve_effect
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
from grid_tactics.minion import MinionInstance
from grid_tactics.player import Player
from grid_tactics.react_stack import ReactEntry, handle_react_action, resolve_react_stack
from grid_tactics.types import STARTING_HP


@pytest.fixture
def library():
    """The real card library from data/cards."""
    return CardLibrary.from_directory(Path("data/cards"))


def _make_state(minions, p1_hand=(), p2_hand=(), p1_mana=10, p2_mana=10, **kwargs):
    """Build a minimal ACTION-phase GameState with the given minions placed."""
    board = Board.empty()
    for m in minions:
        board = board.place(m.position[0], m.position[1], m.instance_id)
    next_id = max((m.instance_id for m in minions), default=-1) + 1
    p1 = Player(
        side=PlayerSide.PLAYER_1, hp=STARTING_HP,
        current_mana=p1_mana, max_mana=10,
        hand=tuple(p1_hand), deck=(), grave=(),
    )
    p2 = Player(
        side=PlayerSide.PLAYER_2, hp=STARTING_HP,
        current_mana=p2_mana, max_mana=10,
        hand=tuple(p2_hand), deck=(), grave=(),
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


# ---------------------------------------------------------------------------
# Finding 1: scale_with="dark_matter" and the (0,0) sentinel caster_pos
# ---------------------------------------------------------------------------


class TestDarkMatterSentinelCasterFix:
    """Magic casts resolve with caster_pos=(0,0); a minion sitting on that
    cell must NOT influence DM scaling.

    Dark Matter pool redesign 2026-07: scale_with="dark_matter" now reads
    the CASTER PLAYER's pool (Player.dark_matter) on every path — minions
    never hold DM. These tests keep the original squatter setups to pin
    that a minion at (0,0) has no effect on the result.
    """

    def _with_p1_pool(self, state, amount):
        return replace(
            state,
            players=(
                replace(state.players[0], dark_matter=amount),
                state.players[1],
            ),
        )

    def test_barrage_scales_with_player_pool_despite_enemy_on_origin(self, library):
        """Dark Matter Barrage: 5 + caster player's pool, even with an
        ENEMY minion parked on (0,0)."""
        rat_id = library.get_numeric_id("rat")
        enemy_on_origin = MinionInstance(
            instance_id=0, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_2, position=(0, 0),
            current_health=20,
        )
        enemy_far = MinionInstance(
            instance_id=1, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_2, position=(3, 3),
            current_health=20,
        )
        state = self._with_p1_pool(
            _make_state((enemy_on_origin, enemy_far)), 4,
        )

        barrage = library.get_by_card_id("dark_matter_barrage")
        damage_effect = barrage.effects[0]
        assert damage_effect.scale_with == "dark_matter"
        assert damage_effect.amount == 5

        result = resolve_effect(
            state, damage_effect, (0, 0), PlayerSide.PLAYER_1, library,
        )

        # 5 base + 4 pool DM = 9 to every enemy.
        assert result.get_minion(0).current_health == 20 - 9
        assert result.get_minion(1).current_health == 20 - 9

    def test_zero_amount_dm_damage_not_skipped_by_origin_squatter(self, library):
        """Matter-of-Time-style amount=0 DM damage must use the caster
        player's DM pool — not silently no-op because a minion sits
        on (0,0)."""
        rat_id = library.get_numeric_id("rat")
        squatter = MinionInstance(
            instance_id=0, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_1, position=(0, 0),
            current_health=20,
        )
        enemy = MinionInstance(
            instance_id=2, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_2, position=(3, 3),
            current_health=20,
        )
        state = self._with_p1_pool(_make_state((squatter, enemy)), 6)

        effect = EffectDefinition(
            effect_type=EffectType.DAMAGE,
            trigger=TriggerType.ON_PLAY,
            target=TargetType.SINGLE_TARGET,
            amount=0,
            scale_with="dark_matter",
        )
        result = resolve_effect(
            state, effect, (0, 0), PlayerSide.PLAYER_1, library,
            target_pos=(3, 3),
        )
        # 0 base + 6 pool DM = 6 damage.
        assert result.get_minion(2).current_health == 20 - 6

    def test_stash_buffs_every_dark_mage_by_pool(self, library):
        """Dark Matter Stash's buff (pool redesign): EVERY friendly Dark
        Mage gains the caster player's pool total — a Dark Mage occupying
        (0,0) is buffed like any other."""
        mage_id = library.get_numeric_id("shadow_blaster")
        mage_on_origin = MinionInstance(
            instance_id=0, card_numeric_id=mage_id,
            owner=PlayerSide.PLAYER_1, position=(0, 0),
            current_health=10,
        )
        mage_far = MinionInstance(
            instance_id=1, card_numeric_id=mage_id,
            owner=PlayerSide.PLAYER_1, position=(0, 2),
            current_health=10,
        )
        state = self._with_p1_pool(
            _make_state((mage_on_origin, mage_far)), 3,
        )

        stash = library.get_by_card_id("dark_matter_stash")
        buff_attack = next(
            e for e in stash.effects
            if e.effect_type == EffectType.BUFF_ATTACK
        )
        assert buff_attack.scale_with == "dark_matter"

        result = resolve_effect(
            state, buff_attack, (0, 0), PlayerSide.PLAYER_1, library,
        )
        # Pool scaling: BOTH Dark Mages get +3 (the player's pool).
        assert result.get_minion(1).attack_bonus == 3
        assert result.get_minion(0).attack_bonus == 3

    def test_minion_source_scales_with_owner_pool(self, library):
        """Triggered effects that thread source_minion_id read the OWNER
        PLAYER's pool (Dark Matter Battery — pool redesign 2026-07)."""
        battery_id = library.get_numeric_id("dark_matter_battery")
        battery = MinionInstance(
            instance_id=0, card_numeric_id=battery_id,
            owner=PlayerSide.PLAYER_1, position=(0, 1),
            current_health=20,
        )
        state = self._with_p1_pool(_make_state((battery,)), 5)

        battery_def = library.get_by_card_id("dark_matter_battery")
        effect = battery_def.effects[0]  # damage opponent, scale dark_matter

        result = resolve_effect(
            state, effect, battery.position, PlayerSide.PLAYER_1, library,
            source_minion_id=battery.instance_id,
        )
        assert result.players[1].hp == STARTING_HP - 5

    def test_activated_ability_uses_activator_player_pool(self, library):
        """Grave Caller's dark_matter_buff (contract action:activate_ability)
        scales off the activating PLAYER's pool (redesign 2026-07)."""
        caller_id = library.get_numeric_id("grave_caller")
        rat_id = library.get_numeric_id("rat")
        caller = MinionInstance(
            instance_id=0, card_numeric_id=caller_id,
            owner=PlayerSide.PLAYER_1, position=(1, 1),
            current_health=13,
        )
        target = MinionInstance(
            instance_id=1, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_1, position=(2, 2),
            current_health=10,
        )
        state = self._with_p1_pool(_make_state((caller, target)), 4)

        buff_effect = EffectDefinition(
            effect_type=EffectType.BUFF_ATTACK,
            trigger=TriggerType.ON_PLAY,
            target=TargetType.SINGLE_TARGET,
            amount=0,
            scale_with="dark_matter",
        )
        result = resolve_effect(
            state, buff_effect, caller.position, PlayerSide.PLAYER_1, library,
            target_pos=(2, 2),
            contract_source="action:activate_ability",
        )
        assert result.get_minion(1).attack_bonus == 4


# ---------------------------------------------------------------------------
# Finding 2: tutor_target tribe selector vs composite tribes
# ---------------------------------------------------------------------------


class TestTutorTribeCompositeMatching:
    def test_ratmobile_matches_ratchanter_composite_tribe(self, library):
        """To The Ratmobile {"tribe": "Rat"} must match Ratchanter
        ("Mage Rat") per the card's own ruling."""
        ratmobile = library.get_by_card_id("to_the_ratmobile")
        ratchanter = library.get_by_card_id("ratchanter")
        assert ratchanter.tribe == "Mage Rat"
        assert ratmobile.tutor_matches(ratchanter) is True

    def test_ratmobile_matches_plain_rat_tribes(self, library):
        ratmobile = library.get_by_card_id("to_the_ratmobile")
        for cid in ("rat", "giant_rat", "rathopper", "emberplague_rat"):
            assert ratmobile.tutor_matches(library.get_by_card_id(cid)) is True, cid

    def test_ratmobile_rejects_non_rats(self, library):
        ratmobile = library.get_by_card_id("to_the_ratmobile")
        assert ratmobile.tutor_matches(library.get_by_card_id("shadow_blaster")) is False
        assert ratmobile.tutor_matches(library.get_by_card_id("tree_wyrm")) is False

    def test_tribe_match_is_whole_word_not_substring(self, library):
        """"Rat" must not match a hypothetical "Ratling" tribe."""
        ratmobile = library.get_by_card_id("to_the_ratmobile")
        ratling = CardDefinition(
            card_id="test_ratling",
            name="Test Ratling",
            card_type=CardType.MINION,
            mana_cost=1,
            attack=1,
            health=1,
            attack_range=0,
            tribe="Ratling",
        )
        assert ratmobile.tutor_matches(ratling) is False


# ---------------------------------------------------------------------------
# Finding 3: _play_react resolver-level enforcement
# ---------------------------------------------------------------------------


def _react_window_state(library, *, pending, p2_hand, extra_minions=()):
    """A REACT-phase window: P1 acted (pending), P2 may react."""
    state = _make_state(
        tuple(extra_minions),
        p2_hand=p2_hand,
    )
    return replace(
        state,
        phase=TurnPhase.REACT,
        react_player_idx=1,
        pending_action=pending,
    )


class TestPlayReactResolverValidation:
    def test_react_condition_enforced_at_resolver(self, library):
        """Prohibition (opponent_plays_magic) cannot be react-played
        against a MOVE — even when bypassing legal_actions."""
        pro_id = library.get_numeric_id("prohibition")
        move = Action(action_type=ActionType.MOVE, minion_id=0, position=(2, 2))
        state = _react_window_state(library, pending=move, p2_hand=(pro_id,))

        with pytest.raises(ValueError, match="react condition"):
            handle_react_action(
                state, play_react_action(card_index=0), library,
            )

    def test_no_friendly_minions_gate_enforced(self, library):
        """Sparkfed Surgebot's react is illegal while its owner controls
        any live friendly minion."""
        bot_id = library.get_numeric_id("surgefed_sparkbot")
        rat_id = library.get_numeric_id("rat")
        friendly = MinionInstance(
            instance_id=0, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_2, position=(4, 4), current_health=10,
        )
        sac = Action(action_type=ActionType.SACRIFICE, card_index=0, position=(4, 0))
        state = _react_window_state(
            library, pending=sac, p2_hand=(bot_id,), extra_minions=(friendly,),
        )

        with pytest.raises(ValueError, match="no friendly"):
            handle_react_action(
                state, play_react_action(card_index=0, target_pos=(3, 0)), library,
            )

    def test_no_friendly_minions_gate_in_legal_actions(self, library):
        """The enumerator must mirror the resolver's
        react_requires_no_friendly_minions gate: with a live friendly
        minion on the board, Surgefed Sparkbot's DEPLOY_SELF react is
        never offered (enumerator/resolver contract)."""
        from grid_tactics.legal_actions import legal_actions

        bot_id = library.get_numeric_id("surgefed_sparkbot")
        rat_id = library.get_numeric_id("rat")
        friendly = MinionInstance(
            instance_id=0, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_2, position=(4, 4), current_health=10,
        )
        sac = Action(action_type=ActionType.SACRIFICE, card_index=0, position=(4, 0))
        state = _react_window_state(
            library, pending=sac, p2_hand=(bot_id,), extra_minions=(friendly,),
        )

        actions = legal_actions(state, library)
        assert not any(
            a.action_type == ActionType.PLAY_REACT for a in actions
        ), "Sparkbot react offered while a live friendly minion is on the board"

        # And every enumerated action must be accepted by the resolver
        # (the react window's contract): only PASS remains, which is fine.
        assert any(a.action_type == ActionType.PASS for a in actions)

    def test_no_friendly_minions_gate_allows_react_on_empty_board(self, library):
        """With no live friendly minions, the enumerator still offers the
        Sparkbot react (the gate must not over-suppress)."""
        from grid_tactics.legal_actions import legal_actions

        bot_id = library.get_numeric_id("surgefed_sparkbot")
        sac = Action(action_type=ActionType.SACRIFICE, card_index=0, position=(4, 0))
        state = _react_window_state(library, pending=sac, p2_hand=(bot_id,))

        actions = legal_actions(state, library)
        assert any(
            a.action_type == ActionType.PLAY_REACT for a in actions
        ), "Sparkbot react missing on an empty friendly board"

    def test_deploy_self_rejects_enemy_row_cell(self, library):
        bot_id = library.get_numeric_id("surgefed_sparkbot")
        sac = Action(action_type=ActionType.SACRIFICE, card_index=0, position=(4, 0))
        state = _react_window_state(library, pending=sac, p2_hand=(bot_id,))

        # (1, 0) is a P1 deploy row — illegal for P2's Surgebot.
        with pytest.raises(ValueError, match="deploy"):
            handle_react_action(
                state, play_react_action(card_index=0, target_pos=(1, 0)), library,
            )

    def test_deploy_self_rejects_occupied_cell(self, library):
        bot_id = library.get_numeric_id("surgefed_sparkbot")
        rat_id = library.get_numeric_id("rat")
        blocker = MinionInstance(
            instance_id=0, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_1, position=(3, 0), current_health=10,
        )
        sac = Action(action_type=ActionType.SACRIFICE, card_index=0, position=(4, 0))
        state = _react_window_state(
            library, pending=sac, p2_hand=(bot_id,), extra_minions=(blocker,),
        )

        with pytest.raises(ValueError, match="deploy"):
            handle_react_action(
                state, play_react_action(card_index=0, target_pos=(3, 0)), library,
            )

    def test_legal_surgebot_react_still_works(self, library):
        """The happy path (condition met, empty friendly board, legal
        deploy cell) still pushes the entry onto the stack."""
        bot_id = library.get_numeric_id("surgefed_sparkbot")
        sac = Action(action_type=ActionType.SACRIFICE, card_index=0, position=(4, 0))
        state = _react_window_state(library, pending=sac, p2_hand=(bot_id,))

        result = handle_react_action(
            state, play_react_action(card_index=0, target_pos=(3, 0)), library,
        )
        assert len(result.react_stack) == 1
        assert result.react_stack[0].card_numeric_id == bot_id
        assert result.react_stack[0].target_pos == (3, 0)

    def test_deploy_self_resolution_fizzles_on_occupied_cell(self, library):
        """If the landing cell is occupied by resolution time, DEPLOY_SELF
        fizzles silently instead of crashing Board.place."""
        bot_id = library.get_numeric_id("surgefed_sparkbot")
        rat_id = library.get_numeric_id("rat")
        blocker = MinionInstance(
            instance_id=0, card_numeric_id=rat_id,
            owner=PlayerSide.PLAYER_1, position=(3, 0), current_health=10,
        )
        sac = Action(action_type=ActionType.SACRIFICE, card_index=0, position=(4, 0))
        state = _react_window_state(
            library, pending=sac, p2_hand=(), extra_minions=(blocker,),
        )
        entry = ReactEntry(
            player_idx=1, card_index=0, card_numeric_id=bot_id,
            target_pos=(3, 0),
        )
        state = replace(state, react_stack=(entry,))

        result = resolve_react_stack(state, library)
        deployed = [m for m in result.minions if m.card_numeric_id == bot_id]
        assert deployed == []

    def test_deploy_self_resolution_rejects_out_of_zone_entry(self, library):
        """A directly-injected DEPLOY_SELF entry outside the owner's deploy
        rows raises at resolution instead of silently landing."""
        bot_id = library.get_numeric_id("surgefed_sparkbot")
        sac = Action(action_type=ActionType.SACRIFICE, card_index=0, position=(4, 0))
        state = _react_window_state(library, pending=sac, p2_hand=())
        entry = ReactEntry(
            player_idx=1, card_index=0, card_numeric_id=bot_id,
            target_pos=(0, 0),  # P1's back row — never legal for P2
        )
        state = replace(state, react_stack=(entry,))

        with pytest.raises(ValueError, match="deploy rows"):
            resolve_react_stack(state, library)


# ---------------------------------------------------------------------------
# Finding 4: card JSON rulings match the implementation
# ---------------------------------------------------------------------------


class TestCardRulingsMatchImplementation:
    def _load(self, name):
        return json.loads(
            Path("data/cards", name).read_text(encoding="utf-8")
        )

    def test_gargoyle_ruling_describes_behind_check(self):
        """front_of_dark_ranged checks the tile BEHIND the Sorceress
        (effect_resolver._check_placement_condition)."""
        data = self._load("minion_gargoyle_sorceress.json")
        rulings = " ".join(data["rulings"])
        assert "directly behind her" in rulings
        assert "in front of her (one row toward the opponent's back row)" not in rulings

    def test_gargoyle_ruling_excludes_her_from_cost_discard_gain(self):
        """DM pool redesign: a cost-discard's per-Dark-Mage gain cannot
        count the Sorceress (she isn't on the board yet), but the grown
        POOL does pump her own Summon buff."""
        data = self._load("minion_gargoyle_sorceress.json")
        rulings = " ".join(data["rulings"])
        assert "does not count her" in rulings
        tips = " ".join(data["tips"])
        assert "it pumps her own buff" in tips

    def test_shadow_blaster_tip_places_gargoyle_in_front(self):
        data = self._load("minion_shadow_blaster.json")
        tips = " ".join(data["tips"])
        assert "Gargoyle Sorceress directly in FRONT of her" in tips
        assert "Gargoyle Sorceress directly BEHIND her" not in tips

    def test_stash_ruling_describes_pool_gain_first_buff_second(self):
        """DM pool redesign 2026-07: gain lands FIRST, then every friendly
        Dark Mage buffs by the pool total AFTER the gain."""
        data = self._load("magic_dark_matter_stash.json")
        first = data["rulings"][0]
        assert "FIRST" in first and "THEN" in first
        assert "AFTER that gain" in first
        assert "that Mage's OWN Dark Matter stacks" not in first
