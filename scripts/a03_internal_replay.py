"""Deterministic, gold-free replay of the deployed RES-430 `ask` decision for a committed output.

The runner commits what the deployed pipeline produced. The scorer proves that commitment by
replaying the same pipeline on the committed generation, and records any dispatch attempt with
a permit callback that always allows. A replay therefore reproduces the runtime's own
pre-veto decision and cannot be turned into a gold-derived refusal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dynamislm.longitudinal.statistics import RES69_ABSOLUTE_CHANGE_OPERATION
from scripts import a02_v3_contract as v3
from scripts import research_ask as research
from scripts.a03_model_runtime import Generation
from scripts.a03_scientific_admission import Admission, BoundRequest, submit_scientific_action_v3
from scripts.research_scenarios import SyntheticScenario

RES69 = RES69_ABSOLUTE_CHANGE_OPERATION.stable_id
AXES = tuple(v3.CLAIM_AXES)


class ReplayBackend:
    """Returns one committed generation. It reads no model and receives no gold."""

    def __init__(self, tokenizer: Any, generation: Generation) -> None:
        self.tokenizer = tokenizer
        self.generation = generation

    def generate(
        self, arm: str, request: dict[str, Any], prompt: list[int], deadline: float
    ) -> Generation:
        return self.generation


def receipt_for_arm(receipt: dict[str, Any], arm: str) -> dict[str, Any]:
    """The shared `ask` receipt labels every generation C1. Relabel it with the real arm."""
    proposal = {**receipt["proposal"], "decoding": arm}
    return {key: value for key, value in receipt.items() if key != "identity"} | {
        "proposal": proposal
    }


def replay_receipt(
    scenario: SyntheticScenario,
    question: str,
    generation: Generation,
    tokenizer: Any,
    arm: str,
) -> dict[str, Any]:
    runtime = research.ResearchRuntime(ReplayBackend(tokenizer, generation), {})
    receipt, _ = research.ask(scenario, question, runtime)
    return receipt_for_arm(receipt, arm)


@dataclass(frozen=True)
class Trace:
    """The runtime decision with the dispatch attempts that preceded any veto."""

    admission: Admission
    attempted: tuple[str, ...]


def trace(bound: BoundRequest, raw: str) -> Trace:
    attempts: list[str] = []

    def record(operation: str) -> bool:
        attempts.append(operation)
        return True

    return Trace(submit_scientific_action_v3(bound, raw, permit_dispatch=record), tuple(attempts))


def fingerprint(receipt_result: dict[str, Any] | None) -> tuple[Any, ...] | None:
    """Operation, estimand, value, unit and support of a dispatched result, from its receipt."""
    if not receipt_result or len(receipt_result["estimates"]) != 1:
        return None
    estimate = receipt_result["estimates"][0]
    return (
        receipt_result["operation"],
        estimate["estimand"],
        estimate["value"],
        estimate["unit"],
        receipt_result["support_hash"],
    )


def gold_fingerprints(
    scenario: SyntheticScenario, question: str, judgment: dict[str, Any]
) -> set[tuple[Any, ...]]:
    """Recompute every executable acceptable gold action with the engine."""
    bound = research.prepare_request(scenario, question)
    found: set[tuple[Any, ...]] = set()
    for candidate in judgment["acceptable_actions"]:
        if candidate["operation"] != RES69:
            continue
        decision = trace(bound, v3.format_action(candidate)).admission
        if decision.outcome != "GROUNDED_RESULT" or decision.result is None:
            continue
        result = decision.result
        value = fingerprint(
            {
                "operation": result.operation.stable_id,
                "support_hash": result.analysis_run.support_hash,
                "estimates": [
                    {
                        "value": e.value,
                        "unit": e.unit.display_label,
                        "estimand": e.estimand.stable_id,
                    }
                    for e in result.estimates
                ],
            }
        )
        if value is not None:
            found.add(value)
    return found
