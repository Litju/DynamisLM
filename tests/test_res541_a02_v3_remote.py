from __future__ import annotations

import hashlib
import io
import json
import tarfile
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
    monkeypatch.setattr(
        execution, "source_identity", lambda: {"commit": "a" * 40, "tree": "b" * 40}
    )
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


def test_source_archive_extracts_and_rejects_parent_paths(tmp_path: Path) -> None:
    archive = tmp_path / "source.tar"
    with tarfile.open(archive, "w") as output:
        member = tarfile.TarInfo("scripts/__init__.py")
        member.size = len(b'"""Synthetic source."""\n')
        output.addfile(member, io.BytesIO(b'"""Synthetic source."""\n'))
    destination = tmp_path / "extracted"
    destination.mkdir()
    remote._safe_extract_source(archive, destination)
    assert (destination / "scripts/__init__.py").read_text() == '"""Synthetic source."""\n'

    unsafe = tmp_path / "unsafe.tar"
    with tarfile.open(unsafe, "w") as output:
        member = tarfile.TarInfo("../escaped.py")
        member.size = len(b"raise AssertionError")
        output.addfile(member, io.BytesIO(b"raise AssertionError"))
    with pytest.raises(ValueError, match="unsafe path"):
        remote._safe_extract_source(unsafe, destination)


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


def test_early_prepare_failure_recovers_sanitized_detail(
    staged: dict[str, Any], monkeypatch: Any
) -> None:
    monkeypatch.setenv("A02_V3_REMOTE_STAGE", "prepare")
    monkeypatch.setenv("A02_V3_REMOTE_STAGE_TIMEOUT", "180")
    monkeypatch.delenv("A02_V3_CHILD_STAGE", raising=False)

    def broken(*args: Any) -> Any:
        raise RuntimeError(
            "download failed token=private-value authorization: Bearer private-bearer"
        )

    monkeypatch.setattr(remote, "outer", broken)
    assert remote.main() == 1
    status = json.loads(remote.STATUS_PATH.read_text())
    assert status["failure_stage"] == "prepare"
    assert status["error_type"] == "RuntimeError"
    assert "download failed" in status["error_detail"]
    assert "private-value" not in status["error_detail"]
    assert "private-bearer" not in status["error_detail"]
    assert status["binding"] == staged["binding"]


def test_failed_weight_download_retains_completed_runtime_qualification(
    staged: dict[str, Any],
    monkeypatch: Any,
) -> None:
    import sys
    from types import SimpleNamespace

    from scripts import a02_dev_runtime, a02_remote

    qualification = {"qualified": True, "synthetic_fixture": True}
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace())
    monkeypatch.setattr(a02_dev_runtime, "inventory", lambda *a: {"synthetic_fixture": True})
    monkeypatch.setattr(a02_dev_runtime, "cuda_smoke", lambda *a: {"synthetic_fixture": True})
    monkeypatch.setattr(a02_dev_runtime, "qualify", lambda *a: qualification)

    def failed_download(*args: Any) -> Any:
        raise RuntimeError("synthetic download failure")

    monkeypatch.setattr(a02_remote, "_weights", failed_download)
    with pytest.raises(RuntimeError, match="synthetic download"):
        remote.child("prepare", 180)
    status = json.loads(remote.STATUS_PATH.read_text())
    assert status["runtime_qualification"] == qualification
    assert status["status"] == "RUNTIME_QUALIFIED"
    assert status["binding"] == staged["binding"]
