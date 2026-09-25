#!/usr/bin/env python3
"""Materialize the RES-115 Phase-B qualification batch outside Git."""

from __future__ import annotations

import argparse
import hashlib
import json
import resource
import secrets
import subprocess
from dataclasses import replace
from pathlib import Path

from dynamislm.benchmark.authoring import (
    AuthoringPlanV1,
    CandidateStoreReceiptV1,
    validate_authoring_plan,
)
from dynamislm.benchmark.public_repository import validate_qualification_repository_boundary
from dynamislm.benchmark.qualification_store import (
    DEFAULT_QUALIFICATION_ROOT,
    read_external_qualification_json,
    read_qualification_store,
    write_external_qualification_json,
    write_qualification_store,
)
from dynamislm.qualification import ReferenceCaseStatus, get_reference_cases
from dynamislm.qualification.res115_authoring import (
    AUTHORING_PROCESS_ID,
    QUALIFICATION_BATCH_ID,
    RES115_SYNTHETIC_GENERATOR_DIGEST,
    QualificationSeedInputV1,
    Res115AuthoringDraftV1,
    build_public_authoring_reports,
    build_res115_qualification_draft,
    build_res115_qualification_manifest,
    validate_res115_qualification_batch,
    write_public_authoring_reports,
)

_ENTRY_HEAD = "332621b47c7a8db2524b6e511e068528d227ad48"
_SEED_INPUT_PATH = "qualification/authoring_plan/private_seed_inputs.json"


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _private_seed_input(
    repository_root: Path,
    qualification_root: Path,
) -> QualificationSeedInputV1:
    seed_path = qualification_root / _SEED_INPUT_PATH
    if seed_path.exists() or seed_path.is_symlink():
        seed_input, _digest, _size = read_external_qualification_json(
            _SEED_INPUT_PATH,
            QualificationSeedInputV1,
            repository_root=repository_root,
            qualification_root=qualification_root,
        )
        return seed_input

    case_ids = tuple(
        sorted(
            (
                reference.case_id
                for reference in get_reference_cases()
                if reference.status is ReferenceCaseStatus.REFUSAL
                and reference.operation_id is None
            ),
            key=lambda value: value.encode("utf-8"),
        )
    )
    seed_input = QualificationSeedInputV1(
        batch_id=QUALIFICATION_BATCH_ID,
        generator_registry_digest=RES115_SYNTHETIC_GENERATOR_DIGEST,
        seed_blocks=tuple((case_id, secrets.token_hex(24)) for case_id in case_ids),
    )
    write_external_qualification_json(
        seed_input,
        _SEED_INPUT_PATH,
        repository_root=repository_root,
        qualification_root=qualification_root,
    )
    return seed_input


def _current_head(repository_root: Path) -> str:
    return subprocess.run(
        ("git", "-C", str(repository_root), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _resume_persisted_plan(
    draft: Res115AuthoringDraftV1,
    repository_root: Path,
    qualification_root: Path,
) -> Res115AuthoringDraftV1:
    batch_key = hashlib.sha256(draft.batch_id.encode("utf-8")).hexdigest()[:24]
    relative_path = f"qualification/authoring_plan/{batch_key}.json"
    plan_path = qualification_root / relative_path
    if not plan_path.exists() and not plan_path.is_symlink():
        return draft
    persisted_plan, _digest, _size = read_external_qualification_json(
        relative_path,
        AuthoringPlanV1,
        repository_root=repository_root,
        qualification_root=qualification_root,
    )
    current_by_id = {item.candidate_id: item for item in draft.plan.items}
    persisted_by_id = {item.candidate_id: item for item in persisted_plan.items}
    if set(current_by_id) != set(persisted_by_id):
        raise ValueError("persisted private authoring plan has different candidate IDs")
    reconciled_items = tuple(
        replace(
            item,
            authoring_rationale=persisted_by_id[item.candidate_id].authoring_rationale,
        )
        for item in draft.plan.items
    )
    expected_plan = replace(
        draft.plan,
        items=reconciled_items,
        plan_digest=persisted_plan.plan_digest,
    )
    if expected_plan != persisted_plan:
        raise ValueError("persisted private plan differs from current recipe/selection inputs")
    validate_authoring_plan(persisted_plan)
    receipt_relative_path = f"qualification/receipts/{batch_key}.json"
    receipt_path = qualification_root / receipt_relative_path
    if receipt_path.exists() or receipt_path.is_symlink():
        persisted_receipt, _receipt_digest, _receipt_size = read_external_qualification_json(
            receipt_relative_path,
            CandidateStoreReceiptV1,
            repository_root=repository_root,
            qualification_root=qualification_root,
        )
        restored_packets = read_qualification_store(
            persisted_receipt,
            repository_root=repository_root,
            qualification_root=qualification_root,
        )
        expected_packets = tuple(
            sorted(draft.packets, key=lambda item: item.candidate_id.encode("utf-8"))
        )
        if restored_packets != expected_packets:
            raise ValueError("persisted candidate packets differ from current authoring inputs")
    return replace(draft, plan=persisted_plan)


def _transient_peak_mb() -> float:
    # Linux reports ru_maxrss in KiB; the report records MiB as MB to six places.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--qualification-root",
        type=Path,
        default=DEFAULT_QUALIFICATION_ROOT,
    )
    parser.add_argument("--qa-pytest", choices=("PASS", "FAIL"), required=True)
    parser.add_argument("--test-count", type=int, required=True)
    parser.add_argument(
        "--qa-tracked-mutation",
        choices=("NONE", "DETECTED"),
        required=True,
    )
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    repository_root = _repository_root()
    qualification_root = arguments.qualification_root.resolve()
    if arguments.test_count < 0:
        raise ValueError("test count cannot be negative")

    seed_input = _private_seed_input(repository_root, qualification_root)
    draft = build_res115_qualification_draft(seed_input=seed_input)
    draft = _resume_persisted_plan(draft, repository_root, qualification_root)
    store_receipt = write_qualification_store(
        draft.packets,
        draft.plan,
        batch_id=draft.batch_id,
        repository_root=repository_root,
        qualification_root=qualification_root,
    )
    manifest = build_res115_qualification_manifest(draft, store_receipt)
    batch_key = hashlib.sha256(draft.batch_id.encode("utf-8")).hexdigest()[:24]
    manifest_path, manifest_sha256, manifest_bytes = write_external_qualification_json(
        manifest,
        f"qualification/manifests/{batch_key}.json",
        repository_root=repository_root,
        qualification_root=qualification_root,
    )
    validation = validate_res115_qualification_batch(draft, manifest, store_receipt)
    leak_guard = validate_qualification_repository_boundary(
        draft.packets,
        draft.plan,
        store_receipt,
        repository_root=repository_root,
        qualification_root=qualification_root,
    )
    if leak_guard.status != "PASS":
        raise ValueError("public repository qualification leak guard did not PASS")

    report_arguments = {
        "entry_head": _ENTRY_HEAD,
        "public_repo_leak_guard": leak_guard.status,
        "transient_peak_mb": _transient_peak_mb(),
        "qa_pytest": arguments.qa_pytest,
        "test_count": arguments.test_count,
        "qa_tracked_mutation": arguments.qa_tracked_mutation,
    }
    reports = build_public_authoring_reports(
        draft,
        manifest,
        store_receipt,
        validation,
        **report_arguments,
    )
    write_public_authoring_reports(reports, repository_root=repository_root)
    final_leak_guard = validate_qualification_repository_boundary(
        draft.packets,
        draft.plan,
        store_receipt,
        repository_root=repository_root,
        qualification_root=qualification_root,
    )
    if final_leak_guard.status != "PASS":
        raise ValueError("public repository qualification leak guard failed after report writing")

    guard_receipt_path, guard_receipt_digest, _guard_receipt_bytes = (
        write_external_qualification_json(
            final_leak_guard,
            f"qualification/receipts/{batch_key}-repository-leak-guard.json",
            repository_root=repository_root,
            qualification_root=qualification_root,
        )
    )
    phase_b = reports["phase_b_authoring_qualification.json"]
    if not isinstance(phase_b, dict):
        raise TypeError("Phase-B public report must be a JSON object")
    safe_summary = {
        "status": phase_b["status"],
        "qualification_cases": phase_b["qualification_cases"],
        "capability_family_cells": phase_b["capability_family_cells"],
        "capabilities": phase_b["capabilities"],
        "families": phase_b["families"],
        "question_classes": phase_b["question_classes"],
        "origins": phase_b["origins"],
        "active_scorers": phase_b["active_scorers"],
        "error_classes": phase_b["error_classes"],
        "source_backed_cases": phase_b["source_backed_cases"],
        "qualification_store_mb": phase_b["qualification_store_mb"],
        "transient_peak_mb": phase_b["transient_peak_mb"],
        "manifest_sha256": manifest_sha256,
        "manifest_bytes": manifest_bytes,
        "manifest_path": manifest_path,
        "repository_head": _current_head(repository_root),
        "authoring_process": AUTHORING_PROCESS_ID,
        "leak_guard_receipt_path": guard_receipt_path,
        "leak_guard_receipt_digest": guard_receipt_digest,
    }
    print(json.dumps(safe_summary, sort_keys=True))
    return 0 if phase_b["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
