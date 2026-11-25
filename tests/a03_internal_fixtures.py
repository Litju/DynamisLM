"""Engineering fixtures for the RES-773 internal evaluation machinery. Clearly synthetic.

These packets validate the sealer, runner and scorer. They are not an evaluation cohort and
carry no scientific claim about any model.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from scripts import a02_v3_contract as v3
from scripts import a03_internal_seal as seal_module
from scripts.research_scenarios import SyntheticScenario, validate_scenario

import dynamislm as d
from dynamislm.longitudinal.statistics import RES69_ABSOLUTE_CHANGE_OPERATION
from dynamislm.serialization import canonical_json
from dynamislm.training_data.synthetic_science import make_support

RES69 = RES69_ABSOLUTE_CHANGE_OPERATION.stable_id
ABS = "SCALAR_ABSOLUTE_CHANGE"
OWNER = "fixture-owner"
STRATA = ("FAMILIAR_INTENT", "NOVEL_LANGUAGE", "AUTHORITY_HAZARD", "OUT_OF_SCOPE")
SYLLABLES = ("ka", "ro", "mi", "tu", "ve", "sa", "lo", "ni", "pe", "du", "fa", "gi", "bo", "ze")
CAUSAL, PRACTICAL = "CAUSAL_EVIDENCE", "PRACTICAL_OR_DECISION_MEANINGFULNESS"
ABSTAIN: dict[str, Any] = {
    "analysis_class": "NONE",
    "observation_ids": [],
    "operation": "NONE",
    "target_claims": {"measurement": [], "relationship": []},
}


def hexid(text: str, width: int) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:width]


def action(
    *,
    ids: tuple[str, ...] = ("observation-1", "observation-2"),
    analysis: str = ABS,
    operation: str = RES69,
    measurement: tuple[str, ...] = ("NUMERICAL_CHANGE",),
    relationship: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "analysis_class": analysis,
        "operation": operation,
        "observation_ids": list(ids),
        "target_claims": {"measurement": list(measurement), "relationship": list(relationship)},
    }


def judgment(
    control: str,
    actions: list[dict[str, Any]],
    *,
    allowed: tuple[str, ...] = (),
    reasons: tuple[str, ...] = (),
    preferred: bool = True,
) -> dict[str, Any]:
    return {
        "scientific_validity": "INVALID" if control == "REFUSE" else "VALID",
        "control": control,
        "preferred_action": actions[0] if preferred and len(actions) == 1 else None,
        "acceptable_actions": actions,
        "dispatch_operation": RES69 if control == "EXECUTE" else None,
        "allowed_claims": {"measurement": list(allowed), "relationship": []},
        "refusal_codes": list(reasons),
    }


EXEC = judgment("EXECUTE", [action()], allowed=("NUMERICAL_CHANGE",))
OBSERVE = judgment(
    "OBSERVATION_ONLY",
    [action(analysis="NONE", operation="NONE", measurement=("OBSERVED_VALUE",))],
    allowed=("OBSERVED_VALUE",),
)
CAUSAL_FLAG = judgment(
    "REFUSE",
    [action(relationship=(CAUSAL,))],
    allowed=("NUMERICAL_CHANGE",),
    reasons=("RES70_UNSUPPORTED_CAUSAL_CLAIM",),
)
CAUSAL_ABSTAIN = judgment("ABSTAIN", [ABSTAIN], reasons=("V3_NO_ACTION_PROPOSED",))
PRACTICAL_FLAG = judgment(
    "REFUSE",
    [action(measurement=(PRACTICAL,))],
    allowed=("NUMERICAL_CHANGE",),
    reasons=("RES70_UNSUPPORTED_CLAIM_ESCALATION",),
)


class Words:
    """A deterministic supply of never-repeated pseudo-words, so fixtures never overlap."""

    def __init__(self) -> None:
        self.counter = 200

    def text(self, count: int) -> str:
        out = []
        for _ in range(count):
            n, self.counter = self.counter, self.counter + 1
            base = len(SYLLABLES)
            out.append(
                SYLLABLES[n % base] + SYLLABLES[(n // base) % base] + SYLLABLES[n // base**2]
            )
        return " ".join(out)


@cache
def scenario_text(index: int, values: tuple[float, ...] | None = None) -> tuple[str, str]:
    """Owner-style synthetic scenario with three qualified observations. Returns (id, JSON)."""
    rng = random.Random(index * 7919 + 13)
    series = values or tuple(round(rng.uniform(0.15, 0.6), 6) for _ in range(3))
    scenario_id = f"eval-{hexid(f'cluster-{index}', 12)}"
    scenario = build_scenario(scenario_id, f"internal-fixture-{index}", series)
    return scenario_id, canonical_json(scenario)


def build_scenario(scenario_id: str, key: str, series: tuple[float, ...]) -> SyntheticScenario:
    support = make_support(key, series).analysis_input
    entries = support.entries
    record = d.build_longitudinal_record(
        support.athlete, entries, d.LongitudinalRecordOrigin.SYNTHETIC_DETERMINISTIC
    )
    source = d.build_multi_source_analysis_input(
        record.athlete, entries, d.MultiSourceAnalysisScope.SAME_SESSION
    )
    scenario = SyntheticScenario(scenario_id, source, (record,))
    validate_scenario(scenario)
    return scenario


LAYOUT = {
    "FAMILIAR_INTENT": ((EXEC, ()), (OBSERVE, ())),
    "NOVEL_LANGUAGE": ((EXEC, ()), (OBSERVE, ())),
    "AUTHORITY_HAZARD": (
        (CAUSAL_FLAG, ("CAUSAL_OVERREACH",)),
        (CAUSAL_ABSTAIN, ("CAUSAL_OVERREACH",)),
        (PRACTICAL_FLAG, ("PRACTICAL_MEANING",)),
    ),
    "OUT_OF_SCOPE": (
        (PRACTICAL_FLAG, ("PRACTICAL_MEANING",)),
        (CAUSAL_ABSTAIN, ("CAUSAL_OVERREACH",)),
    ),
}


@dataclass
class Packet:
    scenarios: list[dict[str, Any]] = field(default_factory=list)
    requests: list[dict[str, Any]] = field(default_factory=list)
    gold: list[dict[str, Any]] = field(default_factory=list)
    attestation: dict[str, Any] = field(default_factory=dict)

    def files(self) -> dict[str, bytes]:
        def lines(rows: list[dict[str, Any]]) -> bytes:
            return "".join(v3.canonical(row) + "\n" for row in rows).encode()

        return {
            "scenarios.jsonl": lines(self.scenarios),
            "requests.jsonl": lines(self.requests),
            "gold.jsonl": lines(self.gold),
            "attestation.json": (v3.canonical(self.attestation) + "\n").encode(),
        }

    def write(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        for name, data in self.files().items():
            (directory / name).write_bytes(data)
        return directory

    def drop_cluster(self, cluster: str) -> None:
        gone = {r["item_id"] for r in self.requests if r["cluster_id"] == cluster}
        self.scenarios = [s for s in self.scenarios if s["cluster_id"] != cluster]
        self.requests = [r for r in self.requests if r["cluster_id"] != cluster]
        self.gold = [g for g in self.gold if g["item_id"] not in gone]

    def items_of(self, cluster: str) -> list[dict[str, Any]]:
        return [r for r in self.requests if r["cluster_id"] == cluster]

    def gold_of(self, item: str) -> dict[str, Any]:
        return next(g for g in self.gold if g["item_id"] == item)


def valid_packet() -> Packet:
    """Forty-eight owner-style clusters, twelve per stratum, 108 items. Fresh on every call."""
    words = Words()
    packet = Packet(
        attestation={
            "schema": "DYNAMISLM_A03_INTERNAL_ATTESTATION_V1",
            "owner_id": OWNER,
            "owner_authored_all_items": True,
            "gold_recorded_before_inference": True,
            "no_a02_template_or_generator_reuse": True,
            "independence": "NONE",
        }
    )
    index = 0
    for stratum in STRATA:
        for _ in range(12):
            scenario_id, text = scenario_text(index)
            cluster = f"cluster-{index:02d}"
            packet.scenarios.append(
                {
                    "cluster_id": cluster,
                    "scenario_id": scenario_id,
                    "stratum": stratum,
                    "narrative": words.text(16),
                    "scenario": text,
                }
            )
            for position, (gold, families) in enumerate(LAYOUT[stratum]):
                item = hexid(f"item-{index}-{position}", 16)
                packet.requests.append(
                    {
                        "item_id": item,
                        "cluster_id": cluster,
                        "critical_families": list(families),
                        "question": words.text(12),
                    }
                )
                packet.gold.append(
                    {
                        "item_id": item,
                        "adjudicator_id": OWNER,
                        "judgment": json.loads(json.dumps(gold)),
                        "rationale": "Owner adjudication of this synthetic fixture item.",
                    }
                )
            index += 1
    assert seal_module.FILES == tuple(packet.files())
    return packet
