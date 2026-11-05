#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/hcf/faultevolve-dl
NAS=/home/hcf/nas_hcf_data
test "$(findmnt -n -T "$NAS" -o SOURCE)" = //10.62.192.79/public/hcf_data
while tmux has-session -t =fe-dl-hypotheses 2>/dev/null || tmux has-session -t =fe-dl-replicas 2>/dev/null; do sleep 15; done
cd "$ROOT/code-v6"
"$ROOT/env/bin/python" - <<'PY'
import importlib.util
import json
from pathlib import Path
spec = importlib.util.spec_from_file_location("controller", "experiments/hdd_dl/controller.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
nas = Path("/home/hcf/nas_hcf_data")
out = nas / "faultevolve-dl/runs/knowledge_sources_20261021"
c.guard(nas, out)
out.mkdir(exist_ok=True)
source = json.loads((nas / "faultevolve-dl/runs/balanced_20261020/summary.json").read_text())
template = Path("experiments/hdd_dl/candidate.py").read_text()
for features in ("basic", "trends"):
    config = {**c.DEFAULT, **source["best"]["config"], "replicas": 1, "feature_set": features}
    text = c.render(template, config)
    path = out / f"{features}.py"
    if path.exists():
        assert path.read_text() == text, "Frozen candidate changed"
    else:
        path.write_text(text)
PY
SOURCE="$NAS/faultevolve-dl/runs/knowledge_sources_20261021"
OUTPUT="$NAS/faultevolve-dl/runs/verify_knowledge_20261021"
"$ROOT/env/bin/python" -u experiments/hdd_dl/verify.py \
  --repo "$ROOT/code-v6" --output "$OUTPUT" \
  --candidate "$SOURCE/basic.py" --candidate "$SOURCE/trends.py" \
  --baseline "$ROOT/code-v6/benchmark/hdd_mvp/init.py" \
  --baseline /home/hcf/faultevolve/three_island_20261008-200410/formal/artifacts/hdd_mvp_formal2b_20261009/programs/4016914b.py \
  --baseline "$NAS/faultevolve/runs/final_B/f9752fcd/programs/d8f34173.py" \
  --seeds 20261027,20261028,20261029 --gpu 0
"$ROOT/env/bin/python" experiments/hdd_dl/paired_report.py \
  --records "$OUTPUT/records.json" --control "$SOURCE/basic.py" --treatment "$SOURCE/trends.py" \
  --seeds 20261027,20261028,20261029 --out "$OUTPUT/paired.json"
