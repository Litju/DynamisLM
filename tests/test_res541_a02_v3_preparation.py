"""Real preparation children behind a deliberately misleading synthetic CLI (RES-541)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_contract as v3
from scripts import a02_v3_decision as decision
from scripts import a02_v3_execution as execution

from test_res541_a02_v3_execution import NOW, PLAN, PROTOCOL, FakeColab, _allowance


class SubprocessPrepare(FakeColab):
    def __init__(self, root: Path, mode: str):
        super().__init__(root, items_per_session=1)
        self.mode = mode
        self.work_called = False

    def exec_stage(self, name: str, stage: str, timeout: int) -> dict[str, Any]:
        if stage == "work":
            self.work_called = True
            return super().exec_stage(name, stage, timeout)
        root = self.root / name
        binding = json.loads((root / "a02-v3-binding.json").read_text())
        ready = {
            "status": "READY",
            "plan_sha256": binding["plan_sha256"],
            "runtime_qualification": {"qualified": True, "synthetic": True},
            "snapshot_path": "/synthetic/model",
            "weights": {
                "model_revision": decision.load_protocol()["candidate_model"]["revision"],
                "weight_files": [{"synthetic": True}],
                "support_files": {
                    k: {"sha256": v} for k, v in v3.load_profile()["tokenizer"]["files"].items()
                },
            },
        }
        child = (
            'import time,sys; print("Fetching pinned fixture; token=secret-value", '
            "file=sys.stderr,flush=True); time.sleep(5)"
            if self.mode == "timeout"
            else "import sys; sys.exit(7)"
            if self.mode == "exit"
            else "pass"
            if self.mode == "incomplete"
            else "from scripts import a02_v3_remote as r; r._write_status(" + repr(ready) + ")"
        )
        driver = f"""
import os,sys
from pathlib import Path
from types import SimpleNamespace
from scripts import a02_v3_remote as r
from scripts.a02_dev_remote import _run_bounded_child
r.SOURCE_ARCHIVE=Path({str(root / "a02-v3-source.tar")!r})
r.BINDING_PATH=Path({str(root / "a02-v3-binding.json")!r})
r.STATUS_PATH=Path({str(root / "a02-v3-status.json")!r})
r.CHECKPOINT=Path({str(root / "a02-v3-checkpoint.jsonl")!r})
r.SOURCE_DIR=Path({str(execution.ROOT)!r})
def child(command,*,cwd,env,timeout):
    env.update(A02_V3_CONTENT_ROOT={str(root)!r})
    return _run_bounded_child([sys.executable,'-c',{child!r}],cwd=cwd,env=env,timeout=1)
result=r.outer('prepare',180,SimpleNamespace(setup=lambda:None,child=child))
print(result)
# Emulate Colab exec: a nested failure does not change this CLI's exit status.
"""
        result = subprocess.run(
            [sys.executable, "-c", driver],
            cwd=execution.ROOT,
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == ("0" if self.mode == "ready" else "1")
        self._prepared = True
        return {"returncode": 0, "timed_out": False}

    def download(self, name: str, remote: str, local: Path) -> bool:
        if remote == execution.REMOTE_STATUS and not self.work_called:
            source = self.root / name / Path(remote).name
            if not source.is_file():
                return False
            shutil.copyfile(source, local)
            return True
        return super().download(name, remote, local)


@pytest.mark.parametrize("mode", ["timeout", "exit", "incomplete", "ready"])
def test_real_child_status_overrules_successful_cli(
    tmp_path: Path, monkeypatch: Any, mode: str
) -> None:
    monkeypatch.setattr(
        execution, "source_identity", lambda: {"commit": "a" * 40, "tree": "b" * 40}
    )
    archive = tmp_path / "source.tar"
    archive.write_bytes(b"synthetic-source")
    client = SubprocessPrepare(tmp_path / "provider", mode)
    state = execution.run_session(
        client=client,
        plan=PLAN,
        ledger_path=tmp_path / "ledger.json",
        authorization=_allowance(),
        session_index=1,
        run_dir=tmp_path / "run",
        source_archive=archive,
        binding=execution.remote_binding(PLAN, archive, "a" * 40),
        now=NOW,
    )
    assert state["prepare"]["returncode"] == 0
    assert state["target_absent_after_stop"] is True
    assert client.work_called is (mode == "ready")
    if mode != "ready":
        assert "failure" in state
        assert "work" not in state
        assert not (tmp_path / "run/checkpoint.jsonl").exists()
        status = state["prepare_status"]
        assert status["status"] == "EXECUTION_FAILED"
        if mode == "timeout":
            assert status["failure_category"] == "CHILD_TIMEOUT"
            assert status["stages"][-1]["timed_out"] is True
            assert "secret-value" not in json.dumps(status)
    else:
        assert "failure" not in state


@pytest.mark.parametrize(
    "fault", ["binding", "runtime", "missing_stage", "timeout", "revision", "tokenizer"]
)
def test_ready_status_requires_complete_bound_preparation(tmp_path: Path, fault: str) -> None:
    # Provider transport alone cannot authorize work with stale or incomplete status.
    from test_res541_a02_v3_execution import FakeColab

    client = FakeColab(tmp_path)
    name = "synthetic"
    root = tmp_path / name
    root.mkdir()
    binding = {"plan_sha256": "a" * 64}
    (root / "a02-v3-binding.json").write_text(json.dumps(binding))
    status_path = tmp_path / "status.json"
    assert client.download(name, execution.REMOTE_STATUS, status_path)
    status = json.loads(status_path.read_text())
    if fault == "binding":
        status["binding"] = {}
    elif fault == "runtime":
        status["runtime_qualification"]["qualified"] = False
    elif fault == "missing_stage":
        status.pop("stages")
    elif fault == "timeout":
        status["stages"][-1]["timed_out"] = True
    elif fault == "revision":
        status["weights"]["model_revision"] = "0" * 40
    else:
        status["weights"]["support_files"] = {}
    with pytest.raises(ValueError):
        execution.validate_prepared_status(status, binding, PROTOCOL)


def test_prepare_window_uses_censored_time_and_session_capacity() -> None:
    bounds = execution.RuntimeBounds(
        session_seconds=3600, exec_seconds=3300, cleanup_reserve_seconds=300
    )
    assert execution.derive_preparation_seconds([108, 155.097149113], bounds) == 660
    for observations in ([], [0], [True], [float("nan")], [float("inf")]):
        with pytest.raises(ValueError):
            execution.derive_preparation_seconds(observations, bounds)
    with pytest.raises(ValueError, match="cannot fit"):
        execution.derive_preparation_seconds([1000], bounds)


@pytest.mark.parametrize(("elapsed", "expected_timeout"), [(250, 440), (370, None), (500, None)])
def test_actual_setup_time_limits_work_and_preserves_cleanup(
    tmp_path: Path, monkeypatch: Any, elapsed: int, expected_timeout: int | None
) -> None:
    clock = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    # The simulated clock jumps without the monitor beating; heartbeat is tested elsewhere.
    monkeypatch.setattr(execution, "SUPERVISOR_HEARTBEAT_SLACK_SECONDS", 10**9)
    monkeypatch.setattr(
        execution, "source_identity", lambda: {"commit": "a" * 40, "tree": "b" * 40}
    )

    class SlowSetup(FakeColab):
        work_timeout: int | None = None

        def exec_stage(self, name: str, stage: str, timeout: int) -> dict[str, Any]:
            if stage == "prepare":
                clock[0] += elapsed
            else:
                self.work_timeout = timeout
            return super().exec_stage(name, stage, timeout)

    client = SlowSetup(tmp_path / "provider", items_per_session=1)
    archive = tmp_path / "source.tar"
    archive.write_bytes(b"synthetic-source")
    state = execution.run_session(
        client=client, plan=PLAN, ledger_path=tmp_path / "ledger.json",
        authorization=_allowance(), session_index=1, run_dir=tmp_path / "run",
        source_archive=archive, binding=execution.remote_binding(PLAN, archive, "a" * 40),
        now=NOW,
    )  # fmt: skip
    assert client.work_timeout == expected_timeout
    assert state["target_absent_after_stop"] is True
    if expected_timeout is None:
        assert "insufficient remaining work-stage time" in state["failure"]
        assert "work" not in state


@pytest.mark.parametrize(
    ("phase", "kind"),
    [
        ("allocation", "rate"),
        ("upload", "rate"),
        ("prepare_status", "rate"),
        ("recovery", "rate"),
        ("upload", "balance"),
    ],
)
def test_cost_monitor_covers_all_paid_session_phases(
    tmp_path: Path, monkeypatch: Any, phase: str, kind: str
) -> None:
    monkeypatch.setattr(execution, "COST_POLL_SECONDS", 0.001)
    monkeypatch.setattr(
        execution, "source_identity", lambda: {"commit": "a" * 40, "tree": "b" * 40}
    )

    class RateChange(FakeColab):
        work_called = False
        changed = False

        def change(self, where: str) -> None:
            if phase != where or self.changed:
                return
            self.changed = True
            if kind == "rate":
                self.rate_when_allocated = 2.0
            else:
                self.balance -= 5.0
            deadline = time.monotonic() + 3
            while not self.stopped and time.monotonic() < deadline:
                time.sleep(0.001)
            assert self.stopped, "monitor did not stop the exact target"

        def new(self, name: str) -> bool:
            result = super().new(name)
            self.change("allocation")
            return result

        def upload(self, name: str, local: Path, remote: str) -> bool:
            self.change("upload")
            return super().upload(name, local, remote)

        def exec_stage(self, name: str, stage: str, timeout: int) -> dict[str, Any]:
            if stage == "work":
                self.work_called = True
            return super().exec_stage(name, stage, timeout)

        def download(self, name: str, remote: str, local: Path) -> bool:
            if remote == execution.REMOTE_STATUS:
                self.change("recovery" if self.work_called else "prepare_status")
            return super().download(name, remote, local)

    client = RateChange(tmp_path / "provider", items_per_session=1)
    archive = tmp_path / "source.tar"
    archive.write_bytes(b"synthetic-source")
    state = execution.run_session(
        client=client, plan=PLAN, ledger_path=tmp_path / "ledger.json",
        authorization=_allowance(), session_index=1, run_dir=tmp_path / "run",
        source_archive=archive, binding=execution.remote_binding(PLAN, archive, "a" * 40),
        now=NOW,
    )  # fmt: skip
    assert state["monitor_failure"] and state["target_absent_after_stop"] is True
    assert client.created == [state["session"]]
    assert all(name == state["session"] for name in client.stopped)
    assert client.work_called is (phase == "recovery")


def test_unresponsive_cost_snapshot_stops_target(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(execution, "COST_POLL_SECONDS", 0.001)
    monkeypatch.setattr(execution, "COST_SNAPSHOT_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(
        execution, "source_identity", lambda: {"commit": "a" * 40, "tree": "b" * 40}
    )

    class StalledSnapshot(FakeColab):
        def snapshot(self) -> dict[str, Any]:
            if threading.current_thread().name == "res541-cost-snapshot":
                time.sleep(0.2)
            return super().snapshot()

        def upload(self, name: str, local: Path, remote: str) -> bool:
            deadline = time.monotonic() + 2
            while not self.stopped and time.monotonic() < deadline:
                time.sleep(0.001)
            assert self.stopped
            return super().upload(name, local, remote)

    client = StalledSnapshot(tmp_path / "provider")
    archive = tmp_path / "source.tar"
    archive.write_bytes(b"synthetic-source")
    state = execution.run_session(
        client=client, plan=PLAN, ledger_path=tmp_path / "ledger.json",
        authorization=_allowance(), session_index=1, run_dir=tmp_path / "run",
        source_archive=archive, binding=execution.remote_binding(PLAN, archive, "a" * 40),
        now=NOW,
    )  # fmt: skip
    assert "live quota snapshot timed out" in state["monitor_failure"][0]
    assert "work" not in state and state["target_absent_after_stop"] is True


@pytest.mark.parametrize("mode", ["timeout", "start", "returned"])
def test_real_command_adapter_recovers_sanitized_transport_evidence(
    tmp_path: Path, monkeypatch: Any, mode: str
) -> None:
    # Exercise _run_colab's real exception wrapper, rather than faking a direct TimeoutExpired.
    client = execution.ColabCLI()
    original = subprocess.run
    script = (
        'import sys,time; print("token=private-token '
        'https://example.invalid/a?sig=private-signature",file=sys.stderr,flush=True); '
        + ("time.sleep(5)" if mode == "timeout" else "sys.exit(7)")
    )

    def run(command: Any, **kwargs: Any) -> Any:
        target = (
            [str(tmp_path / "no-such-cli")] if mode == "start" else [sys.executable, "-c", script]
        )
        return original(
            target, cwd=tmp_path, env=kwargs["env"], capture_output=True, text=True, timeout=0.2
        )

    monkeypatch.setattr(subprocess, "run", run)
    result = client.exec_stage("synthetic-no-gpu", "prepare", 180)
    assert result["returncode"] == (7 if mode == "returned" else None)
    assert result["timed_out"] is (mode == "timeout")
    assert (
        result["failure_category"]
        == {
            "timeout": "CLI_TRANSPORT_TIMEOUT",
            "start": "CLI_TRANSPORT_START_FAILURE",
            "returned": "CLI_OR_TRANSPORT_EXIT",
        }[mode]
    )
    assert "private-token" not in json.dumps(result)
    assert "private-signature" not in json.dumps(result)
    if mode != "start":
        assert "[URL_REDACTED]" in result["stderr_tail"]


def test_owner_window_is_rechecked_after_watchdog_ready(tmp_path: Path, monkeypatch: Any) -> None:
    from datetime import datetime, timedelta
    from types import SimpleNamespace

    clock = [NOW]
    monkeypatch.setattr(
        execution, "source_identity", lambda: {"commit": "a" * 40, "tree": "b" * 40}
    )
    monkeypatch.setattr(
        execution,
        "datetime",
        SimpleNamespace(now=lambda tz: clock[0], fromisoformat=datetime.fromisoformat),
    )

    class DelayedWatchdog(FakeColab):
        def start_watchdog(self, name: str, receipt: Path) -> Any:
            result = super().start_watchdog(name, receipt)
            clock[0] += timedelta(seconds=20)
            return result

    client = DelayedWatchdog(tmp_path / "provider")
    archive = tmp_path / "source.tar"
    archive.write_bytes(b"synthetic source")
    allowance = _allowance(valid_until_utc=(NOW + timedelta(seconds=1000)).isoformat())
    state = execution.run_session(
        client=client,
        plan=PLAN,
        ledger_path=tmp_path / "ledger.json",
        authorization=allowance,
        session_index=1,
        run_dir=tmp_path / "run",
        source_archive=archive,
        binding=execution.remote_binding(PLAN, archive, "a" * 40),
    )
    assert client.created == [] and client.stopped == []
    assert "window cannot cover" in state["failure"]
    assert state["target_absent_after_stop"] is True
    assert json.loads((tmp_path / "run/session-001-watchdog.json").read_text())["verified"] is True


@pytest.mark.parametrize("mode", ["zero", "failure", "unmatched"])
def test_unallocated_watchdog_disarm_requires_both_authenticated_inventories(
    monkeypatch: Any, mode: str
) -> None:
    client = execution.ColabCLI()
    assert client.target_endpoint is None
    monkeypatch.setattr(client._timeouts, "_colab_python", lambda: sys.executable)

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if command[:3] == ["colab", "--auth=oauth2", "sessions"]:
            text = (
                "[foreign] gpu-t4-foreign | Hardware: T4 | Shape: Standard | Variant: GPU\n"
                if mode == "unmatched"
                else "[colab] No active sessions found on server.\n"
            )
            return subprocess.CompletedProcess(command, 0, text, "")
        return subprocess.CompletedProcess(
            command,
            1 if mode == "failure" else 0,
            '{"endpoint":"https://colab.research.google.com/tun/m/assignments","assignments":[]}',
            "",
        )

    monkeypatch.setattr(client, "_run", run)
    assert client.verify_absent("synthetic-unattempted", allocation_attempted=False) is (
        mode == "zero"
    )
    if mode == "zero":
        # An attempted allocation still requires a bound exact endpoint; never weaken that gate.
        with pytest.raises(RuntimeError, match="endpoint"):
            client.verify_absent("synthetic-attempted")


def test_unallocated_watchdog_refuses_missing_cli(monkeypatch: Any) -> None:
    client = execution.ColabCLI()

    def missing() -> str:
        raise RuntimeError("CLI unavailable")

    monkeypatch.setattr(client._timeouts, "_colab_python", missing)
    monkeypatch.setattr(
        client, "_run", lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "", "")
    )
    assert client.verify_absent("synthetic-unattempted", allocation_attempted=False) is False
    assert client.teardown_receipt["assignments"]["error_type"] == "RuntimeError"
