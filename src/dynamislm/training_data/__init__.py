"""Fail-closed training-use authorization for existing DynamisLM sources."""

from dynamislm.training_data.source_authority import (
    LOCKED_EMPIRICAL_SOURCE_IDS,
    TrainingSourceDecision,
    assess_locked_empirical_sources,
    build_training_use_report,
    require_training_permission,
)

__all__ = [
    "LOCKED_EMPIRICAL_SOURCE_IDS",
    "TrainingSourceDecision",
    "assess_locked_empirical_sources",
    "build_training_use_report",
    "require_training_permission",
]
