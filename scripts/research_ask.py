"""Run one synthetic scientific question through the frozen C1 and V3 authority path."""

from __future__ import annotations

import os
import platform
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Protocol

import dynamislm as d
from scripts import a02_v3_contract as v3
from scripts import alpha_adapter_bundle as bundle
from scripts.a03_model_core import EOS, MAX_NEW, verify_files
from scripts.a03_model_runtime import MAX_PROMPT, Generation, PinnedModel
from scripts.a03_scientific_admission import BoundRequest, submit_scientific_action_v3
from scripts.a03_token_decoder import Grammar
from scripts.research_scenarios import SyntheticScenario, validate_scenario

SCHEMA = "DYNAMISLM_RESEARCH_ASK_RECEIPT_V1"
MAX_QUESTION_BYTES = 4096
CALL_SECONDS = 1200


class UnsupportedRuntimeError(ValueError):
    pass


class ModelBackend(Protocol):
    tokenizer: Any

    def generate(
        self, arm: str, request: dict[str, Any], prompt: list[int], deadline: float
    ) -> Generation: ...


@dataclass(frozen=True)
class ResearchRuntime:
    backend: ModelBackend
    identity: dict[str, Any]


def verify_base(base_dir: Path) -> dict[str, Any]:
    base = bundle.base_reference()
    paths = {p.name: p for p in base_dir.iterdir()}
    if paths.keys() != base["files"].keys() or any(
        path.is_symlink() or not path.is_file() for path in paths.values()
    ):
        raise ValueError("base snapshot must contain exactly the nine regular pinned files")
    verify_files(base_dir, base["files"])
    return base


def validate_device(device: str) -> None:
    if device != "cpu":
        raise UnsupportedRuntimeError("RES-430 qualifies --device cpu only")
    if (
        platform.python_implementation() != "CPython"
        or sys.version_info[:2] != (3, 13)
        or sys.platform != "linux"
        or platform.machine() != "x86_64"
    ):
        raise UnsupportedRuntimeError("requires Linux x86_64 and CPython 3.13")


def open_runtime(bundle_path: Path, base_dir: Path, device: str) -> ResearchRuntime:
    """Validate the original RES-772 archive and load only its verified PEFT bytes."""
    validate_device(device)
    if bundle_path.is_dir():
        files = list(bundle_path.iterdir())
        if len(files) != 1 or files[0].suffix != ".tar":
            raise ValueError("bundle directory must contain exactly one verified .tar")
        bundle_path = files[0]
    if bundle_path.is_symlink() or not bundle_path.is_file():
        raise ValueError("bundle archive must be a regular file")
    payload, report = bundle.verified_payload(bundle_path)
    base = verify_base(base_dir)
    report["base_snapshot_verified"] = True
    manifest = v3.json_object(payload["MANIFEST.json"].decode())
    # Read only deployed prompt assets. The historical case manifest stays out of the wheel.
    profile = v3.json_object(v3.PROFILE_PATH.read_text(encoding="utf-8"))
    for name, path in (
        ("action_prompt", v3.ACTION_PROMPT_PATH),
        ("tool_schema", v3.TOOL_SCHEMA_PATH),
    ):
        if v3.sha256(path.read_bytes()) != profile["inputs"][f"{name}_sha256"]:
            raise ValueError(f"deployed prompt asset differs: {name}")
    tokenizer = profile["tokenizer"]
    if tokenizer != {
        "revision": base["revision"],
        "files": {name: base["files"][name] for name in base["tokenizer_files"]},
    }:
        raise ValueError("prompt tokenizer identity differs from the verified bundle")
    packages = {name: pinned for name, pinned in manifest["runtime"].items() if name != "python"}
    packages["torch"] += "+cpu"
    try:
        if {name: version(name) for name in packages} != packages:
            raise UnsupportedRuntimeError(
                "installed model package versions differ from the CPU profile"
            )
    except PackageNotFoundError as exc:
        raise UnsupportedRuntimeError("install the pinned model dependency extra") from exc

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    adapter_files = {
        Path(name).name: report["files"][name] for name in (bundle.CONFIG, bundle.WEIGHTS)
    }
    identity = {
        "device": device,
        "runtime_packages": packages,
        "tokenizer": tokenizer,
        "adapter_files": adapter_files,
    }
    with tempfile.TemporaryDirectory(prefix="dynamislm-verified-adapter-") as staging:
        adapter = Path(staging)
        for name in (bundle.CONFIG, bundle.WEIGHTS):
            (adapter / Path(name).name).write_bytes(payload[name])
        try:
            backend = PinnedModel(base_dir, adapter, identity=identity, cpu_qualification=True)
        except (ImportError, RuntimeError) as exc:
            raise UnsupportedRuntimeError(f"pinned FP32 runtime could not load: {exc}") from exc
    return ResearchRuntime(
        backend,
        {
            "base": base,
            "adapter": manifest["adapter"],
            "bundle": report,
            "runtime": {
                **backend.runtime,
                "packages": packages,
                "precision": "FP32",
                "attention": "sdpa:MATH",
                "greedy": True,
                "autocast": False,
                "tf32": False,
            },
        },
    )


class _SingleObservationRequest(BoundRequest):
    @property
    def entries(self) -> tuple[d.LongitudinalObservationEntry, ...]:
        return self.records[0].entries


def prepare_request(scenario: SyntheticScenario, question: str) -> BoundRequest:
    validate_scenario(scenario)
    if (
        not isinstance(question, str)
        or not question.strip()
        or len(question.encode("utf-8")) > MAX_QUESTION_BYTES
        or "<|" in question
        or any(unicodedata.category(c).startswith("C") and c not in "\n\t\r" for c in question)
    ):
        raise ValueError("invalid question text")
    request_type = (
        _SingleObservationRequest if scenario.source is None and scenario.records else BoundRequest
    )
    bound = request_type(question, scenario.source, scenario.records)
    v3.visible_request(bound.model_request())
    return bound


def ask(
    scenario: SyntheticScenario, question: str, runtime: ResearchRuntime
) -> tuple[dict[str, Any], int]:
    """Deployed inference interface shared by the CLI and authorized evaluation callers."""
    bound = prepare_request(scenario, question)
    request = bound.model_request()
    prompt = v3.build_action_prompt(runtime.backend.tokenizer, request)
    ids = prompt["prompt_token_ids"]
    if not 0 < len(ids) <= MAX_PROMPT:
        raise ValueError("question and evidence exceed the registered prompt token bound")
    try:
        generation = runtime.backend.generate("C1", request, ids, time.monotonic() + CALL_SECONDS)
    except TimeoutError:
        generation = Generation([], "", "MODEL_TIMEOUT")
    except (ImportError, RuntimeError, ValueError) as exc:
        raise UnsupportedRuntimeError(f"pinned model generation failed: {exc}") from exc
    complete = (
        generation.termination == "MODEL_EOS"
        and 0 < len(generation.ids) <= MAX_NEW
        and generation.ids[-1] == EOS
        and EOS not in generation.ids[:-1]
    )
    # A syntactically complete action without EOS cannot authorize dispatch.
    raw = generation.raw
    if not complete:
        decision = None
        reason_codes = ["V3_INCOMPLETE_GENERATION"]
    else:
        decision = (
            submit_scientific_action_v3(bound, raw)
            if Grammar(request).accepts(raw.encode())
            else None
        )
        reason_codes = list(decision.reason_codes) if decision else ["V3_INVALID_PROPOSAL"]

    claim = decision.claim_authority if decision else None
    result = decision.result if decision else None
    outcome = decision.outcome if decision else "ABSTAINED" if not complete else "REFUSED"
    if outcome == "GROUNDED_RESULT" and result is None:
        outcome, reason_codes = "ABSTAINED", ["V3_NO_REGISTERED_RESULT"]
    receipt = {
        "schema": SCHEMA,
        "question": question,
        "scenario": {
            "id": scenario.scenario_id,
            "schema": scenario.schema,
            "origin": "SYNTHETIC_DETERMINISTIC",
            "evidence_sha256": d.canonical_hash((scenario.source, scenario.records)),
            "record_hashes": [record.canonical_record_hash for record in scenario.records],
            "observation_hashes": [d.canonical_hash(e.observation) for e in bound.entries],
        },
        "proposal": {
            "trust": "UNTRUSTED_MODEL_OUTPUT",
            "decoding": "C1",
            "raw": raw,
            "raw_sha256": v3.sha256(raw.encode()),
            "token_ids": generation.ids,
            "termination": generation.termination,
            "prompt_sha256": prompt["rendered_prompt_sha256"],
        },
        "admission": {
            "parse_status": "PARSED"
            if decision and decision.model_proposal
            else ("INCOMPLETE" if not complete else "REJECTED"),
            "outcome": outcome,
            "reason_codes": reason_codes,
            "trusted_admission": decision.trusted_admission if decision else "NOT_REACHED",
            "execution_authorized": bool(decision and decision.execution_authorized),
            "operation_executed": bool(decision and decision.operation_executed),
        },
        "claim_ceiling": {
            "measurement": claim.allowed_measurement_levels if result and claim else (),
            "relationship": claim.allowed_relationship_levels if result and claim else (),
        },
        "result": None
        if result is None
        else {
            "operation": result.operation.stable_id,
            "registered_output_hash": result.canonical_output_hash,
            "canonical_hash": d.canonical_hash(result),
            "support_hash": result.analysis_run.support_hash,
            "estimates": [
                {"value": e.value, "unit": e.unit.display_label, "estimand": e.estimand.stable_id}
                for e in result.estimates
            ],
        },
        "identity": runtime.identity,
    }
    return receipt, 0 if outcome == "GROUNDED_RESULT" else 2


def human_report(receipt: dict[str, Any]) -> str:
    """Fixed text derived only from the receipt, with untrusted strings escaped."""
    admission = receipt["admission"]
    lines = [
        f"Question (untrusted): {v3.canonical(receipt['question'])}",
        f"Scenario evidence: {v3.canonical(receipt['scenario'])}",
        f"Proposal (untrusted): {v3.canonical(receipt['proposal']['raw'])}",
        f"Parsing: {admission['parse_status']}",
        f"Outcome: {admission['outcome']}",
        f"Reasons: {v3.canonical(admission['reason_codes'])}",
    ]
    if detail := admission.get("detail"):
        lines.append(f"Detail: {v3.canonical(detail)}")
    if result := receipt["result"]:
        estimate = result["estimates"][0]
        lines.extend(
            [
                f"Authorized calculation for the proposal: {estimate['value']} {estimate['unit']}",
                f"Operation: {result['operation']}",
                f"Result hash: {result['registered_output_hash']}",
                f"Support hash: {result['support_hash']}",
            ]
        )
    lines.append(f"Claim ceiling: {v3.canonical(receipt['claim_ceiling'])}")
    identity = receipt["identity"]
    if identity:
        base = identity["base"]
        lines.extend(
            [
                f"Base model: {base['id']}@{base['revision']}",
                f"Adapter SHA-256: {identity['adapter']['weights_sha256']}",
                f"Distribution: {identity['bundle']['distribution']}",
                f"Runtime: {v3.canonical(identity['runtime'])}",
            ]
        )
    return "\n".join(lines)
