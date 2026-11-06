/**
 * GPU 本地评估器、云端进化回放、白名单出口记录。
 */
import { StatusBadge } from '@/components/ui/StatusBadge';

import type { CloudReplay, Evaluation, GatePacket, GpuStatus } from './edge-api';

const METRIC_ROWS: Array<[string, string, (v: number) => string]> = [
  ['combined_score', 'ROS 综合分', (v) => v.toFixed(2)],
  ['f1_p10', 'F1（P10）', (v) => v.toFixed(3)],
  ['auprc', 'AUPRC', (v) => v.toFixed(3)],
  ['recall_at_far', 'Recall@FAR≤1%', (v) => `${(v * 100).toFixed(1)}%`],
  ['recall', '召回率', (v) => `${(v * 100).toFixed(1)}%`],
  ['precision', '精确率', (v) => `${(v * 100).toFixed(1)}%`],
  ['false_alarm_rate', '误报率', (v) => `${(v * 100).toFixed(2)}%`],
];

function Gauge({ label, value, max, unit }: { label: string; value: number | null | undefined; max: number; unit: string }) {
  const pct = value == null ? 0 : Math.min(100, (value / max) * 100);
  return (
    <div>
      <div className="flex justify-between text-[10px] text-fg-subtle">
        <span>{label}</span>
        <span className="tabular text-fg">{value == null ? '—' : `${Math.round(value)}${unit}`}</span>
      </div>
      <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-surface-muted">
        <div className="h-full rounded-full bg-gradient-to-r from-success-500 via-brand-500 to-danger-500 transition-all duration-500" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function pick(metric: Record<string, number> | undefined, key: string, score?: number): number | undefined {
  if (key === 'combined_score') return score;
  return metric?.[key];
}

export function GpuEvaluatorPanel({ gpu, evaluation, onRun, starting }: { gpu?: GpuStatus; evaluation?: Evaluation; onRun: () => void; starting: boolean }) {
  const running = evaluation?.status === 'running' || starting;
  const before = evaluation?.official?.before;
  const after = evaluation?.official?.after;
  const boot = evaluation?.bootstrap;
  return (
    <section className="fe-card flex flex-col gap-3 p-4" data-gpu-evaluator="true">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold text-fg">本地评估器</h3>
        <StatusBadge tone={gpu?.available ? 'success' : 'neutral'}>{gpu?.available ? gpu.name : '无 GPU'}</StatusBadge>
        <span className="flex-1" />
        <button type="button" onClick={onRun} disabled={running} className="fe-btn fe-btn-primary fe-btn-sm px-3 py-1 text-xs">
          {running ? (evaluation?.step ?? '启动中…') : '运行本地完整评估'}
        </button>
      </div>
      <div className="grid grid-cols-4 gap-3">
        <Gauge label="GPU 利用率" value={gpu?.util} max={100} unit="%" />
        <Gauge label="显存" value={gpu?.mem_used_mb} max={gpu?.mem_total_mb ?? 12288} unit=" MB" />
        <Gauge label="功耗" value={gpu?.power_w} max={170} unit=" W" />
        <Gauge label="温度" value={gpu?.temp_c} max={90} unit="℃" />
      </div>
      {evaluation?.status === 'error' ? <div className="text-xs text-danger-500">{evaluation.error}</div> : null}
      {before && after ? (
        <div className="grid grid-cols-[1.25fr_1fr] gap-3">
          <table className="w-full text-[11px]">
            <thead className="text-fg-subtle">
              <tr><th className="text-left font-normal">官方 evaluator.py · 完整 val</th><th className="font-normal">进化前</th><th className="font-normal">进化后</th></tr>
            </thead>
            <tbody>
              {METRIC_ROWS.map(([key, label, fmt]) => {
                const b = pick(before.metric, key, before.combined_score);
                const a = pick(after.metric, key, after.combined_score);
                const better = a !== undefined && b !== undefined && (key === 'false_alarm_rate' ? a < b : a > b);
                return (
                  <tr key={key} className="border-t border-border-subtle">
                    <td className="py-1 text-fg-muted">{label}</td>
                    <td className="tabular text-center">{b === undefined ? '—' : fmt(b)}</td>
                    <td className={`tabular text-center font-semibold ${better ? 'text-success-700 dark:text-success-500' : 'text-fg'}`}>{a === undefined ? '—' : fmt(a)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {boot ? (
            <div className="flex flex-col gap-2 rounded-card bg-surface-muted p-3 text-[11px]">
              <div className="font-medium text-fg">GPU 配对 bootstrap</div>
              <div className="text-fg-muted">
                {boot.n_boot.toLocaleString()} 次重采样 × {boot.n_disks.toLocaleString()} 盘 · {boot.device} · {boot.elapsed_s}s（
                {Math.round(boot.resamples_per_s).toLocaleString()} 次/秒）
              </div>
              <div>
                ΔF1 95% CI <b className="tabular">[{boot.f1.delta.lo.toFixed(3)}, {boot.f1.delta.hi.toFixed(3)}]</b>
              </div>
              <div>
                ΔAUPRC 95% CI <b className="tabular">[{boot.auprc.delta.lo.toFixed(3)}, {boot.auprc.delta.hi.toFixed(3)}]</b>
              </div>
              <div className="mt-auto rounded-card bg-success-500/10 px-2 py-1.5 text-success-700 dark:text-success-500">
                P(进化后更好) = <b className="tabular text-sm">{(boot.p_improve_f1 * 100).toFixed(2)}%</b>
              </div>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="rounded-card bg-surface-muted px-3 py-4 text-center text-[11px] text-fg-muted">
          在本机对完整验证集运行官方 evaluator.py（进化前 / 进化后两个程序），再用 GPU 做配对 bootstrap 给出提升的置信区间。
        </div>
      )}
    </section>
  );
}

export function CloudReplayPanel({ cloud }: { cloud?: CloudReplay }) {
  if (!cloud) return <section className="fe-card p-4 text-xs text-fg-subtle">加载云端进化记录…</section>;
  const scored = cloud.timeline.filter((t) => t.score !== null);
  const n = cloud.timeline.length;
  const lo = Math.floor(cloud.initial_score - 4);
  const hi = Math.ceil(cloud.best_score + 3);
  const W = 520;
  const H = 150;
  const x = (i: number) => 28 + (i / Math.max(1, n - 1)) * (W - 40);
  const y = (v: number) => 10 + (1 - (v - lo) / (hi - lo)) * (H - 28);
  const best = cloud.timeline.map((t, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(t.best_so_far).toFixed(1)}`).join(' ');
  const islands = Object.entries(cloud.islands);
  return (
    <section className="fe-card flex flex-col gap-3 p-4" data-cloud-replay="true">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold text-fg">云端进化</h3>
        <StatusBadge tone="info">服务器真实运行 · 回放</StatusBadge>
        <span className="flex-1" />
        <span className="font-mono text-[10px] text-fg-subtle">{cloud.run_id}</span>
      </div>
      <div className="flex items-end gap-4">
        <div>
          <div className="text-[10px] text-fg-subtle">ROS</div>
          <div className="tabular text-2xl font-bold text-fg">
            {cloud.initial_score.toFixed(2)} <span className="text-fg-subtle">→</span> <span className="text-success-700 dark:text-success-500">{cloud.best_score.toFixed(2)}</span>
          </div>
        </div>
        <div className="text-[11px] text-fg-muted">
          {n} 个候选 · {islands.length} 个岛 · {(cloud.total_tokens / 1e6).toFixed(1)}M tokens · {cloud.wall_time_h}h
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
        {[lo, (lo + hi) / 2, hi].map((v) => (
          <g key={v}>
            <line x1={28} x2={W - 12} y1={y(v)} y2={y(v)} className="stroke-border-subtle" strokeDasharray="3 4" />
            <text x={0} y={y(v) + 3} className="fill-fg-subtle text-[9px]">{v.toFixed(0)}</text>
          </g>
        ))}
        {scored.map((t) => (
          <circle
            key={t.id}
            cx={x(t.order)}
            cy={y(Math.max(lo, t.score ?? lo))}
            r={t.on_best_path ? 4.5 : 2.2}
            className={t.on_best_path ? 'fill-success-500 stroke-white' : 'fill-brand-300'}
            strokeWidth={t.on_best_path ? 1.5 : 0}
          />
        ))}
        <path d={best} fill="none" className="stroke-success-500" strokeWidth={2} />
      </svg>
      <ol className="flex flex-col gap-1 text-[11px]">
        {cloud.best_path.map((p, i) => (
          <li key={p.id} className="flex items-baseline gap-2">
            <span className="tabular w-12 shrink-0 font-semibold text-fg">{p.score.toFixed(2)}</span>
            <span className="shrink-0 font-mono text-fg-subtle">{p.id}</span>
            <span className="truncate text-fg-muted">{i === 0 ? '初始程序 init.py' : [p.operator, p.intent].filter(Boolean).join(' · ')}</span>
          </li>
        ))}
      </ol>
      <div className="text-[10px] text-fg-subtle">{cloud.note}</div>
    </section>
  );
}

function Packet({ p }: { p: GatePacket }) {
  return (
    <div className="rounded-card border border-border-subtle p-2">
      <div className="flex items-center gap-2 text-[11px]">
        <span className="font-medium text-fg">
          {p.kind === 'candidate_eval'
            ? `候选评估回传 · ${String(p.allowed.candidate_id ?? '')}`
            : p.kind.startsWith('stream_summary_')
              ? `数据流结果回传 · ${p.kind.endsWith('after') ? '进化后' : '进化前'}`
              : p.kind}
        </span>
        <span className="text-fg-subtle">{new Date(p.at * 1000).toLocaleTimeString()}</span>
        <span className="flex-1" />
        <span className="tabular text-fg-subtle">出域 {p.bytes_allowed} B</span>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1">
        {Object.entries(p.allowed).map(([k, v]) => (
          <span key={k} className="rounded bg-success-500/10 px-1.5 py-0.5 text-[10px] text-success-700 dark:text-success-500" title={k}>
            {p.allowed_labels[k] ?? k}={typeof v === 'number' ? Number(v.toFixed(4)) : String(v)}
          </span>
        ))}
        {p.blocked.map((b) => (
          <span key={b.field} className="rounded bg-danger-500/10 px-1.5 py-0.5 text-[10px] text-danger-700 line-through decoration-danger-500/60 dark:text-danger-500" title={b.reason}>
            {b.field} · {b.size}
          </span>
        ))}
      </div>
    </div>
  );
}

export function BoundaryLog({ uploads, cloudPackets, keptLocal }: { uploads: GatePacket[]; cloudPackets: GatePacket[]; keptLocal: string[] }) {
  const recent = [...uploads].reverse().slice(0, 6);
  const allowedBytes = uploads.reduce((s, p) => s + p.bytes_allowed, 0) + cloudPackets.reduce((s, p) => s + p.bytes_allowed, 0);
  return (
    <section className="fe-card flex flex-col gap-3 p-4" data-boundary-log="true">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold text-fg">数据出域审计</h3>
        <StatusBadge tone="success">白名单闸门</StatusBadge>
        <span className="flex-1" />
        <span className="text-[11px] text-fg-muted">
          累计回传 {uploads.length + cloudPackets.length} 包 · {(allowedBytes / 1024).toFixed(1)} KB · 原始数据 0 B
        </span>
      </div>
      <div className="flex flex-wrap gap-1 text-[10px]">
        <span className="text-fg-subtle">始终留在本机：</span>
        {keptLocal.map((k) => (
          <span key={k} className="rounded border border-border-subtle px-1.5 py-0.5 text-fg-muted">{k}</span>
        ))}
      </div>
      <div className="flex max-h-72 flex-col gap-1.5 overflow-y-auto">
        {recent.map((p) => <Packet key={`${p.kind}-${p.at}`} p={p} />)}
        {cloudPackets.slice(-3).reverse().map((p) => <Packet key={`c-${String(p.allowed.candidate_id)}`} p={p} />)}
      </div>
    </section>
  );
}
