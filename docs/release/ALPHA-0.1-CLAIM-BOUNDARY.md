# Research Alpha 0.1 — claim boundary

**Status: INTERNAL_NO_GO, report-only candidate.** No external publication is
authorized. These are the only claims the retained evidence supports.

## Supported claims

- The frozen step-510 PEFT adapter and the pinned SmolLM3-3B base can be
  identified, loaded and verified by SHA-256.
- The RES-430 `ask` path can run native greedy (N) and constrained (C1) decoding
  over packaged synthetic scenarios on a qualified T4 and CPU.
- The RES-70 admission and RES-69 execution authorities reject proposals that
  lack measurement, provenance, comparability or statistical authority.
- On the 96-item internal cohort, the tested checkpoint produced zero
  unauthorized dispatches and zero completed executions.
- On that cohort, structured V3 output was valid for 96/96 generations in both
  arms; N and C1 token IDs were identical for all 96 items.
- The internal decision under the frozen rule is `INTERNAL_NO_GO`.

## Not supported

- General scientific reasoning, causal inference, practical or coaching
  significance, clinical or return-to-play use, talent selection, or use with
  real athletes.
- Independent, external or population validation.
- Any claim that LoRA fine-tuning caused the measured behaviour. No untouched
  foundation-model arm was run.
- Any claim that constrained decoding improves scientific action selection.
- Any claim that deterministic engine correctness is learned model capability.
- Any claim about the broader engine operation surface beyond the narrow V3 path.

## Evidence labels

`INTERNAL_OWNER_ADJUDICATED`; independence `NONE`; synthetic scenarios only;
owner batch adjudication with 96 accepted dispositions; recorded Linear
approval, not a cryptographic signature. RES-746 independent-prospective
evidence is separate and remains unchanged.

## Release boundary

The adapter bundle remains `LICENSE_DECISION_REQUIRED`. The model-backed release
does not qualify. Any report-only publication would require a separate explicit
owner publication decision naming the exact artifacts and destination. Base
weights are not redistributed.
