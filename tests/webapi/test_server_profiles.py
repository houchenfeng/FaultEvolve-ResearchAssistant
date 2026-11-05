"""Server profile storage and masking (TODO 4.3 / 4.4, plan D-E)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from faultevolve.webapi import server_profiles  # noqa: E402
from faultevolve.webapi.app import create_app  # noqa: E402
from faultevolve.webapi.errors import ServerNotFoundError  # noqa: E402
from faultevolve.webapi.settings import WebSettings  # noqa: E402

EVIL_NOTES = "使用 conda; rm -rf / # $(whoami) && cat /etc/passwd"


def _settings(tmp_path: Path) -> WebSettings:
    return WebSettings(
        task_roots=[tmp_path],
        allowed_path_roots=[tmp_path],
        server_profile_store=tmp_path / "profiles.json",
    )


def _client(settings: WebSettings) -> TestClient:
    return TestClient(create_app(settings), raise_server_exceptions=False)


# --------------------------------------------------------------------------
# store lifecycle
# --------------------------------------------------------------------------


def test_unconfigured_store_is_a_capability_gap(tmp_path: Path) -> None:
    client = _client(WebSettings(allowed_path_roots=[tmp_path]))
    response = client.get("/api/servers")
    assert response.status_code == 501
    assert response.json()["error_code"] == "not_supported"
    meta = client.get("/api/meta").json()
    assert meta["server_profiles_enabled"] is False


def test_first_list_creates_the_default_local_profile(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    client = _client(settings)

    listing = client.get("/api/servers").json()
    assert listing["default_profile_id"] is not None
    default = next(
        p
        for p in listing["profiles"]
        if p["profile_id"] == listing["default_profile_id"]
    )
    assert default["display_name"] == server_profiles.DEFAULT_PROFILE_DISPLAY_NAME
    assert default["mode"] == "local_cloud"
    assert default["has_private_key"] is False

    # Persisted: a second list does not duplicate it.
    again = client.get("/api/servers").json()
    assert len(again["profiles"]) == 1


def test_upsert_then_get_then_delete(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    client = _client(settings)

    created = client.post(
        "/api/servers",
        json={
            "display_name": "Rocky 服务器",
            "mode": "ssh_cloud",
            "host": "10.61.48.10",
            "port": 22,
            "user": "hcf",
            "repo_dir": "/opt/faultevolve",
        },
    )
    assert created.status_code == 200
    profile_id = created.json()["profile_id"]

    fetched = client.get(f"/api/servers/{profile_id}")
    assert fetched.status_code == 200
    assert fetched.json()["host"] == "10.61.48.10"

    assert client.delete(f"/api/servers/{profile_id}").status_code == 204
    assert client.get(f"/api/servers/{profile_id}").status_code == 404
    assert client.get(f"/api/servers/{profile_id}").json()["error_code"] == (
        "server.not_found"
    )

    with pytest.raises(ServerNotFoundError):
        server_profiles.require_record(settings, profile_id)


# --------------------------------------------------------------------------
# secrets never travel, never land in the store
# --------------------------------------------------------------------------


def test_password_is_not_even_an_accepted_field(tmp_path: Path) -> None:
    """``extra=forbid`` is what makes "no password field" a guarantee."""
    client = _client(_settings(tmp_path))
    response = client.post(
        "/api/servers",
        json={"display_name": "x", "mode": "local_cloud", "password": "hunter2"},
    )
    assert response.status_code == 422
    assert "password" not in client.get("/api/servers").json()["profiles"][0]


def test_store_file_never_contains_secret_material(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    client = _client(settings)
    client.post(
        "/api/servers",
        json={
            "display_name": "k",
            "mode": "ssh_cloud",
            "host": "h",
            "user": "u",
            "private_key_ref": "mykey",
        },
    )
    raw = (tmp_path / "profiles.json").read_text(encoding="utf-8")
    assert "private_key_ref" in raw  # the *reference* is stored
    for forbidden in ("password", "BEGIN OPENSSH", "hunter2", "sk-"):
        assert forbidden not in raw


def test_private_key_ref_resolves_through_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_file = tmp_path / "id_ed25519"
    key_file.write_text("not a real key", encoding="utf-8")
    monkeypatch.setenv("FE_WEB_SSH_KEY_MYKEY", str(key_file))
    assert server_profiles.resolve_key_ref("mykey") == key_file
    assert server_profiles.resolve_key_ref("nope") is None
    assert server_profiles.resolve_key_ref(None) is None


def test_key_ref_resolves_under_posix_case_sensitivity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lookup must not depend on ``os.environ`` folding case.

    ``os.environ`` is case-insensitive on Windows and case-sensitive on
    POSIX, so ``monkeypatch.setenv("FE_WEB_SSH_KEY_MYKEY", ...)`` alone cannot
    catch a missing ``.upper()``: the dev host would go green while CI went
    red. Swapping the module's ``os`` for a namespace whose ``environ`` is a
    plain dict restores true POSIX semantics on every host.
    """
    key_file = tmp_path / "id_ed25519"
    key_file.write_text("not a real key", encoding="utf-8")
    monkeypatch.setattr(
        server_profiles,
        "os",
        types.SimpleNamespace(environ={"FE_WEB_SSH_KEY_MYKEY": str(key_file)}),
    )
    assert server_profiles.resolve_key_ref("mykey") == key_file
    assert server_profiles.resolve_key_ref("MYKEY") == key_file
    assert server_profiles.resolve_key_ref("nope") is None
    assert server_profiles.resolve_key_ref(None) is None


# --------------------------------------------------------------------------
# free text stays free text
# --------------------------------------------------------------------------


def test_notes_are_stored_verbatim_and_never_spawned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TODO 阶段 4 测试项: 自由文本不能变成命令参数."""
    settings = _settings(tmp_path)
    client = _client(settings)

    created = client.post(
        "/api/servers",
        json={"display_name": "x", "mode": "local_cloud", "notes": EVIL_NOTES},
    )
    profile_id = created.json()["profile_id"]

    # Stored verbatim: no parsing, no sanitising, no executing.
    fetched = client.get(f"/api/servers/{profile_id}").json()
    assert fetched["notes"] == EVIL_NOTES

    # And nothing the API does with the profile ever hands it to a process.
    calls: list[tuple[tuple, dict]] = []
    real_exec = asyncio.create_subprocess_exec

    async def spying_exec(*args, **kwargs):
        calls.append((args, kwargs))
        return await real_exec(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spying_exec)

    assert client.post(f"/api/servers/{profile_id}/probe").status_code == 200
    assert (
        client.post(
            f"/api/servers/{profile_id}/check-path", json={"path": str(tmp_path)}
        ).status_code
        == 200
    )
    for args, kwargs in calls:
        assert "shell" not in kwargs or kwargs["shell"] is False
        for arg in args:
            assert EVIL_NOTES not in str(arg)
    assert calls == [], "probe/check-path must not spawn anything at all"


# --------------------------------------------------------------------------
# durability
# --------------------------------------------------------------------------


def test_failed_save_leaves_the_previous_store_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    client = _client(settings)
    client.get("/api/servers")  # creates the default profile
    before = (tmp_path / "profiles.json").read_text(encoding="utf-8")

    def failing_replace(src: Path, dst: Path) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", failing_replace)
    response = client.post(
        "/api/servers",
        json={"display_name": "y", "mode": "local_cloud"},
    )
    # The OSError is the server's, not the client's: a 500, never a torn store.
    assert response.status_code == 500

    assert (tmp_path / "profiles.json").read_text(encoding="utf-8") == before
    payload = json.loads(before)
    assert len(payload["profiles"]) == 1
    # The abandoned temp file is cleaned up, not left as litter.
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".")]
    assert leftovers == []
