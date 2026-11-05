"""Run lifecycle (TODO 7.1-7.5): start, cancel, pause, live, recover, append.

What is real here and what is stubbed, stated plainly:

* **Real**: ``WebSettings``, the task catalogue, the readiness gate, the run
  registry, path allow-listing, and the process actually spawned. A launch that
  passes these tests passes the same gates production does.
* **Stubbed**: only the child argv (see ``_SLEEP_ARGV``). Running the engine
  would make these tests slow and would test the engine, not the lifecycle;
  phase 7's end-to-end smoke does that separately with ``--mock``.

The security assertions are the point of several tests below: no secret may
reach the registry, and no request value may reach a command line.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from faultevolve.webapi import run_control, run_registry, server_profiles  # noqa: E402
from faultevolve.webapi.app import create_app  # noqa: E402
from faultevolve.webapi.contracts import (  # noqa: E402
    AppendRoundsRequest,
    RunCreateRequest,
    ServerProfileRequest,
)
from faultevolve.webapi.errors import (  # noqa: E402
    CapabilityNotSupportedError,
    RunControlConflictError,
    RunNotRegisteredError,
    TaskNotReadyError,
)
from faultevolve.webapi.sanitization import REDACTED_PATH  # noqa: E402
from faultevolve.webapi.settings import WebSettings  # noqa: E402

#: A child that stays alive, so cancel/live have something real to act on.
_SLEEP_ARGV = [
    sys.executable,
    "-c",
    "import time; print('child-alive', flush=True); time.sleep(60)",
]

#: Files the hdd adapter's readiness check insists on, under <root>/public.
_REQUIRED_DATA = (
    "train_history.csv.gz",
    "train_labels.csv",
    "val_history.csv.gz",
    "val_index.csv",
)


def _kill_children() -> None:
    """Reap every child this module started. Called from the fixture teardown."""
    for handle in list(run_control._live_handles.values()):
        process = getattr(handle, "payload", None)
        try:
            if process is not None and getattr(process, "returncode", None) is None:
                process.kill()
        except Exception:  # pragma: no cover - best effort cleanup
            pass
    run_control._live_handles.clear()


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Real settings/task/readiness; only the child argv is replaced."""
    task_root = tmp_path / "tasks"
    task = task_root / "demo"
    task.mkdir(parents=True)
    (task / "init.py").write_text("# init", encoding="utf-8")
    (task / "problem.md").write_text("# p", encoding="utf-8")
    (task / "prompt.md").write_text("# p", encoding="utf-8")
    (task / "evaluator.py").write_text(
        "def evaluate(p, **kw):\n"
        "    return {'validity': 1, 'combined_score': 22, 'cost_time': 1,"
        " 'error_info': '', 'metric': {}}\n",
        encoding="utf-8",
    )
    (task / "evolve.yaml").write_text("task:\n  adapter: hdd\n", encoding="utf-8")

    public = tmp_path / "data" / "public"
    public.mkdir(parents=True)
    for name in _REQUIRED_DATA:
        (public / name).write_bytes(b"")
    monkeypatch.setenv("HDD_BENCH_DATA_ROOT", str(tmp_path / "data"))

    runs = tmp_path / "runs"
    runs.mkdir()
    settings = WebSettings(
        task_roots=[task_root],
        runs_root=runs,
        allowed_path_roots=[tmp_path],
        server_profile_store=tmp_path / "servers.json",
        run_registry=tmp_path / "web_runs.sqlite3",
        enable_process_control=True,
    )
    profile = server_profiles.upsert_profile(
        settings,
        ServerProfileRequest(
            display_name="本机", mode="local_cloud", runs_dir=str(runs)
        ),
        None,
    )

    real_launch_argv = run_control._launch_argv
    monkeypatch.setattr(run_control, "_launch_argv", lambda **kwargs: list(_SLEEP_ARGV))

    env = SimpleNamespace(
        settings=settings,
        task_id="demo",
        runs=runs,
        profile_id=profile.profile_id,
        tmp_path=tmp_path,
        real_launch_argv=real_launch_argv,
    )
    yield env
    _kill_children()


def _request(env: SimpleNamespace, **overrides: object) -> RunCreateRequest:
    payload: dict[str, object] = {
        "task_id": env.task_id,
        "server_profile_id": env.profile_id,
        "preset": "quick",
        "mock_llm": True,
    }
    payload.update(overrides)
    return RunCreateRequest(**payload)


# --------------------------------------------------------------------------
# start (TODO 7.3)
# --------------------------------------------------------------------------


async def test_start_records_the_run_and_writes_the_config_snapshot(
    env: SimpleNamespace,
) -> None:
    response = await run_control.start_run(env.settings, _request(env))

    assert response.status == run_registry.STATUS_RUNNING
    assert response.execution_backend == "local_cloud"
    assert response.task_id == "demo"

    record = run_registry.get_record(env.settings, response.run_id)
    assert record is not None
    assert record.pid is not None and record.pid > 0
    assert record.status == run_registry.STATUS_RUNNING

    # The snapshot is what makes the run execute the configuration the UI
    # showed -- without it the preset would be cosmetic.
    run_dir = Path(record.db_dir)
    assert (run_dir / run_control.EFFECTIVE_CONFIG_NAME).is_file()
    # And the log redirect really is open on a file under logs/.
    assert Path(record.log_dir) == run_dir / "logs"
    assert (Path(record.log_dir) / run_control.RUN_LOG_NAME).is_file()


async def test_two_launches_get_distinct_ids_and_rows(env: SimpleNamespace) -> None:
    """No client-supplied id exists, so a re-submit is a new run, never a re-use."""
    first = await run_control.start_run(env.settings, _request(env))
    second = await run_control.start_run(env.settings, _request(env))

    assert first.run_id != second.run_id
    assert len(run_registry.list_records(env.settings)) == 2


async def test_registry_never_records_a_secret(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TODO 7.2: the stored start command carries no key material."""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-supersecret-value")

    response = await run_control.start_run(env.settings, _request(env))
    record = run_registry.get_record(env.settings, response.run_id)
    blob = json.dumps(run_registry.as_dict(record), ensure_ascii=False)

    assert "sk-supersecret-value" not in blob
    assert "DASHSCOPE" not in blob


async def test_start_refuses_when_the_switch_is_off(env: SimpleNamespace) -> None:
    settings = env.settings.model_copy(update={"enable_process_control": False})
    with pytest.raises(CapabilityNotSupportedError):
        await run_control.start_run(settings, _request(env))
    assert run_registry.list_records(env.settings) == []


async def test_start_refuses_when_no_registry_is_configured(
    env: SimpleNamespace,
) -> None:
    """Without a registry a started process cannot be accounted for."""
    settings = env.settings.model_copy(update={"run_registry": None})
    with pytest.raises(CapabilityNotSupportedError):
        await run_control.start_run(settings, _request(env))


async def test_start_refuses_a_task_that_is_not_ready(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The readiness gate really runs: pulling the data out must block the launch.

    Delete the data root rather than stubbing the check, so this asserts the
    gate itself and not a mock of it.
    """
    monkeypatch.delenv("HDD_BENCH_DATA_ROOT", raising=False)
    (env.tmp_path / "data" / "public" / "train_labels.csv").unlink()

    with pytest.raises(TaskNotReadyError):
        await run_control.start_run(env.settings, _request(env))
    assert run_registry.list_records(env.settings) == []


async def test_start_refuses_a_runs_dir_outside_the_allow_list(
    env: SimpleNamespace, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """A profile pointing outside the roots is a 403, not a silent escape."""
    from faultevolve.webapi.settings import PathNotAllowedError

    outside = tmp_path_factory.mktemp("outside")
    profile = server_profiles.upsert_profile(
        env.settings,
        ServerProfileRequest(
            display_name="外部", mode="local_cloud", runs_dir=str(outside)
        ),
        None,
    )
    with pytest.raises(PathNotAllowedError):
        await run_control.start_run(
            env.settings, _request(env, server_profile_id=profile.profile_id)
        )


async def test_injection_shaped_ids_never_reach_the_command_line(
    env: SimpleNamespace,
) -> None:
    """A task id is an identifier, not a path: separators cannot be represented."""
    for bad in ("demo; rm -rf /", "../../etc", "demo|cat /etc/passwd"):
        with pytest.raises(Exception):
            await run_control.start_run(env.settings, _request(env, task_id=bad))
    assert run_registry.list_records(env.settings) == []


def test_launch_argv_is_a_list_of_literals(env: SimpleNamespace) -> None:
    """The real builder: argv items, no shell, no profile free text."""
    argv = env.real_launch_argv(
        task_dir=env.tmp_path / "tasks" / "demo",
        runs_dir=env.runs,
        artifacts_dir=env.runs,
        config_path=env.tmp_path / "cfg.yaml",
        iterations=5,
        mock_llm=True,
        seed=7,
        run_id="web0001",
        resume_id=None,
    )

    assert argv[:3] == [sys.executable, "-m", "faultevolve.cli"]
    assert argv[3:5] == ["evolve", "local"]
    assert "--run-id" in argv and "web0001" in argv
    assert "--resume" not in argv
    assert "--mock" in argv
    # One element per argument: nothing was concatenated into a command string.
    assert all(isinstance(part, str) and "\n" not in part for part in argv)


# --------------------------------------------------------------------------
# cancel / pause / live
# --------------------------------------------------------------------------


async def test_cancel_stops_the_process_and_keeps_artifacts(
    env: SimpleNamespace,
) -> None:
    """TODO test #13: cancelling never deletes what the run already produced."""
    response = await run_control.start_run(env.settings, _request(env))
    record = run_registry.get_record(env.settings, response.run_id)
    marker = Path(record.db_dir) / "tree.json"
    marker.write_text("{}", encoding="utf-8")

    result = await run_control.cancel_run(env.settings, response.run_id)

    assert result.applied is True
    assert result.status == run_registry.STATUS_CANCELLED
    assert marker.is_file(), "取消不得删除已有制品"
    assert (
        run_registry.get_record(env.settings, response.run_id).status
        == run_registry.STATUS_CANCELLED
    )


async def test_cancel_is_refused_once_the_run_is_terminal(
    env: SimpleNamespace,
) -> None:
    response = await run_control.start_run(env.settings, _request(env))
    await run_control.cancel_run(env.settings, response.run_id)
    with pytest.raises(RunControlConflictError):
        await run_control.cancel_run(env.settings, response.run_id)


async def test_pause_always_conflicts_with_a_reason(env: SimpleNamespace) -> None:
    """TODO 7.4: no safe point exists, so 409 with an explanation -- not a 200."""
    response = await run_control.start_run(env.settings, _request(env))
    with pytest.raises(RunControlConflictError) as excinfo:
        await run_control.pause_run(env.settings, response.run_id)

    assert excinfo.value.http_status == 409
    assert excinfo.value.error_code.value == "not_supported"
    # Still running: the refusal did not quietly stop anything.
    assert (
        run_registry.get_record(env.settings, response.run_id).status
        == run_registry.STATUS_RUNNING
    )


async def test_live_reports_the_real_process_state(env: SimpleNamespace) -> None:
    response = await run_control.start_run(env.settings, _request(env))
    live = await run_control.live_state(env.settings, response.run_id)

    assert live.registered is True
    assert live.process_alive is True
    assert live.pid == run_registry.get_record(env.settings, response.run_id).pid
    assert run_control.RUN_LOG_ARTIFACT_ID in live.log_artifacts


async def test_live_is_404_for_a_run_this_service_never_started(
    env: SimpleNamespace,
) -> None:
    with pytest.raises(RunNotRegisteredError) as excinfo:
        await run_control.live_state(env.settings, "deadbeef")
    assert excinfo.value.http_status == 404


# --------------------------------------------------------------------------
# live reconciliation (TODO 7.5, the in-service half)
# --------------------------------------------------------------------------
#
# Found by the end-to-end smoke, not by these tests: a run that finished while
# the service was up stayed `running` in the registry forever, because nothing
# polled it. Every reading of /live returned a stale status, and a later cancel
# reaped the stale handle and relabelled a *completed* run as `cancelled`.


async def _await_not_alive(env: SimpleNamespace, run_id: str, *, tries: int = 200):
    """Poll /live until the child is gone. Returns the reconciled view."""
    live = None
    for _ in range(tries):
        live = await run_control.live_state(env.settings, run_id)
        if live.process_alive is False:
            return live
        await asyncio.sleep(0.05)
    raise AssertionError(f"child never exited: {live}")


async def test_live_closes_a_row_whose_process_vanished(env: SimpleNamespace) -> None:
    _seed_running_row(env, "gone0001", 999_999)

    live = await run_control.live_state(env.settings, "gone0001")

    assert live.status == run_registry.STATUS_INTERRUPTED
    assert live.process_alive is False
    assert live.finished_at is not None


async def test_live_calls_a_vanished_row_completed_when_a_summary_exists(
    env: SimpleNamespace,
) -> None:
    _seed_running_row(env, "gone0002", 999_999, with_summary=True)

    live = await run_control.live_state(env.settings, "gone0002")

    assert live.status == run_registry.STATUS_COMPLETED
    assert live.process_alive is False


async def test_live_reaps_the_handle_and_harvests_the_exit_code(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not reaping leaks the child's log descriptor until the service restarts."""
    monkeypatch.setattr(
        run_control,
        "_launch_argv",
        lambda **kwargs: [sys.executable, "-c", "raise SystemExit(3)"],
    )
    created = await run_control.start_run(env.settings, _request(env))
    assert created.run_id in run_control._live_handles

    live = await _await_not_alive(env, created.run_id)

    assert live.exit_code == 3
    assert created.run_id not in run_control._live_handles


async def test_live_never_harvests_an_exit_code_from_a_bare_pid_probe(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The kernel sees the process die before asyncio fills in ``returncode``.

    ``_pid_alive`` answers "gone" a few ms before ``asyncio``'s child watcher
    records the status, so harvesting the exit code at that instant stores
    ``NULL`` **forever** -- nothing ever fills it back in. Forced here rather
    than waited for: the window is a few ms wide, so a test that hopes to hit it
    is a test that reports "flaky" instead of reporting the bug.
    """
    monkeypatch.setattr(
        run_control,
        "_launch_argv",
        lambda **kwargs: [sys.executable, "-c", "import time; time.sleep(0.4)"],
    )
    # The race, stated as a fact: the pid probe is already certain.
    monkeypatch.setattr(run_control, "_pid_alive", lambda pid: False)

    created = await run_control.start_run(env.settings, _request(env))

    early = await run_control.live_state(env.settings, created.run_id)
    # Still ours to reap => still running, exit code not yet knowable.
    assert early.status == run_registry.STATUS_RUNNING
    assert early.exit_code is None
    assert early.process_alive is True
    assert created.run_id in run_control._live_handles

    live = await _await_not_alive(env, created.run_id)

    # Now the handle has the real answer, and it is the one that gets stored.
    assert live.exit_code == 0
    assert created.run_id not in run_control._live_handles


async def test_cancel_cannot_relabel_a_run_that_already_finished(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stale-handle regression, stated as one assertion: status stays `completed`."""
    summary_code = (
        "import pathlib,sys;"
        "p=pathlib.Path(sys.argv[1]);p.mkdir(parents=True,exist_ok=True);"
        "(p/'run_summary.json').write_text('{}')"
    )
    monkeypatch.setattr(
        run_control,
        "_launch_argv",
        lambda **kwargs: [
            sys.executable,
            "-c",
            summary_code,
            str(Path(kwargs["artifacts_dir"]) / kwargs["run_id"]),
        ],
    )
    created = await run_control.start_run(env.settings, _request(env))

    live = await _await_not_alive(env, created.run_id)
    assert live.status == run_registry.STATUS_COMPLETED

    with pytest.raises(RunControlConflictError):
        await run_control.cancel_run(env.settings, created.run_id)
    assert (
        run_registry.get_record(env.settings, created.run_id).status
        == run_registry.STATUS_COMPLETED
    )


async def test_append_rounds_counts_from_the_run_summary(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`done` must come from `<artifacts_dir>/<run_id>/`, not the shared root.

    Read off the root, `done` was always 0 and an append silently asked for the
    wrong total instead of `already_done + delta`.
    """
    captured: dict[str, object] = {}

    def _argv(**kwargs):
        captured.update(kwargs)
        return [sys.executable, "-c", "import time; time.sleep(60)"]

    monkeypatch.setattr(run_control, "_launch_argv", _argv)
    created = await run_control.start_run(env.settings, _request(env))
    run_artifacts = env.runs / created.run_id
    run_artifacts.mkdir(parents=True, exist_ok=True)
    (run_artifacts / "run_summary.json").write_text(
        json.dumps({"iterations_done": 7}), encoding="utf-8"
    )

    # The run is still alive, so stop it first: appending a running run is a 409.
    await run_control.cancel_run(env.settings, created.run_id)
    captured.clear()

    await run_control.append_rounds(
        env.settings, created.run_id, AppendRoundsRequest(additional_iterations=5)
    )

    assert captured["iterations"] == 12


# --------------------------------------------------------------------------
# log tail (the only reachable diagnosis)
# --------------------------------------------------------------------------
#
# The run log is listed as an artifact but ``kind="log"`` is in the replay
# layer's non-downloadable set, so the UI cannot fetch it. Without a tail on
# /live, a process that dies in 200 ms is a dead end: the workbench page shows
# "no artifacts" and the reason (the CLI's own error line) is unreachable.


async def test_live_returns_a_sanitized_log_tail(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    child = (
        "import sys;"
        "print('Error: DASHSCOPE_API_KEY not set. Use --mock');"
        "print(r'run dir: C:\\\\Users\\\\someone\\\\secret\\\\runs');"
        "sys.stdout.flush()"
    )
    monkeypatch.setattr(
        run_control,
        "_launch_argv",
        lambda **kwargs: [sys.executable, "-c", child],
    )
    created = await run_control.start_run(env.settings, _request(env))

    live = await _await_not_alive(env, created.run_id)

    assert live.log_tail is not None
    assert "DASHSCOPE_API_KEY not set" in live.log_tail
    # The host path the child printed must not survive into the response.
    # Assert against the constant, not a literal: the marker is the server's.
    assert "someone" not in live.log_tail
    assert REDACTED_PATH in live.log_tail
    assert live.log_tail_truncated is False


async def test_live_marks_a_truncated_log_tail(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    child = "[print(f'line {i}') for i in range(120)]"
    monkeypatch.setattr(
        run_control,
        "_launch_argv",
        lambda **kwargs: [sys.executable, "-c", child],
    )
    created = await run_control.start_run(env.settings, _request(env))

    live = await _await_not_alive(env, created.run_id)

    assert live.log_tail is not None
    assert live.log_tail_truncated is True
    # 40 lines are kept, and they are the *last* ones.
    assert live.log_tail.count("\n") + 1 == run_control._LOG_TAIL_LINES
    assert live.log_tail.rstrip().endswith("line 119")


def test_log_tail_is_none_without_a_log_dir(env: SimpleNamespace) -> None:
    record = run_registry.RunRecord(
        run_id="nologs01",
        execution_backend="local_cloud",
        server_profile_id=None,
        pid=None,
        status=run_registry.STATUS_COMPLETED,
        task_dir=str(env.tmp_path),
        db_dir=str(env.runs / "nologs01"),
        artifacts_dir=str(env.runs),
        log_dir=None,
        start_args=[],
        created_at=run_registry.now_iso(),
    )
    assert run_control._log_tail(record) == (None, False)


# --------------------------------------------------------------------------
# recovery (TODO 7.5)
# --------------------------------------------------------------------------


def _seed_running_row(
    env: SimpleNamespace, run_id: str, pid: int | None, *, with_summary: bool = False
) -> str:
    """Insert a `running` row directly, and optionally a completion summary.

    ``artifacts_dir`` is the shared **root** here, exactly as ``start_run``
    records it (it is passed to the child as ``--artifacts-dir``), and the
    summary goes to ``<root>/<run_id>/`` -- which is where the engine writes it
    (``engine.py``: ``art_dir = artifacts_dir / exp_id``). Seeding it at the
    root instead is what let a real bug hide: recovery then read the root, found
    nothing, and called every finished run ``interrupted``.
    """
    artifacts = env.tmp_path / f"artifacts_{run_id}"
    artifacts.mkdir(parents=True, exist_ok=True)
    if with_summary:
        run_artifacts = artifacts / run_id
        run_artifacts.mkdir(parents=True, exist_ok=True)
        (run_artifacts / "run_summary.json").write_text(
            json.dumps({"iterations_done": 7}), encoding="utf-8"
        )
    run_registry.insert_record(
        env.settings,
        run_registry.RunRecord(
            run_id=run_id,
            execution_backend="local_cloud",
            server_profile_id=None,
            pid=pid,
            status=run_registry.STATUS_RUNNING,
            task_dir=str(env.tmp_path),
            db_dir=str(env.runs / run_id),
            artifacts_dir=str(artifacts),
            log_dir=None,
            start_args=[],
            created_at=run_registry.now_iso(),
        ),
    )
    return str(artifacts)


def test_recover_marks_a_vanished_process_interrupted(env: SimpleNamespace) -> None:
    _seed_running_row(env, "dead0001", 999_999)

    reconciled = run_control.recover_on_startup(env.settings)

    assert "dead0001" in reconciled
    assert (
        run_registry.get_record(env.settings, "dead0001").status
        == run_registry.STATUS_INTERRUPTED
    )


def test_recover_calls_a_vanished_process_completed_when_a_summary_exists(
    env: SimpleNamespace,
) -> None:
    """The registry status is not trusted over the engine's own artifacts."""
    _seed_running_row(env, "done0001", 999_999, with_summary=True)

    run_control.recover_on_startup(env.settings)

    assert (
        run_registry.get_record(env.settings, "done0001").status
        == run_registry.STATUS_COMPLETED
    )


def test_recover_leaves_a_live_process_alone(env: SimpleNamespace) -> None:
    """Monitoring a live run is the live endpoint's job, not recovery's."""
    _seed_running_row(env, "live0001", os.getpid())

    reconciled = run_control.recover_on_startup(env.settings)

    assert "live0001" not in reconciled
    assert (
        run_registry.get_record(env.settings, "live0001").status
        == run_registry.STATUS_RUNNING
    )


def test_recover_is_a_noop_without_a_registry(env: SimpleNamespace) -> None:
    assert run_control.recover_on_startup(WebSettings()) == []


# --------------------------------------------------------------------------
# HTTP surface
# --------------------------------------------------------------------------


def test_http_launch_live_pause_cancel_round_trip(env: SimpleNamespace) -> None:
    client = TestClient(create_app(env.settings))

    created = client.post(
        "/api/runs",
        json={
            "task_id": env.task_id,
            "server_profile_id": env.profile_id,
            "preset": "quick",
            "mock_llm": True,
        },
    )
    assert created.status_code == 202
    run_id = created.json()["run_id"]

    live = client.get(f"/api/runs/{run_id}/live")
    assert live.status_code == 200
    assert live.json()["registered"] is True
    assert live.json()["process_alive"] is True

    paused = client.post(f"/api/runs/{run_id}/pause")
    assert paused.status_code == 409
    assert paused.json()["error_code"] == "not_supported"

    cancelled = client.post(f"/api/runs/{run_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["applied"] is True


def test_http_live_unknown_run_is_a_localised_404(env: SimpleNamespace) -> None:
    client = TestClient(create_app(env.settings))
    response = client.get("/api/runs/deadbeef/live")
    assert response.status_code == 404
    assert response.json()["error_code"] == "run.not_found"


def test_http_rounds_rejects_a_non_positive_delta(env: SimpleNamespace) -> None:
    """``additional_iterations`` is a delta: zero means "do nothing", so refuse."""
    client = TestClient(create_app(env.settings))
    response = client.post("/api/runs/whatever/rounds", json={"additional_iterations": 0})
    assert response.status_code == 422


def test_http_write_endpoints_are_inert_without_the_switch() -> None:
    """Default deployment: every write endpoint says so instead of acting."""
    client = TestClient(create_app(), raise_server_exceptions=False)

    cases = [
        ("/api/runs", {"task_id": "t", "server_profile_id": "p", "preset": "quick"}),
        ("/api/runs/x/cancel", None),
        ("/api/runs/x/pause", None),
        ("/api/runs/x/resume", None),
        ("/api/runs/x/rounds", {"additional_iterations": 3}),
    ]
    for path, payload in cases:
        response = client.post(path, json=payload) if payload else client.post(path)
        assert response.status_code == 501, path
        assert response.json()["error_code"] == "not_supported", path
