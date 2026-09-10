"""Repository-external, content-addressed storage for RES-63 artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from dynamislm.serialization import canonical_json

DATA_ROOT_ENVIRONMENT_VARIABLE = "DYNAMISLM_DATA_ROOT"
DEFAULT_DATA_ROOT_RELATIVE = Path("data") / "dynamislm"
ACQUISITION_TEMP_RELATIVE = Path("tmp") / "acquisition"
DATA_ROOT_DIRECTORIES = (
    Path("objects") / "sha256",
    Path("metadata"),
    Path("receipts"),
    Path("canonical"),
    Path("quarantine"),
    ACQUISITION_TEMP_RELATIVE,
)
_CHUNK_SIZE = 1024 * 1024


def resolve_repository_root(start: Path | None = None) -> Path:
    """Resolve the current Git project root without a repository path constant."""

    candidate = (start or Path.cwd()).expanduser()
    if not candidate.exists():
        raise ValueError(f"repository context does not exist: {candidate}")
    if candidate.is_file():
        candidate = candidate.parent
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=candidate,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise ValueError("could not resolve a Git repository root from the current project context")
    return Path(result.stdout.strip()).resolve()


def _configured_data_root(configured_root: str | Path | None) -> Path:
    if configured_root is None:
        configured_text = os.environ.get(DATA_ROOT_ENVIRONMENT_VARIABLE)
        if configured_text is None:
            return (Path.home() / DEFAULT_DATA_ROOT_RELATIVE).resolve(strict=False)
        if not configured_text.strip():
            raise ValueError(f"{DATA_ROOT_ENVIRONMENT_VARIABLE} must not be empty")
        configured_root = configured_text
    return Path(configured_root).expanduser().resolve(strict=False)


def assert_external_data_root(data_root: Path, repository_root: Path) -> Path:
    """Fail closed if the resolved data root is the repository or beneath it."""

    resolved_data_root = data_root.expanduser().resolve(strict=False)
    resolved_repository_root = repository_root.expanduser().resolve(strict=False)
    if resolved_data_root == resolved_repository_root or resolved_data_root.is_relative_to(
        resolved_repository_root
    ):
        raise ValueError(
            "DYNAMISLM_DATA_ROOT must be outside the repository root after symlink resolution"
        )
    return resolved_data_root


def resolve_data_root(
    configured_root: str | Path | None = None,
    *,
    repository_root: Path | None = None,
    project_context: Path | None = None,
) -> Path:
    """Resolve and validate the configured external empirical-data root."""

    repo_root = repository_root or resolve_repository_root(project_context)
    data_root = _configured_data_root(configured_root)
    return assert_external_data_root(data_root, repo_root)


def ensure_data_tree(
    configured_root: str | Path | None = None,
    *,
    repository_root: Path | None = None,
    project_context: Path | None = None,
) -> Path:
    """Create the fixed external tree after the containment guard passes."""

    data_root = resolve_data_root(
        configured_root,
        repository_root=repository_root,
        project_context=project_context,
    )
    for relative_directory in DATA_ROOT_DIRECTORIES:
        (data_root / relative_directory).mkdir(parents=True, exist_ok=True)
    return data_root


def _digest_hex(digest: str) -> str:
    value = digest.removeprefix("sha256:").lower()
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("digest must be a SHA-256 hexadecimal value")
    return value


def content_addressed_object_path(data_root: Path, digest: str) -> Path:
    """Return ``objects/sha256/<first-two>/<full-digest>`` for a digest."""

    digest_hex = _digest_hex(digest)
    return data_root.resolve(strict=False) / "objects" / "sha256" / digest_hex[:2] / digest_hex


def relative_data_path(data_root: Path, path: Path) -> str:
    """Return a portable data-root-relative POSIX path and reject escapes."""

    resolved_root = data_root.expanduser().resolve(strict=False)
    resolved_path = path.expanduser().resolve(strict=False)
    try:
        relative = resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("path is not inside DYNAMISLM_DATA_ROOT") from exc
    return relative.as_posix()


def file_digest_and_size(path: Path) -> tuple[str, int]:
    """Stream one file and return its SHA-256 digest and exact byte size."""

    digest = hashlib.sha256()
    byte_size = 0
    try:
        with path.open("rb") as source:
            while chunk := source.read(_CHUNK_SIZE):
                digest.update(chunk)
                byte_size += len(chunk)
    except OSError as exc:
        raise ValueError(f"could not read artifact bytes: {path}") from exc
    return f"sha256:{digest.hexdigest()}", byte_size


def store_verified_temporary_file(
    temporary_path: Path,
    *,
    data_root: Path,
    expected_sha256: str,
    expected_byte_size: int,
) -> Path:
    """Verify and atomically store a temporary acquisition by content address."""

    expected_digest = f"sha256:{_digest_hex(expected_sha256)}"
    if not isinstance(expected_byte_size, int) or isinstance(expected_byte_size, bool):
        raise ValueError("expected_byte_size must be an integer")
    if expected_byte_size < 0:
        raise ValueError("expected_byte_size must not be negative")
    temporary_relative = relative_data_path(data_root, temporary_path)
    if not temporary_relative.startswith("tmp/acquisition/"):
        raise ValueError("temporary acquisition must be under tmp/acquisition")
    actual_digest, actual_size = file_digest_and_size(temporary_path)
    if actual_digest != expected_digest or actual_size != expected_byte_size:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise ValueError("downloaded bytes do not match the expected SHA-256 digest and byte size")

    target = content_addressed_object_path(data_root, expected_digest)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        existing_digest, existing_size = file_digest_and_size(target)
        if existing_digest != expected_digest or existing_size != expected_byte_size:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
            raise ValueError("existing content-addressed object failed digest or size verification")
        temporary_path.unlink()
        return target

    os.replace(temporary_path, target)
    stored_digest, stored_size = file_digest_and_size(target)
    if stored_digest != expected_digest or stored_size != expected_byte_size:
        raise ValueError("atomically stored object failed digest or size verification")
    return target


def write_external_json(data_root: Path, relative_path: str, value: object) -> Path:
    """Write a deterministic JSON receipt/report under the external data root."""

    target = (data_root / relative_path).resolve(strict=False)
    relative_data_path(data_root, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    serialized = (
        canonical_json(value)
        if not isinstance(value, dict | list)
        else json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8", newline="\n") as output:
        output.write(serialized)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, target)
    return target


def count_files(relative_directory: Path, data_root: Path) -> int:
    directory = data_root / relative_directory
    if not directory.exists():
        return 0
    return sum(1 for path in directory.rglob("*") if path.is_file())


def data_root_inventory(data_root: Path) -> dict[str, int]:
    """Return deterministic category counts and total bytes for handoff evidence."""

    resolved_root = data_root.resolve(strict=False)
    total_bytes = sum(path.stat().st_size for path in resolved_root.rglob("*") if path.is_file())
    return {
        "DATA_ROOT_TOTAL_BYTES": total_bytes,
        "DATA_ROOT_OBJECT_COUNT": count_files(Path("objects"), resolved_root),
        "DATA_ROOT_METADATA_COUNT": count_files(Path("metadata"), resolved_root),
        "DATA_ROOT_RECEIPT_COUNT": count_files(Path("receipts"), resolved_root),
        "DATA_ROOT_CANONICAL_ARTIFACT_COUNT": count_files(Path("canonical"), resolved_root),
        "DATA_ROOT_QUARANTINE_COUNT": count_files(Path("quarantine"), resolved_root),
    }


def sha256_file(path: Path) -> str:
    """Return only the SHA-256 digest for callers that do not need the size."""

    return file_digest_and_size(path)[0]


def verify_file(
    path: Path,
    *,
    expected_sha256: str,
    expected_byte_size: int | None = None,
) -> None:
    """Fail closed when an existing file differs from a registered identity."""

    actual_digest, actual_size = file_digest_and_size(path)
    normalized = f"sha256:{_digest_hex(expected_sha256)}"
    if actual_digest != normalized:
        raise ValueError("file SHA-256 differs from the registered identity")
    if expected_byte_size is not None and actual_size != expected_byte_size:
        raise ValueError("file byte size differs from the registered identity")


def real_data_git_firewall(repo_root: Path, data_root: Path) -> dict[str, bool]:
    """Compare real raw/canonical bytes with tracked Git files by full digest."""

    resolved_root = resolve_data_root(data_root, repository_root=repo_root)
    tracked_result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    tracked_paths = tuple(
        repo_root / Path(path) for path in tracked_result.stdout.decode("utf-8").split("\0") if path
    )
    tracked_digests: set[str] = set()
    for tracked_path in tracked_paths:
        if tracked_path.is_file():
            tracked_digests.add(file_digest_and_size(tracked_path)[0])

    raw_digests: set[str] = set()
    raw_directory = resolved_root / "objects" / "sha256"
    if raw_directory.exists():
        for path in raw_directory.rglob("*"):
            if path.is_file():
                raw_digests.add(file_digest_and_size(path)[0])
    canonical_digests: set[str] = set()
    canonical_directory = resolved_root / "canonical"
    if canonical_directory.exists():
        for path in canonical_directory.rglob("*"):
            if path.is_file():
                canonical_digests.add(file_digest_and_size(path)[0])

    raw_in_git = bool(raw_digests & tracked_digests)
    canonical_in_git = bool(canonical_digests & tracked_digests)
    if raw_in_git or canonical_in_git:
        raise ValueError("real raw or canonical artifact bytes are present in tracked Git files")
    return {
        "RAW_SOURCE_BYTES_IN_GIT": raw_in_git,
        "REAL_CANONICAL_ROWS_IN_GIT": canonical_in_git,
    }


__all__ = [
    "ACQUISITION_TEMP_RELATIVE",
    "DATA_ROOT_DIRECTORIES",
    "DATA_ROOT_ENVIRONMENT_VARIABLE",
    "DEFAULT_DATA_ROOT_RELATIVE",
    "assert_external_data_root",
    "content_addressed_object_path",
    "count_files",
    "data_root_inventory",
    "ensure_data_tree",
    "file_digest_and_size",
    "real_data_git_firewall",
    "relative_data_path",
    "resolve_data_root",
    "resolve_repository_root",
    "sha256_file",
    "store_verified_temporary_file",
    "verify_file",
    "write_external_json",
]
