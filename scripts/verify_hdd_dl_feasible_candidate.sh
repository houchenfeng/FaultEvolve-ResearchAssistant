#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/hcf/faultevolve-dl
NAS=/home/hcf/nas_hcf_data
test "$(findmnt -n -T "$NAS" -o SOURCE)" = //10.62.192.79/public/hcf_data
cd "$ROOT/code-v41"
"$ROOT/env/bin/python" - <<'PY'
import hashlib
import json
from pathlib import Path
root = Path('/home/hcf/nas_hcf_data/faultevolve-dl/runs/resource_search_20261021')
rows = json.loads((root / 'trials.json').read_text())
for trial in (1, 3):
    row = next(r for r in rows if r['trial'] == trial)
    path = root / f'candidate_{trial:04d}.py'
    assert row['result']['validity'] == 1
    assert hashlib.sha256(path.read_bytes()).hexdigest() == row['candidate_sha256']
PY
SOURCE="$NAS/faultevolve-dl/runs/resource_search_20261021"
OUTPUT="$NAS/faultevolve-dl/runs/verify_feasible_candidate_20261021"
"$ROOT/env/bin/python" -u experiments/hdd_dl/verify.py \
  --repo "$ROOT/code-v41" --output "$OUTPUT" \
  --candidate "$SOURCE/candidate_0001.py" --candidate "$SOURCE/candidate_0003.py" \
  --baseline "$ROOT/code-v41/benchmark/hdd_mvp/init.py" \
  --baseline /home/hcf/faultevolve/three_island_20261008-200410/formal/artifacts/hdd_mvp_formal2b_20261009/programs/4016914b.py \
  --baseline "$NAS/faultevolve/runs/final_B/f9752fcd/programs/d8f34173.py" \
  --seeds 20270321,20270322,20270323 --gpu 0
"$ROOT/env/bin/python" experiments/hdd_dl/paired_report.py \
  --records "$OUTPUT/records.json" --control "$SOURCE/candidate_0001.py" \
  --treatment "$SOURCE/candidate_0003.py" --seeds 20270321,20270322,20270323 \
  --out "$OUTPUT/paired.json"
