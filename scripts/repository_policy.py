"""Deterministic policy for tracked repository data and secret-like files."""

from __future__ import annotations

import fnmatch
import subprocess
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

MAX_FIXTURE_SIZE_BYTES = 1 * 1024 * 1024
APPROVED_FIXTURE_ROOT = "tests/fixtures/synthetic"
CONTROLLED_FIXTURE_EXTENSIONS = frozenset({".csv", ".tsv", ".xlsx", ".zip"})
FORBIDDEN_DIRECTORY_NAMES = frozenset(
    {
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
        or lower_basename in {"id_rsa", "id_ed25519"}
        or fnmatch.fnmatchcase(lower_basename, "*.pem")
        or fnmatch.fnmatchcase(lower_basename, "*.key")
    )


def _path_failures(
    path: str,
    size_bytes: int,
    allowlisted_fixtures: frozenset[str],
) -> tuple[str, ...]:
    if size_bytes < 0:
        return (f"MISSING_TRACKED_FILE={path}",)

    path_parts = PurePosixPath(path).parts
    if any(part in FORBIDDEN_DIRECTORY_NAMES for part in path_parts):
        return (f"FORBIDDEN_PATH={path}",)

    suffix = PurePosixPath(path).suffix.lower()
    if suffix in FORBIDDEN_EXTENSIONS:
        return (f"FORBIDDEN_EXTENSION={path}",)

    if _is_secret_like(path):
        return (f"SECRET_LIKE_FILE={path}",)

    if suffix in CONTROLLED_FIXTURE_EXTENSIONS:
        if not _is_under(path, APPROVED_FIXTURE_ROOT) or path not in allowlisted_fixtures:
            return (f"UNALLOWLISTED_FIXTURE={path}",)
        if size_bytes > MAX_FIXTURE_SIZE_BYTES:
            return (f"OVERSIZED_FIXTURE={path}",)

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


def _read_fixture_allowlist(repo_root: Path) -> tuple[str, ...]:
    allowlist_path = repo_root / ".repo-policy" / "allowed-fixtures.txt"
    if not allowlist_path.is_file():
        return ()
    return tuple(
        line
        for line in (
            raw_line.strip() for raw_line in allowlist_path.read_text(encoding="utf-8").splitlines()
        )
        if line and not line.startswith("#")
    )


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    failures = evaluate_paths(
        tracked_path_sizes(repo_root),
        allowlisted_fixtures=_read_fixture_allowlist(repo_root),
    )
    if failures:
        print("\n".join(failures))
        return 1
    print("REPOSITORY_POLICY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
