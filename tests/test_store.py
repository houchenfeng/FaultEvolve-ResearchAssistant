"""Tests for SQLite store."""

import tempfile
from pathlib import Path

import pytest

from faultevolve.cloud.store import Store
from faultevolve.common.schemas import (
    BranchMemory,
    Event,
    Experiment,
    ExperimentConfig,
    HypothesisStatus,
    Insight,
    LLMCall,
    Node,
    NodeArtifact,
    NodeEvidence,
    NodeStatus,
    OperatorType,
)


@pytest.fixture
def store():
    """Create a temporary store."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    yield Store(db_path)
    db_path.unlink(missing_ok=True)


def test_create_and_get_experiment(store):
    """Test creating and retrieving an experiment."""
    exp = Experiment(
        id="exp-001",
        name="Test Experiment",
        status="running",
        config=ExperimentConfig(max_iterations=100),
        problem_md="Test problem",
        prompt_md="Test prompt",
    )
    store.create_experiment(exp)

    retrieved = store.get_experiment("exp-001")
    assert retrieved is not None
    assert retrieved.id == "exp-001"
    assert retrieved.name == "Test Experiment"
    assert retrieved.config.max_iterations == 100


def test_update_experiment(store):
    """Test updating experiment fields."""
    exp = Experiment(id="exp-002", name="Test")
    store.create_experiment(exp)

    store.update_experiment(
        "exp-002",
        status="finished",
        best_score=25.5,
        iterations_done=10,
    )

    retrieved = store.get_experiment("exp-002")
    assert retrieved.status == "finished"
    assert retrieved.best_score == 25.5
    assert retrieved.iterations_done == 10


def test_create_and_get_node(store):
    """Test creating and retrieving a node."""
    node = Node(
        id="node-001",
        experiment_id="exp-001",
        parent_id=None,
        branch_id="main",
        depth=0,
        operator=OperatorType.INIT,
        artifact=NodeArtifact(code="# test", intent="Initial"),
        status=NodeStatus.DONE,
    )
    store.create_node(node)

    retrieved = store.get_node("node-001")
    assert retrieved is not None
    assert retrieved.id == "node-001"
    assert retrieved.operator == OperatorType.INIT
    assert retrieved.artifact.code == "# test"


def test_update_node(store):
    """Test updating node fields."""
    node = Node(
        id="node-002",
        experiment_id="exp-001",
        branch_id="main",
        operator=OperatorType.REFINE,
        artifact=NodeArtifact(code="# code"),
    )
    store.create_node(node)

    store.update_node(
        "node-002",
        status="done",
        visit_count=5,
        children=["node-003", "node-004"],
    )

    retrieved = store.get_node("node-002")
    assert retrieved.status == NodeStatus.DONE
    assert retrieved.visit_count == 5
    assert retrieved.children == ["node-003", "node-004"]


def test_get_nodes_by_experiment(store):
    """Test retrieving all nodes for an experiment."""
    for i in range(3):
        node = Node(
            id=f"node-{i}",
            experiment_id="exp-001",
            branch_id="main",
            operator=OperatorType.REFINE,
            artifact=NodeArtifact(code=f"# code {i}"),
        )
        store.create_node(node)

    nodes = store.get_nodes_by_experiment("exp-001")
    assert len(nodes) == 3


def test_create_and_get_insight(store):
    """Test creating and retrieving insights."""
    insight = Insight(
        id="ins-001",
        origin_node="node-001",
        branch_id="main",
        polarity=1,
        change_summary="Added feature X",
        mechanism="Feature X improves recall",
        delta=2.5,
        z_score=1.25,
    )
    store.create_insight(insight, "exp-001")

    insights = store.get_insights_by_experiment("exp-001")
    assert len(insights) == 1
    assert insights[0].change_summary == "Added feature X"


def test_create_event(store):
    """Test creating and retrieving events."""
    event = Event(
        experiment_id="exp-001",
        type="iteration_complete",
        payload={"node_id": "node-001", "score": 22.5},
    )
    store.create_event(event)

    events = store.get_events("exp-001")
    assert len(events) == 1
    assert events[0].type == "iteration_complete"
    assert events[0].payload["score"] == 22.5


def test_create_llm_call(store):
    """Test recording LLM calls."""
    llm_call = LLMCall(
        id="llm-001",
        experiment_id="exp-001",
        node_id="node-001",
        purpose="refine",
        model="qwen3-coder-plus",
        prompt_tokens=1000,
        completion_tokens=500,
        latency_ms=2000,
    )
    store.create_llm_call(llm_call)


def test_claim_tables_crud(store):
    """CRUD for discovery claim tables."""
    claim = {
        "id": "C-1",
        "origin_node_id": "n1",
        "source": "insight",
        "prereg_hash": "hash1",
        "status": "proposed",
        "grade": None,
        "title": "t",
    }
    store.create_claim("exp-001", claim, round_idx=1)
    claims = store.get_claims("exp-001")
    assert len(claims) == 1
    assert claims[0]["id"] == "C-1"

    store.update_claim("C-1", status="graded", grade="discovered")
    with store._conn() as conn:
        row = conn.execute("SELECT status, grade FROM claim WHERE id = ?", ("C-1",)).fetchone()
    assert row["status"] == "graded"
    assert row["grade"] == "discovered"

    store.create_claim_test("C-1", "exp-001", "confirm", {"p": 0.01})
    tests = store.get_claim_tests("C-1")
    assert len(tests) == 1
    assert tests[0]["p"] == 0.01

    store.record_discovered_card("D-exp-001", "C-1", "exp-001", "discovered")
    cards = store.get_discovered_cards("exp-001")
    assert len(cards) == 1
    assert cards[0]["card_id"] == "D-exp-001"


def test_store_reopen_compatible(tmp_path):
    """Re-opening an existing DB applies new DDL without error."""
    db_path = tmp_path / "legacy.db"
    s1 = Store(db_path)
    s1.create_experiment(Experiment(id="exp-old", name="legacy"))
    del s1
    s2 = Store(db_path)
    assert s2.get_experiment("exp-old") is not None
    s2.create_claim("exp-old", {"id": "C-x", "source": "top_node"}, round_idx=0)
    assert len(s2.get_claims("exp-old")) == 1
