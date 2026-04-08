---
milestone: v1.0
status: in-progress
stopped_at: completed_01-02
last_updated: 2026-04-07
progress:
  phase: 1
  phase_name: Foundation & Schema Design
  plan: 02
  phases_total: 9
  phases_completed: 0
  plans_completed_in_phase: 2
  plans_total_in_phase: 4
  percent: 6
---

# Project State — Grid Tactics Wiki

## Project Reference

See: `.planning/PROJECT.md`

**Core value:** Living, semantically-queryable knowledge base that auto-mirrors Grid Tactics card and mechanic state via git hooks.
**Current focus:** Phase 1 — Foundation & Schema Design

## Current Position

Phase: 1 of 9 (Foundation & Schema Design)
Plan: 02 of 4 complete — mwclient bot auth + SMW verify
Status: In progress
Last activity: 2026-04-07 — Completed 01-02-PLAN.md (wiki/sync package, SMW 6.0.1 confirmed, bot Admin@phase1 authenticated)

Progress: `██░░░░░░░░` 6%

## Performance Metrics

**Velocity:**
- Total plans completed: 2
- Average duration: ~20 min/plan

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|---|---|---|---|
| 1 — Foundation & Schema Design | 2 | 4 | ~20 min |

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
- **[01-02]** mwclient Site path is `/w/` on this Taqasta build (confirmed by curling `/w/api.php?action=query&meta=siteinfo`). Centralized in `wiki/sync/client.py::get_site()`.
- **[01-02]** Bot credential format is `Admin@phase1` (capital A — the admin DB row is `Admin`, lowercase `admin` makes `createBotPassword.php` fail silently with exit 1).
- **[01-02]** BotPassword grants chosen: `basic,highvolume,editpage,createeditmovepage`. Sufficient for schema bootstrap (01-03) and template uploads (01-04); widen in later plans if needed.
- **[01-02]** `wiki/pyproject.toml` relaxed to `requires-python = ">=3.11"` for the wiki subproject (ambient interpreter is 3.11.9). The root CLAUDE.md's >=3.12 target applies to the RL engine, not the wiki bot.
- **[01-02]** `wiki/sync/verify_smw.py` is the canonical smoke test — every downstream sync plan should run `python -m sync.verify_smw` as a gate.

### Pending Todos

- Phase 1 remaining plans: 01-03 (SMW schema bootstrap), 01-04 (Template:Card + forms)
- Phase 2 watch item: the `MW_DB_INSTALLDB_USER == MW_DB_USER` trick and the db-init SQL must be preserved in the Railway deploy — do NOT point installer at root credentials.
- Phase 2 watch item: BotPassword must be recreated on the Railway instance (credential lives in the wiki DB, doesn't port across). Automate via `createBotPassword.php` one-shot after deploy.
- Phase 1 open checkpoint: 01-02 Task 3 (human-verify Special:Version + bot login UI) deferred like 14.x posture — the `verify_smw.py` smoke test covers the same ground headlessly.

### Blockers/Concerns

- **[01-01 minor]** `wiki/db-init/01-create-wiki-user.sql` hardcodes `wikipass` to match `.env.example`. If a designer changes `MW_DB_PASS` in `.env` without editing this file, first boot will fail with auth error. Consider templating in a future polish pass.
- **[01-01 cosmetic]** `wiki_mediawiki` compose healthcheck lingers in `(health: starting)` even after the site serves HTTP 301. Not blocking — revisit in polish.

## Session Continuity

Last session: 2026-04-07
Stopped at: Completed 01-02-PLAN.md — wiki/sync bot authenticated, SMW 6.0.1 verified
Resume file: None (ready for 01-03 SMW schema bootstrap)
