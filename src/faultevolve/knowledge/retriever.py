"""Knowledge card retrieval for ERA-style injection.

Retrieves relevant knowledge cards based on:
- Priority prior
- Tag/keyword match with node context
- Bayesian mean of observed score delta after adoption
- UCB-style exploration bonus

Excludes:
- Cards refuted on this branch
- Cards already adopted by ancestors

Enforces category diversity (at most 2 cards per category).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from faultevolve.knowledge.loader import KnowledgeCard, load_cards_from_dir


@dataclass
class CardStats:
    """Statistics for a knowledge card's adoption outcomes."""

    card_id: str
    n: int = 0
    sum_delta: float = 0.0
    sum_sq: float = 0.0
    refuted_count: int = 0
    invalid_count: int = 0

    @property
    def mean_delta(self) -> float:
        """Bayesian mean of score delta (prior mean = 0)."""
        if self.n == 0:
            return 0.0
        return self.sum_delta / self.n

    @property
    def variance(self) -> float:
        """Variance of observed deltas."""
        if self.n < 2:
            return 1.0
        mean = self.mean_delta
        return max(0.01, self.sum_sq / self.n - mean * mean)

    @property
    def std(self) -> float:
        return math.sqrt(self.variance)

    @property
    def invalid_rate(self) -> float:
        """Rate of invalid adoptions (invalid / total)."""
        if self.n == 0:
            return 0.0
        return self.invalid_count / self.n


@dataclass
class RetrievalContext:
    """Context for card retrieval scoring."""

    code_text: str = ""
    last_reflection: str = ""
    error_classes: list[str] | None = None
    branch_refuted_cards: set[str] | None = None
    ancestor_adopted_cards: set[str] | None = None
    keywords: list[str] | None = None
    profile_keywords: list[str] | None = None
    recently_offered_cards: dict[str, int] | None = None
    failed_card_sets: list[set[str]] | None = None


def extract_keywords_from_text(text: str) -> set[str]:
    """Extract generic keywords from text for tag matching.

    This is a task-agnostic fallback. Task-specific keyword extraction
    should be done in the adapter's context_keywords() method.

    Args:
        text: Text to extract keywords from

    Returns:
        Set of extracted keywords
    """
    keywords = set()

    if re.search(r"model|predict|classifier|regressor", text, re.IGNORECASE):
        keywords.add("model")

    if re.search(r"threshold|cutoff", text, re.IGNORECASE):
        keywords.add("threshold")

    if re.search(r"weight|sample_weight|class_weight", text, re.IGNORECASE):
        keywords.add("class_weight")

    if re.search(r"fillna|NaN|missing|impute", text, re.IGNORECASE):
        keywords.add("missing_values")

    if re.search(r"precision|recall|f1|auc", text, re.IGNORECASE):
        keywords.add("evaluation")

    if re.search(r"feature|groupby|pivot|aggregate", text, re.IGNORECASE):
        keywords.add("feature_engineering")

    if re.search(r"cross.?val|KFold|cv|oof", text, re.IGNORECASE):
        keywords.add("cv")

    return keywords


def compute_tag_match_score(card: KnowledgeCard, context_keywords: set[str]) -> float:
    """Compute tag/keyword match score between card and context.

    Args:
        card: Knowledge card
        context_keywords: Keywords extracted from context

    Returns:
        Match score in [0, 1]
    """
    if not card.tags or not context_keywords:
        return 0.0

    card_keywords = set()
    for tag in card.tags:
        parts = tag.lower().replace(":", "_").replace("-", "_").split("_")
        card_keywords.update(parts)

    card_keywords.add(card.category.replace("_", " ").split()[0])

    intersection = len(card_keywords & context_keywords)
    union = len(card_keywords | context_keywords)

    if union == 0:
        return 0.0

    return intersection / union


def compute_priority_score(card: KnowledgeCard) -> float:
    """Compute priority-based score (priority 1 = highest).

    Args:
        card: Knowledge card

    Returns:
        Priority score in [0, 1]
    """
    return (6 - card.priority) / 5.0


def compute_exploration_bonus(stats: CardStats | None, total_adoptions: int) -> float:
    """Compute UCB-style exploration bonus.

    Args:
        stats: Card statistics (None if never adopted)
        total_adoptions: Total adoptions across all cards

    Returns:
        Exploration bonus
    """
    if stats is None or stats.n == 0:
        return 1.0

    if total_adoptions <= 0:
        return 0.5

    return math.sqrt(2 * math.log(max(total_adoptions, 1)) / stats.n)


def compute_bayesian_mean_score(stats: CardStats | None, prior_mean: float = 0.0, prior_n: int = 2) -> float:
    """Compute Bayesian mean of score delta.

    Uses a prior of (prior_mean, prior_n) observations.

    Args:
        stats: Card statistics (None if never adopted)
        prior_mean: Prior mean delta
        prior_n: Prior pseudo-observations

    Returns:
        Bayesian mean score
    """
    if stats is None or stats.n == 0:
        return prior_mean

    total_n = stats.n + prior_n
    return (stats.sum_delta + prior_mean * prior_n) / total_n


def compute_invalid_penalty(stats: CardStats | None) -> float:
    """Compute penalty based on invalid adoption rate.

    Args:
        stats: Card statistics (None if never adopted)

    Returns:
        Penalty in [0, 1] where higher = more penalty
    """
    if stats is None or stats.n == 0:
        return 0.0
    return stats.invalid_rate


def compute_retrieval_score(
    card: KnowledgeCard,
    context_keywords: set[str],
    stats: CardStats | None,
    total_adoptions: int,
    weights: dict[str, float] | None = None,
    recently_offered_penalty: float = 0.0,
) -> float:
    """Compute overall retrieval score for a card.

    Score = w_prior * priority + w_match * tag_match + w_bayes * bayesian_mean + w_explore * exploration
            - invalid_penalty - recently_offered_penalty

    Args:
        card: Knowledge card
        context_keywords: Keywords from context
        stats: Card statistics
        total_adoptions: Total adoptions
        weights: Component weights (defaults provided)
        recently_offered_penalty: Penalty for being offered recently (0-1)

    Returns:
        Retrieval score
    """
    if weights is None:
        weights = {
            "priority": 0.3,
            "match": 0.3,
            "bayes": 0.25,
            "explore": 0.15,
        }

    priority_score = compute_priority_score(card)
    match_score = compute_tag_match_score(card, context_keywords)
    bayes_score = compute_bayesian_mean_score(stats) / 10.0 + 0.5
    explore_score = compute_exploration_bonus(stats, total_adoptions)
    invalid_penalty = compute_invalid_penalty(stats) * 0.5

    base_score = (
        weights["priority"] * priority_score
        + weights["match"] * match_score
        + weights["bayes"] * min(1.0, max(0.0, bayes_score))
        + weights["explore"] * explore_score
    )

    return base_score - invalid_penalty - recently_offered_penalty


class CardRetriever:
    """Retrieves relevant knowledge cards for a node."""

    def __init__(
        self,
        cards: list[KnowledgeCard],
        card_stats: dict[str, CardStats] | None = None,
        max_per_category: int = 2,
        default_k: int = 4,
    ) -> None:
        """Initialize the retriever.

        Args:
            cards: List of all knowledge cards
            card_stats: Statistics for each card
            max_per_category: Maximum cards per category
            default_k: Default number of cards to return
        """
        self.cards = cards
        self.card_stats = card_stats or {}
        self.max_per_category = max_per_category
        self.default_k = default_k

    def retrieve(
        self,
        context: RetrievalContext,
        k: int | None = None,
    ) -> list[KnowledgeCard]:
        """Retrieve top-k relevant cards for the context.

        Enforces rotation to prevent priority-1 cards from monopolizing:
        - Cards offered recently get a penalty proportional to offer count
        - At most 1 card from a set that failed in recent iterations

        Args:
            context: Retrieval context
            k: Number of cards to return (defaults to self.default_k)

        Returns:
            List of selected knowledge cards
        """
        k = k or self.default_k

        refuted = context.branch_refuted_cards or set()
        adopted = context.ancestor_adopted_cards or set()
        excluded = refuted | adopted

        candidates = [c for c in self.cards if c.id not in excluded]

        if not candidates:
            return []

        if context.keywords:
            context_keywords = set(kw.lower() for kw in context.keywords)
        else:
            context_keywords = extract_keywords_from_text(context.code_text)

        if context.error_classes:
            context_keywords.update(e.lower() for e in context.error_classes)
        if context.last_reflection:
            context_keywords.update(extract_keywords_from_text(context.last_reflection))
        if context.profile_keywords:
            context_keywords.update(k.lower() for k in context.profile_keywords)

        total_adoptions = sum(s.n for s in self.card_stats.values())

        recently_offered = context.recently_offered_cards or {}
        failed_sets = context.failed_card_sets or []

        all_failed_cards: set[str] = set()
        for fs in failed_sets:
            all_failed_cards.update(fs)

        scored = []
        for card in candidates:
            stats = self.card_stats.get(card.id)

            offer_count = recently_offered.get(card.id, 0)
            recently_penalty = min(0.3, offer_count * 0.1)

            score = compute_retrieval_score(
                card, context_keywords, stats, total_adoptions,
                recently_offered_penalty=recently_penalty,
            )
            scored.append((card, score))

        scored.sort(key=lambda x: x[1], reverse=True)

        selected: list[KnowledgeCard] = []
        category_counts: dict[str, int] = {}
        from_failed_set_count = 0
        max_from_failed = 1

        for card, score in scored:
            cat = card.category
            if category_counts.get(cat, 0) >= self.max_per_category:
                continue

            if card.id in all_failed_cards:
                if from_failed_set_count >= max_from_failed:
                    continue
                from_failed_set_count += 1

            selected.append(card)
            category_counts[cat] = category_counts.get(cat, 0) + 1

            if len(selected) >= k:
                break

        return selected

    def get_card_by_id(self, card_id: str) -> KnowledgeCard | None:
        """Get a card by its ID.

        Args:
            card_id: Card ID

        Returns:
            KnowledgeCard or None if not found
        """
        for card in self.cards:
            if card.id == card_id:
                return card
        return None


def retrieve_knowledge_cards(
    knowledge_dir: Path,
    context: RetrievalContext,
    card_stats: dict[str, CardStats] | None = None,
    k: int = 4,
    max_per_category: int = 2,
) -> tuple[list[KnowledgeCard], list[str]]:
    """Convenience function to load and retrieve cards.

    Args:
        knowledge_dir: Path to knowledge directory
        context: Retrieval context
        card_stats: Card statistics
        k: Number of cards to return
        max_per_category: Max cards per category

    Returns:
        Tuple of (selected_cards, error_messages)
    """
    cards, errors = load_cards_from_dir(knowledge_dir)
    if not cards:
        return [], errors

    retriever = CardRetriever(
        cards=cards,
        card_stats=card_stats,
        max_per_category=max_per_category,
        default_k=k,
    )

    selected = retriever.retrieve(context, k=k)
    return selected, errors
