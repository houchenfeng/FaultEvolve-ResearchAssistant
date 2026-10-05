"""Functional novelty and literature entailment."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable, Literal

from faultevolve.config import DiscoveryConfig
from faultevolve.discovery.schemas import Claim
from faultevolve.knowledge.loader import KnowledgeCard

ENTAIL_MARKER = "KD_ENTAIL"


@dataclass
class Entailment:
    relation: Literal["same", "opposite", "different_magnitude", "none", "unknown"]
    card_id: str | None = None
    attempts: int = 1
    reply_tail: str = ""


def functional_novel(rho_max_abs: float, incr_ci_low: float, cfg: DiscoveryConfig) -> bool:
    return rho_max_abs < cfg.rho_max and incr_ci_low > 0


def _parse_entailment_response(text: str, valid_ids: set[str]) -> Entailment:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return Entailment(relation="unknown", reply_tail=text[-200:])
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return Entailment(relation="unknown", reply_tail=text[-200:])
    rel = data.get("relation", "unknown")
    cid = data.get("card_id")
    if rel not in {"same", "opposite", "different_magnitude", "none"}:
        return Entailment(relation="unknown", reply_tail=text[-200:])
    if cid is not None and cid not in valid_ids:
        return Entailment(relation="unknown", reply_tail=text[-200:])
    return Entailment(relation=rel, card_id=cid, reply_tail=text[-200:])


def judge_entailment(
    claim: Claim,
    cards: list[KnowledgeCard],
    llm_call: Callable[[list[dict[str, str]]], str],
) -> Entailment:
    card_lines = []
    valid_ids = {c.id for c in cards}
    for c in cards:
        if c.id.startswith("D-"):
            continue
        card_lines.append(json.dumps({"id": c.id, "title": c.title, "claim": c.claim}, ensure_ascii=False))
    cards_blob = "\n".join(card_lines) if card_lines else "(none)"
    prompt = f"""{ENTAIL_MARKER}
Blind entailment: compare the candidate claim to literature cards (id/title/claim only).
Respond with JSON {{"card_id": null or id, "relation": "same|opposite|different_magnitude|none"}}

Candidate title: {claim.title}
Candidate outcome: {claim.outcome}
Candidate condition: {claim.condition}

Literature cards:
{cards_blob}
"""
    text = llm_call([{"role": "user", "content": prompt}])
    ent = _parse_entailment_response(text, valid_ids)
    ent.attempts = 1
    if ent.relation == "unknown":
        text2 = llm_call([{"role": "user", "content": prompt}])
        ent2 = _parse_entailment_response(text2, valid_ids)
        ent2.attempts = 2
        return ent2
    return ent
