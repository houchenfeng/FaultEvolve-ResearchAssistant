#!/usr/bin/env bash
set -euo pipefail
ROOT=/home/hcf/faultevolve-dl
NAS=/home/hcf/nas_hcf_data
test "$(findmnt -n -T "$NAS" -o FSTYPE)" = cifs
test "$(findmnt -n -T "$NAS" -o SOURCE)" = //10.62.192.79/public/hcf_data
mkdir -p "$ROOT" "$ROOT/state" "$ROOT/install-tmp" "$NAS/faultevolve-dl/cache" "$NAS/faultevolve-dl/runs"
# pip rollback needs POSIX metadata operations unavailable on this CIFS mount.
# The installation scratch area is local and used only while >=150 GiB is free.
test "$(df -PB1 "$ROOT" | awk 'NR==2 {print $4}')" -gt 161061273600
export TMPDIR="$ROOT/install-tmp"
export PIP_CACHE_DIR="$NAS/faultevolve-dl/cache/pip"
export XDG_CACHE_HOME="$NAS/faultevolve-dl/cache/xdg"
if [ ! -e "$ROOT/env/bin/python" ]; then
  /home/hcf/miniconda3/envs/faultevolve/bin/python -m venv "$ROOT/env"
fi
"$ROOT/env/bin/python" -m ensurepip
"$ROOT/env/bin/python" -m pip install torch --index-url https://download.pytorch.org/whl/cu128
"$ROOT/env/bin/python" -m pip install numpy pandas scipy scikit-learn lightgbm pytest pyyaml httpx openai
"$ROOT/env/bin/python" -c 'import torch; print({"torch":torch.__version__,"cuda":torch.cuda.is_available(),"devices":torch.cuda.device_count()})'
