"""Task adapter registry and factory."""

from __future__ import annotations

import importlib
import inspect
from typing import Any

from faultevolve.config import EvolveConfig
from faultevolve.tasks.protocol import TaskAdapter

ADAPTER_ALIASES: dict[str, str] = {
    "hdd": "faultevolve.tasks.hdd_adapter:HDDAdapter",
    "famou": "faultevolve.tasks.famou_adapter:FamouAdapter",
    "backblaze": "faultevolve.tasks.backblaze_adapter:BackblazeAdapter",
    "alibaba_ssd": "faultevolve.tasks.ssd_alibaba_adapter:AlibabaSSDAdapter",
    "smartmem": "faultevolve.tasks.smartmem_adapter:SmartMemAdapter",
}

STUB_ADAPTER_DOCS: dict[str, str] = {
    "alibaba_ssd": "docs/datasets/alibaba_ssd.md",
}


def stub_doc_for(spec: str) -> str | None:
    """Return documentation path for stub adapters, if any."""
    return STUB_ADAPTER_DOCS.get(spec)


def resolve_adapter_class(spec: str) -> type:
    """Resolve adapter alias or 'module:Class' import path to a class."""
    target = ADAPTER_ALIASES.get(spec, spec)
    if ":" not in target:
        aliases = sorted(ADAPTER_ALIASES)
        raise ValueError(
            f"unknown task.adapter '{spec}'; aliases: {aliases} or 'module:Class'"
        )
    module_name, class_name = target.split(":", 1)
    try:
        module = importlib.import_module(module_name)
        cls = getattr(module, class_name)
    except (ImportError, AttributeError) as exc:
        aliases = sorted(ADAPTER_ALIASES)
        raise ValueError(
            f"unknown task.adapter '{spec}'; aliases: {aliases} or 'module:Class' ({exc})"
        ) from None
    return cls


def create_adapter(config: EvolveConfig) -> TaskAdapter:
    """Construct a task adapter from evolution config."""
    cls = resolve_adapter_class(config.task.adapter)
    kwargs: dict[str, Any] = {
        "min_noise_delta": 0.5,
        "kappa": config.selection.kappa_noise,
        "dev_late_fraction": config.analysis.dev_late_fraction,
        "analysis_min_group_count": config.analysis.min_group_count,
    }
    sig = inspect.signature(cls.__init__)
    filtered = {k: v for k, v in kwargs.items() if k in sig.parameters}
    return cls(**filtered)
