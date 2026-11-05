/**
 * 录入状态与必填卡/预检的纯逻辑测试（TODO §6 阶段 4 测试项的前端半边）。
 *
 * 覆盖：三卡阻塞规则（evaluator / init / 数据目录缺失 ⇒ fail）、
 * 「已自定义」与「恢复默认」（patch 清空即消失）、知识选项映射、
 * 预检聚合与警告确认。
 */
import { beforeEach, describe, expect, it } from 'vitest';

import { deriveArtifactCards } from '@/features/intake/task-artifacts-logic';
import {
  derivePreflightChecks,
  preflightBlockers,
  preflightWarnings,
} from '@/features/intake/preflight-logic';
import {
  buildConfigPatch,
  knowledgePatch,
  selectIsCustomized,
  useIntakeStore,
} from '@/stores/intake-store';

const READY_CARD = {
  data_ready: true,
  data_missing: [],
  evaluator_ready: true,
  init_ready: true,
  metrics: { initial_score: 22.81, primary_metric: 'ROS' },
};

describe('三张必填卡的阻塞规则', () => {
  it('全部就绪时三卡都通过', () => {
    const cards = deriveArtifactCards(READY_CARD, false, false);
    expect(cards.map((card) => card.state)).toEqual(['pass', 'pass', 'pass']);
  });

  it('数据目录缺失 ⇒ 数据集卡失败并给出缺失文件', () => {
    const cards = deriveArtifactCards(
      { ...READY_CARD, data_ready: false, data_missing: ['meta.json'] },
      false,
      false,
    );
    expect(cards[0]).toMatchObject({ state: 'fail', reason: '缺少数据文件：meta.json' });
    // 一张 fail 卡就让预检出现阻塞。
    const checks = derivePreflightChecks({
      taskSelected: true,
      artifactCards: cards,
      serverSelected: true,
      presetValid: null,
    });
    expect(preflightBlockers(checks).map((check) => check.id)).toContain('artifact:dataset');
  });

  it('evaluator 缺失 ⇒ evaluator 卡失败', () => {
    const cards = deriveArtifactCards({ ...READY_CARD, evaluator_ready: false }, false, false);
    expect(cards[1]).toMatchObject({ state: 'fail' });
    const checks = derivePreflightChecks({
      taskSelected: true,
      artifactCards: cards,
      serverSelected: true,
      presetValid: null,
    });
    expect(preflightBlockers(checks).map((check) => check.id)).toContain('artifact:evaluator');
  });

  it('init 缺失 ⇒ 初始算法卡失败', () => {
    const cards = deriveArtifactCards({ ...READY_CARD, init_ready: false }, false, false);
    expect(cards[2]).toMatchObject({ state: 'fail' });
    const checks = derivePreflightChecks({
      taskSelected: true,
      artifactCards: cards,
      serverSelected: true,
      presetValid: null,
    });
    expect(preflightBlockers(checks).map((check) => check.id)).toContain('artifact:init');
  });

  it('初始分未试跑时显示「待评估」，不出现假定分数', () => {
    const cards = deriveArtifactCards(
      { ...READY_CARD, metrics: { initial_score: null, primary_metric: 'ROS' } },
      false,
      false,
    );
    expect(cards[2].facts.find(([label]) => label === '初始基线分')?.[1]).toContain('待评估');
  });

  it('加载中是 checking，错误是 fail（不允许在未知状态下继续）', () => {
    expect(deriveArtifactCards(null, true, false).every((card) => card.state === 'checking')).toBe(
      true,
    );
    expect(deriveArtifactCards(null, false, true).every((card) => card.state === 'fail')).toBe(true);
  });
});

describe('预检聚合', () => {
  it('未选任务与未选服务器都是阻塞项', () => {
    const checks = derivePreflightChecks({
      taskSelected: false,
      artifactCards: deriveArtifactCards(READY_CARD, false, false),
      serverSelected: false,
      presetValid: null,
    });
    const ids = preflightBlockers(checks).map((check) => check.id);
    expect(ids).toContain('task');
    expect(ids).toContain('server');
  });

  it('服务端校验失败的预设是阻塞项', () => {
    const checks = derivePreflightChecks({
      taskSelected: true,
      artifactCards: deriveArtifactCards(READY_CARD, false, false),
      serverSelected: true,
      presetValid: false,
    });
    expect(preflightBlockers(checks).map((check) => check.id)).toContain('preset');
  });

  it('warn 级别进警告列表而不是阻塞列表', () => {
    const checks = derivePreflightChecks({
      taskSelected: true,
      artifactCards: deriveArtifactCards(
        { ...READY_CARD, data_ready: true, data_missing: [] },
        false,
        false,
      ).map((card) => (card.id === 'dataset' ? { ...card, state: 'warn' as const } : card)),
      serverSelected: true,
      presetValid: null,
    });
    expect(preflightBlockers(checks)).toHaveLength(0);
    expect(preflightWarnings(checks).map((check) => check.id)).toContain('artifact:dataset');
  });
});

describe('「已自定义」与「恢复默认」', () => {
  beforeEach(() => {
    useIntakeStore.setState({ preset: 'standard', patch: {}, presetPreview: 'idle' });
  });

  it('patch 为空 ⇒ 不算自定义；改动 ⇒ 算；恢复默认 ⇒ 又不算', () => {
    const store = useIntakeStore.getState();
    expect(selectIsCustomized(useIntakeStore.getState())).toBe(false);

    store.applyPatch({ budget: { max_iterations: 7 } });
    expect(selectIsCustomized(useIntakeStore.getState())).toBe(true);

    useIntakeStore.getState().resetToPreset();
    expect(selectIsCustomized(useIntakeStore.getState())).toBe(false);
    expect(useIntakeStore.getState().patch).toEqual({});
  });

  it('切换预设清空 patch（三档是三套基线）', () => {
    useIntakeStore.getState().applyPatch({ budget: { max_iterations: 7 } });
    useIntakeStore.getState().setPreset('deep');
    expect(useIntakeStore.getState().patch).toEqual({});
    expect(useIntakeStore.getState().preset).toBe('deep');
  });
});

describe('知识注入选项映射到真实引擎字段', () => {
  it('四档各自的 patch 只含 KnowledgeConfig / DiscoveryConfig 真实字段', () => {
    expect(knowledgePatch('off')).toEqual({ knowledge: { enabled: false } });
    expect(knowledgePatch('default')).toEqual({});
    expect(knowledgePatch('auto')).toEqual({ discovery: { enabled: true } });
    expect(knowledgePatch('tournament')).toEqual({
      discovery: { enabled: true, tournament: { enabled: true } },
    });
  });

  it('buildConfigPatch 把字段覆盖与知识映射合并成一份 patch', () => {
    useIntakeStore.setState({
      preset: 'standard',
      patch: { budget: { max_iterations: 7 } },
      knowledgeMode: 'tournament',
    });
    expect(buildConfigPatch(useIntakeStore.getState())).toEqual({
      budget: { max_iterations: 7 },
      discovery: { enabled: true, tournament: { enabled: true } },
    });
  });
});
