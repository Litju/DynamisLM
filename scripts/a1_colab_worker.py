"""A1 Colab worker (RES-832): resumable, multi-phase, hash-chained inference in one session.

Runs inside the allocated T4 under the pinned inference interpreter. Phases:

``bootstrap``  verify the payload digest, unpack the minimal source and work order, install the
               pinned inference environment and PEFT overlay, probe the runtime, and write the
               environment receipt.
``download``   download the pinned public base revision, verify every file digest, and write the
               base receipt.
``verify``     tokenize every frozen request straight from the transported payload and compare
               the tokenizer-level digest with the seal. No model and no local evaluation data.
``smoke``      load the real model once and execute the four development-only smoke calls
               (M0 native, M0 constrained, M1 native, M1 constrained) through the real backend.
``run``        execute the frozen work order in priority order under one cumulative session
               deadline, committing every call to its arm's hash chain.
``campaign``   one process: verify, smoke when not yet complete, then run under one model load and
               one cumulative deadline. This is the phase the controller uses, so a successful
               smoke continues into the frozen factorial in the same session.
``status``     print the current per-arm progress as JSON.
``evidence``   package run files so partial progress survives a session boundary.
``resume``     unpack a prior evidence archive into the run directory of a fresh session.
``cleanup``    remove the work tree.

No gold, no reference answer, no adjudication metadata and no authored evaluation case is in the
payload. The worker cannot read them: they were never uploaded.
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
SMOKE_OUT = WORK / "smoke"
EVIDENCE = WORK / "evidence.tar"
MODEL_ID = "HuggingFaceTB/SmolLM3-3B"
MODEL_REVISION = "a07cc9a04f16550a088caea529712d1d335b0ac1"
PINNED_TORCH = "2.14.1+cu130"
PINNED_PYTHON = Path("/content/a02/inference-venv/bin/python")
PINNED_UV = Path("/content/a02/uv-venv/bin/uv")
PHASES = (
    "bootstrap",
    "resume",
    "download",
    "verify",
    "smoke",
    "run",
    "campaign",
    "status",
    "evidence",
    "cleanup",
)
# Teardown and evidence packaging are reserved out of the generation budget by the controller.
MIN_GENERATION_SECONDS = 60.0


def _use_source() -> None:
    """The payload source checkout is the only import root for every phase."""
    for entry in (str(SOURCE), str(SOURCE / "src")):
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
        "work_order_sha256": sha256(WORK / "work-order.json"),
        "bundle_tar_sha256": sha256(WORK / "bundle.tar"),
        "members": sorted(path.name for path in WORK.iterdir()),
    }


def install_environment() -> dict[str, Any]:
    _use_source()
    from scripts import a02_remote as remote

    remote.WORK.mkdir(mode=0o700, exist_ok=True)
    uv = remote._install_uv()
    python = remote._setup_inference(uv, SOURCE)
    remote._run(
        [
            str(PINNED_UV),
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
        "print(json.dumps({'executable': sys.executable,"
        "'python': sys.version.split()[0],"
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
                str(PINNED_UV),
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
    if Path(observed["executable"]).resolve() != python.resolve():
        raise ValueError("runtime probe did not run under the pinned inference interpreter")
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
        "uv": str(PINNED_UV),
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
        "path": str(BASE),
        "files": {
            name: sha256(BASE / name) for name in sorted(d0.MODEL_FILES | _tokenizer_files())
        },
    }


def work_order() -> dict[str, Any]:
    """The transported frozen work order, re-verified against its own digests."""
    _use_source()
    from scripts import a02_v3_contract as v3
    from scripts import a1_work_order

    raw = (WORK / "work-order.json").read_bytes()
    if sha256(WORK / "work-order.json") != os.environ["A1_WORK_ORDER_SHA256"]:
        raise ValueError("work order bytes differ from the approved digest")
    value = v3.json_object(raw.decode("utf-8"))
    return a1_work_order.verify(value)


def _tokenizer() -> Any:
    from transformers import AutoTokenizer  # type: ignore[import-not-found]

    return AutoTokenizer.from_pretrained(str(BASE), local_files_only=True)


class _TokenizerBackend:
    def __init__(self, tokenizer: Any) -> None:
        self.tokenizer = tokenizer


def verify_requests() -> dict[str, Any]:
    """Tokenize every frozen request from the payload alone; compare to the sealed digest."""
    _use_source()
    from scripts import a02_v3_contract as v3
    from scripts import a1_run

    order = work_order()
    backend = _TokenizerBackend(_tokenizer())
    checked = 0
    tokens = 0
    digests = set()
    for condition in order["conditions"]:
        for item in condition["items"]:
            ids, rendered = a1_run.prompt_ids(backend, item["messages"])
            if not 0 < len(ids) <= a1_run.MAX_PROMPT:
                raise ValueError(f"{condition['arm']}: prompt outside the disclosed token bound")
            digest = v3.sha256(v3.canonical(item["messages"]).encode())
            if digest != item["prompt_sha256"]:
                raise ValueError(f"{condition['arm']}: prompt digest differs from the seal")
            if v3.sha256(rendered.encode()) == item["prompt_sha256"]:
                raise ValueError("rendered prompt must not redefine the message digest")
            digests.add(digest)
            tokens += len(ids)
            checked += 1
    smoke = order["smoke"]
    ids, _rendered = a1_run.prompt_ids(backend, smoke["messages"])
    if not 0 < len(ids) <= a1_run.MAX_PROMPT:
        raise ValueError("smoke prompt outside the disclosed token bound")
    result = {
        "checked": checked,
        "planned": order["planned_generations"],
        "distinct_prompts": len(digests),
        "total_prompt_tokens": tokens,
        "smoke_prompt_tokens": len(ids),
        "smoke_prompt_sha256": smoke["prompt_sha256"],
        "complete": checked == order["planned_generations"],
    }
    write(WORK / "verify.json", result)
    write(WORK / "phase.json", {"phase": "VERIFY_COMPLETE", "verified": checked})
    if not result["complete"]:
        raise ValueError("the transported payload does not reconstruct every frozen request")
    return result


class _ConditionBackend:
    """The runner-facing backend: fixes the adaptation arm and delegates generation."""

    def __init__(self, backend: Any, model: str) -> None:
        self.backend = backend
        self.model = model
        self.tokenizer = backend.tokenizer

    def generate(
        self, arm: str, request: dict[str, Any], prompt: list[int], deadline: float
    ) -> Any:
        with self.backend.adapted(self.model):
            return self.backend.generate(arm, request, prompt, deadline)


def open_backend(label: str) -> Any:
    """Load the real pinned model with explicit remote path bindings."""
    _use_source()
    from scripts import a1_backend

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["A1_BASE_DIR"] = str(BASE)
    os.environ["A1_ADAPTER_ARCHIVE"] = str(WORK / "bundle.tar")
    started = time.monotonic()
    backend = a1_backend.A1Backend("cuda", WORK / "adapter-work")
    backend.setup_seconds = round(time.monotonic() - started, 3)
    write(
        WORK / f"{label}-identity.json",
        {
            **a1_backend.identity("cuda"),
            "setup_seconds": backend.setup_seconds,
            "bundle_report": backend.bundle_report,
        },
    )
    return backend


def _identity(label: str) -> dict[str, Any]:
    value = json.loads((WORK / f"{label}-identity.json").read_text())
    value.pop("bundle_report", None)
    return dict(value)


def smoke_phase(backend: Any) -> dict[str, Any]:
    """Four real development-only generations through the actual backend."""
    _use_source()
    from scripts import a1_chain, a1_run

    order = work_order()
    smoke = order["smoke"]
    ident = _identity("smoke")
    if SMOKE_OUT.exists():
        shutil.rmtree(SMOKE_OUT)
    SMOKE_OUT.mkdir(mode=0o700)
    item = {
        "case_id": "smoke-development-only",
        "cluster": "smoke-development-only",
        "prompt_sha256": smoke["prompt_sha256"],
        "request_sha256": smoke["request_sha256"],
    }
    receipts = []
    for condition in smoke["conditions"]:
        arm = f"SMOKE-{condition['label']}"
        receipt = a1_run.run_arm(
            _ConditionBackend(backend, condition["model"]),
            {
                "arm": arm,
                "role": "SMOKE",
                "model": condition["model"],
                "decoder": condition["decoder"],
                "representation": "SMOKE",
                "system": "S-hist",
                "fewshot": "0",
                "items": [item],
            },
            identity=ident,
            root=SMOKE_OUT,
            deadline_seconds=180.0,
            work={"smoke-development-only": smoke},
        )
        receipts.append(receipt)
    entries = {
        condition["label"]: a1_chain.read_arm(
            a1_chain.arm_path(f"SMOKE-{condition['label']}", SMOKE_OUT),
            f"SMOKE-{condition['label']}",
            [item],
        )["entries"]
        for condition in smoke["conditions"]
    }
    result = {
        "schema": "DYNAMISLM_A1_SMOKE_RECEIPT_V1",
        "purpose": smoke["purpose"],
        "receipts": receipts,
        "arms": {
            label: [
                {
                    "model": entry["model"],
                    "decoder": entry["decoder"],
                    "termination": entry["termination"],
                    "prompt_sha256": entry["prompt_sha256"],
                    "output_bytes": len(entry["raw_output"].encode()),
                }
                for entry in values
            ]
            for label, values in entries.items()
        },
        "adapters": {
            label: sorted({entry["model"] for entry in values}) for label, values in entries.items()
        },
        "distinct_outputs": len(
            {
                (entry["model"], entry["decoder"], entry["raw_output"])
                for values in entries.values()
                for entry in values
            }
        ),
        "measurements": backend.measurements(),
        "complete": all(receipt["complete"] for receipt in receipts)
        and all(len(values) == 1 for values in entries.values()),
    }
    write(WORK / "smoke-receipt.json", result)
    if not result["complete"]:
        raise ValueError("smoke generation did not complete all four arms")
    return result


def _smoke_complete() -> bool:
    path = WORK / "smoke-receipt.json"
    if not path.is_file():
        return False
    return bool(json.loads(path.read_text()).get("complete"))


def run_phase(backend: Any, seconds: float) -> dict[str, Any]:
    """Execute the frozen work order under one cumulative session deadline."""
    _use_source()
    from scripts import a1_chain, a1_run

    order = work_order()
    start = time.monotonic()
    deadline = start + seconds
    ident = _identity("run")
    OUT.mkdir(mode=0o700, exist_ok=True)
    work = {
        item["case_id"]: item for condition in order["conditions"] for item in condition["items"]
    }
    receipts = []
    for condition in order["conditions"]:
        if deadline - time.monotonic() < a1_run.MIN_CALL_SECONDS:
            break
        receipt = a1_run.run_arm(
            _ConditionBackend(backend, condition["model"]),
            condition,
            identity=ident,
            root=OUT,
            deadline_seconds=max(0.0, deadline - time.monotonic()),
            work=work,
            session_deadline=deadline,
        )
        receipts.append(receipt)
        write(WORK / "progress.json", {"phase": "run", "receipts": receipts})
        if not receipt["complete"]:
            break
    counts = a1_chain.count_lines(OUT)
    complete = sum(counts.values()) == order["planned_generations"]
    write(
        WORK / "run-receipt.json",
        {
            "receipts": receipts,
            "budget_seconds": seconds,
            "elapsed_seconds": round(time.monotonic() - start, 3),
            "commitments": counts,
            "committed": sum(counts.values()),
            "planned": order["planned_generations"],
            "complete": complete,
            "measurements": backend.measurements(),
        },
    )
    write(
        WORK / "phase.json",
        {"phase": "RUN_COMPLETE" if complete else "RUN_PARTIAL", "commitments": counts},
    )
    return {"receipts": receipts, "commitments": counts, "complete": complete}


def campaign_phase(seconds: float, run_smoke: bool) -> dict[str, Any]:
    """Verify the frozen requests, then smoke (first session only) and run the work order.

    The four smoke generations are authorized exactly once. A later session starts from a fresh
    filesystem and receives this session's committed chains in its payload, so it skips the smoke
    and resumes the frozen order directly.
    """
    verify = verify_requests()
    previous_smoke: dict[str, Any] | None = None
    if (WORK / "smoke-receipt.json").is_file():
        previous_smoke = json.loads((WORK / "smoke-receipt.json").read_text())
    backend = open_backend("smoke")
    if run_smoke:
        smoke = smoke_phase(backend)
    elif previous_smoke is not None:
        smoke = previous_smoke
    else:
        raise ValueError("campaign phase requires a smoke receipt in a later session")
    started = time.monotonic()
    if seconds <= 0:
        raise ValueError("campaign phase requires a positive generation budget")
    run = run_phase(backend, seconds)
    write(
        WORK / "campaign-receipt.json",
        {
            "schema": "DYNAMISLM_A1_CAMPAIGN_PHASE_V1",
            "verify": verify,
            "smoke": {
                "complete": smoke["complete"],
                "arms": smoke["arms"],
                "distinct_outputs": smoke.get("distinct_outputs"),
                "executed_this_session": run_smoke,
            },
            "run": run,
            "setup_seconds": backend.setup_seconds,
            "phase_seconds": round(time.monotonic() - started, 3),
            "measurements": backend.measurements(),
        },
    )
    return {
        "verify": verify["complete"],
        "smoke": smoke["complete"],
        "smoke_executed": run_smoke,
        "committed": run["committed"],
        "planned": run["planned"],
        "complete": run["complete"],
    }


def status() -> dict[str, Any]:
    """Current progress. A missing work tree is a legitimate pre-session state, not an error."""
    if not WORK.is_dir():
        return {
            "arms": {},
            "committed": 0,
            "smoke": {"present": False, "complete": None, "adapters": None},
            "phase": {},
            "error": None,
            "work_tree": False,
        }
    _use_source()
    from scripts import a1_chain

    phase = {}
    if (WORK / "phase.json").is_file():
        phase = json.loads((WORK / "phase.json").read_text())
    smoke = {}
    if (WORK / "smoke-receipt.json").is_file():
        smoke = json.loads((WORK / "smoke-receipt.json").read_text())
    counts = a1_chain.count_lines(OUT)
    return {
        "arms": counts,
        "committed": sum(counts.values()),
        "smoke": {
            "present": bool(smoke),
            "complete": smoke.get("complete"),
            "adapters": smoke.get("adapters"),
        },
        "phase": phase,
        "error": _error(),
        "work_tree": True,
    }


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
    if not OUT.is_dir() and not SMOKE_OUT.is_dir():
        raise ValueError("no run directory exists yet")
    evidence()
    _use_source()
    from scripts import a1_chain

    return {
        "evidence_sha256": sha256(EVIDENCE),
        "arms": a1_chain.count_lines(OUT),
        "smoke_arms": a1_chain.count_lines(SMOKE_OUT),
    }


def resume_phase() -> dict[str, Any]:
    """Verify the committed chains a fresh session received in its payload.

    Each session starts with a fresh filesystem, so continuation is carried *by the payload*: the
    controller includes the already-harvested arm files, and extraction places them directly in
    the run directories. This phase therefore verifies those chains against the frozen item order
    instead of unpacking a second archive. A chain that does not correspond to the frozen next
    item fails closed before any generation.
    """
    _use_source()
    from scripts import a1_chain

    order = work_order()
    items = {condition["arm"]: condition["items"] for condition in order["conditions"]}
    verified: dict[str, int] = {}
    for arm, expected in items.items():
        path = a1_chain.arm_path(arm, OUT)
        if not path.is_file():
            continue
        state = a1_chain.read_arm(path, arm, expected)
        if state["torn_tail_discarded"]:
            a1_chain.truncate_torn_tail(path)
            state = a1_chain.read_arm(path, arm, expected)
        verified[arm] = len(state["entries"])
    write(
        WORK / "phase.json",
        {"phase": "RESUME_COMPLETE", "arms": len(verified), "committed": sum(verified.values())},
    )
    return status()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", nargs="?", choices=PHASES)
    parser.add_argument(
        "--seconds", type=float, default=float(os.environ.get("A1_SECONDS", "0") or 0)
    )
    args = parser.parse_args()
    # `colab exec --file` runs the file with no positional arguments, so the phase arrives in the
    # environment. Accept both forms and refuse an ambiguous or missing phase.
    phase = args.phase or os.environ.get("A1_PHASE")
    if phase not in PHASES:
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
        elif args.phase == "verify":
            verify_requests()
        elif args.phase == "smoke":
            write(WORK / "smoke-summary.json", smoke_phase(open_backend("smoke")))
        elif args.phase == "run":
            if args.seconds <= 0:
                raise ValueError("run phase requires a positive A1_SECONDS budget")
            print(json.dumps(run_phase(open_backend("run"), args.seconds), sort_keys=True))
        elif args.phase == "campaign":
            if args.seconds <= 0:
                raise ValueError("campaign phase requires a positive A1_SECONDS budget")
            print(
                json.dumps(
                    campaign_phase(args.seconds, os.environ.get("A1_SMOKE", "1") != "0"),
                    sort_keys=True,
                )
            )
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
        WORK.mkdir(mode=0o700, parents=True, exist_ok=True)
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
    return status_code


if __name__ == "__main__":
    raise SystemExit(main())
