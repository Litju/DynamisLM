from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_contract as v3
from scripts.a03_benchmark_seal import FILES, MIN_CLUSTERS, STRATA, _exposed_questions, seal

Packet = tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]


@pytest.fixture
def packet() -> Packet:
    # Shape test only. These placeholders have no source, author or adjudicator authority.
    rows: Packet = ([], [], [])
    requests, gold, reviews = rows
    for index in range(MIN_CLUSTERS):
        item = f"smoke-item-{index}"
        positive = index % 2 == 0
        operation = v3.EXPOSED_OPERATIONS[1] if positive else v3.NONE
        claims: dict[str, list[str]] = {
            "measurement": ["NUMERICAL_CHANGE"] if positive else [],
            "relationship": [],
        }
        ids = ["observation-1", "observation-2"] if positive else []
        action = {
            "analysis_class": "SCALAR_ABSOLUTE_CHANGE" if positive else v3.NONE,
            "operation": operation,
            "observation_ids": ids,
            "target_claims": claims,
        }
        observations = [
            {
                "alias": alias,
                "binding": "QUALIFIED",
                "device": "synthetic-device",
                "protocol": "synthetic-protocol",
                "unit": "m",
                "source_sha256": "0" * 64,
                "record_sha256": "1" * 64,
                "observation_sha256": v3.sha256(f"{item}/{alias}".encode()),
            }
            for alias in ids
        ]
        requests.append(
            {
                "item_id": item,
                "cluster_id": f"smoke-cluster-{index}",
                "scenario_id": f"smoke-scenario-{index}",
                "author_id": f"smoke-author-{index % 2}",
                "stratum": STRATA[index % len(STRATA)],
                "critical_families": [],
                "question": f"Placeholder schema test {index}",
                "observations": observations,
                "requested_claims": {"measurement": [], "relationship": []},
            }
        )
        judgment = {
            "scientific_validity": "VALID" if positive else "INVALID",
            "control": "EXECUTE" if positive else "REFUSE",
            "preferred_action": action,
            "acceptable_actions": [action],
            "dispatch_operation": operation if positive else None,
            "allowed_claims": claims,
            "refusal_codes": [] if positive else ["V3_OBSERVATION_REFERENCE_UNRESOLVED"],
        }
        reviewers = ["smoke-reviewer-a", "smoke-reviewer-b"]
        gold.append(
            {
                "item_id": item,
                "initial_reviewers": reviewers,
                "arbitration_reviewer": None,
                "judgment": deepcopy(judgment),
                "rationale": "Synthetic structural check",
            }
        )
        reviews.extend(
            {
                "item_id": item,
                "reviewer_id": reviewer,
                "judgment": deepcopy(judgment),
                "rationale": "Synthetic structural check",
            }
            for reviewer in reviewers
        )
    return requests, gold, reviews


def _write(path: Path, packet: Packet) -> None:
    for name, rows in zip(FILES, packet, strict=True):
        (path / name).write_text("".join(v3.canonical(row) + "\n" for row in rows))


def test_packet_seal_hashes_exact_bytes_and_allows_reasoned_arbitration(
    tmp_path: Path,
    packet: Packet,
) -> None:
    _, gold, reviews = packet
    reviews[1]["judgment"]["preferred_action"] = None
    reviews.append({**reviews[0], "reviewer_id": "smoke-reviewer-c"})
    gold[0]["arbitration_reviewer"] = "smoke-reviewer-c"
    _write(tmp_path, packet)
    first = seal(tmp_path)
    assert first["items"] == first["clusters"] == MIN_CLUSTERS
    with (tmp_path / "requests.jsonl").open("a") as handle:
        handle.write("  ")
    # Spaces are harmless inside a line, but a trailing whitespace-only record is invalid.
    with pytest.raises(ValueError):
        seal(tmp_path)
    text = (tmp_path / "requests.jsonl").read_text()
    (tmp_path / "requests.jsonl").write_text(" " + text.rstrip(" "))
    assert seal(tmp_path)["files"]["requests.jsonl"] != first["files"]["requests.jsonl"]


@pytest.mark.parametrize(
    ("tamper", "reason"),
    [
        ("exposed", "exposed A0.2"),
        ("shared_observation", "same observation split"),
        ("self_review", "different person's authored item"),
        ("forged_label", "agreed reviews must be preserved"),
        ("unqualified_schema", "expected non-empty text"),
        ("missing_gold", "complete gold"),
    ],
)
def test_packet_seal_rejects_contamination_or_authority_drift(
    tmp_path: Path,
    packet: Packet,
    tamper: str,
    reason: str,
) -> None:
    requests, gold, reviews = packet
    match tamper:
        case "exposed":
            requests[0]["question"] = min(_exposed_questions() - {""})
        case "shared_observation":
            requests[2]["observations"] = requests[0]["observations"]
        case "self_review":
            reviews[0]["reviewer_id"] = requests[0]["author_id"]
        case "forged_label":
            gold[0]["judgment"]["preferred_action"] = None
        case "unqualified_schema":
            requests[0]["observations"][0]["source_sha256"] = None
        case "missing_gold":
            gold.pop()
    _write(tmp_path, packet)
    with pytest.raises(ValueError, match=reason):
        seal(tmp_path)
