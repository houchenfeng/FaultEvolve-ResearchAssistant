/**
 * 运行对比与波动判定（PRD 13.3）。
 *
 * 这一节的名字和它实际能做的事必须分开讲清楚：
 * **跨运行对比**在运行对比页按同一 task_id 并排；PRD 13.3 那句「当两次运行差异落在已知波动范围内，
 * 应显示『未形成明确改进证据』」在**节点级**是有真实数据支撑的——
 * `TreeNodeDTO.within_noise_band` 由后端 `_within_noise()` 算好
 * （`replay_service.py:1031-1035`），前端只转达。
 *
 * 所以本节给出的是：最佳节点的波动判定 + 全树的三值计数。
 * 标题里明写「节点级」，不让读者以为这是两次运行的比较。
 */
import { StatusBadge } from '@/components/ui/StatusBadge';
import type { Cell } from '@/features/discovery/card-logic';
import type { NoiseSummary, NoiseVerdict } from '@/features/results/results-logic';

export interface RunComparisonProps {
  bestNodeId: string | null;
  verdict: NoiseVerdict;
  summary: NoiseSummary;
  /** 进化树请求是否成功。失败时计数一律未记录，不得显示 0。 */
  treeLoaded: boolean;
}

function Counter({ label, cell }: { label: string; cell: Cell }) {
  return (
    <div className="fe-card px-2.5 py-1.5">
      <dt className="text-[10px] text-fg-subtle">{label}</dt>
      <dd
        data-noise-count={label}
        data-recorded={cell.recorded ? 'true' : 'false'}
        className={`tabular text-sm font-semibold ${cell.recorded ? 'text-fg' : 'text-fg-subtle'}`}
      >
        {cell.value}
      </dd>
    </div>
  );
}

export function RunComparison({
  bestNodeId,
  verdict,
  summary,
  treeLoaded,
}: RunComparisonProps) {
  return (
    <div className="flex flex-col gap-3">
      <section className="flex flex-col gap-2" data-best-verdict>
        <h3 className="text-xs font-medium text-fg-muted">最佳节点的改进是否站得住</h3>

        {bestNodeId ? (
          <div className="flex flex-wrap items-center gap-2">
            <code className="font-mono text-[11px] text-fg">{bestNodeId}</code>
            <span
              className="inline-flex"
              data-verdict-tone={verdict.tone}
              data-verdict-band={verdict.band}
            >
              <StatusBadge tone={verdict.tone} showDot={false}>
                {verdict.label}
              </StatusBadge>
            </span>
          </div>
        ) : (
          <p className="text-[11px] text-fg-subtle" data-verdict-tone="neutral">
            没有最佳节点，因此无从判定。这不表示「没有改进」。
          </p>
        )}

        <p className="text-[11px] text-fg-subtle" data-verdict-reason>
          {verdict.reason}
        </p>
      </section>

      <section className="flex flex-col gap-2" data-noise-summary>
        <h3 className="text-xs font-medium text-fg-muted">全树的波动判定计数（节点级）</h3>

        {!treeLoaded ? (
          <p className="text-[11px] text-fg-subtle" data-tree-unavailable>
            进化树未取到，以下计数一律未记录。这不表示「没有节点落在波动带内」。
          </p>
        ) : null}

        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          <Counter label="节点总数" cell={summary.total} />
          <Counter label="已评分" cell={summary.scored} />
          <Counter label="有对比基线" cell={summary.compared} />
          <Counter label="落在波动带内" cell={summary.within} />
          <Counter label="超出波动带" cell={summary.beyond} />
          <Counter label="无法判断" cell={summary.unknown} />
        </dl>

        <p className="text-[11px] text-fg-subtle">
          后三项的分母是「有对比基线」的节点数，不是节点总数：根节点没有 delta，
          混进去会让「无法判断」凭空多出一个，看起来像后端漏算。
        </p>
      </section>
    </div>
  );
}
