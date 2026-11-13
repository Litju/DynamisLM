from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_contract as v3
from scripts import a02_v3_cost as cost
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
    assert entry["compute_units_spent"] == accounting["conservative_cu"] > 0.04
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
    assert len(client.created) == len(ledger["sessions"]) <= 9
    assert sum(s["compute_units_spent"] for s in ledger["sessions"]) > 0.3
    assert len(ledger["sessions"]) < PLAN["session_count"]  # stopped by the cap, not the count


def _kwargs(tmp_path: Path, client: FakeColab) -> dict[str, Any]:
    archive = tmp_path / "source.tar"
    archive.write_bytes(b"source")
    return {
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


@pytest.mark.parametrize("policy", [None, {}, {"schema": "X"}])
def test_missing_or_invalid_cost_policy_blocks_the_first_allocation(
    tmp_path: Path, policy: Any
) -> None:
    client = FakeColab(tmp_path / "remote", items_per_session=3)
    result = execution.run_campaign(**_kwargs(tmp_path, client), cost_policy=policy)
    assert result["status"] == "NOT_ADMITTED" and "cost policy" in result["reason"]
    assert client.created == [] and not (tmp_path / "ledger.json").exists()
    assert not list((tmp_path / "run").glob("session-*-used.json"))  # no marker consumed
    with pytest.raises(execution.AdmissionError, match="cost policy"):
        execution.run_session(**_kwargs(tmp_path, client), session_index=1, cost_policy=policy)


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
    with pytest.raises(execution.AdmissionError, match="cost policy"):
        execution.run_session(**_kwargs(tmp_path, client), session_index=1, cost_policy=policy)
    assert client.created == []


def test_pricing_that_cannot_fit_one_session_is_refused_before_allocation(
    tmp_path: Path,
) -> None:
    client = FakeColab(tmp_path / "remote", items_per_session=3, cost_per_session=0.0)
    expensive = {**COST_POLICY, "startup_charge_cu": PER_SESSION}
    result = execution.run_campaign(**_kwargs(tmp_path, client), cost_policy=expensive)
    assert result["status"] == "NOT_ADMITTED" and "pricing" in result["reason"]
    assert client.created == []


def test_pricing_that_exhausts_the_cumulative_allowance_is_refused_at_admission(
    tmp_path: Path,
) -> None:
    client = FakeColab(tmp_path / "remote", items_per_session=3)
    kwargs = _kwargs(tmp_path, client)
    kwargs["authorization"] = _allowance(cumulative_cap_cu=round(PER_SESSION * 1.05, 4))
    ledger = execution.ledger_new(PLAN)
    ledger["sessions"].append(
        {
            "index": 1,
            "name": "prior",
            "cost_status": "KNOWN",
            "teardown_verified": True,
            "compute_units_spent": 0.3,
            "cost_accounting": {"cost_status": "KNOWN", "conservative_cu": 0.3},
        }
    )
    with pytest.raises(execution.AdmissionError, match="cumulative"):
        execution.admit(
            plan=PLAN,
            ledger=ledger,
            authorization=kwargs["authorization"],
            snapshot=QUIET,
            session_index=2,
            now=NOW,
            cost_policy=COST_POLICY,
        )


def test_uncertain_teardown_cost_blocks_all_further_allocation(tmp_path: Path) -> None:
    client = Supervised(tmp_path / "remote", items_per_session=3)
    client.verify_script = [False] * 500
    assert _campaign(tmp_path, client)["status"] == "STOPPED_ON_ANOMALY"
    entry = _ledger(tmp_path)["sessions"][0]
    assert entry["cost_status"] == "UNKNOWN" and entry["teardown_verified"] is False
    client.verify_script = []
    assert _campaign(tmp_path, client)["status"] == "NOT_ADMITTED"
    assert len(client.created) == 1


def _legacy_ledger() -> dict[str, Any]:
    ledger = execution.ledger_new(PLAN)
    ledger["sessions"].append(
        {"index": 1, "name": "legacy", "cost_status": "KNOWN", "compute_units_spent": 0.0}
    )
    return ledger


def test_prior_session_understated_by_the_old_algorithm_is_not_trusted() -> None:
    allowance = _allowance(cumulative_cap_cu=round(PER_SESSION * 1.5, 4))
    ledger = _legacy_ledger()
    ledger["sessions"][0]["teardown_verified"] = True
    with pytest.raises(execution.AdmissionError, match="cumulative"):
        execution.admit(
            plan=PLAN, ledger=ledger, authorization=allowance, snapshot=QUIET,
            session_index=2, now=NOW,
        )  # fmt: skip
    assert ledger["sessions"][0]["compute_units_spent"] == 0.0  # never rewritten


def test_missing_teardown_evidence_is_refused() -> None:
    for teardown in (None, False, "yes"):
        ledger = _legacy_ledger()
        if teardown is not None:
            ledger["sessions"][0]["teardown_verified"] = teardown
        with pytest.raises(execution.AdmissionError, match="teardown evidence"):
            execution.admit(
                plan=PLAN, ledger=ledger, authorization=_allowance(), snapshot=QUIET,
                session_index=2, now=NOW,
            )  # fmt: skip


def test_an_inherited_flag_alone_never_exempts_an_entry(monkeypatch: Any) -> None:
    allowance = _allowance(cumulative_cap_cu=round(PER_SESSION * 1.5, 4))
    ledger = _legacy_ledger()
    ledger["sessions"][0]["inherited"] = True  # forged: no sealed receipt backs it
    with pytest.raises(execution.AdmissionError, match="teardown evidence"):
        execution.admit(
            plan=PLAN, ledger=ledger, authorization=allowance, snapshot=QUIET,
            session_index=2, now=NOW,
        )  # fmt: skip
    # Only an entry whose canonical hash is sealed from the verified predecessor is exempt.
    digest = v3.sha256(v3.canonical(ledger["sessions"][0]).encode())
    monkeypatch.setattr(execution, "SEALED_INHERITED_ENTRY_SHA256", frozenset({digest}))
    assert execution.admit(
        plan=PLAN, ledger=ledger, authorization=allowance, snapshot=QUIET,
        session_index=2, now=NOW,
    )["admitted"]  # fmt: skip


def _real_entry(tmp_path: Path) -> dict[str, Any]:
    client = FakeColab(tmp_path / "remote", items_per_session=3, cost_per_session=0.0)
    _session(tmp_path, client, 1)
    entry: dict[str, Any] = _ledger(tmp_path)["sessions"][0]
    return entry


def test_a_genuine_record_is_verified_and_counted_at_its_recorded_amount(tmp_path: Path) -> None:
    entry = _real_entry(tmp_path)
    ledger = {"schema": execution.LEDGER_SCHEMA}
    assert execution._verified_accounting(entry, COST_POLICY)
    assert (
        execution._ledger_charge(entry, ledger, PER_SESSION, COST_POLICY)
        == (entry["compute_units_spent"])
    )
    assert execution._ledger_charge(entry, ledger, PER_SESSION, None) == PER_SESSION


@pytest.mark.parametrize(
    "tamper",
    [
        lambda e: e.update(compute_units_spent=-5.0)
        or e["cost_accounting"].update(conservative_cu=-5.0),
        lambda e: e.update(compute_units_spent=float("nan"))
        or e["cost_accounting"].update(conservative_cu=float("nan")),
        lambda e: e.update(compute_units_spent=0.0)
        or e["cost_accounting"].update(conservative_cu=0.0),  # below the minimum for any session
        lambda e: e["cost_accounting"].update(cost_policy_sha256="0" * 64),
        lambda e: e["cost_accounting"].update(schema="OTHER"),
        lambda e: e["cost_accounting"].update(elapsed_seconds=0.0, conservative_cu=0.0001)
        or e.update(compute_units_spent=0.0001),
        lambda e: e.update(teardown_verified=None),
        lambda e: e["cost_accounting"].update(cost_confidence="PRECISE_PROVIDER"),
    ],
)
def test_forged_or_malformed_accounting_never_lowers_the_guard(tmp_path: Path, tamper: Any) -> None:
    entry = _real_entry(tmp_path)
    tamper(entry)
    assert not execution._verified_accounting(entry, COST_POLICY)
    ledger = {"schema": execution.LEDGER_SCHEMA}
    assert execution._ledger_charge(entry, ledger, PER_SESSION, COST_POLICY) >= PER_SESSION


def test_negative_matching_amounts_cannot_defeat_the_cumulative_guard(tmp_path: Path) -> None:
    entry = _real_entry(tmp_path)
    entry["compute_units_spent"] = -50.0
    entry["cost_accounting"]["conservative_cu"] = -50.0
    ledger = execution.ledger_new(PLAN)
    ledger["sessions"].append(entry)
    with pytest.raises(execution.AdmissionError, match="malformed"):
        execution.admit(
            plan=PLAN, ledger=ledger, authorization=_allowance(), snapshot=QUIET,
            session_index=2, now=NOW, cost_policy=COST_POLICY,
        )  # fmt: skip


def _approval(policy: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    return {
        "schema": execution.POLICY_APPROVAL_SCHEMA,
        "policy_sha256": cost.policy_sha256(policy),
        "approved": True,
        "owner_statement": "synthetic owner approval for the exact policy bytes",
        "recorded_utc": "2026-11-13T00:00:00+00:00",
        **overrides,
    }


def _write_policy(directory: Path, policy: dict[str, Any], approval: Any) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "cost-policy.json").write_text(json.dumps(policy))
    if approval is not None:
        (directory / "cost-policy-approval.json").write_text(json.dumps(approval))


def test_policy_loads_only_with_an_exact_owner_approval(tmp_path: Path) -> None:
    _write_policy(tmp_path / "ok", COST_POLICY, _approval(COST_POLICY))
    assert execution.load_authorized_policy(tmp_path / "ok") == COST_POLICY
    changed = {**COST_POLICY, "startup_charge_cu": 0.0}  # understated pricing, valid shape
    cases = {
        "no_approval": (COST_POLICY, None),
        "other_policy": (changed, _approval(COST_POLICY)),
        "not_approved": (COST_POLICY, _approval(COST_POLICY, approved=False)),
        "blank_statement": (COST_POLICY, _approval(COST_POLICY, owner_statement=" ")),
        "future": (COST_POLICY, _approval(COST_POLICY, recorded_utc="2999-01-01T00:00:00+00:00")),
        "extra_key": (COST_POLICY, {**_approval(COST_POLICY), "x": 1}),
        "naive_time": (COST_POLICY, _approval(COST_POLICY, recorded_utc="2026-11-13T00:00:00")),
    }
    for name, (policy, approval) in cases.items():
        _write_policy(tmp_path / name, policy, approval)
        with pytest.raises(execution.AdmissionError, match="cost policy|approved"):
            execution.load_authorized_policy(tmp_path / name)
    with pytest.raises(execution.AdmissionError):
        execution.load_authorized_policy(tmp_path / "does-not-exist")
