# Hosted CI operations

## Architecture

Local hooks provide developer feedback. GitHub-hosted `ubuntu-24.04` CI runs
the same full-QA command in a clean environment. The active `DynamisLM Main
Authority` ruleset makes the successful `ci` check the merge gate for `main`.

There is one workflow, one job, and one deterministic CI check. CI runs for
pull requests targeting `main` and for pushes to `main`; it has no secrets,
cache, artifact upload, service container, or deployment step.

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
`main` is not part of the workflow. Stacked PRs are exceptional and require an
independently useful prerequisite with its own merge decision. Trivial cleanup
must not be fragmented into artificial PRs.

RES-63 is grandfathered on `work/res-63-canonical-dataset-ingestion` and PR
`#24`; RES-64 starts fresh from `main` after RES-63 and RES-77 are sealed.

## PR lifecycle

The normal lifecycle is:

```text
implementation
  -> local QA
  -> push
  -> PR
  -> hosted ci
  -> adversarial review
  -> repair on the same mission branch
  -> rerun deterministic QA
  -> final review of the current head
  -> merge
  -> delete the merged branch
```

The PR description records the full Linear issue URL, the base and head SHAs,
authority-impact declarations, deterministic QA evidence, review findings,
limitations, and the final qualification state. Every finding is verified
against the current head before code changes are made. Blocking findings are
resolved or explicitly dispositioned before merge.

## Review layers

The repository review architecture is:

```text
LOCAL_HOOKS = developer feedback
HOSTED_CI = independent deterministic verification
GITHUB_RULESET = enforced merge authority
AGENT_REVIEW = advisory/adversarial reasoning
FINAL_SCIENTIFIC_REVIEW = project-process requirement for authority-changing scientific missions
```

No external AI-review service is a required status check or merge dependency.
Rate limits, SaaS outages, reviewer quotas, and plan changes must not block
DynamisLM merge eligibility. AI review findings can be useful evidence, but
they are not self-authenticating and do not replace deterministic CI or final
scientific/adversarial review.

## Ruleset relationship

The `DynamisLM Main Authority` ruleset remains the root merge authority for
the default branch. It requires a pull request, strict up-to-date `ci`, blocks
force pushes and branch deletion, has no bypass actors, and preserves the
repository's existing merge and review settings. This mission removes an
external review dependency without changing the ruleset authority.

Read the live ruleset when diagnosing a merge decision:

```bash
gh api repos/Litju/DynamisLM/rulesets
gh api repos/Litju/DynamisLM/rulesets/<RULESET_ID>
```

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

The ruleset is intentionally the only merge-enforcement layer for this mission.

## Action pins and Dependabot

Workflow Actions use full commit SHAs and same-line release comments. To
update a pin safely, inspect the official Action repository's current stable
release, resolve its tag through the Git refs API, dereference annotated tags
to the commit object, verify the commit belongs to the intended repository,
update the SHA and release comment, and let the normal pull-request `ci` check
qualify the change. Do not replace a pin with a mutable tag.

Dependabot creates weekly updates only for GitHub Actions. Treat each update as
a normal pull request; do not auto-merge it.

## Repository policy and synthetic fixtures

The policy reads tracked paths from `git ls-files`, not arbitrary ignored local
files. It rejects data/model/checkpoint/corpus directories, large scientific
data extensions, and secret-like files. `.env.example` is explicitly allowed.

CSV, XLSX, and ZIP are allowed only as small, clearly synthetic fixtures under
`tests/fixtures/synthetic/` with an exact entry in
`.repo-policy/allowed-fixtures.txt`. The maximum size is 1 MiB. The allowlist
may remain empty while no controlled fixture exists. Real RES-63 source files
must never be added there.

## Scope boundaries

The Actions SHA policy and ruleset may be modified only through an explicit
repository-governance issue. This mission makes no workflow change, uses no
self-hosted runner, and adds no CD because neither is needed for the current
verification boundary.

RES-63 remains responsible for canonical dataset qualification and source/data
authority. RES-75 established hosted CI and repository governance; it does not
ingest or qualify a dataset and does not change scientific formulas, numerical
authority, serialization version, or historical hashes.
