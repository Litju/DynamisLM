# RES-541 A0.1 prospective activation decision V1

Disposition: **BLOCKED_OWNER_ELIGIBILITY_BUDGET_APPROVAL / KEEP_PROFILE_INACTIVE**.
Baseline: `6038c70d21233a619ffec09ea464c9077ebfbe5c`. This is CPU-only preparation,
not an activation commit or authorization to allocate compute.

## Exact proposal and approval status

Prospective eligible Python set: **3.13.15, 3.13.16, 3.13.17, 3.13.18**. These are
compatibility candidates, not observed or proven equivalent environments, and this
proposal does not establish release availability or the failed VM's version.
`PROFILE.candidate_python_patches` records this ordered finite set. Candidate
screening rejects other patches as well as other minors/prereleases. The approved
list stays empty, `active` stays false, and both approval records remain null.
Source approval cannot introduce a patch outside this proposed set.

The latest [recorded independent PR review](https://github.com/Litju/DynamisLM/pull/46#pullrequestreview-5661784087)
reviews exactly the baseline and says **PASS_WITH_LIMITATIONS** for the CPU
implementation, **KEEP_PROFILE_INACTIVE** for activation. It is an advisory
COMMENT, explicitly not GPU or merge approval. The corresponding RES-541 Linear
comment `f7ce579e-0b8f-4421-9c99-333a699b7b25` records the same hold. The current
instructions, PR reviews/discussion, and RES-541 issue/comments provide no owner
approval of this exact four-patch eligibility set and future compute budget.
Prior attempt approvals do not transfer. Neither record is copied into a source
approval field or assigned an invented reviewer identity.

The four-patch proposal still needs independent review of its precise scope and
an authentic, inspectable owner record approving the set, reviewed source and
bounded single-session budget. Only after those records exist may a separate
minimal activation commit fill the approved list/attestations, set active true,
refresh the standalone runtime SHA, pass full QA and hosted exact-head CI, and
receive fresh interactive authorization at that exact pushed source. No future
activation commit hash can truthfully be supplied now.

## Preserved requirements and proposed session budget

- Standard final CPython 3.13 on Linux x86-64, exact
  `cpython-313-x86_64-linux-gnu` SOABI, GIL enabled, no free-threaded/debug build;
  all version/build/compiler/ABI observations must be present.
- Exact Torch `2.11.0+cu130`, observed `torch.version.cuda == "13.0"`, one
  `Tesla T4`, SM 7.5, at least 12 GiB total and 8 GiB free VRAM; FP16 load policy
  with actual floating parameter dtype verified by the frozen loader.
- Exactly one `a0_diagnostic / 16` experiment. Host run watchdog/CLI timeout 900s,
  inherited remote execution deadline 840s, report download 120s, stop 30s and
  zero-session verification 30s. Cleanup is additional potentially billable time.
- Weight metadata ceiling 8 GiB; bootstrap free disk minimum 12 GiB and inherited
  loader disk margin of weights plus 2 GiB. Input limit 1,024 tokens, generation
  limit 64, greedy non-thinking decoding and seed 541 remain unchanged.
- Current quota, acceptable compute-unit/cost spend and this future attempt's
  exact eligibility/budget consent are **not approved or measured here**. Time
  bounds are not a measurement or guarantee of billed compute units.

## Gate, serialization and preservation review

Both frozen original functions retain their literal Python/Torch gates in source.
Their SHA-verified private copies adapt exactly one Python comparison each. The
bootstrap captures inventory before setup/clone/downloads, writes an exclusive
inventory sidecar and qualifies before the inherited preflight. Inference checks
before tokenizer downloads and again at its private loader gate before weights.
Remaining dependency, hardware, precision, resource and scientific checks stay.

Inventory uses JSON-native Python build/capability lists, explicit missing values,
and real metadata queries. Bootstrap evidence survives preparation's JSON transfer;
child agreement permits only a venv executable-path difference. NO_GO reports
retain rejected inventory and partial generations. Existing report/sidecar paths
are rejected. The host preserves downloaded bytes, verifies source/run/suite/profile,
requires successful stop plus an explicit zero-session response, and independently
replays token evidence, inventory qualification and deterministic scientific score.

No blocking adapter defect was demonstrated by this inspection or the focused CPU
falsification tests. This change narrows the prospective screen and expands tests;
it does not rewrite the adapters, host replay or scientific engine. The standalone
SHA changes because the fetched runtime module now contains the finite proposal.
Full QA/CI results are recorded on PR #46 and in E:-local evidence, not inferred
from this review statement.

## Hashes and execution decision

Hashes use SHA-256 of sorted-key compact JSON, with the patch lists in the stated
ascending order; the standalone hash covers the complete source bytes.

| Item | SHA-256 |
| --- | --- |
| Inactive profile | `68d6a8d4c596b62ea98c93474e6eeb89adea00a6c27d21892f945b195213fe77` |
| Proposed candidate list | `6e5419a815970109ea028f6d6bad0a7168c5fbacfe6f71a8f9958c0774d623b5` |
| Empty approved list `[]` | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |
| Standalone runtime source | `727b19ae028ec62cd7cf6df1622fa56317bffdaf0f294c16ff6f620869c0a74c` |

**Execution NO_GO: stop before GPU.** After authentic approvals and a reviewed
activation commit, one supervised T4 session may inventory its actual runtime and
proceed directly to inference only if every gate qualifies. Otherwise stop before
weights, preserve incompatibility evidence and verify teardown. No retry, alternate
GPU, weights/training/PSE access, additional PR or merge is authorized here.

Historical A0/A0.1 evidence, unknown failed-runtime inventory, frozen SmolLM3
checkpoint/tokenizer/prompt/cases, strict parser, RES-69/70 authority and serialization
remain unchanged. A changed runtime patch is a prompt-plus-runtime comparison,
not a prompt-only causal ablation. Local artifacts/caches/temp files remain on E:;
future model weights remain remote and ephemeral. CPU tests are not live runtime
compatibility, numerical equivalence or scientific model-performance evidence.
