"""Run lifecycle: create, cancel, resume, append rounds, recover (TODO 7.3-7.5).

This is the module where the Web API stops being read-only. Everything it does
was already unit-tested at the transport level (``execution_backend``); what is
added here is the *policy* around it:

* **Readiness comes before a process exists.** A run that would fail its
  pre-flight is refused with the blockers, not started and then observed dying.
* **The registry is written before the reply leaves.** A process the API cannot
  name afterwards would be an orphan.
* **Nothing is faked.** The engine has no safe pause point, so ``pause`` answers
  409 with the reason instead of pretending to stop (TODO 7.4). A run is only
  reported ``completed`` when its ``run_summary.json`` says so.
* **A row claiming ``running`` is not trusted indefinitely.** The live endpoint
  closes a row whose process is gone -- ``completed`` when the engine left a
  summary, ``interrupted`` otherwise -- and the start-up pass does the same for
  rows left over from a previous lifetime. ``run_summary.json`` lives in
  ``<artifacts_dir>/<run_id>/``; see :func:`_summary_path`.

Two module-level caches exist deliberately and both are honest about their
limits: ``_live_handles`` holds process objects for runs started in *this*
process, and the recovery pass re-derives state from pids and artifacts after a
restart. With more than one worker they would each hold a subset -- the API is
specified as single-worker, and the code does not pretend otherwise.
"""

from __future__ import annotations

import asyncio
import ctypes
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import yaml

from faultevolve.webapi import presets as presets_module
from faultevolve.webapi import run_registry as registry
from faultevolve.webapi import server_profiles, task_service
from faultevolve.webapi.contracts import (
    AppendRoundsRequest,
    ControlAction,
    RunControlResponse,
    RunCreateRequest,
    RunCreateResponse,
    RunLiveResponse,
)
from faultevolve.webapi.errors import (
    CapabilityNotSupportedError,
    RunControlConflictError,
    RunNotRegisteredError,
    TaskNotReadyError,
    WebApiError,
)
from faultevolve.webapi.execution_backend import (
    LocalCloudExecutionBackend,
    ProcessHandle,
    RunLaunchSpec,
    SSHCloudExecutionBackend,
    close_log,
    poll_any,
    terminate_any,
)
from faultevolve.webapi.settings import PathNotAllowedError, WebSettings
from faultevolve.webapi.sanitization import sanitize

#: Filename of the effective configuration snapshot, inside the run directory.
EFFECTIVE_CONFIG_NAME = "evolve.effective.yaml"

#: Log filename inside ``<run_dir>/logs/``.
RUN_LOG_NAME = "run.log"

#: Logical artifact id the UI uses to address the captured log.
RUN_LOG_ARTIFACT_ID = "run_log"

#: How much of the captured log travels back on ``/live``. The log is advertised
#: as an artifact but is **not downloadable** (``kind="log"`` is in the replay
#: layer's non-downloadable set, because a child's stdout can quote host paths),
#: so this bounded, sanitized tail is the only way the UI can answer "why did my
#: run die?". 40 lines covers a traceback's head plus the CLI's own error line.
_LOG_TAIL_LINES = 40
_LOG_TAIL_CHARS = 4000

#: Process objects for runs started in this worker. Never sent anywhere: the
#: routes only read ``pid`` off the registry.
_live_handles: dict[str, ProcessHandle] = {}


# --------------------------------------------------------------------------
# guards
# --------------------------------------------------------------------------


def process_control_available(settings: WebSettings) -> bool:
    """Both the switch and the registry have to be present to launch."""
    return bool(settings.enable_process_control) and registry.registry_configured(
        settings
    )


def _require_control_enabled(settings: WebSettings) -> None:
    if not settings.enable_process_control:
        raise CapabilityNotSupportedError(
            "进程控制未启用（设置 FE_WEB_ENABLE_PROCESS_CONTROL=true 后重启）"
        )


def _require_registry(settings: WebSettings) -> None:
    if not registry.registry_configured(settings):
        raise CapabilityNotSupportedError(
            "未配置运行注册表（FE_WEB_RUN_REGISTRY）"
        )


# --------------------------------------------------------------------------
# process aliveness
# --------------------------------------------------------------------------


def _pid_alive(pid: int | None) -> bool | None:
    """Whether ``pid`` names a live process. ``None`` when unknowable.

    ``None`` rather than ``False`` matters: a remote handle has no local pid, and
    reporting a remote run as dead would be a claim the server cannot support.
    """
    if pid is None or pid <= 0:
        return None
    if os.name == "nt":
        # OpenProcess + GetExitCodeProcess: no tasklist round-trip, no psutil.
        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(
            process_query_limited_information, False, int(pid)
        )
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return None
            return code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Alive, just not ours to signal.
        return True
    except OSError:
        return None
    return True


def _summary_path(record: registry.RunRecord) -> Path | None:
    """This run's ``run_summary.json``, or ``None`` when there is none.

    **``record.artifacts_dir`` is a root, not the run's own directory.** The
    launch passes it as ``--artifacts-dir``, and the engine writes
    ``<artifacts_dir>/<exp_id>/run_summary.json`` -- ``cli.py`` says so in its
    own docstring and ``engine.py`` computes ``art_dir = artifacts_dir / exp_id``.
    Probing the root directly finds nothing, and every caller of this function
    would then reach a wrong conclusion: a finished run reported ``interrupted``
    after a restart, or a resume/append silently reading ``done = 0``.

    No fallback to the root itself: a stray ``run_summary.json`` directly under a
    shared artifacts root would otherwise be attributed to *every* run in it.
    """
    if not record.artifacts_dir:
        return None
    candidate = Path(record.artifacts_dir) / record.run_id / "run_summary.json"
    try:
        return candidate if candidate.is_file() else None
    except OSError:
        return None


def _summary_iterations(record: registry.RunRecord) -> int | None:
    """``iterations_done`` off the run summary, or ``None`` if unreadable."""
    path = _summary_path(record)
    if path is None:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("iterations_done")
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, int) else None


# --------------------------------------------------------------------------
# path + argv construction
# --------------------------------------------------------------------------


def _resolve_dir(settings: WebSettings, raw: str | Path | None, *, field: str) -> Path:
    """Resolve one configured directory and assert it is on the allow-list.

    Raises ``CapabilityNotSupportedError`` when nothing is configured at all
    (better than inventing a default the operator never chose) and lets
    ``PathNotAllowedError`` escape as a 403 when the path is out of bounds.
    """
    if raw is None or str(raw).strip() == "":
        raise CapabilityNotSupportedError(
            f"未配置 {field}：请在服务器配置中填写，或设置 "
            f"FE_WEB_{field.upper().replace('_DIR', '_ROOT')}"
        )
    try:
        return settings.ensure_allowed(Path(raw))
    except PathNotAllowedError:
        raise


def _launch_argv(
    *,
    task_dir: Path,
    runs_dir: Path,
    artifacts_dir: Path,
    config_path: Path | None,
    iterations: int | None,
    mock_llm: bool,
    seed: int | None,
    run_id: str | None,
    resume_id: str | None,
) -> list[str]:
    """Build the child argv. A list -- there is no code path to a shell.

    Every element is either a fixed literal or a value this server derived. No
    profile field and no free text from the request reaches this function, which
    is what makes command injection unrepresentable rather than filtered.
    """
    argv: list[str] = [
        sys.executable,
        "-m",
        "faultevolve.cli",
        "evolve",
        "local",
        str(task_dir),
        "--json",
        "--runs-dir",
        str(runs_dir),
        "--artifacts-dir",
        str(artifacts_dir),
    ]
    if iterations is not None:
        argv += ["--iterations", str(int(iterations))]
    if config_path is not None:
        argv += ["--config-file", str(config_path)]
    if mock_llm:
        argv.append("--mock")
    if seed is not None:
        argv += ["--seed", str(int(seed))]
    if resume_id is not None:
        argv += ["--resume", resume_id]
    elif run_id is not None:
        # Pre-assigned so the registry id and the run directory agree.
        argv += ["--run-id", run_id]
    return argv


def _backend_for(settings: WebSettings, record: dict[str, Any]):
    if record.get("mode") == "ssh_cloud":
        return SSHCloudExecutionBackend(settings, record)
    return LocalCloudExecutionBackend(settings)


def _iterations_from_config(config: dict[str, Any]) -> int | None:
    """Read ``budget.max_iterations`` off a resolved preset config.

    The ``--iterations`` flag is passed on the command line *and* wins over the
    config file, so it has to carry the same number the snapshot holds -- sending
    nothing would let the CLI default silently override the preset.
    """
    budget = config.get("budget")
    if isinstance(budget, dict):
        value = budget.get("max_iterations")
        if isinstance(value, int) and value > 0:
            return value
    return None


def _write_effective_config(run_dir: Path, config: dict[str, Any]) -> Path:
    """Persist the merged configuration so the run uses what the UI showed."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / EFFECTIVE_CONFIG_NAME
    path.write_text(
        yaml.safe_dump(
            config, allow_unicode=True, sort_keys=False, default_flow_style=False
        ),
        encoding="utf-8",
    )
    return path


# --------------------------------------------------------------------------
# registry helpers
# --------------------------------------------------------------------------


def _record_or_raise(settings: WebSettings, run_id: str) -> registry.RunRecord:
    record = registry.get_record(settings, run_id)
    if record is None:
        raise RunNotRegisteredError(run_id)
    return record


def _live_artifacts(record: registry.RunRecord) -> list[str]:
    """Logical names of files this run produced that the UI may address.

    Only names, never paths (PRD 22.2 rule 3), and only ones that actually
    exist -- a name with no file behind it would turn into a 404 in the UI.
    """
    names: list[str] = []
    if record.log_dir and (Path(record.log_dir) / RUN_LOG_NAME).is_file():
        names.append(RUN_LOG_ARTIFACT_ID)
    return names


def _log_tail(record: registry.RunRecord) -> tuple[str | None, bool]:
    """Sanitized tail of this run's captured log, and whether it was cut.

    Sanitization is the server's, not the browser's: the child's stdout can
    quote absolute host paths (it does -- the CLI prints its output JSON with
    full paths). Redacting here means the bound is a bound, not a hope.
    """
    if not record.log_dir:
        return None, False
    path = Path(record.log_dir) / RUN_LOG_NAME
    try:
        if not path.is_file():
            return None, False
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, False

    lines = text.splitlines()
    truncated = len(lines) > _LOG_TAIL_LINES
    tail = "\n".join(lines[-_LOG_TAIL_LINES:])
    if len(tail) > _LOG_TAIL_CHARS:
        tail = tail[-_LOG_TAIL_CHARS:]
        truncated = True
    cleaned = sanitize(tail)[0].strip()
    return (cleaned or None), truncated


# --------------------------------------------------------------------------
# start
# --------------------------------------------------------------------------


async def start_run(
    settings: WebSettings, request: RunCreateRequest
) -> RunCreateResponse:
    """TODO 7.3, steps 1-9. Returns the 202 body; the route supplies the status."""
    _require_control_enabled(settings)
    _require_registry(settings)

    # 2. resolve and validate paths -- by id, never by a client-supplied path.
    task_dir = task_service.resolve_task_dir(settings, request.task_id)
    profile = server_profiles.require_record(settings, request.server_profile_id)
    mode = str(profile.get("mode") or "local_cloud")

    # 3. build the effective config; this also re-validates the patch through
    #    EvolveConfig, so an invalid combination fails here and not mid-run.
    preset = presets_module.merge_patch(request.preset, request.config_patch)

    # 4. readiness before anything is spawned.
    readiness = task_service.task_readiness(settings, task_dir)
    if not readiness.ready:
        blockers = [check.reason for check in readiness.checks if check.reason]
        raise TaskNotReadyError("；".join(blockers) or None)

    # 5. id. Server-minted and validated by shape, so it is safe as a path
    #    segment and unique per launch (there is no client-supplied id to reuse).
    run_id = uuid.uuid4().hex[:12]

    runs_dir = _resolve_dir(
        settings,
        profile.get("runs_dir") or settings.runs_root,
        field="runs_dir",
    )
    artifacts_dir = _resolve_dir(
        settings,
        profile.get("artifacts_dir") or runs_dir,
        field="artifacts_dir",
    )

    run_dir = runs_dir / run_id
    log_dir = run_dir / "logs"
    log_path = log_dir / RUN_LOG_NAME
    config_path = _write_effective_config(run_dir, preset.config)

    # 6/7. pick the transport and start the process.
    argv = _launch_argv(
        task_dir=task_dir,
        runs_dir=runs_dir,
        artifacts_dir=artifacts_dir,
        config_path=config_path,
        iterations=_iterations_from_config(preset.config),
        mock_llm=request.mock_llm,
        seed=request.seed,
        run_id=run_id,
        resume_id=None,
    )
    backend = _backend_for(settings, profile)
    try:
        handle = await backend.start_run(
            RunLaunchSpec(argv=argv, log_path=str(log_path))
        )
    except WebApiError:
        raise
    except OSError as exc:
        raise WebApiError(
            message_zh="启动子进程失败",
            detail=type(exc).__name__,
        ) from None

    # 8. record the handle before replying. A started process the API cannot
    #    name afterwards would be an orphan.
    created_at = registry.now_iso()
    try:
        registry.insert_record(
            settings,
            registry.RunRecord(
                run_id=run_id,
                execution_backend=str(getattr(backend, "backend_name", mode)),
                server_profile_id=request.server_profile_id,
                pid=handle.pid,
                status=registry.STATUS_RUNNING,
                task_dir=str(task_dir),
                db_dir=str(run_dir),
                artifacts_dir=str(artifacts_dir),
                log_dir=str(log_dir),
                start_args=argv,
                created_at=created_at,
                detail="",
            ),
        )
    except Exception:
        # The row is what makes the process accountable; without it, stop the
        # process rather than leave it running untracked.
        try:
            await backend.terminate(handle)
        finally:
            close_log(handle)
        raise

    _live_handles[run_id] = handle

    # 9. 202 is set by the route.
    return RunCreateResponse(
        run_id=run_id,
        status=registry.STATUS_RUNNING,
        execution_backend=str(getattr(backend, "backend_name", mode)),
        task_id=request.task_id,
        created_at=created_at,
    )


# --------------------------------------------------------------------------
# control
# --------------------------------------------------------------------------


async def _stop_handle(handle: ProcessHandle) -> int | None:
    """Terminate and reap, so the log is flushed and no descriptor leaks."""
    await terminate_any(handle)
    exit_code: int | None = None
    for _ in range(50):  # up to ~5s
        status = await poll_any(handle)
        if not status.running:
            exit_code = status.exit_code
            break
        await asyncio.sleep(0.1)
    close_log(handle)
    return exit_code


async def cancel_run(settings: WebSettings, run_id: str) -> RunControlResponse:
    """Stop a run, keeping whatever it already produced (TODO test #13)."""
    _require_control_enabled(settings)
    _require_registry(settings)
    record = _record_or_raise(settings, run_id)

    if record.is_terminal:
        raise RunControlConflictError(
            f"该运行已处于终态（{record.status}），无需取消"
        )

    handle = _live_handles.pop(run_id, None)
    exit_code: int | None = None
    if handle is not None:
        exit_code = await _stop_handle(handle)
    elif _pid_alive(record.pid):
        # A process is alive under the recorded pid, but this service has no
        # handle to it and pids get reused. Killing a stranger's process would
        # be far worse than admitting the limit, so the row stays running and
        # the message says what to do.
        raise RunControlConflictError(
            "该进程由本服务的上一生命周期启动，无法安全确认其身份；"
            "请在目标机上手动终止后刷新状态"
        )

    registry.mark_finished(
        settings,
        run_id,
        status=registry.STATUS_CANCELLED,
        exit_code=exit_code,
        detail="已取消；已产生的制品保留",
    )
    return RunControlResponse(
        run_id=run_id,
        status=registry.STATUS_CANCELLED,
        action=ControlAction.CANCEL,
        applied=True,
        detail="已停止进程，已有制品保留",
    )


async def pause_run(settings: WebSettings, run_id: str) -> RunControlResponse:
    """Always refused. The engine has no safe point to pause at (TODO 7.4).

    A 409 with a reason is the honest answer; a 200 that did nothing would break
    PRD 22.1's "run state matches the backend" outright.
    """
    _require_control_enabled(settings)
    _require_registry(settings)
    _record_or_raise(settings, run_id)
    raise RunControlConflictError(
        "引擎不支持安全暂停（无安全点），本版本只提供取消与恢复"
    )


async def resume_run(settings: WebSettings, run_id: str) -> RunCreateResponse:
    """Restart a stopped run under the same id, continuing its experiment."""
    _require_control_enabled(settings)
    _require_registry(settings)
    record = _record_or_raise(settings, run_id)

    if record.status == registry.STATUS_RUNNING and _pid_alive(record.pid):
        raise RunControlConflictError("该运行正在进行，无需恢复")

    task_dir = _resolve_dir(settings, record.task_dir, field="task_dir")
    runs_dir = _resolve_dir(settings, Path(record.db_dir).parent, field="runs_dir")
    artifacts_dir = _resolve_dir(settings, record.artifacts_dir, field="artifacts_dir")

    # Reuse the snapshot the original launch used, so a resume cannot silently
    # pick up a config the user changed in the meantime. Falling back to None
    # (the task's own evolve.yaml) when there is no snapshot is the old
    # behaviour and is stated rather than guessed at.
    config_path = Path(record.db_dir) / EFFECTIVE_CONFIG_NAME
    if not config_path.is_file():
        config_path = None

    # Carry over how far the run got, so `--iterations` reproduces the same
    # budget instead of letting the CLI default silently take over.
    iterations = _summary_iterations(record)

    argv = _launch_argv(
        task_dir=task_dir,
        runs_dir=runs_dir,
        artifacts_dir=artifacts_dir,
        config_path=config_path,
        iterations=iterations,
        mock_llm=False,
        seed=None,
        run_id=None,
        resume_id=run_id,
    )
    backend = _backend_for(settings, {"mode": record.execution_backend})
    handle = await backend.start_run(
        RunLaunchSpec(argv=argv, log_path=str(Path(record.log_dir or runs_dir) / RUN_LOG_NAME))
    )

    registry.update_launch(
        settings,
        run_id,
        pid=handle.pid,
        status=registry.STATUS_RUNNING,
        execution_backend=str(getattr(backend, "backend_name", record.execution_backend)),
        detail="已恢复",
    )
    _live_handles[run_id] = handle

    # The id is unchanged: resume continues the same experiment, which is what
    # makes the run's history stay in one place.
    return RunCreateResponse(
        run_id=run_id,
        status=registry.STATUS_RUNNING,
        execution_backend=str(getattr(backend, "backend_name", record.execution_backend)),
        task_id=Path(record.task_dir).name,
        created_at=record.created_at,
        resumed_from=run_id,
        detail="已从已有运行恢复",
    )


async def append_rounds(
    settings: WebSettings, run_id: str, request: AppendRoundsRequest
) -> RunControlResponse:
    """Ask a finished run to evolve further (PRD §16.1).

    ``additional_iterations`` is a delta on top of what the run already did. The
    original ``run_summary.json`` is not rewritten -- "N rounds, then M more"
    stays auditable once the engine's own resume path appends to the same
    experiment.
    """
    _require_control_enabled(settings)
    _require_registry(settings)
    record = _record_or_raise(settings, run_id)

    if record.status == registry.STATUS_RUNNING and _pid_alive(record.pid):
        raise RunControlConflictError("该运行正在进行，无法追加轮次")

    # 0 when the summary is missing *or* unreadable: an append on an interrupted
    # run still has to move forward, and claiming a wrong baseline would make
    # "N rounds, then M more" unauditable.
    done = _summary_iterations(record) or 0

    task_dir = _resolve_dir(settings, record.task_dir, field="task_dir")
    runs_dir = _resolve_dir(settings, Path(record.db_dir).parent, field="runs_dir")
    artifacts_dir = _resolve_dir(settings, record.artifacts_dir, field="artifacts_dir")
    config_path = Path(record.db_dir) / EFFECTIVE_CONFIG_NAME
    if not config_path.is_file():
        config_path = None

    argv = _launch_argv(
        task_dir=task_dir,
        runs_dir=runs_dir,
        artifacts_dir=artifacts_dir,
        config_path=config_path,
        iterations=done + request.additional_iterations,
        mock_llm=False,
        seed=None,
        run_id=None,
        resume_id=run_id,
    )
    backend = _backend_for(settings, {"mode": record.execution_backend})
    handle = await backend.start_run(
        RunLaunchSpec(
            argv=argv, log_path=str(Path(record.log_dir or runs_dir) / RUN_LOG_NAME)
        )
    )
    registry.update_launch(
        settings,
        run_id,
        pid=handle.pid,
        status=registry.STATUS_RUNNING,
        detail=f"追加 {request.additional_iterations} 轮",
    )
    _live_handles[run_id] = handle
    return RunControlResponse(
        run_id=run_id,
        status=registry.STATUS_RUNNING,
        action=ControlAction.RESUME,
        applied=True,
        detail=f"已在原运行上追加 {request.additional_iterations} 轮",
    )


# --------------------------------------------------------------------------
# live view
# --------------------------------------------------------------------------


async def live_state(settings: WebSettings, run_id: str) -> RunLiveResponse:
    """Process-level view of a run.

    It needs no control flag -- it does not start or stop anything -- but it
    **does reconcile**: a row claiming ``running`` whose process is gone gets
    closed.

    Without that, a run that finishes while the service is up is reported as
    ``running`` forever (nothing else polls it), and a later ``cancel`` would
    relabel a *completed* run as ``cancelled``. Reconciling here also reaps the
    in-memory handle, which is what releases the child's log descriptor —
    otherwise one fd leaks per finished run until the service restarts.
    """
    _require_registry(settings)
    record = _record_or_raise(settings, run_id)

    alive: bool | None = None
    if record.status == registry.STATUS_RUNNING:
        exit_code: int | None = None
        # **本进程起的进程，只认自己的 handle。** 裸 pid 探测（`_pid_alive`）
        # 会比 asyncio 的 child watcher 早几毫秒看到"进程没了"：内核已经回收了
        # 进程对象，而 `Process.returncode` 还没被填上。那一瞬去收退出码收到的
        # 必然是 None，而 `mark_finished` 会把它**永久**写进注册表 —— 之后再没有
        # 任何机会补回来（这正是 tests 里那条 exit_code 断言时红时绿的原因，
        # 不是测试不稳定，是退出码真的丢了）。
        #
        # pid 探测只留给"没有 handle"的行：上一生命周期启动的运行，我们手里
        # 没有它的 asyncio Process 对象，只能问系统；那种情况下退出码诚实地
        # 保持 None（系统也不一定肯给）。
        handle = _live_handles.get(run_id)
        if handle is not None:
            polled = await poll_any(handle)
            alive = polled.running
            if not polled.running:
                _live_handles.pop(run_id, None)
                exit_code = polled.exit_code
        else:
            alive = _pid_alive(record.pid)

        if alive is not True:
            status = (
                registry.STATUS_COMPLETED
                if _summary_path(record) is not None
                else registry.STATUS_INTERRUPTED
            )
            registry.mark_finished(
                settings,
                run_id,
                status=status,
                exit_code=exit_code,
                detail=(
                    "进程已退出且已产出运行摘要"
                    if status == registry.STATUS_COMPLETED
                    else "进程已消失且未产出运行摘要"
                ),
            )
            record = _record_or_raise(settings, run_id)
            alive = False

    tail, tail_truncated = _log_tail(record)

    return RunLiveResponse(
        contract_version=_contract_version(),
        run_id=record.run_id,
        registered=True,
        status=record.status,
        execution_backend=record.execution_backend,
        server_profile_id=record.server_profile_id,
        pid=record.pid,
        process_alive=alive,
        created_at=record.created_at,
        finished_at=record.finished_at,
        exit_code=record.exit_code,
        resumed_from=record.resumed_from,
        detail=record.detail,
        log_artifacts=_live_artifacts(record),
        log_tail=tail,
        log_tail_truncated=tail_truncated,
    )


def _contract_version() -> str:
    from faultevolve.webapi.contracts import CONTRACT_VERSION

    return CONTRACT_VERSION


# --------------------------------------------------------------------------
# recovery (TODO 7.5)
# --------------------------------------------------------------------------


def recover_on_startup(settings: WebSettings) -> list[str]:
    """Reconcile the registry with reality after a restart.

    Runs that are still alive keep their ``running`` status -- monitoring is the
    live endpoint's job, this pass only fixes what is provably wrong. A row
    whose process is gone is closed: ``completed`` when the engine left a
    ``run_summary.json``, ``interrupted`` otherwise. Trusting the recorded
    status alone would be how a finished run gets mislabelled.
    """
    if not registry.registry_configured(settings):
        return []

    reconciled: list[str] = []
    for record in registry.running_records(settings):
        if _pid_alive(record.pid):
            continue
        status = (
            registry.STATUS_COMPLETED
            if _summary_path(record) is not None
            else registry.STATUS_INTERRUPTED
        )
        registry.mark_finished(
            settings,
            record.run_id,
            status=status,
            detail=(
                "服务重启后核对：已产出运行摘要"
                if status == registry.STATUS_COMPLETED
                else "服务重启后核对：进程已消失且未产出运行摘要"
            ),
        )
        reconciled.append(record.run_id)
    return reconciled


__all__ = [
    "EFFECTIVE_CONFIG_NAME",
    "RUN_LOG_ARTIFACT_ID",
    "RUN_LOG_NAME",
    "append_rounds",
    "cancel_run",
    "live_state",
    "pause_run",
    "process_control_available",
    "recover_on_startup",
    "resume_run",
    "start_run",
]
