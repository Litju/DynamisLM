"""Falsify budget, physical-evidence, training recovery and sequencing gates (RES-541)."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_automatic as automatic
from scripts import a02_v3_contract as v3
from scripts import a02_v3_cost as cost
from scripts import a02_v3_decision as decision
from scripts import a02_v3_diagnostic_session as diagnostic_session
from scripts import a02_v3_execution as execution
from scripts import a02_v3_gpu_diagnostic as diagnostic
from scripts import a02_v3_training as training
from scripts import a02_v3_worker as worker

from test_res541_a02_v3_execution import COST_POLICY, write_authorized_policy


@pytest.mark.parametrize("fault", [None, "corrupt_part", "zero_without_receipt"])
def test_large_checkpoint_upload_is_exact_atomic_and_requires_remote_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    monkeypatch.setattr(automatic, "UPLOAD_DIRECT_LIMIT_BYTES", 16)
    monkeypatch.setattr(automatic, "UPLOAD_PART_BYTES", 8)
    monkeypatch.setattr(execution, "E_ROOT", tmp_path / "evidence")
    source = tmp_path / "source.tar"
    data = b"SYNTHETIC binary checkpoint\x00\xff\n" * 3
    source.write_bytes(data)
    remote = tmp_path / "remote"
    remote.mkdir()
    target = remote / "checkpoint.tar"
    target.write_bytes(b"SYNTHETIC original target")
    uploads: list[int] = []

    def run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        assert 0 < timeout <= 240
        if "upload" in command:
            part, destination = Path(command[-2]), Path(command[-1])
            body = part.read_bytes()
            uploads.append(len(body))
            if fault == "corrupt_part" and len(uploads) == 2:
                body = b"X" + body[1:]
            destination.write_bytes(body)
            return subprocess.CompletedProcess(command, 0, "", "")
        if "exec" in command:
            if fault == "zero_without_receipt":
                return subprocess.CompletedProcess(command, 0, "", "")
            return subprocess.run(
                [sys.executable, command[command.index("--file") + 1]],
                capture_output=True,
                text=True,
                timeout=20,
            )
        assert "download" in command
        if not Path(command[-2]).exists():
            return subprocess.CompletedProcess(command, 1, "", "missing receipt")
        shutil.copyfile(command[-2], command[-1])
        return subprocess.CompletedProcess(command, 0, "", "")

    client = automatic.PipelineCLI()
    monkeypatch.setattr(client, "_run", run)
    assert client.upload("SYNTHETIC no provider", source, str(target)) is (fault is None)
    assert uploads and max(uploads) <= 8 and sum(uploads) == len(data)
    assert source.read_bytes() == data
    assert target.read_bytes() == (data if fault is None else b"SYNTHETIC original target")


def _stage2_proposal() -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "proposal_sha256": "a" * 64,
        "source_identity": {"commit": "b" * 40, "tree": "c" * 40},
        "source_archive_sha256": v3.sha256(b"SYNTHETIC source"),
        "valid_from_utc": (now - timedelta(minutes=1)).isoformat(),
        "valid_until_utc": (now + timedelta(hours=48)).isoformat(),
        "protocol_sha256": decision.protocol_sha256(),
        "training": training.specification(),
        "observed_cost_controls": {
            "schema": cost.OBSERVED_COST_POLICY_SCHEMA,
            "balance_display_resolution_cu": 0.01,
            "observed_rate_floor_cu_per_hour": 1.15,
            "maximum_observed_rate_cu_per_hour": 1.4375,
            "risk_reserve_cu": 0.20,
        },
    }


def _stage2_approval(proposal: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "RES541_FINAL_LORA_STUDY_OWNER_APPROVAL_V1",
        "proposal_sha256": proposal["proposal_sha256"],
        "approved": True,
        "accept_observed_billing_risk": True,
        "recorded_utc": datetime.now(UTC).isoformat(),
        "owner_statement": "SYNTHETIC Stage 2 owner acceptance, not real GPU authority",
    }


@pytest.mark.parametrize("fault", ["baseline_approval", "risk", "proposal", "timestamp"])
def test_stage2_requires_fresh_exact_training_and_billing_approval(fault: str) -> None:
    proposed = _stage2_proposal()
    approval = _stage2_approval(proposed)
    assert automatic.stage2_approval(proposed, approval)["owner_acceptance"]["accepted"]
    if fault == "baseline_approval":
        approval["schema"] = "RES541_BASELINE_SUCCESSOR_OWNER_APPROVAL_V1"
    elif fault == "risk":
        approval["accept_observed_billing_risk"] = False
    elif fault == "proposal":
        approval["proposal_sha256"] = "f" * 64
    else:
        approval["recorded_utc"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    with pytest.raises(ValueError):
        automatic.stage2_approval(proposed, approval)


def test_stage2_budget_is_separate_finite_and_modeled(tmp_path: Path) -> None:
    budget = automatic.Budget(tmp_path, {"SYNTHETIC Stage 2": True}, maximum_cu=1, modeled=True)
    control = tmp_path / "control.json"
    control.write_text('{"synthetic":true}')
    budget.reserve("training-001", "TRAINING", 0.7)
    budget.close("training-001", 0.6, control, passed=True)
    assert budget.remaining() == pytest.approx(0.4)
    assert budget.state()["sessions"][0]["cost_status"] == "MODELED"
    with pytest.raises(ValueError, match="ceiling"):
        budget.reserve("evaluation-001", "EVALUATION", 0.5)
    with pytest.raises(ValueError, match="authority differs"):
        automatic.Budget(tmp_path, {"SYNTHETIC Stage 2": True}).state()


def test_stage2_refuses_before_provider_access_without_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(automatic, "validate_stage2", lambda *a: _stage2_proposal())
    monkeypatch.setattr(
        automatic, "PipelineCLI", lambda: pytest.fail("provider must not be accessed")
    )
    receipt = tmp_path / "approval.json"
    receipt.write_text("{}")
    with pytest.raises(ValueError, match="Stage 2 approval"):
        automatic.run_stage2(tmp_path, receipt)


@pytest.mark.parametrize("fault", ["baseline", "archive", "expired", "source"])
def test_stage2_preparation_is_readonly_and_validation_rejects_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    (baseline / "checkpoint.jsonl").write_bytes(b"SYNTHETIC sealed observations")
    controls = _stage2_proposal()["observed_cost_controls"]
    (baseline / "proposal.json").write_text(json.dumps({"cost_policy": controls}))
    descriptor = {
        "new_campaign_modeled_cu": 1,
        "files": {"checkpoint.jsonl": v3.sha256((baseline / "checkpoint.jsonl").read_bytes())},
    }
    source = {"commit": "a" * 40, "tree": "b" * 40}
    archive_bytes = b"SYNTHETIC source"

    def archive(path: Path) -> tuple[Path, str]:
        path.write_bytes(archive_bytes)
        return path, source["commit"]

    client = TrainingClient()
    monkeypatch.setattr(automatic, "BASELINE_SUCCESSOR", baseline)
    monkeypatch.setattr(automatic, "completed_baseline", lambda: descriptor)
    monkeypatch.setattr(automatic, "stage2_plan", lambda: {"maximum_additional_modeled_cu": 1})
    monkeypatch.setattr(execution, "source_identity", lambda: source)
    monkeypatch.setattr(execution, "source_archive", archive)
    monkeypatch.setattr(diagnostic_session, "head_archive_sha256", lambda: v3.sha256(archive_bytes))
    monkeypatch.setattr(automatic, "PipelineCLI", lambda: client)
    directory = tmp_path / "study"
    proposal = automatic.prepare_stage2(directory)
    assert automatic.validate_stage2(directory) == proposal
    assert "owner_acceptance" not in proposal["observed_cost_controls"]
    assert not client.calls  # no GPU or owner approval is fabricated by preparation
    if fault == "baseline":
        (baseline / "checkpoint.jsonl").write_bytes(b"SYNTHETIC changed observations")
    elif fault == "archive":
        (directory / "source.tar").write_bytes(b"SYNTHETIC wrong source")
    else:
        if fault == "expired":
            proposal["valid_until_utc"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        else:
            proposal["source_identity"] = {"commit": "f" * 40, "tree": "b" * 40}
        proposal["proposal_sha256"] = v3.sha256(
            v3.canonical({k: v for k, v in proposal.items() if k != "proposal_sha256"}).encode()
        )
        (directory / "stage2-proposal.json").write_text(json.dumps(proposal))
    with pytest.raises(ValueError):
        automatic.validate_stage2(directory)


def _synthetic_study_checkpoint(path: Path, *, adapted: bool) -> None:
    protocol = decision.load_protocol()
    examples = {decision.example_id(e): e for e in decision.heldout_examples(protocol)}
    items = training.adapted_work_items(protocol) if adapted else worker.work_items(protocol)
    head = worker.GENESIS
    model = protocol["candidate_model"]
    for seq, item in enumerate(items):
        record: dict[str, Any]
        if item.key == "QUALIFICATION":
            record = {
                "schema": worker.QUALIFICATION_SCHEMA,
                "passed": True,
                "model_id": model["id"],
                "model_revision": model["revision"],
            }
        elif item.key.startswith("HELDOUT:"):
            example = examples[item.key]
            action = {**example["gold_action"]}
            if not adapted:
                action["analysis_class"] = (
                    "SCALAR_ABSOLUTE_CHANGE"
                    if action["analysis_class"] != "SCALAR_ABSOLUTE_CHANGE"
                    else "RELIABILITY_RANDOM_ERROR_COMPARISON"
                )
            record = decision.make_record(
                protocol=protocol,
                arm=item.arm,
                example=example,
                raw_output=v3.format_action(action),
                truncated=False,
                model=model,
            )
        else:
            record = {
                "arm": item.arm,
                "case_id": item.key.removeprefix("EXPOSED:"),
                "raw_output": "SYNTHETIC invalid output",
                "truncated": False,
            }
        head = worker._append(
            path,
            {
                "schema": worker.CHECKPOINT_SCHEMA,
                "seq": seq,
                "prev_sha256": head,
                "item": item.id,
                "record": record,
            },
        )


@pytest.mark.parametrize("training_failure", [False, True])
def test_stage2_sequence_never_replays_baseline_or_evaluates_partial_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, training_failure: bool
) -> None:
    # Explicitly synthetic orchestration evidence; no model, provider, or real grant is used.
    baseline = tmp_path / "sealed-baseline"
    baseline.mkdir()
    _synthetic_study_checkpoint(baseline / "checkpoint.jsonl", adapted=False)
    sealed = (baseline / "checkpoint.jsonl").read_bytes()
    root = tmp_path / "study"
    root.mkdir()
    (root / "source.tar").write_bytes(b"SYNTHETIC source")
    proposed = _stage2_proposal()
    proposed["baseline"] = {"files": {"checkpoint.jsonl": v3.sha256(sealed)}}
    proposed["plan"] = {
        "maximum_additional_modeled_cu": 3,
        "training_sessions": 2,
        "training_per_session_modeled_cu": 1,
        "training_prepare_seconds": 840,
        "evaluation": {
            "plan_sha256": "d" * 64,
            "protocol_sha256": decision.protocol_sha256(),
            "session_count": 1,
            "bounds": {"session_seconds": 3600},
            "compute_units": {"cumulative_cap": 1, "per_session_cap": 1},
            "item_cost_bounds_seconds": {
                "QUALIFICATION": 10,
                "ADAPTED_UNCONSTRAINED": 1,
                "ADAPTED_CONSTRAINED": 1,
            },
        },
    }
    receipt = root / "approval.json"
    receipt.write_text(json.dumps(_stage2_approval(proposed)))
    calls: list[str] = []
    monkeypatch.setattr(automatic, "BASELINE_SUCCESSOR", baseline)
    monkeypatch.setattr(automatic, "validate_stage2", lambda *a: proposed)
    monkeypatch.setattr(execution, "source_identity", lambda: proposed["source_identity"])
    monkeypatch.setattr(automatic, "PipelineCLI", TrainingClient)

    def train(directory: Path, grant: dict[str, Any], *a: Any, **kw: Any) -> dict[str, Any]:
        calls.append("training")
        client = TrainingClient()
        client.binding = {
            "source_identity": grant["source_identity"],
            "source_archive_sha256": grant["source_archive_sha256"],
            "plan_sha256": "e" * 64,
            "training_spec": grant["training"],
        }
        files = client._files()
        job = directory / "session-001"
        job.mkdir()
        (job / "checkpoint.tar").write_bytes(files["checkpoint.tar"])
        state = {
            "passed": not training_failure,
            "conservative_cu": 0.3,
            "result": json.loads(files["status.json"])["training_result"],
            "binding": client.binding,
            "recovered": {"checkpoint.tar": v3.sha256(files["checkpoint.tar"])},
        }
        (job / "control.json").write_text(json.dumps(state))
        return state

    def evaluate(**kw: Any) -> dict[str, Any]:
        calls.append("evaluation")
        assert calls == ["training", "evaluation"]
        assert kw["binding"]["adapter_sha256"] == v3.sha256(
            (kw["final_adapter"] / "adapter_model.safetensors").read_bytes()
        )
        _synthetic_study_checkpoint(kw["run_dir"] / "checkpoint.jsonl", adapted=True)
        state = {"cost_accounting": {"conservative_cu": 0.4}}
        (kw["run_dir"] / "session-001-control.json").write_text(json.dumps(state))
        return state

    monkeypatch.setattr(automatic, "training_session", train)
    monkeypatch.setattr(execution, "run_session", evaluate)
    monkeypatch.setattr(execution, "session_anomaly", lambda *a: None)
    result = automatic.run_stage2(root, receipt)
    assert (baseline / "checkpoint.jsonl").read_bytes() == sealed
    assert result["complete"] is (not training_failure), result
    assert calls == (["training"] if training_failure else ["training", "evaluation"])
    if not training_failure:
        assert result["scientific_score"]["decision"] == "ADAPTATION_BENEFIT_DEMONSTRATED"
        assert result["additional_modeled_cu"] == pytest.approx(0.7)
        assert result["actual_final_provider_charge_cu"] is None
    with pytest.raises(ValueError, match="already consumed"):
        automatic.run_stage2(root, receipt)


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

    def verify_absent(self, name: str, *, allocation_attempted: bool = True) -> bool:
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


@pytest.mark.parametrize("bad_prepare_binding", [False, True])
def test_stage2_training_checks_prepare_receipt_before_work_and_models_cost(
    tmp_path: Path, bad_prepare_binding: bool
) -> None:
    class Client(TrainingClient):
        def start_watchdog(self, name: str, receipt: Path) -> bool:
            assert self.watchdog_seconds == 7020
            self.calls.append("watchdog")
            return True

        def snapshot(self) -> dict[str, Any]:
            value = super().snapshot()
            value["usage_rate_cu_per_hour"] = 1.15 if self.active else 0.0
            return value

        def download(self, name: str, remote_path: str, local: Path) -> bool:
            if local.name != "prepare-status.json":
                return super().download(name, remote_path, local)
            value = {
                "status": "READY",
                "binding": self.binding,
                "plan_sha256": self.binding["plan_sha256"],
                "runtime_qualification": {"qualified": True},
                "snapshot_path": "/SYNTHETIC/snapshot",
                "stages": [{"stage": "prepare", "returncode": 0, "timed_out": False}],
                "weights": {
                    "model_revision": decision.load_protocol()["candidate_model"]["revision"],
                    "weight_files": [{"SYNTHETIC": True}],
                    "support_files": {
                        name: {"sha256": digest}
                        for name, digest in v3.load_profile()["tokenizer"]["files"].items()
                    },
                },
            }
            if bad_prepare_binding:
                value["binding"] = {"SYNTHETIC wrong binding": True}
            local.write_text(json.dumps(value))
            return True

    (tmp_path / "source.tar").write_bytes(b"SYNTHETIC source")
    (tmp_path / "baseline").mkdir()
    (tmp_path / "baseline/checkpoint.jsonl").write_bytes(b"SYNTHETIC sealed baseline")
    directory = tmp_path / "training"
    directory.mkdir()
    proposed = _stage2_proposal()
    grant = {**proposed, "owner_receipt_sha256": "d" * 64}
    policy = automatic.stage2_approval(proposed, _stage2_approval(proposed))
    client = Client()
    result = automatic.training_session(
        directory, grant, 1, None, 1.4375, 3.111, client, cost_policy=policy, prepare_seconds=840
    )
    assert result["passed"] is (not bad_prepare_binding), result
    assert ("work" in client.calls) is (not bad_prepare_binding)
    assert result["cost_accounting"]["cost_status"] == "MODELED"
    assert result["cost_accounting"]["actual_spending_bound_guaranteed"] is False
    assert client.calls.count("new") == 1
    assert client.calls[-3:] == ["stop", "both_inventories", ("disarm", True)]


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
    write_authorized_policy(tmp_path)
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
        accounting = cost.conservative_charge(
            policy=COST_POLICY,
            balance_before=100,
            balance_after=99.8,
            elapsed_seconds=60,
            observed_rates=[1.15],
            teardown_verified=True,
        )
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
                {
                    "source_identity": source,
                    "sessions": [
                        {
                            "index": 1,
                            "committed_items": 581,
                            "cost_status": "KNOWN",
                            "teardown_verified": True,
                            "compute_units_spent": accounting["conservative_cu"],
                            "cost_accounting": accounting,
                        }
                    ],
                }
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
    write_authorized_policy(tmp_path)
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


def test_cached_native_projection_uses_fp32_operations_not_uncached_or_fp16_rate() -> None:
    report = _physical_fixture()
    report["native_calibration_timing"] = {"tokens": 123, "seconds": 299.04}
    report["rows"][0]["candidates"][0]["c_call"]["keep"] = 1000
    with pytest.raises(ValueError, match="budget"):
        automatic.measured_plan(report, 1.15, 45)
    plan = automatic.measured_plan(report, 1.15, 45, native_cache=True)
    assert plan["item_cost_bounds_seconds"]["ZERO_SHOT_UNCONSTRAINED"] < 10
    assert plan["native_cache_projection"]["uncached_native_observation"]["seconds"] == 299.04
    assert "projection" in plan["native_cache_projection"]["basis"]
    native_bound = plan["native_cache_projection"]["per_session_native_calibration_seconds_bound"]
    assert plan["bounds"]["inference_overhead_seconds"] >= 100 + native_bound
    assert plan["generation_seconds_per_session"] == (
        3300 - 180 - plan["bounds"]["inference_overhead_seconds"] - 60
    )
    automatic.validate_plan(plan, report, 1.15, 45, native_cache=True)
    with pytest.raises(ValueError):
        automatic.validate_plan(plan, report, 1.15, 45)


def test_native_continuation_preserves_original_paid_cost_and_terminal_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_root = tmp_path / "owner"
    owner_root.mkdir()
    owner = owner_root / "owner-delegated-budget-50cu-v2.json"
    owner.write_text(
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
    identity = [{"commit": "a" * 40, "tree": "b" * 40}]
    monkeypatch.setattr(execution, "source_identity", lambda: identity[0])

    def archive(path: Path) -> tuple[Path, str]:
        path.write_bytes(identity[0]["commit"].encode())
        return path, identity[0]["commit"]

    monkeypatch.setattr(execution, "source_archive", archive)
    monkeypatch.setattr(
        diagnostic_session, "head_archive_sha256", lambda: v3.sha256(identity[0]["commit"].encode())
    )
    monkeypatch.setattr(
        automatic, "cache_compatibility", lambda predecessor: {"synthetic_kernel": "e" * 64}
    )
    directory = automatic.ROOT / v3.sha256(owner.read_bytes())
    original = automatic.prepare(directory)
    budget = automatic.Budget(directory, original)
    control = directory / "diagnostic-control.json"
    control.write_text('{"passed":true}')
    budget.reserve("diagnostic", "DIAGNOSTIC", 3)
    budget.close("diagnostic", 0.3564, control, passed=True)
    terminal = directory / "terminal-anomaly.json"
    terminal.write_text(
        json.dumps(
            {"error_detail": "measured conservative campaign exceeds remaining delegated budget"}
        )
    )
    saved = {
        name: (directory / name).read_bytes()
        for name in [
            "grant.json",
            "source.tar",
            "budget-ledger.json",
            "diagnostic-charge.json",
            "terminal-anomaly.json",
        ]
    }
    identity[0] = {"commit": "c" * 40, "tree": "d" * 40}
    active = automatic.prepare_native_cache_continuation(directory)
    automatic.validate_grant(directory, active)
    assert active["native_cache"] is True
    assert automatic.Budget(directory, original).remaining() == pytest.approx(49.6436)
    assert all((directory / name).read_bytes() == data for name, data in saved.items())
    assert automatic.source_archive_path(directory, active).name == "source-native-cache.tar"
    with pytest.raises(ValueError, match="already prepared"):
        automatic.prepare_native_cache_continuation(directory)
    with pytest.raises(ValueError, match="finite owner scope"):
        automatic.validate_grant(directory, {**active, "maximum_new_cu": 100})
    terminal.write_text('{"error_detail":"paid baseline failed"}')
    with pytest.raises(ValueError, match="nonpaid planning"):
        automatic.validate_grant(directory, active)


def test_qualified_numerical_kernel_certificate_matches_real_predecessor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hashes = automatic.cache_compatibility("37367746c4187bbf3e24fa95757ec473a31daab3")
    assert hashes["scripts/a02_v3_constrained.py"]
    original = Path.read_bytes
    numerical = execution.ROOT / "scripts/a02_v3_numerics.py"

    def changed(path: Path) -> bytes:
        return original(path) + (b"\nCHANGED" if path == numerical else b"")

    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(ValueError, match="source changed"):
        automatic.cache_compatibility("37367746c4187bbf3e24fa95757ec473a31daab3")
