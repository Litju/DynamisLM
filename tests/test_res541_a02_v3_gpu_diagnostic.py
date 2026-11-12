"""Adversarial controls for an isolated diagnostic, never a scientific campaign (RES-541)."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_contract as v3
from scripts import a02_v3_diagnostic_session as session
from scripts import a02_v3_execution as execution
from scripts import a02_v3_gpu_diagnostic as diagnostic


@pytest.fixture
def bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any, Any, Path]:
    monkeypatch.setattr(
        execution, "source_identity", lambda: {"commit": "a" * 40, "tree": "b" * 40}
    )
    monkeypatch.setattr(session, "ROOT", tmp_path / "single-attempt")
    archive = tmp_path / "source.tar"
    archive.write_bytes(b"synthetic diagnostic archive; no model weights")
    monkeypatch.setattr(session, "head_archive_sha256", lambda: v3.sha256(archive.read_bytes()))
    proposal = session.proposal(archive)
    approval = {
        "schema": session.AUTH_SCHEMA,
        "proposal_sha256": proposal["proposal_sha256"],
        "accept_a1_for_diagnostic_only": True,
        "approve_exact_source_one_session": True,
        "maximum_new_cu": 0.26,
    }
    quota = {"balance": 10.0, "usage_rate_cu_per_hour": 0.0, "active_sessions": []}
    return proposal, approval, quota, archive


def test_bounded_cost_preserves_history_and_frozen_gate() -> None:
    spec = diagnostic.specification()
    assert spec["historical_cu"] == 0.2537
    assert spec["maximum_new_cu"] == 0.26
    assert spec["tolerance_nats"] == 0.001
    assert spec["scientific_evaluations"] == 0
    assert diagnostic.bounded_cost(1.25, 0) <= 0.26
    with pytest.raises(ValueError, match="insufficient"):
        diagnostic.bounded_cost(1.25, 0.01)


@pytest.mark.parametrize("rate", [0.0, -1, float("nan"), float("inf"), 1.26])
def test_bad_rates_fail_closed(rate: float) -> None:
    with pytest.raises(ValueError):
        diagnostic.bounded_cost(rate)


def test_admission_requires_both_explicit_owner_decisions(bound: Any) -> None:
    proposed, approval, quota, _ = bound
    for altered in (
        None,
        {},
        {**approval, "accept_a1_for_diagnostic_only": False},
        {**approval, "approve_exact_source_one_session": False},
        {**approval, "maximum_new_cu": 2.0},
    ):
        with pytest.raises(ValueError, match="owner"):
            session.admit(proposed, altered, quota, startup_cu=0, live_t4_rate=1.15)
    session.admit(proposed, approval, quota, startup_cu=0, live_t4_rate=1.15)


@pytest.mark.parametrize(
    "fault",
    ["expired", "future", "unknown_startup", "usage", "balance", "sessions", "source", "spec"],
)
def test_admission_negative_controls(
    bound: Any, fault: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    proposed, approval, quota, _ = bound
    now = datetime.now(UTC)
    startup: float | None = 0
    if fault == "expired":
        now += timedelta(days=2)
    elif fault == "future":
        now -= timedelta(days=2)
    elif fault == "unknown_startup":
        startup = None
    elif fault == "usage":
        quota["usage_rate_cu_per_hour"] = float("nan")
    elif fault == "balance":
        quota["balance"] = float("nan")
    elif fault == "sessions":
        quota["active_sessions"] = [{"name": "unrelated"}]
    elif fault == "source":
        monkeypatch.setattr(
            execution, "source_identity", lambda: {"commit": "c" * 40, "tree": "b" * 40}
        )
    else:
        proposed["specification"]["precision"] = "float16"
    with pytest.raises(ValueError):
        session.admit(proposed, approval, quota, startup_cu=startup, live_t4_rate=1.15, now=now)


class FakeClient:
    def __init__(self, quota: dict[str, Any], *, watchdog_ready: bool = True):
        self.quota = quota
        self.calls: list[Any] = []
        self.watchdog_ready = watchdog_ready

    def snapshot(self) -> dict[str, Any]:
        return deepcopy(self.quota)

    def sessions(self) -> list[str]:
        return []

    def start_watchdog(self, name: str, receipt: Path) -> Any:
        self.calls.append("watchdog")
        if not self.watchdog_ready:
            raise RuntimeError("watchdog not READY")
        return True

    def new(self, name: str) -> bool:
        self.calls.append("new")
        return True

    def hardware(self, name: str) -> str:
        self.quota["usage_rate_cu_per_hour"] = 1.15
        self.quota["active_sessions"] = [{"name": name}]
        return "T4"

    def upload(self, name: str, local: Path, remote: str) -> bool:
        self.calls.append("upload")
        return True

    def exec_stage(self, name: str, stage: str, timeout: int) -> dict[str, Any]:
        self.calls.append(stage)
        return {"returncode": 0 if stage == "prepare" else 1, "timed_out": False}

    def download(self, name: str, remote: str, local: Path) -> bool:
        self.calls.append("download")
        return False

    def stop(self, name: str) -> bool:
        self.calls.append("stop")
        self.quota["usage_rate_cu_per_hour"] = 0.0
        self.quota["active_sessions"] = []
        return True

    def verify_absent(self, name: str) -> bool:
        self.calls.append("both_inventories")
        return True

    def finish_watchdog(self, watchdog: Any, verified: bool) -> None:
        self.calls.append(("disarm", verified))


def test_remote_failure_tears_down_exact_target_without_retry(bound: Any) -> None:
    proposed, approval, quota, archive = bound
    client = FakeClient(quota)
    result = session.run(
        client=client,
        proposed=proposed,
        approval=approval,
        archive=archive,
        startup_cu=0,
        live_t4_rate=1.15,
    )
    assert result["passed"] is False
    assert client.calls.count("new") == 1
    assert client.calls.index("watchdog") < client.calls.index("new")
    assert client.calls[-3:] == ["stop", "both_inventories", ("disarm", True)]
    with pytest.raises(FileExistsError):
        session.run(
            client=client,
            proposed=proposed,
            approval=approval,
            archive=archive,
            startup_cu=0,
            live_t4_rate=1.15,
        )
    assert client.calls.count("new") == 1


def test_missing_watchdog_prevents_allocation(bound: Any) -> None:
    proposed, approval, quota, archive = bound
    client = FakeClient(quota, watchdog_ready=False)
    result = session.run(
        client=client,
        proposed=proposed,
        approval=approval,
        archive=archive,
        startup_cu=0,
        live_t4_rate=1.15,
    )
    assert result["passed"] is False
    assert client.calls == ["watchdog"]


@pytest.mark.parametrize(
    "fault", ["targets_match", "cache_state_consistent", "kv_dtype", "nan", "over_tolerance"]
)
def test_equal_scores_cannot_bypass_structural_or_precision_gates(fault: str) -> None:
    row: dict[str, Any] = {
        "complete": True,
        "winners_agree": True,
        "scorer_calls": 1,
        "candidates": [
            {
                "targets_match": True,
                "cache_state_consistent": True,
                "c_call": {"kv_dtype": "torch.float32"},
                "path_states": {"B": [{"kv_dtype": "torch.float32"}]},
            }
        ],
        "summary": {
            pair: {"max_abs_score_difference": 0.0, "candidates_above_tolerance": 0}
            for pair in ("A_vs_B", "B_vs_C", "A_vs_C")
        },
    }
    diagnostic.validate_row(row)
    if fault in {"targets_match", "cache_state_consistent"}:
        row["candidates"][0][fault] = False
    elif fault == "kv_dtype":
        row["candidates"][0]["c_call"]["kv_dtype"] = "torch.float16"
    else:
        row["summary"]["A_vs_C"]["max_abs_score_difference"] = (
            float("nan") if fault == "nan" else 0.00101
        )
    with pytest.raises(ValueError):
        diagnostic.validate_row(row)


@pytest.mark.parametrize("fault", [None, "digest", "binding", "failed", "missing"])
def test_source_bound_report_recovery(bound: Any, fault: str | None) -> None:
    import json

    proposed, approval, quota, archive = bound

    class SuccessfulClient(FakeClient):
        binding: dict[str, Any]

        def upload(self, name: str, local: Path, remote: str) -> bool:
            if remote == execution.REMOTE_BINDING:
                self.binding = json.loads(local.read_bytes())
            return True

        def exec_stage(self, name: str, stage: str, timeout: int) -> dict[str, Any]:
            return {"returncode": 0, "timed_out": False}

        def download(self, name: str, remote: str, local: Path) -> bool:
            evidence = json.dumps({"phase": "FINAL", "passed": fault != "failed"}) + "\n"
            if fault == "missing":
                return False
            if remote == session.REMOTE_REPORT:
                local.write_text(evidence)
            else:
                local.write_text(
                    json.dumps(
                        {
                            "status": "DIAGNOSTIC_COMPLETE",
                            "binding": self.binding if fault != "binding" else {},
                            "diagnostic_sha256": v3.sha256(evidence.encode())
                            if fault != "digest"
                            else "0" * 64,
                        }
                    )
                )
            return True

    client = SuccessfulClient(quota)
    result = session.run(
        client=client,
        proposed=proposed,
        approval=approval,
        archive=archive,
        startup_cu=0,
        live_t4_rate=1.15,
    )
    assert result["passed"] is (fault is None)
    assert result["target_absent"] is True
    if fault is not None:
        assert "evidence_error" in result


def test_campaign_estimate_uses_fp32_measurements_and_frozen_work_order() -> None:
    rows = [{"scorer_calls": 73, "timing_seconds": {"A": 10, "B": 5, "C": 2}}] * 3
    report = diagnostic.campaign_estimate(rows, {"tokens": 32, "seconds": 5}, 100)
    assert report["distribution"] == {"qualification": 1, "unconstrained": 290, "constrained": 290}
    assert not report["campaign_authorized"]
    assert report["expected"]["work_seconds"] == 36 + 290 * 7
    assert (
        report["conservative"]["maximum_cu_with_reserve"] > report["expected"]["cu_at_rate_ceiling"]
    )
    refused = diagnostic.campaign_estimate(rows, {"tokens": 32, "seconds": 5}, 900)
    assert not refused["conservative"]["fits"]


def test_diagnostic_remote_binding_is_distinct_from_campaign(tmp_path: Path) -> None:
    import json

    from scripts import a02_v3_remote as remote

    identity = {"commit": "a" * 40, "tree": "b" * 40}
    binding = {
        "schema": "RES541_A1_DIAGNOSTIC_REMOTE_BINDING_V1",
        "source_archive_sha256": "c" * 64,
        "source_revision": identity["commit"],
        "source_identity": identity,
        "plan_sha256": "d" * 64,
        "protocol_sha256": diagnostic.specification()["protocol_sha256"],
        "session_index": 1,
        "item_cost_bounds": {
            "QUALIFICATION": 1,
            "ZERO_SHOT_UNCONSTRAINED": 1,
            "ZERO_SHOT_CONSTRAINED": 1,
        },
        "numerical_diagnostic": diagnostic.specification(),
    }
    path = tmp_path / "binding.json"
    path.write_text(json.dumps(binding))
    assert remote.load_binding(path) == binding
    binding["schema"] = remote.BINDING_SCHEMA
    path.write_text(json.dumps(binding))
    with pytest.raises(ValueError, match="fields"):
        remote.load_binding(path)
