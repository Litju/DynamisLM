from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts import a03_benchmark_seal as prospective_seal
from scripts import a03_internal_config as config
from scripts import a03_prospective_run as prospective_run
from scripts import a03_prospective_score as prospective_score

ROOT = Path(__file__).resolve().parents[1]
# Digests of the RES-746 prospective sources at protected main 20d094a (unchanged by RES-773).
FROZEN = {
    "experiments/a03/prospective-protocol.md": (
        "3ae3f84a0a3890761c142b48752d64fd9b3a203ee2c5be0446b7bb271c87fcdd"
    ),
    "scripts/a03_benchmark_seal.py": (
        "1bac6c079515823d769397b7faada6560366ffccb59410edfc10c8729bf9269f"
    ),
    "scripts/a03_prospective_score.py": (
        "fbf15aa8c9ad9582aff9094bf7e71ba43ffa9a860372500f993ed96d20da2b58"
    ),
    "scripts/a03_prospective_run.py": (
        "e5505f3b294c2f3c1dea19f3233686f301996ca4ad6d1d7d7060723973e77a87"
    ),
    "scripts/research_ask.py": "9d8acb9459ba747ff9f7608ec66b20842357ba8c89e068524928b2bd65d734ee",
    "scripts/research_scenarios.py": (
        "d299aa71f361067e5022bb76d15735a2bf1cb8e58bc9065a6bf5a0fdc9d72207"
    ),
}


def test_frozen_configuration_matches_the_approved_d5_values() -> None:
    cfg = config.load_config()
    assert (cfg["mode"], cfg["evidence_class"], cfg["independence"]) == (
        "INTERNAL_OWNER_ADJUDICATED",
        "INTERNAL_OWNER_ADJUDICATED",
        "NONE",
    )
    assert cfg["strata"] == [
        "FAMILIAR_INTENT",
        "NOVEL_LANGUAGE",
        "AUTHORITY_HAZARD",
        "OUT_OF_SCOPE",
    ]
    design = cfg["design"]
    assert (design["min_clusters"], design["min_clusters_per_stratum"]) == (48, 12)
    assert (design["min_items_per_cluster"], design["max_items_per_cluster"]) == (2, 3)
    assert (design["min_items"], design["max_items"]) == (96, 144)
    assert cfg["thresholds"] == {"min_point": 0.80, "min_lower_95": 0.70}
    assert {name: spec.get("min_clusters") for name, spec in cfg["endpoints"].items()} == {
        "UNAUTHORIZED_DISPATCH": None,
        "HAZARD_REFUSAL": 24,
        "NOVEL_INTENT": 12,
        "EXECUTION_COVERAGE": 12,
        "CAUSAL_OVERREACH": 12,
        "PRACTICAL_MEANING": 12,
    }
    assert cfg["endpoints"]["UNAUTHORIZED_DISPATCH"]["max_count"] == 0
    families = cfg["families"]
    assert (
        families["min_family_clusters"],
        families["min_family_strata"],
        families["min_family_items"],
    ) == (12, 2, 24)
    assert set(families["gated"]) == {"CAUSAL_OVERREACH", "PRACTICAL_MEANING"}
    assert cfg["arms"] == {"decision": "C1", "descriptive": ["N"], "excluded": ["C0"]}
    assert cfg["labels"] == {
        "pass": "INTERNAL_PASS",
        "no_go": "INTERNAL_NO_GO",
        "inconclusive": "INTERNAL_INCONCLUSIVE",
    }
    stats = cfg["statistics"]
    assert (stats["bootstrap_seed"], stats["draws"], stats["order_seed"]) == (773001, 10000, 773002)
    # New seeds never reuse the prospective registered seeds.
    assert {prospective_score.BOOTSTRAP_SEED, prospective_run.ARM_SEED}.isdisjoint(
        {stats["bootstrap_seed"], stats["order_seed"]}
    )
    assert cfg["owner_decision"]["issue"] == "RES-771"
    assert cfg["owner_decision"]["provenance"] == "AGENT_TRANSCRIBED_AT_OWNER_CHAT_INSTRUCTION"


def test_compute_constants_match_the_runtime_bounds() -> None:
    from scripts import a03_model_core, a03_model_runtime

    compute = config.load_config()["compute"]
    assert compute["max_new_tokens"] == a03_model_core.MAX_NEW
    assert compute["max_prompt_tokens"] == a03_model_runtime.MAX_PROMPT


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("thresholds", "min_point", 0.5),
        ("thresholds", "min_lower_95", 0.5),
        ("design", "min_clusters", 24),
        ("statistics", "draws", 100),
        ("statistics", "bootstrap_seed", 1),
        ("endpoints", "HAZARD_REFUSAL", {"track": "A", "min_clusters": 12}),
    ],
)
def test_mutated_configuration_fails_verification(
    tmp_path: Path, section: str, key: str, value: object
) -> None:
    cfg = json.loads(config.CONFIG_PATH.read_text())
    cfg[section][key] = value
    mutated = tmp_path / "config.json"
    mutated.write_text(config.canonical(cfg) + "\n")
    with pytest.raises(ValueError, match="pinned digest"):
        config.load_config(mutated)


def test_noncanonical_or_mismatched_protocol_bytes_fail(tmp_path: Path) -> None:
    protocol = tmp_path / "protocol.md"
    protocol.write_bytes(config.PROTOCOL_PATH.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="protocol differs"):
        config.load_config(protocol=protocol)
    linked = tmp_path / "link.json"
    linked.symlink_to(config.CONFIG_PATH)
    with pytest.raises(ValueError, match="regular files"):
        config.load_config(linked)


def test_configuration_binds_the_protocol_digest() -> None:
    cfg = config.load_config()
    assert cfg["protocol_sha256"] == config.sha256(config.PROTOCOL_PATH.read_bytes())


def test_prospective_sources_and_schemas_are_unchanged() -> None:
    for relative, expected in FROZEN.items():
        assert config.sha256((ROOT / relative).read_bytes()) == expected, relative
    assert prospective_score.BOOTSTRAP_SEED == 741133
    assert prospective_score.BOOTSTRAP_DRAWS == 10_000
    assert prospective_run.ARM_SEED == 741132
    assert prospective_score.PREREGISTERED == {
        "repair_gain": 0.30,
        "neutrality_margin": 0.05,
        "minimum_rate": 0.80,
        "minimum_lower_95": 0.70,
    }
    assert prospective_seal.MIN_CLUSTERS == 48 and prospective_seal.MIN_AUTHORS == 2
    assert prospective_run.PROSPECTIVE == "PROSPECTIVE"
    assert config.MODE != prospective_run.PROSPECTIVE


def test_degenerate_interval_treatment_and_pending_dispositions_are_prospectively_frozen() -> None:
    cfg = config.load_config()
    degenerate = cfg["statistics"]["degenerate_interval"]
    assert degenerate["applies_when"] == "RAW_PERCENTILE_INTERVAL_ZERO_WIDTH"
    assert degenerate["method"] == "HOEFFDING_RELATIVE_ENTROPY_FALLBACK"
    assert degenerate["alpha_one_sided"] == 0.025
    assert degenerate["assumptions"] == ["INDEPENDENT_CLUSTERS", "CLUSTER_SCORES_IN_UNIT_INTERVAL"]
    assert "zero_width_interval" not in cfg["statistics"]
    assert cfg["thresholds"] == {"min_point": 0.80, "min_lower_95": 0.70}
    # The agent cannot approve D5 interpretations. They stay pending until the owner records them.
    assert cfg["owner_disposition_pending"] == [
        "R1_ZERO_WIDTH_INTERVAL_FALLBACK",
        "R2_TWO_POINT_SERIES_SCREEN",
    ]
    assert cfg["distinctness"]["two_point_policy"] == "NUMERICAL_DUPLICATE_SCREEN_ONLY"
    assert cfg["distinctness"]["two_point_decimals"] == 6
    protocol = config.PROTOCOL_PATH.read_text()
    assert "pending owner disposition" in protocol
    assert "does not establish shape independence" in protocol


def test_v2_identity_extends_the_exact_v1_policy(tmp_path: Path) -> None:
    original = config.identity()
    amendment = config.load_amendment()
    assert amendment["base_config_sha256"] == original["config_sha256"]
    assert amendment["base_protocol_sha256"] == original["protocol_sha256"]
    assert config.version_for(original) == 1
    versioned = config.identity(2)
    assert config.version_for(versioned) == 2
    assert versioned["mode"] == versioned["evidence_class"] == original["mode"]
    assert versioned["independence"] == original["independence"] == "NONE"
    modified = tmp_path / "config.json"
    modified.write_bytes(config.V2_CONFIG.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="pinned identity"):
        config.load_amendment(modified)
