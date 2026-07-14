# Git hooks

Repository-managed hooks enforce local pre-commit checks and synchronize planning state after commits. Enable them with:

```text
git config core.hooksPath .githooks
```

Hooks must remain fast, deterministic, and safe when optional local tools are missing.
