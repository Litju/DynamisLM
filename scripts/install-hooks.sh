#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

git config --local core.hooksPath .githooks
[[ "$(git config --get core.hooksPath)" == ".githooks" ]]
[[ -x .githooks/pre-commit ]]
[[ -x .githooks/pre-push ]]

printf '%s\n' \
    'HOOKS_PATH=.githooks' \
    'PRE_COMMIT=READY' \
    'PRE_PUSH=READY'
