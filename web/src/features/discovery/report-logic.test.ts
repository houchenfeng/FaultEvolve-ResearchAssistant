/**
 * 结果页读数（TODO 6.4，含阶段 6 测试要求 5 / 6 / 7 / 8 / 9）。
 *
 * - 「manifest 字段缺失」→ `describe('分项指标')`
 * - 「波动区间 → 未形成明确改进证据」→ `describe('运行波动')`
 * - 「多数据集不可比较字段显示 N/A」→ `describe('多数据集对比')`
 * - 「下载 MIME 和文件名正确」→ `describe('下载描述')`
 * - 「不允许下载 holdout 或任意路径」→ `describe('下载拒绝')`
 */
import { describe, expect, it } from 'vitest';

import {
  boundaryAudit,
  comparisonTable,
  downloadDescriptor,
  formatBytes,
  headlineNumbers,
  metricRows,
  NO_CLEAR_EVIDENCE_TEXT,
  noiseBandVerdict,
  normalizeDirection,
  reportDownload,
  topK,
} from '@/features/discovery/report-logic';

describe('初始 / 最佳 / 提升', () => {
  it('三个数字都从 DTO 来', () => {
    const headline = headlineNumbers(0.5, 0.62, 0.12, 'higher');
    expect(headline.initial.text).toBe('0.5000');
    expect(headline.best.text).toBe('0.6200');
    expect(headline.improvement.text).toBe('+0.1200');
    expect(headline.improved).toBe(true);
  });

  it('missing 值报未记录，不是 0', () => {
    const headline = headlineNumbers(null, null, null, 'higher');
    expect(headline.initial.state).toBe('unrecorded');
    expect(headline.best.state).toBe('unrecorded');
    expect(headline.improvement.state).toBe('unrecorded');
    expect(headline.improved).toBeNull();
  });

  it('improvement 缺失但有初始/最佳 ⇒ 按方向自己减', () => {
    // higher 任务：最佳 - 初始
    expect(headlineNumbers(0.5, 0.7, null, 'higher').improvement.text).toBe('+0.2000');
    // lower 任务（越小越好）：初始 - 最佳
    expect(headlineNumbers(0.5, 0.3, null, 'lower').improvement.text).toBe('+0.2000');
    // lower 任务但变差了
    expect(headlineNumbers(0.5, 0.7, null, 'lower').improvement.text).toBe('-0.2000');
  });

  it('缩小时不用绿色 —— 颜色是结论', () => {
    expect(headlineNumbers(0.5, 0.4, -0.1, 'higher').improvement.tone).toBe('muted');
  });

  it('方向未知时按 higher 处理', () => {
    expect(normalizeDirection(undefined)).toBe('higher');
    expect(normalizeDirection('weird')).toBe('higher');
    expect(normalizeDirection('lower')).toBe('lower');
  });
});

describe('运行波动（测试要求：落在波动区间时报未形成明确改进证据）', () => {
  it('提升落在噪声带内 ⇒ 必须说那句话', () => {
    const verdict = noiseBandVerdict(0.003, 0.02);
    expect(verdict.withinBand).toBe(true);
    expect(verdict.note).toContain(NO_CLEAR_EVIDENCE_TEXT);
    expect(verdict.note).toContain('落在运行波动');
    expect(verdict.tone).toBe('muted');
  });

  it('提升超出噪声带 ⇒ 报超出', () => {
    const verdict = noiseBandVerdict(0.15, 0.02);
    expect(verdict.withinBand).toBe(false);
    expect(verdict.note).toContain('超出运行波动');
    expect(verdict.tone).toBe('positive');
  });

  it('边界值（正好等于带宽）算带内 —— 不占便宜', () => {
    expect(noiseBandVerdict(0.02, 0.02).withinBand).toBe(true);
  });

  it('负向变化同样按绝对值比较', () => {
    expect(noiseBandVerdict(-0.02, 0.05).withinBand).toBe(true);
  });

  it('没有噪声带估计 ⇒ 说"无法判断"，不默认"超出"', () => {
    const verdict = noiseBandVerdict(0.5, null);
    expect(verdict.withinBand).toBeNull();
    expect(verdict.note).toContain('无法判断');
    expect(verdict.note).not.toContain('超出');
  });

  it('没有提升数字时不给提示', () => {
    expect(noiseBandVerdict(null, 0.02).note).toBeNull();
  });
});

describe('分项指标（测试要求：manifest 字段缺失）', () => {
  it('缺失字段报未记录，且标成不可比', () => {
    const rows = metricRows({ iterations_done: 12, valid_rate: 0.75 });
    const byKey = new Map(rows.map((row) => [row.key, row]));
    expect(byKey.get('iterations_done')?.view.text).toBe('12');
    expect(byKey.get('valid_rate')?.view.text).toBe('75.0%');
    expect(byKey.get('rounds_to_target')?.view.state).toBe('unrecorded');
    expect(byKey.get('rounds_to_target')?.comparable).toBe(false);
  });

  it('空的 outcome 不炸，全部未记录', () => {
    const rows = metricRows(null);
    expect(rows).toHaveLength(7);
    expect(rows.every((row) => row.view.state === 'unrecorded')).toBe(true);
  });

  it('空字符串算缺失', () => {
    const rows = metricRows({ stop_reason: '   ' });
    expect(rows.find((row) => row.key === 'stop_reason')?.view.state).toBe('unrecorded');
  });

  it('0 是有值（有效率为 0 与没记录不是一回事）', () => {
    const rows = metricRows({ valid_rate: 0, iterations_done: 0 });
    expect(rows.find((row) => row.key === 'valid_rate')?.view.text).toBe('0.0%');
    expect(rows.find((row) => row.key === 'valid_rate')?.comparable).toBe(true);
  });
});

describe('多数据集对比（测试要求：不可比较字段显示 N/A）', () => {
  it('某个运行缺该指标 ⇒ 整行 N/A，不显示 0', () => {
    const table = comparisonTable([
      { datasetId: 'hdd', runId: 'r1', outcome: { iterations_done: 10, valid_rate: 0.8 } },
      { datasetId: 'hdd', runId: 'r2', outcome: { iterations_done: 20 } },
    ]);
    const validRate = table.rows.find((row) => row.key === 'valid_rate');
    expect(validRate?.comparable).toBe(false);
    expect(validRate?.cells.every((cell) => cell.text === 'N/A')).toBe(true);
  });

  it('都有的指标正常显示，且可排名（同数据集）', () => {
    const table = comparisonTable([
      { datasetId: 'hdd', runId: 'r1', outcome: { iterations_done: 10 } },
      { datasetId: 'hdd', runId: 'r2', outcome: { iterations_done: 20 } },
    ]);
    const row = table.rows.find((candidate) => candidate.key === 'iterations_done');
    expect(row?.comparable).toBe(true);
    expect(row?.cells.map((cell) => cell.text)).toEqual(['10', '20']);
    expect(table.rankable).toBe(true);
    expect(table.note).toBeNull();
  });

  it('不同数据集 ⇒ 不可横向排名，并给出说明与数据集清单', () => {
    const table = comparisonTable([
      { datasetId: 'hdd_mvp', runId: 'r1', outcome: { iterations_done: 10 } },
      { datasetId: 'backblaze', runId: 'r2', outcome: { iterations_done: 20 } },
    ]);
    expect(table.rankable).toBe(false);
    expect(table.datasetIds).toEqual(['hdd_mvp', 'backblaze']);
    expect(table.note).toContain('不可直接横向排名');
    expect(table.note).toContain('只比较共有指标');
  });

  it('空输入不炸', () => {
    const table = comparisonTable([]);
    expect(table.rows).toEqual([]);
    expect(table.rankable).toBe(false);
    expect(table.note).toBe('没有可对比的运行');
  });
});

describe('Top-K', () => {
  it('有 rank 时按 rank 排，不自己重排', () => {
    const entries = [
      { node_id: 'c', score: 0.9, rank: 3 },
      { node_id: 'a', score: 0.5, rank: 1 },
      { node_id: 'b', score: 0.7, rank: 2 },
    ];
    expect(topK(entries, 2).map((entry) => entry.node_id)).toEqual(['a', 'b']);
  });

  it('没有 rank 时按分数降序', () => {
    const entries = [
      { node_id: 'a', score: 0.5 },
      { node_id: 'b', score: 0.7 },
    ];
    expect(topK(entries, 1).map((entry) => entry.node_id)).toEqual(['b']);
  });

  it('K 为 0 或负数给空数组；K 超过长度给全部', () => {
    const entries = [{ node_id: 'a', score: 1 }];
    expect(topK(entries, 0)).toEqual([]);
    expect(topK(entries, -3)).toEqual([]);
    expect(topK(entries, 99)).toHaveLength(1);
  });

  it('分数缺失的排到最后，不炸', () => {
    const entries = [{ node_id: 'a' }, { node_id: 'b', score: 1 }];
    expect(topK(entries, 2)[0].node_id).toBe('b');
  });
});

describe('数据边界审计', () => {
  it('逐项报可读性，missing/invalid 标为值得提醒', () => {
    const audit = boundaryAudit(
      { tree: 'available', discovery: 'missing', events: 'invalid' },
      [],
    );
    const byKey = new Map(audit.rows.map((row) => [row.key, row]));
    expect(byKey.get('tree')?.view.text).toBe('可读');
    expect(byKey.get('tree')?.noteworthy).toBe(false);
    expect(byKey.get('discovery')?.view.text).toBe('不存在');
    expect(byKey.get('discovery')?.noteworthy).toBe(true);
    expect(byKey.get('events')?.view.text).toBe('不可解析');
    expect(audit.hasIssues).toBe(true);
  });

  it('键名排序稳定', () => {
    const audit = boundaryAudit({ zeta: 'available', alpha: 'available' }, []);
    expect(audit.rows.map((row) => row.key)).toEqual(['alpha', 'zeta']);
  });

  it('契约警告一并带出；全好时 hasIssues 为 false', () => {
    const clean = boundaryAudit({ tree: 'available' }, []);
    expect(clean.hasIssues).toBe(false);

    const withWarning = boundaryAudit({ tree: 'available' }, [{ field: 'discovery', reason: '轮次不一致' }]);
    expect(withWarning.warnings[0].reason).toBe('轮次不一致');
    expect(withWarning.hasIssues).toBe(true);
  });

  it('null 输入不炸', () => {
    expect(boundaryAudit(null, null).rows).toEqual([]);
  });
});

describe('下载描述（测试要求：MIME 和文件名正确）', () => {
  const report = {
    artifact_id: 'report-summary.md',
    display_name: 'summary.md',
    media_type: 'text/markdown',
    size_bytes: 4096,
    state: 'available' as const,
  };

  it('URL 只由 run_id + artifact_id 拼成，逐段编码', () => {
    const decision = downloadDescriptor('hdd_mvp_demo_7510f100', report);
    expect(decision.allowed).toBe(true);
    if (!decision.allowed) return;
    expect(decision.url).toBe('/api/runs/hdd_mvp_demo_7510f100/artifacts/report-summary.md');
  });

  it('MIME 与文件名取自 DTO，不自己推断', () => {
    const decision = downloadDescriptor('r1', report);
    if (!decision.allowed) throw new Error('应当允许');
    expect(decision.mediaType).toBe('text/markdown');
    expect(decision.filename).toBe('summary.md');
    expect(decision.sizeBytes).toBe(4096);
  });

  it('media_type 缺失时回落到 octet-stream', () => {
    const decision = downloadDescriptor('r1', { ...report, media_type: '' });
    if (!decision.allowed) throw new Error('应当允许');
    expect(decision.mediaType).toBe('application/octet-stream');
  });

  it('显示名里带路径时只取 basename', () => {
    const decision = downloadDescriptor('r1', {
      ...report,
      display_name: '../../etc/passwd',
    });
    if (!decision.allowed) throw new Error('应当允许');
    expect(decision.filename).toBe('passwd');
  });

  it('size 缺失时报 null（渲染成"未知"，不是 0 B）', () => {
    const decision = downloadDescriptor('r1', { ...report, size_bytes: null });
    if (!decision.allowed) throw new Error('应当允许');
    expect(decision.sizeBytes).toBeNull();
    expect(formatBytes(null).text).toBe('未知');
  });

  it('reportDownload 直接吃 manifest 文件', () => {
    const decision = reportDownload('hdd_mvp_demo_7510f100', report);
    expect(decision.allowed).toBe(true);
  });

  it('体积格式化走人读单位', () => {
    expect(formatBytes(512).text).toBe('512 B');
    expect(formatBytes(2048).text).toBe('2.0 KB');
    expect(formatBytes(5 * 1024 * 1024).text).toBe('5.00 MB');
  });
});

describe('下载拒绝（测试要求：不允许下载 holdout 或任意路径）', () => {
  const base = {
    display_name: 'x.json',
    media_type: 'application/json',
    state: 'available' as const,
  };

  it('引擎内部制品（downloadable=false）被拒', () => {
    const decision = downloadDescriptor('r1', {
      ...base,
      artifact_id: 'database',
      downloadable: false,
    });
    expect(decision.allowed).toBe(false);
    if (decision.allowed) return;
    expect(decision.reason).toBe('non_downloadable');
    expect(decision.message).toContain('不开放下载');
  });

  it('任意路径被拒 —— 四种路径形态', () => {
    const ids = [
      '../../etc/passwd',
      '..\\windows\\system32',
      'C:/Users/A/secret.txt',
      'a/b/c.json',
    ];
    for (const id of ids) {
      const decision = downloadDescriptor('r1', { ...base, artifact_id: id });
      expect(decision.allowed).toBe(false);
      if (decision.allowed) continue;
      expect(['invalid_id', 'protected_name']).toContain(decision.reason);
    }
  });

  it('holdout 类名字被拒（纵深防御）', () => {
    for (const id of ['holdout-scores', 'eval_only_data', 'val_labels.csv', 'test_labels']) {
      const decision = downloadDescriptor('r1', { ...base, artifact_id: id });
      expect(decision.allowed).toBe(false);
      if (decision.allowed) continue;
      expect(decision.reason).toBe('protected_name');
      expect(decision.message).toContain('评测保留区');
    }
  });

  it('显示名里出现受保护名字也拒（id 看着干净也不行）', () => {
    const decision = downloadDescriptor('r1', {
      ...base,
      artifact_id: 'report-foo',
      display_name: 'holdout_summary.md',
    });
    expect(decision.allowed).toBe(false);
  });

  it('超长 id 被拒（服务端铸 id 上限 64 字符）', () => {
    const decision = downloadDescriptor('r1', { ...base, artifact_id: 'a'.repeat(65) });
    expect(decision.allowed).toBe(false);
    if (decision.allowed) return;
    expect(decision.reason).toBe('invalid_id');
  });

  it('空 id / 前导点被拒', () => {
    expect(downloadDescriptor('r1', { ...base, artifact_id: '' }).allowed).toBe(false);
    expect(downloadDescriptor('r1', { ...base, artifact_id: '.hidden' }).allowed).toBe(false);
  });

  it('state 不是 available 时被拒', () => {
    const decision = downloadDescriptor('r1', {
      ...base,
      artifact_id: 'report-a',
      state: 'missing',
    });
    expect(decision.allowed).toBe(false);
    if (decision.allowed) return;
    expect(decision.reason).toBe('not_available');
  });

  it('缺 run_id 被拒', () => {
    const decision = downloadDescriptor('', { ...base, artifact_id: 'report-a' });
    expect(decision.allowed).toBe(false);
    if (decision.allowed) return;
    expect(decision.reason).toBe('invalid_id');
  });

  it('正常 id 仍然放行（拒绝不能误伤）', () => {
    for (const id of ['run_summary', 'program-43d93d40', 'discovery-phenomena.json', 'report-a.md']) {
      expect(downloadDescriptor('r1', { ...base, artifact_id: id }).allowed).toBe(true);
    }
  });
});
