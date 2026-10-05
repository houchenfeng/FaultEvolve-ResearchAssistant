"""Evolution-strength presets, built and validated server-side (TODO 4.6).

The front-end never assembles an ``EvolveConfig``. It picks a preset name and
sends back only a *patch*; this module merges the patch onto the preset and
re-validates the result against the engine's own model, so an invalid
combination is rejected here rather than mid-run.

``sources`` on the response states, per touched field, whether the value came
from the preset default or from the user patch -- the UI's "已自定义" badge is
derived from the patch being non-empty, and this list explains *what* changed.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from faultevolve.config import EvolveConfig
from faultevolve.webapi.contracts import (
    PresetFieldSource,
    PresetListResponse,
    PresetResponse,
)
from faultevolve.webapi.errors import PresetInvalidError, PresetUnknownError

#: Preset names in UI order. ``/api/meta`` exposes this tuple verbatim so the
#: front-end never hard-codes the list.
PRESET_NAMES: tuple[str, ...] = ("quick", "standard", "deep")

#: Per-preset overrides. Everything not listed here stays at the engine's own
#: defaults, which is what makes a preset auditable: the diff against
#: ``EvolveConfig()`` is exactly this table.
_PRESET_OVERRIDES: dict[str, dict[str, Any]] = {
    "quick": {
        "budget": {"max_iterations": 5, "max_wall_hours": 0.25},
        "analysis": {"enabled": False},
        "discovery": {"enabled": False, "tournament": {"enabled": False}},
        "smoke_test": {"enabled": True},
    },
    "standard": {
        "budget": {"max_iterations": 20, "max_wall_hours": 2.0},
        "analysis": {"enabled": True},
        "discovery": {"enabled": False, "tournament": {"enabled": False}},
        "smoke_test": {"enabled": True},
    },
    "deep": {
        "budget": {"max_iterations": 50, "max_wall_hours": 6.0},
        "analysis": {"enabled": True},
        "discovery": {"enabled": True, "tournament": {"enabled": True}},
        "smoke_test": {"enabled": True},
    },
}

_DISPLAY_NAMES_ZH = {
    "quick": "快速演示",
    "standard": "标准进化",
    "deep": "深度进化",
}

_SUMMARIES_ZH = {
    "quick": "证明系统能真实跑起来：少量轮次，关闭分析与知识发现。",
    "standard": "默认强度：开启错误分析，关闭知识发现与机制辩论赛。",
    "deep": "完整强度：开启知识发现与机制辩论赛（tournament）。",
}


def _validate_preset_name(preset: str) -> str:
    if preset not in _PRESET_OVERRIDES:
        raise PresetUnknownError(preset)
    return preset


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursive dict merge. Lists and scalars in the patch replace the base."""
    merged = dict(base)
    for key, value in patch.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _flatten_overrides(overrides: dict[str, Any]) -> dict[str, Any]:
    """``{"budget": {"max_iterations": 5}}`` -> ``{"budget.max_iterations": 5}``."""
    flat: dict[str, Any] = {}
    for key, value in overrides.items():
        if isinstance(value, dict):
            for inner_key, inner_value in value.items():
                if isinstance(inner_value, dict):
                    for leaf, leaf_value in inner_value.items():
                        flat[f"{key}.{inner_key}.{leaf}"] = leaf_value
                else:
                    flat[f"{key}.{inner_key}"] = inner_value
        else:
            flat[key] = value
    return flat


def build_preset(preset: str) -> PresetResponse:
    """One preset as a complete, already-validated ``EvolveConfig`` dump."""
    name = _validate_preset_name(preset)
    overrides = _PRESET_OVERRIDES[name]
    config = _merged_config(name, {})
    sources = [
        PresetFieldSource(field=field, value=value, source="preset_default")
        for field, value in sorted(_flatten_overrides(overrides).items())
    ]
    return PresetResponse(
        name=name,
        display_name_zh=_DISPLAY_NAMES_ZH[name],
        summary_zh=_SUMMARIES_ZH[name],
        config=config,
        sources=sources,
    )


def list_presets() -> PresetListResponse:
    """All presets, in UI order, each individually validated."""
    return PresetListResponse(
        presets=[build_preset(name) for name in PRESET_NAMES]
    )


def _merged_config(preset: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Preset config with ``patch`` merged, validated through the engine.

    Raises ``PresetInvalidError`` carrying the offending *field names* only:
    values could quote a path or a key fragment.
    """
    name = _validate_preset_name(preset)
    base = EvolveConfig().model_dump(mode="json")
    merged = _deep_merge(_deep_merge(base, _PRESET_OVERRIDES[name]), patch)
    try:
        EvolveConfig.model_validate(merged)
    except ValidationError as exc:
        fields = sorted(
            {
                ".".join(str(part) for part in error.get("loc", ()))
                for error in exc.errors()
            }
        )
        raise PresetInvalidError(fields) from exc
    return merged


def merge_patch(preset: str, patch: dict[str, Any]) -> PresetResponse:
    """The merged result plus per-field provenance (TODO 4.6).

    Every field the patch touched is reported with ``source="user_patch"``;
    preset-touched fields keep ``preset_default``. Fields at engine defaults
    are not listed at all -- "unchanged" needs no explanation.
    """
    name = _validate_preset_name(preset)
    merged = _merged_config(name, patch)
    sources = [
        PresetFieldSource(field=field, value=value, source="user_patch")
        for field, value in sorted(_flatten_overrides(patch).items())
    ]
    preset_sources = [
        PresetFieldSource(field=field, value=value, source="preset_default")
        for field, value in sorted(
            _flatten_overrides(_PRESET_OVERRIDES[name]).items()
        )
        if field not in _flatten_overrides(patch)
    ]
    return PresetResponse(
        name=name,
        display_name_zh=_DISPLAY_NAMES_ZH[name],
        summary_zh=_SUMMARIES_ZH[name],
        config=merged,
        sources=sources + preset_sources,
    )


__all__ = [
    "PRESET_NAMES",
    "build_preset",
    "list_presets",
    "merge_patch",
]
