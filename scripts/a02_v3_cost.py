"""RES-541 conservative compute-unit accounting for paid Colab sessions.

Displayed balances are rounded, so a before/after difference can read zero (or understate) while
a session was really charged. The difference is therefore never a cost: it is one observation.
A session charge is the conservative combination of independently justified bounds:

* ``delta_upper``: displayed balance delta plus the documented display resolution;
* ``time_estimate``: startup charge plus verified rate times the *billed* seconds, i.e. the
  allocation-to-confirmed-stop duration plus the posting delay rounded up to the billing
  granularity;
* ``conservative = max(delta_upper, time_estimate) + operational_reserve``.

If authenticated precise billing is supplied it replaces the estimate. If any necessary
component is missing, unverified, non-finite or untrustworthy the session cost is ``UNKNOWN``
and no further allocation is admitted. The policy values are owner-verified at authorization
time and bound by hash into the ledger; this module invents none of them.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from datetime import datetime
from typing import Any

COST_POLICY_SCHEMA = "RES541_A02_V3_COST_POLICY_V1"
ACCOUNTING_SCHEMA = "RES541_A02_V3_SESSION_COST_V1"
POLICY_KEYS = frozenset(
    {
        "schema",
        "balance_display_resolution_cu",
        "billing_granularity_seconds",
        "posting_delay_seconds",
        "startup_charge_cu",
        "verified_rate_cu_per_hour",
        "operational_reserve_cu",
        "verification",
    }
)


class CostPolicyError(ValueError):
    """The cost policy is absent, malformed or not verified."""


def _positive(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and 0 < value < math.inf


def _non_negative(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and 0 <= value < math.inf


def validate_policy(policy: Any) -> dict[str, Any]:
    if not isinstance(policy, dict) or set(policy) != POLICY_KEYS:
        raise CostPolicyError("cost policy fields differ from the contract")
    verification = policy["verification"]
    if (
        policy["schema"] != COST_POLICY_SCHEMA
        or not _positive(policy["balance_display_resolution_cu"])
        or not isinstance(policy["billing_granularity_seconds"], int)
        or isinstance(policy["billing_granularity_seconds"], bool)
        or policy["billing_granularity_seconds"] < 1
        or not _non_negative(policy["posting_delay_seconds"])
        or not _non_negative(policy["startup_charge_cu"])
        or not _positive(policy["verified_rate_cu_per_hour"])
        or not _non_negative(policy["operational_reserve_cu"])
        or not isinstance(verification, dict)
        or set(verification) != {"source", "verified_at_utc"}
        or not isinstance(verification["source"], str)
        or not verification["source"].strip()
    ):
        raise CostPolicyError("cost policy component is missing, unverified or not finite")
    try:
        stamp = datetime.fromisoformat(str(verification["verified_at_utc"]))
    except ValueError as exc:
        raise CostPolicyError("cost policy verification time is not a timestamp") from exc
    if stamp.tzinfo is None:
        raise CostPolicyError("cost policy verification time needs a timezone")
    return policy


def policy_sha256(policy: dict[str, Any]) -> str:
    text = json.dumps(policy, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode()).hexdigest()


def projected_bound(
    policy: dict[str, Any], *, observed_delta: float, elapsed_seconds: float, rate: float
) -> float:
    """Conservative charge if the session ended after ``elapsed_seconds`` (policy must be valid).

    This is the single formula used for admission, live monitoring and final accounting.
    """
    resolution = float(policy["balance_display_resolution_cu"])
    granularity = int(policy["billing_granularity_seconds"])
    billed = (
        math.ceil(
            (max(elapsed_seconds, 0.0) + float(policy["posting_delay_seconds"])) / granularity
        )
        * granularity
    )
    time_estimate = float(policy["startup_charge_cu"]) + (
        max(float(policy["verified_rate_cu_per_hour"]), rate) * billed / 3600
    )
    delta_upper = max(observed_delta, 0.0) + resolution
    return max(delta_upper, time_estimate) + float(policy["operational_reserve_cu"])


def _ceil4(value: float) -> float:
    """Round up to four decimals: a ledger charge may never be rounded below the bound."""
    return math.ceil(value * 10_000 - 1e-9) / 10_000


def _unknown(reason: str, **observed: Any) -> dict[str, Any]:
    return {
        "schema": ACCOUNTING_SCHEMA,
        "cost_status": "UNKNOWN",
        "cost_confidence": "UNKNOWN",
        "reason": reason,
        "conservative_cu": None,
        **observed,
    }


def conservative_charge(
    *,
    policy: Any,
    balance_before: Any,
    balance_after: Any,
    elapsed_seconds: Any,
    observed_rates: Sequence[Any],
    teardown_verified: bool,
    allocation_attempted: bool = True,
    precise_charge_cu: Any = None,
) -> dict[str, Any]:
    """Return the session cost record; ``conservative_cu`` is None whenever it is UNKNOWN."""
    try:
        policy = validate_policy(policy)
    except CostPolicyError as exc:
        return _unknown(f"cost policy unusable: {exc}")
    digest = policy_sha256(policy)
    observed: dict[str, Any] = {
        "cost_policy_sha256": digest,
        "displayed_balance_before": balance_before,
        "displayed_balance_after": balance_after,
        "elapsed_seconds": elapsed_seconds,
    }
    if teardown_verified is not True:
        return _unknown("exact-target teardown is not verified", **observed)
    for label, value in (("before", balance_before), ("after", balance_after)):
        if not _non_negative(value):
            return _unknown(f"displayed balance {label} is negative or non-finite", **observed)
    delta = float(balance_before) - float(balance_after)
    resolution = float(policy["balance_display_resolution_cu"])
    observed["observed_displayed_delta_cu"] = round(delta, 6)
    if delta < -resolution:
        return _unknown("displayed balance rose; the delta is untrustworthy", **observed)
    delta = max(delta, 0.0)
    delta_upper = delta + resolution
    observed["delta_upper_bound_cu"] = round(delta_upper, 6)
    reserve = float(policy["operational_reserve_cu"])
    if not allocation_attempted:
        # No allocation was issued: only a displayed movement beyond rounding is unexplained.
        if delta > resolution:
            return _unknown("balance moved although no allocation was attempted", **observed)
        return {
            "schema": ACCOUNTING_SCHEMA,
            "cost_status": "KNOWN",
            "cost_confidence": "NO_ALLOCATION",
            "conservative_cu": 0.0,
            **observed,
        }
    if precise_charge_cu is not None:
        if not _non_negative(precise_charge_cu):
            return _unknown("precise provider charge is negative or non-finite", **observed)
        precise = max(float(precise_charge_cu), delta)
        return {
            "schema": ACCOUNTING_SCHEMA,
            "cost_status": "KNOWN",
            "cost_confidence": "PRECISE_PROVIDER",
            "precise_provider_cu": float(precise_charge_cu),
            "conservative_cu": _ceil4(precise),
            **observed,
        }
    if not _non_negative(elapsed_seconds):
        return _unknown("allocation-to-stop duration is negative or non-finite", **observed)
    rates = [r for r in observed_rates if _positive(r)]
    if len(rates) != len(list(observed_rates)) or not rates:
        return _unknown("no verified positive live rate; time charge is unbounded", **observed)
    rate = max(float(policy["verified_rate_cu_per_hour"]), *(float(r) for r in rates))
    granularity = int(policy["billing_granularity_seconds"])
    billed = (
        math.ceil((float(elapsed_seconds) + float(policy["posting_delay_seconds"])) / granularity)
        * granularity
    )
    time_estimate = float(policy["startup_charge_cu"]) + rate * billed / 3600
    conservative = max(delta_upper, time_estimate) + reserve
    if not math.isfinite(conservative):
        return _unknown("conservative bound is not finite", **observed)
    return {
        "schema": ACCOUNTING_SCHEMA,
        "cost_status": "KNOWN",
        "cost_confidence": "CONSERVATIVE_BOUND",
        "rate_used_cu_per_hour": rate,
        "billed_seconds": billed,
        "time_estimated_cu": round(time_estimate, 6),
        "operational_reserve_cu": reserve,
        "conservative_cu": _ceil4(conservative),
        **observed,
    }
