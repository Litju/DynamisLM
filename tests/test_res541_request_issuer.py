"""Real SSH signatures and synthetic operator PTYs; no actual owner credential or approval."""

from __future__ import annotations

import json
import os
import pty
import re
import select
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from scripts import a0_engine as engine
from scripts import request_issuer as issuer

PASSWORD = "public-synthetic-test-passphrase"


def terminal_command(arguments: list[str], answers: list[tuple[str, str]]) -> tuple[int, str]:
    """Drive the actual controlling-terminal boundary, including OpenSSH's password prompt."""
    pid, master = pty.fork()
    if pid == 0:
        os.execv(sys.executable, [sys.executable, "-m", "scripts.request_issuer", *arguments])
    output = ""
    offset = 0
    deadline = time.monotonic() + 25
    try:
        while time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                output += chunk.decode(errors="replace")
            if answers:
                marker, answer = answers[0]
                found = re.search(marker, output[offset:])
                if found:
                    if answer == "CHALLENGE":
                        answer = found.group(1)
                    os.write(master, (answer + "\n").encode())
                    offset += found.end()
                    answers.pop(0)
        else:
            raise AssertionError("synthetic operator terminal timed out")
    finally:
        os.close(master)
        waited, status = os.waitpid(pid, os.WNOHANG)
        reap_deadline = time.monotonic() + 1
        while not waited and time.monotonic() < reap_deadline:
            time.sleep(0.01)
            waited, status = os.waitpid(pid, os.WNOHANG)
        if not waited:
            os.kill(pid, signal.SIGTERM)
            _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status), output


@pytest.fixture
def operator() -> Iterator[issuer.Issuer]:
    # Private-key permission tests need a POSIX filesystem, not the Windows 9p temp mount.
    with tempfile.TemporaryDirectory(prefix="res541-synthetic-issuer-", dir="/tmp") as temporary:
        root = Path(temporary)
        key = root / "operator"
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-a", "1", "-N", PASSWORD, "-f", str(key)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        directory = root / "state"
        code, transcript = terminal_command(
            [
                "--state-dir",
                str(directory),
                "initialize",
                "--issuer",
                "synthetic-operator",
                "--key",
                str(key),
            ],
            [(r"Type exactly (TRUST RES-541 [0-9a-f]{64})", "CHALLENGE")],
        )
        assert code == 0, transcript
        yield issuer.Issuer(directory)


def context(case_id: str = "valid-positive-01") -> engine.CaseContext:
    return engine._build_context(next(c for c in engine.load_cases() if c.case_id == case_id))


def choices(
    analysis: str = "SCALAR_ABSOLUTE_CHANGE",
    measurement: str = "NUMERICAL_CHANGE",
    relationship: str = "NONE",
    objective_id: str = "objective",
) -> list[tuple[str, str]]:
    return [
        ("Objective ID:", objective_id),
        ("a: choose exactly", analysis),
        ("b: choose exactly", "BASELINE"),
        ("f: choose exactly", "FOLLOWUP"),
        ("m: choose exactly", measurement),
        ("r: choose exactly", relationship),
    ]


def issue(
    operator: issuer.Issuer,
    case_id: str = "valid-positive-01",
    objectives: list[list[tuple[str, str]]] | None = None,
    tail: list[tuple[str, str]] | None = None,
) -> tuple[int, str]:
    objectives = objectives or [choices()]
    answers = [("Number of independently identified objectives", str(len(objectives)))]
    for objective in objectives:
        answers += objective
    answers += (
        tail
        if tail is not None
        else [
            ("Any unresolved/contradictory requirements", "NONE"),
            ("Are ALL original objectives", "ALL"),
            (r"Type exactly (CONFIRM RES-541 [0-9a-f]{64})", "CHALLENGE"),
            ("Enter passphrase", PASSWORD),
        ]
    )
    return terminal_command(
        ["--state-dir", str(operator.directory), "issue", "--case-id", case_id], answers
    )


def contract(
    operator: issuer.Issuer,
    case_id: str = "valid-positive-01",
    objectives: list[list[tuple[str, str]]] | None = None,
) -> str:
    code, transcript = issue(operator, case_id, objectives)
    assert code == 0, transcript
    assert PASSWORD not in transcript
    match = re.search(r'\{"contract_id": "([0-9a-f]{64})"\}', transcript)
    assert match, transcript
    return match.group(1)


def raw(
    analysis: str = "SCALAR_ABSOLUTE_CHANGE",
    measurement: str | None = "NUMERICAL_CHANGE",
    relationship: str | None = None,
) -> str:
    return json.dumps(
        dict(
            v=1, d="EXECUTE", a=analysis, b="BASELINE", f="FOLLOWUP", m=measurement, r=relationship
        )
    )


@pytest.mark.parametrize(
    ("case_id", "value"),
    [
        ("valid-positive-01", 0.125),
        ("valid-negative-01", -0.0625),
        ("valid-zero-01", 0.0),
    ],
)
def test_actual_operator_issuance_to_registered_result(
    operator: issuer.Issuer, case_id: str, value: float
) -> None:
    identifier = contract(operator, case_id)
    result = operator.execute(context(case_id), identifier, (("objective", raw()),))
    assert result["guard_status"] == "VERIFIED" and result["lifecycle"] == "USED"
    final = result["objectives"][0]["result"]
    assert final["result_value"] == value and final["result_unit"] == "m"
    assert final["statistical_result_hash"] and final["claim_authority_hash"]
    assert final["analysis_authorization_hash"]
    assert result["issuer"] == "synthetic-operator"
    assert result["confirmation_reference"].startswith(f"ssh-tty:{os.getuid()}:")
    assert (
        operator.execute(context(case_id), identifier, (("objective", raw()),))["guard_status"]
        == "REJECTED"
    )


@pytest.mark.parametrize(
    ("case_id", "analysis", "measurement", "relationship", "reason"),
    [
        (
            "refuse-causal-claim",
            "SCALAR_ABSOLUTE_CHANGE",
            "NONE",
            "CAUSAL_EVIDENCE",
            "RES70_UNSUPPORTED_CAUSAL_CLAIM",
        ),
        (
            "refuse-practical-meaning",
            "SCALAR_ABSOLUTE_CHANGE",
            "PRACTICAL_OR_DECISION_MEANINGFULNESS",
            "NONE",
            "RES70_COMPARABILITY_AUTHORITY_MISSING",
        ),
        (
            "refuse-unregistered-association",
            "WITHIN_ATHLETE_ASSOCIATION",
            "NONE",
            "ASSOCIATION",
            "COMPUTATION_NOT_REGISTERED",
        ),
        (
            "refuse-missing-unit",
            "SCALAR_ABSOLUTE_CHANGE",
            "NUMERICAL_CHANGE",
            "NONE",
            "RES70_UNRESOLVED_IDENTITY",
        ),
    ],
)
def test_issued_faithful_requirements_retain_canonical_refusals(
    operator: issuer.Issuer,
    case_id: str,
    analysis: str,
    measurement: str,
    relationship: str,
    reason: str,
) -> None:
    identifier = contract(operator, case_id, [choices(analysis, measurement, relationship)])
    result = operator.execute(
        context(case_id),
        identifier,
        (
            (
                "objective",
                raw(
                    analysis,
                    None if measurement == "NONE" else measurement,
                    None if relationship == "NONE" else relationship,
                ),
            ),
        ),
    )
    assert result["guard_status"] == "VERIFIED" and result["outcome"] == "REFUSED"
    final = result["objectives"][0]["result"]
    assert reason in final["reason_codes"] and final["result_value"] is None


@pytest.mark.parametrize(
    ("case_id", "objectives", "proposal"),
    [
        ("refuse-causal-claim", choices(measurement="NONE", relationship="CAUSAL_EVIDENCE"), raw()),
        (
            "refuse-practical-meaning",
            choices(measurement="PRACTICAL_OR_DECISION_MEANINGFULNESS"),
            raw("SCALAR_RELATIVE_CHANGE"),
        ),
        (
            "refuse-unregistered-association",
            choices("WITHIN_ATHLETE_ASSOCIATION", "NONE", "ASSOCIATION"),
            raw("WITHIN_ATHLETE_ASSOCIATION"),
        ),
    ],
)
def test_observed_substitutions_fail_after_real_issuance(
    operator: issuer.Issuer, case_id: str, objectives: list[tuple[str, str]], proposal: str
) -> None:
    identifier = contract(operator, case_id, [objectives])
    result = operator.execute(context(case_id), identifier, (("objective", proposal),))
    assert result["guard_status"] == "REJECTED" and result["failure_stage"] == "PROPOSALS"
    assert result["objectives"] == []


@pytest.mark.parametrize(
    "failure", ["unknown", "contradicted", "incomplete", "unconfirmed", "wrong-password"]
)
def test_cannot_issue_without_independent_confirmation(
    operator: issuer.Issuer, failure: str
) -> None:
    objectives = [choices()]
    tail = [
        ("Any unresolved/contradictory requirements", "NONE"),
        ("Are ALL original objectives", "ALL"),
    ]
    if failure == "unknown":
        objectives = [choices(measurement="UNKNOWN")]
        tail = []
    elif failure == "contradicted":
        tail = [("Any unresolved/contradictory requirements", "conflicting objectives")]
    elif failure == "incomplete":
        tail[-1] = ("Are ALL original objectives", "NO")
    elif failure == "unconfirmed":
        tail += [("Type exactly CONFIRM RES-541", "CONFIRM")]
    else:
        tail += [
            (r"Type exactly (CONFIRM RES-541 [0-9a-f]{64})", "CHALLENGE"),
            ("Enter passphrase", "wrong"),
        ]
    code, _ = issue(operator, objectives=objectives, tail=tail)
    assert code != 0
    with sqlite3.connect(operator.database) as connection:
        assert connection.execute("SELECT count(*) FROM contracts").fetchone()[0] == 0


def test_model_stdin_is_not_operator_confirmation(operator: issuer.Issuer) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.request_issuer",
            "--state-dir",
            str(operator.directory),
            "issue",
            "--case-id",
            "valid-positive-01",
        ],
        input="ALL\nCONFIRM\n" + PASSWORD,
        text=True,
        capture_output=True,
        start_new_session=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "contract_id" not in result.stdout


@pytest.mark.parametrize(
    "attack", ["missing", "signature", "payload", "revoked", "expired", "context", "source"]
)
def test_issued_contract_adversarial_lifecycle(
    operator: issuer.Issuer, attack: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    identifier = contract(operator)
    ctx = context()
    if attack == "missing":
        identifier = "f" * 64
    elif attack in {"signature", "payload"}:
        with sqlite3.connect(operator.database) as connection:
            column = "signature" if attack == "signature" else "payload"
            connection.execute(
                f"UPDATE contracts SET {column}=? WHERE id=?", (b"forged", identifier)
            )
    elif attack == "revoked":
        code, output = terminal_command(
            ["--state-dir", str(operator.directory), "revoke", "--contract-id", identifier],
            [(r"Type exactly (REVOKE RES-541 [0-9a-f]{64})", "CHALLENGE")],
        )
        assert code == 0, output
    elif attack == "expired":
        future = time.time() + issuer.LIFETIME + 1
        monkeypatch.setattr(time, "time", lambda: future)
    elif attack == "context":
        ctx = replace(ctx, case=replace(ctx.case, request="silently replaced request"))
    else:
        original = Path.read_bytes
        monkeypatch.setattr(
            Path,
            "read_bytes",
            lambda self: b"different-source" if str(self) == issuer.__file__ else original(self),
        )
    result = operator.execute(ctx, identifier, (("objective", raw()),))
    assert result["guard_status"] == "REJECTED" and result["objectives"] == []


def test_full_multiobjective_issuance_and_omitted_objective(operator: issuer.Issuer) -> None:
    objectives = [
        choices(objective_id="number"),
        choices(measurement="NONE", relationship="CAUSAL_EVIDENCE", objective_id="causality"),
    ]
    omitted = contract(operator, objectives=objectives)
    assert operator.execute(context(), omitted, (("number", raw()),))["guard_status"] == "REJECTED"
    identifier = contract(operator, objectives=objectives)
    result = operator.execute(
        context(),
        identifier,
        (("number", raw()), ("causality", raw(measurement=None, relationship="CAUSAL_EVIDENCE"))),
    )
    assert result["outcome"] == "PARTIALLY_REFUSED"
    assert [o["result"]["outcome"] for o in result["objectives"]] == ["RESULT", "REFUSED"]


def test_execution_never_reads_signing_credential_or_oracle(
    operator: issuer.Issuer, monkeypatch: pytest.MonkeyPatch
) -> None:
    identifier = contract(operator)

    def forbidden(*args: Any) -> Any:
        raise AssertionError("signing credential or oracle reached from proposal path")

    monkeypatch.setattr(issuer, "_key", forbidden)
    monkeypatch.setattr(engine, "oracle_intent", forbidden)
    ctx = context()
    ctx = replace(ctx, case=replace(ctx.case, expectation=None))  # type: ignore[arg-type]
    assert operator.execute(ctx, identifier, (("objective", raw()),))["guard_status"] == "VERIFIED"


def test_state_permissions_symlinks_and_unencrypted_keys_are_rejected(
    operator: issuer.Issuer,
) -> None:
    operator.database.chmod(0o644)
    with pytest.raises(ValueError):
        issuer.Issuer(operator.directory)
    operator.database.chmod(0o600)
    link = operator.directory.parent / "linked-state"
    link.symlink_to(operator.directory, target_is_directory=True)
    with pytest.raises(ValueError):
        issuer.Issuer(link)
    key = operator.directory.parent / "unprotected"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    with pytest.raises(ValueError, match="encrypted"):
        issuer._key(key)


def test_cli_execution_and_model_cannot_supply_issuance_fields(operator: issuer.Issuer) -> None:
    identifier = contract(operator)
    proposal = operator.directory.parent / "proposals.json"
    command = [
        sys.executable,
        "-m",
        "scripts.request_issuer",
        "--state-dir",
        str(operator.directory),
        "execute",
        "--case-id",
        "valid-positive-01",
        "--contract-id",
        identifier,
        "--proposals",
        str(proposal),
    ]
    proposal.write_text(
        json.dumps(
            [{"objective_id": "objective", "raw_json": raw(), "issuer": "model", "confirmed": True}]
        )
    )
    rejected = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert rejected.returncode != 0 and "result_value" not in rejected.stdout
    proposal.write_text(json.dumps([{"objective_id": "objective", "raw_json": raw()}]))
    accepted = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    result = json.loads(accepted.stdout)
    assert result["guard_status"] == "VERIFIED"
    assert result["objectives"][0]["result"]["result_value"] == 0.125
    assert PASSWORD not in accepted.stdout + accepted.stderr


def test_cryptographically_valid_rogue_signer_is_not_trusted(operator: issuer.Issuer) -> None:
    identifier = contract(operator)
    key = operator.directory.parent / "model-key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    with sqlite3.connect(operator.database) as connection:
        payload = connection.execute(
            "SELECT payload FROM contracts WHERE id=?", (identifier,)
        ).fetchone()[0]
        forged = subprocess.run(
            ["ssh-keygen", "-Y", "sign", "-n", issuer.NAMESPACE, "-f", str(key)],
            input=payload,
            capture_output=True,
            check=True,
        ).stdout
        connection.execute("UPDATE contracts SET signature=? WHERE id=?", (forged, identifier))
    assert (
        operator.execute(context(), identifier, (("objective", raw()),))["failure_stage"]
        == "ISSUANCE"
    )


def test_concurrent_replay_has_one_scientific_execution(operator: issuer.Issuer) -> None:
    identifier = contract(operator)
    ctx = context()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(operator.execute, ctx, identifier, (("objective", raw()),))
            for _ in range(2)
        ]
    assert sorted(f.result()["guard_status"] for f in futures) == ["REJECTED", "VERIFIED"]


def test_missing_configuration_does_not_create_authority(tmp_path: Path) -> None:
    missing = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.request_issuer",
            "--state-dir",
            str(tmp_path / "missing"),
            "execute",
            "--case-id",
            "valid-positive-01",
            "--contract-id",
            "model-invented",
            "--proposals",
            str(tmp_path / "none"),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert missing.returncode != 0 and "result_value" not in missing.stdout


def test_duplicate_operator_objectives_cannot_be_issued(operator: issuer.Issuer) -> None:
    code, _ = issue(operator, objectives=[choices(), choices()])
    assert code != 0
    with sqlite3.connect(operator.database) as connection:
        assert connection.execute("SELECT count(*) FROM contracts").fetchone()[0] == 0


def test_private_state_in_any_git_worktree_is_rejected(operator: issuer.Issuer) -> None:
    subprocess.run(["git", "init", "-q", str(operator.directory.parent)], check=True)
    with pytest.raises(ValueError, match="Git worktree"):
        issuer.Issuer(operator.directory)
