"""Validate new mission commits and PR metadata; historical ancestors are never rewritten."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

BRANCH = re.compile(r"work/res-([1-9][0-9]*)-[a-z0-9]+(?:-[a-z0-9]+)*")
BOT_BRANCH = re.compile(r"dependabot/github_actions/[a-zA-Z0-9_./-]+")
BOT_TITLE = re.compile(r"build\(deps\): bump (?:actions/|astral-sh/)[a-z-]+ from \S+ to \S+")
BOT_FILES = {".github/workflows/ci.yml", ".github/dependabot.yml"}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def mission(branch: str) -> str:
    match = BRANCH.fullmatch(branch)
    if not match:
        raise ValueError("MISSION_BRANCH: use work/res-N-description")
    return f"RES-{match[1]}"


def validate_subject(subject: str, issue: str) -> None:
    if not subject.startswith(f"{issue}: ") or not subject[len(issue) + 2 :].strip():
        raise ValueError(f"COMMIT_SUBJECT: expected {issue}: description")


def validate_pr(pr: dict[str, Any], merge_base: str) -> tuple[str, bool]:
    branch = pr["head"]["ref"]
    if pr["base"]["ref"] != "main":
        raise ValueError("PR_BASE: expected main")
    bot = pr["user"]["login"] == "dependabot[bot]" and bool(BOT_BRANCH.fullmatch(branch))
    if bot:
        if not BOT_TITLE.fullmatch(pr["title"]):
            raise ValueError("BOT_TITLE: only bounded GitHub Actions dependency updates")
        return "", True
    issue = mission(branch)
    validate_subject(pr["title"], issue)
    fields: dict[str, str] = {}
    for line in (pr.get("body") or "").splitlines():
        key, sep, value = line.partition(":")
        if sep:
            if key in fields:
                raise ValueError(f"DUPLICATE_PR_FIELD={key}")
            fields[key] = value.strip()
    expected = {
        "Linear issue": issue,
        "Mission": issue,
        "Branch": branch,
        "Base head": merge_base,
        "Current head": pr["head"]["sha"],
        "Mission scope isolated to this PR?": "YES",
        "Real raw/canonical empirical data committed?": "NO",
    }
    for key, value in expected.items():
        if fields.get(key) != value:
            raise ValueError(f"PR_FIELD={key}: expected {value}")
    if not re.fullmatch(
        rf"https://linear\.app/alignerr-cmj/issue/{issue}/[a-z0-9-]+",
        fields.get("Full Linear URL", ""),
    ):
        raise ValueError("PR_LINEAR_URL: expected matching issue URL")
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
        if fields.get(key) not in {"YES", "NO"}:
            raise ValueError(f"PR_AUTHORITY_FIELD={key}: expected YES or NO")
    for key in ("Local full QA", "Adversarial review", "Open blockers", "Known limitations"):
        if not fields.get(key) or fields[key].lower() in {"tbd", "todo", "..."}:
            raise ValueError(f"PR_MISSING_FIELD={key}")
    return issue, False


def validate_range(base: str, head: str, issue: str, *, bot: bool = False) -> None:
    for commit in git("rev-list", "--reverse", f"{base}..{head}").splitlines():
        subject = git("show", "-s", "--format=%s", commit)
        if bot:
            if not BOT_TITLE.fullmatch(subject):
                raise ValueError("BOT_COMMIT_SUBJECT")
            paths = set(
                git(
                    "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", commit
                ).splitlines()
            )
            if not paths or not paths <= BOT_FILES:
                raise ValueError("BOT_SCOPE: only GitHub Actions configuration")
            continue
        else:
            validate_subject(subject, issue)
        # Inspect every new tree, including files removed again before the final head.
        subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("repository_policy.py")),
                "--revision",
                commit,
            ],
            check=True,
        )
    if bot:
        paths = set(git("diff", "--name-only", base, head).splitlines())
        if not paths or not paths <= BOT_FILES:
            raise ValueError("BOT_SCOPE: only GitHub Actions configuration")


def validate_push(lines: list[str], branch: str, head: str) -> None:
    for line in lines:
        local_ref, local_sha, remote_ref, remote_sha = line.split()
        if remote_ref == "refs/heads/main":
            raise ValueError("DIRECT_MAIN_PUSH_FORBIDDEN")
        if (local_ref, local_sha, remote_ref) != (
            f"refs/heads/{branch}",
            head,
            f"refs/heads/{branch}",
        ):
            raise ValueError("PUSH_SCOPE: only current tested mission head; no deletion or tags")
        if remote_sha != "0" * 40:
            subprocess.run(["git", "merge-base", "--is-ancestor", remote_sha, head], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit-message", type=Path)
    parser.add_argument("--pre-push", action="store_true")
    parser.add_argument("--event", type=Path)
    args = parser.parse_args()
    try:
        if args.event:
            event = json.loads(args.event.read_text())
            if "pull_request" in event:
                pr = event["pull_request"]
                base, head = pr["base"]["sha"], pr["head"]["sha"]
                merge_base = git("merge-base", base, head)
                issue, bot = validate_pr(pr, merge_base)
                validate_range(merge_base, head, issue, bot=bot)
            else:
                # PR gates check branch commits; main continuity checks resulting main trees.
                base, head = event["before"], event["after"]
                for commit in git("rev-list", "--first-parent", f"{base}..{head}").splitlines():
                    subprocess.run(
                        [
                            sys.executable,
                            str(Path(__file__).with_name("repository_policy.py")),
                            "--revision",
                            commit,
                        ],
                        check=True,
                    )
        else:
            branch, head = git("branch", "--show-current"), git("rev-parse", "HEAD")
            issue = mission(branch)
            if args.commit_message:
                subject = args.commit_message.read_text().splitlines()[0]
                validate_subject(subject, issue)
            else:
                if args.pre_push:
                    validate_push(sys.stdin.read().splitlines(), branch, head)
                    subprocess.run(["git", "diff", "--quiet", "HEAD", "--"], check=True)
                base = git("merge-base", "origin/main", head)
                validate_range(base, head, issue)
    except (ValueError, KeyError, IndexError, OSError, subprocess.CalledProcessError) as exc:
        print(f"MISSION_POLICY=FAIL: {exc}", file=sys.stderr)
        return 1
    print("MISSION_POLICY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
