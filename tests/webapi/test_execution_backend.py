"""Execution backends (TODO 4.3): local lifecycle + honest SSH failures."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from faultevolve.webapi.errors import (  # noqa: E402
    CapabilityNotSupportedError,
    WebApiError,
)
from faultevolve.webapi.execution_backend import (  # noqa: E402
    LocalCloudExecutionBackend,
    PathProbe,
    ProcessHandle,
    RunLaunchSpec,
    ServerProbe,
    SshProbeFailure,
    SSHCloudExecutionBackend,
)
from faultevolve.webapi.settings import PathNotAllowedError, WebSettings  # noqa: E402


def _settings(tmp_path: Path) -> WebSettings:
    return WebSettings(
        allowed_path_roots=[tmp_path], task_roots=[tmp_path]
    )


# --------------------------------------------------------------------------
# local backend
# --------------------------------------------------------------------------


async def test_local_probe_reports_a_live_machine(tmp_path: Path) -> None:
    backend = LocalCloudExecutionBackend(_settings(tmp_path))
    probe = await backend.probe()
    assert isinstance(probe, ServerProbe)
    assert probe.reachable is True
    assert probe.python_version
    assert probe.engine_installed is True


async def test_local_check_path_on_a_real_directory(tmp_path: Path) -> None:
    target = tmp_path / "data"
    target.mkdir()
    backend = LocalCloudExecutionBackend(_settings(tmp_path))

    probe = await backend.check_path(str(target))
    assert isinstance(probe, PathProbe)
    assert (probe.exists, probe.is_directory, probe.writable) == (True, True, True)
    assert probe.free_gb is not None and probe.free_gb > 0


async def test_local_check_path_refuses_outside_the_allow_list(
    tmp_path: Path,
) -> None:
    backend = LocalCloudExecutionBackend(_settings(tmp_path))
    with pytest.raises(PathNotAllowedError):
        await backend.check_path("C:/Windows")


async def test_local_run_lifecycle_start_poll_terminate(tmp_path: Path) -> None:
    """start_run/poll/terminate exist and work, even though no route serves
    them yet (decision D-A = A1)."""
    backend = LocalCloudExecutionBackend(_settings(tmp_path))

    handle = await backend.start_run(
        RunLaunchSpec(argv=[sys.executable, "-c", "print('ok')"])
    )
    assert isinstance(handle, ProcessHandle)
    status: ProcessHandle | None = None
    for _ in range(200):
        status = await backend.poll(handle)  # type: ignore[assignment]
        if not status.running:
            break
        await asyncio.sleep(0.05)
    assert status is not None and status.exit_code == 0

    # terminate on a finished process is a no-op, not an error
    await backend.terminate(handle)


async def test_local_terminate_stops_a_running_process(tmp_path: Path) -> None:
    backend = LocalCloudExecutionBackend(_settings(tmp_path))
    handle = await backend.start_run(
        RunLaunchSpec(argv=[sys.executable, "-c", "import time; time.sleep(30)"])
    )
    assert (await backend.poll(handle)).running is True
    await backend.terminate(handle)
    for _ in range(200):
        if not (await backend.poll(handle)).running:
            break
        await asyncio.sleep(0.05)
    assert not (await backend.poll(handle)).running


async def test_local_start_run_rejects_non_list_argv(tmp_path: Path) -> None:
    backend = LocalCloudExecutionBackend(_settings(tmp_path))
    with pytest.raises(WebApiError):
        await backend.start_run(RunLaunchSpec(argv=[]))  # type: ignore[arg-type]


async def test_start_run_never_uses_a_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exec call must be argv-only; a ``shell=True`` here is the one bug
    this whole module exists to prevent."""
    seen: list[dict] = []
    real_exec = asyncio.create_subprocess_exec

    async def spying_exec(*args, **kwargs):
        seen.append({"args": args, "kwargs": kwargs})
        return await real_exec(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spying_exec)
    backend = LocalCloudExecutionBackend(_settings(tmp_path))
    handle = await backend.start_run(
        RunLaunchSpec(argv=[sys.executable, "-c", "print(1)"])
    )
    assert seen, "the spawn must have gone through create_subprocess_exec"
    for call in seen:
        assert call["kwargs"].get("shell", False) is False
        assert isinstance(call["args"], tuple)
    await backend.poll(handle)


# --------------------------------------------------------------------------
# ssh backend
# --------------------------------------------------------------------------


def _ssh_record(**overrides) -> dict:
    record = {"mode": "ssh_cloud", "host": "127.0.0.1", "port": 1, "user": "u"}
    record.update(overrides)
    return record


async def test_ssh_backend_refuses_without_known_hosts(tmp_path: Path) -> None:
    """No known_hosts configured means *unusable*, never *skip validation*."""
    settings = WebSettings(allowed_path_roots=[tmp_path])  # no ssh_known_hosts
    backend = SSHCloudExecutionBackend(settings, _ssh_record())
    with pytest.raises(SshProbeFailure) as excinfo:
        await backend.probe()
    assert excinfo.value.kind == "unconfigured"
    assert excinfo.value.error_code.value == "backend.unavailable"


async def test_ssh_backend_reports_an_unreachable_host_honestly(
    tmp_path: Path,
) -> None:
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("", encoding="utf-8")
    settings = WebSettings(
        allowed_path_roots=[tmp_path], ssh_known_hosts=known_hosts
    )
    backend = SSHCloudExecutionBackend(settings, _ssh_record(port=1))
    with pytest.raises(SshProbeFailure) as excinfo:
        await backend.probe()
    # 127.0.0.1:1 refuses the connection: unreachable, not a host-key problem.
    assert excinfo.value.kind == "unreachable"
    assert excinfo.value.http_status >= 500


async def test_ssh_backend_requires_host_and_user(tmp_path: Path) -> None:
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("", encoding="utf-8")
    settings = WebSettings(
        allowed_path_roots=[tmp_path], ssh_known_hosts=known_hosts
    )
    backend = SSHCloudExecutionBackend(settings, _ssh_record(host=None))
    with pytest.raises(SshProbeFailure) as excinfo:
        await backend.probe()
    assert excinfo.value.kind == "unconfigured"


async def test_missing_asyncssh_is_a_capability_gap_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """asyncssh is installed (D-B = B2), so its absence is simulated."""
    monkeypatch.setitem(sys.modules, "asyncssh", None)
    settings = WebSettings(allowed_path_roots=[tmp_path])
    backend = SSHCloudExecutionBackend(settings, _ssh_record())
    with pytest.raises(CapabilityNotSupportedError):
        await backend.probe()


async def test_ssh_unknown_handle_is_rejected(tmp_path: Path) -> None:
    backend = SSHCloudExecutionBackend(WebSettings(allowed_path_roots=[tmp_path]), _ssh_record())
    with pytest.raises(WebApiError):
        await backend.poll(ProcessHandle(backend="ssh_cloud", ref="x", payload=None))


# --------------------------------------------------------------------------
# /api/meta wiring (decision D-D)
# --------------------------------------------------------------------------


def test_meta_reports_local_available_and_ssh_by_import() -> None:
    from faultevolve.webapi.app import create_app
    from faultevolve.webapi import server_profiles

    client = TestClient(create_app(), raise_server_exceptions=False)
    modes = {
        entry["mode"]: entry for entry in client.get("/api/meta").json()["deployment_modes"]
    }
    assert modes["local_cloud"]["available"] is True
    assert modes["local_cloud"]["detail"] == "本机/同机云端执行目标可用"
    # ssh_cloud mirrors whether asyncssh actually imports in this build.
    assert modes["ssh_cloud"]["available"] is server_profiles.ssh_available()


def test_process_control_is_off_until_switched_on() -> None:
    """Launching is opt-in: the endpoints exist from phase 7, the switch does not.

    Replaces the phase-1/4 pin that asserted the *routes* were absent. What
    still has to hold is the stronger property: with the switch off, a request
    that reaches ``POST /api/runs`` must answer ``not_supported`` (501) rather
    than 404 or -- far worse -- start something. The UI reads that code to
    disable the launch button and say why.
    """
    from faultevolve.webapi.app import create_app

    client = TestClient(create_app(), raise_server_exceptions=False)
    assert client.get("/api/meta").json()["process_control_enabled"] is False
    assert client.get("/api/meta").json()["run_registry_configured"] is False

    response = client.post(
        "/api/runs",
        json={"task_id": "t", "server_profile_id": "p", "preset": "quick"},
    )
    assert response.status_code == 501
    assert response.json()["error_code"] == "not_supported"
    # And nothing was started behind the refusal.
    assert client.get("/api/runs").json() == []
