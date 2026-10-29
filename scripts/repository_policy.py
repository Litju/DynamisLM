"""Deterministic policy for tracked repository data and secret-like files."""

from __future__ import annotations

import argparse
import csv
import fnmatch
import hashlib
import io
import json
import os
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any

BASELINE = "6d6892c95134f83ffdb224e11e6e3603296fc5ed"
LEGACY_HEAD = "97d361badf02a80b411aaefdb6ddac1c4e8e126e"
LEGACY_BRANCH = "julitocrztuga/res-541-a0-wslcolab-gpu-scientific-reasoning-alpha-development-only"
MAX_FILE_SIZE_BYTES = 1 * 1024 * 1024
MAX_FIXTURE_SIZE_BYTES = MAX_FILE_SIZE_BYTES
INVENTORY = ".repo-policy/noncode-inventory.tsv"
APPROVED_FIXTURE_ROOT = "tests/fixtures/synthetic"
APPROVED_DATASET_REGISTRY_ROOT = "registries/datasets"
CONTROLLED_FIXTURE_EXTENSIONS = frozenset({".csv", ".tab", ".tsv", ".xlsx", ".zip"})
FORBIDDEN_DIRECTORY_NAMES = frozenset(
    {
        ".cache",
        ".git",
        ".ipynb_checkpoints",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "notebooks",
        "tmp",
        "artifacts",
        "checkpoints",
        "corpus",
        "corpus-shards",
        "data",
        "datasets",
        "hf-cache",
        "local-data",
        "logs",
        "model-weights",
        "optimizer-states",
        "training-outputs",
    }
)
FORBIDDEN_EXTENSIONS = frozenset(
    {
        ".ipynb",
        ".jsonl",
        ".ndjson",
        ".sqlite",
        ".sqlite3",
        ".db",
        ".pkl",
        ".pickle",
        ".onnx",
        ".gguf",
        ".ggml",
        ".pyc",
        ".arrow",
        ".bin",
        ".ckpt",
        ".h5",
        ".hdf5",
        ".npy",
        ".npz",
        ".parquet",
        ".pth",
        ".pt",
        ".safetensors",
    }
)

type TrackedPath = tuple[str, int]


def _is_under(path: str, root: str) -> bool:
    path_parts = PurePosixPath(path).parts
    root_parts = PurePosixPath(root).parts
    return path_parts[: len(root_parts)] == root_parts and len(path_parts) > len(root_parts)


def _is_secret_like(path: str) -> bool:
    basename = PurePosixPath(path).name
    lower_basename = basename.lower()
    if lower_basename == ".env.example":
        return False
    return (
        lower_basename == ".env"
        or lower_basename.startswith(".env.")
        or lower_basename
        in {
            "id_rsa",
            "id_ed25519",
            "credentials.json",
            "credentials",
            "token",
            "tokens.json",
            ".netrc",
            ".pypirc",
        }
        or fnmatch.fnmatchcase(lower_basename, "*.pem")
        or fnmatch.fnmatchcase(lower_basename, "*.key")
    )


def _is_public_dataset_registry(path: str) -> bool:
    candidate = PurePosixPath(path)
    return (
        candidate.parent.as_posix() == APPROVED_DATASET_REGISTRY_ROOT
        and candidate.suffix == ".json"
    )


def _path_failures(
    path: str,
    size_bytes: int,
    allowlisted_fixtures: frozenset[str],
) -> tuple[str, ...]:
    if size_bytes < 0:
        return (f"MISSING_TRACKED_FILE={path}",)

    path_parts = PurePosixPath(path).parts
    if any(
        part.lower() in FORBIDDEN_DIRECTORY_NAMES for part in path_parts
    ) and not _is_public_dataset_registry(path):
        return (f"FORBIDDEN_PATH={path}",)

    suffix = PurePosixPath(path).suffix.lower()
    if suffix in FORBIDDEN_EXTENSIONS:
        return (f"FORBIDDEN_EXTENSION={path}",)

    if _is_secret_like(path):
        return (f"SECRET_LIKE_FILE={path}",)

    if suffix in CONTROLLED_FIXTURE_EXTENSIONS and path != INVENTORY:
        if not _is_under(path, APPROVED_FIXTURE_ROOT) or path not in allowlisted_fixtures:
            return (f"UNALLOWLISTED_FIXTURE={path}",)
        if size_bytes > MAX_FIXTURE_SIZE_BYTES:
            return (f"OVERSIZED_FIXTURE={path}",)

    if size_bytes > MAX_FILE_SIZE_BYTES:
        return (f"OVERSIZED_FILE={path}",)

    return ()


def evaluate_paths(
    paths: Iterable[TrackedPath],
    *,
    allowlisted_fixtures: Iterable[str] = (),
) -> tuple[str, ...]:
    """Return deterministic policy failures for path/size pairs."""

    allowlist = frozenset(PurePosixPath(path).as_posix() for path in allowlisted_fixtures)
    failures: list[str] = []
    for path, size_bytes in sorted(paths, key=lambda item: item[0]):
        failures.extend(_path_failures(path, size_bytes, allowlist))
    return tuple(failures)


def tracked_path_sizes(repo_root: Path) -> tuple[TrackedPath, ...]:
    """Read only tracked paths from Git and attach their current file sizes."""

    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    paths = tuple(path for path in result.stdout.decode("utf-8").split("\0") if path)
    records: list[TrackedPath] = []
    for path in paths:
        try:
            size_bytes = (repo_root / PurePosixPath(path)).stat().st_size
        except OSError:
            size_bytes = -1
        records.append((path, size_bytes))
    return tuple(records)


def is_noncode(path: str) -> bool:
    return PurePosixPath(path).suffix not in {".py", ".sh"} and not path.startswith(".githooks/")


def is_evidence(path: str) -> bool:
    return path.startswith(
        ("docs/architecture/", "docs/decisions/", "docs/qualification/", "reports/", "registries/")
    ) and not path.endswith("README.md")


def git_bytes(repo_root: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=repo_root, check=True, capture_output=True).stdout


def is_legacy_pr(pr: dict[str, Any], repo_root: Path) -> bool:
    """Only PR #46 in the original repository may retain its pinned ancestry."""
    if not (
        pr.get("number") == 46
        and pr["head"]["ref"] == LEGACY_BRANCH
        and pr["base"]["ref"] == "main"
        and pr["base"]["repo"]["full_name"] == "Litju/DynamisLM"
        and pr["head"]["repo"]["full_name"] == "Litju/DynamisLM"
    ):
        return False
    if (
        git_bytes(repo_root, "merge-base", BASELINE, LEGACY_HEAD).decode().strip() != BASELINE
        or git_bytes(repo_root, "rev-list", "--count", f"{BASELINE}..{LEGACY_HEAD}").strip()
        != b"27"
    ):
        raise ValueError("LEGACY_ANCESTRY: historical range must remain exactly pinned")
    git_bytes(repo_root, "merge-base", "--is-ancestor", LEGACY_HEAD, pr["head"]["sha"])
    git_bytes(repo_root, "merge-base", "--is-ancestor", BASELINE, pr["base"]["sha"])
    return True


def local_legacy_pr(repo_root: Path) -> dict[str, Any] | None:
    if git_bytes(repo_root, "branch", "--show-current").decode().strip() != LEGACY_BRANCH:
        return None
    pr: dict[str, Any] = json.loads(
        subprocess.run(
            ["gh", "api", "--hostname", "github.com", "repos/Litju/DynamisLM/pulls/46"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    if not is_legacy_pr(pr, repo_root):
        raise ValueError("LEGACY_PR_IDENTITY")
    pr["head"]["sha"] = git_bytes(repo_root, "rev-parse", "HEAD").decode().strip()
    if not is_legacy_pr(pr, repo_root):
        raise ValueError("LEGACY_LOCAL_ANCESTRY")
    return pr


def repository_failures(
    repo_root: Path, revision: str | None = None, *, pr: dict[str, Any] | None = None
) -> tuple[str, ...]:
    """Check actual index/commit blobs; without a revision also check tracked working bytes."""
    entries = (
        git_bytes(repo_root, "ls-tree", "-rz", revision)
        if revision
        else git_bytes(repo_root, "ls-files", "--stage", "-z")
    )
    blobs: dict[str, bytes] = {}
    failures: list[str] = []
    for entry in entries.split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, kind_or_oid, oid_or_stage = metadata.decode().split()
        path = raw_path.decode("utf-8")
        if mode not in {"100644", "100755"} or (not revision and oid_or_stage != "0"):
            failures.append(f"NON_REGULAR_OR_UNMERGED_FILE={path}")
            continue
        oid = oid_or_stage if revision else kind_or_oid
        size = int(git_bytes(repo_root, "cat-file", "-s", oid))
        if size > MAX_FILE_SIZE_BYTES:
            failures.append(f"OVERSIZED_FILE={path}")
            continue
        blobs[path] = git_bytes(repo_root, "cat-file", "blob", oid)

    legacy_blobs: set[str] = set()
    if pr is not None and is_legacy_pr(pr, repo_root):
        for path in (
            git_bytes(repo_root, "diff", "--name-only", "--diff-filter=A", BASELINE, LEGACY_HEAD)
            .decode()
            .splitlines()
        ):
            if blobs.get(path) == git_bytes(repo_root, "show", f"{LEGACY_HEAD}:{path}"):
                legacy_blobs.add(path)

    allowlist = tuple(
        line.strip()
        for line in blobs.get(".repo-policy/allowed-fixtures.txt", b"").decode().splitlines()
        if line.strip() and not line.startswith("#")
    )
    failures.extend(
        evaluate_paths(((p, len(b)) for p, b in blobs.items()), allowlisted_fixtures=allowlist)
    )
    try:
        rows = list(csv.DictReader(io.StringIO(blobs[INVENTORY].decode()), delimiter="\t"))
        inventory = {r["path"]: r for r in rows}
        legacy_paths = {p for p in legacy_blobs if is_noncode(p)}
        if len(rows) != len(inventory) or (set(inventory) | legacy_paths) != {
            p for p in blobs if is_noncode(p)
        }:
            failures.append("NONCODE_INVENTORY_MISMATCH")
        for path, row in inventory.items():
            if row["classification"] not in {"configuration", "authority", "documentation"}:
                failures.append(f"INVALID_CLASSIFICATION={path}")
            if not row["reason"].strip():
                failures.append(f"MISSING_DISPOSITION={path}")
            if is_evidence(path) and (
                row["classification"] != "authority"
                or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
            ):
                failures.append(f"UNCLASSIFIED_OR_UNPINNED_AUTHORITY={path}")
            digest = row["sha256"]
            if digest != "-" and hashlib.sha256(blobs.get(path, b"")).hexdigest() != digest:
                failures.append(f"INVENTORY_DIGEST_MISMATCH={path}")
    except (KeyError, ValueError, UnicodeError, csv.Error):
        failures.append("INVALID_NONCODE_INVENTORY")
        inventory = {}

    # Baseline authority cannot be unpinned by editing the inventory to obtain PASS.
    baseline_paths = git_bytes(repo_root, "ls-tree", "-rz", BASELINE)
    for entry in baseline_paths.split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        path = raw_path.decode()
        if is_evidence(path) or (
            path.startswith("tests/fixtures/synthetic/") and not path.endswith("README.md")
        ):
            oid = metadata.decode().split()[2]
            expected = git_bytes(repo_root, "cat-file", "blob", oid)
            if blobs.get(path) != expected:
                failures.append(f"BASELINE_EVIDENCE_CHANGED={path}")
            if inventory.get(path, {}).get("sha256") != hashlib.sha256(expected).hexdigest():
                failures.append(f"BASELINE_EVIDENCE_UNPINNED={path}")

    for path in allowlist:
        row = inventory.get(path, {})
        if not _is_under(path, APPROVED_FIXTURE_ROOT) or not re.fullmatch(
            r"[0-9a-f]{64}", row.get("sha256", "")
        ):
            failures.append(f"UNBOUNDED_FIXTURE_EXCEPTION={path}")

    secret = re.compile(
        rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
        rb"|(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})"
        rb"|AKIA[0-9A-Z]{16}"
    )
    for path, content in blobs.items():
        try:
            content.decode("utf-8")
        except UnicodeError:
            failures.append(f"BINARY_FILE={path}")
        if b"\0" in content:
            failures.append(f"BINARY_FILE={path}")
        # PR #46 contains a public key-format marker in an exact pinned source blob.
        if secret.search(content) and not (
            path == "scripts/request_issuer.py" and path in legacy_blobs
        ):
            failures.append(f"SECRET_CONTENT={path}")
        if revision is None:
            local = repo_root / path
            if (
                local.is_symlink()
                or not local.is_file()
                or local.stat().st_size != len(content)
                or local.read_bytes() != content
            ):
                failures.append(f"INDEX_WORKTREE_MISMATCH={path}")
    return tuple(failures)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--revision", help="Check a committed tree instead of index and working tree"
    )
    parser.add_argument("--staged", action="store_true", help="Check index blobs only")
    parser.add_argument("--event", type=Path, default=os.environ.get("GITHUB_EVENT_PATH"))
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    # write-tree fails closed on unresolved index entries and never includes unstaged bytes.
    revision = args.revision
    if args.staged:
        revision = git_bytes(repo_root, "write-tree").decode().strip()
    event = json.loads(args.event.read_text()) if args.event else {}
    pr = event.get("pull_request") if args.event else local_legacy_pr(repo_root)
    failures = repository_failures(repo_root, revision, pr=pr)
    if failures:
        print("\n".join(failures))
        return 1
    print("REPOSITORY_POLICY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
