"""Bounded train-only diagnostic replay; never a benchmark score."""
import fcntl
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

import candidate
import controller


def main():
    root = Path('/home/hcf/faultevolve-dl')
    nas = Path('/home/hcf/nas_hcf_data')
    output = nas / 'faultevolve-dl/runs/threshold_diagnostics_public_20261021'
    with (root / 'state/campaign.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        controller.guard(nas, output)
        output.mkdir(exist_ok=False)
        source = nas / 'faultevolve-dl/runs/evidence_search_20261021'
        row = json.loads((source / 'summary.json').read_text())['balanced']
        assert row['trial'] == 10
        assert controller.sha(source / 'candidate_0010.py') == row['candidate_sha256']
        data = nas / 'faultevolve/data/hdd_mvp/public'
        train = pd.read_csv(data / 'train_labels.csv')
        history = pd.read_csv(data / 'train_history.csv.gz')
        config = {**row['config'], 'quantile_subsample': None, 'alarm_far_budget': 0.002}
        candidate.CONFIG = config
        columns = sorted(c for c in history if c.startswith('smart_'))
        tab, seq = candidate.features(history, train, columns)
        manifest = {'scope': 'training_oof_diagnostic_not_benchmark',
                    'seeds': [20270411, 20270412, 20270413], 'config': config,
                    'candidate_sha256': controller.sha(Path(candidate.__file__)),
                    'source_candidate_sha256': row['candidate_sha256']}
        (output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
        rows = []
        for seed in manifest['seeds']:
            controller.guard(nas, output)
            diagnostics = {'seed': seed}
            # Two training feature rows only satisfy the inference interface; their
            # predictions are discarded and never interpreted as validation results.
            candidate.fit_predict(tab, seq, train.label.to_numpy(dtype=np.float32),
                train.weight.to_numpy(dtype=np.float32), tab[:2], seq[:2],
                {**config, 'seed': seed}, diagnostics)
            rows.append(diagnostics)
            (output / 'diagnostics.json').write_text(json.dumps(rows, indent=2))
            print(json.dumps(diagnostics), flush=True)
        (output / 'status.json').write_text(json.dumps({'phase': 'complete', 'seeds': len(rows)}))


if __name__ == '__main__':
    main()
