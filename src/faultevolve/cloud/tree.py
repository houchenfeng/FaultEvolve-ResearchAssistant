"""Tree data structure for the evolution tree.

Provides an in-memory view with max-backup value propagation,
parent-child relationships, and subtree operations.
"""

from __future__ import annotations

from typing import Any, Callable

from faultevolve.common.schemas import (
    BranchMemory,
    HypothesisStatus,
    Node,
    NodeArtifact,
    NodeEvidence,
    NodeStatus,
    OperatorType,
)
from faultevolve.cloud.store import Store


class Tree:
    """In-memory tree view for evolution.

    Maintains:
    - Node lookup by ID
    - Parent-child relationships
    - Subtree best scores (max-backup)
    - Visit counts
    """

    def __init__(self, experiment_id: str, store: Store) -> None:
        """Initialize tree.

        Args:
            experiment_id: ID of the experiment
            store: Database store for persistence
        """
        self.experiment_id = experiment_id
        self.store = store
        self.nodes: dict[str, Node] = {}
        self.root_id: str | None = None
        self.subtree_best: dict[str, float] = {}
        #: Called once per node as it enters the tree, after it is persisted.
        #: The engine installs :meth:`EvolutionEngine._log_node_created` here so
        #: that ``node_created`` is emitted by the **only** funnel every node
        #: passes through, instead of at each of the call sites -- a call site
        #: that forgets to log produces an event stream that is quietly missing
        #: a node, and nothing downstream can tell.
        self.on_node_added: Callable[[Node], None] | None = None

    def load_from_store(self) -> None:
        """Load all nodes from the store."""
        nodes = self.store.get_nodes_by_experiment(self.experiment_id)
        for node in nodes:
            self.nodes[node.id] = node
            if node.parent_id is None:
                self.root_id = node.id

        self._rebuild_subtree_best()

    def _rebuild_subtree_best(self) -> None:
        """Rebuild subtree best scores from leaf to root."""
        self.subtree_best.clear()

        for node_id, node in self.nodes.items():
            score = node.get_score()
            self.subtree_best[node_id] = score

        changed = True
        while changed:
            changed = False
            for node_id, node in self.nodes.items():
                current_best = self.subtree_best[node_id]
                for child_id in node.children:
                    if child_id in self.subtree_best:
                        child_best = self.subtree_best[child_id]
                        if child_best > current_best:
                            self.subtree_best[node_id] = child_best
                            changed = True

    def get_node(self, node_id: str) -> Node | None:
        """Get a node by ID."""
        return self.nodes.get(node_id)

    def get_root(self) -> Node | None:
        """Get the root node."""
        if self.root_id is None:
            return None
        return self.nodes.get(self.root_id)

    def get_children(self, node_id: str) -> list[Node]:
        """Get children of a node."""
        node = self.nodes.get(node_id)
        if node is None:
            return []
        return [self.nodes[cid] for cid in node.children if cid in self.nodes]

    def get_expandable_children(self, node_id: str) -> list[Node]:
        """Get expandable children of a node."""
        return [c for c in self.get_children(node_id) if c.is_expandable()]

    def get_regular_children_count(self, node_id: str) -> int:
        """Get count of regular (non-repair, non-invalid) children.

        Used for progressive widening to exclude repair nodes and invalid nodes
        from the child count calculation.

        Args:
            node_id: ID of the node

        Returns:
            Count of children that are not repair or invalid nodes
        """
        children = self.get_children(node_id)
        return sum(
            1 for c in children
            if not c.is_repair_node()
            and c.status not in (NodeStatus.INVALID, NodeStatus.ABANDONED)
        )

    def get_subtree_best_score(self, node_id: str) -> float:
        """Get the best score in the subtree rooted at node_id."""
        return self.subtree_best.get(node_id, 0.0)

    def get_parent(self, node_id: str) -> Node | None:
        """Get the parent of a node."""
        node = self.nodes.get(node_id)
        if node is None or node.parent_id is None:
            return None
        return self.nodes.get(node.parent_id)

    def get_ancestors(self, node_id: str) -> list[Node]:
        """Get all ancestors of a node, from parent to root."""
        ancestors = []
        current = self.get_parent(node_id)
        while current is not None:
            ancestors.append(current)
            current = self.get_parent(current.id)
        return ancestors

    def add_node(self, node: Node) -> None:
        """Add a new node to the tree.

        Also updates the parent's children list and subtree best scores.
        """
        self.nodes[node.id] = node

        if node.parent_id is None:
            self.root_id = node.id
        elif node.parent_id in self.nodes:
            parent = self.nodes[node.parent_id]
            if node.id not in parent.children:
                parent.children.append(node.id)
                self.store.update_node(parent.id, children=parent.children)

        self.store.create_node(node)

        # After the row exists, so a listener that re-reads the node finds it.
        # Before the score propagation below, so the payload is the node as it
        # was born -- a listener must not observe a half-updated subtree.
        if self.on_node_added is not None:
            self.on_node_added(node)

        score = node.get_score()
        self.subtree_best[node.id] = score
        self._propagate_best_score(node.id, score)

    def update_node_evidence(self, node_id: str, evidence: NodeEvidence) -> None:
        """Update a node's evidence and propagate score changes."""
        node = self.nodes.get(node_id)
        if node is None:
            return

        node.evidence = evidence

        if evidence.evaluation is not None:
            if evidence.evaluation.validity >= 1.0:
                node.status = NodeStatus.DONE
            else:
                node.status = NodeStatus.INVALID

        self.store.update_node(
            node_id,
            evidence_json=evidence.model_dump_json(),
            status=node.status.value,
        )

        score = node.get_score()
        self.subtree_best[node_id] = max(self.subtree_best.get(node_id, 0.0), score)
        self._propagate_best_score(node_id, score)

    def _propagate_best_score(self, node_id: str, score: float) -> None:
        """Propagate a score up to ancestors if it's better."""
        for ancestor in self.get_ancestors(node_id):
            current_best = self.subtree_best.get(ancestor.id, 0.0)
            if score > current_best:
                self.subtree_best[ancestor.id] = score
            else:
                break

    def update_node_status(self, node_id: str, status: NodeStatus) -> None:
        """Update a node's status."""
        node = self.nodes.get(node_id)
        if node is None:
            return
        node.status = status
        self.store.update_node(node_id, status=status.value)

    def update_hypothesis_status(self, node_id: str, status: HypothesisStatus) -> None:
        """Update a node's hypothesis status."""
        node = self.nodes.get(node_id)
        if node is None:
            return
        node.hypothesis_status = status
        self.store.update_node(node_id, hypothesis_status=status.value)

    def increment_visit_count(self, node_id: str) -> None:
        """Increment a node's visit count."""
        node = self.nodes.get(node_id)
        if node is None:
            return
        node.visit_count += 1
        self.store.update_node(node_id, visit_count=node.visit_count)

    def increment_expand_count(self, node_id: str) -> None:
        """Increment a node's expand count."""
        node = self.nodes.get(node_id)
        if node is None:
            return
        node.expand_count += 1
        self.store.update_node(node_id, expand_count=node.expand_count)

    def mark_repair_attempted(self, node_id: str) -> None:
        """Mark that repair was attempted for a node."""
        node = self.nodes.get(node_id)
        if node is None:
            return
        node.repair_attempted = True
        self.store.update_node(node_id, repair_attempted=True)

    def increment_repair_count(self, node_id: str) -> int:
        """Increment repair count for a node and return new count."""
        node = self.nodes.get(node_id)
        if node is None:
            return 0
        node.repair_count += 1
        self.store.update_node(node_id, repair_count=node.repair_count)
        return node.repair_count

    def get_repair_chain_root(self, node_id: str) -> Node | None:
        """Find the root of a repair chain by following repair_parent_id.

        The root is the original failed refine node that triggered repairs.
        Returns the node itself if it's not a repair node.

        Args:
            node_id: ID of the node to trace

        Returns:
            The root node of the repair chain, or None if not found
        """
        node = self.nodes.get(node_id)
        if node is None:
            return None

        while node.repair_parent_id is not None:
            parent = self.nodes.get(node.repair_parent_id)
            if parent is None:
                break
            node = parent

        return node

    def mark_repair_exhausted(self, node_id: str) -> None:
        """Mark a node as repair exhausted."""
        node = self.nodes.get(node_id)
        if node is None:
            return
        node.repair_exhausted = True
        self.store.update_node(node_id, repair_exhausted=True)

    def get_repair_chain_length(self, node_id: str) -> int:
        """Get the number of repairs in a chain.

        Follows repair_parent_id to count the chain length from root.

        Args:
            node_id: ID of the node to check

        Returns:
            Number of repair nodes in the chain (0 for non-repair nodes)
        """
        node = self.nodes.get(node_id)
        if node is None:
            return 0

        count = 0
        while node is not None and node.repair_parent_id is not None:
            count += 1
            node = self.nodes.get(node.repair_parent_id)

        return count

    def set_error_class(self, node_id: str, error_class: str) -> None:
        """Set the error class for a node."""
        node = self.nodes.get(node_id)
        if node is None:
            return
        node.error_class = error_class
        self.store.update_node(node_id, error_class=error_class)

    def increment_hypothesis_fail_count(self, node_id: str) -> None:
        """Increment hypothesis fail count for a node."""
        node = self.nodes.get(node_id)
        if node is None:
            return
        node.hypothesis_fail_count += 1
        self.store.update_node(node_id, hypothesis_fail_count=node.hypothesis_fail_count)

    def add_insight_to_node(self, node_id: str, insight_id: str) -> None:
        """Add an insight ID to a node's insight list."""
        node = self.nodes.get(node_id)
        if node is None:
            return
        if insight_id not in node.insight_ids:
            node.insight_ids.append(insight_id)
            self.store.update_node(node_id, insight_ids=node.insight_ids)

    def update_branch_memory(self, node_id: str, branch_memory: BranchMemory) -> None:
        """Update a node's branch memory."""
        node = self.nodes.get(node_id)
        if node is None:
            return
        node.branch_memory = branch_memory
        self.store.update_node(node_id, branch_memory_json=branch_memory.model_dump_json())

    def add_refuted_hypothesis(self, node_id: str, hypothesis: str) -> None:
        """Add a refuted hypothesis to a node's branch memory."""
        node = self.nodes.get(node_id)
        if node is None:
            return
        if hypothesis not in node.branch_memory.refuted_hypotheses:
            node.branch_memory.refuted_hypotheses.append(hypothesis)
            self.store.update_node(node_id, branch_memory_json=node.branch_memory.model_dump_json())

    def get_global_best(self) -> tuple[str | None, float]:
        """Get the best node ID and score across the entire tree."""
        best_id = None
        best_score = 0.0

        for node_id, node in self.nodes.items():
            score = node.get_score()
            if score > best_score:
                best_score = score
                best_id = node_id

        return best_id, best_score

    def get_frontier(self) -> list[Node]:
        """Get all expandable nodes (frontier)."""
        return [n for n in self.nodes.values() if n.is_expandable()]

    def to_export(self) -> dict[str, Any]:
        """Export tree structure for visualization."""
        nodes = []
        edges = []

        for node_id, node in self.nodes.items():
            nodes.append({
                "id": node_id,
                "branch_id": node.branch_id,
                "depth": node.depth,
                "operator": node.operator.value,
                "score": node.get_score(),
                "status": node.status.value,
                "hypothesis_status": node.hypothesis_status.value,
                "intent": node.artifact.intent,
                "visit_count": node.visit_count,
                "adopted_cards": list(node.card_ids),
            })
            if node.parent_id is not None:
                edges.append({
                    "source": node.parent_id,
                    "target": node_id,
                })

        return {
            "experiment_id": self.experiment_id,
            "nodes": nodes,
            "edges": edges,
        }


def create_init_node(experiment_id: str, branch_id: str, code: str, intent: str = "") -> Node:
    """Create the initial node for an experiment."""
    import uuid

    return Node(
        id=str(uuid.uuid4())[:8],
        experiment_id=experiment_id,
        parent_id=None,
        branch_id=branch_id,
        depth=0,
        operator=OperatorType.INIT,
        artifact=NodeArtifact(code=code, intent=intent or "Initial solution"),
        evidence=NodeEvidence(),
        status=NodeStatus.PENDING,
    )


def create_child_node(
    parent: Node,
    code: str,
    intent: str,
    hypothesis: str,
    operator: OperatorType,
) -> Node:
    """Create a child node from a parent."""
    import uuid

    return Node(
        id=str(uuid.uuid4())[:8],
        experiment_id=parent.experiment_id,
        parent_id=parent.id,
        branch_id=parent.branch_id,
        depth=parent.depth + 1,
        operator=operator,
        artifact=NodeArtifact(code=code, intent=intent, hypothesis=hypothesis),
        evidence=NodeEvidence(),
        status=NodeStatus.PENDING,
    )


def create_repair_node(
    failed_node: Node,
    code: str,
    intent: str,
    hypothesis: str,
    error_class: str,
) -> Node:
    """Create a repair node for a failed node.

    The repair node has the failed node as parent and tracks the error class.

    Args:
        failed_node: The node that failed with runtime error
        code: Repaired code
        intent: Description of the repair
        hypothesis: Hypothesis about the fix
        error_class: Classified error type

    Returns:
        New repair node
    """
    import uuid

    return Node(
        id=str(uuid.uuid4())[:8],
        experiment_id=failed_node.experiment_id,
        parent_id=failed_node.parent_id,
        branch_id=failed_node.branch_id,
        depth=failed_node.depth,
        operator=OperatorType.REPAIR,
        artifact=NodeArtifact(code=code, intent=intent, hypothesis=hypothesis),
        evidence=NodeEvidence(),
        status=NodeStatus.PENDING,
        repair_parent_id=failed_node.id,
        error_class=error_class,
    )
