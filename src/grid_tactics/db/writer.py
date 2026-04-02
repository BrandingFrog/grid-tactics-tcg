"""SQLite writers for game results and training metadata.

Provides:
  - GameResultWriter: Buffered batch writer for game results
  - TrainingRunWriter: Training run lifecycle management

Design decisions:
  - WAL mode for concurrent read/write (Pitfall 5)
  - Batch inserts via executemany, never per-step writes
  - training_player column tracks which side the RL agent played (Pitfall 6)
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from grid_tactics.db.schema import ensure_schema


class GameResultWriter:
    """Buffered batch writer for game results.

    Accumulates game results in memory and flushes to SQLite
    when the buffer reaches ``buffer_size`` or on explicit ``flush()`` call.

    Usage as context manager ensures buffer is flushed on exit::

        with GameResultWriter(db_path, buffer_size=100) as writer:
            writer.record_game(run_id="run-001", ...)
    """

    def __init__(self, db_path: Path, buffer_size: int = 100) -> None:
        self._db_path = Path(db_path)
        self._buffer_size = buffer_size
        self._buffer: list[tuple[str, int, Optional[int], Optional[int], int, int, int,
                                 Optional[str], Optional[str], Optional[float],
                                 Optional[int], str]] = []
        ensure_schema(self._db_path)

    def record_game(
        self,
        run_id: str,
        episode_num: int,
        seed: Optional[int] = None,
        winner: Optional[int] = None,
        turn_count: int = 0,
        p1_hp: int = 0,
        p2_hp: int = 0,
        p1_deck_hash: Optional[str] = None,
        p2_deck_hash: Optional[str] = None,
        game_duration_ms: Optional[float] = None,
        training_player: Optional[int] = None,
    ) -> None:
        """Record a single game result to the buffer.

        Auto-flushes when buffer reaches ``buffer_size``.

        Args:
            run_id: ID of the training run this game belongs to.
            episode_num: Episode number within the run.
            seed: RNG seed used for this game.
            winner: 0 for player 1, 1 for player 2, None for draw.
            turn_count: Total turns played.
            p1_hp: Player 1's final HP.
            p2_hp: Player 2's final HP.
            p1_deck_hash: Hash of player 1's deck composition.
            p2_deck_hash: Hash of player 2's deck composition.
            game_duration_ms: Game wall-clock duration in milliseconds.
            training_player: Which player index (0 or 1) the training agent was.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        self._buffer.append((
            run_id, episode_num, seed, winner, turn_count,
            p1_hp, p2_hp, p1_deck_hash, p2_deck_hash,
            game_duration_ms, training_player, timestamp,
        ))
        if len(self._buffer) >= self._buffer_size:
            self.flush()

    def flush(self) -> None:
        """Batch-insert all buffered game results to SQLite."""
        if not self._buffer:
            return

        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.executemany(
                """INSERT INTO game_results
                   (run_id, episode_num, seed, winner, turn_count,
                    p1_final_hp, p2_final_hp, p1_deck_hash, p2_deck_hash,
                    game_duration_ms, training_player, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                self._buffer,
            )
            conn.commit()
        finally:
            conn.close()
        self._buffer.clear()

    def __enter__(self) -> GameResultWriter:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.flush()


class TrainingRunWriter:
    """Manages training run lifecycle in SQLite.

    Handles:
      - Starting/ending training runs with metadata
      - Recording periodic win rate snapshots
      - Storing deck compositions
      - Recording per-game card action statistics
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        ensure_schema(self._db_path)

    def _connect(self) -> sqlite3.Connection:
        """Open a connection to the database."""
        return sqlite3.connect(str(self._db_path))

    def start_run(
        self,
        run_id: str,
        hyperparameters: dict[str, object],
        description: str = "",
    ) -> str:
        """Create a new training run record.

        Args:
            run_id: Unique identifier for this run.
            hyperparameters: Dict of training hyperparameters (stored as JSON).
            description: Optional human-readable description.

        Returns:
            The run_id.
        """
        started_at = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO training_runs
                   (run_id, started_at, hyperparameters, description)
                   VALUES (?, ?, ?, ?)""",
                (run_id, started_at, json.dumps(hyperparameters), description),
            )
            conn.commit()
        finally:
            conn.close()
        return run_id

    def end_run(
        self,
        run_id: str,
        total_timesteps: int,
        model_path: Optional[str] = None,
    ) -> None:
        """Mark a training run as complete.

        Args:
            run_id: ID of the run to end.
            total_timesteps: Total environment steps taken during training.
            model_path: Path to the saved model file.
        """
        ended_at = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                """UPDATE training_runs
                   SET ended_at = ?, total_timesteps = ?, model_path = ?
                   WHERE run_id = ?""",
                (ended_at, total_timesteps, model_path, run_id),
            )
            conn.commit()
        finally:
            conn.close()

    def record_snapshot(
        self,
        run_id: str,
        timestep: int,
        episode_num: int,
        win_rate_100: float,
        win_rate_1000: Optional[float] = None,
        avg_game_length: Optional[float] = None,
        avg_reward: Optional[float] = None,
    ) -> None:
        """Record a periodic win rate snapshot.

        Args:
            run_id: ID of the training run.
            timestep: Current training timestep.
            episode_num: Current episode number.
            win_rate_100: Win rate over the last 100 games.
            win_rate_1000: Win rate over the last 1000 games (if available).
            avg_game_length: Average game length over recent games.
            avg_reward: Average reward over recent games.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO win_rate_snapshots
                   (run_id, timestep, episode_num, win_rate_100,
                    win_rate_1000, avg_game_length, avg_reward, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, timestep, episode_num, win_rate_100,
                 win_rate_1000, avg_game_length, avg_reward, timestamp),
            )
            conn.commit()
        finally:
            conn.close()

    def record_deck(self, deck_hash: str, card_counts: dict[str, int]) -> None:
        """Store a deck composition. Idempotent via INSERT OR IGNORE.

        Args:
            deck_hash: Unique hash identifying this deck composition.
            card_counts: Mapping of card_id to count in the deck.
        """
        conn = self._connect()
        try:
            conn.execute(
                """INSERT OR IGNORE INTO deck_compositions
                   (deck_hash, card_counts)
                   VALUES (?, ?)""",
                (deck_hash, json.dumps(card_counts)),
            )
            conn.commit()
        finally:
            conn.close()

    def record_card_actions(
        self,
        game_id: int,
        player: int,
        card_numeric_id: int,
        times_played: int,
        total_damage: int = 0,
        times_killed: int = 0,
    ) -> None:
        """Record per-game card usage statistics.

        Args:
            game_id: ID of the game (from game_results.game_id).
            player: Player index (0 or 1).
            card_numeric_id: Numeric ID of the card.
            times_played: How many times this card was played in the game.
            total_damage: Total damage dealt by this card.
            times_killed: Number of kills attributed to this card.
        """
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO card_actions
                   (game_id, player, card_numeric_id, times_played,
                    total_damage, times_killed)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (game_id, player, card_numeric_id, times_played,
                 total_damage, times_killed),
            )
            conn.commit()
        finally:
            conn.close()
