#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TMP="$(mktemp -d)"
OUT="$ROOT/.fe-budget-mock"
trap 'rm -rf "$TMP"' EXIT

cp -R "$ROOT/tests/fixtures/toy_task" "$TMP/task"
cat > "$TMP/task/evolve.yaml" <<'YAML'
budget:
  max_iterations: 12
  max_tokens: 20000
  max_wall_hours: 1
  stage_caps: {reflect: 0.01}
  stagnation_window: 4
  min_iterations_before_stop: 0
selection:
  policy: uct
  value:
    mode: multi
    rank_keys: [auprc, recall_at_far]
    noise_key: f1_boot_std
    elite_m: 3
    elite_prob: 0.2
smoke_test: {enabled: false}
YAML
rm -rf "$OUT"
python3 -m faultevolve.cli evolve local "$TMP/task" --mock --iterations 12 \
  --runs-dir "$TMP/runs" --artifacts-dir "$OUT" --json
python3 "$ROOT/skill/fe-node-value-budget/scripts/check_budget_summary.py" "$OUT"
