"""SQLite schema creation for training data persistence.

Provides:
  - SCHEMA_SQL: Full CREATE TABLE SQL for the 5 training data tables
  - ensure_schema(): Idempotent schema creation with WAL mode

Tables:
  - training_runs: One row per training session with hyperparameters
  - game_results: One row per completed game episode
  - deck_compositions: Maps deck hashes to card count JSON
  - card_actions: Per-game card usage statistics (aggregated, not per-step)
  - win_rate_snapshots: Periodic aggregate metrics during training
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_SQL = """\
-- Training runs: one row per training session
CREATE TABLE IF NOT EXISTS training_runs (
    run_id          TEXT PRIMARY KEY,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    total_timesteps INTEGER,
    hyperparameters TEXT NOT NULL,
    model_path      TEXT,
    description     TEXT,
    git_commit      TEXT
);

-- Game results: one row per completed game episode
CREATE TABLE IF NOT EXISTS game_results (
    game_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES training_runs(run_id),
    episode_num     INTEGER NOT NULL,
    seed            INTEGER,
    winner          INTEGER,
    turn_count      INTEGER NOT NULL,
    p1_final_hp     INTEGER NOT NULL,
    p2_final_hp     INTEGER NOT NULL,
    p1_deck_hash    TEXT,
    p2_deck_hash    TEXT,
    game_duration_ms REAL,
    training_player INTEGER,
    timestamp       TEXT NOT NULL
);

-- Deck compositions: maps deck hashes to card lists
CREATE TABLE IF NOT EXISTS deck_compositions (
    deck_hash       TEXT PRIMARY KEY,
    card_counts     TEXT NOT NULL
);

-- Card actions: per-game card usage stats (aggregated, not per-step)
CREATE TABLE IF NOT EXISTS card_actions (
    game_id         INTEGER NOT NULL REFERENCES game_results(game_id),
    player          INTEGER NOT NULL,
    card_numeric_id INTEGER NOT NULL,
    times_played    INTEGER DEFAULT 0,
    total_damage    INTEGER DEFAULT 0,
    times_killed    INTEGER DEFAULT 0,
    PRIMARY KEY (game_id, player, card_numeric_id)
);

-- Win rate snapshots: periodic aggregates during training
CREATE TABLE IF NOT EXISTS win_rate_snapshots (
    snapshot_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES training_runs(run_id),
    timestep        INTEGER NOT NULL,
    episode_num     INTEGER NOT NULL,
    win_rate_100    REAL,
    win_rate_1000   REAL,
    avg_game_length REAL,
    avg_reward      REAL,
    timestamp       TEXT NOT NULL
);

-- Indexes for dashboard queries
CREATE INDEX IF NOT EXISTS idx_game_results_run ON game_results(run_id);
CREATE INDEX IF NOT EXISTS idx_game_results_winner ON game_results(winner);
CREATE INDEX IF NOT EXISTS idx_win_rate_run ON win_rate_snapshots(run_id, timestep);
CREATE INDEX IF NOT EXISTS idx_card_actions_game ON card_actions(game_id);
"""


def ensure_schema(db_path: Path) -> None:
    """Create all tables and indexes if they don't exist.

    Sets WAL journal mode for concurrent read/write support.
    Idempotent: safe to call multiple times.

    Args:
        db_path: Path to the SQLite database file. Created if it doesn't exist.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()
