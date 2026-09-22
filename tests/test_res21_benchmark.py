from __future__ import annotations

from dataclasses import replace

import pytest

from dynamislm.benchmark import (
    CandidateAnswer,
    ErrorClass,
    ExclusionRegistry,
    HiddenAccessRequest,
    HiddenStoreDescriptor,
    Principal,
    SplitName,
    TaskOutcome,
    allocate_splits,
    audit_contamination,
    bind_case_payload,
    bind_res71_operation,
    bind_res71_refusal,
    build_contamination_report,
    build_error_event_report,
    build_fixture_allocation,
    build_fixture_exclusion_registry,
    build_fixture_manifest_bundle,
    build_res71_runtime_binding,
    build_synthetic_reference_fixture_cases,
    coverage_manifest_digest,
    coverage_obligation_count,
    make_authority_binding,
    minimum_full_coverage_case_count,
    preflight_hidden_access,
    preflight_training_exclusion,
    score_case,
    target_counts,
    validate_authority_binding,
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
from dynamislm.benchmark.constants import (
    AuthorityKind,
    CaseOrigin,
    PreflightStatus,
    ScoringProfile,
)
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


def test_res60_res62_res69_bindings_reject_cross_authority_forgery() -> None:
    population = make_authority_binding(
        AuthorityKind.RES60_POPULATION,
        governed_field_ids=("expected_answer",),
    )
    provenance = make_authority_binding(
        AuthorityKind.RES62_PROVENANCE,
        governed_field_ids=("expected_answer",),
    )
    statistics = make_authority_binding(
        AuthorityKind.RES69_STATISTICS,
        governed_field_ids=("expected_answer",),
    )
    for binding in (population, provenance, statistics):
        validate_authority_binding(binding)
    with pytest.raises(ValueError):
        validate_authority_binding(replace(population, digest=provenance.digest))
    with pytest.raises(ValueError):
        validate_authority_binding(replace(provenance, version="0.0.0"))
    with pytest.raises(ValueError):
        make_authority_binding(
            AuthorityKind.RES69_STATISTICS,
            source_reference_id=population.source_reference_id,
            governed_field_ids=("expected_answer",),
        )


def test_ground_truth_and_mutation_contracts_reject_forged_metadata() -> None:
    cases = build_synthetic_reference_fixture_cases()
    engine = cases[0]
    missing_expected = bind_case_payload(
        replace(
            engine,
            expected_answer=replace(
                engine.expected_answer,
                required_field_ids=("value", "missing"),
            ),
            case_payload_hash="sha256:" + "0" * 64,
        )
    )
    with pytest.raises(ValueError, match="absent from expected_fields"):
        validate_case(missing_expected)
    missing_authority = bind_case_payload(
        replace(
            engine,
            authority=tuple(
                replace(binding, governed_field_ids=("input.deterministic_results",))
                for binding in engine.authority
            ),
            case_payload_hash="sha256:" + "0" * 64,
        )
    )
    with pytest.raises(ValueError, match="not covered"):
        validate_case(missing_authority)
    mutation = next(
        case for case in cases if case.provenance.origin_class is CaseOrigin.ADVERSARIAL_MUTATION
    )
    forged_mutation = bind_case_payload(
        replace(
            mutation,
            provenance=replace(mutation.provenance, changed_fields=("question",)),
            case_payload_hash="sha256:" + "0" * 64,
        )
    )
    with pytest.raises(ValueError, match="changed_fields"):
        validate_case_set(tuple(forged_mutation if case is mutation else case for case in cases))
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


def test_split_allocator_qualifies_the_frozen_benchmark_scale() -> None:
    """The allocator must handle the first exact-count feasible matrix scale."""

    from dataclasses import replace

    from dynamislm.benchmark.hashing import bind_case_payload

    assert coverage_obligation_count() == 87
    assert minimum_full_coverage_case_count() == 434
    assert target_counts(434) == {
        SplitName.PUBLIC_DEVELOPMENT: 260,
        SplitName.FROZEN_VALIDATION: 87,
        SplitName.HIDDEN_FINAL: 87,
    }

    template = next(
        case
        for case in build_synthetic_reference_fixture_cases()
        if case.provenance.origin_class is CaseOrigin.DETERMINISTIC_SYNTHETIC
    )
    scale_cases = []
    for index in range(434):
        case_id = f"scale-fixture-{index:03d}"
        namespace = f"PSE-V1/scale/fixture-generator/{index:03d}"
        seed_block = f"seed-{index:04d}"
        scale_cases.append(
            bind_case_payload(
                replace(
                    template,
                    case_id=case_id,
                    question=f"{template.question} Fixture member {index}.",
                    input=replace(
                        template.input,
                        question_text=f"{template.question} Fixture member {index}.",
                    ),
                    provenance=replace(
                        template.provenance,
                        seed_namespace=namespace,
                        seed_block=seed_block,
                        generator_family=f"scale-generator-family-{index:03d}",
                    ),
                    split=replace(
                        template.split,
                        isolation_cluster_id=f"scale-cluster-{index:03d}",
                    ),
                    contamination=replace(
                        template.contamination,
                        source_family_id=f"scale-source-{index:03d}",
                        protocol_template_id=f"scale-template-{index:03d}",
                        expert_author_batch_id=f"scale-batch-{index:03d}",
                        artifact_ids=(f"scale-artifact-{index:03d}",),
                        benchmark_artifact_ids=(f"scale-artifact-{index:03d}",),
                        training_exclusion_ids=(f"scale-exclusion-{index:03d}",),
                        generator_namespace=namespace,
                        generator_seed_block=seed_block,
                    ),
                    case_payload_hash="sha256:" + "0" * 64,
                )
            )
        )
    cases = tuple(scale_cases)
    first = allocate_splits(cases)
    second = allocate_splits(cases)
    assert first.cases == second.cases
    assert tuple(
        sum(case.split.split_name is split for case in first.cases)
        for split in (
            SplitName.PUBLIC_DEVELOPMENT,
            SplitName.FROZEN_VALIDATION,
            SplitName.HIDDEN_FINAL,
        )
    ) == (260, 87, 87)


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
    no_private_index = ExclusionRegistry(entries=registry.entries)
    blocked_without_private_text = audit_contamination(exact_candidate, no_private_index)
    assert blocked_without_private_text.status == "BLOCKED"
    report = build_contamination_report(approved)
    assert report.audit_label == "PSE_V1_CONTAMINATION_AUDIT=PASS"
    assert report.pretraining_exposure == "UNKNOWN"


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


def test_exclusion_preflight_rejects_incomplete_artifact_inventory() -> None:
    bundle = build_fixture_manifest_bundle()
    incomplete = replace(
        bundle.exclusion_manifest,
        entries=bundle.exclusion_manifest.entries[1:],
    )
    from dynamislm.benchmark.hashing import bind_exclusion_manifest

    incomplete = bind_exclusion_manifest(incomplete)
    result = preflight_training_exclusion(
        incomplete,
        expected_manifest_hash=incomplete.manifest_digest,
    )
    assert result.status is PreflightStatus.BLOCKED


def test_error_reports_fail_closed_for_positive_events_without_denominators() -> None:
    bundle = build_fixture_manifest_bundle()
    engine = next(case for case in bundle.cases if case.capability_id == "C08")
    result = score_case(engine, {"fields": {"value": 999.0}, "unit": "m"})
    with pytest.raises(ValueError, match="no eligible case denominator"):
        build_error_event_report((result,), cases=())


def test_calibration_profile_is_explicitly_not_scored_until_runner_support() -> None:
    engine = next(
        case
        for case in build_synthetic_reference_fixture_cases()
        if case.provenance.origin_class is CaseOrigin.DETERMINISTIC_ENGINE_DERIVED
    )
    calibration = bind_case_payload(
        replace(
            engine,
            expected_answer=replace(
                engine.expected_answer,
                required_field_ids=("probabilities",),
                expected_fields={"probabilities": ("PASS", "FAIL")},
            ),
            scoring_contract=replace(
                engine.scoring_contract,
                profile_id=ScoringProfile.CALIBRATION_V1,
                required_output_fields=("probabilities",),
                critical_fields=("probabilities",),
                error_attribution=(
                    ("probabilities", ErrorClass.INVENTED_NUMERICAL_SCIENCE),
                    ("__over_refusal__", ErrorClass.OVER_REFUSAL),
                ),
            ),
            case_payload_hash="sha256:" + "0" * 64,
        )
    )
    calibration_score = score_case(
        calibration,
        {"fields": {"probabilities": {"PASS": 1.0}}},
    )
    assert calibration_score.outcome is TaskOutcome.NOT_SCORED


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
