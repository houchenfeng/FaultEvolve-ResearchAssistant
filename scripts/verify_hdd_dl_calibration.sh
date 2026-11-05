#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/hcf/faultevolve-dl
NAS=/home/hcf/nas_hcf_data
test "$(findmnt -n -T "$NAS" -o SOURCE)" = //10.62.192.79/public/hcf_data
while tmux has-session -t =fe-dl-compact 2>/dev/null; do sleep 15; done
cd "$ROOT/code-v13"
"$ROOT/env/bin/python" - <<'PY'
import importlib.util
import json
from pathlib import Path
spec = importlib.util.spec_from_file_location("controller", "experiments/hdd_dl/controller.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
nas = Path("/home/hcf/nas_hcf_data")
out = nas / "faultevolve-dl/runs/calibration_sources_20261021"
c.guard(nas, out)
out.mkdir(exist_ok=True)
records = json.loads((nas / "faultevolve-dl/runs/hybrid_search_20261021/trials.json").read_text())
source = next(r for r in records if r["trial"] == 31)
original = nas / "faultevolve-dl/runs/hybrid_search_20261021/candidate_0031.py"
assert c.sha(original) == source["candidate_sha256"]
template = Path("experiments/hdd_dl/candidate.py").read_text()
source["config"].update(replicas=1, lr=0.001, epochs=30)
variants = {"original": {}, "raw_unit": {"threshold_scale": 1.0},
            "aligned": {"threshold_scale": 1.0, "fold_calibration": "threshold_ratio"}}
for name, changes in variants.items():
    text = c.render(template, {**source["config"], **changes})
    path = out / f"{name}.py"
    if path.exists():
        assert path.read_text() == text, "Frozen candidate changed"
    else:
        path.write_text(text)
PY
SOURCE="$NAS/faultevolve-dl/runs/calibration_sources_20261021"
OUTPUT="$NAS/faultevolve-dl/runs/verify_calibration_20261021"
"$ROOT/env/bin/python" -u experiments/hdd_dl/verify.py \
  --repo "$ROOT/code-v13" --output "$OUTPUT" \
  --candidate "$SOURCE/original.py" --candidate "$SOURCE/raw_unit.py" --candidate "$SOURCE/aligned.py" \
  --baseline "$ROOT/code-v13/benchmark/hdd_mvp/init.py" \
  --baseline /home/hcf/faultevolve/three_island_20261008-200410/formal/artifacts/hdd_mvp_formal2b_20261009/programs/4016914b.py \
  --baseline "$NAS/faultevolve/runs/final_B/f9752fcd/programs/d8f34173.py" \
  --seeds 20261120,20261121,20261122 --gpu 0
for variant in raw_unit aligned; do
  "$ROOT/env/bin/python" experiments/hdd_dl/paired_report.py \
    --records "$OUTPUT/records.json" --control "$SOURCE/original.py" --treatment "$SOURCE/$variant.py" \
    --seeds 20261120,20261121,20261122 --out "$OUTPUT/paired_$variant.json"
done
"$ROOT/env/bin/python" experiments/hdd_dl/paired_report.py \
  --records "$OUTPUT/records.json" --control "$SOURCE/raw_unit.py" --treatment "$SOURCE/aligned.py" \
  --seeds 20261120,20261121,20261122 --out "$OUTPUT/paired_alignment_only.json"
