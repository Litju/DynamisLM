# Hosted CI operations

## Architecture

Local hooks provide developer feedback. GitHub-hosted `ubuntu-24.04` CI runs
the same full-QA command in a clean environment. The active `DynamisLM Main
Authority` ruleset makes the app-bound `ci` check and the required CodeRabbit
review layer merge gates for `main`; CodeRabbit does not replace deterministic
CI or scientific review.

There is one workflow, one job, and one deterministic CI check. CI runs for
pull requests targeting `main` and for pushes to `main`; it has no secrets,
cache, artifact upload, service container or deployment step.

## Branch-per-mission topology

The repository uses one bounded mission, one branch, one reviewable pull
request, and one merge decision:

```text
main
  -> work/<mission>-<bounded-scope>
  -> one PR targeting main
```

Unrelated missions must not share a branch or pull request. Review fixes for
the same mission remain on that mission branch and PR. A new mission starts
from the current qualified `main`. Multiple branches do not require multiple
worktrees; one canonical checkout may switch branches. Direct development on
`main` is not part of the workflow. Stacked PRs are reserved for an
independently useful prerequisite that genuinely needs its own merge decision,
and trivial changes must not be fragmented into artificial PRs.

RES-63 is grandfathered on `work/res-63-canonical-dataset-ingestion` and PR
`#24`; RES-64 starts fresh from `main` after RES-63 and RES-77 are sealed.

## PR lifecycle

The normal lifecycle is:

```text
implementation
  -> local QA
  -> push
  -> draft PR if scope is still being assembled
  -> ready-for-review
  -> hosted ci
  -> CodeRabbit review
  -> review fixes on the same mission branch
  -> CodeRabbit latest-head review
  -> resolve or disposition every review thread
  -> final adversarial/scientific review
  -> squash merge
  -> delete the merged branch
```

The PR description must include the full Linear issue URL, the base and head
SHAs, authority-impact declarations, deterministic QA evidence, CodeRabbit
latest-head status, and review-finding disposition.

## CodeRabbit's role

CodeRabbit is an independent AI reviewer. It may inspect the PR and linked
issue context, inspect GitHub Checks, leave inline findings, request changes,
re-review new commits, resolve its addressed threads, and approve after its
own review requirements are met. It is not the scientific authority, the
deterministic authority, or the primary coding agent. It must not silently
mutate code, generate unit-test or docstring PRs, automatically fix CI,
automatically resolve merge conflicts, or become scientific truth authority.

The repository configuration keeps CodeRabbit's finishing touches disabled.
Its summaries belong in the walkthrough, not in the authoritative PR body.
CodeRabbit's optional Linear context depends on an OAuth connection and the
active plan; the repository must not pretend that connection exists when it
does not.

## Final review lifecycle

CodeRabbit approval alone is not final scientific or merge authority. Explicit
CodeRabbit commands such as `approve` or `resolve` can override or resolve its
own review state, so they do not make the review unbypassable. The final
decision still requires the deterministic root authority, disposition of all
blocking findings and threads, and final adversarial or scientific review when
the mission touches scientific, data, measurement, population, provenance, or
comparability authority.

The authority layers are:

```text
LOCAL_HOOKS = developer feedback
HOSTED_CI = deterministic independent verification
CODERABBIT = independent AI review
GITHUB_RULESET = merge enforcement
FINAL_SCIENTIFIC_REVIEW = scientific/adversarial disposition
```

## Ruleset relationship

The `DynamisLM Main Authority` ruleset remains the root merge authority for
the default branch. It requires a pull request, strict up-to-date required
checks, the app-bound `ci` check, and the observed CodeRabbit check; it blocks
force pushes and branch deletion, has no bypass actors, requires resolved
review threads, and permits squash history only. Ruleset changes are an
extension of this existing protection, not a second governance system.

The required `ci` context is restricted to the GitHub Actions app, and the
CodeRabbit context is restricted to the exact CodeRabbit app identity observed
from a real check run. Never guess a check name, slug, or app ID.

## CodeRabbit failure and rate-limit handling

If CodeRabbit is unavailable, rate-limited, uninstalled, or fails to emit an
identifiable check, record the exact state and stop the CodeRabbit-dependent
qualification step. Do not fabricate a PASS, substitute a local imitation,
weaken deterministic CI, or relax the ruleset. Use the repository PR checks and
the documented commands to diagnose the condition, then retry after the
service or authorization issue is resolved. CodeRabbit failure does not make
the deterministic `ci` check optional.

Manual review commands:

```text
@coderabbitai review
@coderabbitai full review
@coderabbitai configuration
@coderabbitai rate limit
```

Installation and Linear OAuth are human actions in the CodeRabbit UI. Install
only the intended repository when prompted; do not authorize all repositories.

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
