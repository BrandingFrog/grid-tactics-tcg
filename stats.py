"""View training stats from the SQLite database."""

import sys
from pathlib import Path

db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/training.db")

if not db_path.exists():
    print(f"No training database found at {db_path}")
    print("Run train.bat first to generate training data.")
    input("\nPress Enter to close...")
    sys.exit(1)

from grid_tactics.db.reader import GameResultReader

reader = GameResultReader(db_path)

# --- Training Runs ---
runs = reader.get_runs()
print(f"\n{'='*60}")
print(f"  GRID TACTICS TCG - Training Stats")
print(f"  Database: {db_path}")
print(f"{'='*60}")

if not runs:
    print("\n  No training runs found. Run train.bat first.")
    input("\nPress Enter to close...")
    sys.exit(0)

print(f"\n  {len(runs)} training run(s)\n")
for run in runs:
    print(f"  Run: {run['run_id']}")
    print(f"    Started:    {run.get('started_at', 'N/A')}")
    print(f"    Ended:      {run.get('ended_at', 'N/A')}")
    print(f"    Timesteps:  {run.get('total_timesteps', 'N/A')}")
    print(f"    Model:      {run.get('model_path', 'N/A')}")
    print(f"    Desc:       {run.get('description', '')}")
    print()

# --- Win Rate Over Time ---
for run in runs:
    run_id = run['run_id']
    snapshots = reader.get_win_rate_over_time(run_id)
    if snapshots:
        print(f"  Win Rate History ({run_id}):")
        print(f"  {'Step':>10}  {'Episodes':>10}  {'Win Rate':>10}")
        print(f"  {'-'*10}  {'-'*10}  {'-'*10}")
        for s in snapshots:
            wr = s.get('win_rate_100', 0) or 0
            print(f"  {s.get('timestep', 0):>10}  {s.get('episode_num', 0):>10}  {wr:>9.1%}")
        print()

# --- Game Results Summary ---
for run in runs:
    run_id = run['run_id']
    results = reader.get_game_results(run_id, limit=None)
    if results:
        total = len(results)
        wins = sum(1 for r in results if r.get('winner') == 0)  # training player
        losses = sum(1 for r in results if r.get('winner') == 1)
        draws = sum(1 for r in results if r.get('winner') is None)
        avg_turns = sum(r.get('turn_count', 0) for r in results) / total if total else 0

        print(f"  Game Results ({run_id}): {total} games")
        print(f"    Wins:   {wins:>5} ({wins/total*100:.1f}%)")
        print(f"    Losses: {losses:>5} ({losses/total*100:.1f}%)")
        print(f"    Draws:  {draws:>5} ({draws/total*100:.1f}%)")
        print(f"    Avg turns: {avg_turns:.0f}")
        print()

# --- Card Usage (if available) ---
for run in runs:
    run_id = run['run_id']
    try:
        card_stats = reader.get_card_stats(run_id)
        if card_stats:
            print(f"  Card Stats ({run_id}):")
            print(f"  {'Card':>25}  {'Played':>8}  {'Win%':>8}")
            print(f"  {'-'*25}  {'-'*8}  {'-'*8}")
            for cs in card_stats[:15]:  # top 15
                name = cs.get('card_id', 'unknown')
                count = cs.get('play_count', 0)
                wr = cs.get('win_rate', 0) or 0
                print(f"  {name:>25}  {count:>8}  {wr:>7.1%}")
            print()
    except Exception:
        pass  # card_stats may not be populated yet

print(f"{'='*60}")
print(f"  TensorBoard: .venv\\Scripts\\tensorboard.exe --logdir data/tb_logs")
print(f"{'='*60}")
