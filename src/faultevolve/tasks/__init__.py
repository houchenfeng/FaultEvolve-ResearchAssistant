"""Task adapters for FaultEvolve."""

from __future__ import annotations

from faultevolve.tasks.protocol import (
    DataStatus,
    DataStatusProvider,
    DiscoveryDataProvider,
    DiscoveryFrames,
    ErrorProfiler,
    ObjectiveBriefProvider,
    ObjectiveSpec,
    TaskAdapter,
    TaskSpec,
)
from faultevolve.tasks.famou_adapter import FamouAdapter
from faultevolve.tasks.hdd_adapter import HDDAdapter
from faultevolve.tasks.registry import (
    ADAPTER_ALIASES,
    STUB_ADAPTER_DOCS,
    create_adapter,
    resolve_adapter_class,
    stub_doc_for,
)


def create_benchmark_adapter(config):  # noqa: ANN001 — EvolveConfig
    """Construct the task adapter from evolution config (default: HDD MVP)."""
    return create_adapter(config)


__all__ = [
    "ADAPTER_ALIASES",
    "STUB_ADAPTER_DOCS",
    "TaskAdapter",
    "TaskSpec",
    "DataStatus",
    "DataStatusProvider",
    "DiscoveryDataProvider",
    "DiscoveryFrames",
    "FamouAdapter",
    "HDDAdapter",
    "ErrorProfiler",
    "ObjectiveBriefProvider",
    "ObjectiveSpec",
    "create_adapter",
    "create_benchmark_adapter",
    "resolve_adapter_class",
    "stub_doc_for",
]
