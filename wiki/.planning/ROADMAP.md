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

### Phase 3: Card Page Generator

**Goal:** Every card in `data/cards/*.json` has a live wiki page that visually matches the in-game card, with art uploaded and cross-links working.
**Depends on:** Phase 2
**Requirements:** WIKI-02, CARD-01, CARD-02, CARD-03, CARD-04, SEMANTIC-03
**Plans:** 3 plans

Plans:
- [ ] 03-01-PLAN.md — Core card-to-wikitext conversion module with keyword derivation, rules text synthesis, and cross-link rendering
- [ ] 03-02-PLAN.md — Fix Template:Card category name, upload CardBack.png placeholder, verify file upload permissions
- [ ] 03-03-PLAN.md — sync_wiki.py CLI for bulk card upsert, art upload, and end-to-end verification

**Success Criteria:**
1. `Template:Card` renders a sample card on the wiki in a layout that matches the in-game look (art, name, cost, element, type, stats, rules text, keywords).
2. `python sync/sync_wiki.py --all-cards` upserts every card and the page count under `Category:Card` equals the JSON count.
3. Every card page displays its art, sourced from `src/grid_tactics/server/static/art/<card_id>.png`, uploaded via the API.
4. Tutor, transform, and promote targets in card effects render as working wikilinks.
5. `Special:Browse` on any card page shows every SMW property populated with the correct value.

---

### Phase 4: Taxonomy Pages

**Goal:** Elements, tribes, keywords, and conceptual rules pages exist and use SMW queries to auto-list members.
**Depends on:** Phase 3
**Requirements:** WIKI-03, WIKI-04, WIKI-05, WIKI-06, SEMANTIC-01

**Success Criteria:**
1. All 7 element pages exist; each inline query returns exactly the cards of that element.
2. Every distinct tribe in the card set has a page that lists its members via `{{#ask:}}`.
3. Every keyword in `data/GLOSSARY.md` has a page whose text matches the glossary entry.
4. The six conceptual pages (overview, 5x5 board, mana, react window, win conditions, turn structure) exist with real content and the `{{ManuallyMaintained}}` marker.
5. Expected-vs-actual spot checks on three taxonomy pages all match.

---

### Phase 5: Patch Notes Generator & Hook Integration

**Goal:** Every commit that touches card, glossary, or enum files auto-creates or updates a `Patch:X.Y.Z` page through a git hook.
**Depends on:** Phase 3
**Requirements:** PATCH-01, PATCH-02, PATCH-03, PATCH-04, PATCH-05, AUTO-01, AUTO-07

**Success Criteria:**
1. A commit touching a card JSON triggers the `post-commit` hook which runs `sync/sync_wiki.py` and produces a `Patch:X.Y.Z` page matching `VERSION.json`.
2. The patch page lists added, changed, and removed cards, each as a wikilink to the card page.
3. Edits to `data/GLOSSARY.md` or effect-type enums show up under a Mechanics heading on the same patch page.
4. `Patch:Index` lists all patches reverse-chronologically.
5. `wiki/.sync_state.json` tracks the last synced commit SHA; re-running sync only processes new commits.

---

### Phase 6: Card History Tracking

**Goal:** Every card page carries a complete per-patch change history, and deleted cards are preserved with a deprecated marker.
**Depends on:** Phase 5
**Requirements:** CARD-05, CARD-06

**Success Criteria:**
1. After two simulated patch cycles that modify a card, its `== History ==` section lists both versions keyed by patch.
2. Simulated removal of a card from `data/cards/*.json` results in the wiki page being marked `{{DeprecatedCard}}` and preserved (not deleted).
3. The `Has_last_changed_patch` SMW property reflects the most recent patch that modified each card.

---

### Phase 7: Semantic Query Showcase & Homepage

**Goal:** The wiki has a navigable homepage and a showcase of powerful semantic queries that designers and players can actually use.
**Depends on:** Phase 4, Phase 6
**Requirements:** WIKI-08, SEMANTIC-02

**Success Criteria:**
1. The Main Page links to element, tribe, keyword, rules, and patch indexes, and all links resolve.
2. `Semantic:Showcase` demonstrates at least 5 queries including "Fire minions under 3 mana", "cards changed in last 3 patches", and "minions with attack > 10 grouped by tribe".
3. Every showcase query returns at least one row against the current card set.

---

### Phase 8: Idempotency, Drift Detection & Reliability

**Goal:** The sync pipeline is safe to run repeatedly, detects any drift between JSON and wiki, and fails loudly in CI.
**Depends on:** Phase 5
**Requirements:** AUTO-02, AUTO-03, AUTO-04, AUTO-05, AUTO-06

**Success Criteria:**
1. Two sequential sync runs against the same state produce zero edits on the second run (verified by test).
2. `sync/sync_wiki.py --dry-run` reports planned changes without making API calls (verified by mock).
3. Manually editing a card page on the live wiki causes `sync/check_drift.py` to exit non-zero with a readable report.
4. A simulated mid-batch API failure leaves a resume manifest; rerunning completes the remaining edits.
5. A GitHub Actions workflow runs drift check on every push to master and fails on divergence.

---

### Phase 9: Launch Polish

**Goal:** The wiki is presentable, backed up, reachable at a real domain, and ready for public announcement.
**Depends on:** Phase 7, Phase 8
**Requirements:** DEPLOY-05, DEPLOY-06, WIKI-07, POLISH-01, POLISH-02, POLISH-03

**Success Criteria:**
1. Wiki is reachable at the chosen custom domain with a valid HTTPS cert.
2. Weekly `mysqldump` backups are running and at least one artifact has been recovered in a test.
3. Deck-building guide page exists with an auto-updated archetypes section.
4. Home, card, element, and patch pages all render cleanly at ≤480px width.
5. Site logo and favicon are visible on every page.
6. MediaWiki search returns card pages by name, tribe, and keyword.

---

## Progress

| Phase | Status | Completed |
|---|---|---|
| 1 - Foundation & Schema Design | complete | 2026-04-08 |
| 2 - MediaWiki + SMW Deployment on Railway | complete | 2026-04-09 |
| 3 - Card Page Generator | planned | — |
| 4 - Taxonomy Pages | Not started | — |
| 5 - Patch Notes Generator & Hook Integration | Not started | — |
| 6 - Card History Tracking | Not started | — |
| 7 - Semantic Query Showcase & Homepage | Not started | — |
| 8 - Idempotency, Drift Detection & Reliability | Not started | — |
| 9 - Launch Polish | Not started | — |

## Coverage

All v1 and v1.1 requirements mapped to exactly one phase.
POLISH-04 and POLISH-05 deferred to `future` milestone.

---

*Roadmap for milestone: v1.0*
