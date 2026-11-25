"""CPU-only compute estimate for a sealed internal packet. It authorizes nothing.

Reads the blinded export (never gold), counts N and C1 inference calls, tokenizes every prompt
with the pinned tokenizer, applies the frozen max-new-token bound and timing model, and writes a
digest-bound `compute-estimate.json`. It loads no model and allocates no accelerator. The owner
records a separate, dated approval of an exact envelope that cites this estimate's digest.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

from scripts import a02_v3_contract as v3
from scripts import a03_internal_config as config
from scripts import a03_internal_run as runner
from scripts import research_ask as research

SCHEMA = "DYNAMISLM_A03_INTERNAL_COMPUTE_ESTIMATE_V1"
TIMING_SCHEMA = "DYNAMISLM_A03_INTERNAL_TIMING_EVIDENCE_V1"
DEVICE_NOTE = (
    "Planning values are historical RES-746 T4 timings. The shipped RES-430 ask runtime is "
    "qualified on CPU only, so any accelerated execution needs a separately qualified path and "
    "an owner-approved exact envelope. This estimate authorizes no compute."
)


def timing_model(evidence: bytes | None) -> dict[str, Any]:
    """Frozen planning timings, or a measured file whose digest is bound into the estimate."""
    compute = config.load_config()["compute"]
    if evidence is None:
        return {
            "source": compute["source"],
            "status": compute["status"],
            "expected_seconds_per_call": compute["expected_seconds_per_call"],
            "conservative_seconds_per_call": compute["conservative_seconds_per_call"],
            "setup_teardown_seconds": compute["setup_teardown_seconds"],
            "evidence_sha256": None,
        }
    row = v3.json_object(evidence.decode("utf-8"))
    names = (
        "schema source expected_seconds_per_call conservative_seconds_per_call "
        "setup_teardown_seconds calls"
    )
    if set(row) != set(names.split()) or row["schema"] != TIMING_SCHEMA:
        raise ValueError("timing evidence fields differ")
    for key in names.split()[2:]:
        value = row[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError("timing evidence needs finite positive values")
    if row["conservative_seconds_per_call"] < row["expected_seconds_per_call"]:
        raise ValueError("conservative timing cannot be below expected timing")
    return {
        "source": row["source"],
        "status": "MEASURED_FROM_BOUND_EVIDENCE",
        "expected_seconds_per_call": row["expected_seconds_per_call"],
        "conservative_seconds_per_call": row["conservative_seconds_per_call"],
        "setup_teardown_seconds": row["setup_teardown_seconds"],
        "evidence_sha256": v3.sha256(evidence),
    }


def envelope(calls: int, per_call: float, compute: dict[str, Any], setup: float) -> dict[str, Any]:
    usable = compute["session_seconds"] - setup
    if usable <= 0:
        raise ValueError("setup and teardown consume the whole session")
    seconds = calls * per_call
    sessions = max(1, math.ceil(seconds / usable))
    total = seconds + sessions * setup
    cu = total / 3600 * compute["cu_per_hour"] + sessions * compute["cu_reserve_per_session"]
    return {
        "generation_seconds": round(seconds, 6),
        "total_seconds": round(total, 6),
        "sessions": sessions,
        "cu": round(cu, 6),
    }


def estimate(
    requests: bytes,
    scenarios: bytes,
    tokenizer: Any,
    timing: bytes | None = None,
    *,
    protocol_version: int = 1,
) -> dict[str, Any]:
    compute = config.load_config()["compute"]
    items = runner.load_blind(requests, scenarios)
    counts: dict[str, int] = {}
    for item in items:
        request = research.prepare_request(item.scenario, item.question).model_request()
        counts[item.item_id] = len(v3.build_action_prompt(tokenizer, request)["prompt_token_ids"])
    model = timing_model(timing)
    calls = len(items) * compute["calls_per_item"]
    over = sorted(i for i, n in counts.items() if not 0 < n <= compute["max_prompt_tokens"])
    setup = model["setup_teardown_seconds"]
    return {
        "schema": SCHEMA,
        **config.identity(protocol_version),
        "authorizes": "NOTHING",
        "device_note": DEVICE_NOTE,
        "inputs": {
            "blind_requests_sha256": v3.sha256(requests),
            "blind_scenarios_sha256": v3.sha256(scenarios),
        },
        "calls": {"items": len(items), "per_item": compute["calls_per_item"], "total": calls},
        "arms": compute["arms"],
        "tokens": {
            "max_new_tokens": compute["max_new_tokens"],
            "max_prompt_tokens": compute["max_prompt_tokens"],
            "prompt_min": min(counts.values()),
            "prompt_max": max(counts.values()),
            "prompt_total": sum(counts.values()),
            "per_item": dict(sorted(counts.items())),
            "items_over_prompt_bound": over,
        },
        "timing": model,
        "session_seconds": compute["session_seconds"],
        "expected": envelope(calls, model["expected_seconds_per_call"], compute, setup),
        "worst_case": envelope(calls, model["conservative_seconds_per_call"], compute, setup),
        "valid": not over,
    }


def render(artifact: dict[str, Any]) -> bytes:
    """Canonical bytes with the digest of everything else embedded, so it is self-verifying."""
    digest = v3.sha256(v3.canonical(artifact).encode())
    return (v3.canonical({**artifact, "estimate_sha256": digest}) + "\n").encode()


def verify(
    artifact: bytes, requests: bytes, scenarios: bytes, tokenizer: Any, timing: bytes | None = None
) -> dict[str, Any]:
    """Independently recompute the estimate from the blinded inputs and require identical bytes."""
    parsed = v3.json_object(artifact.decode("utf-8"))
    claimed = parsed.get("estimate_sha256")
    if render(
        estimate(
            requests, scenarios, tokenizer, timing, protocol_version=config.version_for(parsed)
        )
    ) != artifact or (
        v3.sha256(
            v3.canonical({k: v for k, v in parsed.items() if k != "estimate_sha256"}).encode()
        )
        != claimed
    ):
        raise ValueError("compute estimate does not reproduce from the blinded inputs")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("blind_directory", type=Path)
    parser.add_argument("output_directory", type=Path)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--timing-evidence", type=Path)
    parser.add_argument("--protocol-version", type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    from scripts import a03_d0_runtime as d0
    from scripts import a03_prospective_run as prospective
    from scripts.a02_v3_preflight import load_pinned_tokenizer

    blind = prospective.restricted(args.blind_directory)
    requests, scenarios = runner.read_blind(blind)
    prospective.require_file_inventory(
        args.tokenizer, d0.MODEL_FILES | v3.load_profile()["tokenizer"]["files"]
    )
    timing = args.timing_evidence.read_bytes() if args.timing_evidence else None
    data = render(
        estimate(
            requests,
            scenarios,
            load_pinned_tokenizer(args.tokenizer),
            timing,
            protocol_version=args.protocol_version,
        )
    )
    target = prospective.restricted(args.output_directory) / "compute-estimate.json"
    with target.open("xb") as stream:
        stream.write(data)
    print(v3.canonical({"estimate_sha256": v3.json_object(data.decode())["estimate_sha256"]}))


if __name__ == "__main__":
    main()
