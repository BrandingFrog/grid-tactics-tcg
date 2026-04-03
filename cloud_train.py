"""Cloud training script — runs on RunPod GPU instances.

This is the entry point that executes on the remote machine.
It trains the RL agent and saves results to /root/output/.

GPU utilization strategy:
  - Verifies CUDA availability before training
  - Uses SubprocVecEnv for parallel env stepping (fixes /dev/shm if needed)
  - Falls back to DummyVecEnv if SubprocVecEnv fails
  - Never forces n_envs=1 — multiple envs improve learning efficiency
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# Training config (can be overridden via env vars)
TOTAL_TIMESTEPS = int(os.environ.get("TRAIN_STEPS", "10_000_000"))
N_ENVS = int(os.environ.get("TRAIN_ENVS", "16"))
EVAL_FREQ = int(os.environ.get("EVAL_FREQ", "100_000"))
EVAL_GAMES = int(os.environ.get("EVAL_GAMES", "100"))
SEED = int(os.environ.get("TRAIN_SEED", "42"))
DESCRIPTION = os.environ.get("TRAIN_DESC", f"RunPod cloud training {TOTAL_TIMESTEPS} steps seed={SEED}")
# Training method override (hyperparameter presets)
METHOD = os.environ.get("TRAIN_METHOD", "default")


def verify_gpu():
    """Verify CUDA is available and print GPU info. Exit if no GPU found."""
    import torch

    print("\n--- GPU Verification ---")
    print(f"PyTorch version: {torch.__version__}")
    print(f"CUDA available: {torch.cuda.is_available()}")
    print(f"CUDA version: {torch.version.cuda}")

    if not torch.cuda.is_available():
        print("FATAL: CUDA not available! Training would be CPU-only.")
        print("Possible causes:")
        print("  - pip install overwrote GPU PyTorch with CPU version")
        print("  - CUDA drivers not loaded in container")
        print("  - Wrong container image")
        sys.exit(1)

    device_count = torch.cuda.device_count()
    for i in range(device_count):
        name = torch.cuda.get_device_name(i)
        mem = torch.cuda.get_device_properties(i).total_memory / 1e9
        print(f"GPU {i}: {name} ({mem:.1f} GB)")

    # Quick benchmark: measure GPU vs CPU speed
    x = torch.randn(1000, 1000, device="cuda")
    y = torch.randn(1000, 1000, device="cuda")
    torch.cuda.synchronize()
    import time
    start = time.perf_counter()
    for _ in range(100):
        _ = x @ y
    torch.cuda.synchronize()
    gpu_time = time.perf_counter() - start

    x_cpu = torch.randn(1000, 1000)
    y_cpu = torch.randn(1000, 1000)
    start = time.perf_counter()
    for _ in range(100):
        _ = x_cpu @ y_cpu
    cpu_time = time.perf_counter() - start

    speedup = cpu_time / gpu_time
    print(f"GPU speedup: {speedup:.1f}x (matmul benchmark)")
    print("--- GPU OK ---\n")
    return torch.cuda.get_device_name(0)


def fix_shared_memory():
    """Try to increase /dev/shm for SubprocVecEnv. Non-fatal if it fails."""
    try:
        result = subprocess.run(
            ["mount", "-o", "remount,size=2G", "/dev/shm"],
            capture_output=True, timeout=5,
        )
        if result.returncode == 0:
            print("Resized /dev/shm to 2GB for SubprocVecEnv")
            return True
    except Exception:
        pass

    # Check current /dev/shm size
    try:
        result = subprocess.run(
            ["df", "-h", "/dev/shm"], capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            print(f"Current /dev/shm:\n{result.stdout.strip()}")
    except Exception:
        pass

    return False


def get_method_hyperparams(method: str) -> dict:
    """Return hyperparameter overrides for different training methods.

    All methods use a large network (512-512-256) to actually utilize GPU.
    The default MlpPolicy [64,64] is too small — 0-3% GPU usage on a 4090.
    With [512,512,256] the network has ~460k params and GPU does real work.
    """
    # GPU-worthy network: 292 input -> 512 -> 512 -> 256 -> output
    # This is ~460k params vs ~25k for default [64,64]
    _gpu_net = {"policy_kwargs": {"net_arch": [512, 512, 256]}}
    # Even bigger for methods that need more capacity
    _big_net = {"policy_kwargs": {"net_arch": [1024, 512, 512, 256]}}

    methods = {
        "default": {
            "desc": "Standard PPO with GPU-sized network (512-512-256)",
            **_gpu_net,
        },
        "high_entropy": {
            "desc": "High exploration (ent_coef=0.05, 512-512-256)",
            "ent_coef": 0.05,
            **_gpu_net,
        },
        "low_lr": {
            "desc": "Low learning rate (1e-4, 512-512-256)",
            "learning_rate": 1e-4,
            **_gpu_net,
        },
        "large_batch": {
            "desc": "Large batches + big network (n_steps=2048, batch=512, 1024-512-512-256)",
            "n_steps": 2048,
            "batch_size": 512,
            **_big_net,
        },
        "aggressive": {
            "desc": "Aggressive learning (lr=1e-3, 20 epochs, 512-512-256)",
            "learning_rate": 1e-3,
            "n_epochs": 20,
            "ent_coef": 0.001,
            **_gpu_net,
        },
        "exploration": {
            "desc": "Maximum exploration (ent_coef=0.1, clip=0.3, 512-512-256)",
            "ent_coef": 0.1,
            "clip_range": 0.3,
            **_gpu_net,
        },
    }
    if method not in methods:
        print(f"WARNING: Unknown method '{method}', using default")
        print(f"Available methods: {', '.join(methods.keys())}")
        return {}
    preset = methods[method]
    print(f"Method: {method} — {preset.pop('desc')}")
    return preset


def create_env(n_envs: int, seed: int, use_shaped_reward: bool = True):
    """Create vectorized training environment, preferring SubprocVecEnv."""
    from grid_tactics.card_library import CardLibrary
    from grid_tactics.rl.env import GridTacticsEnv
    from grid_tactics.rl.self_play import SelfPlayEnv

    library = CardLibrary.from_directory(Path("data/cards"))

    # Build deck (same logic as training.py)
    from grid_tactics.rl.training import _build_standard_deck
    deck = _build_standard_deck(library)

    def _make_env(env_seed: int):
        def _init():
            base = GridTacticsEnv(library, deck, deck, seed=env_seed)
            return SelfPlayEnv(base, opponent_policy=None, use_shaped_reward=use_shaped_reward)
        return _init

    vec_type = "single"

    if n_envs > 1:
        # Use DummyVecEnv — SubprocVecEnv is unstable on cloud containers
        # (crashes on pkill, shared memory issues, connection resets).
        # DummyVecEnv runs sequentially but gives training diversity
        # and the workload is CPU-bound anyway.
        from stable_baselines3.common.vec_env import DummyVecEnv
        env = DummyVecEnv([_make_env(seed + i) for i in range(n_envs)])
        vec_type = f"DummyVecEnv({n_envs})"
        print(f"Using {vec_type} — {n_envs} envs for training diversity")

    if n_envs == 1:
        base_env = GridTacticsEnv(library, deck, deck, seed=seed)
        env = SelfPlayEnv(base_env, opponent_policy=None, use_shaped_reward=use_shaped_reward)
        vec_type = "single"

    return env, library, deck, vec_type


def main():
    print("=" * 60)
    print("  GRID TACTICS TCG — Cloud Training")
    print(f"  Steps: {TOTAL_TIMESTEPS:,}")
    print(f"  Parallel envs: {N_ENVS}")
    print(f"  Method: {METHOD}")
    print(f"  Seed: {SEED}")
    print("=" * 60)

    # Step 1: Verify GPU
    gpu_name = verify_gpu()

    # Step 2: Get method hyperparameters
    method_kwargs = get_method_hyperparams(METHOD)

    # Step 3: Create environment
    output_dir = Path("/root/output")
    output_dir.mkdir(parents=True, exist_ok=True)

    env, library, deck, vec_type = create_env(N_ENVS, SEED)

    # Step 4: Train
    from grid_tactics.rl.training import train_self_play
    from grid_tactics.rl.env import GridTacticsEnv
    from grid_tactics.rl.self_play import SelfPlayEnv

    desc = f"{DESCRIPTION} | method={METHOD} | gpu={gpu_name} | vec={vec_type}"

    # eval_freq is in SB3 "calls" not timesteps. With VecEnv, each call
    # steps all n_envs at once, so divide by n_envs to get the right frequency.
    actual_n_envs = N_ENVS if vec_type != "single" else 1
    adjusted_eval_freq = max(1, EVAL_FREQ // actual_n_envs)
    print(f"  Eval freq: every {adjusted_eval_freq} calls ({EVAL_FREQ} timesteps / {actual_n_envs} envs)")

    result = train_self_play(
        total_timesteps=TOTAL_TIMESTEPS,
        n_envs=actual_n_envs,
        device="cuda",
        db_path=output_dir / "training.db",
        checkpoint_dir=output_dir / "checkpoints",
        tensorboard_log=None,
        eval_freq=adjusted_eval_freq,
        eval_games=EVAL_GAMES,
        description=desc,
        seed=SEED,
        **method_kwargs,
    )

    # Save summary
    summary = {
        "run_id": result["run_id"],
        "final_win_rate": result["final_win_rate"],
        "model_path": result["model_path"],
        "total_timesteps": TOTAL_TIMESTEPS,
        "n_envs": N_ENVS,
        "method": METHOD,
        "seed": SEED,
        "gpu": gpu_name,
        "vec_type": vec_type,
        "hyperparams": method_kwargs,
    }
    with open(output_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print()
    print("=" * 60)
    print("  TRAINING COMPLETE")
    print(f"  Win rate vs random: {result['final_win_rate']:.1%}")
    print(f"  Run ID: {result['run_id']}")
    print(f"  Model: {result['model_path']}")
    print(f"  GPU: {gpu_name}")
    print(f"  Vec type: {vec_type}")
    print(f"  Method: {METHOD}")
    print(f"  Results: {output_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
