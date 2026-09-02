"""Small, explicit CMJ registry surface for the P1B/P1C/P1D contracts."""

from __future__ import annotations

from dynamislm.measurement.cmj.identity import CMJ_REGISTRY_VERSION
from dynamislm.measurement.identity import RegistryReference, ScientificIdentifier, UnitReference


def _reference(object_type: str, key: str, label: str) -> RegistryReference:
    return RegistryReference(
        identifier=ScientificIdentifier("dynamislm", object_type, key, CMJ_REGISTRY_VERSION),
        display_label=label,
    )


CMJ_RAW_VERTICAL_FORCE_SIGNAL_SCHEMA = _reference(
    "schema", "cmj-raw-vertical-force-signal", "CMJ raw vertical-force signal"
)
CMJ_ACQUISITION_COMPARABILITY_RULE = _reference(
    "comparability-rule", "cmj-acquisition-identity-v1", "CMJ acquisition identity comparability"
)
CMJ_DERIVED_COMPARABILITY_RULE = _reference(
    "comparability-rule", "cmj-derived-measurement-v1", "CMJ derived-measurement comparability"
)
CMJ_EVENT_COMPARABILITY_RULE = _reference(
    "comparability-rule", "cmj-event-v1", "CMJ event comparability"
)

CMJ_MOVEMENT_ONSET_EVENT_DEFINITION_REF = _reference(
    "event-definition", "cmj-movement-onset", "CMJ movement onset"
)
CMJ_TAKEOFF_CONTACT_LOSS_EVENT_DEFINITION_REF = _reference(
    "event-definition", "cmj-takeoff-contact-loss", "CMJ takeoff/contact loss"
)
CMJ_LANDING_CONTACT_REGAIN_EVENT_DEFINITION_REF = _reference(
    "event-definition", "cmj-landing-contact-regain", "CMJ landing/contact regain"
)
CMJ_MOVEMENT_ONSET_BASELINE_SD_METHOD_REF = _reference(
    "event-method", "cmj-movement-onset-baseline-sd", "CMJ baseline-SD movement-onset detector"
)
CMJ_TAKEOFF_ABSOLUTE_FORCE_METHOD_REF = _reference(
    "event-method", "cmj-takeoff-absolute-force", "CMJ absolute-force takeoff detector"
)
CMJ_LANDING_ABSOLUTE_FORCE_METHOD_REF = _reference(
    "event-method", "cmj-landing-absolute-force", "CMJ absolute-force landing detector"
)

RES36_DECISION_MOVEMENT_ONSET = RegistryReference(
    identifier=ScientificIdentifier(
        "dynamislm", "decision-record", "res36-movement-onset", CMJ_REGISTRY_VERSION
    ),
    display_label="RES-36 movement-onset decision",
    reference_ids=(
        "docs/decisions/RES36-DR-001-movement-onset.md",
        "https://pubmed.ncbi.nlm.nih.gov/20664368/",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC9783824/",
        "https://pubmed.ncbi.nlm.nih.gov/31711369/",
        "https://doi.org/10.1519/JSC.0000000000000311",
    ),
)
RES36_DECISION_TAKEOFF = RegistryReference(
    identifier=ScientificIdentifier(
        "dynamislm", "decision-record", "res36-takeoff-contact-loss", CMJ_REGISTRY_VERSION
    ),
    display_label="RES-36 takeoff/contact-loss decision",
    reference_ids=(
        "docs/decisions/RES36-DR-002-takeoff-contact-loss.md",
        "https://pubmed.ncbi.nlm.nih.gov/38863789/",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC9865236/",
    ),
)
RES36_DECISION_LANDING = RegistryReference(
    identifier=ScientificIdentifier(
        "dynamislm", "decision-record", "res36-landing-contact-regain", CMJ_REGISTRY_VERSION
    ),
    display_label="RES-36 landing/contact-regain decision",
    reference_ids=(
        "docs/decisions/RES36-DR-003-landing-contact-regain.md",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC9865236/",
        "https://pubmed.ncbi.nlm.nih.gov/38863789/",
    ),
)
RES36_DECISION_EVENT_SEMANTICS = RegistryReference(
    identifier=ScientificIdentifier(
        "dynamislm", "decision-record", "res36-event-semantics", CMJ_REGISTRY_VERSION
    ),
    display_label="RES-36 event index/time/comparability decision",
    reference_ids=(
        "docs/decisions/RES36-DR-004-event-index-time-and-comparability.md",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC9865236/",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC9783824/",
        "https://pubmed.ncbi.nlm.nih.gov/38863789/",
    ),
)

CMJ_EXPLICIT_WEIGHING_SEGMENT = _reference(
    "selection-method", "cmj-explicit-weighing-segment-v1", "CMJ explicit weighing segment"
)
CMJ_SYSTEM_WEIGHT_MEAN_FORCE = _reference(
    "estimator", "cmj-system-weight-mean-force-v1", "CMJ system weight mean force estimator"
)
CMJ_BILATERAL_TOTAL_VERTICAL_FORCE_SUM = _reference(
    "registered-operation",
    "cmj-bilateral-total-vertical-force-sum-v1",
    "CMJ bilateral total vertical-force sum",
)
CMJ_SYSTEM_WEIGHT_OPERATION = _reference(
    "registered-operation", "cmj-system-weight-v1", "CMJ system weight from weighing segment"
)
CMJ_SYSTEM_MASS_FROM_WEIGHT = _reference(
    "registered-operation", "cmj-system-mass-from-weight-v1", "CMJ system mass from system weight"
)
CMJ_TOTAL_SUPPORTED_VERTICAL_FORCE_SCHEMA = _reference(
    "schema", "cmj-total-supported-vertical-force-v1", "CMJ total supported vertical-force series"
)
CMJ_SYSTEM_WEIGHT_MEASURAND = _reference("measurand", "cmj-system-weight", "CMJ system weight")
CMJ_SYSTEM_WEIGHT_METRIC = _reference("metric", "cmj-system-weight", "System weight")
CMJ_SYSTEM_MASS_MEASURAND = _reference("measurand", "cmj-system-mass", "CMJ system mass")
CMJ_SYSTEM_MASS_METRIC = _reference("metric", "cmj-system-mass", "System mass")
CMJ_TOTAL_SUPPORTED_VERTICAL_FORCE_MEASURAND = _reference(
    "measurand", "cmj-total-supported-vertical-force", "CMJ total supported vertical force"
)
CMJ_TOTAL_SUPPORTED_VERTICAL_FORCE_METRIC = _reference(
    "metric", "cmj-total-supported-vertical-force", "Total supported vertical force"
)
CMJ_DYNAMISLM_PROCESSING_SYSTEM = _reference(
    "processing-system", "dynamislm-res35", "DynamisLM RES-35 processing system"
)
CMJ_SUPPORTED_SYSTEM_CONSTRUCT = _reference(
    "construct", "cmj-supported-system", "CMJ supported physical system"
)
STANDARD_GRAVITY_SOURCE = RegistryReference(
    identifier=ScientificIdentifier(
        "dynamislm", "reference-source", "standard-acceleration-of-gravity", CMJ_REGISTRY_VERSION
    ),
    display_label="BIPM/NIST conventional standard acceleration of gravity",
    reference_ids=(
        "https://www.bipm.org/documents/d/guest/si-brochure-9-pdf",
        "https://www.nist.gov/pml/special-publication-811/nist-guide-si-appendix-b9",
    ),
)

NEWTON = UnitReference(
    ScientificIdentifier("dynamislm", "unit", "newton", CMJ_REGISTRY_VERSION), "N"
)
KILONEWTON = UnitReference(
    ScientificIdentifier("dynamislm", "unit", "kilonewton", CMJ_REGISTRY_VERSION), "kN"
)
POUND_FORCE = UnitReference(
    ScientificIdentifier("dynamislm", "unit", "pound-force", CMJ_REGISTRY_VERSION), "lbf"
)
KILOGRAM_FORCE = UnitReference(
    ScientificIdentifier("dynamislm", "unit", "kilogram-force", CMJ_REGISTRY_VERSION), "kgf"
)
KILOGRAM = UnitReference(
    ScientificIdentifier("dynamislm", "unit", "kilogram", CMJ_REGISTRY_VERSION), "kg"
)
METERS_PER_SECOND_SQUARED = UnitReference(
    ScientificIdentifier("dynamislm", "unit", "meter-per-second-squared", CMJ_REGISTRY_VERSION),
    "m/s^2",
)
REGISTERED_FORCE_UNITS = (NEWTON, KILONEWTON, POUND_FORCE, KILOGRAM_FORCE)


def is_registered_force_unit(unit: UnitReference) -> bool:
    """Return whether the unit is explicitly registered for CMJ force signals."""

    return any(
        candidate.identifier.stable_id == unit.identifier.stable_id
        for candidate in REGISTERED_FORCE_UNITS
    )


def is_registered_axis(reference: RegistryReference) -> bool:
    return reference.identifier.object_type == "axis"


def is_registered_reference_frame(reference: RegistryReference) -> bool:
    return reference.identifier.object_type == "reference-frame"


def is_registered_arrangement(reference: RegistryReference) -> bool:
    return reference.identifier.object_type == "acquisition-arrangement"
