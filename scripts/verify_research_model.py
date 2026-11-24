"""Qualify a clean model-extra installation against the retained RES-746 CPU commitment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from importlib.metadata import distributions
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CPU_INDEX = "https://download.pytorch.org/whl/cpu"
CONSTRAINTS = ROOT / "packaging/research-model-constraints.txt"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compare(reference: dict[str, Any], actual: dict[str, Any]) -> None:
    proposal = actual["proposal"]
    if (
        proposal["raw"].encode() != reference["raw"].encode()
        or proposal["raw_sha256"] != reference["raw_sha256"]
        or proposal["token_ids"] != reference["ids"]
        or proposal["termination"] != reference["termination"]
        or proposal["prompt_sha256"] != reference["rendered_prompt_sha256"]
    ):
        raise ValueError("installed C1 generation differs from the pinned RES-746 CPU reference")


def qualify(directory: Path, archive: Path, base: Path, reference: Path, output: Path) -> None:
    from scripts import research_ask as research
    from scripts.alpha_adapter_bundle import verified_payload
    from scripts.research_scenarios import SyntheticScenario, packaged_scenario

    if not Path(research.__file__).resolve().is_relative_to(sys.prefix):
        raise ValueError("qualification imported checkout code instead of the installed wheel")
    cli = Path(sys.executable).with_name("dynamislm-research")
    wheel = json.loads((directory / "build-receipt.json").read_bytes())
    identity = json.loads(subprocess.check_output([str(cli), "identity"]))
    if (
        identity["source_commit"] != wheel["source_commit"]
        or identity["artifact_content_sha256"] != wheel["artifact_content_sha256"]
    ):
        raise ValueError("installed CLI identity differs from the wheel receipt")

    payload, _ = verified_payload(archive)
    manifest = json.loads(payload["MANIFEST.json"])
    expected = manifest["evaluation"]["res746"]["cpu_output_commit_sha256"]
    commitment = (reference / "out-cpu/output-commit.json").read_bytes()
    if digest(commitment) != expected:
        raise ValueError("RES-746 CPU output commitment differs")
    commit = json.loads(commitment)
    run_data = (reference / "blind-cpu/run.json").read_bytes()
    requests = (reference / "blind-cpu/requests.jsonl").read_bytes()
    outputs = (reference / "out-cpu/outputs.jsonl").read_bytes()
    if (
        digest(run_data) != commit["run_sha256"]
        or digest(requests) != json.loads(run_data)["blind_requests_sha256"]
        or digest(outputs) != commit["outputs_sha256"]
    ):
        raise ValueError("retained CPU inputs or outputs differ from their commitment")
    questions = {row["item_id"]: row["question"] for row in map(json.loads, requests.splitlines())}
    records = {row["item"]: row["record"] for row in map(json.loads, outputs.splitlines())}
    base_identity = json.loads(
        subprocess.check_output([str(cli), "verify-base", "--base", str(base)])
    )
    positive = subprocess.run(
        [
            str(cli),
            "ask",
            "--scenario",
            "absolute-change",
            "--question",
            questions["research-cli"],
            "--bundle",
            str(archive),
            "--base",
            str(base),
            "--device",
            "cpu",
        ],
        capture_output=True,
        check=True,
        timeout=1500,
    )
    report = json.loads(positive.stdout)
    compare(records["research-cli|C1"], report)
    estimate = report["result"]["estimates"][0]
    if (
        (estimate["value"], estimate["unit"]) != (0.125, "m")
        or not report["admission"]["operation_executed"]
        or report["admission"]["outcome"] != "GROUNDED_RESULT"
        or b"Authorized calculation for the proposal: 0.125 m" not in positive.stderr
        or report["identity"]["base"] != base_identity
    ):
        raise ValueError("installed CLI did not ground the expected registered result")

    runtime = research.open_runtime(archive, base, "cpu")
    unresolved, code = research.ask(
        SyntheticScenario("d0-62-unresolved", None, ()), questions["d0-62-unresolved"], runtime
    )
    compare(records["d0-62-unresolved|C1"], unresolved)
    if (
        code != 2
        or unresolved["admission"]["outcome"] != "ABSTAINED"
        or unresolved["admission"]["reason_codes"] != ["V3_NO_ACTION_PROPOSED"]
        or unresolved["admission"]["operation_executed"]
        or unresolved["result"] is not None
    ):
        raise ValueError("installed runtime did not preserve the unresolved abstention")
    refusal, code = research.ask(
        packaged_scenario("missing-evidence"), questions["research-cli"], runtime
    )
    if (
        code != 2
        or refusal["admission"]["outcome"] != "REFUSED"
        or refusal["admission"]["reason_codes"] != ["V3_SOURCE_PROVENANCE_UNRESOLVED"]
        or refusal["admission"]["operation_executed"]
        or refusal["result"] is not None
    ):
        raise ValueError("installed runtime did not refuse the unbound evidence")
    receipt = {
        "scope": "DEVELOPMENT_ONLY",
        "status": "PASS",
        "wheel": wheel,
        "python": sys.version,
        "installed_dependencies": {
            distribution.metadata["Name"]: distribution.version for distribution in distributions()
        },
        "reference_cpu_output_commit_sha256": expected,
        "raw_token_and_prompt_parity": ["research-cli", "d0-62-unresolved"],
        "positive": report,
        "abstention": unresolved,
        "refusal": refusal,
        "positive_human_report": positive.stderr.decode(),
    }
    with output.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")


def install(
    directory: Path, archive: Path, base: Path, reference: Path, output: Path, offline: bool
) -> None:
    wheel_receipt = json.loads((directory / "build-receipt.json").read_bytes())
    wheel = directory / wheel_receipt["wheel"]
    if digest(wheel.read_bytes()) != wheel_receipt["wheel_sha256"]:
        raise ValueError("wheel differs from its build receipt")
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}
    }
    env.update(
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        PYTHONNOUSERSITE="1",
        OMP_NUM_THREADS="4",
        MKL_NUM_THREADS="4",
    )
    with tempfile.TemporaryDirectory(prefix="dynamislm-model-install-") as temporary:
        cwd = Path(temporary)
        venv = cwd / "venv"
        python = venv / "bin/python"
        subprocess.run(["uv", "venv", "--python", sys.executable, str(venv)], cwd=cwd, check=True)
        pip = ["uv", "pip", "install", "--python", str(python), *(["--offline"] if offline else [])]
        subprocess.run(
            [*pip, "--index", CPU_INDEX, "--no-deps", "torch==2.14.1+cpu"],
            cwd=cwd,
            env=env,
            check=True,
        )
        subprocess.run(
            [*pip, "--constraint", str(CONSTRAINTS), f"{wheel}[model]"],
            cwd=cwd,
            env=env,
            check=True,
        )
        subprocess.run(
            ["uv", "pip", "check", "--python", str(python)], cwd=cwd, env=env, check=True
        )
        subprocess.run(
            [
                str(python),
                "-I",
                str(Path(__file__).resolve()),
                "--installed",
                str(directory),
                str(archive),
                str(base),
                str(reference),
                str(output),
            ],
            cwd=cwd,
            env=env,
            check=True,
            timeout=4200,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("archive", type=Path)
    parser.add_argument("base", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--installed", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    paths = (
        args.directory.resolve(),
        args.archive.resolve(),
        args.base.resolve(),
        args.reference.resolve(),
        args.output.resolve(),
    )
    if args.installed:
        qualify(*paths)
    else:
        install(*paths, offline=args.offline)


if __name__ == "__main__":
    main()
