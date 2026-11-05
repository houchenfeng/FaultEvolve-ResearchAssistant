"""Offline tests for dev-set error profiling and evaluator-aware prompts."""

from __future__ import annotations

import gzip
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest
from typer.testing import CliRunner

from faultevolve.cli import app
from faultevolve.cloud.engine import EvolutionEngine
from faultevolve.cloud.insights import LayeredReflector, summarize_error_profile_diff
from faultevolve.cloud.llm import MockLLM
from faultevolve.cloud.operators import OperatorContext, OperatorType, build_user_message
from faultevolve.cloud.store import Store
from faultevolve.common.schemas import EvaluationResult, NodeArtifact, NodeEvidence
from faultevolve.config import EvolveConfig
from faultevolve.tasks.hdd_adapter import HDDAdapter
from faultevolve.worker.runner import FakeAdapter, FakeTaskSpec


class TrackingReasonLLM(MockLLM):
    def __init__(self) -> None:
        super().__init__()
        self.reasoning_history: list[list[dict[str, str]]] = []

    def chat_for_reasoning(self, messages, temperature=0.2):
        self.reasoning_history.append(list(messages))
        return super().chat_for_reasoning(messages, temperature)


class FakeProfiler(FakeAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.analyze_calls = 0

    def analyze(self, code: str, task_spec: Any, timeout: int) -> dict[str, Any]:
        self.analyze_calls += 1
        return {
            "dev_metrics": {"f1": 0.2, "recall": 0.1},
            "fn_groups": [{"dimension": "model", "value": "A", "n": 12, "share": 1.0, "group_recall": 0.0}],
            "fp_groups": [],
            "silent_share": None,
            "notes": "",
        }

    def objective_brief(self, task_spec: Any) -> str:
        return "ROS marginal +0.5; FAR 0.2%; 推算"


def _engine(tmp_path: Path, adapter, config: EvolveConfig | None = None) -> EvolutionEngine:
    config = config or EvolveConfig()
    config.budget.max_iterations = 2
    store = Store(tmp_path / "fe.db")
    spec = FakeTaskSpec(task_dir=tmp_path)
    return EvolutionEngine(
        config=config,
        task_adapter=adapter,
        task_spec=spec,
        store=store,
        llm=MockLLM(),
        mock=True,
        task_dir=tmp_path,
    )


def test_error_profiler_protocol_optional(tmp_path):
    config = EvolveConfig()
    config.analysis.enabled = True
    config.budget.max_iterations = 1
    adapter = FakeAdapter()
    adapter.set_results([{"validity": 1.0, "combined_score": 22.0, "metric": {}}])
    engine = _engine(tmp_path, adapter, config)
    engine.initialize()
    engine.run(max_iterations=1)
    assert engine.metrics.analysis_calls == 0
    assert engine.metrics.analysis_failures == 0


def _write_synthetic_train(public_dir: Path, n_dates: int = 5) -> None:
    public_dir.mkdir(parents=True, exist_ok=True)
    dates = [f"2024-01-{i+1:02d}" for i in range(n_dates)]
    rows = []
    hist = []
    for i, d in enumerate(dates):
        for j in range(4):
            sn = f"SN_{d}_{j}"
            label = 1 if (i + j) % 2 == 0 else 0
            rows.append({
                "serial_number": sn,
                "model": f"M{i%2}",
                "cutoff_date": d,
                "label": label,
                "weight": 10.0 if label == 0 else 1.0,
            })
            hist.append({
                "date": d,
                "serial_number": sn,
                "model": f"M{i%2}",
                "capacity_bytes": 8 * 1024**4,
                "smart_5_raw": 0,
                "smart_187_raw": 0,
                "smart_197_raw": 0,
                "smart_198_raw": 0,
            })
    pd.DataFrame(rows).to_csv(public_dir / "train_labels.csv", index=False)
    pd.DataFrame(hist).to_csv(public_dir / "train_history.csv.gz", index=False, compression="gzip")


def test_hdd_dev_split_no_eval_only_access(tmp_path, monkeypatch):
    public = tmp_path / "public"
    _write_synthetic_train(public)
    adapter = HDDAdapter(dev_late_fraction=0.4, analysis_min_group_count=10)
    spec = FakeTaskSpec(task_dir=tmp_path)
    monkeypatch.setattr(adapter, "_get_data_dir", lambda _spec: public)

    opened: list[str] = []
    real_open = open

    def track_open(file, *args, **kwargs):
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    with patch("builtins.open", side_effect=track_open):
        dev_dir, late_labels, _ = adapter._build_analysis_data(spec)

    for path in opened:
        assert "eval_only" not in path
        assert "holdout" not in path
        assert path.endswith("train_labels.csv") or path.endswith("train_history.csv.gz") or str(dev_dir) in path

    files = {p.name for p in dev_dir.iterdir()}
    assert files == {"train_labels.csv", "train_history.csv.gz", "val_index.csv", "val_history.csv.gz"}
    val_idx = pd.read_csv(dev_dir / "val_index.csv")
    assert list(val_idx.columns) == ["serial_number", "model", "cutoff_date"]
    assert not late_labels.empty
    adapter.cleanup_analysis_data()


def _pred_program() -> str:
    return '''
import argparse, os, pandas as pd
ap = argparse.ArgumentParser()
ap.add_argument("--data-dir", required=True)
ap.add_argument("--split", required=True)
ap.add_argument("--out", required=True)
args = ap.parse_args()
idx = pd.read_csv(os.path.join(args.data_dir, f"{args.split}_index.csv"))
rows = []
for sn in idx["serial_number"]:
    if str(sn).startswith("A"):
        alarm = 0
    elif str(sn).startswith("F"):
        alarm = 1
    else:
        alarm = 0
    rows.append({"serial_number": sn, "score": 0.5, "alarm": alarm})
pd.DataFrame(rows).to_csv(args.out, index=False)
'''


def _build_group_labels(public: Path) -> None:
    public.mkdir(parents=True, exist_ok=True)
    dates = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    rows = []
    hist = []
    for i in range(12):
        sn = f"A{i:02d}"
        rows.append({"serial_number": sn, "model": "MODEL_A", "cutoff_date": dates[-1], "label": 1, "weight": 1.0})
        hist.append({"date": dates[-1], "serial_number": sn, "model": "MODEL_A", "capacity_bytes": 8*1024**4,
                     "smart_5_raw": 0, "smart_187_raw": 0, "smart_197_raw": 0, "smart_198_raw": 0})
    for i in range(8):
        sn = f"B{i:02d}"
        rows.append({"serial_number": sn, "model": "MODEL_B", "cutoff_date": dates[-1], "label": 1, "weight": 1.0})
        hist.append({"date": dates[-1], "serial_number": sn, "model": "MODEL_B", "capacity_bytes": 8*1024**4,
                     "smart_5_raw": 0, "smart_187_raw": 0, "smart_197_raw": 0, "smart_198_raw": 0})
    for i in range(5):
        sn = f"E{i:02d}"
        rows.append({"serial_number": sn, "model": "MODEL_A", "cutoff_date": dates[0], "label": 0, "weight": 10.0})
        hist.append({"date": dates[0], "serial_number": sn, "model": "MODEL_A", "capacity_bytes": 8*1024**4,
                     "smart_5_raw": 0, "smart_187_raw": 0, "smart_197_raw": 0, "smart_198_raw": 0})
    for i in range(10):
        sn = f"F{i:02d}"
        rows.append({"serial_number": sn, "model": "MODEL_C", "cutoff_date": dates[-1], "label": 0, "weight": 10.0})
        hist.append({"date": dates[-1], "serial_number": sn, "model": "MODEL_C", "capacity_bytes": 8*1024**4,
                     "smart_5_raw": 0, "smart_187_raw": 0, "smart_197_raw": 0, "smart_198_raw": 0})
    for d in dates[:-1]:
        for sn in [f"E{i:02d}" for i in range(5)]:
            hist.append({"date": d, "serial_number": sn, "model": "MODEL_A", "capacity_bytes": 8*1024**4,
                         "smart_5_raw": 0, "smart_187_raw": 0, "smart_197_raw": 0, "smart_198_raw": 0})
    pd.DataFrame(rows).to_csv(public / "train_labels.csv", index=False)
    pd.DataFrame(hist).to_csv(public / "train_history.csv.gz", index=False, compression="gzip")


def test_hdd_analysis_expected_groups(tmp_path, monkeypatch):
    public = tmp_path / "public"
    _build_group_labels(public)
    adapter = HDDAdapter(dev_late_fraction=0.4, analysis_min_group_count=10)
    spec = FakeTaskSpec(task_dir=tmp_path)
    monkeypatch.setattr(adapter, "_get_data_dir", lambda _spec: public)
    result = adapter.analyze(_pred_program(), spec, timeout=60)
    models = {g["value"] for g in result["fn_groups"]}
    assert "MODEL_A" in models
    assert "MODEL_B" not in models
    assert result["dev_metrics"]["n_positive"] == pytest.approx(20.0)
    assert result["dev_metrics"]["n_negative_weighted"] == pytest.approx(100.0)
    blob = json.dumps(result)
    assert "A00" not in blob and "SYN" not in blob
    adapter.cleanup_analysis_data()


def test_analysis_groups_small_cell_suppression():
    adapter = HDDAdapter(analysis_min_group_count=10)

    def make_df(n_fn: int) -> pd.DataFrame:
        rows = []
        for _ in range(n_fn):
            rows.append({
                "label": 1, "alarm": 0, "weight": 1.0, "model": "SMALL",
                "vendor_prefix": "SML", "capacity_bucket": "6-<10TB", "silent": False,
            })
        rows.append({
            "label": 0, "alarm": 0, "weight": 10.0, "model": "SMALL",
            "vendor_prefix": "SML", "capacity_bucket": "6-<10TB", "silent": False,
        })
        return pd.DataFrame(rows)

    fn_groups, _, _, _ = adapter._top_groups(make_df(9))
    assert not any(g["value"] == "SMALL" for g in fn_groups)
    fn_groups2, _, _, _ = adapter._top_groups(make_df(10))
    assert any(g["value"] == "SMALL" and g["n"] >= 10 for g in fn_groups2)


def test_days_to_failure_group_skipped_when_unavailable(tmp_path, monkeypatch):
    public = tmp_path / "public"
    _build_group_labels(public)
    adapter = HDDAdapter()
    spec = FakeTaskSpec(task_dir=tmp_path)
    monkeypatch.setattr(adapter, "_get_data_dir", lambda _spec: public)
    profile = adapter.analyze(_pred_program(), spec, timeout=60)
    assert "days_to_failure" in profile["notes"]
    assert not any(g["dimension"] == "days_to_failure" for g in profile["fn_groups"])
    adapter.cleanup_analysis_data()


def test_analysis_written_to_metric_and_prompt(tmp_path):
    config = EvolveConfig()
    config.analysis.enabled = True
    config.analysis.on_new_best = True
    adapter = FakeProfiler()
    adapter.set_results([
        {"validity": 1.0, "combined_score": 20.0, "metric": {}},
        {"validity": 1.0, "combined_score": 25.0, "metric": {}},
    ])
    engine = _engine(tmp_path, adapter, config)
    engine.initialize()
    engine.run(max_iterations=1)
    root = engine.tree.get_root()
    assert root.evidence.evaluation.metric.get("analysis")
    ctx = OperatorContext(root, engine.task_spec, OperatorType.REFINE)
    ctx.set_error_profile(root.evidence.evaluation.metric["analysis"])
    msg = build_user_message(ctx)
    assert "聚合错例画像" in msg
    assert "不代表因果关系" in msg


def test_analysis_top_k_and_new_best_gating(tmp_path):
    config = EvolveConfig()
    config.analysis.enabled = False
    config.analysis.top_k = 2
    config.analysis.on_new_best = False
    profiler = FakeProfiler()
    profiler.set_results([{"validity": 1.0, "combined_score": 10.0, "metric": {}}])
    engine = _engine(tmp_path, profiler, config)
    engine.initialize()
    config.analysis.enabled = True
    engine.config = config
    from faultevolve.cloud.tree import create_child_node

    parent = engine.tree.get_root()
    for i, score in enumerate([12.0, 11.0, 15.0, 9.0, 14.0], start=1):
        child = create_child_node(
            parent, f"x={i}", "i", "h", OperatorType.REFINE,
        )
        engine.tree.add_node(child)
        engine.tree.update_node_evidence(child.id, NodeEvidence(
            evaluation=EvaluationResult(
                validity=1.0, combined_score=score, cost_time=1.0, metric={},
            ),
        ))
    calls_before = profiler.analyze_calls
    for node in engine.tree.nodes.values():
        if node.id == parent.id:
            continue
        engine._maybe_analyze_node(node, 20.0)
    assert profiler.analyze_calls - calls_before == 2
    top_node = max(
        (n for n in engine.tree.nodes.values() if n.id != parent.id),
        key=lambda n: n.get_score(),
    )
    before = profiler.analyze_calls
    engine._maybe_analyze_node(top_node, 20.0)
    assert profiler.analyze_calls == before


class TimeoutProfiler(FakeAdapter):
    def analyze(self, code, task_spec, timeout):
        raise TimeoutError("analysis timeout")


def test_analysis_failure_nonfatal(tmp_path):
    config = EvolveConfig()
    config.analysis.enabled = True
    adapter = TimeoutProfiler()
    adapter.set_results([
        {"validity": 1.0, "combined_score": 22.0, "metric": {}},
        {"validity": 1.0, "combined_score": 23.0, "metric": {}},
    ])
    engine = _engine(tmp_path, adapter, config)
    engine.initialize()
    events = []
    orig = engine._log_event

    def capture(evt, payload):
        events.append((evt, payload))
        orig(evt, payload)

    engine._log_event = capture
    engine.run(max_iterations=1)
    assert engine.metrics.analysis_failures >= 1
    assert engine.metrics.iterations_done >= 1
    assert any(e[0] == "analysis_failed" for e in events)


def test_objective_brief_in_prompt(tmp_path):
    adapter = FakeProfiler()
    adapter.set_results([{"validity": 1.0, "combined_score": 22.0, "metric": {}}])
    engine = _engine(tmp_path, adapter)
    engine.initialize()
    root = engine.tree.get_root()
    ctx = OperatorContext(root, engine.task_spec)
    ctx.set_objective_brief(engine._objective_brief)
    msg = build_user_message(ctx)
    assert "0.2%" in msg or "FAR" in msg
    assert "推算" in msg
    ctx2 = OperatorContext(root, engine.task_spec)
    assert "## 评估目标与权衡" not in build_user_message(ctx2)


def test_jev_screened_candidate_not_analyzed(tmp_path):
    config = EvolveConfig()
    config.analysis.enabled = True
    profiler = FakeProfiler()
    profiler.set_results([
        {"validity": 1.0, "combined_score": 22.0, "metric": {}},
        {"validity": 1.0, "combined_score": 23.0, "metric": {}},
    ])
    engine = _engine(tmp_path, profiler, config)
    engine.initialize()
    evals_after_init = profiler._call_count
    from faultevolve.cloud.judge import PrescreenResult

    engine._apply_prescreen = lambda *args, **kwargs: PrescreenResult(
        attempted=True, ok=True, decision="skip_invalid", value=0.1,
    )
    engine.config.judge.prescreen = True
    engine.config.judge.audit_rate = 0.0
    engine.run(max_iterations=1)
    assert profiler._call_count == evals_after_init


def test_deferred_evaluation_analyzed_once(tmp_path):
    config = EvolveConfig()
    config.analysis.enabled = True
    config.judge.defer_flush_evals = 1
    profiler = FakeProfiler()
    profiler.set_results([
        {"validity": 1.0, "combined_score": 22.0, "metric": {}},
        {"validity": 1.0, "combined_score": 24.0, "metric": {}},
    ])
    engine = _engine(tmp_path, profiler, config)
    engine.initialize()
    from faultevolve.cloud.judge import PrescreenResult

    def prescreen(parent, child, offered):
        if child.id not in engine.tree.nodes:
            return PrescreenResult(attempted=False, decision="evaluate")
        return PrescreenResult(attempted=True, ok=True, decision="defer", value=0.01)

    engine._apply_prescreen = prescreen
    engine.config.judge.prescreen = True
    before = engine.metrics.iterations_done
    engine.run(max_iterations=1)
    assert engine.metrics.iterations_done == before + 1
    assert profiler.analyze_calls >= 2


def test_reflection_includes_fn_diff():
    parent_analysis = {
        "fn_groups": [{"dimension": "model", "value": "A", "n": 10, "share": 0.5, "group_recall": 0.1}],
        "dev_metrics": {"recall": 0.2},
    }
    child_analysis = {
        "fn_groups": [{"dimension": "model", "value": "B", "n": 10, "share": 0.4, "group_recall": 0.2}],
        "dev_metrics": {"recall": 0.3},
    }
    diff = summarize_error_profile_diff(parent_analysis, child_analysis)
    assert diff["new_top_fn_groups"]
    assert diff["no_longer_top_fn_groups"]
    assert diff["dev_metrics_delta"]["recall"] == pytest.approx(0.1)

    from faultevolve.common.schemas import Node, OperatorType

    llm = TrackingReasonLLM()
    reflector = LayeredReflector(llm, "exp")
    parent = Node(
        id="p", experiment_id="e", branch_id="b", operator=OperatorType.REFINE,
        artifact=NodeArtifact(code="a=1", intent="i", hypothesis="h"),
        evidence=NodeEvidence(evaluation=EvaluationResult(
            validity=1.0, combined_score=20.0, cost_time=1.0,
            metric={"analysis": parent_analysis},
        )),
    )
    child = Node(
        id="c", experiment_id="e", branch_id="b", operator=OperatorType.REFINE,
        artifact=NodeArtifact(code="a=2", intent="i", hypothesis="h"),
        evidence=NodeEvidence(evaluation=EvaluationResult(
            validity=1.0, combined_score=21.0, cost_time=1.0,
            metric={"analysis": child_analysis},
        )),
    )
    reflector.reflect_with_llm(parent, child, 1.0, 0.1)
    assert len(llm.reasoning_history) == 1
    content = llm.reasoning_history[0][0]["content"]
    assert "聚合错例画像变化" in content
    assert "new_top_fn_groups" in content or "MODEL_B" in content or "B" in content


def test_analyze_cli_json(tmp_path, monkeypatch):
    runner = CliRunner()
    program = tmp_path / "p.py"
    program.write_text("x=1\n", encoding="utf-8")
    with patch.object(HDDAdapter, "analyze", return_value={"fn_groups": [], "fp_groups": []}):
        with patch.object(HDDAdapter, "load_task", return_value=FakeTaskSpec(task_dir=tmp_path)):
            with patch.object(HDDAdapter, "static_check", return_value=""):
                result = runner.invoke(
                    app,
                    ["analyze", str(tmp_path), "--program", str(program), "--json"],
                )
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["ok"] is True
    assert "analysis" in data

    with patch.object(HDDAdapter, "load_task", side_effect=RuntimeError("boom /secret/path")):
        result = runner.invoke(
            app,
            ["analyze", str(tmp_path), "--program", str(program), "--json"],
        )
    assert result.exit_code == 1
    assert "/secret" not in result.stdout


def test_cloud_modules_remain_task_agnostic():
    root = Path(__file__).resolve().parents[1] / "src" / "faultevolve" / "cloud"
    banned = re.compile(r"HDD|SMART|Backblaze|hard\s*disk", re.IGNORECASE)
    for name in ("engine.py", "operators.py", "insights.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert not banned.search(text), f"{name} contains domain-specific token"
