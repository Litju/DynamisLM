"""Synthetic operator contracts; expected outcomes never supply runtime requirements."""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path
from types import FrameType
from typing import Any

import pytest
from scripts import a0_engine as engine
from scripts import a01_experiment as experiment
from scripts import request_guard as guard

from dynamislm import (
    AnalysisClass,
    MeasurementClaimLevel,
    RelationshipClaimLevel,
    authorize_analysis,
    authorize_claim,
)
from dynamislm.longitudinal.statistics import calculate_absolute_change

KEY = bytes(range(32))  # Public synthetic test key, never an operator credential.
ISSUER = "synthetic-test-operator"


def intent(
    analysis: AnalysisClass = AnalysisClass.SCALAR_ABSOLUTE_CHANGE,
    measurement: MeasurementClaimLevel | None = MeasurementClaimLevel.NUMERICAL_CHANGE,
    relationship: RelationshipClaimLevel | None = None,
) -> engine.ModelIntent:
    return engine.ModelIntent(
        engine.ModelDecision.EXECUTE,
        analysis,
        engine.ObservationRole.BASELINE,
        engine.ObservationRole.FOLLOWUP,
        measurement,
        relationship,
        None,
    )


def raw(value: engine.ModelIntent) -> str:
    return json.dumps(engine._model_intent_wire(value))


def context(case_id: str = "valid-positive-01") -> engine.CaseContext:
    case = next(case for case in engine.load_cases() if case.case_id == case_id)
    return engine._build_context(case)


def requirements(ctx: engine.CaseContext, *objectives: guard.Objective) -> guard.Requirements:
    now = int(time.time())
    return guard.Requirements(
        guard.VERSION,
        ISSUER,
        "synthetic-operator-selection/1",
        now - 10,
        now + 300,
        guard.context_digest(ctx),
        guard.SCOPE,
        objectives or (guard.Objective("difference", intent()),),
        True,
        (),
    )


def signature(req: guard.Requirements, key: bytes = KEY) -> str:
    # Independent issuer-side encoding; the runtime adapter has no signing endpoint.
    body = json.dumps(asdict(req), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hmac.new(key, body.encode(), "sha256").hexdigest()


def evaluate(
    ctx: engine.CaseContext,
    req: guard.Requirements,
    proposals: tuple[tuple[str, str], ...] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return guard.evaluate(
        ctx,
        req,
        kwargs.pop("signature", signature(req)),
        proposals
        if proposals is not None
        else tuple((o.objective_id, raw(o.intent)) for o in req.objectives),
        trusted_issuer=kwargs.pop("trusted_issuer", ISSUER),
        verification_key=kwargs.pop("verification_key", KEY),
        **kwargs,
    )


@pytest.fixture
def calls() -> Any:
    observed: list[str] = []
    targets = {
        authorize_analysis.__code__: "analysis",
        calculate_absolute_change.__code__: "calculation",
        authorize_claim.__code__: "claim",
    }

    def profile(frame: FrameType, event: str, arg: Any) -> None:
        if event == "call" and frame.f_code in targets:
            observed.append(targets[frame.f_code])

    previous = sys.getprofile()
    sys.setprofile(profile)
    try:
        yield observed
    finally:
        sys.setprofile(previous)


@pytest.mark.parametrize(
    ("case_id", "required", "substitution"),
    [
        (
            "refuse-causal-claim",
            intent(measurement=None, relationship=RelationshipClaimLevel.CAUSAL_EVIDENCE),
            intent(),
        ),
        (
            "refuse-practical-meaning",
            intent(measurement=MeasurementClaimLevel.PRACTICAL_OR_DECISION_MEANINGFULNESS),
            intent(AnalysisClass.SCALAR_RELATIVE_CHANGE),
        ),
        (
            "refuse-unregistered-association",
            intent(
                AnalysisClass.WITHIN_ATHLETE_ASSOCIATION, None, RelationshipClaimLevel.ASSOCIATION
            ),
            intent(AnalysisClass.WITHIN_ATHLETE_ASSOCIATION),
        ),
    ],
)
def test_observed_semantic_failures_stop_before_authorization(
    case_id: str, required: engine.ModelIntent, substitution: engine.ModelIntent, calls: list[str]
) -> None:
    ctx = context(case_id)
    req = requirements(ctx, guard.Objective("question", required))
    result = evaluate(ctx, req, (("question", raw(substitution)),))
    assert result["guard_status"] == "REJECTED"
    assert result["objectives"] == []
    assert not calls


@pytest.mark.parametrize(
    ("case_id", "required", "reason", "calculated"),
    [
        ("refuse-missing-baseline", intent(), "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT", False),
        ("refuse-multiple-athletes", intent(), "RES70_WRONG_LEVEL_OF_ANALYSIS", False),
        ("refuse-unit-mismatch", intent(), "RES70_COMPARABILITY_AUTHORITY_MISSING", False),
        ("refuse-missing-unit", intent(), "RES70_UNRESOLVED_IDENTITY", False),
        (
            "refuse-unregistered-association",
            intent(
                AnalysisClass.WITHIN_ATHLETE_ASSOCIATION, None, RelationshipClaimLevel.ASSOCIATION
            ),
            "COMPUTATION_NOT_REGISTERED",
            False,
        ),
        (
            "refuse-causal-claim",
            intent(measurement=None, relationship=RelationshipClaimLevel.CAUSAL_EVIDENCE),
            "RES70_UNSUPPORTED_CAUSAL_CLAIM",
            True,
        ),
        (
            "refuse-practical-meaning",
            intent(measurement=MeasurementClaimLevel.PRACTICAL_OR_DECISION_MEANINGFULNESS),
            "RES70_COMPARABILITY_AUTHORITY_MISSING",
            True,
        ),
    ],
)
def test_faithful_requests_retain_canonical_refusals(
    case_id: str, required: engine.ModelIntent, reason: str, calculated: bool, calls: list[str]
) -> None:
    ctx = context(case_id)
    result = evaluate(ctx, requirements(ctx, guard.Objective("question", required)))
    assert result["guard_status"] == "VERIFIED"
    assert result["outcome"] == "REFUSED"
    final = result["objectives"][0]["result"]
    assert reason in final["reason_codes"]
    assert final["result_value"] is None
    assert ("calculation" in calls) is calculated


@pytest.mark.parametrize(
    ("case_id", "value"),
    [("valid-positive-01", 0.125), ("valid-negative-01", -0.0625), ("valid-zero-01", 0.0)],
)
def test_legitimate_calculations_and_exact_provenance(case_id: str, value: float) -> None:
    ctx = context(case_id)
    req = requirements(ctx)
    result = evaluate(ctx, req)
    assert result["guard_status"] == "VERIFIED"
    assert result["outcome"] == "RESULT"
    objective = result["objectives"][0]
    final = objective["result"]
    assert final["result_value"] == value and final["result_unit"] == "m"
    assert final["support_hash"] == ctx.support.canonical_support_hash
    assert final["analysis_authorization_hash"] and final["claim_authority_hash"]
    assert final["statistical_result_hash"]
    assert "intent_matches_expectation" not in final
    assert objective["proposal_sha256"] == hashlib.sha256(raw(intent()).encode()).hexdigest()
    assert result["context_sha256"] == guard.context_digest(ctx)


@pytest.mark.parametrize(
    "mutation",
    [
        {"version": "UNKNOWN"},
        {"issuer": "model"},
        {"confirmation_reference": ""},
        {"expires_at": 0},
        {"issued_at": 999999999999},
        {"issued_at": True},
        {"scope": "GROUP"},
        {"scope": "REAL_EMPIRICAL"},
        {"complete": False},
        {"complete": 1},
        {"unknowns": ("relationship_axis",)},
        {"unknowns": ("unresolved_second_question",)},
        {"unknowns": []},
        {"objectives": ()},
        {"context_sha256": "0" * 64},
    ],
)
def test_signed_but_invalid_authority_fails_closed(
    mutation: dict[str, Any], calls: list[str]
) -> None:
    ctx = context()
    req = replace(requirements(ctx), **mutation)
    assert evaluate(ctx, req)["guard_status"] == "REJECTED"
    assert not calls


@pytest.mark.parametrize("attack", ["missing", "wrong-key", "tamper", "weak-key", "wrong-issuer"])
def test_forged_or_missing_authority(attack: str, calls: list[str]) -> None:
    ctx = context()
    req = requirements(ctx)
    signed = signature(req)
    key, issuer = KEY, ISSUER
    if attack == "missing":
        assert (
            guard.evaluate(ctx, None, "", (), trusted_issuer=issuer, verification_key=key)[
                "guard_status"
            ]
            == "REJECTED"
        )
    else:
        if attack == "wrong-key":
            signed = signature(req, bytes(reversed(KEY)))
        elif attack == "tamper":
            req = replace(req, confirmation_reference="forged")
        elif attack == "weak-key":
            key = b"short"
        elif attack == "wrong-issuer":
            issuer = "unconfigured-issuer"
        assert (
            evaluate(ctx, req, signature=signed, verification_key=key, trusted_issuer=issuer)[
                "guard_status"
            ]
            == "REJECTED"
        )
    assert not calls


@pytest.mark.parametrize("attack", ["text", "support", "roles", "source", "adapter"])
def test_stale_context_binding(
    attack: str, monkeypatch: pytest.MonkeyPatch, calls: list[str]
) -> None:
    ctx = context()
    req = requirements(ctx)
    if attack == "text":
        ctx = replace(ctx, case=replace(ctx.case, request=ctx.case.request + " "))
    elif attack == "support":
        ctx = replace(ctx, support=context("valid-negative-01").support)
    elif attack == "roles":
        ctx = replace(
            ctx,
            entries_by_role={
                "BASELINE": ctx.entries_by_role["FOLLOWUP"],
                "FOLLOWUP": ctx.entries_by_role["BASELINE"],
            },
        )
    elif attack == "source":
        original_git = experiment.git
        monkeypatch.setattr(
            experiment,
            "git",
            lambda *args: "different-source"
            if args == ("rev-parse", "HEAD")
            else original_git(*args),
        )
    else:
        original = guard._digest
        monkeypatch.setattr(
            guard,
            "_digest",
            lambda value: "different-adapter"
            if value == Path(guard.__file__).read_bytes()
            else original(value),
        )
    assert evaluate(ctx, req)["guard_status"] == "REJECTED"
    assert not calls


@pytest.mark.parametrize(
    "attack", ["omitted", "duplicate", "extra", "late-mismatch", "model-refusal", "invalid-json"]
)
def test_whole_objective_inventory_is_checked_before_any_dispatch(
    attack: str, calls: list[str]
) -> None:
    ctx = context()
    first = guard.Objective("difference", intent())
    second = guard.Objective(
        "causality", intent(measurement=None, relationship=RelationshipClaimLevel.CAUSAL_EVIDENCE)
    )
    req = requirements(ctx, first, second)
    proposals: tuple[tuple[str, str], ...] = (
        (first.objective_id, raw(first.intent)),
        (second.objective_id, raw(second.intent)),
    )
    if attack == "omitted":
        proposals = proposals[:1]
    elif attack == "duplicate":
        proposals = (proposals[0], proposals[0])
    elif attack == "extra":
        proposals += (("extra", raw(intent())),)
    else:
        bad = (
            raw(intent())
            if attack == "late-mismatch"
            else '{"v":1,"d":"REFUSE","x":"UNSUPPORTED_ANALYSIS"}'
            if attack == "model-refusal"
            else "{"
        )
        proposals = (proposals[0], (second.objective_id, bad))
    assert evaluate(ctx, req, proposals)["guard_status"] == "REJECTED"
    assert not calls


def test_multiple_objectives_do_not_turn_a_causal_refusal_into_success() -> None:
    ctx = context()
    req = requirements(
        ctx,
        guard.Objective("difference", intent()),
        guard.Objective(
            "causality",
            intent(measurement=None, relationship=RelationshipClaimLevel.CAUSAL_EVIDENCE),
        ),
    )
    result = evaluate(ctx, req)
    assert result["outcome"] == "PARTIALLY_REFUSED"
    assert [r["objective_id"] for r in result["objectives"]] == ["difference", "causality"]
    assert result["objectives"][0]["result"]["result_value"] == 0.125
    assert result["objectives"][1]["result"]["result_value"] is None
    assert "RES70_UNSUPPORTED_CAUSAL_CLAIM" in result["objectives"][1]["result"]["reason_codes"]


def test_no_fixture_oracle_or_expectations_enter_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = context()
    req = requirements(ctx)
    expected = evaluate(ctx, req)

    def forbidden(*args: Any) -> Any:
        raise AssertionError("benchmark oracle accessed")

    monkeypatch.setattr(engine, "oracle_intent", forbidden)
    ctx = replace(ctx, case=replace(ctx.case, expectation=None))  # type: ignore[arg-type]
    assert evaluate(ctx, req) == expected


def test_duplicate_signed_objectives_and_absent_axes_stop_dispatch(calls: list[str]) -> None:
    ctx = context()
    first = guard.Objective("same", intent())
    duplicate = requirements(ctx, first, first)
    assert evaluate(ctx, duplicate)["guard_status"] == "REJECTED"
    absent = requirements(ctx, guard.Objective("missing-axes", intent(measurement=None)))
    assert evaluate(ctx, absent)["guard_status"] == "REJECTED"
    assert not calls


def test_signed_arbitrary_support_cannot_claim_synthetic_scope(calls: list[str]) -> None:
    ctx = context()
    ctx = replace(ctx, support=context("valid-negative-01").support)
    req = requirements(ctx)
    result = evaluate(ctx, req)
    assert result["guard_status"] == "REJECTED"
    assert result["failure_stage"] == "CONTEXT"
    assert not calls
