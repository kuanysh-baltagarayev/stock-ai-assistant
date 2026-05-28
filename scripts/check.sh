#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

PYTHON_BIN="${PYTHON:-.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python"
fi

"$PYTHON_BIN" -m ruff check .
"$PYTHON_BIN" -m coverage run -m unittest discover -v
"$PYTHON_BIN" -m coverage report
"$PYTHON_BIN" -m compileall app scripts tests
