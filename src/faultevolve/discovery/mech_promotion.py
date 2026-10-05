"""Promote established mechanisms to discovery cards."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from faultevolve.discovery.schemas import Claim, Mechanism
from faultevolve.knowledge.loader import validate_card


def _existing_mech_seq(cards_path: Path, experiment_id: str) -> int:
    if not cards_path.exists():
        return 0
    pat = re.compile(rf"^D-{re.escape(experiment_id)}-M(\d+)$")
    max_seq = 0
    with cards_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            cid = data.get("id", "")
            m = pat.match(cid)
            if m:
                max_seq = max(max_seq, int(m.group(1)))
    return max_seq


def promote_mechanisms(
    established: list[Mechanism],
    claims: dict[str, Claim],
    cards_path: Path,
    experiment_id: str,
    log_event: Callable[[str, dict], None] | None = None,
) -> list[dict]:
    if cards_path.name == "cards.jsonl":
        raise ValueError("discovered cards must not write to cards.jsonl")
    seen_hash: set[str] = set()
    if cards_path.exists():
        with cards_path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                    if row.get("prereg_hash"):
                        seen_hash.add(row["prereg_hash"])
                except json.JSONDecodeError:
                    continue
    seq = _existing_mech_seq(cards_path, experiment_id)
    promoted: list[dict] = []
    cards_path.parent.mkdir(parents=True, exist_ok=True)
    for m in established:
        claim = claims.get(m.claim_id)
        if claim is None:
            continue
        prereg = claim.prereg_hash
        if prereg in seen_hash:
            continue
        seq += 1
        card_id = f"D-{experiment_id}-M{seq:03d}"
        category = claim.category if claim.category == "pitfalls" else "feature_engineering"
        card = {
            "id": card_id,
            "title": m.title[:120],
            "category": category,
            "priority": 1,
            "evidence": "run",
            "grade": "established",
            "source_ids": [
                f"run:{experiment_id}",
                f"mechanism:{m.id}",
                f"claim:{claim.id}",
            ],
            "claim": f"{m.title} ({claim.scope})"[:400],
            "impl_hint": claim.feature_code[:600],
            "tags": list(claim.tags),
            "prereg_hash": prereg,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        validate_card(card)
        with cards_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(card, ensure_ascii=False) + "\n")
        seen_hash.add(prereg)
        promoted.append(card)
        if log_event:
            log_event("mechanism_card_promoted", {"card_id": card_id, "mechanism_id": m.id})
    return promoted
