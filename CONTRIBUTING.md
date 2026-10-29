# Contributing to DynamisLM

Contributions should preserve the sealed P0 scientific contracts and keep numerical authority in registered deterministic Python operations.

For a scientific change, record the following when applicable:

- the scientific question;
- the evidence or decision record;
- the stable method and measurement-identity definition;
- the implementation and tests;
- versioning and deterministic-serialization implications;
- provenance and reprocessing implications;
- comparability and refusal implications.

An undocumented metric-definition change is not a refactor. A new protocol, device, estimator, or method normally receives a distinct identity or rule rather than silently changing an existing one.

## Development checks

Use Python 3.12 and uv. Before opening a pull request, run:

```bash
uv sync --frozen
./scripts/install-hooks.sh
./scripts/ci.sh
```

Do not add model weights, datasets, corpus shards, credentials, or generated training artifacts to Git. Keep artifact licenses and provenance separate from the AGPL-licensed source tree.

## Mission and artifact policy

One active engineering mission uses one issue, one `work/res-N-description` branch
from qualified `main`, one PR and one merge decision. Start commit and PR subjects
with `RES-N: `. Same-mission review repairs stay on that PR. Park the previous
mission in Linear before starting another; CI validates Git/PR consistency, while
Linear scheduling authority must still be checked against the live issue.

Complete the PR template with exact issue URL, mission, branch, merge-base SHA,
current head SHA and authority-impact answers. Updating a commit requires updating
`Current head` in the PR body; metadata edits rerun `ci`. Do not rewrite historical
signed commits to satisfy the new subject policy: only the PR's new commit range
is checked. GitHub's post-merge subject is not retroactively constrained.

The sole automation exception is authenticated `dependabot[bot]` PRs under
`dependabot/github_actions/`, with `build(deps): bump actions/...` or
`build(deps): bump astral-sh/...` subjects and changes confined in every commit
to `.github/workflows/ci.yml` or `.github/dependabot.yml`. This does not authorize
an additional engineering mission or automatic merge.

The tracked non-code inventory in `.repo-policy/noncode-inventory.tsv` is also the
explicit artifact admission list. Its classes are configuration (including test
inputs), authority/immutable evidence, and necessary documentation. Add a new
non-code path only with a reviewed classification and purpose; arbitrary research
outputs, even Markdown or JSON, are not admitted automatically. Redundancy was not
proven for any baseline non-code file: deletion inventory is empty. Historical
contracts, receipts and reports retain authority even when a later document
supersedes part of their scope.

All files are capped at 1 MiB. Notebooks, caches, datasets, model weights, private
keys, known token formats, binary files, symlinks and submodules are rejected.
The only current tabular exception is the 100-byte synthetic
`tests/fixtures/synthetic/source-a/source-a.tab`, explicitly allowlisted and
SHA-256 pinned. A future fixture exception must be text, synthetic, under that
root, individually listed and digest pinned; an exception never permits real
empirical rows. Baseline scientific authorities and fixture bytes are checked
against the immutable audit commit, independently of editable inventory digests.
Changing those authorities requires an explicit future mission, not new expected
hashes to obtain PASS. Raw source bytes, canonical rows, weights, caches and PSE
protected material remain outside Git. No history rewriting is part of hygiene.

Pre-commit inspects index blobs (so clean working copies cannot hide staged
artifacts); commit-msg checks the mission subject; pre-push rejects direct main,
force/deletion/ref-mismatch pushes and checks the exact clean current head before
full QA. Hooks provide feedback and remain bypassable. Hosted `ci` separately
checks the merged tree, PR metadata and every new mission commit tree, including
artifacts added and later removed. Repository policy is artifact control plus
known-secret detection, not proof that arbitrary text contains no sensitive data;
review and source-use authorization remain mandatory.
