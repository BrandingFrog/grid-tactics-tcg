from enum import IntEnum


class PlayerSide(IntEnum):
    """Which player. IntEnum for efficient serialization and numpy compatibility."""

    PLAYER_1 = 0
    PLAYER_2 = 1


class TurnPhase(IntEnum):
    """Current phase within a turn.

    ACTION = active player acts, REACT = opponent may counter.
    Phase 14.7-02: extended with START_OF_TURN and END_OF_TURN for the
    3-phase turn model mandated by the turn-structure spec. Each turn now
    progresses START_OF_TURN -> ACTION -> END_OF_TURN with a REACT window
    open after each phase's triggered effects finish firing. Values are
    append-only so downstream numpy/tensor/int encodings stay stable.
    """

    ACTION = 0
    REACT = 1
    START_OF_TURN = 2   # New: Phase 14.7-02
    END_OF_TURN = 3     # New: Phase 14.7-02


class ReactContext(IntEnum):
    """Which kind of event opened the current REACT window.

    Drives react_condition matching (plan 14.7-07) and tells the UI which
    animation to play (plan 14.7-09). ``react_return_phase`` on GameState
    tells the state machine which phase to transition back to after PASS-
    PASS closes the react chain.

    Phase 14.7-02: enum introduced. Today only AFTER_ACTION is used
    (backwards-compat with legacy after-action react window). The other
    values are reserved for later plans in Phase 14.7 that wire start-of-
    turn triggers (14.7-03), summon compound windows (14.7-04), and death
    windows.
    """

    AFTER_START_TRIGGER = 0
    AFTER_ACTION = 1
    AFTER_SUMMON_DECLARATION = 2
    AFTER_SUMMON_EFFECT = 3
    AFTER_DEATH_EFFECT = 4
    BEFORE_END_OF_TURN = 5


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
    APPLY_BURNING = 15  # Phase 14.3: grant N burning_stacks to the target minion (stacks additively)
    GRANT_DARK_MATTER = 16  # Add `amount` Dark Matter stacks to a target minion. Currently only consumed by Ratchanter's activated ability (magnitude scales with caster.dark_matter_stacks).
    REVIVE = 17  # Summon up to `amount` copies of revive_card_id from grave to the board
    DRAW = 18    # Draw `amount` cards from deck to hand
    BURN_BONUS = 19  # Aura: adds `amount` to burn tick damage for this player's burning enemies


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
    OPPONENT_DISCARDS = 13     # Opponent discarded a card from hand
    OPPONENT_ENDS_TURN = 14    # Fires after opponent's turn action (one-per-turn game — semantically "end of opponent's turn")
    # Phase 14.7-07: react_context-aware conditions. Matched against
    # state.react_context rather than pending_action, so they fire in the
    # exact window opened by summon declaration / start-of-turn trigger /
    # end-of-turn trigger respectively. No card JSON uses these yet —
    # added for future expressivity; existing cards (Prohibition etc.)
    # are unchanged.
    OPPONENT_SUMMONS_MINION = 15   # Opponent deployed a minion (AFTER_SUMMON_DECLARATION)
    OPPONENT_START_OF_TURN = 16    # Opponent's start-of-turn trigger fired (AFTER_START_TRIGGER)
    OPPONENT_END_OF_TURN = 17      # Opponent's end-of-turn trigger fired (BEFORE_END_OF_TURN)


class TriggerType(IntEnum):
    """When the effect activates (D-02)."""

    ON_PLAY = 0     # When the card is played/deployed
    ON_DEATH = 1    # When the minion dies
    ON_ATTACK = 2   # When the minion attacks
    ON_DAMAGED = 3  # When the minion takes damage
    ON_MOVE = 4     # When the minion moves
    # 5 was PASSIVE. DELETED in Phase 14.8-05 (was unused since 14.7-03 — all
    # three ex-PASSIVE cards migrated to on_start_of_turn / on_end_of_turn).
    # The invariant test `test_no_card_uses_passive_trigger` in
    # tests/test_phase_contract_invariants.py guards against re-introduction.
    # Value 5 is BURNED, not reused — TriggerType is append-only for numpy /
    # tensor-engine encoding stability.
    ON_DISCARD = 6  # Fires when this card is discarded (sent from hand to exhaust pile)
    AURA = 7        # Always active while this minion is alive on the board
    # Phase 14.7-03: explicit turn-phase and summon triggers
    ON_SUMMON = 8             # When minion is deployed from hand (14.7-04 opens compound windows)
    ON_START_OF_TURN = 9      # At the start of the owner's turn (after burn ticks, before ACTION)
    ON_END_OF_TURN = 10       # At the end of the owner's turn (before turn passes)


class TargetType(IntEnum):
    """What the effect targets (D-03)."""

    SINGLE_TARGET = 0  # Player chooses one target
    ALL_ENEMIES = 1    # Hits all enemy minions
    ADJACENT = 2       # Hits all adjacent units
    SELF_OWNER = 3     # Affects self or owning player
    OPPONENT_PLAYER = 4  # Deals damage/effect to the opponent player's HP
    ALL_ALLIES = 5       # Hits all friendly minions (optionally filtered by target_tribe)
    ALL_MINIONS = 6      # Hits every living minion (both sides), optionally filtered by target_tribe and/or target_element


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
    ACTIVATE_ABILITY = 11   # Use a minion's activated ability (mana + turn action)
    CONJURE_DEPLOY = 12     # Deploy a conjured card to a board tile (Phase 14.6)
    DECLINE_CONJURE = 13    # Decline conjure deployment — card goes to hand instead
    DEATH_TARGET_PICK = 14  # Pick a target for a death-triggered modal effect (e.g. Lasercannon on_death destroy)
    REVIVE_PLACE = 15       # Place a revived minion from grave onto a board tile
    DECLINE_REVIVE = 16     # Decline remaining revive placements
    # Phase 14.7-05: simultaneous-trigger priority picker
    TRIGGER_PICK = 17       # Pick a queued trigger to resolve next (reuses PLAY_CARD[0:N] slots)
    DECLINE_TRIGGER = 18    # Decline / skip remaining triggers (reuses PASS slot 1001)
