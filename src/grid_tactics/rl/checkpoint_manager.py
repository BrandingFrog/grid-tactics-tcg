"""Checkpoint pool manager for self-play training.

Saves, loads, samples, and prunes model checkpoints used in the
opponent pool for self-play training. Prevents strategy cycling
by maintaining a diverse pool of historical opponents.
"""

from __future__ import annotations

import random
from pathlib import Path


class CheckpointManager:
    """Manages a pool of model checkpoints for self-play opponent sampling.

    Checkpoints are stored as .zip files (SB3 save format) in pool_dir.
    Naming convention: checkpoint_{step}.zip

    Attributes:
        pool_dir: Directory for storing checkpoint files.
        pool_size: Maximum number of checkpoints to keep in pool.
    """

    def __init__(self, pool_dir: Path, pool_size: int = 10) -> None:
        """Initialize the checkpoint manager.

        Args:
            pool_dir: Directory for checkpoint storage. Created if missing.
            pool_size: Maximum checkpoints to retain after pruning.
        """
        self.pool_dir = Path(pool_dir)
        self.pool_size = pool_size
        self.pool_dir.mkdir(parents=True, exist_ok=True)

    def save(self, model: object, step: int) -> Path:
        """Save a model checkpoint to the pool.

        Args:
            model: SB3 model with a .save() method.
            step: Training step number for checkpoint naming.

        Returns:
            Path to the saved checkpoint .zip file.
        """
        path = self.pool_dir / f"checkpoint_{step}"
        model.save(str(path))  # type: ignore[attr-defined]
        # SB3 appends .zip automatically
        zip_path = self.pool_dir / f"checkpoint_{step}.zip"
        return zip_path

    def sample(self, latest_ratio: float = 0.5) -> Path | None:
        """Sample a checkpoint from the pool.

        With probability latest_ratio, returns the latest checkpoint.
        Otherwise, returns a random historical checkpoint.

        Args:
            latest_ratio: Probability of selecting the latest checkpoint.

        Returns:
            Path to a checkpoint .zip file, or None if pool is empty.
        """
        checkpoints = self.list_checkpoints()
        if not checkpoints:
            return None

        if len(checkpoints) == 1:
            return checkpoints[0]

        if random.random() < latest_ratio:
            return checkpoints[-1]  # latest (sorted ascending)
        else:
            # Random from all (including latest)
            return random.choice(checkpoints)

    def list_checkpoints(self) -> list[Path]:
        """List all checkpoints sorted by step number ascending.

        Returns:
            List of Path objects to checkpoint .zip files, sorted by step.
        """
        checkpoints = list(self.pool_dir.glob("checkpoint_*.zip"))

        def _extract_step(p: Path) -> int:
            # checkpoint_12345.zip -> 12345
            stem = p.stem  # checkpoint_12345
            parts = stem.split("_")
            return int(parts[1])

        checkpoints.sort(key=_extract_step)
        return checkpoints

    def prune(self) -> None:
        """Remove oldest checkpoints exceeding pool_size.

        Keeps only the newest pool_size checkpoints, deleting the rest.
        """
        checkpoints = self.list_checkpoints()
        if len(checkpoints) <= self.pool_size:
            return

        # Delete oldest (list is sorted ascending, so oldest are first)
        to_delete = checkpoints[: len(checkpoints) - self.pool_size]
        for path in to_delete:
            path.unlink(missing_ok=True)
