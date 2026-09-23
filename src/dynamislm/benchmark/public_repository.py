"""Deterministic public-repository leak guard for protected PSE-V1 splits."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import subprocess
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from dynamislm.benchmark.constants import SplitName
from dynamislm.benchmark.contracts import BenchmarkCaseV1, BenchmarkManifestV1
from dynamislm.serialization import canonical_data, canonical_hash, canonical_json

_PROTECTED_SPLITS = frozenset({SplitName.FROZEN_VALIDATION, SplitName.HIDDEN_FINAL})
_FORBIDDEN_CASE_FIELDS = frozenset(
    {
        "answer",
        "answers",
        "case_payload",
        "expected_answer",
        "input",
        "payload",
        "prompt",
        "question",
        "question_text",
    }
)
_ALLOWED_PROTECTED_METADATA_FIELDS = frozenset(
    {
        "answer_fingerprint",
        "answer_hash",
        "benchmark_manifest_hash",
        "case_id",
        "case_ids",
        "case_payload_hash",
        "case_hashes",
        "credential_namespace",
        "exact_shingle_digest",
        "fingerprints",
        "fuzzy_fingerprint",
        "manifest_commitment",
        "manifest_hash",
        "membership_digest",
        "normalized_text_sha256",
        "payload_fingerprint",
        "payload_hash",
        "protected_case_ids",
        "protected_case_hashes",
        "protected_split",
        "split",
        "split_manifest_hash",
        "split_membership_digest",
        "split_name",
        "store_id",
        "store_version",
    }
)
_CASE_ID_LIST_FIELDS = ("case_ids", "protected_case_ids", "validation_case_ids", "hidden_case_ids")
_CASE_HASH_FIELDS = ("case_hashes", "protected_case_hashes", "hidden_case_hashes")
_SENSITIVE_PATH_PARTS = ("answer", "input", "payload", "prompt", "question")
_DIGEST_METADATA_FIELDS = frozenset(
    {
        "answer_fingerprint",
        "answer_hash",
        "benchmark_manifest_hash",
        "case_payload_hash",
        "exact_shingle_digest",
        "fuzzy_fingerprint",
        "manifest_commitment",
        "manifest_hash",
        "membership_digest",
        "normalized_text_sha256",
        "payload_fingerprint",
        "payload_hash",
        "split_manifest_hash",
        "split_membership_digest",
    }
)


@dataclass(frozen=True, slots=True)
class ProtectedPublicCaseCommitmentV1:
    protected_split: SplitName
    case_id: str
    case_payload_hash: str
    payload_hash: str
    answer_hash: str
    normalized_text_sha256: str
    exact_shingle_digest: str
    fuzzy_fingerprint: str
    split_manifest_hash: str
    benchmark_manifest_hash: str


@dataclass(frozen=True, slots=True)
class ProtectedRepositoryLeakGuardV1:
    repository_head: str
    protected_case_hashes: tuple[tuple[str, str], ...]
    artifact_count: int
    repository_artifact_digest: str
    status: str = "PASS"

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{40,64}", self.repository_head):
            raise ValueError("repository leak evidence must bind a Git HEAD")
        if not self.protected_case_hashes:
            raise ValueError("repository leak evidence must bind protected cases")
        if self.artifact_count < 1:
            raise ValueError("repository leak evidence must inspect public artifacts")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.repository_artifact_digest):
            raise ValueError("repository leak evidence must bind the scanned artifact inventory")
        if self.status != "PASS":
            raise ValueError("repository leak evidence can only be constructed after PASS")


def public_protected_case_commitments(
    cases: Iterable[BenchmarkCaseV1], benchmark_manifest: BenchmarkManifestV1
) -> tuple[ProtectedPublicCaseCommitmentV1, ...]:
    """Return the exact metadata allowed for public protected-split manifests."""

    protected_cases = tuple(case for case in cases if case.split.split_name in _PROTECTED_SPLITS)
    if not protected_cases:
        raise ValueError("protected public commitments require protected cases")
    manifest_hash = benchmark_manifest.benchmark_manifest_hash
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", manifest_hash):
        raise ValueError("protected public commitments require a bound benchmark manifest")
    commitments = tuple(
        ProtectedPublicCaseCommitmentV1(
            protected_split=_require_protected_split(case),
            case_id=case.case_id,
            case_payload_hash=case.case_payload_hash,
            payload_hash=canonical_hash({"question": case.question, "input": case.input}),
            answer_hash=canonical_hash(case.expected_answer),
            normalized_text_sha256=_required_normalized_text_fingerprint(case),
            exact_shingle_digest=case.contamination.exact_shingle_digest,
            fuzzy_fingerprint=case.contamination.fuzzy_fingerprint,
            split_manifest_hash=case.split.split_manifest_hash or "",
            benchmark_manifest_hash=manifest_hash,
        )
        for case in sorted(protected_cases, key=lambda item: item.case_id.encode("utf-8"))
    )
    if any(not commitment.split_manifest_hash for commitment in commitments):
        raise ValueError("protected public commitments require split-manifest bindings")
    return commitments


def validate_protected_repository_boundary(
    cases: Iterable[BenchmarkCaseV1],
    *,
    repository_root: str | Path,
    benchmark_manifest_hash: str | None = None,
) -> ProtectedRepositoryLeakGuardV1:
    """Scan current HEAD, the Git index, and working files for protected bytes."""

    protected_cases = tuple(case for case in cases if case.split.split_name in _PROTECTED_SPLITS)
    if not protected_cases:
        raise ValueError("protected repository guard requires validation/hidden cases")
    protected_cases = tuple(sorted(protected_cases, key=lambda item: item.case_id.encode("utf-8")))
    case_hashes = tuple((case.case_id, case.case_payload_hash) for case in protected_cases)
    root = Path(repository_root).resolve()
    repository_head = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    artifact_inventory: dict[tuple[str, str], str] = {}
    contents: list[tuple[str, str, bytes]] = []

    for object_id, relative_path in _head_blobs(root):
        data = _git(root, "cat-file", "blob", object_id)
        path = f"{relative_path}"
        artifact_inventory[("HEAD", path)] = _bytes_sha256(data)
        contents.append(("HEAD", path, data))
    for object_id, relative_path in _index_blobs(root):
        data = _git(root, "cat-file", "blob", object_id)
        artifact_inventory[("INDEX", relative_path)] = _bytes_sha256(data)
        contents.append(("INDEX", relative_path, data))
    for relative_path in _working_paths(root):
        full_path = root / PurePosixPath(relative_path)
        if full_path.is_symlink():
            data = os.fsencode(os.readlink(full_path))
        elif full_path.is_file():
            data = full_path.read_bytes()
        else:
            continue
        artifact_inventory[("WORKTREE", relative_path)] = _bytes_sha256(data)
        contents.append(("WORKTREE", relative_path, data))

    _reject_protected_material(
        protected_cases,
        contents,
        benchmark_manifest_hash=benchmark_manifest_hash,
    )
    inventory_digest = canonical_hash(
        tuple(
            (source, path, digest)
            for (source, path), digest in sorted(
                artifact_inventory.items(),
                key=lambda item: (item[0][0], item[0][1].encode("utf-8")),
            )
        )
    )
    return ProtectedRepositoryLeakGuardV1(
        repository_head=repository_head,
        protected_case_hashes=case_hashes,
        artifact_count=len(artifact_inventory),
        repository_artifact_digest=inventory_digest,
    )


def _git(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
    )
    return result.stdout


def _head_blobs(root: Path) -> Iterator[tuple[str, str]]:
    output = _git(root, "ls-tree", "-r", "-z", "HEAD")
    for record in output.split(b"\0"):
        if not record:
            continue
        header, path_bytes = record.split(b"\t", 1)
        mode, kind, object_id = header.decode("ascii").split(" ", 2)
        if kind == "blob" and mode != "160000":
            yield object_id, os.fsdecode(path_bytes)


def _index_blobs(root: Path) -> Iterator[tuple[str, str]]:
    output = _git(root, "ls-files", "--stage", "-z")
    for record in output.split(b"\0"):
        if not record:
            continue
        header, path_bytes = record.split(b"\t", 1)
        _mode, object_id, stage = header.decode("ascii").split(" ", 2)
        if stage == "0":
            yield object_id, os.fsdecode(path_bytes)


def _working_paths(root: Path) -> Iterator[str]:
    output = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    for path_bytes in output.split(b"\0"):
        if path_bytes:
            yield os.fsdecode(path_bytes)


def _bytes_sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _reject_protected_material(
    protected_cases: tuple[BenchmarkCaseV1, ...],
    contents: list[tuple[str, str, bytes]],
    *,
    benchmark_manifest_hash: str | None,
) -> None:
    case_by_id = {case.case_id: case for case in protected_cases}
    case_metadata = {case.case_id: _case_public_metadata(case) for case in protected_cases}
    case_splits = {case.case_id: _require_protected_split(case).value for case in protected_cases}
    patterns: dict[bytes, str] = {}
    expected_json_values: list[object] = []
    prompt_texts: set[str] = set()
    answer_json_texts: set[str] = set()
    for case in protected_cases:
        prompt_texts.update((case.question, case.input.question_text))
        _add_pattern(patterns, case.question.encode("utf-8"), f"{case.split.split_name} prompt")
        _add_pattern(
            patterns,
            case.input.question_text.encode("utf-8"),
            f"{case.split.split_name} prompt",
        )
        expected_json_values.extend(
            (canonical_data(case.input), canonical_data(case.expected_answer))
        )
        answer_json_texts.add(
            json.dumps(
                canonical_data(case.expected_answer),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        answer_json_texts.add(canonical_json(case.expected_answer))

    for source, path, data in contents:
        normalized_path = path.casefold()
        path_case_ids = tuple(case_id for case_id in case_by_id if case_id in path)
        if path_case_ids and any(part in normalized_path for part in _SENSITIVE_PATH_PARTS):
            case_id = min(path_case_ids, key=lambda item: item.encode("utf-8"))
            raise ValueError(
                f"protected case artifact path exposes prompt/input/answer bytes for {case_id} "
                f"in {source}:{path}"
            )
        for pattern, label in patterns.items():
            if pattern in data:
                raise ValueError(
                    f"protected {label} bytes found in public repository artifact {source}:{path}"
                )
        for document in _public_structures(data, path):
            for value in _walk_json(document):
                if isinstance(value, str) and value in prompt_texts:
                    raise ValueError(
                        f"protected prompt text found in public repository artifact {source}:{path}"
                    )
                if isinstance(value, str) and value in answer_json_texts:
                    raise ValueError(
                        "protected answer bytes found in public repository artifact "
                        f"{source}:{path}"
                    )
                if value in expected_json_values:
                    raise ValueError(
                        "protected payload/answer object found in public repository artifact "
                        f"{source}:{path}"
                    )
                if isinstance(value, dict):
                    referenced_ids = set()
                    direct_case_id = value.get("case_id")
                    if isinstance(direct_case_id, str):
                        referenced_ids.add(direct_case_id)
                    for key in _CASE_ID_LIST_FIELDS:
                        ids = value.get(key)
                        if isinstance(ids, list):
                            referenced_ids.update(item for item in ids if isinstance(item, str))
                    for key in _CASE_HASH_FIELDS:
                        pairs = value.get(key)
                        if isinstance(pairs, list):
                            referenced_ids.update(
                                item[0]
                                for item in pairs
                                if isinstance(item, list)
                                and len(item) == 2
                                and isinstance(item[0], str)
                            )
                    protected_ids = referenced_ids.intersection(case_by_id)
                    if protected_ids:
                        forbidden = set(value).intersection(_FORBIDDEN_CASE_FIELDS)
                        nested_fields = {
                            key
                            for nested in _walk_json(value)
                            if isinstance(nested, dict)
                            for key in nested
                        }
                        unexpected = nested_fields.difference(_ALLOWED_PROTECTED_METADATA_FIELDS)
                        if forbidden or unexpected:
                            case_id = min(protected_ids, key=lambda item: item.encode("utf-8"))
                            fields = sorted(forbidden or unexpected)
                            raise ValueError(
                                "public protected-split record exposes payload fields for "
                                f"{case_id} in {source}:{path}: {', '.join(fields)}"
                            )
                        _validate_metadata_values(
                            value,
                            protected_ids=protected_ids,
                            case_metadata=case_metadata,
                            case_splits=case_splits,
                            benchmark_manifest_hash=benchmark_manifest_hash,
                        )


def _case_public_metadata(case: BenchmarkCaseV1) -> dict[str, str | None]:
    return {
        "case_payload_hash": case.case_payload_hash,
        "payload_hash": canonical_hash({"question": case.question, "input": case.input}),
        "answer_hash": canonical_hash(case.expected_answer),
        "protected_split": _require_protected_split(case).value,
        "normalized_text_sha256": case.contamination.normalized_text_sha256,
        "exact_shingle_digest": case.contamination.exact_shingle_digest,
        "fuzzy_fingerprint": case.contamination.fuzzy_fingerprint,
        "membership_digest": case.split.membership_digest,
        "split_membership_digest": case.split.membership_digest,
        "split_manifest_hash": case.split.split_manifest_hash,
    }


def _require_protected_split(case: BenchmarkCaseV1) -> SplitName:
    split = case.split.split_name
    if split not in _PROTECTED_SPLITS:
        raise ValueError(f"case is not in a protected split: {case.case_id}")
    return split


def _required_normalized_text_fingerprint(case: BenchmarkCaseV1) -> str:
    fingerprint = case.contamination.normalized_text_sha256
    if fingerprint is None:
        raise ValueError(f"protected case lacks its normalized-text fingerprint: {case.case_id}")
    return fingerprint


def _validate_metadata_values(
    record: dict[str, object],
    *,
    protected_ids: set[str],
    case_metadata: dict[str, dict[str, str | None]],
    case_splits: dict[str, str],
    benchmark_manifest_hash: str | None,
) -> None:
    for nested in _walk_json(record):
        if not isinstance(nested, dict):
            continue
        for key, value in nested.items():
            if key in _DIGEST_METADATA_FIELDS:
                if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
                    raise ValueError(
                        f"public protected metadata field {key} must contain a SHA-256 digest"
                    )
                if key == "benchmark_manifest_hash" and benchmark_manifest_hash is not None:
                    if value != benchmark_manifest_hash:
                        raise ValueError(
                            "public protected record has a stale benchmark manifest hash"
                        )
                elif key in {"manifest_hash", "manifest_commitment"}:
                    continue
                elif key in {"payload_fingerprint", "answer_fingerprint"}:
                    expected_fingerprints = {
                        digest
                        for case_id in protected_ids
                        for digest in case_metadata[case_id].values()
                        if digest is not None
                    }
                    if value not in expected_fingerprints:
                        raise ValueError(f"public protected record has an unregistered {key}")
                elif key in case_metadata[next(iter(protected_ids))]:
                    expected_values = {case_metadata[case_id].get(key) for case_id in protected_ids}
                    if value not in expected_values:
                        raise ValueError(f"public protected record has a stale or wrong {key}")
            elif key == "case_id":
                if not isinstance(value, str) or value not in case_metadata:
                    raise ValueError("public protected record has an unknown case ID")
            elif key in _CASE_ID_LIST_FIELDS and isinstance(value, list):
                if any(not isinstance(item, str) or item not in case_metadata for item in value):
                    raise ValueError("public protected record has an unknown protected case ID")
            elif key in _CASE_HASH_FIELDS and isinstance(value, list):
                for pair in value:
                    if not (
                        isinstance(pair, list)
                        and len(pair) == 2
                        and isinstance(pair[0], str)
                        and isinstance(pair[1], str)
                        and pair[0] in case_metadata
                        and pair[1] == case_metadata[pair[0]]["case_payload_hash"]
                    ):
                        raise ValueError("public protected record has a stale or wrong case hash")
            elif key in {"split", "protected_split", "split_name"}:
                expected_splits = {case_splits[case_id] for case_id in protected_ids}
                if isinstance(value, str) and value not in expected_splits:
                    raise ValueError("public protected record has a wrong split label")
                if not isinstance(value, str | dict):
                    raise ValueError("public protected split metadata is malformed")


def _public_structures(data: bytes, path: str) -> Iterator[object]:
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError:
        return
    suffix = PurePosixPath(path).suffix.casefold()
    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        reader = csv.DictReader(io.StringIO(decoded), delimiter=delimiter)
        yield from reader
        return
    try:
        yield json.loads(decoded)
        return
    except json.JSONDecodeError:
        if suffix not in {".jsonl", ".ndjson"}:
            return
    for line in decoded.splitlines():
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _add_pattern(patterns: dict[bytes, str], pattern: bytes, label: str) -> None:
    if pattern:
        patterns.setdefault(pattern, label)


def _walk_json(value: object) -> Iterator[object]:
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk_json(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_json(item)


__all__ = [
    "ProtectedPublicCaseCommitmentV1",
    "ProtectedRepositoryLeakGuardV1",
    "public_protected_case_commitments",
    "validate_protected_repository_boundary",
]
