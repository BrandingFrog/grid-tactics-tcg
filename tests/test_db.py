"""Tests for SQLite data persistence layer (schema, writer, reader)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("sb3_contrib"),
    reason="audit-followup: sb3_contrib not installed in this env (RL deps gated)",
)
def test_sb3_import():
    """SB3 and MaskablePPO are importable (skipped when RL deps missing)."""
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

    card_counts = {"rat": 3, "to_the_ratmobile": 3, "prohibition": 2}
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

    card_counts = {"rat": 3}
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


# ---------------------------------------------------------------------------
# Reader tests -- GameResultReader
# ---------------------------------------------------------------------------

def _populate_run(db_path: Path, run_id: str, num_games: int = 5) -> None:
    """Helper: create a run with game results and snapshots for reader tests."""
    from grid_tactics.db.writer import GameResultWriter, TrainingRunWriter

    tw = TrainingRunWriter(db_path)
    tw.start_run(run_id, {"lr": 3e-4, "batch_size": 64}, description="reader test")

    with GameResultWriter(db_path, buffer_size=200) as gw:
        for i in range(num_games):
            gw.record_game(
                run_id=run_id,
                episode_num=i,
                seed=i * 10,
                winner=0 if i % 3 != 0 else 1,
                turn_count=30 + i,
                p1_hp=10 if i % 3 != 0 else 0,
                p2_hp=0 if i % 3 != 0 else 15,
                training_player=0,
            )

    tw.record_snapshot(run_id, timestep=1000, episode_num=50, win_rate_100=0.55)
    tw.record_snapshot(run_id, timestep=5000, episode_num=250, win_rate_100=0.70,
                       avg_game_length=35.0, avg_reward=0.4)


def test_reader_get_runs(tmp_path: Path):
    """get_runs returns all runs ordered by start time descending."""
    import time
    from grid_tactics.db.reader import GameResultReader
    from grid_tactics.db.writer import TrainingRunWriter

    db_path = tmp_path / "test.db"
    tw = TrainingRunWriter(db_path)
    tw.start_run("run-older", {"lr": 1e-3})
    time.sleep(0.05)  # ensure different timestamps
    tw.start_run("run-newer", {"lr": 3e-4})

    reader = GameResultReader(db_path)
    runs = reader.get_runs()

    assert len(runs) == 2
    assert runs[0]["run_id"] == "run-newer"
    assert runs[1]["run_id"] == "run-older"


def test_reader_get_game_results(tmp_path: Path):
    """get_game_results returns all games for a run."""
    from grid_tactics.db.reader import GameResultReader

    db_path = tmp_path / "test.db"
    _populate_run(db_path, "run-reader-001", num_games=5)

    reader = GameResultReader(db_path)
    games = reader.get_game_results("run-reader-001")

    assert len(games) == 5
    # Verify ordering by episode_num
    episode_nums = [g["episode_num"] for g in games]
    assert episode_nums == list(range(5))


def test_reader_win_rate_over_time(tmp_path: Path):
    """get_win_rate_over_time returns snapshots ordered by timestep."""
    from grid_tactics.db.reader import GameResultReader

    db_path = tmp_path / "test.db"
    _populate_run(db_path, "run-wr-001")

    reader = GameResultReader(db_path)
    snapshots = reader.get_win_rate_over_time("run-wr-001")

    assert len(snapshots) == 2
    assert snapshots[0]["timestep"] == 1000
    assert snapshots[1]["timestep"] == 5000
    assert snapshots[0]["win_rate_100"] == pytest.approx(0.55)
    assert snapshots[1]["win_rate_100"] == pytest.approx(0.70)


def test_reader_card_usage(tmp_path: Path):
    """get_card_usage returns aggregated card statistics."""
    from grid_tactics.db.reader import GameResultReader
    from grid_tactics.db.writer import GameResultWriter, TrainingRunWriter

    db_path = tmp_path / "test.db"
    tw = TrainingRunWriter(db_path)
    tw.start_run("run-cu-001", {"lr": 1e-3})

    with GameResultWriter(db_path, buffer_size=100) as gw:
        # Game 1: player 0 wins
        gw.record_game(
            run_id="run-cu-001", episode_num=0, seed=1,
            winner=0, turn_count=30, p1_hp=10, p2_hp=0,
        )
        # Game 2: player 1 wins
        gw.record_game(
            run_id="run-cu-001", episode_num=1, seed=2,
            winner=1, turn_count=40, p1_hp=0, p2_hp=5,
        )

    # Card 5 played in both games by player 0
    tw.record_card_actions(game_id=1, player=0, card_numeric_id=5,
                           times_played=3, total_damage=10, times_killed=1)
    tw.record_card_actions(game_id=2, player=0, card_numeric_id=5,
                           times_played=2, total_damage=5, times_killed=0)
    # Card 7 played in game 1 only
    tw.record_card_actions(game_id=1, player=0, card_numeric_id=7,
                           times_played=1, total_damage=3, times_killed=1)

    reader = GameResultReader(db_path)
    usage = reader.get_card_usage("run-cu-001")

    assert len(usage) == 2

    # Card 5 should be first (most played)
    card5 = usage[0]
    assert card5["card_numeric_id"] == 5
    assert card5["total_times_played"] == 5
    assert card5["games_with_card"] == 2
    # Win rate: game 1 won (1.0), game 2 lost (0.0) => 0.5
    assert card5["win_rate_with_card"] == pytest.approx(0.5)

    card7 = usage[1]
    assert card7["card_numeric_id"] == 7
    assert card7["total_times_played"] == 1
    assert card7["games_with_card"] == 1
    assert card7["win_rate_with_card"] == pytest.approx(1.0)


def test_reader_overall_stats(tmp_path: Path):
    """get_overall_stats returns correct aggregates."""
    from grid_tactics.db.reader import GameResultReader

    db_path = tmp_path / "test.db"
    _populate_run(db_path, "run-stats-001", num_games=6)

    reader = GameResultReader(db_path)
    stats = reader.get_overall_stats("run-stats-001")

    assert stats["total_games"] == 6
    # training_player=0; winner pattern: 1,0,0,1,0,0 => 4 wins out of 6
    assert stats["win_rate"] == pytest.approx(4 / 6)
    assert stats["avg_game_length"] is not None
    assert stats["avg_game_length"] > 0
    # avg_reward comes from latest snapshot
    assert stats["avg_reward"] == pytest.approx(0.4)


def test_reader_overall_stats_empty(tmp_path: Path):
    """get_overall_stats returns zeros for a run with no games."""
    from grid_tactics.db.reader import GameResultReader
    from grid_tactics.db.writer import TrainingRunWriter

    db_path = tmp_path / "test.db"
    tw = TrainingRunWriter(db_path)
    tw.start_run("run-empty", {"lr": 1e-3})

    reader = GameResultReader(db_path)
    stats = reader.get_overall_stats("run-empty")

    assert stats["total_games"] == 0
    assert stats["win_rate"] == 0.0
    assert stats["avg_game_length"] == 0.0
