#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/hcf/faultevolve-dl
NAS=/home/hcf/nas_hcf_data
test "$(findmnt -n -T "$NAS" -o SOURCE)" = //10.62.192.79/public/hcf_data
while tmux has-session -t =fe-dl-knowledge 2>/dev/null; do sleep 15; done
cd "$ROOT/code-v7"
"$ROOT/env/bin/python" - <<'PY'
import importlib.util
import json
from pathlib import Path
spec = importlib.util.spec_from_file_location("controller", "experiments/hdd_dl/controller.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
nas = Path("/home/hcf/nas_hcf_data")
out = nas / "faultevolve-dl/runs/ranking_sources_20261021"
c.guard(nas, out)
out.mkdir(exist_ok=True)
source = json.loads((nas / "faultevolve-dl/runs/balanced_20261020/summary.json").read_text())
template = Path("experiments/hdd_dl/candidate.py").read_text()
for weight in (0.0, 0.1, 0.3):
    config = {**c.DEFAULT, **source["best"]["config"], "replicas": 1, "ranking_weight": weight}
    text = c.render(template, config)
    path = out / f"ranking_{weight}.py"
    if path.exists():
        assert path.read_text() == text, "Frozen candidate changed"
    else:
        path.write_text(text)
PY
SOURCE="$NAS/faultevolve-dl/runs/ranking_sources_20261021"
OUTPUT="$NAS/faultevolve-dl/runs/verify_ranking_20261021"
"$ROOT/env/bin/python" -u experiments/hdd_dl/verify.py \
  --repo "$ROOT/code-v7" --output "$OUTPUT" \
  --candidate "$SOURCE/ranking_0.0.py" --candidate "$SOURCE/ranking_0.1.py" --candidate "$SOURCE/ranking_0.3.py" \
  --baseline "$ROOT/code-v7/benchmark/hdd_mvp/init.py" \
  --baseline /home/hcf/faultevolve/three_island_20261008-200410/formal/artifacts/hdd_mvp_formal2b_20261009/programs/4016914b.py \
  --baseline "$NAS/faultevolve/runs/final_B/f9752fcd/programs/d8f34173.py" \
  --seeds 20261030,20261031,20261101 --gpu 0
for weight in 0.1 0.3; do
  "$ROOT/env/bin/python" experiments/hdd_dl/paired_report.py \
    --records "$OUTPUT/records.json" --control "$SOURCE/ranking_0.0.py" --treatment "$SOURCE/ranking_$weight.py" \
    --seeds 20261030,20261031,20261101 --out "$OUTPUT/paired_$weight.json"
done
