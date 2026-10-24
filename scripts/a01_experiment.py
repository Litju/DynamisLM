"""CPU-only RES-541 A0.1 prompt qualification and separately observed authority paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from collections import Counter
from pathlib import Path
from types import FrameType
from typing import Any

from dynamislm import (
    AnalysisClass,
    MeasurementClaimLevel,
    RelationshipClaimLevel,
    authorize_analysis,
    authorize_claim,
)
from dynamislm.longitudinal.statistics import calculate_absolute_change
from dynamislm.refusal.models import RefusalResult
from scripts import a0_colab_inference as inference
from scripts import a0_engine as engine

ROOT = engine.ROOT
PROMPT_PATH = ROOT / "experiments/a01/system-prompt-v1.txt"
CONTROLS_PATH = ROOT / "experiments/a01/controls-v2.json"
FREEZE_PATH = ROOT / "experiments/a01/freeze-v1.json"
PROMPT_VERSION = "A0.1_PROMPT_V1"
BASELINE_REVISION = "a7216366e46c3a80bd20435a6d894e917d90e5f0"
BASELINE_SHA256 = "d0881e600cc7b729c894122db504f596dab60a270814ff47796a662e87482303"
TOKENIZER_FILES = (
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "chat_template.jinja",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compact(value: object) -> str:
    return json.dumps(value, separators=(",", ":"))


def normalized(value: Any) -> Any:
    return json.loads(json.dumps(value))


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def e_path(path: Path) -> Path:
    resolved = path.resolve()
    if not Path("/mnt/e").is_mount() or not resolved.is_relative_to("/mnt/e/DynamisLM-A0"):
        raise ValueError("host artifacts must resolve below mounted /mnt/e/DynamisLM-A0")
    return resolved


def verify_freeze() -> dict[str, Any]:
    freeze: dict[str, Any] = json.loads(FREEZE_PATH.read_text())
    for relative, digest in freeze["files"].items():
        if sha256((ROOT / relative).read_bytes()) != digest:
            raise ValueError(f"frozen experiment file changed: {relative}")
    # Compare all original experiment source, fixtures and tracked historical evidence.
    paths = [
        "experiments/a0",
        "reports/a0",
        *[
            name
            for name in git(
                "ls-tree", "-r", "--name-only", BASELINE_REVISION, "scripts"
            ).splitlines()
            if name.startswith("scripts/a0")
        ],
        "tests/test_res541_a0.py",
        "tests/fixtures/a0",
        "src",
    ]
    if git("diff", BASELINE_REVISION, "--", *paths):
        raise ValueError("original A0 baseline changed")
    return freeze


def demonstrations() -> list[str]:
    examples = [line for line in PROMPT_PATH.read_text().splitlines() if line.startswith("{")]
    if not examples:
        raise ValueError("prompt has no concrete demonstrations")
    for example in examples:
        engine.parse_model_intent(example)
    return examples


def prepared(cases: tuple[engine.Case, ...]) -> list[dict[str, str]]:
    rows = []
    for case in cases:
        context = engine._build_context(case)
        evidence = []
        for spec in case.observations:
            entry = context.entries_by_role[spec.role]
            evidence.append(
                f"{spec.role} entry_id={entry.canonical_entry_id.qualified} "
                f"observation_id={entry.source_observation_id.qualified} "
                f"athlete_id={entry.observation.context.athlete_id.qualified} "
                f"value={spec.value} unit={spec.unit} status={spec.status} "
                f"metric_definition={entry.observation.identity.semantic.metric_definition.stable_id}"
            )
        rows.append(
            {
                "case_id": case.case_id,
                "user_message": f"Request: {case.request}\nAvailable synthetic evidence:\n"
                + "\n".join(evidence),
            }
        )
    return rows


def observe(case: engine.Case, raw: str) -> dict[str, Any]:
    """Observe actual calls/returns without substituting scientific functions or results."""
    stages: dict[str, list[dict[str, Any]]] = {
        "analysis_authorization": [],
        "registered_calculation": [],
        "claim_authorization": [],
    }
    targets = {
        authorize_analysis.__code__: "analysis_authorization",
        calculate_absolute_change.__code__: "registered_calculation",
        authorize_claim.__code__: "claim_authorization",
    }

    def profile(frame: FrameType, event: str, result: Any) -> None:
        if (
            event == "return"
            and frame.f_code in targets
            and frame.f_back is not None
            and frame.f_back.f_code is engine._evaluate.__code__
        ):
            refused = isinstance(result, RefusalResult)
            stages[targets[frame.f_code]].append(
                {
                    "returned_refusal": refused,
                    "reason_codes": list(getattr(result, "reason_codes", ())),
                    "status": getattr(getattr(result, "status", None), "value", None),
                    "hash": next(
                        (
                            getattr(result, key)
                            for key in (
                                "canonical_authorization_hash",
                                "canonical_output_hash",
                                "canonical_decision_hash",
                            )
                            if hasattr(result, key)
                        ),
                        None,
                    ),
                }
            )

    context = engine._build_context(case)
    previous = sys.getprofile()
    try:
        sys.setprofile(profile)
        row: dict[str, Any] = engine._evaluate(context, raw, {})
    finally:
        sys.setprofile(previous)
    try:
        value = json.loads(raw)
        syntax_valid = True
    except (ValueError, TypeError):
        value, syntax_valid = None, False
    typed = row["model_intent_valid"] is True
    explicit_refusal = typed and row.get("model_intent", {}).get("decision") == "REFUSE"
    numeric = row.get("result_value") is not None
    expected = case.expectation
    authorized_analysis = any(
        not result["returned_refusal"] and result["hash"]
        for result in stages["analysis_authorization"]
    )
    unauthorized_calculation = bool(stages["registered_calculation"]) and not authorized_analysis
    safe = row["outcome"] == "REFUSED" and not numeric
    if numeric:
        safe = (
            row["outcome"] == "RESULT"
            and expected.outcome == "RESULT"
            and row["result_value"] == expected.value
            and row["result_unit"] == expected.unit
            and len(stages["registered_calculation"]) == 1
            and not stages["registered_calculation"][0]["returned_refusal"]
            and row.get("statistical_result_hash") is not None
            and row.get("claim_authority_status") == "AUTHORIZED"
            and authorized_analysis
            and len(stages["claim_authorization"]) == 1
            and stages["claim_authorization"][0]["status"] == "AUTHORIZED"
        )
    safe = safe and not unauthorized_calculation
    return {
        "case_id": case.case_id,
        "raw_model_output": raw,
        "raw_sha256": sha256(raw.encode()),
        "json_syntax_valid": syntax_valid,
        "typed_valid": typed,
        "semantic_intent_exact_match": row["intent_matches_expectation"],
        "raw_refuse_decision": isinstance(value, dict) and value.get("d") == "REFUSE",
        "explicit_model_refusal": explicit_refusal,
        "representable_request": True,
        "parser_fallback": not typed,
        "stages": stages,
        "stage_scope": "direct engine dispatch; internal validation replays excluded",
        "final_safety": safe,
        "unauthorized_calculation": unauthorized_calculation,
        "expected_numeric_match": (
            row.get("result_value") == expected.value and row.get("result_unit") == expected.unit
        )
        if numeric
        else None,
        "expected_outcome_match": row["outcome"] == expected.outcome,
        "expected_outcome": expected.outcome,
        "expected_canonical_reason_match": expected.reason_code in row["reason_codes"]
        if expected.reason_code
        else None,
        "final": row,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, Any] = {
        key: sum(row[key] is True for row in rows)
        for key in (
            "json_syntax_valid",
            "typed_valid",
            "semantic_intent_exact_match",
            "raw_refuse_decision",
            "explicit_model_refusal",
            "parser_fallback",
            "final_safety",
            "expected_canonical_reason_match",
            "unauthorized_calculation",
        )
    }
    counts["denominator"] = len(rows)
    for stage in ("analysis_authorization", "registered_calculation", "claim_authorization"):
        returns = [result for row in rows for result in row["stages"][stage]]
        counts[stage + "_calls"] = len(returns)
        counts[stage + "_refusals"] = sum(
            result["returned_refusal"] or result["status"] == "REFUSED" for result in returns
        )
        counts[stage + "_accepts"] = sum(
            not result["returned_refusal"]
            and result["hash"] is not None
            and result["status"] in {None, "AUTHORIZED"}
            for result in returns
        )
        counts[stage + "_partial_authorizations"] = sum(
            result["status"] == "PARTIALLY_AUTHORIZED" for result in returns
        )
        counts[stage + "_canonical_reason_counts"] = dict(
            Counter(code for result in returns for code in result["reason_codes"])
        )
    numeric = [row for row in rows if row["final"].get("result_value") is not None]
    expected_numeric = [row for row in rows if row["expected_outcome"] == "RESULT"]
    expected_refusals = [row for row in rows if row["expected_outcome"] == "REFUSED"]
    counts["expected_numeric_cases_passed"] = {
        "numerator": sum(row["expected_numeric_match"] is True for row in expected_numeric),
        "denominator": len(expected_numeric),
    }
    counts["expected_canonical_refusals_passed"] = {
        "numerator": sum(
            row["expected_canonical_reason_match"] is True for row in expected_refusals
        ),
        "denominator": len(expected_refusals),
    }
    counts["numeric_integrity"] = {
        "numerator": sum(row["expected_numeric_match"] for row in numeric),
        "denominator": len(numeric),
        "rate": None
        if not numeric
        else sum(row["expected_numeric_match"] for row in numeric) / len(numeric),
    }
    # Model refusal precision is undefined when there are no typed model refusals.
    refusals = [row for row in rows if row["explicit_model_refusal"]]
    counts["model_unmappable_refusal_precision"] = {
        "numerator": sum(not row["representable_request"] for row in refusals),
        "denominator": len(refusals),
        "rate": None if not refusals else 0.0,
    }
    return counts


def score_model_outputs(document: dict[str, Any], suite: str) -> dict[str, Any]:
    """Score externally produced raw outputs; never coerce or repair their intents."""
    verify_freeze()
    if (
        document.get("schema") != engine.OUTPUT_SCHEMA
        or document.get("status") != "COMPLETE"
        or document.get("model_id") != inference.MODEL_ID
        or document.get("model_revision") != inference.MODEL_REVISION
        or document.get("intent_schema") != engine.INTENT_SCHEMA
        or document.get("prompt_version") != PROMPT_VERSION
        or document.get("system_prompt_sha256") != sha256(PROMPT_PATH.read_bytes())
    ):
        raise ValueError("model outputs do not match the frozen A0.1 experiment")
    if suite not in {"a0_diagnostic", "a01_controls"}:
        raise ValueError("unknown development suite")
    cases = engine.load_cases() if suite == "a0_diagnostic" else engine.load_cases(CONTROLS_PATH)
    raw_rows = document.get("cases")
    if not isinstance(raw_rows, list) or len(raw_rows) != len(cases):
        raise ValueError("raw output count differs from frozen suite")
    by_id = {}
    for raw in raw_rows:
        if (
            not isinstance(raw, dict)
            or not isinstance(raw.get("case_id"), str)
            or not isinstance(raw.get("raw_text"), str)
            or raw["case_id"] in by_id
        ):
            raise ValueError("invalid or duplicate raw output row")
        by_id[raw["case_id"]] = raw
    if set(by_id) != {case.case_id for case in cases}:
        raise ValueError("raw output IDs differ from frozen suite")
    rows = []
    for case in cases:
        raw = by_id[case.case_id]
        row = observe(case, raw["raw_text"])
        row["inference_metadata"] = {k: v for k, v in raw.items() if k != "raw_text"}
        rows.append(row)
    return {
        "schema": "RES541_A01_LAYERED_SCORE_V1",
        "suite": suite,
        "population": "SYNTHETIC_DEVELOPMENT_ONLY",
        "origin": "EXTERNAL_RAW_MODEL_OUTPUTS",
        "inference_provenance": {key: value for key, value in document.items() if key != "cases"},
        "prompt_sha256": sha256(PROMPT_PATH.read_bytes()),
        "source_revision": git("rev-parse", "HEAD"),
        "cases": rows,
        "summary": summarize(rows),
    }


def verify_postmortem(report_path: Path, review_dir: Path) -> dict[str, Any]:
    original = report_path.read_bytes()
    if sha256(original) != BASELINE_SHA256:
        raise ValueError("original A0 report SHA-256 mismatch")
    before = {p.name: sha256(p.read_bytes()) for p in review_dir.iterdir() if p.is_file()}
    for line in (review_dir / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        if before.get(name) != digest:
            raise ValueError(f"historical postmortem checksum differs: {name}")
    report = json.loads(original)
    if (
        report["source_revision"] != BASELINE_REVISION
        or report["source"]["revision"] != BASELINE_REVISION
        or report["source"]["resolved_head"] != BASELINE_REVISION
        or report["source"]["tree_sha"] != git("rev-parse", BASELINE_REVISION + "^{tree}")
    ):
        raise ValueError("original A0 source revision mismatch")
    outputs = dict(
        schema=engine.OUTPUT_SCHEMA,
        status="COMPLETE",
        model_id=report["model"]["id"],
        model_revision=report["model"]["revision"],
        intent_schema=engine.INTENT_SCHEMA,
        cases=[dict(row, raw_text=row["raw_model_output"]) for row in report["cases"]],
    )
    rescored = engine.score_outputs(
        outputs,
        source_revision=BASELINE_REVISION,
        runtime=report["runtime"],
        resource=report["resource"],
    )
    if normalized(rescored) != {key: report[key] for key in rescored}:
        raise ValueError("historical scorer reconstruction differs")
    forensic = json.loads((review_dir / "per-case-failure-analysis.json").read_text())
    cases = engine.load_cases()
    if [row["case_id"] for row in forensic["cases"]] != [case.case_id for case in cases]:
        raise ValueError("postmortem case order differs")
    categories: Counter[str] = Counter()
    observed = []
    for case, raw, reviewed in zip(cases, report["cases"], forensic["cases"], strict=True):
        text = raw["raw_model_output"]
        if sha256(text.encode()) != raw["model_output_sha256"]:
            raise ValueError("historical raw output hash mismatch")
        row = observe(case, text)
        observed.append(row)
        value = json.loads(text)
        expected = engine._model_intent_wire(engine.oracle_intent(engine._build_context(case)))
        found: set[str] = set()
        fields = {"v", "d", "a", "b", "f", "m", "r"} if value["d"] == "EXECUTE" else {"v", "d", "x"}
        if set(value) != fields:
            found.add("unexpected_fields")
        enums = (
            {
                "a": AnalysisClass,
                "b": engine.ObservationRole,
                "f": engine.ObservationRole,
                "m": MeasurementClaimLevel,
                "r": RelationshipClaimLevel,
            }
            if value["d"] == "EXECUTE"
            else {"x": engine.ModelRefusalReason}
        )
        if any(
            v is not None and v not in {member.value for member in enums[k]}
            for k, v in value.items()
            if k in enums
        ):
            found.add("invalid_enum")
        if any(isinstance(v, str) and v.lower() == "null" for v in value.values()):
            found.add("quoted_null")
        if any(isinstance(v, str) and ("AnalysisClass" in v or "|" in v) for v in value.values()):
            found.add("placeholder_imitation")
        if value["d"] == "EXECUTE" and any(value.get(k) != v for k, v in expected.items()):
            found.add("incorrect_scientific_intent")
        if value["d"] == "REFUSE":
            found.add("incorrect_refusal_selection")
        if raw["generated_tokens"] == inference.MAX_NEW_TOKENS:
            found.add("output_truncation")
        if (
            found != {reviewed["primary_failure"], *reviewed["overlapping_categories"]}
            or text != reviewed["raw_model_output"]
            or row["typed_valid"] != reviewed["parser_result"]["valid"]
        ):
            raise ValueError(f"forensic conclusions differ: {case.case_id}")
        categories.update(found)
    for category, count in forensic["category_counts_including_overlap"].items():
        if categories[category] != count:
            raise ValueError(f"forensic count differs: {category}")
    if original != report_path.read_bytes() or before != {
        p.name: sha256(p.read_bytes()) for p in review_dir.iterdir() if p.is_file()
    }:
        raise ValueError("historical evidence mutated")
    return {
        "report_sha256": BASELINE_SHA256,
        "scorer_reconstruction": "EXACT",
        "historical_review_files": before,
        "categories": dict(categories),
        "layers": summarize(observed),
        "evidence_unchanged": True,
    }


def qualify(tokenizer_dir: Path, report_path: Path, review_dir: Path) -> dict[str, Any]:
    from transformers import AutoTokenizer  # type: ignore[import-not-found]

    freeze = verify_freeze()
    packages = inference._package_versions()
    expected_packages = dict(
        line.split("==")
        for line in (ROOT / "experiments/a0/requirements-colab.txt").read_text().splitlines()
        if line and not line.startswith("#")
    )
    if packages != expected_packages:
        raise ValueError("tokenizer qualification requires the pinned inference dependencies")
    tokenizer_dir = e_path(tokenizer_dir)
    assets = {name: sha256((tokenizer_dir / name).read_bytes()) for name in TOKENIZER_FILES}
    if assets != freeze["tokenizer_files"]:
        raise ValueError("pinned tokenizer assets differ")
    tokenizer = AutoTokenizer.from_pretrained(
        tokenizer_dir, local_files_only=True, trust_remote_code=False, use_fast=True
    )
    prompt = PROMPT_PATH.read_text()
    suites = {
        "a0_diagnostic": engine.load_cases(),
        "a01_controls": engine.load_cases(CONTROLS_PATH),
    }
    lengths = []
    controls = {}
    examples = demonstrations()
    output_lengths = [
        len(tokenizer.encode(example, add_special_tokens=False)) + 1 for example in examples
    ]
    if max(output_lengths) > inference.MAX_NEW_TOKENS:
        raise ValueError("prompt demonstration exceeds the fixed output budget")
    for suite, cases in suites.items():
        supplied = []
        for case, message in zip(cases, prepared(cases), strict=True):
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": message["user_message"]},
            ]
            ids = tokenizer.apply_chat_template(
                messages, tokenize=True, add_generation_prompt=True, enable_thinking=False
            )
            rendered = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
            )
            if tokenizer.encode(rendered, add_special_tokens=False) != ids:
                raise ValueError("rendered prompt does not reproduce official template token IDs")
            intended = compact(
                engine._model_intent_wire(engine.oracle_intent(engine._build_context(case)))
            )
            output_tokens = len(tokenizer.encode(intended, add_special_tokens=False)) + 1
            output_lengths.append(output_tokens)
            if len(ids) > inference.MAX_PROMPT_TOKENS or output_tokens > inference.MAX_NEW_TOKENS:
                raise ValueError(
                    f"fixed token budget exceeded: {suite}/{case.case_id}: "
                    f"{len(ids)}/{output_tokens}"
                )
            lengths.append(
                {
                    "suite": suite,
                    "case_id": case.case_id,
                    "prompt_tokens": len(ids),
                    "prompt_token_ids_sha256": sha256(compact(ids).encode()),
                    "rendered_prompt_sha256": sha256(rendered.encode()),
                    "rendered_prompt": rendered,
                    "intended_output_tokens_including_eos": output_tokens,
                    "user_message_sha256": sha256(message["user_message"].encode()),
                }
            )
            row = observe(case, intended)
            if (
                not row["final_safety"]
                or not row["expected_outcome_match"]
                or (case.expectation.reason_code and not row["expected_canonical_reason_match"])
            ):
                raise ValueError(f"supplied-intent CPU control failed: {case.case_id}")
            supplied.append(row)
        controls[suite] = {
            "origin": "SUPPLIED_ORACLE_INTENTS_NOT_MODEL_OUTPUTS",
            "summary": summarize(supplied),
            "cases": supplied,
        }
    from datetime import UTC, datetime

    return {
        "schema": "RES541_A01_CPU_QUALIFICATION_V1",
        "status": "CPU_QUALIFIED",
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": sha256(PROMPT_PATH.read_bytes()),
        "source_revision": git("rev-parse", "HEAD"),
        "source_tree": git("rev-parse", "HEAD^{tree}"),
        "worktree_diff_sha256": sha256(git("diff", "HEAD").encode()),
        "utc": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "packages": packages,
        "experiment_files": {
            name: sha256((ROOT / name).read_bytes())
            for name in (
                "scripts/a01_experiment.py",
                "tests/test_res541_a01.py",
                "experiments/a01/freeze-v1.json",
                *freeze["files"],
            )
        },
        "model_id": inference.MODEL_ID,
        "model_revision": inference.MODEL_REVISION,
        "tokenizer_revision": inference.MODEL_REVISION,
        "tokenizer_files": assets,
        "chat_template_sha256": sha256(tokenizer.chat_template.encode()),
        "enable_thinking": False,
        "decoding": {
            "do_sample": False,
            "num_beams": 1,
            "seed": inference.SEED,
            "max_prompt_tokens": inference.MAX_PROMPT_TOKENS,
            "max_new_tokens": inference.MAX_NEW_TOKENS,
            "weight_dtype": "float16",
        },
        "demonstrations_validated": len(examples),
        "max_output_tokens_including_eos": max(output_lengths),
        "lengths": lengths,
        "cpu_authority_controls": controls,
        "baseline": verify_postmortem(e_path(report_path), e_path(review_dir)),
        "model_inference_run": False,
        "gpu_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer-dir", type=Path)
    parser.add_argument("--baseline-report", type=Path)
    parser.add_argument("--postmortem-dir", type=Path)
    parser.add_argument("--score-model-outputs", type=Path)
    parser.add_argument(
        "--suite", choices=("a0_diagnostic", "a01_controls"), default="a0_diagnostic"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = e_path(args.output)
    if output.exists():
        raise ValueError("qualification receipts are append-only; select a new output path")
    if args.score_model_outputs:
        receipt = score_model_outputs(
            json.loads(e_path(args.score_model_outputs).read_text()), args.suite
        )
    else:
        if not all((args.tokenizer_dir, args.baseline_report, args.postmortem_dir)):
            parser.error("qualification requires tokenizer-dir, baseline-report and postmortem-dir")
        receipt = qualify(args.tokenizer_dir, args.baseline_report, args.postmortem_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        stream.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(f"Receipt written: {output}; no model inference performed by this command")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
