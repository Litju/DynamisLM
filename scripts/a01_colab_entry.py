"""Standalone Colab bootstrap for the explicitly selected A0.1 suite."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.request import urlopen

RUNTIME_SHA256 = "727b19ae028ec62cd7cf6df1622fa56317bffdaf0f294c16ff6f620869c0a74c"
_RUNTIME: Any = None


def runtime_module() -> Any:
    if _RUNTIME is not None:
        return _RUNTIME
    from scripts import a01_runtime

    return a01_runtime


A0_ENTRY_SHA256 = "3150cba8d6f75092e928eb207bad12dbb360b36614289609b931b6d77bcbb123"


def adapt(module: ModuleType, suite: str, count: int) -> ModuleType:
    """Reuse the frozen bootstrap with A0.1 routing and failure diagnostics."""
    original_run = module._run
    compatibility = runtime_module()

    def check() -> bool:
        compatibility.qualify(observed_runtime)
        return True

    compatibility.adapt_gate(
        module, "a0_colab_entry", Path(str(module.__file__)).read_bytes(), check
    )
    original_preflight = module._preflight
    retained: dict[str, Any] = {}
    observed_runtime: dict[str, Any] = {}

    def preflight() -> Any:
        observed_runtime.update(compatibility.inventory())
        compatibility.immutable(
            inventory_path,
            {
                "schema": "RES541_A01_RUNTIME_INVENTORY_V1",
                "source_revision": revision_id,
                "run_id": session_id,
                **compatibility.binding(),
                "inventory": observed_runtime,
            },
        )
        try:
            compatibility.qualify(observed_runtime)
        except ValueError as exc:
            raise module.A0Error("GPU_PREFLIGHT", "RUNTIME_INCOMPATIBLE") from exc
        return original_preflight()

    module.__dict__["_preflight"] = preflight

    def dispatch(command: list[str], **kwargs: Any) -> str:
        replacement = list(command)
        if len(command) > 2 and command[1].endswith("/scripts/a0_engine.py"):
            if command[2] == "prepare":
                replacement = [
                    command[0],
                    "-m",
                    "scripts.a01_execution",
                    "prepare",
                    "--suite",
                    suite,
                    "--cases",
                    str(count),
                    *command[3:],
                ]
            elif command[2] == "score":
                replacement = [
                    command[0],
                    "-m",
                    "scripts.a01_execution",
                    "score",
                    "--suite",
                    suite,
                    "--cases",
                    str(count),
                    *command[3:],
                ]
            else:
                raise ValueError("unknown A0 engine command in A0.1 bootstrap")
        elif len(command) > 1 and command[1].endswith("/scripts/a0_colab_inference.py"):
            replacement = [command[0], "-m", "scripts.a01_inference", *command[2:]]
        if "scripts.a01_execution" in replacement or "scripts.a01_inference" in replacement:
            kwargs["env"] = {**(kwargs.get("env") or os.environ), "RES541_A01_REMOTE": "1"}
        try:
            result = str(original_run(replacement, **kwargs))
            if "scripts.a01_execution" in replacement and "prepare" in replacement:
                path = Path(replacement[replacement.index("--output") + 1])
                prepared = json.loads(path.read_text())
                prepared["bootstrap_inventory"] = observed_runtime
                prepared["run_id"] = session_id
                path.write_text(json.dumps(prepared, sort_keys=True) + "\n")
            return result
        finally:
            if "scripts.a01_inference" in replacement:
                path = Path(replacement[replacement.index("--output") + 1])
                if path.exists() and path.stat().st_size <= 2 * 1024**2:
                    retained["model_outputs"] = json.loads(path.read_text())

    module.__dict__["_run"] = dispatch
    original = module.run

    revision_id = session_id = ""
    inventory_path = Path("/nonexistent")

    def run(revision: str, run_id: str, report_path: Path) -> int:
        nonlocal revision_id, session_id, inventory_path
        revision_id, session_id = revision, run_id
        inventory_path = report_path.with_suffix(".inventory.json")
        if report_path.exists() or inventory_path.exists():
            raise ValueError("immutable A0.1 runtime report already exists")
        code = int(original(revision, run_id, report_path))
        report = json.loads(report_path.read_text())
        report.update(retained)
        report["schema"] = "RES541_A01_REPORT_V1"
        report["execution_version"] = compatibility.VERSION
        report.update(compatibility.binding())
        report["runtime_inventory"] = observed_runtime
        report["suite"] = suite
        report["approved_case_count"] = count
        report["run_id"] = run_id
        if "failure_stage" in report:
            report["runtime_preflight"] = {
                **observed_runtime,
                **report.get("runtime_preflight", {}),
            }
            print(
                f"RES-541 A0.1 stopped at {report['failure_stage']}: "
                f"{report['failure_category']}; observed runtime={observed_runtime}",
                file=sys.stderr,
            )
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        if report_path.stat().st_size > 2 * 1024**2:
            raise ValueError("A0.1 report exceeds the inherited artifact bound")
        return code

    module.__dict__["run"] = run
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--report-path", type=Path, required=True)
    parser.add_argument("--suite", choices=("a0_diagnostic", "a01_controls"), required=True)
    parser.add_argument("--cases", type=int, required=True)
    args = parser.parse_args()
    count = 16 if args.suite == "a0_diagnostic" else 12
    if args.cases != count or re.fullmatch(r"[0-9a-f]{40}", args.source_revision) is None:
        parser.error("invalid exact source revision or approved suite count")
    # Colab uploads one script. Fetch only the immutable bootstrap before its full source clone.
    url = (
        f"https://raw.githubusercontent.com/Litju/DynamisLM/{args.source_revision}"
        "/scripts/a0_colab_entry.py"
    )
    with urlopen(url, timeout=30) as response:
        source = response.read(64 * 1024 + 1)
    if hashlib.sha256(source).hexdigest() != A0_ENTRY_SHA256:
        raise ValueError("immutable A0 bootstrap SHA-256 mismatch")
    global _RUNTIME
    runtime_url = url.rsplit("/", 1)[0] + "/a01_runtime.py"
    with urlopen(runtime_url, timeout=30) as response:
        runtime_source = response.read(64 * 1024 + 1)
    if hashlib.sha256(runtime_source).hexdigest() != RUNTIME_SHA256:
        raise ValueError("A0.1 runtime adapter SHA-256 mismatch")
    _RUNTIME = ModuleType("_a01_runtime")
    exec(compile(runtime_source, "a01_runtime.py", "exec"), _RUNTIME.__dict__)
    with tempfile.TemporaryDirectory(prefix="res541-a01-bootstrap-") as temporary:
        path = Path(temporary) / "a0_colab_entry.py"
        path.write_bytes(source)
        module = ModuleType("_a01_bootstrap")
        module.__file__ = str(path)
        exec(compile(source, str(path), "exec"), module.__dict__)
        return int(
            adapt(module, args.suite, count).run(
                args.source_revision, args.run_id, args.report_path
            )
        )


if __name__ == "__main__":
    raise SystemExit(main())
