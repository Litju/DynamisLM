# RES75-DR-001 — Hosted CI and repository governance

## Control

`DECISION_ID=RES75-DR-001`

`STATUS=ADOPTED`

`SPEC_VERSION=1.0.0`

This record adopts the architecture in **DynamisLM — Hosted CI & Repository
Governance Specification V1** for the public `Litju/DynamisLM` repository.

## Decision

### 1. Hosted CI

CI uses standard GitHub-hosted ephemeral runners. The repository is public, so
the standard hosted-runner allocation is a zero-cost fit for this gate. The
runner is explicitly `ubuntu-24.04`; the job installs Python `3.12` and the
fixed uv tool version `0.12.2` from the frozen lockfile.

`SELF_HOSTED_RUNNER=NONE` is deliberate. Self-hosted runners were rejected
because they add machine lifecycle, trust, credential, isolation and
reproducibility obligations without closing a requirement here. WSL CI
distributions, Docker, Kubernetes and ARC are likewise outside this mission.

### 2. One workflow and one check

One workflow is sufficient because this mission has one independent full-QA
boundary. It has one job named `ci`, which produces one required check named
`ci`. Splitting equivalent checks would create additional enforcement state
without increasing verification coverage.

The workflow runs on pull requests targeting `main` and on pushes to `main`.
The pull-request run is the independent clean-environment verification; the
post-merge push run provides main-branch continuity.

`CI_WORKFLOWS=1`

`CI_REQUIRED_JOBS=1`

`REQUIRED_CHECK=ci`

### 3. Authority boundaries

The authority topology is:

```text
LOCAL_HOOKS = DEVELOPER_FEEDBACK
REMOTE_GITHUB_HOSTED_CI = INDEPENDENT_CLEAN_ENVIRONMENT_VERIFICATION
GITHUB_MAIN_RULESET = MERGE_ENFORCEMENT_AUTHORITY
```

The versioned `pre-commit` hook delegates fast checks to
`scripts/qa-fast.sh --staged`. The versioned `pre-push` hook delegates the
complete gate to `scripts/ci.sh`. Remote CI invokes that same `scripts/ci.sh`,
so local pre-push and hosted verification share one full-QA command authority.

### 4. QA and repository policy

`scripts/qa-fast.sh` owns Ruff lint and format checks and, in staged mode, the
staged whitespace check. It is read-only and performs no network calls or
automatic formatting.

`scripts/ci.sh` owns the full sequence: frozen uv synchronization, fast QA,
mypy, the deterministic tracked-repository policy, and pytest. It compares the
tracked index/worktree diff before and after QA, allowing unrelated local edits
while detecting mutations introduced by QA.

`scripts/repository_policy.py` examines only `git ls-files`. It rejects data,
model, checkpoint, corpus and secret-like paths and extensions. CSV, XLSX and
ZIP are not globally banned, but a controlled fixture must be under
`tests/fixtures/synthetic/`, be explicitly listed in the optional
`.repo-policy/allowed-fixtures.txt`, and be no larger than 1 MiB. No current
RES-63 source artifact is permitted by this fixture rule.

### 5. Action and dependency maintenance

Every external workflow Action is pinned to a full commit SHA, with its
human-readable release tag retained in a same-line comment. The repository
Actions policy additionally requires server-side SHA pinning while preserving
the existing `enabled=true` and `allowed_actions=all` settings. Dependabot is
configured only for weekly GitHub Actions updates. Dependabot pull requests
must pass the normal `ci` check and are not auto-merged.

### 6. Main authority ruleset

One active ruleset named `DynamisLM Main Authority` targets the default branch.
It requires a pull request, requires the `ci` status check to be successful and
up to date, blocks force pushes and branch deletion, and requires zero
approving reviews. It does not require linear history, conversation resolution,
code-owner review or signed commits, and it has no bypass actor, merge queue,
deployment rule or additional rule.

The ruleset is the merge-enforcement authority. It is intentionally configured
only after a successful hosted pull-request CI run proves that the `ci` check
exists and passes.

### 7. No CD and RES-63 boundary

There is no deployment/CD workflow in RES-75. No deployment target or release
authority is required to establish hosted CI and repository governance, and
adding one would expand the mission beyond its smallest maintainable scope.

RES-63 remains the canonical dataset qualification mission. RES-75 adds only
the tracked-repository policy that prevents accidental data or secret artifacts
from entering source control; it does not download, ingest, map, qualify or
otherwise implement RES-63 data authority.

No scientific formulas, numerical authority, wire format, historical hashes or
model/GPU work are changed by this decision.
