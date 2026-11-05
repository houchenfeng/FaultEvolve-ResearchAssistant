"""Re-audit archived paired campaigns under the runtime-excluded quality gate."""
import hashlib
import json
import math
from pathlib import Path

from controller import QUALITY_KEYS, LOWER

CAMPAIGNS = ['verify_tail_risk_20261021', 'verify_tail_refresh_20261021',
             'verify_refreshed_vs_zero_20261021', 'verify_shared_preprocessing_20261021',
             'verify_shared_tree_20261021', 'verify_combined_reuse_20261021',
             'verify_fused_optimizer_20261021', 'verify_reuse_replicas_20261021',
             'verify_single_learning_rate_20261021', 'verify_temporal_attention_20261021']


def audit(root):
    rows, sources = [], {}
    for name in CAMPAIGNS:
        folder = root / name
        files = {key: folder / (key + '.json') for key in ('manifest', 'status', 'records')}
        data = {key: json.loads(path.read_text(encoding='utf-8')) for key, path in files.items()}
        sources[name] = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in files.items()}
        manifest, records = data['manifest'], data['records']
        expected = {(c, seed) for c in manifest['candidates'] for seed in manifest['seeds']}
        assert data['status']['phase'] == 'complete'
        assert len(records) == len(expected) == data['status']['evaluations']
        assert {(r['candidate'], r['seed']) for r in records} == expected
        for candidate in manifest['candidates']:
            selected = [r for r in records if r['candidate'] == candidate]
            failures = {key: 0 for key in QUALITY_KEYS}
            seed_passes = 0
            for record in selected:
                assert record['result']['validity'] == 1
                comparisons = record['comparisons']
                assert len(comparisons) == len(manifest['baselines'])
                assert {c['baseline'] for c in comparisons} == set(manifest['baselines'])
                failed = set()
                for comparison in comparisons:
                    for key in QUALITY_KEYS:
                        item = comparison.get('metrics', {}).get(key, {})
                        a, b = item.get('candidate'), item.get('baseline')
                        finite = all(isinstance(v, (int, float)) and math.isfinite(v) for v in (a, b))
                        better = finite and (a < b if key in LOWER else a > b)
                        if not better:
                            failed.add(key)
                seed_passes += not failed
                for key in failed:
                    failures[key] += 1
            rows.append({'campaign': name, 'candidate': candidate, 'seeds': len(selected),
                         'passing_seeds': seed_passes, 'all_seeds_quality_pass': seed_passes == len(selected),
                         'nonwinning_seed_counts': failures})
    return {'scope': 'archived_training_seed_stability_on_reused_validation',
            'independent_generalization': False, 'excluded_from_gate': ['run_time_s', 'combined_score'],
            'quality_keys': QUALITY_KEYS, 'source_sha256': sources, 'candidates': rows,
            'passing_candidates': sum(r['all_seeds_quality_pass'] for r in rows)}


if __name__ == '__main__':
    root = Path(__file__).resolve().parent / 'evidence'
    result = audit(root)
    (root / 'runtime_excluded_quality_audit_20261021.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'campaigns': len(CAMPAIGNS), 'candidates': len(result['candidates']),
                      'passing_candidates': result['passing_candidates'],
                      'passing_seed_evaluations': sum(r['passing_seeds'] for r in result['candidates'])}))
