"""Validate and seal an INTERNAL_OWNER_ADJUDICATED A0.3 packet and export its blinded inputs.

Reuses the RES-746 sealer's judgment validation, the RES-430 scenario validator and the frozen
internal configuration. It never relaxes a prospective rule and never accepts a prospective
packet.
"""

from __future__ import annotations

import argparse
import math
import re
from collections import defaultdict
from collections.abc import Iterable
from functools import cache
from pathlib import Path
from statistics import fmean
from typing import Any

from dynamislm.longitudinal.statistics import RES69_ABSOLUTE_CHANGE_OPERATION
from dynamislm.measurement.result import ScalarValue
from dynamislm.serialization import canonical_hash, canonical_json, from_canonical_json
from scripts import a02_v3_contract as v3
from scripts import a02_v3_decision as historical
from scripts import a02_v3_score as historical_score
from scripts import a02_v3_synthetic as synthetic
from scripts import a03_benchmark_seal as prospective_sealer
from scripts import a03_internal_config as config
from scripts import a03_internal_replay as replay
from scripts.research_scenarios import (
    CATALOGUE,
    SyntheticScenario,
    packaged_scenario,
    validate_scenario,
)

SCHEMA = "DYNAMISLM_A03_INTERNAL_PACKET_V1"
ATTESTATION_SCHEMA = "DYNAMISLM_A03_INTERNAL_ATTESTATION_V1"
FILES = ("scenarios.jsonl", "requests.jsonl", "gold.jsonl", "attestation.json")
BLIND_FILES = ("blind-scenarios.jsonl", "blind-requests.jsonl")
RELEASE_FILE = "gold-release.json"
RES69 = RES69_ABSOLUTE_CHANGE_OPERATION.stable_id
HAZARD_STRATA = ("AUTHORITY_HAZARD", "OUT_OF_SCOPE")


class PacketRefusalError(ValueError):
    """A packet that cannot be sealed. Nothing is merged, excluded or repaired."""


def refuse(message: str) -> PacketRefusalError:
    return PacketRefusalError(message)


# ---------------------------------------------------------------- text and series overlap


@cache
def _measurement_names() -> tuple[str, ...]:
    """Template measurement names are masked, so a renamed measurement cannot hide a template."""
    names = {
        name.casefold()
        for split in synthetic.MEASUREMENTS.values()
        for row in split
        for name in row[:2]
    }
    return tuple(sorted(names, key=lambda name: (-len(name), name)))


def tokens(text: str) -> list[str]:
    masked = text.casefold()
    for name in _measurement_names():
        masked = masked.replace(name, " measurement ")
    return re.findall(r"[a-z0-9]+", masked)


def shingles(text: str, width: int) -> frozenset[tuple[str, ...]]:
    words = tokens(text)
    if len(words) < width:
        return frozenset({tuple(words)}) if words else frozenset()
    return frozenset(tuple(words[i : i + width]) for i in range(len(words) - width + 1))


def jaccard(left: frozenset[tuple[str, ...]], right: frozenset[tuple[str, ...]]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def series_keys(values: list[float], decimals: int) -> frozenset[tuple[Any, ...]]:
    """Identity keys that make shifted, rescaled or reflected copies of a series collide.

    Three or more varying points compare after shift-and-scale normalization. Two points are
    equivalent under that normalization for every pair, so they compare on the raw values, the
    signed difference (a shifted copy) and the ratio (a rescaled copy). Constant or single
    points compare on raw values.
    """
    if not values:
        return frozenset()
    if any(not math.isfinite(v) for v in values):
        return frozenset({("NONFINITE", tuple(map(str, values)))})
    raw = ("RAW", tuple(round(v, decimals) for v in values))
    if len(values) == 2:
        keys = {raw, ("DELTA", round(values[1] - values[0], decimals))}
        if values[0] != 0:
            keys.add(("RATIO", round(values[1] / values[0], decimals)))
        return frozenset(keys)
    mean = fmean(values)
    spread = math.sqrt(fmean((v - mean) ** 2 for v in values))
    if len(values) < 2 or spread < 10 ** (-decimals):
        return frozenset({raw})
    scaled = [(v - mean) / spread for v in values]
    sign = -1.0 if next(s for s in scaled if abs(s) > 10 ** (-decimals)) < 0 else 1.0
    return frozenset({("SHAPE", tuple(round(sign * s + 0.0, decimals) for s in scaled))})


def _strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _strings(item)


@cache
def exposure_texts() -> tuple[str, ...]:
    """Every previously exposed or template phrasing the internal cohort must not echo."""
    texts = [prospective_sealer.EXPOSED_RESEARCH_CLI_QUESTION]
    texts.extend(
        text.replace("{m}", "measurement")
        for table in (synthetic.TEMPLATES, synthetic.ESCALATING_QUESTIONS)
        for text in _strings(table)
    )
    requests = [row["request"] for row in historical.heldout_examples(historical.load_protocol())]
    requests.extend(case["request"] for case in historical_score._cases().values())
    for request in requests:
        for field in ("objective", "question"):
            if isinstance(request.get(field), str):
                texts.append(request[field])
    texts.extend(name.replace("-", " ") for name in CATALOGUE)
    return tuple(texts)


def _numeric_series(value: object) -> list[float] | None:
    if not isinstance(value, list) or not value:
        return None
    numbers = [
        row["value"]
        for row in value
        if isinstance(row, dict)
        and isinstance(row.get("value"), int | float)
        and not isinstance(row.get("value"), bool)
    ]
    return [float(v) for v in numbers] if len(numbers) == len(value) else None


@cache
def exposure_series(decimals: int) -> frozenset[tuple[Any, ...]]:
    requests = [row["request"] for row in historical.heldout_examples(historical.load_protocol())]
    requests.extend(case["request"] for case in historical_score._cases().values())
    keys: set[tuple[Any, ...]] = set()
    for request in requests:
        if (values := _numeric_series(request.get("observations"))) is not None:
            keys |= series_keys(values, decimals)
    for name in CATALOGUE:
        keys |= series_keys(scenario_series(packaged_scenario(name)), decimals)
    return frozenset(keys)


# ---------------------------------------------------------------- scenario facts


def scenario_entries(scenario: SyntheticScenario) -> tuple[Any, ...]:
    if scenario.source is not None:
        return tuple(scenario.source.entries)
    return tuple(scenario.records[0].entries) if scenario.records else ()


def scenario_athlete(scenario: SyntheticScenario) -> Any:
    if scenario.source is not None:
        return scenario.source.athlete
    return scenario.records[0].athlete if scenario.records else None


def scenario_series(scenario: SyntheticScenario) -> list[float]:
    values = []
    for entry in scenario_entries(scenario):
        value = entry.observation.result.value
        if not isinstance(value, ScalarValue):
            raise refuse("scenario observations must be scalar for series distinctness")
        values.append(float(value.value))
    return values


def scenario_facts(scenario: SyntheticScenario) -> dict[str, Any]:
    entries = scenario_entries(scenario)
    athlete = scenario_athlete(scenario)
    artifacts = {
        artifact.content_digest
        for entry in entries
        for artifact in entry.observation.provenance.source_artifacts
    }
    return {
        "content": canonical_hash((scenario.source, scenario.records)),
        "series": scenario_series(scenario),
        "identity": (athlete.athlete_id.value, athlete.display_label) if athlete else None,
        "observations": {canonical_hash(entry.observation) for entry in entries},
        "records": {record.canonical_record_hash for record in scenario.records},
        "artifacts": artifacts,
        "ids": [f"observation-{i}" for i in range(1, len(entries) + 1)],
    }


# ---------------------------------------------------------------- packet validation


def _json_lines(data: bytes) -> list[dict[str, Any]]:
    if not data.endswith(b"\n"):
        raise refuse("JSONL is empty or has an unfinished line")
    return [v3.json_object(line) for line in data.decode("utf-8").splitlines()]


def _pattern(value: object, pattern: str, what: str) -> str:
    text = prospective_sealer._text(value)
    if not re.fullmatch(pattern, text):
        raise refuse(f"{what} must be an opaque identifier matching {pattern}")
    return text


def _signature(judgment: dict[str, Any], families: list[str]) -> str:
    actions = sorted(
        v3.canonical(v3.normalize_action(action)) for action in judgment["acceptable_actions"]
    )
    return v3.canonical([actions, judgment["allowed_claims"], sorted(families)])


def _read(directory: Path) -> dict[str, bytes]:
    if not directory.is_dir() or directory.is_symlink():
        raise refuse("packet must be a regular directory")
    present = {p.name for p in directory.iterdir() if p.name not in (*BLIND_FILES, RELEASE_FILE)}
    if present != set(FILES):
        raise refuse(f"packet files differ: {sorted(present ^ set(FILES))}")
    for name in FILES:
        if (directory / name).is_symlink():
            raise refuse("packet files must not be symlinks")
    return {name: (directory / name).read_bytes() for name in FILES}


@cache
def _scenario_info(text: str) -> tuple[SyntheticScenario, str, dict[str, Any]]:
    """Pure: canonical text to a validated RES-430 scenario, its digest and distinctness facts."""
    scenario = from_canonical_json(text, SyntheticScenario)
    if canonical_json(scenario) != text:
        raise ValueError("noncanonical scenario text")
    validate_scenario(scenario)
    return scenario, canonical_hash(scenario), scenario_facts(scenario)


def _clusters(cfg: dict[str, Any], content: dict[str, bytes]) -> dict[str, dict[str, Any]]:
    design, text = cfg["design"], cfg["distinctness"]
    clusters: dict[str, dict[str, Any]] = {}
    scenario_ids: set[str] = set()
    for row in _json_lines(content["scenarios.jsonl"]):
        prospective_sealer._fields(row, "cluster_id scenario_id stratum narrative scenario")
        cluster = prospective_sealer._key(row["cluster_id"])
        scenario_id = _pattern(row["scenario_id"], design["scenario_id_pattern"], "scenario_id")
        if cluster in clusters or scenario_id in scenario_ids:
            raise refuse("duplicate cluster or scenario identity")
        scenario_ids.add(scenario_id)
        if row["stratum"] not in cfg["strata"]:
            raise refuse("unknown sampling stratum")
        narrative = prospective_sealer._text(row["narrative"])
        try:
            scenario, digest, facts = _scenario_info(prospective_sealer._text(row["scenario"]))
        except (ValueError, TypeError, KeyError) as exc:
            raise refuse(f"scenario fails the RES-430 validator: {exc}") from exc
        if scenario.scenario_id != scenario_id:
            raise refuse("scenario identity differs from its declared identifier")
        clusters[cluster] = {
            "scenario_id": scenario_id,
            "stratum": row["stratum"],
            "digest": digest,
            "narrative": shingles(narrative, text["shingle_words"]),
            "scenario": row["scenario"],
            **facts,
        }
    return clusters


def _distinct_clusters(cfg: dict[str, Any], clusters: dict[str, dict[str, Any]]) -> None:
    text = cfg["distinctness"]
    seen: dict[str, dict[Any, str]] = defaultdict(dict)
    shape = text["series_decimals"]
    exposed = exposure_series(shape)
    packaged = {canonical_hash(packaged_scenario(name)) for name in CATALOGUE}
    for cluster, data in sorted(clusters.items()):
        if data["digest"] in packaged:
            raise refuse("cluster reuses a packaged RES-430 scenario")
        keys = series_keys(data["series"], shape)
        if keys & exposed:
            raise refuse("cluster reuses an exposed A0.2 or packaged observation series")
        groups: list[tuple[str, Iterable[Any]]] = [
            ("digest", [data["digest"]]),
            ("content", [data["content"]]),
            ("series", keys),
            ("identity", data["identity"] or ()),
            ("observation", data["observations"]),
            ("record", data["records"]),
            ("artifact", data["artifacts"]),
        ]
        for kind, values in groups:
            for value in values:
                if seen[kind].setdefault(value, cluster) != cluster:
                    raise refuse(f"{kind} is shared between clusters")
    limit = text["max_cross_cluster_narrative_jaccard"]
    ordered = sorted(clusters)
    for i, left in enumerate(ordered):
        for right in ordered[i + 1 :]:
            if jaccard(clusters[left]["narrative"], clusters[right]["narrative"]) >= limit:
                raise refuse("cluster narratives overlap beyond the frozen threshold")


def _items(
    cfg: dict[str, Any], clusters: dict[str, dict[str, Any]], content: dict[str, bytes]
) -> list[dict[str, Any]]:
    design, text, families = cfg["design"], cfg["distinctness"], cfg["families"]
    allowed_families = {*families["gated"], *families["reported"]}
    rows, seen = [], set()
    exposed = [shingles(t, text["shingle_words"]) for t in exposure_texts()]
    for row in _json_lines(content["requests.jsonl"]):
        prospective_sealer._fields(row, "item_id cluster_id critical_families question")
        item = _pattern(row["item_id"], design["item_id_pattern"], "item_id")
        if item in seen or row["cluster_id"] not in clusters:
            raise refuse("duplicate item or unknown cluster")
        seen.add(item)
        prospective_sealer._subset(row["critical_families"], tuple(sorted(allowed_families)))
        question = prospective_sealer._text(row["question"])
        if "<|" in question or len(question.encode()) > 4096:
            raise refuse("question is not a valid ask input")
        grams = shingles(question, text["shingle_words"])
        for other in exposed:
            if jaccard(grams, other) >= text["max_exposure_jaccard"]:
                raise refuse("exposed A0.2, D0, demonstration or template phrasing")
        rows.append({**row, "grams": grams})
    by_cluster: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_cluster[row["cluster_id"]].append(row)
    if set(by_cluster) != set(clusters):
        raise refuse("every cluster needs items")
    for members in by_cluster.values():
        if not design["min_items_per_cluster"] <= len(members) <= design["max_items_per_cluster"]:
            raise refuse("cluster item count is outside the frozen 2 to 3")
        for i, left in enumerate(members):
            for right in members[i + 1 :]:
                if (
                    jaccard(left["grams"], right["grams"])
                    >= text["max_within_cluster_question_jaccard"]
                ):
                    raise refuse("paraphrase-only items within a cluster")
    limit = text["max_cross_cluster_question_jaccard"]
    for i, left in enumerate(rows):
        for right in rows[i + 1 :]:
            if (
                left["cluster_id"] != right["cluster_id"]
                and jaccard(left["grams"], right["grams"]) >= limit
            ):
                raise refuse("questions overlap across clusters")
    return rows


def _gold(
    cfg: dict[str, Any],
    clusters: dict[str, dict[str, Any]],
    items: list[dict[str, Any]],
    content: dict[str, bytes],
    owner: str,
) -> dict[str, dict[str, Any]]:
    by_id = {row["item_id"]: row for row in items}
    judgments: dict[str, dict[str, Any]] = {}
    for row in _json_lines(content["gold.jsonl"]):
        prospective_sealer._fields(row, "item_id adjudicator_id judgment rationale")
        item = prospective_sealer._key(row["item_id"])
        if item in judgments or item not in by_id:
            raise refuse("unresolved or duplicate gold item")
        if row["adjudicator_id"] != owner:
            raise refuse("missing or non-owner adjudication")
        prospective_sealer._text(row["rationale"])
        cluster = clusters[by_id[item]["cluster_id"]]
        try:
            prospective_sealer._judgment(row["judgment"], cluster["ids"])
        except ValueError as exc:
            raise refuse(f"invalid gold judgment: {exc}") from exc
        judgment = row["judgment"]
        if judgment["control"] == "EXECUTE" and judgment["dispatch_operation"] != RES69:
            raise refuse("only the RES-69 absolute change may be an execution control")
        if judgment["control"] == "EXECUTE" and not replay.gold_fingerprints(
            _scenario_info(cluster["scenario"])[0], by_id[item]["question"], judgment
        ):
            raise refuse("execution gold is not executable by the engine")
        for family, spec in cfg["families"]["gated"].items():
            if family in by_id[item]["critical_families"] and (
                spec["level"] in judgment["allowed_claims"][spec["axis"]]
            ):
                raise refuse("family item gold must not allow the family's claim level")
        judgments[item] = judgment
    if judgments.keys() != by_id.keys():
        raise refuse("missing adjudication")
    for cluster_id in clusters:
        signatures = [
            _signature(judgments[r["item_id"]], r["critical_families"])
            for r in items
            if r["cluster_id"] == cluster_id
        ]
        if len(signatures) != len(set(signatures)):
            raise refuse("items in a cluster must differ in gold action, claims or family")
    controls = {judgment["control"] for judgment in judgments.values()}
    if not {"EXECUTE", "REFUSE"}.issubset(controls):
        raise refuse("packet needs both positive and negative controls")
    return judgments


def _attestation(content: dict[str, bytes]) -> dict[str, Any]:
    row = v3.json_object(content["attestation.json"].decode("utf-8"))
    prospective_sealer._fields(
        row,
        "schema owner_id owner_authored_all_items gold_recorded_before_inference "
        "no_a02_template_or_generator_reuse independence",
    )
    prospective_sealer._key(row["owner_id"])
    if (
        row["schema"] != ATTESTATION_SCHEMA
        or row["independence"] != config.INDEPENDENCE
        or row["owner_authored_all_items"] is not True
        or row["gold_recorded_before_inference"] is not True
        or row["no_a02_template_or_generator_reuse"] is not True
    ):
        raise refuse("owner attestation is missing, false or claims independence")
    return row


def support(
    cfg: dict[str, Any],
    clusters: dict[str, dict[str, Any]],
    items: list[dict[str, Any]],
    judgments: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Effective support per endpoint, from gold. Mirrors the scorer's populations."""
    stratum = {cluster: data["stratum"] for cluster, data in clusters.items()}

    def population(predicate: Any, rows: list[dict[str, Any]] | None = None) -> dict[str, int]:
        chosen = [r for r in (rows or items) if predicate(r, judgments[r["item_id"]])]
        return {
            "items": len(chosen),
            "clusters": len({r["cluster_id"] for r in chosen}),
            "strata": len({stratum[r["cluster_id"]] for r in chosen}),
        }

    result = {
        "HAZARD_REFUSAL": population(
            lambda r, j: stratum[r["cluster_id"]] in HAZARD_STRATA
            and j["control"] in ("REFUSE", "ABSTAIN")
        ),
        "NOVEL_INTENT": population(
            lambda r, j: stratum[r["cluster_id"]] == "NOVEL_LANGUAGE"
            and j["control"] != "AMBIGUOUS"
        ),
        "EXECUTION_COVERAGE": population(lambda r, j: j["control"] == "EXECUTE"),
    }
    for family in cfg["families"]["gated"]:
        result[family] = population(lambda r, j, f=family: f in r["critical_families"])
    for family in cfg["families"]["reported"]:
        result[family] = population(lambda r, j, f=family: f in r["critical_families"])
    return result


def seal(directory: Path) -> dict[str, Any]:
    """Refuse an invalid packet whole. Return the sealed manifest, which excludes all gold."""
    cfg = config.load_config()
    content = _read(directory)
    attestation = _attestation(content)
    clusters = _clusters(cfg, content)
    _distinct_clusters(cfg, clusters)
    items = _items(cfg, clusters, content)
    judgments = _gold(cfg, clusters, items, content, attestation["owner_id"])
    design = cfg["design"]
    strata = {name: 0 for name in cfg["strata"]}
    for data in clusters.values():
        strata[data["stratum"]] += 1
    if (
        len(clusters) < design["min_clusters"]
        or any(count < design["min_clusters_per_stratum"] for count in strata.values())
        or not design["min_items"] <= len(items) <= design["max_items"]
    ):
        raise refuse("packet is below the frozen cluster, stratum or item minimums")
    counts = support(cfg, clusters, items, judgments)
    for name, spec in cfg["endpoints"].items():
        if "min_clusters" in spec and counts[name]["clusters"] < spec["min_clusters"]:
            raise refuse(f"insufficient effective support for {name}")
    families = cfg["families"]
    for family in families["gated"]:
        got = counts[family]
        if (
            got["clusters"] < families["min_family_clusters"]
            or got["strata"] < families["min_family_strata"]
            or got["items"] < families["min_family_items"]
        ):
            raise refuse(f"insufficient family support for {family}")
    return {
        "schema": SCHEMA,
        **config.identity(),
        "owner_id": attestation["owner_id"],
        "clusters": len(clusters),
        "items": len(items),
        "stratum_clusters": strata,
        "support": counts,
        "files": {name: v3.sha256(data) for name, data in content.items()},
    }


def blind_export(directory: Path) -> dict[str, bytes]:
    """Gold-free runner inputs. Identifiers are opaque and the order carries no authoring order."""
    content = _read(directory)
    scenarios = {row["cluster_id"]: row for row in _json_lines(content["scenarios.jsonl"])}
    requests = sorted(_json_lines(content["requests.jsonl"]), key=lambda row: row["item_id"])
    used = sorted({scenarios[row["cluster_id"]]["scenario_id"] for row in requests})
    by_scenario = {row["scenario_id"]: row for row in scenarios.values()}
    blind_scenarios = [
        {"scenario_id": name, "scenario": by_scenario[name]["scenario"]} for name in used
    ]
    blind_requests = [
        {
            "item_id": row["item_id"],
            "scenario_id": scenarios[row["cluster_id"]]["scenario_id"],
            "question": row["question"],
        }
        for row in requests
    ]
    return {
        "blind-scenarios.jsonl": "".join(v3.canonical(r) + "\n" for r in blind_scenarios).encode(),
        "blind-requests.jsonl": "".join(v3.canonical(r) + "\n" for r in blind_requests).encode(),
    }


def packet_sha256(manifest: dict[str, Any]) -> str:
    return v3.sha256(v3.canonical(manifest).encode())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet", type=Path)
    parser.add_argument("--blind-out", type=Path)
    args = parser.parse_args()
    manifest = seal(args.packet)
    output: dict[str, Any] = {"manifest": manifest, "packet_sha256": packet_sha256(manifest)}
    if args.blind_out is not None:
        exported = blind_export(args.packet)
        if args.blind_out.exists() and any(args.blind_out.iterdir()):
            raise ValueError("blind export directory must be new or empty")
        args.blind_out.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name, data in exported.items():
            (args.blind_out / name).write_bytes(data)
        output["blind_files"] = {n: v3.sha256(d) for n, d in exported.items()}
    print(v3.canonical(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
