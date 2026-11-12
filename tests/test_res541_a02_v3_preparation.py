"""Real preparation children behind a deliberately misleading synthetic CLI (RES-541)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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
