"""Batched observation encoding -- converts TensorGameState to [N, 292] float32.

Ports the Python encode_observation() as batch tensor operations.
All values normalized to [-1.0, 1.0] matching the Python encoder.
"""

from __future__ import annotations

import torch

from grid_tactics.tensor_engine.constants import (
    DEFAULT_TURN_LIMIT,
    GRID_COLS,
    GRID_ROWS,
    GRID_SIZE,
    MAX_HAND,
    MAX_MANA_CAP,
    MAX_REACT_DEPTH,
    MAX_STAT,
    MIN_DECK_SIZE,
    STARTING_HP,
    MAX_MINIONS,
)

OBSERVATION_SIZE: int = 292
FEATURES_PER_CELL: int = 10
HAND_FEATURES: int = 2

# Dynamic normalization constants -- computed once from card_table at first call
_norm_cache = {}

def _get_norms(card_table, device):
    """Compute normalization constants from card_table. Cached per device."""
    key = id(card_table)
    if key not in _norm_cache:
        max_atk = max(card_table.attack.max().item(), 1)
        max_hp = max(card_table.health.max().item(), 1)
        max_cost = max(card_table.mana_cost.max().item(), 1)
        max_range = max(card_table.attack_range.max().item(), 1)
        num_elems = max(card_table.element.max().item(), 1)
        _norm_cache[key] = {
            'atk': float(max_atk),
            'hp': float(max_hp),
            'cost': float(max_cost),
            'range': float(max_range),
            'elem': float(num_elems),
        }
    return _norm_cache[key]


def encode_observations_batch(
    state,
    card_table,
    observer_idx: torch.Tensor,  # [N] int32
) -> torch.Tensor:
    """Encode game state into [N, 292] float32 observation tensor.

    Perspective-relative: observer's own resources in MY_RESOURCES,
    opponent's in OPPONENT_VISIBLE. Board minion ownership is +1/-1
    relative to observer.

    Normalization is dynamic -- derived from card_table, not hardcoded.
    Scales to any number of cards or stat ranges.
    """
    N = state.board.shape[0]
    device = state.board.device
    obs = torch.zeros(N, OBSERVATION_SIZE, dtype=torch.float32, device=device)
    arange_n = torch.arange(N, device=device)
    norms = _get_norms(card_table, device)

    # --- Board encoding: 25 cells x 10 features [0:250] ---
    for row in range(GRID_ROWS):
        for col in range(GRID_COLS):
            cell_flat = row * GRID_COLS + col
            base = cell_flat * FEATURES_PER_CELL

            slot = state.board[:, row, col]  # [N]
            occupied = slot >= 0  # [N]

            if not occupied.any():
                continue

            safe_slot = slot.clamp(min=0)

            # Get minion properties
            m_cid = state.minion_card_id[arange_n, safe_slot]  # [N]
            m_owner = state.minion_owner[arange_n, safe_slot]  # [N]
            m_health = state.minion_health[arange_n, safe_slot]  # [N]
            m_atk_bonus = state.minion_atk_bonus[arange_n, safe_slot]  # [N]
            safe_cid = m_cid.clamp(min=0)

            # Card properties
            c_attack = card_table.attack[safe_cid].float()
            c_range = card_table.attack_range[safe_cid].float()
            c_elem = card_table.element[safe_cid].float()

            # Owner encoding: +1 if mine, -1 if opponent
            is_mine = (m_owner == observer_idx).float()
            owner_val = torch.where(is_mine.bool(), torch.tensor(1.0, device=device), torch.tensor(-1.0, device=device))

            # has_on_death, has_on_damaged
            has_on_death = torch.zeros(N, dtype=torch.float32, device=device)
            has_on_damaged = torch.zeros(N, dtype=torch.float32, device=device)
            for eff_idx in range(3):
                valid_eff = eff_idx < card_table.num_effects[safe_cid]
                trigger = card_table.effect_trigger[safe_cid, eff_idx]
                has_on_death = torch.where(
                    occupied & valid_eff & (trigger == 1),
                    torch.tensor(1.0, device=device),
                    has_on_death,
                )
                has_on_damaged = torch.where(
                    occupied & valid_eff & (trigger == 3),
                    torch.tensor(1.0, device=device),
                    has_on_damaged,
                )

            occ_f = occupied.float()
            obs[:, base + 0] = occ_f                                        # is_occupied
            obs[:, base + 1] = torch.where(occupied, owner_val, torch.tensor(0.0, device=device))
            obs[:, base + 2] = torch.where(occupied, c_attack / norms['atk'], torch.tensor(0.0, device=device))
            obs[:, base + 3] = torch.where(occupied, m_health.float() / norms['hp'], torch.tensor(0.0, device=device))
            obs[:, base + 4] = torch.where(occupied, c_range / max(norms['range'], 1), torch.tensor(0.0, device=device))
            obs[:, base + 5] = torch.where(occupied, m_atk_bonus.float() / norms['atk'], torch.tensor(0.0, device=device))
            obs[:, base + 6] = 0.0  # card_type (reserved)
            obs[:, base + 7] = torch.where(occupied, c_elem / max(norms['elem'], 1), torch.tensor(0.0, device=device))
            obs[:, base + 8] = torch.where(occupied, has_on_death, torch.tensor(0.0, device=device))
            obs[:, base + 9] = torch.where(occupied, has_on_damaged, torch.tensor(0.0, device=device))

    # --- My hand [250:270]: 10 slots x 2 features ---
    hand_offset = 250
    for hi in range(MAX_HAND):
        slot_base = hand_offset + hi * HAND_FEATURES
        card_id = state.hands[arange_n, observer_idx.long(), hi]  # [N]
        has_card = card_id >= 0
        safe_cid = card_id.clamp(min=0)
        obs[:, slot_base + 0] = has_card.float()
        obs[:, slot_base + 1] = torch.where(
            has_card,
            card_table.mana_cost[safe_cid].float() / norms['cost'],
            torch.tensor(0.0, device=device),
        )

    # --- My resources [270:275] ---
    res_offset = 270
    my_mana = state.player_mana[arange_n, observer_idx.long()]
    my_max_mana = state.player_max_mana[arange_n, observer_idx.long()]
    my_hp = state.player_hp[arange_n, observer_idx.long()]
    my_deck_remaining = state.deck_sizes[arange_n, observer_idx.long()] - state.deck_tops[arange_n, observer_idx.long()]
    my_graveyard_size = state.graveyard_sizes[arange_n, observer_idx.long()]

    obs[:, res_offset + 0] = my_mana.float() / MAX_MANA_CAP
    obs[:, res_offset + 1] = my_max_mana.float() / MAX_MANA_CAP
    obs[:, res_offset + 2] = my_hp.float() / max(STARTING_HP, 1)
    obs[:, res_offset + 3] = my_deck_remaining.float() / max(MIN_DECK_SIZE, 1)
    obs[:, res_offset + 4] = my_graveyard_size.float() / max(MIN_DECK_SIZE, 1)

    # --- Opponent visible [275:279] ---
    opp_offset = 275
    opp_idx = (1 - observer_idx).long()
    opp_hp = state.player_hp[arange_n, opp_idx]
    opp_mana = state.player_mana[arange_n, opp_idx]
    opp_hand_size = state.hand_sizes[arange_n, opp_idx]
    opp_deck_remaining = state.deck_sizes[arange_n, opp_idx] - state.deck_tops[arange_n, opp_idx]

    obs[:, opp_offset + 0] = opp_hp.float() / max(STARTING_HP, 1)
    obs[:, opp_offset + 1] = opp_mana.float() / MAX_MANA_CAP
    obs[:, opp_offset + 2] = opp_hand_size.float() / MAX_HAND
    obs[:, opp_offset + 3] = opp_deck_remaining.float() / max(MIN_DECK_SIZE, 1)

    # --- Game context [279:282] ---
    gc_offset = 279
    obs[:, gc_offset + 0] = state.turn_number.float() / DEFAULT_TURN_LIMIT
    obs[:, gc_offset + 1] = (state.phase == 0).float()

    # am_i_active
    is_action_phase = state.phase == 0
    is_react_phase = state.phase == 1
    am_active_action = is_action_phase & (state.active_player == observer_idx)
    am_active_react = is_react_phase & (state.react_player == observer_idx)
    obs[:, gc_offset + 2] = (am_active_action | am_active_react).float()

    # --- React context [282:292] ---
    rc_offset = 282
    obs[:, rc_offset + 0] = (state.phase == 1).float()
    obs[:, rc_offset + 1] = state.react_stack_depth.float() / MAX_REACT_DEPTH
    # 282+2 through 282+9 remain 0.0 (reserved)

    return obs
