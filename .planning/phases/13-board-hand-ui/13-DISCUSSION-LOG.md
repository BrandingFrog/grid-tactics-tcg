# Phase 13: Board & Hand UI - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-05
**Phase:** 13-board-hand-ui
**Areas discussed:** Page structure, Board layout & style, Card design in hand, Deck builder flow

---

## Page Structure

| Option | Description | Selected |
|--------|-------------|----------|
| New tab in dashboard | Add "Play" tab alongside existing tabs. Same page. | ✓ |
| Standalone page | Separate HTML file served by Flask. | |
| You decide | Claude picks | |

**User's choice:** New tab in dashboard
**Notes:** None.

---

## Hosting

| Option | Description | Selected |
|--------|-------------|----------|
| Flask serves everything | One server, one URL. Game UI + dashboard. | ✓ (Claude's discretion) |
| Dashboard on Vercel, game on Flask | Two deployments. | |

**User's choice:** You decide → Claude selected Flask serves everything (simplest for PvP testing).

---

## Board Perspective

| Option | Description | Selected |
|--------|-------------|----------|
| Flip for P2 | Each player sees themselves at bottom. Standard. | ✓ |
| Fixed orientation | Both players see same grid. | |

**User's choice:** Yes, flip for P2

---

## Minion Display

| Option | Description | Selected |
|--------|-------------|----------|
| Compact card-in-cell | Card name, ATK/HP, attribute border, owner tint. | ✓ |
| Icon + stats | Minimal letter/icon with numbers. | |

**User's choice:** Compact card, adapted from YGO GitHub repo card style.
**Notes:** User has a private repo `BrandingFrog/ygo` with a Roblox card renderer (CardFrameBuilder.luau). Wants to reuse that visual style for Grid Tactics.

---

## Card Style in Hand

| Option | Description | Selected |
|--------|-------------|----------|
| Full YGO adaptation | 2:3 cards, type-colored bg, attribute circle, ATK/HP, mana badge. No art. | ✓ |
| Simplified version | Same colors but compact, skip art area. | |

**User's choice:** Full YGO adaptation
**Notes:** Reference: `BrandingFrog/ygo/src/client/CardFrameBuilder.luau` and `Constants.luau`.

---

## Deck Builder Flow

| Option | Description | Selected |
|--------|-------------|----------|
| Before room creation | Build deck first, then create/join. | ✓ (base) |
| In the lobby | Build after joining room. | |

**User's choice:** Build deck before room creation, PLUS save slots and lobby deck selection.
**Notes:** "1 but also have a few save slots and select on the lobby before readying." Save to localStorage, select in lobby.

---

## Claude's Discretion

- CSS Grid dimensions and spacing
- Hand card layout (scroll vs fixed)
- Mana/HP widget design
- Lobby UI layout
- Dashboard tab integration
- Responsive behavior

## Deferred Ideas

None
