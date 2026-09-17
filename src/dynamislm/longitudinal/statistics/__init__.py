"""RES-69 deterministic longitudinal statistics authority."""

from dynamislm.longitudinal.statistics import agreement as _agreement
from dynamislm.longitudinal.statistics import descriptive as _descriptive
from dynamislm.longitudinal.statistics import models as _models
from dynamislm.longitudinal.statistics import registry as _registry
from dynamislm.longitudinal.statistics import reliability as _reliability
from dynamislm.longitudinal.statistics import support as _support
from dynamislm.longitudinal.statistics import validation as _validation
from dynamislm.longitudinal.statistics.agreement import *  # noqa: F403
from dynamislm.longitudinal.statistics.descriptive import *  # noqa: F403
from dynamislm.longitudinal.statistics.models import *  # noqa: F403
from dynamislm.longitudinal.statistics.registry import *  # noqa: F403
from dynamislm.longitudinal.statistics.reliability import *  # noqa: F403
from dynamislm.longitudinal.statistics.support import *  # noqa: F403
from dynamislm.longitudinal.statistics.validation import *  # noqa: F403

__all__ = [
    *_models.__all__,
    *_registry.__all__,
    *_support.__all__,
    *_descriptive.__all__,
    *_reliability.__all__,
    *_agreement.__all__,
    *_validation.__all__,
]
for _module in (_models, _registry, _support, _descriptive, _reliability, _agreement, _validation):
    for _name in _module.__all__:
        if _name == "StatisticalConstraintError":
            continue
        globals()[_name] = getattr(_module, _name)
__all__ = [name for name in dict.fromkeys(__all__) if name != "StatisticalConstraintError"]
