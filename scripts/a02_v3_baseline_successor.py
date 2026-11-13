"""Explicit baseline-only successor to the sealed preparation failure (RES-541).

prepare is read-only at the provider. run requires a separate exact-proposal owner receipt.
Original failed grants, ledgers, costs and checkpoints are never modified or reactivated.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import re
import subprocess
import time
from collections import Counter
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from scripts import a02_v3_automatic as automatic
from scripts import a02_v3_contract as v3
from scripts import a02_v3_decision as decision
from scripts import a02_v3_execution as execution
from scripts import a02_v3_worker as worker
from scripts.a02_execution import _write_json
from scripts.a02_v3_diagnostic_session import head_archive_sha256

PREDECESSOR = (
    execution.E_ROOT
    / "a02/owner-automatic-v1/479482b90196299056d47bc94a15261d57c8b4520b33b1afd451728cae9ed1f4"
)
MANIFEST_SHA256 = "b17615b81b30f63e23f0ff86379948d02910049f842d7216aa6fe453a015f949"
CHECKPOINT_SHA256 = "ab3e6bd176d3081dca66bac87a210c62c75f83b1876544f549822c30bc949eb8"
PREDECESSOR_HEAD = "441f30562d8a006909e3d6750ff5fa5f06a1d35d"
SCHEMA = "RES541_BASELINE_PREPARATION_SUCCESSOR_V1"
START = 307  # qualification plus153 genuine evaluations per arm


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_manifest(root: Path, expected: str) -> dict[str, str]:
    path = root / "execution-evidence-manifest-20261112.json"
    if digest(path) != expected:
        raise ValueError("sealed predecessor manifest changed")
    files = automatic.read(path)["files"]
    for name, expected_hash in files.items():
        relative = Path(name)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or (root / relative).resolve().parent.is_relative_to(root.resolve()) is False
        ):
            raise ValueError("unsafe predecessor manifest path")
        if digest(root / name) != expected_hash:
            raise ValueError(f"sealed predecessor evidence changed: {name}")
    return dict(files)


def scientific_compatibility() -> dict[str, str]:
    # Only orchestration, tests and the prospective recovery note may change.
    allowed = {
        "scripts/a02_v3_execution.py",
        "scripts/a02_v3_remote.py",
        "scripts/a02_v3_baseline_successor.py",
        "experiments/a02/preparation-successor-v1.md",
        ".repo-policy/noncode-inventory.tsv",
    }
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", PREDECESSOR_HEAD, "HEAD"], cwd=execution.ROOT, text=True
    ).splitlines()
    if any(name not in allowed and not name.startswith("tests/") for name in changed):
        raise ValueError("successor changes scientific or dependency sources")
    inventory = ".repo-policy/noncode-inventory.tsv"
    old_rows = subprocess.check_output(
        ["git", "show", f"{PREDECESSOR_HEAD}:{inventory}"], cwd=execution.ROOT, text=True
    ).splitlines()
    new_rows = (execution.ROOT / inventory).read_text().splitlines()
    if (
        new_rows[: len(old_rows)] != old_rows
        or len(new_rows) != len(old_rows) + 1
        or (
            new_rows[-1].split("\t")[:3]
            != [
                "experiments/a02/preparation-successor-v1.md",
                "documentation",
                digest(execution.ROOT / "experiments/a02/preparation-successor-v1.md"),
            ]
        )
    ):
        raise ValueError("successor changed predecessor inventory authority")
    previous = subprocess.check_output(
        ["git", "show", f"{PREDECESSOR_HEAD}:scripts/a02_v3_remote.py"], cwd=execution.ROOT
    ).decode()

    def child_ast(source: str) -> str:
        tree = ast.parse(source)
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "child")
        for item in ast.walk(node):
            if isinstance(item, ast.Dict):
                pairs = [
                    (k, v)
                    for k, v in zip(item.keys, item.values, strict=True)
                    if not (isinstance(k, ast.Constant) and k.value == "prepare_phase")
                ]
                item.keys = [k for k, v in pairs]
                item.values = [v for k, v in pairs]
        return ast.dump(node, include_attributes=False)

    if child_ast(previous) != child_ast((execution.ROOT / "scripts/a02_v3_remote.py").read_text()):
        raise ValueError("remote model/scoring child changed beyond progress metadata")
    paths = [
        "scripts/a02_v3_worker.py",
        "scripts/a02_v3_constrained.py",
        "scripts/a02_v3_numerics.py",
        "scripts/a02_v3_precision.py",
        "scripts/a02_v3_decision.py",
        "scripts/a02_v3_score.py",
        "scripts/a02_v3_contract.py",
        "scripts/a02_remote.py",
        "experiments/a02/model-comparison-protocol-v3.json",
        "experiments/a02/development-profile-v3.json",
        "experiments/a02/numerical-amendment-a1.md",
        "uv.lock",
        "pyproject.toml",
    ]
    return {
        **{name: digest(execution.ROOT / name) for name in paths},
        "unchanged_remote_child_ast": v3.sha256(child_ast(previous).encode()),
    }


def verify_predecessor(root: Path = PREDECESSOR) -> dict[str, Any]:
    files = verify_manifest(root, MANIFEST_SHA256)
    protocol = decision.load_protocol()
    items = worker.work_items(protocol)
    checkpoint = root / "baseline/checkpoint.jsonl"
    state = worker.read_checkpoint(checkpoint, items)
    worker.check_identity(state["entries"], protocol)
    if (
        digest(checkpoint) != CHECKPOINT_SHA256
        or len(state["entries"]) != START
        or state["torn_tail_discarded"]
    ):
        raise ValueError("predecessor checkpoint prefix differs")
    rows = state["entries"]
    qualification = rows[0]["record"]
    if (
        not qualification["passed"]
        or qualification["tolerance_nats"] != worker.QUALIFICATION_TOLERANCE_NATS
    ):
        raise ValueError("inherited qualification is invalid")
    counts = Counter(row["record"].get("arm") for row in rows[1:])
    if counts != {"ZERO_SHOT_UNCONSTRAINED": 153, "ZERO_SHOT_CONSTRAINED": 153}:
        raise ValueError("preserved baseline arm counts differ")
    examples = {decision.example_id(x): x for x in decision.heldout_examples(protocol)}
    for row, item in zip(rows[1:], items[1:START], strict=True):
        record = row["record"]
        if (
            record["raw_output_sha256"]
            != v3.sha256(record["raw_output"].encode("utf-8", "surrogatepass"))
            or record["arm"] != item.arm
            or record["example_id"] != item.key
            or record["request_sha256"] != decision.request_sha256(examples[item.key]["request"])
            or any(
                re.fullmatch(r"[0-9a-f]{64}", str(record.get(key, ""))) is None
                for key in ("generated_token_ids_sha256", "rendered_prompt_sha256")
            )
        ):
            raise ValueError("model record output or arm differs")
    first = automatic.read(root / "baseline/session-001-status.json")
    second = automatic.read(root / "baseline/session-002-status.json")
    binding = automatic.read(root / "baseline/session-001-binding.json")
    if (
        binding["source_identity"]["commit"] != PREDECESSOR_HEAD
        or binding["precision"] != "float32"
        or binding["protocol_sha256"] != decision.protocol_sha256()
    ):
        raise ValueError("predecessor source/protocol/precision binding differs")
    audit = first["precision_audit"]
    if (
        first["checkpoint_sha256"] != CHECKPOINT_SHA256
        or first["binding"] != binding
        or any(
            audit[key] != ["torch.float32"]
            for key in ("parameter_dtypes", "intermediate_dtypes", "logit_dtypes")
        )
    ):
        raise ValueError("preserved actual FP32 runtime proof differs")
    if first["weights"]["model_revision"] != protocol["candidate_model"]["revision"] or any(
        first["weights"]["support_files"][name]["sha256"] != value
        for name, value in v3.load_profile()["tokenizer"]["files"].items()
    ):
        raise ValueError("preserved model/tokenizer hashes differ")
    if (
        second["status"] != "EXECUTION_FAILED"
        or second["stages"][-1]["timed_out"] is not True
        or second["stages"][-1]["returncode"] != -15
    ):
        raise ValueError("predecessor is not the sealed preparation timeout")
    budget = automatic.read(root / "budget-ledger.json")
    old_grant = automatic.read(root / "grant.json")
    if (
        budget["maximum_new_cu"] != 50
        or budget["historical_cu_separate"] != 0.2537
        or budget["grant_sha256"] != v3.sha256(v3.canonical(old_grant).encode())
        or len(budget["sessions"]) != 3
    ):
        raise ValueError("original finite financial authority differs")
    for index, row in enumerate(budget["sessions"]):
        charge = automatic.read(root / Path(row["charge_path"]).name)
        marker = automatic.read(root / (row["key"] + "-used.json"))
        control_path = root / Path(charge["control_path"]).name
        if row["kind"] == "BASELINE":
            control_path = root / "baseline" / Path(charge["control_path"]).name
        if (
            digest(root / Path(row["charge_path"]).name) != row["charge_sha256"]
            or digest(control_path) != row["control_sha256"]
            or any(
                charge[k] != row[k]
                for k in (
                    "key",
                    "kind",
                    "sequence",
                    "cap_cu",
                    "conservative_cu",
                    "execution_status",
                    "cost_status",
                    "control_sha256",
                )
            )
            or marker["sequence"] != index
            or marker["grant_sha256"] != budget["grant_sha256"]
            or charge["grant_sha256"] != budget["grant_sha256"]
            or row["cost_status"] != "KNOWN"
            or not 0 <= row["conservative_cu"] <= row["cap_cu"]
        ):
            raise ValueError("predecessor cost/charge/control binding differs")
    if [row["execution_status"] for row in budget["sessions"]] != [
        "CLEAN",
        "CLEAN",
        "FAILED",
    ] or automatic.read(root / "terminal-anomaly-native-cache.json")[
        "automatic_retry_permitted"
    ] is not False:
        raise ValueError("predecessor terminal disposition changed")
    for index in (1, 2):
        control = automatic.read(root / f"baseline/session-{index:03d}-control.json")
        inventories = control["teardown_receipt"]
        if (
            not control["stopped"]
            or not control["target_absent_after_stop"]
            or inventories["sessions"]["returncode"] != 0
            or "No active sessions found" not in inventories["sessions"]["stdout"]
            or inventories["assignments"]["returncode"] != 0
            or json.loads(inventories["assignments"]["stdout"])["assignments"]
            or automatic.read(root / f"baseline/session-{index:03d}-watchdog.json")["phase"]
            != "DISARMED"
        ):
            raise ValueError("predecessor teardown is not confirmed")
        if digest(root / f"baseline/session-{index:03d}-checkpoint.jsonl") != CHECKPOINT_SHA256:
            raise ValueError("failed preparation changed the inherited checkpoint")
    spent = sum(row["conservative_cu"] for row in budget["sessions"])
    return {
        "manifest_sha256": MANIFEST_SHA256,
        "sealed_files": files,
        "source_identity": binding["source_identity"],
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "checkpoint_head": state["head"],
        "starting_entries": START,
        "verified_task_evaluations": START - 1,
        "per_arm": dict(counts),
        "work_list_sha256": worker.work_list_sha256(items),
        "remaining_worklist": [x.id for x in items[START:]],
        "remaining_worklist_sha256": v3.sha256(
            v3.canonical([x.id for x in items[START:]]).encode()
        ),
        "new_campaign_spent_cu": spent,
        "historical_cu_separate": 0.2537,
        "unspent_original_ceiling_cu": 50 - spent,
        "terminal_failed_session_preserved": True,
        "last_observed_t4_cu_per_hour": automatic.read(root / "baseline/session-002-control.json")[
            "rate_after_allocation"
        ],
    }


def continuation_plan(root: Path, predecessor: dict[str, Any], rate: float) -> dict[str, Any]:
    if not math.isfinite(rate) or not 0 < rate <= 4:
        raise ValueError("invalid observed T4 rate")
    original = automatic.read(root / "baseline-plan-native-cache.json")
    protocol = decision.load_protocol()
    items = worker.work_items(protocol)
    first = automatic.read(root / "baseline/session-001-status.json")
    second = automatic.read(root / "baseline/session-002-status.json")
    bounds = execution.RuntimeBounds(**original["bounds"])
    observed = [first["prepare_seconds"], second["prepare_seconds"]]
    prepare = execution.derive_preparation_seconds(observed, bounds)
    bounds = replace(
        bounds,
        prepare_seconds=prepare,
        t4_rate_cu_per_hour=rate,
        admission_rate_ceiling_cu_per_hour=rate * 1.25,
    )
    # Use actual complete-item measurements, normalize to the frozen token/call maxima, double.
    native = first["native_cache_measurements"]
    records = [
        r["record"]
        for r in worker.read_checkpoint(root / "baseline/checkpoint.jsonl", items)["entries"][1:]
    ]
    calls = original["scorer_call_bound"]["used_for_pricing"]
    costs = {
        "QUALIFICATION": original["item_cost_bounds_seconds"]["QUALIFICATION"],
        "ZERO_SHOT_UNCONSTRAINED": 1
        + 2
        * max(x["seconds"] / x["tokens"] for x in native)
        * v3.load_profile()["decoding"]["action_max_new_tokens"],
        "ZERO_SHOT_CONSTRAINED": 1
        + 2
        * max(
            r["seconds"] / r["scorer_calls"] for r in records if r["arm"] == "ZERO_SHOT_CONSTRAINED"
        )
        * calls,
    }
    budget = execution.generation_seconds_per_session(bounds)
    packed = []
    start, used = START, 0.0
    for index, item in enumerate(items[START:], START):
        cost = costs[item.arm]
        if cost > budget:
            raise ValueError("one remaining item exceeds session capacity")
        if used + cost > budget:
            packed.append({"first_item": start, "end_item": index, "worst_case_seconds": used})
            start, used = index, 0.0
        used += cost
    packed.append({"first_item": start, "end_item": len(items), "worst_case_seconds": used})
    new_sessions = len(packed) + 1
    prior_cost = sum(
        x["conservative_cu"]
        for x in automatic.read(root / "budget-ledger.json")["sessions"]
        if x["kind"] == "BASELINE"
    )
    per = (
        bounds.session_seconds / 3600 * bounds.admission_rate_ceiling_cu_per_hour
        + bounds.cost_buffer_cu
    )
    cap = math.ceil(per * new_sessions * 10000) / 10000
    if cap > predecessor["unspent_original_ceiling_cu"]:
        raise ValueError("successor exceeds remaining original 50-CU ceiling")
    expected_scoring = sum(r["seconds"] for r in records) / (START - 1) * (len(items) - START)
    expected_sessions = max(1, math.ceil(expected_scoring / budget))
    plan = {
        "schema": execution.PLAN_SCHEMA,
        "protocol_sha256": decision.protocol_sha256(),
        "bounds": asdict(bounds),
        "item_cost_bounds_seconds": costs,
        "operation_cost_policy": {
            "basis": "actual FP32 complete-item timings, frozen token/call maxima, 2x margin",
            "legacy_shared_decode_floor_used": False,
        },
        "generation_seconds_per_session": budget,
        "work_items": len(items),
        "starting_item": START,
        "scheduled_work_items": len(items) - START,
        "sessions": [dict(s, index=i + 3) for i, s in enumerate(packed)],
        "packed_sessions": len(packed),
        "reserve_sessions": 1,
        "session_count": new_sessions + 2,
        "new_session_count": new_sessions,
        "worst_case_generation_seconds": sum(s["worst_case_seconds"] for s in packed),
        "compute_units": {
            "per_session_cap": per,
            "cumulative_cap": prior_cost + cap,
            "maximum_additional_cu": cap,
            "expected_sessions": expected_sessions,
            "expected_scoring_seconds": expected_scoring,
            "expected_at_observed_rate_cu": rate
            * (
                expected_sessions
                * (prepare + bounds.inference_overhead_seconds + bounds.cleanup_reserve_seconds)
                + expected_scoring
            )
            / 3600,
        },
        "preparation_derivation": {
            "observed_seconds": observed,
            "censored": True,
            "multiplier": 4,
            "round_up_seconds": 60,
            "result_seconds": prepare,
            "qualification": "censored time is a lower bound; download completion is uncertain",
        },
        "qualification": "INHERITED_PASSED_DO_NOT_REPEAT",
        "rate_basis": "last actual paid T4 observations; live preallocation quote unavailable",
        "retry_policy": "No anomaly retry. Reserve slots continue clean incomplete checkpoints.",
    }
    plan["plan_sha256"] = v3.sha256(v3.canonical(plan).encode())
    return plan


def prepare(directory: Path, client: Any) -> dict[str, Any]:
    if directory.exists():
        raise ValueError("successor directory already exists; no overwrite")
    predecessor = verify_predecessor()
    compatibility = scientific_compatibility()
    snapshot = automatic.quiet(client)
    source = execution.source_identity()
    now = datetime.now(UTC)
    directory.mkdir(parents=True)
    archive, _ = execution.source_archive(directory / "source.tar")
    last = predecessor["last_observed_t4_cu_per_hour"]
    plan = continuation_plan(PREDECESSOR, predecessor, last)
    value = {
        "schema": SCHEMA,
        "status": "PROPOSED_NOT_AUTHORIZED",
        "scope": "REMAINING_BASELINE_ONLY_NO_TRAINING",
        "execution_directory": str(directory.resolve()),
        "source_identity": source,
        "source_archive_sha256": digest(archive),
        "scientific_compatibility": compatibility,
        "predecessor": predecessor,
        "plan": plan,
        "valid_from_utc": now.isoformat(),
        "valid_until_utc": (now + timedelta(hours=48)).isoformat(),
        "live_readonly_snapshot": snapshot,
        "last_observed_t4_cu_per_hour": last,
        "live_t4_preallocation_quote": "UNAVAILABLE; idle rate is not a T4 quote",
        "original_maximum_new_cu": 50,
        "maximum_additional_cu": plan["compute_units"]["maximum_additional_cu"],
        "maximum_cumulative_new_campaign_cu": predecessor["new_campaign_spent_cu"]
        + plan["compute_units"]["maximum_additional_cu"],
        "maximum_new_sessions": plan["new_session_count"],
        "first_new_session_index": 3,
        # Reserve 180 seconds for watchdog discovery, stop and both inventory checks.
        "independent_watchdog_seconds": plan["bounds"]["session_seconds"] - 180,
        "stop_reserve_seconds": plan["bounds"]["cleanup_reserve_seconds"],
        "no_retry": True,
        "training_authorized": False,
    }
    value["proposal_sha256"] = v3.sha256(v3.canonical(value).encode())
    execution._write_exclusive(directory / "proposal.json", value)
    return value


def validate_window(value: dict[str, Any], required_seconds: float = 0) -> None:
    try:
        start = datetime.fromisoformat(value["valid_from_utc"])
        end = datetime.fromisoformat(value["valid_until_utc"])
        now = datetime.now(UTC)
        if (
            start.tzinfo is None
            or end.tzinfo is None
            or not start <= now < end
            or end - start > timedelta(hours=48)
            or (end - now).total_seconds() < required_seconds
        ):
            raise ValueError("successor window cannot cover the bounded session and teardown")
    except (TypeError, KeyError) as exc:
        raise ValueError("malformed successor validity window") from exc


def validate(directory: Path, *, required_seconds: float | None = 0) -> dict[str, Any]:
    value = automatic.read(directory / "proposal.json")
    payload = {k: v for k, v in value.items() if k != "proposal_sha256"}
    if (
        value.get("schema") != SCHEMA
        or value.get("execution_directory") != str(directory.resolve())
        or v3.sha256(v3.canonical(payload).encode()) != value.get("proposal_sha256")
        or value["source_identity"] != execution.source_identity()
        or digest(directory / "source.tar") != value["source_archive_sha256"]
        or head_archive_sha256() != value["source_archive_sha256"]
    ):
        raise ValueError("successor proposal/source/archive differs")
    if (
        value["predecessor"] != verify_predecessor()
        or value["scientific_compatibility"] != scientific_compatibility()
        or value["plan"]
        != continuation_plan(
            PREDECESSOR, value["predecessor"], value["last_observed_t4_cu_per_hour"]
        )
    ):
        raise ValueError("successor evidence or re-derived plan differs")
    if (
        value["scope"] != "REMAINING_BASELINE_ONLY_NO_TRAINING"
        or value["training_authorized"] is not False
        or value["no_retry"] is not True
        or value["original_maximum_new_cu"] != 50
        or value["maximum_additional_cu"] != value["plan"]["compute_units"]["maximum_additional_cu"]
        or value["maximum_new_sessions"] != value["plan"]["new_session_count"]
        or value["maximum_cumulative_new_campaign_cu"]
        != value["predecessor"]["new_campaign_spent_cu"] + value["maximum_additional_cu"]
        or value["last_observed_t4_cu_per_hour"]
        != value["predecessor"]["last_observed_t4_cu_per_hour"]
        or value["first_new_session_index"] != 3
        or value["independent_watchdog_seconds"] != value["plan"]["bounds"]["session_seconds"] - 180
        or value["stop_reserve_seconds"] != value["plan"]["bounds"]["cleanup_reserve_seconds"]
    ):
        raise ValueError("successor scope/budget differs")
    if required_seconds is not None:
        validate_window(value, required_seconds)
    return value


def validate_approval(proposal: dict[str, Any], approval: dict[str, Any]) -> None:
    if (
        set(approval)
        != {"schema", "proposal_sha256", "approved", "owner_statement", "recorded_utc"}
        or approval["schema"] != "RES541_BASELINE_SUCCESSOR_OWNER_APPROVAL_V1"
        or approval["proposal_sha256"] != proposal["proposal_sha256"]
        or approval["approved"] is not True
        or not isinstance(approval["owner_statement"], str)
        or not approval["owner_statement"].strip()
    ):
        raise ValueError("explicit exact-proposal successor owner approval required")
    stamp = datetime.fromisoformat(approval["recorded_utc"])
    if not datetime.fromisoformat(proposal["valid_from_utc"]) <= stamp <= datetime.now(UTC):
        raise ValueError("owner approval timestamp differs from the validity window")


def inherited_ledger(proposal: dict[str, Any]) -> dict[str, Any]:
    old = automatic.read(PREDECESSOR / "baseline/ledger.json")
    charges = automatic.read(PREDECESSOR / "budget-ledger.json")["sessions"][1:]
    entries = [
        {
            **row,
            "source_identity": proposal["predecessor"]["source_identity"],
            "original_account_delta_cu": row["compute_units_spent"],
            "compute_units_spent": charge["conservative_cu"],
            "inherited_charge_sha256": charge["charge_sha256"],
            "inherited": True,
        }
        for row, charge in zip(old["sessions"], charges, strict=True)
    ]
    return {
        "schema": execution.LEDGER_SCHEMA,
        "plan_sha256": proposal["plan"]["plan_sha256"],
        "source_identity": proposal["source_identity"],
        "predecessor_manifest_sha256": MANIFEST_SHA256,
        "sessions": entries,
    }


def run(directory: Path, approval_path: Path, client: Any) -> dict[str, Any]:
    proposal = validate(directory)
    approval = automatic.read(approval_path)
    validate_approval(proposal, approval)
    if (directory / "execution-used.json").exists():
        raise ValueError("successor execution already consumed; no retry")
    automatic.quiet(client)
    execution._write_exclusive(
        directory / "execution-used.json",
        {"proposal_sha256": proposal["proposal_sha256"], "owner_approval": approval},
    )
    plan = proposal["plan"]
    ledger_path = directory / "ledger.json"
    checkpoint = directory / "checkpoint.jsonl"
    # Exclusive copies carry bytes and identities forward; predecessor files remain untouched.
    with checkpoint.open("xb") as stream:
        stream.write((PREDECESSOR / "baseline/checkpoint.jsonl").read_bytes())
    execution._write_exclusive(ledger_path, inherited_ledger(proposal))
    allowance = {
        "schema": execution.ALLOWANCE_SCHEMA,
        "plan_sha256": plan["plan_sha256"],
        "source_identity": proposal["source_identity"],
        "max_sessions": plan["session_count"],
        "cumulative_cap_cu": plan["compute_units"]["cumulative_cap"],
        "max_cu_per_session": plan["compute_units"]["per_session_cap"],
        "valid_until_utc": proposal["valid_until_utc"],
        "allow_concurrent_unrelated_usage": False,
    }
    archive = directory / "source.tar"
    binding = execution.remote_binding(
        plan, archive, proposal["source_identity"]["commit"], precision="float32", native_cache=True
    )
    protocol = decision.load_protocol()
    items = worker.work_items(protocol)
    result: dict[str, Any] = {
        "complete": False,
        "proposal_sha256": proposal["proposal_sha256"],
        "additional_conservative_cu": 0.0,
        "inherited_task_evaluations": START - 1,
        "new_task_evaluations": 0,
        "sessions": [],
    }

    def checked_checkpoint() -> dict[str, Any]:
        # Completed observations remain valid after the paid-allocation window closes.
        checked = validate(directory, required_seconds=None)
        if checked["proposal_sha256"] != proposal["proposal_sha256"]:
            raise ValueError("approved proposal changed during successor execution")
        state = worker.read_checkpoint(checkpoint, items)
        worker.check_identity(state["entries"], protocol)
        if not checkpoint.read_bytes().startswith(
            (PREDECESSOR / "baseline/checkpoint.jsonl").read_bytes()
        ):
            raise ValueError("successor replaced inherited checkpoint bytes")
        return state

    try:
        for index in range(3, plan["session_count"] + 1):
            before = checked_checkpoint()
            if len(before["entries"]) == len(items):
                break
            validate_window(proposal, required_seconds=plan["bounds"]["session_seconds"] + 90)
            automatic.quiet(client)
            if (
                result["additional_conservative_cu"] + plan["compute_units"]["per_session_cap"]
                > proposal["maximum_additional_cu"] + 1e-9
            ):
                raise ValueError("successor additional cap exhausted")
            client.watchdog_module = "scripts.a02_v3_execution"
            client.watchdog_seconds = proposal["independent_watchdog_seconds"]
            started = time.monotonic()
            state = execution.run_session(
                client=client,
                plan=plan,
                ledger_path=ledger_path,
                authorization=allowance,
                session_index=index,
                run_dir=directory,
                source_archive=archive,
                binding=binding,
            )
            spent = None
            if state.get("target_absent_after_stop") and state.get("quota_after"):
                spent = max(
                    state["quota_before"]["balance"] - state["quota_after"]["balance"],
                    state.get("rate_after_allocation", 0) * (time.monotonic() - started) / 3600,
                )
            after = worker.read_checkpoint(checkpoint, items)
            problem = execution.session_anomaly(
                state,
                len(before["entries"]),
                len(after["entries"]),
                plan["compute_units"]["per_session_cap"],
            )
            if (
                spent is None
                or not math.isfinite(spent)
                or not 0 <= spent <= plan["compute_units"]["per_session_cap"]
            ):
                problem = "unknown or excessive successor cost"
            result["sessions"].append(
                {
                    "index": index,
                    "conservative_cu": spent,
                    "control_sha256": digest(directory / f"session-{index:03d}-control.json"),
                    "problem": problem,
                }
            )
            if spent is not None:
                result["additional_conservative_cu"] += spent
            result["new_task_evaluations"] = len(after["entries"]) - START
            _write_json(directory / "progress.json", result)
            if problem:
                raise ValueError(problem)
        final = checked_checkpoint()
        if len(final["entries"]) != len(items) or final["torn_tail_discarded"]:
            raise ValueError("successor bounded session count exhausted before complete baseline")
        result["scientific_score"] = worker.score_checkpoint(decision.load_protocol(), checkpoint)
        result["complete"] = True
        result["training_started"] = False
        result["total_new_campaign_cu"] = (
            proposal["predecessor"]["new_campaign_spent_cu"] + result["additional_conservative_cu"]
        )
        result["total_with_historical_cu"] = 0.2537 + result["total_new_campaign_cu"]
    except Exception as exc:
        result["error"] = str(exc)
        execution._write_exclusive(
            directory / "terminal-anomaly.json",
            {"error": str(exc), "automatic_retry_permitted": False},
        )
    _write_json(directory / "result.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "validate", "run"))
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--approval", type=Path)
    args = parser.parse_args()
    if not args.directory.resolve().is_relative_to(execution.E_ROOT):
        raise ValueError("persistent successor evidence belongs on E:")
    os.environ["COLAB_CLI_ASSIGN_RETRIES"] = "0"
    if args.command == "prepare":
        output = prepare(args.directory, automatic.PipelineCLI())
    elif args.command == "validate":
        output = validate(args.directory)
    else:
        if args.approval is None:
            raise ValueError("separate explicit owner approval file required")
        output = run(args.directory, args.approval, automatic.PipelineCLI())
    print(json.dumps(output, sort_keys=True))
    return 0 if args.command != "run" or output["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
