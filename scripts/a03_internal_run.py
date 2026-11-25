"""Track A: run the deployed RES-430 `ask` pipeline over a blinded internal packet, gold-free.

The runner receives only opaque item identifiers, owner-written questions and validated
synthetic scenarios. It cannot read the sealed packet, never receives gold, and commits each
row's raw generation, parse result, admission, authorization, execution and result hash to a
hash-chained checkpoint before any gold is released. It dispatches nothing the runtime does not
authorize, and the only dispatchable operation is the side-effect-free RES-69 absolute change
over in-memory synthetic data.
"""

from __future__ import annotations

import argparse
import fcntl
import math
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from scripts import a02_v3_contract as v3
from scripts import a02_v3_worker as checkpoint
from scripts import a03_benchmark_seal as prospective_sealer
from scripts import a03_d0_runtime as d0
from scripts import a03_internal_config as config
from scripts import a03_internal_replay as replay
from scripts import a03_internal_seal as sealer
from scripts import a03_prospective_run as prospective
from scripts import research_ask as research
from scripts.research_scenarios import SyntheticScenario

SCHEMA = "DYNAMISLM_A03_INTERNAL_RUN_V1"
ARMS = ("N", "C1")
COMMIT_STATUSES = ("COMMITTED", "EXHAUSTED", "STOPPED")
PACKET_FILES = frozenset(sealer.FILES)


class Backend(Protocol):
    tokenizer: Any

    def generate(
        self, arm: str, request: dict[str, Any], prompt: list[int], deadline: float
    ) -> Any: ...


class ArmBackend:
    """The shipped `ask` path always asks for C1. This wrapper selects the decoding arm."""

    def __init__(self, backend: Backend, arm: str) -> None:
        self.backend, self.arm, self.tokenizer = backend, arm, backend.tokenizer

    def generate(
        self, arm: str, request: dict[str, Any], prompt: list[int], deadline: float
    ) -> Any:
        return self.backend.generate(self.arm, request, prompt, deadline)


@dataclass(frozen=True)
class BlindItem:
    item_id: str
    scenario: SyntheticScenario
    question: str


def read_blind(directory: Path) -> tuple[bytes, bytes]:
    """Read the blinded export. A directory that also holds packet or gold files is refused."""
    names = {p.name for p in directory.iterdir()}
    if names & PACKET_FILES or sealer.RELEASE_FILE in names:
        raise ValueError("gold visible to the runner: blinded input must not contain packet files")
    if not set(sealer.BLIND_FILES) <= names or names - set(sealer.BLIND_FILES) - {"run.json"}:
        raise ValueError("blinded input inventory differs")
    return (directory / "blind-requests.jsonl").read_bytes(), (
        directory / "blind-scenarios.jsonl"
    ).read_bytes()


def load_blind(requests: bytes, scenarios: bytes) -> list[BlindItem]:
    cfg = config.load_config()
    design = cfg["design"]
    scenario_rows = prospective.jsonl(scenarios)
    by_id: dict[str, SyntheticScenario] = {}
    for row in scenario_rows:
        prospective_sealer._fields(row, "scenario_id scenario")
        name = sealer._pattern(row["scenario_id"], design["scenario_id_pattern"], "scenario_id")
        try:
            scenario = sealer._scenario_info(prospective_sealer._text(row["scenario"]))[0]
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f"blinded scenario fails the RES-430 validator: {exc}") from exc
        if name in by_id or scenario.scenario_id != name:
            raise ValueError("duplicate or mismatched blinded scenario identity")
        by_id[name] = scenario
    items, seen = [], set()
    for row in prospective.jsonl(requests):
        prospective_sealer._fields(row, "item_id scenario_id question")
        item = sealer._pattern(row["item_id"], design["item_id_pattern"], "item_id")
        if item in seen or row["scenario_id"] not in by_id:
            raise ValueError("duplicate item or missing scenario binding")
        seen.add(item)
        scenario = by_id[row["scenario_id"]]
        research.prepare_request(scenario, row["question"])
        items.append(BlindItem(item, scenario, row["question"]))
    if [i.item_id for i in items] != sorted(seen) or {
        row["scenario_id"] for row in prospective.jsonl(requests)
    } != set(by_id):
        raise ValueError("blinded inventory is unsorted or has unused scenarios")
    return items


def work_items(items: list[BlindItem]) -> list[checkpoint.WorkItem]:
    rng = random.Random(config.load_config()["statistics"]["order_seed"])
    return [
        checkpoint.WorkItem(item.item_id, arm)
        for item in items
        for arm in rng.sample(ARMS, len(ARMS))
    ]


def source_identity() -> dict[str, str]:
    """An exact clean source checkout, bound like the RES-746 runner binds its own."""
    if prospective._git("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("real-model execution requires an exact clean source checkout")
    files = set(prospective._git("ls-files").splitlines())
    return {
        "commit": prospective._git("rev-parse", "HEAD"),
        "tree": prospective._git("rev-parse", "HEAD^{tree}"),
        "checkout_sha256": prospective.object_hash(
            {name: d0.digest(prospective.ROOT / name) for name in sorted(files)}
        ),
    }


def run_manifest(
    requests: bytes,
    scenarios: bytes,
    *,
    packet_sha256: str,
    bundle_archive_sha256: str,
    source: dict[str, str] | None = None,
) -> dict[str, Any]:
    items = load_blind(requests, scenarios)
    prospective_sealer._digest(bundle_archive_sha256)
    prospective_sealer._digest(packet_sha256)
    return {
        "schema": SCHEMA,
        **config.identity(),
        "source": source if source is not None else source_identity(),
        "packet_sha256": packet_sha256,
        "bundle_archive_sha256": bundle_archive_sha256,
        "blind_requests_sha256": v3.sha256(requests),
        "blind_scenarios_sha256": v3.sha256(scenarios),
        "arms": list(ARMS),
        "order_seed": config.load_config()["statistics"]["order_seed"],
        "work_sha256": checkpoint.work_list_sha256(work_items(items)),
    }


def verify_manifest(
    manifest: dict[str, Any],
    requests: bytes,
    scenarios: bytes,
    *,
    bundle_archive_sha256: str,
    verify_source: bool = True,
) -> list[BlindItem]:
    expected = run_manifest(
        requests,
        scenarios,
        packet_sha256=manifest.get("packet_sha256", ""),
        bundle_archive_sha256=bundle_archive_sha256,
        source=None if verify_source else manifest.get("source"),
    )
    if manifest != expected:
        raise ValueError("run manifest, source, inputs, protocol or bundle digest differ")
    return load_blind(requests, scenarios)


def live_violation(receipt: dict[str, Any]) -> str | None:
    """Gold-free stop rules from the frozen protocol."""
    result = receipt["result"]
    if result is not None and not result.get("registered_output_hash"):
        return "NUMERIC_RESULT_WITHOUT_RECEIPT"
    if result is not None and result["operation"] != replay.RES69:
        return "DISPATCH_OTHER_THAN_RES69_ABSOLUTE_CHANGE"
    return None


def verify_rows(
    path: Path, manifest: dict[str, Any], work: list[checkpoint.WorkItem]
) -> dict[str, Any]:
    state = checkpoint.read_checkpoint(path, work)
    if state["torn_tail_discarded"]:
        raise ValueError("torn checkpoint requires external custody disposition")
    run_sha256 = prospective.object_hash(manifest)
    for entry, scheduled in zip(state["entries"], work, strict=False):
        row = entry["record"]
        if (
            set(row) != {"run_sha256", "item_id", "arm", "error", "receipt", "seconds"}
            or row["run_sha256"] != run_sha256
            or (row["item_id"], row["arm"]) != (scheduled.key, scheduled.arm)
            or (row["error"] is None) == (row["receipt"] is None)
            or type(row["seconds"]) not in (int, float)
            or not math.isfinite(row["seconds"])
            or row["seconds"] < 0
        ):
            raise ValueError("checkpoint record binding differs")
    return state


def write_commit(
    directory: Path, manifest: dict[str, Any], status: str, state: dict[str, Any]
) -> dict[str, Any]:
    if status not in COMMIT_STATUSES:
        raise ValueError("unknown commitment status")
    commit = directory / "output-commit.json"
    runtime = directory / "runtime.json"
    result = {
        "status": status,
        "entries": len(state["entries"]),
        "run_sha256": prospective.object_hash(manifest),
        "head": state["head"],
        "outputs_sha256": d0.digest(directory / "outputs.jsonl"),
        "runtime_sha256": d0.digest(runtime),
    }
    with commit.open("x", encoding="utf-8") as stream:
        stream.write(v3.canonical(result) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return result


def commit_partial(
    output: Path, manifest: dict[str, Any], work: list[checkpoint.WorkItem], status: str
) -> dict[str, Any]:
    """Seal an incomplete run (`EXHAUSTED` envelope or `STOPPED` live rule). Never resumable."""
    if status == "COMMITTED":
        raise ValueError("a partial run cannot claim a complete commitment")
    directory = prospective.restricted(output)
    state = verify_rows(directory / "outputs.jsonl", manifest, work)
    if len(state["entries"]) >= len(work) and status == "EXHAUSTED":
        raise ValueError("a complete run is committed, not exhausted")
    return write_commit(directory, manifest, status, state)


def run(
    manifest: dict[str, Any],
    requests: bytes,
    scenarios: bytes,
    output: Path,
    runtime: research.ResearchRuntime,
    *,
    seconds: float,
    resume_sha256: str | None = None,
    verify_source: bool = True,
) -> dict[str, Any]:
    """Only blinded bytes and the shipped runtime enter this interface."""
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("a finite positive time bound is required")
    items = verify_manifest(
        manifest,
        requests,
        scenarios,
        bundle_archive_sha256=manifest["bundle_archive_sha256"],
        verify_source=verify_source,
    )
    if runtime.identity["bundle"]["archive_sha256"] != manifest["bundle_archive_sha256"]:
        raise ValueError("runtime bundle archive digest differs from the run manifest")
    directory = prospective.restricted(output)
    if {p.name for p in directory.iterdir()} & (PACKET_FILES | {sealer.RELEASE_FILE}):
        raise ValueError("gold visible to the runner: output directory holds packet files")
    work = work_items(items)
    by_id = {item.item_id: item for item in items}
    path, commit = directory / "outputs.jsonl", directory / "output-commit.json"
    runtime_receipt = directory / "runtime.json"
    if any(p.is_symlink() for p in (path, commit, runtime_receipt, directory / ".writer.lock")):
        raise ValueError("output state must not use symlinks")
    run_sha256 = prospective.object_hash(manifest)
    with (directory / ".writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if commit.exists():
            raise ValueError("committed outputs are immutable")
        if path.exists() != (resume_sha256 is not None) or (
            resume_sha256 is not None and d0.digest(path) != resume_sha256
        ):
            raise ValueError("incomplete run requires the exact externally retained prefix digest")
        receipt = {"run_sha256": run_sha256, "identity": runtime.identity}
        if runtime_receipt.exists():
            if runtime_receipt.read_bytes() != (v3.canonical(receipt) + "\n").encode():
                raise ValueError("resumed inference runtime differs")
        else:
            d0.write(runtime_receipt, receipt)
        if not path.exists():
            path.touch(mode=0o600, exist_ok=False)
        state = verify_rows(path, manifest, work)
        deadline = time.monotonic() + seconds
        head, first = state["head"], len(state["entries"])
        for seq in range(first, len(work)):
            if time.monotonic() >= deadline:
                return {"status": "INCOMPLETE", "entries": seq, "prefix_sha256": d0.digest(path)}
            scheduled = work[seq]
            item = by_id[scheduled.key]
            arm_runtime = research.ResearchRuntime(
                ArmBackend(runtime.backend, scheduled.arm), runtime.identity
            )
            start = time.monotonic()
            error: str | None = None
            row_receipt: dict[str, Any] | None = None
            try:
                full, _ = research.ask(item.scenario, item.question, arm_runtime)
                row_receipt = replay.receipt_for_arm(full, scheduled.arm)
            except ValueError as exc:  # includes UnsupportedRuntimeError and prompt-bound errors
                error = type(exc).__name__
            record = {
                "run_sha256": run_sha256,
                "item_id": scheduled.key,
                "arm": scheduled.arm,
                "error": error,
                "receipt": row_receipt,
                "seconds": time.monotonic() - start,
            }
            head = checkpoint._append(
                path,
                {
                    "schema": checkpoint.CHECKPOINT_SCHEMA,
                    "seq": seq,
                    "item": scheduled.id,
                    "prev_sha256": head,
                    "record": record,
                },
            )
            rule = live_violation(row_receipt) if row_receipt is not None else None
            if rule is not None:
                return {
                    "status": "STOPPED_LIVE_RULE",
                    "rule": rule,
                    "entries": seq + 1,
                    "prefix_sha256": d0.digest(path),
                }
        return write_commit(directory, manifest, "COMMITTED", verify_rows(path, manifest, work))


def write_manifest(
    blind: Path, *, packet_sha256: str, bundle_archive_sha256: str
) -> dict[str, Any]:
    """Create `run.json` beside the blinded export. Binds the clean source checkout."""
    directory = prospective.restricted(blind)
    requests, scenarios = read_blind(directory)
    manifest = run_manifest(
        requests,
        scenarios,
        packet_sha256=packet_sha256,
        bundle_archive_sha256=bundle_archive_sha256,
    )
    d0.write(directory / "run.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("manifest", help="bind a blinded export to the source and bundle")
    make.add_argument("blind_directory", type=Path)
    make.add_argument("--packet-sha256", required=True)
    make.add_argument("--bundle-archive-sha256", required=True)
    go = sub.add_parser("run", help="run the shipped ask pipeline over the blinded export")
    go.add_argument("blind_directory", type=Path)
    go.add_argument("output_directory", type=Path)
    go.add_argument("--manifest-sha256", required=True)
    go.add_argument("--bundle", type=Path, required=True)
    go.add_argument("--base", type=Path, required=True)
    go.add_argument("--device", default="cpu")
    go.add_argument("--seconds", type=float, required=True)
    go.add_argument("--resume-sha256")
    part = sub.add_parser("seal-partial", help="seal an exhausted or stopped run")
    part.add_argument("blind_directory", type=Path)
    part.add_argument("output_directory", type=Path)
    part.add_argument("--manifest-sha256", required=True)
    part.add_argument("--status", choices=("EXHAUSTED", "STOPPED"), required=True)
    args = parser.parse_args()
    blind = prospective.restricted(args.blind_directory)
    if args.command == "manifest":
        manifest = write_manifest(
            blind,
            packet_sha256=args.packet_sha256,
            bundle_archive_sha256=args.bundle_archive_sha256,
        )
        print(v3.canonical({"manifest_sha256": d0.digest(blind / "run.json"), **manifest}))
        return
    requests, scenarios = read_blind(blind)
    manifest = v3.json_object(
        prospective.verified_bytes(blind / "run.json", args.manifest_sha256).decode()
    )
    if args.command == "seal-partial":
        work = work_items(
            verify_manifest(
                manifest,
                requests,
                scenarios,
                bundle_archive_sha256=manifest["bundle_archive_sha256"],
            )
        )
        print(v3.canonical(commit_partial(args.output_directory, manifest, work, args.status)))
        return
    runtime = research.open_runtime(args.bundle, args.base, args.device)
    print(
        v3.canonical(
            run(
                manifest,
                requests,
                scenarios,
                args.output_directory,
                runtime,
                seconds=args.seconds,
                resume_sha256=args.resume_sha256,
            )
        )
    )


if __name__ == "__main__":
    main()
