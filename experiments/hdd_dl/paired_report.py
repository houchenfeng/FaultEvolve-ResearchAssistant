"""Report matched-seed differences; never interpret reused validation as a held-out test."""
import argparse
import json
import math
from pathlib import Path
import statistics


def compare(records, control, treatment, seeds):
    selected = {}
    for row in records:
        if row["candidate"] not in [control, treatment]:
            continue
        key = (row["candidate"], row["seed"])
        if key in selected:
            raise ValueError("Duplicate candidate/seed observation")
        selected[key] = row["result"]
    pairs = []
    for seed in seeds:
        a, b = selected.get((control, seed)), selected.get((treatment, seed))
        if a and b and a.get("validity") == b.get("validity") == 1:
            pairs.append((seed, a, b))
    metrics = {}
    for key in ["combined_score", "precision", "recall", "f1", "f1_p10", "auprc",
                "recall_at_far", "false_alarm_rate", "missed_detection_rate",
                "f1_boot_std", "run_time_s"]:
        deltas = []
        for seed, a, b in pairs:
            av = a.get(key) if key == "combined_score" else a.get("metric", {}).get(key)
            bv = b.get(key) if key == "combined_score" else b.get("metric", {}).get(key)
            if all(isinstance(v, (int, float)) and math.isfinite(v) for v in [av, bv]):
                deltas.append({"seed": seed, "treatment_minus_control": bv-av})
        lower = key in ["false_alarm_rate", "missed_detection_rate", "f1_boot_std", "run_time_s"]
        metrics[key] = {
            "pairs": deltas,
            "mean_delta": statistics.mean(d["treatment_minus_control"] for d in deltas) if deltas else None,
            "strict_wins": sum((d["treatment_minus_control"] < 0 if lower else
                                d["treatment_minus_control"] > 0) for d in deltas),
            "complete": len(deltas) == len(seeds),
        }
    return {"control": control, "treatment": treatment, "expected_seeds": seeds,
            "complete": all(m["complete"] for m in metrics.values()),
            "scope": "paired_training_seed_comparison_on_reused_validation",
            "independent_generalization": False, "metrics": metrics}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", required=True)
    parser.add_argument("--control", required=True)
    parser.add_argument("--treatment", required=True)
    parser.add_argument("--seeds", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    seeds = [int(s) for s in args.seeds.split(",")]
    if len(set(seeds)) != len(seeds) or len(seeds) < 2:
        parser.error("At least two distinct seeds required")
    report = compare(json.loads(Path(args.records).read_text(encoding="utf-8")),
                     args.control, args.treatment, seeds)
    Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
