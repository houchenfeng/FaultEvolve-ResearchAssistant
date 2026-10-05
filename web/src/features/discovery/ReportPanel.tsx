/**
 * 结果与报告面板（TODO 6.4 / PRD 13）。
 *
 * 六项要求：
 *  1. 初始 / 最佳 / 提升 —— `headlineNumbers`
 *  2. 分项指标 —— `metricRows`
 *  3. Top-K —— `topK`
 *  4. 运行波动和诚实提示 —— `noiseBandVerdict`（落在噪声带内必须明说「未形成明确改进证据」）
 *  5. 数据边界审计 —— `boundaryAudit`
 *  6. 制品下载 —— `downloadDescriptor` / `reportDownload`
 *
 * ## 两个字段的来源必须说清楚
 *
 * - **噪声带**：`RunDetailResponse.outcome` 里没有这个字段，运行目录里唯一带
 *   `noise_delta` 的地方是**进化树的节点**。页面传最优节点的值进来；
 *   传不进来时宁可报「无法判断」，也不默认"超出噪声带"。
 * - **目标方向**：只在任务卡 `TaskCardMetrics.target_direction` 上。跑完的运行
 *   目录**不含任务 id**，所以这里常常拿不到 —— 拿不到就明说按"越大越好"展示，
 *   而不是假装知道。
 *
 * ## 下载的三条纪律（TODO §9 两条测试要求）
 *
 * 1. 只接受服务端铸的 `artifact_id`，URL **只有一种拼法**；
 * 2. `downloadable === false` / 状态不可用 / 命中受保护名字 / id 形状不对 —— 四种都拒绝并说明；
 * 3. 报告文件走 `reportDownload`（服务端只收 `kind === 'report'`）。
 */
import type { ReactNode } from 'react';

import type {
  ArtifactResponse,
  ReportManifestResponse,
  RunDetailResponse,
  ScoreboardEntryResponse,
} from '@/generated/api';
import { StatusBadge } from '@/components/ui/StatusBadge';
import type { FieldView } from '@/features/discovery/card-logic';
import {
  boundaryAudit,
  downloadDescriptor,
  formatBytes,
  headlineNumbers,
  metricRows,
  noiseBandVerdict,
  reportDownload,
  topK,
  type DownloadDecision,
} from '@/features/discovery/report-logic';

const shortId = (id: string) => (id.length > 10 ? id.slice(0, 10) : id || '未记录');

function Field({ label, view }: { label: string; view: FieldView }) {
  const placeholder = view.state !== 'recorded';
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-[10px] text-fg-subtle">{label}</span>
      <span
        className={`tabular text-[11px] ${placeholder ? 'text-fg-subtle italic' : 'text-fg'}`}
        data-field-state={view.state}
      >
        {view.text}
      </span>
    </div>
  );
}

function Panel({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="fe-card-panel p-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <h3 className="text-[12px] font-semibold text-fg">{title}</h3>
        {hint ? <span className="text-[10px] text-fg-subtle">{hint}</span> : null}
      </div>
      <div className="mt-2">{children}</div>
    </section>
  );
}

/** 一个下载入口：允许就是真链接，拒绝就明说为什么。 */
function DownloadLink({ decision }: { decision: DownloadDecision }) {
  if (!decision.allowed) {
    return (
      <div
        className="flex flex-wrap items-center gap-2 text-[10px] text-fg-subtle"
        data-download-refusal={decision.reason}
      >
        <span className="line-through decoration-fg-subtle">不提供下载</span>
        <span>{decision.message}</span>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2" data-download-allowed>
      <a
        href={decision.url}
        // 服务端已用 Content-Disposition 给名，前端只做同一份 basename
        download={decision.filename}
        className="text-[11px] text-brand-600 underline-offset-2 hover:underline dark:text-brand-300"
      >
        {decision.filename}
      </a>
      <span className="text-[10px] text-fg-subtle" data-media-type={decision.mediaType}>
        {decision.mediaType}
      </span>
      <span className="tabular text-[10px] text-fg-subtle">{formatBytes(decision.sizeBytes).text}</span>
    </div>
  );
}

export interface ReportPanelProps {
  runId: string;
  run: RunDetailResponse;
  leaderboard?: ScoreboardEntryResponse[];
  /** 噪声带（`|Δ| ≤ 该值` 判为未形成明确改进证据）。取自最优节点的 `noise_delta`。 */
  noiseDelta?: number | null;
  /** 任务卡上的目标方向；运行目录拿不到时传 `undefined`。 */
  targetDirection?: string | null;
  reportManifest?: ReportManifestResponse | null;
  artifacts?: ArtifactResponse[];
  onLocateNode?: (nodeId: string) => void;
}

export function ReportPanel({
  runId,
  run,
  leaderboard,
  noiseDelta,
  targetDirection,
  reportManifest,
  artifacts,
  onLocateNode,
}: ReportPanelProps) {
  const outcome = run.outcome ?? null;
  const headline = headlineNumbers(
    outcome?.initial_score,
    outcome?.best_score,
    outcome?.improvement,
    targetDirection,
  );
  const noise = noiseBandVerdict(outcome?.improvement ?? null, noiseDelta);
  const metrics = metricRows(run.outcome as Record<string, unknown> | null | undefined);
  const candidates = topK(leaderboard ?? [], 10);
  const boundary = boundaryAudit(run.artifact_states, run.warnings);
  const directionKnown = typeof targetDirection === 'string' && targetDirection !== '';

  return (
    <div className="flex flex-col gap-3" data-testid="report-panel">
      {/* 1. 初始 / 最佳 / 提升 */}
      <Panel title="总体结果" hint="数字直接取自 API DTO，前端不重算任何评测量">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div>
            <div className="text-[10px] text-fg-subtle">初始分</div>
            <div className="tabular text-[16px] text-fg" data-headline="initial">
              {headline.initial.text}
            </div>
          </div>
          <div>
            <div className="text-[10px] text-fg-subtle">最佳分</div>
            <div className="tabular text-[16px] text-fg" data-headline="best">
              {headline.best.text}
            </div>
          </div>
          <div>
            <div className="text-[10px] text-fg-subtle">提升</div>
            <div
              className={`tabular text-[16px] ${
                headline.improved === true ? 'text-success-700 dark:text-success-500' : 'text-fg'
              }`}
              data-headline="improvement"
            >
              {headline.improvement.text}
            </div>
          </div>
          <div>
            <div className="text-[10px] text-fg-subtle">目标方向</div>
            <div className="text-[11px] text-fg" data-headline="direction">
              {directionKnown
                ? headline.direction === 'lower'
                  ? '越小越好'
                  : '越大越好'
                : '未记录（按「越大越好」展示）'}
            </div>
          </div>
        </div>

        {!directionKnown ? (
          <p className="mt-2 text-[10px] text-fg-subtle" data-testid="direction-unknown-note">
            这次运行没有记录任务的目标方向（运行目录不含任务卡），所有"提升"按「越大越好」解释；
            若该数据集是越低越好，请以任务卡为准。
          </p>
        ) : null}
      </Panel>

      {/* 4. 运行波动与诚实提示 —— 放在显眼位置，因为它修正上面那个数字 */}
      <div
        role="status"
        data-testid="noise-verdict"
        data-within-band={noise.withinBand === null ? 'unknown' : String(noise.withinBand)}
        className={`rounded-panel border p-2.5 text-[11px] ${
          noise.tone === 'positive'
            ? 'border-success-500/30 bg-success-50 text-success-700 dark:border-success-500/40 dark:bg-success-500/10 dark:text-success-500'
            : 'border-warning-500/30 bg-warning-50 text-warning-700 dark:border-warning-500/40 dark:bg-warning-500/10 dark:text-warning-500'
        }`}
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">运行波动</span>
          {noise.note ?? '提升不可得，无法与噪声带比较'}
        </div>
        {noiseDelta === null || noiseDelta === undefined ? (
          <div className="mt-1 text-fg-muted">
            噪声带取自进化树最优节点的记录；本次没读到该记录，因此不下"超出波动"的结论。
          </div>
        ) : null}
      </div>

      {/* 2. 分项指标 */}
      <Panel title="分项指标" hint="缺字段显示「未记录」，不显示 0">
        <div className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2 lg:grid-cols-3">
          {metrics.map((row) => (
            <div key={row.key} data-metric={row.key}>
              <Field label={row.label} view={row.view} />
            </div>
          ))}
        </div>
      </Panel>

      {/* 3. Top-K */}
      <Panel title={`Top-${candidates.length || 10} 候选`} hint="名次由服务端给出，前端不重排">
        {candidates.length === 0 ? (
          <p className="text-[11px] text-fg-subtle italic">这次运行还没有可排名的节点</p>
        ) : (
          <table className="w-full text-[11px]">
            <thead>
              <tr className="bg-surface-muted text-left text-fg-muted">
                <th className="w-8 px-2 py-1 font-medium">#</th>
                <th className="px-1 py-1 font-medium">节点</th>
                <th className="px-2 py-1 text-right font-medium">分数</th>
              </tr>
            </thead>
            <tbody>
              {candidates.map((entry) => (
                <tr key={entry.node_id} className="border-t border-border-subtle">
                  <td className="tabular px-2 py-1 text-fg-muted">
                    {entry.rank}
                    {entry.is_best ? <span className="ml-1 text-brand-600">★</span> : null}
                  </td>
                  <td className="px-1 py-1">
                    {onLocateNode ? (
                      <button
                        type="button"
                        onClick={() => onLocateNode(entry.node_id)}
                        className="tabular font-mono text-brand-600 underline-offset-2 hover:underline dark:text-brand-300"
                      >
                        {shortId(entry.node_id)}
                      </button>
                    ) : (
                      <span className="tabular font-mono">{shortId(entry.node_id)}</span>
                    )}
                  </td>
                  <td className="tabular px-2 py-1 text-right">
                    {entry.score === null || entry.score === undefined
                      ? '未评分'
                      : entry.score.toFixed(4)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      {/* 5. 数据边界审计 */}
      <Panel
        title="数据边界审计"
        hint="只报可读性：available 表示文件在，不代表里面有数据"
      >
        <div className="grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-3 lg:grid-cols-4">
          {boundary.rows.map((row) => (
            <div key={row.key} className="flex items-baseline justify-between gap-2">
              <span className="truncate font-mono text-[10px] text-fg-muted" title={row.key}>
                {row.key}
              </span>
              <StatusBadge
                tone={row.view.tone === 'positive' ? 'success' : row.noteworthy ? 'warning' : 'neutral'}
                showDot={false}
              >
                {row.view.text}
              </StatusBadge>
            </div>
          ))}
        </div>

        {boundary.warnings.length > 0 ? (
          <ul className="mt-2 flex list-none flex-col gap-1 border-t border-border-subtle p-0 pt-2">
            {boundary.warnings.map((warning, index) => (
              <li key={`${warning.field}-${index}`} className="text-[10px] text-warning-500">
                契约警告：<span className="font-mono">{warning.field || '（未指定字段）'}</span>
                {' '}— {warning.reason || '未给出原因'}
              </li>
            ))}
          </ul>
        ) : null}
      </Panel>

      {/* 6. 制品下载 */}
      <Panel title="报告文件" hint="只有服务端铸出的制品 id 能下载">
        {reportManifest && reportManifest.available === false ? (
          <p className="text-[11px] text-fg-subtle" data-testid="report-unavailable">
            该运行还没有生成报告文件（PRD 13.5：报告导出属后续阶段，这里只展示已存在的文件）。
          </p>
        ) : null}
        {(reportManifest?.files ?? []).length === 0 ? (
          <p className="text-[11px] text-fg-subtle italic">没有报告文件</p>
        ) : (
          <div className="flex flex-col gap-1.5">
            {(reportManifest?.files ?? []).map((file) => (
              <DownloadLink key={file.artifact_id} decision={reportDownload(runId, file)} />
            ))}
          </div>
        )}
      </Panel>

      <Panel title="全部制品" hint="引擎内部产物（数据库 / 日志）不开放下载">
        {(artifacts ?? []).length === 0 ? (
          <p className="text-[11px] text-fg-subtle italic">没有制品</p>
        ) : (
          <div className="flex flex-col gap-1.5">
            {(artifacts ?? []).map((artifact) => (
              <div key={artifact.artifact_id} className="flex flex-wrap items-baseline gap-2">
                <span className="font-mono text-[10px] text-fg-muted">{artifact.kind}</span>
                <DownloadLink
                  decision={downloadDescriptor(runId, {
                    artifact_id: artifact.artifact_id,
                    display_name: artifact.display_name,
                    media_type: artifact.media_type,
                    size_bytes: artifact.size_bytes,
                    state: artifact.state,
                    downloadable: artifact.downloadable,
                  })}
                />
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
