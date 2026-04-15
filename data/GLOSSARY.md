# Keyword Glossary

This file is the source of truth for all card keywords and their descriptions.
Update this file and the matching `KEYWORD_GLOSSARY` in `src/grid_tactics/server/static/game.js` will be kept in sync.

## Trigger Keywords

| Keyword | Description |
|---------|-------------|
| Summon | This effect activates when the minion is played onto the board. |
| Death | This effect activates when the minion is destroyed. |
| Move | This effect activates when the minion moves forward. |
| Attack | This effect activates when the minion attacks. |
| Damaged | This effect activates when the minion takes damage. |
| Passive | This effect triggers automatically every turn. |
| Active | This ability can be used once per turn instead of attacking. |

## Mechanic Keywords

| Keyword | Description |
|---------|-------------|
| Unique | Only one copy of this minion can exist on the board per player at a time. |
| Melee | Attacks adjacent orthogonal tiles (1 tile). |
| Range X | Attacks X+1 tiles orthogonally, X tiles diagonally. |
| Tutor | Search your deck for a specific card and add it to your hand. |
| Promote | When this minion dies, specified minion transforms into this card. |
| Rally | When this minion moves, all other friendly copies of it also advance forward. |
| Negate | Cancel the effect of an opponent's spell or ability. |
| React | This card can be played during the opponent's turn in response to their action. |
| Destroy | Remove a target minion from the board regardless of its 🤍. |
| Transform | Pay mana to transform this minion into another form. |
| Cost | An additional requirement or modifier that changes how much you pay to play this card. |
| Discard | Send a card from your hand to the Exhaust Pile. |
| Exhaust | Send a card to the Exhaust Pile. |
| Heal | Restore 🤍 to a target. |
| Deal | Deal damage to a target. |
| Burn | Applies Burning to affected enemies. A burning minion takes 5🤍 damage at the start of its owner's turn. Persists until the minion dies. |
| Burning | A burning minion takes 5🤍 damage at the start of its owner's turn. Burning is a boolean status — re-applying it does nothing. It persists until the minion dies. |
| Dark Matter | A stacking resource used by Dark Mages. Buffs and costs scale with accumulated stacks. |
| Leap | If blocked by an enemy, jump over to the next available tile. Cannot leap allies. If all tiles ahead are enemy-occupied, enables sacrifice. |
| Conjure | Summon a card from your deck directly to the board. |
| Revive | Summon a card from the Grave to the board. |
