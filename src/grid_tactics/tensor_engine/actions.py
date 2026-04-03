"""Batched action dispatch for all 7 action types.

Each action type is computed for the full batch, then merged via
action_type mask. No Python branching over the batch dimension.
"""

from __future__ import annotations

import torch

from grid_tactics.tensor_engine.constants import (
    ATTACK_BASE,
    BACK_ROW_P1,
    BACK_ROW_P2,
    DRAW_IDX,
    EMPTY,
    GRID_COLS,
    GRID_SIZE,
    MAX_HAND,
    MAX_MINIONS,
    MOVE_BASE,
    PASS_IDX,
    PLAY_CARD_BASE,
    REACT_BASE,
    SACRIFICE_BASE,
)
from grid_tactics.tensor_engine.effects import apply_effects_batch


# Direction deltas: 0=up, 1=down, 2=left, 3=right
_DIR_DELTAS = torch.tensor([[-1, 0], [1, 0], [0, -1], [0, 1]], dtype=torch.int32)


def decode_actions(
    action_ints: torch.Tensor,
    state,
    card_table,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """Decode [N] action ints into structured fields.

    Returns: action_type, hand_idx, source_flat, target_flat, direction (all [N] int32)
    """
    N = action_ints.shape[0]
    device = action_ints.device

    action_type = torch.full((N,), 4, dtype=torch.int32, device=device)  # default PASS
    hand_idx = torch.zeros(N, dtype=torch.int32, device=device)
    source_flat = torch.zeros(N, dtype=torch.int32, device=device)
    target_flat = torch.zeros(N, dtype=torch.int32, device=device)
    direction = torch.zeros(N, dtype=torch.int32, device=device)

    a = action_ints.long()

    # PLAY_CARD [0:250]
    is_play = (a >= PLAY_CARD_BASE) & (a < MOVE_BASE)
    if is_play.any():
        idx = a - PLAY_CARD_BASE
        action_type = torch.where(is_play, torch.tensor(0, device=device), action_type)
        hand_idx = torch.where(is_play, (idx // GRID_SIZE).int(), hand_idx)
        target_flat = torch.where(is_play, (idx % GRID_SIZE).int(), target_flat)

    # MOVE [250:350]
    is_move = (a >= MOVE_BASE) & (a < ATTACK_BASE)
    if is_move.any():
        idx = a - MOVE_BASE
        action_type = torch.where(is_move, torch.tensor(1, device=device), action_type)
        source_flat = torch.where(is_move, (idx // 4).int(), source_flat)
        direction = torch.where(is_move, (idx % 4).int(), direction)

    # ATTACK [350:975]
    is_attack = (a >= ATTACK_BASE) & (a < SACRIFICE_BASE)
    if is_attack.any():
        idx = a - ATTACK_BASE
        action_type = torch.where(is_attack, torch.tensor(2, device=device), action_type)
        source_flat = torch.where(is_attack, (idx // GRID_SIZE).int(), source_flat)
        target_flat = torch.where(is_attack, (idx % GRID_SIZE).int(), target_flat)

    # SACRIFICE [975:1000]
    is_sacrifice = (a >= SACRIFICE_BASE) & (a < DRAW_IDX)
    if is_sacrifice.any():
        idx = a - SACRIFICE_BASE
        action_type = torch.where(is_sacrifice, torch.tensor(6, device=device), action_type)
        source_flat = torch.where(is_sacrifice, idx.int(), source_flat)

    # DRAW [1000]
    is_draw = (a == DRAW_IDX)
    if is_draw.any():
        action_type = torch.where(is_draw, torch.tensor(3, device=device), action_type)

    # PASS [1001]
    is_pass = (a == PASS_IDX)
    if is_pass.any():
        action_type = torch.where(is_pass, torch.tensor(4, device=device), action_type)

    # PLAY_REACT [1002:1262]
    is_react = (a >= REACT_BASE) & (a < REACT_BASE + MAX_HAND * 26)
    if is_react.any():
        idx = a - REACT_BASE
        action_type = torch.where(is_react, torch.tensor(5, device=device), action_type)
        hand_idx = torch.where(is_react, (idx // 26).int(), hand_idx)
        target_flat = torch.where(is_react, (idx % 26).int(), target_flat)

    return action_type, hand_idx, source_flat, target_flat, direction


def apply_draw_batch(state, mask, card_table):
    """Draw top card from deck to hand for masked games."""
    if not mask.any():
        return
    N = mask.shape[0]
    device = mask.device
    arange_n = torch.arange(N, device=device)
    ap = state.active_player  # [N]

    # Get card from top of deck
    safe_top = state.deck_tops[arange_n, ap].clamp(0, 39)
    card_id = state.decks[arange_n, ap, safe_top]

    # Check deck not empty
    can_draw = mask & (state.deck_tops[arange_n, ap] < state.deck_sizes[arange_n, ap])

    if not can_draw.any():
        return

    # Place in hand at hand_sizes position
    hs = state.hand_sizes[arange_n, ap].clamp(0, MAX_HAND - 1)
    # Only draw if hand not full
    can_draw = can_draw & (state.hand_sizes[arange_n, ap] < MAX_HAND)
    if not can_draw.any():
        return

    for i in range(N):
        if can_draw[i]:
            p = ap[i].item()
            hi = state.hand_sizes[i, p].item()
            dt = state.deck_tops[i, p].item()
            state.hands[i, p, hi] = state.decks[i, p, dt]
            state.hand_sizes[i, p] += 1
            state.deck_tops[i, p] += 1


def apply_move_batch(state, mask, action_type, source_flat, direction):
    """Move minion from source to adjacent cell."""
    is_move = mask & (action_type == 1)
    if not is_move.any():
        return

    N = mask.shape[0]
    device = mask.device
    deltas = _DIR_DELTAS.to(device)
    arange_n = torch.arange(N, device=device)

    src_row = (source_flat // GRID_COLS).clamp(0, 4)
    src_col = (source_flat % GRID_COLS).clamp(0, 4)
    dr = deltas[direction.clamp(0, 3).long(), 0]
    dc = deltas[direction.clamp(0, 3).long(), 1]
    dst_row = (src_row + dr).clamp(0, 4)
    dst_col = (src_col + dc).clamp(0, 4)

    for i in range(N):
        if not is_move[i]:
            continue
        sr, sc = src_row[i].item(), src_col[i].item()
        dr_i, dc_i = dst_row[i].item(), dst_col[i].item()
        slot = state.board[i, sr, sc].item()
        if slot < 0:
            continue
        # Move on board
        state.board[i, sr, sc] = EMPTY
        state.board[i, dr_i, dc_i] = slot
        # Update minion position
        state.minion_row[i, slot] = dr_i
        state.minion_col[i, slot] = dc_i


def apply_play_card_batch(state, mask, action_type, hand_idx, target_flat, card_table):
    """Play a card from hand (minion deploy or magic cast)."""
    is_play = mask & (action_type == 0)
    if not is_play.any():
        return

    N = mask.shape[0]
    device = mask.device
    arange_n = torch.arange(N, device=device)
    ap = state.active_player  # [N]

    # Get card from hand
    safe_hi = hand_idx.clamp(0, MAX_HAND - 1)
    card_id = state.hands[arange_n, ap, safe_hi]
    safe_cid = card_id.clamp(min=0)

    # Card properties
    ctype = card_table.card_type[safe_cid]  # [N]
    cost = card_table.mana_cost[safe_cid]   # [N]

    # Process each game individually for correctness
    for i in range(N):
        if not is_play[i]:
            continue
        p = ap[i].item()
        hi = safe_hi[i].item()
        cid = state.hands[i, p, hi].item()
        if cid < 0:
            continue

        ct = card_table.card_type[cid].item()
        mc = card_table.mana_cost[cid].item()

        # Spend mana
        state.player_mana[i, p] -= mc

        # Remove card from hand (shift left)
        _remove_from_hand(state, i, p, hi)

        # Add to graveyard
        _add_to_graveyard(state, i, p, cid)

        if ct == 0:  # MINION
            _deploy_minion(state, i, p, cid, target_flat[i].item(), card_table)
        elif ct == 1:  # MAGIC
            # Resolve ON_PLAY effects
            _apply_magic_effects(state, i, p, cid, target_flat[i].item(), card_table)


def _deploy_minion(state, game_idx, player_idx, card_id, target_flat, card_table):
    """Deploy a single minion for one game."""
    row = target_flat // GRID_COLS
    col = target_flat % GRID_COLS
    if row < 0 or row >= 5 or col < 0 or col >= 5:
        return

    slot = state.next_minion_slot[game_idx].item()
    if slot >= MAX_MINIONS:
        return

    state.board[game_idx, row, col] = slot
    state.minion_card_id[game_idx, slot] = card_id
    state.minion_owner[game_idx, slot] = player_idx
    state.minion_row[game_idx, slot] = row
    state.minion_col[game_idx, slot] = col
    state.minion_health[game_idx, slot] = card_table.health[card_id].item()
    state.minion_atk_bonus[game_idx, slot] = 0
    state.minion_alive[game_idx, slot] = True
    state.next_minion_slot[game_idx] += 1

    # Trigger ON_PLAY effects for the deployed minion
    # NOTE: For minion ON_PLAY effects, the target_flat from the action encoding
    # is the DEPLOY position, NOT the effect target. The action space encoding
    # doesn't capture the effect target separately for minion deploys.
    # So we pass -1 (no target) -- matching what happens when the Python engine
    # decodes from integer (target_pos=None, which means SINGLE_TARGET effects skip).
    N = state.board.shape[0]
    device = state.board.device
    cids = torch.full((N,), card_id, dtype=torch.int32, device=device)
    owners = torch.full((N,), player_idx, dtype=torch.int32, device=device)
    slots = torch.full((N,), slot, dtype=torch.int32, device=device)
    # Pass -1 as target: action encoding doesn't capture ON_PLAY target for minions
    tgt = torch.full((N,), -1, dtype=torch.int32, device=device)
    game_mask = torch.zeros(N, dtype=torch.bool, device=device)
    game_mask[game_idx] = True
    apply_effects_batch(state, cids, 0, owners, slots, tgt, card_table, game_mask)  # trigger=ON_PLAY=0


def _apply_magic_effects(state, game_idx, player_idx, card_id, target_flat, card_table):
    """Apply ON_PLAY effects for a magic card (no minion on board)."""
    N = state.board.shape[0]
    device = state.board.device
    cids = torch.full((N,), card_id, dtype=torch.int32, device=device)
    owners = torch.full((N,), player_idx, dtype=torch.int32, device=device)
    slots = torch.full((N,), -1, dtype=torch.int32, device=device)  # no caster minion
    tgt = torch.full((N,), target_flat, dtype=torch.int32, device=device)
    game_mask = torch.zeros(N, dtype=torch.bool, device=device)
    game_mask[game_idx] = True
    apply_effects_batch(state, cids, 0, owners, slots, tgt, card_table, game_mask)


def apply_attack_batch(state, mask, action_type, source_flat, target_flat, card_table):
    """Apply ATTACK action -- simultaneous damage exchange."""
    is_attack = mask & (action_type == 2)
    if not is_attack.any():
        return

    N = mask.shape[0]
    device = mask.device
    arange_n = torch.arange(N, device=device)

    src_row = (source_flat // GRID_COLS).clamp(0, 4)
    src_col = (source_flat % GRID_COLS).clamp(0, 4)
    tgt_row = (target_flat // GRID_COLS).clamp(0, 4)
    tgt_col = (target_flat % GRID_COLS).clamp(0, 4)

    for i in range(N):
        if not is_attack[i]:
            continue
        sr, sc = src_row[i].item(), src_col[i].item()
        tr, tc = tgt_row[i].item(), tgt_col[i].item()

        a_slot = state.board[i, sr, sc].item()
        d_slot = state.board[i, tr, tc].item()
        if a_slot < 0 or d_slot < 0:
            continue

        a_cid = state.minion_card_id[i, a_slot].item()
        d_cid = state.minion_card_id[i, d_slot].item()

        # Effective attack = base + bonus
        a_eff = card_table.attack[a_cid].item() + state.minion_atk_bonus[i, a_slot].item()
        d_eff = card_table.attack[d_cid].item() + state.minion_atk_bonus[i, d_slot].item()

        # Simultaneous damage
        state.minion_health[i, a_slot] -= d_eff
        state.minion_health[i, d_slot] -= a_eff

    # Trigger ON_ATTACK for attacker, ON_DAMAGED for both
    for i in range(N):
        if not is_attack[i]:
            continue
        sr, sc = src_row[i].item(), src_col[i].item()
        tr, tc = tgt_row[i].item(), tgt_col[i].item()
        a_slot = state.board[i, sr, sc].item()
        d_slot = state.board[i, tr, tc].item()
        if a_slot < 0:
            continue

        a_cid = state.minion_card_id[i, a_slot].item()
        game_mask = torch.zeros(N, dtype=torch.bool, device=device)
        game_mask[i] = True
        cids = torch.full((N,), a_cid, dtype=torch.int32, device=device)
        owners = torch.full((N,), state.minion_owner[i, a_slot].item(), dtype=torch.int32, device=device)
        slots = torch.full((N,), a_slot, dtype=torch.int32, device=device)
        tgt = torch.full((N,), target_flat[i].item(), dtype=torch.int32, device=device)

        # ON_ATTACK (2) for attacker
        if state.minion_alive[i, a_slot]:
            apply_effects_batch(state, cids, 2, owners, slots, tgt, card_table, game_mask)

        # ON_DAMAGED (3) for attacker (if defender had attack > 0)
        if d_slot >= 0:
            d_cid = state.minion_card_id[i, d_slot].item()
            d_eff = card_table.attack[d_cid].item() + state.minion_atk_bonus[i, d_slot].item()
            if d_eff > 0 and state.minion_alive[i, a_slot]:
                apply_effects_batch(state, cids, 3, owners, slots, tgt, card_table, game_mask)

            # ON_DAMAGED (3) for defender
            a_eff = card_table.attack[a_cid].item() + state.minion_atk_bonus[i, a_slot].item()
            if a_eff > 0 and state.minion_alive[i, d_slot]:
                d_cids = torch.full((N,), d_cid, dtype=torch.int32, device=device)
                d_owners = torch.full((N,), state.minion_owner[i, d_slot].item(), dtype=torch.int32, device=device)
                d_slots = torch.full((N,), d_slot, dtype=torch.int32, device=device)
                src_pos = torch.full((N,), source_flat[i].item(), dtype=torch.int32, device=device)
                apply_effects_batch(state, d_cids, 3, d_owners, d_slots, src_pos, card_table, game_mask)


def apply_sacrifice_batch(state, mask, action_type, source_flat, card_table):
    """Sacrifice minion on opponent's back row, dealing damage to opponent."""
    is_sac = mask & (action_type == 6)
    if not is_sac.any():
        return

    N = mask.shape[0]
    device = mask.device

    src_row = (source_flat // GRID_COLS).clamp(0, 4)
    src_col = (source_flat % GRID_COLS).clamp(0, 4)

    for i in range(N):
        if not is_sac[i]:
            continue
        sr, sc = src_row[i].item(), src_col[i].item()
        slot = state.board[i, sr, sc].item()
        if slot < 0:
            continue

        cid = state.minion_card_id[i, slot].item()
        owner = state.minion_owner[i, slot].item()
        eff_atk = card_table.attack[cid].item() + state.minion_atk_bonus[i, slot].item()

        # Remove minion
        state.board[i, sr, sc] = EMPTY
        state.minion_alive[i, slot] = False

        # Add to graveyard
        _add_to_graveyard(state, i, owner, cid)

        # Deal damage to opponent
        opponent = 1 - state.active_player[i].item()
        state.player_hp[i, opponent] -= eff_atk


def apply_react_batch(state, mask, action_type, hand_idx, target_flat, card_table):
    """Play a react card: spend mana, discard, push to stack, swap react_player."""
    is_react = mask & (action_type == 5)
    if not is_react.any():
        return

    N = mask.shape[0]
    device = mask.device

    for i in range(N):
        if not is_react[i]:
            continue
        rp = state.react_player[i].item()
        hi = hand_idx[i].item()
        if hi < 0 or hi >= state.hand_sizes[i, rp].item():
            continue

        cid = state.hands[i, rp, hi].item()
        if cid < 0:
            continue

        # Determine cost
        ct = card_table.card_type[cid].item()
        if card_table.is_multi_purpose[cid].item():
            cost = card_table.react_mana_cost[cid].item()
        else:
            cost = card_table.mana_cost[cid].item()

        # Spend mana
        state.player_mana[i, rp] -= cost

        # Remove from hand
        _remove_from_hand(state, i, rp, hi)

        # Add to graveyard
        _add_to_graveyard(state, i, rp, cid)

        # Push onto react stack
        depth = state.react_stack_depth[i].item()
        if depth < 10:
            # target: for PLAY_REACT, target_flat encodes target_or_none(26)
            # 0-24 = flat pos, 25 = no target
            tf = target_flat[i].item()
            state.react_stack[i, depth, 0] = rp
            state.react_stack[i, depth, 1] = cid
            state.react_stack[i, depth, 2] = tf  # store as-is (25 = no target)
            state.react_stack_depth[i] += 1

        # Swap react player
        state.react_player[i] = 1 - rp


# ---------------------------------------------------------------------------
# Hand / graveyard helpers
# ---------------------------------------------------------------------------

def _remove_from_hand(state, game_idx: int, player_idx: int, hand_idx: int):
    """Remove card at hand_idx, shift remaining cards left."""
    hs = state.hand_sizes[game_idx, player_idx].item()
    for j in range(hand_idx, hs - 1):
        state.hands[game_idx, player_idx, j] = state.hands[game_idx, player_idx, j + 1]
    if hs > 0:
        state.hands[game_idx, player_idx, hs - 1] = EMPTY
        state.hand_sizes[game_idx, player_idx] -= 1


def _add_to_graveyard(state, game_idx: int, player_idx: int, card_id: int):
    """Add card to graveyard at next slot."""
    gs = state.graveyard_sizes[game_idx, player_idx].item()
    if gs < 80:
        state.graveyards[game_idx, player_idx, gs] = card_id
        state.graveyard_sizes[game_idx, player_idx] += 1
