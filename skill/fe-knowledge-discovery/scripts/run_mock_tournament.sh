#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
TASK="${ROOT}/tests/fixtures/toy_task"
export PATH="${HOME}/.local/bin:${PATH}"
OUT="${FE_RUNS_DIR:-/tmp/fe_tournament_runs}"
mkdir -p "$OUT"
RES=$(fe evolve start "$TASK" --mock -n 6 --json --runs-dir "$OUT" 2>/dev/null | tail -1)
EXP=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['experiment_id'])" "$RES")
ART="$OUT/$EXP"
python3 "$ROOT/skill/fe-knowledge-discovery/scripts/check_tournament_summary.py" "$ART"
echo "mock tournament check finished for $EXP"
