from enum import IntEnum


class PlayerSide(IntEnum):
    """Which player. IntEnum for efficient serialization and numpy compatibility."""

    PLAYER_1 = 0
    PLAYER_2 = 1


class TurnPhase(IntEnum):
    """Current phase within a turn. ACTION = active player acts, REACT = opponent may counter."""

    ACTION = 0
    REACT = 1


# ---------------------------------------------------------------------------
# Phase 2: Card system enums
# ---------------------------------------------------------------------------


class CardType(IntEnum):
    """Card type determines play rules and which fields are relevant."""

    MINION = 0  # Deployed to board, has attack/health/range
    MAGIC = 1   # Immediate effect, then discarded
    REACT = 2   # Played during opponent's action window


class Attribute(IntEnum):
    """Elemental attribute for future synergy mechanics (D-09)."""

    NEUTRAL = 0
    FIRE = 1
    DARK = 2
    LIGHT = 3


class EffectType(IntEnum):
    """What the effect does. Starter cards use damage/heal/buff only (D-01)."""

    DAMAGE = 0
    HEAL = 1
    BUFF_ATTACK = 2
    BUFF_HEALTH = 3
    NEGATE = 4       # Cancel the triggering action (react-only)


class ReactCondition(IntEnum):
    """What opponent action must have occurred for a react card to be playable.

    React cards MUST match a condition -- they can't be played generically.
    The condition is checked against the pending_action in GameState.
    """

    OPPONENT_PLAYS_MAGIC = 0    # Opponent cast a magic card
    OPPONENT_PLAYS_MINION = 1   # Opponent deployed a minion
    OPPONENT_ATTACKS = 2        # Opponent attacked with a minion
    OPPONENT_PLAYS_REACT = 3    # Opponent played a react card (counter-react)
    ANY_ACTION = 4              # Reacts to any opponent action


class TriggerType(IntEnum):
    """When the effect activates (D-02)."""

    ON_PLAY = 0     # When the card is played/deployed
    ON_DEATH = 1    # When the minion dies
    ON_ATTACK = 2   # When the minion attacks
    ON_DAMAGED = 3  # When the minion takes damage


class TargetType(IntEnum):
    """What the effect targets (D-03)."""

    SINGLE_TARGET = 0  # Player chooses one target
    ALL_ENEMIES = 1    # Hits all enemy minions
    ADJACENT = 2       # Hits all adjacent units
    SELF_OWNER = 3     # Affects self or owning player


# ---------------------------------------------------------------------------
# Phase 3: Action system enums
# ---------------------------------------------------------------------------


class ActionType(IntEnum):
    """Type of action a player can take on their turn (D-12, D-17).

    One action per turn: play card, move minion, attack, draw, or pass.
    PLAY_REACT is used during the react window (D-04 through D-07).
    """

    PLAY_CARD = 0   # Deploy minion or cast magic
    MOVE = 1        # Move a minion on the board
    ATTACK = 2      # Attack with a minion
    DRAW = 3        # Draw a card (costs action per D-15)
    PASS = 4        # Pass turn (always legal per D-16)
    PLAY_REACT = 5  # Play a react card during react window
    SACRIFICE = 6   # Sacrifice minion on opponent's back row for player damage
