"""A1 generation hash chain (RES-832): one implementation for local and remote runners.

The chain is the unit of evidence. Every committed call appends exactly one canonical line that
binds its sequence number, the previous line digest, the arm, the frozen case identity, the
request and prompt digests, the decoding arm, the identity record and the raw generation.

Resumption reads the chain, verifies every link, and refuses anything but a torn final write.
A committed observation is never regenerated. This module carries no case, prompt or gold logic,
so the remote payload can import it without the local evaluation cohort.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from scripts import a02_v3_contract as v3

OUTPUT_SCHEMA = "DYNAMISLM_A1_GENERATION_LINE_V1"
GENESIS = "0" * 64


class ChainError(ValueError):
    pass


def arm_path(arm: str, root: Path) -> Path:
    return root / f"{arm}.jsonl"


def line_hash(entry: dict[str, Any]) -> str:
    return v3.sha256(v3.canonical(entry).encode())


def read_arm(path: Path, arm: str, expected: list[dict[str, Any]]) -> dict[str, Any]:
    """Verify a committed chain against the frozen item order, discarding only a torn tail."""
    if not path.exists():
        return {"entries": [], "head": GENESIS, "torn_tail_discarded": False}
    data = path.read_bytes()
    lines = data.split(b"\n")
    if lines and lines[-1] != b"":
        lines = lines[:-1]
        torn = True
    else:
        lines = lines[:-1]
        torn = False
    entries: list[dict[str, Any]] = []
    head = GENESIS
    for seq, raw in enumerate(lines):
        try:
            line = v3.json_object(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ChainError(f"{arm} line {seq} is corrupt") from exc
        digest = line.pop("line_sha256", None)
        if (
            line.get("schema") != OUTPUT_SCHEMA
            or line.get("arm") != arm
            or line.get("seq") != seq
            or line.get("prev_sha256") != head
            or digest != line_hash(line)
        ):
            raise ChainError(f"{arm} chain breaks at line {seq}")
        if seq >= len(expected) or line.get("case_id") != expected[seq]["case_id"]:
            raise ChainError(f"{arm} line {seq} is not the frozen next case")
        if line.get("prompt_sha256") != expected[seq]["prompt_sha256"]:
            raise ChainError(f"{arm} line {seq} prompt digest differs from the seal")
        entries.append(line)
        head = digest
    return {"entries": entries, "head": head, "torn_tail_discarded": torn}


def truncate_torn_tail(path: Path) -> None:
    data = path.read_bytes()
    with path.open("r+b") as handle:
        handle.truncate(data.rfind(b"\n") + 1)
        handle.flush()
        os.fsync(handle.fileno())


def append(path: Path, entry: dict[str, Any]) -> str:
    digest = line_hash(entry)
    data = (v3.canonical({**entry, "line_sha256": digest}) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    return digest


def count_lines(root: Path) -> dict[str, int]:
    """Committed line counts per arm; used for progress, never for scoring."""
    if not root.is_dir():
        return {}
    counts = {}
    for path in sorted(root.glob("*.jsonl")):
        counts[path.stem] = len([line for line in path.read_bytes().split(b"\n") if line])
    return counts
