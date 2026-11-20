#!/usr/bin/env python3
"""Exhaustive partition of the pytest modules into the independent required CI jobs.

Every ``tests/test_*.py`` module belongs to exactly one shard. ``--check`` fails when a module
is unassigned, assigned twice or no longer exists, so a new test cannot silently fall outside
every required job. Shards run in separate hosted runners and share no filesystem state.
Durations were balanced from ``pytest --durations`` profiling (RES-541).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Expensive integration and full-workload integrity qualification: the complete 581-item
# campaign, real bounded subprocess children and complete CPU pipelines.
INTEGRATION = (
    "test_res402_sft.py",
    "test_res541_a02_pipeline_rehearsal.py",
    "test_res541_a02_v3_bootstrap_integration.py",
    "test_res541_a02_v3_execution.py",
    "test_res541_a02_v3_worker.py",
)

# Controller, safety and fault-injection regression: admission, cost, supervision, watchdogs,
# teardown and session lifecycle.
CONTROLLER = (
    "test_res541_a02_dev_diagnostics.py",
    "test_res541_a02_dev_execution.py",
    "test_res541_a02_dev_forensics.py",
    "test_res541_a02_dev_remote.py",
    "test_res541_a02_dev_runtime.py",
    "test_res541_a02_recovery.py",
    "test_res541_a02_v3_automatic.py",
    "test_res541_a02_v3_baseline_successor.py",
    "test_res541_a02_v3_controller_qualification.py",
    "test_res541_a02_v3_cost.py",
    "test_res541_a02_v3_cost_ledger.py",
    "test_res541_a02_v3_gpu_diagnostic.py",
    "test_res541_a02_v3_lifecycle_monitoring.py",
    "test_res541_a02_v3_live_safety.py",
    "test_res541_a02_v3_preflight.py",
    "test_res541_a02_v3_preparation.py",
    "test_res541_a02_v3_remote.py",
    "test_res541_a02_v3_successor.py",
    "test_res541_a02_v3_supervision.py",
    "test_res541_a1_campaign_binding.py",
)

SHARDS = {"integration": INTEGRATION, "controller": CONTROLLER}


def modules(root: Path = ROOT) -> list[str]:
    return sorted(path.name for path in (root / "tests").glob("test_*.py"))


def partition(root: Path = ROOT) -> dict[str, list[str]]:
    """Fast scientific, contract and unit regression owns every module not assigned above."""
    present = modules(root)
    assigned = [name for shard in SHARDS.values() for name in shard]
    duplicates = sorted({name for name in assigned if assigned.count(name) > 1})
    missing = sorted(set(assigned) - set(present))
    if duplicates or missing:
        raise ValueError(f"TEST_SHARDS: duplicated={duplicates} missing={missing}")
    result = {name: sorted(shard) for name, shard in SHARDS.items()}
    result["fast"] = sorted(set(present) - set(assigned))
    covered = sorted(name for shard in result.values() for name in shard)
    if covered != present or not all(result.values()):
        raise ValueError("TEST_SHARDS: partition is not exhaustive and disjoint")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shard", nargs="?", choices=["fast", "controller", "integration"])
    parser.add_argument("--check", action="store_true", help="validate the partition only")
    args = parser.parse_args(argv)
    shards = partition()
    if args.check or args.shard is None:
        sizes = " ".join(f"{name}={len(files)}" for name, files in sorted(shards.items()))
        print(f"TEST_SHARDS=PASS {sizes} modules={len(modules())}")
        return 0
    print("\n".join(f"tests/{name}" for name in shards[args.shard]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
