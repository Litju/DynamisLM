from __future__ import annotations

from dataclasses import replace

import pytest

from dynamislm.benchmark import (
    CandidateAnswer,
    ErrorClass,
    HiddenAccessRequest,
    HiddenStoreDescriptor,
    Principal,
    SplitName,
    TaskOutcome,
    audit_contamination,
    bind_res71_operation,
    bind_res71_refusal,
    build_fixture_allocation,
    build_fixture_exclusion_registry,
    build_fixture_manifest_bundle,
    build_res71_runtime_binding,
    build_synthetic_reference_fixture_cases,
    coverage_manifest_digest,
    preflight_hidden_access,
    preflight_training_exclusion,
    score_case,
    validate_case,
    validate_case_coverage,
    validate_case_payload_hash,
    validate_case_set,
    validate_coverage_matrix,
    validate_manifest_bundle,
    validate_res71_operation_binding,
    validate_res71_refusal_binding,
    validate_res71_runtime_binding,
    validate_split_assignment,
)
from dynamislm.benchmark.constants import CaseOrigin, PreflightStatus
from dynamislm.benchmark.contracts import BenchmarkCaseV1
from dynamislm.serialization import canonical_json, from_canonical_json


def test_frozen_coverage_matrix_proves_all_capabilities_and_families() -> None:
    result = validate_coverage_matrix()

    assert result.status == "PASS"
    assert len(result.represented_capabilities) == 18
    assert len(result.represented_families) == 14
    assert coverage_manifest_digest().startswith("sha256:")
    assert validate_case_coverage(build_synthetic_reference_fixture_cases()).status == "BLOCKED"


def test_case_hash_is_content_only_and_round_trips_with_serialization_v3() -> None:
    case = build_synthetic_reference_fixture_cases()[0]

    validate_case_payload_hash(case)
    restored = from_canonical_json(canonical_json(case), BenchmarkCaseV1)
    assert restored == case

    split_mutation = replace(
        case,
        split=replace(
            case.split,
            split_name=SplitName.HIDDEN_FINAL,
            split_manifest_version=None,
            split_manifest_hash=None,
            membership_digest=None,
        ),
    )
    assert split_mutation.case_payload_hash == case.case_payload_hash
    with pytest.raises(ValueError, match="payload hash mismatch"):
        validate_case_payload_hash(
            replace(
                case,
                question="mutated question",
                input=replace(case.input, question_text="mutated question"),
            )
        )
    with pytest.raises(TypeError):
        case.input.structured_context["mutation"] = True  # type: ignore[index]


def test_res71_runtime_reference_operation_and_refusal_bindings_are_live() -> None:
    runtime = build_res71_runtime_binding()
    validate_res71_runtime_binding(runtime)

    operation = bind_res71_operation(
        "dynamislm:registered-operation:unit-normalization@1.0.0",
        reference_case_id="res71-external-unit-km-to-m",
    )
    validate_res71_operation_binding(operation)
    refusal = bind_res71_refusal("CMJ RFD")
    validate_res71_refusal_binding(refusal)

    with pytest.raises(ValueError):
        validate_res71_runtime_binding(
            replace(runtime, sealed_reference_digest="sha256:" + "0" * 64)
        )
    with pytest.raises(ValueError):
        bind_res71_operation(
            "dynamislm:registered-operation:unit-normalization@1.0.0",
            reference_case_id="res71-causal-overclaim-refusal",
        )


def test_authority_and_provenance_fail_closed() -> None:
    cases = build_synthetic_reference_fixture_cases()
    for case in cases:
        validate_case(case)
    validate_case_set(cases)

    engine = cases[0]
    with pytest.raises(ValueError):
        validate_case(
            replace(
                engine,
                authority=(
                    replace(engine.authority[0], digest="sha256:" + "0" * 64),
                    *engine.authority[1:],
                ),
            )
        )
    with pytest.raises(ValueError):
        replace(engine.provenance.review, approval_status="PENDING")

    source = next(
        case
        for case in cases
        if case.provenance.origin_class.value == "SOURCE_BACKED_EVIDENCE_EXTRACTION"
    )
    with pytest.raises(ValueError):
        validate_case(
            replace(
                source,
                provenance=replace(
                    source.provenance,
                    origin_class=CaseOrigin.DETERMINISTIC_SYNTHETIC,
                ),
            )
        )


def test_split_allocator_is_deterministic_exact_and_lineage_atomic() -> None:
    from dynamislm.benchmark.split import allocate_splits

    cases = build_synthetic_reference_fixture_cases()
    first = allocate_splits(cases)
    second = allocate_splits(cases)

    assert first.cases == second.cases
    assert first.target_counts == {
        SplitName.PUBLIC_DEVELOPMENT: 4,
        SplitName.FROZEN_VALIDATION: 1,
        SplitName.HIDDEN_FINAL: 1,
    }
    parent = next(case for case in first.cases if case.case_id == "fixture-expert-refusal")
    mutation = next(
        case for case in first.cases if case.case_id == "fixture-adversarial-refusal-mutation"
    )
    assert parent.split.split_name is mutation.split.split_name

    allocated = first.cases
    # The case set is provisional until manifests bind split hashes.
    with pytest.raises(ValueError, match="missing split manifest"):
        validate_split_assignment(allocated)


def test_contamination_registry_runs_exact_and_fuzzy_mandatory_checks() -> None:
    allocation = build_fixture_allocation()
    registry = build_fixture_exclusion_registry(allocation)
    reference = registry.artifacts[0]
    exact_candidate = replace(
        reference, artifact_id="candidate-exact", source_family_id="new-family"
    )
    exact_audit = audit_contamination(exact_candidate, registry)
    assert exact_audit.status == "BLOCKED"
    assert reference.artifact_id in exact_audit.exact_matches

    fuzzy_candidate = replace(
        reference,
        artifact_id="candidate-fuzzy",
        text=reference.text.replace("registered", "registered-variant"),
        source_family_id="new-family",
    )
    fuzzy_audit = audit_contamination(fuzzy_candidate, registry)
    assert fuzzy_audit.status == "BLOCKED"
    assert reference.artifact_id in fuzzy_audit.fuzzy_matches

    approved = audit_contamination(
        exact_candidate,
        registry,
        approved_overlap_artifact_ids=(reference.artifact_id,),
    )
    assert approved.status == "PASS"


def test_manifest_bundle_rejects_stale_bindings_and_hidden_training_access() -> None:
    bundle = build_fixture_manifest_bundle()
    validate_manifest_bundle(bundle)
    stale = replace(
        bundle,
        benchmark_manifest=replace(
            bundle.benchmark_manifest,
            authority_manifest_hash="sha256:" + "0" * 64,
        ),
    )
    with pytest.raises(ValueError):
        validate_manifest_bundle(stale)

    hidden_case = next(
        case for case in bundle.cases if case.split.split_name is SplitName.HIDDEN_FINAL
    )
    store = HiddenStoreDescriptor(
        store_id="fixture-hidden-store",
        store_version="1.0.0",
        benchmark_manifest_hash=bundle.benchmark_manifest.benchmark_manifest_hash,
        hidden_case_ids=(hidden_case.case_id,),
        payloads_available=True,
        answers_available=True,
        hidden_case_hashes=((hidden_case.case_id, hidden_case.case_payload_hash),),
    )
    request = HiddenAccessRequest(Principal.TRAINING, hidden_case.case_id, "PAYLOAD", "training")
    blocked = preflight_hidden_access(
        request,
        case=hidden_case,
        benchmark_manifest=bundle.benchmark_manifest,
        store=store,
    )
    assert blocked.status is PreflightStatus.BLOCKED
    allowed = preflight_hidden_access(
        replace(request, principal=Principal.EVALUATION_SERVICE),
        case=hidden_case,
        benchmark_manifest=bundle.benchmark_manifest,
        store=store,
    )
    assert allowed.status is PreflightStatus.PASS

    assert (
        preflight_training_exclusion(
            bundle.exclusion_manifest,
            expected_manifest_hash=bundle.exclusion_manifest.manifest_digest,
        ).status
        is PreflightStatus.PASS
    )
    assert (
        preflight_training_exclusion(None, expected_manifest_hash=None).status
        is PreflightStatus.BLOCKED
    )


def test_scorers_apply_exact_unit_zero_tolerance_and_refusal_contract() -> None:
    bundle = build_fixture_manifest_bundle()
    engine = next(case for case in bundle.cases if case.capability_id == "C08")
    assert (
        score_case(engine, {"fields": {"value": 1000.0}, "unit": "m"}).outcome is TaskOutcome.PASS
    )
    assert (
        score_case(engine, {"fields": {"value": 1000.0}, "unit": "km"}).outcome is TaskOutcome.FAIL
    )
    assert score_case(engine, {"fields": {"value": 1000.0}}).outcome is TaskOutcome.FAIL

    refusal = next(case for case in bundle.cases if case.case_id == "fixture-expert-refusal")
    expected = refusal.refusal_expectation
    assert expected.refusal_class is not None
    correct = score_case(
        refusal,
        CandidateAnswer(
            decision="REFUSE",
            fields={},
            refusal={
                "blocked_claim": expected.blocked_claim,
                "refusal_class": expected.refusal_class.value,
                "reason_codes": expected.reason_codes,
                "missing_information": expected.missing_information,
                "safe_description": expected.what_can_still_be_safely_described,
            },
        ),
    )
    assert correct.outcome is TaskOutcome.REFUSAL_CORRECT
    incorrect = score_case(refusal, {"decision": "ANSWER", "fields": {}})
    assert incorrect.outcome is TaskOutcome.REFUSAL_INCORRECT
    assert any(
        event.error_class is ErrorClass.FALSE_SCIENTIFIC_ACCEPTANCE
        for event in incorrect.error_events
    )
