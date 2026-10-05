"""Claim translation and extraction from LLM responses."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from typing import Any, Callable

from faultevolve.config import DiscoveryConfig
from faultevolve.discovery.schemas import Claim
from faultevolve.knowledge.loader import VALID_CATEGORIES

TRANSLATE_MARKER = "KD_TRANSLATE"

_REQUIRED_KEYS = {
    "title",
    "condition",
    "feature_code",
    "outcome",
    "direction",
    "scope",
    "falsifier",
}


def _parse_claim_block(raw: str) -> dict[str, Any] | None:
    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    if not _REQUIRED_KEYS.issubset(data.keys()):
        return None
    if data.get("direction") not in {"+", "-"}:
        return None
    if "def feature(" not in str(data.get("feature_code", "")):
        return None
    return data


def extract_claim_from_response(text: str) -> dict[str, Any] | None:
    match = re.search(r"<claim>\s*(.*?)\s*</claim>", text, re.DOTALL | re.IGNORECASE)
    if not match:
        return None
    return _parse_claim_block(match.group(1))


def extract_claims_from_response(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for match in re.finditer(r"<claim>\s*(.*?)\s*</claim>", text, re.DOTALL | re.IGNORECASE):
        parsed = _parse_claim_block(match.group(1))
        if parsed is not None:
            out.append(parsed)
    return out


def preregister(claim: Claim, cfg: DiscoveryConfig) -> str:
    payload = {
        "condition": claim.condition,
        "feature_code": claim.feature_code,
        "outcome": claim.outcome,
        "direction": claim.direction,
        "scope": claim.scope,
        "falsifier": claim.falsifier,
        "split_salt": cfg.split_salt,
        "confirmation_fraction": cfg.confirmation_fraction,
        "alpha": cfg.alpha,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def translate_claim(
    parent_code: str,
    child_code: str,
    insight: dict,
    frames_note: str,
    llm_call: Callable[[list[dict[str, str]]], str],
) -> Claim | None:
    diff = "\n".join(
        difflib.unified_diff(
            parent_code.splitlines(),
            child_code.splitlines(),
            lineterm="",
        )
    )
    if len(diff) > 4000:
        diff = diff[:4000]
    insight_json = json.dumps(insight, ensure_ascii=False, sort_keys=True)
    user = f"""{TRANSLATE_MARKER}
Translate the code change into a testable claim JSON wrapped in <claim></claim>.
Required keys: title, condition, feature_code, outcome, direction (+ or -), scope, falsifier, category, tags.
feature_code must define def feature(history): returning a pandas Series indexed by unit id.

Insight:
{insight_json}

Schema note:
{frames_note}

Diff:
{diff}
"""
    text = llm_call([{"role": "user", "content": user}])
    data = extract_claim_from_response(text)
    if data is None:
        return None
    category = data.get("category", "feature_engineering")
    if category not in VALID_CATEGORIES:
        category = "feature_engineering"
    tags = data.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    return Claim(
        source="insight",
        title=str(data["title"]),
        condition=str(data["condition"]),
        feature_code=str(data["feature_code"]),
        outcome=str(data["outcome"]),
        direction=data["direction"],
        scope=str(data["scope"]),
        falsifier=str(data["falsifier"]),
        category=category,
        tags=[str(t) for t in tags],
    )
