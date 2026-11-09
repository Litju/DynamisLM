from __future__ import annotations

import itertools
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_decision as decision
from scripts import a02_v3_execution as execution
from scripts import a02_v3_worker as worker

from test_res541_a02_v3_worker import COSTS, _Backend

PROTOCOL = decision.load_protocol()
ITEMS = worker.work_items(PROTOCOL)
PREFLIGHT = {
    "schema": "RES541_A02_V3_CPU_PREFLIGHT_V1",
    "max_constrained_scorer_calls": 69,
    "max_prompt_tokens": 1508,
    "gpu_allocated": False,
    "weights_loaded": False,
}
BOUNDS = execution.RuntimeBounds()
PLAN = execution.build_plan(PROTOCOL, PREFLIGHT, BOUNDS, live_rate_cu_per_hour=0.0)
QUIET = {"balance": 87.08, "usage_rate_cu_per_hour": 0.0, "active_sessions": []}


def _authorization(index: int, **overrides: Any) -> dict[str, Any]:
    return {
        "schema": execution.AUTHORIZATION_SCHEMA,
        "plan_sha256": PLAN["plan_sha256"],
        "session_index": index,
        "max_cu_this_session": PLAN["compute_units"]["per_session_cap"],
        "cumulative_cap_cu": PLAN["compute_units"]["cumulative_cap"],
        **overrides,
    }


# ---- plan -----------------------------------------------------------------------------


def test_plan_is_deterministic_and_honest_about_session_count() -> None:
    again = execution.build_plan(PROTOCOL, PREFLIGHT, BOUNDS, live_rate_cu_per_hour=0.0)
    assert again["plan_sha256"] == PLAN["plan_sha256"]
    assert PLAN["work_items"] == len(ITEMS) == 581
    # The preregistered 2,735.7 s estimate cannot fit one 900 s session.
    assert PLAN["session_count"] > 1
    assert (
        PLAN["worst_case_generation_seconds"]
        > PROTOCOL["compute_estimate"]["estimate"]["total_seconds"]
        - PROTOCOL["compute_estimate"]["estimate"]["model_load_seconds"]
    )
    sessions = PLAN["sessions"]
    assert sessions[0]["first_item"] == 0 and sessions[-1]["end_item"] == len(ITEMS)
    assert all(a["end_item"] == b["first_item"] for a, b in itertools.pairwise(sessions))
    assert all(s["worst_case_seconds"] <= PLAN["generation_seconds_per_session"] for s in sessions)


def test_plan_costs_follow_profile_preflight_and_bounds() -> None:
    costs = PLAN["item_cost_bounds_seconds"]
    assert costs["ZERO_SHOT_UNCONSTRAINED"] == pytest.approx(1 + 128 / 20)
    assert costs["ZERO_SHOT_CONSTRAINED"] == pytest.approx(1 + 69 / 20)
    assert costs["QUALIFICATION"] == pytest.approx(3 * (1 + 69 / 20 + 69 * 0.6))
    assert PLAN["generation_seconds_per_session"] == 720 - 180 - 100 - 30
    assert PLAN["cache_qualification"]["uncached_full_forwards"] == 207


def test_compute_unit_cap_follows_session_count_and_rate_ceiling() -> None:
    cu = PLAN["compute_units"]
    per = 900 / 3600 * 1.25 + 0.05
    assert cu["per_session_cap"] == pytest.approx(per, abs=1e-4)
    assert cu["cumulative_cap"] == pytest.approx(PLAN["session_count"] * per, abs=1e-3)
    assert cu["expected_at_observed_t4_rate"] < cu["cumulative_cap"]


def test_plan_rejects_bounds_that_cannot_hold_one_item() -> None:
    tight = execution.RuntimeBounds(exec_seconds=330)
    with pytest.raises(ValueError, match="cannot fit"):
        execution.build_plan(PROTOCOL, PREFLIGHT, tight)


# ---- admission ------------------------------------------------------------------------


def test_admission_requires_an_individual_authorization() -> None:
    ledger = execution.ledger_new(PLAN)
    with pytest.raises(execution.AdmissionError, match="no owner authorization"):
        execution.admit(
            plan=PLAN, ledger=ledger, authorization=None, snapshot=QUIET, session_index=1
        )
    admitted = execution.admit(
        plan=PLAN, ledger=ledger, authorization=_authorization(1), snapshot=QUIET, session_index=1
    )
    assert admitted["admitted"] is True


@pytest.mark.parametrize(
    ("authorization", "snapshot", "index", "message"),
    [
        (_authorization(2), QUIET, 1, "session_index"),
        (_authorization(1, plan_sha256="0" * 64), QUIET, 1, "plan_sha256"),
        (_authorization(1, schema="X"), QUIET, 1, "schema"),
        (_authorization(2), QUIET, 2, "next unused"),
        (_authorization(1, cumulative_cap_cu=0.1), QUIET, 1, "cumulative"),
        (_authorization(1, max_cu_this_session=0.1), QUIET, 1, "per-session"),
        (_authorization(1), {**QUIET, "balance": 0.2}, 1, "live balance"),
        (_authorization(1), {**QUIET, "usage_rate_cu_per_hour": 6.7}, 1, "not attributable"),
    ],
)
def test_admission_fails_closed(
    authorization: dict[str, Any], snapshot: dict[str, Any], index: int, message: str
) -> None:
    with pytest.raises(execution.AdmissionError, match=message):
        execution.admit(
            plan=PLAN,
            ledger=execution.ledger_new(PLAN),
            authorization=authorization,
            snapshot=snapshot,
            session_index=index,
        )


def test_admission_stops_when_planned_sessions_or_cap_are_exhausted() -> None:
    ledger = execution.ledger_new(PLAN)
    for i in range(1, PLAN["session_count"] + 1):
        ledger["sessions"].append({"index": i, "compute_units_spent": 0.0})
    n = PLAN["session_count"] + 1
    with pytest.raises(execution.AdmissionError, match="exhausted"):
        execution.admit(
            plan=PLAN,
            ledger=ledger,
            authorization=_authorization(n),
            snapshot=QUIET,
            session_index=n,
        )
    spent = execution.ledger_new(PLAN)
    spent["sessions"].append(
        {"index": 1, "compute_units_spent": PLAN["compute_units"]["cumulative_cap"]}
    )
    with pytest.raises(execution.AdmissionError, match="cumulative"):
        execution.admit(
            plan=PLAN,
            ledger=spent,
            authorization=_authorization(2),
            snapshot=QUIET,
            session_index=2,
        )


def test_tampered_ledger_is_rejected() -> None:
    ledger = execution.ledger_new(PLAN)
    ledger["sessions"].append({"index": 2, "compute_units_spent": 0.0})
    with pytest.raises(execution.AdmissionError, match="inconsistent"):
        execution.admit(
            plan=PLAN,
            ledger=ledger,
            authorization=_authorization(2),
            snapshot=QUIET,
            session_index=2,
        )
    with pytest.raises(execution.AdmissionError, match="not bound"):
        execution.admit(
            plan=PLAN,
            ledger={**execution.ledger_new(PLAN), "plan_sha256": "x"},
            authorization=_authorization(1),
            snapshot=QUIET,
            session_index=1,
        )


# ---- simulated sessions -----------------------------------------------------------------


class FakeColab:
    """A provider simulation: the 'work' stage runs the real worker on a remote copy."""

    def __init__(self, root: Path, *, items_per_session: int, tear_after: bool = False) -> None:
        self.root = root
        self.items_per_session = items_per_session
        self.tear_after = tear_after
        self.active: dict[str, dict[str, Any]] = {"res338-fits": {"files": {}}}
        self.stopped: list[str] = []
        self.balance = 87.08
        self.rate_when_allocated = 1.15
        self.fail_download = False
        self.fail_new = False
        self.remote_mutator: Any = None

    def snapshot(self) -> dict[str, Any]:
        ours = [n for n in self.active if n.startswith("res541")]
        return {
            "balance": self.balance,
            "usage_rate_cu_per_hour": self.rate_when_allocated if ours else 0.0,
            "active_sessions": [{"name": n} for n in self.active if n.startswith("res541")],
        }

    def new(self, name: str) -> bool:
        if self.fail_new:
            return False
        self.active[name] = {"files": {}}
        return True

    def hardware(self, name: str) -> str | None:
        return "T4" if name in self.active else None

    def upload(self, name: str, local: Path, remote: str) -> bool:
        target = self.root / name / Path(remote).name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local, target)
        return True

    def exec_stage(self, name: str, stage: str, timeout: int) -> dict[str, Any]:
        if stage == "prepare":
            return {"returncode": 0, "timed_out": False}
        remote = self.root / name / Path(execution.REMOTE_CHECKPOINT).name
        status = worker.run_worker(
            protocol=PROTOCOL,
            items=ITEMS,
            checkpoint=remote,
            backend=_Backend(),
            deadline=float("inf"),
            item_cost_bounds=COSTS,
            stop_after=self.items_per_session,
        )
        if self.tear_after:
            with remote.open("ab") as handle:
                handle.write(b'{"schema":"RES541_A02_V3_CHECKPOINT_LINE_V1","seq":')
            return {"returncode": None, "timed_out": True}
        if self.remote_mutator:
            self.remote_mutator(remote)
        return {"returncode": 0 if status["status"] == "COMPLETE" else 3, "timed_out": False}

    def download(self, name: str, remote: str, local: Path) -> bool:
        source = self.root / name / Path(remote).name
        if self.fail_download or not source.exists():
            return False
        shutil.copyfile(source, local)
        return True

    def stop(self, name: str) -> bool:
        self.stopped.append(name)
        self.active.pop(name, None)
        self.balance -= 0.29
        return True

    def sessions(self) -> list[str]:
        return list(self.active)


def _session(
    tmp_path: Path, client: FakeColab, index: int, auth: Any = "default"
) -> dict[str, Any]:
    archive = tmp_path / "source.tar"
    archive.write_bytes(b"source")
    return execution.run_session(
        client=client,
        plan=PLAN,
        ledger_path=tmp_path / "ledger.json",
        authorization=_authorization(index) if auth == "default" else auth,
        session_index=index,
        run_dir=tmp_path / "run",
        source_archive=archive,
        binding={"plan_sha256": PLAN["plan_sha256"], "item_cost_bounds": COSTS},
    )


def test_interrupted_sessions_resume_to_completion_and_score_on_cpu(tmp_path: Path) -> None:
    client = FakeColab(tmp_path / "remote", items_per_session=200, tear_after=True)
    states = [_session(tmp_path, client, i) for i in (1, 2, 3)]
    for state in states:
        assert state["work"]["timed_out"] is True  # every session was cut off mid-write
        assert state["merge"]["torn_tail_discarded"] is True
        assert state["stopped"] is True and state["target_absent_after_stop"] is True
        assert state["unrelated_sessions_after"] == ["res338-fits"]
    assert [s["merge"]["committed_after"] for s in states] == [200, 400, 581]
    assert "res338-fits" not in client.stopped
    report = worker.score_checkpoint(PROTOCOL, tmp_path / "run" / "checkpoint.jsonl")
    assert report["decision"]["decision"] == "ADOPT_REPAIRED_CONTRACT_WITH_CONSTRAINED_DECODING"
    ledger = json.loads((tmp_path / "ledger.json").read_text())
    assert [s["committed_items"] for s in ledger["sessions"]] == [200, 400, 581]
    assert all(s["compute_units_spent"] == pytest.approx(0.29) for s in ledger["sessions"])


def test_unauthorized_session_never_allocates(tmp_path: Path) -> None:
    client = FakeColab(tmp_path / "remote", items_per_session=10)
    with pytest.raises(execution.AdmissionError, match="no owner authorization"):
        _session(tmp_path, client, 1, auth=None)
    assert client.stopped == [] and set(client.active) == {"res338-fits"}
    assert not (tmp_path / "run").exists()


def test_session_marker_is_consumed_and_cannot_be_reused(tmp_path: Path) -> None:
    client = FakeColab(tmp_path / "remote", items_per_session=5)
    _session(tmp_path, client, 1)
    with pytest.raises(execution.AdmissionError, match="session_index|next unused"):
        _session(tmp_path, client, 1)
    (tmp_path / "ledger.json").unlink()
    with pytest.raises(FileExistsError):
        _session(tmp_path, client, 1)  # the marker alone still blocks reuse


def test_rate_above_ceiling_stops_before_any_work(tmp_path: Path) -> None:
    client = FakeColab(tmp_path / "remote", items_per_session=5)
    client.rate_when_allocated = 2.0
    state = _session(tmp_path, client, 1)
    assert "exceeds the admission ceiling" in state["failure"]
    assert "work" not in state and "prepare" not in state
    assert client.stopped == [state["session"]]


def test_allocation_failure_is_not_retried_and_still_tears_down(tmp_path: Path) -> None:
    client = FakeColab(tmp_path / "remote", items_per_session=5)
    client.fail_new = True
    state = _session(tmp_path, client, 1)
    assert "allocation failed; no retry" in state["failure"]
    assert client.stopped == [state["session"]] and "merge" not in state


def test_forked_remote_checkpoint_is_rejected_and_local_evidence_kept(tmp_path: Path) -> None:
    client = FakeColab(tmp_path / "remote", items_per_session=20)
    _session(tmp_path, client, 1)
    local = tmp_path / "run" / "checkpoint.jsonl"
    kept = local.read_bytes()

    def fork(remote: Path) -> None:
        lines = remote.read_bytes().split(b"\n")
        entry = json.loads(lines[3])
        entry["record"]["raw_output"] = "forged"
        lines[3] = json.dumps(entry).encode()
        remote.write_bytes(b"\n".join(lines))

    client.remote_mutator = fork
    state = _session(tmp_path, client, 2)
    assert str(state["merge"]).startswith("REJECTED")
    assert local.read_bytes() == kept


def test_lost_download_preserves_local_evidence(tmp_path: Path) -> None:
    client = FakeColab(tmp_path / "remote", items_per_session=15)
    _session(tmp_path, client, 1)
    kept = (tmp_path / "run" / "checkpoint.jsonl").read_bytes()
    client.fail_download = True
    state = _session(tmp_path, client, 2)
    assert state["merge"] == "EVIDENCE_NOT_RETRIEVED"
    assert (tmp_path / "run" / "checkpoint.jsonl").read_bytes() == kept
    assert state["stopped"] is True


def test_merge_rejects_shorter_remote_evidence(tmp_path: Path) -> None:
    long_path = tmp_path / "long.jsonl"
    short_path = tmp_path / "short.jsonl"
    worker.run_worker(
        protocol=PROTOCOL, items=ITEMS, checkpoint=long_path, backend=_Backend(),
        deadline=float("inf"), item_cost_bounds=COSTS, stop_after=6,
    )  # fmt: skip
    data = long_path.read_bytes().split(b"\n")
    short_path.write_bytes(b"\n".join(data[:3]) + b"\n")
    with pytest.raises(worker.CheckpointError, match="shorter"):
        execution.merge_checkpoint(long_path, short_path, ITEMS)
