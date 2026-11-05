"""Training-only audit of sequence scale and within-window variation."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import candidate
import controller

nas = Path('/home/hcf/nas_hcf_data')
data = nas / 'faultevolve/data/hdd_mvp/public'
out = nas / 'faultevolve-dl/runs/sequence_scale_diagnostics_20261021'
controller.guard(nas, out)
out.mkdir(exist_ok=False)
index = pd.read_csv(data / 'train_labels.csv')
history = pd.read_csv(data / 'train_history.csv.gz')
columns = sorted(c for c in history if c.startswith('smart_'))
candidate.CONFIG = {}
_, seq = candidate.features(history, index, columns)
values, mask = seq[:,:len(columns)], seq[:,len(columns):] > 0
rows = []
for j, name in enumerate(columns):
    v,m = values[:,j],mask[:,j]
    obs = v[m]
    lo = np.where(m,v,np.inf).min(axis=1)
    hi = np.where(m,v,-np.inf).max(axis=1)
    eligible = m.sum(axis=1)>=2
    span = (hi[eligible]-lo[eligible])
    scale = max(float(np.abs(v).max()),1.)
    rows.append({'channel':name,'observed_cells':int(m.sum()),'scale':scale,
        'observed_abs_median_to_scale':float(np.median(np.abs(obs))/scale) if len(obs) else None,
        'eligible_windows':int(eligible.sum()),
        'varying_windows':int((span>0).sum()),
        'median_nonzero_range_to_scale':float(np.median(span[span>0])/scale) if (span>0).any() else None})
result={'scope':'training_only_scale_diagnostic_not_benchmark','channels':rows,
    'data_hashes':{n:controller.sha(data/n) for n in ('train_labels.csv','train_history.csv.gz')},
    'runner_sha256':controller.sha(Path(__file__)),
    'candidate_sha256':controller.sha(Path(candidate.__file__))}
controller.write_json(out/'diagnostics.json',result)
print(json.dumps(rows))
