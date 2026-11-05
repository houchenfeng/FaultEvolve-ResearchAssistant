/** Export only public aggregate metrics; never ship paths, labels or runtime logs. */
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('../', import.meta.url));
const source = 'experiments/hdd_dl/evidence/verified_search_20261021';
const summary = JSON.parse(await readFile(path.join(root, source, 'summary.json'), 'utf8'));
const report = await readFile(path.join(root, source, 'REPORT.md'), 'utf8');
const keys = ['combined_score', 'precision', 'recall', 'f1', 'auprc', 'false_alarm_rate', 'run_time_s'];
const rows = Object.fromEntries(keys.map(key => {
  const row = report.split('\n').find(line => line.startsWith(`| ${key} |`));
  if (!row) throw new Error(`Missing source metric: ${key}`);
  const numbers = row.split('|').slice(2, 6).map(value => Number(value.trim()));
  if (numbers.length !== 4 || numbers.some(value => !Number.isFinite(value))) throw new Error(key);
  return [key, numbers];
}));
if (Math.abs(rows.combined_score[0] - summary.best.result.combined_score) > 1e-8) {
  throw new Error('Report and machine-readable summary disagree');
}
const evidence = {
  source, sourceCommit: '5ee57ba89b24866ed014e3bf6eb8ff16bba2e123',
  split: 'val', trials: summary.trials,
  independentReplication: summary.independent_replication,
  caveat: '验证集参与候选搜索，尚未独立复验；以下为归档实验结果，不是当前运行或私有测试成绩。',
  config: { family: summary.best.config.family, treeBlend: summary.best.config.tree_blend,
    replicas: summary.best.config.replicas, epochs: summary.best.config.epochs },
  models: [
    { id: 'initial', label: '初始逻辑回归', phase: '起点', column: 1 },
    { id: 'preliminary', label: '初赛最佳方案', phase: '初赛', column: 3 },
    { id: 'islands', label: '三岛 ML 方案', phase: '多岛演化', column: 2 },
    { id: 'hybrid', label: 'TCN + 树模型', phase: '混合建模', column: 0 },
  ].map(({ column, ...model }) => ({ ...model,
    metrics: Object.fromEntries(keys.map(key => [key, rows[key][column]])),
  })),
};
const outputs = ['web/src/features/presentation/evidence.json', 'web/public/evidence/hdd-results.json'];
const contents = JSON.stringify(evidence, null, 2) + '\n';
for (const output of outputs) {
  const target = path.join(root, output);
  if (process.argv.includes('--check')) {
    if (await readFile(target, 'utf8') !== contents) throw new Error(`Stale evidence: ${output}`);
  } else {
    await mkdir(path.dirname(target), { recursive: true });
    await writeFile(target, contents);
  }
}
console.log('Showcase evidence matches the archived evaluator results.');
