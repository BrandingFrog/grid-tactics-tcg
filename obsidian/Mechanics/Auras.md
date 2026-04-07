# Auras

Passive effects emitted by a minion while it lives.

## Examples
- [[Cards/Emberplague Rat]] — burns adjacent enemies (passive [[Burn]])
- [[Cards/Ratchanter]] — buffs friendly Rats (see bug fix history)
- [[Cards/Fallen Paladin]] — passive heal to owner each turn

## Implementation
- Triggered each turn-start tick in `effect_resolver.py`.
- Tensor parity is critical — see [[Architecture/Tensor Engine]].

## Related
- [[Status Effects]] · [[Bugs/_index|emberplague redesign]]
