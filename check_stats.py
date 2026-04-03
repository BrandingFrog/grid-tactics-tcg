from grid_tactics.db.reader import GameResultReader
from pathlib import Path
r = GameResultReader(Path("/root/output/training.db"))
runs = r.get_runs()
for run in runs:
    rid = run["run_id"]
    s = r.get_overall_stats(rid)
    h = r.get_win_rate_over_time(rid)
    print("Run:", rid)
    print("Games:", s["total_games"])
    wr = s["win_rate"] or 0
    print("Win rate:", round(wr * 100, 1), "%")
    al = s["avg_game_length"] or 0
    print("Avg turns:", round(al))
    for snap in h:
        swr = snap["win_rate_100"] or 0
        print("  Step", snap["timestep"], ":", round(swr * 100, 1), "%")
