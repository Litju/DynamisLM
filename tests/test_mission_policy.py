from __future__ import annotations

import copy
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from scripts import repository_policy
from scripts.mission_policy import (
    REPO_ROOT,
    mission,
    validate_pr,
    validate_push,
    validate_range,
    validate_subject,
)


def valid_pr() -> dict[str, Any]:
    body = """Linear issue: RES-556
Full Linear URL: https://linear.app/alignerr-cmj/issue/RES-556/unified-repository-hygiene-and-governance-hardening
Mission: RES-556
Branch: work/res-556-repository-hygiene
Base head: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
Current head: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
Mission scope isolated to this PR?: YES
Real raw/canonical empirical data committed?: NO
Local full QA: PASS
Adversarial review: Pending current-head review; NO_GO
Open blockers: independent review
Known limitations: no semantic DLP
"""
    for key in (
        "Scientific numerical authority changed?",
        "Serialization version changed?",
        "Historical hashes intentionally changed?",
        "Source/data artifact added?",
        "Population authority affected?",
        "Measurement identity affected?",
        "Comparability authority affected?",
        "Repository/governance authority affected?",
        "Model-training authority affected?",
        "Expected hashes/counts changed?",
    ):
        body += f"{key}: NO\n"
    return {
        "head": {"ref": "work/res-556-repository-hygiene", "sha": "b" * 40},
        "base": {"ref": "main", "sha": "a" * 40},
        "user": {"login": "owner"},
        "title": "RES-556: Harden repository governance",
        "body": body,
    }


def test_valid_pr_and_subject() -> None:
    assert validate_pr(valid_pr(), "a" * 40) == ("RES-556", False)
    validate_subject("RES-556: Harden policy", "RES-556")


@pytest.mark.parametrize("branch", ["main", "work/res-541-mixed", "work/res-0-bad", "feature/foo"])
def test_invalid_or_mismatched_mission(branch: str) -> None:
    pr = valid_pr()
    pr["head"]["ref"] = branch
    with pytest.raises(ValueError):
        validate_pr(pr, "a" * 40)


@pytest.mark.parametrize(
    "old,new",
    [
        ("Current head: " + "b" * 40, "Current head: " + "c" * 40),
        ("Linear issue: RES-556", "Linear issue: RES-541"),
        ("Mission: RES-556", "Mission: RES-541"),
        ("issue/RES-556/", "issue/RES-541/"),
        ("committed?: NO", "committed?: YES"),
        ("Local full QA: PASS", "Local full QA: TBD"),
        ("identity affected?: NO", "identity affected?: YES/NO"),
    ],
)
def test_metadata_refuses_forged_stale_or_placeholder_values(old: str, new: str) -> None:
    pr = valid_pr()
    pr["body"] = pr["body"].replace(old, new)
    with pytest.raises(ValueError):
        validate_pr(pr, "a" * 40)


def test_duplicate_field_rejected() -> None:
    pr = valid_pr()
    pr["body"] += "Mission: RES-541\n"
    with pytest.raises(ValueError, match="DUPLICATE"):
        validate_pr(pr, "a" * 40)


def test_bot_exception_requires_authenticated_author() -> None:
    pr = valid_pr()
    pr["head"]["ref"] = "dependabot/github_actions/actions/setup-python-7.1.0"
    pr["title"] = "build(deps): bump actions/setup-python from 7.0.0 to 7.1.0"
    with pytest.raises(ValueError):
        validate_pr(pr, "a" * 40)
    pr["user"]["login"] = "dependabot[bot]"
    assert validate_pr(pr, "a" * 40) == ("", True)
    pr["title"] = "build(deps): bump arbitrary/runtime from 1 to 2"
    with pytest.raises(ValueError):
        validate_pr(pr, "a" * 40)


def test_subject_cannot_use_another_mission() -> None:
    assert mission("work/res-556-cleanup") == "RES-556"
    with pytest.raises(ValueError):
        validate_subject("RES-541: unrelated work", "RES-556")


@pytest.mark.parametrize(
    "remote,local_sha",
    [
        ("refs/heads/main", "b" * 40),
        ("refs/heads/work/res-541-other", "b" * 40),
        ("refs/heads/work/res-556-cleanup", "0" * 40),
    ],
)
def test_push_rejects_main_other_refs_and_deletions(remote: str, local_sha: str) -> None:
    with pytest.raises(ValueError):
        validate_push(
            [f"refs/heads/work/res-556-cleanup {local_sha} {remote} {'0' * 40}"],
            "work/res-556-cleanup",
            "b" * 40,
        )


def test_new_current_branch_push_is_permitted() -> None:
    ref = "refs/heads/work/res-556-cleanup"
    validate_push([f"{ref} {'b' * 40} {ref} {'0' * 40}"], "work/res-556-cleanup", "b" * 40)


# Minimal metadata observed from GitHub PRs #46-48 on 2026-10-29; no artifact data.
OBSERVED_PRS: dict[int, dict[str, Any]] = {
    46: {
        "number": 46,
        "title": "RES-541: terminal-confirmed request issuance and CPU semantic guard",
        "user": {"login": "Litju"},
        "base": {
            "ref": "main",
            "sha": "6d6892c95134f83ffdb224e11e6e3603296fc5ed",
            "repo": {"full_name": "Litju/DynamisLM"},
        },
        "head": {
            "ref": (
                "julitocrztuga/res-541-a0-wslcolab-gpu-scientific-reasoning-alpha-development-only"
            ),
            "sha": "97d361badf02a80b411aaefdb6ddac1c4e8e126e",
            "repo": {"full_name": "Litju/DynamisLM"},
        },
    },
    47: {
        "number": 47,
        "title": "build(deps): bump astral-sh/setup-uv from 10.0.1 to 10.3.2",
        "user": {"login": "dependabot[bot]"},
        "base": {
            "ref": "main",
            "sha": "6d6892c95134f83ffdb224e11e6e3603296fc5ed",
            "repo": {"full_name": "Litju/DynamisLM"},
        },
        "head": {
            "ref": "dependabot/github_actions/astral-sh/setup-uv-10.3.2",
            "sha": "a083b6adaf637d456f09f1c8e32ccf91c8cd9731",
            "repo": {"full_name": "Litju/DynamisLM"},
        },
    },
    48: {
        "number": 48,
        "title": "build(deps): bump actions/setup-python from 7.0.0 to 7.1.0",
        "user": {"login": "dependabot[bot]"},
        "base": {
            "ref": "main",
            "sha": "6d6892c95134f83ffdb224e11e6e3603296fc5ed",
            "repo": {"full_name": "Litju/DynamisLM"},
        },
        "head": {
            "ref": "dependabot/github_actions/actions/setup-python-7.1.0",
            "sha": "e562904a024a32a06b832ca90becea7b09949a7d",
            "repo": {"full_name": "Litju/DynamisLM"},
        },
    },
}


def test_observed_parked_pr46_keeps_exact_27_commit_history() -> None:
    pr = copy.deepcopy(OBSERVED_PRS[46])
    assert (
        repository_policy.git_bytes(
            REPO_ROOT, "rev-list", "--count", f"{pr['base']['sha']}..{pr['head']['sha']}"
        ).strip()
        == b"27"
    )
    assert validate_pr(pr, pr["base"]["sha"]) == ("RES-541", False)
    # Actual Git traversal, not a mocked assertion: no historical subject/tree is revalidated.
    validate_range(pr["base"]["sha"], pr["head"]["sha"], "RES-541", pr=pr)


@pytest.mark.parametrize(
    "field,value",
    [
        ("number", 50),
        ("branch", "work/res-541-other"),
        ("repo", "other/DynamisLM"),
        ("head", "6505076e1f2886541d079d3dee932eece1ed578f"),
        ("base", "0" * 40),
    ],
)
def test_legacy_exception_cannot_escape_identity_or_ancestry(field: str, value: Any) -> None:
    pr = copy.deepcopy(OBSERVED_PRS[46])
    if field == "number":
        pr["number"] = value
    elif field == "branch":
        pr["head"]["ref"] = value
    elif field == "repo":
        pr["head"]["repo"]["full_name"] = value
    elif field == "head":
        pr["head"]["sha"] = value
    else:
        pr["base"]["sha"] = value
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        issue, bot = validate_pr(pr, pr["base"]["sha"])
        validate_range(pr["base"]["sha"], pr["head"]["sha"], issue, bot=bot, pr=pr)


@pytest.fixture
def legacy_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    # Disposable object store/index; historical refs and the real index are never modified.
    objects = tmp_path / "objects"
    objects.mkdir()
    original_objects = (
        repository_policy.git_bytes(
            REPO_ROOT, "rev-parse", "--path-format=absolute", "--git-path", "objects"
        )
        .decode()
        .strip()
    )
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(objects))
    monkeypatch.setenv("GIT_ALTERNATE_OBJECT_DIRECTORIES", original_objects)
    # Copy the reviewed index, including staged remediation during local development.
    index = (
        repository_policy.git_bytes(
            REPO_ROOT, "rev-parse", "--path-format=absolute", "--git-path", "index"
        )
        .decode()
        .strip()
    )
    temporary_index = tmp_path / "index"
    temporary_index.write_bytes(Path(index).read_bytes())
    monkeypatch.setenv("GIT_INDEX_FILE", str(temporary_index))
    for entry in repository_policy.git_bytes(
        REPO_ROOT, "ls-tree", "-rz", repository_policy.LEGACY_HEAD
    ).split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t")
        path = raw_path.decode()
        # Only add paths absent from main; modern policy/configuration stays in place.
        if repository_policy.git_bytes(REPO_ROOT, "ls-tree", "HEAD", "--", path):
            continue
        mode, _, oid = metadata.decode().split()
        repository_policy.git_bytes(
            REPO_ROOT, "update-index", "--add", "--cacheinfo", mode, oid, path
        )
    return repository_policy.git_bytes(REPO_ROOT, "write-tree").decode().strip()


def _future_legacy_pr(tree: str, subject: str) -> dict[str, Any]:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Synthetic policy test",
        "GIT_AUTHOR_EMAIL": "synthetic@example.invalid",
        "GIT_COMMITTER_NAME": "Synthetic policy test",
        "GIT_COMMITTER_EMAIL": "synthetic@example.invalid",
    }
    head = subprocess.check_output(
        [
            "git",
            "-c",
            "commit.gpgsign=false",
            "commit-tree",
            tree,
            "-p",
            repository_policy.LEGACY_HEAD,
            "-m",
            subject,
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
    ).strip()
    pr = copy.deepcopy(OBSERVED_PRS[46])
    pr["head"]["sha"] = head
    return pr


def test_unchanged_legacy_artifacts_pass_only_for_observed_pr46(legacy_tree: str) -> None:
    assert repository_policy.repository_failures(REPO_ROOT, legacy_tree, pr=OBSERVED_PRS[46]) == ()
    wrong = copy.deepcopy(OBSERVED_PRS[46])
    wrong["number"] = 50
    failures = repository_policy.repository_failures(REPO_ROOT, legacy_tree, pr=wrong)
    assert "NONCODE_INVENTORY_MISMATCH" in failures
    assert "SECRET_CONTENT=scripts/request_issuer.py" in failures


def test_future_legacy_commits_require_current_metadata_and_subjects(legacy_tree: str) -> None:
    pr = _future_legacy_pr(legacy_tree, "old-style subject is no longer exempt")
    with pytest.raises(ValueError, match="PR_FIELD"):
        validate_pr(pr, pr["base"]["sha"])
    with pytest.raises(ValueError, match="COMMIT_SUBJECT"):
        validate_range(pr["base"]["sha"], pr["head"]["sha"], "RES-541", pr=pr)


def test_future_legacy_artifacts_are_not_exempt(legacy_tree: str, tmp_path: Path) -> None:
    oid = (
        subprocess.check_output(
            ["git", "hash-object", "-w", "--stdin"], cwd=REPO_ROOT, input=b"{}\n"
        )
        .decode()
        .strip()
    )
    repository_policy.git_bytes(
        REPO_ROOT,
        "update-index",
        "--add",
        "--cacheinfo",
        "100644",
        oid,
        "experiments/a01/uncontrolled.json",
    )
    tree = repository_policy.git_bytes(REPO_ROOT, "write-tree").decode().strip()
    pr = _future_legacy_pr(tree, "RES-541: Synthetic policy test")
    event = tmp_path / "event.json"

    event.write_text(json.dumps({"pull_request": pr}))
    with pytest.raises(subprocess.CalledProcessError):
        validate_range(pr["base"]["sha"], pr["head"]["sha"], "RES-541", pr=pr, event=event)
    # Modifying an old artifact also loses the exact historical-byte admission.
    repository_policy.git_bytes(REPO_ROOT, "read-tree", legacy_tree)
    repository_policy.git_bytes(
        REPO_ROOT, "update-index", "--cacheinfo", "100644", oid, "experiments/a0/cases.json"
    )
    changed = repository_policy.git_bytes(REPO_ROOT, "write-tree").decode().strip()
    assert "NONCODE_INVENTORY_MISMATCH" in repository_policy.repository_failures(
        REPO_ROOT, changed, pr=pr
    )


@pytest.mark.parametrize("number", [47, 48])
def test_observed_dependabot_metadata_and_commit_scope(
    number: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    pr = copy.deepcopy(OBSERVED_PRS[number])
    assert validate_pr(pr, pr["base"]["sha"]) == ("", True)
    # Both observed commits change exactly this workflow and use the observed title.
    paths = ".github/workflows/ci.yml"
    head: str = pr["head"]["sha"]
    subject: str = pr["title"]

    def observed_git(*args: str) -> str:
        if args[0] == "rev-list":
            return head
        if args[0] == "show":
            return subject
        return paths

    monkeypatch.setattr("scripts.mission_policy.git", observed_git)
    validate_range(pr["base"]["sha"], pr["head"]["sha"], "", bot=True)
    paths = "src/unrelated.py"
    with pytest.raises(ValueError, match="BOT_SCOPE"):
        validate_range(pr["base"]["sha"], pr["head"]["sha"], "", bot=True)


def test_future_legacy_commit_can_pass_current_controls(legacy_tree: str, tmp_path: Path) -> None:
    pr = _future_legacy_pr(legacy_tree, "RES-541: Synthetic compliant policy test")
    pr["body"] = (
        valid_pr()["body"]
        .replace("work/res-556-repository-hygiene", repository_policy.LEGACY_BRANCH)
        .replace("RES-556", "RES-541")
        .replace("a" * 40, pr["base"]["sha"])
        .replace("b" * 40, pr["head"]["sha"])
    )
    assert validate_pr(pr, pr["base"]["sha"]) == ("RES-541", False)
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": pr}))
    validate_range(pr["base"]["sha"], pr["head"]["sha"], "RES-541", pr=pr, event=event)


def test_modified_legacy_source_cannot_hide_new_secret(legacy_tree: str) -> None:
    token = b"ghp_" + b"X" * 36
    oid = (
        subprocess.check_output(["git", "hash-object", "-w", "--stdin"], cwd=REPO_ROOT, input=token)
        .decode()
        .strip()
    )
    repository_policy.git_bytes(
        REPO_ROOT, "update-index", "--cacheinfo", "100644", oid, "scripts/request_issuer.py"
    )
    tree = repository_policy.git_bytes(REPO_ROOT, "write-tree").decode().strip()
    assert "SECRET_CONTENT=scripts/request_issuer.py" in repository_policy.repository_failures(
        REPO_ROOT, tree, pr=OBSERVED_PRS[46]
    )
