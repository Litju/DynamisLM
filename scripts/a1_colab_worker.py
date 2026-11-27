"""A1 Colab worker (RES-832): resumable, multi-phase, hash-chained inference in one session.

Runs inside the allocated T4. Phases:

``bootstrap``  verify payload, unpacks source, installs the pinned inference environment and
               PEFT overlay, probes the runtime, and writes the environment receipt.
``download``   downloads the pinned public base revision, verifies every file digest, and writes
               the base receipt.
``run``        loads the FP32 model once and executes the frozen arms in priority order until
               the phase deadline. Every call is committed to its arm's hash chain.
``status``     prints the current per-arm progress as JSON.
``cleanup``    removes the work tree.

No gold, no reference answer and no adjudication metadata is present in the payload. The worker
cannot read them: they are not uploaded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

WORK = Path("/content/a1")
PAYLOAD = Path("/content/a1-payload.tar")
SOURCE = WORK / "source"
BASE = WORK / "base"
OUT = WORK / "runs"
EVIDENCE = WORK / "evidence.tar"
MODEL_ID = "HuggingFaceTB/SmolLM3-3B"
MODEL_REVISION = "a07cc9a04f16550a088caea529712d1d335b0ac1"
PINNED_TORCH = "2.14.1+cu130"


def _use_source() -> None:
    """The source checkout is the only import root for every phase."""
    for entry in (str(SOURCE / "src"), str(SOURCE)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    os.chdir(SOURCE)
    os.environ["PYTHONPATH"] = str(SOURCE / "src")


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_extract(archive: Path, destination: Path) -> None:
    with tarfile.open(archive) as source:
        members = source.getmembers()
        if not members or any(
            member.name.startswith("/") or ".." in Path(member.name).parts for member in members
        ):
            raise ValueError("payload archive contains an unsafe path")
        source.extractall(destination, filter="data")


def verify_payload() -> dict[str, Any]:
    expected = os.environ["A1_PAYLOAD_SHA256"]
    if sha256(PAYLOAD) != expected:
        raise ValueError("payload differs from the approved digest")
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(mode=0o700)
    safe_extract(PAYLOAD, WORK)
    safe_extract(WORK / "source.tar", SOURCE)
    return {
        "payload_sha256": expected,
        "source_tar_sha256": sha256(WORK / "source.tar"),
        "manifest_sha256": sha256(WORK / "call-manifest.json"),
        "bundle_tar_sha256": sha256(WORK / "bundle.tar"),
        "members": sorted(path.name for path in WORK.iterdir()),
    }


def install_environment() -> dict[str, Any]:
    _use_source()
    from scripts import a02_remote as remote

    remote.WORK.mkdir(mode=0o700, exist_ok=True)
    uv = remote._install_uv()
    python = remote._setup_inference(uv, SOURCE)
    uv_bin = Path("/content/a02/uv-venv/bin/uv")
    remote._run(
        [
            str(uv_bin),
            "pip",
            "install",
            "--python",
            str(python),
            "--no-deps",
            "--only-binary=:all:",
            "-r",
            "experiments/a02/training-requirements-v1.txt",
        ],
        cwd=SOURCE,
        timeout=180,
        stage="PEFT_PINNED_INSTALL",
    )
    probe = (
        "import json, torch, transformers, peft, tokenizers, sys;"
        "p=torch.cuda.get_device_properties(0); f,t=torch.cuda.mem_get_info(0);"
        "print(json.dumps({'python': sys.version.split()[0],"
        "'torch': torch.__version__, 'cuda': torch.version.cuda,"
        "'transformers': transformers.__version__, 'peft': peft.__version__,"
        "'tokenizers': tokenizers.__version__, 'cuda_available': torch.cuda.is_available(),"
        "'device_count': torch.cuda.device_count(), 'gpu_name': p.name,"
        "'compute_capability': list(torch.cuda.get_device_capability(0)),"
        "'total_vram_bytes': int(t), 'free_vram_bytes': int(f)}))"
    )
    observed = json.loads(
        remote._run([str(python), "-c", probe], cwd=SOURCE, timeout=60, stage="RUNTIME_PROBE")
    )
    if observed["torch"] != PINNED_TORCH or observed["cuda"] != "13.0":
        remote._run(
            [
                str(uv_bin),
                "pip",
                "install",
                "--python",
                str(python),
                "--only-binary=:all:",
                "torch==2.14.1",
                "--index-url",
                "https://download.pytorch.org/whl/cu130",
            ],
            cwd=SOURCE,
            timeout=1200,
            stage="TORCH_PINNED_INSTALL",
        )
        observed = json.loads(
            remote._run(
                [str(python), "-c", probe], cwd=SOURCE, timeout=60, stage="RUNTIME_PROBE_RETRY"
            )
        )
    if (
        observed["torch"] != PINNED_TORCH
        or observed["transformers"] != "4.53.0"
        or observed["peft"] != "0.16.0"
        or observed["tokenizers"] != "0.21.1"
        or observed["cuda_available"] is not True
        or observed["device_count"] != 1
    ):
        raise ValueError(f"pinned runtime differs: {observed}")
    if (
        "T4" not in observed["gpu_name"]
        or observed["total_vram_bytes"] < 12 * 1024**3
        or observed["free_vram_bytes"] < 14 * 1024**3
    ):
        raise ValueError("T4 VRAM qualification differs")
    return {
        "observed": observed,
        "python": str(python),
        "gpu": {
            "name": observed["gpu_name"],
            "compute_capability": observed["compute_capability"],
            "total_vram_bytes": observed["total_vram_bytes"],
            "free_vram_bytes_before_load": observed["free_vram_bytes"],
        },
    }


def _tokenizer_files() -> dict[str, str]:
    data = json.loads((SOURCE / "experiments/a02/tokenizer-files-v1.json").read_text())
    files: dict[str, str] = data["files"]
    return files


def download_base() -> dict[str, Any]:
    _use_source()
    from huggingface_hub import snapshot_download

    from scripts import a03_model_core as d0

    BASE.mkdir(mode=0o700)
    snapshot_download(
        MODEL_ID,
        revision=MODEL_REVISION,
        local_dir=BASE,
        token=False,
        allow_patterns=sorted(d0.MODEL_FILES | _tokenizer_files()),
    )
    d0.verify_files(BASE, d0.MODEL_FILES | _tokenizer_files())
    return {
        "model": MODEL_ID,
        "revision": MODEL_REVISION,
        "files": {
            name: sha256(BASE / name) for name in sorted(d0.MODEL_FILES | _tokenizer_files())
        },
    }


def _python() -> str:
    return "/content/a02/inference-venv/bin/python"


class _Backend:
    """Adapter dispatcher: the runner selects M0/M1 per arm through this wrapper."""

    def __init__(self, backend: Any) -> None:
        self.backend = backend
        self.tokenizer = backend.tokenizer
        self._model = "M1"

    def set_model(self, model: str) -> None:
        self._model = model

    def generate(
        self, arm: str, request: dict[str, Any], prompt: list[int], deadline: float
    ) -> Any:
        with self.backend.adapted(self._model):
            return self.backend.generate(arm, request, prompt, deadline)


def _open(seconds: float) -> tuple[Any, _Backend, Any]:
    _use_source()
    from scripts import a1_backend, a1_run

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    started = time.monotonic()
    backend = a1_backend.A1Backend("cuda", WORK / "adapter-work")
    backend.setup_seconds = round(time.monotonic() - started, 3)
    return a1_run, _Backend(backend), backend


def run_phase(seconds: float) -> dict[str, Any]:
    _use_source()
    from scripts import a02_v3_contract as v3
    from scripts import a1_backend, a1_manifest

    claim = os.environ["A1_MANIFEST_SHA256"]
    manifest_bytes = (WORK / "call-manifest.json").read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != claim:
        raise ValueError("call manifest bytes differ from the approved digest")
    manifest = v3.json_object(manifest_bytes.decode())
    if manifest != a1_manifest.load_manifest():
        raise ValueError("call manifest differs from the frozen source manifest")
    runner, backend, real = _open(seconds)
    ident = {
        **a1_backend.identity("cuda"),
        "runtime": real.runtime if hasattr(real, "runtime") else None,
    }
    order_all = a1_manifest.all_conditions(manifest)
    order = [c for c in order_all if c["role"] != "SHORTCUT_PROBE"]
    order += [c for c in order_all if c["role"] == "SHORTCUT_PROBE"]
    OUT.mkdir(mode=0o700, exist_ok=True)
    deadline = time.monotonic() + seconds
    receipts = []
    for condition in order:
        if time.monotonic() >= deadline:
            break
        backend.set_model(condition["model"])
        receipt = runner.run_arm(
            backend,
            condition,
            identity=ident,
            root=OUT,
            deadline_seconds=max(60.0, deadline - time.monotonic()),
        )
        receipts.append(receipt)
        write(WORK / "progress.json", {"phase": "run", "receipts": receipts})
        if not receipt["complete"]:
            break
    write(
        WORK / "run-receipt.json",
        {
            "receipts": receipts,
            "seconds": seconds,
            "measurements": real.measurements(),
            "complete": all(r["complete"] for r in receipts) and len(receipts) == len(order),
        },
    )
    write(WORK / "phase.json", {"phase": "RUN_PHASE_COMPLETE"})
    return {"receipts": receipts, "measurements": real.measurements()}


def status() -> dict[str, Any]:
    result = {}
    if OUT.is_dir():
        for path in sorted(OUT.glob("*.jsonl")):
            lines = [line for line in path.read_bytes().split(b"\n") if line]
            result[path.stem] = len(lines)
    phase = {}
    if (WORK / "phase.json").is_file():
        phase = json.loads((WORK / "phase.json").read_text())
    return {"arms": result, "phase": phase, "error": _error()}


def _error() -> dict[str, Any] | None:
    path = WORK / "error.json"
    return json.loads(path.read_text()) if path.is_file() else None


def evidence() -> None:
    if EVIDENCE.exists():
        EVIDENCE.unlink()
    with tarfile.open(EVIDENCE, "w") as archive:
        for path in sorted(WORK.rglob("*")):
            if not path.is_file() or path == EVIDENCE or path.name == ".writer.lock":
                continue
            if path.is_relative_to(WORK / "base") or path.is_relative_to(WORK / "source"):
                continue
            if path.is_relative_to(WORK / "adapter-work"):
                continue
            if path.name == "resume.tar":
                continue
            archive.add(path, arcname=path.relative_to(WORK).as_posix())


def evidence_phase() -> dict[str, Any]:
    """Package run files so partial progress survives a session boundary."""
    if not OUT.is_dir():
        raise ValueError("no run directory exists yet")
    evidence()
    return {
        "evidence_sha256": sha256(EVIDENCE),
        "arms": {
            path.stem: len([line for line in path.read_bytes().split(b"\n") if line])
            for path in sorted(OUT.glob("*.jsonl"))
        },
    }


def resume_phase() -> dict[str, Any]:
    """Unpack a prior evidence archive into the run directory of a fresh session."""
    archive = WORK / "resume.tar"
    if not archive.is_file():
        raise ValueError("resume archive is missing")
    OUT.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tarfile.open(archive) as source:
        for member in source.getmembers():
            if not member.isfile() or not member.name.startswith("runs/"):
                continue
            name = Path(member.name).name
            if not name.endswith(".jsonl"):
                continue
            handle = source.extractfile(member)
            if handle is None:
                continue
            (OUT / name).write_bytes(handle.read())
    write(WORK / "phase.json", {"phase": "RESUME_COMPLETE"})
    return status()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "phase",
        nargs="?",
        choices=("bootstrap", "resume", "download", "run", "status", "evidence", "cleanup"),
    )
    parser.add_argument(
        "--seconds", type=float, default=float(os.environ.get("A1_SECONDS", "0") or 0)
    )
    args = parser.parse_args()
    # `colab exec --file` runs the file with no positional arguments, so the phase arrives in the
    # environment. Accept both forms and refuse an ambiguous or missing phase.
    phase = args.phase or os.environ.get("A1_PHASE")
    if phase not in {
        "bootstrap",
        "resume",
        "download",
        "run",
        "status",
        "evidence",
        "cleanup",
    }:
        parser.error("phase must be given as an argument or in A1_PHASE")
    args.phase = phase
    started = time.monotonic()
    status_code = 0
    try:
        if args.phase == "bootstrap":
            write(WORK / "payload.json", verify_payload())
            write(WORK / "environment.json", install_environment())
            write(WORK / "phase.json", {"phase": "SETUP_COMPLETE"})
        elif args.phase == "download":
            write(WORK / "base.json", download_base())
            write(WORK / "phase.json", {"phase": "BASE_COMPLETE"})
        elif args.phase == "run":
            run_phase(args.seconds)
        elif args.phase == "status":
            print(json.dumps(status(), sort_keys=True))
        elif args.phase == "resume":
            print(json.dumps(resume_phase(), sort_keys=True))
        elif args.phase == "evidence":
            print(json.dumps(evidence_phase(), sort_keys=True))
        else:
            shutil.rmtree(WORK)
            return 0
    except Exception as exc:
        status_code = 1
        WORK.mkdir(mode=0o700, exist_ok=True)
        write(
            WORK / "error.json",
            {
                "phase": args.phase,
                "error_type": type(exc).__name__,
                "message": str(exc)[:4000],
                "elapsed_seconds": round(time.monotonic() - started, 3),
            },
        )
    finally:
        if args.phase not in {"cleanup", "status", "evidence", "resume"} and WORK.exists():
            try:
                evidence()
            except Exception as exc:
                print(f"EVIDENCE_PACKAGING_FAILED={type(exc).__name__}:{exc}", file=sys.stderr)
        if args.phase == "run" and (WORK / "phase.json").exists():
            print((WORK / "phase.json").read_text(), end="")
    return status_code


if __name__ == "__main__":
    raise SystemExit(main())
