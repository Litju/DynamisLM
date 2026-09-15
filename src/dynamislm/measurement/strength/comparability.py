"""RES-66 fixed-load comparability entry points."""

from dynamislm.measurement.strength.vbt import (
    assess_vbt_fixed_load_comparability,
    compare_fixed_load_longitudinally,
    compare_vbt_fixed_load,
    compare_vbt_fixed_loads,
)

__all__ = [
    "assess_vbt_fixed_load_comparability",
    "compare_fixed_load_longitudinally",
    "compare_vbt_fixed_load",
    "compare_vbt_fixed_loads",
]
