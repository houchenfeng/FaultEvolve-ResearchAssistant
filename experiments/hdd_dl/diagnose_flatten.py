"""Training-only replay of pooled/flattened representations; no benchmark score."""
import ast
import fcntl
import json
from pathlib import Path

import numpy as np
import pandas as pd

import candidate
import controller


def main():
    root = Path('/home/hcf/faultevolve-dl')
    nas = Path('/home/hcf/nas_hcf_data')
    output = nas / 'faultevolve-dl/runs/flatten_diagnostics_20261021'
    source = nas / 'faultevolve-dl/runs/quality_flatten_sources_20261021'
    data = nas / 'faultevolve/data/hdd_mvp/public'
    with (root / 'state/campaign.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        controller.guard(nas, output)
        output.mkdir(exist_ok=False)
        configs = {}
        for name in ('without', 'with'):
            tree = ast.parse((source / f'{name}.py').read_text())
            assignments = [n.value for n in tree.body if isinstance(n, ast.Assign)
                           and any(isinstance(t, ast.Name) and t.id == 'CONFIG' for t in n.targets)]
            assert len(assignments) == 1
            configs[name] = ast.literal_eval(assignments[0])
        assert configs['without']['temporal_flatten'] is False
        assert configs['with']['temporal_flatten'] is True
        assert {k: v for k, v in configs['without'].items() if k != 'temporal_flatten'} == {
            k: v for k, v in configs['with'].items() if k != 'temporal_flatten'}
        seeds = [20270620, 20270621, 20270622]
        controller.write_json(output / 'manifest.json', {
            'scope': 'training_only_diagnostic_not_benchmark', 'configs': configs, 'seeds': seeds,
            'candidate_sha256': controller.sha(Path(candidate.__file__)),
            'runner_sha256': controller.sha(Path(__file__)),
            'source_hashes': {n: controller.sha(source / f'{n}.py') for n in configs},
            'data_hashes': {n: controller.sha(data / n) for n in ('train_labels.csv', 'train_history.csv.gz')}})
        train = pd.read_csv(data / 'train_labels.csv')
        history = pd.read_csv(data / 'train_history.csv.gz')
        candidate.CONFIG = configs['without']
        tab, seq = candidate.features(history, train, sorted(c for c in history if c.startswith('smart_')))
        rows = []
        for seed in seeds:
            for name, cfg in configs.items():
                controller.guard(nas, output)
                controller.write_json(output / 'status.json', {'phase': 'running', 'seed': seed, 'arm': name})
                details = {'seed': seed, 'arm': name}
                # Dummy inference inputs are training rows; discard all predictions.
                candidate.fit_predict(tab, seq, train.label.to_numpy(dtype=np.float32),
                    train.weight.to_numpy(dtype=np.float32), tab[:2], seq[:2],
                    {**cfg, 'seed': seed}, details)
                rows.append(details)
                controller.write_json(output / 'diagnostics.json', rows)
                print(json.dumps({'seed': seed, 'arm': name, 'models': len(details['models']),
                                  'threshold': details['final_threshold']}), flush=True)
        controller.write_json(output / 'status.json', {'phase': 'complete', 'replays': len(rows)})


if __name__ == '__main__':
    main()
