"""Cloud training script — runs on RunPod GPU instances.

This is the entry point that executes on the remote machine.
It trains the RL agent and saves results to /workspace/output/.
"""

import sys
import os
import json
from pathlib import Path

# Training config (can be overridden via env vars)
TOTAL_TIMESTEPS = int(os.environ.get("TRAIN_STEPS", "10_000_000"))
N_ENVS = int(os.environ.get("TRAIN_ENVS", "16"))
EVAL_FREQ = int(os.environ.get("EVAL_FREQ", "100_000"))
EVAL_GAMES = int(os.environ.get("EVAL_GAMES", "100"))
DESCRIPTION = os.environ.get("TRAIN_DESC", f"RunPod cloud training {TOTAL_TIMESTEPS} steps")

def main():
    print("=" * 60)
    print("  GRID TACTICS TCG — Cloud Training")
    print(f"  Steps: {TOTAL_TIMESTEPS:,}")
    print(f"  Parallel envs: {N_ENVS}")
    print(f"  Device: cuda")
    print("=" * 60)

    # Ensure output dir exists
    output_dir = Path("/root/output")
    output_dir.mkdir(parents=True, exist_ok=True)

    from grid_tactics.rl.training import train_self_play

    # SubprocVecEnv crashes on RunPod (shared memory issue)
    # Use single env — GPU still accelerates the neural net
    actual_envs = 1 if N_ENVS > 1 else N_ENVS
    if actual_envs != N_ENVS:
        print(f"  Note: Using 1 env (SubprocVecEnv not supported on this container)")

    result = train_self_play(
        total_timesteps=TOTAL_TIMESTEPS,
        n_envs=actual_envs,
        device="cuda",
        db_path=output_dir / "training.db",
        checkpoint_dir=output_dir / "checkpoints",
        tensorboard_log=str(output_dir / "tb_logs"),
        eval_freq=EVAL_FREQ,
        eval_games=EVAL_GAMES,
        description=DESCRIPTION,
    )

    # Save summary
    summary = {
        "run_id": result["run_id"],
        "final_win_rate": result["final_win_rate"],
        "model_path": result["model_path"],
        "total_timesteps": TOTAL_TIMESTEPS,
        "n_envs": N_ENVS,
    }
    with open(output_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print()
    print("=" * 60)
    print(f"  TRAINING COMPLETE")
    print(f"  Win rate vs random: {result['final_win_rate']:.1%}")
    print(f"  Run ID: {result['run_id']}")
    print(f"  Model: {result['model_path']}")
    print(f"  Results: {output_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
