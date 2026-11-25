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


def two_point(index: int) -> tuple[float, float]:
    rng = random.Random(index * 104729 + 7)
    return round(rng.uniform(0.15, 0.35), 6), round(rng.uniform(0.36, 0.6), 6)


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


def valid_packet(points: int = 3) -> Packet:
    """Forty-eight owner-style clusters, twelve per stratum, 108 items. Fresh on every call.

    `points=2` builds every scenario from two observations, the shape the two-point screen covers.
    """
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
            scenario_id, text = scenario_text(index, two_point(index) if points == 2 else None)
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


# ---------------------------------------------------------------------------- run fixtures

BUNDLE_SHA = "ab" * 32
IDENTITY: dict[str, Any] = {
    "bundle": {"archive_sha256": BUNDLE_SHA, "distribution": "FIXTURE"},
    "adapter": {"weights_sha256": "cd" * 32},
    "base": {"revision": "fixture"},
}
FIXTURE_SOURCE = {"commit": "f" * 40, "tree": "e" * 40, "checkout_sha256": "d" * 64}


class FakeTokenizer:
    """Satisfies the V3 prompt contract. It tokenizes nothing and carries no model."""

    def apply_chat_template(self, messages: Any, *, tokenize: bool, **_: Any) -> Any:
        return [1] if tokenize else "fixture prompt"

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]:
        return [1]


def grammar_text(candidate: dict[str, Any], request: dict[str, Any]) -> str:
    from scripts import a02_v3_constrained as c0

    return str(
        c0.decode(
            request=request,
            prompt_ids=[],
            encode=lambda text: list(text.encode()),
            chooser=c0.target_chooser(candidate),
        )["text"]
    )


class Scripted:
    """A scripted stand-in for the pinned model. `outputs` maps (question, arm) to raw text."""

    def __init__(self, outputs: dict[tuple[str, str], str | Exception]) -> None:
        self.outputs = outputs
        self.tokenizer = FakeTokenizer()
        self.calls: list[tuple[str, str]] = []

    def generate(
        self, arm: str, request: dict[str, Any], prompt: list[int], deadline: float
    ) -> Any:
        from scripts.a03_model_core import EOS
        from scripts.a03_model_runtime import Generation

        self.calls.append((request["question"], arm))
        out = self.outputs[request["question"], arm]
        if isinstance(out, Exception):
            raise out
        return Generation([5, EOS], out, "MODEL_EOS")


def scenario_of(packet: Packet, cluster: str) -> Any:
    row = next(s for s in packet.scenarios if s["cluster_id"] == cluster)
    return seal_module._scenario_info(row["scenario"])[0]


def scripted_outputs(packet: Packet, choose: Any = None) -> dict[tuple[str, str], str | Exception]:
    """Raw output per (question, arm). `choose(item, gold, arm)` returns an action dict."""
    from scripts import research_ask as research

    outputs: dict[tuple[str, str], str | Exception] = {}
    for item in packet.requests:
        gold = packet.gold_of(item["item_id"])["judgment"]
        bound = research.prepare_request(scenario_of(packet, item["cluster_id"]), item["question"])
        for arm in ("N", "C1"):
            picked = choose(item, gold, arm) if choose else gold["acceptable_actions"][0]
            outputs[item["question"], arm] = (
                picked
                if isinstance(picked, Exception)
                else grammar_text(picked, bound.model_request())
                if isinstance(picked, dict)
                else str(picked)
            )
    return outputs


def prepare_run(tmp_path: Path, packet: Packet, backend: Any) -> dict[str, Any]:
    """Seal, export blind inputs and build the manifest. Nothing is generated yet."""
    import os

    from scripts import a03_internal_run as run_module
    from scripts import a03_prospective_run as prospective_run
    from scripts import research_ask as research

    os.chmod(tmp_path, 0o700)
    protected = packet.write(tmp_path / "protected")
    protected.chmod(0o700)
    manifest_packet = seal_module.seal(protected)
    blind = tmp_path / "blind"
    blind.mkdir(mode=0o700)
    exported = seal_module.blind_export(protected)
    for name, data in exported.items():
        (blind / name).write_bytes(data)
    requests, scenarios = exported["blind-requests.jsonl"], exported["blind-scenarios.jsonl"]
    manifest = run_module.run_manifest(
        requests,
        scenarios,
        packet_sha256=prospective_run.object_hash(manifest_packet),
        bundle_archive_sha256=BUNDLE_SHA,
        source=FIXTURE_SOURCE,
    )
    output = tmp_path / "out"
    output.mkdir(mode=0o700)
    return {
        "protected": protected,
        "blind": blind,
        "output": output,
        "manifest": manifest,
        "packet_manifest": manifest_packet,
        "requests": requests,
        "scenarios": scenarios,
        "runtime": research.ResearchRuntime(backend, IDENTITY),
    }


def pack_and_run(
    tmp_path: Path, packet: Packet, backend: Any, *, seconds: float = 3600.0
) -> dict[str, Any]:
    from scripts import a03_internal_run as run_module

    prepared = prepare_run(tmp_path, packet, backend)
    prepared["result"] = run_module.run(
        prepared["manifest"],
        prepared["requests"],
        prepared["scenarios"],
        prepared["output"],
        prepared["runtime"],
        seconds=seconds,
        verify_source=False,
    )
    return prepared


def release_gold(run: dict[str, Any], *, commit_sha256: str | None = None) -> tuple[Path, str]:
    """The custodian step: release gold only after the output commitment exists."""
    from scripts import a03_internal_run as run_module

    commit = run["output"] / "output-commit.json"
    digest = commit_sha256 or v3.sha256(commit.read_bytes())
    release = {
        "schema": "DYNAMISLM_A03_INTERNAL_GOLD_RELEASE_V1",
        "mode": "INTERNAL_OWNER_ADJUDICATED",
        "output_commit_sha256": digest,
        "packet": run["packet_manifest"],
    }
    path = run["protected"] / seal_module.RELEASE_FILE
    path.write_text(v3.canonical(release) + "\n")
    del run_module
    return path, v3.sha256(path.read_bytes())


def score_run(run: dict[str, Any], **kw: Any) -> dict[str, Any]:
    from scripts import a03_internal_run as run_module
    from scripts import a03_internal_score as score_module

    path, release_sha = release_gold(run)
    return score_module.score(
        run["manifest"],
        run["requests"],
        run["scenarios"],
        run["output"],
        v3.sha256((run["output"] / "output-commit.json").read_bytes()),
        path,
        release_sha,
        FakeTokenizer(),
        bundle_archive_sha256=kw.pop("bundle_archive_sha256", BUNDLE_SHA),
        verify_source=False,
        **kw,
    ) | {"_run_module": run_module.SCHEMA}


def install_memoization(monkeypatch: Any) -> None:
    """Speed only: RES-70 admission and `seal` are deterministic functions of their inputs.

    Both are tested directly elsewhere. Memoizing them here lets the runner and scorer tests
    exercise many model behaviours without repeating identical engine work. A permissive permit
    callback is replayed from the recorded attempts, so dispatch capture is still exercised.
    """
    import copy

    from scripts import a03_internal_replay as replay_module
    from scripts import research_ask as research
    from scripts.a03_scientific_admission import submit_scientific_action_v3

    real_submit = submit_scientific_action_v3
    real_seal = seal_module.seal
    submissions: dict[Any, Any] = {}
    seals: dict[Any, Any] = {}

    def submit(bound: Any, raw: Any, *, permit_dispatch: Any = None) -> Any:
        key = (
            type(bound).__name__,
            bound.question,
            id(bound.source),
            id(bound.records),
            v3.sha256(str(raw).encode()),
        )
        if key not in submissions:
            attempts: list[str] = []

            def record(operation: str) -> bool:
                attempts.append(operation)
                return True

            submissions[key] = (real_submit(bound, raw, permit_dispatch=record), tuple(attempts))
        decision, attempts_seen = submissions[key]
        for operation in attempts_seen if permit_dispatch is not None else ():
            assert permit_dispatch(operation), "memoization only supports permissive permits"
        return decision

    def cached_seal(directory: Path, *, owner_key: Path | None = None) -> Any:
        if owner_key is not None or (directory / "provenance.json").exists():
            return real_seal(directory, owner_key=owner_key)
        key = tuple(
            (name, v3.sha256((directory / name).read_bytes())) for name in seal_module.FILES
        )
        if key not in seals:
            seals[key] = real_seal(directory)
        return copy.deepcopy(seals[key])

    monkeypatch.setattr(replay_module, "submit_scientific_action_v3", submit)
    monkeypatch.setattr(research, "submit_scientific_action_v3", submit)
    monkeypatch.setattr(seal_module, "seal", cached_seal)
