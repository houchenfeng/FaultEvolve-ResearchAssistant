#!/usr/bin/env python3
"""Build knowledge cards for FaultEvolve.

Usage:
    python build_cards.py --sources references/sources.yaml --expert references/expert.md --out <task>/knowledge/cards.jsonl
    python build_cards.py --validate-only cards.jsonl

Cards are currently hand-curated from sources.yaml and expert.md.
The arXiv/Semantic Scholar retrieval described in SKILL.md is not yet implemented;
to add new cards, manually add them to this script's card() calls.

Exit codes:
    0: Success
    1: Validation errors found
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any


VALID_CATEGORIES = [
    "feature_engineering", "model", "evaluation", "pitfalls",
    "thresholding", "labeling", "imbalance", "transfer", "ensembling"
]


def validate_card(card: dict[str, Any]) -> list[str]:
    """Validate a card against the schema.
    
    Returns list of error messages (empty if valid).
    """
    errors = []
    
    required = ["id", "title", "category", "claim", "source_ids", "tags"]
    for field in required:
        if field not in card:
            errors.append(f"Missing required field: {field}")
    
    if "id" in card and not card["id"]:
        errors.append("id cannot be empty")
    
    if "category" in card and card["category"] not in VALID_CATEGORIES:
        errors.append(f"Invalid category: {card['category']}. Valid: {VALID_CATEGORIES}")
    
    if "priority" in card:
        p = card["priority"]
        if not isinstance(p, int) or p < 1 or p > 5:
            errors.append(f"priority must be integer 1-5, got {p}")
    
    return errors


def load_and_validate(path: Path) -> tuple[list[dict], list[str]]:
    """Load cards from JSONL and validate each.
    
    Returns (cards, all_errors).
    """
    cards = []
    all_errors = []
    seen_ids = set()
    
    with path.open() as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            
            try:
                card = json.loads(line)
            except json.JSONDecodeError as e:
                all_errors.append(f"Line {i}: Invalid JSON: {e}")
                continue
            
            errs = validate_card(card)
            for e in errs:
                all_errors.append(f"Line {i} ({card.get('id', '?')}): {e}")
            
            card_id = card.get("id")
            if card_id:
                if card_id in seen_ids:
                    all_errors.append(f"Line {i}: Duplicate ID: {card_id}")
                else:
                    seen_ids.add(card_id)
                    cards.append(card)
    
    return cards, all_errors


# ============== CARD DEFINITIONS ==============
# Cards are hand-curated from sources.yaml and expert.md
# To add new cards: add a card() call below

CARDS: list[dict] = []

def card(id, title, category, claim, rationale, applicability, expected_effect, risk, source_ids, tags,
         impl_hint, priority, evidence="paper"):
    """Register a card."""
    CARDS.append(dict(
        id=id, title=title, category=category, claim=claim, rationale=rationale,
        applicability=applicability, expected_effect=expected_effect, risk=risk,
        source_ids=source_ids, tags=tags, impl_hint=impl_hint, priority=priority,
        evidence=evidence
    ))


def build_all_cards():
    """Build all cards. Call card() for each."""
    
    # ---- feature engineering ----
    card("FE01", "Window deltas of critical error counters", "feature_engineering",
         "Adding per-disk deltas over the 14-day window for smart_5/187/188/197/198/199 raw will raise AUPRC.",
         "Backblaze notes these counters are cumulative; jumps signal risk more than totals.",
         "All vendors; 187/188 mostly Seagate.", "Large", 
         "Counter resets must be clipped.",
         ["backblaze2016", "botezatu2016"], ["smart_5", "smart_187", "trend", "delta"],
         "g=h.sort_values('date').groupby('serial_number'); delta=g[c].last()-g[c].first()", 1)
    
    card("FE02", "Error growth rate normalised by observed days", "feature_engineering",
         "Dividing each counter delta by observed days and using log1p for trend features.",
         "Rate-based features are robust to missing days and short histories.",
         "Any disk with >=2 rows.", "Medium",
         "Division by small spans can explode.",
         ["backblaze2016", "han2019"], ["rate", "missing_days"],
         "rate = (last-first)/max(1, days); feature=np.log1p(rate.clip(0))", 2)
    
    card("FE03", "First-appearance flags for reallocation", "feature_engineering",
         "Binary features 'became non-zero inside window' for smart_5, 197, 198.",
         "First scan error raises 60-day failure risk 39x (Google study).",
         "All vendors.", "Medium-large",
         "Stable old reallocations are common in healthy disks.",
         ["pinheiro2007", "backblaze2016"], ["smart_5", "smart_197", "onset"],
         "became = (~nz.iloc[:,0]) & nz.iloc[:,-1]", 1)
    
    # ---- model ----
    card("M01", "LightGBM on engineered window features", "model",
         "LightGBM (num_leaves 15-31, learning_rate 0.03-0.05) outperforms LR significantly.",
         "GBDT dominates failure prediction in production and competitions.",
         "Always; trains in seconds.", "Large",
         "Keep leaves small for 1104 positives.",
         ["ke2017", "pakdd2020"], ["lightgbm", "gbdt"],
         "lgb.LGBMClassifier(n_estimators=600, num_leaves=31, min_child_samples=30)", 1)
    
    # ---- thresholding ----
    card("T01", "Pick threshold on OOF scores, not in-sample", "thresholding",
         "OOF-based threshold will raise val F1 vs in-sample (init.py weakness).",
         "In-sample scores of boosted trees are overconfident.",
         "Any model with alarm output.", "Medium-large",
         "OOF threshold on refit model may shift slightly.",
         ["lipton2014"], ["threshold", "oof", "f1"],
         "threshold = argmax over OOF grid", 1)
    
    # ---- evaluation ----
    card("E01", "Replicate ROS on OOF predictions", "evaluation",
         "Implementing evaluator's weighted F1_p10 on grouped 5-fold OOF will correlate with val ROS.",
         "The score combines three metrics with specific weighting.",
         "Always; costs seconds.", "Medium indirect",
         "Q3 OOF differs from Q4 val (drift).",
         ["BENCH"], ["oof", "metric_replication", "cv"],
         "Copy weighted_auprc / bootstrap_f1 logic; StratifiedKFold(5, shuffle=True)", 1)


def write_cards(output_path: Path) -> int:
    """Build and write cards to output file.
    
    Returns number of cards written.
    """
    build_all_cards()
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with output_path.open("w", encoding="utf-8") as f:
        for c in CARDS:
            c["idea"] = c["claim"]
            c["source"] = ", ".join(c["source_ids"])
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    
    return len(CARDS)


def main():
    parser = argparse.ArgumentParser(
        description="Build or validate knowledge cards for FaultEvolve",
        epilog="Cards are hand-curated. To add cards, edit the card() calls in this script."
    )
    parser.add_argument(
        "--sources", type=Path,
        help="Path to sources.yaml (for reference, not yet parsed)"
    )
    parser.add_argument(
        "--expert", type=Path,
        help="Path to expert.md (for reference, not yet parsed)"
    )
    parser.add_argument(
        "--out", type=Path,
        help="Output path for cards.jsonl. Required unless --validate-only."
    )
    parser.add_argument(
        "--validate-only", type=Path, metavar="CARDS_FILE",
        help="Validate an existing cards.jsonl and exit"
    )
    
    args = parser.parse_args()
    
    if args.validate_only:
        cards, errors = load_and_validate(args.validate_only)
        if errors:
            print(f"Validation FAILED with {len(errors)} errors:", file=sys.stderr)
            for e in errors:
                print(f"  {e}", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"Validation PASSED: {len(cards)} cards OK")
            sys.exit(0)
    
    if not args.out:
        parser.error("--out is required unless --validate-only is used")
    
    if args.sources and not args.sources.exists():
        print(f"Warning: --sources file not found: {args.sources}", file=sys.stderr)
    if args.expert and not args.expert.exists():
        print(f"Warning: --expert file not found: {args.expert}", file=sys.stderr)
    
    count = write_cards(args.out)
    print(f"Wrote {count} cards to {args.out}")
    
    cards, errors = load_and_validate(args.out)
    if errors:
        print(f"Validation FAILED with {len(errors)} errors:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"Validation PASSED: {len(cards)} cards OK")


if __name__ == "__main__":
    main()
