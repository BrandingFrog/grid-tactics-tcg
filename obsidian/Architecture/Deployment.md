# Deployment

## PvP Server — Railway
- `pvp_server.py` entry, `Procfile`, `railway.json`, `nixpacks.toml`
- Hosts the Flask-SocketIO [[Server]] for live PvP.

## RL Training — RunPod
- `deploy_runpod.py` uploads tarball to Supabase Storage.
- `start_pod.sh` downloads code, installs deps, runs `tensor_train.py`.
- `manage_pods.py` lifecycle helpers.
- Pods stream metrics to Supabase.

## Data — Supabase
- `training_runs`, `training_snapshots`, `card_stats`, `game_results`
- REST writes via `supabase-py`
- Realtime reads from the dashboard

## Dashboard — Vercel
- `web-dashboard/` static site
- Chart.js + supabase-js with anon key
