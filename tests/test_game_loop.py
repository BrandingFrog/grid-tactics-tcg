"""Tests for the game loop module -- GameResult, run_game, and random agent smoke test.

TDD RED: All tests should fail because game_loop.py does not exist yet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import PlayerSide
from grid_tactics.types import DEFAULT_TURN_LIMIT, MAX_COPIES_PER_DECK, MIN_DECK_SIZE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "cards"


def _load_library() -> CardLibrary:
    """Load the real card library from data/cards/."""
    return CardLibrary.from_directory(DATA_DIR)


def _build_test_decks(library: CardLibrary) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Build two valid 40-card decks from the starter pool.

    Uses a mix of minion cards so games have meaningful combat actions.
    Each card appears up to MAX_COPIES_PER_DECK (3) times.  Fill to
    MIN_DECK_SIZE by repeating eligible cards.
    """
    # Use minion-heavy decks for interesting game play
    card_counts: dict[str, int] = {
        # 1-cost (2 cards * 3 = 6)
        "fire_imp": 3,
        "shadow_stalker": 3,
        # 2-cost (3 cards * 3 = 9)
        "dark_assassin": 3,
        "light_cleric": 3,
        "wind_archer": 3,
        # 3-cost (4 cards * 3 = 12)
        "dark_sentinel": 3,
        "holy_paladin": 3,
        "iron_guardian": 3,
        "shadow_knight": 3,
        # 4-cost (1 card * 1 = 1)
        "stone_golem": 1,
    }
    # Total = 6 + 9 + 12 + 1 = 28 minions
    # Fill remaining 12 with magic/react cards (3 each)
    card_counts["fireball"] = 3
    card_counts["holy_light"] = 3
    card_counts["dark_drain"] = 3
    card_counts["shield_block"] = 3
    # Total = 28 + 12 = 40

    deck = library.build_deck(card_counts)
    assert len(deck) == MIN_DECK_SIZE
    return deck, deck  # Same deck for both players (different shuffle per seed)


# ---------------------------------------------------------------------------
# GameResult tests
# ---------------------------------------------------------------------------


class TestGameResult:
    """Test the GameResult dataclass."""

    def test_game_result_fields(self):
        """GameResult has all expected fields."""
        from grid_tactics.game_loop import GameResult

        result = GameResult(
            winner=PlayerSide.PLAYER_1,
            turn_count=10,
            final_hp=(5, 0),
            is_draw=False,
            reason="hp_zero",
        )
        assert result.winner == PlayerSide.PLAYER_1
        assert result.turn_count == 10
        assert result.final_hp == (5, 0)
        assert result.is_draw is False
        assert result.reason == "hp_zero"

    def test_game_result_is_draw(self):
        """is_draw is True when winner is None and game ended."""
        from grid_tactics.game_loop import GameResult

        result = GameResult(
            winner=None,
            turn_count=200,
            final_hp=(3, 3),
            is_draw=True,
            reason="turn_limit",
        )
        assert result.is_draw is True
        assert result.winner is None


# ---------------------------------------------------------------------------
# run_game tests
# ---------------------------------------------------------------------------


class TestRunGame:
    """Test the run_game function."""

    def test_run_game_returns_result(self):
        """run_game with seed=42 returns a GameResult with turn_count > 0."""
        from grid_tactics.game_loop import GameResult, run_game

        library = _load_library()
        deck_p1, deck_p2 = _build_test_decks(library)
        result = run_game(seed=42, deck_p1=deck_p1, deck_p2=deck_p2, library=library)

        assert isinstance(result, GameResult)
        assert result.turn_count > 0

    def test_run_game_deterministic(self):
        """Same seed + same decks -> identical result."""
        from grid_tactics.game_loop import run_game

        library = _load_library()
        deck_p1, deck_p2 = _build_test_decks(library)

        result1 = run_game(seed=42, deck_p1=deck_p1, deck_p2=deck_p2, library=library)
        result2 = run_game(seed=42, deck_p1=deck_p1, deck_p2=deck_p2, library=library)

        assert result1.winner == result2.winner
        assert result1.turn_count == result2.turn_count
        assert result1.final_hp == result2.final_hp
        assert result1.is_draw == result2.is_draw
        assert result1.reason == result2.reason

    def test_run_game_different_seeds(self):
        """Different seeds produce different results (at least not all identical)."""
        from grid_tactics.game_loop import run_game

        library = _load_library()
        deck_p1, deck_p2 = _build_test_decks(library)

        results = [
            run_game(seed=i, deck_p1=deck_p1, deck_p2=deck_p2, library=library)
            for i in range(10)
        ]
        # Not all results should be identical
        turn_counts = {r.turn_count for r in results}
        winners = {r.winner for r in results}
        assert len(turn_counts) > 1 or len(winners) > 1, (
            "All 10 seeds produced identical results -- RNG is not working"
        )

    def test_run_game_respects_turn_limit(self):
        """With turn_limit=5, game ends by turn 5."""
        from grid_tactics.game_loop import run_game

        library = _load_library()
        deck_p1, deck_p2 = _build_test_decks(library)

        result = run_game(
            seed=42, deck_p1=deck_p1, deck_p2=deck_p2,
            library=library, turn_limit=5,
        )
        assert result.turn_count <= 5

    def test_run_game_turn_limit_is_draw(self):
        """When turn limit reached and no winner, is_draw is True."""
        from grid_tactics.game_loop import run_game

        library = _load_library()
        deck_p1, deck_p2 = _build_test_decks(library)

        # Use a very low limit that's unlikely to produce a natural win
        result = run_game(
            seed=42, deck_p1=deck_p1, deck_p2=deck_p2,
            library=library, turn_limit=3,
        )
        # If no natural winner by turn 3, this should be a draw
        if result.winner is None:
            assert result.is_draw is True
            assert result.reason == "turn_limit"

    def test_run_game_final_hp_tuple(self):
        """Result final_hp is a 2-tuple."""
        from grid_tactics.game_loop import run_game

        library = _load_library()
        deck_p1, deck_p2 = _build_test_decks(library)

        result = run_game(seed=42, deck_p1=deck_p1, deck_p2=deck_p2, library=library)
        assert isinstance(result.final_hp, tuple)
        assert len(result.final_hp) == 2


# ---------------------------------------------------------------------------
# 1000-game smoke test
# ---------------------------------------------------------------------------


class TestSmoke:
    """Smoke test running 1000 complete games."""

    def test_smoke_1000_games(self):
        """1000 games with seeds 0-999 all complete without exception.

        Validates:
          - All complete without crash
          - At least one win (not all draws)
          - At least one natural termination before turn limit
          - Every game has turn_count >= 1
          - Every game has final_hp as a 2-tuple
        """
        from grid_tactics.game_loop import run_game

        library = _load_library()
        deck_p1, deck_p2 = _build_test_decks(library)

        results = []
        for seed in range(1000):
            result = run_game(
                seed=seed, deck_p1=deck_p1, deck_p2=deck_p2, library=library,
            )
            results.append(result)

        # All completed (if we got here without exception, they all finished)
        assert len(results) == 1000

        # At least 1 game ends in a win (not all draws)
        wins = [r for r in results if r.winner is not None]
        assert len(wins) >= 1, "All 1000 games were draws -- no wins at all"

        # At least 1 game ends before turn limit (natural termination)
        natural_ends = [r for r in results if r.turn_count < DEFAULT_TURN_LIMIT]
        assert len(natural_ends) >= 1, (
            "All 1000 games hit the turn limit -- no natural termination"
        )

        # Every game has turn_count >= 1
        for i, r in enumerate(results):
            assert r.turn_count >= 1, f"Game {i} has turn_count={r.turn_count}"

        # Every game has final_hp as a 2-tuple
        for i, r in enumerate(results):
            assert isinstance(r.final_hp, tuple), (
                f"Game {i} final_hp is not a tuple: {type(r.final_hp)}"
            )
            assert len(r.final_hp) == 2, (
                f"Game {i} final_hp has {len(r.final_hp)} elements"
            )
