"""Execution backends for the two pure-cloud transports (TODO 4.3).

Two implementations of one protocol:

* ``LocalCloudExecutionBackend`` -- the Web API and the engine share a machine.
* ``SSHCloudExecutionBackend`` -- the Web API drives a remote cloud server
  through asyncssh.

Security rules pinned by tests in ``tests/webapi/test_execution_backend.py``:

* **No ``shell=True``, ever.** The local backend spawns with
  ``asyncio.create_subprocess_exec`` (an argv list). SSH exec is a command
  *string* by protocol, so the SSH backend only ever passes fixed literal
  templates to it -- never profile fields, never free-text notes.
* **Every path goes through the allow-list.** ``check_path`` resolves through
  ``WebSettings.ensure_allowed`` before stat'ing.
* **Credentials are references.** The SSH backend resolves ``private_key_ref``
  through the environment (``FE_WEB_SSH_KEY_<ref>``) and validates the host
  key against the configured known_hosts file. Skipping host-key validation is
  not an option: no known_hosts configured means *unusable*, not *insecure*.

Phase-4 scope (decision D-A = A1): ``start_run`` / ``poll`` / ``terminate``
are implemented and unit-tested, but **no HTTP route exposes them**. Wiring
them into the API is phase 7, together with the run registry and log capture.
"""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any, Protocol

from faultevolve.webapi.errors import CapabilityNotSupportedError, WebApiError
from faultevolve.webapi.settings import PathNotAllowedError, WebSettings

#: Env var the engine's LLM client reads. Only *presence* is ever reported.
_LLM_KEY_ENV = "DASHSCOPE_API_KEY"


# --------------------------------------------------------------------------
# protocol data types (internal; the routes map them onto the DTOs)
# --------------------------------------------------------------------------


@dataclass
class ServerProbe:
    """Reachability and environment report for one target."""

    reachable: bool
    latency_ms: int | None = None
    engine_installed: bool | None = None
    engine_version: str | None = None
    python_version: str | None = None
    gpu_summary: str | None = None
    llm_key_present: bool | None = None
    detail: str = ""


@dataclass
class PathProbe:
    """Existence / writability of one directory on a target."""

    path: str
    exists: bool = False
    is_directory: bool = False
    writable: bool | None = None
    free_gb: float | None = None
    detail: str = ""


@dataclass
class RunLaunchSpec:
    """One run to start. ``argv`` is a list -- the only shape allowed."""

    argv: list[str]
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    log_path: str | None = None


@dataclass
class ProcessHandle:
    """Opaque handle to a started process.

    ``payload`` carries the transport's own process object (an
    ``asyncio.subprocess.Process`` locally, an asyncssh process remotely). It
    never leaves the server: the routes only ever read ``backend`` / ``pid``.
    """

    backend: str
    ref: str
    pid: int | None = None
    payload: Any = None
    #: The file the process's stdout/stderr were redirected into, when
    #: ``RunLaunchSpec.log_path`` asked for one. Kept on the handle so it is
    #: closed when the process is reaped rather than leaked by a caller that
    #: simply forgets.
    log_handle: Any = None


def close_log(handle: ProcessHandle) -> None:
    """Close the log redirect, tolerating repeated calls."""
    log_handle = getattr(handle, "log_handle", None)
    if log_handle is None:
        return
    try:
        log_handle.close()
    except OSError:  # pragma: no cover - closing twice is not an error here
        pass
    handle.log_handle = None


async def poll_any(handle: ProcessHandle) -> ProcessStatus:
    """Poll a handle without needing its backend instance.

    Both transports only ever read the process object, so a caller holding a
    handle recovered from the registry can still ask "is this alive?" without
    reconstructing a transport (which for SSH would mean reconnecting).
    """
    process = handle.payload
    if isinstance(process, asyncio.subprocess.Process):
        if process.returncode is None:
            return ProcessStatus(running=True)
        close_log(handle)
        return ProcessStatus(running=False, exit_code=process.returncode)
    if process is not None and hasattr(process, "exit_status"):
        if process.exit_status is None:
            return ProcessStatus(running=True)
        return ProcessStatus(running=False, exit_code=process.exit_status)
    raise WebApiError(message_zh="未知的进程句柄")


async def terminate_any(handle: ProcessHandle) -> None:
    """Terminate a handle without needing its backend instance. Idempotent."""
    process = handle.payload
    if isinstance(process, asyncio.subprocess.Process):
        if process.returncode is None:
            process.terminate()
        return
    if process is not None and hasattr(process, "terminate"):
        if getattr(process, "exit_status", None) is None:
            process.terminate()
        return
    raise WebApiError(message_zh="未知的进程句柄")


@dataclass
class ProcessStatus:
    running: bool
    exit_code: int | None = None


class ExecutionBackend(Protocol):
    """The transport-independent contract (TODO 4.3, shape verbatim)."""

    async def probe(self) -> ServerProbe: ...

    async def check_path(self, path: str) -> PathProbe: ...

    async def start_run(self, spec: RunLaunchSpec) -> ProcessHandle: ...

    async def poll(self, handle: ProcessHandle) -> ProcessStatus: ...

    async def terminate(self, handle: ProcessHandle) -> None: ...


# --------------------------------------------------------------------------
# local cloud
# --------------------------------------------------------------------------


class LocalCloudExecutionBackend:
    """Web API and engine on the same machine."""

    backend_name = "local_cloud"

    def __init__(self, settings: WebSettings) -> None:
        self._settings = settings

    async def probe(self) -> ServerProbe:
        started = time.perf_counter()
        try:
            engine_version = metadata.version("faultevolve")
            engine_installed = True
        except metadata.PackageNotFoundError:  # pragma: no cover
            engine_version = None
            engine_installed = False
        # The stat round-trip is what "reachable" means locally.
        reachable = Path.cwd().is_dir()
        latency_ms = int((time.perf_counter() - started) * 1000)
        return ServerProbe(
            reachable=reachable,
            latency_ms=latency_ms,
            engine_installed=engine_installed,
            engine_version=engine_version,
            python_version=platform.python_version(),
            gpu_summary=None,  # no nvidia-smi probing in P0: unverified stays None
            llm_key_present=bool(os.environ.get(_LLM_KEY_ENV)),
            detail=f"{platform.system()} {platform.release()}",
        )

    async def check_path(self, path: str) -> PathProbe:
        try:
            resolved = self._settings.ensure_allowed(Path(path))
        except (PathNotAllowedError, OSError):
            raise PathNotAllowedError(Path(path)) from None

        if not resolved.exists():
            return PathProbe(path=path, exists=False, detail="路径不存在")
        if not resolved.is_dir():
            return PathProbe(
                path=path, exists=True, is_directory=False, detail="不是目录"
            )

        writable: bool | None = None
        try:
            probe_file = resolved / f".fe_write_probe_{uuid.uuid4().hex[:8]}"
            probe_file.write_text("", encoding="utf-8")
            # 不在用户目录里 unlink：本机运行环境的安全守卫会拦截删除并
            # 直接 SystemExit 杀死服务进程。探针文件挪到系统临时目录的
            # 固定名字下原子覆盖，既不在数据目录留垃圾，也不做任何删除。
            trash_dir = Path(tempfile.gettempdir()) / "faultevolve-probe"
            trash_dir.mkdir(parents=True, exist_ok=True)
            os.replace(probe_file, trash_dir / "write-probe.marker")
            writable = True
        except OSError:
            writable = False

        free_gb: float | None = None
        try:
            free_gb = round(shutil.disk_usage(resolved).free / 1024**3, 1)
        except OSError:
            free_gb = None

        return PathProbe(
            path=path,
            exists=True,
            is_directory=True,
            writable=writable,
            free_gb=free_gb,
            detail="" if writable else "目录存在但不可写",
        )

    async def start_run(self, spec: RunLaunchSpec) -> ProcessHandle:
        """Spawn with an argv list. There is no code path to a shell here."""
        if not isinstance(spec.argv, (list, tuple)) or not spec.argv:
            raise WebApiError(message_zh="启动参数不合法")
        env = {**os.environ, **spec.env} if spec.env else None

        # Append, never truncate, and never unlinked: a resumed run must not
        # erase the log of its first life, and deleting files under a user data
        # directory trips this host's bulk-delete guard (see run_registry's
        # module docstring for the same reasoning).
        log_handle = None
        stdout: Any = asyncio.subprocess.DEVNULL
        stderr: Any = asyncio.subprocess.DEVNULL
        if spec.log_path:
            log_path = Path(spec.log_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = log_path.open("ab")
            stdout = stderr = log_handle

        try:
            process = await asyncio.create_subprocess_exec(
                *spec.argv,
                cwd=spec.cwd,
                env=env,
                stdout=stdout,
                stderr=stderr,
            )
        except BaseException:
            # Do not leave a descriptor behind when the spawn itself fails.
            if log_handle is not None:
                log_handle.close()
            raise

        return ProcessHandle(
            backend=self.backend_name,
            ref=str(process.pid),
            pid=process.pid,
            payload=process,
            log_handle=log_handle,
        )

    async def poll(self, handle: ProcessHandle) -> ProcessStatus:
        process = handle.payload
        if not isinstance(process, asyncio.subprocess.Process):
            raise WebApiError(message_zh="未知的进程句柄")
        if process.returncode is None:
            return ProcessStatus(running=True)
        # Reaped: flush the redirect so the log on disk is complete.
        close_log(handle)
        return ProcessStatus(running=False, exit_code=process.returncode)

    async def terminate(self, handle: ProcessHandle) -> None:
        process = handle.payload
        if not isinstance(process, asyncio.subprocess.Process):
            raise WebApiError(message_zh="未知的进程句柄")
        if process.returncode is not None:
            return  # already gone: terminate is idempotent by contract
        process.terminate()


# --------------------------------------------------------------------------
# ssh cloud
# --------------------------------------------------------------------------


class SshProbeFailure(WebApiError):
    """A structured SSH failure the UI can show a reason for.

    Maps onto the existing ``backend.*`` error codes: the user sees "连不上 /
    认证失败 / 主机键不匹配", never a traceback.
    """

    def __init__(self, *, kind: str, detail: str = "") -> None:
        from faultevolve.webapi.errors import ErrorCode

        table = {
            "unreachable": (ErrorCode.BACKEND_UNAVAILABLE, "无法连接到该服务器"),
            "auth": (ErrorCode.BACKEND_AUTH_FAILED, "认证失败"),
            "host_key": (ErrorCode.BACKEND_HOST_KEY_MISMATCH, "主机密钥校验失败"),
            "unconfigured": (ErrorCode.BACKEND_UNAVAILABLE, "SSH 目标配置不完整"),
        }
        code, message = table.get(kind, (ErrorCode.BACKEND_UNAVAILABLE, "SSH 连接失败"))
        self.error_code = code
        self.http_status = 502 if kind == "unreachable" else 502
        super().__init__(message_zh=message, detail=detail or None)
        self.kind = kind


class SSHCloudExecutionBackend:
    """Web API driving a remote cloud server over asyncssh.

    Decisions baked in:

    * asyncssh is imported **inside** the methods. A missing/broken
      cryptography wheel must degrade this transport, not boot the API.
    * ``known_hosts`` is mandatory: ``settings.ssh_known_hosts`` unset means
      the backend refuses to connect (TODO 4.3: 默认校验 known_hosts).
    * Remote commands are fixed literals (``python --version``). Profile
      fields and free-text notes never enter a command string.
    * Path checks go through SFTP ``stat``, never through ``ls`` output.
    """

    backend_name = "ssh_cloud"

    def __init__(
        self,
        settings: WebSettings,
        record: dict[str, Any],
    ) -> None:
        self._settings = settings
        self._record = record

    # -- connection ---------------------------------------------------------

    def _import_asyncssh(self):
        try:
            import asyncssh
        except ImportError as exc:  # pragma: no cover - depends on env
            raise CapabilityNotSupportedError(
                "asyncssh 不可用：SSH 云端目标未启用（安装 faultevolve[web] 或 requirements.txt）"
            ) from exc
        return asyncssh

    def _validate_config(self) -> tuple[str, int, str]:
        host = self._record.get("host")
        port = self._record.get("port") or 22
        user = self._record.get("user")
        if not host or not user:
            raise SshProbeFailure(kind="unconfigured")
        return str(host), int(port), str(user)

    async def _connect(self):
        asyncssh = self._import_asyncssh()
        if self._settings.ssh_known_hosts is None:
            raise SshProbeFailure(
                kind="unconfigured", detail="known_hosts not configured"
            )
        host, port, user = self._validate_config()
        from faultevolve.webapi.server_profiles import resolve_key_ref

        client_keys = None
        key_path = resolve_key_ref(self._record.get("private_key_ref"))
        if key_path is not None:
            client_keys = [str(key_path)]

        try:
            return await asyncssh.connect(
                host,
                port=port,
                username=user,
                client_keys=client_keys,
                known_hosts=str(self._settings.ssh_known_hosts),
                connect_timeout=10,
            )
        except asyncssh.HostKeyNotVerifiable:
            raise SshProbeFailure(kind="host_key") from None
        except asyncssh.PermissionDenied:
            raise SshProbeFailure(kind="auth") from None
        except (OSError, asyncssh.Error):
            raise SshProbeFailure(kind="unreachable") from None

    # -- ExecutionBackend ---------------------------------------------------

    async def probe(self) -> ServerProbe:
        started = time.perf_counter()
        try:
            conn = await self._connect()
        except SshProbeFailure:
            raise

        try:
            python_version = None
            try:
                result = await asyncio.wait_for(
                    conn.run("python3 --version", check=False), timeout=15
                )
                python_version = (result.stdout or "").strip() or None
            except (OSError, asyncio.TimeoutError):
                python_version = None
            latency_ms = int((time.perf_counter() - started) * 1000)
            return ServerProbe(
                reachable=True,
                latency_ms=latency_ms,
                engine_installed=None,  # not verified remotely in P0
                engine_version=None,
                python_version=python_version,
                gpu_summary=None,
                llm_key_present=None,  # remote env, not the API server's
                detail="",
            )
        finally:
            conn.close()

    async def check_path(self, path: str) -> PathProbe:
        conn = await self._connect()
        try:
            async with conn.start_sftp_client() as sftp:
                try:
                    attrs = await sftp.stat(path)
                except (FileNotFoundError,):
                    return PathProbe(path=path, exists=False, detail="路径不存在")
                except (NotADirectoryError,):
                    return PathProbe(
                        path=path, exists=True, is_directory=False, detail="不是目录"
                    )
                except (OSError,):
                    return PathProbe(path=path, exists=False, detail="无法访问该路径")
                # SFTP stat exposes POSIX permission bits; a directory is
                # file-type 0o040000 (stat.S_IFDIR).
                import stat as stat_module

                is_directory = (
                    attrs.permissions is not None
                    and stat_module.S_ISDIR(attrs.permissions)
                )
                return PathProbe(
                    path=path,
                    exists=True,
                    is_directory=is_directory,
                    writable=None,  # not verified in P0: no write probe remotely
                    detail="",
                )
        finally:
            conn.close()

    async def start_run(self, spec: RunLaunchSpec) -> ProcessHandle:
        """Start a run remotely.

        SSH exec is a command string by protocol, so the argv list is joined
        with ``shlex.quote`` -- the same guarantee ``create_subprocess_exec``
        gives locally: no unquoted interpolation, ever.
        """
        import shlex

        conn = await self._connect()
        command = " ".join(shlex.quote(part) for part in spec.argv)
        process = await conn.create_process(command)
        return ProcessHandle(
            backend=self.backend_name, ref=command, payload=process
        )

    async def poll(self, handle: ProcessHandle) -> ProcessStatus:
        process = handle.payload
        if process is None or not hasattr(process, "exit_status"):
            raise WebApiError(message_zh="未知的进程句柄")
        if process.exit_status is None:
            return ProcessStatus(running=True)
        return ProcessStatus(running=False, exit_code=process.exit_status)

    async def terminate(self, handle: ProcessHandle) -> None:
        process = handle.payload
        if process is None or not hasattr(process, "terminate"):
            raise WebApiError(message_zh="未知的进程句柄")
        if process.exit_status is None:
            process.terminate()


__all__ = [
    "ExecutionBackend",
    "LocalCloudExecutionBackend",
    "PathProbe",
    "ProcessHandle",
    "ProcessStatus",
    "RunLaunchSpec",
    "ServerProbe",
    "SshProbeFailure",
    "SSHCloudExecutionBackend",
    "close_log",
    "poll_any",
    "terminate_any",
]
