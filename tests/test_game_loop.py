"""Tests for the game loop module -- GameResult, run_game, and random agent smoke test.

Covers:
  - GameResult dataclass fields and semantics
  - run_game() determinism, turn limits, and basic behavior
  - 1000-game smoke test proving engine stability
  - Win mechanism verification via focused integration test
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import ActionType, PlayerSide, TurnPhase
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
        # Magic/react fill (12)
        "fireball": 3,
        "holy_light": 3,
        "dark_drain": 3,
        "shield_block": 3,
    }
    # Total = 6 + 9 + 12 + 1 + 12 = 40

    deck = library.build_deck(card_counts)
    assert len(deck) == MIN_DECK_SIZE
    return deck, deck  # Same deck for both players (different shuffle per seed)


def _build_no_heal_decks(library: CardLibrary) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Build 40-card decks without healing cards.

    Excludes dark_drain, holy_light, holy_paladin, light_cleric, dark_mirror
    to prevent healing from counteracting sacrifice damage.
    """
    card_counts: dict[str, int] = {
        "fire_imp": 3,
        "shadow_stalker": 3,
        "dark_assassin": 3,
        "wind_archer": 3,
        "dark_sentinel": 3,
        "iron_guardian": 3,
        "shadow_knight": 3,
        "stone_golem": 3,
        "flame_wyrm": 3,
        "fireball": 3,
        "inferno": 3,
        "counter_spell": 3,
        "shield_block": 3,
        # 13 * 3 = 39, need 1 more; include 1 dark_drain (minimal heal)
        "dark_drain": 1,
    }
    deck = library.build_deck(card_counts)
    assert len(deck) == MIN_DECK_SIZE
    return deck, deck


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
        """Different seeds produce different game states (different HP outcomes)."""
        from grid_tactics.game_loop import run_game

        library = _load_library()
        deck_p1, deck_p2 = _build_test_decks(library)

        results = [
            run_game(seed=i, deck_p1=deck_p1, deck_p2=deck_p2, library=library)
            for i in range(50)
        ]
        # Different seeds should produce at least some variation in final HP
        hp_outcomes = {r.final_hp for r in results}
        assert len(hp_outcomes) > 1, (
            "All 50 seeds produced identical final HP -- RNG is not working"
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

        # Use a very low limit that won't produce a natural win
        result = run_game(
            seed=42, deck_p1=deck_p1, deck_p2=deck_p2,
            library=library, turn_limit=3,
        )
        # With turn_limit=3, no natural winner is possible
        assert result.winner is None
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
# Win mechanism integration test
# ---------------------------------------------------------------------------


class TestWinMechanism:
    """Verify the game loop correctly detects and reports wins.

    Random agents with standard decks rarely produce wins because healing
    effects negate sacrifice damage. These tests use no-heal decks and/or
    low starting HP to verify the win pathway works end-to-end through
    the normal game loop.
    """

    def test_win_via_low_hp_game(self):
        """A game where one player starts at 1 HP ends in a win via sacrifice."""
        from grid_tactics.game_state import GameState
        from grid_tactics.legal_actions import legal_actions
        from grid_tactics.action_resolver import resolve_action

        library = _load_library()
        deck_p1, deck_p2 = _build_no_heal_decks(library)

        # Set P2 to 1 HP so any sacrifice kills them
        state, rng = GameState.new_game(0, deck_p1, deck_p2)
        p2_low = replace(state.players[1], hp=1)
        state = replace(state, players=(state.players[0], p2_low))

        # Run the game loop manually (same logic as run_game)
        turn_limit = 2000
        while not state.is_game_over and state.turn_number <= turn_limit:
            actions = legal_actions(state, library)
            action = rng.choice(actions)
            state = resolve_action(state, action, library)

        # With P2 at 1 HP and a no-heal deck, a sacrifice should kill them
        assert state.is_game_over, (
            f"Game should have ended (P2 started at 1 HP). "
            f"Final HP: ({state.players[0].hp}, {state.players[1].hp})"
        )
        assert state.winner == PlayerSide.PLAYER_1

    def test_both_players_can_win(self):
        """Both P1 and P2 can win depending on game dynamics."""
        from grid_tactics.game_state import GameState
        from grid_tactics.legal_actions import legal_actions
        from grid_tactics.action_resolver import resolve_action

        library = _load_library()
        deck_p1, deck_p2 = _build_no_heal_decks(library)

        p1_wins = 0
        p2_wins = 0
        for seed in range(200):
            state, rng = GameState.new_game(seed, deck_p1, deck_p2)
            # Set both to 1 HP so first sacrifice wins
            p1_low = replace(state.players[0], hp=1)
            p2_low = replace(state.players[1], hp=1)
            state = replace(state, players=(p1_low, p2_low))

            while not state.is_game_over and state.turn_number <= 2000:
                actions = legal_actions(state, library)
                action = rng.choice(actions)
                state = resolve_action(state, action, library)

            if state.is_game_over and state.winner == PlayerSide.PLAYER_1:
                p1_wins += 1
            elif state.is_game_over and state.winner == PlayerSide.PLAYER_2:
                p2_wins += 1

        # Both players should win at least once across 200 games
        assert p1_wins >= 1, "P1 never won across 200 low-HP games"
        assert p2_wins >= 1, "P2 never won across 200 low-HP games"

    def test_game_over_stops_loop(self):
        """Once game is over, the loop terminates (no further actions processed)."""
        from grid_tactics.game_state import GameState
        from grid_tactics.legal_actions import legal_actions
        from grid_tactics.action_resolver import resolve_action
        from grid_tactics.actions import sacrifice_action
        from grid_tactics.minion import MinionInstance
        from grid_tactics.board import Board

        library = _load_library()
        deck_p1, deck_p2 = _build_test_decks(library)

        # Set up a state where a sacrifice is about to happen
        state, rng = GameState.new_game(42, deck_p1, deck_p2)

        # Place a P1 minion on P2's back row (row 4) ready to sacrifice
        fire_imp_id = library.get_numeric_id("fire_imp")
        minion = MinionInstance(
            instance_id=0,
            card_numeric_id=fire_imp_id,
            owner=PlayerSide.PLAYER_1,
            position=(4, 0),
            current_health=1,
        )
        new_board = state.board.place(4, 0, 0)
        # Set P2 to 1 HP
        p2_low = replace(state.players[1], hp=1)
        state = replace(
            state,
            board=new_board,
            minions=(minion,),
            next_minion_id=1,
            players=(state.players[0], p2_low),
        )

        # Manually apply sacrifice
        sac = sacrifice_action(minion_id=0)
        state = resolve_action(state, sac, library)

        # Game should be over now
        assert state.is_game_over
        assert state.winner == PlayerSide.PLAYER_1

        # legal_actions on a game_over state should only return PASS
        actions = legal_actions(state, library)
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.PASS


# ---------------------------------------------------------------------------
# 1000-game smoke test
# ---------------------------------------------------------------------------


class TestSmoke:
    """Smoke test running 1000 complete games."""

    def test_smoke_1000_games(self):
        """1000 games with seeds 0-999 all complete without exception.

        Validates:
          - All complete without crash
          - At least some games deal player damage (sacrifice works)
          - Every game has turn_count >= 1
          - Every game has final_hp as a 2-tuple
          - No game has turn_count == 0

        Note: With random agents and the starter card pool (which includes
        healing cards), most games end at the turn limit. The win mechanism
        is separately verified in TestWinMechanism.
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

        # At least some games dealt player damage (proves sacrifice mechanics work)
        games_with_damage = [
            r for r in results
            if r.final_hp[0] < 20 or r.final_hp[1] < 20
        ]
        assert len(games_with_damage) >= 1, (
            "No games dealt any player damage -- sacrifice mechanics not working"
        )

        # Result turn_count <= DEFAULT_TURN_LIMIT
        for i, r in enumerate(results):
            assert r.turn_count <= DEFAULT_TURN_LIMIT, (
                f"Game {i} exceeded turn limit: turn_count={r.turn_count}"
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
