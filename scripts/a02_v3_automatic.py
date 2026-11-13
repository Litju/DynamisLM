"""Owner-delegated RES-541 diagnostic → frozen baseline → learned LoRA artifacts.

All paid stages share one finite append-only 50-CU budget. Completed clean checkpoints may
continue; any anomaly or unknown cost stops the pipeline. There is no diagnostic retry.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import os
import subprocess
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from scripts import a02_v3_contract as v3
from scripts import a02_v3_decision as decision
from scripts import a02_v3_diagnostic_session as diagnostic_session
from scripts import a02_v3_execution as execution
from scripts import a02_v3_gpu_diagnostic as diagnostic
from scripts import a02_v3_remote as remote
from scripts import a02_v3_training as training
from scripts import a02_v3_worker as worker
from scripts.a02_execution import _write_json

ROOT = execution.E_ROOT / "a02/owner-automatic-v1"
TOTAL_CAP_CU = 50.0
TRAINING_SECONDS = 7200
TRAINING_CLEANUP_SECONDS = 600


def source_archive_path(directory: Path, grant: dict[str, Any]) -> Path:
    name: str = grant.get("source_archive_name", "source.tar")
    if name not in {"source.tar", "source-native-cache.tar"}:
        raise ValueError("unknown source archive policy")
    return directory / name


def cache_compatibility(predecessor: str) -> dict[str, str]:
    paths = [
        "scripts/a02_v3_constrained.py",
        "scripts/a02_v3_numerics.py",
        "scripts/a02_v3_precision.py",
        "scripts/a02_v3_gpu_diagnostic.py",
        "scripts/a02_v3_contract.py",
        "scripts/a02_v3_synthetic.py",
        "scripts/a02_v3_decision.py",
        "scripts/a02_v3_gold.py",
        "scripts/a02_v3_score.py",
        "experiments/a02/model-comparison-protocol-v3.json",
        "experiments/a02/development-profile-v3.json",
        "experiments/a02/numerical-amendment-a1.md",
        "experiments/a0/requirements-colab.txt",
        "pyproject.toml",
        "uv.lock",
        "scripts/a02_dev_runtime.py",
        "scripts/a02_remote.py",
    ]
    hashes = {}
    for path in paths:
        old = subprocess.check_output(["git", "show", f"{predecessor}:{path}"], cwd=execution.ROOT)
        current = (execution.ROOT / path).read_bytes()
        if old != current:
            raise ValueError(f"qualified numerical/model/data source changed: {path}")
        hashes[path] = v3.sha256(current)

    def normalized(data: bytes) -> str:
        tree = ast.parse(data)
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "HFWorkerBackend":
                node.body = [
                    entry
                    for entry in node.body
                    if not (
                        isinstance(entry, ast.FunctionDef)
                        and entry.name in {"__init__", "generate_native"}
                    )
                ]
        return ast.dump(tree, include_attributes=False)

    old = subprocess.check_output(
        ["git", "show", f"{predecessor}:scripts/a02_v3_worker.py"], cwd=execution.ROOT
    )
    if normalized(old) != normalized((execution.ROOT / "scripts/a02_v3_worker.py").read_bytes()):
        raise ValueError("qualification, work order, scoring or checkpoint worker changed")
    hashes["worker_except_native_generation"] = v3.sha256(normalized(old).encode())
    return hashes


def validate_continuation(directory: Path, grant: dict[str, Any]) -> None:
    certificate = grant["native_cache_continuation"]
    if certificate["native_amendment_sha256"] != v3.sha256(
        (execution.ROOT / "experiments/a02/native-cache-execution-v1.md").read_bytes()
    ):
        raise ValueError("native cache execution amendment changed")
    financial = read(directory / "grant.json")
    if (
        v3.sha256((directory / "grant.json").read_bytes())
        != certificate["predecessor_grant_sha256"]
        or grant["maximum_new_cu"] != financial["maximum_new_cu"]
        or grant["owner_receipt_sha256"] != financial["owner_receipt_sha256"]
        or grant["valid_until_utc"] != financial["valid_until_utc"]
        or grant.get("native_cache") is not True
    ):
        raise ValueError("continuation cannot replace or extend financial authority")
    state = Budget(directory, financial).state()
    if (
        not state["sessions"]
        or state["sessions"][0]["kind"] != "DIAGNOSTIC"
        or state["sessions"][0]["charge_sha256"] != certificate["diagnostic_charge_sha256"]
    ):
        raise ValueError("successful diagnostic cost/evidence was not carried forward")
    control = directory / "diagnostic-control.json"
    terminal = directory / "terminal-anomaly.json"
    if (
        v3.sha256(control.read_bytes()) != certificate["diagnostic_control_sha256"]
        or read(control).get("passed") is not True
        or v3.sha256(terminal.read_bytes()) != certificate["prior_planning_stop_sha256"]
        or read(terminal).get("error_detail")
        != "measured conservative campaign exceeds remaining delegated budget"
    ):
        raise ValueError(
            "only successful qualification followed by a nonpaid planning stop may continue"
        )
    if (
        cache_compatibility(financial["source_identity"]["commit"])
        != certificate["unchanged_qualified_sources"]
    ):
        raise ValueError("qualified numerical/data source equivalence differs")


def prepare_native_cache_continuation(directory: Path) -> dict[str, Any]:
    financial = read(directory / "grant.json")
    state = Budget(directory, financial).state()
    if len(state["sessions"]) != 1 or state["sessions"][0]["kind"] != "DIAGNOSTIC":
        raise ValueError("native cache continuation cannot retry any baseline/training allocation")
    terminal = directory / "terminal-anomaly.json"
    if (
        read(terminal).get("error_detail")
        != "measured conservative campaign exceeds remaining delegated budget"
    ):
        raise ValueError("continuation requires the recorded nonpaid planning stop")
    archive = directory / "source-native-cache.tar"
    if archive.exists() or (directory / "grant-native-cache.json").exists():
        raise ValueError("continuation already prepared; no reset")
    unchanged = cache_compatibility(financial["source_identity"]["commit"])
    execution.source_archive(archive)
    grant = {
        **financial,
        "source_identity": execution.source_identity(),
        "source_archive_name": archive.name,
        "source_archive_sha256": v3.sha256(archive.read_bytes()),
        "diagnostic": diagnostic.specification(delegated=True),
        "native_cache": True,
        "native_cache_continuation": {
            "native_amendment_sha256": v3.sha256(
                (execution.ROOT / "experiments/a02/native-cache-execution-v1.md").read_bytes()
            ),
            "predecessor_grant_sha256": v3.sha256((directory / "grant.json").read_bytes()),
            "diagnostic_charge_sha256": state["sessions"][0]["charge_sha256"],
            "diagnostic_control_sha256": v3.sha256(
                (directory / "diagnostic-control.json").read_bytes()
            ),
            "prior_planning_stop_sha256": v3.sha256(terminal.read_bytes()),
            "unchanged_qualified_sources": unchanged,
            "purpose": "native KV caching; qualified diagnostic and original budget preserved",
        },
    }
    validate_grant(directory, grant)
    execution._write_exclusive(directory / "grant-native-cache.json", grant)
    return grant


def read(path: Path) -> dict[str, Any]:
    return v3.json_object(path.read_text())


class Budget:
    def __init__(self, directory: Path, grant: dict[str, Any]):
        self.directory = directory
        self.path = directory / "budget-ledger.json"
        self.grant_hash = v3.sha256(v3.canonical(grant).encode())
        if not self.path.exists():
            if (
                list(directory.glob("*-used.json"))
                or list(directory.glob("*-charge.json"))
                or list(directory.rglob("*control.json"))
                or (directory / "terminal-anomaly.json").exists()
            ):
                raise ValueError("missing budget ledger has prior session evidence; no reset")
            execution._write_exclusive(
                self.path,
                {
                    "schema": "RES541_FINITE_AUTOMATIC_BUDGET_V1",
                    "grant_sha256": self.grant_hash,
                    "maximum_new_cu": TOTAL_CAP_CU,
                    "historical_cu_separate": 0.2537,
                    "sessions": [],
                },
            )

    def state(self) -> dict[str, Any]:
        value = read(self.path)
        if (
            value.get("grant_sha256") != self.grant_hash
            or value.get("maximum_new_cu") != TOTAL_CAP_CU
            or value.get("historical_cu_separate") != 0.2537
        ):
            raise ValueError("automatic budget authority differs")
        if any(entry.get("cost_status") != "KNOWN" for entry in value["sessions"]):
            raise ValueError("prior/open session cost is unknown or exceeded its cap")
        keys = [entry["key"] for entry in value["sessions"]]
        used = {path.name.removesuffix("-used.json") for path in self.directory.glob("*-used.json")}
        charged = {
            path.name.removesuffix("-charge.json") for path in self.directory.glob("*-charge.json")
        }
        if len(keys) != len(set(keys)) or set(keys) != used or set(keys) != charged:
            raise ValueError("budget ledger omits immutable session evidence")
        for index, entry in enumerate(value["sessions"]):
            amount = entry.get("conservative_cu")
            if (
                entry.get("cost_status") != "KNOWN"
                or isinstance(amount, bool)
                or not isinstance(amount, int | float)
                or not math.isfinite(amount)
                or not 0 <= amount <= entry["cap_cu"]
            ):
                raise ValueError("prior/open session cost is unknown or exceeded its cap")
            if entry.get("execution_status") != "CLEAN":
                raise ValueError("prior failed execution is terminal; no retry")
            marker = read(self.directory / (entry["key"] + "-used.json"))
            if (
                marker.get("grant_sha256") != self.grant_hash
                or marker.get("sequence") != index
                or any(marker.get(key) != entry.get(key) for key in ("key", "kind", "cap_cu"))
            ):
                raise ValueError("budget session sequence/used marker differs")
            charge = Path(entry["charge_path"])
            if v3.sha256(charge.read_bytes()) != entry["charge_sha256"]:
                raise ValueError("immutable budget charge receipt changed")
            receipt = read(charge)
            if (
                receipt["grant_sha256"] != self.grant_hash
                or any(
                    receipt[key] != entry[key]
                    for key in (
                        "key",
                        "kind",
                        "sequence",
                        "cap_cu",
                        "conservative_cu",
                        "control_sha256",
                        "cost_status",
                        "execution_status",
                    )
                )
                or v3.sha256(Path(receipt["control_path"]).read_bytes()) != entry["control_sha256"]
            ):
                raise ValueError("budget charge/control evidence differs")
        if sum(entry["conservative_cu"] for entry in value["sessions"]) > TOTAL_CAP_CU:
            raise ValueError("cumulative automatic budget exceeded")
        return value

    def remaining(self) -> float:
        spent: float = sum(entry["conservative_cu"] for entry in self.state()["sessions"])
        return TOTAL_CAP_CU - spent

    def reserve(self, key: str, kind: str, cap: float) -> None:
        value = self.state()
        if (
            isinstance(cap, bool)
            or not math.isfinite(cap)
            or cap <= 0
            or cap > self.remaining()
            or len(value["sessions"]) >= 64
        ):
            raise ValueError("finite automatic budget/session ceiling cannot cover next session")
        execution._write_exclusive(
            self.directory / (key + "-used.json"),
            {
                "key": key,
                "kind": kind,
                "cap_cu": cap,
                "grant_sha256": self.grant_hash,
                "sequence": len(value["sessions"]),
            },
        )
        value["sessions"].append(
            {
                "key": key,
                "kind": kind,
                "cap_cu": cap,
                "cost_status": "OPEN",
                "conservative_cu": None,
                "sequence": len(value["sessions"]),
                "execution_status": "OPEN",
            }
        )
        _write_json(self.path, value)

    def close(self, key: str, amount: float | None, control: Path, *, passed: bool) -> None:
        value = read(self.path)
        if value.get("grant_sha256") != self.grant_hash:
            raise ValueError("automatic budget grant changed")
        entry = value["sessions"][-1]
        if entry["key"] != key or entry["cost_status"] != "OPEN":
            raise ValueError("automatic budget session sequence differs")
        known = (
            not isinstance(amount, bool)
            and amount is not None
            and math.isfinite(amount)
            and 0 <= amount <= entry["cap_cu"]
            and control.is_file()
        )
        entry.update(
            conservative_cu=(
                amount
                if not isinstance(amount, bool) and amount is not None and math.isfinite(amount)
                else None
            ),
            cost_status="KNOWN" if known else "UNKNOWN_OR_OVERRUN",
            control_sha256=v3.sha256(control.read_bytes()) if control.exists() else None,
            execution_status="CLEAN" if passed is True else "FAILED",
        )
        charge = self.directory / (key + "-charge.json")
        execution._write_exclusive(
            charge,
            {**entry, "control_path": str(control.resolve()), "grant_sha256": self.grant_hash},
        )
        entry.update(
            charge_path=str(charge.resolve()), charge_sha256=v3.sha256(charge.read_bytes())
        )
        _write_json(self.path, value)
        if not known:
            raise ValueError("session cost unknown or exceeded cap; no downstream work")
        if passed is not True:
            raise ValueError("failed execution is terminal; no automatic retry")


class PipelineCLI(diagnostic_session.DiagnosticCLI):
    def download(self, name: str, remote_path: str, local: Path) -> bool:
        timeout = 240 if remote_path.endswith(".tar") else 30
        return (
            self._run(
                ["colab", "--auth=oauth2", "download", "--session", name, remote_path, str(local)],
                timeout=timeout,
            ).returncode
            == 0
        )


def quiet(client: Any) -> dict[str, Any]:
    value: dict[str, Any] = client.snapshot()
    if (
        value["active_sessions"]
        or value["usage_rate_cu_per_hour"] != 0
        or client.sessions()
        or not math.isfinite(value["balance"])
    ):
        raise ValueError("automatic execution requires zero preexisting sessions/usage")
    return value


def prepare(directory: Path) -> dict[str, Any]:
    owner_path = diagnostic_session.ROOT / "owner-delegated-budget-50cu-v2.json"
    owner = read(owner_path)
    if directory.resolve() != (ROOT / v3.sha256(owner_path.read_bytes())).resolve():
        raise ValueError("one delegated owner receipt has one fixed budget directory")
    directory.mkdir(parents=True, exist_ok=True)
    if (directory / "grant.json").exists() or (directory / "source.tar").exists():
        raise ValueError("owner grant directory is already prepared; no budget reset")
    if (
        owner["agent_selected_total_new_cu"] != TOTAL_CAP_CU
        or not owner["automatic_campaign_requested"]
        or not owner["actual_lora_weights_requested"]
    ):
        raise ValueError("explicit delegated campaign/training budget receipt is missing")
    archive, revision = execution.source_archive(directory / "source.tar")
    issued = datetime.now(UTC)
    grant: dict[str, Any] = {
        "schema": "RES541_OWNER_DELEGATED_AUTOMATIC_GRANT_V1",
        "source_identity": execution.source_identity(),
        "source_archive_sha256": v3.sha256(archive.read_bytes()),
        "owner_receipt_sha256": v3.sha256(owner_path.read_bytes()),
        "maximum_new_cu": TOTAL_CAP_CU,
        "historical_cu": 0.2537,
        "valid_from_utc": issued.isoformat(),
        "valid_until_utc": (issued + timedelta(days=7)).isoformat(),
        "diagnostic": diagnostic.specification(delegated=True),
        "training": training.specification(),
        "protocol_sha256": decision.protocol_sha256(),
        "maximum_total_sessions": 64,
        "automatic_baseline": True,
        "owner_requested_training_after_baseline": True,
        "retries": False,
    }
    if revision != grant["source_identity"]["commit"]:
        raise ValueError("archive revision differs")
    execution._write_exclusive(directory / "grant.json", grant)
    return grant


def validate_grant(directory: Path, grant: dict[str, Any], *, required_seconds: float = 0) -> None:
    if (
        grant.get("schema") != "RES541_OWNER_DELEGATED_AUTOMATIC_GRANT_V1"
        or grant.get("maximum_new_cu") != TOTAL_CAP_CU
        or grant.get("historical_cu") != 0.2537
        or grant.get("maximum_total_sessions") != 64
        or grant.get("retries") is not False
        or grant.get("automatic_baseline") is not True
        or grant.get("owner_requested_training_after_baseline") is not True
    ):
        raise ValueError("automatic grant differs from finite owner scope")
    if execution.source_identity() != grant["source_identity"]:
        raise ValueError("automatic source differs from approved clean commit/tree")
    if (
        v3.sha256(source_archive_path(directory, grant).read_bytes())
        != grant["source_archive_sha256"]
        or diagnostic_session.head_archive_sha256() != grant["source_archive_sha256"]
        or grant["protocol_sha256"] != decision.protocol_sha256()
    ):
        raise ValueError("automatic source archive/protocol differs")
    owner = diagnostic_session.ROOT / "owner-delegated-budget-50cu-v2.json"
    if directory.resolve() != (ROOT / v3.sha256(owner.read_bytes())).resolve():
        raise ValueError("automatic budget directory differs from the owner receipt")
    if v3.sha256(owner.read_bytes()) != grant["owner_receipt_sha256"]:
        raise ValueError("owner delegation receipt changed")
    start = datetime.fromisoformat(grant["valid_from_utc"])
    end = datetime.fromisoformat(grant["valid_until_utc"])
    if (
        start.tzinfo is None
        or end.tzinfo is None
        or end - start > timedelta(days=7)
        or not start <= datetime.now(UTC) < end
        or (end - datetime.now(UTC)).total_seconds() < required_seconds
    ):
        raise ValueError("automatic finite grant expired")
    diagnostic.validate_specification(grant["diagnostic"])
    if "native_cache_continuation" in grant:
        validate_continuation(directory, grant)
    training.validate_specification(grant["training"])


def measured_plan(
    report: dict[str, Any], rate: float, remaining: float, *, native_cache: bool = False
) -> dict[str, Any]:
    identity = decision.load_protocol()["candidate_model"]
    runtime = report.get("runtime", {})
    audit = report.get("precision_audit", {})
    if (
        report.get("schema") != diagnostic.SCHEMA
        or report.get("model_identity") != identity
        or not str(runtime.get("device", "")).startswith("cuda")
        or runtime.get("gpu") != "Tesla T4"
        or runtime.get("dtype") != "torch.float32"
        or audit.get("parameter_dtypes") != ["torch.float32"]
        or audit.get("intermediate_dtypes") != ["torch.float32"]
        or audit.get("logit_dtypes") != ["torch.float32"]
        or not 3_000_000_000 <= audit.get("parameter_count", 0) <= 3_200_000_000
    ):
        raise ValueError("planning requires actual pinned 3B/T4 FP32 runtime evidence")
    rows = report["rows"]
    native = report["native_calibration_timing"]
    if report.get("passed") is not True or len(rows) != 3 or not native["tokens"]:
        raise ValueError("complete real-model FP32 diagnostic and throughput required")
    for row in rows:
        diagnostic.validate_row(row)
    if not math.isfinite(rate) or rate <= 0 or rate > 4:
        raise ValueError("invalid observed T4 rate")
    native_floor = native["tokens"] / native["seconds"] / 2
    call_floor = min(row["scorer_calls"] / row["timing_seconds"]["C"] for row in rows) / 2
    full_forward = max(c["timing_seconds"]["A"] for row in rows for c in row["candidates"]) * 2
    overhead = max(100, report["load_seconds"] * 2 + 60)
    bounds = execution.RuntimeBounds(
        session_seconds=3600,
        exec_seconds=3300,
        cleanup_reserve_seconds=300,
        prepare_seconds=180,
        inference_overhead_seconds=math.ceil(overhead),
        worker_margin_seconds=60,
        decode_floor_tokens_per_second=min(native_floor, call_floor),
        full_forward_seconds=full_forward,
        t4_rate_cu_per_hour=rate,
        admission_rate_ceiling_cu_per_hour=min(4, rate * 1.25),
        cost_buffer_cu=0.2,
    )
    protocol = decision.load_protocol()
    preflight = {"max_constrained_scorer_calls": execution.workload_scorer_calls(protocol)}
    projected_costs = None
    native_projection = None
    if native_cache:
        tails = [
            c["timing_seconds"]["C"]
            for row in rows
            for c in row["candidates"]
            if c["c_call"]["keep"] > 0
        ]
        if not tails or any(not math.isfinite(value) or value <= 0 for value in tails):
            raise ValueError("cached-native projection needs observed FP32 cached-tail timings")
        cap = v3.load_profile()["decoding"]["action_max_new_tokens"]
        calls = preflight["max_constrained_scorer_calls"]
        tail_bound = max(tails) * 2
        native_bound = full_forward + cap * tail_bound + 1
        cached_bound = (
            max(row["timing_seconds"]["C"] * calls / row["scorer_calls"] for row in rows) * 2
        )
        qualification = (
            sum(row["timing_seconds"]["A"] + row["timing_seconds"]["C"] for row in rows) * 2
        )
        qualification *= calls / min(row["scorer_calls"] for row in rows)
        projected_costs = {
            "QUALIFICATION": qualification,
            "ZERO_SHOT_UNCONSTRAINED": native_bound,
            "ZERO_SHOT_CONSTRAINED": cached_bound,
        }
        bounds = replace(bounds, inference_overhead_seconds=math.ceil(overhead + native_bound))
        native_projection = {
            "basis": "FP32 cached-tail projection; cached-native timing pending",
            "cached_tail_samples": len(tails),
            "per_session_native_calibration_seconds_bound": native_bound,
            "cached_tail_seconds_bound": tail_bound,
            "full_prefill_seconds_bound": full_forward,
            "native_max_tokens": cap,
            "uncached_native_observation": native,
            "required": "time cached-native on TRAIN first; reject an exceeded bound",
        }
    plan = execution.build_plan(protocol, preflight, bounds, measured_cost_bounds=projected_costs)
    if native_projection is not None:
        plan["native_cache_projection"] = native_projection
    plan["compute_units"]["rate_basis"] = (
        "current pinned 3B/T4 FP32 diagnostic; conservative 2x operation times"
    )
    payload = {
        k: v for k, v in plan.items() if k not in {"plan_sha256", "live_observation_not_hashed"}
    }
    plan["plan_sha256"] = v3.sha256(v3.canonical(payload).encode())
    if plan["compute_units"]["cumulative_cap"] > remaining:
        raise ValueError("measured conservative campaign exceeds remaining delegated budget")
    return plan


def validate_plan(
    plan: dict[str, Any],
    report: dict[str, Any],
    rate: float,
    initial_budget: float,
    *,
    native_cache: bool = False,
) -> None:
    payload = {
        k: v for k, v in plan.items() if k not in {"plan_sha256", "live_observation_not_hashed"}
    }
    if plan.get("plan_sha256") != v3.sha256(v3.canonical(payload).encode()):
        raise ValueError("persisted baseline plan content hash differs")
    derived = measured_plan(report, rate, initial_budget, native_cache=native_cache)
    expected = {
        k: v for k, v in derived.items() if k not in {"plan_sha256", "live_observation_not_hashed"}
    }
    if payload != expected:
        raise ValueError("persisted baseline plan differs from measured FP32 derivation")


def baseline_state(
    directory: Path, items: list[worker.WorkItem], plan: dict[str, Any], grant: dict[str, Any]
) -> dict[str, Any]:
    checkpoint = directory / "checkpoint.jsonl"
    state = worker.read_checkpoint(checkpoint, items)
    controls = sorted(directory.glob("session-*-control.json"))
    if not controls:
        if state["entries"] or (directory / "ledger.json").exists():
            raise ValueError("unbound baseline checkpoint/ledger; no repeated evaluations")
        return state
    ledger = read(directory / "ledger.json")
    if ledger.get("source_identity") != grant["source_identity"] or len(ledger["sessions"]) != len(
        controls
    ):
        raise ValueError("baseline ledger/control source or sequence differs")
    cursor = 0
    for index, path in enumerate(controls, 1):
        control = read(path)
        merge = control.get("merge")
        if not isinstance(merge, dict):
            raise ValueError("prior baseline evidence was rejected; no retry")
        after = merge["committed_after"]
        anomaly = execution.session_anomaly(
            control, cursor, after, plan["compute_units"]["per_session_cap"]
        )
        if (
            anomaly
            or control.get("index") != index
            or merge["committed_before"] != cursor
            or ledger["sessions"][index - 1]["committed_items"] != after
        ):
            raise ValueError(f"prior baseline anomaly/sequence differs; no retry: {anomaly}")
        cursor = after
    latest = read(controls[-1])
    if (
        len(state["entries"]) != cursor
        or state["head"] != latest["merge"]["head"]
        or state["torn_tail_discarded"]
        or v3.sha256(checkpoint.read_bytes()) != latest["remote_status"]["checkpoint_sha256"]
    ):
        raise ValueError("baseline checkpoint rollback/fork detected; no repeated evaluations")
    return state


def verified_training_prior(path: Path, grant: dict[str, Any]) -> dict[str, Any]:
    control = read(path.parent / "control.json")
    result: dict[str, Any] = control["result"]
    actual = v3.sha256(path.read_bytes())
    if (
        control.get("passed") is not True
        or actual != control["recovered"]["checkpoint.tar"]
        or actual != result["checkpoint_sha256"]
        or control["binding"]["source_identity"] != grant["source_identity"]
        or control["binding"]["training_spec"] != grant["training"]
    ):
        raise ValueError("prior training archive/control changed; no optimizer rollback")
    return result


def validate_training_advance(previous: dict[str, Any], current: dict[str, Any]) -> None:
    if current["next_step"] <= previous["next_step"] or any(
        current[key] != previous[key]
        for key in (
            "total_steps",
            "initial_adapter_fingerprint",
            "identity",
            "specification_sha256",
            "data_order_sha256",
            "runtime",
        )
    ):
        raise ValueError("training recovery cursor/identity rolled back or changed")


def training_session(
    directory: Path,
    grant: dict[str, Any],
    index: int,
    prior: Path | None,
    rate_ceiling: float,
    cap: float,
    client: PipelineCLI,
) -> dict[str, Any]:
    """One training allocation, checkpoint recovery, unconditional exact-target teardown."""
    previous = verified_training_prior(prior, grant) if prior is not None else None
    before = quiet(client)
    if before["balance"] < cap + 0.2:
        raise ValueError("quota cannot cover bounded training session")
    name = f"res541-lora-{grant['source_identity']['commit'][:8]}-{index:03d}"
    jobdir = directory / f"session-{index:03d}"
    jobdir.mkdir(parents=True, exist_ok=False)
    spec = grant["training"]
    stable = {
        "source_identity": grant["source_identity"],
        "source_archive_sha256": grant["source_archive_sha256"],
        "training_spec": spec,
        "baseline_checkpoint_sha256": v3.sha256(
            (directory.parent / "baseline/checkpoint.jsonl").read_bytes()
        ),
        "owner_receipt_sha256": grant["owner_receipt_sha256"],
    }
    plan_hash = v3.sha256(v3.canonical(stable).encode())
    binding = {
        "schema": remote.TRAINING_BINDING_SCHEMA,
        "source_identity": grant["source_identity"],
        "source_revision": grant["source_identity"]["commit"],
        "source_archive_sha256": grant["source_archive_sha256"],
        "protocol_sha256": grant["protocol_sha256"],
        "plan_sha256": plan_hash,
        "session_index": index,
        "training_spec": spec,
        "training_checkpoint_sha256": v3.sha256(prior.read_bytes()) if prior else None,
    }
    binding_path = jobdir / "binding.json"
    execution._write_exclusive(binding_path, binding)
    state: dict[str, Any] = {
        "session": name,
        "binding": binding,
        "quota_before": before,
        "passed": False,
    }
    watchdog = None
    attempted = False
    allocated = False
    rate = None
    initial_delta = None
    started = time.monotonic()
    client.watchdog_seconds = TRAINING_SECONDS
    try:
        watchdog = client.start_watchdog(name, jobdir / "watchdog.json")
        attempted = True
        allocated = client.new(name)
        if not allocated or client.hardware(name) != "T4":
            raise RuntimeError("single T4 training allocation failed; no retry")
        after = client.snapshot()
        rate = float(after["usage_rate_cu_per_hour"])
        initial_delta = before["balance"] - after["balance"]
        state["pricing_observation"] = {"rate": rate, "initial_account_delta": initial_delta}
        if (
            not math.isfinite(rate)
            or not 0 < rate <= rate_ceiling
            or not math.isfinite(initial_delta)
            or not 0 <= initial_delta <= 0.15
            or {r["name"] for r in after["active_sessions"]} != {name}
        ):
            raise ValueError("training price/resource admission failed before model work")
        files = [
            (source_archive_path(directory.parent, grant), execution.REMOTE_SOURCE),
            (binding_path, execution.REMOTE_BINDING),
        ]
        if prior is not None:
            files.append((prior, "/content/a02-training-prior.tar"))
        for local, target in files:
            if not client.upload(name, local, target):
                raise RuntimeError("training upload failed")
        admission = {
            "started_monotonic": started,
            "per_session_cap": cap,
            "cumulative_cap": cap,
            "spent_before": 0,
        }
        for stage, ceiling in (
            ("prepare", 240),
            ("work", TRAINING_SECONDS - TRAINING_CLEANUP_SECONDS - 240),
        ):
            remaining = TRAINING_SECONDS - TRAINING_CLEANUP_SECONDS - (time.monotonic() - started)
            if remaining < 60:
                raise TimeoutError("training session has no remaining bounded work window")
            state[stage] = execution.monitored_stage(
                client,
                name,
                stage,
                min(ceiling, int(remaining)),
                before,
                admission,
                {"bounds": {"cost_buffer_cu": 0.2}},
                rate,
            )
            if state[stage].get("returncode") != 0:
                raise RuntimeError(f"training {stage} failed; no retry")
        state["remote_completed"] = True
    except Exception as exc:
        state.update(error_type=type(exc).__name__, error_detail=str(exc))
    finally:
        state["recovered"] = {}
        if allocated:
            for target, local_name in (
                (execution.REMOTE_STATUS, "status.json"),
                ("/content/a02-training-report.jsonl", "report.jsonl"),
                ("/content/a02-training/checkpoint.tar", "checkpoint.tar"),
            ):
                try:
                    saved = client.download(name, target, jobdir / local_name)
                    state["recovered"][local_name] = (
                        v3.sha256((jobdir / local_name).read_bytes()) if saved else None
                    )
                except Exception as exc:
                    state["recovered"][local_name] = {"error_type": type(exc).__name__}
        if attempted:
            try:
                state["stopped"] = client.stop(name)
            except Exception as exc:
                state["stop_error"] = type(exc).__name__
            try:
                state["target_absent"] = client.verify_absent(name)
                state["teardown_receipt"] = getattr(client, "teardown_receipt", None)
            except Exception as exc:
                state.update(target_absent=False, teardown_error=type(exc).__name__)
        if watchdog is not None:
            try:
                client.finish_watchdog(watchdog, state.get("target_absent") is True)
            except Exception as exc:
                state["watchdog_error"] = type(exc).__name__
        try:
            after = quiet(client)
            state["quota_after"] = after
            delta = before["balance"] - after["balance"]
            if (
                not state.get("target_absent")
                or rate is None
                or not math.isfinite(rate)
                or rate <= 0
                or initial_delta is None
                or not math.isfinite(initial_delta)
                or initial_delta < 0
                or not math.isfinite(delta)
                or delta < 0
            ):
                raise ValueError("training cost/teardown unknown")
            spent = max(delta, rate * (time.monotonic() - started) / 3600 + initial_delta)
            if not math.isfinite(spent) or not 0 <= spent <= cap:
                raise ValueError("training cost cap exceeded")
            state["conservative_cu"] = spent
        except Exception as exc:
            state["cost_error"] = str(exc)
        try:
            status = read(jobdir / "status.json")
            if status["binding"] != binding or status["status"] not in {
                "TRAINING_COMPLETE",
                "TRAINING_PAUSED",
            }:
                raise ValueError("training status source/result binding differs")
            if status["training_checkpoint_sha256"] != v3.sha256(
                (jobdir / "checkpoint.tar").read_bytes()
            ) or status["training_report_sha256"] != v3.sha256(
                (jobdir / "report.jsonl").read_bytes()
            ):
                raise ValueError("training recovery digest differs")
            result = status["training_result"]
            final = json.loads((jobdir / "report.jsonl").read_text().splitlines()[-1])
            if (
                final.get("phase") != "TRAIN_FINAL"
                or {k: v for k, v in final.items() if k != "phase"} != result
            ):
                raise ValueError("training final report and status differ")
            expected_identity = {
                "source_identity": binding["source_identity"],
                "source_archive_sha256": binding["source_archive_sha256"],
                "plan_sha256": plan_hash,
            }
            if (
                result["identity"] != expected_identity
                or result["specification_sha256"] != v3.sha256(v3.canonical(spec).encode())
                or result["checkpoint_sha256"] != status["training_checkpoint_sha256"]
                or result["completed"] != (result["next_step"] == result["total_steps"])
            ):
                raise ValueError("training result model/data/source/cursor identity differs")
            if previous is not None:
                validate_training_advance(previous, result)
            if result["steps_this_session"] <= 0:
                raise ValueError("training session made no optimizer progress")
            verified = jobdir / "verified-checkpoint"
            training.unpack(jobdir / "checkpoint.tar", verified)
            metadata = read(verified / "metadata.json")
            if (
                metadata.get("schema") != training.SCHEMA
                or any(
                    metadata.get(key) != result.get(key)
                    for key in (
                        "identity",
                        "specification_sha256",
                        "next_step",
                        "total_steps",
                        "completed",
                        "adapter_sha256",
                        "adapter_fingerprint",
                        "initial_adapter_fingerprint",
                    )
                )
                or metadata["adapter_sha256"]
                != v3.sha256((verified / "adapter_model.safetensors").read_bytes())
            ):
                raise ValueError("recovered adapter metadata or weight bytes differ")
            state["result"] = result
            state["passed"] = bool(
                state.get("remote_completed")
                and state.get("target_absent")
                and state.get("stopped")
                and not state.get("cost_error")
                and not state.get("watchdog_error")
            )
        except Exception as exc:
            state["evidence_error"] = str(exc)
        state["seconds"] = time.monotonic() - started
        _write_json(jobdir / "control.json", state)
    return state


def run(directory: Path) -> dict[str, Any]:
    financial_grant = read(directory / "grant.json")
    active_file = directory / "grant-native-cache.json"
    grant = read(active_file) if active_file.exists() else financial_grant
    validate_grant(directory, grant)
    continuation = "native_cache_continuation" in grant
    terminal_path = directory / (
        "terminal-anomaly-native-cache.json" if continuation else "terminal-anomaly.json"
    )
    result_path = directory / (
        "pipeline-result-native-cache.json" if continuation else "pipeline-result.json"
    )
    archive = source_archive_path(directory, grant)
    native_cache = grant.get("native_cache") is True
    os.environ["COLAB_CLI_ASSIGN_RETRIES"] = "0"
    if terminal_path.exists():
        raise ValueError("pipeline has a terminal anomaly; no automatic retry")
    budget = Budget(directory, financial_grant)
    budget.state()
    client = PipelineCLI()
    quiet(client)
    result: dict[str, Any] = {"source_identity": grant["source_identity"], "complete": False}
    try:
        diagnostic_control = directory / "diagnostic-control.json"
        if not diagnostic_control.exists():
            validate_grant(
                directory, grant, required_seconds=grant["diagnostic"]["wall_seconds"] + 300
            )
            proposed = diagnostic_session.proposal(archive, delegated=True)
            approval = {
                "schema": diagnostic_session.AUTH_SCHEMA,
                "proposal_sha256": proposed["proposal_sha256"],
                "accept_a1_for_diagnostic_only": True,
                "approve_exact_source_one_session": True,
                "maximum_new_cu": grant["diagnostic"]["maximum_new_cu"],
            }
            execution._write_exclusive(directory / "diagnostic-proposal.json", proposed)
            execution._write_exclusive(
                directory / "diagnostic-owner-delegated-approval.json", approval
            )
            budget.reserve("diagnostic", "DIAGNOSTIC", grant["diagnostic"]["maximum_new_cu"])
            state = diagnostic_session.run(
                client=client,
                proposed=proposed,
                approval=approval,
                archive=archive,
                startup_cu=None,
                live_t4_rate=None,
            )
            _write_json(diagnostic_control, state)
            budget.close(
                "diagnostic",
                state.get("new_conservative_cu"),
                diagnostic_control,
                passed=state.get("passed") is True,
            )
        state = read(diagnostic_control)
        if not state.get("passed"):
            raise ValueError("full-model diagnostic failed; no downstream work")
        proposed = read(directory / "diagnostic-proposal.json")
        report_path = (
            diagnostic_session.ROOT
            / proposed["proposal_sha256"]
            / Path(diagnostic_session.REMOTE_REPORT).name
        )
        if (
            v3.sha256(report_path.read_bytes())
            != state["recovered"][diagnostic_session.REMOTE_REPORT]
        ):
            raise ValueError("diagnostic evidence changed")
        report = json.loads(report_path.read_text().splitlines()[-1])
        rate = state["pricing_observation"]["rate_cu_per_hour"]
        plan_path = directory / (
            "baseline-plan-native-cache.json" if native_cache else "baseline-plan.json"
        )
        initial_baseline_budget = TOTAL_CAP_CU - sum(
            row["conservative_cu"]
            for row in budget.state()["sessions"]
            if row["kind"] == "DIAGNOSTIC"
        )
        if not plan_path.exists():
            execution._write_exclusive(
                plan_path,
                measured_plan(report, rate, initial_baseline_budget, native_cache=native_cache),
            )
        plan = read(plan_path)
        validate_plan(plan, report, rate, initial_baseline_budget, native_cache=native_cache)
        baseline = directory / "baseline"
        baseline.mkdir(exist_ok=True)
        allowance = {
            "schema": execution.ALLOWANCE_SCHEMA,
            "plan_sha256": plan["plan_sha256"],
            "source_identity": grant["source_identity"],
            "max_sessions": plan["session_count"],
            "cumulative_cap_cu": plan["compute_units"]["cumulative_cap"],
            "max_cu_per_session": plan["compute_units"]["per_session_cap"],
            "valid_until_utc": grant["valid_until_utc"],
            "allow_concurrent_unrelated_usage": False,
        }
        binding = execution.remote_binding(
            plan,
            archive,
            grant["source_identity"]["commit"],
            precision="float32",
            native_cache=native_cache,
        )
        items = worker.work_items(decision.load_protocol())
        checkpoint = baseline / "checkpoint.jsonl"
        while True:
            validate_grant(
                directory, grant, required_seconds=plan["bounds"]["session_seconds"] + 300
            )
            checked_baseline = baseline_state(baseline, items, plan, grant)
            count = len(checked_baseline["entries"])
            if count == len(items):
                break
            ledger = (
                read(baseline / "ledger.json")
                if (baseline / "ledger.json").exists()
                else {"sessions": []}
            )
            index = len(ledger["sessions"]) + 1
            key = f"baseline-{index:03d}"
            quiet(client)
            policy = execution.load_authorized_policy(directory)  # before any reservation
            budget.reserve(key, "BASELINE", plan["compute_units"]["per_session_cap"])
            client.watchdog_seconds = plan["bounds"]["session_seconds"]
            state = execution.run_session(
                client=client,
                plan=plan,
                ledger_path=baseline / "ledger.json",
                authorization=allowance,
                session_index=index,
                run_dir=baseline,
                source_archive=archive,
                binding=binding,
                cost_policy=policy,
            )
            path = baseline / f"session-{index:03d}-control.json"
            # One accounting authority: the shared ledger's policy-bound conservative charge.
            charged = read(baseline / "ledger.json")["sessions"][-1]
            spent = (
                charged["compute_units_spent"]
                if charged.get("cost_status") == "KNOWN"
                and charged.get("teardown_verified") is True
                and "failure" not in state
                else None
            )
            after = (
                len(worker.read_checkpoint(checkpoint, items)["entries"])
                if checkpoint.exists()
                else 0
            )
            anomaly = execution.session_anomaly(
                state, count, after, plan["compute_units"]["per_session_cap"]
            )
            budget.close(key, spent, path, passed=anomaly is None)
            if anomaly:
                raise ValueError(anomaly)
        score = worker.score_checkpoint(decision.load_protocol(), checkpoint)
        _write_json(directory / "baseline-score.json", score)
        result["baseline"] = score
        training_dir = directory / "training"
        training_dir.mkdir(exist_ok=True)
        sessions = sorted(training_dir.glob("session-*/control.json"))
        prior = None
        for path in sessions:
            state = read(path)
            if not state.get("passed"):
                raise ValueError("prior training anomaly; no retry")
            prior = path.parent / "checkpoint.tar"
            verified_training_prior(prior, grant)
        while not sessions or not state["result"]["completed"]:
            validate_grant(directory, grant, required_seconds=TRAINING_SECONDS + 300)
            index = len(sessions) + 1
            key = f"training-{index:03d}"
            ceiling = min(4, rate * 1.25)
            cap = (TRAINING_SECONDS + 90) * ceiling / 3600 + 0.2
            quiet(client)
            budget.reserve(key, "TRAINING", cap)
            state = training_session(training_dir, grant, index, prior, ceiling, cap, client)
            path = training_dir / f"session-{index:03d}/control.json"
            budget.close(
                key, state.get("conservative_cu"), path, passed=state.get("passed") is True
            )
            if not state["passed"]:
                raise ValueError("training anomaly; no automatic retry")
            prior = path.parent / "checkpoint.tar"
            verified_training_prior(prior, grant)
            sessions.append(path)
        assert prior is not None
        budget.state()
        export = directory / "trained-weights"
        if not export.exists():
            training.unpack(prior, export)
        metadata = read(export / "metadata.json")
        if (
            not metadata["completed"]
            or any(
                metadata.get(key) != state["result"].get(key)
                for key in (
                    "identity",
                    "specification_sha256",
                    "next_step",
                    "total_steps",
                    "adapter_sha256",
                    "adapter_fingerprint",
                    "initial_adapter_fingerprint",
                )
            )
            or metadata["adapter_fingerprint"] == metadata["initial_adapter_fingerprint"]
            or metadata["adapter_sha256"]
            != v3.sha256((export / "adapter_model.safetensors").read_bytes())
        ):
            raise ValueError("recovered learned weights are incomplete or unchanged")
        _write_json(
            export / "inference-manifest.json",
            {
                "base_model": grant["training"]["base_model"],
                "adapter_sha256": metadata["adapter_sha256"],
                "source_identity": grant["source_identity"],
                "training_manifest_sha256": grant["training"]["training"]["manifest_sha256"],
                "training_specification": grant["training"],
                "trained_candidate_task_accuracy": "NOT_EVALUATED",
                "full_fp32_trained_candidate_cache_qualification": "NOT_YET_EXECUTED",
            },
        )
        result.update(
            complete=True,
            trained_adapter_path=str(export / "adapter_model.safetensors"),
            trained_adapter_sha256=metadata["adapter_sha256"],
            training=state["result"],
            trained_candidate_task_accuracy="NOT_EVALUATED; training loss is not task accuracy",
            training_authority_basis="OWNER_REQUESTED_STUDY_AFTER_FROZEN_BASELINE",
        )
    except Exception as exc:
        result.update(error_type=type(exc).__name__, error_detail=str(exc))
        execution._write_exclusive(
            terminal_path,
            {
                "grant_sha256": budget.grant_hash,
                "error_type": type(exc).__name__,
                "error_detail": str(exc),
                "automatic_retry_permitted": False,
            },
        )
    result["budget"] = read(budget.path)
    _write_json(result_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "prepare-native-cache", "run"))
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    if not args.directory.resolve().is_relative_to(execution.E_ROOT):
        raise ValueError("persistent artifacts belong on E:")
    if args.command == "prepare":
        output = prepare(args.directory)
    elif args.command == "prepare-native-cache":
        output = prepare_native_cache_continuation(args.directory)
    else:
        output = run(args.directory)
    print(json.dumps(output, sort_keys=True))
    return 0 if args.command != "run" or output["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
