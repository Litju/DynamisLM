"""Source-bound one-shot A1 T4 diagnostic; never evaluates scientific work items (RES-541)."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from scripts import a02_v3_contract as v3
from scripts import a02_v3_decision as decision
from scripts import a02_v3_numerics as numerics
from scripts import a02_v3_precision as precision
from scripts import a02_v3_worker as worker

SCHEMA = "RES541_A1_T4_DIAGNOSTIC_V1"
AMENDMENT = v3.ROOT / "experiments/a02/numerical-amendment-a1.md"
HISTORICAL_CU = 0.2537
MAX_NEW_CU = 0.26
# Independent watchdog stops at 600 s; reserve covers inventory/stop latency and rate uncertainty.
WALL_SECONDS = 600
STOP_RESERVE_SECONDS = 90
RATE_CEILING = 1.25
RESERVE_CU = 0.02


def specification(*, delegated: bool = False) -> dict[str, Any]:
    value = {
        "schema": SCHEMA,
        "precision": "float32",
        "protocol_sha256": decision.protocol_sha256(),
        "amendment_sha256": v3.sha256(AMENDMENT.read_bytes()),
        "candidate_model": decision.load_protocol()["candidate_model"],
        "calibration_indices": list(worker.CALIBRATION_INDICES),
        "tolerance_nats": worker.QUALIFICATION_TOLERANCE_NATS,
        "minimum_free_bytes_before_load": 13 * 2**30,
        "wall_seconds": WALL_SECONDS,
        "stop_reserve_seconds": STOP_RESERVE_SECONDS,
        "rate_ceiling_cu_per_hour": RATE_CEILING,
        "reserve_cu": RESERVE_CU,
        "maximum_new_cu": MAX_NEW_CU,
        "historical_cu": HISTORICAL_CU,
        "retry": False,
        "scientific_evaluations": 0,
    }

    if delegated:
        value.update(
            pricing_policy="OBSERVE_BEFORE_MODEL_LOAD",
            operational_amendment_sha256=v3.sha256(
                (v3.ROOT / "experiments/a02/owner-delegated-execution-v1.md").read_bytes()
            ),
            owner_delegated_total_new_cu=50.0,
            maximum_new_cu=3.0,
            wall_seconds=1800,
            rate_ceiling_cu_per_hour=4.0,
            reserve_cu=0.05,
            startup_allowance_cu=0.15,
        )
    return value


def validate_specification(value: dict[str, Any]) -> None:
    if value != specification(delegated="pricing_policy" in value):
        raise ValueError("diagnostic specification differs from exact source")


def bounded_cost(
    rate: float, startup_cu: float = 0.0, *, spec: dict[str, Any] | None = None
) -> float:
    if not math.isfinite(rate) or rate <= 0 or not math.isfinite(startup_cu) or startup_cu < 0:
        raise ValueError("live rate/startup charge must be finite and known")
    spec = specification() if spec is None else spec
    validate_specification(spec)
    cost: float = (
        rate * (spec["wall_seconds"] + spec["stop_reserve_seconds"]) / 3600
        + startup_cu
        + spec["reserve_cu"]
    )
    if rate > spec["rate_ceiling_cu_per_hour"] or cost > spec["maximum_new_cu"]:
        raise ValueError(
            f"{spec['maximum_new_cu']} CU insufficient or rate outside admission ceiling: "
            f"{cost:.6f} CU"
        )
    return cost


def memory(torch: Any) -> dict[str, int]:
    free, total = torch.cuda.mem_get_info(0)
    return {
        "free_bytes": int(free),
        "total_bytes": int(total),
        "allocated_bytes": int(torch.cuda.memory_allocated(0)),
        "reserved_bytes": int(torch.cuda.memory_reserved(0)),
        "peak_allocated_bytes": int(torch.cuda.max_memory_allocated(0)),
        "peak_reserved_bytes": int(torch.cuda.max_memory_reserved(0)),
    }


def validate_candidate(candidate: dict[str, Any]) -> None:
    if (
        not candidate["targets_match"]
        or not candidate["cache_state_consistent"]
        or candidate["c_call"]["kv_dtype"] != "torch.float32"
        or any(step["kv_dtype"] != "torch.float32" for step in candidate["path_states"]["B"])
    ):
        raise ValueError("scored targets/cache state/precision differ")
    for name in ("A_vs_B", "B_vs_C", "A_vs_C"):
        difference = candidate[name]["abs_sum_difference"]
        if (
            not math.isfinite(difference)
            or difference < 0
            or difference > worker.QUALIFICATION_TOLERANCE_NATS
        ):
            raise ValueError("FP32 numerical qualification failed; stop without retry")


def validate_row(row: dict[str, Any]) -> None:
    if (
        row["complete"] is not True
        or row["winners_agree"] is not True
        or not row["candidates"]
        or len(row["candidates"]) != row["scorer_calls"]
    ):
        raise ValueError("incomplete diagnostic or candidate ranking disagreement")
    for candidate in row["candidates"]:
        validate_candidate(candidate)
    for name in ("A_vs_B", "B_vs_C", "A_vs_C"):
        pair = row["summary"][name]
        difference = pair["max_abs_score_difference"]
        if (
            not math.isfinite(difference)
            or difference < 0
            or difference > worker.QUALIFICATION_TOLERANCE_NATS
            or pair["candidates_above_tolerance"] != 0
        ):
            raise ValueError("FP32 numerical qualification failed; stop without retry")


def campaign_estimate(
    rows: list[dict[str, Any]],
    native: dict[str, Any],
    overhead: float,
    *,
    rate_ceiling: float = RATE_CEILING,
) -> dict[str, Any]:
    """Planning only: measured FP32 calibration; pack the frozen 581-item order."""
    if (
        not rows
        or not native["tokens"]
        or overhead < 0
        or not math.isfinite(rate_ceiling)
        or rate_ceiling <= 0
    ):
        raise ValueError("complete measured FP32 throughput and initialization are required")
    from scripts import a02_execution
    from scripts.a02_v3_execution import RuntimeBounds, workload_scorer_calls

    protocol = decision.load_protocol()
    items = worker.work_items(protocol)
    cap = v3.load_profile()["decoding"]["action_max_new_tokens"]
    maximum_calls = workload_scorer_calls(protocol)
    cached = [r["timing_seconds"]["C"] / r["scorer_calls"] for r in rows]
    uncached = [r["timing_seconds"]["A"] / r["scorer_calls"] for r in rows]
    qualification = sum(r["timing_seconds"]["A"] + r["timing_seconds"]["C"] for r in rows)
    expected = {
        "QUALIFICATION": qualification,
        "ZERO_SHOT_UNCONSTRAINED": native["seconds"],
        "ZERO_SHOT_CONSTRAINED": sum(r["timing_seconds"]["C"] for r in rows) / len(rows),
    }
    conservative = {
        "QUALIFICATION": 3 * maximum_calls * (max(cached) + max(uncached)) * 2,
        "ZERO_SHOT_UNCONSTRAINED": native["seconds"] / native["tokens"] * cap * 2,
        "ZERO_SHOT_CONSTRAINED": max(cached) * maximum_calls * 2,
    }
    window = RuntimeBounds().session_seconds
    conservative_recovery = (
        2 * a02_execution.DOWNLOAD_TIMEOUT_SECONDS
        + a02_execution.STOP_TIMEOUT_SECONDS
        + 2 * a02_execution.VERIFY_TIMEOUT_SECONDS
        + 30
    )
    result: dict[str, Any] = {
        "basis": "FP32 calibration extrapolation; conservative uses 2x slowest rate",
        "distribution": {"qualification": 1, "unconstrained": 290, "constrained": 290},
        "initialization_seconds_per_session": overhead,
        "expected_recovery_teardown_seconds_per_session": STOP_RESERVE_SECONDS,
        "conservative_recovery_teardown_seconds_per_session": conservative_recovery,
        "operational_margin_seconds_per_session": 30,
        "hypothetical_campaign_session_seconds": window,
        "campaign_authorized": False,
    }
    for label, costs in (("expected", expected), ("conservative", conservative)):
        recovery = STOP_RESERVE_SECONDS if label == "expected" else conservative_recovery
        usable = window - recovery - overhead - 30
        if usable <= 0 or any(cost > usable for cost in costs.values()):
            result[label] = {
                "fits": False,
                "item_cost_seconds": costs,
                "reason": "item cannot fit hypothetical campaign session",
            }
            continue
        used, sessions, work = 0.0, 1, 0.0
        for item in items:
            cost = costs["QUALIFICATION" if item.key == "QUALIFICATION" else item.arm]
            if used + cost > usable:
                sessions += 1
                used = 0.0
            used += cost
            work += cost
        elapsed = work + sessions * (overhead + recovery + 30)
        result[label] = {
            "fits": True,
            "packed_sessions": sessions,
            "maximum_sessions_with_reserve": sessions + 1,
            "work_seconds": work,
            "expected_elapsed_seconds": elapsed,
            "cu_at_rate_ceiling": elapsed * rate_ceiling / 3600 + sessions * RESERVE_CU,
            "maximum_cu_with_reserve": (sessions + 1) * (window * rate_ceiling / 3600 + RESERVE_CU),
            "startup_charges": "additional per-session minimum, if any; must be reverified",
            "item_cost_seconds": costs,
        }
    return result


def run(
    snapshot: Path,
    *,
    deadline: float,
    emit: Callable[[dict[str, Any]], None],
    prepare_seconds: float,
    diagnostic_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One pinned-model load, TRAIN-only A/B/C diagnostics, no retry or scientific checkpoint."""
    import torch  # type: ignore[import-not-found]
    from transformers import AutoTokenizer  # type: ignore[import-not-found]

    diagnostic_spec = specification() if diagnostic_spec is None else diagnostic_spec
    validate_specification(diagnostic_spec)

    def check() -> None:
        if time.monotonic() >= deadline:
            raise TimeoutError("diagnostic work deadline reached; no retry")

    def progress(value: dict[str, Any]) -> None:
        emit(value)
        if value.get("phase") in {"PATH_A", "PATH_C"} and any(
            not math.isfinite(score) for score in value["token_logprobs"]
        ):
            raise ValueError("non-finite likelihood; stop without retry")
        if value.get("phase") == "CANDIDATE_COMPLETE":
            validate_candidate(value)

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "specification": diagnostic_spec,
        "rows": [],
        "passed": False,
        "scientific_evaluations": 0,
    }
    audit = None
    try:
        if torch.cuda.device_count() != 1 or torch.cuda.get_device_name(0) != "Tesla T4":
            raise ValueError("diagnostic requires exactly one Tesla T4")
        torch.cuda.reset_peak_memory_stats(0)
        report["before_load_memory"] = memory(torch)
        emit({"phase": "BEFORE_LOAD", **report})
        if (
            report["before_load_memory"]["free_bytes"]
            < diagnostic_spec["minimum_free_bytes_before_load"]
        ):
            raise ValueError("less than 13 GiB free before FP32 load; no allocation probe")
        check()
        started = time.monotonic()
        model = precision.load_model(snapshot, "float32")
        torch.cuda.synchronize(0)
        report["load_seconds"] = time.monotonic() - started
        report["loaded_memory"] = memory(torch)
        audit = precision.PrecisionAudit(model, "float32")
        report["runtime"] = numerics.runtime_identity(model)
        tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True)
        report["model_identity"] = decision.load_protocol()["candidate_model"]
        emit({"phase": "LOADED", **report})
        protocol = decision.load_protocol()
        for example in worker.calibration_examples(protocol):
            check()
            request = example["request"]
            prompt = v3.build_action_prompt(tokenizer, request)
            if prompt["prompt_tokens"] > v3.load_profile()["decoding"]["action_max_prompt_tokens"]:
                raise ValueError("calibration exceeds frozen prompt limit")
            row = numerics.three_path(
                model=model,
                request=request,
                prompt_ids=prompt["prompt_token_ids"],
                encode=lambda text: list(tokenizer.encode(text, add_special_tokens=False)),
                before_call=check,
                emit=progress,
                trace_layers=not report["rows"],
            )
            row["example_id"] = decision.example_id(example)
            row["rendered_prompt_sha256"] = prompt["rendered_prompt_sha256"]
            row["memory"] = memory(torch)
            report["rows"].append(row)
            report["precision_audit"] = audit.report()
            emit({"phase": "CALIBRATION_COMPLETE", **report})
            validate_row(row)
        check()
        # Calibration timing only, never score or count its generated answer as a task result.
        started = time.monotonic()
        ids, _, truncated = worker.HFWorkerBackend(
            model, tokenizer, protocol["candidate_model"]
        ).generate_native(
            prompt["prompt_token_ids"], v3.load_profile()["decoding"]["action_max_new_tokens"]
        )
        torch.cuda.synchronize(0)
        report["native_calibration_timing"] = {
            "tokens": len(ids),
            "seconds": time.monotonic() - started,
            "truncated": truncated,
        }
        check()
        report["campaign_estimate"] = campaign_estimate(
            report["rows"],
            report["native_calibration_timing"],
            prepare_seconds + report["load_seconds"],
            rate_ceiling=diagnostic_spec["rate_ceiling_cu_per_hour"],
        )
        report["precision_audit"] = audit.report()
        report["passed"] = True
    except Exception as exc:
        report.update(error_type=type(exc).__name__, error_detail=str(exc)[:1000])
    finally:
        if audit is not None:
            audit.close()
        if torch.cuda.is_available():
            report["final_memory"] = memory(torch)
        emit({"phase": "FINAL", **report})
    return report
