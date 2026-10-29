"""Opt-in local operator issuance; model inputs never enter confirmation or signing."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import io
import json
import os
import re
import sqlite3
import stat
import struct
import subprocess
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, TextIO

from dynamislm import AnalysisClass, MeasurementClaimLevel, RelationshipClaimLevel
from scripts import a0_engine as engine
from scripts import a01_experiment as experiment
from scripts import request_guard as guard

NAMESPACE = "dynamislm-res541-request-v1"
LIFETIME = 600


def _private(path: Path, directory: bool = False) -> Path:
    path = path.absolute()
    info = path.lstat()
    if (
        path.is_symlink()
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
        or (not stat.S_ISDIR(info.st_mode) if directory else not stat.S_ISREG(info.st_mode))
        or path.resolve().is_relative_to(engine.ROOT)
    ):
        raise ValueError("operator state/credentials must be private, owned and outside Git")
    probe = path if directory else path.parent
    if (
        subprocess.run(
            ["git", "-C", str(probe), "rev-parse", "--is-inside-work-tree"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    ):
        raise ValueError("operator state/credentials cannot reside in a Git worktree")
    return path


def _terminal() -> TextIO:
    terminal = io.TextIOWrapper(
        open("/dev/tty", "r+b", buffering=0), encoding="utf-8", write_through=True
    )
    if not terminal.isatty():
        terminal.close()
        raise ValueError("operator controlling terminal required")
    return terminal


def _ask(terminal: TextIO, prompt: str) -> str:
    terminal.write(prompt + "\n")
    terminal.flush()
    answer = terminal.readline()
    if not answer:
        raise ValueError("operator confirmation cancelled")
    return answer.strip()


def _confirm(terminal: TextIO, action: str, digest: str) -> None:
    phrase = f"{action} RES-541 {digest}"
    if _ask(terminal, f"Type exactly {phrase}") != phrase:
        raise ValueError("operator did not confirm the exact content")


def _key(path: Path) -> Path:
    path = _private(path)
    _private(path.parent, directory=True)
    encoded = path.read_text().splitlines()
    if not encoded or encoded[0] != "-----BEGIN OPENSSH PRIVATE KEY-----":
        raise ValueError("encrypted OpenSSH private key required")
    body = base64.b64decode("".join(encoded[1:-1]), validate=True)
    magic = b"openssh-key-v1\0"
    if not body.startswith(magic) or len(body) < len(magic) + 4:
        raise ValueError("invalid OpenSSH key")
    size = struct.unpack(">I", body[len(magic) : len(magic) + 4])[0]
    if not 0 < size <= len(body) - len(magic) - 4:
        raise ValueError("invalid OpenSSH cipher field")
    cipher = body[len(magic) + 4 : len(magic) + 4 + size]
    if cipher not in {b"aes256-ctr", b"aes256-cbc", b"aes256-gcm@openssh.com"}:
        raise ValueError("an encrypted operator key with a passphrase is required")
    return path


class Issuer:
    """Trusted local control plane. Its state path is configuration, never proposal data."""

    def __init__(self, directory: Path):
        self.directory = _private(directory, directory=True)
        policy = json.loads(_private(directory / "policy.json").read_text())
        self.issuer = policy["issuer"]
        self.key_path = Path(policy["key"])
        self.allowed = _private(directory / "allowed_signers")
        self.database = _private(directory / "contracts.sqlite")
        if not isinstance(self.issuer, str) or re.fullmatch(r"[\w.@-]+", self.issuer) is None:
            raise ValueError("invalid operator identity")

    @staticmethod
    def initialize(directory: Path, issuer: str, key: Path) -> None:
        key = _key(key)
        public = Path(str(key) + ".pub").read_text().split()
        if (
            re.fullmatch(r"[\w.@-]+", issuer) is None
            or len(public) < 2
            or public[0] != "ssh-ed25519"
        ):
            raise ValueError("operator identity and Ed25519 public key required")
        trust = f"{issuer} {public[0]} {public[1]}\n"
        with _terminal() as terminal:
            terminal.write(json.dumps({"issuer": issuer, "public_key": public[:2]}) + "\n")
            _confirm(terminal, "TRUST", hashlib.sha256(trust.encode()).hexdigest())
        if directory.resolve().is_relative_to(engine.ROOT):
            raise ValueError("operator state must be outside Git")
        directory.mkdir(mode=0o700)  # Existing state is never overwritten.
        _private(directory, directory=True)
        for name, content in (
            ("policy.json", guard._json({"issuer": issuer, "key": str(key)})),
            ("allowed_signers", trust.encode()),
            ("contracts.sqlite", b""),
        ):
            with os.fdopen(
                os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
            ) as stream:
                stream.write(content)
        with sqlite3.connect(directory / "contracts.sqlite") as connection:
            connection.execute(
                "CREATE TABLE contracts (id TEXT PRIMARY KEY, payload BLOB, signature BLOB, "
                "state TEXT NOT NULL CHECK(state IN ('ACTIVE','USED','REVOKED')))"
            )

    def _verify(self, payload: bytes, signature: bytes) -> None:
        with tempfile.TemporaryDirectory(dir=self.directory) as temporary:
            path = Path(temporary) / "signature"
            path.write_bytes(signature)
            subprocess.run(
                [
                    "ssh-keygen",
                    "-Y",
                    "verify",
                    "-f",
                    str(self.allowed),
                    "-I",
                    self.issuer,
                    "-n",
                    NAMESPACE,
                    "-s",
                    str(path),
                ],
                input=payload,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=10,
            )

    def issue(self, context: engine.CaseContext) -> str:
        """Collect independent operator selections; there is deliberately no proposal argument."""
        experiment.verify_freeze()
        synthetic = engine._build_context(context.case)
        if (
            synthetic.support != context.support
            or synthetic.entries_by_role != context.entries_by_role
        ):
            raise ValueError("only the deterministic synthetic context is supported")
        key = _key(self.key_path)
        with _terminal() as terminal:
            terminal.write("Independently select ALL objectives. Do not copy a model proposal.\n")
            terminal.write(
                guard._json(
                    {
                        "request": context.case.request,
                        "observations": [asdict(o) for o in context.case.observations],
                    }
                ).decode()
                + "\n"
            )
            count = int(_ask(terminal, "Number of independently identified objectives (1-16):"))
            if not 1 <= count <= 16:
                raise ValueError("complete bounded objective inventory required")
            objectives = []
            for _ in range(count):
                objective_id = _ask(terminal, "Objective ID:")
                values: dict[str, Any] = {"v": 1, "d": "EXECUTE"}
                for field, options in (
                    ("a", [v.value for v in AnalysisClass]),
                    ("b", ["BASELINE", "FOLLOWUP", "NONE", "UNKNOWN"]),
                    ("f", ["BASELINE", "FOLLOWUP", "NONE", "UNKNOWN"]),
                    ("m", [v.value for v in MeasurementClaimLevel] + ["NONE", "UNKNOWN"]),
                    ("r", [v.value for v in RelationshipClaimLevel] + ["NONE", "UNKNOWN"]),
                ):
                    answer = _ask(terminal, f"{field}: choose exactly {', '.join(options)}")
                    if answer not in options or answer == "UNKNOWN":
                        raise ValueError("unresolved scientific requirements")
                    values[field] = None if answer == "NONE" else answer
                objectives.append(
                    guard.Objective(objective_id, engine.parse_model_intent(json.dumps(values)))
                )
            if (
                _ask(terminal, "Any unresolved/contradictory requirements? Type NONE only if none:")
                != "NONE"
            ):
                raise ValueError("unresolved or contradictory requirements")
            if (
                _ask(terminal, "Are ALL original objectives and both axes accounted for? Type ALL:")
                != "ALL"
            ):
                raise ValueError("incomplete objective inventory")
            now = int(time.time())
            issuer_source = guard._digest(Path(__file__).read_bytes())
            reference = f"ssh-tty:{os.getuid()}:{os.urandom(16).hex()}:{issuer_source}"
            requirements = guard.Requirements(
                guard.VERSION,
                self.issuer,
                reference,
                now,
                now + LIFETIME,
                guard.context_digest(context),
                guard.SCOPE,
                tuple(objectives),
                True,
                (),
            )
            guard._validate(requirements, self.issuer, now)
            payload = guard._json(asdict(requirements))
            contract_id = guard._digest(payload)
            terminal.write("Review the complete contract bound to the original request/evidence:\n")
            terminal.write(
                guard._json(
                    {
                        "request": context.case.request,
                        "observations": [asdict(o) for o in context.case.observations],
                        "requirements": asdict(requirements),
                    }
                ).decode()
                + "\n"
            )
            _confirm(terminal, "CONFIRM", contract_id)
            environment = dict(os.environ)
            for name in ("SSH_AUTH_SOCK", "SSH_ASKPASS", "DISPLAY"):
                environment.pop(name, None)
            environment["SSH_ASKPASS_REQUIRE"] = "never"
            signature = subprocess.run(
                ["ssh-keygen", "-Y", "sign", "-n", NAMESPACE, "-f", str(key)],
                input=payload,
                stdout=subprocess.PIPE,
                stderr=terminal,
                env=environment,
                check=True,
                timeout=120,
            ).stdout
        self._verify(payload, signature)
        guard._validate(requirements, self.issuer, int(time.time()))
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "INSERT INTO contracts VALUES (?, ?, ?, 'ACTIVE')",
                (contract_id, payload, signature),
            )
        return contract_id

    def revoke(self, contract_id: str) -> None:
        with _terminal() as terminal:
            _confirm(terminal, "REVOKE", contract_id)
        with sqlite3.connect(self.database) as connection:
            if (
                connection.execute(
                    "UPDATE contracts SET state='REVOKED' WHERE id=? AND state='ACTIVE'",
                    (contract_id,),
                ).rowcount
                != 1
            ):
                raise ValueError("no active contract")

    def execute(
        self, context: engine.CaseContext, contract_id: str, proposals: tuple[tuple[str, str], ...]
    ) -> dict[str, Any]:
        try:
            with sqlite3.connect(self.database) as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT payload, signature FROM contracts WHERE id=? AND state='ACTIVE'",
                    (contract_id,),
                ).fetchone()
                if row is None or guard._digest(row[0]) != contract_id:
                    raise ValueError("missing, used, revoked or altered contract")
                payload, signature = row
                self._verify(payload, signature)
                document = json.loads(payload)
                objectives = []
                for item in document.pop("objectives"):
                    value = item["intent"]
                    wire = dict(
                        v=1,
                        d=value["decision"],
                        a=value["analysis_class"],
                        b=value["baseline_role"],
                        f=value["followup_role"],
                        m=value["measurement_claim_level"],
                        r=value["relationship_claim_level"],
                    )
                    objectives.append(
                        guard.Objective(
                            item["objective_id"], engine.parse_model_intent(json.dumps(wire))
                        )
                    )
                document["unknowns"] = tuple(document["unknowns"])
                requirements = guard.Requirements(**document, objectives=tuple(objectives))
                if guard._json(asdict(requirements)) != payload:
                    raise ValueError("noncanonical requirements")
                prefix = f"ssh-tty:{os.getuid()}:"
                if not requirements.confirmation_reference.startswith(
                    prefix
                ) or requirements.confirmation_reference.split(":")[-1] != guard._digest(
                    Path(__file__).read_bytes()
                ):
                    raise ValueError("stale issuer confirmation")
                connection.execute("UPDATE contracts SET state='USED' WHERE id=?", (contract_id,))
            # Adapt authenticated SSH requirements to the unchanged HMAC guard, in memory only.
            key = os.urandom(32)
            result = guard.evaluate(
                context,
                requirements,
                hmac.new(key, payload, "sha256").hexdigest(),
                proposals,
                trusted_issuer=self.issuer,
                verification_key=key,
            )
            return {**result, "contract_id": contract_id, "lifecycle": "USED"}
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            subprocess.SubprocessError,
            sqlite3.Error,
        ):
            return {
                "outcome": "REFUSED",
                "guard_status": "REJECTED",
                "failure_stage": "ISSUANCE",
                "reason_codes": ("RES541_ISSUANCE_REQUIRED",),
                "objectives": [],
            }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state-dir", type=Path, default=Path.home() / ".config/dynamislm/res541-issuer"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("initialize")
    setup.add_argument("--issuer", required=True)
    setup.add_argument("--key", type=Path, required=True)
    issue = commands.add_parser("issue")
    issue.add_argument("--case-id", required=True)
    execute = commands.add_parser("execute")
    execute.add_argument("--case-id", required=True)
    execute.add_argument("--contract-id", required=True)
    execute.add_argument("--proposals", type=Path, required=True)
    commands.add_parser("revoke").add_argument("--contract-id", required=True)
    args = parser.parse_args()
    try:
        if args.command == "initialize":
            Issuer.initialize(args.state_dir, args.issuer, args.key)
            return 0
        issuer = Issuer(args.state_dir)
        if args.command == "revoke":
            issuer.revoke(args.contract_id)
            return 0
        case = next(c for c in engine.load_cases() if c.case_id == args.case_id)
        context = engine._build_context(case)
        if args.command == "issue":
            print(json.dumps({"contract_id": issuer.issue(context)}))
            return 0
        if not args.proposals.is_file() or args.proposals.stat().st_size > 256 * 1024:
            raise ValueError("bounded regular proposal file required")
        proposals = json.loads(args.proposals.read_text())
        if not isinstance(proposals, list) or any(
            set(row) != {"objective_id", "raw_json"} for row in proposals
        ):
            raise ValueError("proposal file may contain only objective_id/raw_json rows")
        result = issuer.execute(
            context,
            args.contract_id,
            tuple((row["objective_id"], row["raw_json"]) for row in proposals),
        )
        print(json.dumps(result, sort_keys=True))
        return 0 if result["guard_status"] == "VERIFIED" else 1
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        StopIteration,
        subprocess.SubprocessError,
        sqlite3.Error,
    ):
        print("RES-541 issuance unavailable or unconfirmed; no scientific dispatch")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
