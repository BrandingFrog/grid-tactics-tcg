"""Tests for SQLite data persistence layer (schema, writer, reader)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

def test_sb3_import():
    """SB3 and MaskablePPO are importable."""
    from sb3_contrib import MaskablePPO  # noqa: F401
    import torch  # noqa: F401


def test_schema_creation(tmp_path: Path):
    """ensure_schema creates all 5 required tables."""
    from grid_tactics.db.schema import ensure_schema

    db_path = tmp_path / "test.db"
    ensure_schema(db_path)

    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = sorted(
        row[0] for row in cursor.fetchall()
        if not row[0].startswith("sqlite_")
    )
    conn.close()

    expected = sorted([
        "card_actions",
        "deck_compositions",
        "game_results",
        "training_runs",
        "win_rate_snapshots",
    ])
    assert tables == expected


def test_wal_mode(tmp_path: Path):
    """ensure_schema sets WAL journal mode."""
    from grid_tactics.db.schema import ensure_schema

    db_path = tmp_path / "test.db"
    ensure_schema(db_path)

    conn = sqlite3.connect(str(db_path))
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()

    assert mode == "wal"


def test_schema_idempotent(tmp_path: Path):
    """Calling ensure_schema twice does not raise."""
    from grid_tactics.db.schema import ensure_schema

    db_path = tmp_path / "test.db"
    ensure_schema(db_path)
    ensure_schema(db_path)  # should not raise


# ---------------------------------------------------------------------------
# Writer tests -- GameResultWriter
# ---------------------------------------------------------------------------

def test_game_result_roundtrip(tmp_path: Path):
    """Write a game result and read it back with raw SQL."""
    from grid_tactics.db.writer import GameResultWriter

    db_path = tmp_path / "test.db"
    with GameResultWriter(db_path, buffer_size=10) as writer:
        writer.record_game(
            run_id="run-001",
            episode_num=1,
            seed=42,
            winner=0,
            turn_count=50,
            p1_hp=10,
            p2_hp=0,
            p1_deck_hash="deck_a",
            p2_deck_hash="deck_b",
            game_duration_ms=1234.5,
            training_player=0,
        )

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM game_results WHERE run_id = 'run-001'").fetchone()
    conn.close()

    assert row is not None
    assert row["winner"] == 0
    assert row["turn_count"] == 50
    assert row["p1_final_hp"] == 10
    assert row["p2_final_hp"] == 0
    assert row["seed"] == 42
    assert row["training_player"] == 0


def test_batch_flush(tmp_path: Path):
    """Buffer auto-flushes when buffer reaches buffer_size."""
    from grid_tactics.db.writer import GameResultWriter

    db_path = tmp_path / "test.db"
    buffer_size = 5
    writer = GameResultWriter(db_path, buffer_size=buffer_size)

    # Write buffer_size - 1 records (should NOT flush)
    for i in range(buffer_size - 1):
        writer.record_game(
            run_id="run-002",
            episode_num=i,
            seed=i,
            winner=0,
            turn_count=10,
            p1_hp=20,
            p2_hp=0,
        )

    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM game_results").fetchone()[0]
    assert count == 0, f"Expected 0 flushed rows, got {count}"

    # Write one more -- triggers auto-flush
    writer.record_game(
        run_id="run-002",
        episode_num=buffer_size - 1,
        seed=99,
        winner=1,
        turn_count=20,
        p1_hp=0,
        p2_hp=15,
    )

    count = conn.execute("SELECT COUNT(*) FROM game_results").fetchone()[0]
    conn.close()
    assert count == buffer_size, f"Expected {buffer_size} flushed rows, got {count}"


def test_context_manager_flushes(tmp_path: Path):
    """Context manager flushes remaining buffer on exit."""
    from grid_tactics.db.writer import GameResultWriter

    db_path = tmp_path / "test.db"
    with GameResultWriter(db_path, buffer_size=100) as writer:
        for i in range(3):
            writer.record_game(
                run_id="run-003",
                episode_num=i,
                seed=i,
                winner=0,
                turn_count=10,
                p1_hp=20,
                p2_hp=0,
            )

    # After context exit, all 3 should be flushed
    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM game_results").fetchone()[0]
    conn.close()
    assert count == 3


# ---------------------------------------------------------------------------
# Writer tests -- TrainingRunWriter
# ---------------------------------------------------------------------------

def test_training_metadata(tmp_path: Path):
    """start_run creates a row, end_run updates it."""
    from grid_tactics.db.writer import TrainingRunWriter

    db_path = tmp_path / "test.db"
    writer = TrainingRunWriter(db_path)

    hyperparams = {"learning_rate": 3e-4, "batch_size": 64}
    writer.start_run("run-meta-001", hyperparams, description="test run")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM training_runs WHERE run_id = 'run-meta-001'"
    ).fetchone()

    assert row is not None
    assert row["started_at"] is not None
    assert row["ended_at"] is None
    assert json.loads(row["hyperparameters"]) == hyperparams
    assert row["description"] == "test run"

    writer.end_run("run-meta-001", total_timesteps=50000, model_path="models/test.zip")

    row = conn.execute(
        "SELECT * FROM training_runs WHERE run_id = 'run-meta-001'"
    ).fetchone()
    conn.close()

    assert row["ended_at"] is not None
    assert row["total_timesteps"] == 50000
    assert row["model_path"] == "models/test.zip"


def test_win_rate_snapshot(tmp_path: Path):
    """record_snapshot writes a queryable win_rate_snapshots row."""
    from grid_tactics.db.writer import TrainingRunWriter

    db_path = tmp_path / "test.db"
    writer = TrainingRunWriter(db_path)
    writer.start_run("run-snap-001", {"lr": 1e-3})

    writer.record_snapshot(
        run_id="run-snap-001",
        timestep=10000,
        episode_num=100,
        win_rate_100=0.65,
        win_rate_1000=0.55,
        avg_game_length=42.3,
        avg_reward=0.3,
    )

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM win_rate_snapshots WHERE run_id = 'run-snap-001'"
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["timestep"] == 10000
    assert row["win_rate_100"] == pytest.approx(0.65)
    assert row["win_rate_1000"] == pytest.approx(0.55)
    assert row["avg_game_length"] == pytest.approx(42.3)


def test_deck_composition(tmp_path: Path):
    """record_deck stores deck composition as JSON."""
    from grid_tactics.db.writer import TrainingRunWriter

    db_path = tmp_path / "test.db"
    writer = TrainingRunWriter(db_path)

    card_counts = {"fire_imp": 3, "fireball": 3, "shield_block": 2}
    writer.record_deck("deck_hash_001", card_counts)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM deck_compositions WHERE deck_hash = 'deck_hash_001'"
    ).fetchone()
    conn.close()

    assert row is not None
    assert json.loads(row["card_counts"]) == card_counts


def test_deck_composition_idempotent(tmp_path: Path):
    """record_deck with same hash does not raise (INSERT OR IGNORE)."""
    from grid_tactics.db.writer import TrainingRunWriter

    db_path = tmp_path / "test.db"
    writer = TrainingRunWriter(db_path)

    card_counts = {"fire_imp": 3}
    writer.record_deck("deck_hash_dup", card_counts)
    writer.record_deck("deck_hash_dup", card_counts)  # should not raise


def test_card_actions(tmp_path: Path):
    """record_card_actions stores per-game card usage."""
    from grid_tactics.db.writer import GameResultWriter, TrainingRunWriter

    db_path = tmp_path / "test.db"
    training_writer = TrainingRunWriter(db_path)
    training_writer.start_run("run-ca-001", {"lr": 1e-3})

    with GameResultWriter(db_path, buffer_size=10) as gw:
        gw.record_game(
            run_id="run-ca-001",
            episode_num=1,
            seed=42,
            winner=0,
            turn_count=30,
            p1_hp=10,
            p2_hp=0,
        )

    training_writer.record_card_actions(
        game_id=1,
        player=0,
        card_numeric_id=5,
        times_played=3,
        total_damage=12,
        times_killed=1,
    )

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM card_actions WHERE game_id = 1 AND player = 0 AND card_numeric_id = 5"
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["times_played"] == 3
    assert row["total_damage"] == 12
    assert row["times_killed"] == 1
