"""Heuristic policy for the Game Preview dummy seat (user 2026-07-10).

Deliberately NOT smart — just goal-directed enough that a solo preview
feels like a game instead of a punching bag: it resolves pending picks
(so modal states never stall the drain), sometimes plays reacts, and on
its turn prefers sacrifice > attack > play (most expensive affordable
card) > move > pass (which is a REST under the variant: +1 mana and a
draw). Win condition is HP depletion, so damage and board presence ARE
"towards the goal".

Pure function of (state, library, legal_actions); uses stdlib random
(server-side only — never touches the deterministic engine RNG).
"""

from __future__ import annotations

import random
from typing import Optional, Sequence

from grid_tactics.actions import Action, pass_action
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import ActionType, TurnPhase
from grid_tactics.game_state import GameState

# Probability the dummy answers with a legal react instead of passing the
# window — high enough that the human sees the react/spell-stage flow in
# previews, low enough that it doesn't burn every card immediately.
REACT_PLAY_CHANCE = 0.5


def pick_preview_action(
    state: GameState,
    library: CardLibrary,
    legal: Sequence[Action],
) -> Optional[Action]:
    """Pick the dummy's next action from ``legal``. Returns None only for
    an empty legal set (caller falls back to its PASS failsafe)."""
    legal = list(legal)
    if not legal:
        return None

    by_type: dict[ActionType, list[Action]] = {}
    for a in legal:
        by_type.setdefault(a.action_type, []).append(a)

    def any_of(*types: ActionType) -> Optional[Action]:
        for t in types:
            if t in by_type:
                return random.choice(by_type[t])
        return None

    # --- Pending modal states: MUST resolve or the drain stalls ---------
    picked = any_of(
        ActionType.TUTOR_SELECT,
        ActionType.CONJURE_DEPLOY,
        ActionType.DEATH_TARGET_PICK,
        ActionType.REVIVE_PLACE,
        ActionType.TRIGGER_PICK,
    )
    if picked is not None:
        return picked

    # --- React windows: sometimes answer, else pass ---------------------
    if state.phase == TurnPhase.REACT:
        reacts = by_type.get(ActionType.PLAY_REACT)
        if reacts and random.random() < REACT_PLAY_CHANCE:
            return random.choice(reacts)
        if ActionType.PASS in by_type:
            return pass_action()
        return random.choice(legal)

    # --- Main phase: damage first, then development ----------------------
    # Sacrifice hits the enemy player directly — always take it.
    if ActionType.SACRIFICE in by_type:
        return random.choice(by_type[ActionType.SACRIFICE])
    # Post-move attack pick / normal attack.
    if ActionType.ATTACK in by_type:
        return random.choice(by_type[ActionType.ATTACK])

    # Play a card — prefer the most expensive affordable one so the mana
    # pool actually gets spent (random target/deploy among that cost).
    plays = by_type.get(ActionType.PLAY_CARD)
    if plays:
        player = state.players[state.active_player_idx]

        def _cost(a: Action) -> int:
            try:
                return library.get_by_id(player.hand[a.card_index]).mana_cost
            except Exception:
                return 0

        best = max(_cost(a) for a in plays)
        return random.choice([a for a in plays if _cost(a) == best])

    # Advance the board (moves are forward-only, i.e. toward the enemy).
    if ActionType.MOVE in by_type:
        return random.choice(by_type[ActionType.MOVE])

    # Variant v4 (2026-07-11): REST (the DRAW slot) beats a dead PASS —
    # +1 mana and +1 draw for the same action.
    if ActionType.DRAW in by_type:
        return by_type[ActionType.DRAW][0]

    # Declines for pending flavours where nothing above applied.
    picked = any_of(
        ActionType.DECLINE_POST_MOVE_ATTACK,
        ActionType.DECLINE_TUTOR,
        ActionType.DECLINE_CONJURE,
        ActionType.DECLINE_REVIVE,
        ActionType.DECLINE_TRIGGER,
    )
    if picked is not None:
        return picked

    if ActionType.PASS in by_type:
        return pass_action()
    return random.choice(legal)
