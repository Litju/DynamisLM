"""Deterministic production transient-cache byte checkpoints."""

from __future__ import annotations

import os
import resource
import sys
from dataclasses import dataclass
from pathlib import Path

from dynamislm.serialization import register_serializable_type

DEFAULT_TRANSIENT_CACHE_ROOT = Path("/mnt/d/Dev/Caches/DynamisLM/PMC")
TRANSIENT_CACHE_MAX_BYTES = 2_000_000_000


def measure_transient_cache_bytes(
    root: str | Path = DEFAULT_TRANSIENT_CACHE_ROOT,
) -> int:
    """Sum regular-file logical bytes below the cache root; reject links/devices."""

    path = Path(root)
    if path.is_symlink():
        raise ValueError("transient cache root cannot be a symlink")
    if not path.exists():
        return 0
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("transient cache root must be a directory")
    total = 0
    pending = [resolved]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in sorted(entries, key=lambda item: item.name.encode("utf-8")):
                if entry.is_symlink():
                    raise ValueError("transient cache cannot contain symlinks")
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
                else:
                    raise ValueError("transient cache contains a non-regular filesystem entry")
    return total


def process_peak_rss_mb() -> float:
    """Measure process RSS independently; it is never used as cache storage."""

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / 1_048_576 if sys.platform == "darwin" else peak / 1024


def _enforce_transient_cache_limit(cache_bytes: int) -> None:
    if cache_bytes > TRANSIENT_CACHE_MAX_BYTES:
        raise ValueError("transient cache exceeds the 2 GB hard limit")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class TransientCacheCheckpointV1:
    checkpoint_name: str
    transient_cache_bytes: int
    process_peak_rss_mb: float

    def __post_init__(self) -> None:
        if not self.checkpoint_name:
            raise ValueError("transient cache checkpoint name must be non-empty")
        if self.transient_cache_bytes < 0 or self.process_peak_rss_mb < 0:
            raise ValueError("transient storage metrics cannot be negative")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class TransientCacheMeasurementV1:
    cache_root: str
    hard_limit_bytes: int
    checkpoints: tuple[TransientCacheCheckpointV1, ...]
    transient_cache_peak_bytes: int
    process_peak_rss_mb: float

    def __post_init__(self) -> None:
        if self.cache_root != DEFAULT_TRANSIENT_CACHE_ROOT.as_posix():
            raise ValueError("production transient metrics must bind the frozen PMC cache root")
        if self.hard_limit_bytes != TRANSIENT_CACHE_MAX_BYTES:
            raise ValueError("production transient metrics must bind the 2 GB hard limit")
        if not self.checkpoints:
            raise ValueError("transient measurement requires deterministic checkpoints")
        if self.transient_cache_peak_bytes != max(
            item.transient_cache_bytes for item in self.checkpoints
        ):
            raise ValueError("transient cache peak differs from its measured checkpoints")
        if self.process_peak_rss_mb != max(item.process_peak_rss_mb for item in self.checkpoints):
            raise ValueError("process RSS peak differs from its measured checkpoints")
        if self.transient_cache_peak_bytes > self.hard_limit_bytes:
            raise ValueError("transient cache exceeds the 2 GB hard limit")

    @property
    def transient_cache_peak_mb(self) -> float:
        return self.transient_cache_peak_bytes / 1_000_000

    def public_metrics(self) -> dict[str, float | int | str]:
        return {
            "TRANSIENT_CACHE_PEAK_MB": round(self.transient_cache_peak_mb, 6),
            "TRANSIENT_CACHE_PEAK_BYTES": self.transient_cache_peak_bytes,
            "TRANSIENT_CACHE_MAX_BYTES": self.hard_limit_bytes,
            "PROCESS_PEAK_RSS_MB": round(self.process_peak_rss_mb, 6),
            "PROCESS_RSS_REPORTED_SEPARATELY": "YES",
        }


class TransientCachePeakTracker:
    """Measure cache bytes at explicit generation checkpoints and enforce the cap."""

    def __init__(self, root: str | Path = DEFAULT_TRANSIENT_CACHE_ROOT) -> None:
        self.root = Path(root)
        self._checkpoints: list[TransientCacheCheckpointV1] = []

    def checkpoint(self, name: str) -> TransientCacheCheckpointV1:
        if not name or any(item.checkpoint_name == name for item in self._checkpoints):
            raise ValueError("transient cache checkpoint names must be unique non-empty strings")
        size = measure_transient_cache_bytes(self.root)
        _enforce_transient_cache_limit(size)
        checkpoint = TransientCacheCheckpointV1(
            checkpoint_name=name,
            transient_cache_bytes=size,
            process_peak_rss_mb=process_peak_rss_mb(),
        )
        self._checkpoints.append(checkpoint)
        return checkpoint

    def measurement(self) -> TransientCacheMeasurementV1:
        checkpoints = tuple(self._checkpoints)
        if not checkpoints:
            raise ValueError("transient cache requires at least one checkpoint")
        return TransientCacheMeasurementV1(
            cache_root=DEFAULT_TRANSIENT_CACHE_ROOT.as_posix(),
            hard_limit_bytes=TRANSIENT_CACHE_MAX_BYTES,
            checkpoints=checkpoints,
            transient_cache_peak_bytes=max(item.transient_cache_bytes for item in checkpoints),
            process_peak_rss_mb=max(item.process_peak_rss_mb for item in checkpoints),
        )


__all__ = [
    "DEFAULT_TRANSIENT_CACHE_ROOT",
    "TRANSIENT_CACHE_MAX_BYTES",
    "TransientCacheCheckpointV1",
    "TransientCacheMeasurementV1",
    "TransientCachePeakTracker",
    "measure_transient_cache_bytes",
    "process_peak_rss_mb",
]
