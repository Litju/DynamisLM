"""No provider calls: falsify live safety with fake processes and quota snapshots."""

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


@pytest.mark.parametrize("exit_kind", ["death", "disconnect"])
def test_independent_watchdog_survives_parent_death(tmp_path: Path, exit_kind: str) -> None:
    cli = tmp_path / "colab"
    log = tmp_path / "calls"
    cli.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$TEST_CALLS"\n')
    cli.chmod(0o755)
    receipt = tmp_path / "watchdog.json"
    script = """
import os, signal, sys
from pathlib import Path
from typing import Any
from scripts.a02_v3_execution import ColabCLI
client = ColabCLI()
watchdog = client.start_watchdog("exact-test-target", Path(sys.argv[1]))
if sys.argv[2] == "death":
    os.kill(os.getpid(), signal.SIGKILL)
client.finish_watchdog(watchdog, False)
"""
    env = {
        **os.environ,
        "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
        "TEST_CALLS": str(log),
    }
    parent = subprocess.Popen(
        [sys.executable, "-c", script, str(receipt), exit_kind], env=env, cwd=execution.ROOT
    )
    parent.wait(timeout=15)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if receipt.exists() and json.loads(receipt.read_text()).get("phase") == "VERIFY_RETURNED":
            break
        time.sleep(0.05)
    state = json.loads(receipt.read_text())
    assert state["phase"] == "VERIFY_RETURNED"
    assert "--auth=oauth2 stop --session exact-test-target" in log.read_text()
    assert all(
        "stop" not in line or line.endswith("exact-test-target")
        for line in log.read_text().splitlines()
    )


@pytest.mark.parametrize("change", ["rate", "balance", "usage", "exception"])
def test_monitor_stops_during_execution_on_anomaly(monkeypatch: Any, change: str) -> None:
    monkeypatch.setattr(execution, "COST_POLL_SECONDS", 0.001)

    class Client:
        stopped = False

        def snapshot(self) -> dict[str, Any]:
            if change == "exception":
                raise RuntimeError("quota unavailable")
            return {
                "balance": 99 if change == "balance" else 100,
                "usage_rate_cu_per_hour": 2 if change == "rate" else 1.15,
                "active_sessions": [{"name": "target"}]
                + ([{"name": "stranger"}] if change == "usage" else []),
            }

        def stop(self, name: str) -> bool:
            assert name == "target"
            self.stopped = True
            return True

        def exec_stage(self, name: str, stage: str, timeout: int) -> dict[str, Any]:
            deadline = time.monotonic() + 2
            while not self.stopped and time.monotonic() < deadline:
                time.sleep(0.001)
            assert self.stopped
            return {"returncode": 0}

    client = Client()
    state = execution.monitored_stage(
        client,
        "target",
        "work",
        10,  # type: ignore[arg-type]
        {"balance": 100, "active_sessions": []},
        {"per_session_cap": 0.3625, "cumulative_cap": 3.625, "spent_before": 0},
        {"bounds": {"cost_buffer_cu": 0.05}},
        1.15,
    )
    assert state["returncode"] is None and state["monitor_failure"]


def test_source_identity_detects_a_clean_different_commit(tmp_path: Path, monkeypatch: Any) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init")
    git("config", "user.email", "synthetic@example.invalid")
    git("config", "user.name", "Synthetic fixture")
    (tmp_path / "source").write_text("first")
    git("add", "source")
    git("commit", "-m", "synthetic first source")
    monkeypatch.setattr(execution, "ROOT", tmp_path)
    first = execution.source_identity()
    (tmp_path / "source").write_text("second")
    git("add", "source")
    git("commit", "-m", "synthetic changed source")
    second = execution.source_identity()
    assert first["commit"] != second["commit"] and first["tree"] != second["tree"]
