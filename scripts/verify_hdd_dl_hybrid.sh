#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/hcf/faultevolve-dl
NAS=/home/hcf/nas_hcf_data
test "$(findmnt -n -T "$NAS" -o SOURCE)" = //10.62.192.79/public/hcf_data
while tmux has-session -t =fe-dl-context-search 2>/dev/null; do sleep 15; done
cd "$ROOT/code-v11"
"$ROOT/env/bin/python" - <<'PY'
import importlib.util
import json
from pathlib import Path
spec = importlib.util.spec_from_file_location("controller", "experiments/hdd_dl/controller.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
nas = Path("/home/hcf/nas_hcf_data")
out = nas / "faultevolve-dl/runs/hybrid_sources_20261021"
c.guard(nas, out)
out.mkdir(exist_ok=True)
source = json.loads((nas / "faultevolve-dl/runs/balanced_20261020/summary.json").read_text())
template = Path("experiments/hdd_dl/candidate.py").read_text()
for weight in (0.0, 0.25, 0.5):
    config = {**c.DEFAULT, **source["best"]["config"], "replicas": 1, "tree_blend": weight}
    text = c.render(template, config)
    path = out / f"hybrid_{weight}.py"
    if path.exists():
        assert path.read_text() == text, "Frozen candidate changed"
    else:
        path.write_text(text)
PY
SOURCE="$NAS/faultevolve-dl/runs/hybrid_sources_20261021"
OUTPUT="$NAS/faultevolve-dl/runs/verify_hybrid_20261021"
"$ROOT/env/bin/python" -u experiments/hdd_dl/verify.py \
  --repo "$ROOT/code-v11" --output "$OUTPUT" \
  --candidate "$SOURCE/hybrid_0.0.py" --candidate "$SOURCE/hybrid_0.25.py" --candidate "$SOURCE/hybrid_0.5.py" \
  --baseline "$ROOT/code-v11/benchmark/hdd_mvp/init.py" \
  --baseline /home/hcf/faultevolve/three_island_20261008-200410/formal/artifacts/hdd_mvp_formal2b_20261009/programs/4016914b.py \
  --baseline "$NAS/faultevolve/runs/final_B/f9752fcd/programs/d8f34173.py" \
  --seeds 20261108,20261109,20261110 --gpu 0
for weight in 0.25 0.5; do
  "$ROOT/env/bin/python" experiments/hdd_dl/paired_report.py \
    --records "$OUTPUT/records.json" --control "$SOURCE/hybrid_0.0.py" --treatment "$SOURCE/hybrid_$weight.py" \
    --seeds 20261108,20261109,20261110 --out "$OUTPUT/paired_$weight.json"
done
