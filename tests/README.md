# Test suite

Tests are grouped by the subsystem they exercise:

- Root `test_*.py` files cover the rules engine, cards, RL contracts, browser-source contracts, and cross-system integration.
- `server/` covers Flask-SocketIO events, authentication, rooms, decks, and multiplayer flow.
- `e2e/` contains browser-level journeys for critical user flows.
- `conftest.py` provides shared fixtures.

Run everything with `pytest tests/ -q`. During iteration, run the smallest relevant file first, then the full suite before deployment.
