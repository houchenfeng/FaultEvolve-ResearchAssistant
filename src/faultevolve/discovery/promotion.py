"""Promote graded claims to discovered knowledge cards."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from faultevolve.discovery.schemas import Claim, ControlReport, Grade
from faultevolve.knowledge.loader import validate_card


def _existing_exp_seq(cards_path: Path, experiment_id: str) -> int:
    if not cards_path.exists():
        return 0
    prefix = f"D-{experiment_id}-"
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
            if cid.startswith(prefix):
                tail = cid[len(prefix):]
                if tail.isdigit():
                    max_seq = max(max_seq, int(tail))
    return max_seq


def _column_tags(feature_code: str, colnames: list[str]) -> list[str]:
    tags: list[str] = []
    for c in colnames:
        if re.search(rf"\b{re.escape(c)}\b", feature_code):
            tags.append(c)
    return tags


def promote_claims(
    items: list[tuple[Claim, dict]],
    controls: ControlReport,
    cards_path: Path,
    experiment_id: str,
    run_best_score: float,
    baseline_cols: list[str] | None = None,
    log_event=None,
) -> list[dict]:
    if cards_path.name == "cards.jsonl":
        raise ValueError("discovered cards must not write to cards.jsonl")
    if not controls.passed:
        return []
    baseline_cols = baseline_cols or []
    cards_path.parent.mkdir(parents=True, exist_ok=True)
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
    seq = _existing_exp_seq(cards_path, experiment_id)
    promoted: list[dict] = []
    for claim, test_payload in items:
        if claim.grade not in {Grade.DISCOVERED, Grade.REVISED}:
            continue
        if claim.prereg_hash in seen_hash:
            continue
        seq += 1
        card_id = f"D-{experiment_id}-{seq:03d}"
        while any(p.get("id") == card_id for p in promoted):
            seq += 1
            card_id = f"D-{experiment_id}-{seq:03d}"
        effect = test_payload.get("effect", 0)
        ci_low = test_payload.get("ci_low", 0)
        ci_high = test_payload.get("ci_high", 0)
        rationale = (
            f"effect={effect:.4f}, CI=[{ci_low:.4f},{ci_high:.4f}], "
            f"p={test_payload.get('p', 0):.4g}, e={test_payload.get('e', 0):.4g}, n={test_payload.get('n', 0)}"
        )
        tags = list(set(claim.tags) | set(_column_tags(claim.feature_code, baseline_cols)))
        card = {
            "id": card_id,
            "title": claim.title,
            "claim": claim.outcome,
            "category": claim.category,
            "rationale": rationale,
            "applicability": claim.scope,
            "expected_effect": f"{effect:.4f} (CI {ci_low:.4f}..{ci_high:.4f})",
            "risk": "数据驱动发现，未经文献验证；仅在训练集确认切片上检验",
            "source_ids": [
                f"run:{experiment_id}",
                f"node:{claim.origin_node_id}",
                f"claim:{claim.id}",
            ],
            "tags": tags,
            "impl_hint": claim.feature_code[:600],
            "priority": 2 if claim.grade == Grade.DISCOVERED else 3,
            "evidence": "run",
            "grade": claim.grade.value if claim.grade else "",
            "prereg_hash": claim.prereg_hash,
            "confirms": claim.confirms,
            "revises": claim.revises,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        ok, err = validate_card(card)
        if not ok:
            if log_event:
                log_event("card_rejected", {"claim_id": claim.id, "error": err})
            continue
        with cards_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(card, ensure_ascii=False) + "\n")
            f.flush()
        seen_hash.add(claim.prereg_hash)
        promoted.append(card)
    return promoted
