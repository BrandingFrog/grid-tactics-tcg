"""Batched legal action mask computation.

Produces [N, 1262] bool mask matching the Python engine's legal_actions().
All computation as tensor operations over the batch dimension.
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
    MAX_HAND,
    MAX_MINIONS,
    MAX_REACT_DEPTH,
    MOVE_BASE,
    PASS_IDX,
    PLAY_CARD_BASE,
    REACT_BASE,
    SACRIFICE_BASE,
)


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

    return mask


def _compute_action_phase_mask(mask, state, card_table, phase_mask):
    """Compute legal actions for ACTION phase games."""
    N = mask.shape[0]
    device = mask.device
    arange_n = torch.arange(N, device=device)
    ap = state.active_player  # [N]

    # --- PLAY_CARD [0:250] ---
    _compute_play_card_mask(mask, state, card_table, phase_mask, ap)

    # --- MOVE [250:350] ---
    _compute_move_mask(mask, state, card_table, phase_mask, ap)

    # --- ATTACK [350:975] ---
    _compute_attack_mask(mask, state, card_table, phase_mask, ap)

    # --- SACRIFICE [975:1000] ---
    _compute_sacrifice_mask(mask, state, card_table, phase_mask, ap)

    # --- DRAW [1000] ---
    for i in range(N):
        if not phase_mask[i]:
            continue
        p = ap[i].item()
        if state.deck_tops[i, p].item() < state.deck_sizes[i, p].item():
            mask[i, DRAW_IDX] = True

    # --- PASS [1001]: NOT legal in ACTION phase per Python engine ---
    # (no PASS in action phase -- if no actions, empty = auto-lose handled by safety fallback)


def _compute_play_card_mask(mask, state, card_table, phase_mask, ap):
    """Compute PLAY_CARD legal actions."""
    N = mask.shape[0]
    device = mask.device

    for i in range(N):
        if not phase_mask[i]:
            continue
        p = ap[i].item()
        player_mana = state.player_mana[i, p].item()
        hs = state.hand_sizes[i, p].item()

        for hi in range(min(hs, MAX_HAND)):
            cid = state.hands[i, p, hi].item()
            if cid < 0:
                continue

            ct = card_table.card_type[cid].item()
            cost = card_table.mana_cost[cid].item()

            # Skip react cards in ACTION phase
            if ct == 2:  # REACT
                continue
            if player_mana < cost:
                continue

            if ct == 0:  # MINION
                # Compute valid deploy positions
                atk_range = card_table.attack_range[cid].item()
                deploy_cells = _get_deploy_cells(state, i, p, atk_range)

                # Check for ON_PLAY SINGLE_TARGET effects
                has_single_target_on_play = False
                for eff_idx in range(card_table.num_effects[cid].item()):
                    if (card_table.effect_trigger[cid, eff_idx].item() == 0 and  # ON_PLAY
                            card_table.effect_target[cid, eff_idx].item() == 0):  # SINGLE_TARGET
                        has_single_target_on_play = True
                        break

                if has_single_target_on_play:
                    # Enumerate enemy minion positions as targets
                    enemy_positions = _get_enemy_minion_positions(state, i, p)
                    if enemy_positions:
                        # For targeted minion deploy, the encoding uses cell = deploy position
                        # The target_pos is encoded separately (Python engine uses position + target_pos)
                        # But in the action space, PLAY_CARD_BASE + hand_idx * 25 + cell
                        # where cell = deploy position. The target is implicit.
                        # Actually, per the action_space.py: for minion deploy, cell = deploy position
                        # For targeted minions, the Python engine creates one action per deploy_pos x target
                        # but the integer encoding only captures deploy pos (cell).
                        # So we enumerate deploy positions as normal.
                        for cell in deploy_cells:
                            mask[i, PLAY_CARD_BASE + hi * GRID_SIZE + cell] = True
                    else:
                        # Deploy without target (no enemies)
                        for cell in deploy_cells:
                            mask[i, PLAY_CARD_BASE + hi * GRID_SIZE + cell] = True
                else:
                    for cell in deploy_cells:
                        mask[i, PLAY_CARD_BASE + hi * GRID_SIZE + cell] = True

            elif ct == 1:  # MAGIC
                # Check for SINGLE_TARGET ON_PLAY effects
                has_single_target = False
                for eff_idx in range(card_table.num_effects[cid].item()):
                    if (card_table.effect_trigger[cid, eff_idx].item() == 0 and  # ON_PLAY
                            card_table.effect_target[cid, eff_idx].item() == 0):  # SINGLE_TARGET
                        has_single_target = True
                        break

                if has_single_target:
                    # Target cells = enemy minion positions
                    enemy_positions = _get_enemy_minion_positions(state, i, p)
                    for pos in enemy_positions:
                        mask[i, PLAY_CARD_BASE + hi * GRID_SIZE + pos] = True
                else:
                    # Untargeted magic: cell 0 is the encoding
                    mask[i, PLAY_CARD_BASE + hi * GRID_SIZE + 0] = True


def _get_deploy_cells(state, game_idx, player_idx, atk_range):
    """Return list of valid flat cell indices for deploying a minion."""
    cells = []
    if player_idx == 0:
        if atk_range == 0:  # melee: rows 0,1
            rows = [0, 1]
        else:  # ranged: row 0 only
            rows = [0]
    else:
        if atk_range == 0:  # melee: rows 3,4
            rows = [3, 4]
        else:  # ranged: row 4 only
            rows = [4]

    for row in rows:
        for col in range(GRID_COLS):
            if state.board[game_idx, row, col].item() == -1:
                cells.append(row * GRID_COLS + col)
    return cells


def _get_enemy_minion_positions(state, game_idx, player_idx):
    """Return list of flat positions with enemy minions."""
    positions = []
    for s in range(MAX_MINIONS):
        if state.minion_alive[game_idx, s] and state.minion_owner[game_idx, s].item() != player_idx:
            row = state.minion_row[game_idx, s].item()
            col = state.minion_col[game_idx, s].item()
            positions.append(row * GRID_COLS + col)
    return positions


def _get_friendly_minion_positions(state, game_idx, player_idx):
    """Return list of flat positions with friendly minions."""
    positions = []
    for s in range(MAX_MINIONS):
        if state.minion_alive[game_idx, s] and state.minion_owner[game_idx, s].item() == player_idx:
            row = state.minion_row[game_idx, s].item()
            col = state.minion_col[game_idx, s].item()
            positions.append(row * GRID_COLS + col)
    return positions


def _compute_move_mask(mask, state, card_table, phase_mask, ap):
    """Compute MOVE legal actions."""
    N = mask.shape[0]
    device = mask.device

    # Direction deltas: 0=up, 1=down, 2=left, 3=right
    deltas = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    for i in range(N):
        if not phase_mask[i]:
            continue
        p = ap[i].item()

        for s in range(MAX_MINIONS):
            if not state.minion_alive[i, s]:
                continue
            if state.minion_owner[i, s].item() != p:
                continue

            row = state.minion_row[i, s].item()
            col = state.minion_col[i, s].item()
            src_flat = row * GRID_COLS + col

            for d, (dr, dc) in enumerate(deltas):
                nr, nc = row + dr, col + dc
                if 0 <= nr < GRID_ROWS and 0 <= nc < GRID_COLS:
                    if state.board[i, nr, nc].item() == -1:
                        mask[i, MOVE_BASE + src_flat * 4 + d] = True


def _compute_attack_mask(mask, state, card_table, phase_mask, ap):
    """Compute ATTACK legal actions."""
    N = mask.shape[0]
    device = mask.device

    for i in range(N):
        if not phase_mask[i]:
            continue
        p = ap[i].item()

        # Collect owned minions
        for s in range(MAX_MINIONS):
            if not state.minion_alive[i, s]:
                continue
            if state.minion_owner[i, s].item() != p:
                continue

            a_row = state.minion_row[i, s].item()
            a_col = state.minion_col[i, s].item()
            a_flat = a_row * GRID_COLS + a_col
            a_cid = state.minion_card_id[i, s].item()
            a_range = card_table.attack_range[a_cid].item()

            # Check all enemy minions
            for t in range(MAX_MINIONS):
                if not state.minion_alive[i, t]:
                    continue
                if state.minion_owner[i, t].item() == p:
                    continue

                d_row = state.minion_row[i, t].item()
                d_col = state.minion_col[i, t].item()
                d_flat = d_row * GRID_COLS + d_col

                if _can_attack_check(a_row, a_col, d_row, d_col, a_range):
                    mask[i, ATTACK_BASE + a_flat * GRID_SIZE + d_flat] = True


def _can_attack_check(a_row, a_col, d_row, d_col, atk_range):
    """Check if attacker can reach defender per game rules."""
    manhattan = abs(a_row - d_row) + abs(a_col - d_col)
    chebyshev = max(abs(a_row - d_row), abs(a_col - d_col))
    is_ortho = (a_row == d_row) or (a_col == d_col)

    if atk_range == 0:
        # Melee: orthogonal adjacent only
        return manhattan == 1 and is_ortho
    else:
        # Ranged: (orthogonal AND manhattan <= range) OR (diagonal adjacent)
        ortho_in_range = is_ortho and manhattan <= atk_range
        diag_adjacent = chebyshev == 1 and not is_ortho
        return ortho_in_range or diag_adjacent


def _compute_sacrifice_mask(mask, state, card_table, phase_mask, ap):
    """Compute SACRIFICE legal actions."""
    N = mask.shape[0]

    for i in range(N):
        if not phase_mask[i]:
            continue
        p = ap[i].item()

        for s in range(MAX_MINIONS):
            if not state.minion_alive[i, s]:
                continue
            if state.minion_owner[i, s].item() != p:
                continue

            row = state.minion_row[i, s].item()
            col = state.minion_col[i, s].item()
            src_flat = row * GRID_COLS + col

            # P1 minions on row 4 (P2 back row), P2 minions on row 0 (P1 back row)
            if p == 0 and row == BACK_ROW_P2:
                mask[i, SACRIFICE_BASE + src_flat] = True
            elif p == 1 and row == BACK_ROW_P1:
                mask[i, SACRIFICE_BASE + src_flat] = True


def _compute_react_phase_mask(mask, state, card_table, phase_mask):
    """Compute legal actions for REACT phase games."""
    N = mask.shape[0]
    device = mask.device

    for i in range(N):
        if not phase_mask[i]:
            continue

        rp = state.react_player[i].item()
        player_mana = state.player_mana[i, rp].item()
        hs = state.hand_sizes[i, rp].item()
        stack_depth = state.react_stack_depth[i].item()

        # PASS always legal in react
        mask[i, PASS_IDX] = True

        # If stack at max depth, only PASS
        if stack_depth >= MAX_REACT_DEPTH:
            continue

        for hi in range(min(hs, MAX_HAND)):
            cid = state.hands[i, rp, hi].item()
            if cid < 0:
                continue

            ct = card_table.card_type[cid].item()
            is_react_eligible = card_table.is_react_eligible[cid].item()
            if not is_react_eligible:
                continue

            # Determine cost
            is_multi = card_table.is_multi_purpose[cid].item()
            if is_multi:
                cost = card_table.react_mana_cost[cid].item()
            else:
                cost = card_table.mana_cost[cid].item()

            if player_mana < cost:
                continue

            # Check react condition
            if not _check_react_condition(state, i, cid, card_table):
                continue

            if ct == 2:  # REACT card
                # Check for NEGATE
                has_negate = False
                for eff_idx in range(card_table.num_effects[cid].item()):
                    if card_table.effect_type[cid, eff_idx].item() == 4:  # NEGATE
                        has_negate = True
                        break

                if has_negate:
                    # NEGATE: no target needed, sentinel = 25
                    mask[i, REACT_BASE + hi * 26 + 25] = True
                    continue

                # Check for SINGLE_TARGET effects
                has_single_target = False
                for eff_idx in range(card_table.num_effects[cid].item()):
                    if card_table.effect_target[cid, eff_idx].item() == 0:  # SINGLE_TARGET
                        has_single_target = True
                        break

                if has_single_target:
                    # All minion positions (friendly + enemy)
                    all_positions = (
                        _get_enemy_minion_positions(state, i, rp)
                        + _get_friendly_minion_positions(state, i, rp)
                    )
                    if all_positions:
                        for pos in set(all_positions):
                            mask[i, REACT_BASE + hi * 26 + pos] = True
                    else:
                        # No targets available, still playable (untargeted)
                        mask[i, REACT_BASE + hi * 26 + 25] = True
                else:
                    # Untargeted react
                    mask[i, REACT_BASE + hi * 26 + 25] = True

            elif is_multi:
                # Multi-purpose card used as react
                re_type = card_table.react_effect_type[cid].item()
                re_target = card_table.react_effect_target[cid].item()

                if re_type == 5:  # DEPLOY_SELF
                    # Valid deploy positions
                    atk_range = card_table.attack_range[cid].item()
                    deploy_cells = _get_deploy_cells(state, i, rp, atk_range)
                    for cell in deploy_cells:
                        mask[i, REACT_BASE + hi * 26 + cell] = True
                elif re_target == 0:  # SINGLE_TARGET
                    all_positions = (
                        _get_enemy_minion_positions(state, i, rp)
                        + _get_friendly_minion_positions(state, i, rp)
                    )
                    if all_positions:
                        for pos in set(all_positions):
                            mask[i, REACT_BASE + hi * 26 + pos] = True
                    else:
                        mask[i, REACT_BASE + hi * 26 + 25] = True
                else:
                    mask[i, REACT_BASE + hi * 26 + 25] = True


def _check_react_condition(state, game_idx, card_id, card_table):
    """Check if a react card's condition is met for a specific game."""
    rc = card_table.react_condition[card_id].item()
    if rc < 0:
        # No condition (multi-purpose without explicit condition)
        return True

    # ReactCondition enum values
    # 0=OPPONENT_PLAYS_MAGIC, 1=OPPONENT_PLAYS_MINION, 2=OPPONENT_ATTACKS
    # 3=OPPONENT_PLAYS_REACT, 4=ANY_ACTION, 5-8=attribute conditions

    stack_depth = state.react_stack_depth[game_idx].item()

    if stack_depth > 0:
        # Reacting to last stack entry
        last_cid = state.react_stack[game_idx, stack_depth - 1, 1].item()
        if rc == 3:  # OPPONENT_PLAYS_REACT
            return True
        if rc == 0:  # OPPONENT_PLAYS_MAGIC
            last_ct = card_table.card_type[last_cid].item() if last_cid >= 0 else -1
            return last_ct == 1 or last_ct == 2  # MAGIC or REACT
        if rc == 4:  # ANY_ACTION
            return True
        return False

    # Check pending action
    pending_type = state.pending_action_type[game_idx].item()
    pending_cid = state.pending_action_card_id[game_idx].item()
    pending_had_pos = state.pending_action_had_position[game_idx].item()

    if rc == 4:  # ANY_ACTION
        return True

    if rc == 0:  # OPPONENT_PLAYS_MAGIC
        if pending_type == 0 and pending_cid >= 0:  # PLAY_CARD
            return card_table.card_type[pending_cid].item() == 1  # MAGIC
        return False

    if rc == 1:  # OPPONENT_PLAYS_MINION
        if pending_type == 0:  # PLAY_CARD
            return bool(pending_had_pos)
        return False

    if rc == 2:  # OPPONENT_ATTACKS
        return pending_type == 2  # ATTACK

    if rc == 3:  # OPPONENT_PLAYS_REACT
        return False  # No stack entry means nothing to counter

    # Attribute conditions (5-8)
    if 5 <= rc <= 8:
        required_attr = rc - 5 + 1  # FIRE=1, DARK=2, LIGHT=3, NEUTRAL=0
        # Map: rc=5->FIRE(1), rc=6->DARK(2), rc=7->LIGHT(3), rc=8->NEUTRAL(0)
        attr_map = {5: 1, 6: 2, 7: 3, 8: 0}
        required_attr = attr_map.get(rc, -1)
        if pending_type == 0 and pending_cid >= 0:
            return card_table.attribute[pending_cid].item() == required_attr
        return False

    return False
