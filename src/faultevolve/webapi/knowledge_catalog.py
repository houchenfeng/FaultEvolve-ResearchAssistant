"""Join a run's card ids to the task knowledge catalog.

The run directory records which cards were offered and how they scored. The
prose lives in ``<task>/knowledge/cards.jsonl`` and ``sources.yaml``. This
module copies only the fields the contract already names, and only when the
run registry points at a task the server is allowed to read. A miss stays
empty; nothing here invents a title, a claim, or a priority from deltas.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from faultevolve.knowledge.loader import load_cards
from faultevolve.webapi.contracts import KnowledgeSourceResponse
from faultevolve.webapi.errors import TaskNotFoundError
from faultevolve.webapi.sanitization import sanitize
from faultevolve.webapi.settings import PathNotAllowedError, WebSettings

_MAX_TEXT = 4000


@dataclass(frozen=True)
class CatalogCard:
    """Prose for one catalog card, already sanitised."""

    title: str | None
    category: str | None
    claim: str | None
    source_kind: str | None
    source_detail: str | None
    conditions: str | None
    priority: int | None
    sources: tuple[KnowledgeSourceResponse, ...]


def catalog_for_task(settings: WebSettings, task_id: str | None) -> dict[str, CatalogCard]:
    """Cards for one registered task, or ``{}`` when the task cannot be read."""
    if not task_id:
        return {}
    try:
        from faultevolve.webapi import task_service

        task_dir = task_service.resolve_task_dir(settings, task_id)
        knowledge = settings.ensure_allowed(task_dir / "knowledge")
    except (TaskNotFoundError, PathNotAllowedError, OSError):
        return {}
    return _read_catalog(knowledge)


def _clean(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = sanitize(value)[0].strip()
    if not text:
        return None
    if len(text) > _MAX_TEXT:
        text = text[:_MAX_TEXT]
    return text


def _http_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    url = value.strip()
    if not url or any(char in url for char in " \t\r\n"):
        return None
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return url


def _load_sources(path: Path) -> dict[str, tuple[str | None, str | None, str | None]]:
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(data, list):
        return {}
    found: dict[str, tuple[str | None, str | None, str | None]] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        source_id = item.get("id")
        if not isinstance(source_id, str) or not source_id.strip():
            continue
        found[source_id.strip()] = (
            _clean(item.get("title")),
            _http_url(item.get("url")),
            _clean(item.get("takeaway")),
        )
    return found


def _read_catalog(knowledge_dir: Path) -> dict[str, CatalogCard]:
    cards_path = knowledge_dir / "cards.jsonl"
    if not cards_path.is_file():
        return {}
    cards, _errors = load_cards(cards_path)
    sources = _load_sources(knowledge_dir / "sources.yaml")
    catalog: dict[str, CatalogCard] = {}
    for card in cards:
        cited: list[KnowledgeSourceResponse] = []
        for source_id in card.source_ids:
            if not isinstance(source_id, str) or not source_id.strip():
                continue
            title, url, takeaway = sources.get(source_id, (None, None, None))
            cited.append(
                KnowledgeSourceResponse(
                    source_id=source_id, title=title, url=url, takeaway=takeaway
                )
            )
        detail_parts = [item.title or item.source_id for item in cited]
        priority = card.priority if 1 <= card.priority <= 5 else None
        catalog[card.id] = CatalogCard(
            title=_clean(card.title),
            category=_clean(card.category),
            claim=_clean(card.claim),
            source_kind=_clean(card.evidence),
            source_detail=_clean("、".join(detail_parts)) if detail_parts else None,
            conditions=_clean(card.applicability),
            priority=priority,
            sources=tuple(cited),
        )
    return catalog
