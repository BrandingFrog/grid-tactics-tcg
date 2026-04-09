# Phase 3: Card Page Generator - Research

**Researched:** 2026-04-09
**Domain:** MediaWiki API (mwclient), wikitext generation, SMW annotations, file uploads
**Confidence:** HIGH

## Summary

Phase 3 generates wiki pages for all 34 cards in `data/cards/*.json`, uploads card art PNGs, and ensures every page has correct SMW annotations and cross-links. The existing codebase already has most infrastructure in place: `wiki/sync/client.py` provides authenticated mwclient access, `wiki/sync/templates/Card.wiki` defines a working Template:Card with SMW annotations, `wiki/sync/schema.py` defines all 25 SMW properties including effect subproperties, and `wiki/sync/create_sample_card.py` demonstrates the pattern for generating card wikitext from JSON.

The core work is: (1) a `card_to_wikitext()` function that maps any card JSON to a Template:Card invocation with derived keywords and cross-links, (2) an art upload function using `site.upload()`, (3) a `sync_wiki.py --all-cards` CLI that iterates all card JSONs and upserts pages idempotently, and (4) enhancing Template:Card to handle cards without art gracefully and to display cross-link targets.

**Primary recommendation:** Build a single `wiki/sync/sync_cards.py` module with pure-function wikitext generation (testable without wiki) and a thin CLI wrapper. Reuse `client.py` for auth. Derive keywords from card JSON fields (effects, activated_ability, transform_options, etc.) rather than requiring a manual `keywords` field.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| mwclient | 0.11.x | MediaWiki API client (page edit, file upload, ask queries) | Already in use by all Phase 1-2 sync scripts. Proven working against Railway wiki. |
| python-dotenv | any | Load `.env` credentials | Already used by `client.py`. |
| argparse (stdlib) | -- | CLI `--all-cards`, `--dry-run`, `--card <id>` flags | Zero dependency, standard for CLI scripts. |
| json (stdlib) | -- | Read `data/cards/*.json` | Already used everywhere. |
| pathlib (stdlib) | -- | File path handling | Already used in `create_sample_card.py`. |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | >=8.0 | Test wikitext generation without wiki | Unit test `card_to_wikitext()` for all card types. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| mwclient | pywikibot | pywikibot is heavier, designed for bot frameworks. mwclient is already working and simpler. Decision was locked in Phase 1. |
| Direct JSON reading | CardLoader class | CardLoader returns frozen dataclasses with IntEnum values. For wiki sync, we need the raw JSON strings (element names, effect type names as text). Reading JSON directly is simpler and avoids enum-to-string round-trips. |

**Installation:**
```bash
# Already installed from Phase 1-2
pip install mwclient python-dotenv
```

## Architecture Patterns

### Recommended Project Structure
```
wiki/sync/
    client.py              # (exists) mwclient Site factory
    schema.py              # (exists) SMW property definitions
    templates/Card.wiki    # (exists) Template:Card wikitext
    bootstrap_template.py  # (exists) uploads Template:Card
    bootstrap_schema.py    # (exists) creates Property: pages
    create_sample_card.py  # (exists) Phase 1 sample - will be superseded
    sync_cards.py          # NEW - card page generation + upsert
    sync_wiki.py           # NEW or extend - CLI entry point with --all-cards
```

### Pattern 1: Pure Function Wikitext Generation
**What:** `card_to_wikitext(card_json: dict) -> str` takes a raw card JSON dict and returns complete wikitext (Template:Card invocation + categories).
**When to use:** Always. This is the core transformation.
**Why:** Testable without a wiki. Unit tests can assert on output strings. The Phase 1 `create_sample_card.py` already demonstrates this pattern in `_build_wikitext()`.

```python
def card_to_wikitext(card: dict) -> str:
    """Convert a card JSON dict to wikitext using Template:Card."""
    element = str(card.get("element", "")).strip().capitalize()
    card_type = str(card.get("card_type", "")).strip().capitalize()
    
    fields = {
        "name": card["name"],
        "type": card_type,
        "element": element,
        "tribe": card.get("tribe", ""),
        "cost": card.get("mana_cost", ""),
        "attack": card.get("attack", ""),
        "hp": card.get("health", ""),
        "range": card.get("range", ""),
        "rules": build_rules_text(card),
        "flavor": card.get("flavour_text", ""),
        "keywords": ", ".join(derive_keywords(card)),
        "art": f"{card['card_id']}.png",
        "patch": "0.4.2",
        "stable_id": card.get("card_id", ""),
        "deckable": "true" if card.get("deckable", True) else "false",
    }
    
    lines = ["{{Card"]
    for key, value in fields.items():
        if value != "" and value is not None:
            lines.append(f"| {key:9s}= {value}")
    lines.append("}}")
    lines.append("")
    return "\n".join(lines)
```

### Pattern 2: Keyword Derivation from JSON Fields
**What:** Keywords are NOT stored in card JSONs. They must be derived from structural fields.
**Critical finding:** No card JSON has a `keywords` field. The Phase 1 sample hard-coded `keywords = "Sacrifice, Summon"` for Ratchanter. The sync script must derive keywords from:

| JSON Field/Pattern | Derived Keyword(s) |
|---|---|
| `card_type == "react"` | React |
| `react_condition` present | React |
| `unique == true` | Unique |
| `range > 0` | Range {range} |
| `range == 0` (minion) | Melee |
| `tutor_target` present | Tutor |
| `transform_options` present | Transform |
| `promote_target` present | Promote |
| `activated_ability` present | Active |
| `effects` with `type: "burn"` | Burn |
| `effects` with `type: "heal"` | Heal |
| `effects` with `type: "damage"` | Deal |
| `effects` with `type: "destroy"` | Destroy |
| `effects` with `type: "negate"` | Negate |
| `effects` with `type: "leap"` | Leap |
| `effects` with `type: "rally_forward"` | Rally |
| `effects` with `type: "deploy_self"` | Deploy |
| `effects` with `type: "grant_dark_matter"` | Dark Matter |
| `effects` with `trigger: "on_play"` (minion) | Summon |
| `effects` with `trigger: "on_death"` | Death |
| `effects` with `trigger: "passive"` | Passive |
| `activated_ability.effect_type: "conjure_*"` | Conjure |
| `summon_sacrifice_tribe` present | Cost (sacrifice cost) |

### Pattern 3: Cross-Link Rendering
**What:** Cards that reference other cards (tutor_target, transform_options, promote_target, activated_ability.summon_card_id) should render those references as wikilinks in the rules text.
**Cards with cross-links (6 total):**
- Blue Diodebot -> tutors Red Diodebot
- Green Diodebot -> tutors Blue Diodebot  
- Red Diodebot -> tutors Green Diodebot
- Giant Rat -> promotes to Rat (on death)
- Reanimated Bones -> transforms to Pyre Archer / Grave Caller / Fallen Paladin
- Ratchanter -> conjures Rat (activated ability)

**Implementation:** Build rules text that includes `[[Card:Target_Name|Target Name]]` wikilinks. Need a card_id-to-name lookup map built from all card JSONs at sync time.

```python
def build_card_name_map(cards_dir: Path) -> dict[str, str]:
    """Build card_id -> display name map for cross-linking."""
    name_map = {}
    for path in cards_dir.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        name_map[data["card_id"]] = data["name"]
    return name_map

def card_id_to_wikilink(card_id: str, name_map: dict[str, str]) -> str:
    name = name_map.get(card_id, card_id.replace("_", " ").title())
    return f"[[Card:{name}|{name}]]"
```

### Pattern 4: Idempotent Upsert
**What:** Compare current page text to generated text before editing. Skip if identical.
**Already demonstrated:** `create_sample_card.py` does this with `_same_text()` comparing `page.text()` to expected wikitext (rstrip-normalized).

```python
def upsert_card_page(site, page_title: str, wikitext: str, dry_run: bool = False) -> str:
    """Returns 'created', 'updated', 'unchanged', or 'dry-run'."""
    page = site.pages[page_title]
    if dry_run:
        return "dry-run:create" if not page.exists else "dry-run:update"
    if not page.exists:
        page.edit(wikitext, summary="sync card from data/cards/*.json")
        return "created"
    if page.text().rstrip() == wikitext.rstrip():
        return "unchanged"
    page.edit(wikitext, summary="sync card from data/cards/*.json")
    return "updated"
```

### Pattern 5: Art Upload via mwclient
**What:** Upload PNG files using `site.upload()`.
**API (verified from mwclient source):**

```python
def upload_card_art(site, card_id: str, art_dir: Path, dry_run: bool = False) -> str:
    """Upload card art PNG. Returns 'uploaded', 'exists', 'no-art', or 'dry-run'."""
    art_path = art_dir / f"{card_id}.png"
    if not art_path.exists():
        return "no-art"
    if dry_run:
        return "dry-run"
    filename = f"{card_id}.png"  # destination filename (no File: prefix)
    description = f"Card art for [[Card:{card_name}]]."
    try:
        with open(art_path, "rb") as f:
            site.upload(
                file=f,
                filename=filename,
                description=description,
                ignore=True,  # overwrite if exists
                comment="sync card art from src/grid_tactics/server/static/art/",
            )
        return "uploaded"
    except Exception:
        # mwclient raises errors.FileExists if ignore=False
        return "error"
```

**Key details:**
- `filename` parameter does NOT include `File:` prefix
- `ignore=True` suppresses warnings about existing files (allows overwrite)
- `description` becomes the wikitext on the `File:` page
- File must be opened in binary mode (`'rb'`)
- Template:Card references it as `[[File:{card_id}.png|280px|center|link=]]`

### Anti-Patterns to Avoid
- **Don't use CardLoader for wiki sync:** CardLoader converts to IntEnums and frozen dataclasses. Wiki sync needs raw string values from JSON. Read JSON directly with `json.load()`.
- **Don't hard-code keywords per card:** Derive from JSON structure. Hard-coded keywords (like Phase 1 sample did) drift from actual card data.
- **Don't paginate category checks with #ask:** Use `site.categories['Cards']` to count members via mwclient's category API, not SMW ask queries.
- **Don't upload art before checking if file exists on wiki:** Use `ignore=True` to overwrite, but skip upload entirely if no local art file exists (19 of 34 cards have no art yet).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Wiki API auth | Custom HTTP client | `wiki/sync/client.py` `get_site()` | Already handles URL parsing, bot login, MW_API_PATH for Railway |
| Page comparison | Custom diff logic | `page.text().rstrip() == expected.rstrip()` | MediaWiki strips trailing whitespace; rstrip normalization is sufficient |
| File upload | MediaWiki API calls | `site.upload(file, filename, ...)` | mwclient handles multipart upload, chunking, token management |
| Category membership count | `#ask` queries | `len(list(site.categories['Cards']))` | Direct API is faster and doesn't depend on SMW job queue |
| SMW property annotations | Manual `[[Property::Value]]` in sync script | Template:Card handles all annotations | The template already emits all 15+ SMW annotations via `{{#if}}` guards |

**Key insight:** Template:Card already does the heavy lifting for SMW annotations. The sync script only needs to generate the correct Template:Card invocation with the right field values. The template handles `[[Name::...]]`, `[[CardType::...]]`, `[[Element::...]]`, `[[Cost::...]]`, etc., and categories.

## Common Pitfalls

### Pitfall 1: SMW Job Queue Delay
**What goes wrong:** After creating/editing pages, SMW property values aren't immediately queryable via `#ask` or `Special:Browse`.
**Why it happens:** SMW uses a deferred job queue to process semantic annotations. On Railway's single-container setup, jobs may lag.
**How to avoid:** After bulk sync, run `php maintenance/runJobs.php` on the Railway container, or accept a delay. For verification, add a brief wait or retry loop when checking Category membership counts.
**Warning signs:** `Special:Browse` shows stale or empty properties right after sync.

### Pitfall 2: Cards Without Art (19 of 34)
**What goes wrong:** Template:Card shows a broken image for cards without uploaded art.
**Why it happens:** Template currently uses `[[File:{{{art|CardBack.png}}}|280px|center|link=]]` which falls back to `CardBack.png` if `art` param is empty, but the sync script might pass `card_id.png` even when no art exists.
**How to avoid:** Either (a) only pass the `art` parameter when the PNG exists locally, or (b) upload a `CardBack.png` placeholder image and let Template:Card fall back to it. Option (b) is better -- upload a generic card back once, then Template:Card's existing default works.
**Warning signs:** Broken image icons on card pages.

### Pitfall 3: Page Title Naming Convention
**What goes wrong:** Inconsistent page titles break cross-links.
**Why it happens:** Card names have spaces, mixed case. Page titles are case-sensitive in MediaWiki (first letter is auto-capitalized, rest is exact).
**How to avoid:** Use `Card:{display_name}` as the page title consistently. E.g., `Card:Ratchanter`, `Card:Blue Diodebot`, `Card:Dark Matter Infusion`. Build the name map from JSON `name` fields and always use it for cross-links.
**Warning signs:** Red (broken) wikilinks on card pages.

### Pitfall 4: Wikitext Special Characters in Rules Text
**What goes wrong:** Rules text containing `|`, `=`, `{{`, `}}`, `[[`, `]]` breaks template parsing.
**Why it happens:** MediaWiki interprets these as template/link syntax.
**How to avoid:** Current card rules text is synthesized from effect data and doesn't contain wiki markup. But if future cards have raw rules_text with pipes, wrap in `<nowiki>` or use `{{!}}` for pipe. For now, this is LOW risk since rules text is generated, not raw.
**Warning signs:** Garbled template rendering, missing fields.

### Pitfall 5: File Upload Permissions
**What goes wrong:** `site.upload()` fails with permission errors.
**Why it happens:** Bot account may not have `upload` right. MediaWiki's default `$wgEnableUploads` may be false.
**How to avoid:** Verify `$wgEnableUploads = true;` in LocalSettings.php on Railway. Verify bot user has `bot` and `upload` group membership. The Phase 2 bot account may need group adjustment.
**Warning signs:** `mwclient.errors.InsufficientPermission` on upload calls.

### Pitfall 6: Category Name Mismatch
**What goes wrong:** Template uses `[[Category:Cards]]` (plural) but success criteria says "Category:Card" (singular).
**Why it happens:** Template:Card.wiki line 66 says `[[Category:Cards]]` with an 's'.
**How to avoid:** Decide on one name and stick with it. The template currently uses `Cards` (plural). Either update the template to `Card` (matching the success criteria) or update the success criteria. Recommend: update template to `[[Category:Card]]` to match the success criteria wording.
**Warning signs:** Category count check fails because checking wrong category name.

## Code Examples

### Complete card_to_wikitext for a Minion
```python
# Input: data/cards/minion_ratchanter.json
# Output:
"""
{{Card
| name     = Ratchanter
| type     = Minion
| element  = Dark
| tribe    = Mage/Rat
| cost     = 4
| attack   = 15
| hp       = 30
| range    = 0
| rules    = '''Active:''' Pay 2 mana to conjure a [[Card:Rat|Rat]] and buff it.
| keywords = Active, Conjure, Melee
| art      = ratchanter.png
| patch    = 0.4.2
| stable_id= ratchanter
| deckable = true
}}
"""
```

### Complete card_to_wikitext for a Magic card
```python
# Input: data/cards/magic_fireball.json
# Output:
"""
{{Card
| name     = Fireball
| type     = Magic
| element  = Fire
| cost     = 3
| rules    = Deal 40 damage to a target.
| keywords = Deal
| art      = fireball.png
| patch    = 0.4.2
| stable_id= fireball
| deckable = true
}}
"""
```

### Cross-link example: Reanimated Bones (transform)
```python
# Rules text with wikilinks:
# "'''Transform:''' Pay 2 mana -> [[Card:Pyre Archer|Pyre Archer]],
#  Pay 3 mana -> [[Card:Grave Caller|Grave Caller]], 
#  Pay 4 mana -> [[Card:Fallen Paladin|Fallen Paladin]]."
```

### Cross-link example: Blue Diodebot (tutor)
```python
# Rules text with wikilink:
# "'''Summon:''' Search your deck for [[Card:Red Diodebot|Red Diodebot]] and add it to your hand."
```

### CLI Usage Pattern
```python
# sync_wiki.py --all-cards         Upsert all 34 cards + upload art
# sync_wiki.py --card ratchanter   Upsert single card
# sync_wiki.py --all-cards --dry-run  Show what would change
# sync_wiki.py --upload-art        Upload all art PNGs only
# sync_wiki.py --verify            Check Category:Card count matches JSON count
```

### mwclient Category Count Verification
```python
def verify_card_count(site, expected: int) -> bool:
    """Verify Category:Card membership count matches expected."""
    cat = site.categories["Card"]  # or "Cards" -- must match template
    actual = sum(1 for _ in cat)
    print(f"Category:Card: {actual} pages (expected {expected})")
    return actual == expected
```

## Data Model Summary

### Card Count: 34 total
- 26 minions, 5 magic, 3 react
- 15 have art PNGs, 19 do not

### Cards with Cross-Links (6 cards)
| Card | Link Type | Target(s) |
|------|-----------|-----------|
| Blue Diodebot | tutor | Red Diodebot |
| Green Diodebot | tutor | Blue Diodebot |
| Red Diodebot | tutor | Green Diodebot |
| Giant Rat | promote | Rat |
| Reanimated Bones | transform | Pyre Archer, Grave Caller, Fallen Paladin |
| Ratchanter | conjure (activated) | Rat |

### Cards with Special Mechanics
| Card | Mechanic | JSON Field |
|------|----------|------------|
| Giant Rat | Unique | `unique: true` |
| Grave Caller, Fallen Paladin | Non-deckable | `deckable: false` |
| Surgefed Sparkbot, Dark Sentinel | Minion with react | `react_condition`, `react_effect` |
| RGB Lasercannon | Sacrifice cost | `summon_sacrifice_tribe: "Robot"` |
| Ratchanter | Activated ability | `activated_ability: {...}` |

### Effect Types Across All Cards (15 unique)
`buff_health`, `burn`, `conjure_rat_and_buff`, `damage`, `dark_matter_buff`, `deploy_self`, `destroy`, `grant_dark_matter`, `heal`, `leap`, `negate`, `passive_heal`, `promote`, `rally_forward`, `tutor`

### JSON Field -> Template:Card Parameter Mapping
| JSON Field | Template Param | Notes |
|------------|---------------|-------|
| `name` | `name` | Direct |
| `card_type` | `type` | Capitalize: "minion" -> "Minion" |
| `element` | `element` | Capitalize: "dark" -> "Dark" |
| `tribe` | `tribe` | Direct (may contain "/": "Mage/Rat") |
| `mana_cost` | `cost` | Direct number |
| `attack` | `attack` | Minions only; omit for magic/react |
| `health` | `hp` | Minions only; omit for magic/react |
| `range` | `range` | Minions only |
| (derived) | `rules` | Built from effects, abilities, cross-links |
| `flavour_text` | `flavor` | Note: JSON uses British "flavour", template uses American "flavor" |
| (derived) | `keywords` | Comma-separated, derived from card structure |
| `card_id` + ".png" | `art` | Only if art file exists; else omit for CardBack.png fallback |
| (hardcoded) | `patch` | Current game version |
| `card_id` | `stable_id` | Direct |
| `deckable` | `deckable` | Default true; explicit false for non-deckable cards |

## Template:Card Enhancement Needs

The existing Template:Card (from Phase 1) is functional but may need minor updates:

1. **Category name:** Currently `[[Category:Cards]]` -- consider changing to `[[Category:Card]]` to match success criteria. Also adds `[[Category:{type}s]]` (e.g., "Minions") and `[[Category:{element} cards]]`.

2. **Art fallback:** Already handles missing art with `{{{art|CardBack.png}}}` default. Works if `CardBack.png` is uploaded as a placeholder.

3. **No changes needed for SMW annotations:** Template already annotates all properties from schema.py via `{{#if}}` guards and `{{#arraymap}}` for keywords.

4. **Stat labels:** Template shows "ATK" and "HP" text labels. This is fine for wiki display even though in-game uses emoji glyphs.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual card pages | Auto-generated from JSON | Phase 3 (now) | All 34 cards synced from source of truth |
| Hard-coded keywords | Derived from JSON structure | Phase 3 (now) | Keywords always match actual card mechanics |
| No art on wiki | Art uploaded via API | Phase 3 (now) | Visual card pages |

## Open Questions

1. **CardBack.png placeholder:** Should a generic card-back image be uploaded for the 19 cards without art? The template defaults to `CardBack.png` but that file may not exist on the wiki yet. **Recommendation:** Upload a simple placeholder; it is a one-time task.

2. **Rules text generation quality:** The `build_rules_text()` function must synthesize human-readable rules from structured effect data. The Phase 1 sample just used the activated_ability field. For Phase 3, every effect type needs a readable sentence. Some cards have multiple effects (Dark Drain: damage + heal). **Recommendation:** Build a `EFFECT_TYPE_TEMPLATES` dict mapping effect types to sentence patterns, e.g., `"damage": "Deal {amount} damage to a target."`, `"heal": "Restore {amount} HP to {target}."`.

3. **Category:Card vs Category:Cards:** The template says `Cards`, the success criteria says `Card`. This must be resolved before sync. **Recommendation:** Update template to `Card` (singular) to match MediaWiki convention and success criteria.

4. **File upload enabled on Railway?** Need to verify `$wgEnableUploads = true` on the Railway deployment. If not, this is a blocker. **Recommendation:** Check early in Phase 3 execution.

5. **`patch` field value:** What version should be set for initial card sync? The Phase 1 sample used "0.4.2". Need to read `VERSION.json` or hard-code current version. **Recommendation:** Read from `src/grid_tactics/server/static/VERSION.json` if it exists, else use a CLI argument.

## Sources

### Primary (HIGH confidence)
- `wiki/sync/templates/Card.wiki` -- Template:Card wikitext with SMW annotations (local file, read directly)
- `wiki/sync/create_sample_card.py` -- Phase 1 wikitext generation pattern (local file)
- `wiki/sync/client.py` -- mwclient auth factory (local file)
- `wiki/sync/schema.py` -- SMW property schema with 25 properties + 5 effect subproperties (local file)
- `data/cards/*.json` -- All 34 card JSON definitions (local files, read directly)
- mwclient `site.upload()` docstring -- verified via `help(mwclient.Site.upload)` in local Python env
- [mwclient file upload docs](https://github.com/mwclient/mwclient/blob/master/docs/source/user/files.rst)

### Secondary (MEDIUM confidence)
- [mwclient upload example](https://github.com/mwclient/mwclient/blob/master/examples/upload.py) -- GitHub example
- [mwclient API reference](https://mwclient.readthedocs.io/en/latest/_modules/mwclient/client.html)

### Tertiary (LOW confidence)
- File upload permissions on Railway -- needs runtime verification

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all tools already in use from Phase 1-2
- Architecture: HIGH -- patterns demonstrated by existing create_sample_card.py
- Wikitext generation: HIGH -- Template:Card already works, mapping is clear
- Cross-links: HIGH -- all 6 cross-link relationships identified from JSON data
- Keyword derivation: MEDIUM -- mapping is logical but needs testing against glossary expectations
- Art upload: MEDIUM -- mwclient API is documented but Railway upload permissions unverified
- Pitfalls: HIGH -- based on direct code inspection of template and existing scripts

**Research date:** 2026-04-09
**Valid until:** 2026-05-09 (stable domain, card set may grow)
