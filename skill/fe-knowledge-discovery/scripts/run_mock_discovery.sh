#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
TASK="${ROOT}/tests/fixtures/toy_task"
export PATH="${HOME}/.local/bin:${PATH}"
fe doctor --json --task-dir "$TASK" >/dev/null
OUT="${FE_RUNS_DIR:-/tmp/fe_runs}"
mkdir -p "$OUT/datacheck"
fe data checkup "$TASK" --json --out "$OUT/datacheck" >/dev/null
RES=$(fe evolve start "$TASK" --mock -n 4 --json --runs-dir "$OUT" 2>/dev/null | tail -1)
EXP=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['experiment_id'])" "$RES")
fe discover run "$TASK" --run-id "$EXP" --mock --json --runs-dir "$OUT"
fe discover report "$TASK" --run-id "$EXP" --json --runs-dir "$OUT" >/tmp/kd_report.json
ART=$(python3 -c "import json; print(json.loads(open('/tmp/kd_report.json').read())['ok'])")
echo "mock discovery finished for $EXP"
