"""TensorGameEngine -- orchestrates batched game simulation.

Provides reset_batch() and step_batch() as the main entry points.
All N games advance simultaneously with tensor operations.

Fully vectorized: zero .item() calls, zero for-loops over batch N.
Remaining loops are over fixed constants (2 players, MAX_MINIONS slots,
STARTING_HAND_SIZE cards, 2 cleanup passes).
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
        deals starting hands. State writes are batched tensor ops; only the RNG
        shuffle is per-game (numpy requirement for seed compatibility).
        """
        if mask is None:
            mask = torch.ones(self.n_envs, dtype=torch.bool, device=self.device)

        s = self.state
        N = self.n_envs
        device = self.device
        arange_n = torch.arange(N, device=device)

        # --- Batch-reset scalar/per-player state ---
        s.board = torch.where(
            mask.view(N, 1, 1), torch.tensor(EMPTY, device=device, dtype=torch.int32), s.board
        )
        for p in range(2):
            s.player_hp[:, p] = torch.where(mask, torch.tensor(STARTING_HP, device=device, dtype=torch.int32), s.player_hp[:, p])
            s.player_mana[:, p] = torch.where(mask, torch.tensor(STARTING_MANA, device=device, dtype=torch.int32), s.player_mana[:, p])
            s.player_max_mana[:, p] = torch.where(mask, torch.tensor(STARTING_MANA, device=device, dtype=torch.int32), s.player_max_mana[:, p])

        # Clear hands
        s.hands = torch.where(mask.view(N, 1, 1), torch.tensor(EMPTY, device=device, dtype=torch.int32), s.hands)
        s.hand_sizes = torch.where(mask.view(N, 1), torch.tensor(0, device=device, dtype=torch.int32), s.hand_sizes)

        # Clear graveyards
        s.graveyards = torch.where(mask.view(N, 1, 1), torch.tensor(EMPTY, device=device, dtype=torch.int32), s.graveyards)
        s.graveyard_sizes = torch.where(mask.view(N, 1), torch.tensor(0, device=device, dtype=torch.int32), s.graveyard_sizes)

        # Clear minions
        s.minion_card_id = torch.where(mask.unsqueeze(1), torch.tensor(EMPTY, device=device, dtype=torch.int32), s.minion_card_id)
        s.minion_owner = torch.where(mask.unsqueeze(1), torch.tensor(EMPTY, device=device, dtype=torch.int32), s.minion_owner)
        s.minion_row = torch.where(mask.unsqueeze(1), torch.tensor(0, device=device, dtype=torch.int32), s.minion_row)
        s.minion_col = torch.where(mask.unsqueeze(1), torch.tensor(0, device=device, dtype=torch.int32), s.minion_col)
        s.minion_health = torch.where(mask.unsqueeze(1), torch.tensor(0, device=device, dtype=torch.int32), s.minion_health)
        s.minion_atk_bonus = torch.where(mask.unsqueeze(1), torch.tensor(0, device=device, dtype=torch.int32), s.minion_atk_bonus)
        s.minion_alive = torch.where(mask.unsqueeze(1), torch.tensor(False, device=device), s.minion_alive)
        s.next_minion_slot = torch.where(mask, torch.tensor(0, device=device, dtype=torch.int32), s.next_minion_slot)

        # Turn state
        s.active_player = torch.where(mask, torch.tensor(0, device=device, dtype=torch.int32), s.active_player)
        s.phase = torch.where(mask, torch.tensor(0, device=device, dtype=torch.int32), s.phase)
        s.turn_number = torch.where(mask, torch.tensor(1, device=device, dtype=torch.int32), s.turn_number)
        s.is_game_over = torch.where(mask, torch.tensor(False, device=device), s.is_game_over)
        s.winner = torch.where(mask, torch.tensor(EMPTY, device=device, dtype=torch.int32), s.winner)

        # React state
        s.react_player = torch.where(mask, torch.tensor(0, device=device, dtype=torch.int32), s.react_player)
        s.react_stack_depth = torch.where(mask, torch.tensor(0, device=device, dtype=torch.int32), s.react_stack_depth)
        s.react_stack = torch.where(mask.view(N, 1, 1), torch.tensor(EMPTY, device=device, dtype=torch.int32), s.react_stack)
        s.pending_action_type = torch.where(mask, torch.tensor(EMPTY, device=device, dtype=torch.int32), s.pending_action_type)
        s.pending_action_card_id = torch.where(mask, torch.tensor(EMPTY, device=device, dtype=torch.int32), s.pending_action_card_id)
        s.pending_action_had_position = torch.where(mask, torch.tensor(False, device=device), s.pending_action_had_position)
        # Phase 14.1: clear pending post-move attacker on reset
        s.pending_post_move_attacker = torch.where(
            mask, torch.tensor(-1, device=device, dtype=torch.int32), s.pending_post_move_attacker
        )
        # Phase 14.2: clear pending tutor state on reset
        s.pending_tutor_player = torch.where(
            mask, torch.tensor(-1, device=device, dtype=torch.int32), s.pending_tutor_player
        )
        s.pending_tutor_matches = torch.where(
            mask.view(N, 1),
            torch.tensor(-1, device=device, dtype=torch.int32),
            s.pending_tutor_matches,
        )

        # --- Shuffle decks using numpy RNG (per-game for seed compatibility) ---
        # Build shuffled decks on CPU, then upload in bulk
        mask_indices = torch.where(mask)[0]
        if mask_indices.numel() > 0:
            mask_cpu = mask_indices.cpu().numpy()
            deck_p1_cpu = self.deck_p1.cpu().numpy()
            deck_p2_cpu = self.deck_p2.cpu().numpy()

            # Pre-allocate result arrays
            shuffled_p1 = np.empty((len(mask_cpu), self.deck_size), dtype=np.int32)
            shuffled_p2 = np.empty((len(mask_cpu), self.deck_size), dtype=np.int32)

            seeds_cpu = self.seeds.cpu().numpy() if self.seeds is not None else None
            for idx_pos, i in enumerate(mask_cpu):
                seed = int(seeds_cpu[i]) if seeds_cpu is not None else int(i)
                rng = np.random.default_rng(seed)
                d1 = deck_p1_cpu[i].copy()
                d2 = deck_p2_cpu[i].copy()
                rng.shuffle(d1)
                rng.shuffle(d2)
                shuffled_p1[idx_pos] = d1
                shuffled_p2[idx_pos] = d2

            # Bulk upload shuffled decks
            shuffled_p1_t = torch.tensor(shuffled_p1, dtype=torch.int32, device=device)
            shuffled_p2_t = torch.tensor(shuffled_p2, dtype=torch.int32, device=device)

            s.decks[mask_indices, 0, :self.deck_size] = shuffled_p1_t
            s.decks[mask_indices, 1, :self.deck_size] = shuffled_p2_t

            # Set deck pointers
            s.deck_tops[mask_indices] = 0
            s.deck_sizes[mask_indices, 0] = self.deck_size
            s.deck_sizes[mask_indices, 1] = self.deck_size

            # --- Deal starting hands (P1=3, P2=4) ---
            from grid_tactics.types import STARTING_HAND_P1, STARTING_HAND_P2
            hand_sizes_per_player = [STARTING_HAND_P1, STARTING_HAND_P2]
            for p in range(2):
                for h in range(hand_sizes_per_player[p]):
                    dt = s.deck_tops[mask_indices, p]
                    card_id = s.decks[mask_indices, p, dt.long()]
                    s.hands[mask_indices, p, h] = card_id
                    s.deck_tops[mask_indices, p] = dt + 1
            s.hand_sizes[mask_indices, 0] = STARTING_HAND_P1
            s.hand_sizes[mask_indices, 1] = STARTING_HAND_P2
            s.fatigue_count[mask_indices] = 0

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
        arange_n = torch.arange(N, device=device)

        # Phase 14.1: PASS while pending_post_move_attacker is set means
        # DECLINE_POST_MOVE_ATTACK (slot 1001 reused). Reinterpret first.
        has_pending_pre = s.pending_post_move_attacker >= 0
        is_decline = mask & (action_type == 4) & has_pending_pre
        if is_decline.any():
            from grid_tactics.tensor_engine.actions import _apply_decline_post_move_attack
            _apply_decline_post_move_attack(s, is_decline)

        # Apply each action type. Decline games are excluded from PASS/fatigue
        # below to avoid double-handling.
        apply_draw_batch(s, mask & (action_type == 3), self.card_table)
        apply_move_batch(s, mask, action_type, source_flat, direction, self.card_table)
        apply_play_card_batch(s, mask, action_type, hand_idx, target_flat, self.card_table)
        apply_attack_batch(s, mask, action_type, source_flat, target_flat, self.card_table)
        apply_sacrifice_batch(s, mask, action_type, source_flat, self.card_table)
        # PASS (type 4) -- only happens when no other actions available (fatigue)
        # Escalating fatigue damage: 10, 20, 30, 40...
        # Exclude decline-as-PASS games from fatigue.
        is_pass_action = mask & (action_type == 4) & ~is_decline
        if is_pass_action.any():
            ap = s.active_player
            for p in range(2):
                is_p_pass = is_pass_action & (ap == p)
                if is_p_pass.any():
                    s.fatigue_count[:, p] += is_p_pass.int()
                    fatigue_dmg = s.fatigue_count[:, p] * 10  # 10, 20, 30...
                    s.player_hp[:, p] -= fatigue_dmg * is_p_pass.int()

        # Record pending action info for react condition checking (batched)
        ap = s.active_player
        is_play = mask & (action_type == 0)
        if is_play.any():
            # The card was already removed from hand. Look at the last graveyard entry.
            gs = s.graveyard_sizes[arange_n, ap]  # [N]
            safe_gs = (gs - 1).clamp(0, 79).long()
            last_gy_cid = s.graveyards[arange_n, ap, safe_gs]  # [N]

            # Only update for games that actually played a card and have graveyard entries
            has_gy = is_play & (gs > 0)
            s.pending_action_card_id = torch.where(has_gy, last_gy_cid, s.pending_action_card_id)
            # Default to True for has_position (could be minion deploy)
            s.pending_action_had_position = torch.where(is_play, torch.tensor(True, device=device), s.pending_action_had_position)

            # Check if it's actually a minion (had position = deploy) -- only if card_id valid
            safe_cid = s.pending_action_card_id.clamp(0).long()
            ct = self.card_table.card_type[safe_cid]
            is_minion_deploy = (ct == 0)  # MINION
            s.pending_action_had_position = torch.where(
                has_gy & (s.pending_action_card_id >= 0),
                is_minion_deploy,
                s.pending_action_had_position,
            )

        s.pending_action_type = torch.where(mask, action_type, s.pending_action_type)

        # For non-play actions, clear card_id and had_position
        s.pending_action_card_id = torch.where(
            mask & ~is_play,
            torch.tensor(EMPTY, device=device, dtype=torch.int32),
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

        # Transition to REACT phase for non-terminal games.
        # Phase 14.1: defer react if a MOVE just set pending_post_move_attacker.
        # The move+attack/decline pair is one logical action with one react window.
        should_transition = mask & ~s.is_game_over & (s.pending_post_move_attacker < 0)
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
        arange_n = torch.arange(N, device=device)

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

                # Mana regen for new active player (batched).
                # Skip regen when entering turn 2 (P2's first action) so both
                # players start their first action with STARTING_MANA. After
                # advancing, s.turn_number holds the NEW turn number.
                regen_allowed = should_advance & (s.turn_number > 2)
                ap_new = s.active_player  # [N]

                # Regen for player 0 (where regen_allowed and new active == 0)
                regen_p0 = regen_allowed & (ap_new == 0)
                if regen_p0.any():
                    new_mana_p0 = (s.player_mana[:, 0] + 1).clamp(max=10)
                    s.player_mana[:, 0] = torch.where(regen_p0, new_mana_p0, s.player_mana[:, 0])

                # Regen for player 1 (where regen_allowed and new active == 1)
                regen_p1 = regen_allowed & (ap_new == 1)
                if regen_p1.any():
                    new_mana_p1 = (s.player_mana[:, 1] + 1).clamp(max=10)
                    s.player_mana[:, 1] = torch.where(regen_p1, new_mana_p1, s.player_mana[:, 1])

                # Auto-draw for new active player at turn start
                apply_draw_batch(s, should_advance, self.card_table)

    def cleanup_dead_minions_batch(self):
        """Remove minions with health <= 0. Trigger ON_DEATH effects.

        Two-pass cleanup per Python engine convention. Loops over MAX_MINIONS
        slots (fixed 25) and 2 cleanup passes -- NOT over batch dimension N.
        """
        s = self.state
        N = self.n_envs
        device = self.device
        arange_n = torch.arange(N, device=device)

        for cleanup_pass in range(2):  # Two passes per Python engine convention
            # Find dead minions: [N, MAX_MINIONS]
            dead = s.minion_alive & (s.minion_health <= 0)
            if not dead.any():
                break

            # Capture death info as tensors before modifying state
            dead_cid = s.minion_card_id.clone()   # [N, MAX_MINIONS]
            dead_owner = s.minion_owner.clone()    # [N, MAX_MINIONS]
            dead_row = s.minion_row.clone()        # [N, MAX_MINIONS]
            dead_col = s.minion_col.clone()        # [N, MAX_MINIONS]

            # Remove dead minions from board -- iterate over slots (constant MAX_MINIONS=25)
            for slot in range(MAX_MINIONS):
                slot_dead = dead[:, slot]  # [N]
                if not slot_dead.any():
                    continue

                r = dead_row[:, slot]
                c = dead_col[:, slot]

                # Only clear board if the board cell still points to this slot
                board_val = s.board[arange_n, r, c]  # [N]
                should_clear = slot_dead & (board_val == slot)
                s.board[arange_n, r, c] = torch.where(
                    should_clear,
                    torch.tensor(EMPTY, device=device, dtype=torch.int32),
                    s.board[arange_n, r, c]
                )

                # Mark as not alive
                s.minion_alive[:, slot] = torch.where(
                    slot_dead,
                    torch.tensor(False, device=device),
                    s.minion_alive[:, slot]
                )

                # Add to graveyard (batched per-slot)
                cid = dead_cid[:, slot]
                owner = dead_owner[:, slot]

                # Graveyard add for player 0 owners
                for p in range(2):
                    is_p = slot_dead & (owner == p)
                    if not is_p.any():
                        continue
                    gs = s.graveyard_sizes[:, p]  # [N]
                    can_add = is_p & (gs < 80)
                    if can_add.any():
                        safe_gs = gs.clamp(0, 79).long()
                        s.graveyards[arange_n, p, safe_gs] = torch.where(
                            can_add, cid, s.graveyards[arange_n, p, safe_gs]
                        )
                        s.graveyard_sizes[:, p] = torch.where(
                            can_add, gs + 1, gs
                        )

            # Trigger ON_DEATH effects -- iterate over slots (constant MAX_MINIONS=25)
            # Sorted by slot = instance_id equivalent (ascending)
            for slot in range(MAX_MINIONS):
                slot_dead = dead[:, slot]  # [N]
                if not slot_dead.any():
                    continue

                cid = dead_cid[:, slot]
                owner = dead_owner[:, slot]
                safe_cid = cid.clamp(0).long()

                apply_effects_batch(
                    s, safe_cid.int(), 1, owner,
                    torch.full((N,), slot, dtype=torch.int32, device=device),
                    torch.full((N,), EMPTY, dtype=torch.int32, device=device),
                    self.card_table, slot_dead,
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
