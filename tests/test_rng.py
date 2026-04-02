"""Tests for GameRNG deterministic wrapper."""

import pytest

from grid_tactics.rng import GameRNG


class TestGameRNGShuffle:
    """Tests for deterministic shuffle behavior."""

    def test_same_seed_same_shuffle(self):
        """Two GameRNG instances with same seed produce identical shuffles."""
        rng1 = GameRNG(42)
        rng2 = GameRNG(42)
        items = tuple(range(20))
        assert rng1.shuffle(items) == rng2.shuffle(items)

    def test_different_seed_different_shuffle(self):
        """Two GameRNG instances with different seeds produce different shuffles."""
        rng1 = GameRNG(42)
        rng2 = GameRNG(99)
        items = tuple(range(20))
        assert rng1.shuffle(items) != rng2.shuffle(items)

    def test_shuffle_returns_new_tuple(self):
        """Shuffle returns a new tuple; input is not mutated."""
        rng = GameRNG(42)
        original = tuple(range(20))
        result = rng.shuffle(original)
        # Original is a tuple (immutable), but verify result is a separate object
        assert isinstance(result, tuple)
        assert original == tuple(range(20))  # unchanged

    def test_shuffle_contains_same_elements(self):
        """Shuffled output contains the same elements as input (just reordered)."""
        rng = GameRNG(42)
        items = tuple(range(20))
        result = rng.shuffle(items)
        assert sorted(result) == sorted(items)
        assert len(result) == len(items)

    def test_shuffle_actually_reorders(self):
        """Shuffle produces a different ordering (not identity) for non-trivial input."""
        rng = GameRNG(42)
        items = tuple(range(20))
        result = rng.shuffle(items)
        # With 20 elements, probability of identity permutation is ~1/20! (negligible)
        assert result != items


class TestGameRNGState:
    """Tests for save/restore state functionality."""

    def test_get_and_restore_state(self):
        """Save state, do operations, restore, compare outputs."""
        rng1 = GameRNG(42)
        # Advance RNG with some shuffles
        rng1.shuffle(tuple(range(10)))
        # Save state
        state = rng1.get_state()
        # Do more shuffles
        result1 = rng1.shuffle(tuple(range(20)))

        # Restore from saved state
        rng2 = GameRNG.from_state(state)
        result2 = rng2.shuffle(tuple(range(20)))

        assert result1 == result2

    def test_deterministic_sequence(self):
        """Multiple shuffle calls from same seed produce same sequence."""
        rng1 = GameRNG(42)
        rng2 = GameRNG(42)
        items_a = tuple(range(10))
        items_b = tuple(range(20, 40))

        # Both RNGs should produce identical sequences
        assert rng1.shuffle(items_a) == rng2.shuffle(items_a)
        assert rng1.shuffle(items_b) == rng2.shuffle(items_b)

    def test_generator_property(self):
        """GameRNG exposes the underlying numpy Generator."""
        import numpy as np

        rng = GameRNG(42)
        assert isinstance(rng.generator, np.random.Generator)
