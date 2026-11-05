#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/hcf/faultevolve-dl
NAS=/home/hcf/nas_hcf_data
test "$(findmnt -n -T "$NAS" -o SOURCE)" = //10.62.192.79/public/hcf_data
while tmux has-session -t =fe-dl-sequence-scale 2>/dev/null; do sleep 15; done
cd "$ROOT/code-v28"
OUTPUT="$NAS/faultevolve-dl/runs/consolidated_search_20261021"
BASELINES=(--baseline "$ROOT/code-v28/benchmark/hdd_mvp/init.py"
  --baseline /home/hcf/faultevolve/three_island_20261008-200410/formal/artifacts/hdd_mvp_formal2b_20261009/programs/4016914b.py
  --baseline "$NAS/faultevolve/runs/final_B/f9752fcd/programs/d8f34173.py")
"$ROOT/env/bin/python" -u experiments/hdd_dl/controller.py \
  --repo "$ROOT/code-v28" --output "$OUTPUT" \
  --seed-records "$NAS/faultevolve-dl/runs/evidence_search_20261021/trials.json" \
  "${BASELINES[@]}" --trials 48 --hours 8 --gpu 0 --planner \
  --planner-model qwen3.8-flash --planner-max-calls 6 --env-file /home/hcf/faultevolve/.env
test ! -e "$OUTPUT/STOP"
"$ROOT/env/bin/python" - <<'PY'
import hashlib
import json
from pathlib import Path
root = Path("/home/hcf/nas_hcf_data/faultevolve-dl/runs/consolidated_search_20261021")
status = json.loads((root / "status.json").read_text())
assert status["phase"] == "batch_complete" and status["trials"] == 48
summary = json.loads((root / "summary.json").read_text())
selected = []
for name in ("best", "balanced"):
    row = summary[name]
    assert row["result"]["validity"] == 1
    path = root / f'candidate_{row["trial"]:04d}.py'
    path.resolve().relative_to(root.resolve())
    assert hashlib.sha256(path.read_bytes()).hexdigest() == row["candidate_sha256"]
    if str(path) not in selected:
        selected.append(str(path))
text = "\n".join(selected) + "\n"
selection = root / "selected_candidates.txt"
if selection.exists():
    assert selection.read_text() == text, "Frozen selection changed"
else:
    selection.write_text(text)
PY
mapfile -t SELECTED < "$OUTPUT/selected_candidates.txt"
CANDIDATES=()
for path in "${SELECTED[@]}"; do CANDIDATES+=(--candidate "$path"); done
"$ROOT/env/bin/python" -u experiments/hdd_dl/verify.py \
  --repo "$ROOT/code-v28" --output "$OUTPUT/verification" \
  "${CANDIDATES[@]}" "${BASELINES[@]}" --seeds 20270210,20270211,20270212 --gpu 0
