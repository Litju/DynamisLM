from __future__ import annotations

import itertools
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_contract as v3
from scripts import a02_v3_decision as decision
from scripts import a02_v3_execution as execution
from scripts import a02_v3_worker as worker

from test_res541_a02_v3_worker import COSTS, _Backend

PROTOCOL = decision.load_protocol()
ITEMS = worker.work_items(PROTOCOL)
PREFLIGHT = {
    "schema": "RES541_A02_V3_CPU_PREFLIGHT_V1",
    "max_constrained_scorer_calls": 69,  # exposed-only, as the real preflight measures
    "max_prompt_tokens": 1508,
    "gpu_allocated": False,
    "weights_loaded": False,
}
BOUNDS = execution.RuntimeBounds()
PLAN = execution.build_plan(PROTOCOL, PREFLIGHT, BOUNDS, live_rate_cu_per_hour=0.0)
QUIET = {"balance": 87.08, "usage_rate_cu_per_hour": 0.0, "active_sessions": []}


NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def _allowance(**overrides: Any) -> dict[str, Any]:
    return {
        "schema": execution.ALLOWANCE_SCHEMA,
        "plan_sha256": PLAN["plan_sha256"],
        "max_sessions": PLAN["session_count"],
        "cumulative_cap_cu": PLAN["compute_units"]["cumulative_cap"],
        "max_cu_per_session": PLAN["compute_units"]["per_session_cap"],
        "valid_until_utc": (NOW + timedelta(days=2)).isoformat(),
        "allow_concurrent_unrelated_usage": False,
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


def test_plan_hash_ignores_live_account_state_so_printed_and_run_plans_agree() -> None:
    hashes = {
        execution.build_plan(PROTOCOL, PREFLIGHT, BOUNDS, live_rate_cu_per_hour=rate)["plan_sha256"]
        for rate in (None, 0.0, 1.15, 6.7)
    }
    assert hashes == {PLAN["plan_sha256"]}
    assert "live_rate_at_planning_cu_per_hour" not in json.dumps(
        {k: v for k, v in PLAN.items() if k != "live_observation_not_hashed"}
    )
    # Anything deterministic still changes the hash.
    other = execution.build_plan(
        PROTOCOL, PREFLIGHT, execution.RuntimeBounds(session_seconds=901), live_rate_cu_per_hour=0.0
    )
    assert other["plan_sha256"] != PLAN["plan_sha256"]


def _receipt(tmp_path: Path, **changes: Any) -> Path:
    receipt = {
        **PREFLIGHT,
        "profile_sha256": v3.sha256(v3.PROFILE_PATH.read_bytes()),
        **changes,
    }
    path = tmp_path / "preflight.json"
    path.write_text(json.dumps(receipt))
    return path


def test_preflight_receipt_must_match_the_current_profile_and_be_cpu_only(tmp_path: Path) -> None:
    assert execution._load_preflight(_receipt(tmp_path))["gpu_allocated"] is False
    for changes, message in (
        ({"profile_sha256": "0" * 64}, "different contract profile"),
        ({"schema": "X"}, "schema differs"),
        ({"gpu_allocated": True}, "not CPU-only"),
        ({"weights_loaded": True}, "not CPU-only"),
    ):
        with pytest.raises(ValueError, match=message):
            execution._load_preflight(_receipt(tmp_path, **changes))


def test_plan_costs_follow_profile_preflight_and_bounds() -> None:
    costs = PLAN["item_cost_bounds_seconds"]
    assert costs["ZERO_SHOT_UNCONSTRAINED"] == pytest.approx(1 + 128 / 20)
    calls = PLAN["scorer_call_bound"]["used_for_pricing"]
    assert calls == execution.workload_scorer_calls(PROTOCOL)
    assert costs["ZERO_SHOT_CONSTRAINED"] == pytest.approx(1 + calls / 20)
    assert costs["QUALIFICATION"] == pytest.approx(3 * (1 + calls / 20 + calls * 0.6))
    assert PLAN["generation_seconds_per_session"] == 720 - 180 - 100 - 30
    assert PLAN["cache_qualification"]["uncached_full_forwards"] == 3 * calls


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


# ---- admission: one finite campaign allowance ------------------------------------------


def _admit(allowance: Any, *, ledger: Any = None, snapshot: Any = None, index: int = 1) -> Any:
    return execution.admit(
        plan=PLAN,
        ledger=ledger or execution.ledger_new(PLAN),
        authorization=allowance,
        snapshot=snapshot or QUIET,
        session_index=index,
        now=NOW,
    )


def test_one_allowance_admits_every_planned_session_without_per_session_ceremony() -> None:
    allowance = _allowance()
    ledger = execution.ledger_new(PLAN)
    for index in range(1, PLAN["session_count"] + 1):
        assert _admit(allowance, ledger=ledger, index=index)["admitted"] is True
        ledger["sessions"].append(
            {"index": index, "compute_units_spent": PLAN["compute_units"]["per_session_cap"] / 2}
        )
    assert PLAN["session_count"] == 9


def test_admission_requires_an_allowance() -> None:
    with pytest.raises(execution.AdmissionError, match="no owner campaign allowance"):
        _admit(None)


@pytest.mark.parametrize(
    ("allowance", "message"),
    [
        (_allowance(plan_sha256="0" * 64), "not bound to this plan"),
        (_allowance(schema="X"), "schema differs"),
        (_allowance(extra=1), "fields differ"),
        (_allowance(max_sessions=0), "outside the plan"),
        (_allowance(max_sessions=PLAN["session_count"] + 1), "outside the plan"),
        (_allowance(max_sessions=True), "outside the plan"),
        (_allowance(max_sessions=2.5), "outside the plan"),
        (_allowance(cumulative_cap_cu=0), "positive number"),
        (_allowance(cumulative_cap_cu=-1), "positive number"),
        (_allowance(cumulative_cap_cu=True), "positive number"),
        (_allowance(cumulative_cap_cu=PLAN["compute_units"]["cumulative_cap"] + 0.01), "exceeds"),
        (_allowance(max_cu_per_session="lots"), "positive number"),
        (_allowance(allow_concurrent_unrelated_usage="yes"), "boolean"),
        (_allowance(valid_until_utc="tomorrow"), "not a timestamp"),
        (_allowance(valid_until_utc="2026-12-01T00:00:00"), "timezone"),
        (_allowance(valid_until_utc=(NOW - timedelta(seconds=1)).isoformat()), "expired"),
        (_allowance(valid_until_utc=NOW.isoformat()), "expired"),
        (_allowance(cumulative_cap_cu=0.1), "cumulative"),
        (_allowance(max_cu_per_session=0.1), "below the plan bound"),
    ],
)
def test_allowance_can_only_tighten_never_widen_and_fails_closed(
    allowance: dict[str, Any], message: str
) -> None:
    with pytest.raises(execution.AdmissionError, match=message):
        _admit(allowance)


@pytest.mark.parametrize(
    ("snapshot", "message"),
    [
        ({**QUIET, "balance": 0.2}, "live balance"),
        ({**QUIET, "usage_rate_cu_per_hour": 6.7}, "not attributable"),
    ],
)
def test_live_account_state_still_gates_every_session(
    snapshot: dict[str, Any], message: str
) -> None:
    with pytest.raises(execution.AdmissionError, match=message):
        _admit(_allowance(), snapshot=snapshot)
    assert _admit(
        _allowance(allow_concurrent_unrelated_usage=True),
        snapshot={**QUIET, "usage_rate_cu_per_hour": 6.7},
    )["admitted"]


def test_allowance_session_count_and_cap_exhaustion_stop_admission() -> None:
    ledger = execution.ledger_new(PLAN)
    for index in (1, 2, 3):
        ledger["sessions"].append({"index": index, "compute_units_spent": 0.1})
    with pytest.raises(execution.AdmissionError, match="allowance session count is exhausted"):
        _admit(_allowance(max_sessions=3), ledger=ledger, index=4)
    per = PLAN["compute_units"]["per_session_cap"]
    with pytest.raises(execution.AdmissionError, match="cumulative"):
        _admit(_allowance(cumulative_cap_cu=0.3 + per - 0.01), ledger=ledger, index=4)

    full = execution.ledger_new(PLAN)
    for index in range(1, PLAN["session_count"] + 1):
        full["sessions"].append({"index": index, "compute_units_spent": 0.0})
    with pytest.raises(execution.AdmissionError, match="planned V3 session count is exhausted"):
        _admit(_allowance(), ledger=full, index=PLAN["session_count"] + 1)


def test_a_prior_cost_overrun_blocks_further_sessions() -> None:
    ledger = execution.ledger_new(PLAN)
    over = PLAN["compute_units"]["per_session_cap"] + 0.01
    ledger["sessions"].append({"index": 1, "compute_units_spent": over})
    with pytest.raises(execution.AdmissionError, match="exceeded its bounded cost"):
        _admit(_allowance(), ledger=ledger, index=2)


def test_ledger_session_identity_drift_is_rejected() -> None:
    ledger = execution.ledger_new(PLAN)
    ledger["sessions"].append({"index": 2, "compute_units_spent": 0.0})
    with pytest.raises(execution.AdmissionError, match="inconsistent"):
        _admit(_allowance(), ledger=ledger, index=2)
    with pytest.raises(execution.AdmissionError, match="not bound"):
        _admit(_allowance(), ledger={**execution.ledger_new(PLAN), "plan_sha256": "x"})
    with pytest.raises(execution.AdmissionError, match="next unused"):
        _admit(_allowance(), index=2)
    other = execution.build_plan(
        PROTOCOL, PREFLIGHT, execution.RuntimeBounds(cost_buffer_cu=0.06), live_rate_cu_per_hour=0.0
    )
    assert other["plan_sha256"] != PLAN["plan_sha256"]
    with pytest.raises(execution.AdmissionError, match="not bound to this plan"):
        execution.admit(
            plan=other,
            ledger=execution.ledger_new(other),
            authorization=_allowance(),
            snapshot=QUIET,
            session_index=1,
            now=NOW,
        )


# ---- simulated provider -----------------------------------------------------------------


class SimClock:
    """Worst-case session clock: time is the summed cost bounds of this session's commits."""

    def __init__(self, checkpoint: Path) -> None:
        self.checkpoint = checkpoint
        self.base = self._committed()

    def _committed(self) -> int:
        return self.checkpoint.read_bytes().count(b"\n") if self.checkpoint.exists() else 0

    def __call__(self) -> float:
        costs = PLAN["item_cost_bounds_seconds"]
        total = 0.0
        for item in ITEMS[self.base : self._committed()]:
            total += costs["QUALIFICATION" if item.key == "QUALIFICATION" else item.arm]
        return total


class FakeColab:
    """A provider simulation: the 'work' stage runs the real worker on a remote copy."""

    def __init__(
        self,
        root: Path,
        *,
        items_per_session: int | None = None,
        tear_after: bool = False,
        cost_per_session: float = 0.29,
    ) -> None:
        self.root = root
        self.items_per_session = items_per_session  # None: bounded by the plan's session clock
        self.tear_after = tear_after
        self.cost_per_session = cost_per_session
        self.active: dict[str, dict[str, Any]] = {"res338-fits": {"files": {}}}
        self.created: list[str] = []
        self.stopped: list[str] = []
        self.balance = 87.08
        self.rate_when_allocated = 1.15
        self.rate_after_prepare: float | None = None
        self.balance_drop_after_prepare = 0.0
        self.fail_download = False
        self.fail_new = False
        self.fail_stop = False
        self.remote_mutator: Any = None
        self.work_returncode: int | None = None
        self.backend_factory: Any = _Backend

    def snapshot(self) -> dict[str, Any]:
        ours = [n for n in self.active if n.startswith("res541")]
        rate = self.rate_when_allocated if ours else 0.0
        if ours and self.rate_after_prepare is not None and self._prepared:
            rate = self.rate_after_prepare
        return {
            "balance": self.balance - (self.balance_drop_after_prepare if self._prepared else 0.0),
            "usage_rate_cu_per_hour": rate,
            "active_sessions": [{"name": n} for n in self.active if n.startswith("res541")],
        }

    _prepared = False

    def new(self, name: str) -> bool:
        if self.fail_new:
            return False
        self.created.append(name)
        self._prepared = False
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
            self._prepared = True
            return {"returncode": 0, "timed_out": False}
        remote = self.root / name / Path(execution.REMOTE_CHECKPOINT).name
        kwargs: dict[str, Any]
        if self.items_per_session is not None:
            kwargs = {
                "deadline": float("inf"),
                "item_cost_bounds": COSTS,
                "stop_after": self.items_per_session,
            }
        else:
            kwargs = {
                "deadline": float(PLAN["generation_seconds_per_session"]),
                "item_cost_bounds": PLAN["item_cost_bounds_seconds"],
                "clock": SimClock(remote),
            }
        status = worker.run_worker(
            protocol=PROTOCOL,
            items=ITEMS,
            checkpoint=remote,
            backend=self.backend_factory(),
            **kwargs,
        )
        if self.tear_after:
            with remote.open("ab") as handle:
                handle.write(b'{"schema":"RES541_A02_V3_CHECKPOINT_LINE_V1","seq":')
            return {"returncode": None, "timed_out": True}
        if self.remote_mutator:
            self.remote_mutator(remote)
        if self.work_returncode is not None:
            return {"returncode": self.work_returncode, "timed_out": False}
        return {
            "returncode": 3 if status["status"] == "QUALIFICATION_FAILED" else 0,
            "timed_out": False,
        }

    def download(self, name: str, remote: str, local: Path) -> bool:
        source = self.root / name / Path(remote).name
        if self.fail_download or not source.exists():
            return False
        shutil.copyfile(source, local)
        return True

    def stop(self, name: str) -> bool:
        self.stopped.append(name)
        self.balance -= self.cost_per_session
        if self.fail_stop:
            return False
        self.active.pop(name, None)
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
        authorization=_allowance() if auth == "default" else auth,
        session_index=index,
        run_dir=tmp_path / "run",
        source_archive=archive,
        binding={"plan_sha256": PLAN["plan_sha256"], "item_cost_bounds": COSTS},
        now=NOW,
    )


def _campaign(tmp_path: Path, client: FakeColab, allowance: Any = "default") -> dict[str, Any]:
    archive = tmp_path / "source.tar"
    archive.write_bytes(b"source")
    return execution.run_campaign(
        client=client,
        plan=PLAN,
        ledger_path=tmp_path / "ledger.json",
        authorization=_allowance() if allowance == "default" else allowance,
        run_dir=tmp_path / "run",
        source_archive=archive,
        binding={"plan_sha256": PLAN["plan_sha256"], "item_cost_bounds": COSTS},
        now=NOW,
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
    with pytest.raises(execution.AdmissionError, match="no owner campaign allowance"):
        _session(tmp_path, client, 1, auth=None)
    assert client.stopped == [] and client.created == [] and set(client.active) == {"res338-fits"}
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


# ---- the complete bounded campaign ------------------------------------------------------

BOUNDARIES = [session["end_item"] for session in PLAN["sessions"]]


def _drift_revision(remote: Path) -> None:
    """A forged remote checkpoint, re-chained so every hash is valid but a revision differs."""
    head = worker.GENESIS
    lines: list[str] = []
    for seq, line in enumerate(remote.read_bytes().split(b"\n")[:-1]):
        entry = json.loads(line)
        entry.pop("line_sha256")
        if "model_revision" in entry["record"]:
            entry["record"]["model_revision"] = "f" * 40
        entry.update(seq=seq, prev_sha256=head)
        head = worker._line_hash(entry)
        lines.append(v3.canonical({**entry, "line_sha256": head}))
    remote.write_text("\n".join(lines) + "\n")


def test_nine_session_campaign_covers_every_item_exactly_once(tmp_path: Path) -> None:
    client = FakeColab(tmp_path / "remote")
    result = _campaign(tmp_path, client)
    assert result["status"] == "COMPLETE" and result["committed"] == len(ITEMS) == 581
    assert len(result["sessions"]) == PLAN["session_count"] == 9
    # Worst-case timing reproduces the plan's packing exactly, with no session left idle.
    assert [s["committed_after"] for s in result["sessions"]] == BOUNDARIES
    assert len(client.created) == 9 and client.created == client.stopped
    assert "res338-fits" not in client.stopped and set(client.active) == {"res338-fits"}
    entries = worker.read_checkpoint(tmp_path / "run" / "checkpoint.jsonl", ITEMS)["entries"]
    assert [e["item"] for e in entries] == [item.id for item in ITEMS]  # none skipped, none doubled
    assert len({e["item"] for e in entries}) == len(entries)
    markers = sorted((tmp_path / "run").glob("session-*-used.json"))
    assert len(markers) == 9
    ledger = json.loads((tmp_path / "ledger.json").read_text())
    assert [s["index"] for s in ledger["sessions"]] == list(range(1, 10))
    assert (
        sum(s["compute_units_spent"] for s in ledger["sessions"])
        <= (PLAN["compute_units"]["cumulative_cap"])
    )
    report = worker.score_checkpoint(PROTOCOL, tmp_path / "run" / "checkpoint.jsonl")
    assert report["decision"]["decision"] == "ADOPT_REPAIRED_CONTRACT_WITH_CONSTRAINED_DECODING"
    heldout = [e for e in entries if e["item"].startswith("HELDOUT:")]
    assert len(heldout) == 560 and len({e["record"]["example_id"] for e in heldout}) == 280


def test_the_nine_session_result_equals_one_uninterrupted_run(tmp_path: Path) -> None:
    client = FakeColab(tmp_path / "remote")
    _campaign(tmp_path, client)
    single = tmp_path / "single.jsonl"
    worker.run_worker(
        protocol=PROTOCOL, items=ITEMS, checkpoint=single, backend=_Backend(),
        deadline=float("inf"), item_cost_bounds=COSTS,
    )  # fmt: skip

    def content(path: Path) -> list[Any]:
        return [
            (e["item"], {k: v for k, v in e["record"].items() if k != "seconds"})
            for e in worker.read_checkpoint(path, ITEMS)["entries"]
        ]

    assert content(tmp_path / "run" / "checkpoint.jsonl") == content(single)


def test_campaign_stops_at_a_torn_write_then_a_new_invocation_resumes(tmp_path: Path) -> None:
    client = FakeColab(tmp_path / "remote", tear_after=True)
    first = _campaign(tmp_path, client)
    assert first["status"] == "STOPPED_ON_ANOMALY" and len(first["sessions"]) == 1
    assert "work stage did not finish cleanly" in first["anomaly"]
    assert len(client.created) == 1  # the failed session was not retried
    client.tear_after = False
    resumed = _campaign(tmp_path, client)
    assert resumed["status"] == "COMPLETE" and resumed["committed"] == 581
    assert len(client.created) == 1 + 8  # 46 items were already safe; 8 more sessions finish
    entries = worker.read_checkpoint(tmp_path / "run" / "checkpoint.jsonl", ITEMS)["entries"]
    assert [e["item"] for e in entries] == [item.id for item in ITEMS]


@pytest.mark.parametrize(
    ("configure", "anomaly"),
    [
        (lambda c: setattr(c, "fail_new", True), "allocation failed; no retry"),
        (lambda c: setattr(c, "rate_when_allocated", 2.0), "exceeds the admission ceiling"),
        (lambda c: setattr(c, "rate_after_prepare", 3.0), "rate rose above the admission ceiling"),
        (lambda c: setattr(c, "balance_drop_after_prepare", 5.0), "spend already exceeds"),
        (lambda c: setattr(c, "fail_download", True), "evidence was not adopted"),
        (lambda c: setattr(c, "fail_stop", True), "teardown is not confirmed"),
        (lambda c: setattr(c, "work_returncode", 3), "work stage did not finish cleanly"),
        (lambda c: setattr(c, "cost_per_session", 0.9), "cost exceeded its bound"),
        (lambda c: setattr(c, "remote_mutator", _drift_revision), "evidence was not adopted"),
    ],
)
def test_every_anomaly_stops_the_campaign_without_a_retry(
    tmp_path: Path, configure: Any, anomaly: str
) -> None:
    client = FakeColab(tmp_path / "remote")
    configure(client)
    result = _campaign(tmp_path, client)
    assert result["status"] == "STOPPED_ON_ANOMALY", result
    assert anomaly in result["anomaly"]
    assert len(result["sessions"]) == 1
    assert len(client.created) <= 1  # never a second allocation after the anomaly
    assert len(client.stopped) == 1  # teardown targets only the exact session name
    assert client.stopped[0].startswith("res541-a02-v3-") and client.stopped[0] != "res338-fits"
    assert set(client.active) == {"res338-fits"} or client.fail_stop


def test_revision_drift_in_remote_evidence_is_rejected_and_local_evidence_survives(
    tmp_path: Path,
) -> None:
    client = FakeColab(tmp_path / "remote")
    assert _campaign(tmp_path, client, _allowance(max_sessions=1))["status"] == "NOT_ADMITTED"
    local = tmp_path / "run" / "checkpoint.jsonl"
    kept = local.read_bytes()
    client.remote_mutator = _drift_revision
    result = _campaign(tmp_path, client, _allowance(max_sessions=2))
    assert result["status"] == "STOPPED_ON_ANOMALY"
    assert local.read_bytes() == kept
    ledger = json.loads((tmp_path / "ledger.json").read_text())
    assert ledger["sessions"][-1]["committed_items"] == len(
        worker.read_checkpoint(local, ITEMS)["entries"]
    )


def test_cost_overrun_is_recorded_and_blocks_a_later_invocation(tmp_path: Path) -> None:
    client = FakeColab(tmp_path / "remote", cost_per_session=0.9)
    first = _campaign(tmp_path, client)
    assert "cost exceeded its bound" in first["anomaly"]
    client.cost_per_session = 0.29
    second = _campaign(tmp_path, client)
    assert second["status"] == "NOT_ADMITTED" and "exceeded its bounded cost" in second["reason"]
    assert len(client.created) == 1


def test_allowance_session_limit_bounds_the_campaign(tmp_path: Path) -> None:
    client = FakeColab(tmp_path / "remote")
    result = _campaign(tmp_path, client, _allowance(max_sessions=3))
    assert result["status"] == "NOT_ADMITTED"
    assert "allowance session count is exhausted" in result["reason"]
    assert len(client.created) == 3 and result["committed"] == BOUNDARIES[2]


def test_allowance_cap_bounds_the_campaign_before_the_cap_is_exceeded(tmp_path: Path) -> None:
    per = PLAN["compute_units"]["per_session_cap"]
    client = FakeColab(tmp_path / "remote", cost_per_session=0.3)
    result = _campaign(tmp_path, client, _allowance(cumulative_cap_cu=per * 2 + 0.01))
    assert result["status"] == "NOT_ADMITTED" and "cumulative" in result["reason"]
    assert len(client.created) == 2
    spent = sum(
        s["compute_units_spent"]
        for s in json.loads((tmp_path / "ledger.json").read_text())["sessions"]
    )
    assert spent <= per * 2 + 0.01


def test_expired_or_missing_allowance_allocates_nothing(tmp_path: Path) -> None:
    client = FakeColab(tmp_path / "remote")
    expired = _allowance(valid_until_utc=(NOW - timedelta(minutes=1)).isoformat())
    assert _campaign(tmp_path, client, expired)["status"] == "NOT_ADMITTED"
    with pytest.raises(execution.AdmissionError, match="no owner campaign allowance"):
        _campaign(tmp_path, client, None)
    assert client.created == [] and client.stopped == []


def test_a_preexisting_session_with_the_exact_name_is_never_adopted(tmp_path: Path) -> None:
    client = FakeColab(tmp_path / "remote")
    name = f"res541-a02-v3-{PLAN['plan_sha256'][:8]}-001"
    client.active[name] = {"files": {}}
    refused = _campaign(tmp_path, client)  # usage is not attributable while it exists
    assert refused["status"] == "NOT_ADMITTED" and client.created == []
    result = _campaign(tmp_path, client, _allowance(allow_concurrent_unrelated_usage=True))
    assert result["status"] == "STOPPED_ON_ANOMALY" and "already exists" in result["anomaly"]
    assert client.created == [] and client.stopped == []  # a session we did not create stays
    assert name in client.active


def test_failed_cache_qualification_ends_the_campaign_before_any_protected_work(
    tmp_path: Path,
) -> None:
    client = FakeColab(tmp_path / "remote")
    seen: list[_Backend] = []

    def bad_backend() -> _Backend:
        backend = _Backend(reference_offset=0.01)
        seen.append(backend)
        return backend

    client.backend_factory = bad_backend
    result = _campaign(tmp_path, client)
    assert result["status"] == "STOPPED_ON_ANOMALY"
    assert len(client.created) == 1
    users = {u for backend in seen for u in backend.touched}
    protected = {v3.user_message(e["request"]) for e in decision.heldout_examples(PROTOCOL)}
    assert users and not users & protected
