"""TensorGameState -- all game state as batched GPU tensors.

All tensors have leading batch dimension N. Variable-length structures
use fixed-size tensors with sentinel value -1 and size counters.
Uses int32 throughout for broad GPU compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch

from grid_tactics.tensor_engine.constants import (
    EMPTY,
    GRID_COLS,
    GRID_ROWS,
    MAX_DECK,
    MAX_GRAVEYARD,
    MAX_HAND,
    MAX_MINIONS,
    MAX_REACT_DEPTH,
)


@dataclass
class TensorGameState:
    """All game state as batched GPU tensors. Shape [N, ...] where N = batch_size.

    NOT frozen -- tensors are mutable for in-place ops.
    """

    # Board: which minion slot occupies each cell (-1 = empty)
    board: torch.Tensor           # [N, 5, 5] int32

    # Player state
    player_hp: torch.Tensor       # [N, 2] int32
    player_mana: torch.Tensor     # [N, 2] int32
    player_max_mana: torch.Tensor  # [N, 2] int32

    # Hands: card numeric ID per slot, -1 = empty
    hands: torch.Tensor           # [N, 2, MAX_HAND] int32
    hand_sizes: torch.Tensor      # [N, 2] int32

    # Decks: pre-shuffled, draw from deck_tops pointer
    decks: torch.Tensor           # [N, 2, MAX_DECK] int32
    deck_tops: torch.Tensor       # [N, 2] int32 (index of next card to draw)
    deck_sizes: torch.Tensor      # [N, 2] int32 (total cards in each deck)

    # Graveyards
    graveyards: torch.Tensor      # [N, 2, MAX_GRAVEYARD] int32
    graveyard_sizes: torch.Tensor  # [N, 2] int32

    # Minion slots (fixed MAX_MINIONS, use minion_alive mask)
    minion_card_id: torch.Tensor   # [N, MAX_MINIONS] int32
    minion_owner: torch.Tensor     # [N, MAX_MINIONS] int32 (-1=empty, 0=p1, 1=p2)
    minion_row: torch.Tensor       # [N, MAX_MINIONS] int32
    minion_col: torch.Tensor       # [N, MAX_MINIONS] int32
    minion_health: torch.Tensor    # [N, MAX_MINIONS] int32
    minion_atk_bonus: torch.Tensor  # [N, MAX_MINIONS] int32
    minion_alive: torch.Tensor     # [N, MAX_MINIONS] bool
    next_minion_slot: torch.Tensor  # [N] int32

    # Turn state
    active_player: torch.Tensor   # [N] int32 (0 or 1)
    phase: torch.Tensor           # [N] int32 (0=ACTION, 1=REACT)
    turn_number: torch.Tensor     # [N] int32
    is_game_over: torch.Tensor    # [N] bool
    winner: torch.Tensor          # [N] int32 (-1=none/draw, 0=p1, 1=p2)
    fatigue_count: torch.Tensor   # [N, 2] int32 -- escalating bleed counter per player

    # React state
    react_player: torch.Tensor      # [N] int32
    react_stack_depth: torch.Tensor  # [N] int32
    # React stack entries: [player_idx, card_numeric_id, target_flat_pos]
    react_stack: torch.Tensor       # [N, MAX_REACT_DEPTH, 3] int32
    pending_action_type: torch.Tensor     # [N] int32 (-1 = none)
    pending_action_card_id: torch.Tensor  # [N] int32 (-1 = none)
    pending_action_had_position: torch.Tensor  # [N] bool

    # Phase 14.1: pending post-move attack state.
    # Per-game minion slot index of a melee minion that just moved into range
    # of at least one enemy. -1 = no pending. While >= 0, only ATTACK with that
    # slot or DECLINE_POST_MOVE_ATTACK is legal, and the react window is
    # deferred until the pending state clears.
    pending_post_move_attacker: torch.Tensor  # [N] int32 (-1 = none)

    # Phase 14.2: pending tutor choice state.
    # When a tutor on_play card resolves and finds at least one match in the
    # caster's deck, pending_tutor_player[g] is set to the caster idx (0/1) and
    # pending_tutor_matches[g] holds up to K=8 deck indices (-1 padded). While
    # set, only TUTOR_SELECT (PLAY_CARD slots reinterpreted as match index) or
    # DECLINE_TUTOR (PASS slot reinterpreted) is legal, and the react window is
    # deferred until the pending state clears. Mutually exclusive with
    # pending_post_move_attacker (asserted in handlers).
    pending_tutor_player: torch.Tensor   # [N] int32 (-1 = none, else player idx 0/1)
    pending_tutor_matches: torch.Tensor  # [N, 8] int32 (-1 padded deck indices)

    # Boolean burn status: per-minion is_burning flag. Persists until death.
    # Re-applying burn to an already-burning minion is a no-op.
    is_burning: torch.Tensor             # [N, MAX_MINIONS] bool

    # Cumulative max-HP buff. Effective max HP = card_table.health[cid] +
    # minion_max_health_bonus. HEAL caps at the effective max so flat max-HP
    # buffs (e.g. Ratchanter's conjure_rat_and_buff) raise the heal ceiling.
    # Mirrors Python MinionInstance.max_health_bonus.
    minion_max_health_bonus: torch.Tensor  # [N, MAX_MINIONS] int32

    # Dark Matter counters per minion. Currently consumed by Ratchanter
    # (conjure_rat_and_buff scales with caster.dark_matter_stacks) and granted
    # by GRANT_DARK_MATTER effect (Dark Matter Infusion magic card).
    # Mirrors Python MinionInstance.dark_matter_stacks.
    minion_dark_matter_stacks: torch.Tensor  # [N, MAX_MINIONS] int32

    def clone(self) -> TensorGameState:
        """Deep-copy all tensors."""
        return TensorGameState(
            board=self.board.clone(),
            player_hp=self.player_hp.clone(),
            player_mana=self.player_mana.clone(),
            player_max_mana=self.player_max_mana.clone(),
            hands=self.hands.clone(),
            hand_sizes=self.hand_sizes.clone(),
            decks=self.decks.clone(),
            deck_tops=self.deck_tops.clone(),
            deck_sizes=self.deck_sizes.clone(),
            graveyards=self.graveyards.clone(),
            graveyard_sizes=self.graveyard_sizes.clone(),
            minion_card_id=self.minion_card_id.clone(),
            minion_owner=self.minion_owner.clone(),
            minion_row=self.minion_row.clone(),
            minion_col=self.minion_col.clone(),
            minion_health=self.minion_health.clone(),
            minion_atk_bonus=self.minion_atk_bonus.clone(),
            minion_alive=self.minion_alive.clone(),
            next_minion_slot=self.next_minion_slot.clone(),
            active_player=self.active_player.clone(),
            phase=self.phase.clone(),
            turn_number=self.turn_number.clone(),
            is_game_over=self.is_game_over.clone(),
            winner=self.winner.clone(),
            react_player=self.react_player.clone(),
            react_stack_depth=self.react_stack_depth.clone(),
            react_stack=self.react_stack.clone(),
            pending_action_type=self.pending_action_type.clone(),
            pending_action_card_id=self.pending_action_card_id.clone(),
            pending_action_had_position=self.pending_action_had_position.clone(),
            fatigue_count=self.fatigue_count.clone(),
            pending_post_move_attacker=self.pending_post_move_attacker.clone(),
            pending_tutor_player=self.pending_tutor_player.clone(),
            pending_tutor_matches=self.pending_tutor_matches.clone(),
            is_burning=self.is_burning.clone(),
            minion_max_health_bonus=self.minion_max_health_bonus.clone(),
            minion_dark_matter_stacks=self.minion_dark_matter_stacks.clone(),
        )


def create_initial_state(
    n_envs: int,
    device: torch.device,
) -> TensorGameState:
    """Create a zeroed/sentinel TensorGameState for n_envs games."""
    return TensorGameState(
        board=torch.full((n_envs, GRID_ROWS, GRID_COLS), EMPTY, dtype=torch.int32, device=device),
        player_hp=torch.full((n_envs, 2), 0, dtype=torch.int32, device=device),
        player_mana=torch.zeros((n_envs, 2), dtype=torch.int32, device=device),
        player_max_mana=torch.zeros((n_envs, 2), dtype=torch.int32, device=device),
        hands=torch.full((n_envs, 2, MAX_HAND), EMPTY, dtype=torch.int32, device=device),
        hand_sizes=torch.zeros((n_envs, 2), dtype=torch.int32, device=device),
        decks=torch.full((n_envs, 2, MAX_DECK), EMPTY, dtype=torch.int32, device=device),
        deck_tops=torch.zeros((n_envs, 2), dtype=torch.int32, device=device),
        deck_sizes=torch.zeros((n_envs, 2), dtype=torch.int32, device=device),
        graveyards=torch.full((n_envs, 2, MAX_GRAVEYARD), EMPTY, dtype=torch.int32, device=device),
        graveyard_sizes=torch.zeros((n_envs, 2), dtype=torch.int32, device=device),
        minion_card_id=torch.full((n_envs, MAX_MINIONS), EMPTY, dtype=torch.int32, device=device),
        minion_owner=torch.full((n_envs, MAX_MINIONS), EMPTY, dtype=torch.int32, device=device),
        minion_row=torch.zeros((n_envs, MAX_MINIONS), dtype=torch.int32, device=device),
        minion_col=torch.zeros((n_envs, MAX_MINIONS), dtype=torch.int32, device=device),
        minion_health=torch.zeros((n_envs, MAX_MINIONS), dtype=torch.int32, device=device),
        minion_atk_bonus=torch.zeros((n_envs, MAX_MINIONS), dtype=torch.int32, device=device),
        minion_alive=torch.zeros((n_envs, MAX_MINIONS), dtype=torch.bool, device=device),
        next_minion_slot=torch.zeros(n_envs, dtype=torch.int32, device=device),
        active_player=torch.zeros(n_envs, dtype=torch.int32, device=device),
        phase=torch.zeros(n_envs, dtype=torch.int32, device=device),
        turn_number=torch.ones(n_envs, dtype=torch.int32, device=device),
        is_game_over=torch.zeros(n_envs, dtype=torch.bool, device=device),
        winner=torch.full((n_envs,), EMPTY, dtype=torch.int32, device=device),
        react_player=torch.zeros(n_envs, dtype=torch.int32, device=device),
        react_stack_depth=torch.zeros(n_envs, dtype=torch.int32, device=device),
        react_stack=torch.full((n_envs, MAX_REACT_DEPTH, 3), EMPTY, dtype=torch.int32, device=device),
        pending_action_type=torch.full((n_envs,), EMPTY, dtype=torch.int32, device=device),
        pending_action_card_id=torch.full((n_envs,), EMPTY, dtype=torch.int32, device=device),
        pending_action_had_position=torch.zeros(n_envs, dtype=torch.bool, device=device),
        fatigue_count=torch.zeros((n_envs, 2), dtype=torch.int32, device=device),
        pending_post_move_attacker=torch.full((n_envs,), -1, dtype=torch.int32, device=device),
        pending_tutor_player=torch.full((n_envs,), -1, dtype=torch.int32, device=device),
        pending_tutor_matches=torch.full((n_envs, 8), -1, dtype=torch.int32, device=device),
        is_burning=torch.zeros((n_envs, MAX_MINIONS), dtype=torch.bool, device=device),
        minion_max_health_bonus=torch.zeros((n_envs, MAX_MINIONS), dtype=torch.int32, device=device),
        minion_dark_matter_stacks=torch.zeros((n_envs, MAX_MINIONS), dtype=torch.int32, device=device),
    )
