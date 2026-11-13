"""Bounded multi-session controller for the V3 zero-shot arms (RES-541).

Nothing here allocates a GPU unless ``run-session`` or ``run-campaign`` is invoked with a valid
owner campaign allowance bound to the exact plan hash: one finite, expiring grant that names the
most sessions and compute units that may ever be spent. No such allowance exists. The original
V2 campaign ledger and session markers are never read for budget or modified; V3 keeps its own
ledger.

Planning is mechanical: every work item has a worst-case cost derived from the profile and
preflight with conservative runtime bounds, items are packed in preregistered order into
sessions of bounded length, and the compute-unit cap follows from the session count and an
admission rate ceiling. The worker's own deadline check, not this packing, decides where a
session actually stops, so a session never ends mid-item.

A campaign runs sessions back to back under that one allowance, but stops at the first anomaly
and never retries one; only a deliberate new invocation continues after a stop.

Per session: admission against the live read-only quota snapshot and the V3 ledger, a session
marker consumed before allocation, exact-name T4 allocation with no retry, an immediate stop if
the live rate exceeds the ceiling, bounded prepare and work stages, checkpoint download even
after failure, a fork-safe merge of the downloaded checkpoint, and exact-target teardown in
``finally``. Unrelated sessions are never stopped.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import select
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from scripts import a02_v3_constrained as constrained
from scripts import a02_v3_contract as v3
from scripts import a02_v3_decision as decision
from scripts import a02_v3_score as score
from scripts import a02_v3_worker as worker

ROOT = v3.ROOT
E_ROOT = Path("/mnt/e/DynamisLM-A0").resolve()
V3_DIR = E_ROOT / "a02/v3-zero-shot"
PLAN_SCHEMA = "RES541_A02_V3_SESSION_PLAN_V1"
ALLOWANCE_SCHEMA = "RES541_A02_V3_CAMPAIGN_ALLOWANCE_V1"
SUCCESSOR_ALLOWANCE_SCHEMA = "RES541_A02_V3_CAMPAIGN_ALLOWANCE_V2"
ALLOWANCE_KEYS = frozenset(
    {
        "schema",
        "plan_sha256",
        "source_identity",
        "max_sessions",
        "cumulative_cap_cu",
        "max_cu_per_session",
        "valid_until_utc",
        "allow_concurrent_unrelated_usage",
    }
)
SUCCESSOR_ALLOWANCE_KEYS = ALLOWANCE_KEYS | {"predecessor"}
LEDGER_SCHEMA = "RES541_A02_V3_LEDGER_V1"
SUCCESSOR_LEDGER_SCHEMA = "RES541_A02_V3_LEDGER_V2"
REMOTE_STATUS = "/content/a02-v3-status.json"
REMOTE_CHECKPOINT = "/content/a02-v3-checkpoint.jsonl"
REMOTE_SOURCE = "/content/a02-v3-source.tar"
REMOTE_BINDING = "/content/a02-v3-binding.json"


@dataclass(frozen=True)
class RuntimeBounds:
    """Conservative bounds; each is looser than its session-004 observation."""

    session_seconds: int = 900  # reviewed V2 per-session bound
    exec_seconds: int = 720  # reviewed V2 remote exec bound
    cleanup_reserve_seconds: int = 90  # download + exact stop after exec
    prepare_seconds: int = 180  # observed 108 s incl. 79 s weight download
    inference_overhead_seconds: int = 100  # observed 77.7 s + 7.3 s warm-up
    worker_margin_seconds: int = 30
    decode_floor_tokens_per_second: float = 20.0  # observed minimum 23.05
    per_generation_overhead_seconds: float = 1.0  # observed first token <= 0.41 s after warm-up
    full_forward_seconds: float = 0.6  # uncached full re-score; observed prefill ~0.41 s
    t4_rate_cu_per_hour: float = 1.15  # provider-reported T4 rate in session 004
    admission_rate_ceiling_cu_per_hour: float = 1.25  # stop at once above this
    cost_buffer_cu: float = 0.05  # per-session reserve, as in V2
    reserve_sessions: int = 1  # extra sessions beyond worst-case packing; see robustness


def item_cost_bounds(
    profile: dict[str, Any], preflight: dict[str, Any], b: RuntimeBounds
) -> dict[str, float]:
    """Worst-case seconds per work item kind."""
    cap = profile["decoding"]["action_max_new_tokens"]
    calls = preflight["max_constrained_scorer_calls"]
    step = 1.0 / b.decode_floor_tokens_per_second
    native = b.per_generation_overhead_seconds + cap * step
    constrained = b.per_generation_overhead_seconds + calls * step
    qualification = worker.QUALIFICATION_EXAMPLES * (constrained + calls * b.full_forward_seconds)
    return {
        "ZERO_SHOT_UNCONSTRAINED": round(native, 3),
        "ZERO_SHOT_CONSTRAINED": round(constrained, 3),
        "QUALIFICATION": round(qualification, 3),
    }


def generation_seconds_per_session(b: RuntimeBounds) -> int:
    return (
        b.exec_seconds - b.prepare_seconds - b.inference_overhead_seconds - b.worker_margin_seconds
    )


def derive_preparation_seconds(observations: Sequence[float], bounds: RuntimeBounds) -> int:
    """Fourfold headroom over observed/censored prepare times, within the session budget.

    A censored download is only a lower bound; the independent watchdog remains necessary.
    """
    if not observations or any(
        isinstance(x, bool) or not math.isfinite(x) or x <= 0 for x in observations
    ):
        raise ValueError("preparation observations must be finite positive seconds")
    seconds = max(180, math.ceil(max(observations) * 4 / 60) * 60)
    if (
        bounds.exec_seconds + bounds.cleanup_reserve_seconds > bounds.session_seconds
        or generation_seconds_per_session(replace(bounds, prepare_seconds=seconds)) <= 0
    ):
        raise ValueError("derived preparation window cannot fit the bounded session")
    return seconds


def workload_scorer_calls(protocol: dict[str, Any]) -> int:
    """Largest constrained scorer-call bound over every request the worker will score.

    The CPU preflight measures only the ten exposed cases; the work list is dominated by the 280
    held-out examples and uses calibration examples, so its bound must come from all of them.
    """
    requests = [e["request"] for e in decision.heldout_examples(protocol)]
    requests += [e["request"] for e in worker.calibration_examples(protocol)]
    requests += [case["request"] for case in score._cases().values()]
    return int(max(constrained.max_scorer_calls(request) for request in requests))


def build_plan(
    protocol: dict[str, Any],
    preflight: dict[str, Any],
    bounds: RuntimeBounds,
    *,
    live_rate_cu_per_hour: float | None = None,
    measured_cost_bounds: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Deterministic worst-case session packing and compute-unit admission plan."""
    profile = v3.load_profile()
    items = worker.work_items(protocol)
    calls = max(preflight["max_constrained_scorer_calls"], workload_scorer_calls(protocol))
    costs = item_cost_bounds(profile, {**preflight, "max_constrained_scorer_calls": calls}, bounds)
    if measured_cost_bounds is not None:
        if set(measured_cost_bounds) != set(costs) or any(
            isinstance(value, bool) or not math.isfinite(value) or value <= 0
            for value in measured_cost_bounds.values()
        ):
            raise ValueError("measured operation cost bounds must be finite, positive and complete")
        costs = dict(measured_cost_bounds)
    budget = generation_seconds_per_session(bounds)
    if budget <= 0 or any(cost > budget for cost in costs.values()):
        raise ValueError("a single work item cannot fit one bounded session")
    sessions: list[dict[str, Any]] = []
    start, used = 0, 0.0
    for index, item in enumerate(items):
        cost = costs[item.arm if item.key != "QUALIFICATION" else "QUALIFICATION"]
        if used + cost > budget:
            sessions.append({"first_item": start, "end_item": index, "worst_case_seconds": used})
            start, used = index, 0.0
        used += cost
    sessions.append({"first_item": start, "end_item": len(items), "worst_case_seconds": used})
    packed = len(sessions)
    session_count = packed + bounds.reserve_sessions
    capacity = session_count * budget
    slack = capacity - sum(s["worst_case_seconds"] for s in sessions)
    if bounds.reserve_sessions < 0 or slack < budget:
        # A plan that cannot absorb one entire lost session (for example a failed allocation,
        # which is never retried automatically) is not robust enough to propose.
        raise ValueError("the plan has less slack than one whole session; add a reserve session")
    rate = bounds.admission_rate_ceiling_cu_per_hour
    per_session_cu = bounds.session_seconds / 3600 * rate + bounds.cost_buffer_cu
    total_worst = sum(s["worst_case_seconds"] for s in sessions)
    plan = {
        "schema": PLAN_SCHEMA,
        "protocol_sha256": decision.protocol_sha256(),
        "contract_profile_sha256": protocol["contract_profile_sha256"],
        "preflight_sha256": v3.sha256(v3.canonical(preflight).encode()),
        "bounds": asdict(bounds),
        "item_cost_bounds_seconds": costs,
        "scorer_call_bound": {
            "exposed_only_preflight": preflight["max_constrained_scorer_calls"],
            "used_for_pricing": calls,
            "basis": "maximum over held-out, calibration and exposed requests",
        },
        "generation_seconds_per_session": budget,
        "work_items": len(items),
        "worst_case_generation_seconds": round(total_worst, 1),
        "sessions": [{**s, "index": i + 1} for i, s in enumerate(sessions)],
        "packed_sessions": packed,
        "reserve_sessions": bounds.reserve_sessions,
        "session_count": session_count,
        "robustness": {
            "capacity_seconds": capacity,
            "slack_seconds": round(slack, 1),
            "slack_fraction_of_worst_case": round(slack / total_worst, 3),
            "tolerates_one_lost_session": slack >= budget,
            "criterion": "total slack must cover at least one entire lost session, because a "
            "failed session is never retried automatically and still consumes its index",
        },
        "worst_case_session_seconds": session_count * bounds.session_seconds,
        "compute_units": {
            "per_session_cap": round(per_session_cu, 4),
            "cumulative_cap": round(session_count * per_session_cu, 4),
            "expected_at_observed_t4_rate": round(
                packed * bounds.session_seconds / 3600 * bounds.t4_rate_cu_per_hour, 4
            ),
            "expected_if_every_allowed_session_runs": round(
                session_count * bounds.session_seconds / 3600 * bounds.t4_rate_cu_per_hour, 4
            ),
            "rate_basis": "session-004 provider-reported T4 rate; admission stops above ceiling",
        },
        "cache_qualification": {
            "worst_case_seconds": costs["QUALIFICATION"],
            "share_of_first_session": round(costs["QUALIFICATION"] / budget, 3),
            "uncached_full_forwards": worker.QUALIFICATION_EXAMPLES * calls,
        },
        "retry_policy": "No automatic retry. A session that commits fewer items than packed "
        "leaves the remainder to a later session of the same allowance, which may continue only "
        "by a deliberate new invocation. The reserve covers one entirely lost session. If the "
        "allowed count is exhausted, any extra session needs a new allowance and plan amendment.",
    }
    if measured_cost_bounds is not None:
        plan["operation_cost_policy"] = {
            "basis": "separate measured FP32 operation bounds",
            "legacy_shared_decode_floor_used": False,
        }
    # The hash covers deterministic inputs only, so the printed plan and the plan recomputed at
    # run time are the same plan. Live account state is informational and never hashed.
    plan["plan_sha256"] = v3.sha256(v3.canonical(plan).encode())
    plan["live_observation_not_hashed"] = {
        "usage_rate_cu_per_hour_at_planning": live_rate_cu_per_hour
    }
    return plan


# --------------------------------------------------------------------------- admission


class AdmissionError(RuntimeError):
    pass


def ledger_new(plan: dict[str, Any]) -> dict[str, Any]:
    return {"schema": LEDGER_SCHEMA, "plan_sha256": plan["plan_sha256"], "sessions": []}


def successor_predecessor(plan: dict[str, Any]) -> dict[str, Any]:
    """Fingerprint the one consumed V1 session that a V2 allowance may carry forward."""
    run_dir = V3_DIR / f"plan-{plan['plan_sha256'][:12]}"
    paths = {
        "allowance_sha256": V3_DIR / "campaign-allowance.json",
        "ledger_sha256": run_dir / "ledger.json",
        "controller_ledger_sha256": run_dir / "session-001-ledger-controller-output.json",
        "binding_sha256": run_dir / "session-001-binding.json",
        "used_sha256": run_dir / "session-001-used.json",
        "control_sha256": run_dir / "session-001-control.json",
        "status_sha256": run_dir / "session-001-status.json",
        "cost_reconciliation_sha256": run_dir / "session-001-cost-reconciliation.json",
        "stop_summary_sha256": run_dir / "campaign-stop-summary.json",
        "watchdog_sha256": run_dir / "session-001-watchdog.json",
        "source_archive_sha256": run_dir / "source-001.tar",
    }
    evidence = {key: path.read_bytes() for key, path in paths.items()}
    binding = v3.json_object(evidence["binding_sha256"].decode())
    predecessor = {
        "source_identity": binding.get("source_identity"),
        **{key: v3.sha256(data) for key, data in evidence.items()},
    }
    _validate_successor_predecessor(plan, predecessor)
    return predecessor


def _validate_successor_predecessor(
    plan: dict[str, Any], predecessor: dict[str, Any]
) -> dict[str, Any]:
    expected_keys = {
        "source_identity",
        "allowance_sha256",
        "ledger_sha256",
        "controller_ledger_sha256",
        "binding_sha256",
        "used_sha256",
        "control_sha256",
        "status_sha256",
        "cost_reconciliation_sha256",
        "stop_summary_sha256",
        "watchdog_sha256",
        "source_archive_sha256",
    }
    if not isinstance(predecessor, dict) or set(predecessor) != expected_keys:
        raise AdmissionError("V2 allowance predecessor evidence fields differ")
    source = predecessor["source_identity"]
    if not isinstance(source, dict) or set(source) != {"commit", "tree"}:
        raise AdmissionError("V2 allowance predecessor source identity is invalid")
    if not all(isinstance(value, str) and len(value) == 40 for value in source.values()):
        raise AdmissionError("V2 allowance predecessor source identity is invalid")

    run_dir = V3_DIR / f"plan-{plan['plan_sha256'][:12]}"
    paths = {
        "allowance_sha256": V3_DIR / "campaign-allowance.json",
        "ledger_sha256": run_dir / "ledger.json",
        "controller_ledger_sha256": run_dir / "session-001-ledger-controller-output.json",
        "binding_sha256": run_dir / "session-001-binding.json",
        "used_sha256": run_dir / "session-001-used.json",
        "control_sha256": run_dir / "session-001-control.json",
        "status_sha256": run_dir / "session-001-status.json",
        "cost_reconciliation_sha256": run_dir / "session-001-cost-reconciliation.json",
        "stop_summary_sha256": run_dir / "campaign-stop-summary.json",
        "watchdog_sha256": run_dir / "session-001-watchdog.json",
        "source_archive_sha256": run_dir / "source-001.tar",
    }
    content: dict[str, bytes] = {}
    for key, path in paths.items():
        try:
            content[key] = path.read_bytes()
        except OSError as exc:
            raise AdmissionError(f"V2 allowance predecessor evidence is missing: {key}") from exc
        if v3.sha256(content[key]) != predecessor[key]:
            raise AdmissionError(f"V2 allowance predecessor evidence changed: {key}")

    allowance = v3.json_object(content["allowance_sha256"].decode())
    binding = v3.json_object(content["binding_sha256"].decode())
    used = v3.json_object(content["used_sha256"].decode())
    control = v3.json_object(content["control_sha256"].decode())
    status = v3.json_object(content["status_sha256"].decode())
    cost = v3.json_object(content["cost_reconciliation_sha256"].decode())
    stop = v3.json_object(content["stop_summary_sha256"].decode())
    watchdog = v3.json_object(content["watchdog_sha256"].decode())
    ledger = v3.json_object(content["ledger_sha256"].decode())
    original = v3.json_object(content["controller_ledger_sha256"].decode())
    expected_session = f"res541-a02-v3-{plan['plan_sha256'][:8]}-001"
    teardown_receipt = control.get("teardown_receipt")
    if not isinstance(teardown_receipt, dict):
        raise AdmissionError("V2 predecessor teardown receipt is malformed")
    control_sessions = teardown_receipt.get("sessions", {})
    control_assignments = teardown_receipt.get("assignments", {})
    stop_teardown = stop.get("teardown", {})
    stop_evidence = stop.get("evidence", {})
    if not all(
        isinstance(value, dict)
        for value in (control_sessions, control_assignments, stop_teardown, stop_evidence)
    ):
        raise AdmissionError("V2 predecessor teardown receipt is malformed")
    try:
        assignment_inventory = json.loads(control_assignments.get("stdout", "{}"))
    except (json.JSONDecodeError, TypeError) as exc:
        raise AdmissionError("V2 predecessor provider-assignment receipt is malformed") from exc
    exact_delta = cost.get("exact_balance_delta_cu")
    if (
        isinstance(exact_delta, bool)
        or not isinstance(exact_delta, int | float)
        or not math.isfinite(exact_delta)
        or round(exact_delta, 4) != 0.0121
    ):
        raise AdmissionError("V2 predecessor exact cost does not reconcile to session 001")
    if (
        set(allowance) != ALLOWANCE_KEYS
        or allowance.get("schema") != ALLOWANCE_SCHEMA
        or allowance.get("plan_sha256") != plan["plan_sha256"]
        or allowance.get("source_identity") != source
        or allowance.get("max_sessions") != plan["session_count"]
        or allowance.get("cumulative_cap_cu") != plan["compute_units"]["cumulative_cap"]
        or allowance.get("max_cu_per_session") != plan["compute_units"]["per_session_cap"]
        or allowance.get("allow_concurrent_unrelated_usage") is not False
        or binding.get("schema") != "RES541_A02_V3_REMOTE_BINDING_V1"
        or binding.get("plan_sha256") != plan["plan_sha256"]
        or binding.get("source_identity") != source
        or binding.get("session_index") != 1
        or binding.get("source_archive_sha256") != predecessor["source_archive_sha256"]
        or used.get("plan_sha256") != plan["plan_sha256"]
        or used.get("source_identity") != source
        or used.get("session") != expected_session
        or used.get("index") != 1
        or status.get("status") != "EXECUTION_FAILED"
        or status.get("failure_stage") != "work"
        or status.get("error_type") != "ModuleNotFoundError"
        or status.get("error_detail") != "No module named 'scripts'"
        or status.get("binding") != binding
        or status.get("checkpoint_sha256") is not None
        or control.get("session") != used.get("session")
        or control.get("stopped") is not True
        or control.get("target_absent_after_stop") is not True
        or control.get("session-001-status.json_sha256") != predecessor["status_sha256"]
        or control.get("prepare", {}).get("returncode") != 0
        or control.get("work", {}).get("returncode") != 0
        or control.get("quota_after", {}).get("active_sessions") != []
        or control.get("quota_after", {}).get("active_assignment_count") != 0
        or control_sessions.get("returncode") != 0
        or "No active sessions found" not in control_sessions.get("stdout", "")
        or control_assignments.get("returncode") != 0
        or not isinstance(assignment_inventory, dict)
        or assignment_inventory.get("assignments") != []
        or watchdog.get("phase") != "DISARMED"
        or stop.get("campaign_status") != "STOPPED_ON_ANOMALY"
        or stop.get("source_identity") != source
        or stop.get("session", {}).get("committed_items") != 0
        or stop.get("session", {}).get("conservative_recorded_spend_cu") != 0.0121
        or stop.get("allowance", {}).get("sessions_used") != 1
        or stop.get("allowance", {}).get("sessions_remaining") != 9
        or stop.get("allowance", {}).get("conservative_spend_cu") != 0.0121
        or stop_teardown.get("controller_confirmed_absent_from_cli_and_provider") is not True
        or stop_teardown.get("independent_cli_sessions") != 0
        or stop_teardown.get("independent_provider_assignments") != 0
        or stop_teardown.get("post_teardown_usage_rate_cu_per_hour") != 0.0
        or stop_evidence.get("source_archive_matches_binding") is not True
        or stop_evidence.get("remote_status_hash_matches_control") is not True
        or cost.get("schema") != "RES541_A02_V3_SESSION_COST_RECONCILIATION_V1"
        or cost.get("source_identity") != source
        or cost.get("session_index") != 1
        or cost.get("conservative_recorded_spend_cu") != 0.0121
        or cost.get("corrected_ledger_sha256") != predecessor["ledger_sha256"]
        or cost.get("original_controller_ledger_sha256") != predecessor["controller_ledger_sha256"]
        or cost.get("remote_status_sha256") != predecessor["status_sha256"]
        or cost.get("teardown_confirmed") is not True
        or ledger.get("schema") != LEDGER_SCHEMA
        or ledger.get("plan_sha256") != plan["plan_sha256"]
        or ledger.get("source_identity") != source
        or original.get("schema") != LEDGER_SCHEMA
        or original.get("plan_sha256") != plan["plan_sha256"]
        or original.get("source_identity") != source
    ):
        raise AdmissionError("V2 allowance predecessor evidence is inconsistent")
    prior = ledger.get("sessions")
    raw = original.get("sessions")
    if (
        not isinstance(prior, list)
        or len(prior) != 1
        or prior[0].get("index") != 1
        or prior[0].get("name") != used.get("session")
        or prior[0].get("cost_status") != "KNOWN"
        or prior[0].get("compute_units_spent") != 0.0121
        or prior[0].get("committed_items") != 0
        or not isinstance(raw, list)
        or len(raw) != 1
        or raw[0].get("index") != 1
        or raw[0].get("name") != used.get("session")
        or raw[0].get("cost_status") != "KNOWN"
        or raw[0].get("compute_units_spent") != 0.0
    ):
        raise AdmissionError("V2 allowance predecessor ledger is not the consumed session 001")
    return {
        "allowance": allowance,
        "ledger": ledger,
        "cost": cost,
        "source_identity": source,
    }


def validate_allowance(plan: dict[str, Any], allowance: dict[str, Any] | None) -> dict[str, Any]:
    """Return the allowance if it is a well-formed grant that cannot exceed the plan."""
    if allowance is None:
        raise AdmissionError("no owner campaign allowance exists for this V3 plan")
    if not isinstance(allowance, dict):
        raise AdmissionError("campaign allowance is not an object")
    schema = allowance.get("schema")
    successor = schema == SUCCESSOR_ALLOWANCE_SCHEMA
    expected_keys = SUCCESSOR_ALLOWANCE_KEYS if successor else ALLOWANCE_KEYS
    if set(allowance) != expected_keys:
        raise AdmissionError("campaign allowance fields differ from the contract")
    if schema not in {ALLOWANCE_SCHEMA, SUCCESSOR_ALLOWANCE_SCHEMA}:
        raise AdmissionError("campaign allowance schema differs")
    if allowance["plan_sha256"] != plan["plan_sha256"]:
        raise AdmissionError("campaign allowance is not bound to this plan")
    if allowance["source_identity"] != source_identity():
        raise AdmissionError("campaign source identity differs from the exact clean source")
    sessions = allowance["max_sessions"]
    if (
        not isinstance(sessions, int)
        or isinstance(sessions, bool)
        or not (1 <= sessions <= plan["session_count"])
    ):
        raise AdmissionError("campaign allowance session count is outside the plan")
    for key, ceiling in (
        ("cumulative_cap_cu", plan["compute_units"]["cumulative_cap"]),
        ("max_cu_per_session", None),
    ):
        value = allowance[key]
        if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
            raise AdmissionError(f"campaign allowance {key} must be a positive number")
        if ceiling is not None and value > ceiling + 1e-9:
            raise AdmissionError(f"campaign allowance {key} exceeds the plan cap")
    if not isinstance(allowance["allow_concurrent_unrelated_usage"], bool):
        raise AdmissionError("campaign allowance concurrency flag must be boolean")
    try:
        expiry = datetime.fromisoformat(str(allowance["valid_until_utc"]))
    except ValueError as exc:
        raise AdmissionError("campaign allowance expiry is not a timestamp") from exc
    if expiry.tzinfo is None:
        raise AdmissionError("campaign allowance expiry must carry a timezone")
    if successor:
        parent = _validate_successor_predecessor(plan, allowance["predecessor"])
        if allowance["source_identity"] == parent["source_identity"]:
            raise AdmissionError("V2 successor allowance does not change the source identity")
        parent_spend = float(parent["ledger"]["sessions"][0]["compute_units_spent"])
        required_cap = round(parent_spend + plan["compute_units"]["per_session_cap"], 4)
        parent_expiry = datetime.fromisoformat(parent["allowance"]["valid_until_utc"])
        if (
            sessions != 2
            or float(allowance["max_cu_per_session"])
            != float(plan["compute_units"]["per_session_cap"])
            or float(allowance["cumulative_cap_cu"]) != required_cap
            or allowance["allow_concurrent_unrelated_usage"] is not False
            or expiry > parent_expiry
        ):
            raise AdmissionError("V2 successor allowance exceeds the one-session-002 scope")
    return allowance


def _successor_ledger(plan: dict[str, Any], allowance: dict[str, Any]) -> dict[str, Any]:
    parent = _validate_successor_predecessor(plan, allowance["predecessor"])
    prior = dict(parent["ledger"]["sessions"][0])
    prior.update(
        source_identity=parent["source_identity"],
        source_archive_sha256=allowance["predecessor"]["source_archive_sha256"],
        source_binding_sha256=allowance["predecessor"]["binding_sha256"],
    )
    return {
        "schema": SUCCESSOR_LEDGER_SCHEMA,
        "plan_sha256": plan["plan_sha256"],
        "source_identity": allowance["source_identity"],
        "predecessor": allowance["predecessor"],
        "sessions": [prior],
    }


def _validate_successor_ledger(
    plan: dict[str, Any], ledger: dict[str, Any], allowance: dict[str, Any]
) -> None:
    expected = _successor_ledger(plan, allowance)
    if not isinstance(ledger, dict) or set(ledger) != set(expected):
        raise AdmissionError("V2 successor ledger fields differ")
    sessions = ledger.get("sessions")
    if (
        ledger.get("schema") != SUCCESSOR_LEDGER_SCHEMA
        or ledger.get("plan_sha256") != plan["plan_sha256"]
        or ledger.get("source_identity") != allowance["source_identity"]
        or ledger.get("predecessor") != allowance["predecessor"]
        or not isinstance(sessions, list)
        or not 1 <= len(sessions) <= 2
        or sessions[0] != expected["sessions"][0]
    ):
        raise AdmissionError("V2 successor ledger does not preserve session 001")
    if len(sessions) == 2:
        session = sessions[1]
        if (
            not isinstance(session, dict)
            or session.get("index") != 2
            or session.get("source_identity") != allowance["source_identity"]
            or session.get("source_archive_sha256") is None
            or session.get("cost_status") not in {"KNOWN", "UNKNOWN"}
            or session.get("committed_items", -1) < 0
        ):
            raise AdmissionError("V2 successor ledger session 002 is invalid")


def _prepare_successor_ledger(
    plan: dict[str, Any], allowance: dict[str, Any], run_dir: Path
) -> Path:
    path = run_dir / "ledger-v2.json"
    if path.exists():
        ledger = v3.json_object(path.read_text(encoding="utf-8"))
        _validate_successor_ledger(plan, ledger, allowance)
        return path
    if (run_dir / "session-002-used.json").exists():
        raise AdmissionError("session 002 has a consumed marker but no V2 ledger")
    legacy = json.loads((run_dir / "ledger.json").read_text(encoding="utf-8"))
    if legacy != _validate_successor_predecessor(plan, allowance["predecessor"])["ledger"]:
        raise AdmissionError("V2 migration source ledger differs from its predecessor receipt")
    ledger = _successor_ledger(plan, allowance)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(ledger, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    _validate_successor_ledger(plan, v3.json_object(path.read_text()), allowance)
    return path


def admit(
    *,
    plan: dict[str, Any],
    ledger: dict[str, Any],
    authorization: dict[str, Any] | None,
    snapshot: dict[str, Any],
    session_index: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Pure admission decision for one session; raises AdmissionError when not admitted.

    ``authorization`` is the single campaign allowance. It authorizes every session up to its
    own limits, so no per-session ceremony is needed, but each limit is rechecked per session.
    """
    allowance = validate_allowance(plan, authorization)
    if (now or datetime.now(UTC)) >= datetime.fromisoformat(str(allowance["valid_until_utc"])):
        raise AdmissionError("campaign allowance has expired")
    if ledger.get("plan_sha256") != plan["plan_sha256"]:
        raise AdmissionError("V3 ledger is not bound to this plan")
    if ledger.get("schema") == SUCCESSOR_LEDGER_SCHEMA:
        if allowance["schema"] != SUCCESSOR_ALLOWANCE_SCHEMA:
            raise AdmissionError("V2 successor ledger requires a V2 allowance")
        _validate_successor_ledger(plan, ledger, allowance)
    elif ledger.get("schema") != LEDGER_SCHEMA:
        raise AdmissionError("V3 ledger schema differs")
    elif allowance["schema"] == SUCCESSOR_ALLOWANCE_SCHEMA:
        raise AdmissionError("V2 successor allowance requires a V2 successor ledger")
    used = ledger["sessions"]
    if [s["index"] for s in used] != list(range(1, len(used) + 1)):
        raise AdmissionError("V3 ledger session sequence is inconsistent")
    if session_index != len(used) + 1:
        raise AdmissionError("session index is not the next unused V3 session")
    if session_index > plan["session_count"]:
        raise AdmissionError("planned V3 session count is exhausted; amend the plan")
    if session_index > allowance["max_sessions"]:
        raise AdmissionError("campaign allowance session count is exhausted")
    per_session = plan["compute_units"]["per_session_cap"]
    if any(s.get("cost_status") == "UNKNOWN" for s in used):
        raise AdmissionError("a prior session has unknown cost; owner review required")
    if any(float(s["compute_units_spent"]) > per_session + 1e-9 for s in used):
        raise AdmissionError("a prior session exceeded its bounded cost; owner review required")
    spent = sum(float(s["compute_units_spent"]) for s in used)
    cap = min(plan["compute_units"]["cumulative_cap"], float(allowance["cumulative_cap_cu"]))
    if spent + per_session > cap + 1e-9:
        raise AdmissionError("cumulative V3 compute-unit cap would be exceeded")
    if float(allowance["max_cu_per_session"]) + 1e-9 < per_session:
        raise AdmissionError("allowed per-session compute units are below the plan bound")
    if snapshot["balance"] < per_session + plan["bounds"]["cost_buffer_cu"]:
        raise AdmissionError("live balance cannot cover one bounded session")
    if (
        not math.isfinite(snapshot["usage_rate_cu_per_hour"])
        or snapshot["usage_rate_cu_per_hour"] != 0
    ):
        raise AdmissionError("account is already consuming compute; usage is not attributable")
    return {
        "admitted": True,
        "spent_before": spent,
        "per_session_cap": per_session,
        "cumulative_cap": cap,
        "sessions_remaining_in_allowance": allowance["max_sessions"] - session_index,
        "unrelated_sessions": sorted(s["name"] for s in snapshot["active_sessions"]),
    }


# --------------------------------------------------------------------------- checkpoint merge


def validate_prepared_status(
    status: dict[str, Any], binding: dict[str, Any], protocol: dict[str, Any]
) -> None:
    """CLI exit zero cannot attest to a completed, bound preparation child."""
    stages = status.get("stages", [])
    if (
        status.get("binding") != binding
        or status.get("status") != "READY"
        or status.get("plan_sha256") != binding["plan_sha256"]
        or status.get("runtime_qualification", {}).get("qualified") is not True
        or len(stages) != 1
        or stages[-1].get("stage") != "prepare"
        or stages[-1].get("returncode") != 0
        or stages[-1].get("timed_out") is not False
    ):
        raise ValueError("preparation has no matching qualified READY child status")
    weights = status.get("weights", {})
    if (
        weights.get("model_revision") != protocol["candidate_model"]["revision"]
        or not weights.get("weight_files")
        or not status.get("snapshot_path")
        or any(
            weights.get("support_files", {}).get(name, {}).get("sha256") != digest
            for name, digest in v3.load_profile()["tokenizer"]["files"].items()
        )
    ):
        raise ValueError("READY preparation lacks pinned model/tokenizer verification")


def merge_checkpoint(
    local: Path,
    downloaded: Path,
    items: Sequence[worker.WorkItem],
    protocol: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Adopt a downloaded checkpoint only if it verifies and extends the local one."""
    remote_state = worker.read_checkpoint(downloaded, items)
    if protocol is not None:
        worker.check_identity(remote_state["entries"], protocol)
    local_state = worker.read_checkpoint(local, items)
    local_lines = local_state["entries"]
    remote_lines = remote_state["entries"]
    if len(remote_lines) < len(local_lines):
        raise worker.CheckpointError("downloaded checkpoint is shorter than the local evidence")
    if remote_lines[: len(local_lines)] != local_lines:
        raise worker.CheckpointError("downloaded checkpoint forks from the local evidence")
    data = downloaded.read_bytes()
    if remote_state["torn_tail_discarded"]:
        data = data[: data.rfind(b"\n") + 1]
    temporary = local.with_suffix(".merge")
    temporary.write_bytes(data)
    os.replace(temporary, local)
    return {
        "committed_before": len(local_lines),
        "committed_after": len(remote_lines),
        "torn_tail_discarded": remote_state["torn_tail_discarded"],
        "head": remote_state["head"],
    }


# --------------------------------------------------------------------------- session


class ColabClient(Protocol):
    def snapshot(self) -> dict[str, Any]: ...
    def new(self, name: str) -> bool: ...
    def hardware(self, name: str) -> str | None: ...
    def upload(self, name: str, local: Path, remote: str) -> bool: ...
    def exec_stage(self, name: str, stage: str, timeout: int) -> dict[str, Any]: ...
    def download(self, name: str, remote: str, local: Path) -> bool: ...
    def stop(self, name: str) -> bool: ...
    def sessions(self) -> list[str]: ...
    def start_watchdog(self, name: str, receipt: Path) -> Any: ...
    def finish_watchdog(self, watchdog: Any, verified: bool) -> None: ...
    def verify_absent(self, name: str, *, allocation_attempted: bool = True) -> bool: ...


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True) + "\n")


COST_POLL_SECONDS = 5


def monitored_stage(
    client: ColabClient,
    name: str,
    stage: str,
    timeout: int,
    before: dict[str, Any],
    admission: dict[str, Any],
    plan: dict[str, Any],
    initial_rate: float,
) -> dict[str, Any]:
    """V2 conservative maximum of account delta and elapsed-rate bound, with cleanup reserve."""
    halt = threading.Event()
    failures: list[str] = []
    observations: list[dict[str, Any]] = []
    started = admission.get("started_monotonic", time.monotonic())

    def monitor() -> None:
        while not halt.wait(COST_POLL_SECONDS):
            try:
                snap = client.snapshot()
                observations.append(snap)
                rate = float(snap["usage_rate_cu_per_hour"])
                delta = float(before["balance"]) - float(snap["balance"])
                if not math.isfinite(delta) or delta < 0 or rate != initial_rate or rate <= 0:
                    raise RuntimeError("live rate changed or quota attribution is unknown")
                if {row["name"] for row in snap["active_sessions"]} != {
                    row["name"] for row in before["active_sessions"]
                } | {name}:
                    raise RuntimeError("unexpected provider usage")
                upper = max(delta, rate * (time.monotonic() - started) / 3600)
                reserve = plan["bounds"]["cost_buffer_cu"] + rate * 125 / 3600
                remaining = min(
                    admission["per_session_cap"],
                    admission["cumulative_cap"] - admission["spent_before"],
                )
                if upper + reserve >= remaining:
                    raise RuntimeError("live cumulative allowance guard reached")
            except Exception as exc:
                failures.append(type(exc).__name__ + ": " + str(exc))
                try:
                    client.stop(name)
                except Exception as stop_exc:
                    failures.append(type(stop_exc).__name__)
                return

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    try:
        result = client.exec_stage(name, stage, timeout)
    finally:
        halt.set()
        thread.join(timeout=130)
    if thread.is_alive():
        raise RuntimeError("live quota monitor unresponsive")
    if failures:
        return {"returncode": None, "monitor_failure": failures, "cost_observations": observations}
    return {**result, "cost_observations": observations}


def run_session(
    *,
    client: ColabClient,
    plan: dict[str, Any],
    ledger_path: Path,
    authorization: dict[str, Any] | None,
    session_index: int,
    run_dir: Path,
    source_archive: Path,
    binding: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run one admitted session end to end; teardown is unconditional."""
    protocol = decision.load_protocol()
    items = worker.work_items(protocol)
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else ledger_new(plan)
    if authorization is not None and binding.get("source_identity") != authorization.get(
        "source_identity"
    ):
        raise AdmissionError("session binding differs from authorized source identity")
    if authorization is not None and authorization.get("schema") == SUCCESSOR_ALLOWANCE_SCHEMA:
        _validate_successor_ledger(plan, ledger, authorization)
    else:
        if ledger["sessions"] and ledger.get("source_identity") != binding.get("source_identity"):
            raise AdmissionError("ledger source identity differs")
        ledger["source_identity"] = binding.get("source_identity")
    before = client.snapshot()
    admission = admit(
        plan=plan,
        ledger=ledger,
        authorization=authorization,
        snapshot=before,
        session_index=session_index,
        now=now,
    )
    name = f"res541-a02-v3-{plan['plan_sha256'][:8]}-{session_index:03d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    marker = run_dir / f"session-{session_index:03d}-used.json"
    _write_exclusive(
        marker,
        {
            "session": name,
            "index": session_index,
            "plan_sha256": plan["plan_sha256"],
            "source_identity": validate_allowance(plan, authorization)["source_identity"],
            "recorded_at_utc": datetime.now(UTC).isoformat(),
        },
    )
    local = run_dir / "checkpoint.jsonl"
    if local.exists() and not ledger["sessions"]:
        raise AdmissionError("existing checkpoint has no source-bound session ledger")
    downloaded = run_dir / f"session-{session_index:03d}-checkpoint.jsonl"
    state: dict[str, Any] = {
        "session": name,
        "index": session_index,
        "admission": admission,
        "quota_before": before,
    }
    watchdog = None
    allocated = False
    attempted = False  # only a session this run tried to create may be stopped by this run
    state["sessions_before"] = sorted(client.sessions())
    try:
        if name in state["sessions_before"]:
            raise RuntimeError("a session with this exact V3 name already exists; refusing")
        watchdog = client.start_watchdog(
            name, run_dir / f"session-{session_index:03d}-watchdog.json"
        )
        expires = datetime.fromisoformat(
            str(validate_allowance(plan, authorization)["valid_until_utc"])
        )
        if (expires - (now or datetime.now(UTC))).total_seconds() < (
            plan["bounds"]["session_seconds"] + 90
        ):
            raise AdmissionError("owner window cannot cover allocation, watchdog and teardown")
        admission["started_monotonic"] = time.monotonic()
        attempted = True
        allocated = client.new(name)
        state["allocated"] = allocated
        if not allocated:
            raise RuntimeError("single V3 T4 allocation failed; no retry")
        if client.hardware(name) != "T4":
            raise RuntimeError("allocated V3 session is not the exact requested T4")
        after = client.snapshot()
        state["rate_after_allocation"] = after["usage_rate_cu_per_hour"]
        if (
            not math.isfinite(after["usage_rate_cu_per_hour"])
            or after["usage_rate_cu_per_hour"] <= 0
            or after["usage_rate_cu_per_hour"]
            > plan["bounds"]["admission_rate_ceiling_cu_per_hour"]
        ):
            raise RuntimeError("live T4 rate exceeds the admission ceiling; stopping at once")
        binding_path = run_dir / f"session-{session_index:03d}-binding.json"
        binding_path.write_text(json.dumps({**binding, "session_index": session_index}))
        uploads = [(source_archive, REMOTE_SOURCE), (binding_path, REMOTE_BINDING)]
        if local.exists():
            uploads.append((local, REMOTE_CHECKPOINT))
        for path, remote in uploads:
            if not client.upload(name, path, remote):
                raise RuntimeError(f"V3 upload failed: {remote}")
        bounds = plan["bounds"]
        state["prepare"] = monitored_stage(
            client,
            name,
            "prepare",
            bounds["prepare_seconds"],
            before,
            admission,
            plan,
            after["usage_rate_cu_per_hour"],
        )
        prepared_path = run_dir / f"session-{session_index:03d}-prepare-status.json"
        if not client.download(name, REMOTE_STATUS, prepared_path):
            raise RuntimeError("authenticated preparation status recovery failed; no work")
        state["prepare_status_sha256"] = v3.sha256(prepared_path.read_bytes())
        prepared = v3.json_object(prepared_path.read_text())
        state["prepare_status"] = prepared
        if state["prepare"].get("returncode") != 0 or state["prepare"].get("timed_out"):
            raise RuntimeError("preparation transport or CLI failed; no work")
        validate_prepared_status(prepared, {**binding, "session_index": session_index}, protocol)
        if prepared.get("checkpoint_sha256") != (
            v3.sha256(local.read_bytes()) if local.exists() else None
        ):
            raise RuntimeError("prepared checkpoint differs from uploaded prefix; no work")
        if state["prepare"].get("returncode") == 0:
            mid = client.snapshot()
            state["rate_before_work"] = mid["usage_rate_cu_per_hour"]
            if mid["usage_rate_cu_per_hour"] > bounds["admission_rate_ceiling_cu_per_hour"]:
                raise RuntimeError("live T4 rate rose above the admission ceiling; no work stage")
            if mid["usage_rate_cu_per_hour"] != after["usage_rate_cu_per_hour"]:
                raise RuntimeError("unsupported live rate change before work")
            if (
                float(before["balance"]) - float(mid["balance"])
                > plan["compute_units"]["per_session_cap"]
            ):
                raise RuntimeError("session spend already exceeds its bound; no work stage")
            work_timeout = min(
                bounds["exec_seconds"] - bounds["prepare_seconds"],
                math.floor(
                    bounds["exec_seconds"]
                    - (time.monotonic() - admission["started_monotonic"])
                    - 30
                ),
            )
            committed = (
                len(worker.read_checkpoint(local, items)["entries"]) if local.exists() else 0
            )
            next_item = items[committed]
            item_kind = "QUALIFICATION" if next_item.key == "QUALIFICATION" else next_item.arm
            if work_timeout <= (
                bounds["inference_overhead_seconds"]
                + bounds["worker_margin_seconds"]
                + plan["item_cost_bounds_seconds"][item_kind]
            ):
                raise RuntimeError("insufficient remaining work-stage time; no work")
            state["work"] = monitored_stage(
                client,
                name,
                "work",
                work_timeout,
                before,
                admission,
                plan,
                after["usage_rate_cu_per_hour"],
            )
    except Exception as exc:  # recorded; teardown and evidence recovery still run
        state["failure"] = f"{type(exc).__name__}: {exc}"
    finally:
        if allocated:
            status_path = run_dir / f"session-{session_index:03d}-status.json"
            recovered = {}
            for remote, path in ((REMOTE_STATUS, status_path), (REMOTE_CHECKPOINT, downloaded)):
                try:
                    recovered[remote] = client.download(name, remote, path)
                    if recovered[remote]:
                        state[path.name + "_sha256"] = v3.sha256(path.read_bytes())
                except Exception as exc:
                    recovered[remote] = False
                    state[path.name + "_error"] = type(exc).__name__
            try:
                if not recovered.get(REMOTE_STATUS):
                    raise ValueError("remote status missing")
                status = v3.json_object(status_path.read_text())
                if status.get("binding") != {**binding, "session_index": session_index}:
                    raise ValueError("remote status source/session binding differs")
                digest = (
                    v3.sha256(downloaded.read_bytes()) if recovered.get(REMOTE_CHECKPOINT) else None
                )
                if status.get("checkpoint_sha256") != digest:
                    raise ValueError("remote status/checkpoint digest differs")
                if state.get("work", {}).get("returncode") == 0 and (
                    status.get("status") != "READY"
                    or status.get("runtime_qualification", {}).get("qualified") is not True
                ):
                    raise ValueError("successful work has no qualified READY runtime status")
                if binding.get("precision") == "float32":
                    audit = status.get("precision_audit", {})
                    if (
                        audit.get("parameter_dtypes") != ["torch.float32"]
                        or audit.get("selected_precision") != "float32"
                    ):
                        raise ValueError("FP32 work has no actual parameter precision evidence")
                    if audit.get("executed_forwards") is not False and (
                        audit.get("intermediate_dtypes") != ["torch.float32"]
                        or audit.get("logit_dtypes") != ["torch.float32"]
                    ):
                        raise ValueError(
                            "FP32 work has mixed or missing intermediate/logit evidence"
                        )
                state["remote_status"] = status
                if recovered.get(REMOTE_CHECKPOINT):
                    state["merge"] = merge_checkpoint(local, downloaded, items, protocol)
                else:
                    state["merge"] = "EVIDENCE_NOT_RETRIEVED"
            except Exception as exc:
                state["merge"] = f"REJECTED: {exc}"
        state["stopped"] = False
        state["target_absent_after_stop"] = False
        state["unrelated_sessions_after"] = []
        for label, operation in (
            ("stopped", lambda: client.stop(name) if attempted else False),
            (
                "target_absent_after_stop",
                lambda: (attempted or watchdog is not None)
                and client.verify_absent(name, allocation_attempted=attempted),
            ),
            ("unrelated_sessions_after", lambda: sorted(s for s in client.sessions() if s != name)),
        ):
            try:
                state[label] = operation()
            except Exception as exc:
                state[label + "_error"] = type(exc).__name__
        state["teardown_receipt"] = getattr(client, "teardown_receipt", None)
        if watchdog is not None:
            try:
                client.finish_watchdog(watchdog, state["target_absent_after_stop"] is True)
            except Exception as exc:
                state["watchdog_error"] = type(exc).__name__
        spent: float | None = None
        try:
            end = client.snapshot()
            state["quota_after"] = end
            if not state["target_absent_after_stop"]:
                raise ValueError("exact-target teardown is not confirmed; ending quota unknown")
            spent = float(before["balance"]) - float(end["balance"])
            if not math.isfinite(spent) or spent < 0:
                raise ValueError("untrustworthy ending balance")
        except Exception as exc:
            state["failure"] = (
                (
                    "exact-target teardown is not confirmed; "
                    if not state["target_absent_after_stop"]
                    else ""
                )
                + "ending quota unknown: "
                + type(exc).__name__
            )
            spent = None
        ledger_session = {
            "index": session_index,
            "name": name,
            "compute_units_spent": round(spent, 4) if spent is not None else None,
            "cost_status": "KNOWN" if spent is not None else "UNKNOWN",
            "committed_items": len(worker.read_checkpoint(local, items)["entries"])
            if local.exists()
            else 0,
        }
        if ledger.get("schema") == SUCCESSOR_LEDGER_SCHEMA:
            ledger_session.update(
                source_identity=binding["source_identity"],
                source_archive_sha256=binding["source_archive_sha256"],
            )
        ledger["sessions"].append(ledger_session)
        temporary = ledger_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n")
        os.replace(temporary, ledger_path)
        (run_dir / f"session-{session_index:03d}-control.json").write_text(
            json.dumps(state, indent=2, sort_keys=True, default=str) + "\n"
        )
    return state


# --------------------------------------------------------------------------- campaign


def session_anomaly(
    state: dict[str, Any], committed_before: int, committed_after: int, per_session_cap: float
) -> str | None:
    """Why a finished session is not a clean step, or None. Any anomaly ends the campaign."""
    if "failure" in state:
        return f"session failure: {state['failure']}"
    if "watchdog_error" in state:
        return "independent watchdog disarm receipt is not confirmed"
    work = state.get("work")
    if not isinstance(work, dict) or work.get("timed_out") or work.get("returncode") != 0:
        return "work stage did not finish cleanly"
    if not isinstance(state.get("merge"), dict):
        return f"evidence was not adopted: {state.get('merge')}"
    if state["merge"].get("torn_tail_discarded"):
        return "downloaded evidence ended in an interrupted write"
    if not state.get("stopped") or not state.get("target_absent_after_stop"):
        return "exact-target teardown is not confirmed"
    if state["unrelated_sessions_after"] != state["sessions_before"]:
        return "the set of unrelated sessions changed during this session"
    if committed_after <= committed_before:
        return "session committed no new evidence"
    if state.get("compute_units_spent", 0.0) > per_session_cap + 1e-9:
        return "session cost exceeded its bound"
    return None


def run_campaign(
    *,
    client: ColabClient,
    plan: dict[str, Any],
    ledger_path: Path,
    authorization: dict[str, Any] | None,
    run_dir: Path,
    source_archive: Path,
    binding: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run sessions back to back under one allowance until complete or the first anomaly.

    No session is ever retried: after an anomaly the campaign returns and a human decides
    whether a new invocation is justified. A normal step is a session that ends cleanly and
    commits new evidence; the worker's deadline, not the controller, decides where it stops.
    """
    validate_allowance(plan, authorization)
    protocol = decision.load_protocol()
    items = worker.work_items(protocol)
    local = run_dir / "checkpoint.jsonl"

    def committed() -> int:
        return len(worker.read_checkpoint(local, items)["entries"]) if local.exists() else 0

    sessions: list[dict[str, Any]] = []
    while True:
        before = committed()
        if before == len(items):
            # Complete work cannot erase a previous cost or teardown anomaly on re-entry.
            try:
                ledger = json.loads(ledger_path.read_text())
                if ledger.get("source_identity") != binding.get("source_identity"):
                    raise ValueError("complete checkpoint has a different source ledger")
                last = ledger["sessions"][-1]
                receipt = run_dir / f"session-{last['index']:03d}-control.json"
                final = json.loads(receipt.read_text())
                final["compute_units_spent"] = last["compute_units_spent"]
                problem = session_anomaly(
                    final,
                    final.get("merge", {}).get("committed_before", before),
                    before,
                    plan["compute_units"]["per_session_cap"],
                )
            except Exception as exc:
                problem = "completion receipt is untrustworthy: " + type(exc).__name__
            if problem:
                return {
                    "status": "STOPPED_ON_ANOMALY",
                    "anomaly": problem,
                    "committed": before,
                    "sessions": sessions,
                }
            return {"status": "COMPLETE", "committed": before, "sessions": sessions}
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else ledger_new(plan)
        index = len(ledger["sessions"]) + 1
        try:
            state = run_session(
                client=client,
                plan=plan,
                ledger_path=ledger_path,
                authorization=authorization,
                session_index=index,
                run_dir=run_dir,
                source_archive=source_archive,
                binding=binding,
                now=now,
            )
        except AdmissionError as exc:
            return {
                "status": "NOT_ADMITTED",
                "reason": str(exc),
                "committed": before,
                "sessions": sessions,
            }
        after = committed()
        state["compute_units_spent"] = json.loads(ledger_path.read_text())["sessions"][-1][
            "compute_units_spent"
        ]
        sessions.append({"index": index, "committed_before": before, "committed_after": after})
        problem = session_anomaly(state, before, after, plan["compute_units"]["per_session_cap"])
        if problem:
            return {
                "status": "STOPPED_ON_ANOMALY",
                "anomaly": problem,
                "committed": after,
                "sessions": sessions,
            }


# --------------------------------------------------------------------------- CLI


class ColabCLI:  # pragma: no cover - provider commands, used only in an authorized session
    """The reviewed V2 Colab CLI command forms."""

    def __init__(self) -> None:
        from scripts import a02_dev_execution, a02_execution

        self._run = a02_dev_execution._run_colab
        self._snapshot = a02_dev_execution._colab_snapshot
        self._rows = a02_execution._session_rows
        self._timeouts = a02_execution
        self.target_endpoint: str | None = None

    def start_watchdog(self, name: str, receipt: Path) -> Any:
        command = [
            sys.executable,
            "-m",
            getattr(self, "watchdog_module", "scripts.a02_v3_execution"),
            "watchdog",
            name,
            str(receipt),
        ]
        seconds = getattr(self, "watchdog_seconds", None)
        if seconds is not None:
            command.append(str(seconds))
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=self._timeouts.clean_colab_env(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )
        if process.stdout is None:
            raise RuntimeError("watchdog readiness pipe unavailable")
        ready, _, _ = select.select([process.stdout], [], [], 10)
        if not ready or process.stdout.readline().strip() != "READY":
            if process.stdin is not None:
                process.stdin.close()
            raise RuntimeError("watchdog not READY; no allocation")
        if json.loads(receipt.read_text()).get("phase") != "READY":
            if process.stdin is not None:
                process.stdin.close()
            raise RuntimeError("independent watchdog receipt missing")
        return process, receipt

    def finish_watchdog(self, watchdog: Any, verified: bool) -> None:
        process, receipt = watchdog
        if process.stdin is not None:
            if verified:
                process.stdin.write("D")
                process.stdin.flush()
            process.stdin.close()
        if verified:
            process.wait(timeout=10)
            if json.loads(receipt.read_text()).get("phase") != "DISARMED":
                raise RuntimeError("independent watchdog disarm receipt missing")

    def verify_absent(self, name: str, *, allocation_attempted: bool = True) -> bool:
        self.teardown_receipt: dict[str, Any] = {}
        results = {}
        commands: tuple[tuple[str, Callable[[], list[str]]], ...] = (
            ("sessions", lambda: ["colab", "--auth=oauth2", "sessions"]),
            ("assignments", self._timeouts._assignment_command),
        )
        for label, command in commands:
            try:
                result = self._run(command(), timeout=30)
                results[label] = result
                self.teardown_receipt[label] = {
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "sha256": v3.sha256(result.stdout.encode()),
                }
            except Exception as exc:
                self.teardown_receipt[label] = {"error_type": type(exc).__name__}
        if set(results) != {"sessions", "assignments"}:
            return False
        if not allocation_attempted:
            # No POST was issued, so there is no target endpoint to bind. Both inventories
            # must agree and prove the reserved session name absent before watchdog disarm.
            if any(result.returncode != 0 or result.stderr for result in results.values()):
                return False
            sessions = self._timeouts._session_rows(results["sessions"].stdout)
            assignments = self._timeouts._parse_assignments(results["assignments"].stdout)
            return bool(
                {row[1] for row in sessions} == {row["endpoint"] for row in assignments}
                and not any(row[0] == name for row in sessions)
            )
        return bool(
            self._timeouts._verify_target_absent(
                results["sessions"], name, self.target_endpoint, results["assignments"]
            )
        )

    def snapshot(self) -> dict[str, Any]:
        snap: dict[str, Any] = self._snapshot()
        return snap

    def new(self, name: str) -> bool:
        command = ["colab", "--auth=oauth2", "new", "--session", name, "--gpu", "T4"]
        return self._run(command, timeout=self._timeouts.NEW_TIMEOUT_SECONDS).returncode == 0

    def hardware(self, name: str) -> str | None:
        out = self._run(["colab", "--auth=oauth2", "status", "--session", name], timeout=30)
        rows = [row for row in self._rows(out.stdout) if row[0] == name]
        self.target_endpoint = rows[0][1] if len(rows) == 1 else None
        return rows[0][2].upper() if len(rows) == 1 else None

    def upload(self, name: str, local: Path, remote: str) -> bool:
        command = ["colab", "--auth=oauth2", "upload", "--session", name, str(local), remote]
        return self._run(command, timeout=self._timeouts.UPLOAD_TIMEOUT_SECONDS).returncode == 0

    def exec_stage(self, name: str, stage: str, timeout: int) -> dict[str, Any]:
        from scripts.a02_dev_execution import ColabCommandError, _safe_command_excerpt

        command = [
            "colab", "--auth=oauth2", "exec", "--session", name,
            "--env", f"A02_V3_REMOTE_STAGE={stage}",
            "--env", f"A02_V3_REMOTE_STAGE_TIMEOUT={timeout}",
            "--file", str(ROOT / "scripts/a02_v3_remote.py"),
            "--timeout", str(timeout),
        ]  # fmt: skip
        try:
            result = self._run(command, timeout=timeout + 30)
        except ColabCommandError as exc:
            return {
                "returncode": None,
                "timed_out": exc.timed_out,
                "failure_category": "CLI_TRANSPORT_TIMEOUT"
                if exc.timed_out
                else "CLI_TRANSPORT_START_FAILURE",
                "stdout_tail": exc.stdout_tail,
                "stderr_tail": exc.stderr_tail,
            }
        return {
            "returncode": result.returncode,
            "timed_out": False,
            "failure_category": "CLI_OR_TRANSPORT_EXIT" if result.returncode else None,
            "stdout_tail": _safe_command_excerpt(result.stdout),
            "stderr_tail": _safe_command_excerpt(result.stderr),
        }

    def download(self, name: str, remote: str, local: Path) -> bool:
        command = ["colab", "--auth=oauth2", "download", "--session", name, remote, str(local)]
        return self._run(command, timeout=self._timeouts.DOWNLOAD_TIMEOUT_SECONDS).returncode == 0

    def stop(self, name: str) -> bool:
        command = ["colab", "--auth=oauth2", "stop", "--session", name]
        return self._run(command, timeout=self._timeouts.STOP_TIMEOUT_SECONDS).returncode == 0

    def sessions(self) -> list[str]:
        out = self._run(["colab", "--auth=oauth2", "sessions"], timeout=30)
        if out.returncode != 0 or out.stderr:
            raise RuntimeError("session inventory failed")
        return [row[0] for row in self._rows(out.stdout)]


def source_identity() -> dict[str, str]:
    """External authorization freezes source, including runtime and dependency policy bytes."""
    dirty = subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=ROOT, text=True)
    if dirty.strip():
        raise AdmissionError("V3 sessions require the exact clean committed source")
    return {
        key: subprocess.check_output(["git", "rev-parse", ref], cwd=ROOT, text=True).strip()
        for key, ref in (("commit", "HEAD"), ("tree", "HEAD^{tree}"))
    }


def source_archive(path: Path) -> tuple[Path, str]:
    """git archive of the exact clean committed HEAD."""
    dirty = subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=ROOT, text=True)
    if dirty.strip():
        raise AdmissionError("V3 sessions require the exact clean committed source")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    subprocess.run(
        ["git", "archive", "--format=tar", f"--output={path}", head], cwd=ROOT, check=True
    )
    return path, head


def remote_binding(
    plan: dict[str, Any],
    archive: Path,
    revision: str,
    *,
    precision: str = "float16",
    native_cache: bool = False,
) -> dict[str, Any]:
    """The binding the remote bootstrap verifies (session_index is added per session)."""
    if precision not in {"float16", "float32"}:
        raise ValueError("campaign precision must be float16 or float32")
    if native_cache and precision != "float32":
        raise ValueError("prospective native cache policy requires A1 FP32")
    binding = {
        "schema": "RES541_A02_V3_REMOTE_BINDING_V1",
        "source_archive_sha256": v3.sha256(archive.read_bytes()),
        "source_revision": revision,
        "source_identity": source_identity(),
        "plan_sha256": plan["plan_sha256"],
        "protocol_sha256": plan["protocol_sha256"],
        "item_cost_bounds": plan["item_cost_bounds_seconds"],
    }
    if precision == "float32":
        from scripts.a02_v3_gpu_diagnostic import AMENDMENT

        binding.update(
            schema="RES541_A1_FP32_CAMPAIGN_REMOTE_BINDING_V1",
            precision="float32",
            numerical_amendment_sha256=v3.sha256(AMENDMENT.read_bytes()),
        )
        if native_cache:
            binding.update(
                schema="RES541_A1_NATIVE_CACHE_CAMPAIGN_REMOTE_BINDING_V1", native_cache=True
            )
    return binding


def _load_preflight(path: Path) -> dict[str, Any]:
    value = v3.json_object(path.read_text(encoding="utf-8"))
    if value.get("schema") != "RES541_A02_V3_CPU_PREFLIGHT_V1":
        raise ValueError("V3 preflight receipt schema differs")
    if value.get("gpu_allocated") is not False or value.get("weights_loaded") is not False:
        raise ValueError("V3 preflight receipt is not CPU-only")
    if value.get("profile_sha256") != v3.sha256(v3.PROFILE_PATH.read_bytes()):
        raise ValueError("V3 preflight receipt was made for a different contract profile")
    return value


def main() -> int:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan_cmd = sub.add_parser("plan", help="print the session plan using a live read-only snapshot")
    plan_cmd.add_argument("--preflight", type=Path, required=True)
    plan_cmd.add_argument("--offline", action="store_true", help="skip the live quota snapshot")
    run_cmd = sub.add_parser("run-session", help="run the next session under the allowance")
    run_cmd.add_argument("--preflight", type=Path, required=True)
    camp_cmd = sub.add_parser(
        "run-campaign", help="run sessions under the allowance until done or the first anomaly"
    )
    camp_cmd.add_argument("--preflight", type=Path, required=True)
    args = parser.parse_args()
    protocol = decision.load_protocol()
    preflight = _load_preflight(args.preflight)
    if args.command == "plan":
        rate = None if args.offline else ColabCLI().snapshot()["usage_rate_cu_per_hour"]
        print(
            json.dumps(
                build_plan(protocol, preflight, RuntimeBounds(), live_rate_cu_per_hour=rate),
                indent=2,
            )
        )
        return 0
    plan = build_plan(protocol, preflight, RuntimeBounds())
    successor_path = V3_DIR / "campaign-allowance-v2.json"
    path = successor_path if successor_path.exists() else V3_DIR / "campaign-allowance.json"
    allowance = json.loads(path.read_text()) if path.exists() else None
    validate_allowance(plan, allowance)
    run_dir = V3_DIR / f"plan-{plan['plan_sha256'][:12]}"
    run_dir.mkdir(parents=True, exist_ok=True)
    if allowance is not None and allowance["schema"] == SUCCESSOR_ALLOWANCE_SCHEMA:
        if args.command != "run-session":
            raise AdmissionError("V2 successor allowance permits only one explicit run-session")
        ledger_path = _prepare_successor_ledger(plan, allowance, run_dir)
    else:
        ledger_path = run_dir / "ledger.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else ledger_new(plan)
    session_index = len(ledger["sessions"]) + 1
    if allowance is not None and session_index > allowance["max_sessions"]:
        raise AdmissionError("campaign allowance session count is exhausted")
    archive, revision = source_archive(run_dir / f"source-{len(ledger['sessions']) + 1:03d}.tar")
    common: dict[str, Any] = {
        "client": ColabCLI(),
        "plan": plan,
        "ledger_path": ledger_path,
        "authorization": allowance,
        "run_dir": run_dir,
        "source_archive": archive,
        "binding": remote_binding(plan, archive, revision),
    }
    if args.command == "run-campaign":
        result = run_campaign(**common)
    else:
        result = run_session(session_index=session_index, **common)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    if len(sys.argv) == 4 and sys.argv[1] == "watchdog":
        from scripts.a02_execution import _watchdog

        receipt = Path(sys.argv[3])
        receipt.write_text(json.dumps({"session": sys.argv[2], "phase": "READY"}))
        _watchdog(sys.argv[2], receipt)
        if json.loads(receipt.read_text()).get("phase") == "READY":
            receipt.write_text(json.dumps({"session": sys.argv[2], "phase": "DISARMED"}))
    else:
        raise SystemExit(main())
