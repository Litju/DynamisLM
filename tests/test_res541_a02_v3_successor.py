from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_decision as decision
from scripts import a02_v3_execution as execution

from test_res541_a02_v3_execution import NOW, PLAN, QUIET, FakeColab

OLD_SOURCE = {"commit": "a" * 40, "tree": "b" * 40}
NEW_SOURCE = {"commit": "c" * 40, "tree": "d" * 40}


def _write(path: Path, value: dict[str, Any]) -> bytes:
    raw = (json.dumps(value, sort_keys=True) + "\n").encode()
    path.write_bytes(raw)
    return raw


def _successor_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    v3_dir = tmp_path / "v3-zero-shot"
    run_dir = v3_dir / f"plan-{PLAN['plan_sha256'][:12]}"
    run_dir.mkdir(parents=True)
    monkeypatch.setattr(execution, "V3_DIR", v3_dir)
    monkeypatch.setattr(execution, "source_identity", lambda: NEW_SOURCE)

    source_archive = run_dir / "source-001.tar"
    source_archive.write_bytes(b"synthetic session 001 Git archive")
    archive_sha256 = hashlib.sha256(source_archive.read_bytes()).hexdigest()
    binding = {
        "schema": "RES541_A02_V3_REMOTE_BINDING_V1",
        "source_archive_sha256": archive_sha256,
        "source_revision": OLD_SOURCE["commit"],
        "source_identity": OLD_SOURCE,
        "plan_sha256": PLAN["plan_sha256"],
        "protocol_sha256": decision.protocol_sha256(),
        "item_cost_bounds": PLAN["item_cost_bounds_seconds"],
        "session_index": 1,
    }
    session = f"res541-a02-v3-{PLAN['plan_sha256'][:8]}-001"
    binding_hash = _write(run_dir / "session-001-binding.json", binding)
    status = {
        "status": "EXECUTION_FAILED",
        "failure_stage": "work",
        "error_type": "ModuleNotFoundError",
        "error_detail": "No module named 'scripts'",
        "binding": binding,
        "checkpoint_sha256": None,
    }
    status_hash = hashlib.sha256(_write(run_dir / "session-001-status.json", status)).hexdigest()
    used = {
        "session": session,
        "index": 1,
        "plan_sha256": PLAN["plan_sha256"],
        "source_identity": OLD_SOURCE,
        "recorded_at_utc": NOW.isoformat(),
    }
    used_hash = _write(run_dir / "session-001-used.json", used)
    control = {
        "session": session,
        "prepare": {"returncode": 0},
        "work": {"returncode": 0},
        "session-001-status.json_sha256": status_hash,
        "stopped": True,
        "target_absent_after_stop": True,
        "quota_after": {"active_sessions": [], "active_assignment_count": 0},
        "teardown_receipt": {
            "sessions": {"returncode": 0, "stdout": "[colab] No active sessions found on server."},
            "assignments": {
                "returncode": 0,
                "stdout": json.dumps({"assignments": []}),
            },
        },
    }
    control_hash = _write(run_dir / "session-001-control.json", control)
    watchdog_hash = _write(
        run_dir / "session-001-watchdog.json", {"session": session, "phase": "DISARMED"}
    )
    raw_ledger = {
        "schema": execution.LEDGER_SCHEMA,
        "plan_sha256": PLAN["plan_sha256"],
        "source_identity": OLD_SOURCE,
        "sessions": [
            {
                "index": 1,
                "name": session,
                "compute_units_spent": 0.0,
                "cost_status": "KNOWN",
                "committed_items": 0,
            }
        ],
    }
    raw_ledger_hash = _write(run_dir / "session-001-ledger-controller-output.json", raw_ledger)
    corrected_ledger = {
        **raw_ledger,
        "sessions": [{**raw_ledger["sessions"][0], "compute_units_spent": 0.0121}],
    }
    corrected_ledger_hash = _write(run_dir / "ledger.json", corrected_ledger)
    cost = {
        "schema": "RES541_A02_V3_SESSION_COST_RECONCILIATION_V1",
        "plan_sha256": PLAN["plan_sha256"],
        "session_index": 1,
        "source_identity": OLD_SOURCE,
        "conservative_recorded_spend_cu": 0.0121,
        "exact_balance_delta_cu": 0.012062908790767324,
        "corrected_ledger_sha256": hashlib.sha256(corrected_ledger_hash).hexdigest(),
        "original_controller_ledger_sha256": hashlib.sha256(raw_ledger_hash).hexdigest(),
        "remote_status_sha256": status_hash,
        "teardown_confirmed": True,
    }
    cost_hash = _write(run_dir / "session-001-cost-reconciliation.json", cost)
    parent_allowance = {
        "schema": execution.ALLOWANCE_SCHEMA,
        "plan_sha256": PLAN["plan_sha256"],
        "source_identity": OLD_SOURCE,
        "max_sessions": 10,
        "cumulative_cap_cu": 3.625,
        "max_cu_per_session": 0.3625,
        "valid_until_utc": (NOW + timedelta(days=1)).isoformat(),
        "allow_concurrent_unrelated_usage": False,
    }
    parent_allowance_hash = _write(v3_dir / "campaign-allowance.json", parent_allowance)
    stop_summary = {
        "schema": "RES541_A02_V3_CAMPAIGN_STOP_SUMMARY_V1",
        "campaign_status": "STOPPED_ON_ANOMALY",
        "source_identity": OLD_SOURCE,
        "allowance": {"sessions_used": 1, "sessions_remaining": 9, "conservative_spend_cu": 0.0121},
        "session": {"committed_items": 0, "conservative_recorded_spend_cu": 0.0121},
        "teardown": {
            "controller_stopped_exact_target": True,
            "controller_confirmed_absent_from_cli_and_provider": True,
            "independent_cli_sessions": 0,
            "independent_provider_assignments": 0,
            "post_teardown_usage_rate_cu_per_hour": 0.0,
        },
        "evidence": {
            "source_archive_matches_binding": True,
            "remote_status_hash_matches_control": True,
        },
    }
    stop_hash = _write(run_dir / "campaign-stop-summary.json", stop_summary)
    predecessor = {
        "source_identity": OLD_SOURCE,
        "allowance_sha256": hashlib.sha256(parent_allowance_hash).hexdigest(),
        "ledger_sha256": hashlib.sha256(corrected_ledger_hash).hexdigest(),
        "controller_ledger_sha256": hashlib.sha256(raw_ledger_hash).hexdigest(),
        "binding_sha256": hashlib.sha256(binding_hash).hexdigest(),
        "used_sha256": hashlib.sha256(used_hash).hexdigest(),
        "control_sha256": hashlib.sha256(control_hash).hexdigest(),
        "status_sha256": status_hash,
        "cost_reconciliation_sha256": hashlib.sha256(cost_hash).hexdigest(),
        "stop_summary_sha256": hashlib.sha256(stop_hash).hexdigest(),
        "watchdog_sha256": hashlib.sha256(watchdog_hash).hexdigest(),
        "source_archive_sha256": archive_sha256,
    }
    allowance = {
        "schema": execution.SUCCESSOR_ALLOWANCE_SCHEMA,
        "plan_sha256": PLAN["plan_sha256"],
        "source_identity": NEW_SOURCE,
        "max_sessions": 2,
        "cumulative_cap_cu": 0.3746,
        "max_cu_per_session": 0.3625,
        "valid_until_utc": parent_allowance["valid_until_utc"],
        "allow_concurrent_unrelated_usage": False,
        "predecessor": predecessor,
    }
    return {
        "v3_dir": v3_dir,
        "run_dir": run_dir,
        "ledger_path": run_dir / "ledger.json",
        "source_archive": source_archive,
        "allowance": allowance,
        "predecessor": predecessor,
        "legacy_ledger_bytes": (run_dir / "ledger.json").read_bytes(),
        "parent_allowance_bytes": (v3_dir / "campaign-allowance.json").read_bytes(),
    }


def test_revision_2_migrates_session_001_without_mutating_v1_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged = _successor_fixture(tmp_path, monkeypatch)
    allowance = execution.validate_allowance(PLAN, staged["allowance"])
    ledger_path = execution._prepare_successor_ledger(PLAN, allowance, staged["run_dir"])
    successor = json.loads(ledger_path.read_text())

    assert ledger_path.name == "ledger-v2.json"
    assert staged["ledger_path"].read_bytes() == staged["legacy_ledger_bytes"]
    assert (staged["v3_dir"] / "campaign-allowance.json").read_bytes() == staged[
        "parent_allowance_bytes"
    ]
    assert successor["schema"] == execution.SUCCESSOR_LEDGER_SCHEMA
    assert successor["source_identity"] == NEW_SOURCE
    assert successor["sessions"][0]["source_identity"] == OLD_SOURCE
    assert successor["sessions"][0]["compute_units_spent"] == 0.0121

    admitted = execution.admit(
        plan=PLAN,
        ledger=successor,
        authorization=allowance,
        snapshot=QUIET,
        session_index=2,
        now=NOW,
    )
    assert admitted["admitted"] is True and admitted["spent_before"] == 0.0121
    with pytest.raises(execution.AdmissionError, match="next unused|exhausted"):
        execution.admit(
            plan=PLAN,
            ledger=successor,
            authorization=allowance,
            snapshot=QUIET,
            session_index=3,
            now=NOW,
        )


def test_revision_2_session_002_records_its_new_source_and_stops_at_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged = _successor_fixture(tmp_path, monkeypatch)
    allowance = execution.validate_allowance(PLAN, staged["allowance"])
    ledger_path = execution._prepare_successor_ledger(PLAN, allowance, staged["run_dir"])
    source_archive = staged["run_dir"] / "source-002.tar"
    source_archive.write_bytes(b"synthetic session 002 Git archive")
    binding = execution.remote_binding(PLAN, source_archive, NEW_SOURCE["commit"])
    state = execution.run_session(
        client=FakeColab(tmp_path / "remote", items_per_session=1),
        plan=PLAN,
        ledger_path=ledger_path,
        authorization=allowance,
        session_index=2,
        run_dir=staged["run_dir"],
        source_archive=source_archive,
        binding=binding,
        now=NOW,
    )
    updated = json.loads(ledger_path.read_text())
    assert state["index"] == 2 and state["target_absent_after_stop"] is True
    assert updated["sessions"][0]["source_identity"] == OLD_SOURCE
    assert updated["sessions"][0]["compute_units_spent"] == 0.0121
    assert updated["sessions"][1]["source_identity"] == NEW_SOURCE
    assert updated["sessions"][1]["index"] == 2
    assert staged["ledger_path"].read_bytes() == staged["legacy_ledger_bytes"]
    with pytest.raises(execution.AdmissionError, match="allowance session count is exhausted"):
        execution.admit(
            plan=PLAN,
            ledger=updated,
            authorization=allowance,
            snapshot=QUIET,
            session_index=3,
            now=NOW,
        )


def test_revision_2_refuses_changed_parent_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged = _successor_fixture(tmp_path, monkeypatch)
    (staged["run_dir"] / "session-001-status.json").write_text("{}")
    with pytest.raises(execution.AdmissionError, match="predecessor evidence changed"):
        execution.validate_allowance(PLAN, staged["allowance"])


def test_revision_2_cli_only_accepts_one_session_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    v3_dir = tmp_path / "v3-zero-shot"
    v3_dir.mkdir()
    (v3_dir / "campaign-allowance-v2.json").write_text(
        json.dumps({"schema": execution.SUCCESSOR_ALLOWANCE_SCHEMA})
    )
    monkeypatch.setattr(execution, "V3_DIR", v3_dir)
    monkeypatch.setattr(execution, "build_plan", lambda *args, **kwargs: PLAN)
    monkeypatch.setattr(execution, "_load_preflight", lambda path: {})
    monkeypatch.setattr(decision, "load_protocol", lambda: {})
    monkeypatch.setattr(execution, "validate_allowance", lambda plan, allowance: allowance)
    monkeypatch.setattr(
        execution.sys,
        "argv",
        ["a02_v3_execution.py", "run-campaign", "--preflight", "cpu-preflight.json"],
    )
    with pytest.raises(execution.AdmissionError, match="only one explicit run-session"):
        execution.main()
    assert not (v3_dir / f"plan-{PLAN['plan_sha256'][:12]}" / "ledger-v2.json").exists()
