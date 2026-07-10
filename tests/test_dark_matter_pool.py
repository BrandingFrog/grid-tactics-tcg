"""Dark Matter pool redesign (2026-07) regression tests.

Dark Matter is a PLAYER-level stacking resource (Player.dark_matter):

  - grant_dark_matter credits the OWNING PLAYER's pool — +`amount` per
    friendly LIVE Dark Mage on board (scale_with="dark_mages") or flat.
  - "Dark Mage" = tribe exactly "Mage" AND element DARK (single predicate
    ``cards.is_dark_mage``). Composite tribes (Ratchanter "Mage Rat",
    Grave Caller "Mage Undead") do NOT qualify.
  - scale_with="dark_matter" / "player_dark_matter" effects read the
    CASTER PLAYER's pool.
  - Dark Matter Stash order of operations: gain FIRST, buff SECOND —
    the buff magnitude is the pool AFTER the gain.
  - Minions never hold DM: MinionInstance.dark_matter_stacks is
    deprecated (always 0); TRANSFORM does not touch the player pool.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from grid_tactics.actions import Action, pass_action
from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.cards import is_dark_mage
from grid_tactics.effect_resolver import resolve_effect
from grid_tactics.engine_events import EVT_DARK_MATTER_CHANGE, EventStream
from grid_tactics.enums import (
    ActionType,
    EffectType,
    PlayerSide,
    ReactContext,
    TargetType,
    TriggerType,
    TurnPhase,
)
from grid_tactics.game_state import GameState
from grid_tactics.legal_actions import effective_mana_cost
from grid_tactics.minion import MinionInstance
from grid_tactics.player import Player
from grid_tactics.react_stack import ReactEntry, handle_react_action
from grid_tactics.types import STARTING_HP


@pytest.fixture(scope="module")
def library():
    return CardLibrary.from_directory(Path("data/cards"))


def _make_state(minions, p1_dm=0, p2_dm=0, phase=TurnPhase.ACTION, **kwargs):
    board = Board.empty()
    for m in minions:
        board = board.place(m.position[0], m.position[1], m.instance_id)
    next_id = max((m.instance_id for m in minions), default=-1) + 1
    p1 = Player(
        side=PlayerSide.PLAYER_1, hp=STARTING_HP,
        current_mana=10, max_mana=10, hand=(), deck=(), grave=(),
        dark_matter=p1_dm,
    )
    p2 = Player(
        side=PlayerSide.PLAYER_2, hp=STARTING_HP,
        current_mana=10, max_mana=10, hand=(), deck=(), grave=(),
        dark_matter=p2_dm,
    )
    return GameState(
        board=board,
        players=(p1, p2),
        active_player_idx=0,
        phase=phase,
        turn_number=1,
        seed=42,
        minions=tuple(minions),
        next_minion_id=next_id,
        **kwargs,
    )


def _minion(library, card_id, instance_id, pos, owner=PlayerSide.PLAYER_1):
    numeric_id = library.get_numeric_id(card_id)
    card_def = library.get_by_id(numeric_id)
    return MinionInstance(
        instance_id=instance_id,
        card_numeric_id=numeric_id,
        owner=owner,
        position=pos,
        current_health=card_def.health,
    )


def _cast_stash(state, library, event_collector=None):
    """Push a Dark Matter Stash magic_cast originator and drain the react
    window with a PASS — the real resolution path (react_stack LIFO)."""
    stash_id = library.get_numeric_id("dark_matter_stash")
    stash = library.get_by_id(stash_id)
    payload = tuple(
        (i, None, int(PlayerSide.PLAYER_1))
        for i, e in enumerate(stash.effects)
        if e.trigger == TriggerType.ON_PLAY
    )
    originator = ReactEntry(
        player_idx=0, card_index=-1, card_numeric_id=stash_id,
        is_originator=True, origin_kind="magic_cast",
        effect_payload=payload,
    )
    state = replace(
        state,
        phase=TurnPhase.REACT,
        react_player_idx=1,
        react_context=ReactContext.AFTER_ACTION,
        react_return_phase=TurnPhase.ACTION,
        react_stack=(originator,),
    )
    return handle_react_action(
        state, pass_action(), library, event_collector=event_collector,
    )


# ---------------------------------------------------------------------------
# The Dark Mage predicate
# ---------------------------------------------------------------------------


class TestDarkMagePredicate:
    @pytest.mark.parametrize("card_id,expected", [
        ("shadow_blaster", True),        # Mage / dark
        ("eclipse_shade", True),         # Mage / dark
        ("gargoyle_sorceress", True),    # Mage / dark
        ("matter_possessed", True),      # Mage / dark
        ("erebus", True),                # Mage / dark
        ("ratchanter", False),           # Mage Rat — composite tribe
        ("grave_caller", False),         # Mage Undead — composite tribe
        ("dark_matter_battery", False),  # Machine / dark
        ("rat", False),                  # Rat / earth
        ("dark_matter_stash", False),    # magic card, not a minion
    ])
    def test_predicate(self, library, card_id, expected):
        card_def = library.get_by_id(library.get_numeric_id(card_id))
        assert is_dark_mage(card_def) is expected


# ---------------------------------------------------------------------------
# Dark Matter Stash — play (gain FIRST, buff SECOND)
# ---------------------------------------------------------------------------


class TestStashPlay:
    def test_zero_dark_mages_is_full_noop(self, library):
        """Only a Ratchanter (Mage Rat — NOT a Dark Mage) on board: no
        gain, no buff."""
        ratchanter = _minion(library, "ratchanter", 0, (0, 0))
        state = _make_state([ratchanter], p1_dm=0)
        result = _cast_stash(state, library)

        assert result.players[0].dark_matter == 0
        rc = result.get_minion(0)
        assert rc.attack_bonus == 0

    def test_one_dark_mage(self, library):
        """One Dark Mage, empty pool: gain +1 first, then buff +1/+1."""
        blaster = _minion(library, "shadow_blaster", 0, (0, 0))
        base_hp = blaster.current_health
        state = _make_state([blaster], p1_dm=0)
        result = _cast_stash(state, library)

        assert result.players[0].dark_matter == 1
        b = result.get_minion(0)
        assert b.attack_bonus == 1
        assert b.current_health == base_hp + 1

    def test_three_dark_mages_with_banked_pool(self, library):
        """3 Dark Mages, pool 2 → gain lands FIRST (pool 5), then EACH
        Dark Mage buffs by the post-gain total (+5/+5)."""
        blasters = [
            _minion(library, "shadow_blaster", i, (0, i)) for i in range(3)
        ]
        base_hp = blasters[0].current_health
        state = _make_state(blasters, p1_dm=2)
        result = _cast_stash(state, library)

        assert result.players[0].dark_matter == 5
        for i in range(3):
            b = result.get_minion(i)
            assert b.attack_bonus == 5, "buff must use the pool AFTER the gain"
            assert b.current_health == base_hp + 5
            assert b.dark_matter_stacks == 0, "minions never hold DM"

    def test_ratchanter_excluded_from_gain_and_buff(self, library):
        """Ratchanter (Mage Rat) next to a true Dark Mage: gain counts
        only the Dark Mage, and Ratchanter receives NO buff."""
        blaster = _minion(library, "shadow_blaster", 0, (0, 0))
        ratchanter = _minion(library, "ratchanter", 1, (0, 1))
        state = _make_state([blaster, ratchanter], p1_dm=0)
        result = _cast_stash(state, library)

        assert result.players[0].dark_matter == 1  # blaster only
        assert result.get_minion(0).attack_bonus == 1
        assert result.get_minion(1).attack_bonus == 0  # Ratchanter skipped

    def test_gain_emits_dark_matter_change_event(self, library):
        blaster = _minion(library, "shadow_blaster", 0, (0, 0))
        state = _make_state([blaster], p1_dm=3)
        stream = EventStream()
        _cast_stash(state, library, event_collector=stream)

        dm_events = [e for e in stream.events if e.type == EVT_DARK_MATTER_CHANGE]
        assert len(dm_events) == 1
        assert dm_events[0].payload["player_idx"] == 0
        assert dm_events[0].payload["prev"] == 3
        assert dm_events[0].payload["new"] == 4
        assert dm_events[0].payload["delta"] == 1


# ---------------------------------------------------------------------------
# Dark Matter Stash — discard trigger
# ---------------------------------------------------------------------------


class TestStashDiscard:
    def _discard_effect(self, library):
        stash = library.get_by_id(library.get_numeric_id("dark_matter_stash"))
        effects = [
            e for e in stash.effects if e.trigger == TriggerType.ON_DISCARD
        ]
        assert len(effects) == 1
        eff = effects[0]
        assert eff.effect_type == EffectType.GRANT_DARK_MATTER
        assert eff.target == TargetType.OWNER_PLAYER
        assert eff.scale_with == "dark_mages"
        return eff

    def test_discard_grants_one_per_dark_mage(self, library):
        blasters = [
            _minion(library, "shadow_blaster", i, (0, i)) for i in range(2)
        ]
        state = _make_state(blasters, p1_dm=1)
        eff = self._discard_effect(library)
        result = resolve_effect(
            state, eff, (0, 0), PlayerSide.PLAYER_1, library,
            contract_source="trigger:on_discard",
        )
        assert result.players[0].dark_matter == 3  # 1 + 2 Dark Mages
        # No buff on discard — only the gain fires.
        assert result.get_minion(0).attack_bonus == 0
        # Minions still carry no stacks.
        assert all(m.dark_matter_stacks == 0 for m in result.minions)

    def test_discard_with_no_dark_mages_is_noop(self, library):
        ratchanter = _minion(library, "ratchanter", 0, (0, 0))
        state = _make_state([ratchanter], p1_dm=2)
        eff = self._discard_effect(library)
        result = resolve_effect(
            state, eff, (0, 0), PlayerSide.PLAYER_1, library,
            contract_source="trigger:on_discard",
        )
        assert result is state  # identity-preserving silent no-op
        assert result.players[0].dark_matter == 2


# ---------------------------------------------------------------------------
# scale_with reads the caster PLAYER's pool
# ---------------------------------------------------------------------------


class TestScaleWithReadsPlayerPool:
    def test_barrage_damage_scales_with_pool(self, library):
        """Dark Matter Barrage: 5 + caster player's pool, regardless of
        any minion stacks (which are always 0 now)."""
        enemy = _minion(library, "rat", 0, (3, 3), owner=PlayerSide.PLAYER_2)
        state = _make_state([enemy], p1_dm=4)
        barrage = library.get_by_id(library.get_numeric_id("dark_matter_barrage"))
        damage = barrage.effects[0]
        assert damage.scale_with == "dark_matter"

        result = resolve_effect(
            state, damage, (0, 0), PlayerSide.PLAYER_1, library,
            contract_source="trigger:on_play",
        )
        assert result.get_minion(0).current_health == 10 - (5 + 4)

    def test_opponent_pool_does_not_contribute(self, library):
        enemy = _minion(library, "rat", 0, (3, 3), owner=PlayerSide.PLAYER_2)
        state = _make_state([enemy], p1_dm=0, p2_dm=9)
        barrage = library.get_by_id(library.get_numeric_id("dark_matter_barrage"))
        result = resolve_effect(
            state, barrage.effects[0], (0, 0), PlayerSide.PLAYER_1, library,
            contract_source="trigger:on_play",
        )
        assert result.get_minion(0).current_health == 10 - 5

    def test_battery_decay_damage_reads_owner_pool(self, library):
        """Dark Matter Battery's Decay damage = owner's pool (source must
        be alive)."""
        battery = _minion(library, "dark_matter_battery", 0, (0, 2))
        state = _make_state([battery], p1_dm=6, phase=TurnPhase.END_OF_TURN)
        effect = library.get_by_id(battery.card_numeric_id).effects[0]
        result = resolve_effect(
            state, effect, battery.position, PlayerSide.PLAYER_1, library,
            source_minion_id=battery.instance_id,
            contract_source="trigger:on_end_of_turn",
        )
        assert result.players[1].hp == STARTING_HP - 6

    def test_dead_source_still_fizzles(self, library):
        """A dead Battery's queued trigger fizzles even with a fat pool."""
        battery = replace(
            _minion(library, "dark_matter_battery", 0, (0, 2)),
            current_health=0,
        )
        state = _make_state([], p1_dm=8, phase=TurnPhase.END_OF_TURN)
        state = replace(state, minions=(battery,))
        effect = library.get_by_id(battery.card_numeric_id).effects[0]
        result = resolve_effect(
            state, effect, battery.position, PlayerSide.PLAYER_1, library,
            source_minion_id=battery.instance_id,
            contract_source="trigger:on_end_of_turn",
        )
        assert result is state
        assert result.players[1].hp == STARTING_HP

    def test_gargoyle_player_dark_matter_reads_pool(self, library):
        """scale_with='player_dark_matter' (Gargoyle Sorceress) also reads
        the pool."""
        gargoyle = _minion(library, "gargoyle_sorceress", 0, (1, 2))
        state = _make_state([gargoyle], p1_dm=4, phase=TurnPhase.REACT)
        buff = library.get_by_id(gargoyle.card_numeric_id).effects[0]
        assert buff.scale_with == "player_dark_matter"
        result = resolve_effect(
            state, buff, gargoyle.position, PlayerSide.PLAYER_1, library,
            source_minion_id=gargoyle.instance_id,
            contract_source="trigger:on_summon",
        )
        assert result.get_minion(0).attack_bonus == 4

    def test_erebus_cost_reduction_reads_pool(self, library):
        erebus = library.get_by_id(library.get_numeric_id("erebus"))
        state = _make_state([], p1_dm=15)
        assert effective_mana_cost(erebus, state, 0) == 5
        state = _make_state([], p1_dm=25)
        assert effective_mana_cost(erebus, state, 0) == 0
        # Reading never consumes.
        assert state.players[0].dark_matter == 25

    def test_ratchanter_activation_buff_scales_with_pool(self, library):
        """Ratchanter's conjure_rat_and_buff magnitude = 1 + owner pool."""
        from grid_tactics.action_resolver import _apply_activate_ability

        rat = _minion(library, "rat", 0, (4, 0))
        ratchanter = _minion(library, "ratchanter", 1, (4, 2))
        state = _make_state([rat, ratchanter], p1_dm=3)
        result = _apply_activate_ability(
            state,
            Action(action_type=ActionType.ACTIVATE_ABILITY, minion_id=1),
            library,
        )
        buffed = result.get_minion(0)
        assert buffed.attack_bonus == 4       # 1 + pool(3)
        assert buffed.max_health_bonus == 4
        # Pool untouched — the ability reads, never spends.
        assert result.players[0].dark_matter == 3


# ---------------------------------------------------------------------------
# TRANSFORM leaves the player pool alone
# ---------------------------------------------------------------------------


class TestTransformAndPool:
    def test_transform_resets_nothing_dm_related_on_player_pool(self, library):
        from grid_tactics.action_resolver import _apply_transform

        bones = _minion(library, "reanimated_bones", 0, (1, 1))
        state = _make_state([bones], p1_dm=7)
        result = _apply_transform(
            state,
            Action(
                action_type=ActionType.TRANSFORM,
                minion_id=0,
                transform_target="grave_caller",
            ),
            library,
        )
        # The minion is fully reset (incl. the deprecated stacks field)...
        transformed = result.get_minion(0)
        assert transformed.card_numeric_id == library.get_numeric_id("grave_caller")
        assert transformed.dark_matter_stacks == 0
        # ...but the PLAYER pool is never RESET by a transform. It actually
        # GROWS by 1 now: transform-as-summon (user 2026-07-10) fires Grave
        # Caller's 'Summon: Dark Matter +1'.
        assert result.players[0].dark_matter == 8


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestPoolSerialization:
    def test_round_trip(self, library):
        state = _make_state([], p1_dm=4, p2_dm=11)
        d = state.to_dict()
        assert d["players"][0]["dark_matter"] == 4
        assert d["players"][1]["dark_matter"] == 11
        restored = GameState.from_dict(d)
        assert restored.players[0].dark_matter == 4
        assert restored.players[1].dark_matter == 11

    def test_legacy_dict_without_key_defaults_to_zero(self):
        state = _make_state([], p1_dm=0)
        d = state.to_dict()
        for p in d["players"]:
            p.pop("dark_matter", None)
        restored = GameState.from_dict(d)
        assert restored.players[0].dark_matter == 0
        assert restored.players[1].dark_matter == 0
