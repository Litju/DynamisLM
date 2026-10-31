"""RES-417 CPU processing; receipts are evidence, never release capabilities."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from itertools import islice
from pathlib import Path
from typing import Any

from dynamislm.serialization import canonical_bytes, canonical_hash
from dynamislm.training_data import admission
from dynamislm.training_data.admission import Request

TRANSFORM = "res417-utf8-lines-v1"
REQUIRED_EXCLUSIONS = frozenset(
    {
        "PSE_VALIDATION",
        "PSE_HIDDEN_FINAL",
        "BENCHMARK_ANSWERS",
        "UNAPPROVED_BENCHMARK",
        "VALIDATION",
    }
)
# Independent governance provisions exact exclusion bundles in a reviewed code release.
_EXCLUSION_COMMITMENTS: frozenset[str] = frozenset()
MAX_BYTES = 1_000_000
MAX_TOKENS = 4096
MAX_DOCUMENTS = 256
MAX_WORK_UNITS = 2_000_000
SCREENING_VERSION = "res417-lcs-weighted-cells-v2"


def sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def normalize(raw: bytes) -> bytes:
    """Only line endings change; no Unicode folding, whitespace or equation rewriting."""
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("empty or oversized scientific text")
    text = raw.decode("utf-8", errors="strict")
    if any(ord(c) < 32 and c not in "\r\n\t" for c in text):
        raise ValueError("unsupported control character")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


@dataclass(frozen=True)
class _Text:
    digest: str
    tokens: tuple[str, ...]
    max_token_length: int


def _text(raw: bytes) -> _Text:
    tokens = tuple(islice(re.finditer(r"\w+|[^\w\s]", raw.decode()), MAX_TOKENS + 1))
    values = tuple(match.group() for match in tokens)
    return _Text(sha256(raw), values, max(map(len, values), default=0))


@dataclass
class _ScreeningWork:
    comparisons: int = 0
    used_work_units: int = 0
    dp_cells: int = 0
    deferred_comparisons: int = 0
    budget_exhausted: bool = False


def _screen_pair(left: _Text, right: _Text, work: _ScreeningWork) -> str:
    work.comparisons += 1
    if left.digest == right.digest:
        return "EXACT"
    a, b = left.tokens, right.tokens
    if not a or not b or max(len(a), len(b)) > MAX_TOKENS:
        work.deferred_comparisons += 1
        return "MANUAL_REVIEW"
    cells = len(a) * len(b)
    # Each cell does one token equality plus constant-size DP updates.
    cost = cells * (1 + min(left.max_token_length, right.max_token_length))
    if cost > MAX_WORK_UNITS - work.used_work_units:
        work.budget_exhausted = True
        work.deferred_comparisons += 1
        return "MANUAL_REVIEW"
    work.used_work_units += cost
    work.dp_cells += cells
    previous = [0] * (len(b) + 1)
    runs = [0] * (len(b) + 1)
    longest = 0
    for token in a:
        current = [0] * (len(b) + 1)
        next_runs = [0] * (len(b) + 1)
        for j, other in enumerate(b, 1):
            if token == other:
                current[j] = previous[j - 1] + 1
                next_runs[j] = runs[j - 1] + 1
                longest = max(longest, next_runs[j])
            else:
                current[j] = max(previous[j], current[j - 1])
        previous, runs = current, next_runs
    # LCS includes every ordered match found by either former greedy orientation.
    if 4 * previous[-1] >= len(a) + len(b) or longest >= 8:
        return "MANUAL_REVIEW"
    return "NONE"


def _overlap(left: bytes, right: bytes) -> str:
    return _screen_pair(_text(left), _text(right), _ScreeningWork())


def _exclusions(raw: bytes | None) -> list[dict[str, Any]] | None:
    if raw is None or sha256(raw) not in _EXCLUSION_COMMITMENTS:
        return None
    bundle = admission._document(raw)
    if set(bundle) != {"schema", "entries"} or bundle["schema"] != "RES417-EXCLUSIONS-1":
        raise ValueError("invalid exclusion bundle")
    entries = bundle["entries"]
    if not isinstance(entries, list) or len(entries) > MAX_DOCUMENTS:
        raise ValueError("invalid exclusion entries")
    if not entries:
        return None
    roles: set[str] = set()
    identities: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"identity", "role", "text", "sha256"}:
            raise ValueError("invalid exclusion identity")
        if not all(isinstance(v, str) and v for v in entry.values()):
            raise ValueError("invalid exclusion value")
        if entry["identity"] in identities or entry["role"] not in REQUIRED_EXCLUSIONS:
            raise ValueError("duplicate or unknown exclusion identity")
        content = entry["text"].encode("utf-8")
        if sha256(content) != entry["sha256"]:
            raise ValueError("changed exclusion bytes")
        normalize(content)
        identities.add(entry["identity"])
        roles.add(entry["role"])
    return entries if roles == REQUIRED_EXCLUSIONS else None


def require_external(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.is_relative_to(admission._PRODUCTION_ROOT.resolve()):
        raise ValueError("artifacts must be outside repository")
    parent = resolved
    while not parent.exists():
        parent = parent.parent
    result = subprocess.run(
        [
            "git",
            "-C",
            str(parent if parent.is_dir() else parent.parent),
            "rev-parse",
            "--absolute-git-dir",
        ],
        capture_output=True,
    )
    if result.returncode == 0:
        raise ValueError("artifacts must be outside Git")
    return resolved


def process_training_inputs(
    inputs: tuple[tuple[Request, bytes, bytes], ...],
    *,
    exclusion_bundle: bytes | None,
    output_root: Path,
) -> dict[str, Any]:
    """Reauthorize all bytes on every run; publish a shard only for a qualified batch.

    No saved admission, receipt, permission flag or caller-selected trust is accepted.
    Quarantine emits only identity receipts, never input text.
    """
    root = require_external(output_root)
    if not 0 < len(inputs) <= MAX_DOCUMENTS:
        raise ValueError("invalid batch size")
    inputs = tuple(
        sorted(inputs, key=lambda item: canonical_bytes((asdict(item[0]), sha256(item[2]))))
    )
    trust_commitment = admission._PRODUCTION_TRUST_SHA256
    normalized: list[bytes] = []
    rows: list[dict[str, Any]] = []
    for request, content, grant in inputs:
        if request.transformations != (TRANSFORM,):
            raise ValueError("unsupported transformation pipeline")
        released = admission.authorize_training_bytes(request, content, grant)
        normalized.append(normalize(released))
        rows.append(
            {
                "request": asdict(request),
                "raw_sha256": sha256(content),
                "normalized_sha256": sha256(normalized[-1]),
                "grant_sha256": sha256(grant),
                "status": "CLEAN",
                "findings": [],
            }
        )
    exclusions = _exclusions(exclusion_bundle)
    texts = [_text(raw) for raw in normalized]
    excluded_texts = [
        (entry, _text(normalize(entry["text"].encode())))
        for entry in sorted(exclusions or [], key=canonical_bytes)
    ]
    work = _ScreeningWork()
    for i, row in enumerate(rows):
        for j in range(i):
            other = rows[j]
            identity = row["request"]["source"]
            previous = other["request"]["source"]
            same_identity = (identity["source_id"], identity["version"]) == (
                previous["source_id"],
                previous["version"],
            )
            overlap = _screen_pair(texts[i], texts[j], work)
            if same_identity or overlap != "NONE":
                finding = {
                    "kind": (
                        "DUPLICATE_IDENTITY"
                        if same_identity
                        else "EXACT_BYTES"
                        if row["raw_sha256"] == other["raw_sha256"]
                        else "NORMALIZED_CONTENT"
                        if overlap == "EXACT"
                        else overlap
                    ),
                    "peer_sha256": other["raw_sha256"],
                }
                row["findings"].append(finding)
                other["findings"].append({**finding, "peer_sha256": row["raw_sha256"]})
        if exclusions is not None:
            for entry, excluded in excluded_texts:
                overlap = _screen_pair(texts[i], excluded, work)
                if overlap != "NONE":
                    row["findings"].append(
                        {
                            "kind": "CONTAMINATED" if overlap == "EXACT" else "MANUAL_REVIEW",
                            "exclusion_sha256": entry["sha256"],
                            "role": entry["role"],
                        }
                    )
    text_by_digest = {sha256(text): text for text in normalized}
    for row in rows:
        row["findings"].sort(key=canonical_bytes)
        row["document_sha256"] = canonical_hash(
            {
                "request": row["request"],
                "grant_sha256": row["grant_sha256"],
                "normalized_sha256": row["normalized_sha256"],
                "transformation": TRANSFORM,
            }
        )
        row["chunk"] = {
            "document_sha256": row["document_sha256"],
            "start_byte": 0,
            "end_byte": len(text_by_digest[row["normalized_sha256"]]),
        }
        row["chunk_sha256"] = canonical_hash(row["chunk"])
        kinds = {finding["kind"] for finding in row["findings"]}
        row["status"] = (
            "UNQUALIFIED"
            if exclusions is None
            else "CONTAMINATED"
            if "CONTAMINATED" in kinds
            else "QUARANTINED"
            if kinds & {"DUPLICATE_IDENTITY", "EXACT_BYTES", "NORMALIZED_CONTENT"}
            else "MANUAL_REVIEW"
            if kinds
            else "CLEAN"
        )
    status = next(
        (
            state
            for state in ("UNQUALIFIED", "CONTAMINATED", "QUARANTINED", "MANUAL_REVIEW")
            if any(row["status"] == state for row in rows)
        ),
        "CLEAN",
    )
    rows.sort(key=canonical_bytes)
    text_by_hash = {sha256(text): text.decode() for text in normalized}
    shard = (
        canonical_bytes(
            [
                {
                    "source": row["request"]["source"],
                    "qualification_scope": "BATCH_LOCAL_ONLY",
                    "document_sha256": row["document_sha256"],
                    "chunk_sha256": row["chunk_sha256"],
                    "text": text_by_hash[row["normalized_sha256"]],
                }
                for row in rows
            ]
        )
        if status == "CLEAN"
        else None
    )
    receipt = {
        "schema": "RES417-PROCESSING-2",
        "qualification_scope": "BATCH_LOCAL_ONLY",
        "corpus_qualification": "ASSEMBLY_REQUIRED",
        "status": status,
        "sources": rows,
        "transformation": TRANSFORM,
        "implementation_sha256": sha256(Path(__file__).read_bytes()),
        "screening": {
            "algorithm": SCREENING_VERSION,
            "max_work_units": MAX_WORK_UNITS,
            **asdict(work),
            "ratio": 0.5,
            "contiguous_tokens": 8,
            "max_tokens": MAX_TOKENS,
        },
        "exclusion_sha256": sha256(exclusion_bundle) if exclusion_bundle else None,
        "admission_trust_sha256": trust_commitment,
        "partition": "TRAIN",
        "split_isolation": "UNQUALIFIED",
        "shard_sha256": sha256(shard) if shard else None,
    }
    # Long screening must not bypass a grant that expires or is revoked before publication.
    for request, content, grant in inputs:
        admission.authorize_training_bytes(request, content, grant)
    if admission._PRODUCTION_TRUST_SHA256 != trust_commitment:
        raise PermissionError("admission trust changed during processing")
    destination = root / canonical_hash(receipt).removeprefix("sha256:")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = Path(tempfile.mkdtemp(prefix=".res417-", dir=root))
    try:
        (staging / "receipt.json").write_bytes(canonical_bytes(receipt))
        if shard is not None:
            (staging / "shard.json").write_bytes(shard)
        if destination.exists():
            if (
                destination.is_symlink()
                or set(p.name for p in destination.iterdir())
                != set(p.name for p in staging.iterdir())
                or any(
                    (destination / p.name).is_symlink()
                    or (destination / p.name).read_bytes() != p.read_bytes()
                    for p in staging.iterdir()
                )
            ):
                raise ValueError("existing content-addressed artifact changed")
        else:
            os.rename(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return receipt


def authorize_sft_corpus_bytes(receipt: object, shard: bytes) -> bytes:
    """Batch artifacts (including edited/reloaded receipts) never authorize an SFT corpus.

    A future independently trusted assembly gate must reconcile all sources, content,
    document/chunk identities, partitions, exclusion evidence and live training rights.
    No corpus authority is provisioned by RES-417.
    """
    raise PermissionError("CORPUS_ASSEMBLY_REQUIRED: batch-local artifacts confer no SFT approval")
