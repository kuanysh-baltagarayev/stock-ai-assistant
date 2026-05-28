# AGENTS.md

## Role

This file is the repo-level working contract for agents continuing `stock-ai-assistant`.
Keep it short. Put the full development plan, discussion summary, open risks, and phase tracking in `PLAN.md`.

## Sources of Truth

- `README.md`: user-facing setup, run commands, and feature overview.
- `PLAN.md`: complete project plan, previously discussed decisions, current limits, and next implementation phases.
- Tests under `tests/`: executable evidence for API, persistence, CLI, and smoke behavior.

Do not delete `PLAN.md` unless its contents are moved to an equivalent tracked document.

## Current Goal

The user wants the project fully implemented as a practical MVP and does not want prior discussion or decisions lost.
When asked to continue, make concrete progress: inspect state, implement the next useful slice, verify it, update docs, and commit completed work.

## Working Rules

- Start with `git status --short` and inspect relevant files before changing code.
- Preserve user changes. Do not revert unrelated edits.
- Use `apply_patch` for manual edits.
- Prefer non-interactive git commands.
- Keep changes scoped, tested, documented, and committed.
- If the user asks for a commit, finish with an actual commit.
- Update `PLAN.md` when project scope, priorities, or known limits change.
- Update `AGENTS.md` only when agent workflow itself changes.

## Verification

Run these before calling implementation work complete:

```bash
scripts/check.sh
```

If development dependencies are missing, install `requirements-dev.txt` or fall back to:

```bash
.venv/bin/python -m unittest discover -v
.venv/bin/python -m compileall app scripts tests
```

If CLI behavior changes, add or update tests under `tests/`.
If API behavior changes, add or update `TestClient` coverage.

## Launch Commands

API:

```bash
python scripts/run_api.py --reload
python scripts/live_http_smoke.py
```

CLI scan:

```bash
python scripts/scan_market.py
python scripts/scan_market.py AAPL MSFT NVDA --json
```

Live smoke:

```bash
python scripts/live_smoke.py
```

Telegram bot:

```bash
python scripts/run_telegram_bot.py
python scripts/check_telegram.py
```
