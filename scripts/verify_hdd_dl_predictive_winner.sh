#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/hcf/faultevolve-dl
NAS=/home/hcf/nas_hcf_data
test "$(findmnt -n -T "$NAS" -o SOURCE)" = //10.62.192.79/public/hcf_data
while tmux has-session -t =fe-dl-verified-search 2>/dev/null; do sleep 15; done
cd "$ROOT/code-v14"
"$ROOT/env/bin/python" -u experiments/hdd_dl/verify.py \
  --repo "$ROOT/code-v14" --output "$NAS/faultevolve-dl/runs/verify_predictive_winner_20261021" \
  --candidate "$NAS/faultevolve-dl/runs/verified_search_20261021/candidate_0001.py" \
  --baseline "$ROOT/code-v14/benchmark/hdd_mvp/init.py" \
  --baseline /home/hcf/faultevolve/three_island_20261008-200410/formal/artifacts/hdd_mvp_formal2b_20261009/programs/4016914b.py \
  --baseline "$NAS/faultevolve/runs/final_B/f9752fcd/programs/d8f34173.py" \
  --seeds 20261204,20261205,20261206 --gpu 0
