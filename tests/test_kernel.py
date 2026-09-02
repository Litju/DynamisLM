from __future__ import annotations

import datetime as datetime_module
import importlib
import json
import math
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path

import pytest

from dynamislm import (
    SERIALIZATION_VERSION,
    AcquisitionIdentity,
    AcquisitionRecord,
    ApplicabilityDecision,
    CategoricalValue,
    ComparabilityAuthority,
    ComparabilityDecisionSource,
    ComparabilityReasonCode,
    ComparabilityRequest,
    ComparabilityResult,
    ComparabilityState,
    EvidenceApplicability,
    InstanceIdentifier,
    IntervalValue,
    MeasurementIdentity,
    MeasurementQuality,
    MeasurementResult,
    MetadataEntry,
    ObservationContext,
    ProcessingIdentity,
    ProcessingRun,
    RefusalClass,
    RefusalReasonCode,
    RefusalResult,
    RefusalStatus,
    RegisteredComparabilityRule,
    RegistryReference,
    ResultStatus,
    ScalarValue,
    ScientificClassification,
    ScientificIdentifier,
    ScientificMeasurementObservation,
    ScientificRole,
    SemanticIdentity,
    SourceArtifact,
    StructuredOutputReference,
    TransformationRequest,
    UncertaintyMetadata,
    ValueOrigin,
    VectorValue,
    VersionIdentity,
    canonical_hash,
    canonical_json,
    create_derived_observation,
    from_canonical_json,
)

UTC = datetime_module.UTC


def _reference(object_type: str, key: str, label: str, version: str = "1.0.0") -> RegistryReference:
    return RegistryReference(
        identifier=ScientificIdentifier("dynamislm", object_type, key, version),
        display_label=label,
    )


def _identity(
    suffix: str, *, method_version: str = "1.0.0", label: str = "Example metric"
) -> MeasurementIdentity:
    metric = _reference("metric", f"metric-{suffix}", label)
    return MeasurementIdentity(
        identity_id=ScientificIdentifier(
            "dynamislm", "measurement", f"identity-{suffix}", method_version
        ),
        semantic=SemanticIdentity(
            construct=_reference("construct", f"construct-{suffix}", "Example construct"),
            test_family=_reference("test-family", f"family-{suffix}", "Generic test family"),
            protocol=_reference("protocol", f"protocol-{suffix}", "Example protocol"),
            measurand=_reference("measurand", f"measurand-{suffix}", "Example measurand"),
            metric_definition=metric,
        ),
        acquisition=AcquisitionIdentity(
            device=_reference("device", f"device-{suffix}", "Example device"),
            raw_artifact=InstanceIdentifier("artifact", f"raw-{suffix}"),
            sensor_channel="channel-1",
        ),
        processing=ProcessingIdentity(
            estimator=_reference("estimator", f"estimator-{suffix}", "Example estimator"),
            method_parameters=(MetadataEntry("method_version", method_version),),
        ),
        version=VersionIdentity(
            processing_method=_reference(
                "processing-method", f"method-{suffix}", "Example processing method", method_version
            ),
            method_registry_version=method_version,
            software_version="0.1.0",
        ),
    )


def _context(suffix: str = "one") -> ObservationContext:
    return ObservationContext(
        context_id=InstanceIdentifier("context", suffix),
        athlete_id=InstanceIdentifier("athlete", "athlete-1"),
        session_id=InstanceIdentifier("session", "session-1"),
        test_instance_id=InstanceIdentifier("test-instance", "test-1"),
        trial_id=InstanceIdentifier("trial", f"trial-{suffix}"),
        observed_at=datetime_module.datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        population_context="trained adult non-clinical team-sport athlete",
        environment=(MetadataEntry("surface", "indoor"),),
        context_metadata=(MetadataEntry("operator", "researcher-1"),),
    )


def _result(
    suffix: str = "one",
    *,
    value: float = 1.0,
    classification: ScientificClassification | None = None,
) -> MeasurementResult:
    return MeasurementResult(
        result_id=InstanceIdentifier("result", suffix),
        value=ScalarValue(value),
        unit=None,
        classification=classification
        or ScientificClassification(
            ValueOrigin.DIRECT_MEASUREMENT, (ScientificRole.PERFORMANCE_OUTCOME,)
        ),
        quality=MeasurementQuality(),
        uncertainty=UncertaintyMetadata(),
        status=ResultStatus.VALID,
    )


def _derived_observation(
    suffix: str = "one", *, method_version: str = "1.0.0", value: float = 1.0
) -> ScientificMeasurementObservation:
    identity = _identity("same", method_version=method_version)
    observation_id = InstanceIdentifier("observation", suffix)
    artifact_id = identity.acquisition.raw_artifact
    device = identity.acquisition.device
    assert artifact_id is not None
    assert device is not None
    artifact = SourceArtifact(
        artifact_id=artifact_id,
        content_digest="sha256:raw-artifact",
        media_type="application/octet-stream",
    )
    acquisition = AcquisitionRecord(
        acquisition_id=InstanceIdentifier("acquisition", suffix),
        device=device,
        source_artifact_id=artifact.artifact_id,
        sensor_channel=identity.acquisition.sensor_channel,
    )
    processing = ProcessingRun(
        processing_run_id=InstanceIdentifier("processing-run", suffix),
        source_artifact_ids=(artifact.artifact_id,),
        method=identity.version.processing_method,
        parameters=(MetadataEntry("algorithm_version", method_version),),
        software_version="0.1.0",
        output_entity_id=observation_id,
    )
    return create_derived_observation(
        observation_id=observation_id,
        context=_context(suffix),
        identity=identity,
        result=_result(suffix, value=value),
        source_artifact=artifact,
        acquisition=acquisition,
        processing_run=processing,
        recorded_at=datetime_module.datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
    )


def _comparability_request(
    transformations: tuple[TransformationRequest, ...] = (),
) -> ComparabilityRequest:
    return ComparabilityRequest(
        request_id=InstanceIdentifier("comparability-request", "request-1"),
        left_observation_id=InstanceIdentifier("observation", "left"),
        right_observation_id=InstanceIdentifier("observation", "right"),
        claim="compare the observations longitudinally",
        requested_transformations=transformations,
        material_dimensions=("protocol", "device", "processing_method"),
    )


def test_same_display_label_can_have_distinct_measurement_identities() -> None:
    first = _identity("first", label="Peak output")
    second = _identity("second", label="Peak output")

    assert first.display_label == second.display_label
    assert first.identity_id != second.identity_id
    assert first != second


def test_result_value_does_not_redefine_measurement_identity() -> None:
    identity = _identity("stable")
    first = _result("first", value=1.0)
    second = _result("second", value=2.0)
    first_observation = ScientificMeasurementObservation(
        InstanceIdentifier("observation", "first"),
        _context("first"),
        identity,
        first,
        _derived_observation("first").provenance,
    )
    second_observation = ScientificMeasurementObservation(
        InstanceIdentifier("observation", "second"),
        _context("second"),
        identity,
        second,
        _derived_observation("second").provenance,
    )

    assert first_observation.identity == second_observation.identity
    assert first_observation.result != second_observation.result
    assert canonical_hash(first_observation.identity) == canonical_hash(second_observation.identity)
    identity_json = canonical_json(identity)
    assert '"value":1.0' not in identity_json
    assert '"value":2.0' not in identity_json


def test_reprocessing_same_raw_artifact_creates_distinct_observations() -> None:
    first = _derived_observation("d1", method_version="1.0.0")
    second = _derived_observation("d2", method_version="2.0.0")

    assert (
        first.provenance.source_artifacts[0].artifact_id
        == second.provenance.source_artifacts[0].artifact_id
    )
    assert first.identity != second.identity
    assert first.observation_id != second.observation_id
    assert first.provenance.processing_runs[0].method != second.provenance.processing_runs[0].method
    assert first.provenance.processing_runs[0].output_entity_id == first.observation_id
    assert second.provenance.processing_runs[0].output_entity_id == second.observation_id
    assert canonical_hash(first) != canonical_hash(second)


def test_processing_run_output_entity_contract_is_typed_and_versioned() -> None:
    observation = _derived_observation("output-entity")
    run = observation.provenance.processing_runs[0]

    assert run.output_entity_id == observation.observation_id
    assert run.output_entity_id.instance_type == "observation"
    serialized = canonical_json(run)
    assert '"output_entity_id"' in serialized
    assert '"output_observation_id"' not in serialized
    restored = from_canonical_json(serialized, ProcessingRun)
    assert restored == run
    assert canonical_json(restored) == serialized
    assert canonical_hash(restored) == canonical_hash(run)

    envelope = json.loads(serialized)
    envelope["serialization_version"] = 2
    envelope["payload"]["output_observation_id"] = envelope["payload"].pop("output_entity_id")
    with pytest.raises(ValueError, match="unsupported serialization version"):
        from_canonical_json(json.dumps(envelope), ProcessingRun)


def test_provenance_rejects_forged_processing_output_entity_linkage() -> None:
    observation = _derived_observation("forged-output")
    run = observation.provenance.processing_runs[0]
    forged_run = replace(
        run,
        output_entity_id=InstanceIdentifier("observation", "not-the-produced-observation"),
    )

    with pytest.raises(ValueError, match="output entity"):
        replace(observation.provenance, processing_runs=(forged_run,))


def test_reprocessing_cannot_overwrite_prior_provenance() -> None:
    original = _derived_observation("original", method_version="1.0.0")
    replacement = _derived_observation("replacement", method_version="2.0.0")

    with pytest.raises(FrozenInstanceError):
        original.result = replacement.result  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        original.provenance.processing_runs = replacement.provenance.processing_runs  # type: ignore[misc]
    assert original.provenance.processing_runs[0].method.identifier.version == "1.0.0"


def test_observation_context_is_not_measurement_identity() -> None:
    identity_fields = {field.name for field in fields(MeasurementIdentity)}
    context_fields = {field.name for field in fields(ObservationContext)}

    assert {"context", "athlete_id", "session_id"}.isdisjoint(identity_fields)
    assert {
        "athlete_id",
        "session_id",
        "test_instance_id",
        "trial_id",
        "observed_at",
    } <= context_fields
    assert "athlete-1" not in canonical_json(_identity("context-check"))


def test_evidence_applicability_is_versionable_without_changing_identity() -> None:
    identity = _identity("evidence")
    evidence = _reference("evidence", "method-paper", "Example evidence")
    limited = EvidenceApplicability(
        applicability_id=ScientificIdentifier(
            "dynamislm", "evidence-applicability", "example", "1.0.0"
        ),
        measurement_identity_id=identity.identity_id,
        evidence=evidence,
        decision=ApplicabilityDecision.LIMITED,
        population_scope="trained adult team-sport athletes",
        conditions=("same protocol",),
    )
    supported = EvidenceApplicability(
        applicability_id=ScientificIdentifier(
            "dynamislm", "evidence-applicability", "example", "2.0.0"
        ),
        measurement_identity_id=identity.identity_id,
        evidence=evidence,
        decision=ApplicabilityDecision.SUPPORTED,
        population_scope="trained adult team-sport athletes",
        conditions=(),
    )

    assert (
        limited.measurement_identity_id == supported.measurement_identity_id == identity.identity_id
    )
    assert limited != supported


def test_value_origin_and_scientific_roles_are_independent_axes() -> None:
    classifications = {
        ScientificClassification(origin, (role,))
        for origin in ValueOrigin
        for role in ScientificRole
    }

    assert len(classifications) == len(ValueOrigin) * len(ScientificRole)
    assert (
        ScientificClassification(
            ValueOrigin.DERIVED_MECHANICAL_QUANTITY, (ScientificRole.PERFORMANCE_OUTCOME,)
        )
        in classifications
    )
    assert (
        ScientificClassification(
            ValueOrigin.DIRECT_MEASUREMENT, (ScientificRole.PHYSIOLOGICAL_INFERENCE,)
        )
        in classifications
    )


def test_scientific_roles_allow_zero_or_multiple_explicit_tags() -> None:
    unassigned = ScientificClassification(ValueOrigin.DIRECT_MEASUREMENT, ())
    multiple = ScientificClassification(
        ValueOrigin.DERIVED_MECHANICAL_QUANTITY,
        (ScientificRole.PHYSIOLOGICAL_INFERENCE, ScientificRole.PERFORMANCE_OUTCOME),
    )
    reordered = ScientificClassification(
        ValueOrigin.DERIVED_MECHANICAL_QUANTITY,
        (ScientificRole.PERFORMANCE_OUTCOME, ScientificRole.PHYSIOLOGICAL_INFERENCE),
    )

    assert unassigned.scientific_roles == ()
    assert multiple.scientific_roles == (
        ScientificRole.PERFORMANCE_OUTCOME,
        ScientificRole.PHYSIOLOGICAL_INFERENCE,
    )
    assert multiple == reordered
    assert canonical_hash(multiple) == canonical_hash(reordered)


def test_scientific_classification_rejects_invalid_role_values() -> None:
    with pytest.raises(ValueError, match="must be an immutable tuple"):
        ScientificClassification(
            ValueOrigin.DIRECT_MEASUREMENT,
            [  # type: ignore[arg-type]
                ScientificRole.PERFORMANCE_OUTCOME
            ],
        )
    with pytest.raises(ValueError, match="must not contain duplicates"):
        ScientificClassification(
            ValueOrigin.DIRECT_MEASUREMENT,
            (ScientificRole.PERFORMANCE_OUTCOME, ScientificRole.PERFORMANCE_OUTCOME),
        )
    with pytest.raises(ValueError, match="must be a ValueOrigin"):
        ScientificClassification("DIRECT_MEASUREMENT", ())  # type: ignore[arg-type]


def test_value_origin_does_not_infer_scientific_roles() -> None:
    assert all(
        ScientificClassification(origin, ()).scientific_roles == () for origin in ValueOrigin
    )


def test_derived_mechanical_quantity_does_not_imply_performance_outcome() -> None:
    classification = ScientificClassification(ValueOrigin.DERIVED_MECHANICAL_QUANTITY, ())

    assert ScientificRole.PERFORMANCE_OUTCOME not in classification.scientific_roles


@pytest.mark.parametrize(
    "role",
    (ScientificRole.LATENT_CONSTRUCT_INTERPRETATION, ScientificRole.PHYSIOLOGICAL_INFERENCE),
)
def test_interpretive_roles_remain_explicit(role: ScientificRole) -> None:
    classification = ScientificClassification(ValueOrigin.MODEL_ESTIMATE, (role,))

    assert classification.scientific_roles == (role,)


def test_unassigned_roles_roundtrip_and_hash_are_deterministic() -> None:
    result = _result(
        "unassigned",
        classification=ScientificClassification(ValueOrigin.DIRECT_MEASUREMENT, ()),
    )
    serialized = canonical_json(result)
    restored = from_canonical_json(serialized, MeasurementResult)

    assert '"scientific_roles":[]' in serialized
    assert restored == result
    assert canonical_json(restored) == serialized
    assert canonical_hash(restored) == canonical_hash(result)


def test_performance_outcome_is_explicitly_assignable_to_a_derived_result() -> None:
    result = _result(
        "derived-performance",
        value=0.42,
        classification=ScientificClassification(
            ValueOrigin.DERIVED_MECHANICAL_QUANTITY,
            (ScientificRole.PERFORMANCE_OUTCOME,),
        ),
    )

    assert result.classification.value_origin is ValueOrigin.DERIVED_MECHANICAL_QUANTITY
    assert result.classification.scientific_roles == (ScientificRole.PERFORMANCE_OUTCOME,)


def test_serialization_version_rejects_the_prior_role_cardinality_wire_shape() -> None:
    result = _result(
        "versioned-roles",
        classification=ScientificClassification(ValueOrigin.DIRECT_MEASUREMENT, ()),
    )
    envelope = json.loads(canonical_json(result))

    assert SERIALIZATION_VERSION == 3
    assert envelope["serialization_version"] == SERIALIZATION_VERSION
    envelope["serialization_version"] = 2
    classification_wire = envelope["payload"]["classification"]
    classification_wire["scientific_role"] = "PERFORMANCE_OUTCOME"
    del classification_wire["scientific_roles"]
    with pytest.raises(ValueError, match="unsupported serialization version"):
        from_canonical_json(json.dumps(envelope), MeasurementResult)


def test_all_comparability_states_are_explicit_and_roundtrip() -> None:
    assert {state.value for state in ComparabilityState} == {
        "COMPARABLE",
        "COMPARABLE_WITH_CONDITIONS",
        "REQUIRES_TRANSFORMATION",
        "BRIDGE_VALIDATION_REQUIRED",
        "NOT_COMPARABLE",
        "INSUFFICIENT_INFORMATION",
    }
    rule = _reference("comparability-rule", "example", "Example rule")
    result = ComparabilityResult(
        result_id=InstanceIdentifier("comparability-result", "result-1"),
        request_id=InstanceIdentifier("comparability-request", "request-1"),
        state=ComparabilityState.COMPARABLE_WITH_CONDITIONS,
        reason_codes=(ComparabilityReasonCode.CONDITIONS_APPLY,),
        conditions=("same registered protocol",),
        transformations_required=(),
        missing_information=(),
        rule_reference=rule,
        evidence_references=(),
        decided_by=ComparabilityDecisionSource.DETERMINISTIC_RULE,
    )

    restored = from_canonical_json(canonical_json(result), ComparabilityResult)
    assert restored == result
    assert canonical_hash(restored) == canonical_hash(result)


def test_transformation_request_does_not_imply_comparability() -> None:
    transformation = TransformationRequest(
        operation=_reference("registered-operation", "unit-transform", "Unit transformation"),
        parameters=(MetadataEntry("target_unit", "arbitrary-unit"),),
    )
    request = _comparability_request((transformation,))
    outcome = ComparabilityAuthority().adjudicate(request)

    assert outcome.state is ComparabilityState.INSUFFICIENT_INFORMATION
    assert outcome.transformations_required == (transformation,)
    assert outcome.reason_codes == (ComparabilityReasonCode.COMPARABILITY_NOT_REGISTERED,)
    assert outcome.decided_by is ComparabilityDecisionSource.UNRESOLVED


def test_unresolved_comparability_cannot_be_manually_upgraded() -> None:
    with pytest.raises(ValueError, match="unresolved comparability must be insufficient"):
        ComparabilityResult(
            result_id=InstanceIdentifier("comparability-result", "invalid"),
            request_id=InstanceIdentifier("comparability-request", "request-1"),
            state=ComparabilityState.COMPARABLE,
            reason_codes=(ComparabilityReasonCode.COMPARABILITY_NOT_REGISTERED,),
            conditions=(),
            transformations_required=(),
            missing_information=(),
            rule_reference=None,
            evidence_references=(),
            decided_by=ComparabilityDecisionSource.UNRESOLVED,
        )


def test_registered_comparability_rule_is_deterministic_authority() -> None:
    request = _comparability_request()
    rule_reference = _reference("comparability-rule", "registered", "Registered rule")

    def matches(candidate: ComparabilityRequest) -> bool:
        return candidate.claim == request.claim

    def evaluate(candidate: ComparabilityRequest) -> ComparabilityResult:
        return ComparabilityResult(
            result_id=InstanceIdentifier("comparability-result", "registered-1"),
            request_id=candidate.request_id,
            state=ComparabilityState.COMPARABLE,
            reason_codes=(),
            conditions=(),
            transformations_required=(),
            missing_information=(),
            rule_reference=rule_reference,
            evidence_references=(),
            decided_by=ComparabilityDecisionSource.DETERMINISTIC_RULE,
        )

    authority = ComparabilityAuthority().with_rule(
        RegisteredComparabilityRule(rule_reference, matches, evaluate)
    )
    result = authority.adjudicate(request)

    assert result.state is ComparabilityState.COMPARABLE
    assert result.decided_by is ComparabilityDecisionSource.DETERMINISTIC_RULE
    assert result.rule_reference == rule_reference


def test_registered_rule_cannot_return_a_result_for_another_request() -> None:
    request = _comparability_request()
    rule_reference = _reference("comparability-rule", "request-bound", "Request-bound rule")

    def evaluate(candidate: ComparabilityRequest) -> ComparabilityResult:
        return ComparabilityResult(
            result_id=InstanceIdentifier("comparability-result", "wrong-request"),
            request_id=InstanceIdentifier("comparability-request", "different"),
            state=ComparabilityState.COMPARABLE,
            reason_codes=(),
            conditions=(),
            transformations_required=(),
            missing_information=(),
            rule_reference=rule_reference,
            evidence_references=(),
            decided_by=ComparabilityDecisionSource.DETERMINISTIC_RULE,
        )

    authority = ComparabilityAuthority().with_rule(
        RegisteredComparabilityRule(rule_reference, lambda _: True, evaluate)
    )

    with pytest.raises(ValueError, match="request ID"):
        authority.adjudicate(request)


def test_structured_refusal_blocks_claim_but_preserves_safe_descriptions() -> None:
    result = RefusalResult(
        refusal_id=InstanceIdentifier("refusal", "longitudinal-1"),
        status=RefusalStatus.PARTIALLY_REFUSED,
        refusal_class=RefusalClass.COMPARABILITY_UNESTABLISHED,
        blocked_claim="the athlete improved across sessions",
        reason_codes=(RefusalReasonCode.COMPARABILITY_NOT_REGISTERED,),
        missing_information=("registered device bridge",),
        what_can_still_be_safely_described=(
            "each observation independently exists under its own identity",
            "the recorded values can be reported without a longitudinal comparison",
        ),
        observation_ids=(
            InstanceIdentifier("observation", "left"),
            InstanceIdentifier("observation", "right"),
        ),
    )

    assert result.blocks_claim
    assert len(result.observation_ids) == 2
    assert "each observation independently exists" in result.what_can_still_be_safely_described[0]
    assert from_canonical_json(canonical_json(result), RefusalResult) == result


def test_computation_not_registered_is_a_refusal_class() -> None:
    result = RefusalResult(
        refusal_id=InstanceIdentifier("refusal", "computation-1"),
        status=RefusalStatus.REFUSED,
        refusal_class=RefusalClass.COMPUTATION_NOT_REGISTERED,
        blocked_claim="calculate an unregistered quantity",
        reason_codes=(RefusalReasonCode.NO_REGISTERED_OPERATION,),
        missing_information=("registered deterministic operation",),
        what_can_still_be_safely_described=("the requested quantity is understood semantically",),
    )

    assert result.refusal_class is RefusalClass.COMPUTATION_NOT_REGISTERED


def test_no_test_specific_arithmetic_or_science_is_in_generic_public_package() -> None:
    package_file = importlib.import_module("dynamislm").__file__
    assert package_file is not None
    package_root = Path(package_file).parent
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in package_root.rglob("*.py")
        if "measurement/cmj" not in path.as_posix()
    )

    assert "cmj" not in source.lower()
    assert "vbt" not in source.lower()
    assert not hasattr(importlib.import_module("dynamislm"), "calculate_metric")
    assert not hasattr(importlib.import_module("dynamislm"), "CMJ_TEST_FAMILY")


def test_canonical_serialization_is_stable_and_rejects_non_finite_values() -> None:
    first = {"z": 1, "a": [2, 3]}
    second = {"a": [2, 3], "z": 1}

    assert canonical_json(first) == canonical_json(second)
    assert canonical_hash(first) == canonical_hash(second)
    with pytest.raises(ValueError, match="NaN and Infinity"):
        canonical_json({"value": math.nan})
    with pytest.raises(ValueError, match="NaN or Infinity"):
        ScalarValue(math.inf)


def test_tagged_result_variants_are_typed_and_serializable() -> None:
    values = (
        ScalarValue(2.0),
        VectorValue((1.0, 2.0)),
        IntervalValue(1.0, 2.0),
        CategoricalValue("high", ordinal=3),
        StructuredOutputReference(
            artifact_id=InstanceIdentifier("artifact", "series-1"),
            schema=_reference("schema", "series", "Series schema"),
        ),
    )

    assert [value.kind for value in values] == [
        "scalar",
        "vector",
        "interval",
        "categorical_or_ordinal",
        "structured_reference",
    ]
    for value in values:
        result = MeasurementResult(
            result_id=InstanceIdentifier("result", value.kind),
            value=value,
            unit=None,
            classification=ScientificClassification(
                ValueOrigin.MODEL_ESTIMATE, (ScientificRole.LATENT_CONSTRUCT_INTERPRETATION,)
            ),
        )
        assert from_canonical_json(canonical_json(result), MeasurementResult) == result


def test_clean_environment_import_smoke(tmp_path: Path) -> None:
    source_root = Path(__file__).parents[1] / "src"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import dynamislm; assert dynamislm.SERIALIZATION_VERSION == 3",
        ],
        cwd=tmp_path,
        env={
            "PATH": str(Path(sys.executable).parent),
            "PYTHONPATH": str(source_root),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
