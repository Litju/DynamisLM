from __future__ import annotations

import copy
import math
from typing import Any

import pytest
from scripts import a02_v3_cost as cost

POLICY: dict[str, Any] = {
    "schema": cost.COST_POLICY_SCHEMA,
    "balance_display_resolution_cu": 0.01,
    "billing_granularity_seconds": 60,
    "posting_delay_seconds": 120,
    "startup_charge_cu": 0.05,
    "verified_rate_cu_per_hour": 1.15,
    "operational_reserve_cu": 0.02,
    "verification": {
        "source": "synthetic test fixture",
        "verified_at_utc": "2026-11-13T00:00:00+00:00",
    },
}


def charge(**overrides: Any) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "policy": POLICY,
        "balance_before": 87.08,
        "balance_after": 87.08,
        "elapsed_seconds": 600.0,
        "observed_rates": [1.15],
        "teardown_verified": True,
    }
    return cost.conservative_charge(**{**arguments, **overrides})


def test_equal_displayed_balances_do_not_mean_zero_cost() -> None:
    result = charge()
    assert result["observed_displayed_delta_cu"] == 0
    # 600 s + 120 s posting delay -> 12 billed minutes at 1.15 CU/h, plus startup and reserve.
    expected = 0.05 + 1.15 * 720 / 3600 + 0.02
    assert result["cost_status"] == "KNOWN"
    assert result["conservative_cu"] >= expected - 1e-9
    assert result["conservative_cu"] > 0.29
    assert result["conservative_cu"] > result["observed_displayed_delta_cu"]


def test_small_charge_hidden_by_rounding_is_still_bounded() -> None:
    result = charge(elapsed_seconds=1, balance_after=87.08)
    assert result["delta_upper_bound_cu"] == 0.01
    assert result["conservative_cu"] >= 0.05 + 1.15 * 180 / 3600  # one billed granule + delay


def test_delayed_charge_posting_is_covered_by_the_time_bound() -> None:
    posted_late = charge(balance_after=87.08, elapsed_seconds=1800)
    posted = charge(balance_after=86.58, elapsed_seconds=1800)
    assert posted_late["conservative_cu"] >= 1.15 * 1800 / 3600
    assert posted["delta_upper_bound_cu"] > posted_late["delta_upper_bound_cu"]


def test_startup_charge_is_included() -> None:
    without = charge(policy={**POLICY, "startup_charge_cu": 0.0})
    with_startup = charge(policy={**POLICY, "startup_charge_cu": 0.3})
    assert with_startup["conservative_cu"] - without["conservative_cu"] >= 0.29


def test_rate_increase_during_a_session_uses_the_highest_observed_rate() -> None:
    low = charge(observed_rates=[1.15])
    high = charge(observed_rates=[1.15, 1.9])
    assert high["rate_used_cu_per_hour"] == 1.9
    assert high["conservative_cu"] > low["conservative_cu"]


@pytest.mark.parametrize("bad", [-0.01, math.nan, math.inf, None, "87"])
def test_negative_or_nonfinite_balances_make_cost_unknown(bad: Any) -> None:
    assert charge(balance_after=bad)["cost_status"] == "UNKNOWN"
    assert charge(balance_before=bad)["cost_status"] == "UNKNOWN"


def test_a_rising_balance_is_untrustworthy() -> None:
    assert charge(balance_after=90.0)["cost_status"] == "UNKNOWN"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.pop("billing_granularity_seconds"),  # unknown charging granularity
        lambda p: p.update(billing_granularity_seconds=0),
        lambda p: p.update(startup_charge_cu=math.nan),
        lambda p: p.update(verified_rate_cu_per_hour=0),
        lambda p: p.update(balance_display_resolution_cu=-1),
        lambda p: p.update(
            verification={"source": "", "verified_at_utc": "2026-11-13T00:00:00+00:00"}
        ),
        lambda p: p.update(verification={"source": "x", "verified_at_utc": "2026-11-13T00:00:00"}),
        lambda p: p.update(unexpected=True),
    ],
)
def test_unverifiable_pricing_component_makes_cost_unknown(mutate: Any) -> None:
    policy = copy.deepcopy(POLICY)
    mutate(policy)
    assert charge(policy=policy)["cost_status"] == "UNKNOWN"
    assert charge(policy=None)["cost_status"] == "UNKNOWN"


@pytest.mark.parametrize("elapsed", [-1.0, math.nan, math.inf, None])
def test_untrustworthy_duration_is_unknown(elapsed: Any) -> None:
    assert charge(elapsed_seconds=elapsed)["cost_status"] == "UNKNOWN"


def test_missing_or_invalid_rate_is_unknown_not_zero() -> None:
    assert charge(observed_rates=[])["cost_status"] == "UNKNOWN"
    assert charge(observed_rates=[1.15, 0.0])["cost_status"] == "UNKNOWN"


def test_unverified_teardown_is_unknown() -> None:
    assert charge(teardown_verified=False)["cost_status"] == "UNKNOWN"


def test_precise_provider_charge_replaces_the_estimate_but_not_a_larger_delta() -> None:
    assert charge(precise_charge_cu=0.123)["cost_confidence"] == "PRECISE_PROVIDER"
    assert charge(precise_charge_cu=0.123)["conservative_cu"] == 0.123
    assert charge(balance_after=86.0, precise_charge_cu=0.1)["conservative_cu"] >= 1.08
    assert charge(precise_charge_cu=-1)["cost_status"] == "UNKNOWN"


def test_no_allocation_is_zero_only_when_the_balance_did_not_move() -> None:
    assert charge(allocation_attempted=False)["conservative_cu"] == 0.0
    assert charge(allocation_attempted=False, balance_after=80.0)["cost_status"] == "UNKNOWN"


def test_charge_is_rounded_up_never_down() -> None:
    result = charge()
    assert result["conservative_cu"] * 10_000 == pytest.approx(
        round(result["conservative_cu"] * 10_000)
    )
    assert result["conservative_cu"] >= (
        max(result["delta_upper_bound_cu"], result["time_estimated_cu"])
        + result["operational_reserve_cu"]
        - 1e-9
    )


def test_live_projection_and_final_charge_use_one_formula() -> None:
    result = charge(elapsed_seconds=777.0, balance_after=86.9)
    projected = cost.projected_bound(POLICY, observed_delta=0.18, elapsed_seconds=777.0, rate=1.15)
    assert result["conservative_cu"] == pytest.approx(projected, abs=1e-4)
    assert cost.projected_bound(POLICY, observed_delta=0, elapsed_seconds=0, rate=1.15) >= (
        POLICY["startup_charge_cu"] + POLICY["operational_reserve_cu"]
    )
