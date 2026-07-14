# Server tests

These tests exercise socket handlers and server-side multiplayer behavior, including pregame flow, room state, event reconciliation, AI preview handling, and player-safe state views.

Use the in-memory Flask-SocketIO test client where possible. Add an end-to-end browser test only when DOM behavior or timing cannot be validated at the event layer.
