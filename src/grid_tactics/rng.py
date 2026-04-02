"""Deterministic RNG wrapper around numpy.random.Generator.

Provides seeded, reproducible randomness for game setup and card draws.
NOT stored inside frozen GameState (it's mutable).
Passed alongside GameState as a separate parameter.
"""

from __future__ import annotations

from typing import Any

import numpy as np


class GameRNG:
    """Deterministic RNG wrapper using numpy's PCG64 generator.

    Two instances created with the same seed will produce identical
    sequences of results, guaranteeing deterministic reproducibility (ENG-11).
    """

    __slots__ = ("_rng",)

    def __init__(self, seed: int) -> None:
        self._rng: np.random.Generator = np.random.default_rng(seed)

    def shuffle(self, items: tuple[int, ...]) -> tuple[int, ...]:
        """Return a new shuffled tuple. Does not mutate input."""
        arr = list(items)
        self._rng.shuffle(arr)
        return tuple(arr)

    def get_state(self) -> dict[str, Any]:
        """Get serializable RNG state for save/restore."""
        return self._rng.bit_generator.state

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> GameRNG:
        """Restore a GameRNG from a previously saved state."""
        instance = cls.__new__(cls)
        instance._rng = np.random.default_rng()
        instance._rng.bit_generator.state = state
        return instance

    @property
    def generator(self) -> np.random.Generator:
        """Access the underlying numpy Generator for advanced use."""
        return self._rng
