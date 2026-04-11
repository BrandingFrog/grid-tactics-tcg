# Roadmap — Grid Tactics Wiki

**Project:** grid-tactics-wiki
**Created:** 2026-04-07
**Phases:** 9
**Milestone:** v1.0

## Overview

Phases are ordered by dependency: foundation and schema first, then infrastructure, then the card pipeline, then taxonomy, then patch automation, then history tracking, then discovery/query UX, then reliability hardening, and finally launch polish. Every v1 and v1.1 requirement maps to exactly one phase.

## Phases

### Phase 1: Foundation & Schema Design ✓

**Goal:** Local dev environment runs MediaWiki + SMW and the SMW property model is fully defined.
**Depends on:** Nothing
**Requirements:** DEPLOY-02, WIKI-01

**Success Criteria:**
1. `docker compose up` from `wiki/` brings up a working local MediaWiki + SMW instance at `http://localhost:8080`.
2. Every SMW property the project needs (card_id, mana_cost, element, tribe, attack, health, range, card_type, keyword, effect, first_patch, last_changed_patch, deckable, stable_id) has a documented `Property:` page with a type declaration.
3. Research flags from PROJECT.md are resolved: chosen MediaWiki+SMW Docker base, chosen Python client library (`mwclient` vs `pywikibot`).
4. `wiki/` directory layout is committed with `sync/`, `docker/`, `.planning/` subdirs.

---

### Phase 2: MediaWiki + SMW Deployment on Railway ✓

**Goal:** A public HTTPS wiki is live on Railway with a bot account ready to accept API edits.
**Status:** COMPLETE 2026-04-09. Live at https://mediawiki-production-7169.up.railway.app with SMW 5.1.0. Pivoted mid-phase from Taqasta to `mediawiki:1.42` + composer-installed SMW — see `phases/02-mediawiki-smw-on-railway/02-01-SUMMARY.md` for the deviation log.
**Depends on:** Phase 1
**Requirements:** DEPLOY-01, DEPLOY-03, DEPLOY-04

**Success Criteria:**
1. The Docker image built in Phase 1 is deployed as a Railway service with a persistent MariaDB volume.
2. The public URL serves the wiki over HTTPS and restarts preserve all data.
3. A bot account with a BotPassword exists; `python sync/sync_wiki.py --whoami` authenticates successfully against the live service using credentials from `.env`.

---

### Phase 3: Card Page Generator ✓

**Goal:** Every card in `data/cards/*.json` has a live wiki page that visually matches the in-game card, with art uploaded and cross-links working.
**Status:** COMPLETE 2026-04-09. All 34 card pages live on wiki with art, cross-links, and SMW properties. `python -m sync.sync_wiki --all-cards` is the canonical sync command.
**Depends on:** Phase 2
**Requirements:** WIKI-02, CARD-01, CARD-02, CARD-03, CARD-04, SEMANTIC-03
**Plans:** 3 plans

Plans:
- [x] 03-01-PLAN.md — Core card-to-wikitext conversion module with keyword derivation, rules text synthesis, and cross-link rendering
- [x] 03-02-PLAN.md — Fix Template:Card category name, upload CardBack.png placeholder, verify file upload permissions
- [x] 03-03-PLAN.md — sync_wiki.py CLI for bulk card upsert, art upload, and end-to-end verification

**Success Criteria:**
1. `Template:Card` renders a sample card on the wiki in a layout that matches the in-game look (art, name, cost, element, type, stats, rules text, keywords).
2. `python sync/sync_wiki.py --all-cards` upserts every card and the page count under `Category:Card` equals the JSON count.
3. Every card page displays its art, sourced from `src/grid_tactics/server/static/art/<card_id>.png`, uploaded via the API.
4. Tutor, transform, and promote targets in card effects render as working wikilinks.
5. `Special:Browse` on any card page shows every SMW property populated with the correct value.

---

### Phase 4: Taxonomy Pages ✓

**Goal:** Elements, tribes, keywords, and conceptual rules pages exist and use SMW queries to auto-list members.
**Status:** COMPLETE 2026-04-09. 54 taxonomy pages live: 7 elements, 14 tribes, 27 keywords, 6 rules. Full verification passing.
**Depends on:** Phase 3
**Requirements:** WIKI-03, WIKI-04, WIKI-05, WIKI-06, SEMANTIC-01
**Plans:** 2 plans

Plans:
- [x] 04-01-PLAN.md — Create sync_taxonomy.py module, upsert 7 element + 14 tribe pages with SMW ask queries
- [x] 04-02-PLAN.md — Upsert keyword pages from GLOSSARY.md + 6 conceptual rules pages, full verification

**Success Criteria:**
1. All 7 element pages exist; each inline query returns exactly the cards of that element.
2. Every distinct tribe in the card set has a page that lists its members via `{{#ask:}}`.
3. Every keyword in `data/GLOSSARY.md` has a page whose text matches the glossary entry.
4. The six conceptual pages (overview, 5x5 board, mana, react window, win conditions, turn structure) exist with real content and the `{{ManuallyMaintained}}` marker.
5. Expected-vs-actual spot checks on three taxonomy pages all match.

---

### Phase 5: Patch Notes Generator & Hook Integration ✓

**Goal:** Every commit that touches card, glossary, or enum files auto-creates or updates a `Patch:X.Y.Z` page through a git hook.
**Status:** COMPLETE 2026-04-09. Template:Patch bootstrapped, Patch:0.2.20 created on wiki, post-commit hook active, .sync_state.json tracking HEAD.
**Depends on:** Phase 3
**Requirements:** PATCH-01, PATCH-02, PATCH-03, PATCH-04, PATCH-05, AUTO-01, AUTO-07
**Plans:** 2 plans

Plans:
- [x] 05-01-PLAN.md — Core diff engine (patch_diff.py) and wikitext generator (patch_page.py)
- [x] 05-02-PLAN.md — Patch sync CLI, Patch:Index, .sync_state.json tracking, post-commit hook

**Success Criteria:**
1. A commit touching a card JSON triggers the `post-commit` hook which runs `sync/sync_wiki.py` and produces a `Patch:X.Y.Z` page matching `VERSION.json`.
2. The patch page lists added, changed, and removed cards, each as a wikilink to the card page.
3. Edits to `data/GLOSSARY.md` or effect-type enums show up under a Mechanics heading on the same patch page.
4. `Patch:Index` lists all patches reverse-chronologically.
5. `wiki/.sync_state.json` tracks the last synced commit SHA; re-running sync only processes new commits.

---

### Phase 6: Card History Tracking ✓

**Goal:** Every card page carries a complete per-patch change history, and deleted cards are preserved with a deprecated marker.
**Status:** COMPLETE 2026-04-09. card_history.py pure functions, DeprecatedCard template, LastChangedPatch SMW property, history tracking wired into patch sync pipeline. Templates live on Railway wiki.
**Depends on:** Phase 5
**Requirements:** CARD-05, CARD-06
**Plans:** 2 plans

Plans:
- [x] 06-01-PLAN.md — Pure-function card history module, updated Card template with LastChangedPatch, DeprecatedCard template
- [x] 06-02-PLAN.md — Wire history tracking into patch sync pipeline, bootstrap templates on live wiki, end-to-end verification

**Success Criteria:**
1. After two simulated patch cycles that modify a card, its `== History ==` section lists both versions keyed by patch.
2. Simulated removal of a card from `data/cards/*.json` results in the wiki page being marked `{{DeprecatedCard}}` and preserved (not deleted).
3. The `Has_last_changed_patch` SMW property reflects the most recent patch that modified each card.

---

### Phase 7: Semantic Query Showcase & Homepage ✓

**Goal:** The wiki has a navigable homepage and a showcase of powerful semantic queries that designers and players can actually use.
**Status:** COMPLETE 2026-04-09. Main Page with navigation hub and Semantic:Showcase page with 7 live SMW queries on Railway wiki.
**Depends on:** Phase 4, Phase 6
**Requirements:** WIKI-08, SEMANTIC-02
**Plans:** 2 plans

Plans:
- [x] 07-01-PLAN.md — Main Page with navigation links to all index pages
- [x] 07-02-PLAN.md — Semantic:Showcase page with 7 live SMW queries

**Success Criteria:**
1. The Main Page links to element, tribe, keyword, rules, and patch indexes, and all links resolve.
2. `Semantic:Showcase` demonstrates at least 5 queries including "Fire minions under 3 mana", "cards changed in last 3 patches", and "minions with attack > 10 grouped by tribe".
3. Every showcase query returns at least one row against the current card set.

---

### Phase 8: Idempotency, Drift Detection & Reliability ✓

**Goal:** The sync pipeline is safe to run repeatedly, detects any drift between JSON and wiki, and fails loudly in CI.
**Status:** COMPLETE 2026-04-09. 46 tests passing (idempotency, dry-run, drift detection, CLI). GitHub Actions workflow triggers on push to master.
**Depends on:** Phase 5
**Requirements:** AUTO-02, AUTO-03, AUTO-04, AUTO-05, AUTO-06
**Plans:** 3 plans

Plans:
- [x] 08-01-PLAN.md — Idempotency and dry-run mock tests
- [x] 08-02-PLAN.md — Drift detection CLI (check_drift.py) and resume manifest
- [x] 08-03-PLAN.md — GitHub Actions drift-check workflow and check_drift unit tests

**Success Criteria:**
1. Two sequential sync runs against the same state produce zero edits on the second run (verified by test).
2. `sync/sync_wiki.py --dry-run` reports planned changes without making API calls (verified by mock).
3. Manually editing a card page on the live wiki causes `sync/check_drift.py` to exit non-zero with a readable report.
4. A simulated mid-batch API failure leaves a resume manifest; rerunning completes the remaining edits.
5. A GitHub Actions workflow runs drift check on every push to master and fails on divergence.

---

### Phase 9: Launch Polish ✓

**Goal:** The wiki is presentable, backed up, reachable at a real domain, and ready for public announcement.
**Status:** COMPLETE 2026-04-09. Mobile CSS, logo/favicon, deck guide, backups, search all verified. Custom domain deferred (Railway URL sufficient).
**Depends on:** Phase 7, Phase 8
**Requirements:** DEPLOY-05, DEPLOY-06, WIKI-07, POLISH-01, POLISH-02, POLISH-03
**Plans:** 4 plans

Plans:
- [x] 09-01-PLAN.md — Mobile CSS, site logo/favicon, and search verification
- [x] 09-02-PLAN.md — Deck-building guide page with auto-updated archetypes
- [x] 09-03-PLAN.md — Weekly backup via GitHub Actions (XML export)
- [x] 09-04-PLAN.md — Custom domain decision and final Phase 9 verification

**Success Criteria:**
1. Wiki is reachable at the chosen custom domain with a valid HTTPS cert.
2. Weekly `mysqldump` backups are running and at least one artifact has been recovered in a test.
3. Deck-building guide page exists with an auto-updated archetypes section.
4. Home, card, element, and patch pages all render cleanly at ≤480px width.
5. Site logo and favicon are visible on every page.
6. MediaWiki search returns card pages by name, tribe, and keyword.

---

### Phase 9.1: SMW DisplayTitleLookup Backtick Fix (INSERTED) ✓

**Goal:** `/wiki/Category:Card` (and every other SMW-prefetched category page) returns HTTP 200 instead of HTTP 500 under the pinned SMW 5.1.0 + MW 1.43.8 pairing.
**Status:** COMPLETE 2026-04-11. Bumped SMW composer pin `~5.0` → `~6.0` in `wiki/Dockerfile` (commit `2712922`). SMW 6.0.1 contains upstream PR #6172 which removes the redundant `$connection->tablename()` wrapper. Verified green across 9/9 SMW-backed category pages, Special:Browse renders all typed properties including `"Display title of"` (the property backing `smw_fpt_dtitle`), and Semantic:Showcase's 7 `#ask` queries all render correct live data under SMW 6.0.x. Phase 9.2 unblock proxy (SMW ask API) passed with 26 results. MW_DEBUG flipped back to 0 post-verification.
**Depends on:** Phase 9 (runs against the already-live wiki)
**Urgency:** Blocking — `Category:Card` is the primary entry point from the game client's in-app "Wiki" nav link (`src/grid_tactics/server/static/game.html:24`) and from `Main Page → All Cards`. Also a hard prerequisite for Phase 9.2 (Drilldown) because the Drilldown landing page hits the same `DisplayTitleLookup` prefetch codepath.
Plans:
- [ ] 09.1-01-PLAN.md — bump SMW composer pin to ~6.0 in wiki/Dockerfile, deploy via Railway, verify live wiki, flip MW_DEBUG=0 after user sign-off

**Plans:** 1 plan (created by /gsd:plan-phase — wave 1, non-autonomous: has checkpoint for user verification)

**Root cause** (captured via `MW_DEBUG=1` on Railway deployment `ad905e6e`, 2026-04-11):

- Exception: `InvalidArgumentException: cannot contain quote, dot or null characters: got '` `smw_fpt_dtitle` `'`
- Call chain: `Category:Card` render → `SMW\SQLStore\EntityStore\CacheWarmer::prepareCache` → `SMW\DisplayTitleFinder::prefetchFromList` → `SMW\SQLStore\Lookup\DisplayTitleLookup::fetchFromTable` (line 124) → `$db->select('` `smw_fpt_dtitle` `', ...)` → `Wikimedia\Rdbms\Platform\SQLPlatform::addIdentifierQuotes` rejects the pre-quoted identifier.
- SMW `DisplayTitleLookup.php:124` pre-wraps the table name in backticks; MW 1.43's Rdbms layer was hardened to reject pre-quoted identifiers. Bug is live in SMW 5.1.0 (latest stable on Packagist as of 2025-07-24) against MW 1.43.8.

**Success Criteria:**

1. `GET /wiki/Category:Card` returns HTTP 200 on the production Railway wiki.
2. Every other SMW-populated category page (e.g. `Category:Minion`, `Category:Fire cards`) renders without 500.
3. The fix survives a clean Docker image rebuild — it is codified in `wiki/Dockerfile`, not a one-off patch on a running container.
4. The fix is minimal and auditable (targeted, surgical — not a blanket disable of DisplayTitle or a rollback of MW).
5. `MW_DEBUG` env var can be flipped back to `0` (the ops-commit error-logging gate stays in place but disabled by default) once 9.1 lands and the fix is verified.

**Fix options to evaluate in the plan step:**

- (a) Dockerfile `sed` patch stripping the backticks from `extensions/SemanticMediaWiki/src/SQLStore/Lookup/DisplayTitleLookup.php:124` during image build.
- (b) `cweagans/composer-patches` with a `.patch` file committed under `wiki/patches/` — cleaner, versionable, survives SMW upgrades that don't touch the same line.
- (c) Check SMW GitHub for an already-merged fix on `master` or a pending `5.1.x` patch release; upgrade the composer constraint if a fix is available.
- (d) Open an upstream PR (parallel track, not blocking the production fix).

---

### Phase 9.2: Semantic Drilldown Faceted Card Search (INSERTED) ✓

**Goal:** "All Cards" on the wiki becomes a faceted card-search UI (Element / CardType / Tribe / ManaCost / Attack / HP / Keyword) backed by the existing SMW property annotations from `sync_cards.py`, with URL-bookmarkable filter state and multi-select facets.
**Status:** COMPLETE 2026-04-11. Semantic Drilldown 5.0.0-beta1 (@7ca8f802) live on Railway wiki. 8 facets on `Special:BrowseData/Card` (Element, CardType, Tribe, ManaCost, Attack, HP, Range, Keyword). Element narrowing verified (6 Fire cards), two-facet narrowing verified (4 Fire Minions via Element=Fire + CardType=Minion), bookmarkable URLs, Keyword multi-select verified (5-card OR-union from Tutor + Promote). Entry points repointed: `game.html:24` in-game nav link, `Main_Page` "All Cards", `sync_taxonomy.py:341` See Also. `MW_DEBUG` flipped back to 0. All 9.1 baselines preserved.
**Depends on:** Phase 9.1 ✓ (9.1 verified 2026-04-11 — DisplayTitleLookup prefetch no longer crashes on SMW 6.0.x; ask API returns correct results)
**Plans:** 1 plan (wave 1, non-autonomous: has one user-verification checkpoint between Drilldown install verification and entry-point rewrites)

Plans:
- [ ] 09.2-01-PLAN.md — install Semantic Drilldown 5.0.0-beta1 (@7ca8f802) via Dockerfile git clone, wire wfLoadExtension + $sdg* config in LocalSettings.php, create wiki/sync/sync_filters.py (single-writer of Category:Card, {{#drilldowninfo:}} with 8 facets), rewrite "All Cards" entry points (game.html:24 + sync_homepage.py + sync_taxonomy.py), run Playwright faceted-search smoke test, flip MW_DEBUG=0, close phase

**Context:**

The SMW enrichment pipeline (`wiki/sync/schema.py`, `wiki/sync/templates/Card.wiki`, `wiki/sync/sync_cards.py`) already annotates every card page with 20 typed properties (Name, CardType, Element, Tribe, ManaCost, Attack, HP, Range, Keyword, RulesText, FirstPatch, LastChangedPatch, etc.). Consumers today: 54 taxonomy pages and 7 canned `#ask` queries on `Semantic:Showcase`. Drilldown is the natural payoff on that investment — it turns the flat set of typed properties into a faceted product feature without any change to the sync pipeline.

**Success Criteria:**

1. A Semantic Drilldown release compatible with SMW 5.1.0 + MW 1.43.8 + PHP 8.3 is installed via composer in `wiki/Dockerfile`, loaded in `LocalSettings.php`, and survives clean rebuild.
2. Filter pages exist for at least: `Element`, `CardType`, `Tribe`, `ManaCost` (numeric-range), `Attack` (numeric-range), `HP` (numeric-range), `Keyword` (multi-select). A new `wiki/sync/sync_filters.py` idempotently upserts them.
3. `Special:BrowseData/Card` renders a faceted sidebar showing all facets with live counts.
4. Picking `Element=Fire` narrows the result set to only Fire cards; picking `ManaCost 1–3` additionally filters to budget cards; the URL is bookmarkable and round-trips on reload.
5. `Keyword` facet allows multiple simultaneous selections (e.g. `Tutor` OR `Promote`).
6. `Main Page` "All Cards" link and the game client's in-app "Wiki" nav link (`src/grid_tactics/server/static/game.html:24`) both point at `Special:BrowseData/Card` instead of `Category:Card`.
7. Playwright smoke test walks the landing page, applies a 2-facet filter, asserts the result set narrows correctly, and asserts the URL contains the filter state.
8. Rollback path is documented: remove the composer line, remove the `wfLoadExtension`, redeploy — filter pages and `sync_filters.py` are harmless orphans if Drilldown is later removed.

**Compatibility research must complete in plan step 1, before any code change:**

- Verify Semantic Drilldown's current release is compatible with SMW 5.1.0 + MW 1.43.8 + PHP 8.3 (the live stack).
- Confirm install method (composer `mediawiki/semantic-drilldown` vs. drop-in tarball) and whether Page Forms is still a hard dependency (older SD versions required it).
- Confirm no regression on the SMW DisplayTitleLookup bug from 9.1 — Drilldown's category browsing uses the same prefetch path.

---

## Progress

| Phase | Status | Completed |
|---|---|---|
| 1 - Foundation & Schema Design | complete | 2026-04-08 |
| 2 - MediaWiki + SMW Deployment on Railway | complete | 2026-04-09 |
| 3 - Card Page Generator | complete | 2026-04-09 |
| 4 - Taxonomy Pages | complete | 2026-04-09 |
| 5 - Patch Notes Generator & Hook Integration | complete | 2026-04-09 |
| 6 - Card History Tracking | complete | 2026-04-09 |
| 7 - Semantic Query Showcase & Homepage | complete | 2026-04-09 |
| 8 - Idempotency, Drift Detection & Reliability | complete | 2026-04-09 |
| 9 - Launch Polish | complete | 2026-04-09 |
| 9.1 - SMW DisplayTitleLookup Backtick Fix (INSERTED) | complete | 2026-04-11 |
| 9.2 - Semantic Drilldown Faceted Card Search (INSERTED) | complete | 2026-04-11 |

## Coverage

All v1 and v1.1 requirements mapped to exactly one phase.
POLISH-04 and POLISH-05 deferred to `future` milestone.

---

*Roadmap for milestone: v1.0*
