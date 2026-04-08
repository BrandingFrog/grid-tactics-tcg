# Grid Tactics Wiki

An auto-generated Semantic MediaWiki that mirrors the current state of the [Grid Tactics TCG](../). Cards, keywords, elements, tribes, and patch notes are all projected from the canonical game data (`../data/cards/*.json`, `../data/GLOSSARY.md`) via git hooks. Humans never edit card pages directly — the wiki is a read-only projection and patch notes are generated from git diffs on every commit.

## Relationship to the Parent Project

This is a **subproject** of Grid Tactics TCG, living at `wiki/` inside the main repo so sync scripts and git hooks have direct file access to card JSONs and version metadata.

- **Source of truth:** `../data/cards/*.json`, `../data/GLOSSARY.md`, `../src/grid_tactics/enums.py`
- **Version source:** `../src/grid_tactics/server/static/VERSION.json`
- **Art source:** `../src/grid_tactics/server/static/art/*.png`
- **Deployment target:** Railway (alongside the existing grid-tactics game service)

The wiki does **not** replace the `../obsidian/` vault — Obsidian is for manual internal notes; the wiki is the public auto-updated documentation.

## Planning Docs

All GSD planning artifacts live in `.planning/`:

- [`.planning/PROJECT.md`](.planning/PROJECT.md) — vision, core value, tech stack, constraints
- [`.planning/REQUIREMENTS.md`](.planning/REQUIREMENTS.md) — numbered requirements by category (DEPLOY, WIKI, CARD, SEMANTIC, PATCH, AUTO, POLISH)
- [`.planning/ROADMAP.md`](.planning/ROADMAP.md) — 9 phases from foundation to launch polish
- [`.planning/STATE.md`](.planning/STATE.md) — current position and accumulated context
- [`.planning/config.json`](.planning/config.json) — GSD workflow config

## Local Development (once Phase 1 lands)

```bash
cd wiki
docker compose up       # brings up MediaWiki + MariaDB locally
# open http://localhost:8080
```

Then, from the repo root, run the sync script to populate local pages:

```bash
python wiki/sync/sync_wiki.py --all-cards --target local
```

## Automation Flow

1. Developer edits `../data/cards/some_card.json` and commits.
2. `.githooks/post-commit` detects the change and runs `wiki/sync/sync_wiki.py`.
3. Sync script diffs against `wiki/.sync_state.json`, upserts changed card pages via the MediaWiki API, and writes a `Patch:X.Y.Z` page using the version in `VERSION.json`.
4. Running the hook twice is a no-op (idempotent).

## Status

**Phase 1 — Foundation & Schema Design** (not started). Run `/gsd:plan-phase 1` from this directory to generate the execution plan.
