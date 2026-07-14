# Browser client

The live game UI is intentionally framework-free and loads ordered CSS and JavaScript files from `game.html`.

- `css/` contains layered styles; `zz-overrides.css` is the final compatibility and hot-fix layer.
- `js/` contains numbered modules whose load order is significant.
- `art/` contains browser-served card and interface artwork.
- `sfx/` contains audio assets and their attribution file.

When adding a JavaScript module, update `game.html` explicitly and add a contract assertion in `tests/test_client_game_js.py`. Avoid renaming numbered files without updating every script reference.
