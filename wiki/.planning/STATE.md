---
milestone: v1.0
status: phase-4-in-progress
stopped_at: completed_04-01
last_updated: 2026-04-09
progress:
  phase: 4
  phase_name: Taxonomy Pages
  plan: 01
  phases_total: 9
  phases_completed: 3
  plans_completed_in_phase: 1
  plans_total_in_phase: 2
  percent: 37
---

# Project State — Grid Tactics Wiki

## Project Reference

See: `.planning/PROJECT.md`

**Core value:** Living, semantically-queryable knowledge base that auto-mirrors Grid Tactics card and mechanic state via git hooks.
**Current focus:** Phase 4 in progress — Taxonomy Pages (element + tribe pages live, keywords/rules next)

## Current Position

Phase: 4 of 9 (Taxonomy Pages)
Plan: 01 of 2 complete — 21 taxonomy pages (7 elements + 14 tribes) synced to live wiki.
Status: In progress. Plan 02 (keywords + rules pages) next.
Last activity: 2026-04-09 — Completed 04-01 (sync_taxonomy.py + 21 taxonomy pages live)

Progress: `████░░░░░░` 37%

## Performance Metrics

**Velocity:**
- Total plans completed: 4
- Average duration: ~18 min/plan

**By Phase:**

| Phase | Plans | Total | Avg/Plan | Status |
|---|---|---|---|---|
| 1 — Foundation & Schema Design | 4 | 4 | ~18 min | complete |

## Accumulated Context

### Decisions

- **[03-01]** Keywords derived from JSON structure, never hard-coded per card. `derive_keywords()` inspects `card_type`, `range`, `effects`, `activated_ability`, `transform_options`, `tutor_target`, `promote_target`, `summon_sacrifice_tribe`, `react_condition`, `react_effect`.
- **[03-01]** Cross-links use `[[Card:Display Name|Display Name]]` format via name_map lookup with title-case fallback.
- **[03-01]** `react_effect` field (separate from `effects[]` array) is processed for both keywords and rules text (affects Dark Sentinel, Surgefed Sparkbot).
- **[03-02]** CardBack.png is a solid #1a1a1a (280x400) dark gray PNG matching the card template background color. Serves as art fallback.
- **[03-02]** SMW ask results on Railway mediawiki:1.42 return OrderedDict values (not plain numbers). Use `_smw_val()` helper pattern to extract `fulltext`.
- **[03-02]** After template changes, existing pages need purge + null edit to force re-categorization (MediaWiki job queue may be slow).
- **[03-03]** Card:Rat cross-link target is actually Card:Common Rat (the JSON `name` field is "Common Rat"). All cross-links resolve correctly.
- **[03-03]** MediaWiki `fileexists-no-change` on duplicate art uploads treated as "unchanged" for idempotent re-runs.
- **[04-01]** Element and tribe page titles are bare names (Fire, Rat), not namespaced. SMW ask queries resolve correctly.
- **[04-01]** `upsert_taxonomy_pages()` is a generic reusable function for any taxonomy page type (elements, tribes, keywords, rules).
- **[04-01]** Mage/Rat tribe page works with slash in title (MediaWiki subpage behavior is acceptable here).
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
- **[01-02]** BotPassword grants chosen: `basic,highvolume,editpage,createeditmovepage`. Sufficient for schema bootstrap (01-03) and template uploads (01-04); widen in Phase 3 when card art upload begins (need `upload` grant).
- **[01-02]** `wiki/pyproject.toml` relaxed to `requires-python = ">=3.11"` for the wiki subproject (ambient interpreter is 3.11.9). The root CLAUDE.md's >=3.12 target applies to the RL engine, not the wiki bot.
- **[01-02]** `wiki/sync/verify_smw.py` is the canonical smoke test — every downstream sync plan should run `python -m sync.verify_smw` as a gate.
- **[01-03]** Property naming: **CamelCase** (Name, CardType, Cost, HasEffect), not snake_case. Matches SMW community convention; diverges from roadmap examples but roadmap semantics are preserved.
- **[01-03]** `wiki/sync/schema.py` is the single source of truth — 20 core properties + 5 effect subobject fields. Any new property added in later phases goes here first, then `bootstrap_schema.py` re-runs.
- **[01-03]** Idempotency pattern: compare `page.text().rstrip() == expected.rstrip()` because MediaWiki strips the trailing newline on storage. Exact equality would re-edit every page on every run. This pattern is now reused by `bootstrap_template.py` and `create_sample_card.py`.
- **[01-03]** SMW change-propagation lock (`smw-change-propagation-protection`) is expected on legitimate schema expansions — `bootstrap_schema._edit_with_retry()` retries with linear backoff up to 6 times.
- **[01-03]** `verify_schema.py`'s `ask([[Property:+]])` cross-check is a **soft** signal on SMW 6.0.1 (returns nothing on this build); the page-level `[[Has type::X]]` marker check is the authoritative gate.
- **[01-03]** `CardType`/`Element` are SMW `Page` type with `[[Allows value::X]]` constraints. SMW does NOT auto-create target pages — Phase 3 card sync must create stub pages (Minion, Wood, ...) or accept red-link dereferences.
- **[01-04]** `wiki/sync/templates/` is the canonical on-disk home for MediaWiki template wikitext. `.wiki` files are plain text, version-controlled, and pushed to the wiki by a paired `bootstrap_*.py` script.
- **[01-04]** Template:Card emits infobox HTML AND SMW annotations in a single `<includeonly>` pass. Every SMW property annotation except `Name` is wrapped in `{{#if:...}}` so missing params don't pollute the store with empty values. `Name` falls back to `{{PAGENAME}}`.
- **[01-04]** Keyword multi-valuedness is implemented via `#arraymap` (Extension:Arrays, confirmed present in the Taqasta bundle) splitting a comma-separated `keywords=` param into repeated `[[Keyword::X]]` calls.
- **[01-04]** `mwclient.Site.ask()` yields FLAT dicts shaped `{"fulltext": "...", "printouts": {"Cost": [4], ...}}`, NOT nested-by-title. Any future verification code that reads ask results must use `result["fulltext"]` and `result["printouts"]`, not `result.items()`.
- **[01-04]** Sample cards source values from the real `data/cards/*.json`, not from illustrative values in plan text. This makes Phase 1's sample an honest dry-run of Phase 3's sync path.
- **[01-04]** Rules-text synthesis for cards without a `rules_text` field: derive from `activated_ability` or `effects` blocks. Phase 3 should formalize this as a dedicated helper in `sync_cards.py`.
- **[01-04]** Subobject emission (`{{#subobject:}}`) intentionally deferred to Phase 3 — Phase 1 sample proves basic property annotations only.

### Pending Todos

- **Phase 1 is complete.** Next action: Phase 2 (Railway deploy).
- Phase 2 watch item: the `MW_DB_INSTALLDB_USER == MW_DB_USER` trick and the db-init SQL must be preserved in the Railway deploy — do NOT point installer at root credentials.
- Phase 2 watch item: BotPassword must be recreated on the Railway instance (credential lives in the wiki DB, doesn't port across). Automate via `createBotPassword.php` one-shot after deploy.
- Phase 2 watch item: post-deploy bootstrap sequence on Railway must run in order — `bootstrap_schema.py` → `verify_schema.py` → `bootstrap_template.py` → `create_sample_card.py`. All four scripts are idempotent.
- Phase 3 watch item: `CardType`/`Element` Page-type properties with `[[Allows value::X]]` produce red-links until stub pages are created. Decide whether to auto-create stubs or accept red-links.
- Phase 3 watch item: widen BotPassword grants to include `upload` before card art sync begins.
- Phase 3 watch item: ~~formalize rules-text synthesis helper~~ DONE in 03-01: `build_rules_text()` in `sync_cards.py`.
- Phase 1 open checkpoints (deferred in 14.x posture, not blocking):
  - 01-02 Task 3 — visual check of Special:Version + bot login UI
  - 01-04 Task 3 — visual check of Card:Ratchanter infobox + Factbox
  Both are covered headlessly by the automated verification scripts; the user is expected to drop in visually at their convenience.

### Blockers/Concerns

- **[01-01 minor]** `wiki/db-init/01-create-wiki-user.sql` hardcodes `wikipass` to match `.env.example`. If a designer changes `MW_DB_PASS` in `.env` without editing this file, first boot will fail with auth error. Consider templating in a future polish pass.
- **[01-01 cosmetic]** `wiki_mediawiki` compose healthcheck lingers in `(health: starting)` even after the site serves HTTP 301. Not blocking — revisit in polish.
- **[01-04 cosmetic]** `Card:Ratchanter` shows a broken-image placeholder for `File:Ratchanter.png`. Accepted — card art upload is Phase 3.

## Session Continuity

Last session: 2026-04-09
Stopped at: Completed 04-01 — 21 taxonomy pages live (7 elements + 14 tribes). sync_taxonomy.py ready for reuse.
Resume file: None (ready for 04-02)
