"""RES-541 attempt-3 recovery V1: CPU replay of retained, digest-pinned evidence.

The inference protocol and scorer remain immutable. Only the scorer's attempt
admission, date metadata spelling and global-session check are adapted in memory, after independent
evidence admission. Scientific replay, metrics and decision rules are unchanged.
This verifier is deliberately limited to the already executed attempt 3.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import re
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts import a02_execution, a02_experiment, a02_score

RUN_ID = "res541-a02-003-cbf5476e6bceb2d023699d6e"
SOURCE_REVISION = "e35728808d3989418cb2e6867257a602a41f5ed9"
MANIFEST_SHA256 = "d1ff57dfa6f6c33036496c41f3dfa070350787c9fdd13e6eef0e1467b249dc10"
TEARDOWN_SHA256 = "83efcacdbc7c4d2b9ebac2e22c246e52402fc4c7f4818cdaed5781fd30b53ba6"
WATCHDOG_SHA256 = "1b1d95c05827805f45d36b1d3ee1c954658d190641147f94958b4aab567ae0cb"
WEIGHTS = {
    "model-00001-of-00002.safetensors": (
        4966315264,
        "e5eed4113a925264c33e3cdf76cd9f547c06a207ef2270914a7274a2bf685ffd",
    ),
    "model-00002-of-00002.safetensors": (
        1183919744,
        "6c3ad90646457295723e4da5ee8afac47006e20407b122df5174693dd8d68a43",
    ),
}


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pinned_json(path: Path, expected: str) -> dict[str, Any]:
    data = path.read_bytes()
    if _hash(data) != expected:
        raise ValueError(f"evidence digest mismatch: {path.name}")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError(f"evidence must be an object: {path.name}")
    return value


def _session_rows(text: str) -> list[tuple[str, str]]:
    if text.strip() == "[colab] No active sessions found on server.":
        return []
    rows = []
    for line in text.strip().splitlines():
        match = re.fullmatch(
            r"\[([^\]\n]+)\] (gpu-[a-z0-9-]+) \| Hardware: [A-Za-z0-9]+"
            r" \| Shape: [A-Za-z]+ \| Variant: GPU(?: \| Status: [A-Z]+)?",
            line,
        )
        if match is None:
            raise ValueError("UNKNOWN: unrecognized provider session output")
        rows.append((match[1], match[2]))
    if not rows:
        raise ValueError("UNKNOWN: missing provider session output")
    return rows


def _target_absent(
    command: dict[str, Any], target: str, endpoint: str, assignments: dict[str, Any]
) -> bool:
    if (
        command.get("command") != ["colab", "--auth=oauth2", "sessions"]
        or type(command.get("exit_code")) is not int
        or command["exit_code"] != 0
        or command.get("stderr") != ""
        or assignments.get("exit_code") != 0
        or assignments.get("stderr") != ""
    ):
        raise ValueError("UNKNOWN: authenticated provider request did not succeed")
    rows = _session_rows(command["stdout"])
    provider = json.loads(assignments["stdout"])
    if provider.get("endpoint") != "https://colab.research.google.com/tun/m/assignments":
        raise ValueError("UNKNOWN: provider assignment origin missing")
    endpoints = [row["endpoint"] for row in provider["assignments"]]
    if len(endpoints) != len(set(endpoints)) or set(endpoints) != {row[1] for row in rows}:
        raise ValueError("UNKNOWN: provider and CLI session inventories differ")
    return not any(name == target or ep == endpoint for name, ep in rows)


def verify_teardown(path: Path, run_dir: Path) -> dict[str, Any]:
    receipt = _pinned_json(path, TEARDOWN_SHA256)
    if receipt.get("schema") != "RES541_A02_TARGET_TEARDOWN_V1" or receipt.get("run_id") != RUN_ID:
        raise ValueError("wrong teardown identity")
    for base, entries in (
        (path.parent, receipt["evidence"]),
        (run_dir, receipt["original_evidence"]),
    ):
        for name, expected in entries.items():
            if Path(name).name != name:
                raise ValueError("unsafe teardown evidence path")
            data = (base / name).read_bytes()
            if len(data) != expected["bytes"] or _hash(data) != expected["sha256"]:
                raise ValueError(f"teardown supporting evidence changed: {name}")
    commands = receipt["commands_and_outputs"]
    for name, command in commands.items():
        if json.loads((path.parent / name).read_bytes()) != command:
            raise ValueError("teardown command evidence differs")
        start = datetime.fromisoformat(command["started_utc"])
        finish = datetime.fromisoformat(command["finished_utc"])
        if (
            start.tzinfo is None
            or finish.tzinfo is None
            or not 0 <= (finish - start).total_seconds() <= 40
        ):
            raise ValueError("provider observation timestamps are invalid")
    control: dict[str, Any] = json.loads((run_dir / "control.json").read_bytes())
    history = [
        json.loads(line) for line in (path.parent / "cli-events.jsonl").read_text().splitlines()
    ]
    endpoint = receipt["target_endpoint"]
    if (
        not _target_absent(
            commands["sessions.json"], RUN_ID, endpoint, commands["provider-assignments.json"]
        )
        or receipt.get("target_absent") is not True
        or receipt.get("decision") != "TARGET_STOPPED_UNRELATED_SESSION_ACTIVE"
        or control["session"] != RUN_ID
        or control["stop_exit_code"] != 0
        or history[0]["event_type"] != "session_created"
        or history[0]["endpoint"] != endpoint
        or history[-1]["event_type"] != "session_terminated"
        or history[-1]["reason"] != "user_requested"
        or receipt["termination_event"] != history[-1]
        or endpoint not in control["status_after_allocation"]
        or any(
            name == RUN_ID or ep == endpoint
            for name, ep in _session_rows(control["session_list_after_stop"])
        )
        or datetime.fromisoformat(history[-1]["timestamp"])
        > datetime.fromisoformat(control["stop_returned_utc"])
        or datetime.fromisoformat(commands["sessions.json"]["started_utc"])
        < datetime.fromisoformat(control["stop_returned_utc"])
    ):
        raise ValueError("target teardown is ACTIVE or UNKNOWN")
    return receipt


def verify_population(remote: dict[str, Any], preflight: dict[str, Any]) -> None:
    expected = Counter(
        [("historical", row["case_id"]) for row in preflight["historical_cases"]]
        + [("new", row["case_id"]) for row in preflight["new_action_cases"]]
    )
    actual = Counter((row["protocol"], row["case_id"]) for row in remote["cases"])
    if (
        len(expected) != 26
        or any(count != 1 for count in expected.values())
        or actual != expected
        or any(row.get("case_status") != "COMPLETE" for row in remote["cases"])
    ):
        raise ValueError("frozen 26-case population is missing, duplicated or incomplete")


def _decoding_equal(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    # Frozen preflight renders %d; the protocol's prose metadata omitted its leading zero.
    return actual == expected or (
        expected.get("template_date") == "3 November 2026"
        and actual == {**expected, "template_date": "03 November 2026"}
    )


def verify_originals(run_dir: Path) -> dict[str, Any]:
    manifest = _pinned_json(run_dir / "artifact-hashes.json", MANIFEST_SHA256)
    for entry in manifest["files"]:
        name = entry["name"]
        if Path(name).name != name or Path(entry["local_path"]) != run_dir / name:
            raise ValueError("original manifest identity mismatch")
        data = (run_dir / name).read_bytes()
        if name == "watchdog-receipt.json":
            # The launcher hashed STOP_REQUESTED before its asynchronous watchdog finished.
            initial = (
                json.dumps({"phase": "STOP_REQUESTED", "session": RUN_ID}, indent=2, sort_keys=True)
                + "\n"
            ).encode()
            if (
                _hash(data) != WATCHDOG_SHA256
                or len(initial) != entry["bytes"]
                or _hash(initial) != entry["sha256"]
            ):
                raise ValueError("watchdog phase discrepancy differs from reviewed evidence")
        elif len(data) != entry["bytes"] or _hash(data) != entry["sha256"]:
            raise ValueError(f"original artifact changed: {name}")
    control: dict[str, Any] = json.loads((run_dir / "control.json").read_bytes())
    binding = json.loads((run_dir / "binding.json").read_bytes())
    if (
        binding != control["binding"]
        or binding["attempt"] != 3
        or binding["run_id"] != RUN_ID
        or binding["source_revision"] != SOURCE_REVISION
        or (run_dir / "attempt-003-used.json").read_bytes()
        != a02_execution.THIRD_MARKER.read_bytes()
        or _hash((run_dir / "source.tar").read_bytes()) != binding["source_archive_sha256"]
    ):
        raise ValueError("attempt-3 marker or run binding differs")
    archive = subprocess.run(
        ["git", "archive", "--format=tar", SOURCE_REVISION],
        cwd=a02_score.ROOT,
        check=True,
        capture_output=True,
    ).stdout
    tree = subprocess.run(
        ["git", "rev-parse", f"{SOURCE_REVISION}^{{tree}}"],
        cwd=a02_score.ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if _hash(archive) != binding["source_archive_sha256"] or tree != binding["source_tree"]:
        raise ValueError("retained source differs from inference Git revision")
    remote = json.loads((run_dir / "remote-report.json").read_bytes())
    weight_rows = remote["model"]["weight_files"]
    weights = {row["name"]: (row["bytes"], row["sha256"]) for row in weight_rows}
    if len(weight_rows) != len(WEIGHTS) or weights != WEIGHTS:
        raise ValueError("weight identities differ from pinned Hub revision metadata")
    verify_population(remote, json.loads((run_dir / "tokenizer-preflight-v1.json").read_bytes()))
    return control


def adapted_scorer() -> tuple[Any, str]:
    """Exact, auditable admission-only substitutions in the digest-pinned scorer."""
    protocol = json.loads(a02_experiment.PROTOCOL_PATH.read_bytes())
    source_path = a02_score.ROOT / "scripts/a02_score.py"
    if _hash(source_path.read_bytes()) != protocol["experiment_files"]["scripts/a02_score.py"]:
        raise ValueError("frozen scorer source changed")
    source = inspect.getsource(a02_score.verify_run)
    replacements = {
        "if attempt not in (1, 2):": "if attempt not in (1, 2, 3):",
        "a02_execution.ATTEMPT_MARKER if attempt == 1 else a02_execution.REPLACEMENT_MARKER": (
            "a02_execution.THIRD_MARKER if attempt == 3 else "
            "(a02_execution.ATTEMPT_MARKER if attempt == 1 else a02_execution.REPLACEMENT_MARKER)"
        ),
        "if attempt == 2:": "if attempt in (2, 3):",
        'attempt_marker.get("attempt") != 2': 'attempt_marker.get("attempt") != attempt',
        'authorization.get("attempt") != 2': 'authorization.get("attempt") != attempt',
        "a02_execution._check_attempt(2, allow_used=True)": (
            "a02_execution._check_attempt(attempt, allow_used=True)"
        ),
        'if not control.get("session_absent_after_stop") or control.get("stop_exit_code") != 0:': (
            'if control.get("stop_exit_code") != 0:'
        ),
        'remote["runtime"].get(remote_key) != protocol["new_a02_cases"][protocol_key]': (
            'not _recovery_decoding_equal(remote["runtime"].get(remote_key), '
            'protocol["new_a02_cases"][protocol_key])'
        ),
    }
    for before, after in replacements.items():
        if source.count(before) != 1:
            raise ValueError("frozen admission boundary differs from recovery V1")
        source = source.replace(before, after)
    namespace = vars(a02_score).copy()
    namespace["_recovery_decoding_equal"] = _decoding_equal
    exec(compile(source, "<RES541_A02_RECOVERY_V1_ADMISSION_ONLY>", "exec"), namespace)
    return namespace["verify_run"], source


def inspect_cases(run_dir: Path) -> dict[str, Any]:
    """Measure observed behavior after rejection; never issue scientific qualification.

    Reuse the frozen measurement body, recording every preflight mismatch instead
    of stopping at the first one. All token checks and CPU event replay still run.
    No admission requirement, scientific threshold or verified report is changed.
    """
    adapted_scorer()  # Verify the frozen source digest before extracting its measurement body.
    protocol = json.loads(a02_experiment.PROTOCOL_PATH.read_bytes())
    a02_experiment.verify_protocol_source_bindings(protocol)
    from transformers import AutoTokenizer  # type: ignore[import-not-found]

    directory = a02_score.E_ROOT / "a01/tokenizer"
    for name, expected in protocol["model"]["tokenizer_files"].items():
        if _hash((directory / name).read_bytes()) != expected:
            raise ValueError("local tokenizer asset changed")
    tokenizer = AutoTokenizer.from_pretrained(
        directory, local_files_only=True, trust_remote_code=False, use_fast=True
    )
    baseline, hashes = a02_score._a01_baseline(protocol)
    source = inspect.getsource(a02_score.verify_run)
    body = source[source.index("    historical_ids =") : source.index("    critical_ok =")]
    refusal = 'raise ValueError(f"action prompt differs from CPU preflight: {case_id}")'
    if body.count(refusal) != 1:
        raise ValueError("frozen diagnostic boundary changed")
    body = body.replace(refusal, "prompt_mismatches.append(case_id)")
    source = (
        "def observed_diagnostics(remote, preflight, protocol, "
        "a01_report, a01_hashes, tokenizer):\n"
        "    prompt_mismatches = []\n"
        + body
        + "    return dict(metrics=metrics, case_results=verified_rows, "
        "paired_a01_comparison=paired_a01, frozen_prompt_mismatches=prompt_mismatches)\n"
    )
    namespace = vars(a02_score).copy()
    exec(compile(source, "<RES541_UNQUALIFIED_OBSERVED_DIAGNOSTICS>", "exec"), namespace)
    result: dict[str, Any] = namespace["observed_diagnostics"](
        json.loads((run_dir / "remote-report.json").read_bytes()),
        json.loads((run_dir / "tokenizer-preflight-v1.json").read_bytes()),
        protocol,
        baseline,
        hashes,
        tokenizer,
    )
    return {
        "schema": "RES541_A02_UNQUALIFIED_OBSERVED_DIAGNOSTICS_V1",
        "scientific_qualification": False,
        "scope": "Observed synthetic development behavior; frozen prompt conformance failed",
        "measurement_source_sha256": _hash(source.encode()),
        **result,
    }


def recover(run_dir: Path, teardown: Path, output_dir: Path) -> dict[str, Any]:
    run_dir, teardown, output_dir = map(a02_score._under_e, (run_dir, teardown, output_dir))
    if output_dir == run_dir or output_dir.is_relative_to(run_dir) or output_dir.exists():
        raise ValueError("recovery outputs require a new directory outside original evidence")
    control = verify_originals(run_dir)
    adjudication = verify_teardown(teardown, run_dir)
    scorer, source = adapted_scorer()
    validation_error = None
    try:
        report = scorer(
            run_dir / "remote-report.json",
            run_dir / "control.json",
            run_dir / "tokenizer-preflight-v1.json",
            output_dir,
        )
    except ValueError as exc:
        validation_error = str(exc)
        diagnostics = inspect_cases(run_dir)
        output_dir.mkdir(parents=True)
        (output_dir / "unqualified-observed-diagnostics.json").write_text(
            json.dumps(diagnostics, indent=2, sort_keys=True, allow_nan=False) + "\n"
        )
        report = {"terminal_outcome": None, "verified_report_sha256": None}
    (output_dir / "admission-adapted-scorer.py").write_text(source)
    qualification = {
        "schema": "RES541_A02_RECOVERY_QUALIFICATION_V1",
        "disposition": (
            "A02_ATTEMPT3_EVIDENCE_VALIDATION_FAILED"
            if validation_error
            else "A02_ATTEMPT3_SCIENTIFIC_NO_GO"
            if report["terminal_outcome"] == "STAGE_A_SCIENTIFIC_NO_GO"
            else "A02_ATTEMPT3_SCIENCE_RECOVERED_AND_VERIFIED"
        ),
        "validation_error": validation_error,
        "run_id": RUN_ID,
        "scientific_decision": report["terminal_outcome"],
        "inference_source_revision": SOURCE_REVISION,
        "recovery_source_revision": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=a02_score.ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "recovery_verifier_sha256": _hash(Path(__file__).read_bytes()),
        "admission_adapted_scorer_sha256": _hash(source.encode()),
        "frozen_scorer_sha256": _hash(Path(a02_score.__file__).read_bytes()),
        "teardown_adjudication_sha256": _hash(teardown.read_bytes()),
        "teardown_decision": adjudication["decision"],
        "original_control_sha256": _hash((run_dir / "control.json").read_bytes()),
        "original_session_absent_after_stop": control["session_absent_after_stop"],
        "original_watchdog_phase": control["watchdog_phase"],
        "verified_report_sha256": report["verified_report_sha256"],
        "account_compute_unit_delta_attribution": "SHARED_ACCOUNT_NOT_ATTRIBUTABLE_TO_A02",
        "decoding_metadata_discrepancy": (
            "3/03 November 2026: metadata spelling only; rendered prompts and token IDs "
            "must still match frozen preflight exactly"
        ),
        "watchdog_manifest_discrepancy": (
            "INITIAL_STOP_REQUESTED_HASH_REPRODUCED_FINAL_BYTES_SEPARATELY_PINNED"
        ),
        "scientific_scope": "SYNTHETIC_DEVELOPMENT_DIAGNOSTICS_NOT_FORMAL_PSE",
    }
    (output_dir / "recovery-qualification.json").write_text(
        json.dumps(qualification, indent=2, sort_keys=True) + "\n"
    )
    return qualification


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--teardown", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    qualification = recover(args.run_dir, args.teardown, args.output_dir)
    print(json.dumps(qualification, indent=2))
    return 2 if qualification["validation_error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
