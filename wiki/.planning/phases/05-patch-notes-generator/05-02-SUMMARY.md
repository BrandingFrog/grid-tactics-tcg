---
phase: 05-patch-notes-generator
plan: 02
subsystem: wiki-sync
tags: [patch-notes, git-hook, cli, wiki-api, sync-state]
dependency_graph:
  requires: [05-01]
  provides: [sync_patches, post-commit-hook, patch-cli, sync-state]
  affects: [06, 08]
tech_stack:
  added: []
  patterns: [post-commit-hook, idempotent-upsert, sync-state-tracking]
file_tracking:
  created: [wiki/sync/sync_patches.py, .git/hooks/post-commit]
  modified: [wiki/sync/sync_wiki.py, wiki/.gitignore, wiki/sync/patch_diff.py]
decisions:
  - id: "05-02-01"
    summary: "Category:Patch used to discover patch pages for index (not namespace prefix search)"
  - id: "05-02-02"
    summary: "post-commit hook checks wiki/.env existence before attempting sync"
  - id: "05-02-03"
    summary: "First-ever sync diffs HEAD~1..HEAD only (not full history)"
metrics:
  duration: ~15min
  completed: 2026-04-09
---

# Phase 5 Plan 2: Patch Sync CLI, Index, State Tracking, and Post-Commit Hook Summary

Wire patch diff engine to live wiki with CLI integration, persistent state tracking via .sync_state.json, Patch:Index page, and auto-sync post-commit git hook.

## What Was Built

### sync_patches.py -- Patch sync orchestrator

Full pipeline connecting patch_diff.py and patch_page.py to the live wiki:

- **State management:** `load_sync_state()` / `save_sync_state()` read/write `.sync_state.json` with `last_synced_sha` and ISO timestamp
- **Template bootstrap:** `bootstrap_patch_template()` idempotently upserts `Template:Patch` on the wiki
- **Core sync:** `sync_patch()` diffs two commits, generates wikitext, upserts `Patch:X.Y.Z` page with rstrip comparison for idempotency
- **Index rebuild:** `sync_patch_index()` reads all pages in `Category:Patch`, extracts version/date/commit via regex, generates index wikitable
- **Pending sync:** `sync_all_pending()` walks commits since last sync, filters by watched paths, syncs each relevant commit, updates state
- **CLI:** `main()` with `--pending`, `--commit SHA`, `--bootstrap-template`, `--dry-run`

### CLI integration in sync_wiki.py

Two new options added to the existing mutually exclusive group:
- `--patch`: syncs all pending commits (bootstraps template first)
- `--patch-commit SHA`: syncs a specific commit against its parent

### Post-commit hook (.git/hooks/post-commit)

Bash script that:
1. Lists files changed in HEAD commit via `git diff-tree`
2. Filters against watched patterns: `data/cards/`, `data/GLOSSARY.md`, `src/grid_tactics/enums.py`
3. Exits silently if no relevant files changed
4. Checks `wiki/.env` exists (credentials available)
5. Runs `python -m sync.sync_wiki --patch` from the wiki directory
6. Always exits 0 (never blocks the commit)

### Gitignore update

Added `.sync_state.json` to `wiki/.gitignore` to keep local sync state out of version control.

## Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Patch sync orchestrator | ae4bf38 | wiki/sync/sync_patches.py |
| 2 | CLI integration + post-commit hook | 752e04d | wiki/sync/sync_wiki.py, wiki/.gitignore, .git/hooks/post-commit |
| 3 | Bug fixes (encoding + date format) | 965198a | wiki/sync/patch_diff.py, wiki/sync/sync_patches.py |

## Decisions Made

1. **Category:Patch for index** -- Patch pages are discovered via `site.categories["Patch"]` rather than allpages prefix search, since "Patch:" is not a real MediaWiki namespace.
2. **wiki/.env gate** -- The post-commit hook checks for `wiki/.env` before running, so developers without wiki credentials don't get errors.
3. **First sync = HEAD~1** -- When no `.sync_state.json` exists, only the most recent commit is diffed (not full history). Avoids generating dozens of irrelevant patch pages.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed git date format in patch_diff.py**
- **Found during:** Task 3 (end-to-end verification)
- **Issue:** `--format=%Y-%m-%d` is a Python strftime format, not a git format. Git was outputting `%Y->-` instead of `2026-04-08`.
- **Fix:** Changed to `--format=%cs` (git's short date format).
- **Files modified:** wiki/sync/patch_diff.py
- **Commit:** 965198a

**2. [Rule 1 - Bug] Fixed Windows encoding crash in subprocess calls**
- **Found during:** Task 3 (end-to-end verification)
- **Issue:** Git subprocess output containing emoji characters (from card JSON) crashed with `UnicodeDecodeError: 'charmap' codec can't decode byte 0x8d` on Windows cp1252 locale.
- **Fix:** Added `encoding="utf-8", errors="replace"` to all `subprocess.run()` calls in both `patch_diff.py` and `sync_patches.py`.
- **Files modified:** wiki/sync/patch_diff.py, wiki/sync/sync_patches.py
- **Commit:** 965198a

## Live Wiki Verification

- Template:Patch: created on wiki (first run)
- Patch:0.2.20: created on wiki with correct card changes, wikilinks, and date
- Patch:Index: not yet populated (only one patch page exists)
- .sync_state.json: written with HEAD sha after sync
- Idempotency: re-run prints "No pending patch changes" with zero edits

## Next Phase Readiness

Phase 5 is complete. Phase 6 (Card History Tracking) can proceed -- it builds on the patch infrastructure to add per-card history sections.
