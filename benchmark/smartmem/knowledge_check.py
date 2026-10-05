"""Validate the SmartMem knowledge pack.

The loader in ``faultevolve.knowledge.loader`` checks the card schema and nothing else: it accepts
any id, any evidence label, any source id, and an empty ``risk``. That is correct for a generic
loader, but a knowledge pack is the artefact this phase is graded on, so the rules that make a
claim checkable live here instead:

- every card states its condition, expected effect and risk, so a reader can tell when not to
  follow it;
- every card points at a source somebody actually read, and every source is cited by a card, so the
  two files cannot drift apart;
- an external source must carry a url, how it was read and when; a local record must name the
  document that holds the evidence;
- LLM guesses are allowed but must be labelled ``llm_hypothesis`` and cannot masquerade as a
  citation;
- nothing in the pack may leak a private path, a bare serial number or an HDD SMART claim renamed
  into DRAM vocabulary.

This module is domain data validation, so it lives with the pack rather than in the generic layer.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from faultevolve.knowledge.loader import KnowledgeCard, load_cards

DEFAULT_PACK = Path(__file__).resolve().parent / "knowledge"

CARD_NAMESPACE = "SM-"
# the HDD pack uses bare FE*/M*/T* and discovery cards use D-*; requiring the namespace here is what
# keeps a renamed copy of an HDD card from shadowing an existing id when both packs load

REQUIRED_PROSE = ("rationale", "applicability", "expected_effect", "risk", "impl_hint")

ALLOWED_EVIDENCE = {
    "user_run",
    "official",
    "paper",
    "expert",
    "benchmark",
    "llm_hypothesis",
}
LOCAL_EVIDENCE_CLASS = "local"

# plan section 8.1: SMART counter semantics do not transfer to a DRAM mcelog stream, so a card that
# carries one of these tokens is treated as a renamed HDD card rather than a SmartMem claim.
# Matching is word-bounded: "headline" is English, "reallocated" is a SMART attribute.
HDD_TOKENS = ("smart_5", "smart_187", "197", "198", "reallocated", "power_on_hours", "head")
HDD_TOKEN_PATTERN = re.compile(
    r"\b(?:%s)\b" % "|".join(re.escape(token) for token in HDD_TOKENS)
)

PRIVATE_PATH_PATTERNS = (
    re.compile(r"[A-Za-z]:[\\/]{1,2}Users[\\/]"),
    re.compile(r"/home/[a-z0-9_]+/"),
)
# an unannotated long digit run is a serial number or an epoch timestamp; both identify a machine
BARE_LONG_NUMBER = re.compile(r"\b\d{9,}\b")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

PROSE_FILE_NAMES = ("cards.jsonl", "sources.yaml", "expert.md", "README.md")
MIN_TAKEAWAY_WORDS = 8


def load_sources(sources_path: Path) -> dict[str, dict[str, Any]]:
    """Read sources.yaml into an id -> entry mapping.

    Args:
        sources_path: Path to the pack's sources.yaml

    Returns:
        Mapping of source id to its entry; empty when the file is missing or unreadable
    """
    if not sources_path.exists():
        return {}
    try:
        document = yaml.safe_load(sources_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return {}

    entries = document
    if isinstance(document, dict):
        entries = document.get("sources")
    if not isinstance(entries, list):
        return {}

    sources: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source_id = str(entry.get("id", "")).strip()
        if source_id:
            sources[source_id] = entry
    return sources


def _validate_prose(cards: list[KnowledgeCard]) -> list[str]:
    errors: list[str] = []
    for card in cards:
        for field_name in REQUIRED_PROSE:
            value = getattr(card, field_name, "")
            if not str(value).strip():
                errors.append(f"{card.id}: {field_name} is empty")

        if not card.source_ids:
            errors.append(f"{card.id}: cites no source")
        if not card.tags:
            errors.append(f"{card.id}: has no tags, so it can never be retrieved")
    return errors


def _validate_namespace(cards: list[KnowledgeCard]) -> list[str]:
    # the category itself is not re-checked here: load_cards rejects a category outside
    # VALID_CATEGORIES and validate_pack stops at the first loader error, so a card reaching this
    # function already has a legal category
    errors: list[str] = []
    for card in cards:
        if not card.id.startswith(CARD_NAMESPACE):
            errors.append(f"{card.id}: id must start with {CARD_NAMESPACE}")
        if card.evidence not in ALLOWED_EVIDENCE:
            errors.append(f"{card.id}: unknown evidence class {card.evidence}")
    return errors


def _validate_source_links(
    cards: list[KnowledgeCard], sources: dict[str, dict[str, Any]]
) -> list[str]:
    errors: list[str] = []
    cited: set[str] = set()
    for card in cards:
        for source_id in card.source_ids:
            cited.add(source_id)
            if source_id not in sources:
                errors.append(f"{card.id}: cites unknown source {source_id}")

    for source_id in sorted(set(sources) - cited):
        errors.append(f"source {source_id} is cited by no card")
    return errors


def _validate_source_records(sources: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for source_id, entry in sorted(sources.items()):
        if entry.get("evidence_class") == LOCAL_EVIDENCE_CLASS:
            if not str(entry.get("record", "")).strip():
                errors.append(f"source {source_id} is local but names no record")
            continue

        if not str(entry.get("url", "")).strip():
            errors.append(f"source {source_id} is external but has no url")
        if not str(entry.get("retrieved_via", "")).strip():
            errors.append(f"source {source_id} does not say how it was read")
        if not ISO_DATE.fullmatch(str(entry.get("retrieved", ""))):
            errors.append(f"source {source_id} has no retrieval date as YYYY-MM-DD")

        takeaway = str(entry.get("takeaway", "")).split()
        if len(takeaway) < MIN_TAKEAWAY_WORDS:
            errors.append(f"source {source_id} takeaway is filler")
    return errors


def _privacy_errors(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    errors: list[str] = []
    for pattern in PRIVATE_PATH_PATTERNS:
        if pattern.search(text):
            errors.append(f"{path.name} carries a private local path")
    if BARE_LONG_NUMBER.search(text):
        errors.append(f"{path.name} carries a bare long number (serial or epoch)")
    if path.name == "cards.jsonl":
        hit = HDD_TOKEN_PATTERN.search(text.lower())
        if hit:
            errors.append(f"cards.jsonl carries HDD token {hit.group(0)}")
    return errors


def validate_pack(pack_dir: Path = DEFAULT_PACK) -> list[str]:
    """Return every reason the pack in ``pack_dir`` should not be shipped.

    Args:
        pack_dir: Directory holding cards.jsonl and sources.yaml

    Returns:
        Error strings, empty when the pack is sound
    """
    errors: list[str] = []

    cards_path = pack_dir / "cards.jsonl"
    sources_path = pack_dir / "sources.yaml"

    if not cards_path.exists():
        errors.append(f"{pack_dir}: cards.jsonl is missing")
    if not sources_path.exists():
        errors.append(f"{pack_dir}: sources.yaml is missing")
    if errors:
        return errors

    cards, loader_errors = load_cards(cards_path)
    errors.extend(loader_errors)
    if loader_errors:
        # a malformed line is rejected by the loader, so its fields cannot be trusted for the
        # semantic checks below; report the schema break and stop
        return errors

    sources = load_sources(sources_path)
    errors.extend(_validate_namespace(cards))
    errors.extend(_validate_prose(cards))
    errors.extend(_validate_source_links(cards, sources))
    errors.extend(_validate_source_records(sources))

    for name in PROSE_FILE_NAMES:
        path = pack_dir / name
        if path.is_file():
            errors.extend(_privacy_errors(path))

    return errors


def load_pack(pack_dir: Path = DEFAULT_PACK) -> tuple[list[KnowledgeCard], list[str]]:
    """Load the pack for a run: cards only when every semantic check passes.

    Args:
        pack_dir: Directory holding cards.jsonl and sources.yaml

    Returns:
        Tuple of (cards, errors); cards are empty when errors are present
    """
    errors = validate_pack(pack_dir)
    if errors:
        return [], errors
    cards, _ = load_cards(pack_dir / "cards.jsonl")
    return cards, []


def pack_summary(pack_dir: Path = DEFAULT_PACK) -> dict[str, Any]:
    """Count what the pack holds, for the run record and the README table.

    Args:
        pack_dir: Directory holding cards.jsonl and sources.yaml

    Returns:
        Dict with card and source counts plus per-category and per-evidence histograms
    """
    cards, _ = load_cards(pack_dir / "cards.jsonl")
    sources = load_sources(pack_dir / "sources.yaml")
    return {
        "cards": len(cards),
        "sources": len(sources),
        "categories": dict(Counter(card.category for card in cards)),
        "evidence": dict(Counter(card.evidence for card in cards)),
    }


def main(argv: list[str] | None = None) -> int:
    """Report pack problems: one line each, exit 1 when the pack should not ship."""
    args = list(sys.argv[1:] if argv is None else argv)
    pack_dir = Path(args[0]) if args else DEFAULT_PACK
    errors = validate_pack(pack_dir)
    for error in errors:
        print(error)
    if errors:
        return 1
    summary = pack_summary(pack_dir)
    print(
        json.dumps(
            {"pack": pack_dir.name, **summary}, ensure_ascii=False, sort_keys=True
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
