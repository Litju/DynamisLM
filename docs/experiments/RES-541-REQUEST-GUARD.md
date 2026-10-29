# RES-541 CPU request-contract boundary

`scripts.request_issuer` adds opt-in local operator issuance and execution around
`scripts.request_guard`. Both use the frozen A0 scientific execution path. They
do not modify or protect the historical A0/A0.1 entry points, invoke a model,
or grant scientific permission independently of RES-69/70.

## Trusted origin and confirmation

The trusted control plane is the operator's local OS account, private state
directory, pinned public signing identity and encrypted Ed25519 private key.
The model is an untrusted producer of proposal **data**, not a process allowed
arbitrary code execution under that account. Filesystem permissions do not
isolate same-account hostile code. Such code, a stolen passphrase, a compromised
host, or an operator who falsely confirms a model's interpretation defeats this
trust assumption. A terminal alone is not proof that a human approved anything.

Initialization pins the public identity only after a controlling-terminal
confirmation of its exact digest. Existing state is never overwritten. Private
key/state files must be owned by the current UID, mode 0600, with mode 0700 state
and key directories, outside Git and without symlink final paths. Use a POSIX
filesystem for these permissions; Windows E: mounts generally cannot supply them.
No credential is provisioned automatically and no production credential is in Git.

Issuance reads only `/dev/tty`, never stdin, a requirements file, a model proposal
or fixture expectations. The operator independently selects every objective,
analysis class, baseline/follow-up roles and **both** claim axes. NONE deliberately
excludes an axis; UNKNOWN blocks issuance. Unresolved/contradictory requirements,
an incomplete inventory, duplicate IDs and invalid intents block issuance.
The original question, evidence and complete selected requirements are displayed
again, and the operator must type `CONFIRM RES-541 <exact-contract-digest>`.
No keyword or model classifier establishes meaning or detects contradictions.

Only after this confirmation does OpenSSH request the encrypted private key's
passphrase through the terminal and sign the canonical requirements. Agent and
askpass shortcuts are disabled for signing. The passphrase is not placed in
Python variables, arguments, environment variables, proposal files or receipts.
Execution verifies with the pinned public identity and does not read the private
key or ask for its passphrase. A model-supplied signature/issuer/confirmation is
not an execution input. All test credentials and terminal operators are synthetic.

## Contract, binding and lifecycle

The existing inner `RES541_REQUEST_REQUIREMENTS_V1` contract is unchanged. It
contains issuer, confirmation reference, issue/expiry times, exact context digest,
fixed synthetic ATHLETE_WITHIN / WITHIN_ATHLETE scope, complete objective inventory
and explicit unknowns. Completeness is an operator attestation against the original
question, not a machine-verified natural-language property.

Canonical bytes are UTF-8 JSON from `dataclasses.asdict(requirements)`, sorted keys,
compact separators, no NaN. OpenSSH signs these bytes in the separate namespace
`dynamislm-res541-request-v1`. Their SHA-256 is the contract ID. The confirmation
reference binds the local UID, a random issuance nonce and issuer source digest.
The context digest binds exact request text/ID, current Git revision, guard source,
canonical support and role-to-entry mapping. Source/context changes require fresh
issuance. The supplied context must exactly reproduce from the existing synthetic
constructor; this does not establish that input numbers originated synthetically.

A private SQLite ledger stores the canonical bytes, signature and ACTIVE/USED/
REVOKED state. No key or passphrase is stored there. Contracts expire 600 seconds
after collection. A verified execution attempt atomically consumes the contract
**before** dispatch, including a proposal mismatch or scientific refusal; concurrent
replay has at most one accepted attempt. Crash after consumption requires fresh
issuance, not a retry. Revocation requires its own exact terminal confirmation.
Backing up/restoring or rewriting the ledger is trusted administration, not an
untrusted model capability; no rollback-resistant remote ledger is claimed.

After SSH verification and lifecycle admission, an ephemeral in-memory HMAC adapts
the authenticated requirements to the unchanged guard API. This HMAC key is never
stored or supplied by the model. The low-level `request_guard.evaluate` API still
requires trusted caller configuration; it is not the issuance endpoint.

The whole proposal inventory and every typed intent must match before scientific
authorization. Unknown requirements and missing, duplicate, extra or substituted
objectives fail closed. A model REFUSE is not a canonical scientific refusal.
Accepted objectives retain separate RES-69/70 results/refusals. Descriptive
computation can legitimately precede refusal of a preserved higher-level claim.
A separately requested numerical result plus a causal refusal yields aggregate
PARTIALLY_REFUSED, never RESULT for the complete question.

The original `_evaluate` function runs with only its evaluation-only oracle
disabled in a private namespace; its scoring field is removed. Canonical scientific
functions remain unchanged. Receipts bind the contract/context, issuer/confirmation,
objective IDs, proposal digests and scientific authority hashes. ISSUANCE rejection
and guard contract rejection are orchestration dispositions, not RES-70 authority.

## Operator use (CPU only)

Run from the existing worktree in a personally controlled local terminal. Create
an encrypted key interactively; choose a nonempty passphrase and keep it out of
agent sessions and logs. Do not run a model under this operator account with shell
or credential/state access.

```sh
install -d -m 700 "$HOME/.config/dynamislm"
ssh-keygen -t ed25519 -a 64 -f "$HOME/.config/dynamislm/request-signing"
.venv/bin/python -m scripts.request_issuer initialize --issuer local-operator \
  --key "$HOME/.config/dynamislm/request-signing"
.venv/bin/python -m scripts.request_issuer issue --case-id valid-positive-01
.venv/bin/python -m scripts.request_issuer execute --case-id valid-positive-01 \
  --contract-id CONTRACT_ID --proposals /mnt/e/DynamisLM-A0/proposals.json
.venv/bin/python -m scripts.request_issuer revoke --contract-id CONTRACT_ID
```

The CLI is deliberately restricted to the existing 16 synthetic development case
IDs. It reads their questions/observations, never their expected scientific answers.
Proposal files contain only a JSON list of `objective_id` / `raw_json` objects.
`--state-dir` is trusted operator configuration, not a field accepted from a model.
Keep public proposal/report artifacts on E: and credentials/private state outside
Git in the protected POSIX directory. No real owner contract is generated by tests.

Engineering checks establish an authenticated operator-contract path and contract
consistency, not language comprehension, operator scientific competence, objective
completeness against free text, generalization or model qualification. Without
actual operator configuration and fresh confirmation/passphrase, no issuance occurs.
