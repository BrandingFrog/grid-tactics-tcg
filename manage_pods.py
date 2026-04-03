"""RunPod GPU Pod Manager — full control over cloud training infrastructure.

Commands:
    python manage_pods.py launch [--gpu 4090] [--steps 10M] [--method default] [--envs 16]
    python manage_pods.py experiment                    # Launch multi-method experiment suite
    python manage_pods.py list                          # List all pods
    python manage_pods.py status <pod_id>               # Detailed pod status + GPU utilization
    python manage_pods.py gpu <pod_id>                  # nvidia-smi over SSH
    python manage_pods.py logs <pod_id>                 # Tail training logs
    python manage_pods.py download <pod_id> [--dest .]  # Download results via SFTP
    python manage_pods.py stop <pod_id>                 # Stop + terminate pod
    python manage_pods.py stop-all                      # Stop all pods
    python manage_pods.py budget                        # Show cost estimates
    python manage_pods.py gpus                          # List available GPU types + pricing
"""

import argparse
import io
import json
import os
import sys
import tarfile
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BUDGET_EUR = 140.0
USD_TO_EUR = 0.92  # approximate conversion

GPU_MAP = {
    "4090": "NVIDIA GeForce RTX 4090",
    "A100": "NVIDIA A100 80GB PCIe",
    "A100-SXM": "NVIDIA A100-SXM4-80GB",
    "H100": "NVIDIA H100 80GB HBM3",
    "L40S": "NVIDIA L40S",
    "A40": "NVIDIA A40",
    "3090": "NVIDIA GeForce RTX 3090",
}

# Container image with CUDA PyTorch pre-installed
CONTAINER_IMAGE = "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04"

# Files/dirs to upload to the pod
CODE_PATHS = [
    "src/",
    "data/cards/",
    "cloud_train.py",
    "check_stats.py",
]

# Pip install that does NOT overwrite the pre-installed GPU PyTorch
INSTALL_CMD = (
    "cd /workspace && "
    # Pin torch to container version to prevent pip from changing it
    'TORCH_VER=$(python -c "import torch; print(torch.__version__)") && '
    'pip install numpy gymnasium sb3-contrib stable-baselines3 "torch==$TORCH_VER" -q && '
    # Verify CUDA still works after install
    'python -c "import torch; assert torch.cuda.is_available(), \'CUDA BROKEN\'; '
    "print(f'GPU OK: {torch.cuda.get_device_name(0)}')\" && "
    # Fix shared memory for SubprocVecEnv
    "mount -o remount,size=2G /dev/shm 2>/dev/null; "
    "echo 'Setup complete'"
)

# Cost tracking file
COST_FILE = Path(__file__).parent / ".pod_costs.json"


def load_api_key():
    """Load RunPod API key from .env file or environment."""
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("RUNPOD_API_KEY=") and not line.startswith("#"):
                key = line.split("=", 1)[1].strip()
                if key and key != "your_key_here":
                    return key
    return os.environ.get("RUNPOD_API_KEY")


def init_runpod():
    """Initialize RunPod SDK with API key."""
    import runpod
    key = load_api_key()
    if not key:
        print("ERROR: No RUNPOD_API_KEY found in .env or environment")
        sys.exit(1)
    runpod.api_key = key
    return runpod


def create_code_archive() -> bytes:
    """Create a tar.gz archive of the source code in memory."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for code_path in CODE_PATHS:
            full = Path(__file__).parent / code_path
            if full.is_dir():
                tar.add(str(full), arcname=code_path)
            elif full.is_file():
                tar.add(str(full), arcname=code_path)
            else:
                print(f"WARNING: {code_path} not found, skipping")
    return buf.getvalue()


def wait_for_pod(runpod, pod_id: str, timeout: int = 300) -> dict:
    """Wait for pod to reach RUNNING status."""
    print(f"Waiting for pod {pod_id} to start...", end="", flush=True)
    start = time.time()
    while time.time() - start < timeout:
        pod = runpod.get_pod(pod_id)
        status = pod.get("desiredStatus", "UNKNOWN")
        runtime = pod.get("runtime")
        if status == "RUNNING" and runtime:
            ports = runtime.get("ports", [])
            if ports:
                print(f" READY ({int(time.time() - start)}s)")
                return pod
        print(".", end="", flush=True)
        time.sleep(5)
    print(f" TIMEOUT after {timeout}s")
    return pod


def get_ssh_connection(pod_id: str):
    """Get SSH connection to a pod. Returns SSHConnection or None."""
    try:
        from runpod.cli.utils.ssh_cmd import SSHConnection
        return SSHConnection(pod_id)
    except Exception as e:
        print(f"SSH connection failed: {e}")
        print("Ensure your SSH public key is set in RunPod account settings.")
        print("Go to: https://www.runpod.io/console/user/settings")
        return None


def upload_code(ssh, archive_bytes: bytes):
    """Upload code archive to pod and extract it."""
    import tempfile
    # Write archive to temp file for SFTP upload
    tmp = Path(tempfile.mktemp(suffix=".tar.gz"))
    tmp.write_bytes(archive_bytes)
    try:
        print("Uploading code archive...")
        ssh.put_file(str(tmp), "/workspace/code.tar.gz")
        print("Extracting on pod...")
        ssh.run_commands([
            "cd /workspace && tar xzf code.tar.gz && rm code.tar.gz",
            "ls -la /workspace/src/ /workspace/data/cards/ /workspace/cloud_train.py",
        ])
        print("Code uploaded successfully")
    finally:
        tmp.unlink(missing_ok=True)


def record_cost(pod_id: str, gpu_type: str, hours: float, cost_usd: float):
    """Record pod cost to tracking file."""
    costs = {}
    if COST_FILE.exists():
        costs = json.loads(COST_FILE.read_text())

    if "pods" not in costs:
        costs["pods"] = {}

    costs["pods"][pod_id] = {
        "gpu": gpu_type,
        "hours": hours,
        "cost_usd": cost_usd,
        "cost_eur": cost_usd * USD_TO_EUR,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    costs["total_usd"] = sum(p["cost_usd"] for p in costs["pods"].values())
    costs["total_eur"] = costs["total_usd"] * USD_TO_EUR
    costs["remaining_eur"] = BUDGET_EUR - costs["total_eur"]

    COST_FILE.write_text(json.dumps(costs, indent=2))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_launch(args):
    """Launch a single training pod."""
    runpod = init_runpod()
    gpu_name = GPU_MAP.get(args.gpu, args.gpu)

    steps = args.steps
    if isinstance(steps, str):
        steps = steps.upper().replace("M", "000000").replace("K", "000")
    steps = int(steps)

    print("=" * 60)
    print("  RunPod Launch")
    print(f"  GPU: {args.gpu} ({gpu_name})")
    print(f"  Steps: {steps:,}")
    print(f"  Envs: {args.envs}")
    print(f"  Method: {args.method}")
    print(f"  Seed: {args.seed}")
    print("=" * 60)

    # Create code archive
    archive = create_code_archive()
    print(f"Code archive: {len(archive) / 1024:.1f} KB")

    # Setup command: install deps then start training
    train_cmd = (
        f"cd /workspace && "
        f"TRAIN_STEPS={steps} "
        f"TRAIN_ENVS={args.envs} "
        f"TRAIN_METHOD={args.method} "
        f"TRAIN_SEED={args.seed} "
        f"EVAL_FREQ={max(steps // 20, 50000)} "
        f"EVAL_GAMES=100 "
        f"python cloud_train.py 2>&1 | tee /workspace/training.log"
    )

    try:
        pod = runpod.create_pod(
            name=f"gt-{args.method}-{args.gpu}-s{args.seed}",
            image_name=CONTAINER_IMAGE,
            gpu_type_id=gpu_name,
            gpu_count=1,
            volume_in_gb=20,
            container_disk_in_gb=20,
            start_ssh=True,
            cloud_type="ALL",  # community pods are cheaper
            env={
                "TRAIN_STEPS": str(steps),
                "TRAIN_ENVS": str(args.envs),
                "TRAIN_METHOD": args.method,
                "TRAIN_SEED": str(args.seed),
            },
        )

        pod_id = pod.get("id")
        print(f"\nPod created: {pod_id}")
        print(f"Dashboard: https://www.runpod.io/console/pods/{pod_id}")

        # Wait for pod to be ready
        pod = wait_for_pod(runpod, pod_id)

        # Upload code and start training via SSH
        ssh = get_ssh_connection(pod_id)
        if ssh:
            try:
                upload_code(ssh, archive)
                print("\nInstalling dependencies (preserving GPU PyTorch)...")
                ssh.run_commands([INSTALL_CMD])
                print("\nStarting training...")
                ssh.run_commands([f"nohup bash -c '{train_cmd}' &"])
                print("\nTraining started in background!")
            finally:
                ssh.close()
        else:
            print("\nCouldn't establish SSH. Upload code manually:")
            print(f"  1. Go to https://www.runpod.io/console/pods/{pod_id}")
            print(f"  2. Open web terminal")
            print(f"  3. Upload code and run: {train_cmd}")

        print(f"\nManagement commands:")
        print(f"  Status:   python manage_pods.py status {pod_id}")
        print(f"  GPU:      python manage_pods.py gpu {pod_id}")
        print(f"  Logs:     python manage_pods.py logs {pod_id}")
        print(f"  Download: python manage_pods.py download {pod_id}")
        print(f"  Stop:     python manage_pods.py stop {pod_id}")

        return pod_id

    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


def cmd_experiment(args):
    """Launch a multi-method experiment suite on multiple 4090s."""
    runpod = init_runpod()

    steps = args.steps
    if isinstance(steps, str):
        steps = steps.upper().replace("M", "000000").replace("K", "000")
    steps = int(steps)

    # Experiment configurations
    experiments = [
        {"method": "default", "seed": 42, "desc": "Baseline PPO"},
        {"method": "high_entropy", "seed": 42, "desc": "High exploration"},
        {"method": "large_batch", "seed": 42, "desc": "Large batches (GPU-optimized)"},
        {"method": "aggressive", "seed": 42, "desc": "Aggressive learning"},
        {"method": "default", "seed": 123, "desc": "Baseline PPO (different seed)"},
        {"method": "exploration", "seed": 42, "desc": "Maximum exploration"},
    ]

    # Budget check: estimate cost per experiment
    # 4090 ~$0.40/hr, 10M steps with 16 envs takes ~2-4 hours
    est_hours = 3.0  # conservative estimate per run
    est_cost_per = 0.40 * est_hours  # ~$1.20 per run
    max_experiments = int(BUDGET_EUR / (est_cost_per * USD_TO_EUR))

    print("=" * 60)
    print("  Experiment Suite")
    print(f"  GPU: RTX 4090 (~$0.40/hr)")
    print(f"  Steps per run: {steps:,}")
    print(f"  Estimated hours per run: ~{est_hours}")
    print(f"  Budget: {BUDGET_EUR:.0f}")
    print(f"  Max experiments in budget: ~{max_experiments}")
    print("=" * 60)

    print(f"\nPlanned experiments ({len(experiments)}):")
    total_est_cost = 0
    for i, exp in enumerate(experiments, 1):
        cost_eur = est_cost_per * USD_TO_EUR
        total_est_cost += cost_eur
        print(f"  {i}. {exp['desc']} (method={exp['method']}, seed={exp['seed']}) ~{cost_eur:.2f}")

    print(f"\nEstimated total cost: ~{total_est_cost:.2f}")
    print(f"Budget remaining after: ~{BUDGET_EUR - total_est_cost:.2f}")

    if total_est_cost > BUDGET_EUR:
        print(f"\nWARNING: Estimated cost exceeds budget! Reducing experiments.")
        experiments = experiments[:max_experiments]

    response = input(f"\nLaunch {len(experiments)} experiments? (y/n): ").strip().lower()
    if response != "y":
        print("Cancelled.")
        return

    # Launch experiments
    pod_ids = []
    archive = create_code_archive()
    print(f"Code archive: {len(archive) / 1024:.1f} KB")

    for i, exp in enumerate(experiments, 1):
        print(f"\n--- Launching experiment {i}/{len(experiments)}: {exp['desc']} ---")

        try:
            pod = runpod.create_pod(
                name=f"gt-{exp['method']}-s{exp['seed']}",
                image_name=CONTAINER_IMAGE,
                gpu_type_id=GPU_MAP["4090"],
                gpu_count=1,
                volume_in_gb=20,
                container_disk_in_gb=20,
                start_ssh=True,
                cloud_type="ALL",
                env={
                    "TRAIN_STEPS": str(steps),
                    "TRAIN_ENVS": "16",
                    "TRAIN_METHOD": exp["method"],
                    "TRAIN_SEED": str(exp["seed"]),
                },
            )
            pod_id = pod.get("id")
            pod_ids.append(pod_id)
            print(f"  Pod: {pod_id}")

            # Wait and setup
            wait_for_pod(runpod, pod_id, timeout=180)
            ssh = get_ssh_connection(pod_id)
            if ssh:
                try:
                    upload_code(ssh, archive)
                    ssh.run_commands([INSTALL_CMD])
                    train_cmd = (
                        f"cd /workspace && "
                        f"TRAIN_STEPS={steps} TRAIN_ENVS=16 "
                        f"TRAIN_METHOD={exp['method']} TRAIN_SEED={exp['seed']} "
                        f"EVAL_FREQ={max(steps // 20, 50000)} EVAL_GAMES=100 "
                        f"python cloud_train.py 2>&1 | tee /workspace/training.log"
                    )
                    ssh.run_commands([f"nohup bash -c '{train_cmd}' &"])
                    print(f"  Training started!")
                finally:
                    ssh.close()

            # Small delay between launches to avoid API rate limits
            if i < len(experiments):
                time.sleep(5)

        except Exception as e:
            print(f"  FAILED: {e}")
            continue

    print(f"\n{'=' * 60}")
    print(f"  Launched {len(pod_ids)}/{len(experiments)} experiments")
    print(f"  Pod IDs: {', '.join(pod_ids)}")
    print(f"\n  Monitor all: python manage_pods.py list")
    print(f"  Stop all:    python manage_pods.py stop-all")
    print(f"{'=' * 60}")


def cmd_list(args):
    """List all active pods."""
    runpod = init_runpod()
    pods = runpod.get_pods()

    if not pods:
        print("No active pods.")
        return

    print(f"{'ID':<20} {'Name':<30} {'Status':<12} {'GPU':<25} {'Uptime'}")
    print("-" * 100)
    for pod in pods:
        pid = pod.get("id", "?")
        name = pod.get("name", "?")
        status = pod.get("desiredStatus", "?")
        gpu = pod.get("machine", {}).get("gpuDisplayName", "?")
        runtime = pod.get("runtime", {})
        uptime = runtime.get("uptimeInSeconds", 0) if runtime else 0
        uptime_str = f"{uptime // 3600}h {(uptime % 3600) // 60}m" if uptime else "—"
        print(f"{pid:<20} {name:<30} {status:<12} {gpu:<25} {uptime_str}")


def cmd_status(args):
    """Show detailed pod status."""
    runpod = init_runpod()
    pod = runpod.get_pod(args.pod_id)

    print(f"Pod: {args.pod_id}")
    print(f"  Name: {pod.get('name', '?')}")
    print(f"  Status: {pod.get('desiredStatus', '?')}")

    machine = pod.get("machine", {})
    if machine:
        print(f"  GPU: {machine.get('gpuDisplayName', '?')}")

    runtime = pod.get("runtime", {})
    if runtime:
        uptime = runtime.get("uptimeInSeconds", 0)
        print(f"  Uptime: {uptime // 3600}h {(uptime % 3600) // 60}m {uptime % 60}s")
        gpus = runtime.get("gpus", [])
        for gpu in gpus:
            print(f"  GPU ID: {gpu.get('id', '?')}")
        ports = runtime.get("ports", [])
        for port in ports:
            print(f"  Port: {port.get('privatePort')} -> {port.get('ip')}:{port.get('publicPort')} ({port.get('type')})")

    # Try SSH for live GPU stats
    print("\n  Checking GPU utilization via SSH...")
    ssh = get_ssh_connection(args.pod_id)
    if ssh:
        try:
            ssh.run_commands(["nvidia-smi"])
        finally:
            ssh.close()


def cmd_gpu(args):
    """Check GPU utilization on a pod via SSH."""
    ssh = get_ssh_connection(args.pod_id)
    if not ssh:
        return
    try:
        ssh.run_commands([
            "nvidia-smi",
            "echo",
            "echo '--- GPU Memory Usage ---'",
            "nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv,noheader",
        ])
    finally:
        ssh.close()


def cmd_logs(args):
    """Tail training logs from a pod."""
    ssh = get_ssh_connection(args.pod_id)
    if not ssh:
        return
    try:
        lines = args.lines or 50
        ssh.run_commands([
            f"tail -n {lines} /workspace/training.log 2>/dev/null || echo 'No training.log found'",
            "echo",
            "echo '--- Process Check ---'",
            "ps aux | grep python | grep -v grep || echo 'No Python processes'",
        ])
    finally:
        ssh.close()


def cmd_download(args):
    """Download training results from a pod."""
    dest = Path(args.dest or ".")
    dest.mkdir(parents=True, exist_ok=True)

    ssh = get_ssh_connection(args.pod_id)
    if not ssh:
        return

    try:
        # Check what results exist
        print("Checking for results...")
        ssh.run_commands([
            "ls -la /root/output/ 2>/dev/null || echo 'No /root/output/'",
            "ls -la /workspace/output/ 2>/dev/null || echo 'No /workspace/output/'",
        ])

        # Download key files
        files_to_download = [
            ("/root/output/training.db", "training.db"),
            ("/root/output/summary.json", "summary.json"),
            ("/workspace/training.log", "training.log"),
        ]

        for remote_path, local_name in files_to_download:
            local_path = dest / f"{args.pod_id}_{local_name}"
            try:
                ssh.get_file(remote_path, str(local_path))
                print(f"  Downloaded: {local_path}")
            except Exception as e:
                print(f"  Skip {local_name}: {e}")

        # Download model checkpoints
        model_dir = dest / f"{args.pod_id}_checkpoints"
        try:
            ssh.run_commands([
                f"cd /root/output && tar czf /tmp/checkpoints.tar.gz checkpoints/ 2>/dev/null"
            ])
            local_tar = dest / f"{args.pod_id}_checkpoints.tar.gz"
            ssh.get_file("/tmp/checkpoints.tar.gz", str(local_tar))
            print(f"  Downloaded: {local_tar}")
        except Exception as e:
            print(f"  Skip checkpoints: {e}")

        print(f"\nResults saved to: {dest.resolve()}")

    finally:
        ssh.close()


def cmd_stop(args):
    """Stop and terminate a pod."""
    runpod = init_runpod()

    # Get uptime for cost tracking before stopping
    try:
        pod = runpod.get_pod(args.pod_id)
        runtime = pod.get("runtime", {})
        uptime = runtime.get("uptimeInSeconds", 0) if runtime else 0
        gpu = pod.get("machine", {}).get("gpuDisplayName", "Unknown")
        hours = uptime / 3600

        # Estimate cost (rough, based on 4090 pricing)
        hourly_rate = 0.40  # default estimate
        cost_usd = hours * hourly_rate
        record_cost(args.pod_id, gpu, hours, cost_usd)
        print(f"Pod {args.pod_id}: {hours:.1f}h, ~${cost_usd:.2f}")
    except Exception:
        pass

    try:
        runpod.stop_pod(args.pod_id)
        print(f"Stopped {args.pod_id}")
    except Exception as e:
        print(f"Stop failed: {e}")

    try:
        runpod.terminate_pod(args.pod_id)
        print(f"Terminated {args.pod_id}")
    except Exception as e:
        print(f"Terminate failed: {e}")


def cmd_stop_all(args):
    """Stop and terminate all pods."""
    runpod = init_runpod()
    pods = runpod.get_pods()

    if not pods:
        print("No active pods.")
        return

    print(f"Found {len(pods)} active pods:")
    for pod in pods:
        print(f"  {pod.get('id')} — {pod.get('name', '?')} ({pod.get('desiredStatus', '?')})")

    response = input(f"\nStop ALL {len(pods)} pods? (y/n): ").strip().lower()
    if response != "y":
        print("Cancelled.")
        return

    for pod in pods:
        pid = pod.get("id")
        try:
            runpod.stop_pod(pid)
            runpod.terminate_pod(pid)
            print(f"  Stopped + terminated {pid}")
        except Exception as e:
            print(f"  Failed {pid}: {e}")


def cmd_budget(args):
    """Show budget tracking and cost estimates."""
    print(f"Budget: {BUDGET_EUR:.2f}")
    print()

    if COST_FILE.exists():
        costs = json.loads(COST_FILE.read_text())
        pods = costs.get("pods", {})
        if pods:
            print(f"{'Pod ID':<20} {'GPU':<20} {'Hours':>8} {'Cost EUR':>10}")
            print("-" * 60)
            for pid, info in pods.items():
                print(f"{pid:<20} {info['gpu']:<20} {info['hours']:>7.1f}h {info['cost_eur']:>9.2f}")

            print("-" * 60)
            print(f"{'Total:':<20} {'':<20} {'':<8} {costs.get('total_eur', 0):>9.2f}")
            print(f"{'Remaining:':<20} {'':<20} {'':<8} {costs.get('remaining_eur', BUDGET_EUR):>9.2f}")
        else:
            print("No recorded costs yet.")
    else:
        print("No recorded costs yet.")

    # Estimate what we can do with remaining budget
    remaining = BUDGET_EUR
    if COST_FILE.exists():
        costs = json.loads(COST_FILE.read_text())
        remaining = costs.get("remaining_eur", BUDGET_EUR)

    print(f"\n--- What you can run with {remaining:.2f} ---")
    print(f"  4090 Community @ $0.34/hr ({0.34 * USD_TO_EUR:.2f}/hr):")
    hours_4090 = remaining / (0.34 * USD_TO_EUR)
    print(f"    {hours_4090:.0f} GPU-hours")
    print(f"    ~{hours_4090 / 3:.0f} training runs (est 3h each @ 10M steps)")

    print(f"\n  4090 Spot @ $0.20/hr ({0.20 * USD_TO_EUR:.2f}/hr):")
    hours_spot = remaining / (0.20 * USD_TO_EUR)
    print(f"    {hours_spot:.0f} GPU-hours")
    print(f"    ~{hours_spot / 3:.0f} training runs (cheapest, may be interrupted)")

    print(f"\n  A100 Community @ ~$1.04/hr ({1.04 * USD_TO_EUR:.2f}/hr):")
    hours_a100 = remaining / (1.04 * USD_TO_EUR)
    print(f"    {hours_a100:.0f} GPU-hours")
    print(f"    ~{hours_a100 / 2:.0f} training runs (est 2h each, faster GPU)")


def cmd_gpus(args):
    """List available GPU types with pricing (queries each GPU individually for price data)."""
    runpod = init_runpod()
    gpu_list = runpod.get_gpus()

    print(f"{'GPU':<35} {'VRAM':>8} {'Secure $/hr':>12} {'Community':>12} {'Spot':>12}")
    print("-" * 82)

    priced = []
    for gpu_summary in gpu_list:
        gpu_id = gpu_summary.get("id", "")
        try:
            gpu = runpod.get_gpu(gpu_id)
        except Exception:
            gpu = gpu_summary

        name = gpu.get("displayName", "?")
        mem = gpu.get("memoryInGb", "?")
        secure = gpu.get("securePrice")
        community = gpu.get("communityPrice")
        lowest = gpu.get("lowestPrice")
        spot = lowest.get("minimumBidPrice") if isinstance(lowest, dict) else None

        secure_str = f"${secure:.2f}" if secure else "—"
        comm_str = f"${community:.2f}" if community else "—"
        spot_str = f"${spot:.2f}" if spot else "—"

        sort_key = community or secure or 999
        priced.append((sort_key, f"{name:<35} {mem:>6} GB {secure_str:>12} {comm_str:>12} {spot_str:>12}"))

    for _, line in sorted(priced):
        print(line)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="RunPod GPU Pod Manager for Grid Tactics training",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", help="Command")

    # launch
    p = sub.add_parser("launch", help="Launch a single training pod")
    p.add_argument("--gpu", default="4090", help="GPU type (default: 4090)")
    p.add_argument("--steps", default="10000000", help="Training steps (e.g., 10M, 5000000)")
    p.add_argument("--envs", type=int, default=16, help="Parallel envs (default: 16)")
    p.add_argument("--method", default="default", help="Training method preset")
    p.add_argument("--seed", type=int, default=42, help="Random seed")

    # experiment
    p = sub.add_parser("experiment", help="Launch multi-method experiment suite")
    p.add_argument("--steps", default="10000000", help="Steps per experiment")

    # list
    sub.add_parser("list", help="List all active pods")

    # status
    p = sub.add_parser("status", help="Detailed pod status")
    p.add_argument("pod_id", help="Pod ID")

    # gpu
    p = sub.add_parser("gpu", help="Check GPU utilization via SSH")
    p.add_argument("pod_id", help="Pod ID")

    # logs
    p = sub.add_parser("logs", help="Tail training logs")
    p.add_argument("pod_id", help="Pod ID")
    p.add_argument("--lines", type=int, default=50, help="Number of lines")

    # download
    p = sub.add_parser("download", help="Download results from pod")
    p.add_argument("pod_id", help="Pod ID")
    p.add_argument("--dest", default=".", help="Destination directory")

    # stop
    p = sub.add_parser("stop", help="Stop and terminate a pod")
    p.add_argument("pod_id", help="Pod ID")

    # stop-all
    sub.add_parser("stop-all", help="Stop all active pods")

    # budget
    sub.add_parser("budget", help="Show cost tracking and budget")

    # gpus
    sub.add_parser("gpus", help="List available GPU types and pricing")

    args = parser.parse_args()

    commands = {
        "launch": cmd_launch,
        "experiment": cmd_experiment,
        "list": cmd_list,
        "status": cmd_status,
        "gpu": cmd_gpu,
        "logs": cmd_logs,
        "download": cmd_download,
        "stop": cmd_stop,
        "stop-all": cmd_stop_all,
        "budget": cmd_budget,
        "gpus": cmd_gpus,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
