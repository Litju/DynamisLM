"""Freeze the exact A1 model-call manifest before any inference (RES-832).

The manifest is the scientific contract for the campaign. It enumerates every condition once,
deduplicates identical conditions, records the exact prompt digest, and refuses to be altered
after the first observation. Nothing here is generated at inference time.

Workload accounting against the authorized envelope
---------------------------------------------------
The registered RES-832 diagnosis priced its ablations at "96 calls each", i.e. both models over
48 cases. A representation, system-instruction or label intervention only informs the research
question on the adapted model: the untouched model is expected to fail structurally, so its
replication adds no information about the intervention. Those replications are therefore not
purchased. The savings fund exactly the restricted-input probes that the methodological
correction now requires as positive shortcut evidence.

Registered ceiling: 1,336. Frozen here: 1,332.

======================  ==========  ==========
block                   registered  frozen
======================  ==========  ==========
principal factorial            384         384
D1-D5 ablations                480         336
D6 retrospective               192         192
D7 shortcut probes             280         420
total                        1,336       1,332
======================  ==========  ==========

No comparison is silently removed: D1-D5 each still appear, D6 is unchanged, and D7 grows from
the two registered projections to the three that the correction names (objective-only,
question-only, observations-only).

Priority order, as authorized
-----------------------------
1. Principal factorial (M0/M1 x R-hist/R-op x N/C1) over 48 cases.
2. Essential diagnostic interventions (D1-D5 adapted, D6 retrospective base, D7 shortcut).
3. CPU baselines (rule-based, conventional, restricted input).

Freezing
--------
``main`` writes the seal. ``load_manifest`` re-derives every condition from the frozen case
manifest and the renderers, so a changed renderer, prompt, case or arm set fails closed before
allocation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts import a02_v3_contract as v3
from scripts import a1_cases
from scripts import a1_representation as rep

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "DYNAMISLM_A1_CALL_MANIFEST_V1"
SEAL_SCHEMA = "DYNAMISLM_A1_CALL_SEAL_V1"
SEAL_PATH = ROOT / "experiments/a1/call-manifest-v1.json"

MODELS = {"M0": "untouched SmolLM3-3B", "M1": "historical step-510 LoRA"}
DECODERS = {"N": "native greedy", "C1": "token-level V3 grammar mask"}
REPRESENTATIONS = {"R-hist": "A0.2 training representation", "R-op": "operational request"}
SYSTEMS = {"S-hist": "A0.2 shared system prompt", "S-corrected": "corrected system prompt"}
FEWSHOT = {"0": "zero-shot", "3": "three exemplars"}


class ManifestError(ValueError):
    pass


def _key(condition: dict[str, Any]) -> str:
    return v3.sha256(v3.canonical(condition).encode())


def condition(
    *,
    arm: str,
    role: str,
    model: str,
    representation: str,
    decoder: str,
    system: str,
    cases: list[dict[str, Any]],
    fewshot: str = "0",
) -> dict[str, Any]:
    """One deduplicated inference condition with its exact prompt identities."""
    labels = {
        "model": MODELS[model],
        "representation": rep.prompt_label(representation),
        "decoder": DECODERS[decoder],
        "system": rep.SYSTEM_PROMPT_LABEL[system],
        "fewshot": FEWSHOT[fewshot],
    }
    items = []
    for case in cases:
        request = rep.request_for(representation, case)
        prompt = rep.prompt_sha256(request, system, fewshot)
        items.append(
            {
                "case_id": case["case_id"],
                "cluster": case["cluster"],
                "stratum": case["stratum"],
                "request_sha256": rep.request_sha256(request),
                "prompt_sha256": prompt,
            }
        )
    body = {
        "schema": SCHEMA,
        "arm": arm,
        "role": role,
        "model": model,
        "representation": representation,
        "decoder": decoder,
        "system": system,
        "fewshot": fewshot,
        "labels": labels,
        "items": items,
    }
    body["condition_sha256"] = _key(body)
    return body


def _by_stratum(cases: list[dict[str, Any]], stratum: str) -> list[dict[str, Any]]:
    return [case for case in cases if case["stratum"] == stratum]


def principal(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        condition(
            arm=f"P-{model}-{representation}-{decoder}",
            role="PRINCIPAL_FACTORIAL",
            model=model,
            representation=representation,
            decoder=decoder,
            system="S-hist",
            cases=cases,
        )
        for model in ("M0", "M1")
        for representation in ("R-hist", "R-op")
        for decoder in ("N", "C1")
    ]


def diagnostics(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """D1-D4 and D7: adapted-only single-variable interventions on the same 48 cases."""
    return [
        condition(
            arm="D1-corrected-system",
            role="DIAGNOSTIC",
            model="M1",
            representation="R-op",
            decoder="C1",
            system="S-corrected",
            cases=cases,
        ),
        condition(
            arm="D1-corrected-system-hist",
            role="DIAGNOSTIC",
            model="M1",
            representation="R-hist",
            decoder="C1",
            system="S-corrected",
            cases=cases,
        ),
        condition(
            arm="D2-enriched-objective",
            role="DIAGNOSTIC_ASSISTED",
            model="M1",
            representation="E-op",
            decoder="C1",
            system="S-hist",
            cases=cases,
        ),
        condition(
            arm="D3-constant-claims",
            role="DIAGNOSTIC",
            model="M1",
            representation="D3-constant-claims",
            decoder="C1",
            system="S-hist",
            cases=cases,
        ),
        condition(
            arm="D4-human-labels",
            role="DIAGNOSTIC",
            model="M1",
            representation="D4-human",
            decoder="C1",
            system="S-hist",
            cases=cases,
        ),
        condition(
            arm="D5-three-shot",
            role="DIAGNOSTIC_FEWSHOT",
            model="M1",
            representation="R-op",
            decoder="C1",
            system="S-hist",
            cases=cases,
            fewshot="3",
        ),
        condition(
            arm="D5-three-shot-m0",
            role="DIAGNOSTIC_FEWSHOT",
            model="M0",
            representation="R-op",
            decoder="C1",
            system="S-hist",
            cases=cases,
            fewshot="3",
        ),
    ]


def shortcut_probe() -> list[dict[str, Any]]:
    """D7 on A0.2 HELDOUT: structural shortcut probes rendered from the historical request."""
    from scripts import a02_v3_decision as decision
    from scripts import a1_shortcut

    examples = a1_shortcut.probe_examples(decision.load_protocol())
    return [
        condition(
            arm=f"D7-{variant}",
            role="SHORTCUT_PROBE",
            model="M1",
            representation="D7-probe",
            decoder="C1",
            system="S-hist",
            cases=a1_shortcut.probe_cases(examples, variant),
        )
        for variant in a1_shortcut.VARIANTS
    ]


def retrospective() -> list[dict[str, Any]]:
    """D6: untouched foundation model on the exposed 96-item A0.3 cohort, labelled retrospective."""
    from scripts import a1_retrospective

    cohort = a1_retrospective.cohort_cases()
    return [
        condition(
            arm=f"D6-M0-{decoder}",
            role="RETROSPECTIVE_NOT_FINAL_EVIDENCE",
            model="M0",
            representation="D6-retrospective",
            decoder=decoder,
            system="S-hist",
            cases=cohort,
        )
        for decoder in ("N", "C1")
    ]


def manifest() -> dict[str, Any]:
    cases = a1_cases.load_manifest()["cases"]
    conditions = [
        *principal(cases),
        *diagnostics(cases),
        *retrospective(),
        *shortcut_probe(),
    ]
    seen: set[str] = set()
    for entry in conditions:
        if entry["arm"] in seen:
            raise ManifestError(f"duplicate A1 arm: {entry['arm']}")
        seen.add(entry["arm"])
        if entry["role"] not in {"SHORTCUT_PROBE", "RETROSPECTIVE_NOT_FINAL_EVIDENCE"}:
            prompts = [item["prompt_sha256"] for item in entry["items"]]
            if len(set(prompts)) != len(prompts):
                raise ManifestError(f"{entry['arm']} renders duplicate prompts within the arm")
    generations = sum(len(entry["items"]) for entry in conditions)
    return {
        "schema": SEAL_SCHEMA,
        "case_manifest_sha256": a1_cases.load_manifest()["manifest_sha256"],
        "conditions": conditions,
        "planned_generations": generations,
        "planned_conditions": len(conditions),
        "priority": [
            "PRINCIPAL_FACTORIAL",
            "DIAGNOSTIC",
            "DIAGNOSTIC_ASSISTED",
            "DIAGNOSTIC_FEWSHOT",
            "RETROSPECTIVE_NOT_FINAL_EVIDENCE",
            "SHORTCUT_PROBE",
        ],
    }


def load_manifest() -> dict[str, Any]:
    """Re-derive the manifest and require byte-identity with the sealed file."""
    sealed = (SEAL_PATH).read_bytes()
    recorded = v3.json_object(sealed.decode("utf-8"))
    if sealed != (v3.canonical(recorded) + "\n").encode():
        raise ManifestError("A1 call manifest is not canonical JSON")
    derived = manifest()
    if recorded != derived:
        raise ManifestError("A1 call manifest differs from the current renderers")
    return recorded


def main() -> None:
    value = manifest()
    SEAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEAL_PATH.write_text(v3.canonical(value) + "\n", encoding="utf-8")
    digest = v3.sha256(SEAL_PATH.read_bytes())
    print(
        f"A1_CONDITIONS={value['planned_conditions']} "
        f"A1_GENERATIONS={value['planned_generations']} "
        f"manifest_sha256={digest}"
    )
    for entry in value["conditions"]:
        print(f"  {entry['arm']}: {len(entry['items'])} calls")


if __name__ == "__main__":
    main()
