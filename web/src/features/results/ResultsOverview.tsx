/**
 * 结果总览（PRD 13.1）。
 *
 * 只吃 props、不发请求。每行都带 `source`，直接渲染出来：PRD 13.5 要求报告里的
 * 每个数字都能追溯到具体制品，把来源画在页面上比写在文档里更能防止日后漂移。
 *
 * 「分项指标」一节是这一页最需要小心的地方：`NodeEvaluationResponse.metric` 是
 * `dict[str, Any]`，**契约不保证任何键**。所以这里只渲染后端实际给出的键，
 * 一个都没给就明说「后端没有返回任何分项指标」，绝不预置 F1_p10 / AUPRC 这些
 * 名字再填 0——那看起来像「这些指标都是 0」，而真相是「没查到」。
 */
import { NOT_RECORDED } from '@/features/discovery/card-logic';
import type { MetricRow, MetricsState, SourceRow } from '@/features/results/results-logic';

export interface ResultsOverviewProps {
  rows: SourceRow[];
  metrics: MetricRow[];
  /** 分项指标取自哪个节点；null 表示还没有最佳节点。 */
  metricsNodeId: string | null;
  metricsState: MetricsState;
  /** `metricsState === 'skipped'` 时显示的原因，由路由给出（它才知道为什么跳过）。 */
  metricsSkipReason: string | null;
}

export function ResultsOverview({
  rows,
  metrics,
  metricsNodeId,
  metricsState,
  metricsSkipReason,
}: ResultsOverviewProps) {
  return (
    <div className="flex flex-col gap-4">
      <dl
        data-outcome-grid
        className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4"
      >
        {rows.map((row) => (
          <div
            key={row.label}
            data-outcome-cell={row.label}
            data-recorded={row.cell.recorded ? 'true' : 'false'}
            className="fe-card px-3 py-2"
          >
            <dt className="text-[11px] text-fg-subtle">{row.label}</dt>
            <dd
              className={`tabular text-base font-semibold ${
                row.cell.recorded ? 'text-fg' : 'text-fg-subtle'
              }`}
            >
              {row.cell.value}
            </dd>
            <dd className="mt-0.5 text-[10px] text-fg-subtle" data-source>
              {row.source}
            </dd>
          </div>
        ))}
      </dl>

      {/* data-metrics-state 是给测试的稳定落定信号：本节四种状态渲染的内容
          完全不同，靠文案猜会在 pending 阶段读到占位值（同知识卡页的教训）。 */}
      <section className="flex flex-col gap-2" data-metrics data-metrics-state={metricsState}>
        <header className="flex flex-wrap items-baseline gap-2">
          <h3 className="text-xs font-medium text-fg-muted">分项指标</h3>
          {/* 没有最佳节点时这里留空，原因由下面 data-metrics-no-node 那条讲，
              免得同一件事在两处各说一遍、措辞还可能不一致。 */}
          {metricsNodeId ? (
            <span className="text-[11px] text-fg-subtle">
              取自最佳节点 <code className="font-mono">{metricsNodeId}</code> 的
              <code className="ml-1 font-mono">metric</code> 字典
            </span>
          ) : null}
        </header>

        {/* 契约对这个字典没有任何键保证，这句话必须写在数据旁边，
            否则读者会以为下面列出的就是「全部指标」。 */}
        <p className="text-[11px] text-fg-subtle" data-metrics-caveat>
          后端返回什么键就显示什么键：契约不保证 F1_p10 / AUPRC / R@FAR 等任何一项存在，
          前端也不为缺失的键补 0。
        </p>

        {/* 四态分开渲染：「没发请求」「发了失败」「发了但字典为空」指向三个
            完全不同的下一步，混成一个「无数据」会逼读者去猜。 */}
        {metricsState === 'skipped' ? (
          <p className="text-[11px] text-fg-subtle" data-metrics-skipped>
            {metricsSkipReason ?? '没有可用的最佳节点，分项指标无从取起。'}这不表示这些指标为 0。
          </p>
        ) : metricsState === 'pending' ? (
          <p className="text-[11px] text-fg-subtle" data-metrics-pending>
            正在读取节点详情…
          </p>
        ) : metricsState === 'error' ? (
          <p className="text-[11px] text-fg-subtle" data-metrics-unavailable>
            节点详情未取到，分项指标{NOT_RECORDED}。这不表示这些指标为 0。
          </p>
        ) : metrics.length === 0 ? (
          <p className="text-[11px] text-fg-subtle" data-metrics-empty>
            后端没有返回任何分项指标（metric 字典为空）。
          </p>
        ) : (
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
            {metrics.map((row) => (
              <div
                key={row.key}
                data-metric-cell={row.key}
                data-recorded={row.cell.recorded ? 'true' : 'false'}
                className="fe-card px-2.5 py-1.5"
              >
                <dt className="font-mono text-[10px] text-fg-subtle">{row.key}</dt>
                <dd
                  className={`tabular text-sm font-semibold ${
                    row.cell.recorded ? 'text-fg' : 'text-fg-subtle'
                  }`}
                >
                  {row.cell.value}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </section>
    </div>
  );
}
