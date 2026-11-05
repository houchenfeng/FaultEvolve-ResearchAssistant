#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/hcf/faultevolve-dl
NAS=/home/hcf/nas_hcf_data
test "$(findmnt -n -T "$NAS" -o SOURCE)" = //10.62.192.79/public/hcf_data
while tmux has-session -t =fe-dl-contrast 2>/dev/null; do sleep 15; done
cd "$ROOT/code-v20"
"$ROOT/env/bin/python" - <<'PY'
import importlib.util
import json
from pathlib import Path
spec = importlib.util.spec_from_file_location("controller", "experiments/hdd_dl/controller.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
nas = Path("/home/hcf/nas_hcf_data")
root = nas / "faultevolve-dl/runs/evidence_search_20261021"
row = json.loads((root / "summary.json").read_text())["balanced"]
assert row["trial"] == 10
original = root / "candidate_0010.py"
assert c.sha(original) == row["candidate_sha256"]
out = nas / "faultevolve-dl/runs/capacity_sources_20261021"
c.guard(nas, out)
out.mkdir(exist_ok=True)
for name, width in (("original", 128), ("small", 64), ("large", 256)):
    text = c.render(Path("experiments/hdd_dl/candidate.py").read_text(), {**row["config"], "smart_subset": "all", "width": width, "model_identity": False, "threshold_estimator": "empirical"})
    path = out / f"{name}.py"
    if path.exists():
        assert path.read_text() == text, "Frozen candidate changed"
    else:
        path.write_text(text)
PY
SOURCE="$NAS/faultevolve-dl/runs/capacity_sources_20261021"
OUTPUT="$NAS/faultevolve-dl/runs/verify_capacity_20261021"
"$ROOT/env/bin/python" -u experiments/hdd_dl/verify.py \
  --repo "$ROOT/code-v20" --output "$OUTPUT" \
  --candidate "$SOURCE/original.py" --candidate "$SOURCE/small.py" --candidate "$SOURCE/large.py" \
  --baseline "$ROOT/code-v20/benchmark/hdd_mvp/init.py" \
  --baseline /home/hcf/faultevolve/three_island_20261008-200410/formal/artifacts/hdd_mvp_formal2b_20261009/programs/4016914b.py \
  --baseline "$NAS/faultevolve/runs/final_B/f9752fcd/programs/d8f34173.py" \
  --seeds 20270113,20270114,20270115 --gpu 0
for variant in small large; do
  "$ROOT/env/bin/python" experiments/hdd_dl/paired_report.py \
    --records "$OUTPUT/records.json" --control "$SOURCE/original.py" \
    --treatment "$SOURCE/$variant.py" --seeds 20270113,20270114,20270115 \
    --out "$OUTPUT/paired_$variant.json"
done
