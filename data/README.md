# Game data

- `cards/` contains one authoritative JSON definition per card.
- `GLOSSARY.md` defines player-facing keywords.
- `sandbox_saves/` contains local sandbox slots and is ignored except for its placeholder.
- `checkpoints/`, `cloud_dbs/`, `tb_logs/`, model files, and local databases are generated training data and should not be committed unless deliberately curated.

Load cards through `CardLibrary.from_directory()` rather than reading individual files in game code.

Maintained rules and design documents live in [`../docs/`](../docs/README.md), including the authoritative [turn structure](../docs/rules/turn-structure.md).
