"""The contract must be reproducible, and drift must actually fail the build."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import create_model

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_web_contracts as check  # noqa: E402
import export_web_contracts as export  # noqa: E402
from faultevolve.webapi import app as app_module  # noqa: E402
from faultevolve.webapi.contracts import MetaResponse  # noqa: E402


def test_repeated_generation_is_identical() -> None:
    """Two runs in the same process must produce identical bytes."""
    first = export.build_all()
    second = export.build_all()
    assert first == second


def test_committed_files_match_generation() -> None:
    """The committed contract equals what the current source produces."""
    produced = export.build_all()
    for name, expected in produced.items():
        committed = (export.OPENAPI_DIR / name).read_text(encoding="utf-8")
        normalised = committed.replace("\r\n", "\n")
        assert normalised == expected, f"web/openapi/{name} is stale"


def test_drift_check_passes_on_the_committed_contract() -> None:
    assert check.main() == 0


def test_drift_check_fails_on_a_tampered_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hand-edited contract must be rejected."""
    for name, text in export.build_all().items():
        (tmp_path / name).write_text(text, encoding="utf-8", newline="")

    target = tmp_path / "engine-catalog.json"
    tampered = target.read_text(encoding="utf-8").replace(
        '"stream_transport": "sse"', '"stream_transport": "websocket"'
    )
    assert tampered != target.read_text(encoding="utf-8")
    target.write_text(tampered, encoding="utf-8", newline="")

    monkeypatch.setattr(check, "OPENAPI_DIR", tmp_path)
    assert check.main() == 1


def test_drift_check_fails_when_a_file_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, text in export.build_all().items():
        if name != "ui-metadata.json":
            (tmp_path / name).write_text(text, encoding="utf-8", newline="")

    monkeypatch.setattr(check, "OPENAPI_DIR", tmp_path)
    assert check.main() == 1


def test_drift_check_tolerates_a_crlf_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A CRLF worktree copy is git's doing, not drift (WEBUI_BASELINE.md §4.4)."""
    for name, text in export.build_all().items():
        crlf = text.replace("\n", "\r\n")
        (tmp_path / name).write_bytes(crlf.encode("utf-8"))

    monkeypatch.setattr(check, "OPENAPI_DIR", tmp_path)
    assert check.main() == 0


def test_new_dto_field_reaches_the_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adding a field to a DTO must show up in the exported OpenAPI.

    Proof that the sync mechanism covers a model change rather than merely
    re-serialising a stale document.
    """
    baseline = export.build_all()["faultevolve.openapi.json"]
    assert "drift_probe_field" not in baseline

    extended = create_model(
        "MetaResponse",
        __base__=MetaResponse,
        drift_probe_field=(str | None, None),
    )
    patched = tuple(
        extended if model is MetaResponse else model
        for model in app_module.CONTRACT_MODELS
    )
    monkeypatch.setattr(app_module, "CONTRACT_MODELS", patched)

    regenerated = export.build_all()["faultevolve.openapi.json"]
    assert "drift_probe_field" in regenerated
    assert regenerated != baseline


# --------------------------------------------------------------------------
# phase 4: append-only guards
#
# These pin names that the front-end keys off. Removing or renaming any of them
# is a breaking change for a shipped UI, so the guard is deliberately a plain
# equality/inclusion check rather than a schema diff: it fails loudly and the
# fix is to add a *new* name, not to edit this list.
# --------------------------------------------------------------------------

#: DTOs phase 4 introduced. The overview page and the intake form import these
#: straight from the generated client, so their names are part of the contract.
PHASE4_DTOS = (
    "PathProbeRequest",
    "PresetFieldSource",
    "PresetListResponse",
    "PresetResponse",
    "ServerProfileListResponse",
    "TaskCardMetrics",
    "TaskDatasetCardResponse",
)

#: Fields phase 4 added to ``MetaResponse``. All optional, so a phase-3 client
#: keeps working against a phase-4 server.
PHASE4_META_FIELDS = (
    "demo_run_ids",
    "task_catalog_available",
    "preset_names",
    "server_profiles_enabled",
)


def test_phase4_dtos_are_declared_and_published() -> None:
    declared = {model.__name__ for model in app_module.CONTRACT_MODELS}
    for name in PHASE4_DTOS:
        assert name in declared, f"{name} is missing from CONTRACT_MODELS"

    schemas = export.build_all()["faultevolve.openapi.json"]
    for name in PHASE4_DTOS:
        assert f'"{name}"' in schemas, f"{name} never reached components/schemas"


def test_meta_phase4_fields_are_optional_with_safe_defaults() -> None:
    """A phase-3 client must not have to send them, and must not see ``True``.

    ``task_catalog_available`` and ``server_profiles_enabled`` default to
    ``False`` on purpose: an unconfigured deployment reports "not available"
    rather than an empty-looking success.
    """
    fields = MetaResponse.model_fields
    for name in PHASE4_META_FIELDS:
        assert name in fields, f"MetaResponse lost {name}"

    # Only the phase-4 fields are exercised: build a minimal valid instance so
    # the assertion is about defaults, not about the required phase-1 fields.
    probe = MetaResponse(
        contract_version="1.1.0",
        engine_version="0.0.0+test",
        deployment_modes=[],
        default_deployment_mode="local_cloud",
        nav_modules=[],
        stream_transport="sse",
        process_control_enabled=False,
        auth_required=False,
    )
    assert probe.demo_run_ids == []
    assert probe.preset_names == []
    assert probe.task_catalog_available is False
    assert probe.server_profiles_enabled is False


def test_path_probe_request_requires_a_path() -> None:
    """``path`` has no default: an omitted path must fail validation, not
    silently probe the server's cwd."""
    from pydantic import ValidationError

    from faultevolve.webapi.contracts import PathProbeRequest

    with pytest.raises(ValidationError):
        PathProbeRequest()  # type: ignore[call-arg]
    assert PathProbeRequest(path="/data").path == "/data"


def test_phase4_error_codes_are_stable_strings() -> None:
    """The front-end keys its Chinese messages off these exact values."""
    from faultevolve.webapi.errors import ErrorCode

    expected = {
        "TASK_NOT_FOUND": "task.not_found",
        "TASK_NOT_READY": "task.not_ready",
        "SERVER_NOT_FOUND": "server.not_found",
        "PRESET_UNKNOWN": "preset.unknown",
        "PRESET_INVALID": "preset.invalid",
    }
    for attr, value in expected.items():
        assert getattr(ErrorCode, attr).value == value


def test_phase4_error_codes_are_not_marked_unsupported() -> None:
    """``UNSUPPORTED_CODES`` drives "disable the control", not "retry".

    A missing task or an unknown preset is a *request* problem, so treating it
    as an unsupported capability would grey out working UI.
    """
    from faultevolve.webapi.errors import UNSUPPORTED_CODES, ErrorCode

    for code in (
        ErrorCode.TASK_NOT_FOUND,
        ErrorCode.TASK_NOT_READY,
        ErrorCode.SERVER_NOT_FOUND,
        ErrorCode.PRESET_UNKNOWN,
        ErrorCode.PRESET_INVALID,
    ):
        assert code not in UNSUPPORTED_CODES
