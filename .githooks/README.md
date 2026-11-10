# Optional upstream Git hooks

> These inherited development hooks are not needed to run the ClaimDocs browser demo. See the current [application README](../README.md) for setup. Hook configuration is per clone.

# Git hooks

This directory contains project-wide git hooks that are **tracked in the
repo** (unlike `.git/hooks/`, which is per-clone). Git is configured to
use this directory via `core.hooksPath`.

## Setup (fresh clone)

After cloning the repo, run:

```bash
git config core.hooksPath .githooks
```

That's it. Git will now use the hooks in this directory.

## Active hooks

### `pre-commit` — block build artifacts

Scans the staged file list for known build-artifact patterns
(`site/`, `dist/`, `__pycache__/`, `.pyc`, `.egg-info/`, etc.) and
aborts the commit if any are found.

**Why**: `git add -A` with a path filter (e.g. `git add -A site/`)
overrides `.gitignore` and stages ignored files. This hook is the
last line of defense so that a 4 MB mkdocs build never accidentally
lands on `main`.

**Bypass**: `git commit --no-verify` for one-off cases (e.g., you
really do want to commit a specific file in `dist/`).

## Adding new hooks

Drop an executable file in this directory. Git will pick it up
automatically once `core.hooksPath` points here.
