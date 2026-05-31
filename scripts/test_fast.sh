#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

PYTHON_BIN="${PYTHON:-.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python"
fi

"$PYTHON_BIN" -m ruff check .

if [[ "$#" -gt 0 ]]; then
  "$PYTHON_BIN" -m unittest -v "$@"
else
  "$PYTHON_BIN" -m unittest -v \
    tests.test_app.AppSmokeTests \
    tests.test_app.ConfigurationTests \
    tests.test_scripts \
    tests.test_provider_collectors \
    tests.test_telegram_digests \
    tests.test_telegram_details \
    tests.test_telegram_disclaimers \
    tests.test_telegram_preferences \
    tests.test_telegram_watchlists \
    tests.test_research_labels
fi
