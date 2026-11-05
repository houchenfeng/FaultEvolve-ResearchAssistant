#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/hcf/faultevolve-dl
NAS=/home/hcf/nas_hcf_data
test "$(findmnt -n -T "$NAS" -o SOURCE)" = //10.62.192.79/public/hcf_data
while tmux has-session -t =fe-dl-hypotheses 2>/dev/null; do sleep 15; done
cd "$ROOT/code-v6"
"$ROOT/env/bin/python" - <<'PY'
import importlib.util
import json
from pathlib import Path
spec = importlib.util.spec_from_file_location("controller", "experiments/hdd_dl/controller.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
nas = Path("/home/hcf/nas_hcf_data")
out = nas / "faultevolve-dl/runs/replicas_sources_20261021"
c.guard(nas, out)
out.mkdir(exist_ok=True)
source = json.loads((nas / "faultevolve-dl/runs/balanced_20261020/summary.json").read_text())
template = Path("experiments/hdd_dl/candidate.py").read_text()
for name in ("best", "balanced"):
    for replicas in (1, 3):
        config = {**c.DEFAULT, **source[name]["config"], "replicas": replicas}
        text = c.render(template, config)
        path = out / f"{name}_{replicas}.py"
        if path.exists():
            assert path.read_text() == text, "Frozen candidate changed"
        else:
            path.write_text(text)
PY
SOURCE="$NAS/faultevolve-dl/runs/replicas_sources_20261021"
"$ROOT/env/bin/python" -u experiments/hdd_dl/verify.py \
  --repo "$ROOT/code-v6" --output "$NAS/faultevolve-dl/runs/verify_replicas_20261021" \
  --candidate "$SOURCE/best_1.py" --candidate "$SOURCE/best_3.py" \
  --candidate "$SOURCE/balanced_1.py" --candidate "$SOURCE/balanced_3.py" \
  --baseline "$ROOT/code-v6/benchmark/hdd_mvp/init.py" \
  --baseline /home/hcf/faultevolve/three_island_20261008-200410/formal/artifacts/hdd_mvp_formal2b_20261009/programs/4016914b.py \
  --baseline "$NAS/faultevolve/runs/final_B/f9752fcd/programs/d8f34173.py" \
  --seeds 20261024,20261025,20261026 --gpu 0
