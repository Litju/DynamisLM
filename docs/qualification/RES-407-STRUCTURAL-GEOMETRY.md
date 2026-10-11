# RES-407 structural repair checkpoint

The checkpoint diagnoses the exact immutable 449-candidate problem
`sha256:29b85a7b7518c09a40093326a4e4832c6cee7b564d4384806dc9fceeb0abc5c0`.
The typed geometry retains the complete selection vocabulary and authority inventory,
including selected-member colocation hyperedges, parent provenance, and cell inheritance.
An OUT member can break a chain of intersecting hyperedges.

Run `python scripts/res407_repair_geometry.py --fresh-process` in the project environment.
The runner reconstructs RES-405, RES-406, RES-451 and live v1.3 supply authority. It writes
atomic, canonical, digest-bound external diagnostics under
`production/variable-pools/backfill/<original-plan-digest>/<RES-451-merge-sha>/geometry/v2/`.
Earlier exploratory diagnostics remain preserved outside this versioned namespace.
The original variable-pool store is hashed before and after execution.

Each split-capacity solve removes **all three SPLIT_COUNT equalities**. Keeping the
other two counts together with final N=434 would fix the target count by subtraction.
Final N=434, coverage, origin bounds, mutation lineages, split locks, conditional
colocation, qualification/review forcing, and parent provenance/inheritance remain active.
The two ablations additionally remove only their named constraint family. Soft production
objectives do not enter a capacity solve. The certificate records every relaxed ID,
original and active inventory digests, solver version/configuration, an OPTIMAL maximum,
and an independently validated diagnostic witness. These witnesses allocate no final
production membership.

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

Current C08 supply is classified **UNRESOLVED**. It may occupy its locked split and
displace existing selections. It cannot directly cover other capability rows or the
ANSWERABLE obligation. The capacity loss and these facts do not prove sufficiency or
impossibility of repair. `AUTHORITY_EXPANSION_REQUIRED` needs a valid structural proof.
The historical subset helpers remain labelled legacy WIP, and their qualification CLI
is disabled. The structural runner does not invoke them or materialize packets.

## Next direct optimizer

Introduce integer `y[a] >= 0`, the number of additions of governed archetype `a`, and
minimize `sum(y[a])`. The master augments the structural model, restores normal production
split equalities, and retains every other hard authority. Impose lane-wide finite
capacity bounds: `sum(y[a] for a in lane) <= remaining_lane_capacity`. A rule-governed
lane requires an authority-validated materializability rule; it grants no infinite
concrete supply. Unknown feature or identity behavior requires contract refinement or
an explicit unresolved result before the optimizer can assert a repair.

Robustness is a hard requirement. Couple the structural master to the exact
`FinalSelectionProblem` oracle. Add removal scenarios whenever the oracle finds a
failing removal, and require an exact feasible production assignment for every required
scenario before accepting the master repair. UNKNOWN remains inconclusive. Abstract
exchangeable additions may share scenario representatives only with a proved identity
and relation equivalence. Materialize only the winning, authority-backed repair, then
run exact production qualification and its complete robustness gate. Do not enumerate
concrete candidate subsets. A structural optimum alone authorizes no final membership.
