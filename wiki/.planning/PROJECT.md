# Grid Tactics Wiki

**Created:** 2026-04-07
**Parent:** Grid Tactics TCG (`../`)
**Type:** Subproject — auto-generated Semantic MediaWiki

## Vision

A living, semantically-queryable knowledge base that automatically mirrors the current state of the Grid Tactics TCG. Every card, mechanic, keyword, element, tribe, and patch is a wiki page with rich SMW metadata. Git hooks drive all updates — humans never edit card pages directly. The wiki is a **projection** of the canonical game data (`data/cards/*.json`, `data/GLOSSARY.md`, `src/grid_tactics/enums.py`); it is never the source of truth.

## Core Value

**Designers** can run semantic queries like *"all Rat-tribe minions with attack > 10 that were buffed in patches 0.3.x"* to validate balance hypotheses in seconds.

**Players** get a real TCG wiki: cards rendered as they appear in-game, full rules text, element/tribe/keyword cross-links, and per-card change history.

**The team** gets flawless patch notes for free — every commit that touches card or mechanic files auto-generates a `Patch:X.Y.Z` page itemizing exactly what changed.

## Relationship to Parent Project

| Concern | Grid Tactics (parent) | Wiki (this subproject) |
|---|---|---|
| Source of truth for cards | `data/cards/*.json` | Reads, never writes |
| Source of truth for keywords | `data/GLOSSARY.md` | Reads, never writes |
| Version | `src/grid_tactics/server/static/VERSION.json` | Reads for `Patch:` pages |
| Art assets | `src/grid_tactics/server/static/art/*.png` | Uploaded to wiki via API |
| Deployment | Railway (existing service) | Railway (new Docker service) |
| Edit rights | Human devs via git | Bot account only (for auto pages) |

The wiki coexists with the existing `obsidian/` vault: Obsidian is manual internal notes, the wiki is public auto-generated documentation.

## Tech Stack

| Layer | Technology | Version | Notes |
|---|---|---|---|
| Wiki engine | MediaWiki | 1.42 LTS (TBD — confirm with SMW compat) | Upstream official, no fork |
| Semantic layer | Semantic MediaWiki (SMW) | latest stable (~4.1.x) | Installed via Composer in Docker image |
| Database | MySQL / MariaDB | 10.11 LTS | Railway persistent volume |
| Container | Docker + docker-compose (dev) | — | Single-service Railway deploy in prod |
| Hosting | Railway | — | Alongside existing grid-tactics service |
| Sync runtime | Python | 3.12 | Matches parent project |
| MediaWiki client | `mwclient` | >=0.11 | Lighter than pywikibot; TBD if pywikibot needed for upload edge cases |
| Git integration | `.githooks/post-commit` | — | Shells out to Python sync script |
| Auth | MediaWiki BotPassword | — | Stored in `.env`, never committed |
| Skin | Vector 2022 or Citizen | TBD | Needs mobile-responsive and dark-mode friendly |
| Domain | `wiki.grid-tactics.dev` (TBD) | — | Or subpath on existing Railway domain |
| Backups | Railway volume snapshots + weekly `mysqldump` | — | Backup target TBD (S3? Supabase Storage?) |

**Flagged for research during Phase 1:**
- Official vs community Docker image for MediaWiki+SMW (is there a maintained `semanticmediawiki/docker`?)
- `mwclient` vs `pywikibot` for batch card upserts and file uploads
- Railway volume sizing and snapshot cadence
- Wiki subdomain vs subpath routing

## Constraints

- **JSON is canonical.** The wiki must never drift from `data/cards/*.json`. Drift detection is a v1 requirement.
- **Idempotent hooks.** Running the sync twice on the same commit must be a no-op.
- **No human edits to auto pages.** Card pages, patch pages, taxonomy pages are bot-owned. Only conceptual pages (game overview, deck-building guide) are human-editable.
- **Public read, bot-only write.** No user accounts, no forum, no discussion pages.
- **Patch versioning shared with the game.** Wiki `Patch:X.Y.Z` pages use the same version as `VERSION.json`.
- **Art reuse.** Card images come from `src/grid_tactics/server/static/art/` — uploaded to wiki, not re-authored.
- **Scope discipline.** Only card, mechanic, keyword, and rule changes drive wiki updates. Tensor-engine and RL-training changes are invisible to the wiki.

## Success Definition

v1 is done when:
1. A fresh `git clone` + `docker compose up` + `python sync/sync_wiki.py` produces a fully populated local wiki.
2. Every card in `data/cards/*.json` has a wiki page that matches the in-game card visual and exposes all SMW properties.
3. `git commit` touching any card JSON auto-creates or updates a `Patch:X.Y.Z` page with an itemized diff.
4. A designer can run an SMW query on the wiki homepage and get correct results.
5. The public Railway deployment is live and auto-updating on push to `master`.

## Out of Scope (v1)

- User accounts, authentication, forums, discussion pages, user edits to auto pages
- Forking MediaWiki or SMW
- Tracking non-card source-code changes
- RL training pipeline integration
- Multi-language support
