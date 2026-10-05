#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TMP="$(mktemp -d)"
OUT="$ROOT/.fe-operators-mock"
trap 'rm -rf "$TMP"' EXIT

cp -R "$ROOT/tests/fixtures/toy_task" "$TMP/task"
cat > "$TMP/task/evolve.yaml" <<'YAML'
budget:
  max_iterations: 12
  max_tokens: 20000
  max_wall_hours: 1
operators:
  bandit: true
  enabled: [refine, threshold_calibrate]
  min_explore: 0.4
smoke_test:
  enabled: false
YAML
rm -rf "$OUT"
python3 -m faultevolve.cli evolve local "$TMP/task" --mock --iterations 12 \
  --runs-dir "$TMP/runs" --artifacts-dir "$OUT" --json
python3 "$ROOT/skill/fe-operators/scripts/check_operator_summary.py" "$OUT"
