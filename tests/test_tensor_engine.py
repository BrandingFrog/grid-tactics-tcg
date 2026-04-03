"""Unit tests for tensor engine components."""

import pytest
import torch
from pathlib import Path
from grid_tactics.card_library import CardLibrary
from grid_tactics.tensor_engine import TensorGameEngine, CardTable, TensorGameState


@pytest.fixture
def setup():
    lib = CardLibrary.from_directory(Path("data/cards"))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ct = CardTable.from_library(lib, device)
    all_ids = list(range(18))
    deck = torch.tensor([(all_ids * 3)[:40]], device=device)
    return lib, ct, deck, device


class TestCardTable:
    def test_card_count(self, setup):
        _, ct, _, _ = setup
        assert ct.num_cards == 18

    def test_card_types(self, setup):
        lib, ct, _, _ = setup
        for i in range(18):
            card = lib.get_by_id(i)
            assert ct.card_type[i].item() == card.card_type.value

    def test_minion_stats(self, setup):
        lib, ct, _, _ = setup
        for i in range(18):
            card = lib.get_by_id(i)
            if card.card_type.value == 0:  # MINION
                assert ct.attack[i].item() == card.attack
                assert ct.health[i].item() == card.health
                assert ct.attack_range[i].item() == card.attack_range

    def test_effects(self, setup):
        lib, ct, _, _ = setup
        for i in range(18):
            card = lib.get_by_id(i)
            assert ct.num_effects[i].item() == len(card.effects)
            for j, eff in enumerate(card.effects):
                assert ct.effect_type[i, j].item() == eff.effect_type.value
                assert ct.effect_trigger[i, j].item() == eff.trigger.value

    def test_react_eligible(self, setup):
        lib, ct, _, _ = setup
        for i in range(18):
            card = lib.get_by_id(i)
            expected = card.card_type.value == 2 or card.is_multi_purpose
            assert ct.is_react_eligible[i].item() == expected, (
                f"Card {card.name}: expected react_eligible={expected}"
            )

    def test_distance_matrices(self, setup):
        _, ct, _, _ = setup
        # Manhattan distance between (0,0) and (4,4) = 8
        assert ct.distance_manhattan[0, 24].item() == 8
        # Chebyshev distance between (0,0) and (4,4) = 4
        assert ct.distance_chebyshev[0, 24].item() == 4
        # Same position = 0
        assert ct.distance_manhattan[0, 0].item() == 0
        # Orthogonal: same row
        assert ct.is_orthogonal[0, 1].item() == True  # (0,0) and (0,1)
        assert ct.is_orthogonal[0, 6].item() == False  # (0,0) and (1,1) diagonal


class TestReset:
    def test_initial_state(self, setup):
        _, ct, deck, device = setup
        engine = TensorGameEngine(4, ct, deck.expand(4, -1), deck.expand(4, -1), device)
        engine.reset_batch()
        s = engine.state
        assert (s.player_hp == 20).all()
        assert (s.player_mana[:, 0] == 1).all()  # P1 starts with 1 mana
        assert (s.hand_sizes == 5).all()  # 5 starting cards
        assert (s.turn_number == 1).all()
        assert (s.phase == 0).all()  # ACTION
        assert (s.active_player == 0).all()  # P1 starts
        assert (~s.is_game_over).all()

    def test_hands_have_valid_cards(self, setup):
        _, ct, deck, device = setup
        engine = TensorGameEngine(4, ct, deck.expand(4, -1), deck.expand(4, -1), device)
        engine.reset_batch()
        for p in range(2):
            for i in range(5):
                card_ids = engine.state.hands[:, p, i]
                assert (card_ids >= 0).all() and (card_ids < 18).all()

    def test_board_empty(self, setup):
        _, ct, deck, device = setup
        engine = TensorGameEngine(4, ct, deck.expand(4, -1), deck.expand(4, -1), device)
        engine.reset_batch()
        assert (engine.state.board == -1).all()

    def test_no_minions(self, setup):
        _, ct, deck, device = setup
        engine = TensorGameEngine(4, ct, deck.expand(4, -1), deck.expand(4, -1), device)
        engine.reset_batch()
        assert (~engine.state.minion_alive).all()


class TestStepping:
    def test_draw_action(self, setup):
        _, ct, deck, device = setup
        engine = TensorGameEngine(4, ct, deck.expand(4, -1), deck.expand(4, -1), device)
        engine.reset_batch()
        # DRAW action = 1000
        actions = torch.full((4,), 1000, dtype=torch.int64, device=device)
        engine.step_batch(actions)
        # Hand should have 6 cards now, phase should be REACT
        assert (engine.state.hand_sizes[:, 0] == 6).all()
        assert (engine.state.phase == 1).all()

    def test_pass_advances_turn(self, setup):
        _, ct, deck, device = setup
        engine = TensorGameEngine(4, ct, deck.expand(4, -1), deck.expand(4, -1), device)
        engine.reset_batch()
        # DRAW then PASS
        engine.step_batch(torch.full((4,), 1000, dtype=torch.int64, device=device))
        engine.step_batch(torch.full((4,), 1001, dtype=torch.int64, device=device))
        assert (engine.state.phase == 0).all()
        assert (engine.state.active_player == 1).all()
        assert (engine.state.turn_number == 2).all()

    def test_mana_regen(self, setup):
        _, ct, deck, device = setup
        engine = TensorGameEngine(4, ct, deck.expand(4, -1), deck.expand(4, -1), device)
        engine.reset_batch()
        # After P1's turn, P2 gets mana regen
        engine.step_batch(torch.full((4,), 1000, dtype=torch.int64, device=device))
        engine.step_batch(torch.full((4,), 1001, dtype=torch.int64, device=device))
        assert (engine.state.player_mana[:, 1] == 2).all()

    def test_multiple_turns(self, setup):
        _, ct, deck, device = setup
        engine = TensorGameEngine(4, ct, deck.expand(4, -1), deck.expand(4, -1), device)
        engine.reset_batch()
        # 10 turns of DRAW + PASS
        for _ in range(10):
            engine.step_batch(torch.full((4,), 1000, dtype=torch.int64, device=device))
            engine.step_batch(torch.full((4,), 1001, dtype=torch.int64, device=device))
        assert (engine.state.turn_number == 11).all()


class TestLegalMasks:
    def test_initial_has_actions(self, setup):
        _, ct, deck, device = setup
        engine = TensorGameEngine(4, ct, deck.expand(4, -1), deck.expand(4, -1), device)
        engine.reset_batch()
        from grid_tactics.tensor_engine.legal_actions import compute_legal_mask_batch
        masks = compute_legal_mask_batch(engine.state, ct)
        assert masks.any(dim=1).all(), "Every game must have legal actions at start"

    def test_draw_legal_at_start(self, setup):
        _, ct, deck, device = setup
        engine = TensorGameEngine(4, ct, deck.expand(4, -1), deck.expand(4, -1), device)
        engine.reset_batch()
        from grid_tactics.tensor_engine.legal_actions import compute_legal_mask_batch
        masks = compute_legal_mask_batch(engine.state, ct)
        assert masks[:, 1000].all(), "DRAW should be legal at start"

    def test_pass_not_legal_action_phase(self, setup):
        _, ct, deck, device = setup
        engine = TensorGameEngine(4, ct, deck.expand(4, -1), deck.expand(4, -1), device)
        engine.reset_batch()
        from grid_tactics.tensor_engine.legal_actions import compute_legal_mask_batch
        masks = compute_legal_mask_batch(engine.state, ct)
        assert not masks[:, 1001].any(), "PASS not legal in ACTION phase at start"

    def test_pass_legal_react_phase(self, setup):
        _, ct, deck, device = setup
        engine = TensorGameEngine(4, ct, deck.expand(4, -1), deck.expand(4, -1), device)
        engine.reset_batch()
        # Step to react phase
        engine.step_batch(torch.full((4,), 1000, dtype=torch.int64, device=device))
        from grid_tactics.tensor_engine.legal_actions import compute_legal_mask_batch
        masks = compute_legal_mask_batch(engine.state, ct)
        assert masks[:, 1001].all(), "PASS should be legal in REACT phase"
