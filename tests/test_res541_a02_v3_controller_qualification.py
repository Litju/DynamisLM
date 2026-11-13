"""Deterministic state-transition / fault-injection qualification of the whole controller.

Every fault below is driven through the real ``run_campaign``/``run_session`` code, and each one
must preserve the two controller properties:

* Safety - no allocation beyond the single admitted one, no unmonitored paid work, no admission
  after uncertain cost or teardown, no adoption of a corrupt checkpoint, no retry.
* Liveness - a healthy session that reaches its checkpoint boundary tears down cleanly and the
  next approved session starts without any false terminal anomaly.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_execution as execution
from scripts import a02_v3_worker as worker

from test_res541_a02_v3_execution import (
    ITEMS,
    PLAN,
    _allowance,
    _campaign,
    _drift_revision,
    _session,
)
from test_res541_a02_v3_supervision import Supervised


@pytest.fixture(autouse=True)
def _env(monkeypatch: Any) -> None:
    monkeypatch.setattr(execution, "COST_POLL_SECONDS", 0.01)
    monkeypatch.setattr(
        execution, "source_identity", lambda: {"commit": "a" * 40, "tree": "b" * 40}
    )


def _assert_safe(tmp_path: Path, client: Supervised, result: dict[str, Any]) -> None:
    """Invariants that hold after any faulted campaign."""
    assert result["status"] in {"STOPPED_ON_ANOMALY", "NOT_ADMITTED"}
    assert len(client.created) <= 1  # an anomaly is never retried by the controller
    assert set(client.stopped) <= set(client.created)  # only the exact target was ever stopped
    assert "res338-fits" not in client.stopped  # unrelated sessions are never touched
    ledger = json.loads((tmp_path / "ledger.json").read_text())
    if client.created:
        assert len(ledger["sessions"]) == 1
    # the next invocation cannot allocate while the anomaly stands unless the anomaly was
    # clean evidence-only (checked per case by the caller)


def _faults() -> dict[str, Any]:
    def uploads_fail(c: Supervised) -> None:
        c.upload = lambda *a, **k: False  # type: ignore[method-assign]

    def nested_timeout(c: Supervised) -> None:
        original = c.exec_stage

        def stage(name: str, stage: str, timeout: int) -> dict[str, Any]:
            result = original(name, stage, timeout)
            if stage == "prepare":
                c.nested_prepare_timeout = True  # type: ignore[attr-defined]
            return result

        c.exec_stage = stage  # type: ignore[method-assign]
        original_download = c.download

        def download(name: str, remote: str, local: Path) -> bool:
            ok = original_download(name, remote, local)
            if ok and remote == execution.REMOTE_STATUS and "prepare-status" in local.name:
                data = json.loads(local.read_text())
                data["stages"][0]["timed_out"] = True  # CLI exit 0 but the child timed out
                local.write_text(json.dumps(data))
            return ok

        c.download = download  # type: ignore[method-assign]

    def no_ready(c: Supervised) -> None:
        original = c.download

        def download(name: str, remote: str, local: Path) -> bool:
            ok = original(name, remote, local)
            if ok and remote == execution.REMOTE_STATUS:
                data = json.loads(local.read_text())
                data["status"] = "NOT_READY"
                local.write_text(json.dumps(data))
            return ok

        c.download = download  # type: ignore[method-assign]

    def work_hangs(c: Supervised) -> None:
        c.block_work.set()
        c.rate_spike_on_work = False

    def over_budget(c: Supervised) -> None:
        c.balance_drop_after_prepare = 50.0

    def emergency_stop_fails(c: Supervised) -> None:
        c.block_work.set()
        c.rate_spike_on_work = True
        c.stop_always = False

    def corrupt_checkpoint(c: Supervised) -> None:
        def corrupt(remote: Path) -> None:
            data = remote.read_bytes()
            remote.write_bytes(data[: len(data) // 2] + b"X" + data[len(data) // 2 + 1 :])

        c.remote_mutator = corrupt

    def forked_checkpoint(c: Supervised) -> None:
        c.remote_mutator = _drift_revision

    def partial_download(c: Supervised) -> None:
        c.fail_download = True

    def uncertain_cost(c: Supervised) -> None:
        c.verify_script = [RuntimeError("inventory conflict")] * 500

    return {
        "uploads_fail": uploads_fail,
        "nested_prepare_timeout_with_cli_exit_zero": nested_timeout,
        "authenticated_ready_absent": no_ready,
        "work_hangs_after_preparation": work_hangs,
        "over_budget_detected_by_monitor": over_budget,
        "emergency_stop_fails": emergency_stop_fails,
        "corrupted_checkpoint": corrupt_checkpoint,
        "forked_checkpoint": forked_checkpoint,
        "partial_checkpoint_download": partial_download,
        "cost_uncertain_after_termination": uncertain_cost,
    }


@pytest.mark.parametrize("fault", sorted(_faults()))
def test_every_fault_is_safe_and_terminal(tmp_path: Path, fault: str) -> None:
    client = Supervised(tmp_path / "remote", items_per_session=3)
    _faults()[fault](client)
    result = _campaign(tmp_path, client)
    _assert_safe(tmp_path, client, result)
    local = tmp_path / "run" / "checkpoint.jsonl"
    if fault in {"corrupted_checkpoint", "forked_checkpoint", "partial_checkpoint_download"}:
        # a corrupt remote checkpoint is never adopted: local evidence stays absent or valid
        assert not local.exists() or worker.read_checkpoint(local, ITEMS)["entries"] == []
    # A second invocation against a healthy provider: uncertain cost or teardown must stay terminal.
    fresh = Supervised(tmp_path / "remote2", items_per_session=3)
    again = _campaign(tmp_path, fresh)
    if fault in {"emergency_stop_fails", "cost_uncertain_after_termination"}:
        assert again["status"] == "NOT_ADMITTED" and fresh.created == []
        entry = json.loads((tmp_path / "ledger.json").read_text())["sessions"][0]
        assert entry["cost_status"] == "UNKNOWN" and entry["teardown_verified"] is False


def test_unadmitted_source_binding_never_allocates(tmp_path: Path) -> None:
    client = Supervised(tmp_path / "remote", items_per_session=3)
    other = _allowance(source_identity={"commit": "c" * 40, "tree": "d" * 40})
    with pytest.raises(execution.AdmissionError):
        _campaign(tmp_path, client, other)
    assert client.created == []


def test_ledger_with_different_source_identity_is_refused(tmp_path: Path) -> None:
    client = Supervised(tmp_path / "remote", items_per_session=3)
    assert _session(tmp_path, client, 1)["target_absent_after_stop"] is True
    ledger_path = tmp_path / "ledger.json"
    ledger = json.loads(ledger_path.read_text())
    ledger["source_identity"] = {"commit": "e" * 40, "tree": "f" * 40}
    ledger_path.write_text(json.dumps(ledger))
    with pytest.raises(execution.AdmissionError, match="ledger source identity differs"):
        _session(tmp_path, client, 2)
    assert len(client.created) == 1


def test_liveness_healthy_sessions_chain_to_the_complete_checkpoint(tmp_path: Path) -> None:
    client = Supervised(tmp_path / "remote", items_per_session=200)
    result = _campaign(tmp_path, client)
    assert result["status"] == "COMPLETE" and result["committed"] == len(ITEMS)
    assert [s["committed_after"] for s in result["sessions"]] == [200, 400, len(ITEMS)]
    for index in (1, 2, 3):
        control = json.loads((tmp_path / f"run/session-{index:03d}-control.json").read_text())
        assert "failure" not in control and "monitor_failure" not in control
        assert control["watchdog_disarmed"] is True
        assert control["lifecycle"][-1]["phase"] == "VERIFIED_STOPPED"
    created_before = list(client.created)
    again = _campaign(tmp_path, client)  # allocation stops at the complete checkpoint
    assert again["status"] == "COMPLETE" and client.created == created_before


def test_real_watchdog_subprocess_takes_over_and_is_recorded(tmp_path: Path) -> None:
    stub = tmp_path / "colab"
    log = tmp_path / "calls"
    stub.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$TEST_CALLS"\n')
    stub.chmod(0o755)
    receipt = tmp_path / "watchdog.json"
    script = """
import json, sys
from pathlib import Path
from scripts.a02_v3_execution import ColabCLI
client = ColabCLI()
watchdog = client.start_watchdog("exact-qualification-target", Path(sys.argv[1]))
client.finish_watchdog(watchdog, False)  # unverified absence: never disarm, hand over
print(json.dumps(client.watchdog_takeover))
"""
    done = subprocess.run(
        [sys.executable, "-c", script, str(receipt)],
        cwd=execution.ROOT,
        env={
            **os.environ,
            "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
            "TEST_CALLS": str(log),
            "RES541_WATCHDOG_RETRY_SECONDS": "0",
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    takeover = json.loads(done.stdout.strip().splitlines()[-1])
    assert takeover["receipt"]["phase"] in {"VERIFY_RETURNED", "RETRY_PENDING", "STOP_REQUESTED"}
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if json.loads(receipt.read_text()).get("phase") == "VERIFY_RETURNED":
            break
        time.sleep(0.1)
    final = json.loads(receipt.read_text())
    assert (
        final["phase"] == "VERIFY_RETURNED" and final["round"] == execution.WATCHDOG_ROUNDS
    )  # bounded
    assert "stop --session exact-qualification-target" in log.read_text()
    assert PLAN["session_count"] >= 1
