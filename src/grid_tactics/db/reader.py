"""SQLite reader for dashboard queries.

Provides:
  - GameResultReader: Read-only query interface returning dicts for easy
    DataFrame conversion in the Phase 9 Streamlit dashboard.

All methods return lists of dicts (via sqlite3.Row) so callers can
pass directly to pandas.DataFrame() or iterate as mappings.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional


def _dict_factory(cursor: sqlite3.Cursor, row: tuple[object, ...]) -> dict[str, object]:
    """Row factory that produces dicts keyed by column name."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


class GameResultReader:
    """Read-only query interface for training data.

    Designed for Phase 9 Streamlit dashboard consumption.
    All methods return lists of dicts for easy DataFrame conversion.

    Args:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        """Open a read-only-style connection with dict row factory."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = _dict_factory  # type: ignore[assignment]
        return conn

    def get_runs(self) -> list[dict[str, object]]:
        """Get all training runs sorted by start time (newest first).

        Returns:
            List of run dicts with keys: run_id, started_at, ended_at,
            total_timesteps, hyperparameters, model_path, description, git_commit.
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM training_runs ORDER BY started_at DESC"
            ).fetchall()
            return rows
        finally:
            conn.close()

    def get_run(self, run_id: str) -> Optional[dict[str, object]]:
        """Get a single training run by ID.

        Args:
            run_id: The run identifier.

        Returns:
            Run dict or None if not found.
        """
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM training_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            return row
        finally:
            conn.close()

    def get_game_results(
        self, run_id: str, limit: int | None = 1000
    ) -> list[dict[str, object]]:
        """Get game results for a training run.

        Args:
            run_id: The run identifier.
            limit: Maximum number of results to return, or None for all.

        Returns:
            List of game result dicts ordered by episode_num.
        """
        conn = self._connect()
        try:
            if limit is None:
                rows = conn.execute(
                    """SELECT * FROM game_results
                       WHERE run_id = ?
                       ORDER BY episode_num""",
                    (run_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM game_results
                       WHERE run_id = ?
                       ORDER BY episode_num
                       LIMIT ?""",
                    (run_id, limit),
                ).fetchall()
            return rows
        finally:
            conn.close()

    def get_win_rate_over_time(self, run_id: str) -> list[dict[str, object]]:
        """Get win rate snapshots for a run, ordered by timestep.

        Args:
            run_id: The run identifier.

        Returns:
            List of snapshot dicts with keys: snapshot_id, run_id, timestep,
            episode_num, win_rate_100, win_rate_1000, avg_game_length,
            avg_reward, timestamp.
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT * FROM win_rate_snapshots
                   WHERE run_id = ?
                   ORDER BY timestep""",
                (run_id,),
            ).fetchall()
            return rows
        finally:
            conn.close()

    def get_card_usage(self, run_id: str) -> list[dict[str, object]]:
        """Get aggregated card usage statistics for a run.

        Joins card_actions with game_results to compute per-card aggregates:
        total times played, average times played per game, number of games
        the card appeared in, and win rate when the card was used.

        Args:
            run_id: The run identifier.

        Returns:
            List of dicts with keys: card_numeric_id, total_times_played,
            avg_times_played, games_with_card, win_rate_with_card.
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT
                       ca.card_numeric_id,
                       SUM(ca.times_played) AS total_times_played,
                       AVG(ca.times_played) AS avg_times_played,
                       COUNT(DISTINCT ca.game_id) AS games_with_card,
                       AVG(CASE
                           WHEN gr.winner = ca.player THEN 1.0
                           WHEN gr.winner IS NULL THEN 0.5
                           ELSE 0.0
                       END) AS win_rate_with_card
                   FROM card_actions ca
                   JOIN game_results gr ON ca.game_id = gr.game_id
                   WHERE gr.run_id = ?
                   GROUP BY ca.card_numeric_id
                   ORDER BY total_times_played DESC""",
                (run_id,),
            ).fetchall()
            return rows
        finally:
            conn.close()

    def get_overall_stats(self, run_id: str) -> dict[str, object]:
        """Get aggregate statistics for a training run.

        Args:
            run_id: The run identifier.

        Returns:
            Dict with keys: total_games, win_rate, avg_game_length, avg_reward.
            Returns zeros if no games exist for the run.
        """
        conn = self._connect()
        try:
            row = conn.execute(
                """SELECT
                       COUNT(*) AS total_games,
                       AVG(CASE
                           WHEN training_player IS NOT NULL
                               AND winner = training_player THEN 1.0
                           WHEN winner IS NULL THEN 0.5
                           ELSE 0.0
                       END) AS win_rate,
                       AVG(turn_count) AS avg_game_length,
                       NULL AS avg_reward
                   FROM game_results
                   WHERE run_id = ?""",
                (run_id,),
            ).fetchone()

            if row is None or row["total_games"] == 0:
                return {
                    "total_games": 0,
                    "win_rate": 0.0,
                    "avg_game_length": 0.0,
                    "avg_reward": None,
                }

            # Fetch avg_reward from the latest snapshot if available
            snapshot = conn.execute(
                """SELECT avg_reward FROM win_rate_snapshots
                   WHERE run_id = ?
                   ORDER BY timestep DESC
                   LIMIT 1""",
                (run_id,),
            ).fetchone()

            result = dict(row)
            if snapshot and snapshot["avg_reward"] is not None:
                result["avg_reward"] = snapshot["avg_reward"]

            return result
        finally:
            conn.close()
