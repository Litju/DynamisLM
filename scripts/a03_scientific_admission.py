"""Request-local binding for untrusted V3 model proposals and trusted RES-62 source inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dynamislm.analysis.models import AnalysisClass
from dynamislm.claims.models import MeasurementClaimLevel, RelationshipClaimLevel
from dynamislm.longitudinal.models import (
    LongitudinalAthletePerformanceRecord,
    LongitudinalObservationEntry,
    MultiSourceAnalysisInput,
)
from dynamislm.longitudinal.statistics import (
    StatisticalSupport,
    SupportEntryExclusion,
    SupportExclusionReason,
    build_statistical_support,
)
from dynamislm.measurement.result import ScalarValue
from scripts import a02_v3_contract as v3


class ProposalError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Proposal:
    analysis: AnalysisClass | None
    observation_ids: tuple[str, ...]
    operation: str | None
    measurement: tuple[MeasurementClaimLevel, ...]
    relationship: tuple[RelationshipClaimLevel, ...]


@dataclass(frozen=True)
class BoundRequest:
    """Created by the host using its authenticated source selection for this interaction.

    Only question text and generated action bytes come from untrusted parties. Source objects
    and explicit claim requests from a typed host workflow use separate arguments.
    """

    question: str
    source: MultiSourceAnalysisInput | None
    records: tuple[LongitudinalAthletePerformanceRecord, ...]
    required_measurement: tuple[MeasurementClaimLevel, ...] = ()
    required_relationship: tuple[RelationshipClaimLevel, ...] = ()

    @property
    def entries(self) -> tuple[LongitudinalObservationEntry, ...]:
        return self.source.entries if self.source is not None else ()

    def model_request(self) -> dict[str, Any]:
        if not isinstance(self.question, str):
            raise ProposalError("V3_INVALID_REQUEST")
        rows = []
        for entry in self.entries:
            observation = entry.observation
            identity = observation.identity
            result = observation.result
            rows.append(
                {
                    "date": entry.observed_at.isoformat(),
                    "measurement": identity.semantic.metric_definition.stable_id,
                    "protocol": identity.semantic.protocol.stable_id
                    if identity.semantic.protocol
                    else None,
                    "device": identity.acquisition.device.stable_id
                    if identity.acquisition.device
                    else None,
                    "value": result.value.value if isinstance(result.value, ScalarValue) else None,
                    "unit": result.unit.display_label if result.unit else None,
                }
            )
        return {
            "question": self.question,
            "observations": rows,
            "requested_claims": {
                "measurement": [level.value for level in self.required_measurement],
                "relationship": [level.value for level in self.required_relationship],
            },
        }

    def parse(self, raw: object) -> Proposal:
        try:
            ids = v3.observation_ids(self.model_request())
        except (TypeError, ValueError) as exc:
            raise ProposalError("V3_INVALID_REQUEST") from exc
        try:
            action = v3.parse_action(
                raw, [f"observation-{i}" for i in range(1, v3.MAX_OBSERVATIONS + 1)]
            )
        except (TypeError, ValueError) as exc:
            raise ProposalError("V3_INVALID_PROPOSAL") from exc
        refs = tuple(action["observation_ids"])
        if not set(refs).issubset(ids):
            raise ProposalError("V3_OBSERVATION_REFERENCE_UNRESOLVED")
        operation = action["operation"]
        return Proposal(
            analysis=AnalysisClass(action["analysis_class"])
            if action["analysis_class"] != v3.NONE
            else None,
            observation_ids=refs,
            operation=operation if operation != v3.NONE else None,
            measurement=tuple(
                MeasurementClaimLevel(level) for level in action["target_claims"]["measurement"]
            ),
            relationship=tuple(
                RelationshipClaimLevel(level) for level in action["target_claims"]["relationship"]
            ),
        )

    def resolve(self, proposal: Proposal) -> StatisticalSupport:
        if self.source is None or not proposal.observation_ids:
            raise ProposalError("V3_OBSERVATION_REFERENCE_UNRESOLVED")
        have = {f"observation-{index}": entry for index, entry in enumerate(self.entries, 1)}
        if not set(proposal.observation_ids).issubset(have):
            raise ProposalError("V3_OBSERVATION_REFERENCE_UNRESOLVED")
        if not self.records:
            raise ProposalError("V3_SOURCE_PROVENANCE_UNRESOLVED")
        selected = set(proposal.observation_ids)
        try:
            return build_statistical_support(
                self.source,
                (entry for alias, entry in have.items() if alias in selected),
                source_records=self.records,
                excluded_entries=tuple(
                    SupportEntryExclusion.from_entry(entry, SupportExclusionReason.NOT_SELECTED)
                    for alias, entry in have.items()
                    if alias not in selected
                ),
            )
        except ValueError as exc:
            raise ProposalError("V3_SOURCE_PROVENANCE_UNRESOLVED") from exc
