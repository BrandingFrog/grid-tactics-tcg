"""Batched legal action mask computation -- fully vectorized.

Produces [N, 1262] bool mask matching the Python engine's legal_actions().
All computation as batched tensor operations. NO Python for-loops over any
game dimension. Minimal CUDA kernel launches via bulk tensor ops and scatter_.
"""

from __future__ import annotations

import torch

from grid_tactics.tensor_engine.constants import (
    ACTION_SPACE_SIZE,
    ATTACK_BASE,
    BACK_ROW_P1,
    BACK_ROW_P2,
    DRAW_IDX,
    GRID_COLS,
    GRID_ROWS,
    GRID_SIZE,
    MAX_EFFECTS_PER_CARD,
    MAX_HAND,
    MAX_MINIONS,
    MAX_REACT_DEPTH,
    MOVE_BASE,
    PASS_IDX,
    PLAY_CARD_BASE,
    REACT_BASE,
    SACRIFICE_BASE,
)

# Precomputed direction offsets for moves
_DR = [-1, 1, 0, 0]
_DC = [0, 0, -1, 1]


def compute_legal_mask_batch(state, card_table) -> torch.Tensor:
    """Compute [N, ACTION_SPACE_SIZE] bool legal action mask for all games.

    Returns tensor on same device as state.
    """
    N = state.board.shape[0]
    device = state.board.device
    mask = torch.zeros(N, ACTION_SPACE_SIZE, dtype=torch.bool, device=device)

    # Game-over games get all-zero mask
    alive = ~state.is_game_over
    if not alive.any():
        return mask

    in_action = alive & (state.phase == 0)
    in_react = alive & (state.phase == 1)

    if in_action.any():
        _compute_action_phase_mask(mask, state, card_table, in_action)

    if in_react.any():
        _compute_react_phase_mask(mask, state, card_table, in_react)

    # Safety: if any alive game has no legal actions, force PASS
    no_actions = alive & ~mask.any(dim=1)
    if no_actions.any():
        mask[no_actions, PASS_IDX] = True

    # Phase 14.1: pending-post-move-attack override.
    # For games where pending_post_move_attacker[n] >= 0, restrict the legal
    # mask to (a) ATTACK slots from the pending attacker against in-range
    # enemies, and (b) slot 1001 (PASS_IDX, reinterpreted as
    # DECLINE_POST_MOVE_ATTACK by _step_action_phase). All other slots are
    # cleared. Slot 1001 is the *only* slot whose meaning changes; the
    # action int layout [0:1262] is unchanged.
    if hasattr(state, "pending_post_move_attacker"):
        _apply_pending_post_move_attack_override(mask, state, alive, card_table)

    # Phase 14.2: pending_tutor override.
    # For games where pending_tutor_player[n] >= 0, restrict the legal mask to
    # (a) PLAY_CARD slots [PLAY_CARD_BASE + i*GRID_SIZE for i in 0..n_matches)
    # which the encoder reinterprets as TUTOR_SELECT[match_idx=i] while
    # pending, and (b) slot 1001 (PASS_IDX, reinterpreted as DECLINE_TUTOR).
    # All other slots are cleared. Mutex with pending_post_move_attacker is
    # asserted: a game cannot have both pendings active.
    if hasattr(state, "pending_tutor_player"):
        _apply_pending_tutor_override(mask, state, alive)

    return mask


def _apply_pending_tutor_override(mask, state, alive):
    """Restrict legal mask to TUTOR_SELECT[0..n) + slot 1001 for pending games.

    TUTOR_SELECT encoding mirrors the Python ``ActionEncoder``: match index
    ``i`` -> ``PLAY_CARD_BASE + i * GRID_SIZE`` (cell sub-index pinned to 0).
    DECLINE_TUTOR -> slot 1001.
    """
    device = mask.device

    pending_player = state.pending_tutor_player  # [N] int32, -1 = none
    has_pending_tutor = alive & (pending_player >= 0)
    if not has_pending_tutor.any():
        return

    # Mutex defense: no game may have both pending flavours.
    if hasattr(state, "pending_post_move_attacker"):
        both = has_pending_tutor & (state.pending_post_move_attacker >= 0)
        assert not bool(both.any().item()), (
            "pending_tutor and pending_post_move_attacker active in same game"
        )

    # Per-game number of valid match slots (count of non-(-1) entries).
    n_matches = (state.pending_tutor_matches >= 0).sum(dim=-1).long()  # [N]

    # Zero out all slots for pending-tutor games (we'll re-enable below).
    mask[has_pending_tutor] = False

    # Enable PLAY_CARD slots PLAY_CARD_BASE + i*GRID_SIZE for i in 0..K-1,
    # gated by (i < n_matches[g]) AND has_pending_tutor[g].
    K = state.pending_tutor_matches.shape[1]
    i_range = torch.arange(K, device=device)  # [K]
    slot_idx = (PLAY_CARD_BASE + i_range * GRID_SIZE).long()  # [K]

    enable = has_pending_tutor.unsqueeze(1) & (i_range.unsqueeze(0) < n_matches.unsqueeze(1))  # [N, K]
    # Scatter the enable bits into the corresponding slot columns.
    slot_idx_exp = slot_idx.unsqueeze(0).expand(mask.shape[0], K)  # [N, K]
    mask.scatter_(1, slot_idx_exp, enable)

    # Enable slot 1001 (DECLINE_TUTOR) for all pending-tutor games.
    mask[has_pending_tutor, PASS_IDX] = True


def _apply_pending_post_move_attack_override(mask, state, alive, card_table):
    """Restrict legal mask to ATTACK-from-pending + slot 1001 for pending games.

    Pending implies the attacker is a *melee* minion (Wave 1 invariant: only
    melee minions enter pending and only when at least one in-range enemy
    exists from the new tile). Melee range = manhattan==1 AND orthogonal,
    which collapses to manhattan==1 on a grid (any manhattan==1 pair is
    orthogonal). We therefore enable ATTACK slots from the pending attacker's
    position to each of the 4 cardinal-adjacent cells that contain an alive
    enemy minion.
    """
    N = mask.shape[0]
    device = mask.device

    pending = state.pending_post_move_attacker  # [N] int32, -1 = none
    has_pending = alive & (pending >= 0)
    if not has_pending.any():
        return

    arange_n = torch.arange(N, device=device)
    safe_pending = pending.clamp(0).long()  # [N]

    # Attacker position and owner
    a_row = state.minion_row[arange_n, safe_pending]  # [N]
    a_col = state.minion_col[arange_n, safe_pending]  # [N]
    a_owner = state.minion_owner[arange_n, safe_pending]  # [N]
    a_flat = (a_row * GRID_COLS + a_col).clamp(0, GRID_SIZE - 1).long()  # [N]

    # Build a [N, 25] map of "cell contains an enemy of the pending attacker
    # that is alive". Enemy = minion_alive & owner != a_owner.
    minion_flat = (state.minion_row * GRID_COLS + state.minion_col).clamp(
        0, GRID_SIZE - 1
    ).long()  # [N, MAX_MINIONS]
    is_enemy = state.minion_alive & (state.minion_owner != a_owner.unsqueeze(1))
    enemy_cell_mask = torch.zeros(N, GRID_SIZE, dtype=torch.bool, device=device)
    enemy_cell_mask.scatter_(1, minion_flat, is_enemy)

    # Compute the 4 melee target cells (up/down/left/right) per game.
    # For each adjacent direction compute (nr, nc) and check bounds + enemy.
    dr = torch.tensor(_DR, device=device)  # [4]
    dc = torch.tensor(_DC, device=device)  # [4]
    nr = a_row.unsqueeze(1) + dr  # [N, 4]
    nc = a_col.unsqueeze(1) + dc  # [N, 4]
    in_bounds = (nr >= 0) & (nr < GRID_ROWS) & (nc >= 0) & (nc < GRID_COLS)
    nflat = (nr * GRID_COLS + nc).clamp(0, GRID_SIZE - 1).long()  # [N, 4]
    has_enemy_at = torch.gather(enemy_cell_mask, 1, nflat)  # [N, 4]

    # Effective attack gate: pending attacker must have base+bonus > 0.
    a_cid = state.minion_card_id[arange_n, safe_pending].clamp(0).long()
    a_eff = (
        card_table.attack[a_cid]
        + state.minion_atk_bonus[arange_n, safe_pending]
    )  # [N]
    can_strike_pending = has_pending & (a_eff > 0)
    can_attack = can_strike_pending.unsqueeze(1) & in_bounds & has_enemy_at  # [N, 4]

    # Zero out all slots for pending games (we'll re-enable below)
    mask[has_pending] = False

    # Enable ATTACK slots: ATTACK_BASE + a_flat * 25 + target_flat
    # action_idx[N, 4] = ATTACK_BASE + a_flat[:, None] * 25 + nflat
    action_idx = (ATTACK_BASE + a_flat.unsqueeze(1) * GRID_SIZE + nflat).long()
    mask.scatter_(1, action_idx, can_attack)

    # Enable slot 1001 (DECLINE) for all pending games (always legal)
    mask[has_pending, PASS_IDX] = True


def _compute_action_phase_mask(mask, state, card_table, phase_mask):
    """Compute legal actions for ACTION phase games."""
    N = mask.shape[0]
    device = mask.device
    arange_n = torch.arange(N, device=device)
    ap = state.active_player  # [N]
    num_cards = card_table.num_cards

    # Common data used by multiple sub-computations
    board_flat = state.board.reshape(N, GRID_SIZE)
    board_empty = board_flat == -1  # [N, 25]

    player_mana = state.player_mana[arange_n, ap]  # [N]
    hand_sizes = state.hand_sizes[arange_n, ap]     # [N]

    minion_owner_matches = state.minion_owner == ap.unsqueeze(1)  # [N, MAX_MINIONS]
    friendly_alive = state.minion_alive & minion_owner_matches & phase_mask.unsqueeze(1)
    enemy_alive = state.minion_alive & ~minion_owner_matches & phase_mask.unsqueeze(1)

    minion_flat = (state.minion_row * GRID_COLS + state.minion_col).clamp(0, GRID_SIZE - 1).long()

    # --- DRAW (as action, in addition to auto-draw at turn start) ---
    deck_top = state.deck_tops[arange_n, ap]
    deck_size = state.deck_sizes[arange_n, ap]
    hand_full = hand_sizes >= MAX_HAND
    mask[phase_mask & (deck_top < deck_size) & ~hand_full, DRAW_IDX] = True

    # --- PLAY_CARD ---
    _compute_play_card_mask(
        mask, state, card_table, phase_mask, ap, arange_n,
        player_mana, hand_sizes, board_empty, enemy_alive,
        minion_flat, num_cards
    )

    # --- MOVE ---
    _compute_move_mask(mask, state, phase_mask, friendly_alive, board_flat, card_table)

    # --- ATTACK ---
    _compute_attack_mask(
        mask, card_table, friendly_alive, enemy_alive, minion_flat,
        state.minion_card_id, state.minion_atk_bonus,
    )

    # --- SACRIFICE ---
    _compute_sacrifice_mask(mask, state, ap, friendly_alive)


def _compute_play_card_mask(mask, state, card_table, phase_mask, ap, arange_n,
                             player_mana, hand_sizes, board_empty, enemy_alive,
                             minion_flat, num_cards):
    """Compute PLAY_CARD legal actions -- fully vectorized."""
    N = mask.shape[0]
    device = mask.device

    # Cell row indices: [25]
    cell_rows = torch.arange(GRID_SIZE, device=device) // GRID_COLS

    # Deploy row masks: deploy_masks[player][is_ranged] -> [25]
    p0_melee = (cell_rows == 0) | (cell_rows == 1)
    p0_ranged = cell_rows == 0
    p1_melee = (cell_rows == 3) | (cell_rows == 4)
    p1_ranged = cell_rows == 4
    deploy_masks = torch.stack([
        torch.stack([p0_melee, p0_ranged]),
        torch.stack([p1_melee, p1_ranged]),
    ])  # [2, 2, 25]

    # Enemy minion positions on grid: [N, 25]
    enemy_pos_mask = torch.zeros(N, GRID_SIZE, dtype=torch.bool, device=device)
    enemy_pos_mask.scatter_(1, minion_flat, enemy_alive & state.minion_alive)

    # Gather all card IDs for active player's hand: [N, MAX_HAND]
    all_card_ids = state.hands[arange_n, ap]

    # Hand slot validity: [N, MAX_HAND]
    hi_range = torch.arange(MAX_HAND, device=device).unsqueeze(0)
    slot_valid = phase_mask.unsqueeze(1) & (hi_range < hand_sizes.unsqueeze(1)) & (all_card_ids >= 0)

    # Card properties for all hand slots
    card_ids_safe = all_card_ids.clamp(0, num_cards - 1).long()
    card_ids_flat = card_ids_safe.reshape(-1)

    ct_vals = card_table.card_type[card_ids_flat].reshape(N, MAX_HAND)
    costs = card_table.mana_cost[card_ids_flat].reshape(N, MAX_HAND)
    atk_ranges = card_table.attack_range[card_ids_flat].reshape(N, MAX_HAND)

    # Valid playable: not react, enough mana
    playable = slot_valid & (ct_vals != 2) & (player_mana.unsqueeze(1) >= costs)

    # Unique constraint: can't deploy if unique card already on board for this player
    is_unique_card = card_table.is_unique[card_ids_flat].reshape(N, MAX_HAND)
    has_unique_on_board = torch.zeros(N, MAX_HAND, dtype=torch.bool, device=device)
    for s in range(25):  # MAX_MINIONS
        slot_alive = state.minion_alive[:, s]
        slot_owner = state.minion_owner[:, s]
        slot_cid = state.minion_card_id[:, s]
        # For each hand slot, check if board has same card_id owned by active player
        match = slot_alive.unsqueeze(1) & (slot_owner.unsqueeze(1) == ap.unsqueeze(1)) & (slot_cid.unsqueeze(1) == card_ids_safe)
        has_unique_on_board |= match
    unique_blocked = is_unique_card & has_unique_on_board

    # Summon sacrifice tribe: need another card of matching tribe in hand
    sac_tribe = card_table.summon_sacrifice_tribe_id[card_ids_flat].reshape(N, MAX_HAND)
    has_sac_req = sac_tribe > 0  # [N, MAX_HAND]
    if has_sac_req.any():
        hand_tribes = card_table.tribe_id[card_ids_flat].reshape(N, MAX_HAND)
        has_sacrifice = torch.zeros(N, MAX_HAND, dtype=torch.bool, device=device)
        for hi in range(MAX_HAND):
            needs = has_sac_req[:, hi]
            if not needs.any():
                continue
            req = sac_tribe[:, hi]
            for other in range(MAX_HAND):
                if other == hi:
                    continue
                has_sacrifice[:, hi] |= slot_valid[:, other] & (hand_tribes[:, other] == req)
        sac_blocked = has_sac_req & ~has_sacrifice
        playable = playable & ~sac_blocked

    is_minion = playable & (ct_vals == 0) & ~unique_blocked
    is_magic = playable & (ct_vals == 1)

    # Build output mask: [N, MAX_HAND, 25]
    play_out = torch.zeros(N, MAX_HAND, GRID_SIZE, dtype=torch.bool, device=device)

    # MINION deployment: deploy_masks[ap, is_ranged] & board_empty & is_minion
    is_ranged = (atk_ranges > 0).long()
    deploy_rows = deploy_masks[ap.unsqueeze(1).expand_as(is_ranged), is_ranged]
    play_out |= (deploy_rows & board_empty.unsqueeze(1) & is_minion.unsqueeze(2))

    # MAGIC cards: check for SINGLE_TARGET ON_PLAY effects
    eff_triggers = card_table.effect_trigger[card_ids_flat].reshape(N, MAX_HAND, MAX_EFFECTS_PER_CARD)
    eff_targets = card_table.effect_target[card_ids_flat].reshape(N, MAX_HAND, MAX_EFFECTS_PER_CARD)
    n_effects = card_table.num_effects[card_ids_flat].reshape(N, MAX_HAND)

    eff_idx_range = torch.arange(MAX_EFFECTS_PER_CARD, device=device)
    eff_valid = eff_idx_range < n_effects.unsqueeze(2)
    has_single_target = (eff_valid & (eff_triggers == 0) & (eff_targets == 0)).any(dim=2)

    # Targeted magic -> enemy positions
    targeted_magic = is_magic & has_single_target
    play_out |= (targeted_magic.unsqueeze(2) & enemy_pos_mask.unsqueeze(1))

    # Untargeted magic -> cell 0
    untargeted_magic = is_magic & ~has_single_target
    play_out[:, :, 0] |= untargeted_magic

    # Write to mask: [N, 250]
    mask[:, PLAY_CARD_BASE:PLAY_CARD_BASE + MAX_HAND * GRID_SIZE] |= play_out.reshape(N, -1)


def _compute_move_mask(mask, state, phase_mask, friendly_alive, board_flat, card_table=None):
    """Compute MOVE legal actions -- forward only in lane.

    Player 0 moves forward = DOWN (dir 1), Player 1 moves forward = UP (dir 0).
    No lateral movement. Units stay in their column (lane).

    Audit-followup (LEAP parity): minions whose card has `EffectType.LEAP`
    (precomputed in `card_table.leap_amount > 0`) may also use the forward
    direction slot when the immediate forward tile is BLOCKED, provided some
    landing tile within `1 + leap_amount` forward steps is empty. The MOVE
    action slot only carries (source, direction); the actual leap landing
    row is recomputed at apply time. Mirrors the Python `legal_actions` leap
    branch in `_action_phase_actions`.
    """
    N = mask.shape[0]
    device = mask.device

    minion_row = state.minion_row
    minion_col = state.minion_col
    src_flat = minion_row * GRID_COLS + minion_col  # [N, MAX_MINIONS]

    # All 4 directions still computed, but only forward is allowed
    dr = torch.tensor(_DR, device=device)
    dc = torch.tensor(_DC, device=device)
    nr = minion_row.unsqueeze(2) + dr
    nc = minion_col.unsqueeze(2) + dc

    in_bounds = (nr >= 0) & (nr < GRID_ROWS) & (nc >= 0) & (nc < GRID_COLS)
    dest_flat = (nr * GRID_COLS + nc).clamp(0, GRID_SIZE - 1).long()

    # Check board empty at destination
    dest_flat_2d = dest_flat.reshape(N, -1)
    board_at_dest = torch.gather(board_flat, 1, dest_flat_2d).reshape(N, MAX_MINIONS, 4)
    dest_empty = board_at_dest == -1

    # Forward-only: P0 can only use dir 1 (DOWN), P1 can only use dir 0 (UP)
    # Minion owner: state.minion_owner [N, MAX_MINIONS]
    owner = state.minion_owner  # [N, MAX_MINIONS]
    # dir_allowed[N, MAX_MINIONS, 4]: True only for forward direction
    dir_allowed = torch.zeros(N, MAX_MINIONS, 4, dtype=torch.bool, device=device)
    p0_owned = (owner == 0).unsqueeze(2)
    p1_owned = (owner == 1).unsqueeze(2)
    dir_allowed[:, :, 1] |= p0_owned.squeeze(2)  # P0 forward = DOWN (dir 1)
    dir_allowed[:, :, 0] |= p1_owned.squeeze(2)  # P1 forward = UP (dir 0)

    can_move = friendly_alive.unsqueeze(2) & in_bounds & dest_empty & dir_allowed

    # Standard scatter first; LEAP override (below) OR's into the forward slot.
    d_range_pre = torch.arange(4, device=device)
    action_idx_pre = (MOVE_BASE + src_flat.unsqueeze(2) * 4 + d_range_pre).reshape(N, -1).long()
    mask.scatter_(1, action_idx_pre, can_move.reshape(N, -1))

    # Audit-followup: LEAP — when forward (single-step) is blocked, allow the
    # forward direction slot if minion has LEAP and a landing tile exists.
    if card_table is not None:
        cid = state.minion_card_id.clamp(0).long()  # [N, MAX_MINIONS]
        leap_amt = card_table.leap_amount[cid]      # [N, MAX_MINIONS]
        has_leap = leap_amt > 0                     # [N, MAX_MINIONS]

        # Forward direction index per minion: P0=1 (DOWN), P1=0 (UP)
        # delta row per minion: P0=+1, P1=-1
        owner = state.minion_owner  # [N, MAX_MINIONS]
        drow = torch.where(owner == 0, 1, -1).to(torch.int32)  # [N, MAX_MINIONS]
        fwd_dir = torch.where(owner == 0, 1, 0).to(torch.long)  # [N, MAX_MINIONS]

        # Immediate forward row+col
        m_row = state.minion_row
        m_col = state.minion_col
        fwd_row = m_row + drow
        in_b1 = (fwd_row >= 0) & (fwd_row < GRID_ROWS)

        safe_fr = fwd_row.clamp(0, GRID_ROWS - 1)
        fwd_flat = (safe_fr * GRID_COLS + m_col).clamp(0, GRID_SIZE - 1).long()
        fwd_occupied = torch.gather(board_flat, 1, fwd_flat) != -1  # [N, MAX_MINIONS]

        # Walk forward up to (1 + leap_amt) total steps; we already considered
        # step=1 above. Find first empty landing row in steps 2..(1+max_amt).
        max_amt = int(card_table.leap_amount.max().item()) if card_table.leap_amount.numel() > 0 else 0
        leap_lands = torch.zeros_like(friendly_alive)
        if max_amt > 0:
            for extra in range(1, max_amt + 1):
                land_row = m_row + drow * (1 + extra)
                in_b = (land_row >= 0) & (land_row < GRID_ROWS)
                safe_lr = land_row.clamp(0, GRID_ROWS - 1)
                land_flat = (safe_lr * GRID_COLS + m_col).clamp(0, GRID_SIZE - 1).long()
                land_empty = torch.gather(board_flat, 1, land_flat) == -1
                # Only allowed when the leap distance fits this minion
                allowed = extra <= leap_amt
                # Count this landing only if no closer landing already chosen
                first = ~leap_lands & in_b & land_empty & allowed
                leap_lands = leap_lands | first

        leap_can_move = (
            friendly_alive
            & has_leap
            & phase_mask.unsqueeze(1)
            & in_b1
            & fwd_occupied
            & leap_lands
        )
        if leap_can_move.any():
            # Scatter into the forward-direction slot for each (minion) row
            leap_action_idx = (MOVE_BASE + src_flat * 4 + fwd_dir.to(torch.int32)).long()
            # Use scatter with True only where leap_can_move is True
            mask.scatter_(
                1,
                leap_action_idx,
                leap_can_move | torch.gather(mask, 1, leap_action_idx),
            )

    # (standard scatter moved above so LEAP can OR into forward slot)


def _compute_attack_mask(mask, card_table, friendly_alive, enemy_alive,
                          minion_flat, minion_card_id, minion_atk_bonus):
    """Compute ATTACK legal actions -- fully vectorized over all minion pairs.

    A minion with effective attack <= 0 (card_table.attack[cid] +
    minion_atk_bonus) cannot attack -- general rule, also covers Emberplague
    Rat (base atk 0) unless buffed.
    """
    N = mask.shape[0]
    device = mask.device

    # Guard: skip if no friendly or enemy alive (avoids [N, 25, 25] alloc)
    if not friendly_alive.any() or not enemy_alive.any():
        return

    # Attacker ranges: [N, MAX_MINIONS]
    a_cid = minion_card_id.clamp(0).long()
    a_range = card_table.attack_range[a_cid.reshape(-1)].reshape(N, MAX_MINIONS)

    # Effective attack gate: friendly_alive AND (base + bonus) > 0
    a_base_atk = card_table.attack[a_cid.reshape(-1)].reshape(N, MAX_MINIONS)
    a_eff_atk = a_base_atk + minion_atk_bonus
    can_strike = friendly_alive & (a_eff_atk > 0)

    # Pairwise positions: [N, S, T]
    a_flat = minion_flat.unsqueeze(2).expand(N, MAX_MINIONS, MAX_MINIONS)
    d_flat = minion_flat.unsqueeze(1).expand(N, MAX_MINIONS, MAX_MINIONS)

    # Lookup pairwise distances using precomputed tables
    a_2d = a_flat.reshape(-1)
    d_2d = d_flat.reshape(-1)
    manhattan = card_table.distance_manhattan[a_2d, d_2d].reshape(N, MAX_MINIONS, MAX_MINIONS)
    chebyshev = card_table.distance_chebyshev[a_2d, d_2d].reshape(N, MAX_MINIONS, MAX_MINIONS)
    ortho = card_table.is_orthogonal[a_2d, d_2d].reshape(N, MAX_MINIONS, MAX_MINIONS)

    a_range_exp = a_range.unsqueeze(2)

    # Melee: range==0, manhattan==1, orthogonal
    is_melee = a_range_exp == 0
    melee_ok = is_melee & (manhattan == 1) & ortho

    # Ranged: (ortho & manhattan <= range + 1) | (chebyshev==1 & !ortho)
    # The +1 matches Python _can_attack: range 1 means 2 ortho + 1 diag.
    ranged_ok = ~is_melee & ((ortho & (manhattan <= a_range_exp + 1)) | ((chebyshev == 1) & ~ortho))

    # Pair validity and final mask
    pair_valid = can_strike.unsqueeze(2) & enemy_alive.unsqueeze(1)
    can_attack = pair_valid & (melee_ok | ranged_ok)

    # Scatter to mask
    action_idx = (ATTACK_BASE + a_flat * GRID_SIZE + d_flat).long().reshape(N, -1)
    mask.scatter_(1, action_idx, can_attack.reshape(N, -1))


def _compute_sacrifice_mask(mask, state, ap, friendly_alive):
    """Compute SACRIFICE legal actions -- fully vectorized."""
    N = mask.shape[0]
    minion_row = state.minion_row
    minion_flat = (minion_row * GRID_COLS + state.minion_col).long()

    is_p0 = (ap == 0).unsqueeze(1)
    on_enemy_back_row = torch.where(
        is_p0, minion_row == BACK_ROW_P2, minion_row == BACK_ROW_P1
    )

    can_sacrifice = friendly_alive & on_enemy_back_row
    action_idx = (SACRIFICE_BASE + minion_flat).long()
    mask.scatter_(1, action_idx, can_sacrifice)


def _compute_react_phase_mask(mask, state, card_table, phase_mask):
    """Compute REACT phase legal actions -- fully vectorized.

    Builds [N, MAX_HAND, 26] react mask and writes via flat OR.
    """
    N = mask.shape[0]
    device = mask.device
    arange_n = torch.arange(N, device=device)

    mask[phase_mask, PASS_IDX] = True

    rp = state.react_player
    stack_depth = state.react_stack_depth
    can_react = phase_mask & (stack_depth < MAX_REACT_DEPTH)
    if not can_react.any():
        return

    player_mana = state.player_mana[arange_n, rp]
    hand_sizes = state.hand_sizes[arange_n, rp]
    num_cards = card_table.num_cards

    # React condition check
    react_cond_results = _batch_check_react_condition(state, card_table, can_react)

    # All-minion position mask: [N, 25]
    minion_flat = (state.minion_row * GRID_COLS + state.minion_col).clamp(0, GRID_SIZE - 1).long()
    all_minion_mask = torch.zeros(N, GRID_SIZE, dtype=torch.bool, device=device)
    all_minion_mask.scatter_(1, minion_flat, state.minion_alive)
    has_any_minion = state.minion_alive.any(dim=1)

    # Deploy row masks
    cell_rows = torch.arange(GRID_SIZE, device=device) // GRID_COLS
    board_flat = state.board.reshape(N, GRID_SIZE)
    board_empty = board_flat == -1

    p0_melee = (cell_rows == 0) | (cell_rows == 1)
    p0_ranged = cell_rows == 0
    p1_melee = (cell_rows == 3) | (cell_rows == 4)
    p1_ranged = cell_rows == 4
    deploy_masks = torch.stack([
        torch.stack([p0_melee, p0_ranged]),
        torch.stack([p1_melee, p1_ranged]),
    ])

    # All hand cards: [N, MAX_HAND]
    all_card_ids = state.hands[arange_n, rp]
    hi_range = torch.arange(MAX_HAND, device=device).unsqueeze(0)
    slot_valid = can_react.unsqueeze(1) & (hi_range < hand_sizes.unsqueeze(1)) & (all_card_ids >= 0)

    card_ids_safe = all_card_ids.clamp(0, num_cards - 1).long()
    card_ids_flat = card_ids_safe.reshape(-1)

    # Card properties: [N, MAX_HAND]
    ct_vals = card_table.card_type[card_ids_flat].reshape(N, MAX_HAND)
    is_react_elig = card_table.is_react_eligible[card_ids_flat].reshape(N, MAX_HAND)
    is_multi = card_table.is_multi_purpose[card_ids_flat].reshape(N, MAX_HAND)

    react_mc = card_table.react_mana_cost[card_ids_flat].reshape(N, MAX_HAND)
    normal_mc = card_table.mana_cost[card_ids_flat].reshape(N, MAX_HAND)
    cost = torch.where(is_multi, react_mc, normal_mc)

    valid = slot_valid & is_react_elig & (player_mana.unsqueeze(1) >= cost)

    if not valid.any():
        return

    # React condition per card
    rc = card_table.react_condition[card_ids_flat].reshape(N, MAX_HAND)
    cond_met = rc < 0
    for cond_val, cond_mask in react_cond_results.items():
        cond_met = cond_met | ((rc == cond_val) & cond_mask.unsqueeze(1))
    valid = valid & cond_met

    # Build react output: [N, MAX_HAND, 26]
    react_out = torch.zeros(N, MAX_HAND, 26, dtype=torch.bool, device=device)

    is_pure_react = valid & (ct_vals == 2)
    is_multi_react = valid & is_multi

    # Effect properties
    eff_types = card_table.effect_type[card_ids_flat].reshape(N, MAX_HAND, MAX_EFFECTS_PER_CARD)
    eff_targets = card_table.effect_target[card_ids_flat].reshape(N, MAX_HAND, MAX_EFFECTS_PER_CARD)
    n_effects = card_table.num_effects[card_ids_flat].reshape(N, MAX_HAND)
    eff_idx_range = torch.arange(MAX_EFFECTS_PER_CARD, device=device)
    eff_valid = eff_idx_range < n_effects.unsqueeze(2)

    has_negate = (eff_valid & (eff_types == 4)).any(dim=2)
    has_single_target = (eff_valid & (eff_targets == 0)).any(dim=2)

    # Multi-purpose effect properties
    re_type = card_table.react_effect_type[card_ids_flat].reshape(N, MAX_HAND)
    re_target = card_table.react_effect_target[card_ids_flat].reshape(N, MAX_HAND)

    # Sentinel categories
    cat_negate = is_pure_react & has_negate
    cat_pr_targeted_no = is_pure_react & ~has_negate & has_single_target & ~has_any_minion.unsqueeze(1)
    cat_pr_untargeted = is_pure_react & ~has_negate & ~has_single_target
    cat_multi_st_no = is_multi_react & (re_target == 0) & (re_type != 5) & ~has_any_minion.unsqueeze(1)
    cat_multi_other = is_multi_react & (re_type != 5) & (re_target != 0)

    react_out[:, :, 25] = (
        cat_negate | cat_pr_targeted_no | cat_pr_untargeted | cat_multi_st_no | cat_multi_other
    )

    # Targeted categories: minion positions
    cat_pr_targeted_has = is_pure_react & ~has_negate & has_single_target & has_any_minion.unsqueeze(1)
    cat_multi_st_has = is_multi_react & (re_target == 0) & (re_type != 5) & has_any_minion.unsqueeze(1)
    use_minion_targets = cat_pr_targeted_has | cat_multi_st_has
    react_out[:, :, :25] |= use_minion_targets.unsqueeze(2) & all_minion_mask.unsqueeze(1)

    # Deploy categories
    cat_deploy = is_multi_react & (re_type == 5)
    atk_ranges = card_table.attack_range[card_ids_flat].reshape(N, MAX_HAND)
    is_ranged = (atk_ranges > 0).long()
    deploy_rows = deploy_masks[rp.unsqueeze(1).expand_as(is_ranged), is_ranged]
    react_out[:, :, :25] |= cat_deploy.unsqueeze(2) & deploy_rows & board_empty.unsqueeze(1)

    # Write to mask
    mask[:, REACT_BASE:REACT_BASE + MAX_HAND * 26] |= react_out.reshape(N, -1)


def _batch_check_react_condition(state, card_table, can_react):
    """Batch-check react conditions for all games.

    Returns dict mapping condition_value -> [N] bool mask.
    """
    N = state.board.shape[0]
    device = state.board.device
    arange_n = torch.arange(N, device=device)

    stack_depth = state.react_stack_depth
    has_stack = stack_depth > 0

    last_stack_idx = (stack_depth - 1).clamp(0).long()
    last_cid = state.react_stack[arange_n, last_stack_idx, 1]
    last_cid_safe = last_cid.clamp(0).long()
    last_ct = card_table.card_type[last_cid_safe]

    pending_type = state.pending_action_type
    pending_cid = state.pending_action_card_id
    pending_cid_safe = pending_cid.clamp(0).long()
    pending_ct = card_table.card_type[pending_cid_safe]
    pending_elem = card_table.element[pending_cid_safe]
    pending_had_pos = state.pending_action_had_position

    results = {}

    # 0: OPPONENT_PLAYS_MAGIC
    stack_c0 = has_stack & ((last_ct == 1) | (last_ct == 2))
    no_stack_c0 = ~has_stack & (pending_type == 0) & (pending_cid >= 0) & (pending_ct == 1)
    results[0] = can_react & (stack_c0 | no_stack_c0)

    # 1: OPPONENT_PLAYS_MINION
    results[1] = can_react & ~has_stack & (pending_type == 0) & pending_had_pos

    # 2: OPPONENT_ATTACKS
    results[2] = can_react & ~has_stack & (pending_type == 2)

    # 3: OPPONENT_PLAYS_REACT
    results[3] = can_react & has_stack

    # 4: ANY_ACTION
    results[4] = can_react

    # 5-11: element conditions (ReactCondition value maps to Element value = rc_val - 5)
    for rc_val in range(5, 12):
        required_elem = rc_val - 5
        results[rc_val] = (
            can_react & ~has_stack & (pending_type == 0) &
            (pending_cid >= 0) & (pending_elem == required_elem)
        )

    return results
