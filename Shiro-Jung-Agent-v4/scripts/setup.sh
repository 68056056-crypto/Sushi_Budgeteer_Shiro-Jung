#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/python scripts/install_opa.py
.venv/bin/python -m sushi_budgeteer.database status
.venv/bin/python scripts/run_checks.py
