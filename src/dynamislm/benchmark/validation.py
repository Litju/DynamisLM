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
    AuthorityKind,
    CaseOrigin,
    ExpectedAnswerKind,
    RefusalDecision,
    ScoringProfile,
)
from dynamislm.benchmark.contracts import (
    AuthorityBinding,
    BenchmarkCaseV1,
    ExpertReviewMetadata,
)
from dynamislm.benchmark.hashing import case_content_projection, validate_case_payload_hash
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
        operation_binding = next(
            binding
            for binding in case.authority
            if binding.authority_kind == AuthorityKind.RES71_OPERATION.value
            and binding.source_reference_id == provenance.engine_operation_id
        )
        reference_binding = next(
            binding
            for binding in case.authority
            if binding.authority_kind == AuthorityKind.RES71_REFERENCE_CASE.value
            and binding.source_reference_id == provenance.engine_reference_case_id
        )
        if provenance.engine_method_version != operation_binding.version:
            raise ValueError("engine-derived method version is stale")
        if provenance.engine_registry_digest != operation_binding.digest:
            raise ValueError("engine-derived registry digest is stale or forged")
        if provenance.engine_reference_digest != reference_binding.digest:
            raise ValueError("engine-derived reference digest is stale or forged")
        if not case.input.deterministic_results:
            raise ValueError("engine-derived case requires a deterministic result view")
        for result in case.input.deterministic_results:
            if result.operation_id != provenance.engine_operation_id:
                raise ValueError("deterministic result operation does not match provenance")
            if result.method_version != provenance.engine_method_version:
                raise ValueError("deterministic result method version does not match provenance")
            if result.authority_reference != provenance.engine_reference_case_id:
                raise ValueError(
                    "deterministic result authority reference does not match provenance"
                )
            if result.result_or_refusal_digest != provenance.engine_reference_digest:
                raise ValueError("deterministic result digest does not match provenance")
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
        source_ids = {
            *provenance.source_artifact_ids,
            *(reference.source_reference_id for reference in case.source_evidence_refs),
            *(excerpt.source_id for excerpt in case.input.evidence_excerpts),
        }
        if any(item not in source_ids for item in provenance.source_artifact_ids):
            raise ValueError("source artifact identity is not present in canonical evidence")
        excerpt_ids = {excerpt.excerpt_id for excerpt in case.input.evidence_excerpts}
        if any(item not in excerpt_ids for item in provenance.evidence_span_refs):
            raise ValueError("evidence span identity is not present in the input evidence")
        excerpts_by_id = {excerpt.excerpt_id: excerpt for excerpt in case.input.evidence_excerpts}
        for reference in case.source_evidence_refs:
            matching_excerpts = tuple(
                excerpt
                for excerpt in case.input.evidence_excerpts
                if excerpt.source_id == reference.source_reference_id
                and excerpt.locator == reference.locator
                and excerpt.content_digest == reference.digest
            )
            if not matching_excerpts:
                raise ValueError(
                    "source evidence reference is not bound to an exact canonical span"
                )
        if any(span not in excerpts_by_id for span in provenance.evidence_span_refs):
            raise ValueError("source provenance span is not present in the exact evidence index")
        source_authorities = tuple(
            binding
            for binding in case.authority
            if binding.authority_kind
            in {AuthorityKind.SOURCE_DOCUMENT.value, AuthorityKind.SOURCE_EVIDENCE_SPAN.value}
        )
        if not source_authorities:
            raise ValueError(
                "source-backed case requires source-document or evidence-span authority"
            )
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
    expected_field_ids = tuple(answer.required_field_ids)
    if len(set(expected_field_ids)) != len(expected_field_ids):
        raise ValueError("expected required field IDs must be unique")
    missing_expected = tuple(
        field_id for field_id in expected_field_ids if field_id not in answer.expected_fields
    )
    if missing_expected:
        raise ValueError(
            "expected required fields are absent from expected_fields: "
            + ", ".join(missing_expected)
        )
    if set(case.scoring_contract.required_output_fields) != set(expected_field_ids):
        raise ValueError("scoring required_output_fields must equal expected required fields")
    if any(
        field_id not in case.scoring_contract.required_output_fields
        for field_id in case.scoring_contract.critical_fields
    ):
        raise ValueError("critical fields must be valid scored fields")
    attribution = dict(case.scoring_contract.error_attribution)
    if any(
        field_id not in attribution and "__default__" not in attribution
        for field_id in case.scoring_contract.required_output_fields
    ):
        raise ValueError("every scored field requires explicit error attribution metadata")
    if case.refusal_expectation.decision is not RefusalDecision.PROHIBITED:
        if "__decision__" not in attribution:
            raise ValueError(
                "non-prohibited refusal semantics require explicit decision attribution"
            )
    else:
        if "__over_refusal__" not in attribution:
            raise ValueError(
                "prohibited refusal semantics require explicit over-refusal attribution"
            )
    if case.refusal_expectation.decision is RefusalDecision.REQUIRED:
        if "__refusal__" not in attribution:
            raise ValueError("required refusal semantics require explicit refusal attribution")
    if case.expected_answer.prohibited_claims and "__prohibited_claim__" not in attribution:
        raise ValueError("prohibited claims require explicit error attribution metadata")
    if (
        case.expected_answer.kind is ExpectedAnswerKind.REFUSAL
        and case.refusal_expectation.decision is RefusalDecision.PROHIBITED
    ):
        raise ValueError("a refusal answer cannot be paired with PROHIBITED refusal semantics")
    _validate_answer_authority_contract(case)
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


def _authority_covers_field(binding: AuthorityBinding, field_id: str) -> bool:
    governed = set(binding.governed_field_ids)
    return bool(
        governed
        & {
            field_id,
            f"expected_answer.{field_id}",
            "expected_answer",
            "scoring_contract",
            "refusal_expectation",
            "claim_contract",
        }
    )


def _validate_answer_authority_contract(case: BenchmarkCaseV1) -> None:
    """Require field-level authority coverage and answer-kind authority."""

    for field_id in case.scoring_contract.required_output_fields:
        if not any(_authority_covers_field(binding, field_id) for binding in case.authority):
            raise ValueError(f"scored field is not covered by an applicable authority: {field_id}")

    kinds = {binding.authority_kind for binding in case.authority}
    answer_kind = case.expected_answer.kind
    if answer_kind is ExpectedAnswerKind.NUMERIC_RESULT:
        required = {
            AuthorityKind.RES71_OPERATION.value,
            AuthorityKind.RES71_REFERENCE_CASE.value,
        }
        if not required.issubset(kinds):
            raise ValueError("numeric answer requires RES-71 operation and reference authority")
    elif answer_kind is ExpectedAnswerKind.COMPARABILITY_DECISION:
        if AuthorityKind.RES70_COMPARABILITY.value not in kinds:
            raise ValueError("comparability answer requires RES-70 comparability authority")
    elif answer_kind is ExpectedAnswerKind.CLAIM_AUTHORITY_DECISION:
        if AuthorityKind.RES70_CLAIM.value not in kinds:
            raise ValueError("claim answer requires RES-70 claim authority")
    elif answer_kind is ExpectedAnswerKind.EVIDENCE_EXTRACTION:
        if not kinds.intersection(
            {
                AuthorityKind.SOURCE_DOCUMENT.value,
                AuthorityKind.SOURCE_EVIDENCE_SPAN.value,
            }
        ):
            raise ValueError("evidence answer requires canonical source authority")
    elif answer_kind is ExpectedAnswerKind.REFUSAL:
        refusal_authorities = {
            AuthorityKind.RES71_UNRESOLVED.value,
            AuthorityKind.RES70_CLAIM.value,
            AuthorityKind.RES70_ANALYSIS.value,
            AuthorityKind.RES70_COMPARABILITY.value,
            AuthorityKind.RES69_STATISTICS.value,
            AuthorityKind.RES60_POPULATION.value,
            AuthorityKind.RES62_PROVENANCE.value,
            AuthorityKind.SOURCE_DOCUMENT.value,
            AuthorityKind.SOURCE_EVIDENCE_SPAN.value,
            AuthorityKind.EXPERT_RUBRIC.value,
        }
        if not kinds.intersection(refusal_authorities):
            raise ValueError("refusal answer requires a refusal-capable scientific authority")


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
    from dynamislm.benchmark.contamination import validate_case_contamination_binding

    validate_case_contamination_binding(case)
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
            parent_projection = case_content_projection(parent)
            child_projection = case_content_projection(case)
            changed_projection_fields = tuple(
                sorted(
                    (
                        field_name
                        for field_name in parent_projection
                        if parent_projection[field_name] != child_projection[field_name]
                    ),
                    key=lambda item: item.encode("utf-8"),
                )
            )
            declared_changed_fields = tuple(
                sorted(provenance.changed_fields, key=lambda item: item.encode("utf-8"))
            )
            if declared_changed_fields != changed_projection_fields:
                raise ValueError(
                    "mutation changed_fields do not match the canonical parent-to-child "
                    "semantic projection"
                )
            if not any(
                edge.upstream_id == provenance.parent_case_hash
                and edge.downstream_id == case.case_id
                and edge.relation == "MUTATION"
                for edge in provenance.derivation_edges
            ):
                raise ValueError("mutation lineage must contain an explicit parent-to-child edge")
            parent_primary_authority = tuple(
                binding
                for binding in parent.authority
                if any(
                    governed in {"expected_answer", "refusal_expectation", "claim_contract"}
                    or governed.startswith("expected_answer.")
                    for governed in binding.governed_field_ids
                )
            )
            if not parent_primary_authority:
                raise ValueError("mutation parent has no primary answer authority")
            if any(binding not in case.authority for binding in parent_primary_authority):
                raise ValueError("mutation does not preserve the parent primary authority")
            # Revalidate the preserved authority against the live registries rather than
            # trusting the parent's already-materialized object identity.
            validate_authority_bindings(parent.authority)
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
