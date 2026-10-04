# RES258 supersession map

This map applies the RES-254 human decision under RES-256's `PASS` audit. It
preserves [RES21-DR-001](RES21-DR-001-performance-science-eval-v1.md) and does
not rewrite historical receipts. The active authority is
[RES258-DR-001](RES258-DR-001-pse-v1-pool-first-selection-authority.md) plus
the [pool-first lifecycle](../architecture/PERFORMANCE_SCIENCE_EVAL_PRE_REVIEW_V1.md).

| Prior authority or evidence | Survives | Superseded or limited by RES-258 | Disposition |
| --- | --- | --- | --- |
| RES-126 candidate-review-packet scope and composition | Scientific validity, source/JATS/provenance gates, and composition bounds | A fixed pre-review count of 434; composition bounds applied to the pre-review pool; exact origin counts as final equality | Composition bounds apply at final selection; pool is variable and at least 434 |
| RES-223 incidence-topology repair and exact-feasibility evidence | DR-001 final coverage and split requirements; proof results for the exact evaluated inputs | Treating one fixed 434-candidate topology or its pre-review witness as authority for future pool size, reserve, or final membership | Historical, input-bound feasibility evidence; rerun qualification and final proof on their respective pools |
| RES-225 minimum-repair search | The repair results and certificates for the exact diagnosed model | Repair cardinality, released slots, candidate actions, exact origins, or fixed mutation geometry as required final construction | Historical model-based diagnosis; not the final-selection contract |
| RES-249 A/B/C benchmark | The abstract comparison and its measured results | The exact `240/40/31/12/111` origin vector, `37 lineages × 3 children`, or a particular abstract plan as required final composition/topology | Historical abstract design evidence; eligible to inform later implementation only under RES258 constraints |
| RES-252 reliability frontier and production-lock WIP | Reliability measurements for their tested plans; independent reserve as a pool-qualification reliability requirement | Fixed pre-review `N=434`, exact-origin equality, a fixed oversupply count, or elevating reserve into a stronger final CRITICAL minimum | Reserve is derived from eligible structure; use targeted governed backfill; final CRITICAL minimum remains DR-001 |

## Frozen replacements

```text
PRE_REVIEW_POOL_N=VARIABLE_GE434
FINAL_SELECTED_N=434
FINAL_SPLITS=260/87/87
FINAL_COMPOSITION=RES126_BOUNDS
REJECTION=REMOVE_FROM_FINAL_ELIGIBILITY
EXACT_ORIGIN_VECTOR_240_40_31_12_111=HISTORICAL_EVIDENCE_ONLY
MUTATION_37X3=HISTORICAL_EVIDENCE_ONLY
MUTATION_PARENT_CO_SELECTION=NO
CRITICAL_FINAL_MINIMUM=DR001
CRITICAL_INDEPENDENT_RESERVE=POOL_QUALIFICATION_RELIABILITY_REQUIREMENT
PSE_V1_CLAIM_CEILING=COVERAGE_PLUS_ADVERSARIAL
```

The final composition bounds are `EXPERT_AUTHORED_SEMANTIC <= 240`,
`SOURCE_BACKED_EVIDENCE_EXTRACTION >= 40`,
`DETERMINISTIC_ENGINE_DERIVED >= 30`,
`DETERMINISTIC_SYNTHETIC >= 12`, `ADVERSARIAL_MUTATION >= 60`, and
`MUTATION_LINEAGES >= 20`. They constrain only the exact final selection.

## Evidence and implementation boundaries

RES-223/225/249 and RES-252 artifacts remain historical evidence bound to the
candidate inputs and models they evaluated. None proves that a future reviewed
pool can satisfy final selection without requalification and independent
validation. The RES-257 archive ref
`archive/res253-res252-wip-fdb6c94` preserves the prior WIP separately; no
archived implementation commit is imported by this authority amendment.

RES-3k must implement one constraint vocabulary for pool qualification,
approved-pool selection, final split allocation, and independent validation.
RES-3l must make RES-71 engine-reference identity an explicit isolation
identity. RES-258 does not authorize solver implementation, candidate
materialization, human review, split persistence, or protected-store changes;
any later RES-3m work inherits these constraints and needs its own explicit
scope and gate.
