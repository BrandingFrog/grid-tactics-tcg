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
| Start | This effect triggers in the Rally Phase at the start of the owner's turn, before any actions. |
| End | This effect triggers in the Decay Phase at the end of the owner's turn, after all actions. |
| Rally | The Rally Phase is the start-of-turn window (after the auto-draw) where positive once-per-turn effects trigger. "Rally:" effects proc here. |
| Decay | The Decay Phase is the end-of-turn window where negative once-per-turn effects trigger. "Decay:" effects and Burning ticks proc here. |
| Passive | This effect is always active while the minion is on the board. |
| Active | This ability can be used once per turn instead of attacking. |
| Discarded | This effect triggers when the card is discarded from hand (via a Cost or opponent effect). |

## Mechanic Keywords

| Keyword | Description |
|---------|-------------|
| Unique | Only one copy of this minion can exist on the board per player at a time. |
| Melee | Attacks adjacent orthogonal tiles (1 tile). |
| Range X | Attacks X+1 tiles orthogonally, X tiles diagonally. |
| Tutor | Search your deck for a specific card and add it to your hand. |
| Promote | When this minion dies, specified minion transforms into this card. |
| March | When this minion moves, all other friendly copies of it also advance forward. |
| Negate | Cancel the effect of an opponent's spell or ability. |
| React | This card can be played during the opponent's turn in response to their action. |
| Destroy | Remove a target minion from the board regardless of its 🤍. |
| Transform | Pay mana to transform this minion into another form. |
| Cost | An additional requirement or modifier that changes how much you pay to play this card. |
| Discard | Send a card from your hand to the Exhaust Pile. |
| Exhaust | Send a card to the Exhaust Pile. Cards drawn while your hand is full are also exhausted, revealed. |
| Heal | Restore 🤍 to a target. |
| Deal | Deal damage to a target. |
| Burn | Applies Burning to the affected minions — usually enemies, but some cards burn their own minion (e.g. Eclipse Shade's Summon). |
| Burning | A burning minion takes 5🤍 in its owner's Decay Phase. Burning is a boolean status — re-applying it does nothing. It persists until the minion dies. |
| Dark Matter | A stacking resource used by Dark Mages. Buffs and costs scale with accumulated stacks. |
| Leap | If blocked by an enemy, jump over to the next available tile. Cannot leap allies. If all tiles ahead are enemy-occupied, enables sacrifice. |
| Conjure | Summon a card from your deck directly to the board. |
| Revive | Summon a card from the Grave to the board. |
| Draw | Draw cards from your deck to your hand. If your hand is full (10 cards), the drawn card is sent to the Exhaust Pile, revealed, instead. |
| Handshake | When a player passes and the opponent's previous action was also a pass, a Handshake occurs: at the end of that turn, both players gain +1 mana. A player whose mana is already full draws a card instead. The pass counter then resets — no chaining. |
