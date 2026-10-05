#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TMP="$(mktemp -d)"
OUT="$ROOT/.fe-crossover-mock"
trap 'rm -rf "$TMP"' EXIT

cp -R "$ROOT/tests/fixtures/toy_task" "$TMP/task"
cat > "$TMP/task/evolve.yaml" <<'YAML'
budget:
  max_iterations: 15
  max_tokens: 40000
  max_wall_hours: 1
operators:
  bandit: true
  enabled: [refine, threshold_calibrate]
  min_explore: 0.4
  crossover:
    enabled: true
    min_valid_nodes: 3
smoke_test:
  enabled: false
YAML
rm -rf "$OUT"
python3 -m faultevolve.cli evolve local "$TMP/task" --mock --iterations 15 \
  --runs-dir "$TMP/runs" --artifacts-dir "$OUT" --json
python3 "$ROOT/skill/fe-crossover-ensemble/scripts/check_crossover_summary.py" "$OUT"
