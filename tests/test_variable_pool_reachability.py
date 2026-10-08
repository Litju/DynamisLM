"""Static proof that modern pool-first entrypoints cannot reach superseded authority.

The graph is a conservative over-approximation: every name referenced anywhere in a
reachable top-level definition is followed across ``dynamislm`` modules, regardless of
branch conditions. Historical code may exist; it must not be reachable from these paths.
"""

from __future__ import annotations

import ast
import importlib.util
from functools import cache

import pytest

Node = tuple[str, str]

MODERN_ENTRYPOINTS: tuple[Node, ...] = (
    ("dynamislm.benchmark.variable_pool", "build_initial_variable_pool_authoring_plan"),
    ("dynamislm.benchmark.variable_pool", "historical_recipes_from_authoring_inputs"),
    ("dynamislm.benchmark.variable_pool", "materialize_variable_pool"),
    ("dynamislm.benchmark.variable_pool", "production_source_selection_universe"),
    ("dynamislm.benchmark.variable_pool", "project_variable_pool_selection_candidates"),
    ("dynamislm.benchmark.variable_pool", "validate_variable_pre_review_pool"),
    ("dynamislm.benchmark.variable_pool", "VariablePoolAuthoringPlanV1"),
    ("dynamislm.benchmark.authority_supply", "build_live_authority_supply_inventory"),
    ("dynamislm.benchmark.selection_pool", "assess_authority_supply_inventory"),
    ("dynamislm.benchmark.selection_pool", "plan_variable_pool"),
    ("dynamislm.benchmark.variable_pool_store", "write_variable_pool_store"),
    ("dynamislm.benchmark.variable_pool_store", "read_variable_pool_store"),
)
_AUTHORING = "dynamislm.benchmark.production_authoring"
_PRODUCTION = "dynamislm.benchmark.production"
FORBIDDEN_SYMBOLS: dict[Node, str] = {
    (_AUTHORING, "build_production_authoring_draft"): "historical fixed-434 draft builder",
    (_AUTHORING, "_authoring_input_skeleton"): "fixed 434 authoring skeleton",
    (_AUTHORING, "_new_or_resume_private_inputs"): "RES-223 plan application to inputs",
    (_AUTHORING, "_validate_res128_feasibility_baseline"): "RES-128 fixed digest gate",
    (_AUTHORING, "_RES128_FINAL_AUDIT_SHA256"): "RES-128 fixed digest",
    (_AUTHORING, "_RES128_CANDIDATE_SET_DIGEST"): "RES-128 fixed digest",
    (_AUTHORING, "_RES128_COLOCATION_EDGE_DIGEST"): "RES-128 fixed digest",
    (_AUTHORING, "_RES225_MATERIALIZATION_PATH"): "RES-225 fixed-topology repair",
    (_AUTHORING, "_read_res225_materialization_plan"): "RES-225 fixed-topology repair",
    (_AUTHORING, "_apply_res225_materialization"): "RES-225 fixed-topology repair",
    (_AUTHORING, "_mutation_lineage_specs"): "37x3 mutation topology",
    (_AUTHORING, "_author_mutation_packets"): "111-child mutation equality",
    (_AUTHORING, "_semantic_slot_specs"): "fixed 240 semantic slots",
    (_AUTHORING, "_engine_slot_specs"): "fixed 31 engine slots",
    (_AUTHORING, "_synthetic_slot_specs"): "fixed 12 synthetic slots",
    (_AUTHORING, "_expert_batch_records"): "historical expert batch membership geometry",
    (_AUTHORING, "_choose_supported_sources"): "fixed 40 source selection",
    (_PRODUCTION, "validate_production_exact_feasibility"): "legacy RES-222/224 exact gate",
    (_PRODUCTION, "validate_production_exact_feasibility_receipt"): "legacy exact receipt gate",
    (_PRODUCTION, "validate_production_hard_feasibility"): "legacy fixed-434 feasibility gate",
    (_PRODUCTION, "validate_production_candidate_set"): "exact 434 production set",
    (_PRODUCTION, "bind_production_authoring_plan"): "fixed 434 production authoring plan",
}
FORBIDDEN_MODULES = {
    "dynamislm.benchmark.res223_topology": "RES-223 repaired topology",
    "dynamislm.benchmark.res225_repair": "RES-225 fixed-topology repair",
    "dynamislm.benchmark.res249_redesign": "RES-249 historical design",
}


@cache
def _module_tree(module: str) -> ast.Module | None:
    try:
        spec = importlib.util.find_spec(module)
    except (ImportError, ValueError):
        return None
    if spec is None or spec.origin is None or not spec.origin.endswith(".py"):
        return None
    with open(spec.origin, encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=spec.origin)


def _absolute(module: str, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    package = module.rsplit(".", node.level)[0]
    return f"{package}.{node.module}" if node.module else package


def _imports(module: str, statements: list[ast.stmt]) -> dict[str, Node | str]:
    aliases: dict[str, Node | str] = {}
    for statement in statements:
        for node in ast.walk(statement):
            if isinstance(node, ast.ImportFrom):
                source = _absolute(module, node)
                for alias in node.names:
                    aliases[alias.asname or alias.name] = (source, alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    aliases[alias.asname or alias.name.split(".")[0]] = (
                        alias.name if alias.asname else alias.name.split(".")[0]
                    )
    return aliases


@cache
def _definitions(module: str) -> dict[str, ast.stmt]:
    tree = _module_tree(module)
    definitions: dict[str, ast.stmt] = {}
    if tree is None:
        return definitions
    for statement in tree.body:
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            definitions[statement.name] = statement
        elif isinstance(statement, ast.Assign | ast.AnnAssign):
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    definitions[target.id] = statement
    return definitions


@cache
def _module_imports(module: str) -> dict[str, Node | str]:
    tree = _module_tree(module)
    return {} if tree is None else _imports(module, tree.body)


def _resolve(module: str, name: str, seen: frozenset[Node] = frozenset()) -> Node | None:
    if not module.startswith("dynamislm") or (module, name) in seen:
        return None
    if name in _definitions(module):
        return (module, name)
    imported = _module_imports(module).get(name)
    if isinstance(imported, tuple):
        source, original = imported
        if _module_tree(f"{source}.{original}") is not None:
            return (f"{source}.{original}", "*")
        return _resolve(source, original, seen | {(module, name)})
    return None


def _edges(node: Node) -> set[Node]:
    module, name = node
    if name == "*":
        return set()
    statement = _definitions(module).get(name)
    if statement is None:
        return set()
    local = {**_module_imports(module), **_imports(module, [statement])}
    targets: set[Node] = set()
    for item in ast.walk(statement):
        if isinstance(item, ast.ImportFrom):
            source = _absolute(module, item)
            for alias in item.names:
                resolved = _resolve(source, alias.name)
                if resolved is not None:
                    targets.add(resolved)
        if isinstance(item, ast.Attribute) and isinstance(item.value, ast.Name):
            imported = local.get(item.value.id)
            if isinstance(imported, tuple) and _module_tree(".".join(imported)) is not None:
                resolved = _resolve(".".join(imported), item.attr)
            elif isinstance(imported, str):
                resolved = _resolve(imported, item.attr)
            else:
                resolved = None
            if resolved is not None:
                targets.add(resolved)
        if isinstance(item, ast.Name):
            if item.id in _definitions(module):
                targets.add((module, item.id))
                continue
            imported = local.get(item.id)
            if isinstance(imported, tuple):
                resolved = _resolve(*imported)
                if resolved is not None:
                    targets.add(resolved)
    targets.discard(node)
    return targets


def _reachable(entrypoints: tuple[Node, ...]) -> set[Node]:
    seen: set[Node] = set()
    stack = list(entrypoints)
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        stack.extend(_edges(node) - seen)
    return seen


def _violations(reachable: set[Node]) -> list[str]:
    return sorted(
        [
            f"{module}.{name}: {why}"
            for (module, name), why in FORBIDDEN_SYMBOLS.items()
            if (module, name) in reachable
        ]
        + [
            f"{module}.{name}: {FORBIDDEN_MODULES[module]}"
            for module, name in reachable
            if module in FORBIDDEN_MODULES
        ]
    )


def test_analyzer_detects_superseded_authority_on_the_historical_draft_path() -> None:
    reachable = _reachable(((_AUTHORING, "build_production_authoring_draft"),))
    violations = _violations(reachable)
    for expected in (
        "_authoring_input_skeleton",
        "_validate_res128_feasibility_baseline",
        "_mutation_lineage_specs",
        "validate_production_exact_feasibility",
        "res223_topology.read_repair_plan",
        "res223_topology.apply_repair_actions",
    ):
        assert any(expected in item for item in violations), expected


def test_initial_plan_builder_and_store_are_public_benchmark_exports() -> None:
    from dynamislm import benchmark
    from dynamislm.benchmark import variable_pool, variable_pool_store

    assert benchmark.build_initial_variable_pool_authoring_plan is (
        variable_pool.build_initial_variable_pool_authoring_plan
    )
    assert benchmark.write_variable_pool_store is variable_pool_store.write_variable_pool_store
    assert benchmark.read_variable_pool_store is variable_pool_store.read_variable_pool_store


@pytest.mark.parametrize("entrypoint", MODERN_ENTRYPOINTS, ids=lambda item: item[1])
def test_modern_entrypoint_cannot_reach_superseded_authority(entrypoint: Node) -> None:
    reachable = _reachable((entrypoint,))
    assert entrypoint in reachable
    assert len(reachable) > 1
    assert _violations(reachable) == []
