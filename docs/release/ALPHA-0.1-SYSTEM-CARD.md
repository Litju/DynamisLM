# DynamisLM-Action-3B-v0.1 — experimental system card

**Status: EXPERIMENTAL / NOT QUALIFIED FOR RELEASE.** The internal evaluation
returned `INTERNAL_NO_GO`. This card describes the deployed authority path and
the measured boundary of the release candidate.

## Authority split

The model is an untrusted proposer. Python is the authority.

1. The model receives one packaged synthetic scenario and one question.
2. It may emit a V3 action proposal: `analysis_class`, `observation_ids`,
   `operation`, and `target_claims` for the measurement and relationship axes.
3. The parser accepts only the registered V3 grammar and only observation IDs
   that exist in the scenario.
4. RES-70 admission decides whether the proposal is authorized, refused or
   abstained. It checks measurement identity, source provenance, observation
   support, comparability, statistical authority and claim escalation.
5. Only the RES-69 longitudinal absolute-change operation is dispatchable.
   The model cannot reach other engine operations. Every dispatched result is
   deterministic, receipt-bound and rendered without model prose.
6. C1 prefix-mask decoding restricts the token path to the registered grammar;
   it does not choose a scientifically correct action.

The model's prose and proposed claims are never the scientific result. A
`GROUNDED_RESULT` is a deterministic engine receipt, not a model assertion.

## Threat model

- **Forged executor text:** a question may contain tool-call or instruction
  text. The model input is isolated from the authority path; only parsed V3
  actions reach admission.
- **Silent downgrade:** a model can omit a requested causal or practical claim
  while still proposing an apparently valid action. This occurred on 4 causal
  and 14 practical family items and is reported separately.
- **Unauthorized dispatch:** the runner records pre-veto dispatch attempts.
  The evaluated cohort had zero unauthorized dispatch in 96 C1 items.
- **Prompt injection in questions:** questions are validated for control
  characters, bound length and tool-token injection before inference.
- **Model collapse:** constant refusal is safe but unhelpful. Safety metrics
  must not be read as scientific competence.

## Data handling

Synthetic packaged scenarios only. No real athlete measurements, clinical
records, user-supplied data or personal data are accepted by the runtime. Gold,
family labels and adjudication metadata never enter the inference workspace.

## Evaluation boundary

Evidence class `INTERNAL_OWNER_ADJUDICATED`, independence `NONE`. The approval
record is a recorded Linear owner authorization, not a cryptographic signature.
The evaluation is not independent validation, not the RES-746 prospective
decision, and not a claim about real athletes or real studies.

## Reproducibility

- Source evaluated: `480496b21df65bc026317a2fc52783bb0797ed8c`.
- Adapter bundle: `d0e6c2a34fdafde9ca7783e7cd540d2fcb8d285d5735139fea5f243f9219ddd3`.
- Sealed packet: `ed0ffd72b9388d167a3684664955c6e29154f81473fd92680227266ac73859d5`.
- Run: `0eb2772f55171f50e31a42025037265ccc5dba71eb894665eb240be2ce20b8c7`.
- Output commitment: `6d6a8165cd60dd8de02f8e14e2762195a9faa5796620464ee93e10ed80fe4041`.
- Report: `6cdb3071233e1058ac13ca34bbc2a47ed970bff11d790ef84184a468c6c7ab9f`.
- Gold release: `b06145bbd9e280486f0b1fa33d9c361572d826a2d852d73c3d97ebc67e51650f`.

The `dynamislm-research ask` path decodes, parses, admits and renders a
deterministic receipt. Use the documented CPU path with a verified RES-772
bundle and the exact base revision. CUDA inference is available only in a
separately qualified environment.

## Residual risks

The tested checkpoint proposes no registered operation on 24/24 expected
executions. A deployment that relied on this checkpoint would refuse nearly
everything, not perform science. A deployment that bypassed the authority path
or treated model text as a result would be unsafe and is out of scope.
