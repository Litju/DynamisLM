#!/usr/bin/env bash
set -euo pipefail

if [[ $# -gt 0 && "$1" == "--staged" ]]; then
    git diff --cached --check
    shift
fi

if [[ $# -ne 0 ]]; then
    printf 'usage: %s [--staged]\n' "$0" >&2
    exit 2
fi

uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
