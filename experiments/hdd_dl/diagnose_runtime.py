"""Bounded train-only diagnostic replay; never a benchmark score."""
import cProfile
import pstats
import time
import torch
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
    output = nas / 'faultevolve-dl/runs/runtime_profile_20261021'
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
        config = {**row['config'], 'tail_risk_weight': 0.0}
        candidate.CONFIG = config
        columns = sorted(c for c in history if c.startswith('smart_'))
        tab, seq = candidate.features(history, train, columns)
        manifest = {'scope': 'training_oof_diagnostic_not_benchmark',
                    'seeds': [20270429], 'config': config,
                    'candidate_sha256': controller.sha(Path(candidate.__file__)),
                    'source_candidate_sha256': row['candidate_sha256']}
        (output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
        rows = []
        for seed in manifest['seeds']:
            controller.guard(nas, output)
            diagnostics = {'seed': seed}
            # Two training feature rows only satisfy the inference interface; their
            # predictions are discarded and never interpreted as validation results.
            profiler = cProfile.Profile()
            torch.cuda.synchronize()
            started = time.perf_counter()
            profiler.enable()
            candidate.fit_predict(tab, seq, train.label.to_numpy(dtype=np.float32),
                train.weight.to_numpy(dtype=np.float32), tab[:2], seq[:2],
                {**config, 'seed': seed}, diagnostics)
            torch.cuda.synchronize()
            profiler.disable()
            diagnostics['profile_wall_seconds'] = time.perf_counter() - started
            stats = pstats.Stats(profiler)
            # Aggregate function timings only; no arrays, locals, identifiers or
            # profiler binary dumps are persisted. Nested cumulative times overlap.
            functions = []
            for (filename, line, name), (primitive, total, own, cumulative, callers) in stats.stats.items():
                functions.append({'module': Path(filename).name, 'line': line,
                                  'function': name, 'calls': total,
                                  'self_seconds': own, 'cumulative_seconds': cumulative})
            diagnostics['top_cumulative'] = sorted(functions, key=lambda x: x['cumulative_seconds'], reverse=True)[:50]
            diagnostics['top_self'] = sorted(functions, key=lambda x: x['self_seconds'], reverse=True)[:50]
            diagnostics['profile_notes'] = 'Instrumented training-only replay; CPU function times include synchronization waits, not isolated GPU kernel times. Cumulative times overlap. Query has two training rows, so full query inference and feature construction are not profiled. Not a benchmark runtime.'
            rows.append(diagnostics)
            (output / 'diagnostics.json').write_text(json.dumps(rows, indent=2))
            print(json.dumps(diagnostics), flush=True)
        (output / 'status.json').write_text(json.dumps({'phase': 'complete', 'seeds': len(rows)}))


if __name__ == '__main__':
    main()
