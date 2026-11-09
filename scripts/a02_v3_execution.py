"""Bounded multi-session controller for the V3 zero-shot arms (RES-541).

Nothing here allocates a GPU unless ``run-session`` is invoked with a valid, individually
issued owner authorization for that exact session index and plan hash. No such authorization
exists. The original V2 campaign ledger and session markers are never read for budget or
modified; V3 keeps its own ledger.

Planning is mechanical: every work item has a worst-case cost derived from the profile and
preflight with conservative runtime bounds, items are packed in preregistered order into
sessions of bounded length, and the compute-unit cap follows from the session count and an
admission rate ceiling. The worker's own deadline check, not this packing, decides where a
session actually stops, so a session never ends mid-item.

Per session: admission against the live read-only quota snapshot and the V3 ledger, a session
marker consumed before allocation, exact-name T4 allocation with no retry, an immediate stop if
the live rate exceeds the ceiling, bounded prepare and work stages, checkpoint download even
after failure, a fork-safe merge of the downloaded checkpoint, and exact-target teardown in
``finally``. Unrelated sessions are never stopped.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from scripts import a02_v3_contract as v3
from scripts import a02_v3_decision as decision
from scripts import a02_v3_worker as worker

ROOT = v3.ROOT
E_ROOT = Path("/mnt/e/DynamisLM-A0").resolve()
V3_DIR = E_ROOT / "a02/v3-zero-shot"
PLAN_SCHEMA = "RES541_A02_V3_SESSION_PLAN_V1"
AUTHORIZATION_SCHEMA = "RES541_A02_V3_SESSION_AUTHORIZATION_V1"
LEDGER_SCHEMA = "RES541_A02_V3_LEDGER_V1"
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


def build_plan(
    protocol: dict[str, Any],
    preflight: dict[str, Any],
    bounds: RuntimeBounds,
    *,
    live_rate_cu_per_hour: float | None = None,
) -> dict[str, Any]:
    """Deterministic worst-case session packing and compute-unit admission plan."""
    profile = v3.load_profile()
    items = worker.work_items(protocol)
    costs = item_cost_bounds(profile, preflight, bounds)
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
        "generation_seconds_per_session": budget,
        "work_items": len(items),
        "worst_case_generation_seconds": round(total_worst, 1),
        "sessions": [{**s, "index": i + 1} for i, s in enumerate(sessions)],
        "session_count": len(sessions),
        "worst_case_session_seconds": len(sessions) * bounds.session_seconds,
        "compute_units": {
            "per_session_cap": round(per_session_cu, 4),
            "cumulative_cap": round(len(sessions) * per_session_cu, 4),
            "expected_at_observed_t4_rate": round(
                len(sessions) * bounds.session_seconds / 3600 * bounds.t4_rate_cu_per_hour, 4
            ),
            "rate_basis": "session-004 provider-reported T4 rate; admission stops above ceiling",
            "live_rate_at_planning_cu_per_hour": live_rate_cu_per_hour,
        },
        "cache_qualification": {
            "worst_case_seconds": costs["QUALIFICATION"],
            "share_of_first_session": round(costs["QUALIFICATION"] / budget, 3),
            "uncached_full_forwards": worker.QUALIFICATION_EXAMPLES
            * preflight["max_constrained_scorer_calls"],
        },
        "retry_policy": "No automatic retry. A session that commits fewer items than planned "
        "leaves the remainder to the next individually authorized session; if the planned count "
        "is exhausted, any extra session needs a new owner authorization and plan amendment.",
    }
    plan["plan_sha256"] = v3.sha256(v3.canonical(plan).encode())
    return plan


# --------------------------------------------------------------------------- admission


class AdmissionError(RuntimeError):
    pass


def ledger_new(plan: dict[str, Any]) -> dict[str, Any]:
    return {"schema": LEDGER_SCHEMA, "plan_sha256": plan["plan_sha256"], "sessions": []}


def admit(
    *,
    plan: dict[str, Any],
    ledger: dict[str, Any],
    authorization: dict[str, Any] | None,
    snapshot: dict[str, Any],
    session_index: int,
) -> dict[str, Any]:
    """Pure admission decision for one session; raises AdmissionError when not admitted."""
    if authorization is None:
        raise AdmissionError("no owner authorization exists for this V3 session")
    expected = {
        "schema": AUTHORIZATION_SCHEMA,
        "plan_sha256": plan["plan_sha256"],
        "session_index": session_index,
    }
    for key, value in expected.items():
        if authorization.get(key) != value:
            raise AdmissionError(f"authorization {key} does not match this session")
    if ledger.get("schema") != LEDGER_SCHEMA or ledger.get("plan_sha256") != plan["plan_sha256"]:
        raise AdmissionError("V3 ledger is not bound to this plan")
    used = ledger["sessions"]
    if [s["index"] for s in used] != list(range(1, len(used) + 1)):
        raise AdmissionError("V3 ledger session sequence is inconsistent")
    if session_index != len(used) + 1:
        raise AdmissionError("session index is not the next unused V3 session")
    if session_index > plan["session_count"]:
        raise AdmissionError("planned V3 session count is exhausted; amend the plan")
    per_session = plan["compute_units"]["per_session_cap"]
    spent = sum(float(s["compute_units_spent"]) for s in used)
    cap = min(plan["compute_units"]["cumulative_cap"], float(authorization["cumulative_cap_cu"]))
    if spent + per_session > cap + 1e-9:
        raise AdmissionError("cumulative V3 compute-unit cap would be exceeded")
    if float(authorization["max_cu_this_session"]) + 1e-9 < per_session:
        raise AdmissionError("authorized per-session compute units are below the plan bound")
    if snapshot["balance"] < per_session + plan["bounds"]["cost_buffer_cu"]:
        raise AdmissionError("live balance cannot cover one bounded session")
    if snapshot["usage_rate_cu_per_hour"] > 0 and not authorization.get(
        "allow_concurrent_unrelated_usage"
    ):
        raise AdmissionError("account is already consuming compute; usage is not attributable")
    return {
        "admitted": True,
        "spent_before": spent,
        "per_session_cap": per_session,
        "cumulative_cap": cap,
        "unrelated_sessions": sorted(s["name"] for s in snapshot["active_sessions"]),
    }


# --------------------------------------------------------------------------- checkpoint merge


def merge_checkpoint(
    local: Path, downloaded: Path, items: Sequence[worker.WorkItem]
) -> dict[str, Any]:
    """Adopt a downloaded checkpoint only if it verifies and extends the local one."""
    remote_state = worker.read_checkpoint(downloaded, items)
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


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(value, indent=2, sort_keys=True) + "\n")


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
) -> dict[str, Any]:
    """Run one admitted session end to end; teardown is unconditional."""
    protocol = decision.load_protocol()
    items = worker.work_items(protocol)
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else ledger_new(plan)
    before = client.snapshot()
    admission = admit(
        plan=plan,
        ledger=ledger,
        authorization=authorization,
        snapshot=before,
        session_index=session_index,
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
            "recorded_at_utc": datetime.now(UTC).isoformat(),
        },
    )
    local = run_dir / "checkpoint.jsonl"
    downloaded = run_dir / f"session-{session_index:03d}-checkpoint.jsonl"
    state: dict[str, Any] = {"session": name, "index": session_index, "admission": admission}
    allocated = False
    try:
        allocated = client.new(name)
        state["allocated"] = allocated
        if not allocated:
            raise RuntimeError("single V3 T4 allocation failed; no retry")
        if client.hardware(name) != "T4":
            raise RuntimeError("allocated V3 session is not the exact requested T4")
        after = client.snapshot()
        state["rate_after_allocation"] = after["usage_rate_cu_per_hour"]
        if after["usage_rate_cu_per_hour"] > plan["bounds"]["admission_rate_ceiling_cu_per_hour"]:
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
        state["prepare"] = client.exec_stage(name, "prepare", bounds["prepare_seconds"])
        if state["prepare"].get("returncode") == 0:
            work_timeout = bounds["exec_seconds"] - bounds["prepare_seconds"]
            state["work"] = client.exec_stage(name, "work", work_timeout)
    except Exception as exc:  # recorded; teardown and evidence recovery still run
        state["failure"] = f"{type(exc).__name__}: {exc}"
    finally:
        if allocated:
            try:
                if client.download(name, REMOTE_CHECKPOINT, downloaded):
                    state["merge"] = merge_checkpoint(local, downloaded, items)
                else:
                    state["merge"] = "EVIDENCE_NOT_RETRIEVED"
            except worker.CheckpointError as exc:
                state["merge"] = f"REJECTED: {exc}"
        state["stopped"] = client.stop(name)
        remaining = client.sessions()
        state["target_absent_after_stop"] = name not in remaining
        state["unrelated_sessions_after"] = sorted(s for s in remaining if s != name)
        end = client.snapshot()
        spent = max(0.0, float(before["balance"]) - float(end["balance"]))
        ledger["sessions"].append(
            {
                "index": session_index,
                "name": name,
                "compute_units_spent": round(spent, 4),
                "committed_items": len(worker.read_checkpoint(local, items)["entries"])
                if local.exists()
                else 0,
            }
        )
        temporary = ledger_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n")
        os.replace(temporary, ledger_path)
        (run_dir / f"session-{session_index:03d}-control.json").write_text(
            json.dumps(state, indent=2, sort_keys=True, default=str) + "\n"
        )
    return state


# --------------------------------------------------------------------------- CLI


class ColabCLI:  # pragma: no cover - provider commands, used only in an authorized session
    """The reviewed V2 Colab CLI command forms."""

    def __init__(self) -> None:
        from scripts import a02_dev_execution, a02_execution

        self._run = a02_dev_execution._run_colab
        self._snapshot = a02_dev_execution._colab_snapshot
        self._rows = a02_execution._session_rows
        self._timeouts = a02_execution

    def snapshot(self) -> dict[str, Any]:
        snap: dict[str, Any] = self._snapshot()
        return snap

    def new(self, name: str) -> bool:
        command = ["colab", "--auth=oauth2", "new", "--session", name, "--gpu", "T4"]
        return self._run(command, timeout=self._timeouts.NEW_TIMEOUT_SECONDS).returncode == 0

    def hardware(self, name: str) -> str | None:
        out = self._run(["colab", "--auth=oauth2", "status", "--session", name], timeout=30)
        rows = [row for row in self._rows(out.stdout) if row[0] == name]
        return rows[0][2].upper() if len(rows) == 1 else None

    def upload(self, name: str, local: Path, remote: str) -> bool:
        command = ["colab", "--auth=oauth2", "upload", "--session", name, str(local), remote]
        return self._run(command, timeout=self._timeouts.UPLOAD_TIMEOUT_SECONDS).returncode == 0

    def exec_stage(self, name: str, stage: str, timeout: int) -> dict[str, Any]:
        command = [
            "colab", "--auth=oauth2", "exec", "--session", name,
            "--env", f"A02_V3_REMOTE_STAGE={stage}",
            "--env", f"A02_V3_REMOTE_STAGE_TIMEOUT={timeout}",
            "--file", str(ROOT / "scripts/a02_v3_remote.py"),
            "--timeout", str(timeout),
        ]  # fmt: skip
        try:
            result = self._run(command, timeout=timeout + 30)
        except subprocess.TimeoutExpired:
            return {"returncode": None, "timed_out": True}
        return {"returncode": result.returncode, "timed_out": False}

    def download(self, name: str, remote: str, local: Path) -> bool:
        command = ["colab", "--auth=oauth2", "download", "--session", name, remote, str(local)]
        return self._run(command, timeout=self._timeouts.DOWNLOAD_TIMEOUT_SECONDS).returncode == 0

    def stop(self, name: str) -> bool:
        command = ["colab", "--auth=oauth2", "stop", "--session", name]
        return self._run(command, timeout=self._timeouts.STOP_TIMEOUT_SECONDS).returncode == 0

    def sessions(self) -> list[str]:
        out = self._run(["colab", "--auth=oauth2", "sessions"], timeout=30)
        return [row[0] for row in self._rows(out.stdout)]


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


def remote_binding(plan: dict[str, Any], archive: Path, revision: str) -> dict[str, Any]:
    """The binding the remote bootstrap verifies (session_index is added per session)."""
    return {
        "schema": "RES541_A02_V3_REMOTE_BINDING_V1",
        "source_archive_sha256": v3.sha256(archive.read_bytes()),
        "source_revision": revision,
        "plan_sha256": plan["plan_sha256"],
        "protocol_sha256": plan["protocol_sha256"],
        "item_cost_bounds": plan["item_cost_bounds_seconds"],
    }


def _load_preflight(path: Path) -> dict[str, Any]:
    value = v3.json_object(path.read_text(encoding="utf-8"))
    if value.get("schema") != "RES541_A02_V3_CPU_PREFLIGHT_V1":
        raise ValueError("V3 preflight receipt schema differs")
    if value.get("gpu_allocated") is not False or value.get("weights_loaded") is not False:
        raise ValueError("V3 preflight receipt is not CPU-only")
    return value


def main() -> int:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan_cmd = sub.add_parser("plan", help="print the session plan using a live read-only snapshot")
    plan_cmd.add_argument("--preflight", type=Path, required=True)
    plan_cmd.add_argument("--offline", action="store_true", help="skip the live quota snapshot")
    run_cmd = sub.add_parser("run-session", help="run one individually authorized session")
    run_cmd.add_argument("--preflight", type=Path, required=True)
    run_cmd.add_argument("--index", type=int, required=True)
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
    path = V3_DIR / f"session-{args.index:03d}-authorization.json"
    authorization = json.loads(path.read_text()) if path.exists() else None
    if authorization is None:
        raise AdmissionError("no owner authorization exists for this V3 session")
    run_dir = V3_DIR / f"plan-{plan['plan_sha256'][:12]}"
    run_dir.mkdir(parents=True, exist_ok=True)
    archive, revision = source_archive(run_dir / f"source-{args.index:03d}.tar")
    state = run_session(
        client=ColabCLI(),
        plan=plan,
        ledger_path=run_dir / "ledger.json",
        authorization=authorization,
        session_index=args.index,
        run_dir=run_dir,
        source_archive=archive,
        binding=remote_binding(plan, archive, revision),
    )
    print(json.dumps(state, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
