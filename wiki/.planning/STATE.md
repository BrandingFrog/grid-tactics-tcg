---
milestone: v1.0
status: complete
stopped_at: completed_09-04
last_updated: 2026-04-11
progress:
  phase: 9
  phase_name: Launch Polish
  plan: 04
  phases_total: 9
  phases_completed: 9
  plans_completed_in_phase: 4
  plans_total_in_phase: 4
  percent: 100
inserted_phases:
  - 9.1: SMW DisplayTitleLookup Backtick Fix — not planned
  - 9.2: Semantic Drilldown Faceted Card Search — not planned
---

# Project State — Grid Tactics Wiki

## Project Reference

See: `.planning/PROJECT.md`

**Core value:** Living, semantically-queryable knowledge base that auto-mirrors Grid Tactics card and mechanic state via git hooks.
**Current focus:** All phases complete. Wiki v1.0 milestone achieved.

## Current Position

Phase: 9 of 9 (Launch Polish)
Plan: 04 of 4 complete -- Final verification passed
Status: COMPLETE. All 9 phases, all 16 plans done.
Last activity: 2026-04-09 -- Completed 09-04 (Final verification, all Phase 9 criteria pass)

Progress: `██████████` 100%

## Performance Metrics

**Velocity:**
- Total plans completed: 15
- Average duration: ~10 min/plan

**By Phase:**

| Phase | Plans | Total | Avg/Plan | Status |
|---|---|---|---|---|
| 1 — Foundation & Schema Design | 4 | 4 | ~18 min | complete |
| 4 — Taxonomy Pages | 2 | 2 | ~5 min | complete |
| 5 — Patch Notes Generator | 2 | 2 | ~9 min | complete |
| 6 — Card History Tracking | 2 | 2 | ~5 min | complete |
| 7 — Semantic Query Showcase & Homepage | 2 | 2 | ~3 min | complete |
| 8 — Idempotency, Drift Detection & Reliability | 3 | 3 | ~2 min | complete |
| 9 — Launch Polish | 4 | 4 | ~3 min | complete |

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
- **[04-02]** 27 keywords parsed from GLOSSARY.md (7 trigger + 20 mechanic). Keyword pages use bare names matching SMW property values.
- **[04-02]** Rules pages use descriptive titles (Grid Tactics TCG, 5x5 Board, Mana, React Window, Win Conditions, Turn Structure) with ManuallyMaintained marker.
- **[04-02]** `verify_taxonomy()` is the comprehensive gate for Phase 4 correctness -- 5 check groups covering category counts, spot checks, content, and rules pages.
- **[04-01]** Mage/Rat tribe page works with slash in title (MediaWiki subpage behavior is acceptable here).
- **[05-01]** EffectType is the only enum tracked for patch diffs (others rarely change). Lexicographic version sort for 0.x.y range.
- **[05-01]** Card diffs report field-level changes (not just "changed"). Glossary parsed from markdown table rows.
- **[05-02]** Category:Patch used to discover patch pages for index (not namespace prefix search).
- **[05-02]** post-commit hook checks wiki/.env existence before attempting sync.
- **[05-02]** First-ever sync diffs HEAD~1..HEAD only (not full history).
- **[06-01]** History entries sorted newest-first by reverse lexicographic version string (consistent with Phase 5).
- **[06-01]** DeprecatedCard template keeps page in Category:Card AND Category:Deprecated for SMW query discoverability.
- **[06-01]** LastChangedPatch is a distinct SMW property from FirstPatch (tracks most recent modification vs. introduction).
- **[06-02]** Template bootstraps (Patch, DeprecatedCard, Card) run unconditionally before patch sync, not gated by dry-run.
- **[06-02]** Card history entries deduplicated by version string to prevent double-entries on re-run.
- **[07-01]** Main Page uses direct upsert (not upsert_taxonomy_pages) since it's a single special page.
- **[07-01]** Main Page placed in Category:Rules for discoverability via existing taxonomy.
- **[07-02]** Showcase page uses Semantic:Showcase title (colon namespace) under Category:Rules.
- **[08-01]** Mock site pattern: `page_store` dict with `__getitem__` override for realistic page lookup simulation in tests.
- **[08-01]** MediaWiki `rstrip()` behavior replicated in mocks — stored text has trailing whitespace stripped to match real API.
- **[08-02]** DriftReport uses drift_type string enum (content_mismatch, missing_page, extra_page) rather than booleans.
- **[08-02]** Resume manifest uses .sync_resume.json in wiki/ root, gitignored, deleted on successful completion.
- **[08-02]** Batch-level try/except catches Exception but not KeyboardInterrupt; per-card try/except stays as-is for graceful individual failures.
- **[09-02]** Element flavor text derived from element names (Fire=aggressive, Dark=sacrifice/drain, etc.) for deck guide archetypes.
- **[09-02]** Tribe synergies section only shows tribes with 3+ cards to avoid noise in the guide.
- **[09-01]** Favicon uses PNG format (not ICO) because Railway MediaWiki bans ICO uploads. JS injection in Common.js references Favicon.png.
- **[09-01]** Ranged keyword search uses `srwhat=text` for full-text content matching (default search mode misses template parameters).
- **[09-03]** XML export via MediaWiki API (not mysqldump) because Railway doesn't expose MariaDB port externally. Importable via `importDump.php`.
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

### Roadmap Evolution

- **2026-04-11** — Phase **9.1** inserted after Phase 9: *SMW DisplayTitleLookup Backtick Fix* (URGENT). `Category:Card` returns HTTP 500 on SMW 5.1.0 + MW 1.43.8. Root cause captured via `MW_DEBUG=1` on Railway deployment `ad905e6e`: `SMW\SQLStore\Lookup\DisplayTitleLookup.php:124` pre-wraps table name in backticks, MW 1.43's Rdbms `SQLPlatform::addIdentifierQuotes` rejects pre-quoted identifiers. Blocking the in-game "Wiki" nav link and any Drilldown UI work. Fix options: Dockerfile sed patch, composer-patches, or SMW upstream upgrade if a patch release lands.
- **2026-04-11** — Phase **9.2** inserted after Phase 9.1: *Semantic Drilldown Faceted Card Search*. Tier-2 upgrade on the existing SMW enrichment (20 typed properties per card already populated by `sync_cards.py`). Will install `mediawiki/semantic-drilldown`, create `Filter:Element`, `Filter:CardType`, `Filter:Tribe`, `Filter:ManaCost`, `Filter:Attack`, `Filter:HP`, `Filter:Keyword` via a new `sync_filters.py`, and point "All Cards" at `Special:BrowseData/Card`. Hard-blocked by 9.1 because Drilldown's landing hits the same DisplayTitleLookup prefetch path.

### Pending Todos

- **All phases complete.** v1.0 milestone achieved.
- GitHub secrets (MW_API_URL, MW_BOT_USER, MW_BOT_PASS, MW_API_PATH) must be configured in the repo for wiki-backup.yml workflow to run.
- Phase 2 watch item: BotPassword must be recreated on the Railway instance (credential lives in the wiki DB, doesn't port across). Automate via `createBotPassword.php` one-shot after deploy.
- Phase 3 watch item: `CardType`/`Element` Page-type properties with `[[Allows value::X]]` produce red-links until stub pages are created. Decide whether to auto-create stubs or accept red-links.
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
Stopped at: Completed 09-04 -- All Phase 9 criteria verified. v1.0 milestone complete.
Resume file: None
