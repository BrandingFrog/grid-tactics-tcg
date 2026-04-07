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


class Element(IntEnum):
    """Elemental type for synergy mechanics (D-09)."""

    WOOD = 0
    FIRE = 1
    EARTH = 2
    WATER = 3
    METAL = 4
    DARK = 5
    LIGHT = 6


class EffectType(IntEnum):
    """What the effect does. Starter cards use damage/heal/buff only (D-01)."""

    DAMAGE = 0
    HEAL = 1
    BUFF_ATTACK = 2
    BUFF_HEALTH = 3
    NEGATE = 4       # Cancel the triggering action (react-only)
    DEPLOY_SELF = 5  # Deploy this card as a minion (react-only, for multi-purpose discount deploy)
    RALLY_FORWARD = 6  # Move all other friendly minions with same card_id forward 1 space
    PROMOTE = 7        # On death: promote a friendly minion of promote_target type into this card
    TUTOR = 8          # Search deck for card matching tutor_target and add to hand
    DESTROY = 9        # Destroy target minion (remove regardless of health)
    BURN = 10          # Apply burn DoT to target (amount damage per action, non-stacking)
    DARK_MATTER_BUFF = 11  # Buff attack by amount + player's Dark Matter stacks
    PASSIVE_HEAL = 12  # Heal self by amount (fires on PASSIVE trigger each turn)
    LEAP = 13          # On move: if blocked by enemy, advance to next available tile instead
    CONJURE = 14       # Create a card from outside the deck (specified by summon_token_target)


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
    OPPONENT_PLAYS_WOOD = 5     # Opponent played a card with WOOD element
    OPPONENT_PLAYS_FIRE = 6     # Opponent played a card with FIRE element
    OPPONENT_PLAYS_EARTH = 7    # Opponent played a card with EARTH element
    OPPONENT_PLAYS_WATER = 8    # Opponent played a card with WATER element
    OPPONENT_PLAYS_METAL = 9    # Opponent played a card with METAL element
    OPPONENT_PLAYS_DARK = 10    # Opponent played a card with DARK element
    OPPONENT_PLAYS_LIGHT = 11   # Opponent played a card with LIGHT element
    OPPONENT_SACRIFICES = 12    # Opponent's minion sacrificed at your back row


class TriggerType(IntEnum):
    """When the effect activates (D-02)."""

    ON_PLAY = 0     # When the card is played/deployed
    ON_DEATH = 1    # When the minion dies
    ON_ATTACK = 2   # When the minion attacks
    ON_DAMAGED = 3  # When the minion takes damage
    ON_MOVE = 4     # When the minion moves
    PASSIVE = 5     # Fires every turn (passive effects)


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
    TRANSFORM = 7   # Transform an on-board minion into a different card (costs mana)
    DECLINE_POST_MOVE_ATTACK = 8  # Decline the post-move attack offered to a melee minion
    TUTOR_SELECT = 9        # Pick a specific deck card during pending_tutor (Phase 14.2)
    DECLINE_TUTOR = 10      # Decline a pending tutor; matched cards remain in deck (Phase 14.2)
