# Deployment

Grid Tactics has four independent deployment boundaries. Keep their entrypoints and configuration local to each boundary.

## PvP server: Railway

Railway deploys the root application from `master`:

- `Procfile` starts `python pvp_server.py`.
- `railway.json` uses the same start command and restart policy.
- `nixpacks.toml` configures the build environment.
- `pvp_server.py` is a thin root shim that imports the server package from `src/grid_tactics/`.

Local smoke test:

```powershell
$env:PYTHONPATH = "src"
python pvp_server.py
```

Then open `http://127.0.0.1:5000/` and verify that the lobby loads.

Rejected gameplay actions are written as JSON Lines to
`logs/illegal-actions.jsonl` by default. Railway's ordinary container
filesystem is replaced on deploy; set `GT_SERVER_LOG_DIR` to a mounted volume
directory, or `GT_ILLEGAL_ACTION_LOG_PATH` to a file on that volume, when the
history must survive deploys. Logs rotate at 5 MiB with three backups by
default; tune those limits with `GT_DEBUG_LOG_MAX_BYTES` and
`GT_DEBUG_LOG_BACKUP_COUNT`. The same sanitized records also go to the process
log. Records contain a process-salted room reference and normalized action fields, not
session tokens, player names, hands, decks, or arbitrary client payload keys.

## Training jobs: RunPod

`scripts/manage_pods.py` builds an in-memory archive containing the Python package, card data, and cloud-training scripts. It uploads that archive and starts `scripts/cloud_train.py` with `PYTHONPATH=/workspace/src`.

```powershell
python scripts/manage_pods.py --help
python scripts/manage_pods.py gpus
python scripts/manage_pods.py launch --gpu 4090
```

RunPod commands require `RUNPOD_API_KEY` in the environment or the uncommitted root `.env`. Cost tracking is written to the ignored root `.pod_costs.json`.

## Analytics dashboard: Vercel

`web-dashboard/` is a separate static application with its own configuration. It reads analytics from Supabase in the browser and does not use the Railway Flask process.

## Game wiki

`wiki/` is separately deployable and owns its own package and build configuration.
