/**
 * 13.3 运行对比与波动判定一节。
 *
 * 节标题里写死「节点级」；PRD 13.3 那句「未形成明确改进证据」在节点级
 * 是有真实数据支撑的。把两件事放在同一节里、并且明说哪一件做到了，
 * 比把整节标成暂不支持更准确——后者会连真数据一起藏掉。
 */
import { Link } from '@tanstack/react-router';

import { ApiErrorPanel } from '@/components/states/ApiErrorPanel';
import { RunComparison } from '@/features/results/RunComparison';
import {
  type NoiseSummary,
  type NoiseVerdict,
} from '@/features/results/results-logic';
import type { ContractWarning } from '@/generated/api';
import { toApiError } from '@/lib/api';
import type { SectionState } from '@/lib/section-state';

export interface ComparisonSectionProps {
  state: SectionState;
  error: unknown;
  onRetry: () => void;
  bestNodeId: string | null;
  verdict: NoiseVerdict;
  summary: NoiseSummary;
  /**
   * `TreeResponse.warnings`。后端在 best_node_id 不在树里时会写一条
   * `field="best_node_id"` 的警告（`replay_service.py:753-760`），
   * 那条正是「本页选的最佳节点树里找不到」的权威说法，照实渲染即可。
   */
  warnings: ContractWarning[];
}

export function ComparisonSection({
  state,
  error,
  onRetry,
  bestNodeId,
  verdict,
  summary,
  warnings,
}: ComparisonSectionProps) {
  return (
    <section className="flex flex-col gap-3" data-comparison data-comparison-state={state}>
      <header className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold text-fg">波动判定（节点级）</h2>
        <span className="text-xs text-fg-subtle">
          判定字段 within_noise_band 由后端算好，前端不重算
        </span>
      </header>

      {warnings.map((warning) => (
        <p
          key={`${warning.field}-${warning.reason}`}
          data-tree-warning={warning.field}
          className="rounded-card border border-warning-500/30 bg-warning-50 p-2 text-[11px] text-warning-700 dark:border-warning-500/40 dark:bg-warning-500/10 dark:text-warning-500"
        >
          {warning.reason}
        </p>
      ))}

      {/* 树读不到时仍然渲染计数（一律未记录）：把整节换成错误面板会让人以为
          「没有波动判定这回事」，而真相是这一次没读到。 */}
      {state === 'error' ? (
        <ApiErrorPanel title="读不到进化树" error={toApiError(error)} onRetry={onRetry} />
      ) : null}

      {state === 'pending' ? (
        <div className="px-4 py-6 text-center text-xs text-fg-subtle">正在读取进化树…</div>
      ) : (
        <RunComparison
          bestNodeId={bestNodeId}
          verdict={verdict}
          summary={summary}
          treeLoaded={state === 'ready'}
        />
      )}

      <Link
        to="/compare"
        className="self-start text-xs text-brand-600 hover:underline"
      >
        打开运行对比
      </Link>
    </section>
  );
}
