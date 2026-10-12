# RES-407 structural repair checkpoint

The checkpoint diagnoses the exact immutable 449-candidate problem
`sha256:29b85a7b7518c09a40093326a4e4832c6cee7b564d4384806dc9fceeb0abc5c0`.
The typed geometry retains the complete selection vocabulary and authority inventory,
including selected-member colocation hyperedges, parent provenance, and cell inheritance.
An OUT member can break a chain of intersecting hyperedges.

Run `python scripts/res407_repair_geometry.py --fresh-process` in the project environment.
The runner reconstructs RES-405, RES-406, RES-451 and live v1.3 supply authority. It writes
atomic, canonical, digest-bound external diagnostics under
`production/variable-pools/backfill/<original-plan-digest>/<RES-451-merge-sha>/geometry/v3/`.
Earlier exploratory diagnostics remain preserved outside this versioned namespace.
The original variable-pool store is hashed before and after execution.

Each split-capacity solve removes **all three SPLIT_COUNT equalities**. Keeping the
other two counts together with final N=434 would fix the target count by subtraction.
Final N=434, coverage, origin bounds, mutation lineages, split locks, conditional
colocation, qualification/review forcing, and parent provenance/inheritance remain active.
The two ablations additionally remove only their named constraint family. Soft production
objectives do not enter a capacity solve. A versioned semantic binding beside each stable
Serialization V3 certificate lists every relaxed and retained constraint ID, the retained
inventory digest, `FINAL_N=434`, solver configuration, target-split maximization objective,
`OPTIMAL` status, objective value and bound, and the certificate result digest. The
independently validated witness remains diagnostic and allocates no final production
membership. All three split equalities are removed for each envelope solve; ablations add
only their named relaxation.

| Diagnostic | Public maximum | Validation maximum | Hidden maximum |
| --- | ---: | ---: | ---: |
| Current interacting authority | 212 | 212 | 212 |
| Remove conditional colocation | 260 | not evaluated | not evaluated |
| Remove feature minima | 426 | not evaluated | not evaluated |

The required counts are 260, 87, and 87. Public's capacity deficit is 48. This is not a
candidate count requirement: an independent addition could enable several existing
candidates to move. Typed support evidence records active coverage obligations, selected
support, lock exclusions, and relation/coverage intersections. Ablations demonstrate
interaction; they do not identify a unique causal repair.

The live inventory yields three authorable synthetic split lanes and twelve lane/cell
archetypes. Capacity is rule governed, with no asserted number of concrete candidates.
Finite capacity is shared by the lane and reduced by complete consumption accounting.
Each archetype binds lane and generator authority, cell, origin, split lock, identity
requirements, materializer identity/version/contract, and current materializability.
Feature guarantees remain incomplete rather than extrapolated from an earlier seed.
Synthetic materialization guarantees a shared cluster for its split; fresh independent
isolation is not guaranteed, and other relations, including exact shingle collisions,
remain unknown.

Current C08 supply is classified **UNRESOLVED**. Its governed contract guarantees the
cell binding, split lock, and repeated-instance coupling through a shared split cluster
and generator family. Exact feature vectors, contamination/shingle behavior, and full
interchangeability remain unknown; unique seed-block identity is bounded by the lane rule
without a defined repeat sequence. The structural contract digest is
`sha256:a66311b193d258047a1dd8584541facb408fee731ad9f1bc88cf96361ce2ead6`.

The ideal structural master minimizes additions over typed selection signatures while
preserving the exact hard benchmark authority. Its search domain is bounded by
`FINAL_N=434`, since no feasible assignment can select more added units. The exact run
returned `IDEAL_REPAIR_STATUS=UNKNOWN`; it did not prove a minimum or produce an ideal
repair vector. The optimistic current-C08 relaxation also returned `UNKNOWN`, so
`CURRENT_C08_REPAIR_CAPABILITY=UNRESOLVED`. It preserves C08 origin, split locks, and lane
capacity, grants maximal per-cell feature support, and relaxes relation coupling to
independence. Neither timeout proves authority exhaustion. The governed master remains
`UNRESOLVED` because the repeated-archetype semantics are insufficient, and the missing
capability comparison remains unresolved without an optimal ideal vector.

The next architecture is first-stage governed `y[a]` counts with exact benchmark
assignment recourse, the base scenario initially, and the exact `FinalSelectionProblem`
feasibility oracle. Each failed removal found by the oracle becomes a master scenario;
the exhaustive removal sweep remains the final proof. No removal sweep, concrete
candidate, new seed, packet, human review, or final allocation ran at this checkpoint.
The historical subset helpers remain labelled legacy WIP, their qualification CLI is
disabled, and tests prove the RES-407 path cannot reach them.
