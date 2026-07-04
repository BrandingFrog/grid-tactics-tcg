"""Opus guard — blocks prompts when the session is running on an Opus model.

The user pays usage credits when a session runs on Opus; they want a loud
warning instead of silently burning credits. Hooks cannot switch the model,
so this does the strongest thing available: it BLOCKS the prompt with an
explanation until the user either switches model (/model) or explicitly
allows Opus by creating the bypass file `.claude/allow-opus`.

Registered in .claude/settings.json under UserPromptSubmit.
"""
import json
import os
import sys


def last_assistant_model(transcript_path: str) -> str:
    """Scan the tail of the transcript for the most recent assistant model."""
    try:
        size = os.path.getsize(transcript_path)
        with open(transcript_path, "rb") as f:
            f.seek(max(0, size - 400_000))
            tail = f.read().decode("utf-8", errors="ignore")
    except OSError:
        return ""
    model = ""
    for line in tail.splitlines():
        if '"type":"assistant"' not in line.replace(" ", ""):
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        m = (entry.get("message") or {}).get("model", "")
        if m:
            model = m  # keep the LAST one seen
    return model


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return

    cwd = data.get("cwd") or os.getcwd()
    if os.path.exists(os.path.join(cwd, ".claude", "allow-opus")):
        return  # explicit bypass

    model = last_assistant_model(data.get("transcript_path") or "")
    if "opus" in model.lower():
        print(json.dumps({
            "decision": "block",
            "reason": (
                "OPUS GUARD: this session is running on '" + model + "', which "
                "draws from paid usage credits. Run /model to switch to your "
                "included model (e.g. Fable 5), then resend your message. To "
                "deliberately allow Opus here, create the file .claude/allow-opus "
                "and resend."
            ),
        }))


if __name__ == "__main__":
    main()
