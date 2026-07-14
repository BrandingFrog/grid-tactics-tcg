# Keyword Glossary

This file is the source of truth for all card keywords and their descriptions.
Update this file and the matching `KEYWORD_GLOSSARY` in `src/grid_tactics/server/static/js/03-deck-builder.js` will be kept in sync.

## Trigger Keywords

| Keyword | Description |
|---------|-------------|
| Summon | Triggers when the minion is played onto the board. |
| Death | Triggers when the minion is destroyed. |
| Move | Triggers when the minion moves forward. |
| Attack | Triggers when the minion attacks. |
| Damaged | Triggers when the minion takes damage. |
| Start | Triggers in the Rally Phase, before any action on the owner's turn. |
| End | Triggers in the Decay Phase, after all actions on the owner's turn. |
| Rally | The Rally Phase is the start-of-turn window in which positive once-per-turn effects trigger. |
| Decay | The Decay Phase is the end-of-turn window in which negative once-per-turn effects, including Burning damage, trigger. |
| Passive | Always in effect while the minion is on the board. |
| Active | May be used once per turn instead of attacking. |
| Discarded | Triggers when the card is discarded from hand by a Cost or an opponent's effect. |

## Mechanic Keywords

| Keyword | Description |
|---------|-------------|
| Unique | Each player may have at most one copy of this minion on the board at a time. |
| Melee | Attacks orthogonally adjacent tiles (1 tile). |
| Range X | Attacks up to X+1 tiles orthogonally and up to X tiles diagonally. |
| Tutor | Search your deck for a specified card and add it to your hand. |
| Promote | When this minion dies, the specified minion transforms into this card. |
| March | When this minion moves, all other friendly copies of it also advance forward. |
| Negate | Cancels the effect of an opponent's spell or ability. |
| React | May be played during the opponent's turn in response to their action. |
| Destroy | Removes the target minion from the board regardless of its 🤍. |
| Transform | Pay mana to transform this minion into another form. |
| Cost | An additional requirement or modifier on what you pay to play this card. |
| Discard | Sends a card from your hand to the Exhaust Pile. |
| Exhaust | Sends a card to the Exhaust Pile; a card drawn while your hand is full is exhausted, revealed. |
| Heal | Restores 🤍 to a target. |
| Deal | Deals damage to a target. |
| Burn | Applies Burning to the affected minions: a Burning minion takes 5🤍 in its owner's Decay Phase. |
| Burning | A Burning minion takes 5🤍 in its owner's Decay Phase. Burning does not stack — re-applying it has no effect — and persists until the minion dies. |
| Dark Matter | A stacking player resource pool, visible to both players. Each gain adds +1 per friendly Dark Mage on the board (a Dark-element minion with the Mage tribe, composite tribes included); effects that read the pool do not spend it. |
| Leap | If blocked by an enemy, the minion jumps over it to the next available tile; allies cannot be leapt. If every tile ahead is enemy-occupied, the minion may Sacrifice. |
| Conjure | Summons a card from your deck directly to the board. |
| Sacrifice | Removes a friendly minion from the game — from the opponent's back row, or by Leaping along an all-enemy path — dealing its full 🗡️ as damage to the opponent. "Sacrifice:" effects trigger when that card is sacrificed. |
| Cleanse | Removes all debuffs from the minion: Burning ends and negative 🗡️/🤍 marks reset to 0. Positive buffs remain; lost 🤍 is not restored. |
| Untargetable | Cannot be chosen as the target of a magic card's single-target effect; board-wide magic, minions, and Reacts still affect it. |
| Revive | Summons minions from the Grave to the board; the player chooses each grave card eligible under the reviving card's text and its deployment tile (melee: any tile on the owner's side; ranged: back row). A revived minion counts as summoned and its Summon effect triggers. |
| Draw | Moves the top card of your deck to your hand; if your hand is full (10 cards), the drawn card is sent to the Exhaust Pile, revealed, instead. |
| Handshake | When a REST immediately follows the opponent's REST, both players gain +1 mana and draw 1 at the end of that turn; the REST counter then resets — Handshakes do not chain. PASS or any paid action declines an open offer. |
