"""Tests for Player dataclass -- mana system, HP, hand management.

Covers decisions D-05 through D-09:
  D-05: Starting mana pool = 1
  D-06: Mana regenerates +1 per turn
  D-07: Maximum mana cap = 10
  D-08: Unspent mana carries over (banking)
  D-09: Starting HP = 20
"""

import dataclasses

import pytest

from grid_tactics.enums import PlayerSide
from grid_tactics.types import (
    MAX_MANA_CAP,
    STARTING_HP,
    STARTING_MANA,
)


# ---------------------------------------------------------------------------
# Player construction
# ---------------------------------------------------------------------------


class TestPlayerConstruction:
    def test_new_player_defaults(self, make_player):
        """Player.new(side, deck) has hp=20, mana=1, empty hand, empty graveyard."""
        from grid_tactics.player import Player

        deck = (1, 2, 3, 4, 5)
        p = Player.new(PlayerSide.PLAYER_1, deck)
        assert p.side == PlayerSide.PLAYER_1
        assert p.hp == STARTING_HP
        assert p.current_mana == STARTING_MANA
        assert p.max_mana == STARTING_MANA
        assert p.hand == ()
        assert p.deck == deck
        assert p.graveyard == ()

    def test_starting_hp(self, make_player):
        """Player starts with hp=100 (audit-followup: scaled from 20)."""
        from grid_tactics.player import Player

        p = Player.new(PlayerSide.PLAYER_2, ())
        assert p.hp == 100

    def test_player_is_frozen(self, make_player):
        """Assigning to player.hp raises FrozenInstanceError."""
        p = make_player()
        with pytest.raises(dataclasses.FrozenInstanceError):
            p.hp = 99

    def test_player_collections_are_tuples(self, make_player):
        """hand, deck, graveyard are all tuple type."""
        p = make_player(hand=(1,), deck=(2, 3), graveyard=(4,))
        assert isinstance(p.hand, tuple)
        assert isinstance(p.deck, tuple)
        assert isinstance(p.graveyard, tuple)


# ---------------------------------------------------------------------------
# Mana system
# ---------------------------------------------------------------------------


class TestManaSystem:
    def test_starting_mana(self, make_player):
        """New player has current_mana=1, max_mana=1 (D-05)."""
        from grid_tactics.player import Player

        p = Player.new(PlayerSide.PLAYER_1, ())
        assert p.current_mana == 1
        assert p.max_mana == 1

    def test_mana_regen_no_spend(self, make_player):
        """After regen, current_mana increases by 1 (D-06)."""
        p = make_player(current_mana=1, max_mana=1)
        p2 = p.regenerate_mana()
        assert p2.current_mana == 2

    def test_mana_regen_after_spend(self, make_player):
        """Spend 1, regen, current = 0 + 1 = 1."""
        p = make_player(current_mana=1, max_mana=1)
        p2 = p.spend_mana(1)
        assert p2.current_mana == 0
        p3 = p2.regenerate_mana()
        assert p3.current_mana == 1

    def test_mana_banking(self, make_player):
        """Spend 0 for 3 turns, current = 1 + 1 + 1 + 1 = 4 (D-08)."""
        from grid_tactics.player import Player

        p = Player.new(PlayerSide.PLAYER_1, ())
        assert p.current_mana == 1
        p = p.regenerate_mana()
        assert p.current_mana == 2
        p = p.regenerate_mana()
        assert p.current_mana == 3
        p = p.regenerate_mana()
        assert p.current_mana == 4

    def test_mana_cap(self, make_player):
        """After enough turns without spending, mana caps at 10 (D-07)."""
        p = make_player(current_mana=9, max_mana=1)
        p2 = p.regenerate_mana()
        assert p2.current_mana == 10
        p3 = p2.regenerate_mana()
        assert p3.current_mana == 10  # capped, not 11

    def test_mana_cap_banking_scenario(self, make_player):
        """Have 9 mana, regen gives 10 (not 11)."""
        p = make_player(current_mana=9, max_mana=1)
        p2 = p.regenerate_mana()
        assert p2.current_mana == 10
        assert p2.current_mana <= MAX_MANA_CAP

    def test_mana_regen_after_partial_spend(self, make_player):
        """Have 5, spend 3, regen: 2 + 1 = 3."""
        p = make_player(current_mana=5, max_mana=1)
        p2 = p.spend_mana(3)
        assert p2.current_mana == 2
        p3 = p2.regenerate_mana()
        assert p3.current_mana == 3

    def test_spend_mana_success(self, make_player):
        """current=5, spend 3, result current=2."""
        p = make_player(current_mana=5, max_mana=1)
        p2 = p.spend_mana(3)
        assert p2.current_mana == 2

    def test_spend_mana_insufficient(self, make_player):
        """current=2, spend 3 raises ValueError."""
        p = make_player(current_mana=2, max_mana=1)
        with pytest.raises(ValueError, match="Insufficient mana"):
            p.spend_mana(3)

    def test_spend_mana_negative_raises(self, make_player):
        """spend(-1) raises ValueError."""
        p = make_player(current_mana=5, max_mana=1)
        with pytest.raises(ValueError, match="negative"):
            p.spend_mana(-1)

    def test_mana_multi_turn_sequence(self, make_player):
        """Simulate 12 turns with varied spending, verify each step."""
        from grid_tactics.player import Player

        p = Player.new(PlayerSide.PLAYER_1, ())
        # Turn 1: start with 1
        assert p.current_mana == 1
        # Turn 2: regen to 2
        p = p.regenerate_mana()
        assert p.current_mana == 2
        # Turn 3: spend 1, regen -> 1 + 1 = 2
        p = p.spend_mana(1)
        p = p.regenerate_mana()
        assert p.current_mana == 2
        # Turn 4: regen to 3
        p = p.regenerate_mana()
        assert p.current_mana == 3
        # Turn 5: spend all 3, regen -> 0 + 1 = 1
        p = p.spend_mana(3)
        p = p.regenerate_mana()
        assert p.current_mana == 1
        # Turns 6-11: bank for 6 regens -> 1+6 = 7
        for _ in range(6):
            p = p.regenerate_mana()
        assert p.current_mana == 7
        # Turns 12-14: bank 3 more -> 7+3 = 10 (cap)
        for _ in range(3):
            p = p.regenerate_mana()
        assert p.current_mana == 10
        # Turn 15: regen at cap -> still 10
        p = p.regenerate_mana()
        assert p.current_mana == 10
        # Turn 16: spend 5, regen -> 5+1 = 6
        p = p.spend_mana(5)
        p = p.regenerate_mana()
        assert p.current_mana == 6


# ---------------------------------------------------------------------------
# Hand management
# ---------------------------------------------------------------------------


class TestHandManagement:
    def test_draw_card(self, make_player):
        """deck=(10,20,30), draw -> hand=(10,), deck=(20,30)."""
        p = make_player(deck=(10, 20, 30))
        p2, card = p.draw_card()
        assert card == 10
        assert p2.hand == (10,)
        assert p2.deck == (20, 30)

    def test_draw_card_preserves_immutability(self, make_player):
        """Original player unchanged after draw."""
        p = make_player(deck=(10, 20, 30))
        p2, _ = p.draw_card()
        assert p.hand == ()
        assert p.deck == (10, 20, 30)
        assert p2.hand == (10,)

    def test_draw_from_empty_deck_raises(self, make_player):
        """Empty deck raises ValueError."""
        p = make_player(deck=())
        with pytest.raises(ValueError, match="Cannot draw from empty deck"):
            p.draw_card()

    def test_draw_multiple_cards(self, make_player):
        """Draw 3 times, hand has 3 cards in deck-top order."""
        p = make_player(deck=(10, 20, 30, 40))
        p, c1 = p.draw_card()
        p, c2 = p.draw_card()
        p, c3 = p.draw_card()
        assert (c1, c2, c3) == (10, 20, 30)
        assert p.hand == (10, 20, 30)
        assert p.deck == (40,)

    def test_discard_from_hand(self, make_player):
        """hand=(10,20), discard(10) -> hand=(20,), graveyard=(10,)."""
        p = make_player(hand=(10, 20))
        p2 = p.discard_from_hand(10)
        assert p2.hand == (20,)
        assert p2.graveyard == (10,)

    def test_discard_invalid_card_raises(self, make_player):
        """Discarding card not in hand raises ValueError."""
        p = make_player(hand=(10, 20))
        with pytest.raises(ValueError, match="not in hand"):
            p.discard_from_hand(99)


# ---------------------------------------------------------------------------
# HP / damage
# ---------------------------------------------------------------------------


class TestHP:
    def test_take_damage(self, make_player):
        """hp=20, take 5 -> hp=15."""
        p = make_player(hp=20)
        p2 = p.take_damage(5)
        assert p2.hp == 15

    def test_take_damage_to_zero(self, make_player):
        """hp=5, take 5 -> hp=0."""
        p = make_player(hp=5)
        p2 = p.take_damage(5)
        assert p2.hp == 0

    def test_take_damage_below_zero(self, make_player):
        """hp=3, take 5 -> hp=-2 (allowed)."""
        p = make_player(hp=3)
        p2 = p.take_damage(5)
        assert p2.hp == -2

    def test_is_alive(self, make_player):
        """hp=1 -> True, hp=0 -> False, hp=-1 -> False."""
        assert make_player(hp=1).is_alive is True
        assert make_player(hp=0).is_alive is False
        assert make_player(hp=-1).is_alive is False
