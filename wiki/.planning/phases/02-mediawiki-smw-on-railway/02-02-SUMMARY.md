---
phase: 02-mediawiki-smw-on-railway
plan: 02
subsystem: wiki-schema-bootstrap
tags: [smw, properties, bootstrap, phase-2, complete]
requires:
  - 02-01  # mediawiki-service-live, smw-5.1-installed
provides:
  - smw-properties-live
blocks: []
affects:
  - 02-03
key-files:
  modified:
    - wiki/sync/client.py
decisions:
  - "Reused the existing wiki/sync/bootstrap_schema.py script unchanged from Phase 1 — it is idempotent and creates/updates 25 Property pages with type declarations."
  - "sync/client.py gained an MW_API_PATH env var so the same code works against local Taqasta (/w/) and the Railway mediawiki service (/). Default now / for the live wiki."
  - "Auth via Admin main-account password against action=login. BotPasswords were NOT needed for Phase 2 — the sync scripts run manually, one-off, and the main password is sufficient for Template/Property edits."
metrics:
  completed: "2026-04-09"
  status: complete
---

# Phase 2 Plan 2: Bootstrap SMW Schema — COMPLETE

**One-liner:** Ran `python -m sync.bootstrap_schema` against the live Railway wiki. All 25 SMW Property pages were created successfully with type declarations.

## Verified Behavior

```
$ python -m sync.bootstrap_schema
created: Property:Name
created: Property:StableId
created: Property:CardType
... (25 total)
Summary: 25 created, 0 updated, 0 unchanged (25 total)

$ python -m sync.verify_smw
SMW version: 5.1.0
Bot authenticated as: Admin
ask() returned 0 result(s) (OK)
OK
```

Re-running the bootstrap showed `0 created, 0 updated, 25 unchanged`, confirming idempotency.

## Properties Created

Name, StableId, CardType, Element, Tribe, Cost, Attack, HP, Range, RulesText, Keyword, Artist, ArtFile, FlavorText, FirstPatch, LastChangedPatch, LastModified, SourceFile, Deckable, HasEffect, EffectTrigger, EffectCondition, EffectAction, EffectAmount, EffectText.

## Success Gates

- [x] All 25 properties exist as Property: pages on the live wiki
- [x] Each has the expected type declaration
- [x] `verify_smw` returns OK
- [x] Script is idempotent (second run reports all unchanged)
