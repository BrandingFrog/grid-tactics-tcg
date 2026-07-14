# Project scripts

This folder contains developer-operated utilities rather than importable application code. Run commands from the repository root; the maintained scripts resolve repository paths themselves.

- `dashboard.py` serves the local training dashboard.
- `watch_game.py` renders an AI-vs-AI training game in the terminal.
- `stats.py` and `check_stats.py` inspect local or cloud training results.
- `tensor_train.py` and `cloud_train.py` are experimental training entrypoints.
- `manage_pods.py` packages the required source files and manages RunPod jobs.
- `generate_card_thumbs.py` prepares card thumbnail assets.
- `supabase_decks.sql` defines cloud deck-storage structures.
- `windows/` contains convenience launchers for Windows development.

Generated `*_output.txt` files are ignored. The Railway application entrypoint remains at repository root because `Procfile` and `railway.json` call it directly.
