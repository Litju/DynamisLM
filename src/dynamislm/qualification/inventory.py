# ruff: noqa: E501

"""RES-71 operation inventory and V2 coverage matrix.

The inventory is deliberately checked against the live package registry.  A
new ``registered-operation`` reference therefore fails qualification until it
has an explicit contract entry here.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import dynamislm
from dynamislm.measurement.identity import RegistryReference
from dynamislm.qualification.contracts import (
    CoverageRow,
    CoverageStatus,
    GateComponentStatus,
    OperationDisposition,
    RegisteredOperationInventoryEntry,
    UnresolvedComputation,
)
from dynamislm.refusal.models import RefusalResult

RES71_REGISTRY_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class _OperationMetadata:
    key: str
    version: str
    family: str
    disposition: OperationDisposition
    implementation: tuple[str, ...]
    input_contract: str
    output_contract: str
    provenance_contract: str
    refusal_path: tuple[str, ...]
    test_coverage: tuple[str, ...]
    authority_references: tuple[str, ...]
    tolerance_contract: str
    reason: str = ""
    safe_description: str = ""
    expected_refusal_class: str = "COMPUTATION_NOT_REGISTERED"
    expected_reason_codes: tuple[str, ...] = ("NO_REGISTERED_OPERATION",)

    @property
    def lookup_key(self) -> str:
        return f"{self.key}@{self.version}"


def _operation_id(key: str, version: str = "1.0.0") -> str:
    return f"dynamislm:registered-operation:{key}@{version}"


_INPUT_CONTRACTS = {
    "population": "Typed PopulationIdentity or CanonicalSource with V2 population/source clauses; no free-text eligibility override.",
    "football": "Typed FootballSession and explicit target MatchSession plus an IANA timezone when a relative label is requested.",
    "ingestion": "Qualified source manifest, immutable artifact identity, schema/mapping version and canonical-record evidence.",
    "external-load": "Finite values with registered UnitReference, or timestamped velocity samples with resolved threshold and method identity.",
    "cmj": "Typed CMJ force/event/phase/mechanics inputs with registered source artifact, timebase, estimator and support boundaries.",
    "strength": "Typed IMTP force series/onset or VBT velocity evidence with explicit phase, load, device and trial-selection identity.",
    "field-testing": "Typed source-qualified sprint/505/RSA/IFT observations or exact velocity-series support; no bare label arithmetic.",
    "explosive-tests": "Typed DJ/BPT/MBT source evidence, event/coordinate support, protocol and qualification identity.",
    "longitudinal-statistics": "RES-62-backed StatisticalSupport with exact observation identities, scale semantics, design and missingness policy.",
    "comparability": "Typed observations plus claim-relative identity/context references and canonical RES-70 authority; caller verdicts are not inputs.",
    "analysis": "Typed AnalysisAuthorizationRequest with exact support, level, comparability and evidence prerequisites.",
    "claims": "Typed ClaimIntent with exact observations and validated upstream analysis/comparability/evidence authority.",
}

_OUTPUT_CONTRACTS = {
    "population": "Typed population/source decision with status, clause-level reasons, method/version and refusal class when unresolved.",
    "football": "Immutable MatchDayRelativeLabel retaining target-match/session/context references and registered derivation identity.",
    "ingestion": "Typed canonical record, manifest, analysis input, or promotion decision with replayable artifact lineage.",
    "external-load": "Typed scalar/threshold result or RefusalResult; output identity names operation, units, threshold and aggregation semantics.",
    "cmj": "Typed ScientificMeasurementObservation/result with estimator or mechanics identity, units, quality and refusal-safe output.",
    "strength": "Typed ScientificMeasurementObservation/result or model/aggregation result with value origin, method and source lineage.",
    "field-testing": "Typed field-testing observation/result with protocol, timing/support, source qualification and refusal state.",
    "explosive-tests": "Typed family-specific metric result or provider observation; generic/unqualified power remains a refusal.",
    "longitudinal-statistics": "Typed StatisticalResult/StatisticalNonComputable with estimand, support, uncertainty/design and provenance.",
    "comparability": "Canonical ComparabilityResult/BridgeExecutionResult with state, dimension findings, conditions and authority hashes.",
    "analysis": "AnalysisAuthorization or RefusalResult with operation reference, support hashes, estimand level and claim floor.",
    "claims": "ClaimAuthorityResult with allowed levels, blocked claims, refusal reasons and exact upstream authority references.",
}

_PROVENANCE_CONTRACTS = {
    "population": "Decision references preserve source-evidence bindings, registry version and clause-level applicability; ambiguity is not relabelled.",
    "football": "Derivation preserves session, target match, athlete/team/season context and calendar-time inputs.",
    "ingestion": "Source bytes, acquisition, qualification/mapping version, canonical artifact and replay digest remain linked and immutable.",
    "external-load": "Source artifact/acquisition, provider/device/modality, processing/threshold/aggregation identity and output run are retained.",
    "cmj": "Source observation/artifact, acquisition/timebase, event/phase/mechanics dependencies, processing run and output identity are retained.",
    "strength": "Force/velocity source series, phase/onset/load/trial support, processing run and method parameters remain recoverable.",
    "field-testing": "Source artifact, timing/velocity support, protocol, qualification evidence, context and derived processing run are retained.",
    "explosive-tests": "Source artifact/series, protocol/event/coordinate evidence, qualification, method support and output run remain linked.",
    "longitudinal-statistics": "All source observation IDs, support ordering, analysis/design authority, window and calculation-changing parameters are retained.",
    "comparability": "Exact observation hashes, request hash, canonical rule/bridge registry hash and source applicability are validated.",
    "analysis": "Support/observation hashes, capability registry hash, requested level, prerequisites and evidence applicability are bound.",
    "claims": "Claim intent, exact observations and validated analysis/comparability/evidence/decision prerequisites are rechecked at authorization.",
}

_TESTS = {
    "population": ("tests/test_population.py", "tests/test_ingestion.py"),
    "football": ("tests/test_football.py",),
    "ingestion": ("tests/test_ingestion.py", "tests/test_res63_operational_authority.py"),
    "external-load": ("tests/test_external_load.py",),
    "cmj": (
        "tests/test_cmj.py",
        "tests/test_cmj_jump_height.py",
        "tests/test_cmj_metrics.py",
        "tests/test_cmj_phases.py",
        "tests/test_cmj_session.py",
    ),
    "strength": ("tests/test_strength.py",),
    "field-testing": ("tests/test_field_testing.py",),
    "explosive-tests": ("tests/test_explosive_test_families.py",),
    "longitudinal-statistics": (
        "tests/test_longitudinal.py",
        "tests/test_longitudinal_statistics.py",
    ),
    "comparability": (
        "tests/test_res70_comparability.py",
        "tests/test_res70_bridges.py",
        "tests/test_res70_adversarial.py",
    ),
    "analysis": ("tests/test_res70_analysis_capability.py", "tests/test_res70_models.py"),
    "claims": ("tests/test_res70_claim_authority.py", "tests/test_res70_evidence_and_levels.py"),
}

_AUTHORITY = {
    "population": ("docs/architecture/SCIENTIFIC_CONSTITUTION_V2.md", "RES-60"),
    "football": ("docs/decisions/RES61-DR-001-football-world-ontology.md", "RES-61"),
    "ingestion": ("docs/decisions/RES63-DR-001-canonical-dataset-ingestion.md", "RES-63"),
    "external-load": ("docs/decisions/RES64-DR-001-external-load-scientific-identity.md", "RES-64"),
    "cmj": ("docs/decisions/RES65-DR-001-cmj-football-metric-completion.md", "RES-65"),
    "strength": ("docs/decisions/RES66-DR-001-strength-imtp-vbt-scientific-engine.md", "RES-66"),
    "field-testing": ("docs/decisions/RES67-DR-001-field-testing-scientific-engine.md", "RES-67"),
    "explosive-tests": ("docs/decisions/RES68-DR-001-explosive-test-family-closure.md", "RES-68"),
    "longitudinal-statistics": (
        "docs/decisions/RES69-DR-001-longitudinal-reliability-uncertainty.md",
        "RES-69",
    ),
    "comparability": (
        "docs/decisions/RES70-DR-001-cross-source-comparability-analysis-claim-authority.md",
        "RES-70",
    ),
    "analysis": (
        "docs/decisions/RES70-DR-001-cross-source-comparability-analysis-claim-authority.md",
        "RES-70",
    ),
    "claims": (
        "docs/decisions/RES70-DR-001-cross-source-comparability-analysis-claim-authority.md",
        "RES-70",
    ),
}


def _add(
    metadata: dict[str, _OperationMetadata],
    keys: tuple[str, ...],
    *,
    family: str,
    implementation: tuple[str, ...] = (),
    disposition: OperationDisposition = OperationDisposition.IMPLEMENTED,
    versions: dict[str, str] | None = None,
    refusal_path: tuple[str, ...] = ("dynamislm.refusal.models:RefusalResult",),
    reason: str = "",
    safe_description: str = "",
    tolerance_contract: str = "Finite deterministic output; compare canonical serialized values with the operation-specific tolerance stated by its method contract.",
    expected_refusal_class: str = "COMPUTATION_NOT_REGISTERED",
    expected_reason_codes: tuple[str, ...] = ("NO_REGISTERED_OPERATION",),
) -> None:
    if versions is None:
        versions = {}
    for key in keys:
        version = versions.get(key, "1.0.0")
        lookup_key = f"{key}@{version}"
        if lookup_key in metadata:
            raise ValueError(f"duplicate RES-71 metadata entry: {lookup_key}")
        metadata[lookup_key] = _OperationMetadata(
            key=key,
            version=version,
            family=family,
            disposition=disposition,
            implementation=implementation,
            input_contract=_INPUT_CONTRACTS[family],
            output_contract=_OUTPUT_CONTRACTS[family],
            provenance_contract=_PROVENANCE_CONTRACTS[family],
            refusal_path=refusal_path,
            test_coverage=_TESTS[family],
            authority_references=_AUTHORITY[family],
            tolerance_contract=tolerance_contract,
            reason=reason,
            safe_description=safe_description,
            expected_refusal_class=expected_refusal_class,
            expected_reason_codes=expected_reason_codes,
        )


def _metadata() -> dict[str, _OperationMetadata]:
    """Return the manually reviewed operation-to-contract map."""

    metadata: dict[str, _OperationMetadata] = {}
    _add(
        metadata,
        (
            "canonical-empirical-source-qualification",
            "canonical-football-population-qualification",
        ),
        family="population",
        implementation=("dynamislm.population.qualification:qualify_canonical_population",),
    )
    # The two population operations share the family contract but have distinct callables.
    source_meta = metadata["canonical-empirical-source-qualification@1.0.0"]
    metadata["canonical-empirical-source-qualification@1.0.0"] = _OperationMetadata(
        key=source_meta.key,
        version=source_meta.version,
        family=source_meta.family,
        disposition=source_meta.disposition,
        implementation=("dynamislm.population.qualification:qualify_canonical_source",),
        input_contract=source_meta.input_contract,
        output_contract=source_meta.output_contract,
        provenance_contract=source_meta.provenance_contract,
        refusal_path=source_meta.refusal_path,
        test_coverage=source_meta.test_coverage,
        authority_references=source_meta.authority_references,
        tolerance_contract=source_meta.tolerance_contract,
        expected_refusal_class=source_meta.expected_refusal_class,
        expected_reason_codes=source_meta.expected_reason_codes,
    )
    _add(
        metadata,
        ("match-day-relative-label",),
        family="football",
        implementation=("dynamislm.football.context:derive_match_day_relative_label",),
    )
    _add(
        metadata,
        ("unit-normalization",),
        family="external-load",
        implementation=("dynamislm.external_load.metrics:convert_external_load_value",),
    )
    _add(
        metadata,
        ("duration-normalized-distance",),
        family="external-load",
        implementation=("dynamislm.external_load.metrics:duration_normalized_distance",),
    )
    _add(
        metadata,
        ("velocity-threshold-summary",),
        family="external-load",
        implementation=("dynamislm.external_load.metrics:summarize_velocity_threshold",),
    )
    _add(
        metadata,
        (
            "cmj-bilateral-total-vertical-force-sum-v1",
            "cmj-net-vertical-force-from-total-force-and-system-weight-v1",
            "cmj-net-vertical-impulse-v1",
            "cmj-supported-system-com-vertical-acceleration-v1",
            "cmj-supported-system-com-vertical-velocity-v1",
            "cmj-supported-system-com-relative-vertical-displacement-v1",
            "cmj-physical-system-mass-from-weight-v1",
            "cmj-standard-gravity-mass-equivalent-from-weight-v1",
            "cmj-system-weight-v1",
        ),
        family="cmj",
        implementation=("dynamislm.measurement.cmj:validated-family-operation",),
    )
    cmj_overrides = {
        "cmj-bilateral-total-vertical-force-sum-v1": "dynamislm.measurement.cmj.weighing:construct_total_supported_vertical_force",
        "cmj-net-vertical-force-from-total-force-and-system-weight-v1": "dynamislm.measurement.cmj.mechanics:calculate_net_vertical_force",
        "cmj-net-vertical-impulse-v1": "dynamislm.measurement.cmj.mechanics:integrate_net_vertical_impulse",
        "cmj-supported-system-com-vertical-acceleration-v1": "dynamislm.measurement.cmj.mechanics:derive_supported_system_com_acceleration",
        "cmj-supported-system-com-vertical-velocity-v1": "dynamislm.measurement.cmj.mechanics:integrate_supported_system_com_velocity",
        "cmj-supported-system-com-relative-vertical-displacement-v1": "dynamislm.measurement.cmj.mechanics:integrate_supported_system_com_relative_vertical_displacement",
        "cmj-physical-system-mass-from-weight-v1": "dynamislm.measurement.cmj.weighing:derive_physical_system_mass",
        "cmj-standard-gravity-mass-equivalent-from-weight-v1": "dynamislm.measurement.cmj.weighing:derive_standard_gravity_mass_equivalent",
        "cmj-system-weight-v1": "dynamislm.measurement.cmj.weighing:estimate_system_weight",
    }
    for key, implementation in cmj_overrides.items():
        old = metadata[f"{key}@1.0.0"]
        metadata[f"{key}@1.0.0"] = _replace_implementation(old, implementation)
    _add(
        metadata,
        ("cmj-flight-time-ballistic-jump-height-v1",),
        family="cmj",
        disposition=OperationDisposition.HISTORICAL_REPLAY_ONLY,
        versions={"cmj-flight-time-ballistic-jump-height-v1": "1.0.0"},
        implementation=(
            "dynamislm.measurement.cmj.jump_height:CMJ_FLIGHT_TIME_JUMP_HEIGHT_METHOD_V1",
        ),
        refusal_path=("dynamislm.measurement.cmj.jump_height:CMJJumpHeightResult",),
        reason="Retained for historical Serialization V3 replay; new flight-time computation uses the distinct V2 method.",
        safe_description="Historical V1 results may be decoded and compared by identity; V1 is not minted as the current method.",
    )
    _add(
        metadata,
        ("cmj-flight-time-ballistic-jump-height-v2",),
        family="cmj",
        versions={"cmj-flight-time-ballistic-jump-height-v2": "2.0.0"},
        implementation=("dynamislm.measurement.cmj.jump_height:estimate_flight_time_jump_height",),
    )
    _add(
        metadata,
        ("cmj-left-right-force-asymmetry-right-minus-left-over-left-v1",),
        family="cmj",
        implementation=("dynamislm.measurement.cmj.metrics:calculate_cmj_force_asymmetry",),
    )
    _add(
        metadata,
        ("cmj-phase-duration-v1",),
        family="cmj",
        implementation=("dynamislm.measurement.cmj.phases:calculate_cmj_phase_duration",),
    )
    _add(
        metadata,
        ("cmj-phase-net-vertical-impulse-v1",),
        family="cmj",
        implementation=(
            "dynamislm.measurement.cmj.phases:calculate_cmj_phase_net_vertical_impulse",
        ),
    )
    _add(
        metadata,
        ("cmj-phase-relative-displacement-change-v1",),
        family="cmj",
        implementation=(
            "dynamislm.measurement.cmj.phases:calculate_cmj_phase_relative_displacement_change",
        ),
    )
    _add(
        metadata,
        (
            "cmj-qualified-takeoff-velocity-ballistic-apex-rise-v1",
            "cmj-rsi-modified-flight-time-jump-height-over-time-to-takeoff-v1",
            "cmj-rsi-modified-takeoff-velocity-jump-height-over-time-to-takeoff-v1",
            "cmj-takeoff-velocity-scalar-projection-v1",
        ),
        family="cmj",
        implementation=("dynamislm.measurement.cmj:validated-family-operation",),
    )
    cmj_metric_overrides = {
        "cmj-qualified-takeoff-velocity-ballistic-apex-rise-v1": "dynamislm.measurement.cmj.jump_height:estimate_takeoff_velocity_jump_height",
        "cmj-rsi-modified-flight-time-jump-height-over-time-to-takeoff-v1": "dynamislm.measurement.cmj.metrics:calculate_cmj_rsi_mod",
        "cmj-rsi-modified-takeoff-velocity-jump-height-over-time-to-takeoff-v1": "dynamislm.measurement.cmj.metrics:calculate_cmj_rsi_mod",
        "cmj-takeoff-velocity-scalar-projection-v1": "dynamislm.measurement.cmj.metrics:calculate_cmj_takeoff_velocity",
    }
    for key, implementation in cmj_metric_overrides.items():
        old = metadata[f"{key}@1.0.0"]
        metadata[f"{key}@1.0.0"] = _replace_implementation(old, implementation)
    _add(
        metadata,
        (
            "cmj-sample-peak-total-supported-vertical-force-v1",
            "cmj-time-weighted-mean-total-supported-vertical-force-v1",
        ),
        family="cmj",
        implementation=("dynamislm.measurement.cmj.metrics:calculate_cmj_force_metric",),
    )
    _add(
        metadata,
        (
            "cmj-sampled-signed-power-extremum-v1",
            "cmj-time-weighted-signed-power-mean-v1",
            "cmj-total-supported-force-times-supported-system-com-velocity-v1",
        ),
        family="cmj",
        implementation=("dynamislm.measurement.cmj.metrics:calculate_cmj_power",),
    )
    _add(
        metadata,
        ("cmj-session-selection-aggregation-v1",),
        family="cmj",
        implementation=("dynamislm.measurement.cmj.session:aggregate_cmj_session",),
    )
    _add(
        metadata,
        (
            "drop-jump-flight-time-jump-height-v1",
            "drop-jump-ground-contact-time-v1",
            "drop-jump-rebound-flight-time-v1",
            "drop-jump-rsi-jh-ct-v1",
            "drop-jump-rsr-ft-ct-v1",
        ),
        family="explosive-tests",
        implementation=("dynamislm.measurement.drop_jump:validated-family-operation",),
    )
    dj_overrides = {
        "drop-jump-flight-time-jump-height-v1": "dynamislm.measurement.drop_jump.metrics:calculate_drop_jump_flight_time_jump_height",
        "drop-jump-ground-contact-time-v1": "dynamislm.measurement.drop_jump.metrics:calculate_drop_jump_contact_time",
        "drop-jump-rebound-flight-time-v1": "dynamislm.measurement.drop_jump.metrics:calculate_drop_jump_rebound_flight_time",
        "drop-jump-rsi-jh-ct-v1": "dynamislm.measurement.drop_jump.metrics:calculate_drop_jump_rsi_jh_ct",
        "drop-jump-rsr-ft-ct-v1": "dynamislm.measurement.drop_jump.metrics:calculate_drop_jump_rsr_ft_ct",
    }
    for key, implementation in dj_overrides.items():
        old = metadata[f"{key}@1.0.0"]
        metadata[f"{key}@1.0.0"] = _replace_implementation(old, implementation)
    _add(
        metadata,
        ("bench-press-throw-dynamislm-time-weighted-mean-bar-velocity-v1",),
        family="explosive-tests",
        implementation=(
            "dynamislm.measurement.bench_press_throw.metrics:calculate_bpt_dynamislm_time_weighted_mean_bar_velocity",
        ),
    )
    _add(
        metadata,
        ("bench-press-throw-sampled-maximum-bar-velocity-v1",),
        family="explosive-tests",
        implementation=(
            "dynamislm.measurement.bench_press_throw.metrics:calculate_bpt_sampled_maximum_bar_velocity",
        ),
    )
    _add(
        metadata,
        ("bench-press-throw-mean-propulsive-velocity-v1",),
        family="explosive-tests",
        disposition=OperationDisposition.REPRESENT_BUT_DO_NOT_COMPUTE,
        refusal_path=(
            "dynamislm.measurement.bench_press_throw.metrics:calculate_bpt_mean_propulsive_velocity",
        ),
        reason="Metric support and acceleration/gravity boundary are not registered for generic BPT MPV computation.",
        safe_description="Provider-reported or represented MPV remains origin-qualified; no DynamisLM MPV number is emitted.",
        expected_reason_codes=("NO_REGISTERED_OPERATION", "COMPUTATION_NOT_REGISTERED"),
    )
    _add(
        metadata,
        (
            "medicine-ball-throw-distance-from-registered-coordinates-v1",
            "medicine-ball-throw-instrumented-release-velocity-v1",
        ),
        family="explosive-tests",
        implementation=("dynamislm.measurement.medicine_ball_throw:validated-family-operation",),
    )
    mbt_overrides = {
        "medicine-ball-throw-distance-from-registered-coordinates-v1": "dynamislm.measurement.medicine_ball_throw.metrics:calculate_mbt_throw_distance",
        "medicine-ball-throw-instrumented-release-velocity-v1": "dynamislm.measurement.medicine_ball_throw.metrics:calculate_mbt_instrumented_release_velocity",
    }
    for key, implementation in mbt_overrides.items():
        old = metadata[f"{key}@1.0.0"]
        metadata[f"{key}@1.0.0"] = _replace_implementation(old, implementation)
    _add(
        metadata,
        (
            "imtp-baseline-force-statistics-v1",
            "imtp-endpoint-average-rfd-v1",
            "imtp-force-at-registered-time-v1",
            "imtp-force-body-mass-normalization-v1",
            "imtp-force-impulse-v1",
            "imtp-sampled-peak-force-v1",
            "imtp-trial-selection-aggregation-v1",
        ),
        family="strength",
        implementation=("dynamislm.measurement.strength.imtp:calculate_imtp_metric",),
    )
    imtp_overrides = {
        "imtp-baseline-force-statistics-v1": "dynamislm.measurement.strength.imtp:build_imtp_baseline",
        "imtp-endpoint-average-rfd-v1": "dynamislm.measurement.strength.imtp:calculate_imtp_rfd",
        "imtp-force-at-registered-time-v1": "dynamislm.measurement.strength.imtp:calculate_imtp_force_at_time",
        "imtp-force-body-mass-normalization-v1": "dynamislm.measurement.strength.imtp:normalize_imtp_force",
        "imtp-force-impulse-v1": "dynamislm.measurement.strength.imtp:calculate_imtp_impulse",
        "imtp-sampled-peak-force-v1": "dynamislm.measurement.strength.imtp:calculate_imtp_peak_force",
        "imtp-trial-selection-aggregation-v1": "dynamislm.measurement.strength.imtp:aggregate_imtp_metric_results",
    }
    for key, implementation in imtp_overrides.items():
        old = metadata[f"{key}@1.0.0"]
        metadata[f"{key}@1.0.0"] = _replace_implementation(old, implementation)
    _add(
        metadata,
        ("direct-one-repetition-maximum-assessment-v1", "measured-one-repetition-maximum-v1"),
        family="strength",
        implementation=("dynamislm.measurement.strength.vbt:create_measured_1rm",),
    )
    _add(
        metadata,
        ("estimated-one-repetition-maximum-from-linear-load-velocity-v1",),
        family="strength",
        disposition=OperationDisposition.DEFERRED,
        refusal_path=("dynamislm.measurement.strength.vbt:estimate_1rm_from_load_velocity_model",),
        reason="Current evidence does not authorize terminal-velocity applicability across devices/calibration designs.",
        safe_description="The individual load-velocity model remains describable; no numeric estimated 1RM is emitted.",
        expected_reason_codes=(
            "UNKNOWN_THRESHOLD",
            "UNKNOWN_THRESHOLD_BASIS",
            "DEVICE_BRIDGE_NOT_REGISTERED",
            "NO_REGISTERED_OPERATION",
        ),
    )
    _add(
        metadata,
        ("mean-concentric-velocity-v1",),
        family="strength",
        implementation=(
            "dynamislm.measurement.strength.vbt:calculate_vbt_mean_concentric_velocity",
        ),
    )
    _add(
        metadata,
        ("mean-propulsive-velocity-v1",),
        family="strength",
        disposition=OperationDisposition.REPRESENT_BUT_DO_NOT_COMPUTE,
        refusal_path=("dynamislm.measurement.strength.vbt:calculate_vbt_mean_propulsive_velocity",),
        reason="Acceleration, gravity, filtering, sampling and propulsive-boundary authority are not frozen.",
        safe_description="Concentric velocity is not relabelled as mean propulsive velocity.",
        expected_reason_codes=("NO_REGISTERED_OPERATION",),
    )
    _add(
        metadata,
        ("sampled-peak-concentric-velocity-v1",),
        family="strength",
        implementation=("dynamislm.measurement.strength.vbt:calculate_vbt_peak_velocity",),
    )
    _add(
        metadata,
        ("within-set-velocity-loss-v1",),
        family="strength",
        implementation=("dynamislm.measurement.strength.vbt:calculate_vbt_velocity_loss",),
    )
    _add(
        metadata,
        ("505-asymmetry-v1",),
        family="field-testing",
        disposition=OperationDisposition.REPRESENT_BUT_DO_NOT_COMPUTE,
        refusal_path=("dynamislm.measurement.field_testing.cod:refuse_505_asymmetry",),
        reason="No single denominator, direction and sign convention is registered for 505 asymmetry.",
        safe_description="Left and right 505 results remain separate observations.",
        expected_reason_codes=("NO_REGISTERED_OPERATION", "METRIC_DEFINITION_MISMATCH"),
    )
    _add(
        metadata,
        (
            "505-cod-deficit-mean-505-minus-mean-10m-v1",
            "standard-505-mean-of-three-v1",
        ),
        family="field-testing",
        implementation=("dynamislm.measurement.field_testing.cod:aggregate_standard_505_trials",),
    )
    _add(
        metadata,
        ("30-15-ift-last-completed-stage-v1",),
        family="field-testing",
        implementation=("dynamislm.measurement.field_testing.ift:calculate_vift",),
    )
    _add(
        metadata,
        (
            "linear-sprint-mean-0-10m-reference-v1",
            "sprint-interval-split-v1",
            "sprint-segment-average-velocity-v1",
            "sampled-maximum-sprint-velocity-v1",
        ),
        family="field-testing",
        implementation=("dynamislm.measurement.field_testing.sprint:validated-family-operation",),
    )
    sprint_overrides = {
        "linear-sprint-mean-0-10m-reference-v1": "dynamislm.measurement.field_testing.sprint:aggregate_linear_sprint_30m_reference",
        "sprint-interval-split-v1": "dynamislm.measurement.field_testing.sprint:derive_interval_split",
        "sprint-segment-average-velocity-v1": "dynamislm.measurement.field_testing.sprint:derive_segment_average_velocity",
        "sampled-maximum-sprint-velocity-v1": "dynamislm.measurement.field_testing.sprint:sampled_maximum_velocity",
    }
    for key, implementation in sprint_overrides.items():
        old = metadata[f"{key}@1.0.0"]
        metadata[f"{key}@1.0.0"] = _replace_implementation(old, implementation)
    _add(
        metadata,
        ("sustained-maximum-sprint-velocity-v1",),
        family="field-testing",
        disposition=OperationDisposition.DEFERRED,
        refusal_path=(
            "dynamislm.measurement.field_testing.sprint:refuse_sampled_maximum_as_sustained_maximum",
        ),
        reason="A dwell/sustain estimator and evidence are not registered; V1 is sampled maximum only.",
        safe_description="Sampled maximum velocity remains separately describable and is not relabelled as sustained maximum.",
        expected_reason_codes=("ESTIMATOR_MISMATCH", "NO_REGISTERED_OPERATION"),
    )
    _add(
        metadata,
        (
            "rsa-best-time-v1",
            "rsa-complete-series-aggregation-v1",
            "rsa-mean-time-v1",
            "rsa-percent-decrement-s-dec-v1",
            "rsa-total-time-v1",
        ),
        family="field-testing",
        implementation=("dynamislm.measurement.field_testing.rsa:aggregate_rsa",),
    )
    _add(
        metadata,
        (
            "longitudinal-absolute-change-v1",
            "longitudinal-log-ratio-v1",
            "longitudinal-reference-window-deviation-v1",
            "longitudinal-relative-change-v1",
            "longitudinal-window-descriptives-v1",
            "longitudinal-within-athlete-sample-sd-v1",
        ),
        family="longitudinal-statistics",
        implementation=("dynamislm.longitudinal.statistics:validated-family-operation",),
    )
    stats_overrides = {
        "longitudinal-absolute-change-v1": "dynamislm.longitudinal.statistics.descriptive:calculate_absolute_change",
        "longitudinal-log-ratio-v1": "dynamislm.longitudinal.statistics.descriptive:calculate_log_ratio_change",
        "longitudinal-reference-window-deviation-v1": "dynamislm.longitudinal.statistics.descriptive:calculate_reference_window_deviation",
        "longitudinal-relative-change-v1": "dynamislm.longitudinal.statistics.descriptive:calculate_relative_change",
        "longitudinal-window-descriptives-v1": "dynamislm.longitudinal.statistics.descriptive:calculate_window_descriptives",
        "longitudinal-within-athlete-sample-sd-v1": "dynamislm.longitudinal.statistics.descriptive:calculate_descriptive_within_athlete_sd",
    }
    for key, implementation in stats_overrides.items():
        old = metadata[f"{key}@1.0.0"]
        metadata[f"{key}@1.0.0"] = _replace_implementation(old, implementation)
    _add(
        metadata,
        ("longitudinal-descriptive-ols-v1",),
        family="longitudinal-statistics",
        implementation=("dynamislm.longitudinal.statistics.descriptive:calculate_descriptive_ols",),
    )
    _add(
        metadata,
        (
            "two-replicate-log-multiplicative-error-v1",
            "two-replicate-pooled-raw-relative-error-v1",
            "two-replicate-within-subject-random-error-v1",
        ),
        family="longitudinal-statistics",
        implementation=(
            "dynamislm.longitudinal.statistics.reliability:validated-family-operation",
        ),
    )
    reliability_overrides = {
        "two-replicate-log-multiplicative-error-v1": "dynamislm.longitudinal.statistics.reliability:calculate_log_scale_typical_error",
        "two-replicate-pooled-raw-relative-error-v1": "dynamislm.longitudinal.statistics.reliability:calculate_raw_relative_error",
        "two-replicate-within-subject-random-error-v1": "dynamislm.longitudinal.statistics.reliability:calculate_two_replicate_random_error",
    }
    for key, implementation in reliability_overrides.items():
        old = metadata[f"{key}@1.0.0"]
        metadata[f"{key}@1.0.0"] = _replace_implementation(old, implementation)
    _add(
        metadata,
        ("method-comparison-ba-summary-v1",),
        family="longitudinal-statistics",
        implementation=(
            "dynamislm.longitudinal.statistics.agreement:calculate_bland_altman_summary",
        ),
    )
    _add(
        metadata,
        ("method-comparison-design-authority-v1",),
        family="longitudinal-statistics",
        implementation=(
            "dynamislm.longitudinal.statistics.agreement:build_method_comparison_design_authority",
        ),
    )
    _add(
        metadata,
        ("reliability-design-authority-v1",),
        family="longitudinal-statistics",
        implementation=(
            "dynamislm.longitudinal.statistics.reliability:build_reliability_design_authority",
        ),
    )
    _add(
        metadata,
        ("reliability-assumption-assessment-v1",),
        family="longitudinal-statistics",
        implementation=(
            "dynamislm.longitudinal.statistics.reliability:build_reliability_assumption_assessment",
        ),
    )
    _add(
        metadata,
        ("classical-bland-altman-limits-v1", "sem-from-registered-icc", "mdc-sdc", "icc-variants"),
        family="longitudinal-statistics",
        disposition=OperationDisposition.REPRESENT_BUT_DO_NOT_COMPUTE,
        refusal_path=(
            "dynamislm.longitudinal.statistics.reliability:refuse_unimplemented_reliability_operation",
        ),
        reason="The named reliability/agreement method is represented but lacks a registered V1 estimand/design implementation.",
        safe_description="The underlying observations and method label remain describable without placeholder arithmetic.",
        expected_reason_codes=("RES69_OPERATION_NOT_REGISTERED",),
    )
    _add(
        metadata,
        (
            "log-ba",
            "repeated-measures-ba",
            "confidence-intervals",
            "covariance-propagation",
            "repeated-measures-correlation",
            "mixed-effects",
        ),
        family="longitudinal-statistics",
        disposition=OperationDisposition.DEFERRED,
        refusal_path=(
            "dynamislm.longitudinal.statistics.reliability:refuse_unimplemented_reliability_operation",
        ),
        reason="The method remains outside the sealed V1 numerical surface until its estimand, design and uncertainty contract are registered.",
        safe_description="No numeric result is emitted; a later mission may register the method with explicit prerequisites.",
        expected_reason_codes=("RES69_OPERATION_NOT_REGISTERED",),
    )
    _add(
        metadata,
        ("generic-sem", "generic-meaningful-change", "readiness-fatigue-injury-interpretation"),
        family="longitudinal-statistics",
        disposition=OperationDisposition.REJECTED,
        refusal_path=(
            "dynamislm.longitudinal.statistics.reliability:refuse_unimplemented_reliability_operation",
        ),
        reason="The generic claim is outside current scientific authority and has no registered estimand or decision criterion.",
        safe_description="Observed values and registered descriptive/error results remain independently describable.",
        expected_reason_codes=("RES69_OPERATION_NOT_REGISTERED",),
    )
    _add(
        metadata,
        (
            "longitudinal-athlete-performance-record",
            "multi-source-analysis-input",
            "res62-multi-source-manifest",
        ),
        family="ingestion",
        implementation=("dynamislm.longitudinal.record:build_longitudinal_record",),
    )
    record_overrides = {
        "longitudinal-athlete-performance-record": "dynamislm.longitudinal.record:build_longitudinal_record",
        "multi-source-analysis-input": "dynamislm.longitudinal.record:build_multi_source_analysis_input",
        "res62-multi-source-manifest": "dynamislm.longitudinal.record:build_longitudinal_source_manifest",
    }
    for key, implementation in record_overrides.items():
        old = metadata[f"{key}@1.0.0"]
        metadata[f"{key}@1.0.0"] = _replace_implementation(old, implementation)
    _add(
        metadata,
        ("res70-registered-affine-transformation-v1",),
        family="comparability",
        implementation=("dynamislm.comparability.res70_authority:execute_registered_bridge",),
    )
    return metadata


def _replace_implementation(
    metadata: _OperationMetadata, implementation: str
) -> _OperationMetadata:
    return _OperationMetadata(
        key=metadata.key,
        version=metadata.version,
        family=metadata.family,
        disposition=metadata.disposition,
        implementation=(implementation,),
        input_contract=metadata.input_contract,
        output_contract=metadata.output_contract,
        provenance_contract=metadata.provenance_contract,
        refusal_path=metadata.refusal_path,
        test_coverage=metadata.test_coverage,
        authority_references=metadata.authority_references,
        tolerance_contract=metadata.tolerance_contract,
        reason=metadata.reason,
        safe_description=metadata.safe_description,
        expected_refusal_class=metadata.expected_refusal_class,
        expected_reason_codes=metadata.expected_reason_codes,
    )


def _discover_modules() -> tuple[ModuleType, ...]:
    modules = [dynamislm]
    for info in pkgutil.walk_packages(dynamislm.__path__, dynamislm.__name__ + "."):
        if info.name.startswith("dynamislm.qualification"):
            continue
        modules.append(importlib.import_module(info.name))
    return tuple(modules)


def _discover_references() -> dict[str, RegistryReference]:
    references: dict[str, RegistryReference] = {}
    for module in _discover_modules():
        for value in vars(module).values():
            if not isinstance(value, RegistryReference):
                continue
            if value.identifier.object_type != "registered-operation":
                continue
            references[value.stable_id] = value
    return references


def discovered_registered_operation_ids() -> tuple[str, ...]:
    """Return every registered-operation identity exposed by the package."""

    return tuple(sorted(_discover_references()))


def _metadata_for_id(
    operation_id: str, metadata: dict[str, _OperationMetadata]
) -> _OperationMetadata:
    prefix, version = operation_id.rsplit("@", 1)
    key = prefix.rsplit(":", 1)[1]
    try:
        return metadata[f"{key}@{version}"]
    except KeyError as exc:
        raise ValueError(f"RES-71 inventory missing registered operation: {operation_id}") from exc


def build_registered_operation_inventory() -> tuple[RegisteredOperationInventoryEntry, ...]:
    """Build the complete inventory and fail if the runtime registry grew unreviewed."""

    references = _discover_references()
    metadata = _metadata()
    entries = []
    for operation_id in sorted(references):
        reference = references[operation_id]
        item = _metadata_for_id(operation_id, metadata)
        if item.version != reference.identifier.version:
            raise ValueError(f"RES-71 method version mismatch: {operation_id}")
        entries.append(
            RegisteredOperationInventoryEntry(
                operation_id=operation_id,
                label=reference.display_label,
                method_version=reference.identifier.version,
                scientific_family=item.family,
                disposition=item.disposition,
                implementation=item.implementation,
                input_contract=item.input_contract,
                output_contract=item.output_contract,
                provenance_contract=item.provenance_contract,
                refusal_path=item.refusal_path,
                test_coverage=item.test_coverage,
                authority_references=item.authority_references,
                tolerance_contract=item.tolerance_contract,
            )
        )
    known = {item.lookup_key for item in metadata.values()}
    discovered = {
        f"{operation_id.rsplit(':', 1)[1].rsplit('@', 1)[0]}@{operation_id.rsplit('@', 1)[1]}"
        for operation_id in references
    }
    extra = known - discovered
    if extra:
        raise ValueError(f"RES-71 inventory contains stale operation metadata: {sorted(extra)}")
    return tuple(entries)


def _resolve_symbol(path: str) -> object:
    module_name, attribute_path = path.split(":", 1)
    value: object = importlib.import_module(module_name)
    for attribute in attribute_path.split("."):
        value = getattr(value, attribute)
    return value


def _resolve_route(path: str, *, kind: str, owner: str, require_callable: bool = True) -> object:
    try:
        value = _resolve_symbol(path)
    except (AttributeError, ImportError, ValueError) as exc:
        raise ValueError(f"RES-71 {kind} route is stale for {owner}: {path}") from exc
    if require_callable and not callable(value):
        raise ValueError(f"RES-71 {kind} route is not callable for {owner}: {path}")
    return value


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def validate_registered_operation_inventory(
    entries: tuple[RegisteredOperationInventoryEntry, ...] | None = None,
) -> GateComponentStatus:
    """Validate registry completeness, implementation bindings and test paths."""

    if entries is None:
        entries = build_registered_operation_inventory()
    operation_ids = tuple(item.operation_id for item in entries)
    if len(set(operation_ids)) != len(operation_ids):
        raise ValueError("RES-71 inventory contains duplicate operation IDs")
    if set(operation_ids) != set(discovered_registered_operation_ids()):
        raise ValueError("RES-71 inventory is not complete against the live registry")
    root = _repository_root()
    for item in entries:
        for path in item.implementation:
            _resolve_route(
                path, kind="implementation", owner=item.operation_id, require_callable=False
            )
        for path in item.refusal_path:
            _resolve_route(path, kind="refusal", owner=item.operation_id)
        for path in item.test_coverage:
            if not (root / path).is_file():
                raise ValueError(f"RES-71 operation test path is missing: {path}")
        if item.disposition is OperationDisposition.IMPLEMENTED and not item.implementation:
            raise ValueError(f"implemented operation has no implementation: {item.operation_id}")
        if item.disposition is not OperationDisposition.IMPLEMENTED and not item.refusal_path:
            raise ValueError(f"non-computing operation has no refusal path: {item.operation_id}")
    return GateComponentStatus.PASS


def _ids(
    entries: tuple[RegisteredOperationInventoryEntry, ...], keys: tuple[str, ...]
) -> tuple[str, ...]:
    by_key = {
        item.operation_id.rsplit(":", 1)[1].split("@", 1)[0]: item.operation_id for item in entries
    }
    return tuple(by_key[key] for key in keys)


def build_coverage_matrix() -> tuple[CoverageRow, ...]:
    """Return the required V2 domain coverage matrix."""

    entries = build_registered_operation_inventory()
    cmj_keys = (
        "cmj-bilateral-total-vertical-force-sum-v1",
        "cmj-flight-time-ballistic-jump-height-v1",
        "cmj-flight-time-ballistic-jump-height-v2",
        "cmj-left-right-force-asymmetry-right-minus-left-over-left-v1",
        "cmj-net-vertical-force-from-total-force-and-system-weight-v1",
        "cmj-net-vertical-impulse-v1",
        "cmj-phase-duration-v1",
        "cmj-phase-net-vertical-impulse-v1",
        "cmj-phase-relative-displacement-change-v1",
        "cmj-physical-system-mass-from-weight-v1",
        "cmj-qualified-takeoff-velocity-ballistic-apex-rise-v1",
        "cmj-rsi-modified-flight-time-jump-height-over-time-to-takeoff-v1",
        "cmj-rsi-modified-takeoff-velocity-jump-height-over-time-to-takeoff-v1",
        "cmj-sample-peak-total-supported-vertical-force-v1",
        "cmj-sampled-signed-power-extremum-v1",
        "cmj-session-selection-aggregation-v1",
        "cmj-standard-gravity-mass-equivalent-from-weight-v1",
        "cmj-supported-system-com-relative-vertical-displacement-v1",
        "cmj-supported-system-com-vertical-acceleration-v1",
        "cmj-supported-system-com-vertical-velocity-v1",
        "cmj-system-weight-v1",
        "cmj-takeoff-velocity-scalar-projection-v1",
        "cmj-time-weighted-mean-total-supported-vertical-force-v1",
        "cmj-time-weighted-signed-power-mean-v1",
        "cmj-total-supported-force-times-supported-system-com-velocity-v1",
    )
    strength_keys = (
        "direct-one-repetition-maximum-assessment-v1",
        "estimated-one-repetition-maximum-from-linear-load-velocity-v1",
        "imtp-baseline-force-statistics-v1",
        "imtp-endpoint-average-rfd-v1",
        "imtp-force-at-registered-time-v1",
        "imtp-force-body-mass-normalization-v1",
        "imtp-force-impulse-v1",
        "imtp-sampled-peak-force-v1",
        "imtp-trial-selection-aggregation-v1",
        "mean-concentric-velocity-v1",
        "mean-propulsive-velocity-v1",
        "measured-one-repetition-maximum-v1",
        "sampled-peak-concentric-velocity-v1",
        "within-set-velocity-loss-v1",
    )
    field_keys = (
        "30-15-ift-last-completed-stage-v1",
        "505-asymmetry-v1",
        "505-cod-deficit-mean-505-minus-mean-10m-v1",
        "linear-sprint-mean-0-10m-reference-v1",
        "rsa-best-time-v1",
        "rsa-complete-series-aggregation-v1",
        "rsa-mean-time-v1",
        "rsa-percent-decrement-s-dec-v1",
        "rsa-total-time-v1",
        "sampled-maximum-sprint-velocity-v1",
        "sprint-interval-split-v1",
        "sprint-segment-average-velocity-v1",
        "standard-505-mean-of-three-v1",
        "sustained-maximum-sprint-velocity-v1",
    )
    explosive_keys = (
        "drop-jump-flight-time-jump-height-v1",
        "drop-jump-ground-contact-time-v1",
        "drop-jump-rebound-flight-time-v1",
        "drop-jump-rsi-jh-ct-v1",
        "drop-jump-rsr-ft-ct-v1",
        "bench-press-throw-dynamislm-time-weighted-mean-bar-velocity-v1",
        "bench-press-throw-mean-propulsive-velocity-v1",
        "bench-press-throw-sampled-maximum-bar-velocity-v1",
        "medicine-ball-throw-distance-from-registered-coordinates-v1",
        "medicine-ball-throw-instrumented-release-velocity-v1",
    )
    stats_keys = (
        "classical-bland-altman-limits-v1",
        "confidence-intervals",
        "covariance-propagation",
        "generic-meaningful-change",
        "generic-sem",
        "icc-variants",
        "log-ba",
        "longitudinal-absolute-change-v1",
        "longitudinal-descriptive-ols-v1",
        "longitudinal-log-ratio-v1",
        "longitudinal-reference-window-deviation-v1",
        "longitudinal-relative-change-v1",
        "longitudinal-window-descriptives-v1",
        "longitudinal-within-athlete-sample-sd-v1",
        "mdc-sdc",
        "method-comparison-ba-summary-v1",
        "method-comparison-design-authority-v1",
        "mixed-effects",
        "readiness-fatigue-injury-interpretation",
        "reliability-assumption-assessment-v1",
        "reliability-design-authority-v1",
        "repeated-measures-ba",
        "repeated-measures-correlation",
        "sem-from-registered-icc",
        "two-replicate-log-multiplicative-error-v1",
        "two-replicate-pooled-raw-relative-error-v1",
        "two-replicate-within-subject-random-error-v1",
    )
    record_keys = (
        "longitudinal-athlete-performance-record",
        "multi-source-analysis-input",
        "res62-multi-source-manifest",
    )
    rows = (
        CoverageRow(
            "population/source authority",
            CoverageStatus.QUALIFIED,
            ("dynamislm.population", "dynamislm.ingestion.registry"),
            _ids(
                entries,
                (
                    "canonical-football-population-qualification",
                    "canonical-empirical-source-qualification",
                ),
            ),
            (),
            "Population clauses, evidence role, source license and subgroup separability remain typed and bound.",
            "Population applicability is not a measurement-method equivalence claim.",
            "Noncanonical or ambiguous populations are quarantined; indirect method evidence cannot mint target priors.",
            _TESTS["population"],
            _AUTHORITY["population"],
        ),
        CoverageRow(
            "football world/context",
            CoverageStatus.QUALIFIED,
            ("dynamislm.football", "dynamislm.longitudinal.record"),
            _ids(entries, ("match-day-relative-label", *record_keys)),
            ("nearest-match inference",),
            "Athlete/team/competition/season/session/match/microcycle context is explicit and source-referenced.",
            "Calendar relation and match/training exposure context are not inferred from labels alone.",
            "Context can bound applicability and grouping; it does not create a performance or causal claim.",
            _TESTS["football"] + _TESTS["longitudinal-statistics"],
            _AUTHORITY["football"],
        ),
        CoverageRow(
            "ingestion/qualification",
            CoverageStatus.QUALIFIED,
            ("dynamislm.ingestion.acquisition", "dynamislm.ingestion.promotion"),
            _ids(entries, record_keys),
            ("vendor-derived proprietary formula reconstruction",),
            "Raw bytes, source/version/license, schema, mapping, canonical artifact and replay digest are preserved.",
            "Unknown variable identity or source population remains quarantined/rejected deterministically.",
            "Promoted canonical rows do not broaden the V2 target or authorize model training.",
            _TESTS["ingestion"],
            _AUTHORITY["ingestion"],
        ),
        CoverageRow(
            "external load / GNSS / optical",
            CoverageStatus.QUALIFIED_WITH_EXPLICIT_DEFERRED,
            (
                "dynamislm.external_load.identity",
                "dynamislm.external_load.metrics",
                "dynamislm.external_load.mapping",
            ),
            _ids(
                entries,
                (
                    "unit-normalization",
                    "duration-normalized-distance",
                    "velocity-threshold-summary",
                ),
            ),
            ("hidden vendor algorithm recomputation", "unresolved threshold/sampling semantics"),
            "Provider/device/modality, threshold basis, sampling/processing, aggregation and source origin remain identity fields.",
            "Same-label GNSS/optical/vendor values require identity agreement or a registered bridge.",
            "Provider-derived output is an observation, not DynamisLM computational authority; no workload/fatigue claim.",
            _TESTS["external-load"],
            _AUTHORITY["external-load"],
        ),
        CoverageRow(
            "CMJ",
            CoverageStatus.QUALIFIED_WITH_EXPLICIT_DEFERRED,
            ("dynamislm.measurement.cmj",),
            _ids(entries, cmj_keys),
            ("CMJ RFD", "COM-displacement jump height"),
            "Force/event/phase/mechanics/jump-height outputs retain source signal, support, estimator and processing lineage.",
            "Estimator, event, phase, force-system and aggregation differences are claim-relative and fail closed.",
            "Derived CMJ performance metrics do not establish physiological mechanism, readiness or fatigue.",
            _TESTS["cmj"],
            _AUTHORITY["cmj"],
        ),
        CoverageRow(
            "strength / IMTP / VBT",
            CoverageStatus.QUALIFIED_WITH_EXPLICIT_DEFERRED,
            ("dynamislm.measurement.strength.imtp", "dynamislm.measurement.strength.vbt"),
            _ids(entries, strength_keys),
            ("VBT mean propulsive velocity", "terminal-velocity estimated 1RM applicability"),
            "Force/velocity source series, onset/phase, load, trial selection, method version and value origin are retained.",
            "Velocity metric, device, protocol, phase and fixed-load identity must agree or use a registered bridge.",
            "Velocity loss is mechanical within-set change; it is not fatigue/readiness by automatic relabelling.",
            _TESTS["strength"],
            _AUTHORITY["strength"],
        ),
        CoverageRow(
            "sprint / maximum velocity / COD / RSA / 30-15 IFT",
            CoverageStatus.QUALIFIED_WITH_EXPLICIT_DEFERRED,
            ("dynamislm.measurement.field_testing",),
            _ids(entries, field_keys),
            (
                "sprint acceleration",
                "sustained maximum velocity",
                "505 asymmetry",
                "VIFT-to-VO2max/MAS/MSS",
            ),
            "Timing/velocity support, protocol, source qualification, stage/repetition and context are preserved.",
            "Sampled maximum, segment-average velocity, 505 direction and RSA protocol identities remain distinct.",
            "RSA decrement is a mechanical performance statistic; it is not a fatigue diagnosis or prescription.",
            _TESTS["field-testing"],
            _AUTHORITY["field-testing"],
        ),
        CoverageRow(
            "DJ / bench throw / medicine-ball throw",
            CoverageStatus.QUALIFIED_WITH_EXPLICIT_DEFERRED,
            (
                "dynamislm.measurement.drop_jump",
                "dynamislm.measurement.bench_press_throw",
                "dynamislm.measurement.medicine_ball_throw",
            ),
            _ids(entries, explosive_keys),
            (
                "generic BPT power",
                "MBT distance-as-power",
                "MBT protocol-independent norm",
                "BPT MPV",
            ),
            "Event/trajectory/coordinate/provider support, protocol and qualification evidence are retained.",
            "DJ JH/CT and FT/CT, BPT provider versus DynamisLM velocity, and MBT protocol variants cannot alias.",
            "Explosive-test outputs remain bounded performance observations/derivations; no generic power shortcut is accepted.",
            _TESTS["explosive-tests"],
            _AUTHORITY["explosive-tests"],
        ),
        CoverageRow(
            "longitudinal statistics / reliability / error",
            CoverageStatus.QUALIFIED_WITH_EXPLICIT_DEFERRED,
            ("dynamislm.longitudinal.statistics",),
            _ids(entries, stats_keys),
            (
                "ICC variants",
                "SEM/MDC without registered assumptions",
                "confidence intervals",
                "mixed-effects models",
            ),
            "Statistical support binds exact observations, scale semantics, window/design, assumptions and output provenance.",
            "Statistics cannot consume noncomparable identities or caller-minted reliability assumptions.",
            "Numerical change, error-relative change and practical/fatigue/readiness meaning remain separate gates.",
            _TESTS["longitudinal-statistics"],
            _AUTHORITY["longitudinal-statistics"],
        ),
        CoverageRow(
            "cross-source comparability",
            CoverageStatus.QUALIFIED_WITH_EXPLICIT_DEFERRED,
            ("dynamislm.comparability", "dynamislm.external_load.comparability"),
            _ids(entries, ("res70-registered-affine-transformation-v1",)),
            ("unregistered device/method bridge", "transitive pairwise comparability"),
            "Exact observation hashes, identities, context and authority registry hashes are bound to each decision.",
            "States are explicit: comparable, conditional, transformation-required, bridge-required, not-comparable, insufficient.",
            "A transformation request is not a comparability verdict and cannot be supplied by an LM.",
            _TESTS["comparability"],
            _AUTHORITY["comparability"],
        ),
        CoverageRow(
            "analysis capability",
            CoverageStatus.QUALIFIED_WITH_EXPLICIT_DEFERRED,
            ("dynamislm.analysis.authority", "dynamislm.analysis.registry"),
            _ids(
                entries,
                (
                    "longitudinal-absolute-change-v1",
                    "longitudinal-relative-change-v1",
                    "longitudinal-log-ratio-v1",
                    "longitudinal-reference-window-deviation-v1",
                    "two-replicate-within-subject-random-error-v1",
                    "method-comparison-ba-summary-v1",
                    "repeated-measures-correlation",
                    "mixed-effects",
                ),
            ),
            (
                "between-athlete association",
                "cross-test association",
                "deferred repeated-measures models",
            ),
            "Authorization binds operation, support hashes, identity dimensions, level of analysis and prerequisites.",
            "Missing comparability, support, level, evidence or statistical authority yields structured refusal.",
            "Between-athlete information cannot be relabelled as within-athlete inference or causal evidence.",
            _TESTS["analysis"],
            _AUTHORITY["analysis"],
        ),
        CoverageRow(
            "claim authority",
            CoverageStatus.QUALIFIED_WITH_EXPLICIT_DEFERRED,
            ("dynamislm.claims.authority", "dynamislm.claims.registry", "dynamislm.evidence.res70"),
            (),
            (
                "practical meaningfulness without decision criterion",
                "unsupported causal/readiness/injury claims",
            ),
            "Claim intent revalidates exact observations and all upstream result/evidence/comparability authority.",
            "Claim level cannot promote an unresolved identity, comparison, analysis or applicability bundle.",
            "The claim ladder and causal hierarchy are enforced; refusal preserves safe observation descriptions.",
            _TESTS["claims"] + _TESTS["comparability"],
            _AUTHORITY["claims"],
        ),
    )
    return rows


def validate_coverage_matrix(rows: tuple[CoverageRow, ...] | None = None) -> GateComponentStatus:
    if rows is None:
        rows = build_coverage_matrix()
    required = {
        "population/source authority",
        "football world/context",
        "ingestion/qualification",
        "external load / GNSS / optical",
        "CMJ",
        "strength / IMTP / VBT",
        "sprint / maximum velocity / COD / RSA / 30-15 IFT",
        "DJ / bench throw / medicine-ball throw",
        "longitudinal statistics / reliability / error",
        "cross-source comparability",
        "analysis capability",
        "claim authority",
    }
    actual = {row.domain for row in rows}
    if actual != required:
        raise ValueError(f"RES-71 coverage matrix domain mismatch: {sorted(actual ^ required)}")
    if len(rows) != len(actual):
        raise ValueError("RES-71 coverage matrix contains duplicate domains")
    root = _repository_root()
    for row in rows:
        if not row.authoritative_surfaces or not row.test_coverage:
            raise ValueError(f"coverage row is incomplete: {row.domain}")
        if any(not (root / path).is_file() for path in row.test_coverage):
            raise ValueError(f"coverage row has missing test evidence: {row.domain}")
    return GateComponentStatus.PASS


def build_unresolved_computation_inventory() -> tuple[UnresolvedComputation, ...]:
    entries = build_registered_operation_inventory()
    unresolved: list[UnresolvedComputation] = []
    for entry in entries:
        if entry.disposition in {
            OperationDisposition.IMPLEMENTED,
            OperationDisposition.HISTORICAL_REPLAY_ONLY,
        }:
            continue
        metadata = _metadata_for_id(entry.operation_id, _metadata())
        unresolved.append(
            UnresolvedComputation(
                capability=entry.label,
                registered_operation_id=entry.operation_id,
                disposition=entry.disposition,
                reason=metadata.reason
                or "The operation is explicitly outside current numerical authority.",
                refusal_path=entry.refusal_path,
                expected_refusal_class=metadata.expected_refusal_class,
                safe_description=metadata.safe_description
                or "The input observation remains independently describable.",
                test_coverage=entry.test_coverage,
                authority_references=entry.authority_references,
                expected_reason_codes=metadata.expected_reason_codes,
            )
        )
    unresolved.extend(
        (
            UnresolvedComputation(
                "CMJ RFD",
                None,
                OperationDisposition.DEFERRED,
                "Onset-window, differentiation, filtering and sampling authority is not frozen.",
                ("dynamislm.measurement.cmj.metrics:refuse_unregistered_cmj_rfd",),
                "COMPUTATION_NOT_REGISTERED",
                "Force/event observations and registered CMJ metrics remain describable.",
                ("tests/test_cmj_metrics.py",),
                ("docs/decisions/RES65-RECEIPT.json",),
                expected_reason_codes=("NO_REGISTERED_OPERATION",),
            ),
            UnresolvedComputation(
                "generic BPT load-times-velocity power",
                None,
                OperationDisposition.REJECTED,
                "Generic external-load times velocity is not a registered BPT mechanical-system equation.",
                (
                    "dynamislm.measurement.bench_press_throw.metrics:calculate_bpt_load_times_velocity_power",
                ),
                "COMPUTATION_NOT_REGISTERED",
                "BPT velocity series and provider metrics remain separately describable.",
                ("tests/test_explosive_test_families.py",),
                ("docs/decisions/RES68-RECEIPT.json",),
                expected_reason_codes=("NO_REGISTERED_OPERATION", "COMPUTATION_NOT_REGISTERED"),
            ),
            UnresolvedComputation(
                "MBT distance-as-power or protocol-independent normative score",
                None,
                OperationDisposition.REJECTED,
                "MBT distance and release velocity do not authorize a generic power or norm operation.",
                (
                    "dynamislm.measurement.medicine_ball_throw.metrics:calculate_mbt_distance_as_power",
                    "dynamislm.measurement.medicine_ball_throw.metrics:calculate_mbt_protocol_independent_normative_score",
                ),
                "COMPUTATION_NOT_REGISTERED",
                "Qualified MBT distance or instrumented release velocity remains describable.",
                ("tests/test_explosive_test_families.py",),
                ("docs/decisions/RES68-RECEIPT.json",),
                expected_reason_codes=("NO_REGISTERED_OPERATION", "COMPUTATION_NOT_REGISTERED"),
            ),
            UnresolvedComputation(
                "sprint acceleration",
                None,
                OperationDisposition.DEFERRED,
                "Adjacent split-average velocities do not constitute a registered time-resolved acceleration estimator.",
                ("dynamislm.measurement.field_testing.sprint:refuse_sprint_acceleration",),
                "COMPUTATION_NOT_REGISTERED",
                "Qualified split times and segment-average velocities remain describable.",
                ("tests/test_field_testing.py",),
                ("docs/decisions/RES67-RECEIPT.json",),
                expected_reason_codes=("NO_REGISTERED_OPERATION", "METRIC_DEFINITION_MISMATCH"),
            ),
            UnresolvedComputation(
                "VIFT as VO2max, MAS or maximum sprint speed",
                None,
                OperationDisposition.REJECTED,
                "VIFT is a registered 30-15 IFT final-stage velocity, not a relabelled physiological or sprint construct.",
                (
                    "dynamislm.measurement.field_testing.ift:refuse_vift_as_vo2max",
                    "dynamislm.measurement.field_testing.ift:refuse_vift_as_mas",
                    "dynamislm.measurement.field_testing.ift:refuse_vift_as_mss",
                ),
                "IDENTITY_UNRESOLVED",
                "The exact VIFT stage result remains describable.",
                ("tests/test_field_testing.py",),
                ("docs/decisions/RES67-RECEIPT.json",),
                expected_reason_codes=("MEASURAND_MISMATCH", "METRIC_DEFINITION_MISMATCH"),
            ),
        )
    )
    return tuple(unresolved)


def validate_unresolved_computation_inventory(
    entries: tuple[UnresolvedComputation, ...] | None = None,
) -> GateComponentStatus:
    if entries is None:
        entries = build_unresolved_computation_inventory()
    capabilities = tuple(item.capability for item in entries)
    if len(set(capabilities)) != len(capabilities):
        raise ValueError("RES-71 unresolved inventory contains duplicate capabilities")
    expected = build_unresolved_computation_inventory()
    expected_capabilities = {item.capability for item in expected}
    if set(capabilities) != expected_capabilities:
        raise ValueError("RES-71 unresolved inventory is incomplete against the reviewed set")
    root = _repository_root()
    for item in entries:
        if item.disposition is OperationDisposition.IMPLEMENTED:
            raise ValueError(
                f"implemented capability leaked into unresolved inventory: {item.capability}"
            )
        for path in item.refusal_path:
            route_object = _resolve_route(path, kind="refusal", owner=item.capability)
            if not callable(route_object):
                raise ValueError(f"RES-71 refusal route is not callable: {path}")
            route: Callable[..., object] = route_object
            if item.registered_operation_id is not None and path.endswith(
                "refuse_unimplemented_reliability_operation"
            ):
                references = _discover_references()
                try:
                    operation = references[item.registered_operation_id]
                except KeyError as exc:
                    raise ValueError(
                        f"unresolved inventory operation is not live: {item.registered_operation_id}"
                    ) from exc
                result = route(operation)
            elif path.endswith("estimate_1rm_from_load_velocity_model"):
                result = route(None)
            else:
                result = route()
            if not isinstance(result, RefusalResult):
                raise ValueError(
                    f"RES-71 refusal route did not return RefusalResult: {item.capability}"
                )
            if result.refusal_class.value != item.expected_refusal_class:
                raise ValueError(
                    f"RES-71 refusal class mismatch for {item.capability}: "
                    f"expected {item.expected_refusal_class}, got {result.refusal_class.value}"
                )
            if tuple(result.reason_codes) != item.expected_reason_codes:
                raise ValueError(
                    f"RES-71 refusal reason-code mismatch for {item.capability}: "
                    f"expected {item.expected_reason_codes}, got {result.reason_codes}"
                )
        for path in item.test_coverage:
            if not (root / path).is_file():
                raise ValueError(f"unresolved inventory test path is missing: {path}")
    return GateComponentStatus.PASS


__all__ = [
    "RES71_REGISTRY_VERSION",
    "build_coverage_matrix",
    "build_registered_operation_inventory",
    "build_unresolved_computation_inventory",
    "discovered_registered_operation_ids",
    "validate_coverage_matrix",
    "validate_registered_operation_inventory",
    "validate_unresolved_computation_inventory",
]
