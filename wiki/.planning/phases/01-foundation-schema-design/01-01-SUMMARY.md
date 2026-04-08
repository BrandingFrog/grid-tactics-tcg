---
phase: 01-foundation-schema-design
plan: 01
subsystem: wiki-infrastructure
tags: [docker, docker-compose, mediawiki, taqasta, mariadb, redis, semantic-mediawiki]
requires: []
provides:
  - local-dev-stack
  - mediawiki-schema-baseline
  - compose-topology-template-for-railway
affects:
  - 01-02  # extension enablement builds on this stack
  - 01-03  # SMW schema work needs a running wiki
  - 01-04  # templates/forms need the wiki online
  - 02-*   # Railway deploy mirrors this topology
tech-stack:
  added:
    - "ghcr.io/wikiteq/taqasta:latest (MediaWiki 1.43.5 + SMW + PageForms + Scribunto)"
    - "mariadb:10.11"
    - "redis:7-alpine"
  patterns:
    - "env-var-driven compose via .env file (single source of config)"
    - "per-service named volumes (Railway-compatible: each service owns its own volume)"
    - "docker-entrypoint-initdb.d SQL for deterministic DB user provisioning"
key-files:
  created:
    - wiki/docker-compose.yml
    - wiki/.env.example
    - wiki/.gitignore
    - wiki/Makefile
    - wiki/db-init/01-create-wiki-user.sql
  modified:
    - wiki/README.md
decisions:
  - "Use Taqasta (wikiteq/taqasta) as the MediaWiki base image — matches Railway's official template, includes SMW/PageForms/Scribunto/CategoryTree preinstalled."
  - "MW_DB_INSTALLDB_USER == MW_DB_USER (wiki). Installer detects installer==runtime user and skips its buggy CREATE USER/GRANT phase."
  - "Wiki DB user is pre-created via db-init SQL, not via MARIADB_USER/PASSWORD, to avoid racing with the MediaWiki installer."
  - "Each service has its own named volume (mw_data, db_data, redis_data) to mirror Railway's per-service volume constraint."
  - "MW_SECRET_KEY dev placeholder is 32+ chars; documented in README troubleshooting as the #1 first-boot failure mode."
metrics:
  duration: "~25 minutes (including image pulls and three debug iterations)"
  completed: "2026-04-07"
  tasks_total: 3
  tasks_completed: 3
  commits: 3
---

# Phase 1 Plan 1: docker-compose skeleton Summary

**One-liner:** 3-service Taqasta stack (MediaWiki + MariaDB + Redis) boots locally via `make dev`, reachable at http://localhost:8080, with deterministic first-boot via pre-seeded DB user.

## What Was Built

A reproducible local development environment for the Grid Tactics Wiki that matches the production Railway topology:

- **`wiki/docker-compose.yml`** — 3 services (`mediawiki`, `db`, `redis`) on a shared default network, env-var driven via `env_file: .env`, each with its own named volume.
- **`wiki/.env.example`** — All tunables with dev-safe defaults; designer copies to `.env`, which is git-ignored.
- **`wiki/.gitignore`** — Excludes `.env`, `*.log`, `__pycache__/`.
- **`wiki/Makefile`** — `make dev` / `down` / `logs` / `ps` / `nuke`. `dev` auto-creates `.env` on first run.
- **`wiki/README.md`** — Local Dev Quickstart, Services table, Environment section, Commands table, Troubleshooting section.
- **`wiki/db-init/01-create-wiki-user.sql`** — Mounted into MariaDB's `docker-entrypoint-initdb.d`, pre-creates the `wiki` database and `'wiki'@'%'` user before Taqasta's installer runs.

## Verified Behavior

- `docker compose config` validates with no errors.
- `docker compose up -d` brings all 3 services to "Up" state (verified via `docker compose ps` showing `"State":"running"` count = 3).
- `curl http://localhost:8080` returns HTTP 301 redirecting to the Grid Tactics Wiki Main Page; the rendered page (16,683 bytes) contains `Grid Tactics`, `MediaWiki`, and `Main Page`.
- Named volumes `wiki_mw_data`, `wiki_db_data`, `wiki_redis_data` exist in `docker volume ls`.
- Semantic MediaWiki auto-imports its default vocabulary (smw.vocab.json, smw.groups.json) during first boot, proving the SMW extension loaded cleanly.

## Image Digests (first-boot reference)

| Service    | Repository                 | Tag        | Image ID        | Size   |
|------------|----------------------------|------------|-----------------|--------|
| mediawiki  | `ghcr.io/wikiteq/taqasta`  | `latest`   | `bbd102f890a5`  | 958 MB |
| db         | `mariadb`                  | `10.11`    | `2f2b6bbcdbaf`  | 107 MB |
| redis      | `redis`                    | `7-alpine` | `8b81dd37ff02`  | 17 MB  |

Total first-pull footprint: ~1.1 GB.

## Deviations from Plan

### Rule 2 — Missing critical functionality: first-boot DB provisioning

The plan assumed a clean 3-service stack would boot Taqasta successfully with only `MW_DB_SERVER`/`MW_DB_NAME`/`MW_DB_USER`/`MW_DB_PASS`. In practice, Taqasta's maintenance entrypoint invokes `maintenance/install.php` which **aborts every time** with:

```
Granting permission to user "wiki" failed:
Error 1133: Can't find any matching row in the user table
Query: GRANT ALL PRIVILEGES ON `wiki`.* TO 'wiki'@'db'
```

This is a known MediaWiki installer quirk on Docker networks: the installer's internal `CREATE USER` uses a different host specifier than its subsequent `GRANT`. Even pre-creating `'wiki'@'db'` via init SQL did not help — MariaDB's GRANT lookup still returned error 1133 against the row that visibly existed in `mysql.user`.

**Three-part fix (all committed atomically in `1c6b958`):**

1. **Added `wiki/db-init/01-create-wiki-user.sql`** — Creates the `wiki` database and `'wiki'@'%'` user with full privileges, mounted into `db:/docker-entrypoint-initdb.d:ro`. This is mandatory; without pre-provisioning, Taqasta's installer cannot proceed.
2. **Removed `MARIADB_USER` / `MARIADB_PASSWORD`** from the `db` service env. The MariaDB entrypoint's own user-creation logic races with our init SQL and produces a stale user row that blocks the installer.
3. **Changed `MW_DB_INSTALLDB_USER` / `MW_DB_INSTALLDB_PASS`** from `root` / `MARIADB_ROOT_PASSWORD` to `MW_DB_USER` / `MW_DB_PASS` (the wiki user itself). This makes MediaWiki's installer detect "installer identity == runtime identity" and **skip the buggy `CREATE USER` / `GRANT` phase entirely**. The wiki user already has all privileges it needs on `wiki.*` from the init SQL, so install.php proceeds straight to schema creation.

**Why this matters for later phases:** The same fix will be required in Phase 2 (Railway deployment). Railway's managed MariaDB addon will need either an equivalent pre-provisioning step or `MW_DB_INSTALLDB_USER` pointed at the runtime wiki user. Do NOT set it to the root/admin credential on Railway.

### Rule 2 — Added `MW_DB_INSTALLDB_USER` / `MW_DB_INSTALLDB_PASS` env vars to compose

These were not in the original plan's env var list but are **required** by Taqasta's entrypoint (`run-maintenance-scripts.sh` line ~225 errors out with `"Variable MW_DB_INSTALLDB_PASS must be defined"` if missing). Added to docker-compose.yml and documented in `.env.example`.

## Env Var Names Changed from Research

- **Added:** `MW_DB_INSTALLDB_USER`, `MW_DB_INSTALLDB_PASS` (required by Taqasta, not mentioned in RESEARCH.md §4).
- **Removed:** `MARIADB_USER`, `MARIADB_PASSWORD` (conflicts with db-init SQL; wiki user is provisioned via init script instead).

All other env vars match RESEARCH.md §4 exactly.

## Command Sequence That Worked for First Boot

```bash
cd wiki
cp .env.example .env     # first time only (make dev does this too)
docker compose up -d
# wait ~60 seconds for Taqasta to run installer + SMW vocab import
curl http://localhost:8080   # HTTP 301 -> Main_Page
```

`docker compose ps` should show all 3 services "Up"; `wiki_mediawiki` may show `(health: starting)` for 1-2 minutes while the healthcheck settles — this is cosmetic, the site is already serving.

## Next Phase Readiness

**Ready for 01-02** (extension configuration): the wiki is live, the `wiki` volume persists LocalSettings.php, and SMW is already bootstrapped with its default vocabulary.

**Watch items for downstream plans:**
- The installer-skip trick (`MW_DB_INSTALLDB_USER == MW_DB_USER`) must be preserved in Railway deploy. Flag for Phase 2.
- `db-init/01-create-wiki-user.sql` hardcodes `wikipass` to match `.env.example`. If a designer changes `MW_DB_PASS` in `.env` without editing this file, first boot will fail with an auth error. Documented in README troubleshooting will be needed if this bites.
- Healthcheck status lingers at "starting" even after the site serves; consider adjusting the compose healthcheck in a later polish pass.

## Commits

| # | Hash      | Message                                                    |
|---|-----------|------------------------------------------------------------|
| 1 | `ea6582f` | feat(wiki-01-01): add docker-compose 3-service stack       |
| 2 | `78c4f11` | feat(wiki-01-01): add Makefile and dev quickstart README   |
| 3 | `1c6b958` | fix(wiki-01-01): unblock Taqasta first-boot install on MariaDB |
