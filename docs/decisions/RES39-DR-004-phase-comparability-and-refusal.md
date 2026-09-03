# RES39-DR-004 — Phase comparability and refusal

## QUESTION

How should phase metrics be compared and refused when labels match but phase
systems, boundaries, upstream mechanics, or system contracts differ?

## SOURCES

- RES-34 comparability/refusal boundary;
- RES-36 event comparability;
- RES-37 mechanics comparability;
- RES-39 phase-system, landmark, and metric decisions;
- Harry et al. (2020) as the primary example of a distinct phase framework:
  <https://doi.org/10.1249/MSS.0000000000002197>.

## OPTIONS

Treat same labels as comparable, refuse every cross-system comparison, or use a
registered method-aware comparison that distinguishes direct comparability from
bridge validation.

## DECISION

Use a deterministic method-aware rule. The rule compares phase system/version,
definition, boundary convention and methods, movement-onset/takeoff detector
identity and parameters, peak/direction-change/propulsion method, qualified velocity
identity, net-force/integration identity, timebase, filtering, drift state,
loading/system contract, and exact metric definition.

Same V1 methods and material semantics yield `COMPARABLE`. Same label across
different systems yields `BRIDGE_VALIDATION_REQUIRED` with no silent aliasing.
Different mechanical measurands or metric definitions yield
`NOT_COMPARABLE`. Unregistered comparison authority yields an explicitly
unresolved result.

## PHASE_SYSTEM

`CMJ_PHASE_COMPARABILITY_RULE` is versioned independently from the V1 phase
system and is required for a deterministic verdict.

## BOUNDARIES

Boundary methods and sample/time semantics are part of phase identity. A
`BRAKING` interval from a yielding/braking joint-power system is not silently
treated as a V1 braking interval.

## SAMPLE/TIME SEMANTICS

Trial instance IDs are not themselves a comparability failure; material source
method, timebase, processing, and system fields remain in the comparison key.
The phase occurrence and metric observation retain exact source IDs for
provenance even when those IDs are omitted from the cross-trial method key.
The velocity integration interval and upstream mechanics processing semantics
remain in the method key; a metric source must also be the exact net-force or
displacement result in the velocity lineage, not merely a same-trial quantity.

## EQUATIONS

No value equality or conversion is used as a comparability equation. The rule
is a closed comparison of registered identities and method parameters.

## INPUTS

Two distinct V1-qualified phase metric observations with their phase occurrences,
or two structurally complete phase metric results.

## ASSUMPTIONS

Comparability is claim-relative. A bridge, if later registered, must be
scientifically validated; a user request cannot override the rule.

## CLAIM CEILING

The result authorizes only the stated comparison claim. It does not establish
causal, physiological, or performance interpretation.

## PROVENANCE

The comparison result cites the phase comparability rule and RES-39 decision;
the compared outputs separately retain their full source provenance.

## COMPARABILITY

The rule emits `COMPARABLE`, `BRIDGE_VALIDATION_REQUIRED`, `NOT_COMPARABLE`, or
`INSUFFICIENT_INFORMATION` with explicit reasons and conditions. It never uses a
same-label shortcut.

## REFUSAL

Non-comparable or unresolved results map to
`PHASE_COMPARABILITY_UNESTABLISHED` while preserving each observation ID and
stating that each observation remains independently describable.

## LIMITATIONS

No cross-system bridge is registered in RES-39. No trial selection or
aggregation is authorized; those remain RES-40 work.

## TESTS

Tests cover same-label cross-system rejection/bridge state, source and method
mismatch reasons, deterministic serialization, and refusal preservation.

## VERSION

`RES39-P1G-1.0.0`; `SERIALIZATION_VERSION=3` retained.
