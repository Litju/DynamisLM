"""Small, explicit CMJ registry surface for the P1B-P1F contracts."""

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
CMJ_MECHANICS_COMPARABILITY_RULE = _reference(
    "comparability-rule", "cmj-mechanics-v1", "CMJ mechanics comparability"
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
CMJ_PHYSICAL_SYSTEM_MASS_FROM_WEIGHT = _reference(
    "registered-operation",
    "cmj-physical-system-mass-from-weight-v1",
    "CMJ physical system mass from local support force",
)
CMJ_STANDARD_GRAVITY_MASS_EQUIVALENT_FROM_WEIGHT = _reference(
    "registered-operation",
    "cmj-standard-gravity-mass-equivalent-from-weight-v1",
    "CMJ standard-gravity mass equivalent from system weight",
)
CMJ_MECHANICS_SYSTEM_CONTRACT = _reference(
    "schema", "cmj-mechanics-system-contract-v1", "CMJ mechanics system contract"
)
CMJ_FORCE_PLATFORM_PLUS_GRAVITY_EXTERNAL_FORCE_MODEL = _reference(
    "external-force-model",
    "cmj-force-platform-plus-gravity-v1",
    "CMJ force platform plus gravity external-force model",
)
CMJ_TRAPEZOIDAL_INTEGRATION_METHOD = _reference(
    "integration-method",
    "cmj-sample-attached-trapezoidal-v1",
    "CMJ sample-attached cumulative trapezoidal integration",
)
CMJ_INCLUSIVE_SAMPLE_INTEGRATION_BOUNDARY = _reference(
    "integration-boundary",
    "cmj-inclusive-endpoint-samples-v1",
    "CMJ inclusive endpoint-sample integration boundary",
)
CMJ_NET_VERTICAL_FORCE_OPERATION = _reference(
    "registered-operation",
    "cmj-net-vertical-force-from-total-force-and-system-weight-v1",
    "CMJ net vertical force from total supported force and SYSTEM_WEIGHT",
)
CMJ_NET_VERTICAL_FORCE_SCHEMA = _reference(
    "schema", "cmj-net-vertical-force-series-v1", "CMJ net vertical-force series"
)
CMJ_NET_VERTICAL_FORCE_MEASURAND = _reference(
    "measurand", "cmj-net-vertical-force", "CMJ net vertical force"
)
CMJ_NET_VERTICAL_FORCE_METRIC = _reference("metric", "cmj-net-vertical-force", "Net vertical force")
CMJ_NET_VERTICAL_IMPULSE_OPERATION = _reference(
    "registered-operation",
    "cmj-net-vertical-impulse-v1",
    "CMJ scalar net vertical impulse",
)
CMJ_NET_VERTICAL_IMPULSE_MEASURAND = _reference(
    "measurand", "cmj-net-vertical-impulse", "CMJ net vertical impulse"
)
CMJ_NET_VERTICAL_IMPULSE_METRIC = _reference(
    "metric", "cmj-net-vertical-impulse", "Net vertical impulse"
)
CMJ_SUPPORTED_SYSTEM_COM_ACCELERATION_OPERATION = _reference(
    "registered-operation",
    "cmj-supported-system-com-vertical-acceleration-v1",
    "CMJ supported-system COM vertical acceleration",
)
CMJ_SUPPORTED_SYSTEM_COM_ACCELERATION_MEASURAND = _reference(
    "measurand",
    "cmj-supported-system-com-vertical-acceleration",
    "CMJ supported-system COM vertical acceleration",
)
CMJ_SUPPORTED_SYSTEM_COM_ACCELERATION_METRIC = _reference(
    "metric",
    "cmj-supported-system-com-vertical-acceleration",
    "Supported-system COM vertical acceleration",
)
CMJ_SUPPORTED_SYSTEM_COM_ACCELERATION_SCHEMA = _reference(
    "schema",
    "cmj-supported-system-com-vertical-acceleration-series-v1",
    "CMJ supported-system COM vertical acceleration series",
)
CMJ_SUPPORTED_SYSTEM_COM_VELOCITY_OPERATION = _reference(
    "registered-operation",
    "cmj-supported-system-com-vertical-velocity-v1",
    "CMJ supported-system COM vertical velocity",
)
CMJ_SUPPORTED_SYSTEM_COM_VELOCITY_MEASURAND = _reference(
    "measurand", "cmj-supported-system-com-vertical-velocity", "CMJ supported-system COM velocity"
)
CMJ_SUPPORTED_SYSTEM_COM_VELOCITY_METRIC = _reference(
    "metric", "cmj-supported-system-com-vertical-velocity", "Supported-system COM vertical velocity"
)
CMJ_SUPPORTED_SYSTEM_COM_VELOCITY_SCHEMA = _reference(
    "schema",
    "cmj-supported-system-com-vertical-velocity-series-v1",
    "CMJ supported-system COM vertical velocity series",
)
CMJ_SUPPORTED_SYSTEM_COM_RELATIVE_DISPLACEMENT_OPERATION = _reference(
    "registered-operation",
    "cmj-supported-system-com-relative-vertical-displacement-v1",
    "CMJ supported-system COM relative vertical displacement",
)
CMJ_SUPPORTED_SYSTEM_COM_RELATIVE_DISPLACEMENT_MEASURAND = _reference(
    "measurand",
    "cmj-supported-system-com-relative-vertical-displacement",
    "CMJ supported-system COM relative vertical displacement",
)
CMJ_SUPPORTED_SYSTEM_COM_RELATIVE_DISPLACEMENT_METRIC = _reference(
    "metric",
    "cmj-supported-system-com-relative-vertical-displacement",
    "Supported-system COM relative vertical displacement",
)
CMJ_SUPPORTED_SYSTEM_COM_RELATIVE_DISPLACEMENT_SCHEMA = _reference(
    "schema",
    "cmj-supported-system-com-relative-vertical-displacement-series-v1",
    "CMJ supported-system COM relative vertical displacement series",
)
CMJ_ZERO_INITIAL_VERTICAL_VELOCITY = _reference(
    "initial-condition",
    "cmj-zero-vertical-velocity-at-explicit-sample-v1",
    "CMJ zero vertical velocity at explicit initial-condition sample",
)
CMJ_QUALIFIED_ZERO_VELOCITY_REFERENCE = _reference(
    "zero-velocity-reference",
    "cmj-qualified-zero-vertical-velocity-from-weighing-segment-v1",
    "CMJ qualified zero vertical velocity from an exact weighing segment",
)
CMJ_RELATIVE_DISPLACEMENT_ZERO_ORIGIN = _reference(
    "coordinate-origin",
    "cmj-relative-vertical-displacement-zero-at-initial-sample-v1",
    "CMJ relative vertical displacement zero at initial sample",
)
CMJ_JUMP_HEIGHT_MEASURAND = _reference(
    "measurand",
    "cmj-vertical-ballistic-takeoff-to-apex-rise",
    "CMJ vertical ballistic takeoff-to-apex rise",
)
CMJ_JUMP_HEIGHT_METRIC = _reference(
    "metric",
    "cmj-estimator-qualified-jump-height",
    "CMJ estimator-qualified jump-height estimate",
)
CMJ_JUMP_HEIGHT_SCHEMA = _reference(
    "schema",
    "cmj-jump-height-estimate-v1",
    "CMJ scalar jump-height estimate",
)
CMJ_FLIGHT_TIME_JUMP_HEIGHT_ESTIMATOR = _reference(
    "estimator",
    "cmj-flight-time-ballistic-jump-height-v1",
    "CMJ flight-time ballistic jump-height estimator",
)
CMJ_QUALIFIED_TAKEOFF_VELOCITY_JUMP_HEIGHT_ESTIMATOR = _reference(
    "estimator",
    "cmj-qualified-takeoff-velocity-ballistic-apex-rise-v1",
    "CMJ qualified takeoff-velocity ballistic apex-rise estimator",
)
CMJ_FLIGHT_TIME_JUMP_HEIGHT_OPERATION = _reference(
    "registered-operation",
    "cmj-flight-time-ballistic-jump-height-v1",
    "CMJ flight-time ballistic jump-height estimate",
)
CMJ_QUALIFIED_TAKEOFF_VELOCITY_JUMP_HEIGHT_OPERATION = _reference(
    "registered-operation",
    "cmj-qualified-takeoff-velocity-ballistic-apex-rise-v1",
    "CMJ qualified takeoff-velocity ballistic apex-rise estimate",
)
CMJ_JUMP_HEIGHT_COMPARABILITY_RULE = _reference(
    "comparability-rule",
    "cmj-jump-height-estimator-v1",
    "CMJ estimator-qualified jump-height comparability",
)
CMJ_BALLISTIC_VERTICAL_MOTION_ASSUMPTION = _reference(
    "assumption",
    "cmj-ballistic-vertical-motion-v1",
    "ballistic vertical motion over the takeoff-to-apex interval",
)
CMJ_TAKEOFF_LANDING_HEIGHT_EQUIVALENCE_ASSUMPTION = _reference(
    "assumption",
    "cmj-takeoff-landing-height-equivalence-v1",
    "takeoff and landing COM heights are equivalent",
)
CMJ_NEGLIGIBLE_AIR_RESISTANCE_ASSUMPTION = _reference(
    "assumption",
    "cmj-negligible-air-resistance-v1",
    "air resistance is negligible for the ballistic estimate",
)
CMJ_SUPPORTED_SYSTEM_STABLE_ASSUMPTION = _reference(
    "assumption",
    "cmj-supported-system-stable-v1",
    "supported physical system remains stable through the mechanics chain",
)
CMJ_LOCAL_GRAVITY_APPLICABLE_ASSUMPTION = _reference(
    "assumption",
    "cmj-local-gravity-applicable-v1",
    "the explicit local gravitational reference applies to the trial",
)
CMJ_TAKEOFF_VELOCITY_EVENT_SAMPLE_CONVENTION = _reference(
    "sample-convention",
    "cmj-takeoff-velocity-at-event-sample-v1",
    "takeoff velocity sampled at the registered takeoff event sample",
)
CMJ_TOTAL_SUPPORTED_VERTICAL_FORCE_SCHEMA = _reference(
    "schema", "cmj-total-supported-vertical-force-v1", "CMJ total supported vertical-force series"
)
CMJ_SYSTEM_WEIGHT_MEASURAND = _reference("measurand", "cmj-system-weight", "CMJ system weight")
CMJ_SYSTEM_WEIGHT_METRIC = _reference("metric", "cmj-system-weight", "System weight")
CMJ_PHYSICAL_SYSTEM_MASS_MEASURAND = _reference(
    "measurand", "cmj-physical-system-mass", "CMJ physical system mass"
)
CMJ_PHYSICAL_SYSTEM_MASS_METRIC = _reference(
    "metric", "cmj-physical-system-mass", "Physical system mass"
)
CMJ_STANDARD_GRAVITY_MASS_EQUIVALENT_MEASURAND = _reference(
    "measurand",
    "cmj-standard-gravity-mass-equivalent",
    "CMJ standard-gravity mass equivalent",
)
CMJ_STANDARD_GRAVITY_MASS_EQUIVALENT_METRIC = _reference(
    "metric",
    "cmj-standard-gravity-mass-equivalent",
    "Standard-gravity mass equivalent",
)
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
RES44_DECISION_MASS_METROLOGY = RegistryReference(
    identifier=ScientificIdentifier(
        "dynamislm",
        "decision-record",
        "res44-system-mass-and-standard-gravity-equivalent",
        CMJ_REGISTRY_VERSION,
    ),
    display_label="RES-44 system-mass and standard-gravity-equivalent decision",
    reference_ids=(
        "docs/decisions/RES44-DR-001-system-mass-and-standard-gravity-equivalent.md",
        "https://doi.org/10.59161/AUEZ1291",
        "https://jcgm.bipm.org/vim/en/2.12.html",
        "https://www.nist.gov/pml/owm/si-units-mass",
        "https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication811e1995.pdf",
        "https://nvlpubs.nist.gov/nistpubs/Legacy/TN/nbstechnicalnote491.pdf",
    ),
)
RES37_DECISION_SUPPORTED_SYSTEM_NET_FORCE = RegistryReference(
    identifier=ScientificIdentifier(
        "dynamislm", "decision-record", "res37-supported-system-net-force", CMJ_REGISTRY_VERSION
    ),
    display_label="RES-37 supported-system net-force decision",
    reference_ids=(
        "docs/decisions/RES37-DR-001-supported-system-net-force.md",
        "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0265999",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC7761544/",
    ),
)
RES37_DECISION_IMPULSE_INTEGRATION = RegistryReference(
    identifier=ScientificIdentifier(
        "dynamislm", "decision-record", "res37-impulse-and-integration", CMJ_REGISTRY_VERSION
    ),
    display_label="RES-37 impulse and integration decision",
    reference_ids=(
        "docs/decisions/RES37-DR-002-impulse-and-integration-semantics.md",
        "https://bura.brunel.ac.uk/handle/2438/1392",
        "http://dx.doi.org/10.1119/1.1397460",
        "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0265999",
    ),
)
RES37_DECISION_PHYSICAL_MASS_ACCELERATION = RegistryReference(
    identifier=ScientificIdentifier(
        "dynamislm", "decision-record", "res37-physical-mass-acceleration", CMJ_REGISTRY_VERSION
    ),
    display_label="RES-37 physical mass and acceleration decision",
    reference_ids=(
        "docs/decisions/RES37-DR-003-physical-acceleration-and-mass-contract.md",
        "docs/decisions/RES44-DR-001-system-mass-and-standard-gravity-equivalent.md",
        "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0265999",
    ),
)
RES37_DECISION_INITIAL_VELOCITY = RegistryReference(
    identifier=ScientificIdentifier(
        "dynamislm", "decision-record", "res37-initial-velocity", CMJ_REGISTRY_VERSION
    ),
    display_label="RES-37 initial velocity decision",
    reference_ids=(
        "docs/decisions/RES37-DR-004-velocity-initial-condition.md",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC7761544/",
        "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0265999",
    ),
)
RES46_DECISION_QUALIFIED_ZERO_VELOCITY = RegistryReference(
    identifier=ScientificIdentifier(
        "dynamislm", "decision-record", "res46-qualified-zero-velocity", CMJ_REGISTRY_VERSION
    ),
    display_label="RES-46 qualified zero-velocity integration-start decision",
    reference_ids=(
        "docs/decisions/RES46-DR-001-qualified-zero-velocity-integration-start.md",
        "https://bura.brunel.ac.uk/handle/2438/1392",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC7761544/",
        "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0265999",
        # PMID 20664368 is Meylan, Nosaka, Green & Cronin (2011); the source URL
        # and its applicability to the existing decision remain unchanged.
        "https://pubmed.ncbi.nlm.nih.gov/20664368/",
    ),
)
RES38_DECISION_FLIGHT_TIME_ESTIMATOR = RegistryReference(
    identifier=ScientificIdentifier(
        "dynamislm", "decision-record", "res38-flight-time-estimator", CMJ_REGISTRY_VERSION
    ),
    display_label="RES-38 flight-time estimator decision",
    reference_ids=(
        "docs/decisions/RES38-DR-001-flight-time-estimator.md",
        "https://bura.brunel.ac.uk/handle/2438/1392",
        "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0265999",
    ),
)
RES38_DECISION_TAKEOFF_VELOCITY_ESTIMATOR = RegistryReference(
    identifier=ScientificIdentifier(
        "dynamislm", "decision-record", "res38-takeoff-velocity-estimator", CMJ_REGISTRY_VERSION
    ),
    display_label="RES-38 takeoff-velocity estimator decision",
    reference_ids=(
        "docs/decisions/RES38-DR-002-takeoff-velocity-estimator.md",
        "https://bura.brunel.ac.uk/handle/2438/1392",
        "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0265999",
    ),
)
RES38_DECISION_CLASSIFICATION_COMPARABILITY = RegistryReference(
    identifier=ScientificIdentifier(
        "dynamislm",
        "decision-record",
        "res38-estimator-classification-and-comparability",
        CMJ_REGISTRY_VERSION,
    ),
    display_label="RES-38 estimator classification and comparability decision",
    reference_ids=("docs/decisions/RES38-DR-003-estimator-comparability-and-classification.md",),
)
RES38_DECISION_COM_DISPLACEMENT = RegistryReference(
    identifier=ScientificIdentifier(
        "dynamislm", "decision-record", "res38-com-displacement-decision", CMJ_REGISTRY_VERSION
    ),
    display_label="RES-38 COM-displacement estimator decision",
    reference_ids=("docs/decisions/RES38-DR-004-com-displacement-estimator-decision.md",),
)
RES37_DECISION_DISPLACEMENT_REFERENCE = RegistryReference(
    identifier=ScientificIdentifier(
        "dynamislm", "decision-record", "res37-displacement-reference", CMJ_REGISTRY_VERSION
    ),
    display_label="RES-37 relative displacement reference decision",
    reference_ids=(
        "docs/decisions/RES37-DR-005-relative-displacement-reference.md",
        "https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0265999",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC7761544/",
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
METERS_PER_SECOND = UnitReference(
    ScientificIdentifier("dynamislm", "unit", "meter-per-second", CMJ_REGISTRY_VERSION),
    "m/s",
)
METER = UnitReference(
    ScientificIdentifier("dynamislm", "unit", "meter", CMJ_REGISTRY_VERSION),
    "m",
)
NEWTON_SECOND = UnitReference(
    ScientificIdentifier("dynamislm", "unit", "newton-second", CMJ_REGISTRY_VERSION),
    "N·s",
)
# Short aliases retain readable operation names without creating additional
# registry identities.
CMJ_SUPPORTED_SYSTEM_COM_ACCELERATION = CMJ_SUPPORTED_SYSTEM_COM_ACCELERATION_OPERATION
CMJ_SUPPORTED_SYSTEM_COM_VELOCITY = CMJ_SUPPORTED_SYSTEM_COM_VELOCITY_OPERATION
CMJ_SUPPORTED_SYSTEM_COM_RELATIVE_VERTICAL_DISPLACEMENT = (
    CMJ_SUPPORTED_SYSTEM_COM_RELATIVE_DISPLACEMENT_OPERATION
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
