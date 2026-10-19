#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python -m streamlit run app.py --server.headless true --browser.gatherUsageStats false
