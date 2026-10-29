from __future__ import annotations

from typing import Any

import pytest
from scripts.mission_policy import mission, validate_pr, validate_push, validate_subject


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
