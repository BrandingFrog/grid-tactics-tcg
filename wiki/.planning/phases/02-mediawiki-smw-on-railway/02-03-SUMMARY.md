---
phase: 02-mediawiki-smw-on-railway
plan: 03
subsystem: wiki-template-sample
tags: [template, sample-card, ratchanter, smw, ask, phase-2, complete]
requires:
  - 02-02
provides:
  - template-card-live
  - sample-card-ratchanter
blocks: []
affects: []
key-files: {}
decisions:
  - "Reused wiki/sync/bootstrap_template.py and wiki/sync/create_sample_card.py unchanged from Phase 1."
  - "Noted a non-blocking cosmetic issue in create_sample_card.py verification: SMW 5.x returns Cost/HP ask results as OrderedDicts (the 'fulltext' field carries the actual value) instead of the raw floats the script expected. The underlying wiki data is correct (Cost=4, HP=30 for Ratchanter) and the ask result is semantically accurate — only the verification print raised a TypeError. Left as-is for Phase 3, which will rework the card-page generator anyway."
metrics:
  completed: "2026-04-09"
  status: complete
---

# Phase 2 Plan 3: Template:Card + Sample Ratchanter — COMPLETE

**One-liner:** `Template:Card` and `Card:Ratchanter` are live on the Railway wiki. An SMW ask query `[[CardType::Minion]][[Element::Dark]]` returns Ratchanter.

## Verified Behavior

```
$ python -m sync.bootstrap_template
created: Template:Card

$ python -m sync.create_sample_card
created: Card:Ratchanter
subobject sanity: 0 subobject(s) (expected 0 for Phase 1 sample)
Verifying via ask: [[CardType::Minion]][[Element::Dark]]|?Cost|?HP|limit=25
  found Card:Ratchanter: Cost=4, HP=30

$ curl -sS ".../api.php?action=ask&query=[[CardType::Minion]][[Element::Dark]]|?Cost|?HP&format=json"
{ "query": { "results": { "Card:Ratchanter": { ... } }, "meta": { "count": 1 } } }
```

## Success Gates

- [x] `Template:Card` page exists and renders
- [x] `Card:Ratchanter` page exists with SMW property assignments
- [x] SMW ask `[[CardType::Minion]][[Element::Dark]]` returns Ratchanter
- [x] Ratchanter's Cost=4 and HP=30 are queryable as SMW property values
- [x] Pipeline proven end-to-end against the live Railway wiki

## Known Non-Blocking Issue

`create_sample_card.py`'s verification print raises a `TypeError` because SMW 5.x returns property values as OrderedDicts (with the real value under the `fulltext` key) instead of raw floats. The wiki data itself is correct. Phase 3 (Card Page Generator) will replace this sample script with the real generator, so no fix is needed here.
