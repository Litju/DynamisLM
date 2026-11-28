#!/usr/bin/env bash
# Launch the RES-832 continuation campaign and keep a durable log (campaign scratch, not Git).
set -u
cd "$(dirname "$0")/.."
exec .venv/bin/python scripts/a1_colab.py launch 2>&1 | tee experiments/a1/.campaign/launch.log
