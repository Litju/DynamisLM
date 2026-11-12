"""Finite owner gate and exact-target controller for the A1 diagnostic (RES-541)."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from scripts import a02_v3_contract as v3
from scripts import a02_v3_execution as execution
from scripts import a02_v3_gpu_diagnostic as diagnostic

REMOTE_REPORT = "/content/a02-v3-diagnostic.jsonl"
PROPOSAL_SCHEMA = "RES541_A1_DIAGNOSTIC_PROPOSAL_V1"
AUTH_SCHEMA = "RES541_A1_DIAGNOSTIC_OWNER_APPROVAL_V1"
ROOT = execution.E_ROOT / "a02/a1-diagnostic"


def head_archive_sha256() -> str:
    return v3.sha256(
        subprocess.check_output(["git", "archive", "--format=tar", "HEAD"], cwd=execution.ROOT)
    )


def proposal(
    archive: Path, *, now: datetime | None = None, delegated: bool = False
) -> dict[str, Any]:
    identity = execution.source_identity()
    if v3.sha256(archive.read_bytes()) != head_archive_sha256():
        raise ValueError("archive is not derived from exact HEAD")
    now = now or datetime.now(UTC)
    value = {
        "schema": PROPOSAL_SCHEMA,
        "source_identity": identity,
        "source_archive_sha256": v3.sha256(archive.read_bytes()),
        "specification": diagnostic.specification(delegated=delegated),
        "valid_from_utc": now.isoformat(),
        "valid_until_utc": (now + timedelta(hours=24)).isoformat(),
        "owner_approval": False,
    }
    value["proposal_sha256"] = v3.sha256(v3.canonical(value).encode())
    return value


def validate_proposal(value: dict[str, Any]) -> None:
    payload = {key: val for key, val in value.items() if key != "proposal_sha256"}
    if value.get("schema") != PROPOSAL_SCHEMA or value.get("owner_approval") is not False:
        raise ValueError("unaccepted diagnostic proposal required")
    if value.get("proposal_sha256") != v3.sha256(v3.canonical(payload).encode()):
        raise ValueError("diagnostic proposal hash differs")
    if value["source_identity"] != execution.source_identity():
        raise ValueError("diagnostic source differs from exact clean HEAD")
    if value["source_archive_sha256"] != head_archive_sha256():
        raise ValueError("proposal archive differs from mechanically derived HEAD archive")
    diagnostic.validate_specification(value["specification"])


def admit(
    proposed: dict[str, Any],
    approval: dict[str, Any] | None,
    snapshot: dict[str, Any],
    *,
    startup_cu: float | None,
    live_t4_rate: float | None,
    now: datetime | None = None,
) -> None:
    validate_proposal(proposed)
    spec = proposed["specification"]
    discovery = spec.get("pricing_policy") == "OBSERVE_BEFORE_MODEL_LOAD"
    expected = {
        "schema": AUTH_SCHEMA,
        "proposal_sha256": proposed["proposal_sha256"],
        "accept_a1_for_diagnostic_only": True,
        "approve_exact_source_one_session": True,
        "maximum_new_cu": spec["maximum_new_cu"],
    }
    if approval != expected:
        raise ValueError("explicit owner acceptance of A1 AND exact diagnostic is missing")
    start = datetime.fromisoformat(proposed["valid_from_utc"])
    end = datetime.fromisoformat(proposed["valid_until_utc"])
    current = now or datetime.now(UTC)
    if start.tzinfo is None or end.tzinfo is None or not start <= current < end:
        raise ValueError("diagnostic validity window is not active")
    if end - start > timedelta(hours=24) or (end - current).total_seconds() < (
        spec["wall_seconds"] + spec["stop_reserve_seconds"]
    ):
        raise ValueError("diagnostic validity window cannot cover bounded teardown")
    if startup_cu is None and not discovery:
        raise ValueError("live minimum startup charge must be independently verified")
    if discovery:
        if live_t4_rate is not None or startup_cu is not None:
            raise ValueError("observed-pricing admission must not invent a verified quote")
        diagnostic.bounded_cost(
            spec["rate_ceiling_cu_per_hour"], spec["startup_allowance_cu"], spec=spec
        )
    else:
        if live_t4_rate is None or startup_cu is None:
            raise ValueError("verified live pricing is required")
        diagnostic.bounded_cost(live_t4_rate, startup_cu, spec=spec)
    balance = snapshot["balance"]
    if not math.isfinite(balance) or balance < spec["maximum_new_cu"] + spec["reserve_cu"]:
        raise ValueError("live quota cannot cover the diagnostic")
    if snapshot["usage_rate_cu_per_hour"] != 0 or snapshot["active_sessions"]:
        raise ValueError("diagnostic requires zero preexisting active usage/sessions")


def run(
    *,
    client: execution.ColabClient,
    proposed: dict[str, Any],
    approval: dict[str, Any] | None,
    archive: Path,
    startup_cu: float | None,
    live_t4_rate: float | None,
) -> dict[str, Any]:
    """No allocation before all owner/source/rate/watchdog checks; never retries."""
    before = client.snapshot()
    admit(proposed, approval, before, startup_cu=startup_cu, live_t4_rate=live_t4_rate)
    spec = proposed["specification"]
    discovery = spec.get("pricing_policy") == "OBSERVE_BEFORE_MODEL_LOAD"
    if isinstance(client, DiagnosticCLI):
        client.watchdog_seconds = spec["wall_seconds"]
    if v3.sha256(archive.read_bytes()) != proposed["source_archive_sha256"]:
        raise ValueError("diagnostic archive differs")
    name = f"res541-a1-{proposed['proposal_sha256'][:12]}"
    directory = ROOT / proposed["proposal_sha256"]
    directory.mkdir(parents=True, exist_ok=True)
    if client.sessions():
        raise ValueError("diagnostic requires empty fresh session inventory")
    if discovery:
        execution._write_exclusive(
            ROOT / "owner-delegated-diagnostic-used.json",
            {"session": name, "proposal": proposed},
        )
    execution._write_exclusive(directory / "used.json", {"session": name, "proposal": proposed})
    state: dict[str, Any] = {
        "session": name,
        "proposal": proposed,
        "quota_before": before,
        "passed": False,
        "historical_cu": diagnostic.HISTORICAL_CU,
    }
    watchdog = None
    attempted = False
    started = time.monotonic()
    effective_rate = live_t4_rate
    observed_startup_upper = startup_cu
    state["timing_seconds"] = {}
    try:
        watchdog = client.start_watchdog(name, directory / "watchdog.json")
        attempted = True
        if not client.new(name):
            raise RuntimeError("one T4 allocation failed; no retry")
        if client.hardware(name) != "T4":
            raise RuntimeError("allocated hardware differs from T4")
        after = client.snapshot()
        if discovery:
            effective_rate = float(after["usage_rate_cu_per_hour"])
            observed_startup_upper = float(before["balance"]) - float(after["balance"])
            state["pricing_observation"] = {
                "rate_cu_per_hour": effective_rate,
                "initial_account_delta_cu": observed_startup_upper,
                "minimum_startup_charge_quote": None,
                "basis": "live rate and conservative account delta; not a preallocation quote",
            }
            if observed_startup_upper > spec["startup_allowance_cu"]:
                raise RuntimeError("initial charge exceeds startup allowance; no model loading")
            diagnostic.bounded_cost(effective_rate, observed_startup_upper, spec=spec)
        if effective_rate is None:
            raise RuntimeError("live provider rate is unknown; no model loading")
        if after["usage_rate_cu_per_hour"] != effective_rate or {
            row["name"] for row in after["active_sessions"]
        } != {name}:
            raise RuntimeError("observed provider rate differs from verified rate")
        binding = {
            "schema": "RES541_A1_DIAGNOSTIC_REMOTE_BINDING_V1",
            "source_archive_sha256": proposed["source_archive_sha256"],
            "source_revision": proposed["source_identity"]["commit"],
            "source_identity": proposed["source_identity"],
            "plan_sha256": proposed["proposal_sha256"],
            "protocol_sha256": proposed["specification"]["protocol_sha256"],
            "session_index": 1,
            "item_cost_bounds": {
                "QUALIFICATION": 1,
                "ZERO_SHOT_UNCONSTRAINED": 1,
                "ZERO_SHOT_CONSTRAINED": 1,
            },
            "numerical_diagnostic": proposed["specification"],
        }
        binding_path = directory / "binding.json"
        binding_path.write_text(json.dumps(binding))
        for local, remote in (
            (archive, execution.REMOTE_SOURCE),
            (binding_path, execution.REMOTE_BINDING),
        ):
            if not client.upload(name, local, remote):
                raise RuntimeError("diagnostic upload failed")
        plan = {"bounds": {"cost_buffer_cu": spec["reserve_cu"]}}
        admission = {
            "started_monotonic": started,
            "per_session_cap": spec["maximum_new_cu"],
            "cumulative_cap": spec["maximum_new_cu"],
            "spent_before": 0.0,
        }
        work_ceiling = (
            spec["wall_seconds"] - spec["stop_reserve_seconds"] - 180 if discovery else 360
        )
        for stage, ceiling in (("prepare", 180), ("work", work_ceiling)):
            remaining = (
                spec["wall_seconds"] - spec["stop_reserve_seconds"] - (time.monotonic() - started)
            )
            if remaining < 60:
                raise TimeoutError("insufficient time before independent watchdog stop")
            stage_started = time.monotonic()
            state[stage] = execution.monitored_stage(
                client,
                name,
                stage,
                min(ceiling, int(remaining)),
                before,
                admission,
                plan,
                effective_rate,
            )
            state["timing_seconds"][stage] = time.monotonic() - stage_started
            if state[stage].get("returncode") != 0:
                raise RuntimeError(f"diagnostic {stage} failed; no retry")
        state["remote_completed"] = True
    except Exception as exc:
        state.update(error_type=type(exc).__name__, error_detail=str(exc))
    finally:
        recovery_started = time.monotonic()
        state["recovered"] = {}
        if attempted:
            for remote in (execution.REMOTE_STATUS, REMOTE_REPORT):
                local = directory / Path(remote).name
                try:
                    recovered = client.download(name, remote, local)
                    state["recovered"][remote] = (
                        v3.sha256(local.read_bytes()) if recovered else None
                    )
                except Exception as exc:
                    state["recovered"][remote] = {"error_type": type(exc).__name__}
            state["timing_seconds"]["evidence_recovery"] = time.monotonic() - recovery_started
            teardown_started = time.monotonic()
            try:
                state["stop_requested"] = client.stop(name)
            except Exception as exc:
                state["stop_error"] = type(exc).__name__
            try:
                state["target_absent"] = client.verify_absent(name)
                state["teardown_receipt"] = getattr(client, "teardown_receipt", None)
            except Exception as exc:
                state["target_absent"] = False
                state["teardown_error"] = type(exc).__name__
            state["timing_seconds"]["teardown"] = time.monotonic() - teardown_started
        if watchdog is not None:
            try:
                client.finish_watchdog(watchdog, state.get("target_absent") is True)
            except Exception as exc:
                state["watchdog_error"] = type(exc).__name__
        try:
            after = client.snapshot()
            state["quota_after"] = after
            if after["usage_rate_cu_per_hour"] != 0 or after["active_sessions"]:
                raise ValueError(
                    "unexpected active usage after teardown; cost attribution uncertain"
                )
            delta = before["balance"] - after["balance"]
            if not state.get("target_absent") or not math.isfinite(delta) or delta < 0:
                raise ValueError("cost or teardown is uncertain")
            if (
                effective_rate is None
                or not math.isfinite(effective_rate)
                or effective_rate <= 0
                or observed_startup_upper is None
                or not math.isfinite(observed_startup_upper)
                or observed_startup_upper < 0
            ):
                raise ValueError("live price was not recovered; conservative cost unknown")
            conservative = max(
                delta, effective_rate * (time.monotonic() - started) / 3600 + observed_startup_upper
            )
            state["new_conservative_cu"] = conservative
            state["cumulative_historical_plus_new_cu"] = diagnostic.HISTORICAL_CU + conservative
            if conservative > spec["maximum_new_cu"]:
                raise ValueError("diagnostic cost cap exceeded")
        except Exception as exc:
            state["cost_error"] = str(exc)
        try:
            remote_status = json.loads(
                (directory / Path(execution.REMOTE_STATUS).name).read_bytes()
            )
            if (
                remote_status["binding"] != binding
                or remote_status.get("status") != "DIAGNOSTIC_COMPLETE"
            ):
                raise ValueError("diagnostic status binding/result differs")
            data = directory / Path(REMOTE_REPORT).name
            if remote_status["diagnostic_sha256"] != v3.sha256(data.read_bytes()):
                raise ValueError("diagnostic evidence digest differs")
            final = json.loads(data.read_text().splitlines()[-1])
            if final.get("phase") != "FINAL" or final.get("passed") is not True:
                raise ValueError("full-model diagnostic did not pass")
            state["passed"] = bool(
                state.get("remote_completed")
                and state.get("target_absent")
                and not state.get("cost_error")
                and not state.get("watchdog_error")
            )
        except Exception as exc:
            state["evidence_error"] = str(exc)
        state["timing_seconds"]["total"] = time.monotonic() - started
        (directory / "control.json").write_text(json.dumps(state, sort_keys=True, indent=2) + "\n")
    return state


class DiagnosticCLI(execution.ColabCLI):
    watchdog_seconds: int = diagnostic.WALL_SECONDS

    def new(self, name: str) -> bool:
        if os.environ.get("COLAB_CLI_ASSIGN_RETRIES") != "0":
            raise ValueError("allocation retries must explicitly be disabled")
        return super().new(name)

    def download(self, name: str, remote: str, local: Path) -> bool:
        return (
            self._run(
                ["colab", "--auth=oauth2", "download", "--session", name, remote, str(local)],
                timeout=20,
            ).returncode
            == 0
        )

    watchdog_module = "scripts.a02_v3_diagnostic_session"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposal", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--verified-live-t4-rate", type=float)
    parser.add_argument("--verified-startup-cu", type=float)
    parser.add_argument("--owner-delegated", action="store_true")
    args = parser.parse_args()
    if args.approval is None:
        execution.source_archive(args.archive)
        value = proposal(args.archive, delegated=args.owner_delegated)
        args.proposal.write_text(json.dumps(value, indent=2) + "\n")
        return 0
    proposed = json.loads(args.proposal.read_bytes())
    if args.verified_live_t4_rate is None and "pricing_policy" not in proposed["specification"]:
        raise ValueError("live provider T4 rate must be verified before admission")
    os.environ["COLAB_CLI_ASSIGN_RETRIES"] = "0"
    result = run(
        client=DiagnosticCLI(),
        proposed=proposed,
        approval=json.loads(args.approval.read_bytes()),
        archive=args.archive,
        startup_cu=args.verified_startup_cu,
        live_t4_rate=args.verified_live_t4_rate,
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    if len(sys.argv) in {4, 5} and sys.argv[1] == "watchdog":
        from scripts import a02_execution

        seconds = int(sys.argv[4]) if len(sys.argv) == 5 else diagnostic.WALL_SECONDS
        if seconds not in {diagnostic.WALL_SECONDS, 1800, 3600, 7200}:
            raise ValueError("watchdog duration is outside the source-bound policies")
        a02_execution.MAX_SESSION_SECONDS = seconds
        receipt = Path(sys.argv[3])
        receipt.write_text(json.dumps({"session": sys.argv[2], "phase": "READY"}))
        a02_execution._watchdog(sys.argv[2], receipt)
        if json.loads(receipt.read_text()).get("phase") == "READY":
            receipt.write_text(json.dumps({"session": sys.argv[2], "phase": "DISARMED"}))
    else:
        raise SystemExit(main())
