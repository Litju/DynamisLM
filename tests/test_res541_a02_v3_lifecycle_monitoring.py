from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_execution as execution
from scripts import a02_v3_supervision as supervision

from test_res541_a02_v3_execution import _campaign, _session
from test_res541_a02_v3_supervision import Supervised


@pytest.fixture(autouse=True)
def _env(monkeypatch: Any) -> None:
    monkeypatch.setattr(execution, "COST_POLL_SECONDS", 0.01)
    monkeypatch.setattr(execution, "RECONCILE_ATTEMPTS", 3)
    monkeypatch.setattr(
        execution, "source_identity", lambda: {"commit": "a" * 40, "tree": "b" * 40}
    )


class Racy(Supervised):
    """Provider whose inventory reads are not atomic and can be parked between reads."""

    def __init__(self, root: Path, **kwargs: Any) -> None:
        super().__init__(root, **kwargs)
        self.cut: str | None = None
        self.compare_counts = True
        self.armed = False
        self.parked = threading.Event()
        self.release = threading.Event()
        self.stranger_on_stop = False
        self.monitor_reads_after_stop = 0
        self.stop_done = False
        self.never_converge_after_stop = False
        self.hang_monitor_after_stop = False
        self.vanish_on_work = False
        self.monitor_polls = 0

    def _ours(self) -> list[str]:
        return [n for n in self.active if n.startswith("res541")]

    def snapshot(self) -> dict[str, Any]:
        in_monitor = threading.current_thread().name == "res541-cost-snapshot"
        if in_monitor:
            self.monitor_polls += 1
            if self.stop_done:
                self.monitor_reads_after_stop += 1
                if self.hang_monitor_after_stop:
                    time.sleep(0.5)
        if self.stop_done and self.never_converge_after_stop:
            raise supervision.InventoryMismatchError("inventories never converge")
        ours = self._ours()
        rate = self.rate_when_allocated if ours else 0.0
        balance = self.balance - (self.balance_drop_after_prepare if self._prepared else 0.0)
        usage_count = len(ours)
        if in_monitor and self.armed and self.cut == "usage_sessions":
            self.armed = False
            self.parked.set()
            self.release.wait(2)
        sessions = self._ours()
        if in_monitor and self.armed and self.cut == "sessions_assignments":
            self.armed = False
            self.parked.set()
            self.release.wait(2)
        assignments = self._ours()
        if sessions != assignments or (self.compare_counts and usage_count != len(assignments)):
            raise supervision.InventoryMismatchError("inventory reads differ")
        return {
            "balance": balance,
            "usage_rate_cu_per_hour": rate,
            "active_sessions": [{"name": n} for n in sessions],
        }

    def stop(self, name: str) -> bool:
        self.stopped.append(name)
        self.active.pop(name, None)
        self.balance -= self.cost_per_session
        self.stop_done = True
        self.release.set()
        if self.stranger_on_stop:
            self.active["res541-stranger"] = {"files": {}}
            deadline = time.monotonic() + 2
            baseline = self.monitor_reads_after_stop
            while self.monitor_reads_after_stop <= baseline and time.monotonic() < deadline:
                time.sleep(0.005)
        return True

    def exec_stage(self, name: str, stage: str, timeout: int) -> dict[str, Any]:
        if stage == "work" and self.vanish_on_work:
            self.active.pop(name, None)  # the target disappears without any stop request
            deadline = time.monotonic() + 3
            while not self.stopped and time.monotonic() < deadline:
                time.sleep(0.005)
            return {"returncode": None, "timed_out": True}
        result = super(Supervised, self).exec_stage(name, stage, timeout)
        if stage == "work" and self.cut:
            self.armed = True
            self.parked.wait(2)
        return result


@pytest.mark.parametrize("cut", ["usage_sessions", "sessions_assignments"])
def test_stop_between_inventory_reads_is_not_a_false_terminal_failure(
    tmp_path: Path, cut: str
) -> None:
    client = Racy(tmp_path / "remote", items_per_session=3)
    client.cut = cut
    state = _session(tmp_path, client, 1)
    assert "monitor_failure" not in state and "failure" not in state, state.get("failure")
    assert state["target_absent_after_stop"] is True and state["stopped"] is True
    assert state["transition_reconciliation"], "the straddled read must be reconciled, not ignored"
    phases = [h["phase"] for h in state["lifecycle"]]
    assert phases[-1] == "VERIFIED_STOPPED" and "STOP_REQUESTED" in phases


def test_consistent_but_stale_rate_across_a_stop_is_accepted_only_in_teardown(
    tmp_path: Path,
) -> None:
    client = Racy(tmp_path / "remote", items_per_session=3)
    client.cut = "usage_sessions"
    client.compare_counts = False  # usage read pre-stop, sessions+assignments post-stop: agree
    state = _session(tmp_path, client, 1)
    assert "monitor_failure" not in state and "failure" not in state, state.get("failure")


def test_target_vanishing_during_running_is_a_real_failure(tmp_path: Path) -> None:
    client = Racy(tmp_path / "remote", items_per_session=3)
    client.vanish_on_work = True
    state = _session(tmp_path, client, 1)
    assert any("uncertain" in f for f in state["monitor_failure"])
    assert "failure" in state


def test_unrelated_allocation_during_teardown_is_still_flagged(tmp_path: Path) -> None:
    client = Racy(tmp_path / "remote", items_per_session=3)
    client.stranger_on_stop = True
    state = _session(tmp_path, client, 1)
    assert any("unexpected provider usage" in f for f in state["monitor_failure"])
    assert "failure" in state


def test_hung_inventory_during_teardown_does_not_block_or_falsely_fail(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setattr(execution, "COST_SNAPSHOT_TIMEOUT_SECONDS", 0.05)
    client = Racy(tmp_path / "remote", items_per_session=3)
    client.hang_monitor_after_stop = True
    started = time.monotonic()
    state = _session(tmp_path, client, 1)
    assert time.monotonic() - started < 20  # teardown never waits on the hung snapshot
    assert "monitor_failure" not in state and "failure" not in state, state.get("failure")
    assert state["target_absent_after_stop"] is True


def test_conflicting_inventories_that_never_converge_fail_closed(tmp_path: Path) -> None:
    client = Racy(tmp_path / "remote", items_per_session=3)
    client.never_converge_after_stop = True
    result = _campaign(tmp_path, client)
    assert result["status"] == "STOPPED_ON_ANOMALY"
    ledger = json.loads((tmp_path / "ledger.json").read_text())
    assert ledger["sessions"][0]["cost_status"] == "UNKNOWN"
    client.never_converge_after_stop = False  # provider recovers; the ledger must still refuse
    again = _campaign(tmp_path, client)
    assert again["status"] == "NOT_ADMITTED" and len(client.created) == 1


def test_persistent_mismatch_while_running_is_a_real_failure(tmp_path: Path) -> None:
    client = Racy(tmp_path / "remote", items_per_session=3)
    client.compare_counts = True

    original = client.snapshot

    def broken() -> dict[str, Any]:
        if threading.current_thread().name == "res541-cost-snapshot" and client.created:
            raise supervision.InventoryMismatchError("persistent divergence while running")
        return original()

    client.snapshot = broken  # type: ignore[method-assign]
    state = _session(tmp_path, client, 1)
    assert any("InventoryMismatchError" in f for f in state.get("monitor_failure", []))


def test_normal_teardown_is_followed_by_a_clean_next_session_admission(tmp_path: Path) -> None:
    client = Racy(tmp_path / "remote", items_per_session=200)
    client.cut = "sessions_assignments"
    result = _campaign(tmp_path, client)
    assert result["status"] == "COMPLETE", result
    assert len(client.created) >= 2
    for index in range(1, len(client.created) + 1):
        control = json.loads((tmp_path / f"run/session-{index:03d}-control.json").read_text())
        assert "monitor_failure" not in control and "failure" not in control


class Creating(Supervised):
    """The provider creates the target while ``new()`` is still running."""

    def __init__(self, root: Path, *, mismatching_reads: int, **kwargs: Any) -> None:
        super().__init__(root, **kwargs)
        self.mismatching_reads = mismatching_reads
        self.creating = False

    def new(self, name: str) -> bool:
        self.creating = True
        deadline = time.monotonic() + 1.5
        reads = self.monitor_reads
        while self.monitor_reads < reads + 3 and time.monotonic() < deadline:
            time.sleep(0.005)
        self.creating = False
        return super().new(name)

    monitor_reads = 0

    def snapshot(self) -> dict[str, Any]:
        if threading.current_thread().name == "res541-cost-snapshot":
            self.monitor_reads += 1
            if self.creating and self.monitor_reads <= self.mismatching_reads + 1:
                raise supervision.InventoryMismatchError("target appeared between reads")
            if self.creating and self.mismatching_reads > 100:
                raise supervision.InventoryMismatchError("never converges")
        return super().snapshot()


def test_inventory_mismatch_during_allocation_is_not_a_false_terminal_failure(
    tmp_path: Path,
) -> None:
    client = Creating(tmp_path / "remote", mismatching_reads=2, items_per_session=3)
    state = _session(tmp_path, client, 1)
    assert "monitor_failure" not in state and "failure" not in state, state.get("failure")
    assert state["transition_reconciliation"]


def test_inventories_that_never_converge_during_allocation_still_fail_closed(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setattr(execution, "ALLOCATION_UNRESOLVED_LIMIT", 1)
    monkeypatch.setattr(execution, "RECONCILE_ATTEMPTS", 1)
    client = Creating(tmp_path / "remote", mismatching_reads=10**6, items_per_session=3)
    state = _session(tmp_path, client, 1)
    assert any("never converged" in f for f in state.get("monitor_failure", []))
    assert "failure" in state and state["target_absent_after_stop"] is True
