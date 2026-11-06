/** 案例二：KGTE 三岛协同进化，云端生成候选、本地沙箱评估（HDD 展示运行回放）。 */
import { DEMO_REPORT_INPUT, NODE_BY_ID, buildDemoSteps, describeStep, DEMO_TRANSFERS } from '../demo-script';
import { buildRunReport } from '../report';
import type { DemoCase } from './types';

export const KGTE_CASE: DemoCase = {
  id: 'kgte',
  name: 'KGTE 三岛进化 · 云端进化本地评估',
  badge: '演示数据 · HDD 展示运行',
  seed: '注入已有知识',
  sampleTask: '用 SMART 日志提前 7 天预测硬盘故障，评估用 ROS，误报预算 3%。',
  evaluation: 'ROS · 本地 evaluator.py',
  confirm: {
    checks: [
      { icon: 'server', title: '云端进化服务器', value: 'hcf@10.0.3.21 · ssh_cloud', ok: 'SSH 已连接 · known_hosts 校验通过' },
      { icon: 'laptop', title: '本地评估器', value: 'evaluator.py · 数据目录可读', ok: '沙箱就绪 · 数据不出本地' },
      { icon: 'cloud', title: '模型服务', value: 'qwen3-coder-plus / qwen3-max', ok: 'API 可用' },
    ],
    seedNote: '把知识库中已确认的规律（如 SMART 末端趋势）作为先验注入三岛初始候选。',
    budget: { label: '进化预算', min: 3, max: 10, initial: 6, describe: (n) => `3 岛 × ${n} 轮 · 约 ${n * 7} 分钟` },
    privacy: '云端只会看到分数与聚合统计，原始数据始终留在本地。',
  },
  steps: buildDemoSteps(),
  transfers: DEMO_TRANSFERS,
  describeStep,
  pipeline: {
    cloud: { title: '云端进化 · SSH 服务器', host: 'hcf@10.0.3.21', command: (round) => `fe evolve local benchmark/hdd_mvp · round ${round}` },
    local: { title: '本地评估 · 沙箱', file: 'evaluator.py', note: 'SMART 遥测与工单只在本地读取' },
    boundary: '数据边界 · 仅分数可通过',
    lanes: { cloud: '候选队列', local: '沙箱评估' },
    stages: ['云端提出假设', 'SSH 下发代码', '本地沙箱评估', '回传分数', '云端反思进化'],
    origin: 'cloud',
    candidateLabel: (id) => `${id}.py`,
    result: (id) => {
      const node = NODE_BY_ID.get(id);
      return { label: `${id} ${node?.score.toFixed(2) ?? ''}`, ok: node?.outcome !== 'failed' && node?.outcome !== 'pruned' };
    },
  },
  debate: {
    eyebrow: '新知识发现 · 机制辩论赛',
    title: '窗口末端归一化 SMART 194 与短期故障风险正相关',
    highlight: 'SMART 194',
    rounds: [
      { round: '开场陈述', speaker: 'proponent', line: '窗口末端 SMART 194 越高，短期故障风险越高。我主张它是可复现的正向信号。' },
      { round: '第一轮质询', speaker: 'confounder', line: '会不会是盘龄、型号批次或负载在背后同时推高了两者？' },
      { round: '数据举证', speaker: 'statistician', line: '确认集 n = 9,262，效应估计 0.3124，95% CI [0.278, 0.346]，BH 校正后通过。' },
      { round: '第二轮反驳', speaker: 'proponent', line: '方向与时间切片一致：direction_ok、temporal_ok 均为 true。' },
      { round: '机制追问', speaker: 'critic', line: '16 场机制对局全部平局，统计显著不等于因果机制。' },
      { round: '最终裁决', speaker: 'judge', line: '升级为 CONFIRMED 确认式知识；机制尚未建立，不写成因果定律。' },
    ],
    cast: {
      proponent: { name: '支持方', en: 'Proponent', shape: 'circle', color: '#2563EB' },
      confounder: { name: '混杂方', en: 'Confounder', shape: 'hex', color: '#64748B' },
      statistician: { name: '统计裁判', en: 'Statistician', shape: 'squircle', color: '#0EA5E9' },
      critic: { name: '批评方', en: 'Critic', shape: 'triangle', color: '#6366F1' },
      judge: { name: '总裁判', en: 'Judge', shape: 'circle', color: '#1E3A8A' },
    },
    verdict: [
      { label: '确认集样本', value: 'n = 9,262', round: 2 },
      { label: '效应估计 · 95% CI', value: '0.3124 · [0.278, 0.346]', round: 2 },
      { label: '确认轨 FDR', value: 'BH 通过 ✓', round: 2, good: true },
      { label: '方向 / 时间切片', value: 'direction_ok · temporal_ok', round: 3, good: true },
      { label: '发现轨 FDR', value: 'e-BH 未升级', round: 4 },
      { label: '机制对局', value: '16 场 · 全部平局', round: 4 },
    ],
    outcome: { title: 'CONFIRMED', sub: '确认式知识 · 尚非因果定律' },
    chain: ['现象抽取', '预注册', '确认检验', '多重控制', '机制辩论', '跨切片外推'],
  },
  report: buildRunReport(DEMO_REPORT_INPUT),
};
