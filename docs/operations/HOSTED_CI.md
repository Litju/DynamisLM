# Hosted CI operations

## Architecture

Local hooks provide developer feedback. GitHub-hosted `ubuntu-24.04` CI runs
the same full-QA command in a clean environment. The active `DynamisLM Main
Authority` ruleset makes the successful `ci` check the merge gate for `main`.

There is one workflow, one job, and one required check. CI runs for pull
requests targeting `main` and for pushes to `main`; it has no secrets, cache,
artifact upload, service container or deployment step.

## Local use

Install the repository-local hooks:

```bash
./scripts/install-hooks.sh
```

The installer is idempotent and sets only the local `core.hooksPath` to
`.githooks`. Fast checks can be run directly:

```bash
./scripts/qa-fast.sh
```

The staged pre-commit form also checks staged whitespace:

```bash
./scripts/qa-fast.sh --staged
```

Run the complete local gate before pushing:

```bash
./scripts/ci.sh
```

`ci.sh` runs `uv sync --frozen`, fast QA, mypy, the tracked-repository policy,
and pytest. It preserves unrelated local edits and fails if those QA commands
mutate the tracked index or worktree.

## Remote CI and ruleset

The pull-request workflow is the independent clean-environment verification.
The check name is exactly `ci`; it must be successful and up to date before a
pull request can update `main`. Read the workflow run and job steps when
diagnosing a failure:

```bash
gh pr checks <PR_NUMBER>
gh run list --workflow CI
gh run view <RUN_ID> --log-failed
gh run view <RUN_ID> --json jobs,headSha,status,conclusion
```

The ruleset is intentionally the only merge-enforcement layer for this mission:

```bash
gh api repos/Litju/DynamisLM/rulesets
gh api repos/Litju/DynamisLM/rulesets/<RULESET_ID>
```

## Action pins and Dependabot

Workflow Actions use full commit SHAs and same-line release comments. To
update a pin safely, inspect the official Action repository’s current stable
release, resolve its tag through the Git refs API, dereference annotated tags
to the commit object, verify the commit belongs to the intended repository,
update the SHA and release comment, and let the normal pull-request `ci` check
qualify the change. Do not replace a pin with a mutable tag.

Dependabot creates weekly updates only for GitHub Actions. Treat each update as
a normal pull request; do not auto-merge it.

## Repository policy and synthetic fixtures

The policy reads tracked paths from `git ls-files`, not arbitrary ignored local
files. It rejects data/model/checkpoint/corpus directories, large scientific
data extensions and secret-like files. `.env.example` is explicitly allowed.

CSV, XLSX and ZIP are allowed only as small, clearly synthetic fixtures under
`tests/fixtures/synthetic/` with an exact entry in
`.repo-policy/allowed-fixtures.txt`. The maximum size is 1 MiB. The allowlist
may remain empty while no controlled fixture exists. Real RES-63 source files
must never be added there.

## Scope boundaries

The Actions SHA policy and ruleset may be modified only through an explicit
future repository-governance issue. This mission has no self-hosted runner and
no CD because neither is needed for the current verification boundary.

RES-63 remains responsible for canonical dataset qualification and source/data
authority. RES-75 does not ingest or qualify a dataset and does not change
scientific formulas, numerical authority, serialization version or historical
hashes.
