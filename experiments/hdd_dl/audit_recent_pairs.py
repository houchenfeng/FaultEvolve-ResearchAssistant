"""Summarize frozen paired evidence without pooling seeds into a significance claim."""
import hashlib
import json
from collections import Counter
from pathlib import Path

CAMPAIGNS = (
    'feasible_candidate', 'weak_ranking', 'tail_ranking', 'tail_vs_zero',
    'tab_validity', 'diverse_replicas', 'full_quantiles', 'far_calibration',
    'shared_calibration', 'causal_context',
)


def audit(root):
    experiments, failures, ties, stable_gains = [], Counter(), Counter(), Counter()
    evaluated = 0
    for name in CAMPAIGNS:
        folder = root / f'verify_{name}_20261021'
        sources = {}
        for filename in ('records.json', 'paired.json', 'summary.json', 'status.json'):
            raw = (folder / filename).read_bytes()
            sources[filename] = {'sha256': hashlib.sha256(raw).hexdigest(), 'data': json.loads(raw)}
        paired = sources['paired.json']['data']
        records = sources['records.json']['data']
        status = sources['status.json']['data']
        assert paired['complete'] and status['phase'] == 'complete'
        assert status['evaluations'] == len(records)
        treatment = [r for r in records if r['candidate'] == paired['treatment']]
        assert sorted(r['seed'] for r in treatment) == sorted(paired['expected_seeds'])
        assert all(r['result']['validity'] == 1 for r in treatment)
        local_fail, local_ties = Counter(), Counter()
        for row in treatment:
            strong = [c for c in row['comparisons'] if c['baseline'].endswith('/4016914b.py')]
            assert len(strong) == 1
            for metric, comparison in strong[0]['metrics'].items():
                if not comparison['better']:
                    local_fail[metric] += 1
                if comparison['candidate'] == comparison['baseline']:
                    local_ties[metric] += 1
        failures.update(local_fail)
        ties.update(local_ties)
        evaluated += len(treatment)
        gains = [m for m, v in paired['metrics'].items()
                 if v['complete'] and v['strict_wins'] == len(paired['expected_seeds'])]
        stable_gains.update(gains)
        experiments.append({'campaign': name, 'treatment': paired['treatment'],
            'source_sha256': {f: v['sha256'] for f, v in sources.items()},
            'all_seed_pairwise_gains': gains,
            'mean_paired_deltas': {m: v['mean_delta'] for m, v in paired['metrics'].items()},
            'strong_ml_nonwin_counts': dict(local_fail), 'strong_ml_tie_counts': dict(local_ties),
            'all_seed_predictive_pass': sources['summary.json']['data']['candidates'][paired['treatment']]
                ['all_seeds_all_predictive_better']})
    return {'scope': 'descriptive_audit_of_reused_validation_pairs',
            'independent_generalization': False,
            'warning': 'Counts are descriptive; selected campaigns share data and are not independent trials. Nonwins include ties.',
            'campaigns': len(experiments), 'treatment_evaluations': evaluated,
            'strong_ml_nonwin_counts': dict(failures.most_common()),
            'strong_ml_tie_counts': dict(ties.most_common()),
            'all_seed_pairwise_gain_campaign_counts': dict(stable_gains.most_common()),
            'experiments': experiments}


if __name__ == '__main__':
    root = Path(__file__).resolve().parent / 'evidence'
    output = root / 'recent_pair_bottlenecks_20261021.json'
    report = audit(root)
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'experiments'}, indent=2))
