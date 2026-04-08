---
milestone: v1.0
status: in-progress
stopped_at: completed_01-01
last_updated: 2026-04-07
progress:
  phase: 1
  phase_name: Foundation & Schema Design
  plan: 01
  phases_total: 9
  phases_completed: 0
  plans_completed_in_phase: 1
  plans_total_in_phase: 4
  percent: 3
---

# Project State — Grid Tactics Wiki

## Project Reference

See: `.planning/PROJECT.md`

**Core value:** Living, semantically-queryable knowledge base that auto-mirrors Grid Tactics card and mechanic state via git hooks.
**Current focus:** Phase 1 — Foundation & Schema Design

## Current Position

Phase: 1 of 9 (Foundation & Schema Design)
Plan: 01 of 4 complete — docker-compose skeleton
Status: In progress
Last activity: 2026-04-07 — Completed 01-01-PLAN.md (3-service Taqasta stack boots locally)

Progress: `█░░░░░░░░░` 3%

## Performance Metrics

**Velocity:**
- Total plans completed: 1
- Average duration: ~25 min/plan

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|---|---|---|---|
| 1 — Foundation & Schema Design | 1 | 4 | ~25 min |

## Accumulated Context

### Decisions

- Tech stack locked: MediaWiki + SMW, MariaDB, Docker, Railway, Python `mwclient` (tentative), git post-commit hook.
- JSON in `data/cards/*.json` is canonical; wiki is a projection, never source of truth.
- Wiki lives as a subproject at `wiki/` inside the grid-tactics repo for direct file access.
- Public read, bot-only write. No user accounts, no forums.
- **[01-01]** MediaWiki base image: `ghcr.io/wikiteq/taqasta:latest` (matches Railway template; SMW/PageForms/Scribunto/CategoryTree pre-bundled).
- **[01-01]** Env-var-driven compose via `.env` file; `.env` is git-ignored, `.env.example` committed.
- **[01-01]** Each service has its own named volume (`mw_data`, `db_data`, `redis_data`) to mirror Railway's per-service volume constraint.
- **[01-01]** Wiki DB user (`wiki@%`) is pre-created via `db-init/01-create-wiki-user.sql` mounted into MariaDB's `docker-entrypoint-initdb.d`. `MARIADB_USER/PASSWORD` intentionally NOT set to avoid racing with init SQL.
- **[01-01]** `MW_DB_INSTALLDB_USER == MW_DB_USER` (same credential as runtime). This makes MediaWiki's installer detect installer==runtime and skip its buggy `CREATE USER`/`GRANT` step that otherwise aborts first boot with MariaDB error 1133.

### Pending Todos

- Phase 1 remaining plans: 01-02, 01-03, 01-04
- Phase 2 watch item: the `MW_DB_INSTALLDB_USER == MW_DB_USER` trick and the db-init SQL must be preserved in the Railway deploy — do NOT point installer at root credentials.

### Blockers/Concerns

- **[01-01 minor]** `wiki/db-init/01-create-wiki-user.sql` hardcodes `wikipass` to match `.env.example`. If a designer changes `MW_DB_PASS` in `.env` without editing this file, first boot will fail with auth error. Consider templating in a future polish pass.
- **[01-01 cosmetic]** `wiki_mediawiki` compose healthcheck lingers in `(health: starting)` even after the site serves HTTP 301. Not blocking — revisit in polish.

## Session Continuity

Last session: 2026-04-07
Stopped at: Completed 01-01-PLAN.md — 3-service stack running locally at http://localhost:8080
Resume file: None (ready for 01-02)
