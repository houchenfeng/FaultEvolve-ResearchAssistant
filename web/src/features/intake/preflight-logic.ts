/**
 * 启动前检查的纯逻辑（TODO §7 / PRD §8.1 第五步）。
 *
 * 与 PreflightPanel 组件分文件：react-refresh 要求组件文件只导出组件，
 * 而这些推导函数要被 NewRunPage 与测试直接引用。
 */
import type { ArtifactCard } from '@/features/intake/task-artifacts-logic';

export interface PreflightInput {
  taskSelected: boolean;
  artifactCards: ArtifactCard[];
  serverSelected: boolean;
  presetValid: boolean | null;
  /** `null`：还不知道。`false`：密钥未配置。不读取密钥本身。 */
  qwenConfigured?: boolean | null;
  mockLlm?: boolean;
}

export interface PreflightCheck {
  id: string;
  label: string;
  state: 'pass' | 'warn' | 'fail';
  reason: string | null;
}

export function derivePreflightChecks(input: PreflightInput): PreflightCheck[] {
  const checks: PreflightCheck[] = [];

  checks.push(
    input.taskSelected
      ? { id: 'task', label: '已选择任务', state: 'pass', reason: null }
      : { id: 'task', label: '已选择任务', state: 'fail', reason: '尚未选择任务（回到总览选择数据集）' },
  );

  for (const card of input.artifactCards) {
    checks.push({
      id: `artifact:${card.id}`,
      label: `任务工件 · ${card.title}`,
      state: card.state === 'pass' ? 'pass' : card.state === 'warn' ? 'warn' : 'fail',
      reason: card.reason ?? (card.state === 'fail' ? '该项未通过' : null),
    });
  }

  checks.push(
    input.serverSelected
      ? { id: 'server', label: '已选择执行目标', state: 'pass', reason: null }
      : { id: 'server', label: '已选择执行目标', state: 'fail', reason: '尚未选择或新建服务器配置' },
  );

  if (input.qwenConfigured === false && !input.mockLlm) {
    checks.push({
      id: 'qwen',
      label: 'Qwen 密钥',
      state: 'fail',
      reason: '未配置 Qwen 密钥。可勾选 mock LLM 离线运行。',
    });
  } else if (input.qwenConfigured === true) {
    checks.push({ id: 'qwen', label: 'Qwen 密钥', state: 'pass', reason: null });
  } else if (input.mockLlm) {
    checks.push({
      id: 'qwen',
      label: 'Qwen 密钥',
      state: 'pass',
      reason: '使用 mock LLM，不调用千问',
    });
  }

  if (input.presetValid === false) {
    checks.push({
      id: 'preset',
      label: '进化强度配置合法',
      state: 'fail',
      reason: '当前自定义字段未通过服务端校验，请修正后重试「生成配置预览」',
    });
  }

  return checks;
}

export function preflightBlockers(checks: PreflightCheck[]): PreflightCheck[] {
  return checks.filter((check) => check.state === 'fail');
}

export function preflightWarnings(checks: PreflightCheck[]): PreflightCheck[] {
  return checks.filter((check) => check.state === 'warn');
}
