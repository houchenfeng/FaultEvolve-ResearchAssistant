"""Knowledge injection for FaultEvolve.

This package provides ERA-style knowledge injection capabilities:
- Loading and validating knowledge cards from cards.jsonl
- Retrieving relevant cards based on node context
- Tracking card adoption and feedback
"""

from faultevolve.knowledge.loader import (
    KnowledgeCard,
    load_all_cards,
    load_cards,
    validate_card,
)
from faultevolve.knowledge.retriever import (
    CardRetriever,
    retrieve_knowledge_cards,
)

__all__ = [
    "KnowledgeCard",
    "load_all_cards",
    "load_cards",
    "validate_card",
    "CardRetriever",
    "retrieve_knowledge_cards",
]
