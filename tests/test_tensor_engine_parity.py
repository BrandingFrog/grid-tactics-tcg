"""Phase 14.1 Wave 2 — tensor engine parity tests for pending post-move attack.

These tests verify that the tensor engine matches the Python engine semantics
(Wave 1) for the new move+attack/decline mechanic. They place minions directly
into the tensor state via slot writes (mirroring how test_tensor_engine.py
exercises mid-game scenarios), then drive single-game batches through
step_batch and check the observable invariants:

  1. Melee MOVE adjacent to an enemy -> pending set, react deferred.
  2. Ranged MOVE -> pending stays -1, react phase entered.
  3. ATTACK from pending -> pending cleared, react entered, hp deltas correct.
  4. PASS-as-DECLINE from pending -> pending cleared, react entered, no fatigue.
  5. Melee MOVE into open space -> pending stays -1, react entered immediately.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import torch

from grid_tactics.card_library import CardLibrary
from grid_tactics.tensor_engine import CardTable, TensorGameEngine
from grid_tactics.tensor_engine.constants import ATTACK_BASE, MOVE_BASE, PASS_IDX, GRID_COLS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def setup():
    lib = CardLibrary.from_directory(Path("data/cards"))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ct = CardTable.from_library(lib, device)
    deck = torch.tensor([(list(range(18)) * 3)[:40]], device=device)
    return lib, ct, deck, device


def _melee_card_id(lib: CardLibrary) -> int:
    for cid in range(18):
        c = lib.get_by_id(cid)
        if getattr(c, "card_type").value == 0 and c.attack_range == 0:
            return cid
    raise RuntimeError("no melee minion in library")


def _ranged_card_id(lib: CardLibrary) -> int:
    for cid in range(18):
        c = lib.get_by_id(cid)
        if getattr(c, "card_type").value == 0 and c.attack_range >= 1:
            return cid
    raise RuntimeError("no ranged minion in library")


def _place_minion(state, n_idx: int, slot: int, card_id: int, owner: int, row: int, col: int, hp: int = 100):
    """Directly write a minion into a tensor state slot for one game."""
    state.minion_card_id[n_idx, slot] = card_id
    state.minion_owner[n_idx, slot] = owner
    state.minion_row[n_idx, slot] = row
    state.minion_col[n_idx, slot] = col
    state.minion_health[n_idx, slot] = hp
    state.minion_atk_bonus[n_idx, slot] = 0
    state.minion_alive[n_idx, slot] = True
    state.board[n_idx, row, col] = slot
    if state.next_minion_slot[n_idx].item() <= slot:
        state.next_minion_slot[n_idx] = slot + 1


def _move_action(slot: int, direction: int) -> int:
    # MOVE encoding: MOVE_BASE + slot*4 + direction; "slot" here is flat board index.
    return MOVE_BASE + slot * 4 + direction


def _attack_action(src_flat: int, tgt_flat: int) -> int:
    return ATTACK_BASE + src_flat * 25 + tgt_flat


def _flat(row: int, col: int) -> int:
    return row * GRID_COLS + col


def _make_engine(setup, n: int = 1):
    _, ct, deck, device = setup
    engine = TensorGameEngine(n, ct, deck.expand(n, -1), deck.expand(n, -1), device)
    engine.reset_batch()
    # Clear board / minions: tests place minions explicitly.
    engine.state.board[:] = -1
    engine.state.minion_alive[:] = False
    engine.state.next_minion_slot[:] = 0
    return engine, device


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPendingPostMoveAttack:
    def test_parity_melee_move_pending_state(self, setup):
        """Melee minion moves adjacent to enemy -> pending set, react deferred."""
        lib, _, _, _ = setup
        engine, device = _make_engine(setup)
        s = engine.state

        melee = _melee_card_id(lib)
        # P1 melee minion at (1,2). Enemy P2 at (3,2). After moving down to (2,2),
        # adjacent to enemy at (3,2) -> pending set.
        _place_minion(s, 0, slot=0, card_id=melee, owner=0, row=1, col=2)
        _place_minion(s, 0, slot=1, card_id=melee, owner=1, row=3, col=2)

        # Active player is 0 (P1). MOVE down (direction 1) from flat (1,2) = 7.
        action = _move_action(_flat(1, 2), direction=1)
        engine.step_batch(torch.tensor([action], dtype=torch.int64, device=device))

        assert s.pending_post_move_attacker[0].item() == 0, "pending must hold attacker slot"
        assert s.phase[0].item() == 0, "phase must remain ACTION (react deferred)"
        # Minion actually moved
        assert s.minion_row[0, 0].item() == 2

    def test_parity_ranged_move_no_pending(self, setup):
        """Ranged minion movement does not enter pending state."""
        lib, _, _, _ = setup
        engine, device = _make_engine(setup)
        s = engine.state

        ranged = _ranged_card_id(lib)
        _place_minion(s, 0, slot=0, card_id=ranged, owner=0, row=1, col=2)
        _place_minion(s, 0, slot=1, card_id=ranged, owner=1, row=3, col=2)

        action = _move_action(_flat(1, 2), direction=1)
        engine.step_batch(torch.tensor([action], dtype=torch.int64, device=device))

        assert s.pending_post_move_attacker[0].item() == -1, "ranged must not set pending"
        assert s.phase[0].item() == 1, "phase must transition to REACT immediately"

    def test_parity_melee_move_no_targets_no_pending(self, setup):
        """Melee minion moves into open space -> no pending, react fires."""
        lib, _, _, _ = setup
        engine, device = _make_engine(setup)
        s = engine.state

        melee = _melee_card_id(lib)
        _place_minion(s, 0, slot=0, card_id=melee, owner=0, row=1, col=0)
        # Enemy far away, not in melee range from (2,0).
        _place_minion(s, 0, slot=1, card_id=melee, owner=1, row=4, col=4)

        action = _move_action(_flat(1, 0), direction=1)
        engine.step_batch(torch.tensor([action], dtype=torch.int64, device=device))

        assert s.pending_post_move_attacker[0].item() == -1
        assert s.phase[0].item() == 1, "react phase entered immediately"

    def test_parity_pending_attack_resolves(self, setup):
        """From pending state, ATTACK clears pending and applies damage; react fires."""
        lib, ct, _, _ = setup
        engine, device = _make_engine(setup)
        s = engine.state

        melee = _melee_card_id(lib)
        _place_minion(s, 0, slot=0, card_id=melee, owner=0, row=1, col=2, hp=100)
        _place_minion(s, 0, slot=1, card_id=melee, owner=1, row=3, col=2, hp=100)

        # MOVE down -> pending set
        engine.step_batch(torch.tensor([_move_action(_flat(1, 2), 1)], dtype=torch.int64, device=device))
        assert s.pending_post_move_attacker[0].item() == 0
        assert s.phase[0].item() == 0  # still ACTION

        defender_hp_before = s.minion_health[0, 1].item()
        atk_value = ct.attack[melee].item()

        # Now ATTACK from (2,2) -> (3,2)
        attack = _attack_action(_flat(2, 2), _flat(3, 2))
        engine.step_batch(torch.tensor([attack], dtype=torch.int64, device=device))

        assert s.pending_post_move_attacker[0].item() == -1, "pending cleared"
        assert s.phase[0].item() == 1, "react phase entered after pending resolves"
        # Defender took attacker's damage
        assert s.minion_health[0, 1].item() == defender_hp_before - atk_value

    def test_parity_pending_decline(self, setup):
        """From pending state, DECLINE (PASS slot 1001) clears pending; react fires; no fatigue."""
        lib, _, _, _ = setup
        engine, device = _make_engine(setup)
        s = engine.state

        melee = _melee_card_id(lib)
        _place_minion(s, 0, slot=0, card_id=melee, owner=0, row=1, col=2, hp=100)
        _place_minion(s, 0, slot=1, card_id=melee, owner=1, row=3, col=2, hp=100)

        engine.step_batch(torch.tensor([_move_action(_flat(1, 2), 1)], dtype=torch.int64, device=device))
        assert s.pending_post_move_attacker[0].item() == 0

        hp_before = s.player_hp[0, 0].item()
        fatigue_before = s.fatigue_count[0, 0].item()

        # PASS slot 1001 == DECLINE while pending is set
        engine.step_batch(torch.tensor([PASS_IDX], dtype=torch.int64, device=device))

        assert s.pending_post_move_attacker[0].item() == -1
        assert s.phase[0].item() == 1, "react entered after decline"
        # No fatigue damage applied — DECLINE is not a real PASS
        assert s.player_hp[0, 0].item() == hp_before
        assert s.fatigue_count[0, 0].item() == fatigue_before
        # Defender HP unchanged (no attack happened)
        assert s.minion_health[0, 1].item() == 100

    def test_attack_blocked_when_pending_and_wrong_slot(self, setup):
        """While pending is set, an ATTACK from a non-pending attacker is a no-op."""
        lib, _, _, _ = setup
        engine, device = _make_engine(setup)
        s = engine.state

        melee = _melee_card_id(lib)
        # Pending attacker (slot 0) at (1,2), will move to (2,2).
        _place_minion(s, 0, slot=0, card_id=melee, owner=0, row=1, col=2, hp=100)
        # Other friendly minion (slot 2) already adjacent to an enemy at (4,4).
        _place_minion(s, 0, slot=2, card_id=melee, owner=0, row=3, col=4, hp=100)
        # Enemy adjacent to pending attacker after move
        _place_minion(s, 0, slot=1, card_id=melee, owner=1, row=3, col=2, hp=100)
        # Enemy adjacent to slot 2
        _place_minion(s, 0, slot=3, card_id=melee, owner=1, row=4, col=4, hp=100)

        engine.step_batch(torch.tensor([_move_action(_flat(1, 2), 1)], dtype=torch.int64, device=device))
        assert s.pending_post_move_attacker[0].item() == 0

        # Try to attack with slot 2 (the wrong attacker) — must be blocked.
        wrong = _attack_action(_flat(3, 4), _flat(4, 4))
        hp_target_before = s.minion_health[0, 3].item()
        engine.step_batch(torch.tensor([wrong], dtype=torch.int64, device=device))

        assert s.minion_health[0, 3].item() == hp_target_before, "wrong-attacker ATTACK was gated"
        assert s.pending_post_move_attacker[0].item() == 0, "pending preserved"
