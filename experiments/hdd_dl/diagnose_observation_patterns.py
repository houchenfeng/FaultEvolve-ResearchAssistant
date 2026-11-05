"""Aggregate training-only observation patterns; never read validation/holdout."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import candidate
import controller

root = Path('/home/hcf/nas_hcf_data')
data = root / 'faultevolve/data/hdd_mvp/public'
out = root / 'faultevolve-dl/runs/observation_patterns_20261021'
controller.guard(root, out)
out.mkdir(exist_ok=False)
index = pd.read_csv(data / 'train_labels.csv')
history = pd.read_csv(data / 'train_history.csv.gz')
columns = sorted(c for c in history if c.startswith('smart_'))
candidate.CONFIG = {}
_, seq = candidate.features(history, index, columns)
mask = seq[:, len(columns):] > 0
counts = mask.sum(axis=2)
intermittent = (counts > 0) & (counts < 14)
result = {
    'scope': 'training_only_observation_diagnostic_not_benchmark',
    'devices': len(index), 'smart_channels': len(columns),
    'observed_fraction': float(mask.mean()),
    'intermittent_device_channel_fraction': float(intermittent.mean()),
    'never_observed_device_channel_fraction': float((counts == 0).mean()),
    'fully_observed_device_channel_fraction': float((counts == 14).mean()),
    'devices_with_intermittent_channel_fraction': float(intermittent.any(axis=1).mean()),
    'gap_after_observation_cells': int(((np.maximum.accumulate(mask,axis=2)) & ~mask).sum()),
    'observed_zero_cells': int(((seq[:,:len(columns)] == 0) & mask).sum()),
    'data_hashes': {n: controller.sha(data / n) for n in ('train_labels.csv','train_history.csv.gz')},
    'runner_sha256': controller.sha(Path(__file__)),
    'candidate_sha256': controller.sha(Path(candidate.__file__)),
}
controller.write_json(out / 'diagnostics.json', result)
print(json.dumps(result))
