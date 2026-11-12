"""Falsify budget, physical-evidence, training recovery and sequencing gates (RES-541)."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_automatic as automatic
from scripts import a02_v3_contract as v3
from scripts import a02_v3_decision as decision
from scripts import a02_v3_diagnostic_session as diagnostic_session
from scripts import a02_v3_execution as execution
from scripts import a02_v3_gpu_diagnostic as diagnostic
from scripts import a02_v3_training as training
from scripts import a02_v3_worker as worker


def test_one_budget_counts_all_stages_and_never_erases_unknown_cost(tmp_path: Path) -> None:
    grant = {"synthetic_owner_grant": True}
    budget = automatic.Budget(tmp_path, grant)
    control = tmp_path / "control.json"
    control.write_text('{"synthetic":true}')
    assert budget.remaining() == 50
    budget.reserve("diagnostic", "DIAGNOSTIC", 3)
    with pytest.raises(ValueError, match="unknown"):
        budget.reserve("baseline-001", "BASELINE", 2)
    budget.close("diagnostic", 0.5, control, passed=True)
    assert budget.remaining() == 49.5
    with pytest.raises(FileExistsError):
        budget.reserve("diagnostic", "DIAGNOSTIC", 3)
    with pytest.raises(ValueError, match="ceiling"):
        budget.reserve("overspend", "TRAINING", 49.6)
    budget.reserve("baseline-001", "BASELINE", 1)
    with pytest.raises(ValueError, match="unknown"):
        budget.close("baseline-001", None, control, passed=True)
    with pytest.raises(ValueError, match="unknown"):
        budget.remaining()
    assert automatic.read(budget.path)["historical_cu_separate"] == 0.2537


@pytest.mark.parametrize("amount", [float("nan"), float("inf"), -1.0, 3.01, True])
def test_invalid_or_over_cap_cost_stops_future_sessions(tmp_path: Path, amount: Any) -> None:
    budget = automatic.Budget(tmp_path, {"synthetic": True})
    control = tmp_path / "c.json"
    control.write_text("{}")
    budget.reserve("one", "DIAGNOSTIC", 3)
    with pytest.raises(ValueError):
        budget.close("one", amount, control, passed=True)
    with pytest.raises(ValueError):
        budget.remaining()


def test_budget_and_control_receipts_are_not_editable_shortcuts(tmp_path: Path) -> None:
    budget = automatic.Budget(tmp_path, {"synthetic": True})
    control = tmp_path / "c.json"
    control.write_text("{}")
    budget.reserve("one", "DIAGNOSTIC", 3)
    budget.close("one", 1, control, passed=True)
    ledger = automatic.read(budget.path)
    ledger["sessions"][0]["conservative_cu"] = 0
    budget.path.write_text(json.dumps(ledger))
    with pytest.raises(ValueError, match="evidence differs"):
        budget.remaining()
    ledger["sessions"][0]["conservative_cu"] = 1
    budget.path.write_text(json.dumps(ledger))
    control.write_text('{"changed":true}')
    with pytest.raises(ValueError, match="evidence differs"):
        budget.remaining()


def _physical_fixture() -> dict[str, Any]:
    # Synthetic metadata for plan-math tests; never executed or adopted as real model evidence.
    candidate = {
        "targets_match": True,
        "cache_state_consistent": True,
        "c_call": {"kv_dtype": "torch.float32"},
        "path_states": {"B": [{"kv_dtype": "torch.float32"}]},
        "timing_seconds": {"A": 0.1, "B": 0.1, "C": 0.01},
        **{p: {"abs_sum_difference": 0.0} for p in ("A_vs_B", "B_vs_C", "A_vs_C")},
    }
    row = {
        "complete": True,
        "winners_agree": True,
        "scorer_calls": 1,
        "candidates": [candidate],
        "timing_seconds": {"A": 0.1, "B": 0.1, "C": 0.01},
        "summary": {
            p: {"max_abs_score_difference": 0.0, "candidates_above_tolerance": 0}
            for p in ("A_vs_B", "B_vs_C", "A_vs_C")
        },
    }
    return {
        "schema": diagnostic.SCHEMA,
        "model_identity": decision.load_protocol()["candidate_model"],
        "runtime": {"device": "cuda:0", "gpu": "Tesla T4", "dtype": "torch.float32"},
        "precision_audit": {
            "parameter_count": 3_100_000_000,
            "parameter_dtypes": ["torch.float32"],
            "intermediate_dtypes": ["torch.float32"],
            "logit_dtypes": ["torch.float32"],
        },
        "passed": True,
        "rows": [row, row, row],
        "load_seconds": 1,
        "native_calibration_timing": {"tokens": 32, "seconds": 2},
    }


def test_campaign_is_priced_from_fp32_measurements_and_exact_frozen_workload() -> None:
    report = _physical_fixture()
    plan = automatic.measured_plan(report, 1.15, 45)
    assert plan["work_items"] == 581
    assert plan["bounds"]["session_seconds"] == 3600
    assert plan["compute_units"]["cumulative_cap"] <= 45
    assert "FP32" in plan["compute_units"]["rate_basis"]
    with pytest.raises(ValueError, match="budget"):
        automatic.measured_plan(report, 1.15, 0.1)


@pytest.mark.parametrize("fault", ["cpu", "tiny", "dtype", "failed", "incomplete"])
def test_tiny_cpu_or_failed_diagnostic_cannot_launch_scientific_work(fault: str) -> None:
    report = _physical_fixture()
    if fault == "cpu":
        report["runtime"]["device"] = "cpu"
    elif fault == "tiny":
        report["precision_audit"]["parameter_count"] = 10_000
    elif fault == "dtype":
        report["precision_audit"]["logit_dtypes"] = ["torch.float16"]
    elif fault == "failed":
        report["passed"] = False
    else:
        report["rows"] = report["rows"][:1]
    with pytest.raises(ValueError):
        automatic.measured_plan(report, 1.15, 45)


class TrainingClient(automatic.PipelineCLI):
    """No provider access: emit source-bound synthetic checkpoints for lifecycle tests."""

    def __init__(self, *, fail_work: bool = False, corrupt: bool = False):
        self.active: list[str] = []
        self.binding: dict[str, Any] = {}
        self.fail_work = fail_work
        self.corrupt = corrupt
        self.calls: list[Any] = []
        self.watchdog_seconds = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "balance": 100.0,
            "usage_rate_cu_per_hour": 1.0 if self.active else 0.0,
            "active_sessions": [{"name": n} for n in self.active],
        }

    def sessions(self) -> list[str]:
        return self.active.copy()

    def start_watchdog(self, name: str, receipt: Path) -> bool:
        self.calls.append("watchdog")
        assert self.watchdog_seconds == 7200
        return True

    def new(self, name: str) -> bool:
        self.active.append(name)
        self.calls.append("new")
        return True

    def hardware(self, name: str) -> str:
        return "T4"

    def upload(self, name: str, local: Path, target: str) -> bool:
        if target == execution.REMOTE_BINDING:
            self.binding = json.loads(local.read_bytes())
        return True

    def exec_stage(self, name: str, stage: str, timeout: int) -> dict[str, Any]:
        self.calls.append(stage)
        return {"returncode": 1 if self.fail_work and stage == "work" else 0}

    def _files(self) -> dict[str, bytes]:
        identity = {
            k: self.binding[k] for k in ("source_identity", "source_archive_sha256", "plan_sha256")
        }
        weights = b"SYNTHETIC tensor fixture; not a real adapter"
        meta = {
            "schema": training.SCHEMA,
            "identity": identity,
            "specification_sha256": v3.sha256(v3.canonical(self.binding["training_spec"]).encode()),
            "next_step": 1,
            "total_steps": 1,
            "completed": True,
            "adapter_sha256": v3.sha256(weights),
            "adapter_fingerprint": "a" * 64,
            "initial_adapter_fingerprint": "b" * 64,
        }
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w:") as handle:
            for key, value in {
                "adapter_model.safetensors": weights,
                "adapter_config.json": b"{}",
                "optimizer.pt": b"synthetic",
                "metadata.json": json.dumps(meta).encode(),
            }.items():
                entry = tarfile.TarInfo(key)
                entry.size = len(value)
                handle.addfile(entry, io.BytesIO(value))
        checkpoint = archive.getvalue()
        result = {**meta, "steps_this_session": 1, "checkpoint_sha256": v3.sha256(checkpoint)}
        report = (json.dumps({"phase": "TRAIN_FINAL", **result}) + "\n").encode()
        status = {
            "binding": self.binding,
            "status": "TRAINING_COMPLETE",
            "training_result": result,
            "training_checkpoint_sha256": v3.sha256(checkpoint),
            "training_report_sha256": v3.sha256(report),
        }
        return {
            "checkpoint.tar": checkpoint,
            "report.jsonl": report,
            "status.json": json.dumps(status).encode(),
        }

    def download(self, name: str, remote_path: str, local: Path) -> bool:
        mapped = {
            execution.REMOTE_STATUS: "status.json",
            "/content/a02-training-report.jsonl": "report.jsonl",
            "/content/a02-training/checkpoint.tar": "checkpoint.tar",
        }
        local.write_bytes(self._files()[mapped[remote_path]])
        if self.corrupt and local.name == "checkpoint.tar":
            local.write_bytes(b"corrupt")
        return True

    def stop(self, name: str) -> bool:
        self.calls.append("stop")
        self.active.remove(name)
        return True

    def verify_absent(self, name: str) -> bool:
        self.calls.append("both_inventories")
        return not self.active

    def finish_watchdog(self, watchdog: Any, verified: bool) -> None:
        self.calls.append(("disarm", verified))


@pytest.mark.parametrize("fault", [None, "work", "digest"])
def test_training_session_recovers_weights_or_stops_with_verified_teardown(
    tmp_path: Path, fault: str | None
) -> None:
    (tmp_path / "source.tar").write_bytes(b"synthetic source")
    (tmp_path / "baseline").mkdir()
    (tmp_path / "baseline/checkpoint.jsonl").write_bytes(b"synthetic baseline")
    directory = tmp_path / "training"
    directory.mkdir()
    grant = {
        "source_identity": {"commit": "a" * 40, "tree": "b" * 40},
        "source_archive_sha256": "c" * 64,
        "protocol_sha256": decision.protocol_sha256(),
        "training": training.specification(),
        "owner_receipt_sha256": "d" * 64,
    }
    client = TrainingClient(fail_work=fault == "work", corrupt=fault == "digest")
    result = automatic.training_session(directory, grant, 1, None, 1.5, 4, client)
    assert result["passed"] is (fault is None)
    assert client.calls.count("new") == 1 and client.calls.index("watchdog") < client.calls.index(
        "new"
    )
    assert client.calls[-3:] == ["stop", "both_inventories", ("disarm", True)]
    if fault == "digest":
        assert "evidence_error" in result
    if fault is None:
        assert (directory / "session-001/verified-checkpoint/adapter_model.safetensors").is_file()


def test_fixed_owner_directory_source_and_window_cannot_reset_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime, timedelta

    owner_root = tmp_path / "owner"
    owner_root.mkdir()
    owner_file = owner_root / "owner-delegated-budget-50cu-v2.json"
    owner_file.write_text(
        json.dumps(
            {
                "agent_selected_total_new_cu": 50,
                "automatic_campaign_requested": True,
                "actual_lora_weights_requested": True,
            }
        )
    )
    monkeypatch.setattr(diagnostic_session, "ROOT", owner_root)
    monkeypatch.setattr(automatic, "ROOT", tmp_path / "automatic")
    identity = {"commit": "a" * 40, "tree": "b" * 40}
    monkeypatch.setattr(execution, "source_identity", lambda: identity)

    def archive(path: Path) -> tuple[Path, str]:
        path.write_bytes(b"synthetic fixed archive")
        return path, identity["commit"]

    monkeypatch.setattr(execution, "source_archive", archive)
    monkeypatch.setattr(
        diagnostic_session,
        "head_archive_sha256",
        lambda: v3.sha256(b"synthetic fixed archive"),
    )
    with pytest.raises(ValueError, match="fixed budget directory"):
        automatic.prepare(tmp_path / "another-directory")
    directory = automatic.ROOT / v3.sha256(owner_file.read_bytes())
    grant = automatic.prepare(directory)
    automatic.validate_grant(directory, grant, required_seconds=7500)
    with pytest.raises(ValueError, match="no budget reset"):
        automatic.prepare(directory)
    changed = {**grant, "valid_until_utc": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()}
    with pytest.raises(ValueError, match="expired"):
        automatic.validate_grant(directory, changed)
    with pytest.raises(ValueError, match="expired"):
        automatic.validate_grant(directory, grant, required_seconds=8 * 86400)
    with pytest.raises(ValueError, match="finite owner scope"):
        automatic.validate_grant(directory, {**grant, "maximum_new_cu": 51})
    owner_file.write_text('{"changed":true}')
    with pytest.raises(ValueError):
        automatic.validate_grant(directory, grant)


def test_failed_diagnostic_cannot_start_baseline_or_training(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = {"commit": "a" * 40, "tree": "b" * 40}
    grant = {"source_identity": source, "diagnostic": diagnostic.specification(delegated=True)}
    (tmp_path / "grant.json").write_text(json.dumps(grant))
    (tmp_path / "source.tar").write_bytes(b"synthetic")
    monkeypatch.setattr(automatic, "validate_grant", lambda *args, **kwargs: None)
    monkeypatch.setattr(automatic, "PipelineCLI", TrainingClient)
    monkeypatch.setattr(
        diagnostic_session, "proposal", lambda *a, **k: {"proposal_sha256": "f" * 64}
    )
    calls = []

    def diagnostic_fail(**kwargs: Any) -> dict[str, Any]:
        calls.append("diagnostic")
        return {"passed": False, "new_conservative_cu": 0.1}

    monkeypatch.setattr(diagnostic_session, "run", diagnostic_fail)
    monkeypatch.setattr(
        execution, "run_session", lambda **kwargs: calls.append("BASELINE_MUST_NOT_RUN")
    )
    monkeypatch.setattr(
        automatic, "training_session", lambda *a, **k: calls.append("TRAINING_MUST_NOT_RUN")
    )
    monkeypatch.setenv("COLAB_CLI_ASSIGN_RETRIES", "0")
    result = automatic.run(tmp_path)
    assert not result["complete"]
    assert calls == ["diagnostic"]
    assert len(result["budget"]["sessions"]) == 1
    assert result["budget"]["sessions"][0]["conservative_cu"] == 0.1
    assert not (tmp_path / "baseline").exists() and not (tmp_path / "training").exists()


@pytest.mark.parametrize("fault", [None, "baseline_failure", "baseline_rollback"])
def test_automatic_sequence_reaches_export_without_per_stage_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    # Synthetic lifecycle only; real learned tensors/resume have separate PEFT CPU checks.
    owner = tmp_path / "owner"
    owner.mkdir()
    monkeypatch.setattr(diagnostic_session, "ROOT", owner)
    source = {"commit": "a" * 40, "tree": "b" * 40}
    archive = tmp_path / "source.tar"
    archive.write_bytes(b"synthetic source")
    grant = {
        "source_identity": source,
        "source_archive_sha256": v3.sha256(archive.read_bytes()),
        "diagnostic": diagnostic.specification(delegated=True),
        "training": training.specification(),
        "protocol_sha256": decision.protocol_sha256(),
        "owner_receipt_sha256": "c" * 64,
        "valid_until_utc": "2099-01-01T00:00:00+00:00",
    }
    (tmp_path / "grant.json").write_text(json.dumps(grant))
    monkeypatch.setattr(automatic, "validate_grant", lambda *args, **kwargs: None)
    monkeypatch.setattr(execution, "source_identity", lambda: source)
    monkeypatch.setattr(automatic, "PipelineCLI", TrainingClient)
    proposed = {"proposal_sha256": "f" * 64}
    monkeypatch.setattr(diagnostic_session, "proposal", lambda *args, **kwargs: proposed)
    calls = []
    committed = [0]

    def diagnostic_success(**kwargs: Any) -> dict[str, Any]:
        calls.append("diagnostic")
        path = owner / proposed["proposal_sha256"] / Path(diagnostic_session.REMOTE_REPORT).name
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"phase": "FINAL", **_physical_fixture()}) + "\n")
        return {
            "passed": True,
            "new_conservative_cu": 0.1,
            "pricing_observation": {"rate_cu_per_hour": 1.15},
            "recovered": {diagnostic_session.REMOTE_REPORT: v3.sha256(path.read_bytes())},
        }

    monkeypatch.setattr(diagnostic_session, "run", diagnostic_success)
    monkeypatch.setattr(
        worker,
        "read_checkpoint",
        lambda *args, **kwargs: {
            "entries": [None] * committed[0],
            "head": "e" * 64,
            "torn_tail_discarded": False,
        },
    )
    monkeypatch.setattr(worker, "score_checkpoint", lambda *args: {"synthetic_fixture": True})

    def baseline_success(**kwargs: Any) -> dict[str, Any]:
        calls.append("baseline")
        directory = kwargs["run_dir"]
        (directory / "checkpoint.jsonl").write_bytes(b"SYNTHETIC checkpoint")
        committed[0] = 500 if fault == "baseline_rollback" else 581
        state = {
            "quota_before": {"balance": 100},
            "quota_after": {"balance": 99.8},
            "rate_after_allocation": 1.15,
            "target_absent_after_stop": True,
            "stopped": True,
            "work": {"returncode": 1 if fault == "baseline_failure" else 0},
            "merge": {"committed_before": 0, "committed_after": 581, "head": "e" * 64},
            "index": 1,
            "remote_status": {"checkpoint_sha256": v3.sha256(b"SYNTHETIC checkpoint")},
            "unrelated_sessions_after": [],
            "sessions_before": [],
        }
        (directory / "session-001-control.json").write_text(json.dumps(state))
        (directory / "ledger.json").write_text(
            json.dumps(
                {"source_identity": source, "sessions": [{"index": 1, "committed_items": 581}]}
            )
        )
        return state

    monkeypatch.setattr(execution, "run_session", baseline_success)

    def train_success(directory: Path, *args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append("training")
        assert committed[0] == 581
        client = TrainingClient()
        client.binding = {
            "source_identity": source,
            "source_archive_sha256": grant["source_archive_sha256"],
            "plan_sha256": "e" * 64,
            "training_spec": grant["training"],
        }
        files = client._files()
        jobdir = directory / "session-001"
        jobdir.mkdir()
        (jobdir / "checkpoint.tar").write_bytes(files["checkpoint.tar"])
        state = {
            "passed": True,
            "conservative_cu": 0.3,
            "result": json.loads(files["status.json"])["training_result"],
            "binding": client.binding,
            "recovered": {"checkpoint.tar": v3.sha256(files["checkpoint.tar"])},
        }
        (jobdir / "control.json").write_text(json.dumps(state))
        return state

    monkeypatch.setattr(automatic, "training_session", train_success)
    monkeypatch.setenv("COLAB_CLI_ASSIGN_RETRIES", "0")
    result = automatic.run(tmp_path)
    if fault is not None:
        assert not result["complete"]
        assert calls == ["diagnostic", "baseline"]
        assert (tmp_path / "terminal-anomaly.json").exists()
        with pytest.raises(ValueError, match="terminal anomaly"):
            automatic.run(tmp_path)
        assert calls == ["diagnostic", "baseline"]
        return
    assert result["complete"], result
    assert automatic.run(tmp_path)["complete"]
    assert calls == ["diagnostic", "baseline", "training"]
    assert Path(result["trained_adapter_path"]).is_file()
    assert result["trained_candidate_task_accuracy"].startswith("NOT_EVALUATED")
    assert [entry["kind"] for entry in result["budget"]["sessions"]] == [
        "DIAGNOSTIC",
        "BASELINE",
        "TRAINING",
    ]
    assert sum(entry["conservative_cu"] for entry in result["budget"]["sessions"]) < 50


def test_deleted_or_truncated_ledger_cannot_restore_spending_headroom(tmp_path: Path) -> None:
    grant = {"synthetic": True}
    budget = automatic.Budget(tmp_path, grant)
    control = tmp_path / "control.json"
    control.write_text("{}")
    budget.reserve("one", "DIAGNOSTIC", 3)
    budget.close("one", 0.2, control, passed=True)
    saved = budget.path.read_bytes()
    budget.path.unlink()
    with pytest.raises(ValueError, match="missing budget ledger"):
        automatic.Budget(tmp_path, grant)
    budget.path.write_bytes(saved)
    ledger = automatic.read(budget.path)
    ledger["sessions"] = []
    budget.path.write_text(json.dumps(ledger))
    with pytest.raises(ValueError, match="omits immutable"):
        budget.remaining()


def test_known_cost_failed_execution_is_sticky_even_without_terminal_marker(tmp_path: Path) -> None:
    grant = {"synthetic": True}
    budget = automatic.Budget(tmp_path, grant)
    control = tmp_path / "control.json"
    control.write_text("{}")
    budget.reserve("one", "BASELINE", 3)
    with pytest.raises(ValueError, match="terminal"):
        budget.close("one", 0.2, control, passed=False)
    assert automatic.read(budget.path)["sessions"][0]["cost_status"] == "KNOWN"
    with pytest.raises(ValueError, match="failed execution"):
        automatic.Budget(tmp_path, grant).reserve("two", "BASELINE", 3)


def test_persisted_plan_mutation_or_rehashed_cost_changes_are_rejected() -> None:
    report = _physical_fixture()
    plan = automatic.measured_plan(report, 1.15, 45)
    automatic.validate_plan(plan, report, 1.15, 45)
    plan["item_cost_bounds_seconds"]["ZERO_SHOT_UNCONSTRAINED"] = 0.00001
    with pytest.raises(ValueError, match="content hash"):
        automatic.validate_plan(plan, report, 1.15, 45)
    payload = {
        k: v for k, v in plan.items() if k not in {"plan_sha256", "live_observation_not_hashed"}
    }
    plan["plan_sha256"] = v3.sha256(v3.canonical(payload).encode())
    with pytest.raises(ValueError, match="derivation"):
        automatic.validate_plan(plan, report, 1.15, 45)


def test_training_archive_swap_or_cursor_rollback_is_rejected_before_allocation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "checkpoint.tar"
    path.write_bytes(b"current checkpoint")
    spec = {"synthetic": True}
    source = {"commit": "a" * 40, "tree": "b" * 40}
    control = {
        "passed": True,
        "recovered": {"checkpoint.tar": v3.sha256(path.read_bytes())},
        "binding": {"source_identity": source, "training_spec": spec},
        "result": {"checkpoint_sha256": v3.sha256(path.read_bytes())},
    }
    (tmp_path / "control.json").write_text(json.dumps(control))
    automatic.verified_training_prior(path, {"source_identity": source, "training": spec})
    path.write_bytes(b"older same-source checkpoint")
    with pytest.raises(ValueError, match="rollback"):
        automatic.verified_training_prior(path, {"source_identity": source, "training": spec})
    previous = {
        "next_step": 2,
        "total_steps": 4,
        "initial_adapter_fingerprint": "a" * 64,
        "identity": source,
        "specification_sha256": "b" * 64,
        "data_order_sha256": "c" * 64,
        "runtime": {},
    }
    automatic.validate_training_advance(previous, {**previous, "next_step": 3})
    with pytest.raises(ValueError, match="rolled back"):
        automatic.validate_training_advance(previous, {**previous, "next_step": 2})
    with pytest.raises(ValueError, match="rolled back"):
        automatic.validate_training_advance(
            previous, {**previous, "next_step": 3, "total_steps": 5}
        )
