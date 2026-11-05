/**
 * 任务详情页纯逻辑测试（PRD §7.8 / TODO §4.6 的前端半边）。
 *
 * 重点不是「有数据时显示得对」，而是**没数据时不作弊**：
 * 未记录不得显示成 0，未检查不得显示成通过，契约里没有的字段不得由前端补算。
 */
import { describe, expect, it } from 'vitest';

import type {
  TaskDatasetCardResponse,
  TaskDetailResponse,
  TaskReadinessResponse,
} from '@/generated/api';
import {
  deriveBlockers,
  deriveFileListing,
  deriveReadinessRows,
  deriveScoreContractRows,
  detectProtectedNameLeak,
  scoreSourceLabel,
} from '@/features/intake/task-detail-logic';

const READY_DETAIL: TaskDetailResponse = {
  task_id: 'hdd_mvp',
  display_name: 'HDD MVP',
  adapter: 'hdd',
  problem_md: '# 任务\n预测硬盘故障。',
  prompt_md: '写一个 predict 函数。',
  required_files: ['evaluator.py', 'init.py', 'problem.md', 'prompt.md'],
  missing_files: [],
  candidate_files: ['init.py', 'rule_baseline.py'],
  data_dirs: ['public'],
  knowledge_enabled: true,
  config_schema_available: true,
};

const READY_CARD: TaskDatasetCardResponse = {
  task_id: 'hdd_mvp',
  display_name: 'HDD MVP',
  adapter: 'hdd',
  is_stub: false,
  device_type: 'HDD',
  data_ready: true,
  data_missing: [],
  evaluator_ready: true,
  init_ready: true,
  knowledge_card_count: 18,
  metrics: {
    primary_metric: 'ROS',
    target_direction: 'higher',
    target_score: 32,
    // 后端在建立 run→task 关联之前恒为 null（task_service.py 里写明了原因）。
    initial_score: null,
    score_source: 'unavailable',
  },
};

const READY_READINESS: TaskReadinessResponse = {
  task_id: 'hdd_mvp',
  ready: true,
  checks: [],
  adapter: 'hdd',
  resolved_path: null,
};

function rowById(rows: ReturnType<typeof deriveReadinessRows>, id: string) {
  const row = rows.find((candidate) => candidate.id === id);
  if (!row) throw new Error(`没有 id=${id} 的检查行`);
  return row;
}

describe('就绪检查六行（PRD §7.8 区 3）', () => {
  it('全就绪任务：前五项通过', () => {
    const rows = deriveReadinessRows({
      detail: READY_DETAIL,
      card: READY_CARD,
      pending: false,
      error: false,
    });
    expect(rows.map((row) => row.id)).toEqual([
      'data',
      'evaluator',
      'init',
      'prompt',
      'knowledge',
      'qwen',
    ]);
    for (const id of ['data', 'evaluator', 'init', 'prompt', 'knowledge']) {
      expect(rowById(rows, id).state, id).toBe('pass');
    }
  });

  it('Qwen 永远是「未检查」，并把权威来源指向服务器探测', () => {
    const rows = deriveReadinessRows({
      detail: READY_DETAIL,
      card: READY_CARD,
      pending: false,
      error: false,
    });
    const qwen = rowById(rows, 'qwen');
    expect(qwen.state).toBe('unknown');
    expect(qwen.detail).toContain('llm_key_present');
    expect(qwen.detail).not.toContain('通过');
  });

  it('数据缺失 ⇒ data 失败并列出缺失文件名', () => {
    const rows = deriveReadinessRows({
      detail: READY_DETAIL,
      card: { ...READY_CARD, data_ready: false, data_missing: ['meta.json', 'train.parquet'] },
      pending: false,
      error: false,
    });
    const data = rowById(rows, 'data');
    expect(data.state).toBe('fail');
    expect(data.detail).toContain('meta.json');
    expect(data.detail).toContain('train.parquet');
  });

  it('prompt.md 在 missing_files 里 ⇒ prompt 失败', () => {
    const rows = deriveReadinessRows({
      detail: { ...READY_DETAIL, missing_files: ['prompt.md'] },
      card: READY_CARD,
      pending: false,
      error: false,
    });
    expect(rowById(rows, 'prompt').state).toBe('fail');
  });

  it('prompt.md 不是必需文件 ⇒ unknown，既不判通过也不判失败', () => {
    const rows = deriveReadinessRows({
      detail: { ...READY_DETAIL, required_files: ['evaluator.py', 'init.py'] },
      card: READY_CARD,
      pending: false,
      error: false,
    });
    expect(rowById(rows, 'prompt').state).toBe('unknown');
  });

  it('未启用知识注入是可选状态 ⇒ pass，不是 fail', () => {
    const rows = deriveReadinessRows({
      detail: { ...READY_DETAIL, knowledge_enabled: false },
      card: { ...READY_CARD, knowledge_card_count: null },
      pending: false,
      error: false,
    });
    const knowledge = rowById(rows, 'knowledge');
    expect(knowledge.state).toBe('pass');
    expect(knowledge.detail).toBe('该任务未启用知识注入');
  });

  it('启用了但卡片数量未记录 ⇒ 文案说未记录，绝不显示 0', () => {
    const rows = deriveReadinessRows({
      detail: READY_DETAIL,
      card: { ...READY_CARD, knowledge_card_count: null },
      pending: false,
      error: false,
    });
    const knowledge = rowById(rows, 'knowledge');
    expect(knowledge.detail).toBe('已启用，但卡片数量未记录');
    expect(knowledge.detail).not.toContain('0 张');
  });

  it('detail 请求失败但 card 成功 ⇒ knowledge 降为 unknown，其余照常', () => {
    const rows = deriveReadinessRows({
      detail: null,
      card: READY_CARD,
      pending: false,
      error: false,
    });
    expect(rowById(rows, 'knowledge').state).toBe('unknown');
    expect(rowById(rows, 'evaluator').state).toBe('pass');
  });

  it('card 请求失败 ⇒ 六行全 unknown（不得把「没查到」显示成失败）', () => {
    const rows = deriveReadinessRows({
      detail: READY_DETAIL,
      card: null,
      pending: false,
      error: true,
    });
    expect(rows).toHaveLength(6);
    for (const row of rows) {
      expect(row.state, row.id).toBe('unknown');
    }
    expect(rowById(rows, 'data').detail).toBe('任务卡请求失败，无法判定');
  });

  it('加载中 ⇒ 全 unknown 且文案是「正在读取…」', () => {
    const rows = deriveReadinessRows({
      detail: null,
      card: null,
      pending: true,
      error: false,
    });
    expect(rows.every((row) => row.state === 'unknown')).toBe(true);
    expect(rowById(rows, 'data').detail).toBe('正在读取…');
  });
});

describe('阻塞项透传', () => {
  it('ready=true 且无阻塞项', () => {
    expect(deriveBlockers(READY_READINESS, false, false)).toEqual({ ready: true, checks: [] });
  });

  it('后端给的阻塞项原样透传，前端不增删', () => {
    const readiness: TaskReadinessResponse = {
      task_id: 'hdd_mvp',
      ready: false,
      checks: [
        { field: 'init.py', reason: '无法解析（syntax_error）' },
        { field: 'data', reason: '缺少文件' },
      ],
    };
    const result = deriveBlockers(readiness, false, false);
    expect(result.ready).toBe(false);
    expect(result.checks).toHaveLength(2);
    expect(result.checks[0]).toEqual({ field: 'init.py', reason: '无法解析（syntax_error）' });
  });

  it('请求未回来或失败 ⇒ ready=null（未知），不是 false', () => {
    expect(deriveBlockers(null, false, false).ready).toBeNull();
    expect(deriveBlockers(READY_READINESS, true, false).ready).toBeNull();
    expect(deriveBlockers(READY_READINESS, false, true).ready).toBeNull();
  });
});

describe('评价契约（PRD §7.8 区 2）', () => {
  it('契约里有的字段如实显示', () => {
    const rows = deriveScoreContractRows(READY_CARD, false, false);
    const byLabel = new Map(rows.map((row) => [row.label, row]));
    expect(byLabel.get('主指标')).toMatchObject({ value: 'ROS', state: 'value' });
    expect(byLabel.get('目标方向')).toMatchObject({ value: '越大越好', state: 'value' });
    expect(byLabel.get('目标分数')).toMatchObject({ value: '32', state: 'value' });
  });

  it('initial_score 为 null ⇒ 显示「待评估」，不显示 0 也不显示 22.81', () => {
    const rows = deriveScoreContractRows(READY_CARD, false, false);
    const initial = rows.find((row) => row.label === '初始基线分');
    expect(initial?.value).toBe('待评估');
    expect(initial?.state).toBe('not_recorded');
    expect(rows.map((row) => row.value).join('|')).not.toContain('22.81');
  });

  it('score_source=unavailable ⇒ 说明没有真实评估产生过分数', () => {
    const rows = deriveScoreContractRows(READY_CARD, false, false);
    expect(rows.find((row) => row.label === '评分来源')?.value).toBe(
      '无（尚未有真实评估产生过分数）',
    );
  });

  it('target_score 缺失 ⇒ 「未记录」', () => {
    const rows = deriveScoreContractRows(
      { ...READY_CARD, metrics: { ...READY_CARD.metrics!, target_score: null } },
      false,
      false,
    );
    expect(rows.find((row) => row.label === '目标分数')).toMatchObject({
      value: '未记录',
      state: 'not_recorded',
    });
  });

  it('metrics 整个缺失 ⇒ 五行全 not_recorded，不抛异常', () => {
    const rows = deriveScoreContractRows({ ...READY_CARD, metrics: undefined }, false, false);
    expect(rows).toHaveLength(5);
    expect(rows.every((row) => row.state === 'not_recorded')).toBe(true);
  });

  it('未知的 target_direction 原样显示，不硬翻译成中文', () => {
    const rows = deriveScoreContractRows(
      { ...READY_CARD, metrics: { ...READY_CARD.metrics!, target_direction: 'closer_to_zero' } },
      false,
      false,
    );
    expect(rows.find((row) => row.label === '目标方向')?.value).toBe('closer_to_zero');
  });

  it('card 为 null 或请求失败 ⇒ 全 not_recorded', () => {
    for (const [pending, error] of [
      [true, false],
      [false, true],
    ] as const) {
      const rows = deriveScoreContractRows(null, pending, error);
      expect(rows.every((row) => row.state === 'not_recorded')).toBe(true);
    }
  });

});

describe('scoreSourceLabel', () => {
  it('unavailable / null / undefined 都归到「无」', () => {
    for (const source of ['unavailable', null, undefined, '']) {
      expect(scoreSourceLabel(source)).toBe('无（尚未有真实评估产生过分数）');
    }
  });

  it('其它取值原样返回，避免把新枚举悄悄翻译成「未记录」', () => {
    expect(scoreSourceLabel('evaluator')).toBe('evaluator');
    expect(scoreSourceLabel('baseline_run')).toBe('baseline_run');
  });
});

describe('受保护名称的纵深防御（PRD §7.8 内容安全）', () => {
  it('正常名字不报警', () => {
    expect(detectProtectedNameLeak(['public', 'init.py', 'evaluator.py'])).toEqual([]);
  });

  it('漏网的 holdout 名称被点名，大小写不敏感', () => {
    expect(detectProtectedNameLeak(['public', 'holdout', 'Holdout_labels', null, undefined])).toEqual(
      ['holdout', 'Holdout_labels'],
    );
  });

  it('文件清单剔除受保护名字，并把它记进 leak 供 UI 报数量', () => {
    const listing = deriveFileListing({
      ...READY_DETAIL,
      data_dirs: ['public', 'holdout'],
      candidate_files: ['init.py', 'holdout_labels.csv'],
    });
    expect(listing.dataDirs).toEqual(['public']);
    expect(listing.candidates).toEqual(['init.py']);
    expect(listing.leak).toEqual(['holdout_labels.csv', 'holdout']);
    expect(listing.required).toEqual(READY_DETAIL.required_files);
  });

  it('detail 为 null 时给空清单，不抛异常', () => {
    expect(deriveFileListing(null)).toEqual({
      required: [],
      missing: [],
      candidates: [],
      dataDirs: [],
      leak: [],
    });
  });
});
