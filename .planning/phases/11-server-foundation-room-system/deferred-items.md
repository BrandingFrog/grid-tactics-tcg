# Deferred Items - Phase 11

## Pre-existing Test Failures (Out of Scope)

These test failures exist before Phase 11 changes and are caused by prior modifications to game constants (MIN_DECK_SIZE 40->30, STARTING_HP 20->100, card count 19->21, etc.) without updating the corresponding test assertions.

Affected files:
- tests/test_enums.py: MIN_DECK_SIZE, MAX_STAT, MAX_EFFECT_AMOUNT, STARTING_HP assertions
- tests/test_card_library.py: card count assertion (19 vs 21)
- tests/test_game_state.py: starting hand size (5 vs 3) and deck size assertions
- tests/test_legal_actions.py: assertions depending on old deck/hand sizes
- tests/test_game_loop.py: 40-card deck builder assertions (MIN_DECK_SIZE changed to 30)
- tests/test_action_resolver.py: ranged attack distance assertion

**Action needed:** Update test assertions to match current game constants.
