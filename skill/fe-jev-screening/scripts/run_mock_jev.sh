#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TMP="$(mktemp -d)"
OUT="$ROOT/.fe-jev-mock"
trap 'rm -rf "$TMP"' EXIT

cp -R "$ROOT/tests/fixtures/toy_task" "$TMP/task"
cat > "$TMP/task/evolve.yaml" <<'YAML'
budget: {max_iterations: 12, max_tokens: 3000000, max_wall_hours: 1}
selection: {policy: jev_puct, c_puct: 1.2}
judge:
  provider: mock
  prescreen: true
  warmup: 2
  audit_rate: 0.5
  invalid_threshold: 0.85
  low_value_threshold: 0.15
  prior: true
  prior_tau: 0.5
smoke_test: {enabled: false}
YAML
rm -rf "$OUT"
python3 -m faultevolve.cli evolve local "$TMP/task" --mock --iterations 12 \
  --runs-dir "$TMP/runs" --artifacts-dir "$OUT" --json
python3 "$ROOT/skill/fe-jev-screening/scripts/check_jev_summary.py" "$OUT"
