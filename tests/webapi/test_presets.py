"""Preset generation and patch merging (TODO 4.6)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from faultevolve.config import EvolveConfig  # noqa: E402
from faultevolve.webapi import presets as presets_module  # noqa: E402
from faultevolve.webapi.errors import PresetInvalidError, PresetUnknownError  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    from faultevolve.webapi.app import create_app

    return TestClient(create_app(), raise_server_exceptions=False)


# --------------------------------------------------------------------------
# the three presets are legal, complete configs
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["quick", "standard", "deep"])
def test_every_preset_is_a_valid_evolve_config(name: str) -> None:
    preset = presets_module.build_preset(name)
    # The dump is validated through the engine's own model, not our own
    # re-implementation of the rules.
    config = EvolveConfig.model_validate(preset.config)
    assert config.budget.max_iterations == preset.config["budget"]["max_iterations"]


def test_deep_preset_satisfies_the_tournament_invariant() -> None:
    config = EvolveConfig.model_validate(presets_module.build_preset("deep").config)
    assert config.discovery.enabled is True
    assert config.discovery.tournament.enabled is True


def test_preset_strengths_increase_monotonically() -> None:
    iterations = [
        presets_module.build_preset(name).config["budget"]["max_iterations"]
        for name in ("quick", "standard", "deep")
    ]
    assert iterations == sorted(iterations)
    assert len(set(iterations)) == 3


def test_preset_sources_explain_every_touched_field() -> None:
    preset = presets_module.build_preset("quick")
    fields = {source.field for source in preset.sources}
    assert {
        "budget.max_iterations",
        "budget.max_wall_hours",
        "analysis.enabled",
        "discovery.enabled",
        "discovery.tournament.enabled",
        "smoke_test.enabled",
    } <= fields
    assert all(source.source == "preset_default" for source in preset.sources)


def test_meta_exposes_preset_names(client: TestClient) -> None:
    meta = client.get("/api/meta").json()
    assert meta["preset_names"] == ["quick", "standard", "deep"]


# --------------------------------------------------------------------------
# patch merging
# --------------------------------------------------------------------------


def test_merge_applies_the_patch_and_reports_provenance() -> None:
    merged = presets_module.merge_patch(
        "standard", {"budget": {"max_iterations": 7}, "knowledge": {"enabled": False}}
    )
    assert merged.config["budget"]["max_iterations"] == 7
    assert merged.config["knowledge"]["enabled"] is False
    # Untouched preset fields survive.
    assert merged.config["budget"]["max_wall_hours"] == 2.0

    by_field = {source.field: source.source for source in merged.sources}
    assert by_field["budget.max_iterations"] == "user_patch"
    assert by_field["knowledge.enabled"] == "user_patch"
    assert by_field["analysis.enabled"] == "preset_default"


def test_knowledge_injection_maps_to_real_config_fields() -> None:
    """TODO 4.5: every UI option must land on a real engine field (D-C)."""
    # 关闭
    off = presets_module.merge_patch("standard", {"knowledge": {"enabled": False}})
    assert off.config["knowledge"]["enabled"] is False
    # 自动发现
    auto = presets_module.merge_patch("standard", {"discovery": {"enabled": True}})
    assert auto.config["discovery"]["enabled"] is True
    # tournament（隐含 discovery.enabled）
    tournament = presets_module.merge_patch(
        "standard",
        {"discovery": {"enabled": True, "tournament": {"enabled": True}}},
    )
    assert tournament.config["discovery"]["tournament"]["enabled"] is True


@pytest.mark.parametrize(
    "patch",
    [
        {"discovery": {"every_n_iterations": 0}},  # field constraint (ge=1)
        {"discovery": {"enabled": False, "tournament": {"enabled": True}}},
        {"budget": {"max_iterations": "很多"}},  # type error
    ],
)
def test_invalid_patches_are_rejected_with_field_names(patch: dict) -> None:
    with pytest.raises(PresetInvalidError) as excinfo:
        presets_module.merge_patch("standard", patch)
    assert excinfo.value.fields, "the offending field names must travel"


def test_unknown_preset_is_rejected() -> None:
    with pytest.raises(PresetUnknownError):
        presets_module.build_preset("ultra")


# --------------------------------------------------------------------------
# over HTTP
# --------------------------------------------------------------------------


def test_preset_endpoints_round_trip(client: TestClient) -> None:
    listed = client.get("/api/presets")
    assert listed.status_code == 200
    assert [p["name"] for p in listed.json()["presets"]] == [
        "quick",
        "standard",
        "deep",
    ]

    merged = client.post(
        "/api/presets/quick/merge", json={"budget": {"max_iterations": 3}}
    )
    assert merged.status_code == 200
    assert merged.json()["config"]["budget"]["max_iterations"] == 3

    rejected = client.post(
        "/api/presets/quick/merge",
        json={"discovery": {"every_n_iterations": 0}},
    )
    assert rejected.status_code == 422
    assert rejected.json()["error_code"] == "preset.invalid"

    unknown = client.get("/api/presets/ultra")
    assert unknown.status_code == 400
    assert unknown.json()["error_code"] == "preset.unknown"
