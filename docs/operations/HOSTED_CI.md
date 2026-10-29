# Hosted CI operations

One active engineering mission uses one Linear issue, one `work/res-N-description`
branch from qualified `main`, one PR and one merge decision. Same-mission review
fixes remain on that PR. Linear is scheduling authority; GitHub checks do not
prove that an issue is active. Follow [CONTRIBUTING.md](../../CONTRIBUTING.md) for
commit subjects, artifact admission and narrowly bounded automation exceptions.

## Local and hosted gates

Install hooks with `./scripts/install-hooks.sh`. Pre-commit checks staged artifact
bytes and whitespace plus Ruff; commit-msg validates the mission subject.
Pre-push rejects direct main pushes, mismatched/untested refs, non-fast-forward
updates and deletions, then runs `./scripts/ci.sh` on the clean committed head.
Hooks are developer feedback and can be bypassed.

`./scripts/ci.sh` runs frozen uv synchronization, Ruff lint/format, mypy,
repository policy and pytest, and checks that QA did not mutate tracked files.
Stage reviewed changes before full QA: policy compares index and working bytes.
Ignored local data are never scanned or imported by these gates.

One pinned GitHub-hosted `ubuntu-24.04` workflow/job produces required `ci`.
It runs on PR opening, commit synchronization, reopening, metadata editing and
ready-for-review events, plus pushes to main. Full history is fetched for exact
baseline evidence and new-commit checks. The event payload is read as data,
never interpolated into shell commands. The PR gate validates mission naming,
matching issue/branch/base/head metadata and explicit authority declarations.
Each new mission commit tree is checked, including artifacts subsequently
removed. Only new commit subjects are constrained; historical signed/provenance
ancestors are preserved. Authenticated Dependabot Actions updates receive only
the path/subject exception documented in CONTRIBUTING; they still run full QA.

There are no self-hosted runners, secrets, uploads, services, deployment steps
or required external AI-review checks. External review is advisory; independent
human approval and required scientific/adversarial review remain merge evidence.

The sole historical mission exception is PR #46 in `Litju/DynamisLM`, on
`julitocrztuga/res-541-a0-wslcolab-gpu-scientific-reasoning-alpha-development-only`.
Only the 27 commits from audit baseline through pinned
`97d361badf02a80b411aaefdb6ddac1c4e8e126e` are exempt from new subject/metadata
requirements. Exact PR/repository/branch identity and pinned ancestry are checked.
Subsequent commits must use `RES-541: ` subjects, current PR metadata and current
artifact admission. Only unchanged additions at that historical head receive automatic historical
admission. This includes the public private-key-format marker in the exact pinned
issuer source; changed source bytes receive normal secret scanning. Modified/new
non-code artifacts require the inventory.
Local hooks on that branch read PR #46 via authenticated GitHub CLI and fail closed
if identity/history cannot be verified. This authorizes no experiment or merge.

## Artifact and scientific evidence policy

`.repo-policy/noncode-inventory.tsv` exhaustively lists tracked non-code files,
classifications, retention reasons and immutable evidence SHA-256 values.
It is the reviewed admission list for new Markdown, JSON and other non-code
artifacts, not a blanket research-output exception. Baseline scientific documents,
receipts, public registry metadata, qualification reports and the synthetic table
are compared against audit commit `6d6892c95134f83ffdb224e11e6e3603296fc5ed`.
Changing an inventory digest cannot authorize changing baseline evidence.
The historical RES75 decision record is retained unchanged; current operating
policy is this document and CONTRIBUTING.

No baseline file was demonstrated safe and unnecessary to delete; the exact
deletion inventory is empty. Source reports are metadata/qualification evidence,
not raw source bytes or real canonical row tables. The sole tabular fixture is
100 bytes, explicitly synthetic, allowlisted and pinned. All files are limited
to 1 MiB; notebooks, binary artifacts, datasets, weights, caches, private keys,
known token forms, symlinks and submodules are rejected. Arbitrary text cannot be
certified non-sensitive mechanically; review and data-use authority still apply.

## Live main ruleset audit and required administration

API read-back on 2026-10-29 verified active repository ruleset **22691929**,
`DynamisLM Main Authority`, targeting `~DEFAULT_BRANCH` with no exclusions.
The effective main rules endpoint agrees. Classic branch protection returns
404; protection is supplied by the ruleset, not a classic protection rule.

| Setting | API-observed value | Required disposition |
| --- | --- | --- |
| Pull request required | Yes | Retain |
| Approving reviews | 0 | Set at least 1 independent approval |
| Dismiss stale approvals on push | false | Enable |
| Last-push approval by another reviewer | false | Enable; provision another eligible reviewer |
| Resolve review conversations | false | Enable |
| Required check | `ci`, strict/up-to-date; integration unbound | Bind `integration_id: 15368` (GitHub Actions) |
| Force pushes | Blocked (`non_fast_forward`) | Retain |
| Branch deletion | Blocked (`deletion`) | Retain |
| Bypass actors | Empty; current user `never` | Retain; no admin force/deletion bypass |
| Allowed merge methods | merge, squash, rebase | Prefer merge commits when provenance binds commit identities |
| Code-owner review | false | Optional; not a substitute for independent approval |

**Administrative changes above are specified, not applied.** Do not declare GO
for merge until an administrator enables the missing review requirements,
confirms an eligible independent reviewer exists, and API read-back verifies
all required values. Do not rewrite historical commits to introduce signatures
or new naming. A successful CI run is necessary but insufficient for merge.

A separate active **branch** ruleset should target `refs/heads/work/res-*` with
only `non_fast_forward` and an empty bypass list. Do **not** add a `deletion`
rule to mission branches: ordinary deletion after merge must remain possible.
Do not copy the main-branch PR/check restrictions onto working branches; routine
fast-forward development pushes must remain possible. This pattern does not cover
the legacy PR #46 branch, which stays unchanged. No such mission-branch ruleset
was present in the API listing; this proposal is administrator work, not applied
configuration. Validate it in a disposable branch before relying on enforcement.

```bash
gh api repos/Litju/DynamisLM/rulesets/22691929
gh api repos/Litju/DynamisLM/rules/branches/main
gh pr checks <PR_NUMBER>
gh run view <RUN_ID> --json jobs,headSha,status,conclusion
```

Read the live issue, open PRs, branch lineage, current-head review findings,
scientific/data boundaries and required check results for the final merge
decision. RES-541 PR #46 remains draft/parked with historical evidence unchanged;
RES-556 does not authorize A1, M0, GPU, model training, protected PSE access,
release, or a scientific authority change.
