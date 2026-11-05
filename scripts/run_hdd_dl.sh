#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/hcf/faultevolve-dl
NAS=/home/hcf/nas_hcf_data
for attempt in $(seq 1 120); do
  if ! tmux has-session -t =fe-dl-setup 2>/dev/null; then break; fi
  sleep 15
done
test "$(findmnt -n -T "$NAS" -o SOURCE)" = //10.62.192.79/public/hcf_data
cd "$ROOT/code"
export CUDA_VISIBLE_DEVICES=0
"$ROOT/env/bin/python" -c 'import torch; assert torch.cuda.is_available(); print(torch.__version__)'
"$ROOT/env/bin/python" -m pytest tests/test_hdd_dl_campaign.py -q
OUTPUT="$NAS/faultevolve-dl/runs/refine_20261020"
mkdir -p "$OUTPUT"
"$ROOT/env/bin/python" -m pip freeze > "$OUTPUT/environment.txt"
"$ROOT/env/bin/python" -u experiments/hdd_dl/controller.py \
  --repo "$ROOT/code" --output "$OUTPUT" \
  --baseline "$ROOT/code/benchmark/hdd_mvp/init.py" \
  --baseline /home/hcf/faultevolve/three_island_20261008-200410/formal/artifacts/hdd_mvp_formal2b_20261009/programs/4016914b.py \
  --baseline "$NAS/faultevolve/runs/final_B/f9752fcd/programs/d8f34173.py" \
  --trials 120 --hours 8 --gpu 0
