#!/usr/bin/env bash
# One independent hosted QA shard. scripts/ci.sh stays the complete local QA (it is part of the
# frozen A02 experiment source set and must not change); this runs the same checks split into
# concurrent jobs. Static checks run once, in the fast shard.
set -euo pipefail

if [[ $# -ne 1 || ! "$1" =~ ^(fast|controller|integration)$ ]]; then
    printf 'usage: %s fast|controller|integration\n' "$0" >&2
    exit 2
fi
shard="$1"

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
uv run python scripts/test_shards.py --check
if [[ "$shard" == "fast" ]]; then
    ./scripts/qa-fast.sh
    uv run mypy .
    uv run python scripts/repository_policy.py
fi
mapfile -t shard_modules < <(uv run python scripts/test_shards.py "$shard")
if [[ ${#shard_modules[@]} -eq 0 ]]; then
    printf 'TEST_SHARDS=EMPTY shard=%s\n' "$shard" >&2
    exit 1
fi
uv run --group tokenizer-check pytest --durations=15 "${shard_modules[@]}"

snapshot_tracked_state "$state_dir/after"
if ! cmp -s "$state_dir/before/index.diff" "$state_dir/after/index.diff" \
    || ! cmp -s "$state_dir/before/worktree.diff" "$state_dir/after/worktree.diff"; then
    printf 'QA_TRACKED_MUTATION=DETECTED\n' >&2
    exit 1
fi

if [[ "$shard" == "fast" ]]; then
    printf '%s\n' 'QA_RUFF=PASS' 'QA_FORMAT=PASS' 'QA_MYPY=PASS' 'REPOSITORY_POLICY=PASS'
fi
printf '%s\n' "QA_PYTEST=PASS shard=$shard" 'QA_TRACKED_MUTATION=NONE'
