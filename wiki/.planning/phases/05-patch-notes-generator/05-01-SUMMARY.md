---
phase: 05-patch-notes-generator
plan: 01
subsystem: wiki-sync
tags: [git-diff, wikitext, patch-notes, pure-functions]
dependency_graph:
  requires: []
  provides: [patch_diff, patch_page, PatchDiff-dataclass]
  affects: [05-02]
tech_stack:
  added: []
  patterns: [subprocess-git-show, dataclass-diffing]
file_tracking:
  created: [wiki/sync/patch_diff.py, wiki/sync/patch_page.py]
  modified: []
decisions:
  - id: "05-01-01"
    summary: "EffectType only enum tracked (expandable later)"
  - id: "05-01-02"
    summary: "Lexicographic version sort (sufficient for 0.x.y range)"
metrics:
  duration: ~2min
  completed: 2026-04-09
---

# Phase 5 Plan 1: Patch Diff Engine and Wikitext Generator Summary

Git-based diff engine detecting card/glossary/enum changes between commits, plus wikitext renderer for Patch:X.Y.Z and Patch:Index pages.

## What Was Built

### patch_diff.py -- Git-based diff engine

Four dataclasses (`CardChange`, `KeywordChange`, `EnumChange`, `PatchDiff`) and six functions:

- `_git_show` / `_git_ls_tree`: subprocess wrappers for reading files at specific commits
- `diff_cards`: compares card JSON files, detecting added/changed/removed cards with field-level granularity
- `diff_glossary`: parses GLOSSARY.md table rows at both commits, detects keyword changes
- `diff_enums`: regex-parses EffectType IntEnum members, detects added/removed values
- `build_patch_diff`: orchestrator that reads VERSION.json, commit date, and calls all three diff functions

### patch_page.py -- Wikitext generator

- `patch_to_wikitext`: renders a PatchDiff as a full Patch:X.Y.Z wiki page with template invocation, Cards section (Added/Changed/Removed subsections), and Mechanics section (Keywords/Effect Types). Empty sections omitted entirely.
- `patch_index_wikitext`: renders a reverse-chronological wikitable of all patches.
- `PATCH_TEMPLATE_WIKITEXT`: module-level constant for the Template:Patch infobox.

## Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Git-based diff engine | 5d136f8 | wiki/sync/patch_diff.py |
| 2 | Wikitext generator | 67b1b20 | wiki/sync/patch_page.py |

## Decisions Made

1. **EffectType only** -- Only the EffectType enum is tracked for now. Other enums (CardType, Element, etc.) rarely change and can be added later.
2. **Lexicographic version sort** -- Version strings sorted lexicographically in reverse for the index page. Works correctly for 0.x.y semver range; if versions reach 1.x.y, switch to `packaging.version`.
3. **Field-level card diffing** -- Changed cards list exactly which JSON fields differ, not just "something changed".

## Deviations from Plan

None -- plan executed exactly as written.

## Next Phase Readiness

Plan 05-02 can proceed. It needs:
- `PatchDiff` dataclass from `patch_diff.py` (available)
- `patch_to_wikitext` and `patch_index_wikitext` from `patch_page.py` (available)
- Wiki connection via `client.py` (existing, not needed for this plan)
