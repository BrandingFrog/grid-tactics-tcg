# Card definitions

Each JSON file defines one card and is loaded by `CardLibrary.from_directory()`.

Keep card IDs stable. Player-facing text must follow `data/GLOSSARY.md`, and keyword changes must also be mirrored in `src/grid_tactics/server/static/js/03-deck-builder.js`.

Run the card validation and text tests after changes:

```text
pytest tests/test_card_loader.py tests/test_card_library.py tests/test_card_text_rules.py -q
```
