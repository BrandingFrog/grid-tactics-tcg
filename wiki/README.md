# Grid Tactics Wiki

An auto-generated Semantic MediaWiki that mirrors the current state of the [Grid Tactics TCG](../). Cards, keywords, elements, tribes, and patch notes are all projected from the canonical game data (`../data/cards/*.json`, `../data/GLOSSARY.md`) via git hooks. Humans never edit card pages directly — the wiki is a read-only projection and patch notes are generated from git diffs on every commit.

## Relationship to the Parent Project

This is a **subproject** of Grid Tactics TCG, living at `wiki/` inside the main repo so sync scripts and git hooks have direct file access to card JSONs and version metadata.

- **Source of truth:** `../data/cards/*.json`, `../data/GLOSSARY.md`, `../src/grid_tactics/enums.py`
- **Version source:** `../src/grid_tactics/server/static/VERSION.json`
- **Art source:** `../src/grid_tactics/server/static/art/*.png`
- **Deployment target:** Railway (alongside the existing grid-tactics game service)

The wiki does **not** replace the `../obsidian/` vault — Obsidian is for manual internal notes; the wiki is the public auto-updated documentation.

## Local Dev Quickstart

```bash
cd wiki
make dev
# open http://localhost:8080
```

First boot takes about **60 seconds** while Taqasta generates `LocalSettings.php`, runs the MediaWiki installer against the MariaDB service, and warms the Redis cache. Subsequent `make dev` runs are near-instant.

## Services

| Service    | Image                            | Port          | Purpose                                   |
|------------|----------------------------------|---------------|-------------------------------------------|
| mediawiki  | `ghcr.io/wikiteq/taqasta:latest` | 8080 (host)   | MediaWiki + SMW + PageForms (Taqasta)     |
| db         | `mariadb:10.11`                  | internal      | Persistent wiki database                  |
| redis      | `redis:7-alpine`                 | internal      | Object cache / session store              |

Each service has its own named Docker volume (`mw_data`, `db_data`, `redis_data`) so data survives `make down`.

## Environment

All secrets and site config live in a `.env` file next to `docker-compose.yml`. The repo ships `.env.example` with dev defaults; copy it:

```bash
cp .env.example .env
```

`.env` is git-ignored. `MW_SECRET_KEY` must be at least 32 characters.

## Commands

| Command       | Description                                                |
|---------------|------------------------------------------------------------|
| `make dev`    | Create `.env` if missing and bring the stack up detached.  |
| `make down`   | Stop services (volumes preserved).                         |
| `make logs`   | Tail the mediawiki container log.                          |
| `make ps`     | Show service status.                                       |
| `make nuke`   | **Destroy all volumes** — wipes wiki data. 5s warning.     |

## Troubleshooting

- **Port 8080 already in use:** edit the `mediawiki.ports` mapping in `docker-compose.yml` (e.g. `"8081:80"`).
- **mediawiki crash-loops on first boot:** `make logs` and check `MW_SECRET_KEY` — it must be **at least 32 characters** or MediaWiki refuses to start.
- **DB connection errors in the first ~30s:** Taqasta retries automatically while MariaDB finishes initializing. Give it up to 90 seconds before investigating.
- **Stale data after schema changes:** `make nuke && make dev` resets everything.

## Planning Docs

All GSD planning artifacts live in `.planning/`:

- [`.planning/PROJECT.md`](.planning/PROJECT.md) — vision, core value, tech stack, constraints
- [`.planning/REQUIREMENTS.md`](.planning/REQUIREMENTS.md) — numbered requirements by category
- [`.planning/ROADMAP.md`](.planning/ROADMAP.md) — 9 phases from foundation to launch polish
- [`.planning/STATE.md`](.planning/STATE.md) — current position and accumulated context

## Automation Flow (future phases)

1. Developer edits `../data/cards/some_card.json` and commits.
2. `.githooks/post-commit` detects the change and runs `wiki/sync/sync_wiki.py`.
3. Sync script diffs against `wiki/.sync_state.json`, upserts changed card pages via the MediaWiki API, and writes a `Patch:X.Y.Z` page using the version in `VERSION.json`.
4. Running the hook twice is a no-op (idempotent).
