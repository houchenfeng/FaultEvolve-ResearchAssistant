"""Knowledge card loader and validator.

Loads cards.jsonl files and validates their schema.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence


REQUIRED_FIELDS = {"id", "title", "category", "claim", "source_ids", "tags"}
OPTIONAL_FIELDS = {
    "rationale", "applicability", "expected_effect", "risk",
    "impl_hint", "priority", "evidence", "idea", "source",
}
VALID_CATEGORIES = {
    "feature_engineering", "model", "evaluation", "pitfalls",
    "thresholding", "labeling", "imbalance", "transfer", "ensembling",
}


@dataclass
class KnowledgeCard:
    """A knowledge card from the ERA-style knowledge base."""

    id: str
    title: str
    category: str
    claim: str
    source_ids: list[str]
    tags: list[str]
    rationale: str = ""
    applicability: str = ""
    expected_effect: str = ""
    risk: str = ""
    impl_hint: str = ""
    priority: int = 3
    evidence: str = "paper"

    @property
    def idea(self) -> str:
        """Alias for claim (for hook compatibility)."""
        return self.claim

    @property
    def source(self) -> str:
        """Joined source_ids (for hook compatibility)."""
        return ", ".join(self.source_ids)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "claim": self.claim,
            "rationale": self.rationale,
            "applicability": self.applicability,
            "expected_effect": self.expected_effect,
            "risk": self.risk,
            "source_ids": self.source_ids,
            "tags": self.tags,
            "impl_hint": self.impl_hint,
            "priority": self.priority,
            "evidence": self.evidence,
            "idea": self.idea,
            "source": self.source,
        }

    def to_prompt_dict(self) -> dict[str, str]:
        """Convert to dictionary for prompt injection (claim, impl_hint, risk)."""
        return {
            "id": self.id,
            "title": self.title,
            "claim": self.claim,
            "impl_hint": self.impl_hint,
            "risk": self.risk,
        }


def validate_card(data: dict[str, Any]) -> tuple[bool, str]:
    """Validate a card dictionary against the schema.

    Args:
        data: Card data dictionary

    Returns:
        Tuple of (is_valid, error_message)
    """
    missing = REQUIRED_FIELDS - set(data.keys())
    if missing:
        return False, f"Missing required fields: {sorted(missing)}"

    if not isinstance(data.get("id"), str) or not data["id"]:
        return False, "id must be a non-empty string"

    if not isinstance(data.get("title"), str) or not data["title"]:
        return False, "title must be a non-empty string"

    category = data.get("category", "")
    if category not in VALID_CATEGORIES:
        return False, f"Invalid category '{category}', must be one of {sorted(VALID_CATEGORIES)}"

    if not isinstance(data.get("claim"), str) or not data["claim"]:
        return False, "claim must be a non-empty string"

    source_ids = data.get("source_ids", [])
    if not isinstance(source_ids, list):
        return False, "source_ids must be a list"

    tags = data.get("tags", [])
    if not isinstance(tags, list):
        return False, "tags must be a list"

    priority = data.get("priority", 3)
    if not isinstance(priority, (int, float)) or priority < 1 or priority > 5:
        return False, f"priority must be an integer 1-5, got {priority}"

    return True, ""


def parse_card(data: dict[str, Any]) -> KnowledgeCard:
    """Parse a validated card dictionary into a KnowledgeCard.

    Args:
        data: Validated card data dictionary

    Returns:
        KnowledgeCard instance
    """
    return KnowledgeCard(
        id=data["id"],
        title=data["title"],
        category=data["category"],
        claim=data["claim"],
        source_ids=data.get("source_ids", []),
        tags=data.get("tags", []),
        rationale=data.get("rationale", ""),
        applicability=data.get("applicability", ""),
        expected_effect=data.get("expected_effect", ""),
        risk=data.get("risk", ""),
        impl_hint=data.get("impl_hint", ""),
        priority=int(data.get("priority", 3)),
        evidence=data.get("evidence", "paper"),
    )


def load_cards(cards_path: Path) -> tuple[list[KnowledgeCard], list[str]]:
    """Load and validate cards from a cards.jsonl file.

    Args:
        cards_path: Path to cards.jsonl file

    Returns:
        Tuple of (valid_cards, error_messages)
    """
    if not cards_path.exists():
        return [], [f"Cards file not found: {cards_path}"]

    cards: list[KnowledgeCard] = []
    errors: list[str] = []
    seen_ids: set[str] = set()

    with cards_path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append(f"Line {line_num}: JSON parse error: {e}")
                continue

            is_valid, error = validate_card(data)
            if not is_valid:
                errors.append(f"Line {line_num} (id={data.get('id', '?')}): {error}")
                continue

            card_id = data["id"]
            if card_id in seen_ids:
                errors.append(f"Line {line_num}: Duplicate card id '{card_id}'")
                continue

            seen_ids.add(card_id)
            cards.append(parse_card(data))

    return cards, errors


def load_all_cards(
    knowledge_dir: Path | None,
    extra_paths: Sequence[Path] = (),
) -> tuple[list[KnowledgeCard], list[str]]:
    """Load literature cards plus optional extra jsonl paths."""
    cards: list[KnowledgeCard] = []
    errors: list[str] = []
    seen: set[str] = set()
    if knowledge_dir is not None:
        primary, errs = load_cards_from_dir(knowledge_dir)
        errors.extend(errs)
        for c in primary:
            seen.add(c.id)
            cards.append(c)
    for path in extra_paths:
        if not path.exists():
            continue
        extra_cards, errs = load_cards(path)
        errors.extend(errs)
        for c in extra_cards:
            if c.id in seen:
                errors.append(f"Duplicate card id '{c.id}' rejected from {path}")
                continue
            seen.add(c.id)
            cards.append(c)
    return cards, errors


def load_cards_from_dir(knowledge_dir: Path) -> tuple[list[KnowledgeCard], list[str]]:
    """Load cards from a knowledge directory.

    Looks for cards.jsonl in the specified directory.

    Args:
        knowledge_dir: Path to knowledge directory

    Returns:
        Tuple of (valid_cards, error_messages)
    """
    cards_path = knowledge_dir / "cards.jsonl"
    return load_cards(cards_path)


def get_cards_by_category(cards: list[KnowledgeCard]) -> dict[str, list[KnowledgeCard]]:
    """Group cards by category.

    Args:
        cards: List of knowledge cards

    Returns:
        Dictionary mapping category to list of cards
    """
    by_category: dict[str, list[KnowledgeCard]] = {}
    for card in cards:
        if card.category not in by_category:
            by_category[card.category] = []
        by_category[card.category].append(card)
    return by_category


def get_cards_by_priority(cards: list[KnowledgeCard]) -> list[KnowledgeCard]:
    """Sort cards by priority (1 = highest priority first).

    Args:
        cards: List of knowledge cards

    Returns:
        Cards sorted by priority
    """
    return sorted(cards, key=lambda c: c.priority)
