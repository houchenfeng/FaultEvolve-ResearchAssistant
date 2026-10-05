"""FaultEvolve CLI entry point.

Commands:
    fe evolve local <task_dir> [--mock] [--iterations N] [--resume ID]
    fe doctor
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer


def load_env_file(env_file: Path, warn_missing: bool = True) -> None:
    """Load environment variables from a .env file.

    Supports formats: KEY=VAL, export KEY=VAL, KEY="VAL", KEY='VAL', and # comments.
    Does not override already-set environment variables.

    Args:
        env_file: Path to the .env file
        warn_missing: If True, print a warning when file doesn't exist
    """
    if not env_file.exists():
        if warn_missing:
            typer.echo(
                typer.style(
                    f"Warning: --env-file path does not exist: {env_file}",
                    fg=typer.colors.YELLOW,
                ),
                err=True,
            )
        return

    with env_file.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value


def get_runs_dir(
    cli_runs_dir: Path | None,
    task_dir: Path,
) -> Path:
    """Determine runs directory: CLI > env > default.

    Args:
        cli_runs_dir: Value from --runs-dir flag
        task_dir: Task directory for default path

    Returns:
        Path to runs directory
    """
    if cli_runs_dir:
        return cli_runs_dir.resolve()
    env_dir = os.environ.get("FE_RUNS_DIR")
    if env_dir:
        return Path(env_dir).resolve()
    return task_dir / ".fe" / "runs"


def get_artifacts_dir(
    cli_artifacts_dir: Path | None,
    runs_dir: Path,
    exp_id: str,
) -> Path:
    """Determine artifacts directory: CLI > env > same as runs.

    Args:
        cli_artifacts_dir: Value from --artifacts-dir flag
        runs_dir: Runs directory as fallback
        exp_id: Experiment ID

    Returns:
        Path to artifacts directory for this experiment
    """
    if cli_artifacts_dir:
        return cli_artifacts_dir.resolve() / exp_id
    env_dir = os.environ.get("FE_ARTIFACTS_DIR")
    if env_dir:
        return Path(env_dir).resolve() / exp_id
    return runs_dir / exp_id


def get_base_artifacts_dir(
    cli_artifacts_dir: Path | None,
    runs_dir: Path,
) -> Path | None:
    """Determine base artifacts directory (without exp_id): CLI > env > None.

    Args:
        cli_artifacts_dir: Value from --artifacts-dir flag
        runs_dir: Runs directory as fallback (used to detect if should use default)

    Returns:
        Base path for artifacts directory, or None to use runs_dir default
    """
    if cli_artifacts_dir:
        return cli_artifacts_dir.resolve()
    env_dir = os.environ.get("FE_ARTIFACTS_DIR")
    if env_dir:
        return Path(env_dir).resolve()
    return None


NETWORK_FS_TYPES = {"cifs", "smb3", "smbfs", "nfs", "nfs4", "fuse.sshfs"}


def detect_network_fs(path: Path) -> tuple[bool, str]:
    """Detect if a path is on a network filesystem by parsing /proc/mounts.

    Args:
        path: Path to check

    Returns:
        Tuple of (is_network_fs, fs_type). fs_type is empty if not network.
    """
    try:
        resolved = path.resolve()
    except Exception:
        return False, ""

    proc_mounts = Path("/proc/mounts")
    if not proc_mounts.exists():
        return False, ""

    try:
        mounts_text = proc_mounts.read_text(encoding="utf-8")
    except Exception:
        return False, ""

    best_match = ""
    best_fs_type = ""

    for line in mounts_text.strip().split("\n"):
        parts = line.split()
        if len(parts) < 3:
            continue
        mount_point = parts[1]
        fs_type = parts[2]

        try:
            mp = Path(mount_point)
            if resolved == mp or mp in resolved.parents:
                if len(mount_point) > len(best_match):
                    best_match = mount_point
                    best_fs_type = fs_type
        except Exception:
            continue

    if best_fs_type.lower() in NETWORK_FS_TYPES:
        return True, best_fs_type

    return False, ""


def check_db_path_network_fs(db_path: Path) -> None:
    """Check if the database path is on a network filesystem and fail fast.

    Raises:
        typer.Exit: If db_path is on a network filesystem
    """
    is_network, fs_type = detect_network_fs(db_path.parent)
    if is_network:
        typer.echo(
            typer.style(
                f"Error: Database path is on network filesystem ({fs_type}): {db_path.parent}\n"
                f"SQLite cannot reliably lock files on network filesystems.\n"
                f"Solution: Set FE_RUNS_DIR to a local directory or use --runs-dir flag.",
                fg=typer.colors.RED,
            ),
            err=True,
        )
        raise typer.Exit(1)

app = typer.Typer(
    name="fe",
    help="FaultEvolve: LLM-agent system for evolving device failure-prediction algorithms",
    no_args_is_help=True,
)

evolve_app = typer.Typer(help="Evolution commands")
app.add_typer(evolve_app, name="evolve")
judge_app = typer.Typer(help="Jev judge commands")
app.add_typer(judge_app, name="judge")
discover_app = typer.Typer(help="Knowledge discovery commands")
app.add_typer(discover_app, name="discover")
data_app = typer.Typer(help="Dataset checkup commands")
app.add_typer(data_app, name="data")
web_app = typer.Typer(help="Web API commands")
app.add_typer(web_app, name="web")


@web_app.command("serve")
def web_serve(
    host: str = typer.Option("127.0.0.1", help="Bind address"),
    port: int = typer.Option(8000, help="Bind port"),
    reload: bool = typer.Option(False, help="Auto-reload (dev only)"),
) -> None:
    """Serve the FaultEvolve Web API.

    Configuration comes from FE_WEB_* environment variables -- the same
    ``WebSettings`` the tests inject, read here at start-up rather than at
    import time.

    Before uvicorn binds, the run registry is reconciled with reality
    (``run_control.recover_on_startup``): a row recorded as live whose process
    is gone must not be reported as running to the first request. Note that
    ``--reload`` restarts this process, so the pass runs again on each reload.
    """
    from faultevolve.webapi.app import create_app
    from faultevolve.webapi.run_control import recover_on_startup
    from faultevolve.webapi.settings import WebSettings

    settings = WebSettings()

    try:
        reconciled = recover_on_startup(settings)
    except Exception as exc:  # pragma: no cover - deployment dependent
        # Recovery failing must not stop the API from serving: the replay side
        # is still fully usable, and the registry is the only thing stale.
        reconciled = []
        typer.echo(
            f"Warning: run registry recovery failed ({type(exc).__name__}); "
            "continuing with the registry unverified.",
            err=True,
        )

    typer.echo(
        typer.style(
            "FaultEvolve Web API "
            f"(task_roots={len(settings.task_roots)}, "
            f"server_profiles={'on' if settings.server_profile_store else 'off'}, "
            f"run_registry={'on' if settings.run_registry else 'off'}, "
            f"process_control={'on' if settings.enable_process_control else 'off'}"
            + (f", reconciled={','.join(reconciled)}" if reconciled else "")
            + ")",
            fg=typer.colors.CYAN,
        )
    )
    import uvicorn

    uvicorn.run(create_app(settings), host=host, port=port, reload=reload)


@app.command("report")
def report(
    task_dir: Annotated[Path, typer.Argument(...)],
    run_id: Annotated[str, typer.Option("--run-id")],
    as_json: Annotated[bool, typer.Option("--json")] = False,
    as_md: Annotated[bool, typer.Option("--md")] = False,
    artifacts_dir: Annotated[Optional[Path], typer.Option("--artifacts-dir")] = None,
    runs_dir: Annotated[Optional[Path], typer.Option("--runs-dir")] = None,
) -> None:
    """Build discovery/tournament report from run artifacts."""
    from faultevolve.discovery.report import (
        ReportError,
        build_manifest,
        render_json,
        render_md,
        verify_md,
    )

    try:
        runs = get_runs_dir(runs_dir, task_dir)
        art_dir = get_artifacts_dir(artifacts_dir, runs, run_id)
        manifest = build_manifest(art_dir, run_id)
        use_json = as_json or not as_md
        if use_json:
            typer.echo(render_json(manifest))
        else:
            md = render_md(manifest)
            bad = verify_md(md, manifest)
            if bad:
                raise ReportError("number mismatch")
            typer.echo(md)
    except ReportError:
        typer.echo(json.dumps({"ok": False, "error_type": "ReportError"}))
        raise typer.Exit(2)
    except Exception:
        typer.echo(json.dumps({"ok": False, "error_type": "ReportError"}))
        raise typer.Exit(1)


@discover_app.command("run")
def discover_run(
    task_dir: Annotated[Path, typer.Argument(...)],
    run_id: Annotated[str, typer.Option("--run-id")],
    mock: Annotated[bool, typer.Option("--mock")] = False,
    max_claims: Annotated[int | None, typer.Option("--max-claims")] = None,
    runs_dir: Annotated[Optional[Path], typer.Option("--runs-dir")] = None,
    artifacts_dir: Annotated[Optional[Path], typer.Option("--artifacts-dir")] = None,
    env_file: Annotated[Optional[Path], typer.Option("--env-file")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    if env_file:
        load_env_file(env_file)
    try:
        import time

        from faultevolve.cloud.engine import EvolutionEngine
        from faultevolve.cloud.llm import DashScopeLLM, MockLLM
        from faultevolve.cloud.store import Store
        from faultevolve.config import EvolveConfig
        from faultevolve.discovery.pipeline import DiscoveryRound
        from faultevolve.discovery.sandbox import STDERR_TAIL_CHARS
        from faultevolve.discovery.schemas import DiscoveryStats
        from faultevolve.tasks import create_benchmark_adapter

        task_path = task_dir.resolve()
        output_dir = runs_dir or (task_path / ".fe" / "runs")
        db_path = output_dir / run_id / "fe.db"
        if not db_path.exists():
            payload = {"ok": False, "error_type": "RunNotFound"}
            typer.echo(json.dumps(payload))
            raise typer.Exit(1)
        t0 = time.time()
        store = Store(db_path)
        config = EvolveConfig.from_yaml(task_path / "evolve.yaml")
        config.discovery.enabled = True
        if max_claims is not None:
            config.discovery.max_claims_per_round = max_claims
        adapter = create_benchmark_adapter(config)
        task_spec = adapter.load_task(task_path)
        llm = MockLLM() if mock else DashScopeLLM(config)
        engine = EvolutionEngine(config, adapter, task_spec, store, llm, mock=mock, task_dir=task_path)
        engine.initialize(resume_id=run_id)
        stats = DiscoveryStats()
        card_path = engine._discovery_card_path()
        kd = DiscoveryRound(
            config.discovery,
            store,
            adapter,
            task_spec,
            run_id,
            card_path,
            engine._get_knowledge_dir(),
            engine._discovery_llm_call,
            engine._log_event,
            stats,
        )
        candidates = engine._harvest_discovery_candidates()
        result = kd.run(1, False, candidates)
        art_dir = get_artifacts_dir(artifacts_dir, output_dir, run_id)
        art_dir.mkdir(parents=True, exist_ok=True)
        kd.write_artifacts(art_dir)
        engine._log_event(
            "discovery_round_finished",
            {"promoted": result.promoted_ids, "skipped": result.skipped_reason},
        )
        sandbox_errors: list[dict] = []
        for ev in store.get_events(run_id):
            if ev.type == "claim_sandbox_failed":
                detail = ev.payload or {}
                sandbox_errors.append(
                    {
                        "claim_id": detail.get("claim_id", ""),
                        "error_type": detail.get("error_type", "SandboxFailure"),
                        "error_tail": (detail.get("error") or "")[-STDERR_TAIL_CHARS:],
                    }
                )
        neg_fpr = result.controls.neg_fpr if result.controls else None
        promoted = [{"id": pid, "grade": "discovered"} for pid in result.promoted_ids]
        llm_err_events = [
            ev for ev in store.get_events(run_id) if ev.type == "discovery_llm_error"
        ]
        payload = {
            "ok": True,
            "claims_proposed": stats.claims_proposed,
            "claims_tested": stats.claims_tested,
            "claims_sandbox_failed": stats.claims_sandbox_failed,
            "round_finished": True,
            "elapsed_s": round(time.time() - t0, 3),
            "artifacts_dir": str(art_dir),
            "sandbox_errors": sandbox_errors,
            "neg_control_fpr": neg_fpr,
            "promoted_cards": promoted,
            "discovery_llm_error": {
                "count": stats.discovery_llm_errors or len(llm_err_events),
                "first": stats.discovery_llm_error_first
                or (
                    (llm_err_events[0].payload or {}).get("error")
                    if llm_err_events
                    else None
                ),
            },
        }
        typer.echo(json.dumps(payload, ensure_ascii=False))
    except typer.Exit:
        raise
    except Exception:
        typer.echo(json.dumps({"ok": False, "error_type": "DiscoverRunError"}))
        raise typer.Exit(1) from None


def _generic_mock_feature(frames) -> tuple[str, str]:
    """Offline stand-in factor built from whatever columns the task provides.

    Used when a task adapter does not implement
    ``FactorLibraryProvider.factor_mock_feature``.  It names no device-specific
    column, so ``--mock`` keeps working for any task.
    """
    # ``history.columns`` is a pandas Index: never truth-test it (that raises),
    # and never let the ``[]`` default be reached for an existing empty Index.
    columns = [str(c) for c in getattr(frames.history, "columns", [])]
    skip = {frames.unit_col, frames.time_col, getattr(frames, "label_col", None)}
    usable = [c for c in columns if c not in skip]
    column = usable[0] if usable else "value"
    code = (
        "import pandas as pd\n\n"
        "def feature(history):\n"
        f"    return history.groupby('{frames.unit_col}')['{column}'].last().astype(float)\n"
    )
    return code, f"mock {column} last"


def _discovery_round_setup(
    task_dir: Path,
    run_id: str,
    mock: bool,
    runs_dir: Path | None,
    env_file: Path | None,
):
    """Shared setup for discover subcommands that attach to an existing run DB."""
    if env_file:
        load_env_file(env_file)
    from faultevolve.cloud.engine import EvolutionEngine
    from faultevolve.cloud.llm import DashScopeLLM, MockLLM
    from faultevolve.cloud.store import Store
    from faultevolve.config import EvolveConfig
    from faultevolve.discovery.schemas import DiscoveryStats
    from faultevolve.tasks import create_benchmark_adapter

    task_path = task_dir.resolve()
    output_dir = runs_dir or (task_path / ".fe" / "runs")
    db_path = output_dir / run_id / "fe.db"
    if not db_path.exists():
        return None
    store = Store(db_path)
    config = EvolveConfig.from_yaml(task_path / "evolve.yaml")
    config.discovery.enabled = True
    adapter = create_benchmark_adapter(config)
    task_spec = adapter.load_task(task_path)
    llm = MockLLM() if mock else DashScopeLLM(config)
    engine = EvolutionEngine(
        config, adapter, task_spec, store, llm, mock=mock, task_dir=task_path,
    )
    engine.initialize(resume_id=run_id)
    stats = DiscoveryStats()
    card_path = engine._discovery_card_path()
    return {
        "task_path": task_path,
        "output_dir": output_dir,
        "store": store,
        "config": config,
        "adapter": adapter,
        "task_spec": task_spec,
        "engine": engine,
        "stats": stats,
        "card_path": card_path,
        "llm": llm,
    }


def _redact_discovery_error(exc: BaseException) -> str:
    msg = str(exc)
    for key in ("DASHSCOPE_API_KEY", "TYPESAFE_API_KEY", "FE_API_KEY"):
        val = os.environ.get(key)
        if val and val in msg:
            msg = msg.replace(val, "<redacted>")
    return msg[:200]


@discover_app.command("factors")
def discover_factors(
    task_dir: Annotated[Path, typer.Argument(...)],
    run_id: Annotated[str, typer.Option("--run-id")],
    library: Annotated[
        Path,
        typer.Option("--library", help="Factor library jsonl path"),
    ] = Path("src/faultevolve/discovery/factor_library/hdd_v1.jsonl"),
    max_candidates: Annotated[int, typer.Option("--max-candidates")] = 30,
    max_confirm: Annotated[int, typer.Option("--max-confirm")] = 3,
    confirmation_fraction: Annotated[
        Optional[float],
        typer.Option("--confirmation-fraction", help="Confirm split fraction (preregistered)"),
    ] = None,
    min_explore_effect: Annotated[
        float,
        typer.Option("--min-explore-effect", help="Explore marginal |AUROC-0.5| gate"),
    ] = 0.05,
    explore_only: Annotated[
        bool,
        typer.Option(
            "--explore-only",
            help="Stop after explore freeze; no confirm split, no entailment LLM",
        ),
    ] = False,
    track_label: Annotated[
        str,
        typer.Option(
            "--track-label",
            help="Empty=strict (default); use 'relaxed' for opt-in relaxed KD track",
        ),
    ] = "",
    explore_incr_rule: Annotated[
        str,
        typer.Option(
            "--explore-incr-rule",
            help="Explore increment gate: ci_low (default) or point_gain",
        ),
    ] = "ci_low",
    min_incr_ci_low: Annotated[
        float,
        typer.Option(
            "--min-incr-ci-low",
            help="Min incremental AUROC CI low for ci_low explore rule",
        ),
    ] = 0.0,
    fdr_mode: Annotated[
        str,
        typer.Option(
            "--fdr-mode",
            help="FDR grading: bh_ebh (default) or bh_for_confirm_ebh_for_discover",
        ),
    ] = "bh_ebh",
    mock: Annotated[bool, typer.Option("--mock")] = False,
    runs_dir: Annotated[Optional[Path], typer.Option("--runs-dir")] = None,
    artifacts_dir: Annotated[Optional[Path], typer.Option("--artifacts-dir")] = None,
    env_file: Annotated[Optional[Path], typer.Option("--env-file")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Run decoupled atomic factor discovery from a factor library (KD1-F)."""
    try:
        import time

        from faultevolve.discovery.factors import (
            git_sha_short,
            load_factor_library,
            run_factor_discovery,
        )
        from faultevolve.discovery.grading import VALID_FDR_MODES
        from faultevolve.discovery.pipeline import (
            VALID_EXPLORE_INCR_RULES,
            DiscoveryRound,
        )
        from faultevolve.discovery.report import build_token_tier_table
        from faultevolve.discovery.sandbox import STDERR_TAIL_CHARS

        task_path = task_dir.resolve()
        output_dir = get_runs_dir(runs_dir, task_path)
        setup = _discovery_round_setup(task_path, run_id, mock, output_dir, env_file)
        if setup is None:
            typer.echo(json.dumps({"ok": False, "error_type": "RunNotFound"}))
            raise typer.Exit(1)
        if explore_incr_rule not in VALID_EXPLORE_INCR_RULES:
            typer.echo(
                json.dumps(
                    {
                        "ok": False,
                        "error_type": "InvalidExploreIncrRule",
                        "explore_incr_rule": explore_incr_rule,
                    }
                )
            )
            raise typer.Exit(2)
        if fdr_mode not in VALID_FDR_MODES:
            typer.echo(
                json.dumps(
                    {
                        "ok": False,
                        "error_type": "InvalidFdrMode",
                        "fdr_mode": fdr_mode,
                    }
                )
            )
            raise typer.Exit(2)
        t0 = time.time()
        config = setup["config"]
        config.discovery.max_claims_per_round = max_candidates
        if confirmation_fraction is not None:
            config.discovery.confirmation_fraction = confirmation_fraction
        engine = setup["engine"]

        def _entailment_llm_call(messages: list[dict[str, str]]) -> str:
            from faultevolve.cloud.engine import DiscoveryLLMError
            from faultevolve.cloud.llm import LLMTransientError

            try:
                text, metrics = engine.llm.chat_for_reasoning(messages)
            except LLMTransientError as exc:
                raise DiscoveryLLMError(str(exc)) from exc
            engine._meter_llm_call(
                metrics,
                "entailment",
                node_id="",
                model=config.llm.reason_model,
            )
            return text

        kd = DiscoveryRound(
            config.discovery,
            setup["store"],
            setup["adapter"],
            setup["task_spec"],
            run_id,
            setup["card_path"],
            engine._get_knowledge_dir(),
            engine._discovery_llm_call,
            engine._log_event,
            setup["stats"],
            entailment_llm_call=_entailment_llm_call,
        )
        lib_path = Path(library)
        if not lib_path.is_file():
            lib_path = Path(__file__).resolve().parents[2] / library
        # The task adapter owns which columns a factor may name; the discovery
        # package only enforces the contract it is handed.
        column_provider = getattr(setup["adapter"], "discovery_input_columns", None)
        entries = load_factor_library(
            lib_path,
            max_candidates=max_candidates,
            allowed_columns=column_provider() if callable(column_provider) else None,
        )
        art_dir = get_artifacts_dir(artifacts_dir, output_dir, run_id)
        art_dir.mkdir(parents=True, exist_ok=True)
        fd_result = run_factor_discovery(
            kd,
            entries,
            art_dir,
            max_confirm=max_confirm,
            min_explore_effect=min_explore_effect,
            explore_only=explore_only,
            track_label=track_label,
            explore_incr_rule=explore_incr_rule,
            min_incr_ci_low=min_incr_ci_low,
            fdr_mode=fdr_mode,
        )
        kd.write_artifacts(art_dir)
        result = fd_result.round_result
        stats = fd_result.stats
        engine._log_event(
            "discovery_round_finished",
            {"promoted": result.promoted_ids, "skipped": result.skipped_reason, "mode": "factors"},
        )
        funnel = fd_result.funnel
        from faultevolve.discovery.funnel import funnel_summary_dict

        funnel = funnel_summary_dict(
            funnel,
            {
                "track_label": track_label,
                "explore_incr_rule": explore_incr_rule,
                "min_incr_ci_low": min_incr_ci_low,
                "fdr_mode": fdr_mode,
            },
        )
        neg_fpr = result.controls.neg_fpr if result.controls else None
        run_summary = {
            "experiment_id": run_id,
            "git_sha": git_sha_short(),
            "claims_proposed": stats.claims_proposed,
            "claims_tested": stats.claims_tested,
            "claims_confirmed": stats.confirmed,
            "claims_discovered": stats.discovered,
            "claims_refuted": stats.refuted,
            "claims_undetermined": stats.undetermined,
            "neg_control_fpr": neg_fpr,
            "discovery_tokens": engine.metrics.discovery_tokens,
            "total_tokens": engine.metrics.total_tokens,
            "discovery_token_share": engine.metrics.discovery_token_share,
            "propose_tokens": 0,
            "translate_tokens": 0,
            "entailment_tokens": engine.metrics.entailment_tokens,
        }
        with (art_dir / "run_summary.json").open("w", encoding="utf-8") as f:
            json.dump(run_summary, f, indent=2, ensure_ascii=False)
        sandbox_errors: list[dict] = []
        for ev in setup["store"].get_events(run_id):
            if ev.type == "claim_sandbox_failed":
                detail = ev.payload or {}
                sandbox_errors.append(
                    {
                        "claim_id": detail.get("claim_id", ""),
                        "error_type": detail.get("error_type", "SandboxFailure"),
                        "error_tail": (detail.get("error") or "")[-STDERR_TAIL_CHARS:],
                    }
                )
        payload = {
            "ok": True,
            "mode": "factors",
            "track_label": track_label,
            "explore_incr_rule": explore_incr_rule,
            "min_incr_ci_low": min_incr_ci_low,
            "fdr_mode": fdr_mode,
            "claims_proposed": stats.claims_proposed,
            "claims_tested": stats.claims_tested,
            "claims_sandbox_failed": stats.claims_sandbox_failed,
            "round_finished": True,
            "elapsed_s": round(time.time() - t0, 3),
            "artifacts_dir": str(art_dir),
            "registry_path": str(fd_result.registry_path),
            "funnel": funnel,
            "token_tiers": build_token_tier_table(run_summary),
            "sandbox_errors": sandbox_errors,
            "neg_control_fpr": neg_fpr,
            "promoted_cards": [{"id": pid, "grade": "discovered"} for pid in result.promoted_ids],
            "discovery_llm_error": {
                "count": fd_result.discovery_llm_errors,
                "first": fd_result.discovery_llm_error_first,
            },
        }
        typer.echo(json.dumps(payload, ensure_ascii=False))
    except typer.Exit:
        raise
    except Exception as exc:
        safe_err = _redact_discovery_error(exc)
        typer.echo(safe_err, err=True)
        try:
            task_path = task_dir.resolve()
            output_dir = get_runs_dir(runs_dir, task_path)
            art = get_artifacts_dir(artifacts_dir, output_dir, run_id)
            err_path = art / "discovery" / "error.txt"
            err_path.parent.mkdir(parents=True, exist_ok=True)
            err_path.write_text(safe_err, encoding="utf-8")
        except Exception:
            pass
        typer.echo(json.dumps({"ok": False, "error_type": "DiscoverFactorsError"}))
        raise typer.Exit(1) from None


@discover_app.command("propose")
def discover_propose(
    task_dir: Annotated[Path, typer.Argument(...)],
    run_id: Annotated[str, typer.Option("--run-id")],
    max_candidates: Annotated[int, typer.Option("--max-candidates")] = 12,
    mock: Annotated[bool, typer.Option("--mock")] = False,
    runs_dir: Annotated[Optional[Path], typer.Option("--runs-dir")] = None,
    artifacts_dir: Annotated[Optional[Path], typer.Option("--artifacts-dir")] = None,
    env_file: Annotated[Optional[Path], typer.Option("--env-file")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """LLM-only factor proposals (no scoring)."""
    try:
        import time

        from faultevolve.discovery.factors import (
            build_propose_prompt,
            propose_factors_llm,
            write_proposals,
        )
        from faultevolve.knowledge.loader import load_all_cards
        from faultevolve.tasks.protocol import DiscoveryDataProvider

        task_path = task_dir.resolve()
        output_dir = get_runs_dir(runs_dir, task_path)
        setup = _discovery_round_setup(task_path, run_id, mock, output_dir, env_file)
        if setup is None:
            typer.echo(json.dumps({"ok": False, "error_type": "RunNotFound"}))
            raise typer.Exit(1)
        t0 = time.time()
        adapter = setup["adapter"]
        if not isinstance(adapter, DiscoveryDataProvider):
            typer.echo(json.dumps({"ok": False, "error_type": "NoDiscoveryProvider"}))
            raise typer.Exit(1)
        frames = adapter.discovery_frames(setup["task_spec"])
        cols = list(frames.history.columns) if hasattr(frames.history, "columns") else []
        engine = setup["engine"]
        cards, _ = load_all_cards(engine._get_knowledge_dir(), [])
        titles = [c.title for c in cards if not c.id.startswith("D-")]
        baseline_desc = (
            f"K0 baseline columns: {', '.join(frames.baseline_cols)} "
            f"(last / diff / nonzero count features)"
        )
        prompt = build_propose_prompt(
            frames.schema_note,
            cols,
            baseline_desc,
            titles,
            "positive: smart_197 delta; negative: permuted column",
            max_candidates,
        )

        def llm_call(messages: list[dict[str, str]]) -> str:
            text, metrics = setup["llm"].chat_for_reasoning(messages)
            engine.metrics.add_llm_call(metrics, purpose="discover")
            return text

        mock_provider = getattr(setup["adapter"], "factor_mock_feature", None)
        mock_feature = mock_provider() if callable(mock_provider) else None
        if mock and mock_feature is None:
            mock_feature = _generic_mock_feature(frames)
        proposals = propose_factors_llm(
            llm_call,
            prompt,
            max_candidates,
            mock=mock,
            mock_feature=mock_feature,
        )
        art_dir = get_artifacts_dir(artifacts_dir, output_dir, run_id)
        prop_path = write_proposals(art_dir, proposals)
        payload = {
            "ok": True,
            "mode": "propose",
            "proposals_count": len(proposals),
            "proposals_path": str(prop_path),
            "elapsed_s": round(time.time() - t0, 3),
            "discovery_tokens": engine.metrics.discovery_tokens,
        }
        typer.echo(json.dumps(payload, ensure_ascii=False))
    except typer.Exit:
        raise
    except Exception:
        typer.echo(json.dumps({"ok": False, "error_type": "DiscoverProposeError"}))
        raise typer.Exit(1) from None


@discover_app.command("replay-claim")
def discover_replay_claim(
    task_dir: Annotated[Path, typer.Argument(...)],
    run_id: Annotated[str, typer.Option("--run-id")],
    claim_id: Annotated[str, typer.Option("--claim-id")],
    factor_id: Annotated[str, typer.Option("--factor-id")],
    library: Annotated[
        Path,
        typer.Option("--library", help="Factor library jsonl path"),
    ] = Path("src/faultevolve/discovery/factor_library/hdd_v3.jsonl"),
    source_artifacts_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--source-artifacts-dir",
            help="Source discovery artifacts (data_audit.json); default runs-dir/run-id/artifacts",
        ),
    ] = None,
    enable_tournament: Annotated[
        bool,
        typer.Option("--enable-tournament", help="Run KD2 tournament on frozen confirm mask"),
    ] = False,
    interrogate: Annotated[
        bool,
        typer.Option("--interrogate", help="Run zero-score LLM interrogation (3 roles)"),
    ] = False,
    n_slices: Annotated[
        Optional[int],
        typer.Option("--n-slices", min=2, max=16, help="KD2 slice count (2-16)"),
    ] = None,
    transfer_frame: Annotated[
        Optional[str],
        typer.Option(
            "--transfer-frame",
            help="Transfer validation frame: train_late, backblaze_public_train, or val",
        ),
    ] = None,
    transfer_task_dir: Annotated[
        Optional[Path],
        typer.Option("--transfer-task-dir", help="Task dir for transfer frame data"),
    ] = None,
    allow_val_transfer: Annotated[
        bool,
        typer.Option(
            "--allow-val-transfer",
            help="Allow val history transfer (pollutes evolution scoring set)",
        ),
    ] = False,
    mock: Annotated[bool, typer.Option("--mock")] = False,
    runs_dir: Annotated[Optional[Path], typer.Option("--runs-dir")] = None,
    artifacts_dir: Annotated[Optional[Path], typer.Option("--artifacts-dir")] = None,
    env_file: Annotated[Optional[Path], typer.Option("--env-file")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Replay a frozen library claim: interrogation, KD2 tournament, optional transfer."""
    try:
        import time

        from faultevolve.discovery.replay import ReplayError, run_replay_claim

        task_path = task_dir.resolve()
        output_dir = get_runs_dir(runs_dir, task_path)
        setup = _discovery_round_setup(task_path, run_id, mock, output_dir, env_file)
        if setup is None:
            typer.echo(json.dumps({"ok": False, "error_type": "RunNotFound"}))
            raise typer.Exit(1)
        if transfer_frame and transfer_frame.strip().lower() in {"holdout", "test"}:
            typer.echo(
                json.dumps(
                    {
                        "ok": False,
                        "error_type": "ForbiddenTransferFrame",
                        "transfer_frame": transfer_frame,
                    }
                )
            )
            raise typer.Exit(2)
        if allow_val_transfer:
            typer.echo(
                typer.style(
                    "Warning: val transfer uses evolution scoring labels; report separately.",
                    fg=typer.colors.YELLOW,
                ),
                err=True,
            )
        art_dir = get_artifacts_dir(artifacts_dir, output_dir, run_id)
        src_art = source_artifacts_dir or (output_dir / run_id / "artifacts")
        source_disc = src_art / "discovery"
        engine = setup["engine"]
        config = setup["config"]

        def _mechanism_llm_call(messages: list[dict[str, str]]) -> str:
            from faultevolve.cloud.engine import DiscoveryLLMError
            from faultevolve.cloud.llm import LLMTransientError

            try:
                text, metrics = engine.llm.chat_for_reasoning(messages)
            except LLMTransientError as exc:
                raise DiscoveryLLMError(str(exc)) from exc
            engine._meter_llm_call(
                metrics,
                "mechanism",
                node_id="",
                model=config.llm.reason_model,
            )
            return text

        transfer_adapter = None
        transfer_spec = None
        if transfer_task_dir is not None:
            from faultevolve.tasks import create_benchmark_adapter

            tpath = transfer_task_dir.resolve()
            tconfig = setup["config"]
            transfer_adapter = create_benchmark_adapter(tconfig)
            transfer_spec = transfer_adapter.load_task(tpath)

        column_provider = getattr(setup["adapter"], "discovery_input_columns", None)
        allowed = column_provider() if callable(column_provider) else None
        lib_path = Path(library)
        if not lib_path.is_file():
            lib_path = Path(__file__).resolve().parents[2] / library
        t0 = time.time()
        result = run_replay_claim(
            adapter=setup["adapter"],
            task_spec=setup["task_spec"],
            experiment_id=run_id,
            claim_id=claim_id,
            factor_id=factor_id,
            library_path=lib_path,
            source_discovery_dir=source_disc,
            art_dir=art_dir,
            cfg=config.discovery,
            store=setup["store"],
            mechanism_llm_call=_mechanism_llm_call,
            log_event=engine._log_event,
            enable_tournament=enable_tournament,
            interrogate=interrogate,
            n_slices=n_slices,
            transfer_frame=transfer_frame,
            allow_val_transfer=allow_val_transfer,
            transfer_adapter=transfer_adapter,
            transfer_task_spec=transfer_spec,
            allowed_columns=allowed,
        )
        payload = {
            "ok": result.ok,
            "mode": "replay_claim",
            "claim_id": result.claim_id,
            "factor_id": result.factor_id,
            "frozen_direction": result.frozen_direction,
            "split_salt": result.split_salt,
            "confirmation_fraction": result.confirmation_fraction,
            "interrogation_lines": result.interrogation_lines,
            "tournament": result.tournament,
            "transfer": result.transfer,
            "cards_sha256_unchanged": result.cards_sha256_before == result.cards_sha256_after,
            "elapsed_s": round(time.time() - t0, 3),
            "artifacts_dir": str(art_dir),
        }
        typer.echo(json.dumps(payload, ensure_ascii=False))
    except ReplayError as exc:
        typer.echo(
            json.dumps(
                {
                    "ok": False,
                    "error_type": exc.error_type,
                    **exc.detail,
                },
                ensure_ascii=False,
            )
        )
        raise typer.Exit(2) from None
    except typer.Exit:
        raise
    except Exception as exc:
        safe_err = _redact_discovery_error(exc)
        typer.echo(safe_err, err=True)
        try:
            task_path = task_dir.resolve()
            output_dir = get_runs_dir(runs_dir, task_path)
            art = get_artifacts_dir(artifacts_dir, output_dir, run_id)
            err_path = art / "discovery" / "error.txt"
            err_path.parent.mkdir(parents=True, exist_ok=True)
            err_path.write_text(safe_err, encoding="utf-8")
        except Exception:
            pass
        typer.echo(json.dumps({"ok": False, "error_type": "ReplayClaimError"}))
        raise typer.Exit(1) from None


@discover_app.command("report")
def discover_report(
    task_dir: Annotated[Path, typer.Argument(...)],
    run_id: Annotated[str, typer.Option("--run-id")],
    json_output: Annotated[bool, typer.Option("--json")] = True,
) -> None:
    try:
        from faultevolve.cloud.store import Store
        from faultevolve.config import DiscoveryConfig

        task_path = task_dir.resolve()
        db_path = task_path / ".fe" / "runs" / run_id / "fe.db"
        if not db_path.exists():
            typer.echo(json.dumps({"ok": False, "error_type": "RunNotFound"}))
            raise typer.Exit(1)
        store = Store(db_path)
        claims = store.get_claims(run_id)
        tests = sum(len(store.get_claim_tests(c["id"])) for c in claims if c.get("id"))
        discovered = store.get_discovered_cards(run_id)
        grades: dict[str, int] = {}
        for c in claims:
            g = c.get("grade") or "none"
            grades[g] = grades.get(g, 0) + 1
        payload = {
            "ok": True,
            "claims_tested": tests,
            "neg_control_fpr": None,
            "planted_recovery_rate": {},
            "grades": grades,
            "promoted_cards": [
                {
                    "id": d["card_id"],
                    "grade": d.get("grade"),
                    "prereg_hash": "",
                    "claim_id": d.get("claim_id"),
                    "origin_node_id": "",
                }
                for d in discovered
            ],
        }
        typer.echo(json.dumps(payload, ensure_ascii=False))
    except typer.Exit:
        raise
    except Exception:
        typer.echo(json.dumps({"ok": False, "error_type": "DiscoverReportError"}))
        raise typer.Exit(1) from None


@data_app.command("checkup")
def data_checkup(
    task_dir: Annotated[Path, typer.Argument(...)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
    out: Annotated[Optional[Path], typer.Option("--out")] = None,
) -> None:
    try:
        from faultevolve.config import EvolveConfig
        from faultevolve.tasks import create_benchmark_adapter

        task_path = task_dir.resolve()
        config = EvolveConfig.from_yaml(task_path / "evolve.yaml")
        adapter = create_benchmark_adapter(config)
        task_spec = adapter.load_task(task_path)
        frames = adapter.discovery_frames(task_spec)
        import pandas as pd

        labels = frames.labels if isinstance(frames.labels, pd.DataFrame) else pd.DataFrame(frames.labels)
        n_pos = int((labels[frames.label_col] == 1).sum())
        n_samples = len(labels)
        out_dir = out or (task_path / ".fe" / "datacheck")
        out_dir.mkdir(parents=True, exist_ok=True)
        facts = {
            "n_samples": n_samples,
            "n_positive": n_pos,
            "label_semantics": "1=failure",
            "columns": list(frames.history.columns) if hasattr(frames.history, "columns") else [],
            "min_detectable_effect": 0.05,
        }
        with (out_dir / "data_facts.json").open("w", encoding="utf-8") as f:
            json.dump(facts, f, indent=2)
        hist = frames.history
        coverage_rows = []
        for col in hist.columns:
            if col in (frames.unit_col, frames.time_col):
                continue
            rate = float(hist[col].notna().mean())
            coverage_rows.append({"column": col, "non_null_rate": rate})
        pd.DataFrame(coverage_rows).to_csv(out_dir / "field_coverage.csv", index=False)
        silent_header = ["subset", "stat"]
        silent_path = out_dir / "silent_subset_stats.csv"
        extras = None
        if hasattr(adapter, "checkup_extras"):
            extras = adapter.checkup_extras()
        if extras is not None:
            extras.to_csv(silent_path, index=False)
        else:
            silent_path.write_text(",".join(silent_header) + "\n", encoding="utf-8")
        payload = {"ok": True, "out_dir": str(out_dir), **facts}
        typer.echo(json.dumps(payload, ensure_ascii=False))
    except FileNotFoundError:
        typer.echo(json.dumps({"ok": False, "error_type": "DataMissing"}))
        raise typer.Exit(1) from None
    except Exception:
        typer.echo(json.dumps({"ok": False, "error_type": "CheckupError"}))
        raise typer.Exit(1) from None


@judge_app.command("ping")
def judge_ping(
    task_dir: Annotated[
        Path, typer.Option("--task-dir", help="Task directory")
    ] = Path("benchmark/hdd_mvp"),
    env_file: Annotated[
        Optional[Path], typer.Option("--env-file", help="Load environment file")
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Output as JSON")
    ] = False,
) -> None:
    """Send one minimal sanitized Jev health request."""
    if env_file:
        load_env_file(env_file)
    from faultevolve.cloud.jev_client import JevClient, JevError
    from faultevolve.config import EvolveConfig, JudgeConfig

    config = EvolveConfig.from_yaml(task_dir / "evolve.yaml")
    judge_config = JudgeConfig(**{
        **config.judge.model_dump(),
        "provider": "jev",
    })
    try:
        response = JevClient(judge_config).decide(
            "health check",
            [{
                "name": "valid",
                "type": "noul",
                "instructions": "服务是否可用？",
                "criteria": {"true": "可用", "false": "不可用"},
            }],
        )
        payload = {
            "ok": True,
            "latency_ms": response.latency_ms,
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "total_tokens": response.total_tokens,
            "answer_keys": sorted(response.answers),
        }
        typer.echo(json.dumps(payload) if json_output else payload)
    except (JevError, Exception) as exc:
        payload = {"ok": False, "error_type": type(exc).__name__}
        typer.echo(json.dumps(payload) if json_output else payload)
        raise typer.Exit(1) from None


@app.command("analyze")
def analyze(
    task_dir: Annotated[Path, typer.Argument(..., help="Task directory")],
    program: Annotated[Path, typer.Option("--program", help="Candidate program to profile")],
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    env_file: Annotated[Optional[Path], typer.Option("--env-file", help="Load env vars")] = None,
) -> None:
    """Run dev-set error profiling for a single candidate program."""
    if env_file:
        load_env_file(env_file)

    from faultevolve.config import EvolveConfig
    from faultevolve.tasks import create_adapter

    task_path = task_dir.resolve()
    program_path = program.resolve()
    if not task_path.exists():
        typer.echo(json.dumps({"ok": False, "error_type": "FileNotFoundError"}) if json_output else "task not found", err=True)
        raise typer.Exit(1)
    if not program_path.exists():
        typer.echo(json.dumps({"ok": False, "error_type": "FileNotFoundError"}) if json_output else "program not found", err=True)
        raise typer.Exit(1)

    evolve_yaml = task_path / "evolve.yaml"
    config = EvolveConfig.from_yaml(evolve_yaml) if evolve_yaml.exists() else EvolveConfig()
    adapter = create_adapter(config)
    if not hasattr(adapter, "analyze"):
        payload = {"ok": False, "error_type": "NotSupported"}
        typer.echo(json.dumps(payload) if json_output else "analyze not supported", err=True)
        raise typer.Exit(1)
    start = __import__("time").time()
    try:
        task_spec = adapter.load_task(task_path)
        code = program_path.read_text(encoding="utf-8")
        static_error = adapter.static_check(code, task_spec)
        if static_error:
            payload = {"ok": False, "error_type": "StaticCheckError"}
            typer.echo(json.dumps(payload) if json_output else "static check failed", err=True)
            raise typer.Exit(1)
        profile = adapter.analyze(code, task_spec, config.analysis.timeout_s)
        duration = __import__("time").time() - start
        payload = {"ok": True, "analysis": profile, "analysis_time_s": round(duration, 3)}
        typer.echo(json.dumps(payload, ensure_ascii=False) if json_output else json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        payload = {"ok": False, "error_type": type(exc).__name__}
        typer.echo(json.dumps(payload) if json_output else payload["error_type"], err=True)
        raise typer.Exit(1) from None
    finally:
        adapter.cleanup_analysis_data()


@app.command()
def doctor(
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    task_dir: Annotated[Optional[Path], typer.Option("--task-dir", help="Task dir to check network FS")] = None,
    env_file: Annotated[Optional[Path], typer.Option("--env-file", help="Load env vars from file")] = None,
) -> None:
    """Check environment: Python version, dependencies, API keys (presence only)."""
    if env_file:
        load_env_file(env_file)

    checks: list[dict] = []

    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_ok = sys.version_info >= (3, 12)
    checks.append({
        "name": "python_version",
        "ok": py_ok,
        "value": py_ver,
        "message": f"Python {py_ver}" + ("" if py_ok else " (requires >=3.12)"),
    })

    required_packages = ["numpy", "pandas", "pydantic", "typer", "openai", "httpx", "yaml"]
    for pkg in required_packages:
        try:
            __import__(pkg if pkg != "yaml" else "yaml")
            checks.append({"name": f"package_{pkg}", "ok": True, "message": f"{pkg} available"})
        except ImportError:
            checks.append({"name": f"package_{pkg}", "ok": False, "message": f"{pkg} not installed"})

    from faultevolve.config import EvolveConfig

    judge_api_key_env = "TYPESAFE_API_KEY"
    if task_dir:
        evolve_yaml = task_dir / "evolve.yaml"
        if evolve_yaml.exists():
            cfg = EvolveConfig.from_yaml(evolve_yaml)
            judge_api_key_env = cfg.judge.api_key_env

    env_keys = ["DASHSCOPE_API_KEY", judge_api_key_env, "FE_API_KEY"]
    seen = set()
    for key in env_keys:
        if key in seen:
            continue
        seen.add(key)
        present = key in os.environ and bool(os.environ[key])
        checks.append({
            "name": f"env_{key}",
            "ok": present,
            "message": f"{key} {'set' if present else 'not set'}",
        })

    runs_dir_env = os.environ.get("FE_RUNS_DIR")
    if runs_dir_env:
        runs_path = Path(runs_dir_env)
        is_net, fs_type = detect_network_fs(runs_path)
        if is_net:
            checks.append({
                "name": "runs_dir_network_fs",
                "ok": False,
                "message": f"FE_RUNS_DIR is on network filesystem ({fs_type}): {runs_path}",
            })
        else:
            checks.append({
                "name": "runs_dir_network_fs",
                "ok": True,
                "message": f"FE_RUNS_DIR is on local filesystem: {runs_path}",
            })
    elif task_dir:
        default_runs = task_dir / ".fe" / "runs"
        is_net, fs_type = detect_network_fs(default_runs)
        if is_net:
            checks.append({
                "name": "runs_dir_network_fs",
                "ok": False,
                "message": f"Default runs dir is on network filesystem ({fs_type}): {default_runs}",
            })

    if task_dir:
        from faultevolve.tasks import create_adapter, stub_doc_for
        from faultevolve.tasks.protocol import DataStatusProvider

        task_path = task_dir.resolve()
        required_task_files = ["evaluator.py", "init.py", "problem.md", "prompt.md"]
        missing_tf = [f for f in required_task_files if not (task_path / f).exists()]
        tf_ok = not missing_tf
        tf_msg = "task files ok" if tf_ok else f"missing task files: {missing_tf}"
        if missing_tf:
            evolve_yaml = task_path / "evolve.yaml"
            adapter_name = "hdd"
            if evolve_yaml.exists():
                adapter_name = EvolveConfig.from_yaml(evolve_yaml).task.adapter
            doc = stub_doc_for(adapter_name)
            if doc:
                tf_msg += f"; see {doc}"
        checks.append({"name": "task_files", "ok": tf_ok, "message": tf_msg})

        try:
            evolve_yaml = task_path / "evolve.yaml"
            cfg = EvolveConfig.from_yaml(evolve_yaml) if evolve_yaml.exists() else EvolveConfig()
            adapter = create_adapter(cfg)
            checks.append({
                "name": "task_adapter",
                "ok": True,
                "message": f"adapter {cfg.task.adapter} -> {type(adapter).__name__}",
            })
        except Exception as exc:
            checks.append({
                "name": "task_adapter",
                "ok": False,
                "message": str(exc).splitlines()[0],
            })
            adapter = None

        if adapter is not None and isinstance(adapter, DataStatusProvider):
            ds = adapter.data_status(task_path)
            checks.append({
                "name": "task_data",
                "ok": ds.ok,
                "message": ds.message,
            })

        if os.environ.get("HDD_BENCH_DATA_ROOT"):
            checks.append({
                "name": "task_data_root_env",
                "ok": True,
                "message": (
                    f"HDD_BENCH_DATA_ROOT={os.environ['HDD_BENCH_DATA_ROOT']} "
                    f"(确认它属于 {task_path.name})"
                ),
            })

    all_ok = all(c["ok"] for c in checks)

    if json_output:
        typer.echo(json.dumps({"checks": checks, "all_ok": all_ok}, indent=2))
    else:
        for c in checks:
            symbol = typer.style("✓", fg=typer.colors.GREEN) if c["ok"] else typer.style("✗", fg=typer.colors.RED)
            typer.echo(f"  {symbol} {c['message']}")
        if all_ok:
            typer.echo(typer.style("\nAll checks passed.", fg=typer.colors.GREEN))
        else:
            typer.echo(typer.style("\nSome checks failed.", fg=typer.colors.YELLOW))

    raise typer.Exit(0 if all_ok else 1)


@evolve_app.command("local")
def evolve_local(
    task_dir: Annotated[Path, typer.Argument(help="Path to task directory (e.g., benchmark/hdd_mvp)")],
    mock: Annotated[bool, typer.Option("--mock", help="Use mock LLM for offline testing")] = False,
    iterations: Annotated[int, typer.Option("--iterations", "-n", help="Maximum iterations")] = 50,
    resume: Annotated[Optional[str], typer.Option("--resume", help="Resume from experiment ID")] = None,
    run_id: Annotated[Optional[str], typer.Option("--run-id", help="Pre-assigned ID for a new run")] = None,
    config_file: Annotated[Optional[Path], typer.Option("--config-file", help="Effective config YAML, instead of <task_dir>/evolve.yaml")] = None,
    target_score: Annotated[Optional[float], typer.Option("--target-score", help="Stop when reaching this score")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
    seed: Annotated[int, typer.Option("--seed", help="Random seed")] = 20260926,
    runs_dir: Annotated[Optional[Path], typer.Option("--runs-dir", help="Directory for DB and metadata")] = None,
    artifacts_dir: Annotated[Optional[Path], typer.Option("--artifacts-dir", help="Directory for large artifacts")] = None,
    env_file: Annotated[Optional[Path], typer.Option("--env-file", help="Load env vars from file")] = None,
) -> None:
    """Run local evolution loop on a task directory.

    The task directory must contain: evaluator.py, init.py, problem.md, prompt.md.
    Optionally: evolve.yaml for configuration overrides.

    Results are stored in <runs_dir>/<exp_id>/ for the SQLite DB.
    Artifacts (tree.json, events.jsonl, run_summary.json, programs) go to <artifacts_dir>/<exp_id>/.
    """
    if env_file:
        load_env_file(env_file)

    from faultevolve.cloud.engine import run_local_evolution

    task_path = task_dir.resolve()
    if not task_path.exists():
        typer.echo(f"Error: task directory not found: {task_path}", err=True)
        raise typer.Exit(1)

    required_files = ["evaluator.py", "init.py", "problem.md", "prompt.md"]
    missing = [f for f in required_files if not (task_path / f).exists()]
    if missing:
        from faultevolve.config import EvolveConfig
        from faultevolve.tasks import stub_doc_for

        typer.echo(f"Error: missing required files: {missing}", err=True)
        evolve_yaml = task_path / "evolve.yaml"
        if evolve_yaml.exists():
            cfg = EvolveConfig.from_yaml(evolve_yaml)
            doc = stub_doc_for(cfg.task.adapter)
            if doc:
                typer.echo(f"See {doc}", err=True)
        raise typer.Exit(1)

    if not mock and "DASHSCOPE_API_KEY" not in os.environ:
        typer.echo("Error: DASHSCOPE_API_KEY not set. Use --mock for offline testing.", err=True)
        raise typer.Exit(1)

    if resume and run_id:
        # Quietly preferring one of them would leave the Web layer's registry
        # pointing at an id under which no run was ever created.
        typer.echo("Error: --resume and --run-id are mutually exclusive.", err=True)
        raise typer.Exit(1)

    resolved_runs_dir = get_runs_dir(runs_dir, task_path)
    resolved_artifacts_dir = get_base_artifacts_dir(artifacts_dir, resolved_runs_dir)

    if not resume:
        check_db_path_network_fs(resolved_runs_dir / "test.db")

    try:
        result = run_local_evolution(
            task_dir=task_path,
            mock=mock,
            max_iterations=iterations,
            resume_id=resume,
            target_score=target_score,
            seed=seed,
            runs_dir=resolved_runs_dir,
            artifacts_dir=resolved_artifacts_dir,
            experiment_id=run_id,
            config_path=config_file,
        )
        if json_output:
            typer.echo(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            typer.echo(f"\nEvolution completed: {result['status']}")
            typer.echo(f"  Experiment ID: {result['experiment_id']}")
            typer.echo(f"  Iterations: {result['iterations_done']}")
            typer.echo(f"  Best score: {result['best_score']:.2f}")
            typer.echo(f"  Results: {result['output_dir']}")
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from e


if __name__ == "__main__":
    app()
