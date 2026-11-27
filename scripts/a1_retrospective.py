"""D6: reconstruct the exposed A0.3 cohort for a retrospective foundation-model arm (RES-832).

The cohort already exists in the private RES-774 evidence root. This module reads only the
blinded export (scenario objects, item ids and owner-written questions) plus the released
owner gold, reconstructs the exact ``BoundRequest.model_request()`` the deployed runtime used,
and records the request digest so the reconstruction can be checked against the historical run.

The arm is explicitly retrospective and is never final evidence: the cohort has been exposed,
its gold is public inside the private evidence root, and the historical adapted-model calls are
already known. Its only purpose is to attribute the A0.3 collapse between the two models.

Gold is *not* used to build a prompt here. It is read only to score the arm, and the runner
never sees it: the reconstructed request is a pure function of the blinded scenario and the
owner-written question.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any

from scripts import a02_v3_contract as v3

EVIDENCE_ROOT = Path.home() / ".local/share/dynamislm-evidence"
CAMPAIGN = EVIDENCE_ROOT / "RES-774-campaign.5lKrv0"
BLIND = CAMPAIGN / "blind"
PROTECTED = CAMPAIGN / "protected"
SCHEMA = "DYNAMISLM_A1_RETROSPECTIVE_CASE_V1"
EXPECTED_ITEMS = 96
EXPECTED_CLUSTERS = 48


def _jsonl(data: bytes) -> list[dict[str, Any]]:
    if not data.endswith(b"\n"):
        raise ValueError("retrospective source is empty or has an unfinished line")
    return [v3.json_object(line) for line in data.decode("utf-8").splitlines()]


def available() -> bool:
    """False when the private RES-774 evidence root is absent, as it is in hosted CI."""
    return (BLIND / "blind-scenarios.jsonl").is_file() and (PROTECTED / "gold.jsonl").is_file()


@functools.lru_cache(maxsize=1)
def cohort_request() -> tuple[dict[str, Any], ...]:
    """Reconstruct the deployed requests. Requires the private evidence root."""
    from scripts import research_ask
    from scripts.a03_internal_run import load_blind, read_blind

    requests, scenarios = read_blind(BLIND)
    items = load_blind(requests, scenarios)
    rows = []
    for item in items:
        bound = research_ask.prepare_request(item.scenario, item.question)
        rows.append(
            {
                "item_id": item.item_id,
                "scenario_id": item.scenario.scenario_id,
                "question": item.question,
                "request": bound.model_request(),
            }
        )
    if len(rows) != EXPECTED_ITEMS:
        raise ValueError("retrospective cohort item count differs")
    return tuple(rows)


def gold_rows() -> dict[str, dict[str, Any]]:
    """Released owner gold, keyed by item id. Scoring only; never a prompt input."""
    path = PROTECTED / "gold.jsonl"
    return {row["item_id"]: row["judgment"] for row in _jsonl(path.read_bytes())}


def cohort_cases() -> list[dict[str, Any]]:
    rows = cohort_request()
    gold = gold_rows()
    cases = []
    for row in rows:
        judgment = gold.get(row["item_id"])
        if judgment is None:
            raise ValueError("retrospective cohort item lacks released gold")
        cases.append(
            {
                "case_id": f"d6-{row['item_id']}",
                "cluster": f"d6-{row['scenario_id']}",
                "stratum": judgment["control"],
                "family": judgment["control"],
                "request": row["request"],
                "gold": v3.normalize_action(judgment["preferred_action"]),
                "acceptable_actions": [
                    v3.normalize_action(action) for action in judgment["acceptable_actions"]
                ],
                "source_item_id": row["item_id"],
                "schema": SCHEMA,
            }
        )
    if len({case["cluster"] for case in cases}) != EXPECTED_CLUSTERS:
        raise ValueError("retrospective cohort cluster count differs")
    return cases


def describe() -> dict[str, Any]:
    rows = cohort_request()
    return {
        "items": len(rows),
        "request_sha256": v3.sha256(
            v3.canonical({row["item_id"]: row["request"] for row in rows}).encode()
        ),
        "evidence": str(CAMPAIGN),
    }


def main() -> None:
    print(json.dumps(describe(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
