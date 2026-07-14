# Deployment

## PvP Server — Railway
- `pvp_server.py` entry, `Procfile`, `railway.json`, `nixpacks.toml`
- Hosts the Flask-SocketIO [[Server]] for live PvP.

## RL Training — RunPod
- `scripts/manage_pods.py` archives the required source and uploads it directly to a pod.
- `scripts/cloud_train.py` is the remote training entrypoint.
- Pods stream metrics to Supabase.

## Data — Supabase
- `training_runs`, `training_snapshots`, `card_stats`, `game_results`
- REST writes via `supabase-py`
- Realtime reads from the dashboard

## Dashboard — Vercel
- `web-dashboard/` static site
- Chart.js + supabase-js with anon key
