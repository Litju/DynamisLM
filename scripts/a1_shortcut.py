"""D7 shortcut probes on the frozen A0.2 HELDOUT split (RES-832).

Hypothesis H2 needs evidence that predictions depend on *unintended predictive features*, not
just that they generalise poorly. These probes restrict the adapter's input to one structural
component at a time while leaving the gold action unchanged:

``objective-only``
    only the A0.2 ``objective`` template text survives; the question, measurement and every
    observation are removed.
``question-only``
    only the ``question`` template text survives.
``observations-only``
    only the observation rows survive; both ``objective`` and ``question`` are removed.

A model that reaches materially non-chance exact action agreement from ``objective-only`` or
``observations-only`` is using a feature that carries no answer-bearing information beyond
intent-template and cardinality regularities. This is the shortcut signal the A0.2 generator
was suspected of creating. It is **not** evidence of memorisation: a low training loss alone is
never reported as memorisation. ``question-only`` is the information ceiling the other two are
compared against, because the question does legitimately carry intent.

The probes reuse the frozen A0.2 generator, seeds and manifest hashes; no held-out example is
regenerated, relabelled or removed, and nothing here changes a historical result.
"""

from __future__ import annotations

from typing import Any

from scripts import a02_v3_contract as v3

PROBE_COUNT = 10  # per historical family, ten of the twenty held-out rows
SCHEMA = "DYNAMISLM_A1_SHORTCUT_CASE_V1"
VARIANTS = (
    "objective-only",
    "question-only",
    "observations-only",
)


def rank(example: dict[str, Any]) -> str:
    """Deterministic, family-blind selection: the lowest ten ranks in each family."""
    return v3.sha256(f"A1-SHORTCUT/{example['family']}/{example['index']}".encode())


def probe_examples(protocol: dict[str, Any]) -> list[dict[str, Any]]:
    from collections import defaultdict

    from scripts import a02_v3_synthetic as synthetic

    spec = protocol["data"]["heldout_evaluation"]
    examples = synthetic.generate(spec["split"], spec["seed"], spec["count"])
    families: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for example in examples:
        families[example["family"]].append(example)
    if len(families) != 14 or any(len(group) != 20 for group in families.values()):
        raise ValueError("A0.2 HELDOUT family structure differs from its frozen protocol")
    chosen = [
        example
        for family in sorted(families)
        for example in sorted(families[family], key=rank)[:PROBE_COUNT]
    ]
    if len(chosen) != 140 or len({example["index"] for example in chosen}) != 140:
        raise ValueError("shortcut probe selection is not 140 distinct held-out rows")
    return chosen


def _restricted(request: dict[str, Any], variant: str) -> dict[str, Any]:
    observations = request.get("observations", [])
    if variant == "objective-only":
        return {"objective": request["objective"], "observations": []}
    if variant == "question-only":
        return {"question": request["question"], "observations": []}
    if variant == "observations-only":
        return {"observations": observations}
    raise ValueError(f"unknown shortcut probe variant: {variant}")


def probe_cases(examples: list[dict[str, Any]], variant: str) -> list[dict[str, Any]]:
    """Cases shaped like A1 cases so one manifest and one runner serve both."""
    cases = []
    for example in examples:
        request = example["request"]
        restricted = _restricted(request, variant)
        cases.append(
            {
                "case_id": f"d7-{variant}-{example['family'].lower()}-{example['index']}",
                "cluster": f"d7-{example['family']}",
                "stratum": example["family"],
                "family": example["family"],
                "request": restricted,
                "gold": v3.normalize_action(example["gold_action"]),
                "source_example": f"{example['split']}:{example['seed']}:{example['index']}",
                "schema": SCHEMA,
            }
        )
    return cases
