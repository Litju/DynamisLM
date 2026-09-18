"""Immutable RES-70 cross-source comparability and bridge contracts.

The contracts in this module deliberately carry references and hashes rather
than accepting caller-supplied scientific verdicts.  Deterministic authority
is implemented in :mod:`res70_authority`; these objects only make the
authority inputs and outputs explicit and serializable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from dynamislm.comparability.models import (
    ComparabilityResult,
    ComparabilityState,
    TransformationRequest,
)
from dynamislm.football.models import FootballWorldContext
from dynamislm.football.validation import validate_football_world_context
from dynamislm.measurement.identity import (
    InstanceIdentifier,
    MeasurementIdentity,
    MetadataEntry,
    RegistryReference,
    UnitReference,
    _require_enum,
    _require_instance,
    _require_optional_instance,
    _require_text,
    _require_tuple_items,
    require_tuple,
)
from dynamislm.measurement.observation import ScientificMeasurementObservation
from dynamislm.provenance.models import ProcessingRun, Provenance
from dynamislm.serialization import canonical_hash, register_serializable_type

_SHA256_PREFIX = "sha256:"


def _require_hash(value: str, field_name: str) -> None:
    _require_text(value, field_name)
    digest = value.removeprefix(_SHA256_PREFIX)
    if (
        not value.startswith(_SHA256_PREFIX)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError(f"{field_name} must be a canonical sha256 hash")


def _require_string_tuple(value: object, field_name: str) -> None:
    require_tuple(value, field_name)
    assert isinstance(value, tuple)
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field_name} must contain non-empty strings")


def _require_reference_tuple(value: object, field_name: str) -> None:
    _require_tuple_items(value, RegistryReference, field_name)


def _require_hash_tuple(value: object, field_name: str) -> None:
    require_tuple(value, field_name)
    assert isinstance(value, tuple)
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"{field_name} must contain strings")
        _require_hash(item, f"{field_name}[{index}]")


def _stable_ref(value: RegistryReference | None) -> str:
    return value.stable_id if value is not None else "<none>"


def _identity_component_entries(identity: MeasurementIdentity) -> tuple[MetadataEntry, ...]:
    """Return a reusable identity key without observation-instance identity.

    Raw artifact IDs are intentionally omitted.  They identify a particular
    acquisition instance, not a reusable scientific method/identity key.
    """

    semantic = identity.semantic
    acquisition = identity.acquisition
    processing = identity.processing
    version = identity.version
    entries: list[MetadataEntry] = [
        MetadataEntry("semantic.construct", semantic.construct.stable_id),
        MetadataEntry("semantic.test_family", semantic.test_family.stable_id),
        MetadataEntry("semantic.protocol", _stable_ref(semantic.protocol)),
        MetadataEntry("semantic.measurand", semantic.measurand.stable_id),
        MetadataEntry("semantic.metric_definition", semantic.metric_definition.stable_id),
        MetadataEntry("acquisition.device", _stable_ref(acquisition.device)),
        MetadataEntry("acquisition.sensor_channel", acquisition.sensor_channel),
        MetadataEntry(
            "acquisition.sampling",
            canonical_hash(acquisition.sampling) if acquisition.sampling is not None else "<none>",
        ),
        MetadataEntry(
            "acquisition.calibration_reference",
            _stable_ref(acquisition.calibration_reference),
        ),
        MetadataEntry("acquisition.hardware_firmware", _stable_ref(acquisition.hardware_firmware)),
        MetadataEntry(
            "processing.event_definitions",
            canonical_hash(processing.event_definitions),
        ),
        MetadataEntry(
            "processing.phase_definitions",
            canonical_hash(processing.phase_definitions),
        ),
        MetadataEntry("processing.estimator", _stable_ref(processing.estimator)),
        MetadataEntry(
            "processing.registered_operation",
            _stable_ref(processing.registered_operation),
        ),
        MetadataEntry(
            "processing.method_parameters",
            canonical_hash(processing.method_parameters),
        ),
        MetadataEntry("processing.filtering", canonical_hash(processing.filtering)),
        MetadataEntry(
            "processing.differentiation_method",
            _stable_ref(processing.differentiation_method),
        ),
        MetadataEntry(
            "processing.integration_method",
            _stable_ref(processing.integration_method),
        ),
        MetadataEntry(
            "processing.unit",
            canonical_hash(processing.unit) if processing.unit is not None else "<none>",
        ),
        MetadataEntry(
            "processing.sign_convention",
            canonical_hash(processing.sign_convention)
            if processing.sign_convention is not None
            else "<none>",
        ),
        MetadataEntry(
            "processing.normalization",
            canonical_hash(processing.normalization)
            if processing.normalization is not None
            else "<none>",
        ),
        MetadataEntry("processing.trial_selection", _stable_ref(processing.trial_selection)),
        MetadataEntry("processing.aggregation", _stable_ref(processing.aggregation)),
        MetadataEntry("version.processing_method", version.processing_method.stable_id),
        MetadataEntry("version.method_registry_version", version.method_registry_version),
        MetadataEntry("version.software_version", version.software_version),
        MetadataEntry("version.hardware_firmware", _stable_ref(version.hardware_firmware)),
    ]
    return tuple(entries)


class ComparabilityDimension(StrEnum):
    CONSTRUCT = "CONSTRUCT"
    TEST_FAMILY = "TEST_FAMILY"
    MEASURAND = "MEASURAND"
    METRIC_DEFINITION = "METRIC_DEFINITION"
    PROTOCOL = "PROTOCOL"
    EVENT_DEFINITION = "EVENT_DEFINITION"
    PHASE_DEFINITION = "PHASE_DEFINITION"
    UNIT = "UNIT"
    NORMALIZATION = "NORMALIZATION"
    ESTIMATOR = "ESTIMATOR"
    REGISTERED_PROCESSING_OPERATION = "REGISTERED_PROCESSING_OPERATION"
    PROCESSING_PARAMETERS = "PROCESSING_PARAMETERS"
    FILTERING_SMOOTHING_RESAMPLING = "FILTERING_SMOOTHING_RESAMPLING"
    SAMPLING_AND_TIMEBASE = "SAMPLING_AND_TIMEBASE"
    CALIBRATION_REFERENCE = "CALIBRATION_REFERENCE"
    DEVICE_MEASURING_SYSTEM = "DEVICE_MEASURING_SYSTEM"
    PROVIDER = "PROVIDER"
    SOFTWARE_ALGORITHM_VERSION = "SOFTWARE_ALGORITHM_VERSION"
    HARDWARE_FIRMWARE_VERSION = "HARDWARE_FIRMWARE_VERSION"
    SIGN_CONVENTION_AND_REFERENCE_FRAME = "SIGN_CONVENTION_AND_REFERENCE_FRAME"
    THRESHOLD_IDENTITY = "THRESHOLD_IDENTITY"
    TRIAL_SELECTION_POLICY = "TRIAL_SELECTION_POLICY"
    AGGREGATION_POLICY = "AGGREGATION_POLICY"
    SESSION_SEGMENTATION = "SESSION_SEGMENTATION"
    ACQUISITION_CONTEXT = "ACQUISITION_CONTEXT"
    EXPOSURE_CONTEXT_MATCH_OR_TRAINING = "EXPOSURE_CONTEXT_MATCH_OR_TRAINING"
    VALUE_ORIGIN = "VALUE_ORIGIN"
    UNCERTAINTY_ERROR_MODEL = "UNCERTAINTY_ERROR_MODEL"
    POPULATION_APPLICABILITY = "POPULATION_APPLICABILITY"
    EVIDENCE_APPLICABILITY = "EVIDENCE_APPLICABILITY"
    FOOTBALL_WORLD_CONTEXT = "FOOTBALL_WORLD_CONTEXT"


class DimensionFindingStatus(StrEnum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"
    BRIDGED = "BRIDGED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class BridgeMode(StrEnum):
    DECLARATIVE_EQUIVALENCE = "DECLARATIVE_EQUIVALENCE"
    NUMERICAL_TRANSFORMATION = "NUMERICAL_TRANSFORMATION"


class BridgeInvertibility(StrEnum):
    EXACT = "EXACT"
    APPROXIMATE = "APPROXIMATE"
    NON_INVERTIBLE_LOSSY = "NON_INVERTIBLE_LOSSY"


class BridgeAuthorityOrigin(StrEnum):
    PRODUCTION = "PRODUCTION"
    SYNTHETIC_TEST = "SYNTHETIC_TEST"


class BridgeExecutionStatus(StrEnum):
    EXECUTED = "EXECUTED"
    DECLARATIVE_APPLIED = "DECLARATIVE_APPLIED"


@register_serializable_type
@dataclass(frozen=True, slots=True)
class SemanticIdentityKey:
    """Complete reusable identity key with instance-specific IDs excluded."""

    components: tuple[MetadataEntry, ...]

    def __post_init__(self) -> None:
        _require_tuple_items(self.components, MetadataEntry, "components")
        keys = tuple(item.key for item in self.components)
        if len(set(keys)) != len(keys):
            raise ValueError("semantic identity key components must be unique")
        for item in self.components:
            value = item.value
            if isinstance(value, str) and any(
                value.startswith(prefix)
                for prefix in ("observation:", "artifact:", "acquisition:", "session:")
            ):
                raise ValueError("semantic identity keys cannot contain observation-instance IDs")

    @classmethod
    def from_identity(cls, identity: MeasurementIdentity) -> SemanticIdentityKey:
        _require_instance(identity, MeasurementIdentity, "identity")
        return cls(_identity_component_entries(identity))

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self)

    def as_mapping(self) -> dict[str, object]:
        return {item.key: item.value for item in self.components}


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ObservationAuthorityReference:
    """Exact observation/result/context/provenance hashes used by RES-70."""

    observation_id: InstanceIdentifier
    observation_hash: str
    identity_hash: str
    result_hash: str
    context_hash: str
    provenance_hash: str

    def __post_init__(self) -> None:
        _require_instance(self.observation_id, InstanceIdentifier, "observation_id")
        if self.observation_id.instance_type != "observation":
            raise ValueError("observation_id must identify an observation")
        for field_name in (
            "observation_hash",
            "identity_hash",
            "result_hash",
            "context_hash",
            "provenance_hash",
        ):
            _require_hash(getattr(self, field_name), field_name)

    @classmethod
    def from_observation(
        cls, observation: ScientificMeasurementObservation
    ) -> ObservationAuthorityReference:
        _require_instance(observation, ScientificMeasurementObservation, "observation")
        return cls(
            observation_id=observation.observation_id,
            observation_hash=canonical_hash(observation),
            identity_hash=canonical_hash(observation.identity),
            result_hash=canonical_hash(observation.result),
            context_hash=canonical_hash(observation.context),
            provenance_hash=canonical_hash(observation.provenance),
        )

    def validate_observation(self, observation: ScientificMeasurementObservation) -> None:
        expected = ObservationAuthorityReference.from_observation(observation)
        if self != expected:
            raise ValueError("observation authority reference does not match exact observation")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ClaimContext:
    """Typed claim-relevant context kept outside MeasurementIdentity."""

    context_reference: RegistryReference
    context_kind: str
    attributes: tuple[MetadataEntry, ...] = ()
    football_world_context: FootballWorldContext | None = None

    def __post_init__(self) -> None:
        _require_instance(self.context_reference, RegistryReference, "context_reference")
        _require_text(self.context_kind, "context_kind")
        _require_tuple_items(self.attributes, MetadataEntry, "attributes")
        if self.football_world_context is not None:
            validate_football_world_context(self.football_world_context)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class DimensionFinding:
    """One deterministic finding for one material comparability dimension."""

    dimension: ComparabilityDimension
    status: DimensionFindingStatus
    left_value: str | None = None
    right_value: str | None = None
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_enum(self.dimension, ComparabilityDimension, "dimension")
        _require_enum(self.status, DimensionFindingStatus, "status")
        if self.left_value is not None:
            _require_text(self.left_value, "left_value")
        if self.right_value is not None:
            _require_text(self.right_value, "right_value")
        _require_string_tuple(self.reason_codes, "reason_codes")
        if self.status is DimensionFindingStatus.MATCH and self.left_value != self.right_value:
            raise ValueError("matching dimension findings must have equal values")
        if self.status is DimensionFindingStatus.MISMATCH and (
            self.left_value is None or self.right_value is None
        ):
            raise ValueError("mismatching dimension findings must retain both values")

    @property
    def left_reference(self) -> str | None:
        return self.left_value

    @property
    def right_reference(self) -> str | None:
        return self.right_value


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CrossSourceComparabilityRequest:
    """Claim-relative pairwise cross-source comparability request."""

    request_id: InstanceIdentifier
    left_observation: ObservationAuthorityReference
    right_observation: ObservationAuthorityReference
    claim_intent: RegistryReference
    requested_transformations: tuple[TransformationRequest, ...] = ()
    requested_dimensions: tuple[ComparabilityDimension, ...] = ()
    claim_context: ClaimContext | None = None

    def __post_init__(self) -> None:
        _require_instance(self.request_id, InstanceIdentifier, "request_id")
        if self.request_id.instance_type != "cross-source-comparability-request":
            raise ValueError("request_id must identify a cross-source-comparability-request")
        _require_instance(self.left_observation, ObservationAuthorityReference, "left_observation")
        _require_instance(
            self.right_observation, ObservationAuthorityReference, "right_observation"
        )
        if self.left_observation.observation_id == self.right_observation.observation_id:
            raise ValueError("cross-source comparability requires two distinct observations")
        _require_instance(self.claim_intent, RegistryReference, "claim_intent")
        _require_tuple_items(
            self.requested_transformations,
            TransformationRequest,
            "requested_transformations",
        )
        require_tuple(self.requested_dimensions, "requested_dimensions")
        if any(not isinstance(item, ComparabilityDimension) for item in self.requested_dimensions):
            raise ValueError("requested_dimensions must contain ComparabilityDimension values")
        if len(set(self.requested_dimensions)) != len(self.requested_dimensions):
            raise ValueError("requested_dimensions must not contain duplicates")
        if self.claim_context is not None:
            _require_instance(self.claim_context, ClaimContext, "claim_context")

    @property
    def request_hash(self) -> str:
        return canonical_hash(self)

    @property
    def observation_ids(self) -> tuple[InstanceIdentifier, InstanceIdentifier]:
        return (
            self.left_observation.observation_id,
            self.right_observation.observation_id,
        )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class CrossSourceComparabilityDecision:
    """Pairwise deterministic decision with exact input and registry bindings."""

    decision_id: InstanceIdentifier
    request_hash: str
    state: ComparabilityState
    dimension_findings: tuple[DimensionFinding, ...]
    conditions: tuple[str, ...]
    transformations_required: tuple[TransformationRequest, ...]
    bridge_application_reference: RegistryReference | None
    rule_reference: RegistryReference | None
    evidence_references: tuple[RegistryReference, ...]
    registry_version: str
    registry_hash: str
    left_observation: ObservationAuthorityReference
    right_observation: ObservationAuthorityReference
    reason_codes: tuple[str, ...] = ()
    missing_information: tuple[str, ...] = ()
    leaf_result: ComparabilityResult | None = None
    bridge_execution_hash: str | None = None
    decision_hash: str | None = None

    def __post_init__(self) -> None:
        _require_instance(self.decision_id, InstanceIdentifier, "decision_id")
        if self.decision_id.instance_type != "cross-source-comparability-decision":
            raise ValueError("decision_id must identify a cross-source-comparability-decision")
        _require_hash(self.request_hash, "request_hash")
        _require_enum(self.state, ComparabilityState, "state")
        _require_tuple_items(self.dimension_findings, DimensionFinding, "dimension_findings")
        _require_string_tuple(self.conditions, "conditions")
        _require_tuple_items(
            self.transformations_required,
            TransformationRequest,
            "transformations_required",
        )
        _require_optional_instance(
            self.bridge_application_reference,
            RegistryReference,
            "bridge_application_reference",
        )
        _require_optional_instance(self.rule_reference, RegistryReference, "rule_reference")
        _require_reference_tuple(self.evidence_references, "evidence_references")
        _require_text(self.registry_version, "registry_version")
        _require_hash(self.registry_hash, "registry_hash")
        _require_instance(self.left_observation, ObservationAuthorityReference, "left_observation")
        _require_instance(
            self.right_observation,
            ObservationAuthorityReference,
            "right_observation",
        )
        if self.left_observation.observation_id == self.right_observation.observation_id:
            raise ValueError("decision observations must be distinct")
        _require_string_tuple(self.reason_codes, "reason_codes")
        _require_string_tuple(self.missing_information, "missing_information")
        _require_optional_instance(self.leaf_result, ComparabilityResult, "leaf_result")
        if self.bridge_execution_hash is not None:
            _require_hash(self.bridge_execution_hash, "bridge_execution_hash")
        if self.state is ComparabilityState.COMPARABLE_WITH_CONDITIONS and not self.conditions:
            raise ValueError("conditional comparability must retain explicit conditions")
        if self.state is ComparabilityState.REQUIRES_TRANSFORMATION and not (
            self.transformations_required
        ):
            raise ValueError("transformation-required decision must name transformations")
        expected_hash = self._content_hash()
        if self.decision_hash is None:
            object.__setattr__(self, "decision_hash", expected_hash)
        elif self.decision_hash != expected_hash:
            raise ValueError("decision_hash does not match immutable decision content")
        expected_id = InstanceIdentifier(
            "cross-source-comparability-decision",
            expected_hash.removeprefix(_SHA256_PREFIX),
        )
        if self.decision_id != expected_id:
            raise ValueError("decision_id does not match immutable decision content")

    def _content_hash(self) -> str:
        return canonical_hash(
            {
                "request_hash": self.request_hash,
                "state": self.state,
                "dimension_findings": self.dimension_findings,
                "conditions": self.conditions,
                "transformations_required": self.transformations_required,
                "bridge_application_reference": self.bridge_application_reference,
                "rule_reference": self.rule_reference,
                "evidence_references": self.evidence_references,
                "registry_version": self.registry_version,
                "registry_hash": self.registry_hash,
                "left_observation": self.left_observation,
                "right_observation": self.right_observation,
                "reason_codes": self.reason_codes,
                "missing_information": self.missing_information,
                "leaf_result": self.leaf_result,
                "bridge_execution_hash": self.bridge_execution_hash,
            }
        )

    @property
    def canonical_decision_hash(self) -> str:
        assert self.decision_hash is not None
        return self.decision_hash

    @property
    def pair_key(self) -> frozenset[str]:
        return frozenset(
            (
                self.left_observation.observation_id.qualified,
                self.right_observation.observation_id.qualified,
            )
        )

    @classmethod
    def create(
        cls,
        *,
        request_hash: str,
        state: ComparabilityState,
        dimension_findings: tuple[DimensionFinding, ...],
        conditions: tuple[str, ...],
        transformations_required: tuple[TransformationRequest, ...],
        bridge_application_reference: RegistryReference | None,
        rule_reference: RegistryReference | None,
        evidence_references: tuple[RegistryReference, ...],
        registry_version: str,
        registry_hash: str,
        left_observation: ObservationAuthorityReference,
        right_observation: ObservationAuthorityReference,
        reason_codes: tuple[str, ...] = (),
        missing_information: tuple[str, ...] = (),
        leaf_result: ComparabilityResult | None = None,
        bridge_execution_hash: str | None = None,
    ) -> CrossSourceComparabilityDecision:
        """Construct a decision while deriving its immutable ID and hash."""

        content = {
            "request_hash": request_hash,
            "state": state,
            "dimension_findings": dimension_findings,
            "conditions": conditions,
            "transformations_required": transformations_required,
            "bridge_application_reference": bridge_application_reference,
            "rule_reference": rule_reference,
            "evidence_references": evidence_references,
            "registry_version": registry_version,
            "registry_hash": registry_hash,
            "left_observation": left_observation,
            "right_observation": right_observation,
            "reason_codes": reason_codes,
            "missing_information": missing_information,
            "leaf_result": leaf_result,
            "bridge_execution_hash": bridge_execution_hash,
        }
        decision_hash = canonical_hash(content)
        return cls(
            decision_id=InstanceIdentifier(
                "cross-source-comparability-decision",
                decision_hash.removeprefix(_SHA256_PREFIX),
            ),
            request_hash=request_hash,
            state=state,
            dimension_findings=dimension_findings,
            conditions=conditions,
            transformations_required=transformations_required,
            bridge_application_reference=bridge_application_reference,
            rule_reference=rule_reference,
            evidence_references=evidence_references,
            registry_version=registry_version,
            registry_hash=registry_hash,
            left_observation=left_observation,
            right_observation=right_observation,
            reason_codes=reason_codes,
            missing_information=missing_information,
            leaf_result=leaf_result,
            bridge_execution_hash=bridge_execution_hash,
            decision_hash=decision_hash,
        )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class BridgeRegistration:
    """Immutable declaration of a claim-scoped bridge or transformation."""

    bridge_reference: RegistryReference
    source_semantic_key: SemanticIdentityKey
    target_semantic_key: SemanticIdentityKey
    claim_scope: tuple[RegistryReference, ...]
    bridge_mode: BridgeMode
    transformation_operation: RegistryReference | None
    source_units: tuple[UnitReference, ...]
    target_units: tuple[UnitReference, ...]
    fixed_parameters: tuple[MetadataEntry, ...]
    domain_constraints: tuple[MetadataEntry, ...]
    applicability_conditions: tuple[MetadataEntry, ...]
    method_version: RegistryReference
    evidence_references: tuple[RegistryReference, ...]
    evidence_applicability: tuple[RegistryReference, ...]
    uncertainty_model: RegistryReference | None
    invertibility: BridgeInvertibility
    lossiness_description: str | None
    provenance_rule: RegistryReference
    registry_version: str
    authority_origin: BridgeAuthorityOrigin = BridgeAuthorityOrigin.PRODUCTION
    bridge_hash: str | None = None

    def __post_init__(self) -> None:
        _require_instance(self.bridge_reference, RegistryReference, "bridge_reference")
        if self.bridge_reference.identifier.object_type != "comparability-bridge":
            raise ValueError("bridge_reference must identify a comparability bridge")
        _require_instance(self.source_semantic_key, SemanticIdentityKey, "source_semantic_key")
        _require_instance(self.target_semantic_key, SemanticIdentityKey, "target_semantic_key")
        if self.source_semantic_key == self.target_semantic_key:
            raise ValueError("bridge source and target semantic keys must differ")
        _require_reference_tuple(self.claim_scope, "claim_scope")
        if not self.claim_scope:
            raise ValueError("bridge claim_scope must not be empty")
        _require_enum(self.bridge_mode, BridgeMode, "bridge_mode")
        _require_optional_instance(
            self.transformation_operation,
            RegistryReference,
            "transformation_operation",
        )
        if self.bridge_mode is BridgeMode.NUMERICAL_TRANSFORMATION:
            if self.transformation_operation is None:
                raise ValueError("numerical bridges require a transformation operation")
            if (
                self.uncertainty_model is None
                and self.invertibility is not BridgeInvertibility.EXACT
            ):
                raise ValueError("lossy numerical bridges require an uncertainty model")
        _require_tuple_items(self.source_units, UnitReference, "source_units")
        _require_tuple_items(self.target_units, UnitReference, "target_units")
        _require_tuple_items(self.fixed_parameters, MetadataEntry, "fixed_parameters")
        _require_tuple_items(self.domain_constraints, MetadataEntry, "domain_constraints")
        _require_tuple_items(
            self.applicability_conditions,
            MetadataEntry,
            "applicability_conditions",
        )
        _require_instance(self.method_version, RegistryReference, "method_version")
        _require_reference_tuple(self.evidence_references, "evidence_references")
        _require_reference_tuple(self.evidence_applicability, "evidence_applicability")
        if (
            self.authority_origin is BridgeAuthorityOrigin.PRODUCTION
            and not self.evidence_references
        ):
            raise ValueError("production bridges require evidence references")
        _require_optional_instance(self.uncertainty_model, RegistryReference, "uncertainty_model")
        _require_enum(self.invertibility, BridgeInvertibility, "invertibility")
        if self.invertibility is BridgeInvertibility.NON_INVERTIBLE_LOSSY:
            _require_text(self.lossiness_description or "", "lossiness_description")
        elif self.lossiness_description is not None:
            _require_text(self.lossiness_description, "lossiness_description")
        _require_instance(self.provenance_rule, RegistryReference, "provenance_rule")
        _require_text(self.registry_version, "registry_version")
        _require_enum(self.authority_origin, BridgeAuthorityOrigin, "authority_origin")
        expected_hash = self._content_hash()
        if self.bridge_hash is None:
            object.__setattr__(self, "bridge_hash", expected_hash)
        elif self.bridge_hash != expected_hash:
            raise ValueError("bridge_hash does not match immutable bridge content")

    def _content_hash(self) -> str:
        return canonical_hash(
            {
                "bridge_reference": self.bridge_reference,
                "source_semantic_key": self.source_semantic_key,
                "target_semantic_key": self.target_semantic_key,
                "claim_scope": self.claim_scope,
                "bridge_mode": self.bridge_mode,
                "transformation_operation": self.transformation_operation,
                "source_units": self.source_units,
                "target_units": self.target_units,
                "fixed_parameters": self.fixed_parameters,
                "domain_constraints": self.domain_constraints,
                "applicability_conditions": self.applicability_conditions,
                "method_version": self.method_version,
                "evidence_references": self.evidence_references,
                "evidence_applicability": self.evidence_applicability,
                "uncertainty_model": self.uncertainty_model,
                "invertibility": self.invertibility,
                "lossiness_description": self.lossiness_description,
                "provenance_rule": self.provenance_rule,
                "registry_version": self.registry_version,
                "authority_origin": self.authority_origin,
            }
        )

    @property
    def canonical_bridge_hash(self) -> str:
        assert self.bridge_hash is not None
        return self.bridge_hash


@register_serializable_type
@dataclass(frozen=True, slots=True)
class BridgeApplicationRequest:
    """Request to resolve and, for numerical bridges, execute one bridge."""

    request_id: InstanceIdentifier
    source_observation: ObservationAuthorityReference
    bridge_reference: RegistryReference
    claim_intent: RegistryReference
    requested_parameters: tuple[MetadataEntry, ...] = ()
    target_identity: MeasurementIdentity | None = None

    def __post_init__(self) -> None:
        _require_instance(self.request_id, InstanceIdentifier, "request_id")
        if self.request_id.instance_type != "bridge-request":
            raise ValueError("request_id must identify a bridge request")
        _require_instance(
            self.source_observation, ObservationAuthorityReference, "source_observation"
        )
        _require_instance(self.bridge_reference, RegistryReference, "bridge_reference")
        _require_instance(self.claim_intent, RegistryReference, "claim_intent")
        _require_tuple_items(self.requested_parameters, MetadataEntry, "requested_parameters")
        _require_optional_instance(self.target_identity, MeasurementIdentity, "target_identity")

    @property
    def request_hash(self) -> str:
        return canonical_hash(self)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class BridgeExecutionResult:
    """Provenance-bound result of an executed or declarative bridge."""

    execution_id: InstanceIdentifier
    status: BridgeExecutionStatus
    request_hash: str
    bridge_reference: RegistryReference
    bridge_hash: str
    source_observation: ObservationAuthorityReference
    transformed_observation: ScientificMeasurementObservation | None
    processing_run: ProcessingRun | None
    provenance: Provenance | None
    output_observation_hash: str | None
    uncertainty_model: RegistryReference | None
    lossiness_description: str | None
    execution_hash: str | None = None
    method_version: RegistryReference | None = None
    provenance_rule: RegistryReference | None = None

    def __post_init__(self) -> None:
        _require_instance(self.execution_id, InstanceIdentifier, "execution_id")
        if self.execution_id.instance_type != "bridge-execution":
            raise ValueError("execution_id must identify a bridge execution")
        _require_enum(self.status, BridgeExecutionStatus, "status")
        _require_hash(self.request_hash, "request_hash")
        _require_instance(self.bridge_reference, RegistryReference, "bridge_reference")
        _require_hash(self.bridge_hash, "bridge_hash")
        _require_instance(
            self.source_observation, ObservationAuthorityReference, "source_observation"
        )
        _require_optional_instance(
            self.transformed_observation,
            ScientificMeasurementObservation,
            "transformed_observation",
        )
        _require_optional_instance(self.processing_run, ProcessingRun, "processing_run")
        _require_optional_instance(self.provenance, Provenance, "provenance")
        if self.output_observation_hash is not None:
            _require_hash(self.output_observation_hash, "output_observation_hash")
        _require_optional_instance(self.uncertainty_model, RegistryReference, "uncertainty_model")
        if self.lossiness_description is not None:
            _require_text(self.lossiness_description, "lossiness_description")
        _require_optional_instance(self.method_version, RegistryReference, "method_version")
        _require_optional_instance(self.provenance_rule, RegistryReference, "provenance_rule")
        if self.status is BridgeExecutionStatus.EXECUTED:
            if (
                self.transformed_observation is None
                or self.processing_run is None
                or self.provenance is None
                or self.output_observation_hash is None
                or self.method_version is None
                or self.provenance_rule is None
            ):
                raise ValueError("executed bridge result must contain transformed provenance")
            if canonical_hash(self.transformed_observation) != self.output_observation_hash:
                raise ValueError("output_observation_hash does not match transformed observation")
        elif self.transformed_observation is not None:
            raise ValueError("declarative bridge result cannot contain a transformed observation")
        expected_hash = canonical_hash(
            {
                "request_hash": self.request_hash,
                "bridge_reference": self.bridge_reference,
                "bridge_hash": self.bridge_hash,
                "source_observation": self.source_observation,
                "transformed_observation": self.transformed_observation,
                "processing_run": self.processing_run,
                "provenance": self.provenance,
                "output_observation_hash": self.output_observation_hash,
                "uncertainty_model": self.uncertainty_model,
                "lossiness_description": self.lossiness_description,
                "method_version": self.method_version,
                "provenance_rule": self.provenance_rule,
                "status": self.status,
            }
        )
        if self.execution_hash is None:
            object.__setattr__(self, "execution_hash", expected_hash)
        elif self.execution_hash != expected_hash:
            raise ValueError("execution_hash does not match immutable bridge execution")
        expected_id = InstanceIdentifier(
            "bridge-execution", expected_hash.removeprefix(_SHA256_PREFIX)
        )
        if self.execution_id != expected_id:
            raise ValueError("execution_id does not match immutable bridge execution")

    @property
    def canonical_execution_hash(self) -> str:
        assert self.execution_hash is not None
        return self.execution_hash


__all__ = [
    "BridgeApplicationRequest",
    "BridgeAuthorityOrigin",
    "BridgeExecutionResult",
    "BridgeExecutionStatus",
    "BridgeInvertibility",
    "BridgeMode",
    "BridgeRegistration",
    "ClaimContext",
    "ComparabilityDimension",
    "CrossSourceComparabilityDecision",
    "CrossSourceComparabilityRequest",
    "DimensionFinding",
    "DimensionFindingStatus",
    "ObservationAuthorityReference",
    "SemanticIdentityKey",
]
