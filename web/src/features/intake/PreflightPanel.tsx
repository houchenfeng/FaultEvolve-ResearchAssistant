/**
 * 启动前检查面板（PRD §8.1 第五步的形状；TODO §7 的测试载体）。
 *
 * 阶段 4 这里只做只读汇总，按钮写死禁用并标注「由阶段 7 交付」。阶段 7 交付后
 * 按钮真的会启动运行，所以这个组件的职责变成**如实表达两件不同的事**：
 *
 * 1. `blockedReason` —— 能力层面现在还起不来（进程控制开关未开、没选服务器…）。
 *    按钮禁用，并把原因写在旁边。
 * 2. `checks` 里的阻塞项 —— 请求本身不合法（缺制品、缺目录）。这是即使用户
 *    勾了警告也绕不过去的一类。
 *
 * 两者都可能导致禁用，但**原因不同、文案不同**：把能力缺失说成"你的输入有问题"
 * 会让人去修根本不存在的输入。
 *
 * `mockLlm` 开关是刻意保留的：不带密钥的演示环境必须有一条诚实的离线路径，
 * 否则「启动」只会在子进程里失败，而用户看不出是缺 key。开关文案写明了它
 * 不调用真实模型。
 */
import { useState } from 'react';

import { StatusBadge } from '@/components/ui/StatusBadge';
import {
  preflightBlockers,
  preflightWarnings,
} from '@/features/intake/preflight-logic';
import type { PreflightCheck } from '@/features/intake/preflight-logic';

export function PreflightPanel({
  checks,
  onLaunch,
  launching = false,
  launchError = null,
  blockedReason = null,
  mockLlm = false,
  onMockLlmChange,
}: {
  checks: PreflightCheck[];
  /** 点击「启动运行」。实际请求由页面注入，组件不自己发。 */
  onLaunch: () => void;
  /** 请求进行中：按钮禁用，防重复提交（PRD §8.1 第六步第 1 条）。 */
  launching?: boolean;
  /** 上一次启动失败的可读原因。服务端返回的结构化错误已经过 api-error 归一化。 */
  launchError?: string | null;
  /** 能力层面不可启动的原因；`null` 表示可以启动。 */
  blockedReason?: string | null;
  mockLlm?: boolean;
  onMockLlmChange?: (value: boolean) => void;
}) {
  const [acknowledgeWarnings, setAcknowledgeWarnings] = useState(false);
  const blockers = preflightBlockers(checks);
  const warnings = preflightWarnings(checks);
  const canContinue = blockers.length === 0 && (warnings.length === 0 || acknowledgeWarnings);
  const disabled = launching || !canContinue || blockedReason !== null;

  return (
    <aside
      data-preflight-panel="true"
      className="flex flex-col gap-3 self-start fe-card-panel p-4 shadow-[var(--shadow-fluent-sm)] lg:sticky lg:top-4"
    >
      <h3 className="text-sm font-semibold text-fg">启动前检查</h3>

      <ul className="space-y-1.5">
        {checks.map((check) => (
          <li key={check.id} className="flex items-start justify-between gap-2 text-xs">
            <span className="text-fg-muted">{check.label}</span>
            <StatusBadge
              tone={check.state === 'pass' ? 'success' : check.state === 'warn' ? 'warning' : 'danger'}
            >
              {check.state === 'pass' ? '通过' : check.state === 'warn' ? '警告' : '失败'}
            </StatusBadge>
          </li>
        ))}
        {checks.map(
          (check) =>
            check.reason ? (
              <li key={`${check.id}:reason`} className="pl-1 text-[11px] text-fg-subtle">
                ↳ {check.reason}
              </li>
            ) : null,
        )}
      </ul>

      {warnings.length > 0 ? (
        <label className="flex items-start gap-2 rounded-card border border-warning-500/30 bg-warning-50 p-2 text-[11px] text-warning-700 dark:bg-warning-500/10 dark:text-warning-500">
          <input
            type="checkbox"
            checked={acknowledgeWarnings}
            data-acknowledge-warnings="true"
            onChange={(event) => setAcknowledgeWarnings(event.target.checked)}
            className="mt-0.5"
          />
          存在 {warnings.length} 条警告；我已知晓并接受，允许继续。
        </label>
      ) : null}

      <label className="flex items-start gap-2 text-[11px] text-fg-muted">
        <input
          type="checkbox"
          checked={mockLlm}
          data-mock-llm="true"
          onChange={(event) => onMockLlmChange?.(event.target.checked)}
          className="mt-0.5"
        />
        <span>
          使用 mock LLM（离线演示）
          <span className="block text-fg-subtle">
            不调用真实模型，不消耗 token；用于没有密钥的环境验收整条链路。
          </span>
        </span>
      </label>

      <div className="border-t border-border-subtle pt-3">
        <button
          type="button"
          disabled={disabled}
          onClick={onLaunch}
          data-launch-run="true"
          className="fe-btn fe-btn-primary fe-btn-sm w-full disabled:opacity-50"
        >
          {launching ? '正在启动…' : '启动运行'}
        </button>

        {launchError ? (
          <p data-launch-error="true" className="mt-2 text-[11px] text-danger-700">
            启动失败：{launchError}
          </p>
        ) : null}

        {blockedReason !== null ? (
          <p data-launch-blocked="true" className="mt-2 text-[11px] text-fg-subtle">
            {blockedReason}
          </p>
        ) : !canContinue ? (
          <p className="mt-2 text-[11px] text-danger-700">
            当前有 {blockers.length} 项未通过，无法启动。
          </p>
        ) : (
          <p className="mt-2 text-[11px] text-success-700">检查全部通过（警告已确认）。</p>
        )}
      </div>
    </aside>
  );
}
