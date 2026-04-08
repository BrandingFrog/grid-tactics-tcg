"""Batched action dispatch for all 7 action types.

Each action type is computed for the full batch, then merged via
action_type mask. No Python branching over the batch dimension.

Fully vectorized: zero .item() calls, zero for-loops over N.
"""

from __future__ import annotations

import torch

from grid_tactics.tensor_engine.constants import (
    ACTIVATE_BASE,
    ACTION_SPACE_SIZE,
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

    # ACTIVATE_ABILITY [1262:1287] -- source = activator's flat board position
    is_activate = (a >= ACTIVATE_BASE) & (a < ACTIVATE_BASE + GRID_SIZE)
    if is_activate.any():
        idx = a - ACTIVATE_BASE
        action_type = torch.where(is_activate, torch.tensor(11, device=device), action_type)
        source_flat = torch.where(is_activate, idx.int(), source_flat)

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
    deck_top = state.deck_tops[arange_n, ap]  # [N]
    deck_size = state.deck_sizes[arange_n, ap]  # [N]

    # Check deck not empty and hand not full
    hand_size = state.hand_sizes[arange_n, ap]  # [N]
    can_draw = mask & (deck_top < deck_size) & (hand_size < MAX_HAND)

    if not can_draw.any():
        return

    # Read card from deck at deck_top position
    safe_top = deck_top.clamp(0, 39).long()
    card_id = state.decks[arange_n, ap, safe_top]  # [N]

    # Place in hand at hand_sizes position
    safe_hs = hand_size.clamp(0, MAX_HAND - 1).long()

    # Batched writes with masking
    state.hands[arange_n, ap, safe_hs] = torch.where(
        can_draw, card_id, state.hands[arange_n, ap, safe_hs]
    )
    state.hand_sizes[arange_n, ap] = torch.where(
        can_draw, hand_size + 1, hand_size
    )
    state.deck_tops[arange_n, ap] = torch.where(
        can_draw, deck_top + 1, deck_top
    )


def apply_move_batch(state, mask, action_type, source_flat, direction, card_table=None):
    """Move minion from source to adjacent cell. Triggers ON_MOVE effects."""
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

    # Read slot at source position
    slot = state.board[arange_n, src_row, src_col]  # [N]
    valid = is_move & (slot >= 0)

    # Audit-followup: LEAP — if the chosen forward tile is occupied, walk
    # forward over the blocker(s) up to the minion's leap_amount additional
    # steps and use the first empty landing tile as the actual destination.
    # Mirrors the Python `_apply_move` LEAP path. Lateral directions never
    # leap (delta-col != 0 disables the override).
    if card_table is not None:
        safe_slot_pre = slot.clamp(0).long()
        cid_pre = state.minion_card_id[arange_n, safe_slot_pre].clamp(0).long()
        leap_amt = card_table.leap_amount[cid_pre]  # [N]
        # Original target occupancy (use freshly-computed dst_row, dst_col)
        dst_occupied = (
            state.board[arange_n, dst_row, dst_col] != EMPTY
        )
        is_forward = (dr != 0) & (dc == 0)
        wants_leap = valid & is_forward & dst_occupied & (leap_amt > 0)
        if wants_leap.any():
            cur_row = dst_row.clone()
            found_empty = torch.zeros_like(wants_leap)
            land_row = dst_row.clone()
            max_amt = int(leap_amt.max().item())
            for extra in range(1, max_amt + 1):
                cand = (cur_row + dr).clamp(0, 4)
                in_b = (cur_row + dr >= 0) & (cur_row + dr < 5)
                allowed = wants_leap & ~found_empty & (extra <= leap_amt) & in_b
                empty_here = state.board[arange_n, cand, dst_col] == EMPTY
                pick = allowed & empty_here
                land_row = torch.where(pick, cand, land_row)
                found_empty = found_empty | pick
                cur_row = cand
            dst_row = torch.where(wants_leap & found_empty, land_row, dst_row)
            # If the leap couldn't find a landing, mark the move invalid.
            valid = valid & ~(wants_leap & ~found_empty)

    if not valid.any():
        return

    safe_slot = slot.clamp(0).long()

    # Clear source cell
    state.board[arange_n, src_row, src_col] = torch.where(
        valid, torch.tensor(EMPTY, device=device, dtype=torch.int32),
        state.board[arange_n, src_row, src_col]
    )
    # Set destination cell
    state.board[arange_n, dst_row, dst_col] = torch.where(
        valid, slot, state.board[arange_n, dst_row, dst_col]
    )
    # Update minion position
    state.minion_row[arange_n, safe_slot] = torch.where(
        valid, dst_row, state.minion_row[arange_n, safe_slot]
    )
    state.minion_col[arange_n, safe_slot] = torch.where(
        valid, dst_col, state.minion_col[arange_n, safe_slot]
    )

    # --- ON_MOVE: RALLY_FORWARD effect ---
    # Check if moved minion has ON_MOVE trigger (trigger=4) with RALLY_FORWARD (type=6)
    if card_table is not None:
        moved_card_id = state.minion_card_id[arange_n, safe_slot]  # [N]
        for eff_i in range(3):  # MAX_EFFECTS_PER_CARD
            has_rally = (
                valid
                & (card_table.effect_trigger[moved_card_id.clamp(0).long(), eff_i] == 4)  # ON_MOVE
                & (card_table.effect_type[moved_card_id.clamp(0).long(), eff_i] == 6)     # RALLY_FORWARD
            )
            if has_rally.any():
                _apply_rally_forward(state, has_rally, moved_card_id, safe_slot)
                break

        # --- Phase 14.1: Pending post-move attack state ---
        # Replaces the old auto-attack-after-move. For melee minions
        # (attack_range == 0), if at least one in-range enemy exists from
        # the new tile, set pending_post_move_attacker to this slot. The
        # next action MUST be ATTACK with this slot or DECLINE.
        atk_cid_pm = state.minion_card_id[arange_n, safe_slot].clamp(0).long()
        atk_range_pm = card_table.attack_range[atk_cid_pm]  # [N]
        is_melee = valid & (atk_range_pm == 0)
        atk_owner_pm = state.minion_owner[arange_n, safe_slot]

        # Compute has_target_after_move: any enemy in melee range from
        # (dst_row, dst_col)? Melee = manhattan==1 & orthogonal.
        has_target = torch.zeros(N, dtype=torch.bool, device=device)
        for s in range(MAX_MINIONS):
            t_row = state.minion_row[:, s]
            t_col = state.minion_col[:, s]
            dr = (dst_row - t_row).abs()
            dc = (dst_col - t_col).abs()
            manhattan = dr + dc
            is_ortho = (dr == 0) | (dc == 0)
            in_range_s = (
                is_melee
                & state.minion_alive[:, s]
                & (state.minion_owner[:, s] != atk_owner_pm)
                & (manhattan == 1)
                & is_ortho
            )
            has_target = has_target | in_range_s

        set_pending = is_melee & has_target
        state.pending_post_move_attacker = torch.where(
            set_pending,
            safe_slot.to(torch.int32),
            state.pending_post_move_attacker,
        )


def apply_tutor_select_batch(state, mask, match_index):
    """Phase 14.2: resolve pending_tutor by picking match `match_index`.

    For each masked game with pending_tutor_player >= 0:
      1. Read deck index from pending_tutor_matches[g, match_index].
      2. Pop that deck card to the caster's hand (swap-with-last + shrink).
      3. Clear pending_tutor_player and pending_tutor_matches.

    `match_index` is [N] int32 (the chosen slot 0..7). Mirrors the Python
    engine's TUTOR_SELECT path.
    """
    if not mask.any():
        return
    N = mask.shape[0]
    device = mask.device
    arange_n = torch.arange(N, device=device)

    valid = mask & (state.pending_tutor_player >= 0)
    if not valid.any():
        return

    safe_mi = match_index.clamp(0, 7).long()
    deck_idx = state.pending_tutor_matches[arange_n, safe_mi]  # [N] int32, -1 if invalid slot
    valid = valid & (deck_idx >= 0)
    if not valid.any():
        return

    player = state.pending_tutor_player.long()
    safe_di = deck_idx.clamp(0, 39).long()
    tutored_card = state.decks[arange_n, player, safe_di]

    # Swap-with-last + shrink (mirrors the old _apply_tutor removal)
    deck_size = state.deck_sizes[arange_n, player]
    last_idx = (deck_size - 1).clamp(0, 39).long()
    last_card = state.decks[arange_n, player, last_idx]
    state.decks[arange_n, player, safe_di] = torch.where(
        valid, last_card, state.decks[arange_n, player, safe_di]
    )
    state.decks[arange_n, player, last_idx] = torch.where(
        valid, torch.tensor(-1, device=device, dtype=state.decks.dtype),
        state.decks[arange_n, player, last_idx]
    )
    state.deck_sizes[arange_n, player] = torch.where(
        valid, deck_size - 1, state.deck_sizes[arange_n, player]
    )

    # Add to hand (if hand not full)
    hand_size = state.hand_sizes[arange_n, player]
    safe_hs = hand_size.clamp(0, MAX_HAND - 1).long()
    can_add = valid & (hand_size < MAX_HAND)
    state.hands[arange_n, player, safe_hs] = torch.where(
        can_add, tutored_card, state.hands[arange_n, player, safe_hs]
    )
    state.hand_sizes[arange_n, player] = torch.where(
        can_add, hand_size + 1, state.hand_sizes[arange_n, player]
    )

    # Clear pending tutor state
    state.pending_tutor_player = torch.where(
        valid, torch.tensor(-1, device=device, dtype=torch.int32),
        state.pending_tutor_player,
    )
    state.pending_tutor_matches = torch.where(
        valid.view(N, 1),
        torch.tensor(-1, device=device, dtype=torch.int32),
        state.pending_tutor_matches,
    )


def apply_decline_tutor_batch(state, mask):
    """Phase 14.2: clear pending_tutor without moving any deck card."""
    if not mask.any():
        return
    N = mask.shape[0]
    device = mask.device
    valid = mask & (state.pending_tutor_player >= 0)
    if not valid.any():
        return
    state.pending_tutor_player = torch.where(
        valid, torch.tensor(-1, device=device, dtype=torch.int32),
        state.pending_tutor_player,
    )
    state.pending_tutor_matches = torch.where(
        valid.view(N, 1),
        torch.tensor(-1, device=device, dtype=torch.int32),
        state.pending_tutor_matches,
    )


def _apply_decline_post_move_attack(state, mask):
    """Phase 14.1: clear pending post-move attacker for masked games.

    Only valid where pending_post_move_attacker >= 0; defensively re-mask.
    """
    if not mask.any():
        return
    device = mask.device
    valid = mask & (state.pending_post_move_attacker >= 0)
    if not valid.any():
        return
    state.pending_post_move_attacker = torch.where(
        valid,
        torch.tensor(-1, device=device, dtype=torch.int32),
        state.pending_post_move_attacker,
    )


def _apply_rally_forward(state, mask, card_id, moved_slot):
    """Move all other friendly minions with same card_id forward 1 space."""
    N = mask.shape[0]
    device = mask.device

    owner = state.minion_owner[torch.arange(N, device=device), moved_slot]  # [N]
    # Forward direction: P0 = +1 row, P1 = -1 row
    forward = torch.where(owner == 0, torch.tensor(1, device=device), torch.tensor(-1, device=device))  # [N]

    # For each minion slot, check if it's a rally candidate
    for s in range(25):  # MAX_MINIONS
        is_candidate = (
            mask
            & state.minion_alive[:, s]
            & (state.minion_owner[:, s] == owner)
            & (state.minion_card_id[:, s] == card_id)
            & (s != moved_slot)  # not the minion that just moved
        )
        if not is_candidate.any():
            continue

        cur_row = state.minion_row[:, s]
        cur_col = state.minion_col[:, s]
        new_row = (cur_row + forward).clamp(0, 4)

        # Check destination is in bounds and empty
        can_rally = is_candidate & (new_row >= 0) & (new_row < 5) & (new_row != cur_row)
        if not can_rally.any():
            continue

        # Check board empty at destination
        arange_n = torch.arange(N, device=device)
        dest_occupied = state.board[arange_n, new_row, cur_col] >= 0
        can_rally = can_rally & ~dest_occupied

        if not can_rally.any():
            continue

        # Move the minion
        state.board[arange_n, cur_row, cur_col] = torch.where(
            can_rally, torch.tensor(-1, device=device, dtype=torch.int32),
            state.board[arange_n, cur_row, cur_col]
        )
        state.board[arange_n, new_row, cur_col] = torch.where(
            can_rally, torch.tensor(s, device=device, dtype=torch.int32),
            state.board[arange_n, new_row, cur_col]
        )
        state.minion_row[:, s] = torch.where(can_rally, new_row, state.minion_row[:, s])


def apply_play_card_batch(state, mask, action_type, hand_idx, target_flat, card_table):
    """Play a card from hand (minion deploy or magic cast).

    Batched approach:
    1. All mana deduction, hand removal, graveyard adds are tensor ops
    2. Minion deployment is tensor ops
    3. Effects are dispatched via apply_effects_batch with masks
    """
    is_play = mask & (action_type == 0)
    if not is_play.any():
        return

    N = mask.shape[0]
    device = mask.device
    arange_n = torch.arange(N, device=device)
    ap = state.active_player  # [N]

    # Get card from hand
    safe_hi = hand_idx.clamp(0, MAX_HAND - 1).long()
    card_id = state.hands[arange_n, ap, safe_hi]  # [N]
    valid = is_play & (card_id >= 0)

    if not valid.any():
        return

    safe_cid = card_id.clamp(min=0).long()

    # Card properties
    ctype = card_table.card_type[safe_cid]  # [N]
    cost = card_table.mana_cost[safe_cid]   # [N]

    # Spend mana (batched)
    state.player_mana[arange_n, ap] = torch.where(
        valid, state.player_mana[arange_n, ap] - cost, state.player_mana[arange_n, ap]
    )

    # Remove card from hand (batched shift-left)
    _remove_from_hand_batch(state, valid, ap, safe_hi, arange_n)

    # Phase 14.5: Only magic one-shots route to graveyard on play.
    # Minion plays leave the hand via remove-only; the card lands in the
    # graveyard later via death cleanup iff from_deck=True. Mirrors Python
    # Wave 1 split (remove_from_hand vs discard_from_hand).
    is_magic_type = valid & (ctype == 1)
    if is_magic_type.any():
        _add_to_graveyard_batch(state, is_magic_type, ap, card_id, arange_n)

    # --- SUMMON SACRIFICE: destroy a tribe card from hand ---
    sac_tribe = card_table.summon_sacrifice_tribe_id[safe_cid]  # [N]
    needs_sac = valid & (sac_tribe > 0)
    if needs_sac.any():
        _apply_summon_sacrifice_batch(state, needs_sac, ap, sac_tribe, card_table, arange_n)

    # --- MINION DEPLOY ---
    is_minion = valid & (ctype == 0)
    if is_minion.any():
        _deploy_minion_batch(state, is_minion, ap, card_id, target_flat, card_table, arange_n)

    # --- MAGIC EFFECTS ---
    is_magic = valid & (ctype == 1)
    if is_magic.any():
        # apply_effects_batch handles the entire batch with a mask
        caster_slots = torch.full((N,), -1, dtype=torch.int32, device=device)
        apply_effects_batch(
            state, safe_cid.int(), 0, ap, caster_slots,
            target_flat.int(), card_table, is_magic,
        )


def _deploy_minion_batch(state, deploy_mask, owners, card_ids, target_flat, card_table, arange_n):
    """Deploy minions for all games in deploy_mask -- fully batched."""
    N = deploy_mask.shape[0]
    device = deploy_mask.device

    row = (target_flat // GRID_COLS).clamp(0, 4)
    col = (target_flat % GRID_COLS).clamp(0, 4)

    # Get next available slot
    slot = state.next_minion_slot.clone()  # [N]
    valid = deploy_mask & (slot < MAX_MINIONS) & (target_flat >= 0) & (target_flat < GRID_SIZE)

    if not valid.any():
        return

    safe_slot = slot.clamp(0, MAX_MINIONS - 1).long()
    safe_cid = card_ids.clamp(min=0).long()

    # Set board cell
    state.board[arange_n, row, col] = torch.where(
        valid, safe_slot.int(), state.board[arange_n, row, col]
    )
    # Set minion properties
    state.minion_card_id[arange_n, safe_slot] = torch.where(
        valid, card_ids, state.minion_card_id[arange_n, safe_slot]
    )
    state.minion_owner[arange_n, safe_slot] = torch.where(
        valid, owners, state.minion_owner[arange_n, safe_slot]
    )
    state.minion_row[arange_n, safe_slot] = torch.where(
        valid, row.int(), state.minion_row[arange_n, safe_slot]
    )
    state.minion_col[arange_n, safe_slot] = torch.where(
        valid, col.int(), state.minion_col[arange_n, safe_slot]
    )
    base_health = card_table.health[safe_cid]
    state.minion_health[arange_n, safe_slot] = torch.where(
        valid, base_health, state.minion_health[arange_n, safe_slot]
    )
    state.minion_atk_bonus[arange_n, safe_slot] = torch.where(
        valid, torch.tensor(0, device=device, dtype=torch.int32),
        state.minion_atk_bonus[arange_n, safe_slot]
    )
    # Reset is_burning for the new occupant of this slot
    state.is_burning[arange_n, safe_slot] = torch.where(
        valid, torch.tensor(False, device=device),
        state.is_burning[arange_n, safe_slot]
    )
    # Reset max_health_bonus and dark_matter_stacks for the new occupant
    state.minion_max_health_bonus[arange_n, safe_slot] = torch.where(
        valid, torch.tensor(0, device=device, dtype=torch.int32),
        state.minion_max_health_bonus[arange_n, safe_slot]
    )
    state.minion_dark_matter_stacks[arange_n, safe_slot] = torch.where(
        valid, torch.tensor(0, device=device, dtype=torch.int32),
        state.minion_dark_matter_stacks[arange_n, safe_slot]
    )
    state.minion_alive[arange_n, safe_slot] = torch.where(
        valid, torch.tensor(True, device=device),
        state.minion_alive[arange_n, safe_slot]
    )
    # Phase 14.5: normal PLAY_CARD deploys are from_deck=True. Tokens spawned
    # via activated abilities (no tensor path exists today) would set False
    # explicitly; leave the False default in those hypothetical paths.
    state.minion_from_deck[arange_n, safe_slot] = torch.where(
        valid, torch.tensor(True, device=device),
        state.minion_from_deck[arange_n, safe_slot]
    )
    state.next_minion_slot = torch.where(
        valid, slot + 1, state.next_minion_slot
    )

    # Trigger ON_PLAY effects for deployed minions
    # Pass -1 as target: action encoding doesn't capture ON_PLAY target for minions
    tgt = torch.full((N,), -1, dtype=torch.int32, device=device)
    apply_effects_batch(
        state, safe_cid.int(), 0, owners, safe_slot.int(), tgt, card_table, valid,
    )  # trigger=ON_PLAY=0


def apply_attack_batch(state, mask, action_type, source_flat, target_flat, card_table):
    """Apply ATTACK action -- simultaneous damage exchange, fully batched."""
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

    # Get attacker and defender slots from board
    a_slot = state.board[arange_n, src_row, src_col]  # [N]
    d_slot = state.board[arange_n, tgt_row, tgt_col]  # [N]
    valid = is_attack & (a_slot >= 0) & (d_slot >= 0)

    if not valid.any():
        return

    safe_a_slot = a_slot.clamp(0).long()
    safe_d_slot = d_slot.clamp(0).long()

    # Phase 14.1: pending-post-move-attack gate.
    # If pending_post_move_attacker[n] >= 0, ATTACK is only valid in that
    # game when the attacker slot equals the pending slot.
    has_pending = state.pending_post_move_attacker >= 0
    pending_match = a_slot == state.pending_post_move_attacker
    valid = valid & (~has_pending | pending_match)
    if not valid.any():
        return

    # Get card IDs for attacker and defender
    a_cid = state.minion_card_id[arange_n, safe_a_slot].clamp(0).long()
    d_cid = state.minion_card_id[arange_n, safe_d_slot].clamp(0).long()

    # Effective attack = base + bonus
    a_eff = card_table.attack[a_cid] + state.minion_atk_bonus[arange_n, safe_a_slot]
    d_eff = card_table.attack[d_cid] + state.minion_atk_bonus[arange_n, safe_d_slot]

    # Range combat with first-strike rules
    a_range = card_table.attack_range[a_cid]
    d_range = card_table.attack_range[d_cid]
    dist = (src_row - tgt_row).abs() + (src_col - tgt_col).abs()

    def_can_reach = ((d_range == 0) & (dist <= 1)) | ((d_range > 0) & (dist <= d_range))
    attacker_first = valid & (a_range <= d_range) & ~((a_range == d_range) & def_can_reach)
    simultaneous = valid & def_can_reach & ~attacker_first
    no_retaliate = valid & ~def_can_reach

    # Attacker always hits defender
    state.minion_health[arange_n, safe_d_slot] = torch.where(
        valid, state.minion_health[arange_n, safe_d_slot] - a_eff,
        state.minion_health[arange_n, safe_d_slot]
    )

    # First strike: defender retaliates only if alive
    def_alive_after = state.minion_health[arange_n, safe_d_slot] > 0
    first_strike_ret = attacker_first & def_alive_after
    state.minion_health[arange_n, safe_a_slot] = torch.where(
        first_strike_ret, state.minion_health[arange_n, safe_a_slot] - d_eff,
        state.minion_health[arange_n, safe_a_slot]
    )

    # Simultaneous: defender always retaliates
    state.minion_health[arange_n, safe_a_slot] = torch.where(
        simultaneous, state.minion_health[arange_n, safe_a_slot] - d_eff,
        state.minion_health[arange_n, safe_a_slot]
    )

    # --- Trigger ON_ATTACK for attacker ---
    atk_alive = valid & state.minion_alive[arange_n, safe_a_slot]
    if atk_alive.any():
        apply_effects_batch(
            state, a_cid.int(), 2, state.minion_owner[arange_n, safe_a_slot],
            safe_a_slot.int(), target_flat.int(), card_table, atk_alive,
        )

    # --- Trigger ON_DAMAGED for attacker (if defender had attack > 0) ---
    atk_damaged = valid & (d_eff > 0) & state.minion_alive[arange_n, safe_a_slot]
    if atk_damaged.any():
        apply_effects_batch(
            state, a_cid.int(), 3, state.minion_owner[arange_n, safe_a_slot],
            safe_a_slot.int(), target_flat.int(), card_table, atk_damaged,
        )

    # --- Trigger ON_DAMAGED for defender (if attacker had attack > 0) ---
    def_damaged = valid & (a_eff > 0) & state.minion_alive[arange_n, safe_d_slot]
    if def_damaged.any():
        apply_effects_batch(
            state, d_cid.int(), 3, state.minion_owner[arange_n, safe_d_slot],
            safe_d_slot.int(), source_flat.int(), card_table, def_damaged,
        )

    # Phase 14.1: clear pending post-move attacker after the gated attack.
    clear_pending = valid & (state.pending_post_move_attacker >= 0)
    state.pending_post_move_attacker = torch.where(
        clear_pending,
        torch.tensor(-1, device=device, dtype=torch.int32),
        state.pending_post_move_attacker,
    )


def apply_sacrifice_batch(state, mask, action_type, source_flat, card_table):
    """Sacrifice minion on opponent's back row, dealing damage to opponent."""
    is_sac = mask & (action_type == 6)
    if not is_sac.any():
        return

    N = mask.shape[0]
    device = mask.device
    arange_n = torch.arange(N, device=device)

    src_row = (source_flat // GRID_COLS).clamp(0, 4)
    src_col = (source_flat % GRID_COLS).clamp(0, 4)

    slot = state.board[arange_n, src_row, src_col]  # [N]
    valid = is_sac & (slot >= 0)

    if not valid.any():
        return

    safe_slot = slot.clamp(0).long()
    cid = state.minion_card_id[arange_n, safe_slot]
    owner = state.minion_owner[arange_n, safe_slot]
    eff_atk = card_table.attack[cid.clamp(0).long()] + state.minion_atk_bonus[arange_n, safe_slot]

    # Remove minion from board
    state.board[arange_n, src_row, src_col] = torch.where(
        valid, torch.tensor(EMPTY, device=device, dtype=torch.int32),
        state.board[arange_n, src_row, src_col]
    )
    state.minion_alive[arange_n, safe_slot] = torch.where(
        valid, torch.tensor(False, device=device),
        state.minion_alive[arange_n, safe_slot]
    )

    # Phase 14.5: Only from_deck minions enter the graveyard on sacrifice.
    # Tokens vanish silently. Mirrors Python _apply_sacrifice gating.
    from_deck_mask = state.minion_from_deck[arange_n, safe_slot]
    _add_to_graveyard_batch(state, valid & from_deck_mask, owner, cid, arange_n)

    # Deal damage to opponent
    opponent = (1 - state.active_player).int()  # [N]

    # Damage player 0 where opponent==0 and valid
    dmg_p0 = valid & (opponent == 0)
    if dmg_p0.any():
        state.player_hp[:, 0] -= (eff_atk * dmg_p0.int())
    dmg_p1 = valid & (opponent == 1)
    if dmg_p1.any():
        state.player_hp[:, 1] -= (eff_atk * dmg_p1.int())


def apply_activate_ability_batch(state, mask, action_type, source_flat, card_table):
    """Apply ACTIVATE_ABILITY -- hardcoded Ratchanter dispatch (Phase 14.x).

    Mirrors Python ``_apply_activate_ability`` + ``_apply_conjure_rat_and_buff``
    for the only card with an activated ability today (Ratchanter,
    ``conjure_rat_and_buff`` with target ``none`` and mana_cost 2).

    For each game in mask & (action_type == ACTIVATE_ABILITY) where the
    minion at source_flat is the active player's living Ratchanter and they
    have >=2 mana:
      1. Spend 2 mana
      2. Buff every other friendly Rat by magnitude = 1 + caster_dm_stacks:
         attack_bonus += magnitude
         max_health_bonus += magnitude
         current_health += magnitude
      3. If the caster's deck contains any "rat" card, enter pending_tutor
         with up to K=8 deck indices.
    The PASS-fatigue path in ``_step_action_phase`` already excludes
    ACTIVATE_ABILITY (action_type == 11) because it only fires fatigue on
    ``action_type == 4``.

    TODO: when a second activated-ability card lands, generalise via a
    per-card ``activated_ability_effect_type`` column on CardTable.
    """
    is_act = mask & (action_type == 11)
    if not is_act.any():
        return
    if card_table.ratchanter_card_id < 0:
        # Library does not contain Ratchanter — silently no-op (used in
        # synthetic tests with custom card sets).
        return

    N = mask.shape[0]
    device = mask.device
    arange_n = torch.arange(N, device=device)
    ap = state.active_player

    src_row = (source_flat // GRID_COLS).clamp(0, 4)
    src_col = (source_flat % GRID_COLS).clamp(0, 4)
    slot = state.board[arange_n, src_row, src_col]  # [N]
    valid = is_act & (slot >= 0)
    if not valid.any():
        return

    safe_slot = slot.clamp(0).long()
    cid = state.minion_card_id[arange_n, safe_slot]
    owner = state.minion_owner[arange_n, safe_slot]

    # Caster must be the active player's living Ratchanter
    valid = (
        valid
        & state.minion_alive[arange_n, safe_slot]
        & (owner == ap)
        & (cid == card_table.ratchanter_card_id)
    )
    # Mana cost 2
    valid = valid & (state.player_mana[arange_n, ap] >= 2)
    if not valid.any():
        return

    # Spend mana
    state.player_mana[arange_n, ap] = torch.where(
        valid, state.player_mana[arange_n, ap] - 2, state.player_mana[arange_n, ap]
    )

    # Magnitude per game = 1 + caster.dark_matter_stacks
    magnitude = (1 + state.minion_dark_matter_stacks[arange_n, safe_slot]).int()  # [N]

    # Buff every other friendly Rat on the board.
    # Iterate over MAX_MINIONS slots (constant 25), not over batch.
    caster_slot = safe_slot  # rename for clarity
    for s in range(MAX_MINIONS):
        target_alive = state.minion_alive[:, s]
        target_cid = state.minion_card_id[:, s].clamp(0).long()
        target_is_rat = card_table.is_rat[target_cid]
        target_owner = state.minion_owner[:, s]
        # Exclude the caster slot itself per game (slot equality check)
        not_caster = caster_slot != s
        hit = (
            valid
            & target_alive
            & target_is_rat
            & (target_owner == ap)
            & not_caster
        )
        if not hit.any():
            continue
        delta = magnitude * hit.int()
        state.minion_atk_bonus[:, s] = state.minion_atk_bonus[:, s] + delta
        state.minion_max_health_bonus[:, s] = state.minion_max_health_bonus[:, s] + delta
        state.minion_health[:, s] = state.minion_health[:, s] + delta

    # Enter pending_tutor for "rat" if the caster's deck has any. Reuses
    # the existing pending_tutor pipeline; the engine will reinterpret
    # subsequent PLAY_CARD / PASS actions as TUTOR_SELECT / DECLINE_TUTOR.
    if card_table.rat_card_id < 0:
        return

    K = 8
    deck_top = state.deck_tops[arange_n, ap]
    deck_size = state.deck_sizes[arange_n, ap]
    matches = torch.full((N, K), -1, dtype=torch.int32, device=device)
    counts = torch.zeros(N, dtype=torch.int32, device=device)

    for d in range(state.decks.shape[2]):
        d_card = state.decks[arange_n, ap, d]
        in_deck = valid & (d >= deck_top) & (d < deck_size) & (d_card == card_table.rat_card_id)
        if not in_deck.any():
            continue
        slot_idx = counts.clamp(0, K - 1).long()
        overflow = in_deck & (counts >= K)
        if bool(overflow.any().item()):
            raise AssertionError(
                f"activate_ability tutor: more than K={K} rat matches in one game"
            )
        cur = matches[arange_n, slot_idx]
        new_val = torch.where(
            in_deck, torch.tensor(d, device=device, dtype=torch.int32), cur
        )
        matches[arange_n, slot_idx] = new_val
        counts = counts + in_deck.int()

    found = valid & (counts > 0)
    if not found.any():
        return

    # Mutex defense: pending_tutor cannot coexist with pending_post_move_attack
    bad = found & (state.pending_post_move_attacker >= 0)
    if bool(bad.any().item()):
        raise AssertionError(
            "activate_ability cannot enter pending_tutor while pending_post_move_attack is set"
        )

    state.pending_tutor_player = torch.where(
        found, ap.int(), state.pending_tutor_player
    )
    state.pending_tutor_matches = torch.where(
        found.view(N, 1), matches, state.pending_tutor_matches
    )


def apply_react_batch(state, mask, action_type, hand_idx, target_flat, card_table):
    """Play a react card: spend mana, discard, push to stack, swap react_player."""
    is_react = mask & (action_type == 5)
    if not is_react.any():
        return

    N = mask.shape[0]
    device = mask.device
    arange_n = torch.arange(N, device=device)

    rp = state.react_player  # [N]
    safe_hi = hand_idx.clamp(0, MAX_HAND - 1).long()

    # Check hand slot validity
    hand_size = state.hand_sizes[arange_n, rp]
    valid = is_react & (safe_hi < hand_size)

    if not valid.any():
        return

    cid = state.hands[arange_n, rp, safe_hi]
    valid = valid & (cid >= 0)

    if not valid.any():
        return

    safe_cid = cid.clamp(0).long()

    # Determine cost: multi-purpose uses react_mana_cost, others use mana_cost
    is_multi = card_table.is_multi_purpose[safe_cid]
    cost = torch.where(is_multi, card_table.react_mana_cost[safe_cid], card_table.mana_cost[safe_cid])

    # Spend mana
    state.player_mana[arange_n, rp] = torch.where(
        valid, state.player_mana[arange_n, rp] - cost, state.player_mana[arange_n, rp]
    )

    # Remove from hand
    _remove_from_hand_batch(state, valid, rp, safe_hi, arange_n)

    # Add to graveyard
    _add_to_graveyard_batch(state, valid, rp, cid, arange_n)

    # Push onto react stack
    depth = state.react_stack_depth  # [N]
    can_push = valid & (depth < 10)

    if can_push.any():
        safe_depth = depth.clamp(0, 9).long()
        state.react_stack[arange_n, safe_depth, 0] = torch.where(
            can_push, rp, state.react_stack[arange_n, safe_depth, 0]
        )
        state.react_stack[arange_n, safe_depth, 1] = torch.where(
            can_push, cid, state.react_stack[arange_n, safe_depth, 1]
        )
        state.react_stack[arange_n, safe_depth, 2] = torch.where(
            can_push, target_flat.int(), state.react_stack[arange_n, safe_depth, 2]
        )
        state.react_stack_depth = torch.where(
            can_push, depth + 1, depth
        )

    # Swap react player
    state.react_player = torch.where(
        valid, (1 - rp).int(), rp
    )


# ---------------------------------------------------------------------------
# Summon sacrifice -- fully batched
# ---------------------------------------------------------------------------


def _apply_summon_sacrifice_batch(state, mask, player, req_tribe_id, card_table, arange_n):
    """Sacrifice the first card of matching tribe from hand -- batched.

    Finds the first hand slot with a card whose tribe_id matches req_tribe_id,
    removes it from hand, and adds it to graveyard.
    """
    N = mask.shape[0]
    device = mask.device

    hand_size = state.hand_sizes[arange_n, player]  # [N]
    found_idx = torch.full((N,), -1, dtype=torch.long, device=device)

    for hi in range(MAX_HAND):
        in_range = hi < hand_size
        cid = state.hands[arange_n, player, hi]
        safe_cid = cid.clamp(0).long()
        tribe = card_table.tribe_id[safe_cid]
        is_match = mask & in_range & (cid >= 0) & (tribe == req_tribe_id) & (found_idx < 0)
        found_idx = torch.where(is_match, torch.tensor(hi, device=device, dtype=torch.long), found_idx)

    found = mask & (found_idx >= 0)
    if not found.any():
        return

    safe_idx = found_idx.clamp(0).long()
    sac_card = state.hands[arange_n, player, safe_idx]

    _remove_from_hand_batch(state, found, player, safe_idx, arange_n)
    # Phase 14.5: summon_sacrifice_tribe discards route to EXHAUST, not
    # graveyard. Mirrors Python Player.exhaust_from_hand.
    _add_to_exhaust_batch(state, found, player, sac_card, arange_n)


# ---------------------------------------------------------------------------
# Hand / graveyard helpers -- fully batched
# ---------------------------------------------------------------------------

def _remove_from_hand_batch(state, valid_mask, player, hand_idx, arange_n):
    """Remove card at hand_idx, shift remaining cards left -- batched.

    Iterates over MAX_HAND slots (fixed 10 iterations), not over batch N.
    """
    N = valid_mask.shape[0]
    device = valid_mask.device

    hand_size = state.hand_sizes[arange_n, player]  # [N]

    # For each slot position, shift left if slot >= hand_idx and slot < hand_size - 1
    for j in range(MAX_HAND - 1):
        should_shift = valid_mask & (j >= hand_idx) & (j < hand_size - 1)
        if should_shift.any():
            next_card = state.hands[arange_n, player, j + 1]
            state.hands[arange_n, player, j] = torch.where(
                should_shift, next_card, state.hands[arange_n, player, j]
            )

    # Clear the last occupied slot
    last_slot = (hand_size - 1).clamp(0, MAX_HAND - 1).long()
    should_clear = valid_mask & (hand_size > 0)
    state.hands[arange_n, player, last_slot] = torch.where(
        should_clear,
        torch.tensor(EMPTY, device=device, dtype=torch.int32),
        state.hands[arange_n, player, last_slot]
    )

    # Decrement hand size
    state.hand_sizes[arange_n, player] = torch.where(
        valid_mask & (hand_size > 0), hand_size - 1, hand_size
    )


def _add_to_graveyard_batch(state, valid_mask, player, card_id, arange_n):
    """Add card to graveyard at next slot -- batched."""
    N = valid_mask.shape[0]
    device = valid_mask.device

    gs = state.graveyard_sizes[arange_n, player]  # [N]
    can_add = valid_mask & (gs < 80)

    if not can_add.any():
        return

    safe_gs = gs.clamp(0, 79).long()
    state.graveyards[arange_n, player, safe_gs] = torch.where(
        can_add, card_id, state.graveyards[arange_n, player, safe_gs]
    )
    state.graveyard_sizes[arange_n, player] = torch.where(
        can_add, gs + 1, gs
    )


def _add_to_exhaust_batch(state, valid_mask, player, card_id, arange_n):
    """Phase 14.5: append card to exhaust pile at next slot -- batched.

    Parallel to _add_to_graveyard_batch. Used by discard-for-cost paths
    (summon_sacrifice_tribe). Mirrors Python Player.exhaust_from_hand.
    """
    device = valid_mask.device
    gs = state.exhaust_sizes[arange_n, player]  # [N]
    can_add = valid_mask & (gs < 80)
    if not can_add.any():
        return
    safe_gs = gs.clamp(0, 79).long()
    state.exhausts[arange_n, player, safe_gs] = torch.where(
        can_add, card_id, state.exhausts[arange_n, player, safe_gs]
    )
    state.exhaust_sizes[arange_n, player] = torch.where(
        can_add, gs + 1, gs
    )
