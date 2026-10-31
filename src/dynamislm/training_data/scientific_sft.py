"""RES-402 bounded original development examples; never production training authority."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

from dynamislm.analysis import (
    CANONICAL_ANALYSIS_CAPABILITY_REGISTRY,
    AnalysisAuthorization,
    AnalysisAuthorizationRequest,
    AnalysisClass,
    AnalysisEstimandLevel,
    AnalysisLevelIdentity,
    AnalysisUnitOfAnalysis,
    authorize_analysis,
)
from dynamislm.external_load.metrics import (
    ExternalLoadComputationError,
    convert_external_load_value,
    duration_normalized_distance,
)
from dynamislm.external_load.registry import (
    EXTERNAL_LOAD_KILOMETER,
    EXTERNAL_LOAD_METER,
    EXTERNAL_LOAD_METERS_PER_MINUTE,
    EXTERNAL_LOAD_MINUTE,
)
from dynamislm.longitudinal.statistics import (
    StatisticalResult,
    StatisticalSupport,
    calculate_absolute_change,
    calculate_descriptive_within_athlete_sd,
)
from dynamislm.measurement.cmj.registry import METER
from dynamislm.measurement.identity import UnitReference
from dynamislm.qualification import OperationDisposition, build_registered_operation_inventory
from dynamislm.refusal import RefusalResult
from dynamislm.serialization import (
    canonical_bytes,
    canonical_hash,
    canonical_json,
    register_serializable_type,
)
from dynamislm.training_data.processing import sha256
from dynamislm.training_data.synthetic_science import instance, make_support, reference

SCHEMA = "RES402-SCIENTIFIC-SFT-1"
POPULATION = (
    "SYNTHETIC elite men's senior first-team top-division professional association football"
)


class Category(StrEnum):
    UNIT_CONVERSION = "UNIT_CONVERSION"
    DURATION_RATE = "DURATION_RATE"
    LONGITUDINAL = "LONGITUDINAL"
    METHOD_SELECTION = "METHOD_SELECTION"
    DESCRIPTIVE_DISPERSION = "DESCRIPTIVE_DISPERSION"
    UNIT_MISMATCH = "UNIT_MISMATCH"
    RELIABILITY = "RELIABILITY"
    CROSS_SOURCE = "CROSS_SOURCE"
    MISSING_DATA = "MISSING_DATA"
    UNKNOWN_PROVENANCE = "UNKNOWN_PROVENANCE"
    CAUSAL = "CAUSAL"
    CONTRADICTORY = "CONTRADICTORY"
    NO_DOWNGRADE = "NO_DOWNGRADE"


@register_serializable_type
@dataclass(frozen=True)
class ScientificTask:
    seed: int
    index: int
    category: Category
    question: str
    population: str
    athlete: str
    team: str
    session: str
    temporal_context: str
    objective: str
    requested_analysis_class: AnalysisClass | None
    values: tuple[float, ...]
    input_unit: UnitReference
    measurement_identity: str
    source_provenance: str | None
    available_evidence: tuple[str, ...]
    unavailable_evidence: tuple[str, ...]
    partition: str = "TRAIN"
    rights: str = "DEVELOPMENT_ONLY_NOT_TRAINING_AUTHORIZED"
    measurement_units: tuple[UnitReference, ...] = ()


@register_serializable_type
@dataclass(frozen=True)
class ScalarArguments:
    value: float
    duration: float | None
    input_unit: UnitReference
    output_unit: UnitReference
    duration_unit: UnitReference | None


@register_serializable_type
@dataclass(frozen=True)
class ToolCall:
    operation_id: str | None
    method_version: str
    scalar: ScalarArguments | None = None
    support: StatisticalSupport | None = None
    analysis_request: AnalysisAuthorizationRequest | None = None
    authority_reference: str | None = None


@register_serializable_type
@dataclass(frozen=True)
class ToolResponse:
    engine_response: str
    value: float | None
    unit: UnitReference | None
    refusal_codes: tuple[str, ...]
    analysis_authorization: str | None = None


@register_serializable_type
@dataclass(frozen=True)
class ScientificExample:
    schema: str
    task: ScientificTask
    call: ToolCall | None
    response: ToolResponse
    input_sha256: str
    result_sha256: str
    registry_sha256: str
    implementation_sha256: str
    messages_json: str
    example_sha256: str


@register_serializable_type
@dataclass(frozen=True)
class DevelopmentSet:
    schema: str
    seed: int
    qualification_scope: str
    examples: tuple[ScientificExample, ...]


@lru_cache(maxsize=1)
def authority_identity() -> tuple[str, str]:
    inventory = build_registered_operation_inventory()
    package = Path(__file__).resolve().parents[1]
    files = tuple(
        (p.relative_to(package).as_posix(), sha256(p.read_bytes()))
        for p in sorted(package.rglob("*.py"))
    )
    return canonical_hash((inventory, CANONICAL_ANALYSIS_CAPABILITY_REGISTRY)), canonical_hash(
        files
    )


def _qualified(operation_key: str, function: Callable[..., Any]) -> str:
    operation_id = f"dynamislm:registered-operation:{operation_key}@1.0.0"
    entry = next(
        (e for e in build_registered_operation_inventory() if e.operation_id == operation_id), None
    )
    path = f"{function.__module__}:{function.__name__}"
    if (
        entry is None
        or entry.disposition != OperationDisposition.IMPLEMENTED
        or path not in entry.implementation
    ):
        raise ValueError("unqualified operation adapter")
    return operation_id


def make_task(seed: int, index: int) -> ScientificTask:
    if (
        type(seed) is not int
        or not 0 <= seed <= 1_000_000
        or type(index) is not int
        or not 0 <= index < 39
    ):
        raise ValueError("bounded development seed/index required")
    category = tuple(Category)[index % len(Category)]
    key = f"{seed}-{index}"
    # These are authored input values, never independently calculated scientific answers.
    values: tuple[float, ...] = (0.30 + (seed % 7 + index) / 1000, 0.34 + index / 1000)
    objective = {
        Category.UNIT_CONVERSION: "Convert distance units; retain measurement identity.",
        Category.DURATION_RATE: "Describe distance per valid session duration.",
        Category.DESCRIPTIVE_DISPERSION: "Describe dispersion; do not infer measurement error.",
        Category.RELIABILITY: "Infer random measurement error from two observational trials.",
        Category.CAUSAL: "Identify the causal effect of training on jump performance.",
        Category.CONTRADICTORY: "Estimate causal effect and descriptive change as one estimand.",
        Category.NO_DOWNGRADE: "Estimate within-athlete association; no scalar substitution.",
    }.get(category, "Describe absolute longitudinal jump-height change only.")
    analysis = (
        None
        if category
        in {Category.UNIT_CONVERSION, Category.DURATION_RATE, Category.DESCRIPTIVE_DISPERSION}
        else AnalysisClass.RELIABILITY_RANDOM_ERROR_COMPARISON
        if category == Category.RELIABILITY
        else AnalysisClass.WITHIN_ATHLETE_ASSOCIATION
        if category == Category.NO_DOWNGRADE
        else AnalysisClass.SCALAR_ABSOLUTE_CHANGE
    )
    if category == Category.MISSING_DATA:
        values = values[:1]
    if category == Category.DESCRIPTIVE_DISPERSION:
        values = (*values, 0.33)
    if category == Category.UNIT_CONVERSION:
        values = (5.0 + index,)
    if category == Category.DURATION_RATE:
        values = (5.0 + index, 45.0)
    task = ScientificTask(
        seed,
        index,
        category,
        f"SYNTHETIC instruction {key}: {objective} Evidence case: {category.value}.",
        POPULATION,
        f"SYNTHETIC athlete {key}",
        "SYNTHETIC club first team",
        f"SYNTHETIC session {key}",
        "2026-08-12 UTC; baseline precedes follow-up in testing session",
        objective,
        analysis,
        values,
        EXTERNAL_LOAD_KILOMETER
        if category == Category.UNIT_CONVERSION
        else EXTERNAL_LOAD_METER
        if category == Category.DURATION_RATE
        else METER,
        "SYNTHETIC session distance"
        if category in {Category.UNIT_CONVERSION, Category.DURATION_RATE}
        else "SYNTHETIC fixed-protocol CMJ jump height",
        None
        if category == Category.UNKNOWN_PROVENANCE
        else canonical_hash(("SYNTHETIC original inputs", key, values)),
        ("original synthetic values", "fictional population context"),
        (
            "real athlete evidence",
            "causal identification",
            "reliability design",
            "normative thresholds",
        ),
    )

    units = tuple(
        UnitReference(reference("unit", "wrong-seconds").identifier, "s")
        if category == Category.UNIT_MISMATCH and i == 1
        else EXTERNAL_LOAD_MINUTE
        if category == Category.DURATION_RATE and i == 1
        else task.input_unit
        for i in range(len(values))
    )
    return replace(task, measurement_units=units)


def _analysis(
    task: ScientificTask, support: StatisticalSupport | None
) -> AnalysisAuthorizationRequest:
    assert task.requested_analysis_class is not None
    return AnalysisAuthorizationRequest(
        request_id=instance("analysis-authorization-request", f"{task.seed}-{task.index}"),
        analysis_class=task.requested_analysis_class,
        support=support,
        support_reference=None,
        observations=tuple(entry.observation for entry in support.included_entries)
        if support
        else (),
        identity_hashes=(),
        comparability_decisions=(),
        requested_level=AnalysisLevelIdentity(
            AnalysisUnitOfAnalysis.ATHLETE, AnalysisEstimandLevel.WITHIN_ATHLETE, "athlete_id"
        ),
        evidence_applicability=None,
        context_references=(),
    )


def _capability_id(task: ScientificTask) -> str:
    assert task.requested_analysis_class is not None
    capability = CANONICAL_ANALYSIS_CAPABILITY_REGISTRY.resolve(task.requested_analysis_class)
    if capability is None:
        raise ValueError("unknown analysis capability")
    return capability.capability_reference.identifier.stable_id


def _execute(task: ScientificTask) -> tuple[ToolCall | None, ToolResponse]:
    category = task.category
    local_refusal = {
        Category.CAUSAL: "CAUSAL_IDENTIFICATION_UNSUPPORTED",
        Category.CONTRADICTORY: "CONTRADICTORY_OBJECTIVES",
        Category.UNKNOWN_PROVENANCE: "SOURCE_PROVENANCE_REQUIRED",
    }.get(category)
    if local_refusal:
        return None, ToolResponse(
            canonical_json({"constructor_refusal": local_refusal}), None, None, (local_refusal,)
        )
    if category in {Category.UNIT_CONVERSION, Category.DURATION_RATE}:
        function = (
            convert_external_load_value
            if category == Category.UNIT_CONVERSION
            else duration_normalized_distance
        )
        key = (
            "unit-normalization"
            if category == Category.UNIT_CONVERSION
            else "duration-normalized-distance"
        )
        unit = (
            EXTERNAL_LOAD_METER
            if category == Category.UNIT_CONVERSION
            else EXTERNAL_LOAD_METERS_PER_MINUTE
        )
        arguments = ScalarArguments(
            task.values[0],
            task.values[1] if category == Category.DURATION_RATE else None,
            task.input_unit,
            unit,
            EXTERNAL_LOAD_MINUTE if category == Category.DURATION_RATE else None,
        )
        call = ToolCall(_qualified(key, function), "1.0.0", scalar=arguments)
        try:
            value = (
                convert_external_load_value(arguments.value, arguments.input_unit, unit)
                if category == Category.UNIT_CONVERSION
                else duration_normalized_distance(
                    arguments.value,
                    arguments.duration,
                    distance_unit=arguments.input_unit,
                    duration_unit=EXTERNAL_LOAD_MINUTE,
                    output_unit=unit,
                )
            )
        except ExternalLoadComputationError as exc:
            return call, ToolResponse(
                canonical_json({"reason_code": exc.reason_code}),
                None,
                None,
                (exc.reason_code.value,),
            )
        return call, ToolResponse(canonical_json(value), value, unit, ())
    if category == Category.MISSING_DATA:
        request = _analysis(task, None)
        refusal = authorize_analysis(request)
        if not isinstance(refusal, RefusalResult):
            raise ValueError("missing evidence unexpectedly authorized")
        return (
            ToolCall(
                None, "1.0.0", analysis_request=request, authority_reference=_capability_id(task)
            ),
            ToolResponse(canonical_json(refusal), None, None, refusal.reason_codes),
        )
    authorization_json = None
    support = make_support(
        f"{task.seed}-{task.index}",
        task.values,
        wrong_unit=category == Category.UNIT_MISMATCH,
        different_method=category == Category.CROSS_SOURCE,
    )
    analysis_request = _analysis(task, support) if task.requested_analysis_class else None
    result: AnalysisAuthorization | StatisticalResult | RefusalResult
    if category in {Category.RELIABILITY, Category.NO_DOWNGRADE}:
        assert analysis_request is not None
        # Analysis authorization is a qualified authority surface, not a new numerical operation.
        result = authorize_analysis(analysis_request)
        call = ToolCall(
            None,
            "1.0.0",
            analysis_request=analysis_request,
            authority_reference=_capability_id(task),
        )
    elif category == Category.DESCRIPTIVE_DISPERSION:
        call = ToolCall(
            _qualified(
                "longitudinal-within-athlete-sample-sd-v1", calculate_descriptive_within_athlete_sd
            ),
            "1.0.0",
            support=support,
        )
        result = calculate_descriptive_within_athlete_sd(support)
    else:
        if category in {Category.LONGITUDINAL, Category.METHOD_SELECTION}:
            assert analysis_request is not None
            authorization = authorize_analysis(analysis_request)
            authorization_json = canonical_json(authorization)
            if not isinstance(authorization, AnalysisAuthorization):
                raise ValueError("generated descriptive request did not authorize")
        call = ToolCall(
            _qualified("longitudinal-absolute-change-v1", calculate_absolute_change),
            "1.0.0",
            support=support,
            analysis_request=analysis_request,
        )
        result = calculate_absolute_change(support)
    if isinstance(result, RefusalResult):
        return call, ToolResponse(canonical_json(result), None, None, result.reason_codes)
    if not isinstance(result, StatisticalResult) or len(result.estimates) != 1:
        raise ValueError("unsupported engine response")
    estimate = result.estimates[0]
    if not isinstance(estimate.unit, UnitReference):
        raise ValueError("unsupported derived output unit")
    return call, ToolResponse(
        canonical_json(result), estimate.value, estimate.unit, (), authorization_json
    )


def construct_example(seed: int, index: int) -> ScientificExample:
    task = make_task(seed, index)
    call, response = _execute(task)
    intent = {
        "objective": task.objective,
        "requested_analysis_class": task.requested_analysis_class,
        "selected_operation": call.operation_id if call else None,
    }
    user = task.question + "\n" + canonical_json(task)
    messages: list[dict[str, object]] = [{"role": "user", "content": user}]
    if call:
        messages.append(
            {
                "role": "assistant",
                "content": json.dumps(intent, sort_keys=True),
                "tool_calls": [
                    {
                        "id": "science-1",
                        "type": "function",
                        "function": {
                            "name": "registered_science",
                            "arguments": canonical_json(
                                {
                                    "operation_id": call.operation_id,
                                    "authority_reference": call.authority_reference,
                                    "input_sha256": canonical_hash((task, call)),
                                    "scalar": call.scalar,
                                    "support_sha256": canonical_hash(call.support)
                                    if call.support
                                    else None,
                                    "analysis_request_sha256": canonical_hash(call.analysis_request)
                                    if call.analysis_request
                                    else None,
                                }
                            ),
                        },
                    }
                ],
            }
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": "science-1",
                "name": "registered_science",
                "content": canonical_json(
                    {
                        "result_sha256": canonical_hash(response),
                        "value": response.value,
                        "unit": response.unit,
                        "refusal_codes": response.refusal_codes,
                    }
                ),
            }
        )
    final = (
        "Refused: "
        + ", ".join(response.refusal_codes)
        + ". Requested objective retained: "
        + task.objective
        if response.refusal_codes
        else f"Registered descriptive result: {response.value!r} "
        f"{response.unit.display_label if response.unit else ''}."
    )
    final += (
        " Synthetic evidence only. No causal, normative, readiness or injury-risk conclusion."
        " Uncertainty is not established; descriptive SD is not reliability error."
    )
    messages.append({"role": "assistant", "content": final})
    registry, implementation = authority_identity()
    payload = (
        SCHEMA,
        task,
        call,
        response,
        canonical_hash((task, call)),
        canonical_hash(response),
        registry,
        implementation,
        json.dumps(messages, sort_keys=True, ensure_ascii=False, separators=(",", ":")),
    )
    return ScientificExample(*payload, canonical_hash(payload))


def validate_example(example: ScientificExample) -> None:
    if not isinstance(example, ScientificExample) or not isinstance(example.task, ScientificTask):
        raise ValueError("typed scientific example required")
    task = example.task
    if (
        not isinstance(task.category, Category)
        or not isinstance(task.input_unit, UnitReference)
        or not isinstance(task.measurement_units, tuple)
        or any(not isinstance(unit, UnitReference) for unit in task.measurement_units)
        or (
            task.requested_analysis_class is not None
            and not isinstance(task.requested_analysis_class, AnalysisClass)
        )
        or not isinstance(task.values, tuple)
        or any(type(v) is not float for v in task.values)
        or not isinstance(example.response, ToolResponse)
        or (
            example.response.unit is not None
            and not isinstance(example.response.unit, UnitReference)
        )
    ):
        raise ValueError("typed scientific task and response required")
    call = example.call
    if call is not None and (
        not isinstance(call, ToolCall)
        or (call.support is not None and not isinstance(call.support, StatisticalSupport))
        or (call.scalar is not None and not isinstance(call.scalar, ScalarArguments))
        or (
            call.analysis_request is not None
            and not isinstance(call.analysis_request, AnalysisAuthorizationRequest)
        )
    ):
        raise ValueError("typed registered tool arguments required")
    expected = construct_example(example.task.seed, example.task.index)
    if canonical_bytes(example) != canonical_bytes(expected):
        raise ValueError(
            "scientific task, operation, provenance, response or conversation failed replay"
        )


def generate_development_set(seed: int = 402) -> DevelopmentSet:
    examples = tuple(
        sorted((construct_example(seed, i) for i in range(39)), key=lambda x: x.example_sha256)
    )
    return DevelopmentSet(SCHEMA, seed, "BATCH_LOCAL_ONLY", examples)


def validate_development_set(dataset: DevelopmentSet) -> None:
    if dataset.schema != SCHEMA or dataset.qualification_scope != "BATCH_LOCAL_ONLY":
        raise ValueError("development scope/schema required")
    if len(dataset.examples) != 39 or len({e.example_sha256 for e in dataset.examples}) != 39:
        raise ValueError("duplicate or incomplete development examples")
    if tuple(e.example_sha256 for e in dataset.examples) != tuple(
        sorted(e.example_sha256 for e in dataset.examples)
    ):
        raise ValueError("noncanonical example ordering")
    if {e.task.index for e in dataset.examples} != set(range(39)):
        raise ValueError("conflicting example lineage")
    for example in dataset.examples:
        if example.task.seed != dataset.seed:
            raise ValueError("conflicting seed provenance")
        validate_example(example)
