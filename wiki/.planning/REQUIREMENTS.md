# Requirements — Grid Tactics Wiki

**Milestone:** v1.0
**Categories:** DEPLOY, WIKI, CARD, SEMANTIC, PATCH, AUTO, POLISH

Priority legend: **v1** = must ship for launch, **v1.1** = fast-follow, **future** = deferred.

---

## DEPLOY — MediaWiki + SMW Infrastructure

### DEPLOY-01 — Dockerized MediaWiki + SMW image (v1)
A Dockerfile builds a MediaWiki image with Semantic MediaWiki installed via Composer and enabled in `LocalSettings.php`.
**Acceptance:** `docker build .` succeeds; resulting container starts MediaWiki with SMW special pages reachable at `/wiki/Special:SpecialPages`.

### DEPLOY-02 — Local dev via docker-compose (v1)
`docker-compose.yml` at `wiki/` brings up MediaWiki + MariaDB with persistent volumes.
**Acceptance:** `docker compose up` from `wiki/` yields a working wiki at `http://localhost:8080` with SMW enabled.

### DEPLOY-03 — Railway deployment (v1)
The wiki runs as a Railway service using the Docker image, with a persistent volume for MariaDB and HTTPS enabled.
**Acceptance:** Public URL serves the wiki over HTTPS; restarting the service preserves all pages and uploads.

### DEPLOY-04 — Bot account provisioned (v1)
A MediaWiki user with a BotPassword is created; credentials live in `.env` (never committed).
**Acceptance:** `python sync/sync_wiki.py --whoami` authenticates as the bot and prints the username.

### DEPLOY-05 — DB backup strategy (v1.1)
Weekly `mysqldump` cron dumps to an off-Railway target (S3 or Supabase Storage).
**Acceptance:** At least one successful backup artifact is recoverable.

### DEPLOY-06 — Custom domain (v1.1)
Wiki reachable at `wiki.grid-tactics.dev` (or chosen final domain).
**Acceptance:** DNS resolves; HTTPS cert valid.

---

## WIKI — Schema, Templates, Taxonomy

### WIKI-01 — SMW property model defined (v1)
A documented list of SMW properties (Has_card_id, Has_mana_cost, Has_element, Has_tribe, Has_attack, Has_health, Has_range, Has_card_type, Has_keyword, Has_effect, Has_first_patch, Has_last_changed_patch, Has_deckable, Has_stable_id) with types.
**Acceptance:** `Property:` pages exist for every property; each has a type declaration.

### WIKI-02 — Template:Card renders cards like in-game (v1)
A MediaWiki template takes card fields and renders a visual that matches the in-game card layout (art, name, cost, element, type, stats, rules text, keywords).
**Acceptance:** Rendered HTML of a sample card is visually within spitting distance of the in-game card (manual check against screenshot).

### WIKI-03 — Element pages (v1)
Seven pages, one per element (Wood, Fire, Earth, Water, Metal, Dark, Light), each with a short description and an SMW inline query listing all cards of that element.
**Acceptance:** All 7 pages exist and list the correct cards from a snapshot of `data/cards/`.

### WIKI-04 — Tribe pages (v1)
One page per tribe discovered in `data/cards/*.json`, auto-generated, with an SMW query listing members.
**Acceptance:** Every distinct tribe string in card JSONs has a wiki page; each lists ≥1 card.

### WIKI-05 — Keyword / mechanic pages (v1)
One page per keyword in `data/GLOSSARY.md`, containing the glossary definition and an SMW query for cards with that keyword.
**Acceptance:** Page count matches glossary entry count; content matches glossary source.

### WIKI-06 — Conceptual rules pages (v1)
Manually authored pages for: game overview, 5x5 board, mana system, react window, win conditions, turn structure. Marked `{{ManuallyMaintained}}`.
**Acceptance:** All six pages exist with non-stub content; marker template visible.

### WIKI-07 — Deck-building guide (v1.1)
Semi-static page authored once, with a lightly auto-updated section listing current archetypes.
**Acceptance:** Page exists; auto-updated section refreshes on sync.

### WIKI-08 — Homepage with navigation (v1)
Main page linking to elements, tribes, keywords, rules, patch notes index, and featuring a semantic query showcase.
**Acceptance:** All nav links resolve; showcase query returns live results.

---

## CARD — Per-Card Page Generation

### CARD-01 — Card page generator script (v1)
`sync/generate_card_page.py` reads one card JSON and emits wikitext using Template:Card with full SMW annotations.
**Acceptance:** Unit test: given a sample card JSON, output contains all expected SMW properties and template invocations.

### CARD-02 — Batch upsert all cards (v1)
`sync/sync_wiki.py --all-cards` upserts every card in `data/cards/*.json` via the MediaWiki API.
**Acceptance:** After a full run against an empty wiki, page count under `Category:Card` equals card JSON count.

### CARD-03 — Card art upload (v1)
For each card, the matching PNG from `src/grid_tactics/server/static/art/<card_id>.png` is uploaded to the wiki and referenced by Template:Card.
**Acceptance:** Every card page renders with its art; `Special:ListFiles` contains one entry per card.

### CARD-04 — Related-card cross-links (v1)
Tutor targets, transform targets, and promote targets in effects are rendered as wikilinks.
**Acceptance:** On a card with a tutor effect, clicking the target name navigates to that card's page.

### CARD-05 — Per-card history section (v1)
Each card page has a `== History ==` section that lists every patch in which the card changed, with the diff.
**Acceptance:** After two sync runs across a simulated card edit, the history section shows both versions keyed by patch.

### CARD-06 — Deleted card handling (v1)
If a card is removed from `data/cards/*.json`, its page is marked `{{DeprecatedCard}}` but not deleted (history is preserved).
**Acceptance:** Simulated deletion results in the page persisting with the deprecated marker and final state.

---

## SEMANTIC — Query Capabilities

### SEMANTIC-01 — Inline queries work on taxonomy pages (v1)
Element, tribe, and keyword pages use `{{#ask:}}` queries that return correct results.
**Acceptance:** Manually-computed expected lists match SMW query results on 3 sample pages.

### SEMANTIC-02 — Query showcase index page (v1)
A `Semantic:Showcase` page demonstrating ≥5 useful queries (e.g., "Fire minions under 3 mana", "cards changed in last 3 patches", "minions with attack > 10 by tribe").
**Acceptance:** Page exists; every query returns ≥1 row against current card set.

### SEMANTIC-03 — Property browser reachable (v1)
`Special:Browse` on any card returns a table of all SMW properties with values.
**Acceptance:** Manual check on one card page.

---

## PATCH — Patch Notes Automation

### PATCH-01 — Patch page generator (v1)
`sync/generate_patch_page.py` takes a version and a card-diff payload and emits a `Patch:X.Y.Z` wikitext page with itemized added/changed/removed cards.
**Acceptance:** Unit test: given a synthetic diff, output lists every change under the correct heading.

### PATCH-02 — Version source from VERSION.json (v1)
Patch generator reads `../src/grid_tactics/server/static/VERSION.json` for the current version.
**Acceptance:** Running the generator after a version bump writes to the correct `Patch:` page name.

### PATCH-03 — Patch index page (v1)
`Patch:Index` lists all patches reverse-chronologically with summary counts.
**Acceptance:** After three patch syncs, the index shows three entries in the right order.

### PATCH-04 — Mechanic changes included (v1)
Diffs to `data/GLOSSARY.md` and effect-type enums in `src/grid_tactics/enums.py` appear on the patch page under a Mechanics section.
**Acceptance:** Simulated glossary edit produces a Mechanics entry on the patch page.

### PATCH-05 — Patch page cross-links cards (v1)
Every card mentioned in a patch page links to that card's wiki page.
**Acceptance:** Visual check on a generated patch page.

---

## AUTO — Hooks, Idempotency, Drift Detection

### AUTO-01 — Post-commit hook triggers sync (v1)
`.githooks/post-commit` detects changes to `data/cards/*.json`, `data/GLOSSARY.md`, or `src/grid_tactics/enums.py` and runs `sync/sync_wiki.py` automatically.
**Acceptance:** A commit touching a card JSON causes the wiki to update without manual intervention.

### AUTO-02 — Idempotent upserts (v1)
Running the sync twice on the same commit is a no-op (no duplicate edits, no spurious history entries).
**Acceptance:** Automated test: two sequential sync runs against the same state produce zero MediaWiki edits on the second run.

### AUTO-03 — Dry-run mode (v1)
`sync/sync_wiki.py --dry-run` prints every page that would be created or edited without contacting the API.
**Acceptance:** Dry-run produces a report; no API calls are made (verified via mock).

### AUTO-04 — Drift detection (v1)
`sync/check_drift.py` compares live wiki content against the JSON source and exits non-zero on divergence.
**Acceptance:** Manually editing a card page on the wiki causes the drift check to fail with a clear report.

### AUTO-05 — Sync failure rollback (v1.1)
If a batch upsert fails mid-run, already-applied edits are logged so a rerun can resume safely.
**Acceptance:** Simulated API failure mid-batch leaves a resume manifest; rerun completes the remaining edits.

### AUTO-06 — CI sync check (v1.1)
A GitHub Actions workflow runs `check_drift.py` on every push to master and fails the build on drift.
**Acceptance:** A PR that edits a card JSON without running sync fails CI.

### AUTO-07 — Sync state ledger (v1)
`wiki/.sync_state.json` tracks last-synced commit SHA so diffs only cover new changes.
**Acceptance:** Two commits later, sync only processes the two new commits, not the full card set.

---

## POLISH — Launch-Quality UX

### POLISH-01 — Mobile-responsive skin (v1.1)
Chosen MediaWiki skin renders cleanly on mobile (≤480px width).
**Acceptance:** Manual check on Chrome DevTools mobile viewport for home, card, element, patch pages.

### POLISH-02 — Site logo and favicon (v1.1)
Grid Tactics branding visible on every page.
**Acceptance:** Logo in top-left; favicon in browser tab.

### POLISH-03 — Search works across SMW properties (v1.1)
MediaWiki search returns card pages by name, tribe, and keyword.
**Acceptance:** Searching "Rat" returns all Rat-tribe cards; searching a keyword returns all cards with it.

### POLISH-04 — In-game "View on Wiki" link (future)
Card tooltips in the game UI link to the card's wiki page.
**Acceptance:** Clicking a tooltip link in the running game opens the correct wiki page.

### POLISH-05 — Dark mode (future)
Wiki supports a dark theme.
**Acceptance:** Toggle available; all pages readable in dark mode.

---

## Traceability

| Requirement | Phase | Status |
|---|---|---|
| DEPLOY-01 | Phase 2 | Pending |
| DEPLOY-02 | Phase 1 | Pending |
| DEPLOY-03 | Phase 2 | Pending |
| DEPLOY-04 | Phase 2 | Pending |
| DEPLOY-05 | Phase 9 | Pending |
| DEPLOY-06 | Phase 9 | Pending |
| WIKI-01 | Phase 1 | Pending |
| WIKI-02 | Phase 3 | Pending |
| WIKI-03 | Phase 4 | Pending |
| WIKI-04 | Phase 4 | Pending |
| WIKI-05 | Phase 4 | Pending |
| WIKI-06 | Phase 4 | Pending |
| WIKI-07 | Phase 9 | Pending |
| WIKI-08 | Phase 7 | Pending |
| CARD-01 | Phase 3 | Pending |
| CARD-02 | Phase 3 | Pending |
| CARD-03 | Phase 3 | Pending |
| CARD-04 | Phase 3 | Pending |
| CARD-05 | Phase 6 | Pending |
| CARD-06 | Phase 6 | Pending |
| SEMANTIC-01 | Phase 4 | Pending |
| SEMANTIC-02 | Phase 7 | Pending |
| SEMANTIC-03 | Phase 3 | Pending |
| PATCH-01 | Phase 5 | Pending |
| PATCH-02 | Phase 5 | Pending |
| PATCH-03 | Phase 5 | Pending |
| PATCH-04 | Phase 5 | Pending |
| PATCH-05 | Phase 5 | Pending |
| AUTO-01 | Phase 5 | Pending |
| AUTO-02 | Phase 8 | Pending |
| AUTO-03 | Phase 8 | Pending |
| AUTO-04 | Phase 8 | Pending |
| AUTO-05 | Phase 8 | Pending |
| AUTO-06 | Phase 8 | Pending |
| AUTO-07 | Phase 5 | Pending |
| POLISH-01 | Phase 9 | Pending |
| POLISH-02 | Phase 9 | Pending |
| POLISH-03 | Phase 9 | Pending |
| POLISH-04 | future | Deferred |
| POLISH-05 | future | Deferred |
