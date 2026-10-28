"""CPU-only request-contract guard; no interpretation, issuance, or scientific authority."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from types import FunctionType
from typing import Any

from scripts import a0_engine as engine
from scripts import a01_experiment as experiment

VERSION = "RES541_REQUEST_REQUIREMENTS_V1"
SCOPE = "SYNTHETIC_DEVELOPMENT_ONLY/ATHLETE_WITHIN/WITHIN_ATHLETE"


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


@dataclass(frozen=True)
class Objective:
    objective_id: str
    intent: engine.ModelIntent


@dataclass(frozen=True)
class Requirements:
    version: str
    issuer: str
    confirmation_reference: str
    issued_at: int
    expires_at: int
    context_sha256: str
    scope: str
    objectives: tuple[Objective, ...]
    complete: bool
    unknowns: tuple[str, ...]


def context_digest(context: engine.CaseContext) -> str:
    """Bind exact text, support and the separately stored role mapping, never expectations."""
    return _digest(
        _json(
            {
                "source": experiment.git("rev-parse", "HEAD"),
                "adapter": _digest(Path(__file__).read_bytes()),
                "case_id": context.case.case_id,
                "request": context.case.request,
                "support": context.support.canonical_support_hash,
                "roles": {
                    role: entry.canonical_entry_id.qualified
                    for role, entry in context.entries_by_role.items()
                },
            }
        )
    )


def _validate(requirements: Requirements, issuer: str, now: int) -> None:
    if (
        type(requirements) is not Requirements
        or requirements.version != VERSION
        or not issuer
        or requirements.issuer != issuer
        or not isinstance(requirements.confirmation_reference, str)
        or not requirements.confirmation_reference.strip()
        or type(requirements.issued_at) is not int
        or type(requirements.expires_at) is not int
        or not requirements.issued_at <= now < requirements.expires_at
        or requirements.scope != SCOPE
        or requirements.complete is not True
        or type(requirements.unknowns) is not tuple
        or requirements.unknowns
        or type(requirements.objectives) is not tuple
        or not 1 <= len(requirements.objectives) <= 16
    ):
        raise ValueError("missing, unresolved, stale or unsupported request requirements")
    ids = []
    for objective in requirements.objectives:
        if (
            type(objective) is not Objective
            or not isinstance(objective.objective_id, str)
            or not objective.objective_id.strip()
            or type(objective.intent) is not engine.ModelIntent
            or objective.intent.decision is not engine.ModelDecision.EXECUTE
        ):
            raise ValueError("every objective requires a complete typed execution intent")
        # Round-trip validation rejects missing axes and invalid enum/field combinations.
        if engine.parse_model_intent(
            _json(engine._model_intent_wire(objective.intent)).decode()
        ) != (objective.intent):
            raise ValueError("invalid objective intent")
        ids.append(objective.objective_id)
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate objective IDs")


def evaluate(
    context: engine.CaseContext,
    requirements: Requirements | None,
    signature: str,
    proposals: tuple[tuple[str, str], ...],
    *,
    trusted_issuer: str,
    verification_key: bytes,
) -> dict[str, Any]:
    """Verify operator-issued contracts before any call into the frozen execution path.

    The issuer/key are trusted configuration, never fields supplied by the model.
    A trusted issuer must independently confirm scope and objective completeness.
    """
    stage = "AUTHORITY"
    try:
        if type(verification_key) is not bytes or len(verification_key) < 32:
            raise ValueError("operator-controlled verification key required")
        if requirements is None or type(signature) is not str:
            raise ValueError("signed requirements required")
        _validate(requirements, trusted_issuer, int(time.time()))
        expected = hmac.new(verification_key, _json(asdict(requirements)), "sha256").hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("untrusted requirements")
        stage = "CONTEXT"
        experiment.verify_freeze()
        context = replace(context, entries_by_role=dict(context.entries_by_role))
        if requirements.context_sha256 != context_digest(context):
            raise ValueError("request/source/support/role binding mismatch")
        synthetic = engine._build_context(context.case)
        if (
            synthetic.support != context.support
            or synthetic.entries_by_role != context.entries_by_role
        ):
            raise ValueError("context must use the existing deterministic synthetic constructor")
        context = synthetic
        stage = "PROPOSALS"
        if type(proposals) is not tuple or any(
            type(row) is not tuple or len(row) != 2 or any(type(value) is not str for value in row)
            for row in proposals
        ):
            raise ValueError("invalid proposal batch")
        by_id = dict(proposals)
        if len(by_id) != len(proposals) or set(by_id) != {
            objective.objective_id for objective in requirements.objectives
        }:
            raise ValueError("objective inventory mismatch")
        for objective in requirements.objectives:
            if engine.parse_model_intent(by_id[objective.objective_id]) != objective.intent:
                raise ValueError("proposal changes the requested scientific intent")
    except (TypeError, ValueError, AttributeError, KeyError):
        return {
            "outcome": "REFUSED",
            "guard_status": "REJECTED",
            "failure_stage": stage,
            "reason_codes": ("RES541_REQUEST_CONTRACT_REJECTED",),
            "objectives": [],
        }

    # Disable only the frozen engine's evaluation-only oracle in a private function namespace.
    # No fixture expectations enter dispatch; canonical scientific functions remain unchanged.
    abstention = engine.ModelIntent(
        engine.ModelDecision.REFUSE,
        None,
        None,
        None,
        None,
        None,
        engine.ModelRefusalReason.UNSUPPORTED_ANALYSIS,
    )
    execute = FunctionType(
        engine._evaluate.__code__, {**engine.__dict__, "oracle_intent": lambda _: abstention}
    )
    results = []
    for objective in requirements.objectives:
        raw = by_id[objective.objective_id]
        result = execute(context, raw, {})
        result.pop("intent_matches_expectation")
        results.append(
            {
                "objective_id": objective.objective_id,
                "proposal_sha256": _digest(raw.encode()),
                "result": result,
            }
        )
    outcomes = {row["result"]["outcome"] for row in results}
    return {
        "outcome": next(iter(outcomes)) if len(outcomes) == 1 else "PARTIALLY_REFUSED",
        "guard_status": "VERIFIED",
        "requirements_sha256": _digest(_json(asdict(requirements))),
        "context_sha256": requirements.context_sha256,
        "issuer": requirements.issuer,
        "confirmation_reference": requirements.confirmation_reference,
        "objectives": results,
    }
