"""Verify the exact candidate wheel in a fresh environment outside the checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from scripts.build_research_cli import canonical

REFUSALS = {
    "missing-evidence": "V3_SOURCE_PROVENANCE_UNRESOLVED",
    "unsupported-operation": "COMPUTATION_NOT_REGISTERED",
    "causal-escalation": "RES70_UNSUPPORTED_CAUSAL_CLAIM",
    "practical-escalation": "RES70_UNSUPPORTED_CLAIM_ESCALATION",
}


def verify(directory: Path) -> None:
    build = json.loads((directory / "build-receipt.json").read_bytes())
    wheel = directory / build["wheel"]
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != build["wheel_sha256"]:
        raise ValueError("wheel differs from the build receipt")
    with zipfile.ZipFile(wheel) as archive:
        files = archive.namelist()
        if any(name.lower().endswith((".safetensors", ".pt", ".bin", ".jsonl")) for name in files):
            raise ValueError("wheel includes model weights or evaluation records")
        for name in ("LICENSE", "NOTICE.md"):
            if not any(path.endswith(f".dist-info/licenses/{name}") for path in files):
                raise ValueError(f"wheel omits {name}")
    with tempfile.TemporaryDirectory(prefix="dynamislm-cli-install-") as temporary:
        cwd = Path(temporary)
        python = cwd / "venv/bin/python"
        subprocess.run(["uv", "venv", "--python", sys.executable, str(cwd / "venv")], check=True)
        subprocess.run(["uv", "pip", "install", "--python", str(python), str(wheel)], check=True)
        cli = cwd / "venv/bin/dynamislm-research"
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}
        }

        def invoke(*args: str, status: int = 0) -> bytes:
            out = subprocess.run([str(cli), *args], cwd=cwd, capture_output=True, env=env)
            if out.returncode != status or out.stderr:
                raise ValueError(f"unexpected result for {args}: {out.returncode} {out.stderr!r}")
            return out.stdout

        identity = json.loads(invoke("identity"))
        identity_files = identity["included_source_file_sha256"]
        if (
            identity["source_commit"] != build["source_commit"]
            or identity["artifact_content_sha256"] != build["artifact_content_sha256"]
            or hashlib.sha256(canonical(identity_files)).hexdigest()
            != identity["artifact_content_sha256"]
        ):
            raise ValueError("source or artifact content identity differs")
        with zipfile.ZipFile(wheel) as archive:
            for name, expected in identity_files.items():
                if name.startswith(("src/dynamislm/", "scripts/", "experiments/")):
                    packaged = name.removeprefix("src/")
                    if hashlib.sha256(archive.read(packaged)).hexdigest() != expected:
                        raise ValueError(f"packaged source byte drift: {name}")
        raw = invoke("demo", "absolute-change")
        if raw != invoke("demo", "absolute-change"):
            raise ValueError("positive example is not deterministic")
        positive = json.loads(raw)
        estimate = positive["result"]["estimates"][0]
        if (
            (estimate["value"], estimate["unit"]) != (0.125, "m")
            or not positive["admission"]["operation_executed"]
            or positive["admission"]["claim_status"] != "AUTHORIZED"
        ):
            raise ValueError("registered absolute-change example differs")
        refusals = {}
        for case, expected in REFUSALS.items():
            receipt = json.loads(invoke("demo", case, status=2))
            admission = receipt["admission"]
            if (
                admission["outcome"] != "REFUSED"
                or admission["execution_authorized"]
                or admission["operation_executed"]
                or receipt["result"] is not None
                or expected not in admission["reason_codes"]
            ):
                raise ValueError(f"fail-closed control differs: {case}")
            refusals[case] = receipt
        subprocess.run(
            [
                str(python),
                "-c",
                "import importlib.util as u; "
                "assert all(u.find_spec(n) is None for n in ('torch','transformers','peft'))",
            ],
            cwd=cwd,
            env=env,
            check=True,
        )
        receipt = {
            **build,
            "distribution_version": invoke("--version").decode().strip(),
            "python": subprocess.check_output([str(python), "--version"], text=True).strip(),
            "positive_receipt": positive,
            "refusal_receipts": refusals,
        }
    with (directory / "clean-install-receipt.json").open("xb") as result:
        result.write(canonical(receipt))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    verify(args.candidate.resolve())


if __name__ == "__main__":
    main()
