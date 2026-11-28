"""Regression test for the RES-832 campaign entrypoint defect.

The first A1 campaign attempt consumed all four authorized T4 sessions because the controller
passed the worker's phase in ``A1_PHASE`` while the worker required a positional argument. Every
session exited at argument parsing and produced no generation. These tests pin the fix:

* the worker accepts the phase from the environment, which is how ``colab exec --file`` invokes it;
* the worker refuses an ambiguous or missing phase with a nonzero exit, never silently succeeding;
* the controller refuses to allocate when the entrypoint self-test fails;
* a failed phase aborts the campaign instead of consuming the remaining sessions.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from scripts import a1_colab


def _client() -> Any:
    """A placeholder client; the patched status reader never touches it."""
    return object()


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "scripts/a1_colab_worker.py"


def _run(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(WORKER), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        env={
            **os.environ,
            "PYTHONPATH": f"{ROOT / 'src'}:{ROOT}",
            **env,
        },
    )


def test_worker_accepts_the_phase_from_the_environment() -> None:
    # This is exactly how `colab exec --file` invokes the worker: no positional arguments.
    result = _run([], {"A1_PHASE": "status"})
    assert result.returncode == 0, result.stderr[-800:]
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert set(payload) == {"arms", "committed", "smoke", "phase", "error", "work_tree"}


def test_worker_accepts_the_phase_as_an_argument() -> None:
    result = _run(["status"], {})
    assert result.returncode == 0, result.stderr[-800:]
    assert "arms" in json.loads(result.stdout.strip().splitlines()[-1])


def test_worker_refuses_a_missing_phase() -> None:
    result = _run([], {})
    assert result.returncode == 2
    assert "phase must be given" in result.stderr


def test_worker_refuses_an_unknown_phase() -> None:
    result = _run([], {"A1_PHASE": "not-a-phase"})
    assert result.returncode == 2
    assert "phase must be given" in result.stderr


def test_controller_self_test_requires_a_nonzero_refusal() -> None:
    # The self-test must actually exercise the failure mode: a worker that silently succeeded
    # without a phase would hide the defect that cost the sessions.
    result = _run([], {})
    assert result.returncode != 0


def test_controller_self_test_returns_a_status_payload() -> None:
    observed = a1_colab.check_worker()
    assert observed["arguments_required"] is True
    assert observed["status_ok"] is True
    assert "arms" in observed["status"]


def test_require_phase_aborts_on_a_failed_phase(monkeypatch: pytest.MonkeyPatch) -> None:
    session: dict[str, Any] = {"phases": [{"returncode": 2, "stderr": "argparse error"}]}
    with pytest.raises(a1_colab.DefectError):
        a1_colab._require_phase(session, "bootstrap", "SETUP_COMPLETE", _client())
    assert session["defect"] == "BOOTSTRAP_PHASE_FAILED"


def test_require_phase_aborts_on_a_worker_error(monkeypatch: pytest.MonkeyPatch) -> None:
    session: dict[str, Any] = {"phases": [{"returncode": 0}]}
    monkeypatch.setattr(
        a1_colab, "_remote_status", lambda client: {"error": {"error_type": "ValueError"}}
    )
    with pytest.raises(a1_colab.DefectError):
        a1_colab._require_phase(session, "bootstrap", "SETUP_COMPLETE", _client())
    assert session["defect"] == "BOOTSTRAP_WORKER_ERROR"


def test_require_phase_aborts_when_the_expected_phase_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session: dict[str, Any] = {"phases": [{"returncode": 0}]}
    monkeypatch.setattr(a1_colab, "_remote_status", lambda client: {"phase": {"phase": "OTHER"}})
    with pytest.raises(a1_colab.DefectError):
        a1_colab._require_phase(session, "bootstrap", "SETUP_COMPLETE", _client())
    assert session["defect"] == "BOOTSTRAP_NOT_COMPLETE"


def test_require_phase_records_the_status_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    session: dict[str, Any] = {"phases": [{"returncode": 0}]}
    monkeypatch.setattr(
        a1_colab,
        "_remote_status",
        lambda client: {"phase": {"phase": "SETUP_COMPLETE"}, "arms": {}},
    )
    a1_colab._require_phase(session, "bootstrap", "SETUP_COMPLETE", _client())
    assert session["bootstrap_status"]["phase"]["phase"] == "SETUP_COMPLETE"
    assert "defect" not in session
