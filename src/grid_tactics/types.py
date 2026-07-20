"""Type aliases and constants for grid geometry."""

# Grid dimensions (per D-01, D-02: fixed 5x5 grid, all columns equal)
GRID_ROWS: int = 5
GRID_COLS: int = 5
GRID_SIZE: int = GRID_ROWS * GRID_COLS  # 25 cells total

# Position is always (row, col) -- never (x, y) to avoid confusion
Position = tuple[int, int]

# Row ownership boundaries (per D-01)
PLAYER_1_ROWS: tuple[int, ...] = (0, 1)  # Rows 0-1 = Player 1
PLAYER_2_ROWS: tuple[int, ...] = (3, 4)  # Rows 3-4 = Player 2
NEUTRAL_ROW: int = 2  # Row 2 = No-man's-land

# Mana constants (per D-05 through D-08)
STARTING_MANA: int = 1
MANA_REGEN_PER_TURN: int = 1
MAX_MANA_CAP: int = 10

# Player constants (per D-09, D-10)
STARTING_HP: int = 100
STARTING_HAND_SIZE: int = 5  # legacy default
STARTING_HAND_P1: int = 3    # Player 1 (goes first) draws fewer
STARTING_HAND_P2: int = 4    # Player 2 (goes second) draws more to compensate

# Maximum hand size (turn-structure redesign 2026-07). Any draw that would
# exceed this cap "overdraw-burns": the drawn card goes to the Exhaust Pile
# (revealed) instead of the hand. Applies to ALL draw paths (turn-start
# draw, card effects, Handshake draw, tutor/conjure-to-hand).
MAX_HAND_SIZE: int = 10

# ---------------------------------------------------------------------------
# Phase 2: Card system constants
# ---------------------------------------------------------------------------

# Card deck constraints (per D-12, D-13)
MAX_COPIES_PER_DECK: int = 3
MIN_DECK_SIZE: int = 40

# Card stat ranges (per D-19: stats in 1-5 range)
MIN_STAT: int = 1
MAX_STAT: int = 100

# Effect amount range (starter 1-5, extensible to 10 for Phase 8)
MAX_EFFECT_AMOUNT: int = 100

# ---------------------------------------------------------------------------
# Phase 3: Action system constants
# ---------------------------------------------------------------------------

# Active action-bank rules (GT_MANUAL_DRAW=1). Each player gains one point
# at the start of their own turn, may bank up to three, and spends one on
# each primary action. Reactions and modal continuations never spend points.
ACTION_POINTS_PER_TURN: int = 1
MAX_ACTION_POINTS: int = 3

# Turn economy is deliberately independent from Fortune frequency. Fortune
# offers can be rebalanced without silently accelerating mana, REST draws, or
# the late-game deckout clock.
MANA_RATE_TURN_INTERVAL: int = 10
REST_DRAW_COUNT: int = 1
DECKOUT_DRAW_START_TURN: int = 75


def turn_economy_rates(turn_number: int) -> tuple[int, int, int]:
    """Return ``(turn_mana, rest_draws, automatic_turn_draws)``.

    ``turn_number`` is the incoming/current turn, so ``turn_number - 1`` is
    the number of fully completed turns. The first increase therefore applies
    to turn 11, immediately after turn 10 has completed.
    """
    completed_turns = max(0, int(turn_number) - 1)
    turn_mana = min(
        MAX_MANA_CAP,
        MANA_REGEN_PER_TURN + completed_turns // MANA_RATE_TURN_INTERVAL,
    )
    automatic_draws = int(completed_turns >= DECKOUT_DRAW_START_TURN)
    return turn_mana, REST_DRAW_COUNT, automatic_draws

# DRAW slot 1000 is REST under the active contract. Automatic turn draws are
# disabled through turn 75, then become a one-card late-game clock.

# ---------------------------------------------------------------------------
# Active rules experiment (v5): action bank + REST.
#   - NO turn-start auto-draw before 75 completed turns.
#   - Turn mana rises by one after every 10 completed turns, capped at 10.
#   - After turn 75, turn start draws 1 and an empty deck fatigues.
#   - Primary actions, including MAGIC, spend one action point.
#   - REST is the rewarded no-action end: it spends 0, banks all points,
#     grants +1 mana, draws one card, and offers a Handshake.
#   - After any point is spent REST becomes PASS: free, no effect, end turn.
#   - Handshake payout remains +1 mana AND draw 1 for both players.
# This is now the default rules contract for live, headless, and RL play.
# Set GT_MANUAL_DRAW=0 only for legacy-rule regression/compatibility runs.
# Read at CALL time so tests can flip it with
# monkeypatch.setenv regardless of import order.
# ---------------------------------------------------------------------------
import os


def manual_draw_variant() -> bool:
    """True when the active action-bank/REST rules are selected."""
    return os.environ.get("GT_MANUAL_DRAW", "1") == "1"

# Runaway failsafe ONLY — there is no design-level limit on react chaining
# (turn-structure redesign 2026-07). This cap exists purely to stop a
# pathological infinite PLAY_REACT loop from hanging the engine; normal
# play should never come anywhere near it.
MAX_REACT_STACK_DEPTH: int = 100

# Back-row deployment positions for ranged minions (D-09)
BACK_ROW_P1: int = 0  # Player 1's back row
BACK_ROW_P2: int = 4  # Player 2's back row

# ---------------------------------------------------------------------------
# Phase 4: Game loop constants
# ---------------------------------------------------------------------------

# Maximum turns before game is declared a draw (D-11)
DEFAULT_TURN_LIMIT: int = 100
