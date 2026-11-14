from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_execution as execution
from scripts import a02_v3_supervision as supervision

from test_res541_a02_v3_execution import FakeColab, _campaign, _session


@pytest.fixture(autouse=True)
def _fast(monkeypatch: Any) -> None:
    monkeypatch.setattr(execution, "COST_POLL_SECONDS", 0.01)
    monkeypatch.setattr(execution, "RECONCILE_ATTEMPTS", 2)


class Supervised(FakeColab):
    """FakeColab with observable watchdog disposition and scripted provider misbehaviour."""

    def __init__(self, root: Path, **kwargs: Any) -> None:
        super().__init__(root, **kwargs)
        self.disarm_requests: list[bool] = []
        self.stop_always: Any = None  # False or an Exception: every stop misbehaves
        self.stop_script: list[Any] = []  # True/False/Exception per stop call; empty -> normal
        self.verify_script: list[Any] = []
        self.block_work = threading.Event()
        self.hang_seconds = 5.0  # a blocked work stage gives up only after this long
        self.rate_spike_on_work = False

    def finish_watchdog(self, watchdog: Any, verified: bool) -> None:
        self.disarm_requests.append(verified)
        super().finish_watchdog(watchdog, verified)

    def stop(self, name: str) -> bool:
        self.stopped.append(name)
        if self.stop_always is not None:
            if isinstance(self.stop_always, Exception):
                raise self.stop_always
            return False
        if self.stop_script:
            step = self.stop_script.pop(0)
            if isinstance(step, Exception):
                raise step
            if step is False:
                return False
        self.active.pop(name, None)
        return True

    def verify_absent(self, name: str, *, allocation_attempted: bool = True) -> bool:
        if self.verify_script:
            step = self.verify_script.pop(0)
            if isinstance(step, Exception):
                raise step
            if step is False:
                return False
        return name not in self.active

    def exec_stage(self, name: str, stage: str, timeout: int) -> dict[str, Any]:
        if stage == "work" and self.block_work.is_set():
            self.rate_after_prepare = 2.0 if self.rate_spike_on_work else None
            deadline = time.monotonic() + self.hang_seconds
            while name in self.active and time.monotonic() < deadline:
                time.sleep(0.005)
            return {"returncode": None, "timed_out": True}
        return super().exec_stage(name, stage, timeout)


def _blocked_hung_work(client: Supervised) -> None:
    client.block_work.set()
    client.rate_spike_on_work = True


def test_failed_stop_during_blocked_work_escalates_and_keeps_watchdog_armed(
    tmp_path: Path,
) -> None:
    client = Supervised(tmp_path / "remote")
    _blocked_hung_work(client)
    client.stop_always = False  # the provider never honours any stop
    state = _session(tmp_path, client, 1)
    assert "failure" in state and state["teardown_uncertain"] is True
    assert state["target_absent_after_stop"] is False
    assert client.disarm_requests == [False]  # never disarmed on an attempted stop
    assert state["watchdog_disarmed"] is False
    assert state["emergency_stop"], "the monitor must escalate, not stop once and exit"
    assert state["lifecycle"][-1]["phase"] == "UNCERTAIN"
    assert state["terminal_failures"]
    assert len(state["termination_attempts"]) == execution.TERMINATION_ROUNDS  # bounded
    assert state["abandoned_operations"]  # the blocked exec_stage was abandoned, not awaited


def test_stop_exception_is_recorded_and_never_treated_as_success(tmp_path: Path) -> None:
    client = Supervised(tmp_path / "remote")
    _blocked_hung_work(client)
    client.stop_always = RuntimeError("boom")
    state = _session(tmp_path, client, 1)
    assert state["teardown_uncertain"] is True
    assert any("stop_error" in a for a in state["termination_attempts"])
    assert client.disarm_requests == [False]


def test_delayed_provider_termination_is_verified_before_disarm(tmp_path: Path) -> None:
    client = Supervised(tmp_path / "remote")
    client.stop_script = [False, False]  # slow to die: third stop works
    client.verify_script = [False, False]
    state = _session(tmp_path, client, 1)
    assert state["target_absent_after_stop"] is True
    assert [a["verified_absent"] for a in state["termination_attempts"]] == [False, False, True]
    assert client.disarm_requests == [True]


def test_repeated_inventory_uncertainty_blocks_disarm_and_next_allocation(
    tmp_path: Path,
) -> None:
    client = Supervised(tmp_path / "remote")
    client.verify_script = [RuntimeError("inventory conflict")] * 500
    result = _campaign(tmp_path, client)
    assert result["status"] == "STOPPED_ON_ANOMALY"
    assert client.disarm_requests == [False]
    assert len(client.created) == 1
    again = _campaign(tmp_path, client)  # a second invocation must not allocate either
    assert again["status"] == "NOT_ADMITTED"
    assert len(client.created) == 1


def test_stop_returning_true_is_not_proof_of_absence(tmp_path: Path) -> None:
    client = Supervised(tmp_path / "remote")

    def lying_stop(name: str) -> bool:
        client.stopped.append(name)
        return True  # claims success but the session persists

    client.stop = lying_stop  # type: ignore[method-assign]
    state = _session(tmp_path, client, 1)
    assert state["stopped"] is True and state["target_absent_after_stop"] is False
    assert client.disarm_requests == [False]


def test_watchdog_takeover_is_recorded_in_control_evidence(tmp_path: Path) -> None:
    client = Supervised(tmp_path / "remote")
    client.watchdog_takeover = {"phase": "VERIFY_RETURNED", "target_absent": True}  # type: ignore[attr-defined]
    client.verify_script = [False] * 10
    state = _session(tmp_path, client, 1)
    assert state["watchdog_disarmed"] is False
    assert state["watchdog_takeover"]["phase"] == "VERIFY_RETURNED"
    assert (tmp_path / "run" / "session-001-control.json").exists()


def test_no_allocation_without_an_enforceable_watchdog(tmp_path: Path) -> None:
    client = Supervised(tmp_path / "remote")
    client.start_watchdog = lambda name, receipt: None  # type: ignore[method-assign]
    state = _session(tmp_path, client, 1)
    assert client.created == []
    assert "no enforceable independent watchdog" in state["failure"]


def test_no_work_when_the_monitor_heartbeat_is_stale(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(execution, "SUPERVISOR_HEARTBEAT_SLACK_SECONDS", -10_000)
    client = Supervised(tmp_path / "remote")
    state = _session(tmp_path, client, 1)
    assert client.created == []
    assert "no live resource supervisor" in state["failure"]


def test_lifecycle_refuses_work_after_terminal_failure() -> None:
    lifecycle = supervision.SessionLifecycle()
    lifecycle.require_work_permitted("upload")
    lifecycle.fail("budget guard")
    with pytest.raises(supervision.SupervisionError):
        lifecycle.require_work_permitted("upload")
    with pytest.raises(supervision.SupervisionError):
        supervision.run_cancellable(lambda: True, lifecycle, "work", supervisor_ok=lambda: True)


def test_verified_stopped_is_final_and_bounded_call_abandons_hangs() -> None:
    lifecycle = supervision.SessionLifecycle()
    for phase in (
        supervision.Phase.STOP_REQUESTED,
        supervision.Phase.TEARDOWN_VERIFICATION,
        supervision.Phase.VERIFIED_STOPPED,
    ):
        assert lifecycle.transition(phase)
    assert lifecycle.transition(supervision.Phase.RUNNING) is False
    assert lifecycle.phase is supervision.Phase.VERIFIED_STOPPED
    gate = threading.Event()
    with pytest.raises(supervision.CallTimeoutError):
        supervision.bounded_call(gate.wait, 0.05, "hang")
    gate.set()


@pytest.fixture(autouse=True)
def _clean_source(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        execution, "source_identity", lambda: {"commit": "a" * 40, "tree": "b" * 40}
    )


def test_a_watchdog_that_exited_after_ready_permits_no_allocation(tmp_path: Path) -> None:
    client = Supervised(tmp_path / "remote")
    client.watchdog_alive_flag = False  # READY was printed, then the process died
    state = _session(tmp_path, client, 1)
    assert client.created == []
    assert "no live resource supervisor" in state["failure"]


def test_a_watchdog_dying_during_paid_work_interrupts_it_and_tears_down(
    tmp_path: Path,
) -> None:
    client = Supervised(tmp_path / "remote", items_per_session=3)
    original = client.exec_stage
    never = threading.Event()  # only the test's cleanup sets this: the stage cannot finish alone

    def stage(name: str, stage: str, timeout: int) -> dict[str, Any]:
        if stage == "prepare":
            client.watchdog_alive_flag = False  # the watchdog dies while we are working
            never.wait(60)
            return {"returncode": None, "timed_out": True}
        return original(name, stage, timeout)

    client.exec_stage = stage  # type: ignore[method-assign]
    outcome: dict[str, Any] = {}
    runner = threading.Thread(target=lambda: outcome.update(_session(tmp_path, client, 1)))
    runner.start()
    runner.join(timeout=30)
    interrupted = not runner.is_alive()  # returned although the provider call never did
    never.set()
    runner.join(timeout=30)
    assert interrupted, "the blocked provider call was awaited instead of abandoned"
    assert "work" not in outcome and "failure" in outcome
    assert any("supervisor" in f or "watchdog" in f for f in outcome["terminal_failures"])
    assert outcome["target_absent_after_stop"] is True


def test_unverified_target_leaves_a_marker_that_blocks_every_later_run(tmp_path: Path) -> None:
    client = Supervised(tmp_path / "remote", items_per_session=3)
    client.verify_script = [False] * 500
    _session(tmp_path, client, 1)
    assert (tmp_path / "run" / "TEARDOWN-UNVERIFIED.json").exists()
    (tmp_path / "ledger.json").unlink()  # even with a pristine ledger, the marker refuses
    client.verify_script = []
    with pytest.raises(execution.AdmissionError, match="unverified target"):
        _session(tmp_path, client, 2)
    assert len(client.created) == 1


def test_an_allocation_still_in_flight_is_never_abandoned_or_disarmed(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setattr(execution, "ALLOCATION_WAIT_SECONDS", 0.2)
    client = Supervised(tmp_path / "remote", items_per_session=3)
    original = client.new

    def late_new(name: str) -> bool:
        time.sleep(0.8)  # the provider creates the target long after supervision gave up waiting
        return original(name)

    client.new = late_new  # type: ignore[method-assign]
    state = _session(tmp_path, client, 1)
    assert state["allocation_unresolved"] is True
    assert state["target_absent_after_stop"] is False  # absence now proves nothing about later
    assert client.disarm_requests == [False] and state["watchdog_disarmed"] is False
    assert (tmp_path / "run" / "TEARDOWN-UNVERIFIED.json").exists()
    assert state["teardown_uncertain"] is True


def test_watchdog_death_during_evidence_recovery_aborts_recovery_promptly(
    tmp_path: Path,
) -> None:
    client = Supervised(tmp_path / "remote", items_per_session=3)
    original = client.download
    never = threading.Event()

    def download(name: str, remote: str, local: Path) -> bool:
        recovering = local.name.endswith("-status.json") and "prepare" not in local.name
        if recovering and remote == execution.REMOTE_STATUS:
            client.watchdog_alive_flag = False  # dies while the paid session is being drained
            never.wait(60)
        return original(name, remote, local)

    client.download = download  # type: ignore[method-assign]
    outcome: dict[str, Any] = {}
    runner = threading.Thread(target=lambda: outcome.update(_session(tmp_path, client, 1)))
    runner.start()
    runner.join(timeout=30)
    returned = not runner.is_alive()
    never.set()
    runner.join(timeout=30)
    assert returned, "recovery awaited a provider call after the watchdog died"
    assert outcome["target_absent_after_stop"] is True  # teardown still ran
    assert not isinstance(outcome["merge"], dict)  # evidence recovery was cut short, not adopted
    assert any("supervisor" in f or "watchdog" in f for f in outcome["terminal_failures"])


def test_the_monitor_itself_notices_a_dead_watchdog(tmp_path: Path) -> None:
    client = Supervised(tmp_path / "remote", items_per_session=3)
    client.block_work.set()  # work blocks until the target disappears
    original = client.exec_stage

    def stage(name: str, stage: str, timeout: int) -> dict[str, Any]:
        if stage == "work":
            client.watchdog_alive_flag = False
        return original(name, stage, timeout)

    client.exec_stage = stage  # type: ignore[method-assign]
    state = _session(tmp_path, client, 1)
    assert any("watchdog" in f or "supervisor" in f for f in state["terminal_failures"])
    assert state["target_absent_after_stop"] is True
