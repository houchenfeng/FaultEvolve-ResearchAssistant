"""Tests for insight extraction and layered reflection."""

import json
import tempfile
from pathlib import Path

import pytest

from faultevolve.cloud.insights import (
    BranchMemoryManager,
    InsightExtractor,
    LayeredReflector,
    get_foreign_insights,
    summarize_error_profile_diff,
)
from faultevolve.cloud.llm import MockLLM
from faultevolve.cloud.store import Store, now_iso
from faultevolve.cloud.tree import Tree, create_child_node, create_init_node
from faultevolve.common.schemas import (
    BranchMemory,
    EvaluationResult,
    Experiment,
    ExperimentConfig,
    Insight,
    Node,
    NodeArtifact,
    NodeEvidence,
    NodeStatus,
    OperatorType,
)
from faultevolve.common.textutil import sanitize_error_info


@pytest.fixture
def temp_db():
    """Create a temporary database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    yield db_path
    db_path.unlink(missing_ok=True)


@pytest.fixture
def store(temp_db):
    """Create a store instance."""
    return Store(temp_db)


@pytest.fixture
def experiment_id():
    return "test-exp"


@pytest.fixture
def setup_experiment(store, experiment_id):
    """Set up an experiment for testing."""
    experiment = Experiment(
        id=experiment_id,
        name="test-experiment",
        status="running",
        config=ExperimentConfig(
            max_iterations=10,
            max_tokens=10000,
        ),
        problem_md="Test problem",
        prompt_md="Test prompt",
        created_at=now_iso(),
    )
    store.create_experiment(experiment)
    return experiment


@pytest.fixture
def mock_llm():
    """Create a mock LLM."""
    return MockLLM()


class TestLayeredReflector:
    """Tests for LayeredReflector class."""

    def test_reflect_implementation_syntax_error(self, mock_llm, experiment_id):
        """Test implementation layer reflection with syntax error."""
        reflector = LayeredReflector(mock_llm, experiment_id)

        parent = create_init_node(experiment_id, "main", "# code", "intent")
        child = create_child_node(parent, "# bad code", "intent", "hypothesis", OperatorType.REFINE)

        result = reflector.reflect_implementation(parent, child, "SyntaxError: invalid syntax")

        assert result["layer"] == "implementation"
        assert len(result["causes"]) >= 1
        assert result["causes"][0]["layer"] == "implementation"
        assert "syntax" in result["causes"][0]["cause"].lower()
        assert "repair_hint" in result

    def test_reflect_implementation_timeout(self, mock_llm, experiment_id):
        """Test implementation layer reflection with timeout error."""
        reflector = LayeredReflector(mock_llm, experiment_id)

        parent = create_init_node(experiment_id, "main", "# code", "intent")
        child = create_child_node(parent, "# slow code", "intent", "hypothesis", OperatorType.REFINE)

        result = reflector.reflect_implementation(parent, child, "TimeoutError: Execution timeout exceeded")

        assert result["layer"] == "implementation"
        assert any("timeout" in c["cause"].lower() for c in result["causes"])

    def test_reflect_implementation_static_check(self, mock_llm, experiment_id):
        """Test implementation layer reflection with static check failure."""
        reflector = LayeredReflector(mock_llm, experiment_id)

        parent = create_init_node(experiment_id, "main", "# code", "intent")
        child = create_child_node(parent, "import os\nos.system('rm -rf /')", "intent", "hyp", OperatorType.REFINE)

        result = reflector.reflect_implementation(parent, child, "Static check failed: dangerous pattern")

        assert result["layer"] == "implementation"
        assert any("static check" in c["cause"].lower() for c in result["causes"])

    def test_reflect_with_llm_design_layer(self, mock_llm, experiment_id):
        """Test LLM reflection returns design layer analysis."""
        reflector = LayeredReflector(mock_llm, experiment_id)

        parent = create_init_node(experiment_id, "main", "# code v1", "intent")
        parent.evidence = NodeEvidence(
            evaluation=EvaluationResult(
                validity=1.0,
                combined_score=20.0,
                cost_time=1.0,
                metric={"f1": 0.25},
            )
        )

        child = create_child_node(parent, "# code v2", "intent", "hypothesis", OperatorType.REFINE)
        child.evidence = NodeEvidence(
            evaluation=EvaluationResult(
                validity=1.0,
                combined_score=18.0,
                cost_time=1.0,
                metric={"f1": 0.22},
            )
        )

        result, metrics = reflector.reflect_with_llm(parent, child, delta=-2.0, noise_delta=0.5)

        assert result["layer"] in ("design", "implementation", "hypothesis")
        assert "change_summary" in result
        assert "mechanism" in result
        assert "causes" in result
        assert metrics.prompt_tokens > 0

    def test_reflect_with_llm_counts_tokens(self, mock_llm, experiment_id):
        """Test that reflection properly counts tokens."""
        reflector = LayeredReflector(mock_llm, experiment_id)

        parent = create_init_node(experiment_id, "main", "# code v1", "intent")
        parent.evidence = NodeEvidence(
            evaluation=EvaluationResult(
                validity=1.0,
                combined_score=20.0,
                cost_time=1.0,
                metric={},
            )
        )

        child = create_child_node(parent, "# code v2", "intent", "hypothesis", OperatorType.REFINE)
        child.evidence = NodeEvidence(
            evaluation=EvaluationResult(
                validity=1.0,
                combined_score=22.0,
                cost_time=1.0,
                metric={},
            )
        )

        result, metrics = reflector.reflect_with_llm(parent, child, delta=2.0, noise_delta=0.5)

        assert reflector.total_reflect_tokens > 0
        assert reflector.total_reflect_tokens == metrics.prompt_tokens + metrics.completion_tokens

    def test_json_fallback_on_invalid_response(self, mock_llm, experiment_id):
        """Test fallback when LLM returns invalid JSON."""
        mock_llm.set_reasoning_responses(["This is not valid JSON at all"])
        reflector = LayeredReflector(mock_llm, experiment_id)

        parent = create_init_node(experiment_id, "main", "# code v1", "intent")
        parent.evidence = NodeEvidence(
            evaluation=EvaluationResult(
                validity=1.0,
                combined_score=20.0,
                cost_time=1.0,
                metric={},
            )
        )

        child = create_child_node(parent, "# code v2", "intent", "hypothesis", OperatorType.REFINE)
        child.evidence = NodeEvidence(
            evaluation=EvaluationResult(
                validity=1.0,
                combined_score=15.0,
                cost_time=1.0,
                metric={},
            )
        )

        result, _ = reflector.reflect_with_llm(parent, child, delta=-5.0, noise_delta=0.5)

        assert "layer" in result
        assert result["layer"] == "hypothesis"
        assert "causes" in result

    def test_json_fallback_on_partial_json(self, mock_llm, experiment_id):
        """Test fallback when JSON is missing required fields."""
        mock_llm.set_reasoning_responses(['{"layer": "design"}'])
        reflector = LayeredReflector(mock_llm, experiment_id)

        parent = create_init_node(experiment_id, "main", "# code v1", "intent")
        parent.evidence = NodeEvidence(
            evaluation=EvaluationResult(
                validity=1.0,
                combined_score=20.0,
                cost_time=1.0,
                metric={},
            )
        )

        child = create_child_node(parent, "# code v2", "intent", "hypothesis", OperatorType.REFINE)
        child.evidence = NodeEvidence(
            evaluation=EvaluationResult(
                validity=1.0,
                combined_score=19.0,
                cost_time=1.0,
                metric={},
            )
        )

        result, _ = reflector.reflect_with_llm(parent, child, delta=-1.0, noise_delta=0.5)

        assert result["layer"] == "design"
        assert "causes" in result


class TestLayerAttribution:
    """Tests for three-layer attribution rules."""

    def test_invalid_node_gets_implementation_layer(self, mock_llm, experiment_id):
        """Implementation layer is used for invalid nodes (rule-based, no LLM)."""
        reflector = LayeredReflector(mock_llm, experiment_id)

        parent = create_init_node(experiment_id, "main", "# code", "intent")
        child = create_child_node(parent, "# bad", "intent", "hyp", OperatorType.REFINE)

        result = reflector.reflect_implementation(parent, child, "RuntimeError: something failed")

        assert result["layer"] == "implementation"
        assert "repair_hint" in result

    def test_small_delta_gets_design_layer(self, mock_llm, experiment_id):
        """Design layer for moderate negative delta (-delta to -2*delta)."""
        mock_llm.set_reasoning_responses([
            '{"layer": "design", "change_summary": "test", "mechanism": "test", "conditions": "", "tags": [], "affects": {}, "causes": []}'
        ])
        reflector = LayeredReflector(mock_llm, experiment_id)

        result = reflector._parse_reflection_json(
            '{"layer": "design", "change_summary": "x", "mechanism": "y", "conditions": "", "tags": [], "affects": {}, "causes": []}',
            delta=-1.0,
            noise_delta=0.5,
        )

        assert result["layer"] == "design"

    def test_large_delta_gets_hypothesis_layer(self, mock_llm, experiment_id):
        """Hypothesis layer for large negative delta (> 2*delta)."""
        reflector = LayeredReflector(mock_llm, experiment_id)

        result = reflector._default_reflection(delta=-5.0, noise_delta=0.5)

        assert result["layer"] == "hypothesis"


class TestBranchMemoryManager:
    """Tests for branch memory and propagation."""

    def test_propagate_insight_to_ancestors(self, store, experiment_id, setup_experiment):
        """Test that insights propagate up the ancestor chain."""
        tree = Tree(experiment_id, store)

        root = create_init_node(experiment_id, "main", "# root", "root intent")
        tree.add_node(root)

        child1 = create_child_node(root, "# child1", "intent1", "hyp1", OperatorType.REFINE)
        tree.add_node(child1)

        child2 = create_child_node(child1, "# child2", "intent2", "hyp2", OperatorType.REFINE)
        tree.add_node(child2)

        insight = Insight(
            id="insight1",
            origin_node=child2.id,
            branch_id="main",
            polarity=1,
            change_summary="Test improvement",
            mechanism="Test mechanism",
            conditions="",
            tags=["test"],
            delta=2.0,
            z_score=4.0,
            alpha=1.0,
            beta=1.0,
            created_at=now_iso(),
        )

        manager = BranchMemoryManager(store, tree, top_k=5)
        manager.propagate_insight(insight, child2, experiment_id)

        root_updated = store.get_node(root.id)
        child1_updated = store.get_node(child1.id)

        assert "insight1" in root_updated.branch_memory.top_insight_ids
        assert "insight1" in child1_updated.branch_memory.top_insight_ids

    def test_top_k_propagation_limits_insights(self, store, experiment_id, setup_experiment):
        """Test that only top-k insights by |z-score| are kept."""
        tree = Tree(experiment_id, store)

        root = create_init_node(experiment_id, "main", "# root", "root intent")
        tree.add_node(root)

        child = create_child_node(root, "# child", "intent", "hyp", OperatorType.REFINE)
        tree.add_node(child)

        manager = BranchMemoryManager(store, tree, top_k=2)

        for i, z in enumerate([1.0, 5.0, 3.0, 0.5]):
            insight = Insight(
                id=f"insight{i}",
                origin_node=child.id,
                branch_id="main",
                polarity=1,
                change_summary=f"Insight {i}",
                mechanism="",
                conditions="",
                tags=[],
                delta=z,
                z_score=z,
                alpha=1.0,
                beta=1.0,
                created_at=now_iso(),
            )
            manager.propagate_insight(insight, child, experiment_id)

        root_updated = store.get_node(root.id)
        top_ids = root_updated.branch_memory.top_insight_ids

        assert len(top_ids) == 2
        assert "insight1" in top_ids
        assert "insight2" in top_ids

    def test_get_branch_insights(self, store, experiment_id, setup_experiment):
        """Test retrieving insights from branch memory."""
        tree = Tree(experiment_id, store)

        root = create_init_node(experiment_id, "main", "# root", "intent")
        tree.add_node(root)

        insight = Insight(
            id="test-insight",
            origin_node=root.id,
            branch_id="main",
            polarity=1,
            change_summary="Test",
            mechanism="",
            conditions="",
            tags=[],
            delta=1.0,
            z_score=2.0,
            alpha=1.0,
            beta=1.0,
            created_at=now_iso(),
        )
        store.create_insight(insight, experiment_id)

        memory = BranchMemory(
            summary="",
            top_insight_ids=["test-insight"],
            refuted_hypotheses=[],
        )
        tree.update_branch_memory(root.id, memory)

        manager = BranchMemoryManager(store, tree)
        insights = manager.get_branch_insights(store.get_node(root.id), experiment_id)

        assert len(insights) == 1
        assert insights[0].id == "test-insight"


class TestSanitization:
    """Tests for error info sanitization (redaction)."""

    def test_sanitize_removes_paths(self):
        """Test that absolute paths are redacted."""
        error = "FileNotFoundError: /home/user/project/data/secret.csv not found"
        sanitized = sanitize_error_info(error)

        assert "/home/user/project/data/secret.csv" not in sanitized
        assert "<path>" in sanitized

    def test_sanitize_removes_serial_numbers(self):
        """Test that serial-number-like IDs are redacted."""
        error = "Error processing disk ZTXXXXXX12345678"
        sanitized = sanitize_error_info(error)

        assert "ZTXXXXXX12345678" not in sanitized
        assert "<id>" in sanitized

    def test_sanitize_truncates_long_errors(self):
        """Test that long error messages are truncated."""
        error = "A" * 1000
        sanitized = sanitize_error_info(error, max_chars=100)

        assert len(sanitized) <= 100

    def test_sanitize_preserves_useful_info(self):
        """Test that error type and line info are preserved."""
        error = "SyntaxError: invalid syntax at line 42"
        sanitized = sanitize_error_info(error)

        assert "SyntaxError" in sanitized
        assert "invalid syntax" in sanitized


class TestForeignInsights:
    """Tests for cross-branch insight retrieval."""

    def test_get_foreign_insights_excludes_own_branch(self, store, experiment_id, setup_experiment):
        """Test that foreign insights exclude the node's own branch."""
        own_insight = Insight(
            id="own-insight",
            origin_node="node1",
            branch_id="branch-a",
            polarity=1,
            change_summary="Own",
            mechanism="",
            conditions="",
            tags=[],
            delta=1.0,
            z_score=2.0,
            alpha=1.0,
            beta=1.0,
            created_at=now_iso(),
        )
        store.create_insight(own_insight, experiment_id)

        foreign_insight = Insight(
            id="foreign-insight",
            origin_node="node2",
            branch_id="branch-b",
            polarity=1,
            change_summary="Foreign",
            mechanism="",
            conditions="",
            tags=[],
            delta=2.0,
            z_score=3.0,
            alpha=1.0,
            beta=1.0,
            created_at=now_iso(),
        )
        store.create_insight(foreign_insight, experiment_id)

        node = Node(
            id="test-node",
            experiment_id=experiment_id,
            branch_id="branch-a",
            depth=0,
            parent_id=None,
            children=[],
            visit_count=0,
            expand_count=0,
            hypothesis_fail_count=0,
            repair_attempted=False,
            insight_ids=[],
            artifact=NodeArtifact(code="# test"),
            evidence=NodeEvidence(),
            branch_memory=BranchMemory(),
            status=NodeStatus.PENDING,
            created_at=now_iso(),
        )
        store.create_node(node)

        positive, negative = get_foreign_insights(
            node, store, experiment_id, top_k_positive=5, top_k_negative=5
        )

        foreign_ids = [i["id"] for i in positive]
        assert "foreign-insight" in foreign_ids
        assert "own-insight" not in foreign_ids


def test_summarize_error_profile_diff_empty():
    assert summarize_error_profile_diff(None, {}) == {}
    assert summarize_error_profile_diff({"fn_groups": []}, None) == {}


def test_summarize_error_profile_diff_groups_and_share():
    parent = {
        "fn_groups": [{"dimension": "model", "value": "A", "share": 0.6, "n": 10}],
        "dev_metrics": {"f1": 0.2},
    }
    child = {
        "fn_groups": [
            {"dimension": "model", "value": "B", "share": 0.5, "n": 8},
            {"dimension": "model", "value": "A", "share": 0.4, "n": 10},
        ],
        "dev_metrics": {"f1": 0.25},
    }
    diff = summarize_error_profile_diff(parent, child)
    assert diff["new_top_fn_groups"][0]["value"] == "B"
    assert diff["no_longer_top_fn_groups"] == []
    assert diff["share_delta"][0]["share_delta"] == pytest.approx(-0.2)
    assert diff["dev_metrics_delta"]["f1"] == pytest.approx(0.05)
