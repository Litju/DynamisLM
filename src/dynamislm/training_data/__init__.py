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

from dynamislm.training_data.admission import (
    Code,
    Purpose,
    Request,
    Source,
    SourceClass,
    admit_sources,
    authorize_training_bytes,
    require_admitted,
)

__all__ += [
    "Code",
    "Purpose",
    "Request",
    "Source",
    "SourceClass",
    "admit_sources",
    "authorize_training_bytes",
    "require_admitted",
]
