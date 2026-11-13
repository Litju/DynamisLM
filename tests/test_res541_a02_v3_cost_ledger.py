from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_execution as execution

from test_res541_a02_v3_execution import (
    COST_POLICY,
    NOW,
    PLAN,
    QUIET,
    FakeColab,
    _allowance,
    _campaign,
    _session,
)
from test_res541_a02_v3_supervision import Supervised

PER_SESSION = PLAN["compute_units"]["per_session_cap"]


@pytest.fixture(autouse=True)
def _env(monkeypatch: Any) -> None:
    monkeypatch.setattr(execution, "COST_POLL_SECONDS", 0.01)
    monkeypatch.setattr(
        execution, "source_identity", lambda: {"commit": "a" * 40, "tree": "b" * 40}
    )


def _ledger(tmp_path: Path) -> dict[str, Any]:
    ledger: dict[str, Any] = json.loads((tmp_path / "ledger.json").read_text())
    return ledger


def test_equal_displayed_balances_are_charged_a_positive_conservative_amount(
    tmp_path: Path,
) -> None:
    client = FakeColab(tmp_path / "remote", items_per_session=3, cost_per_session=0.0)
    state = _session(tmp_path, client, 1)
    entry = _ledger(tmp_path)["sessions"][0]
    accounting = entry["cost_accounting"]
    assert accounting["observed_displayed_delta_cu"] == 0
    assert entry["cost_status"] == "KNOWN" and accounting["cost_confidence"] == "CONSERVATIVE_BOUND"
    assert entry["compute_units_spent"] == accounting["conservative_cu"] > 0.1
    assert accounting["conservative_cu"] >= accounting["time_estimated_cu"]
    assert accounting["remaining_budget_after_cu"] < PLAN["compute_units"]["cumulative_cap"]
    assert state["cost_accounting"] == accounting and entry["teardown_verified"] is True


def test_cumulative_guard_cannot_be_defeated_by_rounded_balances(tmp_path: Path) -> None:
    client = FakeColab(tmp_path / "remote", items_per_session=3, cost_per_session=0.0)
    allowance = _allowance(cumulative_cap_cu=round(PER_SESSION * 2, 4))
    result = _campaign(tmp_path, client, allowance)
    ledger = _ledger(tmp_path)
    displayed = sum(s["cost_accounting"]["observed_displayed_delta_cu"] for s in ledger["sessions"])
    assert displayed == 0  # the old algorithm would have recorded zero spend forever
    assert result["status"] == "NOT_ADMITTED" and "cumulative" in result["reason"]
    assert len(client.created) == len(ledger["sessions"]) <= 4
    assert sum(s["compute_units_spent"] for s in ledger["sessions"]) > 0.3


def test_missing_cost_policy_makes_cost_unknown_and_blocks_allocation(tmp_path: Path) -> None:
    client = FakeColab(tmp_path / "remote", items_per_session=3)
    archive = tmp_path / "source.tar"
    archive.write_bytes(b"source")
    kwargs: dict[str, Any] = {
        "client": client,
        "plan": PLAN,
        "ledger_path": tmp_path / "ledger.json",
        "authorization": _allowance(),
        "run_dir": tmp_path / "run",
        "source_archive": archive,
        "binding": {
            "plan_sha256": PLAN["plan_sha256"],
            "item_cost_bounds": PLAN["item_cost_bounds_seconds"],
            "source_identity": {"commit": "a" * 40, "tree": "b" * 40},
        },
        "now": NOW,
    }
    result = execution.run_campaign(**kwargs)
    assert result["status"] == "STOPPED_ON_ANOMALY" and "UNKNOWN" in result["anomaly"]
    assert _ledger(tmp_path)["sessions"][0]["cost_status"] == "UNKNOWN"
    again = execution.run_campaign(**kwargs)
    assert again["status"] == "NOT_ADMITTED" and len(client.created) == 1


@pytest.mark.parametrize("fault", ["negative_balance", "nan_balance", "rising_balance"])
def test_untrustworthy_ending_balance_is_unknown_and_blocks_allocation(
    tmp_path: Path, fault: str
) -> None:
    client = FakeColab(tmp_path / "remote", items_per_session=3, cost_per_session=0.0)
    original = client.stop

    def stop(name: str) -> bool:
        ok = original(name)
        client.balance = {
            "negative_balance": -1.0,
            "nan_balance": float("nan"),
            "rising_balance": 200.0,
        }[fault]
        return ok

    client.stop = stop  # type: ignore[method-assign]
    result = _campaign(tmp_path, client)
    assert result["status"] == "STOPPED_ON_ANOMALY"
    assert _ledger(tmp_path)["sessions"][0]["cost_status"] == "UNKNOWN"
    client.stop = original  # type: ignore[method-assign]
    client.balance = 87.08
    assert _campaign(tmp_path, client)["status"] == "NOT_ADMITTED"
    assert len(client.created) == 1


def test_unverified_pricing_component_blocks_allocation(tmp_path: Path) -> None:
    client = FakeColab(tmp_path / "remote", items_per_session=3)
    policy = {k: v for k, v in COST_POLICY.items() if k != "billing_granularity_seconds"}
    archive = tmp_path / "source.tar"
    archive.write_bytes(b"source")
    state = execution.run_session(
        client=client,
        plan=PLAN,
        ledger_path=tmp_path / "ledger.json",
        authorization=_allowance(),
        session_index=1,
        run_dir=tmp_path / "run",
        source_archive=archive,
        binding={
            "plan_sha256": PLAN["plan_sha256"],
            "item_cost_bounds": PLAN["item_cost_bounds_seconds"],
            "source_identity": {"commit": "a" * 40, "tree": "b" * 40},
        },
        now=NOW,
        cost_policy=policy,
    )
    assert state["cost_accounting"]["cost_status"] == "UNKNOWN"
    with pytest.raises(execution.AdmissionError, match="unknown cost"):
        execution.admit(
            plan=PLAN,
            ledger=_ledger(tmp_path),
            authorization=_allowance(),
            snapshot=QUIET,
            session_index=2,
            now=NOW,
        )


def test_session_cost_above_the_session_cap_is_an_anomaly_and_blocks_more(
    tmp_path: Path,
) -> None:
    client = FakeColab(tmp_path / "remote", items_per_session=3, cost_per_session=0.0)
    expensive = {**COST_POLICY, "startup_charge_cu": PER_SESSION}
    archive = tmp_path / "source.tar"
    archive.write_bytes(b"source")
    result = execution.run_campaign(
        client=client,
        plan=PLAN,
        ledger_path=tmp_path / "ledger.json",
        authorization=_allowance(),
        run_dir=tmp_path / "run",
        source_archive=archive,
        binding={
            "plan_sha256": PLAN["plan_sha256"],
            "item_cost_bounds": PLAN["item_cost_bounds_seconds"],
            "source_identity": {"commit": "a" * 40, "tree": "b" * 40},
        },
        now=NOW,
        cost_policy=expensive,
    )
    assert result["status"] == "STOPPED_ON_ANOMALY" and "exceeded its bound" in result["anomaly"]
    assert len(client.created) == 1


def test_uncertain_teardown_cost_blocks_all_further_allocation(tmp_path: Path) -> None:
    client = Supervised(tmp_path / "remote", items_per_session=3)
    client.verify_script = [False] * 500
    assert _campaign(tmp_path, client)["status"] == "STOPPED_ON_ANOMALY"
    entry = _ledger(tmp_path)["sessions"][0]
    assert entry["cost_status"] == "UNKNOWN" and entry["teardown_verified"] is False
    client.verify_script = []
    assert _campaign(tmp_path, client)["status"] == "NOT_ADMITTED"
    assert len(client.created) == 1


def test_prior_session_understated_by_the_old_algorithm_is_not_trusted(tmp_path: Path) -> None:
    ledger = execution.ledger_new(PLAN)
    ledger["sessions"].append(
        {"index": 1, "name": "legacy", "cost_status": "KNOWN", "compute_units_spent": 0.0}
    )
    allowance = _allowance(cumulative_cap_cu=round(PER_SESSION * 1.5, 4))
    with pytest.raises(execution.AdmissionError, match="cumulative"):
        execution.admit(
            plan=PLAN,
            ledger=ledger,
            authorization=allowance,
            snapshot=QUIET,
            session_index=2,
            now=NOW,
        )
    # The legacy entry is never rewritten, and a sealed inherited receipt keeps its amount.
    assert ledger["sessions"][0]["compute_units_spent"] == 0.0
    ledger["sessions"][0]["inherited"] = True
    assert execution.admit(
        plan=PLAN,
        ledger=ledger,
        authorization=allowance,
        snapshot=QUIET,
        session_index=2,
        now=NOW,
    )["admitted"]


def test_forged_accounting_record_cannot_lower_a_charge() -> None:
    entry = {
        "index": 1,
        "cost_status": "KNOWN",
        "compute_units_spent": 0.0,
        "cost_accounting": {"cost_status": "KNOWN", "conservative_cu": 0.5},
    }
    assert execution._ledger_charge(entry, {"schema": execution.LEDGER_SCHEMA}, PER_SESSION) == (
        PER_SESSION
    )
