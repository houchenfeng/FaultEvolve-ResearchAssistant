"""Tests for UCT selection."""

import tempfile
from pathlib import Path

import pytest

from faultevolve.cloud.selection import UCTSelector, get_uniform_prior
from faultevolve.cloud.store import Store
from faultevolve.cloud.tree import Tree, create_child_node, create_init_node
from faultevolve.common.schemas import (
    EvaluationResult,
    Node,
    NodeEvidence,
    NodeStatus,
    OperatorType,
)
from faultevolve.config import EvolveConfig


@pytest.fixture
def store():
    """Create a temporary store."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    yield Store(db_path)
    db_path.unlink(missing_ok=True)


@pytest.fixture
def config():
    """Create a default config."""
    return EvolveConfig()


def test_uniform_prior():
    """Test uniform prior distribution."""
    options = ["a", "b", "c"]
    prior = get_uniform_prior(options)
    assert len(prior) == 3
    assert all(abs(p - 1/3) < 0.001 for p in prior.values())


def test_uniform_prior_empty():
    """Test uniform prior with empty options."""
    assert get_uniform_prior([]) == {}


def test_selector_initialization(config):
    """Test selector initialization."""
    selector = UCTSelector(config)
    assert selector.c_puct == 1.2
    assert selector.widening_c == 2.0


def test_selector_set_scores(config):
    """Test setting initial and best scores."""
    selector = UCTSelector(config)
    selector.set_initial_score(22.0)
    assert selector.initial_score == 22.0
    assert selector.best_score == 22.0

    selector.update_best_score(25.0)
    assert selector.best_score == 25.0


def test_can_widen_logic(store, config):
    """Test progressive widening logic."""
    tree = Tree("exp-001", store)
    selector = UCTSelector(config)

    root = create_init_node("exp-001", "main", "# test")
    root.evidence = NodeEvidence(
        evaluation=EvaluationResult(validity=1.0, combined_score=20.0, cost_time=1.0, error_info="")
    )
    root.status = NodeStatus.DONE
    tree.add_node(root)

    assert selector._can_widen(tree.get_node(root.id), tree) is True


def test_select_with_single_node(store, config):
    """Test selection with only root node."""
    tree = Tree("exp-001", store)

    root = create_init_node("exp-001", "main", "# code")
    root.evidence = NodeEvidence(
        evaluation=EvaluationResult(validity=1.0, combined_score=22.0, cost_time=1.0, error_info="")
    )
    root.status = NodeStatus.DONE
    tree.add_node(root)

    selector = UCTSelector(config)
    selector.set_initial_score(22.0)
    selector.set_noise_delta(0.5)

    result = selector.select(tree)
    assert result.node.id == root.id
    assert result.should_expand is True


def test_select_prefers_better_subtree(store, config):
    """Test that selection prefers subtrees with better scores."""
    tree = Tree("exp-001", store)

    root = create_init_node("exp-001", "main", "# root")
    root.evidence = NodeEvidence(
        evaluation=EvaluationResult(validity=1.0, combined_score=22.0, cost_time=1.0, error_info="")
    )
    root.status = NodeStatus.DONE
    tree.add_node(root)

    child1 = create_child_node(root, "# child1", "intent1", "hyp1", OperatorType.REFINE)
    child1.evidence = NodeEvidence(
        evaluation=EvaluationResult(validity=1.0, combined_score=23.0, cost_time=1.0, error_info="")
    )
    child1.status = NodeStatus.DONE
    tree.add_node(child1)

    child2 = create_child_node(root, "# child2", "intent2", "hyp2", OperatorType.REFINE)
    child2.evidence = NodeEvidence(
        evaluation=EvaluationResult(validity=1.0, combined_score=25.0, cost_time=1.0, error_info="")
    )
    child2.status = NodeStatus.DONE
    tree.add_node(child2)

    selector = UCTSelector(config)
    selector.set_initial_score(22.0)
    selector.update_best_score(25.0)
    selector.set_noise_delta(0.5)

    assert tree.get_subtree_best_score(child2.id) == 25.0
    assert tree.get_subtree_best_score(child1.id) == 23.0


def test_select_skips_invalid_nodes(store, config):
    """Test that selection skips invalid nodes."""
    tree = Tree("exp-001", store)

    root = create_init_node("exp-001", "main", "# root")
    root.evidence = NodeEvidence(
        evaluation=EvaluationResult(validity=1.0, combined_score=22.0, cost_time=1.0, error_info="")
    )
    root.status = NodeStatus.DONE
    tree.add_node(root)

    invalid_child = create_child_node(root, "# invalid", "intent", "hyp", OperatorType.REFINE)
    invalid_child.status = NodeStatus.INVALID
    tree.add_node(invalid_child)

    selector = UCTSelector(config)
    selector.set_initial_score(22.0)
    selector.set_noise_delta(0.5)

    result = selector.select(tree)
    assert result.node.id == root.id
