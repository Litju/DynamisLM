"""Build the gold-free A1 inference payload (RES-832).

The scientific contract stays local: the 48 authored cases, the frozen gold, the adjudication
strata and the retrospective gold never leave this machine. What is transported is the minimum a
remote T4 needs to execute the frozen calls:

* the exact model-visible request object for every planned generation;
* the exact rendered chat messages that produced the sealed prompt digest;
* the per-item request and prompt digests from the sealed call manifest;
* the inference modules, prompt/tool assets, pinned requirement files and the verified adapter
  archive;
* development-only smoke input (never part of the evaluation cohort).

D6 is included by exporting only its blinded requests, which is exactly what the retrospective
arm needs; its gold is read locally by the scorer and is not transported.

Every digest is recomputed here against the seal before anything is written, so a payload that
would run a different prompt fails closed at build time. The worker recomputes the same digests
again on the remote, so transport corruption fails closed there as well.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Any

from scripts import a02_v3_contract as v3
from scripts import a1_cases, a1_manifest, a1_work_order
from scripts import a1_representation as rep

ROOT = Path(__file__).resolve().parents[1]
WORK_ORDER_SCHEMA = a1_work_order.WORK_ORDER_SCHEMA
PAYLOAD_SCHEMA = "DYNAMISLM_A1_INFERENCE_PAYLOAD_V1"
SMOKE_SCHEMA = a1_work_order.SMOKE_SCHEMA
SMOKE_PATH = ROOT / "experiments/a1/smoke-input-v1.json"
SMOKE_CONDITIONS = (
    {"label": "M0-native", "model": "M0", "decoder": "N"},
    {"label": "M0-constrained", "model": "M0", "decoder": "C1"},
    {"label": "M1-native", "model": "M1", "decoder": "N"},
    {"label": "M1-constrained", "model": "M1", "decoder": "C1"},
)
# Priority for execution: principal factorial first, then diagnostics, retrospective, probes.
ROLE_ORDER = (
    "PRINCIPAL_FACTORIAL",
    "DIAGNOSTIC",
    "DIAGNOSTIC_ASSISTED",
    "DIAGNOSTIC_FEWSHOT",
    "RETROSPECTIVE_NOT_FINAL_EVIDENCE",
    "SHORTCUT_PROBE",
)
# The payload source set: inference modules, prompt authority and pinned requirement files only.
# `a1_cases`, the case manifest, the seal and this builder are deliberately absent. The worker
# verifies the transported work order through `a1_work_order`, which cannot reach the authored
# cohort, the gold or the adjudication metadata.
SOURCE_PATHS = (
    "src/dynamislm",
    "scripts/__init__.py",
    "scripts/a02_remote.py",
    "scripts/a02_v3_contract.py",
    "scripts/a02_v3_precision.py",
    "scripts/a03_hf_token_mask.py",
    "scripts/a03_model_core.py",
    "scripts/a03_token_decoder.py",
    "scripts/a1_backend.py",
    "scripts/a1_chain.py",
    "scripts/a1_run.py",
    "scripts/a1_work_order.py",
    "scripts/alpha_adapter_bundle.py",
    "experiments/a0/requirements-colab.txt",
    "experiments/a02/development-profile-v3.json",
    "experiments/a02/model-comparison-protocol-v3.json",
    "experiments/a02/submit-scientific-action-tool-v3.json",
    "experiments/a02/system-action-development-v3.txt",
    "experiments/a02/tokenizer-files-v1.json",
    "experiments/a02/training-requirements-v1.txt",
)
# Never transported, and asserted so at build time.
FORBIDDEN_SOURCE_PATHS = (
    "scripts/a1_analysis.py",
    "scripts/a1_author.py",
    "scripts/a1_baselines.py",
    "scripts/a1_cases.py",
    "scripts/a1_manifest.py",
    "scripts/a1_payload.py",
    "scripts/a1_retrospective.py",
    "scripts/a1_score.py",
    "scripts/a1_shortcut.py",
    "experiments/a1/call-manifest-v1.json",
    "experiments/a1/cases-v1.json",
)
# Keys that would leak evaluation material into the transported payload.
FORBIDDEN_KEYS = a1_work_order.FORBIDDEN_KEYS


# One error type across the transport boundary: a remote fails closed on the same exception the
# local builder raises, without importing the builder.
PayloadError = a1_work_order.PayloadError


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _cases_by_id() -> dict[str, dict[str, Any]]:
    """Local-only case inventory. Never transported; supplies the request for each item."""
    from scripts import a02_v3_decision as decision
    from scripts import a1_retrospective, a1_shortcut

    cases = {case["case_id"]: case for case in a1_cases.load_manifest()["cases"]}
    if a1_retrospective.available():
        cases.update({case["case_id"]: case for case in a1_retrospective.cohort_cases()})
    examples = a1_shortcut.probe_examples(decision.load_protocol())
    for variant in a1_shortcut.VARIANTS:
        for case in a1_shortcut.probe_cases(examples, variant):
            cases[case["case_id"]] = case
    return cases


def _messages(
    item: dict[str, Any], condition: dict[str, Any]
) -> tuple[dict[str, Any], str, list[dict[str, str]]]:
    case = item["case"]
    request = rep.request_for(condition["representation"], case)
    messages = rep.render_messages(request, condition["system"], condition["fewshot"])
    request_digest = rep.request_sha256(request)
    prompt_digest = v3.sha256(v3.canonical(messages).encode())
    if request_digest != item["request_sha256"]:
        raise PayloadError(f"{condition['arm']}: request digest drift at {item['case_id']}")
    if prompt_digest != item["prompt_sha256"]:
        raise PayloadError(f"{condition['arm']}: prompt digest drift at {item['case_id']}")
    return request, request_digest, messages


def _forbidden(value: Any, path: str) -> None:
    a1_work_order.screen(value, path)


def condition_work(condition: dict[str, Any], cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """One payload condition: exact requests, exact messages, both frozen digests."""
    items = []
    for entry in condition["items"]:
        case = cases.get(entry["case_id"])
        if case is None:
            raise PayloadError(f"{condition['arm']}: unknown case {entry['case_id']}")
        request, request_digest, messages = _messages({**entry, "case": case}, condition)
        items.append(
            {
                "case_id": entry["case_id"],
                "cluster": entry["cluster"],
                "request": request,
                "request_sha256": request_digest,
                "prompt_sha256": entry["prompt_sha256"],
                "messages": messages,
            }
        )
    return {
        "arm": condition["arm"],
        "role": condition["role"],
        "model": condition["model"],
        "representation": condition["representation"],
        "decoder": condition["decoder"],
        "system": condition["system"],
        "fewshot": condition["fewshot"],
        "condition_sha256": condition["condition_sha256"],
        "items": items,
    }


def smoke_work() -> dict[str, Any]:
    """Development-only execution input, outside the frozen evaluation cohort."""
    value = v3.json_object(SMOKE_PATH.read_text(encoding="utf-8"))
    if value.get("schema") != SMOKE_SCHEMA:
        raise PayloadError("A1 smoke input schema differs")
    if value.get("purpose") != "DEVELOPMENT_ONLY_EXECUTION_CHECK":
        raise PayloadError("A1 smoke input is not marked development-only")
    if set(value) != {"schema", "purpose", "note", "request", "expectation"}:
        raise PayloadError("A1 smoke input fields differ")
    _forbidden(value, "smoke")
    request = value["request"]
    visible = v3.visible_request(request)
    if len(visible["observations"]) != 2:
        raise PayloadError("A1 smoke input needs exactly two observations")
    messages = rep.render_messages(request, "S-hist", "0")
    return {
        "schema": SMOKE_SCHEMA,
        "purpose": "DEVELOPMENT_ONLY_EXECUTION_CHECK",
        "expectation": value["expectation"],
        "request": request,
        "request_sha256": rep.request_sha256(request),
        "prompt_sha256": v3.sha256(v3.canonical(messages).encode()),
        "messages": messages,
        "conditions": list(SMOKE_CONDITIONS),
    }


def work_order(commit: str | None = None) -> dict[str, Any]:
    """The complete frozen work order, verified against the seal before it is returned."""
    sealed = a1_manifest.load_manifest()
    cases = _cases_by_id()
    conditions = [*sealed["conditions"], *sealed["retrospective"]["conditions"]]
    work = [condition_work(condition, cases) for condition in conditions]
    work.sort(key=lambda entry: ROLE_ORDER.index(entry["role"]))
    for entry in work:
        _forbidden(entry, entry["arm"])
    planned = sum(len(entry["items"]) for entry in work)
    total = sealed["total_planned_generations"]
    if planned != total or planned != 1332:
        raise PayloadError(f"work order generation count differs: {planned}")
    if len(work) != 20:
        raise PayloadError(f"work order condition count differs: {len(work)}")
    principal = sum(len(entry["items"]) for entry in work if entry["role"] == "PRINCIPAL_FACTORIAL")
    if principal != 384:
        raise PayloadError(f"principal factorial count differs: {principal}")
    return {
        "schema": WORK_ORDER_SCHEMA,
        "source_commit": commit,
        "sealed_manifest_sha256": digest(a1_manifest.SEAL_PATH),
        "case_manifest_sha256": sealed["case_manifest_sha256"],
        "planned_conditions": len(work),
        "planned_generations": planned,
        "principal_generations": principal,
        "conditions": work,
        "smoke": smoke_work(),
        "priority": list(ROLE_ORDER),
    }


def verify_work_order(value: dict[str, Any]) -> dict[str, Any]:
    """Recompute every transported digest. Delegates to the transport-only module."""
    return a1_work_order.verify(value)


def source_inventory() -> dict[str, Any]:
    """Assert the upload source set cannot reach the authored cohort, gold or the seal."""
    overlap = sorted(set(SOURCE_PATHS) & set(FORBIDDEN_SOURCE_PATHS))
    if overlap:
        raise PayloadError(f"payload source set contains evaluation material: {overlap}")
    missing = [path for path in SOURCE_PATHS if not (ROOT / path).exists()]
    if missing:
        raise PayloadError(f"payload source set is missing committed paths: {missing}")
    return {
        "paths": len(SOURCE_PATHS),
        "files": sum(
            1
            for path in SOURCE_PATHS
            for _ in ([(ROOT / path)] if (ROOT / path).is_file() else (ROOT / path).rglob("*"))
            if _.is_file()
        ),
        "forbidden_absent": list(FORBIDDEN_SOURCE_PATHS),
    }


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def build(directory: Path) -> tuple[Path, dict[str, Any]]:
    """Assemble the upload: minimal source, verified work order, verified adapter bundle."""
    if _git("status", "--porcelain", "--untracked-files=no"):
        raise PayloadError("A1 payload requires the exact clean committed source")
    head = _git("rev-parse", "HEAD")
    inventory = source_inventory()
    directory.mkdir(parents=True, exist_ok=True)
    order = work_order(head)
    source = directory / "source.tar"
    source.unlink(missing_ok=True)
    subprocess.run(
        [
            "git",
            "archive",
            "--format=tar",
            f"--output={source}",
            head,
            "--",
            *SOURCE_PATHS,
        ],
        cwd=ROOT,
        check=True,
    )
    order_path = directory / "work-order.json"
    order_path.write_text(v3.canonical(order) + "\n", encoding="utf-8")
    bundle_source = Path(
        "/home/litju/.local/share/dynamislm-evidence/RES-772-adapter-bundle/first.tar"
    )
    if not bundle_source.is_file():
        raise PayloadError("the verified adapter bundle is unavailable")
    bundle = directory / "bundle.tar"
    shutil.copyfile(bundle_source, bundle)
    from scripts import alpha_adapter_bundle

    alpha_adapter_bundle.verified_payload(bundle)
    prior = sorted((ROOT / "experiments/a1/.runs").glob("*.jsonl"))
    payload = directory / "a1-payload.tar"
    payload.unlink(missing_ok=True)
    with tarfile.open(payload, "x") as archive:
        for path in (source, order_path, bundle):
            archive.add(path, arcname=path.name)
        for path in prior:
            archive.add(path, arcname=f"runs/{path.name}")
    receipt = {
        "schema": PAYLOAD_SCHEMA,
        "source_commit": head,
        "source_tar_sha256": digest(source),
        "source_tar_bytes": source.stat().st_size,
        "source_inventory": inventory,
        "work_order_sha256": digest(order_path),
        "bundle_tar_sha256": digest(bundle),
        "payload_sha256": digest(payload),
        "payload_bytes": payload.stat().st_size,
        "planned_generations": order["planned_generations"],
        "planned_conditions": order["planned_conditions"],
        "principal_generations": order["principal_generations"],
        "smoke_conditions": len(order["smoke"]["conditions"]),
        "prior_evidence_arms": len(prior),
        "prior_evidence_lines": sum(
            len([line for line in path.read_bytes().split(b"\n") if line]) for path in prior
        ),
    }
    (directory / "payload-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    return payload, receipt
