# RES-71 verifier-ready reference interface

The deterministic interface is exposed by:

```python
from dynamislm.qualification import (
    get_reference_case,
    get_reference_cases,
    reference_case_digest,
    reference_case_manifest,
)
```

The command-line adapter is:

```text
python scripts/res71_reference_cases.py --digest
python scripts/res71_reference_cases.py --manifest
```

Interface version: `res71-reference-interface@1.0.0`

Reference digest:
`sha256:d29d84699b7cf70c2d409d370c5ffd6c7ad7cd704375b14b541527a95fa385e5`

## Case contract

Each immutable `ReferenceCase` contains:

- stable case/version and scientific family;
- registered operation identity where one exists;
- typed synthetic input descriptors;
- expected scalar outputs or refusal/comparability/claim-authority state;
- reason codes and refusal class;
- absolute/relative tolerance contract for numeric outputs;
- required provenance fields;
- authority references.

The current set contains 12 cases across four outcome classes:

| Outcome | Coverage |
|---|---|
| `VALUE` | external unit conversion, relative distance, CMJ flight-time gold, RSA decrement, longitudinal change |
| `REFUSAL` | nonfinite input, CMJ RFD, generic BPT power, BPT MPV |
| `COMPARABILITY` | same label with different threshold/method identity |
| `CLAIM_AUTHORITY` | causal overclaim and between-to-within estimand mismatch |

The interface is a reference contract, not a second numerical engine. Later
PerformanceScience-Eval/SFT/RLVR verifier code must call the registered
operation and compare its typed result/refusal against the case contract. It
must not treat the expected values as a license for LM arithmetic.

The digest is sealed in runtime code and pinned by tests; the CMJ RFD case
expects the producer reason code `NO_REGISTERED_OPERATION`.
