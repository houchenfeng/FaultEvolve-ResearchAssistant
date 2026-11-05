#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/hcf/faultevolve-dl
NAS=/home/hcf/nas_hcf_data
test "$(findmnt -n -T "$NAS" -o SOURCE)" = //10.62.192.79/public/hcf_data
while tmux has-session -t =fe-dl-quality-replicas9 2>/dev/null; do sleep 15; done
cd "$ROOT/code-v69"
"$ROOT/env/bin/python" - <<'PY'
import importlib.util
import json
from pathlib import Path
spec = importlib.util.spec_from_file_location("controller", "experiments/hdd_dl/controller.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
nas = Path("/home/hcf/nas_hcf_data")
root = nas / "faultevolve-dl/runs/quality_search_20261021"
row = json.loads((root / "summary.json").read_text())["quality_balanced"]
assert row["trial"] == 11
original = root / "candidate_0011.py"
assert c.sha(original) == row["candidate_sha256"]
out = nas / "faultevolve-dl/runs/quality_focal_sources_20261021"
c.guard(nas, out)
out.mkdir(exist_ok=True)
for name, gamma in (("without", 0.0), ("with", 1.0)):
    text = c.render(Path("experiments/hdd_dl/candidate.py").read_text(), {**row["config"], "ranking_weight": 0.0, "tail_risk_weight": 0.0, "share_fold_preprocessing": True, "share_fold_tree": True, "fused_optimizer": False, "replicas": 3, "focal_gamma": gamma})
    path = out / f"{name}.py"
    if path.exists():
        assert path.read_text() == text, "Frozen candidate changed"
    else:
        path.write_text(text)
PY
SOURCE="$NAS/faultevolve-dl/runs/quality_focal_sources_20261021"
OUTPUT="$NAS/faultevolve-dl/runs/verify_quality_focal_20261021"
"$ROOT/env/bin/python" -u experiments/hdd_dl/verify.py \
  --repo "$ROOT/code-v69" --output "$OUTPUT" \
  --candidate "$SOURCE/without.py" --candidate "$SOURCE/with.py" \
  --baseline "$ROOT/code-v69/benchmark/hdd_mvp/init.py" \
  --baseline /home/hcf/faultevolve/three_island_20261008-200410/formal/artifacts/hdd_mvp_formal2b_20261009/programs/4016914b.py \
  --baseline "$NAS/faultevolve/runs/final_B/f9752fcd/programs/d8f34173.py" \
  --seeds 20270530,20270531,20270601 --gpu 0
"$ROOT/env/bin/python" experiments/hdd_dl/paired_report.py \
  --records "$OUTPUT/records.json" --control "$SOURCE/without.py" \
  --treatment "$SOURCE/with.py" --seeds 20270530,20270531,20270601 \
  --out "$OUTPUT/paired.json"
