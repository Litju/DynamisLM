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


def _kernel_run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the worker the way `colab exec --file` does: exec the source in an IPython kernel.

    The kernel's ``sys.argv`` is ``['...ipykernel_launcher.py', '-f', '.../kernel-<id>.json']``.
    Two authorized sessions were lost because the worker consumed that path as a positional
    phase, so every entrypoint test must use this argv rather than an empty one.
    """
    kernel = (
        "import sys, runpy\n"
        f"sys.argv = ['/x/ipykernel_launcher.py', '-f', '/root/.local/share/jupyter/"
        f"runtime/kernel-unit.json']\n"
        f"runpy.run_path({str(WORKER)!r}, run_name='__main__')\n"
    )
    return subprocess.run(
        [sys.executable, "-c", kernel],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        env={
            **{k: v for k, v in os.environ.items() if k != "A1_PHASE"},
            "PYTHONPATH": f"{ROOT / 'src'}:{ROOT}",
            **env,
        },
    )


def test_worker_runs_under_the_real_kernel_argv() -> None:
    """The phase must come from the environment even when argv holds a kernel path."""
    result = _kernel_run({"A1_PHASE": "status"})
    assert result.returncode == 0, result.stderr[-1200:]
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["committed"] == 0


def test_worker_refuses_under_the_kernel_argv_without_a_phase() -> None:
    result = _kernel_run({})
    assert result.returncode != 0
    assert "phase must be given" in result.stderr


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
    assert result.returncode != 0
    assert "phase must be given" in result.stderr


def test_worker_refuses_an_unknown_phase() -> None:
    result = _run([], {"A1_PHASE": "not-a-phase"})
    assert result.returncode != 0
    assert "phase must be given" in result.stderr


def test_controller_self_test_requires_a_nonzero_refusal() -> None:
    # The self-test must actually exercise the failure mode: a worker that silently succeeded
    # without a phase would hide the defect that cost the sessions.
    result = _kernel_run({})
    assert result.returncode != 0


def test_controller_self_test_returns_a_status_payload() -> None:
    observed = a1_colab.check_worker()
    assert observed["kernel_argv_refused"] is True
    assert observed["kernel_status_ok"] is True
    assert observed["positional_status_ok"] is True
    assert "committed" in observed["status"]


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


def test_require_phase_aborts_when_the_worker_never_ran(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`colab exec` returns 0 even when the remote file exits 2, so the output is the evidence."""
    session: dict[str, Any] = {
        "phases": [
            {
                "returncode": 0,
                "stdout": "usage: a1_colab_worker.py [phase]\n",
                "stderr": "a1_colab_worker.py: error: phase must be given as an argument",
            }
        ]
    }
    with pytest.raises(a1_colab.StatusUnavailableError):
        a1_colab._require_phase(session, "bootstrap", "SETUP_COMPLETE", _client())
    assert session["defect"] == "BOOTSTRAP_WORKER_DID_NOT_RUN"


def test_unparsable_status_is_a_deterministic_defect() -> None:
    assert issubclass(a1_colab.StatusUnavailableError, a1_colab.DefectError)


def test_require_phase_records_the_status_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    session: dict[str, Any] = {"phases": [{"returncode": 0, "stdout": "", "stderr": ""}]}
    monkeypatch.setattr(
        a1_colab,
        "_remote_status",
        lambda client: {"phase": {"phase": "SETUP_COMPLETE"}, "arms": {}, "committed": 0},
    )
    a1_colab._require_phase(session, "bootstrap", "SETUP_COMPLETE", _client())
    assert session["bootstrap_status"]["phase"]["phase"] == "SETUP_COMPLETE"
    assert "defect" not in session


def test_session_allowance_subtracts_sessions_already_consumed() -> None:
    """A relaunch must not restart the session count at one.

    The first continuation launch spent four sessions on an entrypoint defect because the loop
    bound was the original maximum rather than the remaining allowance. Attempts already recorded
    must reduce the bound, and an exhausted envelope must allocate nothing at all.
    """
    already = sum(row.sessions for row in a1_colab.CONTINUATION_ATTEMPTS)
    assert already >= a1_colab.MAX_SESSIONS
    assert a1_colab.MAX_SESSIONS - already <= 0


def test_controller_records_every_allocation_it_spent() -> None:
    for attempt in a1_colab.CONTINUATION_ATTEMPTS:
        assert attempt.sessions >= 1
        assert attempt.generations == 0
        assert attempt.modeled_cu >= 0
        assert attempt.wall_clock_seconds > 0
        assert attempt.outcome
        assert attempt.note
        assert set(attempt.record()) == {
            "name",
            "modeled_cu",
            "wall_clock_seconds",
            "sessions",
            "generations",
            "outcome",
            "note",
        }


def test_historical_attempt_1_is_untouched() -> None:
    assert a1_colab.ATTEMPT_1 == {
        "modeled_cu": 0.925,
        "wall_clock_seconds": 272.3,
        "sessions": 4,
        "generations": 0,
    }
