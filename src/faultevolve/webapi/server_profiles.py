"""Stored execution-target profiles (TODO 4.3 / phase-4 plan D-E).

One JSON file, written atomically, holding every profile the user configured.
The storage schema has **no password field at all**: passwords live in
environment variables addressed by name, and private keys are addressed by a
*reference* the server resolves locally (``private_key_ref``). Nothing in this
module ever echoes key material back -- ``ServerProfileResponse`` is built
with boolean flags only.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from faultevolve.webapi.contracts import (
    ServerProfileListResponse,
    ServerProfileRequest,
    ServerProfileResponse,
)
from faultevolve.webapi.errors import ServerNotFoundError
from faultevolve.webapi.settings import WebSettings

#: Environment variable prefix through which a ``private_key_ref`` is resolved
#: to a key file *path on the server*. The value never enters a request, a
#: response or the store.
KEY_REF_ENV_PREFIX = "FE_WEB_SSH_KEY_"

DEFAULT_PROFILE_DISPLAY_NAME = "本机（local_cloud）"

#: Fields a stored record carries. Deliberately identical to
#: ``ServerProfileRequest`` minus secrets plus ``profile_id`` -- anything else
#: in the JSON file is dropped on load, so a tampered store cannot smuggle an
#: extra field into a response.
_RECORD_FIELDS = (
    "display_name",
    "mode",
    "host",
    "port",
    "user",
    "private_key_ref",
    "repo_dir",
    "data_dir",
    "runs_dir",
    "artifacts_dir",
    "logs_dir",
    "python_executable",
    "conda_env",
    "cpu_limit",
    "memory_gb",
    "gpu_count",
    "gpu_model",
    "gpu_devices",
    "max_concurrency",
    "timeout_s",
    "notes",
)


def ssh_available() -> bool:
    """Whether the SSH transport can be used in this build.

    Imported lazily so the health/meta route never pays for the cryptography
    wheel, and so "dependency missing" stays a reportable state instead of a
    boot failure.
    """
    try:
        import asyncssh  # noqa: F401
    except ImportError:
        return False
    return True


def resolve_key_ref(ref: str | None) -> Path | None:
    """Turn a stored reference into a key path, or ``None``.

    The mapping is ``FE_WEB_SSH_KEY_<REF> = <path>``. Returning ``None`` for
    an unresolvable ref (rather than raising) lets the probe report an honest
    "认证未配置" instead of a 500.
    """
    if not ref:
        return None
    # The name is upper-cased before the lookup on purpose: ``os.environ``
    # folds case on Windows but *not* on POSIX, so without this a ref stored
    # as ``mykey`` resolves locally and silently returns ``None`` in
    # production (a bogus "认证未配置" instead of a key path).
    # Refs are stored case-sensitively; env vars use an uppercased suffix so
    # ``mykey`` resolves through ``FE_WEB_SSH_KEY_MYKEY``.
    value = os.environ.get(f"{KEY_REF_ENV_PREFIX}{ref.upper()}")
    if not value:
        return None
    return Path(value)


# --------------------------------------------------------------------------
# store I/O
# --------------------------------------------------------------------------


def _store_path(settings: WebSettings) -> Path | None:
    if settings.server_profile_store is None:
        return None
    return settings.server_profile_store


def load_store(settings: WebSettings) -> dict[str, dict[str, Any]]:
    """Every stored profile, keyed by id. Missing file means empty."""
    path = _store_path(settings)
    if path is None or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    profiles = payload.get("profiles") if isinstance(payload, dict) else None
    if not isinstance(profiles, dict):
        return {}
    clean: dict[str, dict[str, Any]] = {}
    for profile_id, record in profiles.items():
        if not isinstance(record, dict):
            continue
        clean[str(profile_id)] = {
            field: record.get(field) for field in _RECORD_FIELDS
        }
    return clean


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    """Temp file in the same directory, then ``os.replace``.

    Same-directory matters: a cross-device rename would lose atomicity. If
    the replace fails the temp file is removed again, so a failed save leaves
    neither a half-written store nor litter.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _save_store(settings: WebSettings, profiles: dict[str, dict[str, Any]]) -> None:
    path = _store_path(settings)
    if path is None:
        # Routes check ``store_configured`` first; reaching here is a bug.
        raise RuntimeError("server profile store is not configured")
    _atomic_write(path, {"version": 1, "profiles": profiles})


def store_configured(settings: WebSettings) -> bool:
    """Whether profiles can be persisted at all.

    ``/api/meta`` reports this as ``server_profiles_enabled``; routes refuse
    with a capability error (not a 500) when it is ``False``.
    """
    return _store_path(settings) is not None


# --------------------------------------------------------------------------
# profile operations
# --------------------------------------------------------------------------


def to_response(profile_id: str, record: dict[str, Any]) -> ServerProfileResponse:
    """Masked view of one profile. The only shape that leaves this module."""
    return ServerProfileResponse(
        profile_id=profile_id,
        display_name=record.get("display_name") or "",
        mode=record.get("mode") or "local_cloud",
        host=record.get("host"),
        port=record.get("port"),
        user=record.get("user"),
        has_private_key=bool(record.get("private_key_ref")),
        # Always True by construction: this DTO never carries secret material,
        # so the UI can rely on the flag meaning "masked where it matters".
        secret_masked=True,
        repo_dir=record.get("repo_dir"),
        data_dir=record.get("data_dir"),
        runs_dir=record.get("runs_dir"),
        artifacts_dir=record.get("artifacts_dir"),
        logs_dir=record.get("logs_dir"),
        cpu_limit=record.get("cpu_limit"),
        memory_gb=record.get("memory_gb"),
        gpu_count=record.get("gpu_count"),
        gpu_devices=list(record.get("gpu_devices") or []),
        gpu_model=record.get("gpu_model"),
        python_executable=record.get("python_executable"),
        conda_env=record.get("conda_env"),
        max_concurrency=record.get("max_concurrency"),
        timeout_s=record.get("timeout_s"),
        notes=record.get("notes") or "",
    )


def ensure_default_profile(settings: WebSettings) -> str | None:
    """Create the empty local_cloud template when the store is empty (D-E).

    Returns the default profile id, or ``None`` when profiles are already
    configured or the store is not configured at all.
    """
    if _store_path(settings) is None:
        return None
    profiles = load_store(settings)
    if profiles:
        return None
    profile_id = uuid.uuid4().hex[:8]
    profiles[profile_id] = {
        "display_name": DEFAULT_PROFILE_DISPLAY_NAME,
        "mode": "local_cloud",
        "private_key_ref": None,
        "notes": "",
    }
    _save_store(settings, profiles)
    return profile_id


def list_profiles(settings: WebSettings) -> ServerProfileListResponse:
    # Create the default template first, then load: the list must include it.
    ensure_default_profile(settings)
    profiles = load_store(settings)
    ordered = sorted(
        profiles.items(), key=lambda item: item[1].get("display_name") or ""
    )
    default_id = next(
        (
            profile_id
            for profile_id, record in ordered
            if record.get("display_name") == DEFAULT_PROFILE_DISPLAY_NAME
        ),
        None,
    )
    return ServerProfileListResponse(
        profiles=[to_response(profile_id, record) for profile_id, record in ordered],
        default_profile_id=default_id,
        ssh_available=ssh_available(),
    )


def get_profile(settings: WebSettings, profile_id: str) -> ServerProfileResponse:
    record = require_record(settings, profile_id)
    return to_response(profile_id, record)


def require_record(settings: WebSettings, profile_id: str) -> dict[str, Any]:
    """The raw record for one profile, for the execution backends."""
    profiles = load_store(settings)
    record = profiles.get(profile_id)
    if record is None:
        raise ServerNotFoundError(profile_id)
    return record


def upsert_profile(
    settings: WebSettings, request: ServerProfileRequest, profile_id: str | None
) -> ServerProfileResponse:
    """Create or update one profile.

    Update **replaces** the record: a request that omits ``private_key_ref``
    clears it, which is the honest reading of "what you sent is what's stored".
    """
    if _store_path(settings) is None:
        raise RuntimeError("server profile store is not configured")
    profiles = load_store(settings)
    target = profile_id or uuid.uuid4().hex[:8]
    record: dict[str, Any] = {"notes": ""}
    for field in _RECORD_FIELDS:
        value = getattr(request, field)
        record[field] = list(value) if isinstance(value, list) else value
    profiles[target] = record
    _save_store(settings, profiles)
    return to_response(target, record)


def delete_profile(settings: WebSettings, profile_id: str) -> None:
    profiles = load_store(settings)
    if profile_id not in profiles:
        raise ServerNotFoundError(profile_id)
    del profiles[profile_id]
    _save_store(settings, profiles)


__all__ = [
    "DEFAULT_PROFILE_DISPLAY_NAME",
    "KEY_REF_ENV_PREFIX",
    "delete_profile",
    "ensure_default_profile",
    "get_profile",
    "list_profiles",
    "require_record",
    "resolve_key_ref",
    "ssh_available",
    "to_response",
    "upsert_profile",
]
