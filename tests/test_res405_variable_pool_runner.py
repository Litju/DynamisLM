from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from scripts import res405_variable_pool as runner


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-C", str(root), *args),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_runner_requires_clean_tracked_files_and_leaves_untracked_files_alone(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--quiet", "--initial-branch", runner._BRANCH)
    _git(root, "config", "user.name", "RES-405 test")
    _git(root, "config", "user.email", "res405-test@example.invalid")
    tracked = root / "tracked.txt"
    tracked.write_text("committed\n", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "--quiet", "-m", "baseline")
    head = _git(root, "rev-parse", "HEAD")
    monkeypatch.setattr(runner, "DYNAMISLM_EXECUTION_BASELINE", head)

    assert runner._require_clean_execution_tree(root) == head
    forensic = root / "docs" / "qualification" / "RES-397-ACCEPTANCE-RECEIPT.md"
    forensic.parent.mkdir(parents=True)
    forensic.write_text("local forensic evidence\n", encoding="utf-8")
    assert runner._require_clean_execution_tree(root) == head

    tracked.write_text("edited\n", encoding="utf-8")
    with pytest.raises(ValueError, match="clean tracked worktree"):
        runner._require_clean_execution_tree(root)
