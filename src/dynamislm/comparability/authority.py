"""Deterministic-rule-only comparability adjudication."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from dynamislm.comparability.models import (
    ComparabilityDecisionSource,
    ComparabilityRequest,
    ComparabilityResult,
)
from dynamislm.measurement.identity import RegistryReference

RuleMatcher = Callable[[ComparabilityRequest], bool]
RuleEvaluator = Callable[[ComparabilityRequest], ComparabilityResult]


class ComparabilityAuthorityError(ValueError):
    """Raised when a registered rule returns a non-authoritative or inconsistent result."""


@dataclass(frozen=True, slots=True)
class RegisteredComparabilityRule:
    """Pure deterministic rule callback and its stable registry reference."""

    reference: RegistryReference
    matches: RuleMatcher
    evaluate: RuleEvaluator


@dataclass(frozen=True, slots=True)
class ComparabilityAuthority:
    """Immutable collection of rules; no rule means explicit insufficiency."""

    rules: tuple[RegisteredComparabilityRule, ...] = ()

    def with_rule(self, rule: RegisteredComparabilityRule) -> ComparabilityAuthority:
        if any(existing.reference.stable_id == rule.reference.stable_id for existing in self.rules):
            raise ComparabilityAuthorityError(
                f"comparability rule already registered: {rule.reference.stable_id}"
            )
        return ComparabilityAuthority((*self.rules, rule))

    def adjudicate(self, request: ComparabilityRequest) -> ComparabilityResult:
        matches = tuple(rule for rule in self.rules if rule.matches(request))
        if not matches:
            return ComparabilityResult.insufficient(request)
        if len(matches) > 1:
            raise ComparabilityAuthorityError("multiple comparability rules match one request")
        rule = matches[0]
        result = rule.evaluate(request)
        if result.request_id != request.request_id:
            raise ComparabilityAuthorityError(
                "rule result request ID does not match the adjudicated request"
            )
        if result.rule_reference != rule.reference:
            raise ComparabilityAuthorityError(
                "rule result reference does not match registered rule"
            )
        if result.decided_by is not ComparabilityDecisionSource.DETERMINISTIC_RULE:
            raise ComparabilityAuthorityError("registered rule result must be deterministic")
        return result
