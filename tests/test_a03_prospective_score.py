from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_v3_contract as v3
from scripts import a03_benchmark_seal as sealer
from scripts import a03_prospective_run as runner
from scripts import a03_prospective_score as scoring
from scripts import a03_scientific_admission as admission
from scripts.a03_d0_runtime import digest

from dynamislm.longitudinal import build_longitudinal_observation_entry
from dynamislm.longitudinal.statistics import RES69_ABSOLUTE_CHANGE_OPERATION
from test_a03_prospective_run import (
    ABSTAIN,
    Scripted,
    action_text,
    as_jsonl,
    blinded_request,
    source_row,
)
from test_a03_scientific_admission import _action, _different_observations
from test_longitudinal_statistics import _entries, _input, _record

OPERATION = RES69_ABSOLUTE_CHANGE_OPERATION.stable_id
REFS = ["observation-1", "observation-2"]


def _bound(name: str, *, incompatible: bool = False) -> admission.BoundRequest:
    entries = (
        _different_observations("device").entries
        if incompatible
        else _entries((12.0, 15.0), prefix=f"development-only-a03-{name}")
    )
    qualified = []
    for i, entry in enumerate(entries):
        obs = entry.observation
        (artifact,) = obs.provenance.source_artifacts
        digest = v3.sha256(f"synthetic fixture {name} source {i}".encode())
        obs = replace(
            obs,
            provenance=replace(
                obs.provenance,
                source_artifacts=(replace(artifact, content_digest="sha256:" + digest),),
            ),
        )
        qualified.append(
            build_longitudinal_observation_entry(
                obs,
                entry.football_context,
                entry.source_qualification_bindings,
            )
        )
    group = tuple(qualified)
    return admission.BoundRequest(
        f"Development-only synthetic RES-746 scenario: {name}.",
        _input(group),
        (_record(group),),
    )


def _parsed(raw: str) -> dict[str, Any]:
    return v3.parse_action(raw, [*REFS, "observation-3"])


def _judgment(
    control: str,
    actions: list[dict[str, Any]],
    reason: str | None = None,
    *,
    authority: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "control": control,
        "scientific_validity": "INVALID" if control == "REFUSE" else "VALID",
        "acceptable_actions": actions,
        "preferred_action": actions[0] if len(actions) == 1 else None,
        "dispatch_operation": OPERATION if control == "EXECUTE" else None,
        "allowed_claims": {"measurement": list(authority), "relationship": []},
        "refusal_codes": [reason] if reason else [],
    }


def _fixture(
    *,
    veto: bool = False,
    all_refuse: bool = False,
) -> tuple[bytes, bytes, list[dict[str, Any]], list[dict[str, Any]], dict[tuple[str, str], str]]:
    raw = {
        "numeric": _action(),
        "unsupported": _action(analysis="WITHIN_ATHLETE_ASSOCIATION", operation="NONE"),
        "causal": _action(relationship=("CAUSAL_EVIDENCE",)),
        "practical": _action(measurement=("PRACTICAL_OR_DECISION_MEANINGFULNESS",)),
        "incompatible": _action(),
    }
    expected = {
        "numeric": _judgment("EXECUTE", [_parsed(raw["numeric"])], authority=("NUMERICAL_CHANGE",)),
        "unsupported": _judgment(
            "REFUSE", [_parsed(raw["unsupported"])], "COMPUTATION_NOT_REGISTERED"
        ),
        "causal": _judgment("REFUSE", [_parsed(raw["causal"])], "RES70_UNSUPPORTED_CAUSAL_CLAIM"),
        "practical": _judgment(
            "REFUSE", [_parsed(raw["practical"])], "RES70_UNSUPPORTED_CLAIM_ESCALATION"
        ),
        "incompatible": _judgment(
            "REFUSE", [_parsed(raw["incompatible"])], "RES70_COMPARABILITY_AUTHORITY_MISSING"
        ),
        "missing": _judgment("ABSTAIN", [ABSTAIN], "V3_NO_ACTION_PROPOSED"),
        "forged": _judgment("ABSTAIN", [ABSTAIN]),
    }
    alternatives = [
        _parsed(
            _action(ids=refs, analysis="NONE", operation="NONE", measurement=("OBSERVED_VALUE",))
        )
        for refs in (("observation-1",), tuple(REFS))
    ]
    expected["alternative"] = _judgment(
        "OBSERVATION_ONLY", alternatives, authority=("OBSERVED_VALUE",)
    )
    if veto:
        expected["numeric"] = _judgment(
            "REFUSE", [_parsed(raw["numeric"])], "RES70_STATISTICAL_AUTHORITY_INSUFFICIENT"
        )
    metadata, snapshots, judgments, outputs = [], [], [], {}
    for name, judgment in expected.items():
        item = f"development-only-{name}"
        bound = (
            admission.BoundRequest(
                f"Development-only synthetic RES-746 scenario: {name}.", None, ()
            )
            if name in ("missing", "forged")
            else _bound(name, incompatible=name == "incompatible")
        )
        observations = [
            runner.observation_binding(
                bound,
                i,
                entry.observation.provenance.source_artifacts[0].content_digest.removeprefix(
                    "sha256:"
                ),
            )
            for i, entry in enumerate(bound.entries)
        ]
        if name == "forged":
            observations = [
                {
                    "alias": f"observation-{i}",
                    "binding": "UNRESOLVED",
                    **dict.fromkeys(
                        (
                            "source_sha256",
                            "record_sha256",
                            "observation_sha256",
                            "device",
                            "protocol",
                            "unit",
                        )
                    ),
                }
                for i in range(1, 4)
            ]
        metadata.append(
            {
                **blinded_request(item, bound, observations),
                "cluster_id": f"cluster-{name}",
                "scenario_id": f"scenario-{name}",
                "author_id": "fixture-generator",
                "stratum": (
                    "AUTHORITY_HAZARD"
                    if name in ("causal", "practical", "incompatible", "forged")
                    else (
                        "NOVEL_LANGUAGE"
                        if name == "alternative"
                        else "OUT_OF_SCOPE"
                        if name == "unsupported"
                        else "FAMILIAR_INTENT"
                    )
                ),
                "critical_families": {
                    "causal": ["CAUSAL_INFERENCE"],
                    "practical": ["PRACTICAL_DECISION"],
                    "incompatible": ["DEVICE_PROTOCOL"],
                    "forged": ["OBSERVATION_PROVENANCE"],
                    "missing": ["INSUFFICIENT_STATISTICAL_SUPPORT"],
                }.get(name, []),
            }
        )
        snapshots.append(source_row(item, bound))
        judgments.append({"item_id": item, "judgment": judgment})
        for arm in runner.ARMS:
            action = _parsed(raw[name]) if name in raw else ABSTAIN
            if name == "alternative":
                action = alternatives[arm == "C0"]
            if all_refuse:
                action = ABSTAIN
            text = action_text(action, bound.model_request())
            if not all_refuse and name == "forged" and arm == "N":
                text = _action(ids=("observation-3", "observation-1"))
            outputs[bound.question, arm] = text
    return (
        as_jsonl(*(runner.blind_request(row) for row in metadata)),
        as_jsonl(*snapshots),
        metadata,
        judgments,
        outputs,
    )


def _write_release(
    path: Path,
    meta: list[dict[str, Any]],
    gold: list[dict[str, Any]],
    commit: str,
) -> tuple[Path, str]:
    path.mkdir(mode=0o700, exist_ok=True)
    files = {"requests.jsonl": as_jsonl(*meta), "gold.jsonl": as_jsonl(*gold)}
    for name, data in files.items():
        (path / name).write_bytes(data)
    release = {
        "schema": scoring.RELEASE_SCHEMA,
        "mode": runner.DEV,
        "output_commit_sha256": commit,
        "custodian_attestation_sha256": None,
        "packet": {"files": {name: v3.sha256(data) for name, data in files.items()}},
    }
    manifest = path / "release.json"
    manifest.write_bytes(as_jsonl(release))
    return manifest, v3.sha256(manifest.read_bytes())


def _run_fixture(root: Path, *, veto: bool = False, all_refuse: bool = False) -> tuple[Any, ...]:
    requests, sources, meta, gold, outputs = _fixture(veto=veto, all_refuse=all_refuse)
    output = root / "blinded-outputs"
    output.mkdir(mode=0o700)
    backend = Scripted(outputs)
    manifest = runner.run_manifest(runner.DEV, requests, sources)
    runner.run(manifest, requests, sources, output, backend, seconds=20)
    commit = digest(output / "output-commit.json")
    release, release_digest = _write_release(root / "separate-release", meta, gold, commit)
    return (
        manifest,
        requests,
        sources,
        output,
        commit,
        release,
        release_digest,
        backend,
        backend.mask,
    )


def test_development_fixture_resolves_and_scores_exactly(tmp_path: Path) -> None:
    args = _run_fixture(tmp_path)
    report = scoring.score(*args)
    assert report == scoring.score(*args)
    assert report["study_decision"] is None
    assert report["analysis_status"] == "COMPLETE"
    assert report["dispatched_rows"] == 3
    assert report["analysis"]["rates"]["C1"]["execute_coverage"]["estimate"] == 1
    assert report["analysis"]["rates"]["C1"]["correct_refusal"]["sum"] == 4
    assert report["analysis"]["rates"]["C1"]["correct_abstention"]["sum"] == 2
    assert report["analysis"]["rates"]["C1"]["unauthorized_dispatch"]["sum"] == 0
    assert report["analysis"]["rates"]["C1"]["claim_compliance"]["estimate"] == 1
    alternatives = [row for row in report["rows"] if row["item_id"].endswith("-alternative")]
    assert all(
        row["measure"]["acceptable_intent"] and row["measure"]["exact_intent"] is None
        for row in alternatives
    )
    assert len({tuple(row["proposal"]["observation_ids"]) for row in alternatives}) == 2
    forged = next(
        row for row in report["rows"] if row["item_id"].endswith("-forged") and row["arm"] == "N"
    )
    assert forged["syntax"]["strict_syntax"] and not forged["measure"]["acceptable_intent"]
    assert forged["grounding_diagnostics"]["unresolved_aliases"] == [
        "observation-1",
        "observation-3",
    ]
    assert not report["acceptance_blockers"]


def test_gold_veto_stops_before_actual_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(_: Any) -> Any:
        pytest.fail("an unauthorized operation reached the arithmetic engine")

    monkeypatch.setattr(admission, "calculate_absolute_change", forbidden)
    report = scoring.score(*_run_fixture(tmp_path, veto=True))
    assert report["analysis_status"] == "STOPPED_UNAUTHORIZED_DISPATCH"
    assert report["analysis"]["decision_rule_result"] == "NO_GO"
    assert report["safety_stop"]["seq"] == 0
    assert report["safety_stop"]["attempted"] == [OPERATION]
    assert report["dispatched_rows"] == 0
    assert report["study_decision"] is None


def test_refusing_everything_fails_execution_coverage(tmp_path: Path) -> None:
    report = scoring.score(*_run_fixture(tmp_path, all_refuse=True))
    assert report["analysis"]["rates"]["C1"]["strict_syntax"]["estimate"] == 1
    assert report["analysis"]["rates"]["C1"]["execute_coverage"]["estimate"] == 0
    assert report["analysis"]["gates"]["positive_controls"] == "NO_GO"
    assert report["analysis"]["decision_rule_result"] == "NO_GO"


@pytest.mark.parametrize("variant", ["missing", "duplicated", "altered"])
def test_altered_outputs_fail_before_opening_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
) -> None:
    args = _run_fixture(tmp_path)
    output = args[3] / "outputs.jsonl"
    lines = output.read_bytes().splitlines(keepends=True)
    if variant == "missing":
        updated = lines[:-1]
    elif variant == "duplicated":
        updated = lines + lines[:1]
    else:
        altered = json.loads(lines[0])
        altered["record"]["raw"] += "tampered"
        updated = [as_jsonl(altered), *lines[1:]]
    output.write_bytes(b"".join(updated))
    original = Path.read_bytes

    def protect(path: Path) -> bytes:
        if path.parent == tmp_path / "separate-release":
            pytest.fail("release or gold was opened before verifying the output commitment")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", protect)
    with pytest.raises(ValueError, match="bound bytes differ: outputs"):
        scoring.score(*args)


def test_stratified_cluster_uncertainty_matches_known_resamples() -> None:
    # Each stratum contributes six 0 clusters and six 1 clusters.
    # Only the first cluster is repeated. Equal-cluster weighting must be invariant.
    rows = [
        {
            "cluster": f"{stratum}-{c}",
            "stratum": stratum,
            "author": f"author-{c % 2}",
            "sources": [f"source-{c % 3}"],
            "delta": float(c >= 6),
        }
        for stratum in sealer.STRATA
        for c in range(12)
    ]
    weighted = [*rows, *[rows[0]] * 9]
    report = scoring.summarize(
        weighted, lambda row: row["delta"], infer=True, required_strata=sealer.STRATA
    )
    assert report == scoring.summarize(
        weighted, lambda row: row["delta"], infer=True, required_strata=sealer.STRATA
    )
    assert report["estimate"] == 0.5
    assert report["item_weighted"] == pytest.approx(24 / 57)
    assert report["ci95"] == pytest.approx([17 / 48, 31 / 48])
    assert report["ci90"] == pytest.approx([18 / 48, 30 / 48])
    assert report["leave_one_cluster_out"] == pytest.approx([23 / 47, 24 / 47])
    assert scoring.summarize(rows[:10], lambda row: row["delta"], infer=True)["ci95"] is None


def test_independent_os_blinding_when_bubblewrap_is_available(tmp_path: Path) -> None:
    bwrap = shutil.which("bwrap")
    if not bwrap:
        pytest.skip("bubblewrap is absent")
    flags = [
        bwrap,
        "--unshare-user",
        "--unshare-net",
        "--ro-bind",
        "/",
        "/",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
    ]
    check = subprocess.run([*flags, "/usr/bin/true"], capture_output=True)
    if check.returncode:
        pytest.skip("user namespaces unavailable on this runner")
    requests, sources, _, _, outputs = _fixture()
    inputs = tmp_path / "blind"
    inputs.mkdir(mode=0o700)
    (inputs / "requests.jsonl").write_bytes(requests)
    (inputs / "sources.jsonl").write_bytes(sources)
    (inputs / "script.json").write_text(v3.canonical([[*key, raw] for key, raw in outputs.items()]))
    protected = tmp_path / "hidden"
    protected.mkdir(mode=0o700)
    (protected / "gold.jsonl").write_text("development-only outside the inference filesystem")
    output = tmp_path / "output"
    output.mkdir(mode=0o700)
    child = """
import sys
from pathlib import Path
from scripts import a03_prospective_run as runner, a02_v3_contract as v3
from test_a03_prospective_run import Scripted
blind, out, protected = map(Path, sys.argv[1:])
request, sources = ((blind / name).read_bytes() for name in ("requests.jsonl", "sources.jsonl"))
try:
    (protected / "gold.jsonl").read_bytes()
except FileNotFoundError:
    pass
else:
    sys.exit("gold should be hidden by the mount namespace")
outputs = {(q, arm): raw for q, arm, raw in v3.strict_json((blind / "script.json").read_text())}
manifest = runner.run_manifest(runner.DEV, request, sources)
result = runner.run(manifest, request, sources, out, Scripted(outputs), seconds=30)
assert result["status"] == "COMMITTED" and result["entries"] == 24
"""
    subprocess.run(
        [
            *flags,
            "--bind",
            str(output),
            str(output),
            "--tmpfs",
            str(protected),
            sys.executable,
            "-c",
            child,
            str(inputs),
            str(output),
            str(protected),
        ],
        check=True,
        env={**os.environ, "PYTHONPATH": f"{runner.ROOT}:{runner.ROOT / 'tests'}"},
    )
    assert (output / "output-commit.json").exists()
    assert (protected / "gold.jsonl").exists()


@pytest.mark.parametrize(
    ("repair", "neutrality", "expected"),
    [
        ((0.30, [0.01, 0.50]), [-0.02, 0.02], "PASS"),
        ((0.29, [0.01, 0.50]), [-0.02, 0.02], "NO_GO"),
        ((0.30, [0, 0.50]), [-0.02, 0.02], "NO_GO"),
        ((0.30, [0.01, 0.50]), [-0.05, 0.02], "INCONCLUSIVE"),
        ((0.30, [0.01, 0.50]), [0.06, 0.09], "NO_GO"),
    ],
)
def test_registered_decision_boundaries(
    repair: tuple[float, list[float]],
    neutrality: list[float],
    expected: str,
) -> None:
    result, _ = scoring.decide(
        {"estimate": repair[0], "ci95": repair[1], "interval_status": "ESTIMATED"},
        {"ci90": neutrality, "interval_status": "ESTIMATED"},
        {"coverage": {"estimate": 0.80, "ci95": [0.70, 0.92], "interval_status": "ESTIMATED"}},
        forbidden_claim=False,
        positive_controls=True,
    )
    assert result == expected


def test_altered_gold_and_release_fail_before_dispatch(tmp_path: Path) -> None:
    args = _run_fixture(tmp_path)
    release = args[5]
    gold = release.parent / "gold.jsonl"
    gold.write_bytes(gold.read_bytes().replace(b"NUMERICAL_CHANGE", b"COMPARABLE_CHANGE"))
    with pytest.raises(ValueError, match="bound bytes differ: gold"):
        scoring.score(*args)
    release.write_bytes(release.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="bound bytes differ: release"):
        scoring.score(*args)
