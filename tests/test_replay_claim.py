"""Tests for fe discover replay-claim (offline synthetic data)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from faultevolve.cli import app
from faultevolve.cloud.engine import run_local_evolution
from faultevolve.discovery.replay import ReplayError, run_replay_claim
from faultevolve.tasks.protocol import DiscoveryFrames
from faultevolve.worker.runner import FakeAdapter

runner = CliRunner()
REPO = Path(__file__).resolve().parents[1]
F10_CODE = (
    "import pandas as pd\n\n"
    "def feature(history):\n"
    '    col = "smart_194_normalized"\n'
    "    return history.groupby(\"serial_number\", group_keys=False).apply(\n"
    "        lambda g: float(g[col].astype(float).iloc[-1])\n"
    "        if g[col].notna().any() and pd.notna(g[col].astype(float).iloc[-1])\n"
    '        else float("nan")\n'
    "    )\n"
)


class Smart194Adapter(FakeAdapter):
    """Synthetic public-train-like frames with a normalized thermal column."""

    def discovery_frames(self, task_spec) -> DiscoveryFrames:
        rng = np.random.default_rng(42)
        n_units = 80
        rows_hist = []
        labels = []
        y = (rng.random(n_units) < 0.25).astype(int)
        for i in range(n_units):
            unit = f"s{i:04d}"
            cutoff = f"2024-06-{15 + (i % 10):02d}"
            labels.append({"serial_number": unit, "label": int(y[i]), "cutoff_date": cutoff})
            signal = 0.4 if y[i] else 0.0
            for t in range(14):
                rows_hist.append(
                    {
                        "serial_number": unit,
                        "date": f"2024-06-{t + 1:02d}",
                        "smart_194_normalized": rng.normal(signal, 0.2),
                        "smart_1_raw": rng.normal(0, 1),
                        "smart_3_raw": rng.normal(0, 1),
                    }
                )
        history = pd.DataFrame(rows_hist)
        label_df = pd.DataFrame(labels)
        env_frame = pd.DataFrame(
            {
                "env": [f"fam|2024-06" for _ in range(n_units)],
                "conf": ["fam"] * n_units,
                "time": label_df["cutoff_date"],
                "censor": 0,
            }
        )
        return DiscoveryFrames(
            labels=label_df[["serial_number", "label"]],
            history=history,
            unit_col="serial_number",
            time_col="date",
            label_col="label",
            baseline_cols=["smart_1_raw", "smart_3_raw"],
            schema_note="synthetic smart_194_normalized column",
            env_frame=env_frame,
        )

    def discovery_input_columns(self) -> list[str]:
        return [
            "serial_number",
            "date",
            "smart_194_normalized",
            "smart_1_raw",
            "smart_3_raw",
        ]


def _task(tmp_path: Path) -> Path:
    task = tmp_path / "task"
    task.mkdir()
    (task / "init.py").write_text("# init", encoding="utf-8")
    (task / "problem.md").write_text("# p", encoding="utf-8")
    (task / "prompt.md").write_text("# prompt", encoding="utf-8")
    (task / "evaluator.py").write_text(
        "def evaluate(p, **kw):\n"
        "    return {'validity': 1, 'combined_score': 22, 'cost_time': 1, 'error_info': '', 'metric': {}}\n",
        encoding="utf-8",
    )
    (task / "evolve.yaml").write_text(
        "discovery:\n  enabled: true\n  bootstrap_b: 80\n  neg_control_repeats: 1\n"
        "  tournament:\n    enabled: false\n    n_slices: 4\n",
        encoding="utf-8",
    )
    return task


def _write_source_audit(art: Path, *, with_salt: bool = True) -> None:
    disc = art / "discovery"
    disc.mkdir(parents=True, exist_ok=True)
    audit = {"confirmation_fraction": 0.5}
    if with_salt:
        audit["split_salt"] = "fe-kd-test-salt"
    (disc / "data_audit.json").write_text(json.dumps(audit), encoding="utf-8")
    (disc / "phenomena.json").write_text(
        json.dumps(
            [
                {
                    "claim_id": "C-89f4bdd1-0010",
                    "grade": "confirmed",
                    "payload": {"direction": "+", "ci_low": 0.01},
                }
            ]
        ),
        encoding="utf-8",
    )


def _toy_library(tmp_path: Path) -> Path:
    lib = tmp_path / "f10.jsonl"
    lib.write_text(
        json.dumps(
            {
                "factor_id": "HDD3_F10",
                "family": "thermal",
                "title": "smart_194_normalized last value",
                "code": F10_CODE,
                "inputs": ["smart_194_normalized"],
                "window_days": 14,
                "direction": "auto",
                "lane": "confirm",
                "confirm_eligible": True,
                "condition": "c",
                "outcome": "disk_failure",
                "scope": "train_labeled_units",
                "falsifier": "flip",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return lib


def _bootstrap_run(tmp_path: Path) -> tuple[Path, str, Path, Smart194Adapter]:
    task = _task(tmp_path)
    adapter = Smart194Adapter()
    runs = task / ".fe" / "runs"
    with patch("faultevolve.tasks.create_benchmark_adapter", return_value=adapter):
        evo = run_local_evolution(
            task_dir=task,
            mock=True,
            max_iterations=2,
            runs_dir=runs,
            adapter=adapter,
        )
    run_id = evo["experiment_id"]
    src_art = runs / run_id / "artifacts"
    _write_source_audit(src_art)
    return task, run_id, runs, adapter


def test_replay_claim_mock_tournament(tmp_path):
    task, run_id, runs, adapter = _bootstrap_run(tmp_path)
    lib = _toy_library(tmp_path)
    art_root = tmp_path / "out_art"
    with patch("faultevolve.tasks.create_benchmark_adapter", return_value=adapter):
        res = runner.invoke(
            app,
            [
                "discover",
                "replay-claim",
                str(task),
                "--run-id",
                run_id,
                "--claim-id",
                "C-89f4bdd1-0010",
                "--factor-id",
                "HDD3_F10",
                "--library",
                str(lib),
                "--runs-dir",
                str(runs),
                "--artifacts-dir",
                str(art_root),
                "--enable-tournament",
                "--mock",
                "--json",
            ],
        )
    assert res.exit_code == 0
    payload = json.loads(res.stdout)
    assert payload["ok"] is True
    assert payload["cards_sha256_unchanged"] is True
    assert payload["tournament"].get("mechanisms_proposed", 0) >= 5
    disc = art_root / run_id / "discovery"
    assert (disc / "mechanisms.json").exists() or payload["tournament"].get("tournament_skipped")


def test_missing_column_no_llm(tmp_path):
    task, run_id, runs, adapter = _bootstrap_run(tmp_path)

    class NoColAdapter(Smart194Adapter):
        def discovery_frames(self, task_spec):
            frames = super().discovery_frames(task_spec)
            hist = frames.history.drop(columns=["smart_194_normalized"])
            return DiscoveryFrames(
                labels=frames.labels,
                history=hist,
                unit_col=frames.unit_col,
                time_col=frames.time_col,
                label_col=frames.label_col,
                baseline_cols=frames.baseline_cols,
                schema_note=frames.schema_note,
                env_frame=frames.env_frame,
            )

    bad = NoColAdapter()
    lib = _toy_library(tmp_path)
    with patch("faultevolve.tasks.create_benchmark_adapter", return_value=bad):
        res = runner.invoke(
            app,
            [
                "discover",
                "replay-claim",
                str(task),
                "--run-id",
                run_id,
                "--claim-id",
                "C-89f4bdd1-0010",
                "--factor-id",
                "HDD3_F10",
                "--library",
                str(lib),
                "--runs-dir",
                str(runs),
                "--mock",
                "--json",
            ],
        )
    assert res.exit_code == 2
    payload = json.loads(res.stdout)
    assert payload["error_type"] == "missing_column"


def test_transfer_train_late_ci_field(tmp_path):
    task, run_id, runs, adapter = _bootstrap_run(tmp_path)
    lib = _toy_library(tmp_path)
    out_art = tmp_path / "t1"
    with patch("faultevolve.tasks.create_benchmark_adapter", return_value=adapter):
        res = runner.invoke(
            app,
            [
                "discover",
                "replay-claim",
                str(task),
                "--run-id",
                run_id,
                "--claim-id",
                "C-89f4bdd1-0010",
                "--factor-id",
                "HDD3_F10",
                "--library",
                str(lib),
                "--runs-dir",
                str(runs),
                "--artifacts-dir",
                str(out_art),
                "--transfer-frame",
                "train_late",
                "--mock",
                "--json",
            ],
        )
    assert res.exit_code == 0
    payload = json.loads(res.stdout)
    assert "ci_low" in payload["transfer"]


def test_rejects_holdout_transfer_frame(tmp_path):
    task, run_id, runs, adapter = _bootstrap_run(tmp_path)
    lib = _toy_library(tmp_path)
    with patch("faultevolve.tasks.create_benchmark_adapter", return_value=adapter):
        res = runner.invoke(
            app,
            [
                "discover",
                "replay-claim",
                str(task),
                "--run-id",
                run_id,
                "--claim-id",
                "C-89f4bdd1-0010",
                "--factor-id",
                "HDD3_F10",
                "--library",
                str(lib),
                "--runs-dir",
                str(runs),
                "--transfer-frame",
                "holdout",
                "--mock",
                "--json",
            ],
        )
    assert res.exit_code == 2
    assert json.loads(res.stdout)["error_type"] == "ForbiddenTransferFrame"


def test_interrogation_bad_json_fixed_rivals(tmp_path):
    task, run_id, runs, adapter = _bootstrap_run(tmp_path)
    lib = _toy_library(tmp_path)
    from faultevolve.cloud.store import Store
    from faultevolve.config import EvolveConfig

    config = EvolveConfig.from_yaml(task / "evolve.yaml")
    store = Store(runs / run_id / "fe.db")
    art_dir = tmp_path / "debate" / run_id
    result = run_replay_claim(
        adapter=adapter,
        task_spec=adapter.load_task(task),
        experiment_id=run_id,
        claim_id="C-89f4bdd1-0010",
        factor_id="HDD3_F10",
        library_path=lib,
        source_discovery_dir=runs / run_id / "artifacts" / "discovery",
        art_dir=art_dir,
        cfg=config.discovery,
        store=store,
        mechanism_llm_call=lambda m: "not json at all",
        log_event=lambda t, p: None,
        enable_tournament=True,
        interrogate=True,
        allowed_columns=adapter.discovery_input_columns(),
    )
    assert result.interrogation_lines == 3
    assert result.tournament.get("mechanisms_proposed", 0) >= 5
    lines = (art_dir / "discovery" / "interrogation.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3


def test_missing_audit_split_params_exit_2(tmp_path):
    task, run_id, runs, adapter = _bootstrap_run(tmp_path)
    src = runs / run_id / "artifacts" / "discovery" / "data_audit.json"
    src.write_text(json.dumps({"confirmation_fraction": 0.5}), encoding="utf-8")
    lib = _toy_library(tmp_path)
    from faultevolve.config import EvolveConfig
    from faultevolve.cloud.store import Store

    config = EvolveConfig.from_yaml(task / "evolve.yaml")
    store = Store(runs / run_id / "fe.db")
    with pytest.raises(ReplayError) as exc:
        run_replay_claim(
            adapter=adapter,
            task_spec=adapter.load_task(task),
            experiment_id=run_id,
            claim_id="C-89f4bdd1-0010",
            factor_id="HDD3_F10",
            library_path=lib,
            source_discovery_dir=runs / run_id / "artifacts" / "discovery",
            art_dir=tmp_path / "art",
            cfg=config.discovery,
            store=store,
            mechanism_llm_call=lambda m: "<rivals>[]</rivals>",
            log_event=lambda t, p: None,
        )
    assert exc.value.error_type == "missing_audit_split_params"
