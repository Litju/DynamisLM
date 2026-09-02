# RES45-DR-004

DECISION_ID=RES45-DR-004
STATUS=ADOPTED
QUESTION=How should the registered standard-gravity reference represent its exact/conventional status without being confused with an unassessed local-gravity estimate?
PROBLEM=`STANDARD_GRAVITY` currently uses `UncertaintyStatus.NOT_ASSESSED`, which describes an empirical value whose uncertainty has not been assessed. The registered `g_n = 9.80665 m/s^2` is instead a conventional exact/reference value and is not a local measurement.
SCOPE=The metadata and source/type invariants of `STANDARD_GRAVITY` and `LOCAL_GRAVITATIONAL_ACCELERATION` references used by the existing RES-44 mass paths. The numeric value, standard/local distinction, PHYSICAL_SYSTEM_MASS contract, and STANDARD_GRAVITY_MASS_EQUIVALENT contract are unchanged.
SOURCES=
- `docs/decisions/RES44-DR-001-system-mass-and-standard-gravity-equivalent.md`
- [JCGM/VIM 2.12, conventional quantity value](https://jcgm.bipm.org/vim/en/2.12.html)
- [BIPM CGPM Resolution 2 (1901), standard acceleration of gravity](https://www.bipm.org/en/committees/cg/cgpm/3-1901/resolution-2)
- [NIST SP 811, Appendix B.8, standard acceleration of gravity](https://www.nist.gov/pml/special-publication-811/nist-guide-si-appendix-b-conversion-factors/nist-guide-si-appendix-b8)
CANONICAL_AUTHORITY=The existing `UncertaintyStatus` vocabulary is sufficient when `STANDARD_GRAVITY` uses `NOT_APPLICABLE` together with an explicit exact/conventional description; the registered value and source remain authoritative.
OPTIONS_CONSIDERED=
- Keep `NOT_ASSESSED`: rejected because it misstates a conventional exact/reference value as an unassessed empirical estimate.
- Add a broad uncertainty or GUM model: rejected as unnecessary and outside RES-45.
- Add a new general reference-status hierarchy: rejected because the existing status plus explicit description expresses the required narrow state.
- Use `NOT_APPLICABLE` with an exact/conventional description and close the standard-source/local-type pairing: adopted.
DECISION=`STANDARD_GRAVITY` remains exactly `9.80665 m/s^2` with the registered standard source and must serialize with `UncertaintyStatus.NOT_APPLICABLE` and the explicit description that it is a conventional exact/reference value, not a local measurement or an unassessed empirical estimate. A `LOCAL_GRAVITATIONAL_ACCELERATION` reference must not use the standard-gravity source. Local references otherwise remain supplied references with their existing uncertainty metadata, defaulting to `NOT_ASSESSED` when no assessment is supplied.
RATIONALE=VIM identifies conventional quantity values as values attributed by agreement and gives `g_n = 9.80665 m/s^2` as the canonical example. BIPM and NIST describe standard gravity as a conventional reference rather than a location-specific acceleration. `NOT_APPLICABLE` prevents the standard reference from being read as an unresolved empirical uncertainty, while the description preserves the exact/conventional and non-local meaning in the serialized object.
MIGRATION_EFFECT=Existing callers continue to pass the explicit registered `STANDARD_GRAVITY` object or a supplied local reference. Any manually constructed valid standard reference must adopt the required status and description; local references do not inherit standard metadata. No mass arithmetic or result identity is changed.
SERIALIZATION_EFFECT=The corrected uncertainty status and description are serialized in the current version 3 envelope and in RES-44 mass procedure parameters. Canonical hashes and affected mass-observation artifacts therefore change when re-materialized; v2 payloads remain rejected under the strict version gate established by RES45.
ASSUMPTIONS=The BIPM/JCGM/NIST conventional-reference definitions apply to the registered standard-gravity object. A supplied local reference represents an applicable local gravitational acceleration only when its caller provides that applicability; no local estimator is introduced.
LIMITATIONS=No uncertainty propagation, local-gravity estimation, geographic correction, calibration, buoyancy correction, body-mass inference, or new mass operation is defined. The status is a metadata contract, not an uncertainty budget.
IMPLEMENTATION=`src/dynamislm/measurement/cmj/weighing.py`; `src/dynamislm/measurement/cmj/registry.py` source identity remains unchanged.
TESTS=`tests/test_cmj.py`: exact value, `NOT_APPLICABLE` status, explicit conventional/non-local description, constructor rejection of uncorrected standard metadata, rejection of standard source for local type, standard/local distinction, mass-path requirements, and canonical roundtrip.
VERSION=RES45-P1D1-1.0.0
