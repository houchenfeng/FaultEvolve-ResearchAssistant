/**
 * 部署模式三卡片（PRD §4.3）。
 *
 * 纯云端对应已有的 local_cloud / ssh_cloud，可选中，但不改创建运行的请求体：
 * 真正的执行目标仍是下方的服务器配置。
 * 混合模式不在契约枚举里，纯本地对应 local_desktop 且本期不可用。
 * 点禁用卡片只打开说明，不切换当前模式。
 */
import { useState } from 'react';

import { StatusBadge } from '@/components/ui/StatusBadge';
import type { DeploymentModeAvailability } from '@/generated/api';

const HYBRID_DETAIL = '即将支持：远端生成，本地私有评估。本期不能选择。';
const LOCAL_FALLBACK = '即将支持：本地 Qwen 与完全离线运行。本期不能选择。';

export interface DeploymentModeCardsProps {
  modes: DeploymentModeAvailability[];
}

export function DeploymentModeCards({ modes }: DeploymentModeCardsProps) {
  const [explain, setExplain] = useState<string | null>(null);
  const cloud = modes.filter((mode) => mode.mode === 'local_cloud' || mode.mode === 'ssh_cloud');
  const cloudReady = cloud.some((mode) => mode.available);
  const local = modes.find((mode) => mode.mode === 'local_desktop');
  const localDetail = local?.detail?.trim() || LOCAL_FALLBACK;

  return (
    <section className="flex flex-col gap-2" data-deployment-cards="true">
      <h3 className="text-sm font-semibold text-fg">部署模式</h3>
      <div className="grid gap-3 md:grid-cols-3">
        <button
          type="button"
          data-deployment-card="cloud"
          aria-pressed="true"
          disabled={!cloudReady}
          className="rounded-card border border-brand-500 bg-surface p-3 text-left disabled:opacity-60"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-medium text-fg">纯云端</span>
            <StatusBadge tone="brand" showDot={false}>
              本期推荐
            </StatusBadge>
          </div>
          <p className="mt-2 text-[11px] text-fg-muted">
            {cloudReady
              ? `可用：${cloud
                  .filter((mode) => mode.available)
                  .map((mode) => mode.mode)
                  .join('、')}。执行目标在下方服务器配置中选择。`
              : '纯云端执行目标当前不可用。'}
          </p>
        </button>

        <button
          type="button"
          data-deployment-card="hybrid"
          aria-pressed="false"
          aria-disabled="true"
          onClick={() => setExplain(HYBRID_DETAIL)}
          className="fe-card bg-surface-muted p-3 text-left opacity-70"
        >
          <span className="text-xs font-medium text-fg">混合模式</span>
          <p className="mt-2 text-[11px] text-fg-muted">{HYBRID_DETAIL}</p>
        </button>

        <button
          type="button"
          data-deployment-card="local"
          aria-pressed="false"
          aria-disabled="true"
          onClick={() => setExplain(localDetail)}
          className="fe-card bg-surface-muted p-3 text-left opacity-70"
        >
          <span className="text-xs font-medium text-fg">纯本地</span>
          <p className="mt-2 text-[11px] text-fg-muted">{localDetail}</p>
        </button>
      </div>
      <p className="text-[11px] text-fg-subtle">当前模式：纯云端。禁用卡片不会切换模式。</p>

      {explain ? (
        <div
          role="dialog"
          aria-label="部署模式说明"
          className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--fe-overlay)] p-6"
        >
          <div className="w-full max-w-md fe-card-panel p-5">
            <h4 className="text-sm font-semibold text-fg">该模式本期不可用</h4>
            <p className="mt-2 text-xs text-fg-muted">{explain}</p>
            <button
              type="button"
              onClick={() => setExplain(null)}
              className="mt-4 fe-btn fe-btn-primary fe-btn-sm"
            >
              知道了
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
