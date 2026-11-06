/**
 * 本地评估域的三块实时面板：边缘设备、机柜热力图、进化前后在数据流上的对比。
 */
import { StatusBadge } from '@/components/ui/StatusBadge';

import type { EdgeState, GridDisk, SideOutcome } from './edge-api';

const PHASE_LABEL: Record<EdgeState['stream']['phase'], string> = {
  idle: '等待边缘设备',
  ingesting: '接收 SMART 窗口',
  scoring: '本地打分中',
  observing: '观察期（等待真实故障）',
  done: '回放结束',
};

function kb(bytes: number): string {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(2)} MB` : `${(bytes / 1024).toFixed(1)} KB`;
}

export function EdgeDevicePanel({ state, onSimulate, simulating }: { state: EdgeState; onSimulate: () => void; simulating: boolean }) {
  const { device, stream } = state;
  const total = stream.history_days + stream.horizon_days;
  return (
    <section className="fe-card flex flex-col gap-3 p-4" data-edge-device="true">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold text-fg">边缘数据源</h3>
        <StatusBadge tone={device?.online ? 'success' : device ? 'warning' : 'neutral'}>
          {device?.online ? '在线' : device ? '已断开' : '未接入'}
        </StatusBadge>
        <span className="flex-1" />
        <button type="button" onClick={onSimulate} disabled={simulating} className="fe-btn fe-btn-secondary fe-btn-sm px-2 py-1 text-[11px]">
          本机模拟回放
        </button>
      </div>
      <div className="text-xs text-fg">
        {device ? (
          <>
            <b>{device.name}</b> <span className="text-fg-muted">· {device.addr}</span>
          </>
        ) : (
          <span className="text-fg-muted">平板打开「FaultEvolve 机房孪生」并填写下方地址即可接入。</span>
        )}
      </div>
      <div className="rounded-card bg-surface-muted px-3 py-2 font-mono text-[11px] text-fg-muted">
        {state.endpoints.length ? state.endpoints.map((e) => <div key={e}>{e}</div>) : '未检测到局域网地址'}
        {state.tablet_urls[0] ? <div className="mt-1 text-[10px]">浏览器版：{state.tablet_urls[0]}</div> : null}
      </div>
      <div>
        <div className="flex justify-between text-[11px] text-fg-muted">
          <span>{PHASE_LABEL[stream.phase]}</span>
          <span className="tabular">第 {stream.day} / {total} 天</span>
        </div>
        <div className="relative mt-1 h-2 overflow-hidden rounded-full bg-surface-muted">
          <div className="absolute inset-y-0 left-0 border-r-2 border-white/70" style={{ width: `${(stream.history_days / total) * 100}%` }} />
          <div
            className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-brand-400 via-brand-500 to-warning-500 transition-all"
            style={{ width: `${(Math.min(stream.day, total) / total) * 100}%` }}
          />
        </div>
      </div>
      <div className="grid grid-cols-4 gap-2 text-center">
        {[
          ['盘位', String(stream.disks || '—')],
          ['帧', String(stream.frames)],
          ['已接收', kb(stream.bytes)],
          ['速率', `${kb(stream.rate_bps)}/s`],
        ].map(([k, v]) => (
          <div key={k} className="rounded-card bg-surface-muted px-1 py-1.5">
            <div className="text-[10px] text-fg-subtle">{k}</div>
            <div className="tabular text-xs font-semibold text-fg">{v}</div>
          </div>
        ))}
      </div>
      <div className="text-[11px] text-fg-muted">
        模型：
        {state.models.status === 'ready'
          ? `已就绪（训练 ${state.models.fit_seconds}s，仅用本地 train 切分）`
          : state.models.status === 'training'
            ? '正在本地训练进化前/后两个算法…'
            : state.models.status === 'error'
              ? `失败：${state.models.error}`
              : '首次接入时自动训练'}
      </div>
    </section>
  );
}

function cellClass(d: GridDisk): string {
  if (d.failed_day !== null) return d.after ? 'bg-danger-500 ring-2 ring-cyan-400' : 'bg-danger-500';
  if (d.after && d.before) return 'bg-cyan-400 ring-1 ring-warning-500';
  if (d.after) return 'bg-cyan-400';
  if (d.before) return 'bg-warning-500';
  return 'bg-success-500/35';
}

export function RackHeatmap({ grid }: { grid: GridDisk[] }) {
  const racks = Math.max(0, ...grid.map((d) => d.rack + 1));
  return (
    <section className="fe-card flex flex-col gap-3 p-4" data-rack-heatmap="true">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold text-fg">机房孪生 · 盘位状态</h3>
        <span className="text-[11px] text-fg-muted">与平板 3D 场景同步</span>
      </div>
      {grid.length === 0 ? (
        <div className="flex flex-1 items-center justify-center rounded-card bg-surface-muted py-10 text-xs text-fg-subtle">等待平板握手…</div>
      ) : (
        <div className="grid grid-cols-5 gap-2">
          {Array.from({ length: racks }, (_, r) => (
            <div key={r} className="rounded-card border border-border-subtle bg-surface-muted p-1.5">
              <div className="mb-1 text-center text-[10px] font-medium text-fg-muted">R{String(r + 1).padStart(2, '0')}</div>
              <div className="grid grid-cols-6 gap-[3px]">
                {grid
                  .filter((d) => d.rack === r)
                  .sort((a, b) => a.slot - b.slot)
                  .map((d) => (
                    <span
                      key={d.sn}
                      title={`${d.sn} · ${d.model}${d.failed_day ? ` · 第 ${d.failed_day} 天故障` : ''}`}
                      className={`h-3 rounded-[2px] transition-colors ${cellClass(d)}`}
                    />
                  ))}
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="flex flex-wrap gap-3 text-[10px] text-fg-muted">
        <span className="flex items-center gap-1"><i className="h-2.5 w-2.5 rounded-sm bg-success-500/35" />正常</span>
        <span className="flex items-center gap-1"><i className="h-2.5 w-2.5 rounded-sm bg-cyan-400" />进化后预警</span>
        <span className="flex items-center gap-1"><i className="h-2.5 w-2.5 rounded-sm bg-warning-500" />仅进化前预警</span>
        <span className="flex items-center gap-1"><i className="h-2.5 w-2.5 rounded-sm bg-danger-500" />真实故障</span>
      </div>
    </section>
  );
}

function SideCard({ title, sub, o, accent }: { title: string; sub: string; o: SideOutcome; accent: 'before' | 'after' }) {
  const color = accent === 'after' ? 'text-cyan-500' : 'text-warning-700 dark:text-warning-500';
  return (
    <div className={`rounded-card border p-3 ${accent === 'after' ? 'border-cyan-400/60 bg-cyan-400/5' : 'border-border-subtle bg-surface-muted'}`}>
      <div className="text-[11px] font-medium text-fg">{title}</div>
      <div className="text-[10px] text-fg-subtle">{sub}</div>
      <div className={`tabular mt-1 text-3xl font-bold ${color}`}>
        {o.caught}
        <span className="text-base font-medium text-fg-subtle">/{o.failures}</span>
      </div>
      <div className="text-[11px] text-fg-muted">故障被提前预警</div>
      <div className="mt-2 grid grid-cols-3 gap-1 text-center text-[10px]">
        <div><div className="text-fg-subtle">预警</div><div className="tabular font-semibold text-fg">{o.alarms}</div></div>
        <div><div className="text-fg-subtle">漏报</div><div className="tabular font-semibold text-danger-500">{o.missed}</div></div>
        <div><div className="text-fg-subtle">误报</div><div className="tabular font-semibold text-fg">{o.false_alarms ?? `≤${o.pending}`}</div></div>
      </div>
    </div>
  );
}

export function StreamOutcome({ state }: { state: EdgeState }) {
  return (
    <section className="fe-card flex flex-col gap-3 p-4" data-stream-outcome="true">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold text-fg">数据流上的进化前 vs 进化后</h3>
        {state.stream.scored_in_s !== null ? <span className="text-[11px] text-fg-muted">截止日打分 {state.stream.scored_in_s}s</span> : null}
      </div>
      <div className="grid grid-cols-2 gap-2">
        <SideCard title="进化前 · init.py" sub="截止日快照 + 逻辑回归" o={state.outcome.before} accent="before" />
        <SideCard title={`进化后 · ${state.models.after?.label.split('· ')[1] ?? '4016914b'}`} sub="14 天窗口特征 + LightGBM 集成" o={state.outcome.after} accent="after" />
      </div>
      <div className="max-h-40 overflow-y-auto">
        <table className="w-full text-[11px]">
          <thead className="text-fg-subtle">
            <tr><th className="text-left font-normal">故障盘</th><th className="font-normal">位置</th><th className="font-normal">提前</th><th className="font-normal">进化前</th><th className="font-normal">进化后</th></tr>
          </thead>
          <tbody>
            {state.failures.map((f) => (
              <tr key={f.sn} className="border-t border-border-subtle">
                <td className="py-1 font-mono">{f.sn}</td>
                <td className="text-center text-fg-muted">R{String((f.rack ?? 0) + 1).padStart(2, '0')}-{(f.slot ?? 0) + 1}</td>
                <td className="tabular text-center">{f.lead_days} 天</td>
                <td className="text-center">{f.caught_before ? <span className="text-success-700 dark:text-success-500">✔</span> : <span className="text-danger-500">✘</span>}</td>
                <td className="text-center">{f.caught_after ? <span className="text-success-700 dark:text-success-500">✔</span> : <span className="text-danger-500">✘</span>}</td>
              </tr>
            ))}
            {state.failures.length === 0 ? (
              <tr><td colSpan={5} className="py-3 text-center text-fg-subtle">观察期内的真实故障会出现在这里</td></tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}
