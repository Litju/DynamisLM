#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

state_dir="$(mktemp -d)"
trap 'rm -rf "$state_dir"' EXIT

snapshot_tracked_state() {
    local destination="$1"
    mkdir -p "$destination"
    git diff --no-ext-diff --binary --no-renames --cached -- >"$destination/index.diff"
    git diff --no-ext-diff --binary --no-renames -- >"$destination/worktree.diff"
}

snapshot_tracked_state "$state_dir/before"

uv sync --frozen
./scripts/qa-fast.sh
uv run mypy .
uv run python scripts/repository_policy.py
uv run pytest

snapshot_tracked_state "$state_dir/after"
if ! cmp -s "$state_dir/before/index.diff" "$state_dir/after/index.diff" \
    || ! cmp -s "$state_dir/before/worktree.diff" "$state_dir/after/worktree.diff"; then
    printf 'QA_TRACKED_MUTATION=DETECTED\n' >&2
    exit 1
fi

printf '%s\n' \
    'QA_RUFF=PASS' \
    'QA_FORMAT=PASS' \
    'QA_MYPY=PASS' \
    'REPOSITORY_POLICY=PASS' \
    'QA_PYTEST=PASS' \
    'QA_TRACKED_MUTATION=NONE'
