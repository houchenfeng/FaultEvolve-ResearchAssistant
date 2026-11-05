#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/hcf/faultevolve-dl
NAS=/home/hcf/nas_hcf_data
test "$(findmnt -n -T "$NAS" -o SOURCE)" = //10.62.192.79/public/hcf_data
while tmux has-session -t =fe-dl-ranking 2>/dev/null; do sleep 15; done
cd "$ROOT/code-v8"
OUTPUT="$NAS/faultevolve-dl/runs/feedback_20261021"
"$ROOT/env/bin/python" -u experiments/hdd_dl/controller.py \
  --repo "$ROOT/code-v8" --output "$OUTPUT" \
  --seed-records "$NAS/faultevolve-dl/runs/hypotheses_20261021/trials.json" \
  --baseline "$ROOT/code-v8/benchmark/hdd_mvp/init.py" \
  --baseline /home/hcf/faultevolve/three_island_20261008-200410/formal/artifacts/hdd_mvp_formal2b_20261009/programs/4016914b.py \
  --baseline "$NAS/faultevolve/runs/final_B/f9752fcd/programs/d8f34173.py" \
  --trials 48 --hours 8 --gpu 0 --planner --planner-model qwen3.8-flash \
  --planner-max-calls 6 --env-file /home/hcf/faultevolve/.env
