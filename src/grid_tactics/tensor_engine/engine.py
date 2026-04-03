"""TensorGameEngine -- orchestrates batched game simulation.

Provides reset_batch() and step_batch() as the main entry points.
All N games advance simultaneously with tensor operations.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import torch

from grid_tactics.tensor_engine.card_table import CardTable
from grid_tactics.tensor_engine.constants import (
    EMPTY,
    GRID_COLS,
    GRID_ROWS,
    MAX_DECK,
    MAX_EFFECTS_PER_CARD,
    MAX_GRAVEYARD,
    MAX_HAND,
    MAX_MINIONS,
    MAX_REACT_DEPTH,
    STARTING_HAND_SIZE,
    STARTING_HP,
    STARTING_MANA,
)
from grid_tactics.tensor_engine.state import TensorGameState, create_initial_state
from grid_tactics.tensor_engine.actions import (
    apply_attack_batch,
    apply_draw_batch,
    apply_move_batch,
    apply_play_card_batch,
    apply_react_batch,
    apply_sacrifice_batch,
    decode_actions,
)
from grid_tactics.tensor_engine.effects import apply_effects_batch
from grid_tactics.tensor_engine.react import resolve_react_stack_batch


class TensorGameEngine:
    """Batched game engine running N games as tensor operations.

    Args:
        n_envs: Number of parallel games.
        card_table: GPU-resident card lookup table.
        deck_p1: [N, DECK_SIZE] int32 tensor of card IDs for player 1.
        deck_p2: [N, DECK_SIZE] int32 tensor of card IDs for player 2.
        device: torch device.
        seeds: Optional [N] tensor of per-game seeds for reproducible shuffling.
    """

    def __init__(
        self,
        n_envs: int,
        card_table: CardTable,
        deck_p1: torch.Tensor,
        deck_p2: torch.Tensor,
        device: torch.device = torch.device('cpu'),
        seeds: Optional[torch.Tensor] = None,
    ):
        self.n_envs = n_envs
        self.card_table = card_table
        self.device = device
        self.deck_p1 = deck_p1.to(device)
        self.deck_p2 = deck_p2.to(device)
        self.deck_size = deck_p1.shape[1]
        self.seeds = seeds
        self.state: TensorGameState = create_initial_state(n_envs, device)

    def reset_batch(self, mask: Optional[torch.Tensor] = None):
        """Reset all games (or subset via mask).

        Shuffles decks using numpy RNG for reproducibility with the Python engine,
        deals starting hands.
        """
        if mask is None:
            mask = torch.ones(self.n_envs, dtype=torch.bool, device=self.device)

        s = self.state

        for i in range(self.n_envs):
            if not mask[i]:
                continue
            self._reset_single_game(i)

    def _reset_single_game(self, game_idx: int):
        """Reset a single game to starting state."""
        s = self.state
        i = game_idx

        # Clear board
        s.board[i] = EMPTY

        # Player state
        s.player_hp[i, 0] = STARTING_HP
        s.player_hp[i, 1] = STARTING_HP
        s.player_mana[i, 0] = STARTING_MANA
        s.player_mana[i, 1] = STARTING_MANA
        s.player_max_mana[i, 0] = STARTING_MANA
        s.player_max_mana[i, 1] = STARTING_MANA

        # Clear hands
        s.hands[i] = EMPTY
        s.hand_sizes[i] = 0

        # Shuffle decks using numpy RNG for Python engine compatibility
        seed = self.seeds[i].item() if self.seeds is not None else i
        rng = np.random.default_rng(seed)

        # Match Python engine: shuffle p1 first, then p2 (same RNG sequence)
        deck_p1 = self.deck_p1[i].cpu().numpy().copy()
        deck_p2 = self.deck_p2[i].cpu().numpy().copy()
        rng.shuffle(deck_p1)
        rng.shuffle(deck_p2)

        s.decks[i, 0, :len(deck_p1)] = torch.tensor(deck_p1, dtype=torch.int32, device=self.device)
        s.decks[i, 1, :len(deck_p2)] = torch.tensor(deck_p2, dtype=torch.int32, device=self.device)
        s.deck_tops[i] = 0
        s.deck_sizes[i, 0] = len(deck_p1)
        s.deck_sizes[i, 1] = len(deck_p2)

        # Clear graveyards
        s.graveyards[i] = EMPTY
        s.graveyard_sizes[i] = 0

        # Clear minions
        s.minion_card_id[i] = EMPTY
        s.minion_owner[i] = EMPTY
        s.minion_row[i] = 0
        s.minion_col[i] = 0
        s.minion_health[i] = 0
        s.minion_atk_bonus[i] = 0
        s.minion_alive[i] = False
        s.next_minion_slot[i] = 0

        # Turn state
        s.active_player[i] = 0
        s.phase[i] = 0  # ACTION
        s.turn_number[i] = 1
        s.is_game_over[i] = False
        s.winner[i] = EMPTY

        # React state
        s.react_player[i] = 0
        s.react_stack_depth[i] = 0
        s.react_stack[i] = EMPTY
        s.pending_action_type[i] = EMPTY
        s.pending_action_card_id[i] = EMPTY
        s.pending_action_had_position[i] = False

        # Deal starting hands (5 cards each)
        for p in range(2):
            for h in range(STARTING_HAND_SIZE):
                dt = s.deck_tops[i, p].item()
                if dt < s.deck_sizes[i, p].item():
                    s.hands[i, p, h] = s.decks[i, p, dt]
                    s.deck_tops[i, p] += 1
            s.hand_sizes[i, p] = STARTING_HAND_SIZE

    def step_batch(self, action_ints: torch.Tensor):
        """Apply one action per game. Handles both ACTION and REACT phases.

        Flow:
        - ACTION phase: decode + apply action, cleanup dead, check game_over, transition to REACT
        - REACT phase: PASS -> resolve stack; PLAY_REACT -> push to stack
        """
        s = self.state
        N = self.n_envs
        device = self.device

        # Don't process game-over games
        alive = ~s.is_game_over

        action_type, hand_idx, source_flat, target_flat, direction = decode_actions(
            action_ints, s, self.card_table,
        )

        # Split by phase
        in_action_phase = (s.phase == 0) & alive
        in_react_phase = (s.phase == 1) & alive

        # --- ACTION PHASE ---
        if in_action_phase.any():
            self._step_action_phase(
                in_action_phase, action_type, hand_idx,
                source_flat, target_flat, direction,
            )

        # --- REACT PHASE ---
        if in_react_phase.any():
            self._step_react_phase(
                in_react_phase, action_type, hand_idx, target_flat,
            )

    def _step_action_phase(
        self,
        mask: torch.Tensor,
        action_type: torch.Tensor,
        hand_idx: torch.Tensor,
        source_flat: torch.Tensor,
        target_flat: torch.Tensor,
        direction: torch.Tensor,
    ):
        """Process ACTION phase for masked games."""
        s = self.state
        N = self.n_envs
        device = self.device

        # Apply each action type
        apply_draw_batch(s, mask & (action_type == 3), self.card_table)
        apply_move_batch(s, mask, action_type, source_flat, direction)
        apply_play_card_batch(s, mask, action_type, hand_idx, target_flat, self.card_table)
        apply_attack_batch(s, mask, action_type, source_flat, target_flat, self.card_table)
        apply_sacrifice_batch(s, mask, action_type, source_flat, self.card_table)
        # PASS (type 4) is a no-op on state

        # Record pending action info for react condition checking
        arange_n = torch.arange(N, device=device)
        # For PLAY_CARD actions, record the card that was played
        is_play = mask & (action_type == 0)
        if is_play.any():
            # The card was already removed from hand. Look at the last graveyard entry.
            ap = s.active_player
            for i in range(N):
                if is_play[i]:
                    p = ap[i].item()
                    gs = s.graveyard_sizes[i, p].item()
                    if gs > 0:
                        s.pending_action_card_id[i] = s.graveyards[i, p, gs - 1]
                    s.pending_action_had_position[i] = True  # could be minion deploy
                    # Check if it's actually a minion (had position = deploy)
                    cid = s.pending_action_card_id[i].item()
                    if cid >= 0:
                        ct = self.card_table.card_type[cid].item()
                        s.pending_action_had_position[i] = (ct == 0)  # MINION

        s.pending_action_type = torch.where(mask, action_type, s.pending_action_type)

        # For attack actions, record action type
        is_attack = mask & (action_type == 2)
        # pending_action_card_id for attacks: set to -1 (no card played)
        s.pending_action_card_id = torch.where(
            mask & ~is_play,
            torch.tensor(EMPTY, device=device),
            s.pending_action_card_id,
        )
        s.pending_action_had_position = torch.where(
            mask & ~is_play,
            torch.tensor(False, device=device),
            s.pending_action_had_position,
        )

        # Dead minion cleanup
        self.cleanup_dead_minions_batch()

        # Win check
        self.check_game_over_batch()

        # Transition to REACT phase for non-terminal games
        should_transition = mask & ~s.is_game_over
        if should_transition.any():
            s.phase = torch.where(should_transition, torch.tensor(1, device=device, dtype=torch.int32), s.phase)
            s.react_player = torch.where(
                should_transition,
                (1 - s.active_player).int(),
                s.react_player,
            )
            s.react_stack_depth = torch.where(
                should_transition,
                torch.tensor(0, device=device, dtype=torch.int32),
                s.react_stack_depth,
            )

    def _step_react_phase(
        self,
        mask: torch.Tensor,
        action_type: torch.Tensor,
        hand_idx: torch.Tensor,
        target_flat: torch.Tensor,
    ):
        """Process REACT phase for masked games."""
        s = self.state
        N = self.n_envs
        device = self.device

        # PASS in react -> resolve stack and advance turn
        is_pass = mask & (action_type == 4)
        # PLAY_REACT -> push to stack
        is_react = mask & (action_type == 5)

        if is_react.any():
            apply_react_batch(s, mask, action_type, hand_idx, target_flat, self.card_table)

        if is_pass.any():
            # Resolve react stack ONLY for passing games
            resolve_react_stack_batch(s, self.card_table, resolve_mask=is_pass)

            # Cleanup dead minions after react resolution
            self.cleanup_dead_minions_batch()

            # Win check
            self.check_game_over_batch()

            # Advance turn for non-terminal games that were passing
            should_advance = is_pass & ~s.is_game_over
            if should_advance.any():
                # Clear react state
                s.react_stack_depth = torch.where(
                    should_advance, torch.tensor(0, device=device, dtype=torch.int32), s.react_stack_depth
                )
                s.pending_action_type = torch.where(
                    should_advance, torch.tensor(EMPTY, device=device, dtype=torch.int32), s.pending_action_type
                )
                s.pending_action_card_id = torch.where(
                    should_advance, torch.tensor(EMPTY, device=device, dtype=torch.int32), s.pending_action_card_id
                )
                s.pending_action_had_position = torch.where(
                    should_advance, torch.tensor(False, device=device), s.pending_action_had_position
                )

                # Advance turn
                new_active = (1 - s.active_player).int()
                s.active_player = torch.where(should_advance, new_active, s.active_player)
                s.turn_number = torch.where(should_advance, s.turn_number + 1, s.turn_number)
                s.phase = torch.where(
                    should_advance, torch.tensor(0, device=device, dtype=torch.int32), s.phase
                )

                # Mana regen for new active player
                for i in range(N):
                    if should_advance[i]:
                        ap = s.active_player[i].item()
                        new_mana = min(s.player_mana[i, ap].item() + 1, 10)
                        s.player_mana[i, ap] = new_mana

    def cleanup_dead_minions_batch(self):
        """Remove minions with health <= 0. Trigger ON_DEATH effects. Two-pass."""
        s = self.state
        N = self.n_envs
        device = self.device

        for cleanup_pass in range(2):  # Two passes per Python engine convention
            # Find dead minions
            dead = s.minion_alive & (s.minion_health <= 0)
            if not dead.any():
                break

            # Collect death info before removing
            death_info = []
            for i in range(N):
                for slot in range(MAX_MINIONS):
                    if dead[i, slot]:
                        cid = s.minion_card_id[i, slot].item()
                        owner = s.minion_owner[i, slot].item()
                        row = s.minion_row[i, slot].item()
                        col = s.minion_col[i, slot].item()
                        death_info.append((i, slot, cid, owner, row, col))

            # Remove dead minions from board and mark as not alive
            for i, slot, cid, owner, row, col in death_info:
                if s.board[i, row, col].item() == slot:
                    s.board[i, row, col] = EMPTY
                s.minion_alive[i, slot] = False
                # Add to graveyard
                gs = s.graveyard_sizes[i, owner].item()
                if gs < 80:
                    s.graveyards[i, owner, gs] = cid
                    s.graveyard_sizes[i, owner] += 1

            # Trigger ON_DEATH effects (sorted by slot = instance_id equivalent)
            sorted_deaths = sorted(death_info, key=lambda x: (x[0], x[1]))
            for i, slot, cid, owner, row, col in sorted_deaths:
                game_mask = torch.zeros(N, dtype=torch.bool, device=device)
                game_mask[i] = True
                cids = torch.full((N,), cid, dtype=torch.int32, device=device)
                owners = torch.full((N,), owner, dtype=torch.int32, device=device)
                caster_slots = torch.full((N,), slot, dtype=torch.int32, device=device)
                tgt = torch.full((N,), EMPTY, dtype=torch.int32, device=device)
                apply_effects_batch(
                    s, cids, 1, owners, caster_slots, tgt,
                    self.card_table, game_mask,
                )  # trigger=ON_DEATH=1

    def check_game_over_batch(self):
        """Set is_game_over and winner based on player HP."""
        s = self.state
        p1_dead = s.player_hp[:, 0] <= 0
        p2_dead = s.player_hp[:, 1] <= 0

        both_dead = p1_dead & p2_dead & ~s.is_game_over
        p1_only_dead = p1_dead & ~p2_dead & ~s.is_game_over
        p2_only_dead = ~p1_dead & p2_dead & ~s.is_game_over

        # Both dead = draw
        if both_dead.any():
            s.is_game_over = s.is_game_over | both_dead
            s.winner = torch.where(both_dead, torch.tensor(EMPTY, device=self.device, dtype=torch.int32), s.winner)

        # P1 dead = P2 wins
        if p1_only_dead.any():
            s.is_game_over = s.is_game_over | p1_only_dead
            s.winner = torch.where(p1_only_dead, torch.tensor(1, device=self.device, dtype=torch.int32), s.winner)

        # P2 dead = P1 wins
        if p2_only_dead.any():
            s.is_game_over = s.is_game_over | p2_only_dead
            s.winner = torch.where(p2_only_dead, torch.tensor(0, device=self.device, dtype=torch.int32), s.winner)

    def auto_reset(self):
        """Reset games where is_game_over is True."""
        done_mask = self.state.is_game_over
        if done_mask.any():
            self.reset_batch(mask=done_mask)
