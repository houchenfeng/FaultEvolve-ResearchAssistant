"""Node selection for the evolution tree.

Implements UCT (Upper Confidence Bound for Trees) selection with:
- Progressive widening for controlling tree breadth
- Max-backup value propagation
- Hooks for Jev prior integration (returns uniform when not available)
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

from faultevolve.common.schemas import Node, NodeStatus
from faultevolve.cloud.tree import Tree
from faultevolve.config import EvolveConfig

SOFTMAX_TEMP = 0.1


def _num(metric: dict[str, Any], key: str) -> float | None:
    if key not in metric:
        return None
    value = metric[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return float(value)


class EliteArchive:
    """Top-m archives for rank and threshold quality."""

    def __init__(self, m: int) -> None:
        self.m = m
        self.rank: list[tuple[float, str]] = []
        self.threshold: list[tuple[float, str]] = []

    def update(self, node_id: str, rank_q: float | None, thr_q: float | None) -> None:
        if self.m == 0:
            return
        if rank_q is not None:
            self.rank = [(q, nid) for q, nid in self.rank if nid != node_id]
            self.rank.append((rank_q, node_id))
            self.rank.sort(key=lambda x: (-x[0], x[1]))
            self.rank = self.rank[: self.m]
        if thr_q is not None:
            self.threshold = [(q, nid) for q, nid in self.threshold if nid != node_id]
            self.threshold.append((thr_q, node_id))
            self.threshold.sort(key=lambda x: (-x[0], x[1]))
            self.threshold = self.threshold[: self.m]

    def ids(self) -> list[str]:
        return [nid for _, nid in self.rank] + [nid for _, nid in self.threshold]

    def sizes(self) -> dict[str, int]:
        return {"rank": len(self.rank), "threshold": len(self.threshold)}


@dataclass
class SelectionResult:
    """Result of node selection."""
    node: Node
    should_expand: bool
    prior: dict[str, float]


class UCTSelector:
    """UCT-based node selector with progressive widening.

    This implements a simplified J-PUCT where tau=0 (uniform prior),
    equivalent to standard UCT. Hooks are provided for Jev prior integration.
    """

    def __init__(self, config: EvolveConfig) -> None:
        """Initialize selector.

        Args:
            config: Evolution configuration
        """
        self.c_puct = config.selection.c_puct
        self.kappa = config.selection.kappa_noise
        self.widening_c = config.widening.C
        self.widening_alpha = config.widening.alpha
        self.initial_score: float = 0.0
        self.best_score: float = 0.0
        self.noise_delta: float = config.selection.kappa_noise * 0.5
        self.node_values: dict[str, float] = {}
        self.prior_tau = 0.0
        self.prior_enabled = False
        self.value_cfg = config.selection.value
        self._value_rng = random.Random(config.seed)
        self.elite = EliteArchive(self.value_cfg.elite_m)
        self._rank_keys = list(self.value_cfg.rank_keys)
        self._thr_keys = list(self.value_cfg.threshold_keys)
        self._noise_key = self.value_cfg.noise_key
        self._ref_metric: dict[str, Any] = {}
        self._multi_fallback_logged = False
        self._memo: dict[str, float | None] = {}

    def set_objective_spec(
        self,
        rank_keys: list[str],
        threshold_keys: list[str],
        noise_key: str,
    ) -> None:
        if not self._rank_keys and rank_keys:
            self._rank_keys = list(rank_keys)
        if not self._thr_keys and threshold_keys:
            self._thr_keys = list(threshold_keys)
        if not self._noise_key and noise_key:
            self._noise_key = noise_key

    def set_reference(self, node: Node) -> None:
        evaluation = node.evidence.evaluation
        self._ref_metric = dict(evaluation.metric) if evaluation else {}

    @property
    def multi_active(self) -> bool:
        if self.value_cfg.mode != "multi":
            return False
        for key in self._rank_keys:
            if _num(self._ref_metric, key) is not None:
                return True
        if self._noise_key and _num(self._ref_metric, self._noise_key) is not None:
            return True
        return False

    def elite_sizes(self) -> dict[str, int]:
        return self.elite.sizes()

    def observe_node(self, node: Node) -> None:
        if not self.multi_active or self.value_cfg.elite_m <= 0:
            return
        evaluation = node.evidence.evaluation
        if evaluation is None:
            return
        metric = evaluation.metric
        self.elite.update(
            node.id,
            self._rank_gain(metric),
            self._threshold_quality(metric),
        )

    def _rank_gain(self, metric: dict[str, Any]) -> float:
        gains: list[float] = []
        for key in self._rank_keys:
            ref = _num(self._ref_metric, key)
            cur = _num(metric, key)
            if ref is None or cur is None:
                continue
            denom = max(abs(ref), 1e-6)
            gains.append(max(-1.0, min(1.0, (cur - ref) / denom)))
        if not gains:
            return 0.0
        return max(-1.0, min(1.0, sum(gains) / len(gains)))

    def _threshold_quality(self, metric: dict[str, Any]) -> float | None:
        gains: list[float] = []
        for key in self._thr_keys:
            ref = _num(self._ref_metric, key)
            cur = _num(metric, key)
            if ref is None or cur is None:
                continue
            denom = max(abs(ref), 1e-6)
            gains.append(max(-1.0, min(1.0, (cur - ref) / denom)))
        if not gains:
            return None
        return max(-1.0, min(1.0, sum(gains) / len(gains)))

    def _noise_pen(self, metric: dict[str, Any]) -> float:
        if not self._noise_key:
            return 0.0
        ref_std = _num(self._ref_metric, self._noise_key)
        std = _num(metric, self._noise_key)
        if ref_std is None or std is None:
            return 0.0
        denom = max(ref_std, 1e-6)
        return max(-1.0, min(1.0, (std - ref_std) / denom))

    def _node_value(self, node: Node) -> float | None:
        evaluation = node.evidence.evaluation
        if evaluation is None or evaluation.validity < 1.0:
            return None
        if node.status in (NodeStatus.INVALID, NodeStatus.ABANDONED):
            return None
        normalizer = max(self.best_score - self.initial_score, 1.0)
        score_term = (evaluation.combined_score - self.initial_score) / normalizer
        return (
            score_term
            + self.value_cfg.lambda_rank * self._rank_gain(evaluation.metric)
            - self.value_cfg.lambda_noise * self._noise_pen(evaluation.metric)
        )

    def _subtree_values(self, node_id: str, tree: Tree) -> list[float]:
        values: list[float] = []
        node = tree.get_node(node_id)
        if node is None:
            return values
        node_val = self._node_value(node)
        if node_val is not None:
            values.append(node_val)
        for child in tree.get_children(node_id):
            values.extend(self._subtree_values(child.id, tree))
        return values

    def _subtree_value(self, node_id: str, tree: Tree) -> float | None:
        if node_id in self._memo:
            return self._memo[node_id]
        values = self._subtree_values(node_id, tree)
        if not values:
            result: float | None = None
        elif self.value_cfg.backup == "max":
            result = max(values)
        else:
            max_v = max(values)
            weights = [math.exp((v - max_v) / SOFTMAX_TEMP) for v in values]
            total = sum(weights)
            result = sum(v * w for v, w in zip(values, weights)) / total
        self._memo[node_id] = result
        return result

    def set_node_priors(
        self,
        values: dict[str, float],
        tau: float,
        enabled: bool,
    ) -> None:
        self.node_values = dict(values)
        self.prior_tau = min(1.0, max(0.0, tau))
        self.prior_enabled = enabled

    def _compute_option_priors(
        self,
        children: list[Node],
        can_widen: bool,
    ) -> dict[str, float]:
        keys = [child.id for child in children] + (["expand"] if can_widen else [])
        uniform = get_uniform_prior(keys)
        known = [max(0.0, self.node_values[c.id]) for c in children if c.id in self.node_values]
        if not self.prior_enabled or not known:
            return uniform
        fallback = sum(known) / len(known)
        values = {
            child.id: max(0.0, self.node_values.get(child.id, fallback))
            for child in children
        }
        if can_widen:
            values["expand"] = fallback
        total = sum(values.values())
        if total <= 0:
            return uniform
        jev = {key: value / total for key, value in values.items()}
        mixed = compute_tau_weighted_prior(jev, uniform, self.prior_tau)
        mixed_total = sum(mixed.values())
        return {key: value / mixed_total for key, value in mixed.items()}

    def set_initial_score(self, score: float) -> None:
        """Set the initial score for Q-value normalization."""
        self.initial_score = score
        if self.best_score < score:
            self.best_score = score

    def update_best_score(self, score: float) -> None:
        """Update the global best score."""
        if score > self.best_score:
            self.best_score = score

    def set_noise_delta(self, delta: float) -> None:
        """Set the noise delta for significance threshold."""
        self.noise_delta = delta

    def select(self, tree: Tree) -> SelectionResult:
        """Select a node to expand using UCT.

        Traverses from root to a leaf, choosing at each internal node
        the child (or self for expansion) with highest UCT value.

        Args:
            tree: The evolution tree

        Returns:
            SelectionResult with selected node and whether to expand
        """
        root = tree.get_root()
        if root is None:
            raise ValueError("Tree has no root")

        self._memo = {}
        if self.multi_active:
            elite_roll = self._value_rng.random()
            elite_ids = self.elite.ids()
            if elite_ids and elite_roll < self.value_cfg.elite_prob:
                pick = self._value_rng.choice(elite_ids)
                picked = tree.get_node(pick)
                if picked is not None and picked.is_expandable():
                    path_ids: list[str] = []
                    current: Node | None = picked
                    while current is not None:
                        path_ids.append(current.id)
                        current = tree.get_parent(current.id)
                    for nid in path_ids:
                        tree.increment_visit_count(nid)
                    return SelectionResult(node=picked, should_expand=True, prior={})

        node = root
        priors: dict[str, float] = {}

        while True:
            tree.increment_visit_count(node.id)

            children = tree.get_expandable_children(node.id)
            can_widen = self._can_widen(node, tree)

            if not children and not can_widen:
                return SelectionResult(node=node, should_expand=False, prior=priors)

            options: list[tuple[str, float]] = []
            option_priors = self._compute_option_priors(children, can_widen)

            for child in children:
                prior = option_priors[child.id]
                priors[child.id] = prior
                ucb = self._compute_ucb(child, node, tree, prior)
                options.append((child.id, ucb))

            if can_widen:
                expand_prior = option_priors["expand"]
                priors["expand"] = expand_prior
                expand_ucb = self._compute_expand_ucb(node, tree, expand_prior)
                options.append(("expand", expand_ucb))

            if not options:
                return SelectionResult(node=node, should_expand=False, prior=priors)

            best_id, _ = max(options, key=lambda x: x[1])

            if best_id == "expand":
                return SelectionResult(node=node, should_expand=True, prior=priors)

            child_node = tree.get_node(best_id)
            if child_node is None:
                return SelectionResult(node=node, should_expand=can_widen, prior=priors)

            if not child_node.children:
                return SelectionResult(node=child_node, should_expand=True, prior=priors)

            node = child_node

    def _can_widen(self, node: Node, tree: Tree) -> bool:
        """Check if a node can be expanded (progressive widening).

        Excludes repair and invalid children from the child count
        to prevent them from consuming the widening budget.
        """
        if not node.is_expandable():
            return False

        n_children = tree.get_regular_children_count(node.id)
        n_visits = max(1, node.visit_count)

        max_children = math.ceil(self.widening_c * (n_visits ** self.widening_alpha))
        return n_children < max_children

    def _get_prior(self, node: Node, n_options: int) -> float:
        """Get prior probability for a node.

        Hook for Jev integration - currently returns uniform.
        """
        return 1.0 / max(n_options, 1)

    def _compute_ucb(
        self,
        child: Node,
        parent: Node,
        tree: Tree,
        prior: float,
    ) -> float:
        """Compute UCB value for a child node.

        UCB = Q(child) + c_puct * prior * sqrt(N_parent) / (1 + N_child)
        """
        q_value = self._compute_q(child, parent, tree)

        n_parent = max(1, parent.visit_count)
        n_child = max(1, child.visit_count)

        exploration = self.c_puct * prior * math.sqrt(n_parent) / (1 + n_child)

        return q_value + exploration

    def _compute_expand_ucb(
        self,
        node: Node,
        tree: Tree,
        prior: float,
    ) -> float:
        """Compute UCB value for expanding the current node.

        Similar to child UCB but Q is based on node's own subtree best.
        """
        if not self.multi_active:
            subtree_best = tree.get_subtree_best_score(node.id)
            parent_score = node.get_score()
            delta = max(0, subtree_best - parent_score - self.noise_delta)
            normalizer = max(self.best_score - self.initial_score, 1.0)
            q_value = delta / normalizer
        else:
            sub = self._subtree_value(node.id, tree)
            ref = self._node_value(node)
            normalizer = max(self.best_score - self.initial_score, 1.0)
            if sub is None or ref is None:
                q_value = 0.0
            else:
                q_value = max(0.0, sub - ref - self.noise_delta / normalizer)

        n_parent = max(1, node.visit_count)
        n_expand = max(1, node.expand_count)

        exploration = self.c_puct * prior * math.sqrt(n_parent) / (1 + n_expand)

        return q_value + exploration

    def _compute_q(
        self,
        child: Node,
        parent: Node,
        tree: Tree,
    ) -> float:
        """Compute Q-value using max-backup.

        Q(child) = max(0, best_in_subtree(child) - parent_score - delta) / normalizer
        """
        if not self.multi_active:
            subtree_best = tree.get_subtree_best_score(child.id)
            parent_score = parent.get_score()
            delta = max(0, subtree_best - parent_score - self.noise_delta)
            normalizer = max(self.best_score - self.initial_score, 1.0)
            return delta / normalizer

        sub = self._subtree_value(child.id, tree)
        ref = self._node_value(parent)
        normalizer = max(self.best_score - self.initial_score, 1.0)
        if sub is None or ref is None:
            return 0.0
        return max(0.0, sub - ref - self.noise_delta / normalizer)


def get_uniform_prior(options: list[Any]) -> dict[Any, float]:
    """Get uniform prior distribution over options.

    Used as baseline when no prior information is available.
    """
    n = len(options)
    if n == 0:
        return {}
    return {opt: 1.0 / n for opt in options}


def get_jev_prior(
    options: list[Any],
    context: dict[str, Any],
) -> dict[Any, float]:
    """Hook for Jev prior integration.

    Returns prior probabilities from Jev's Choice API for selection decisions.
    Currently returns uniform prior; will be replaced with actual
    Jev Choice API call when Jev integration is implemented.

    Args:
        options: List of options to choose from
        context: Context for the decision (parent node state, etc.)

    Returns:
        Dictionary mapping options to prior probabilities
    """
    values = context.get("values", {})
    enabled = bool(context.get("enabled", False))
    tau = min(1.0, max(0.0, float(context.get("tau", 0.0))))
    uniform = get_uniform_prior(options)
    known = [max(0.0, float(values[o])) for o in options if o in values]
    if not enabled or not known:
        return uniform
    fallback = sum(known) / len(known)
    raw = {option: max(0.0, float(values.get(option, fallback))) for option in options}
    total = sum(raw.values())
    if total <= 0:
        return uniform
    jev = {option: value / total for option, value in raw.items()}
    mixed = compute_tau_weighted_prior(jev, uniform, tau)
    normalizer = sum(mixed.values())
    return {option: value / normalizer for option, value in mixed.items()}


def get_era_knowledge_cards(
    node: Any,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Retrieve ERA-style knowledge cards for the inject/refine operator.

    Returns relevant knowledge cards based on:
    - Priority prior (higher priority cards preferred)
    - Tag/keyword match with node context (code, reflection, errors)
    - Bayesian mean of observed score delta after adoption
    - UCB-style exploration bonus

    Excludes:
    - Cards refuted on this branch
    - Cards already adopted by ancestors

    Enforces category diversity (at most 2 cards per category).

    Args:
        node: Current node to find knowledge for
        context: Additional context with keys:
            - knowledge_dir: Path to knowledge directory (required)
            - store: Store instance for card stats (optional)
            - experiment_id: Experiment ID (optional)
            - k: Number of cards to return (default 4)
            - max_per_category: Max cards per category (default 2)

    Returns:
        List of knowledge card dictionaries with keys:
        - id: Card ID
        - title: Card title
        - source: Origin of the knowledge (paper, best practice, etc.)
        - idea: Core idea or technique (same as claim)
        - claim: The card's claim
        - impl_hint: Implementation guidance
        - risk: Potential downsides or caveats
    """
    from pathlib import Path
    from faultevolve.knowledge.loader import load_all_cards
    from faultevolve.knowledge.retriever import (
        CardRetriever,
        CardStats,
        RetrievalContext,
    )

    knowledge_dir = context.get("knowledge_dir")
    if knowledge_dir is None:
        return []

    if isinstance(knowledge_dir, str):
        knowledge_dir = Path(knowledge_dir)

    cards, errors = load_all_cards(
        knowledge_dir,
        [Path(p) for p in context.get("extra_card_paths") or []],
    )
    if not cards:
        return []

    store = context.get("store")
    experiment_id = context.get("experiment_id", "")
    k = context.get("k", 4)
    max_per_category = context.get("max_per_category", 2)

    card_stats: dict[str, CardStats] = {}
    branch_refuted: set[str] = set()
    ancestor_adopted: set[str] = set()
    recently_offered: dict[str, int] = {}
    failed_card_sets: list[set[str]] = []

    if store is not None and experiment_id:
        raw_stats = store.get_card_stats(experiment_id)
        for card_id, data in raw_stats.items():
            card_stats[card_id] = CardStats(
                card_id=card_id,
                n=data["n"],
                sum_delta=data["sum_delta"],
                sum_sq=data["sum_sq"],
                refuted_count=data["refuted_count"],
                invalid_count=data.get("invalid_count", 0),
            )

        if hasattr(node, "branch_id") and node.branch_id:
            branch_refuted = store.get_branch_refuted_cards(experiment_id, node.branch_id)
            recently_offered = store.get_recently_offered_cards(experiment_id, node.branch_id, 3)
            failed_card_sets = store.get_recently_failed_card_sets(experiment_id, node.branch_id, 3)

        if hasattr(node, "id") and node.id:
            ancestor_adopted = store.get_ancestor_adopted_cards(node.id)

    code_text = ""
    last_reflection = ""
    error_classes: list[str] = []

    if hasattr(node, "artifact") and node.artifact:
        code_text = node.artifact.code or ""

    if hasattr(node, "branch_memory") and node.branch_memory:
        last_reflection = node.branch_memory.summary or ""

    if hasattr(node, "evidence") and node.evidence:
        if node.evidence.evaluation and node.evidence.evaluation.error_info:
            error_info = node.evidence.evaluation.error_info
            if "recall" in error_info.lower():
                error_classes.append("recall")
            if "precision" in error_info.lower() or "false_alarm" in error_info.lower():
                error_classes.append("precision")
            if "timeout" in error_info.lower():
                error_classes.append("runtime")

    keywords = context.get("keywords", None)

    retrieval_context = RetrievalContext(
        code_text=code_text,
        last_reflection=last_reflection,
        error_classes=error_classes,
        branch_refuted_cards=branch_refuted,
        ancestor_adopted_cards=ancestor_adopted,
        keywords=keywords,
        profile_keywords=context.get("profile_keywords"),
        recently_offered_cards=recently_offered,
        failed_card_sets=failed_card_sets,
    )

    retriever = CardRetriever(
        cards=cards,
        card_stats=card_stats,
        max_per_category=max_per_category,
        default_k=k,
    )

    selected = retriever.retrieve(retrieval_context, k=k)

    return [card.to_dict() for card in selected]


def compute_tau_weighted_prior(
    jev_prior: dict[Any, float],
    uniform_prior: dict[Any, float],
    tau: float,
) -> dict[Any, float]:
    """Compute tau-weighted mixture of Jev and uniform priors.

    P_tilde = tau * P_jev + (1 - tau) * P_uniform

    Args:
        jev_prior: Prior from Jev
        uniform_prior: Uniform prior
        tau: Trust weight for Jev (0 = pure uniform, 1 = pure Jev)

    Returns:
        Mixed prior distribution
    """
    result = {}
    all_keys = set(jev_prior.keys()) | set(uniform_prior.keys())

    for key in all_keys:
        p_jev = jev_prior.get(key, 0.0)
        p_uniform = uniform_prior.get(key, 0.0)
        result[key] = tau * p_jev + (1 - tau) * p_uniform

    return result
