---
milestone: v1.0
status: in-progress
stopped_at: completed_01-03
last_updated: 2026-04-07
progress:
  phase: 1
  phase_name: Foundation & Schema Design
  plan: 03
  phases_total: 9
  phases_completed: 0
  plans_completed_in_phase: 3
  plans_total_in_phase: 4
  percent: 8
---

# Project State — Grid Tactics Wiki

## Project Reference

See: `.planning/PROJECT.md`

**Core value:** Living, semantically-queryable knowledge base that auto-mirrors Grid Tactics card and mechanic state via git hooks.
**Current focus:** Phase 1 — Foundation & Schema Design

## Current Position

Phase: 1 of 9 (Foundation & Schema Design)
Plan: 03 of 4 complete — SMW property schema bootstrapped (25 properties live)
Status: In progress
Last activity: 2026-04-07 — Completed 01-03-PLAN.md (schema.py / bootstrap_schema.py / verify_schema.py, 25 Property: pages created, idempotent, verify 25/25 OK)

Progress: `██░░░░░░░░` 8%

## Performance Metrics

**Velocity:**
- Total plans completed: 3
- Average duration: ~20 min/plan

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|---|---|---|---|
| 1 — Foundation & Schema Design | 3 | 4 | ~20 min |

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
- **[01-03]** Property naming: **CamelCase** (Name, CardType, Cost, HasEffect), not snake_case. Matches SMW community convention; diverges from roadmap examples but roadmap semantics are preserved.
- **[01-03]** `wiki/sync/schema.py` is the single source of truth — 20 core properties + 5 effect subobject fields. Any new property added in later phases goes here first, then `bootstrap_schema.py` re-runs.
- **[01-03]** Idempotency pattern: compare `page.text().rstrip() == expected.rstrip()` because MediaWiki strips the trailing newline on storage. Exact equality would re-edit every page on every run.
- **[01-03]** SMW change-propagation lock (`smw-change-propagation-protection`) is expected on legitimate schema expansions — `bootstrap_schema._edit_with_retry()` retries with linear backoff up to 6 times.
- **[01-03]** `verify_schema.py`'s `ask([[Property:+]])` cross-check is a **soft** signal on SMW 6.0.1 (returns nothing on this build); the page-level `[[Has type::X]]` marker check is the authoritative gate.
- **[01-03]** `CardType`/`Element` are SMW `Page` type with `[[Allows value::X]]` constraints. SMW does NOT auto-create target pages — Phase 3 card sync must create stub pages (Minion, Wood, ...) or accept red-link dereferences.

### Pending Todos

- Phase 1 remaining plans: 01-04 (Template:Card + PageForms)
- Phase 2 watch item: the `MW_DB_INSTALLDB_USER == MW_DB_USER` trick and the db-init SQL must be preserved in the Railway deploy — do NOT point installer at root credentials.
- Phase 2 watch item: BotPassword must be recreated on the Railway instance (credential lives in the wiki DB, doesn't port across). Automate via `createBotPassword.php` one-shot after deploy.
- Phase 2 watch item: post-deploy bootstrap sequence on Railway must include `python -m sync.bootstrap_schema` followed by `python -m sync.verify_schema` — SMW schema lives in the wiki DB and does not travel with code.
- Phase 3 watch item: `CardType`/`Element` Page-type properties with `[[Allows value::X]]` produce red-links until stub pages are created. Decide whether to auto-create stubs or accept red-links.
- Phase 1 open checkpoint: 01-02 Task 3 (human-verify Special:Version + bot login UI) deferred like 14.x posture — the `verify_smw.py` smoke test covers the same ground headlessly.

### Blockers/Concerns

- **[01-01 minor]** `wiki/db-init/01-create-wiki-user.sql` hardcodes `wikipass` to match `.env.example`. If a designer changes `MW_DB_PASS` in `.env` without editing this file, first boot will fail with auth error. Consider templating in a future polish pass.
- **[01-01 cosmetic]** `wiki_mediawiki` compose healthcheck lingers in `(health: starting)` even after the site serves HTTP 301. Not blocking — revisit in polish.

## Session Continuity

Last session: 2026-04-07
Stopped at: Completed 01-03-PLAN.md — 25 SMW Property: pages live, bootstrap idempotent, verify 25/25 OK
Resume file: None (ready for 01-04 Template:Card + PageForms)
