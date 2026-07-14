# Project scripts

This folder contains developer-operated utilities rather than importable application code.

- `generate_card_thumbs.py` prepares card thumbnail assets.
- `supabase_decks.sql` defines cloud deck-storage structures.
- `debug_sandbox_*.py` scripts reproduce sandbox timing and reaction issues.
- `verify_sandbox_*.py` scripts check targeted sandbox fixes.

Generated `*_output.txt` files are ignored. Scripts that become required by deployment should gain tests or be promoted to a documented root entrypoint.
