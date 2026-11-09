from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_decision as decision
from scripts import a02_v3_execution as execution
from scripts import a02_v3_remote as remote

from test_res541_a02_v3_execution import PLAN


@pytest.fixture
def staged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    archive = tmp_path / "source.tar"
    archive.write_bytes(b"archive-bytes")
    binding = {
        **execution.remote_binding(PLAN, archive, "a" * 40),
        "session_index": 1,
    }
    binding_path = tmp_path / "binding.json"
    binding_path.write_text(json.dumps(binding))
    for name, value in {
        "SOURCE_ARCHIVE": archive,
        "BINDING_PATH": binding_path,
        "STATUS_PATH": tmp_path / "status.json",
        "WORK": tmp_path / "work",
        "SOURCE_DIR": tmp_path / "work/v3-source",
    }.items():
        monkeypatch.setattr(remote, name, value)
    return {"archive": archive, "binding": binding, "binding_path": binding_path}


class _Helpers:
    def __init__(self, result: dict[str, Any], on_child: Any = None) -> None:
        self.result = result
        self.on_child = on_child
        self.calls: list[Any] = []

    def setup(self) -> None:
        self.calls.append("setup")

    def child(self, command: list[str], *, cwd: Path, env: dict[str, str], timeout: int) -> Any:
        self.calls.append(("child", command, env["A02_V3_CHILD_STAGE"], timeout, env["PYTHONPATH"]))
        if self.on_child:
            self.on_child()
        return self.result


def test_binding_matches_the_controller_contract(staged: dict[str, Any]) -> None:
    binding = remote.load_binding()
    assert binding["plan_sha256"] == PLAN["plan_sha256"]
    assert binding["protocol_sha256"] == decision.protocol_sha256()
    assert binding["source_archive_sha256"] == hashlib.sha256(b"archive-bytes").hexdigest()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda b: b.pop("plan_sha256"), "fields differ"),
        (lambda b: b.update(extra=1), "fields differ"),
        (lambda b: b.update(schema="X"), "schema differs"),
        (lambda b: b["item_cost_bounds"].update(QUALIFICATION=-1), "cost bounds"),
        (lambda b: b["item_cost_bounds"].pop("ZERO_SHOT_CONSTRAINED"), "cost bounds"),
    ],
)
def test_invalid_binding_is_rejected(staged: dict[str, Any], mutate: Any, message: str) -> None:
    binding = json.loads(staged["binding_path"].read_text())
    mutate(binding)
    staged["binding_path"].write_text(json.dumps(binding))
    with pytest.raises(ValueError, match=message):
        remote.load_binding()


def test_archive_hash_mismatch_stops_before_any_setup(staged: dict[str, Any]) -> None:
    staged["archive"].write_bytes(b"different")
    helpers = _Helpers({"returncode": 0, "timed_out": False})
    with pytest.raises(ValueError, match="archive hash"):
        remote.outer("prepare", 300, helpers)
    assert helpers.calls == []


def test_prepare_runs_setup_then_bounded_pinned_child(staged: dict[str, Any]) -> None:
    helpers = _Helpers(
        {"returncode": 0, "timed_out": False},
        on_child=lambda: remote._write_status(
            {"status": "READY", "plan_sha256": PLAN["plan_sha256"]}
        ),
    )
    assert remote.outer("prepare", 180, helpers) == 0
    assert helpers.calls[0] == "setup"
    _, command, stage, timeout, pythonpath = helpers.calls[1]
    assert stage == "prepare" and timeout == 150
    assert command[0].endswith("inference-venv/bin/python")
    assert pythonpath.endswith("/v3-source/src")
    status = json.loads(remote.STATUS_PATH.read_text())
    assert status["status"] == "READY" and status["stages"][0]["returncode"] == 0


def test_work_requires_ready_prepare_for_this_binding(staged: dict[str, Any]) -> None:
    helpers = _Helpers({"returncode": 0, "timed_out": False})
    with pytest.raises(ValueError, match="READY prepare"):
        remote.outer("work", 540, helpers)
    remote._write_status({"status": "READY", "plan_sha256": "0" * 64})
    with pytest.raises(ValueError, match="READY prepare"):
        remote.outer("work", 540, helpers)
    remote._write_status({"status": "READY", "plan_sha256": PLAN["plan_sha256"]})
    assert remote.outer("work", 540, helpers) == 0
    assert helpers.calls == [("child", helpers.calls[0][1], "work", 510, helpers.calls[0][4])]


def test_timed_out_child_reports_failure_and_records_it(staged: dict[str, Any]) -> None:
    remote._write_status({"status": "READY", "plan_sha256": PLAN["plan_sha256"]})
    helpers = _Helpers({"returncode": None, "timed_out": True, "stderr_tail": "killed"})
    assert remote.outer("work", 540, helpers) == 1
    stages = json.loads(remote.STATUS_PATH.read_text())["stages"]
    assert stages[-1] == {
        "stage": "work",
        "returncode": None,
        "timed_out": True,
        "stderr_tail": "killed",
    }
