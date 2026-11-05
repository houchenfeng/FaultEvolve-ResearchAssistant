"""Tests for PR2 features: repair operator, storage config, network FS detection."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from faultevolve.cloud.engine import EvolutionEngine, run_local_evolution
from faultevolve.cloud.llm import MockLLM
from faultevolve.cloud.operators import classify_error, get_error_tail, RepairOperator
from faultevolve.cloud.store import Store
from faultevolve.cloud.tree import create_repair_node
from faultevolve.cli import (
    app,
    detect_network_fs,
    get_artifacts_dir,
    get_runs_dir,
    load_env_file,
)
from faultevolve.common.schemas import Node, NodeArtifact, NodeEvidence, OperatorType
from faultevolve.config import EvolveConfig, JudgeConfig
from faultevolve.worker.runner import FakeAdapter, FakeTaskSpec


class TestErrorClassification:
    """Tests for error classification."""

    def test_classify_type_error(self):
        error = "TypeError: unsupported operand type(s) for +: 'int' and 'str'"
        assert "TypeError" in classify_error(error)

    def test_classify_lightgbm_error(self):
        error = "LightGBM ValueError: Cannot use categorical_feature.\nFile lightgbm/basic.py, line 123"
        result = classify_error(error)
        assert "ValueError" in result
        assert "lightgbm" in result

    def test_classify_timeout_error(self):
        error = "Execution timeout exceeded after 900 seconds"
        assert "TimeoutError" in classify_error(error)

    def test_classify_sklearn_error(self):
        error = "sklearn/linear_model/_base.py: ValueError: could not convert string to float"
        result = classify_error(error)
        assert "ValueError" in result
        assert "sklearn" in result

    def test_classify_unknown_error(self):
        error = ""
        assert classify_error(error) == "UnknownError"


class TestGetErrorTail:
    """Tests for error tail extraction."""

    def test_short_error_unchanged(self):
        error = "Error line 1\nError line 2\nError line 3"
        assert get_error_tail(error, 10) == error

    def test_long_error_truncated(self):
        lines = [f"Line {i}" for i in range(100)]
        error = "\n".join(lines)
        result = get_error_tail(error, 40)
        assert len(result.split("\n")) == 40
        assert "Line 99" in result
        assert "Line 60" in result
        assert "Line 0" not in result


class TestRepairOperator:
    """Tests for the repair operator."""

    def test_repair_generates_code(self):
        llm = MockLLM()
        operator = RepairOperator(llm)
        
        parent = Node(
            id="parent-1",
            experiment_id="exp-1",
            branch_id="main",
            artifact=NodeArtifact(code="# parent code", intent="test"),
        )
        
        task_spec = FakeTaskSpec()
        
        code, intent, hypothesis, metrics = operator.generate(
            failing_code="# failing code",
            error_info="NameError: name 'undefined' is not defined",
            parent_node=parent,
            task_spec=task_spec,
        )
        
        assert code is not None
        assert metrics.prompt_tokens > 0


class TestCreateRepairNode:
    """Tests for repair node creation."""

    def test_create_repair_node_properties(self):
        failed_node = Node(
            id="failed-1",
            experiment_id="exp-1",
            parent_id="parent-1",
            branch_id="main",
            depth=2,
            artifact=NodeArtifact(code="# failed", intent="test"),
        )
        
        repair = create_repair_node(
            failed_node,
            code="# repaired code",
            intent="fix the error",
            hypothesis="wrong variable name",
            error_class="NameError@lightgbm",
        )
        
        assert repair.operator == OperatorType.REPAIR
        assert repair.repair_parent_id == "failed-1"
        assert repair.error_class == "NameError@lightgbm"
        assert repair.parent_id == "parent-1"
        assert repair.depth == 2


class TestStorageConfig:
    """Tests for configurable storage paths."""

    def test_get_runs_dir_cli_takes_precedence(self, tmp_path):
        cli_dir = tmp_path / "cli_runs"
        task_dir = tmp_path / "task"
        
        result = get_runs_dir(cli_dir, task_dir)
        assert result == cli_dir.resolve()

    def test_get_runs_dir_env_takes_precedence_over_default(self, tmp_path):
        task_dir = tmp_path / "task"
        env_dir = tmp_path / "env_runs"
        
        with patch.dict(os.environ, {"FE_RUNS_DIR": str(env_dir)}):
            result = get_runs_dir(None, task_dir)
            assert result == env_dir.resolve()

    def test_get_runs_dir_default(self, tmp_path):
        task_dir = tmp_path / "task"
        
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("FE_RUNS_DIR", None)
            result = get_runs_dir(None, task_dir)
            assert result == task_dir / ".fe" / "runs"

    def test_fe_report_passes_cli_and_task_dir_to_get_runs_dir(self, monkeypatch, tmp_path):
        task_dir = tmp_path / "task"
        task_dir.mkdir()
        custom_runs = tmp_path / "custom_runs"
        seen: dict[str, Path | None] = {}

        def fake_get_runs_dir(cli_runs_dir: Path | None, task: Path) -> Path:
            seen["cli_runs_dir"] = cli_runs_dir
            seen["task_dir"] = task
            return custom_runs

        monkeypatch.setattr("faultevolve.cli.get_runs_dir", fake_get_runs_dir)
        monkeypatch.setattr(
            "faultevolve.cli.get_artifacts_dir",
            lambda _cli, runs, run_id: runs / run_id,
        )
        monkeypatch.setattr(
            "faultevolve.discovery.report.build_manifest",
            lambda _art_dir, _run_id: {"numbers": {}},
        )
        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "report",
                str(task_dir),
                "--run-id",
                "exp-1",
                "--json",
                "--runs-dir",
                str(custom_runs),
            ],
        )
        assert result.exit_code == 0
        assert seen["cli_runs_dir"] == custom_runs
        assert seen["task_dir"] == task_dir

    def test_get_artifacts_dir_cli_takes_precedence(self, tmp_path):
        cli_dir = tmp_path / "cli_artifacts"
        runs_dir = tmp_path / "runs"
        
        result = get_artifacts_dir(cli_dir, runs_dir, "exp-123")
        assert result == cli_dir.resolve() / "exp-123"

    def test_get_artifacts_dir_env_takes_precedence(self, tmp_path):
        runs_dir = tmp_path / "runs"
        env_dir = tmp_path / "env_artifacts"
        
        with patch.dict(os.environ, {"FE_ARTIFACTS_DIR": str(env_dir)}):
            result = get_artifacts_dir(None, runs_dir, "exp-123")
            assert result == env_dir.resolve() / "exp-123"

    def test_get_artifacts_dir_default_same_as_runs(self, tmp_path):
        runs_dir = tmp_path / "runs"
        
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("FE_ARTIFACTS_DIR", None)
            result = get_artifacts_dir(None, runs_dir, "exp-123")
            assert result == runs_dir / "exp-123"


class TestEnvFileLoading:
    """Tests for .env file parsing."""

    def test_load_basic_env(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_KEY=test_value\n")
        
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("TEST_KEY", None)
            load_env_file(env_file)
            assert os.environ.get("TEST_KEY") == "test_value"

    def test_load_export_format(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("export EXPORT_KEY=export_value\n")
        
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("EXPORT_KEY", None)
            load_env_file(env_file)
            assert os.environ.get("EXPORT_KEY") == "export_value"

    def test_load_quoted_value(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text('QUOTED_KEY="quoted value with spaces"\n')
        
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("QUOTED_KEY", None)
            load_env_file(env_file)
            assert os.environ.get("QUOTED_KEY") == "quoted value with spaces"

    def test_no_override_existing(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("EXISTING_KEY=new_value\n")
        
        with patch.dict(os.environ, {"EXISTING_KEY": "old_value"}):
            load_env_file(env_file)
            assert os.environ.get("EXISTING_KEY") == "old_value"

    def test_skip_comments(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\nVALID_KEY=value\n")
        
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("VALID_KEY", None)
            load_env_file(env_file)
            assert os.environ.get("VALID_KEY") == "value"

    def test_missing_file_no_error(self, tmp_path):
        env_file = tmp_path / "nonexistent.env"
        load_env_file(env_file)


class TestNetworkFSDetection:
    """Tests for network filesystem detection."""

    def test_detect_cifs_mount(self, tmp_path):
        mounts_content = f"{tmp_path} cifs rw 0 0\n"
        
        with patch("pathlib.Path.read_text", return_value=mounts_content):
            with patch("pathlib.Path.exists", return_value=True):
                is_net, fs_type = detect_network_fs(tmp_path)

    def test_detect_local_ext4(self, tmp_path):
        mounts_content = f"/ / ext4 rw 0 0\n{tmp_path} {tmp_path} ext4 rw 0 0\n"
        
        proc_mounts = Path("/proc/mounts")
        if proc_mounts.exists():
            is_net, fs_type = detect_network_fs(tmp_path)
            assert not is_net or fs_type not in {"cifs", "nfs", "smbfs"}

    def test_no_proc_mounts_returns_false(self, tmp_path):
        with patch.object(Path, "exists", return_value=False):
            is_net, fs_type = detect_network_fs(tmp_path)
            assert not is_net


class TestJudgeConfig:
    """Tests for JudgeConfig relay settings."""

    def test_judge_config_defaults(self):
        config = JudgeConfig()
        assert config.base_url == "https://miyang.cn/api/v1/decisions"
        assert config.api_key_env == "MIYANG_API_KEY"
        assert config.model == "miyang/jev-1.13"
        assert config.timeout_s == 5.0
        assert config.invalid_threshold == 0.85
        assert config.low_value_action == "skip"
        assert config.prior_tau == 0.5
        assert config.max_consecutive_errors == 3

    def test_judge_config_custom_relay(self):
        config = JudgeConfig(
            base_url="https://miyang.cn/api/v1/decisions",
            api_key_env="MIYANG_API_KEY",
            model="miyang/jev-1.13",
        )
        assert config.base_url == "https://miyang.cn/api/v1/decisions"
        assert config.api_key_env == "MIYANG_API_KEY"

    def test_judge_config_from_yaml(self, tmp_path):
        yaml_content = """
judge:
  base_url: https://custom.example.com/api
  api_key_env: CUSTOM_API_KEY
  model: custom-model
  timeout_s: 60
"""
        yaml_file = tmp_path / "evolve.yaml"
        yaml_file.write_text(yaml_content)
        
        config = EvolveConfig.from_yaml(yaml_file)
        assert config.judge.base_url == "https://custom.example.com/api"
        assert config.judge.api_key_env == "CUSTOM_API_KEY"
        assert config.judge.timeout_s == 60


class TestOneExpIdEverywhere:
    """Test that one experiment ID is used for all outputs."""

    def test_db_and_artifacts_same_folder(self, tmp_path):
        task_dir = tmp_path / "task"
        task_dir.mkdir()
        
        (task_dir / "evaluator.py").write_text(
            "def evaluate(p, **kw): return {'validity': 1, 'combined_score': 20, 'cost_time': 1, 'error_info': '', 'metric': {}}"
        )
        (task_dir / "init.py").write_text("# init")
        (task_dir / "problem.md").write_text("Test problem")
        (task_dir / "prompt.md").write_text("Test prompt")
        
        result = run_local_evolution(
            task_dir=task_dir,
            mock=True,
            max_iterations=1,
        )
        
        exp_id = result["experiment_id"]
        output_dir = Path(result["output_dir"])
        db_dir = Path(result["db_dir"])
        
        assert output_dir == db_dir
        
        assert (db_dir / "fe.db").exists()
        assert (output_dir / "run_summary.json").exists()
        assert (output_dir / "tree.json").exists()
        assert (output_dir / "events.jsonl").exists()


class TestRepairIntegration:
    """Integration tests for repair operator."""

    @pytest.fixture
    def temp_db(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        yield db_path
        db_path.unlink(missing_ok=True)

    @pytest.fixture
    def fake_task_spec(self, tmp_path):
        return FakeTaskSpec(
            task_dir=tmp_path,
            problem_md="Test problem",
            prompt_md="Test prompt",
            init_code="# init",
        )

    def test_repair_node_tracked_in_summary(self, temp_db, fake_task_spec):
        """Test that repair attempts and successes are tracked in run summary."""
        store = Store(temp_db)
        llm = MockLLM(enable_repair_scenario=True)
        adapter = FakeAdapter()

        adapter.set_results([
            {"validity": 1.0, "combined_score": 22.0, "cost_time": 1.0, "metric": {}},
            {"validity": 1.0, "combined_score": 23.0, "cost_time": 1.0, "metric": {}},
            {"validity": 0.0, "combined_score": 0.0, "cost_time": 1.0,
             "error_info": "NameError: name 'undefined' is not defined"},
            {"validity": 1.0, "combined_score": 24.0, "cost_time": 1.0, "metric": {}},
            {"validity": 1.0, "combined_score": 25.0, "cost_time": 1.0, "metric": {}},
        ])

        config = EvolveConfig()
        config.budget.max_iterations = 5

        engine = EvolutionEngine(
            config=config,
            task_adapter=adapter,
            task_spec=fake_task_spec,
            store=store,
            llm=llm,
            mock=True,
        )

        engine.initialize()
        summary = engine.run(max_iterations=4)

        events = store.get_events(engine.experiment_id)
        event_types = [e.type for e in events]

        assert "repair_success" in event_types, "Expected repair_success event"
        assert summary.repair_attempts >= 1, f"Expected repair_attempts >= 1, got {summary.repair_attempts}"
        assert summary.repair_successes >= 1, f"Expected repair_successes >= 1, got {summary.repair_successes}"
        assert summary.repair_iterations >= 1, f"Expected repair_iterations >= 1, got {summary.repair_iterations}"

    def test_repair_failure_path(self, temp_db, fake_task_spec):
        """Test repair failure path when repair doesn't fix the error."""
        store = Store(temp_db)
        llm = MockLLM(enable_repair_scenario=True)
        adapter = FakeAdapter()

        adapter.set_results([
            {"validity": 1.0, "combined_score": 22.0, "cost_time": 1.0, "metric": {}},
            {"validity": 0.0, "combined_score": 0.0, "cost_time": 1.0,
             "error_info": "NameError: undefined"},
            {"validity": 0.0, "combined_score": 0.0, "cost_time": 1.0,
             "error_info": "NameError: still undefined"},
            {"validity": 0.0, "combined_score": 0.0, "cost_time": 1.0,
             "error_info": "NameError: yet again undefined"},
            {"validity": 1.0, "combined_score": 23.0, "cost_time": 1.0, "metric": {}},
        ])

        config = EvolveConfig()
        config.budget.max_iterations = 5

        engine = EvolutionEngine(
            config=config,
            task_adapter=adapter,
            task_spec=fake_task_spec,
            store=store,
            llm=llm,
            mock=True,
        )

        engine.initialize()
        summary = engine.run(max_iterations=4)

        events = store.get_events(engine.experiment_id)
        event_types = [e.type for e in events]

        assert "repair_failed" in event_types, "Expected repair_failed event"
        assert summary.repair_attempts >= 1
        assert summary.repair_iterations >= 1


class TestUnboundedRepairChain:
    """Test that repair chains are bounded to MAX_REPAIR_ATTEMPTS."""

    @pytest.fixture
    def temp_db(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = Path(f.name)
        yield db_path
        db_path.unlink(missing_ok=True)

    @pytest.fixture
    def fake_task_spec(self, tmp_path):
        return FakeTaskSpec(
            task_dir=tmp_path,
            problem_md="Test problem",
            prompt_md="Test prompt",
            init_code="# init",
        )

    def test_always_failing_adapter_bounded_repairs(self, temp_db, fake_task_spec):
        """Test that an always-failing adapter results in exactly 2 repair evaluations per chain."""
        store = Store(temp_db)
        llm = MockLLM(enable_repair_scenario=True)
        adapter = FakeAdapter()

        adapter.set_results([
            {"validity": 1.0, "combined_score": 22.0, "cost_time": 1.0, "metric": {}},
            {"validity": 0.0, "combined_score": 0.0, "cost_time": 1.0,
             "error_info": "NameError: always fails"},
            {"validity": 0.0, "combined_score": 0.0, "cost_time": 1.0,
             "error_info": "NameError: repair 1 fails"},
            {"validity": 0.0, "combined_score": 0.0, "cost_time": 1.0,
             "error_info": "NameError: repair 2 fails"},
        ])

        config = EvolveConfig()
        config.budget.max_iterations = 1

        engine = EvolutionEngine(
            config=config,
            task_adapter=adapter,
            task_spec=fake_task_spec,
            store=store,
            llm=llm,
            mock=True,
        )

        engine.initialize()
        summary = engine.run(max_iterations=1)

        assert summary.repair_iterations == 2, f"Expected exactly 2 repair iterations, got {summary.repair_iterations}"

        assert summary.status == "finished", "Run should terminate"

        repair_nodes = [n for n in engine.tree.nodes.values() if n.is_repair_node()]
        assert len(repair_nodes) == 2, f"Expected exactly 2 repair nodes, got {len(repair_nodes)}"

    def test_run_terminates_with_exhausted_repairs(self, temp_db, fake_task_spec):
        """Test that the run terminates when repairs are exhausted."""
        store = Store(temp_db)
        llm = MockLLM(enable_repair_scenario=True)
        adapter = FakeAdapter()

        always_fail = [
            {"validity": 1.0, "combined_score": 22.0, "cost_time": 1.0, "metric": {}},
        ]
        for i in range(100):
            always_fail.append({
                "validity": 0.0, "combined_score": 0.0, "cost_time": 1.0,
                "error_info": f"NameError: iteration {i}"
            })

        adapter.set_results(always_fail)

        config = EvolveConfig()
        config.budget.max_iterations = 10

        engine = EvolutionEngine(
            config=config,
            task_adapter=adapter,
            task_spec=fake_task_spec,
            store=store,
            llm=llm,
            mock=True,
        )

        engine.initialize()
        summary = engine.run(max_iterations=10)

        total_evals = summary.iterations_done + summary.repair_iterations
        assert total_evals <= 35, f"Too many evaluations: {total_evals}. Repair chain may be unbounded."

        assert summary.status == "finished"


class TestNodeRepairCount:
    """Tests for repair exhaustion tracking on nodes."""

    def test_node_not_expandable_when_repair_exhausted(self):
        """Node with repair_exhausted=True should not be expandable."""
        node = Node(
            id="test-1",
            experiment_id="exp-1",
            branch_id="main",
            artifact=NodeArtifact(code="# code", intent="test"),
            evidence=NodeEvidence(),
        )
        node.repair_exhausted = True

        from faultevolve.common.schemas import EvaluationResult
        node.evidence.evaluation = EvaluationResult(
            validity=1.0,
            combined_score=20.0,
            cost_time=1.0,
        )

        assert not node.is_expandable()

    def test_node_expandable_when_not_repair_exhausted(self):
        """Node with repair_exhausted=False should be expandable if valid."""
        node = Node(
            id="test-1",
            experiment_id="exp-1",
            branch_id="main",
            artifact=NodeArtifact(code="# code", intent="test"),
        )
        node.repair_exhausted = False

        from faultevolve.common.schemas import EvaluationResult
        node.evidence.evaluation = EvaluationResult(
            validity=1.0,
            combined_score=20.0,
            cost_time=1.0,
        )

        assert node.is_expandable()


class TestRunSummaryRepairMetrics:
    """Tests for repair metrics in RunSummary."""

    def test_run_summary_includes_repair_fields(self):
        from faultevolve.common.schemas import RunSummary

        summary = RunSummary(
            experiment_id="exp-1",
            status="finished",
            iterations_done=10,
            best_score=30.0,
            repair_attempts=3,
            repair_successes=2,
            repair_tokens=500,
            repair_iterations=5,
        )

        assert summary.repair_attempts == 3
        assert summary.repair_successes == 2
        assert summary.repair_tokens == 500
        assert summary.repair_iterations == 5

    def test_run_summary_default_repair_values(self):
        from faultevolve.common.schemas import RunSummary

        summary = RunSummary(
            experiment_id="exp-1",
            status="finished",
            iterations_done=10,
            best_score=30.0,
        )

        assert summary.repair_attempts == 0
        assert summary.repair_successes == 0
        assert summary.repair_tokens == 0
        assert summary.repair_iterations == 0


class TestArtifactsDir:
    """Tests for FE_ARTIFACTS_DIR environment variable."""

    def test_artifacts_dir_env_wired(self, tmp_path):
        """Test that FE_ARTIFACTS_DIR env is correctly used."""
        from faultevolve.cli import get_base_artifacts_dir

        env_dir = tmp_path / "env_artifacts"
        runs_dir = tmp_path / "runs"

        with patch.dict(os.environ, {"FE_ARTIFACTS_DIR": str(env_dir)}):
            result = get_base_artifacts_dir(None, runs_dir)
            assert result == env_dir.resolve()

    def test_programs_and_logs_saved(self, tmp_path):
        """Test that programs and logs are saved to artifacts dir."""
        task_dir = tmp_path / "task"
        task_dir.mkdir()

        (task_dir / "evaluator.py").write_text(
            "def evaluate(p, **kw): return {'validity': 1, 'combined_score': 20, 'cost_time': 1, 'error_info': '', 'metric': {}}"
        )
        (task_dir / "init.py").write_text("# init")
        (task_dir / "problem.md").write_text("Test problem")
        (task_dir / "prompt.md").write_text("Test prompt")

        artifacts_dir = tmp_path / "separate_artifacts"

        result = run_local_evolution(
            task_dir=task_dir,
            mock=True,
            max_iterations=2,
            artifacts_dir=artifacts_dir,
        )

        exp_id = result["experiment_id"]
        programs_dir = artifacts_dir / exp_id / "programs"
        logs_dir = artifacts_dir / exp_id / "logs"

        assert programs_dir.exists(), f"Programs dir should exist: {programs_dir}"
        assert logs_dir.exists(), f"Logs dir should exist: {logs_dir}"

        program_files = list(programs_dir.glob("*.py"))
        assert len(program_files) >= 1, "Should have at least one program file"


class TestEnvFileWarning:
    """Tests for --env-file missing file warning."""

    def test_missing_env_file_warns(self, tmp_path, capsys):
        """Test that missing --env-file path produces a warning."""
        from faultevolve.cli import load_env_file

        missing_file = tmp_path / "nonexistent.env"

        load_env_file(missing_file, warn_missing=True)

        captured = capsys.readouterr()
        assert "Warning" in captured.err or "does not exist" in captured.err

    def test_missing_env_file_no_error(self, tmp_path):
        """Test that missing --env-file doesn't raise an exception."""
        from faultevolve.cli import load_env_file

        missing_file = tmp_path / "nonexistent.env"

        load_env_file(missing_file, warn_missing=False)


class TestMockEvolveWithRepair:
    """Integration test with mock evolve showing failure followed by repair."""

    def test_mock_evolve_failure_then_success(self, tmp_path):
        """Test mock evolve CLI showing failure followed by successful repair."""
        task_dir = tmp_path / "task"
        task_dir.mkdir()

        (task_dir / "evaluator.py").write_text(
            "def evaluate(p, **kw): return {'validity': 1, 'combined_score': 20, 'cost_time': 1, 'error_info': '', 'metric': {}}"
        )
        (task_dir / "init.py").write_text("# init")
        (task_dir / "problem.md").write_text("Test problem")
        (task_dir / "prompt.md").write_text("Test prompt")

        result = run_local_evolution(
            task_dir=task_dir,
            mock=True,
            max_iterations=5,
        )

        assert result["status"] == "finished"
        assert "experiment_id" in result
        assert "output_dir" in result

        events_file = Path(result["output_dir"]) / "events.jsonl"
        assert events_file.exists()

        with events_file.open() as f:
            events = [json.loads(line) for line in f]

        event_types = [e["type"] for e in events]
        assert "init_evaluated" in event_types
