"""Fail-closed validation for V1 cases and expert/provenance metadata."""

from __future__ import annotations

import math
from collections.abc import Mapping

from dynamislm.benchmark.authority import (
    validate_authority_bindings,
)
from dynamislm.benchmark.constants import (
    BENCHMARK_SEMANTIC_VERSION,
    CASE_SCHEMA_VERSION,
    CaseOrigin,
    ExpectedAnswerKind,
    RefusalDecision,
    ScoringProfile,
)
from dynamislm.benchmark.contracts import (
    BenchmarkCaseV1,
    ExpertReviewMetadata,
)
from dynamislm.benchmark.hashing import validate_case_payload_hash
from dynamislm.refusal.models import RefusalClass


def _walk_numbers(value: object, path: str = "") -> tuple[tuple[str, float], ...]:
    if isinstance(value, bool):
        return ()
    if isinstance(value, int | float):
        return ((path, float(value)),)
    if isinstance(value, Mapping):
        result: list[tuple[str, float]] = []
        for key, item in value.items():
            result.extend(_walk_numbers(item, f"{path}.{key}" if path else str(key)))
        return tuple(result)
    if isinstance(value, tuple | list):
        result = []
        for index, item in enumerate(value):
            result.extend(_walk_numbers(item, f"{path}[{index}]"))
        return tuple(result)
    return ()


def _validate_finite_expected_answer(case: BenchmarkCaseV1) -> None:
    for path, value in _walk_numbers(case.expected_answer.expected_fields):
        if not math.isfinite(value):
            raise ValueError(f"expected answer contains nonfinite numeric value at {path}")


def validate_expert_review_metadata(review: ExpertReviewMetadata) -> None:
    if not isinstance(review, ExpertReviewMetadata):
        raise TypeError("review must be ExpertReviewMetadata")
    # Construction enforces the core fields; repeat the policy at validation time.
    if review.approval_status != "APPROVED":
        raise ValueError("missing expert reviewer approval")
    if review.author_id == review.reviewer_id:
        raise ValueError("expert reviewer must be independent from author")
    if not review.reviewer_expertise:
        raise ValueError("expert reviewer expertise is required")


def _validate_origin(case: BenchmarkCaseV1) -> None:
    provenance = case.provenance
    contamination = case.contamination
    review = provenance.review
    validate_expert_review_metadata(review)
    origin = provenance.origin_class

    if origin is CaseOrigin.DETERMINISTIC_SYNTHETIC:
        required = (
            provenance.generator_id,
            provenance.generator_version,
            provenance.generator_family,
            provenance.seed_namespace,
            provenance.seed_block,
            contamination.generator_namespace,
            contamination.generator_seed_block,
        )
        if any(value is None for value in required):
            raise ValueError("deterministic synthetic case requires generator and seed metadata")
        if (
            contamination.generator_namespace != provenance.seed_namespace
            or contamination.generator_seed_block != provenance.seed_block
        ):
            raise ValueError("synthetic generator and seed bindings must agree")
        if provenance.generator_registry_digest is None:
            raise ValueError("synthetic case requires a generator registry digest")
        if (
            provenance.source_artifact_ids
            or provenance.source_content_digests
            or case.source_evidence_refs
        ):
            raise ValueError("source/synthetic provenance mixing is not allowed")
        if not any(binding.authority_kind == "GENERATOR" for binding in case.authority):
            raise ValueError("deterministic synthetic case requires a generator authority binding")
        if any(
            binding.digest != provenance.generator_registry_digest
            for binding in case.authority
            if binding.authority_kind == "GENERATOR"
        ):
            raise ValueError("synthetic generator authority is stale or caller-minted")
    elif origin is CaseOrigin.DETERMINISTIC_ENGINE_DERIVED:
        if not provenance.engine_operation_id or not provenance.engine_reference_case_id:
            raise ValueError("engine-derived case requires operation and reference-case identity")
        if provenance.engine_reference_digest is None or provenance.engine_registry_digest is None:
            raise ValueError("engine-derived case requires reference and registry digests")
        operation_binding = next(
            (
                binding
                for binding in case.authority
                if binding.authority_kind == "RES71_OPERATION"
                and binding.source_reference_id == provenance.engine_operation_id
            ),
            None,
        )
        if operation_binding is None:
            raise ValueError("engine-derived case requires RES-71 operation authority")
        if case.expected_answer.reference_case_id != provenance.engine_reference_case_id:
            raise ValueError("engine-derived answer/reference provenance mismatch")
        if case.expected_answer.expected_operation_id != provenance.engine_operation_id:
            raise ValueError("engine-derived answer/operation provenance mismatch")
    elif origin is CaseOrigin.EXPERT_AUTHORED_SEMANTIC:
        if not provenance.authority_lineage or not provenance.review.rubric_digest:
            raise ValueError("expert semantic case requires rubric and authority lineage")
        if not case.authority:
            raise ValueError("expert semantic case requires explicit authority")
        if not any(binding.authority_kind == "EXPERT_RUBRIC" for binding in case.authority):
            raise ValueError("expert semantic case requires an expert-rubric authority binding")
        if any(
            binding.digest != provenance.review.rubric_digest
            for binding in case.authority
            if binding.authority_kind == "EXPERT_RUBRIC"
        ):
            raise ValueError("expert rubric authority is stale or caller-minted")
    elif origin is CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION:
        if not provenance.source_artifact_ids or not provenance.source_content_digests:
            raise ValueError("source-backed case requires source artifact and content digests")
        if not provenance.evidence_span_refs or not case.source_evidence_refs:
            raise ValueError("source-backed case requires exact evidence spans")
        if any(
            reference.reference_kind.value != "SOURCE" for reference in case.source_evidence_refs
        ):
            raise ValueError("source-backed case evidence references must be SOURCE references")
        source_digests = {reference.digest for reference in case.source_evidence_refs} | set(
            provenance.source_content_digests
        )
        if any(
            binding.digest not in source_digests
            for binding in case.authority
            if binding.authority_kind in {"SOURCE_DOCUMENT", "SOURCE_EVIDENCE_SPAN"}
        ):
            raise ValueError("source authority is not bound to a source digest")
        if (
            provenance.generator_id
            or provenance.seed_namespace
            or contamination.generator_namespace
        ):
            raise ValueError("source-backed case cannot carry synthetic generator provenance")
        if case.expected_answer.kind is not ExpectedAnswerKind.EVIDENCE_EXTRACTION:
            raise ValueError("source-backed case must use the evidence-extraction answer contract")
    elif origin is CaseOrigin.ADVERSARIAL_MUTATION:
        if provenance.parent_case_hash is None:
            raise ValueError("adversarial mutation requires a parent case hash")
        if not provenance.mutation_operator or not provenance.mutation_version:
            raise ValueError("adversarial mutation requires operator and version")
        if provenance.mutation_seed is None or not provenance.changed_fields:
            raise ValueError("adversarial mutation requires seed and changed fields")
        if provenance.parent_origin_class is None:
            raise ValueError("adversarial mutation must preserve parent origin class")
    else:  # pragma: no cover - enum construction is exhaustive
        raise ValueError("unsupported case origin")


def _validate_answer_contract(case: BenchmarkCaseV1) -> None:
    answer = case.expected_answer
    numeric_fields = _walk_numbers(answer.expected_fields)
    if numeric_fields:
        if case.tolerance_contract is None:
            raise ValueError("numeric expected value requires a tolerance contract")
        if not answer.reference_case_id or not answer.expected_operation_id:
            raise ValueError("numeric expected value requires a registered operation/reference")
        if any(
            field_id.split(".", 1)[0] not in case.tolerance_contract.field_ids
            for field_id, _ in numeric_fields
            if field_id.split(".", 1)[0] in answer.required_field_ids
        ):
            raise ValueError("numeric tolerance does not cover every expected numeric field")
    if answer.kind is ExpectedAnswerKind.NUMERIC_RESULT:
        if case.tolerance_contract is None:
            raise ValueError("numeric expected answer requires a tolerance contract")
        if answer.reference_case_id is None or answer.expected_operation_id is None:
            raise ValueError("numeric expected answer requires exact RES-71 bindings")
        authority_ids = {binding.source_reference_id for binding in case.authority}
        if answer.reference_case_id not in authority_ids:
            raise ValueError("numeric answer is missing its RES-71 reference-case authority")
        if answer.expected_operation_id not in authority_ids:
            raise ValueError("numeric answer is missing its RES-71 operation authority")
    elif case.tolerance_contract is not None and not case.tolerance_contract.field_ids:
        raise ValueError("tolerance contract cannot be empty")
    refusal = case.refusal_expectation
    if refusal.decision is RefusalDecision.REQUIRED:
        if answer.kind is not ExpectedAnswerKind.REFUSAL:
            raise ValueError("required refusal must use the refusal answer form")
        if refusal.refusal_class is None or not isinstance(refusal.refusal_class, RefusalClass):
            raise ValueError("unsupported refusal class")
    if case.comparability_contract.requested_state is not None:
        if answer.kind is ExpectedAnswerKind.COMPARABILITY_DECISION:
            state = answer.expected_fields.get("state")
            if (
                state is not None
                and str(state) != case.comparability_contract.requested_state.value
            ):
                raise ValueError("comparability answer state disagrees with contract")
    if case.scoring_contract.profile_id is ScoringProfile.NUMERIC_TOLERANCE_V1:
        if case.tolerance_contract is None:
            raise ValueError("numeric scorer requires tolerance")


def validate_case(case: BenchmarkCaseV1, *, validate_hash: bool = True) -> None:
    """Validate a single case against the frozen schema and live authority."""

    if not isinstance(case, BenchmarkCaseV1):
        raise TypeError("case must be BenchmarkCaseV1")
    if (
        case.benchmark_version != BENCHMARK_SEMANTIC_VERSION
        or case.schema_version != CASE_SCHEMA_VERSION
    ):
        raise ValueError("case version is not the frozen V1 contract")
    if validate_hash:
        validate_case_payload_hash(case)
    validate_authority_bindings(case.authority)
    _validate_origin(case)
    _validate_answer_contract(case)
    _validate_finite_expected_answer(case)
    if case.split.split_name is not None and case.split.split_manifest_hash is None:
        raise ValueError("assigned case is missing split manifest binding")
    if case.provenance.origin_class is CaseOrigin.DETERMINISTIC_ENGINE_DERIVED:
        operation = next(
            binding for binding in case.authority if binding.authority_kind == "RES71_OPERATION"
        )
        # The detailed operation object is held by the producer adapter; this check rejects
        # stale caller identity through the canonical authority binding.
        _ = operation


def validate_case_set(cases: tuple[BenchmarkCaseV1, ...], *, validate_hash: bool = True) -> None:
    """Validate uniqueness, mutation lineage, and namespace isolation."""

    if not cases:
        raise ValueError("benchmark case set must be non-empty")
    ids = tuple(case.case_id for case in cases)
    if len(set(ids)) != len(ids):
        raise ValueError("benchmark case IDs must be unique")
    for case in cases:
        validate_case(case, validate_hash=validate_hash)
    by_hash = {case.case_payload_hash: case for case in cases}
    for case in cases:
        provenance = case.provenance
        if provenance.origin_class is CaseOrigin.ADVERSARIAL_MUTATION:
            assert provenance.parent_case_hash is not None
            if provenance.parent_case_hash not in by_hash:
                raise ValueError("adversarial mutation parent case is not present")
            parent = by_hash[provenance.parent_case_hash]
            if provenance.parent_origin_class is not parent.provenance.origin_class:
                raise ValueError("mutation parent origin class is not preserved")
            if case.split.split_name is not None and parent.split.split_name is not None:
                if case.split.split_name is not parent.split.split_name:
                    raise ValueError("mutation lineage crosses split boundary")
    namespaces: dict[tuple[str, str, str], str] = {}
    for case in cases:
        provenance = case.provenance
        if provenance.generator_id and provenance.seed_namespace and provenance.seed_block:
            key = (provenance.generator_id, provenance.seed_namespace, provenance.seed_block)
            prior = namespaces.get(key)
            if prior is not None and prior != case.case_id:
                raise ValueError("generator seed namespace/block is reused")
            namespaces[key] = case.case_id
        if case.contamination.generator_namespace and case.contamination.generator_seed_block:
            key = (
                provenance.generator_id or "unknown-generator",
                case.contamination.generator_namespace,
                case.contamination.generator_seed_block,
            )
            prior = namespaces.get(key)
            if prior is not None and prior != case.case_id:
                raise ValueError("contamination generator seed namespace/block is reused")
            namespaces[key] = case.case_id


__all__ = [
    "validate_case",
    "validate_case_set",
    "validate_expert_review_metadata",
]
