/**
 * 混合云实测：平板（边缘遥测）↔ 本机评估域（GPU）↔ 远端服务器（经跳板机自进化）。
 *
 * 与前面几幕的回放不同，这一幕全部读 `/api/edge/*` 的实时状态：
 * 平板推送 SMART 遥测、本机下发告警；服务器写出候选，本机在平板场景上用 GPU 评估，
 * 只把白名单分数回传服务器。
 */
import { AnimatePresence, motion } from 'motion/react';
import type { ReactNode } from 'react';
import { useState } from 'react';

import type { EdgeState, GpuStatus, RemoteCandidate, RemoteState } from '@/features/hybrid/edge-api';
import { useEdgeActions, useEdgeState, useGpu, useLlmStatus, useRemoteActions, useRemoteState } from '@/features/hybrid/edge-api';

import { EvoBot } from '../bot/EvoBot';
import type { BotMood } from '../bot/EvoBot';
import { AnimatedNumber, Icon } from '../ui';

const PHASE_LABEL: Record<string, string> = {
  idle: '待机',
  ingesting: '接收遥测',
  scoring: '评分中',
  observing: '观察期',
  done: '场景完成',
};

function fmtBytes(n: number): string {
  if (n >= 1 << 20) return `${(n / (1 << 20)).toFixed(1)} MB`;
  if (n >= 1 << 10) return `${(n / (1 << 10)).toFixed(1)} KB`;
  return `${n} B`;
}

export function HybridScreen() {
  const edgeQuery = useEdgeState();
  const gpuQuery = useGpu();
  const remoteQuery = useRemoteState();
  const edge = edgeQuery.data;
  const remote = remoteQuery.data;

  if (edgeQuery.isError) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <div className="evo-card max-w-lg p-6 text-sm text-[var(--evo-muted)]">
          本地评估域接口不可用：{String(edgeQuery.error)}。请用 <code className="evo-mono">scripts/edge_demo.ps1</code> 启动带 /api/edge 的后端。
        </div>
      </div>
    );
  }
  if (!edge || !remote) {
    return <div className="flex h-full items-center justify-center text-sm text-[var(--evo-muted)]">正在连接本地评估域…</div>;
  }

  return (
    <div className="flex h-full flex-col gap-3 p-4" data-evo-hybrid="true">
      <TriDomain edge={edge} remote={remote} gpu={gpuQuery.data} />
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)_minmax(0,1fr)] gap-3">
        <TabletScene edge={edge} />
        <div className="flex min-h-0 flex-col gap-3">
          <RemoteControls remote={remote} />
          <CandidateList remote={remote} />
        </div>
        <EventColumn edge={edge} remote={remote} />
      </div>
    </div>
  );
}

function TriDomain({ edge, remote, gpu }: { edge: EdgeState; remote: RemoteState; gpu?: GpuStatus }) {
  const device = edge.device;
  const streaming = edge.stream.phase === 'ingesting' || edge.stream.phase === 'scoring';
  const evaluating = remote.candidates.some((c) => c.status === 'evaluating') || remote.local_step != null;
  const generating = remote.running && remote.remote.current?.phase === 'llm';
  const tabletMood: BotMood = !device?.online ? 'idle' : streaming ? 'talk' : 'look';
  const localMood: BotMood = evaluating ? 'eval' : streaming ? 'listen' : 'idle';
  const serverMood: BotMood = generating ? 'think' : remote.running ? 'look' : remote.phase === 'done' ? 'happy' : 'idle';
  const best = remote.remote.best;
  const serverGpu = remote.server_gpus[0];

  return (
    <div className="evo-card grid shrink-0 grid-cols-[1fr_auto_1fr_auto_1fr] items-stretch gap-0 px-2 py-3">
      <Domain
        bot={<EvoBot size={46} shape="squircle" mood={tabletMood} color="#0EA5E9" />}
        title="平板 · 机房数字孪生"
        tag={device ? `${device.name} · ${device.addr}` : '未连接'}
        online={!!device?.online}
        lines={[
          ['遥测', `${edge.stream.frames} 帧 · ${fmtBytes(edge.stream.bytes)}`],
          ['场景', `${PHASE_LABEL[edge.stream.phase] ?? edge.stream.phase} · 第 ${edge.stream.day}/${edge.stream.horizon_days} 天`],
        ]}
      />
      <Link up={`SMART 遥测 ${edge.stream.rows} 行`} down={`告警 ${edge.outcome.after.alarms} 条`} active={streaming} />
      <Domain
        bot={<EvoBot size={52} mood={localMood} />}
        title="本机评估域 · GPU"
        tag={gpu?.available ? gpu.name ?? 'GPU' : '无 GPU'}
        online={!!gpu?.available}
        lines={[
          ['GPU', gpu?.available ? `${gpu.util ?? 0}% · ${gpu.mem_used_mb ?? 0}/${gpu.mem_total_mb ?? 0} MB` : '—'],
          ['评估', remote.local_step ?? (evaluating ? '评估候选中' : '空闲')],
        ]}
        highlight={gpu?.util ?? 0}
      />
      <Link up={`白名单分数 ${remote.candidates.filter((c) => c.status !== 'evaluating').length} 次`} down={`候选程序 ${remote.candidates.length} 个`} active={remote.running} reverse />
      <Domain
        bot={<EvoBot size={46} shape="hex" mood={serverMood} color="#7C3AED" />}
        title="远端服务器 · 自进化"
        tag={remote.remote.host ?? remote.config.target ?? '经跳板机 SSH'}
        online={remote.running}
        lines={[
          ['进化', remote.session_id ? `${remote.mode === 'real' ? '真实' : '演示'} · 第 ${remote.remote.generation ?? 0}/${remote.remote.generations ?? '-'} 代` : '未启动'],
          ['最佳', best ? `${best.id} · ROS ${best.score.toFixed(2)}` : '—'],
          ['GPU', serverGpu ? `${serverGpu.name.replace('NVIDIA GeForce ', '')} ${serverGpu.util}%` : '—'],
        ]}
      />
    </div>
  );
}

function Domain({ bot, title, tag, online, lines, highlight }: { bot: ReactNode; title: string; tag: string; online: boolean; lines: [string, string][]; highlight?: number }) {
  return (
    <div className="flex min-w-0 items-center gap-3 px-3">
      <div className="relative">
        {bot}
        <span className={`absolute -right-0.5 -bottom-0.5 size-2.5 rounded-full ring-2 ring-white ${online ? 'bg-green-500' : 'bg-slate-300'}`} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-semibold">{title}</div>
        <div className="evo-mono truncate text-[10.5px] text-[var(--evo-muted)]">{tag}</div>
        <div className="mt-1 space-y-0.5">
          {lines.map(([k, v]) => (
            <div key={k} className="flex gap-2 text-[11.5px]">
              <span className="w-8 shrink-0 text-[var(--evo-subtle)]">{k}</span>
              <span className="evo-mono truncate">{v}</span>
            </div>
          ))}
        </div>
        {highlight !== undefined && (
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-100">
            <motion.div className="h-full rounded-full bg-[var(--evo-brand)]" animate={{ width: `${Math.min(100, highlight)}%` }} transition={{ duration: 0.5 }} />
          </div>
        )}
      </div>
    </div>
  );
}

function Link({ up, down, active, reverse }: { up: string; down: string; active: boolean; reverse?: boolean }) {
  return (
    <div className="flex w-[150px] flex-col justify-center gap-2 text-[10.5px]">
      <Lane label={reverse ? `← ${up}` : `${up} →`} active={active} dir={reverse ? -1 : 1} />
      <Lane label={reverse ? `${down} →` : `← ${down}`} active={active} dir={reverse ? 1 : -1} />
    </div>
  );
}

function Lane({ label, active, dir }: { label: string; active: boolean; dir: 1 | -1 }) {
  return (
    <div>
      <div className="evo-mono truncate text-center text-[var(--evo-muted)]">{label}</div>
      <div className="relative mt-0.5 h-1.5 overflow-hidden rounded-full bg-[var(--evo-brand-50)]">
        {active && (
          <motion.span
            className="absolute top-0 h-full w-8 rounded-full bg-[var(--evo-brand)]"
            initial={{ left: dir === 1 ? '-20%' : '100%' }}
            animate={{ left: dir === 1 ? '100%' : '-20%' }}
            transition={{ duration: 1.1, repeat: Infinity, ease: 'linear' }}
          />
        )}
      </div>
    </div>
  );
}

function diskColor(d: EdgeState['grid'][number]): string {
  if (d.failed_day !== null) return d.after ? 'bg-red-500 ring-2 ring-sky-400' : 'bg-red-500';
  if (d.after) return 'bg-sky-400';
  if (d.before) return 'bg-amber-400';
  return 'bg-slate-200';
}

function TabletScene({ edge }: { edge: EdgeState }) {
  const actions = useEdgeActions();
  const racks = new Map<number, EdgeState['grid']>();
  for (const d of edge.grid) racks.set(d.rack, [...(racks.get(d.rack) ?? []), d]);
  const busy = actions.simulate.isPending || edge.stream.phase === 'ingesting';
  const { before, after } = edge.outcome;
  return (
    <div className="evo-card flex min-h-0 flex-col p-4">
      <div className="flex items-center justify-between">
        <div className="text-xs font-semibold text-[var(--evo-muted)]">平板场景（评估数据来源）</div>
        <button className="evo-chip" disabled={busy} onClick={() => actions.simulate.mutate(1)}>
          <Icon name="play" size={12} /> {busy ? '回放中' : '无平板时回放'}
        </button>
      </div>
      <div className="evo-scroll mt-2 min-h-0 flex-1 space-y-1 overflow-auto">
        {[...racks.entries()].map(([rack, disks]) => (
          <div key={rack} className="flex items-center gap-1.5">
            <span className="evo-mono w-7 text-[10px] text-[var(--evo-subtle)]">R{rack}</span>
            <div className="flex flex-wrap gap-[3px]">
              {disks.map((d) => (
                <span key={d.sn} title={`${d.sn} · ${d.model}`} className={`size-2.5 rounded-[3px] ${diskColor(d)}`} />
              ))}
            </div>
          </div>
        ))}
        {edge.grid.length === 0 && <div className="py-6 text-center text-xs text-[var(--evo-subtle)]">等待平板推送遥测…</div>}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <Outcome title="进化前 · init.py" caught={before.caught} failures={before.failures} fa={before.false_alarms} tone="amber" />
        <Outcome title="进化后 · 4016914b" caught={after.caught} failures={after.failures} fa={after.false_alarms} tone="brand" />
      </div>
      <div className="mt-2 flex gap-3 text-[10.5px] text-[var(--evo-muted)]">
        <Legend cls="bg-amber-400" text="进化前告警" />
        <Legend cls="bg-sky-400" text="进化后告警" />
        <Legend cls="bg-red-500" text="实际故障" />
      </div>
    </div>
  );
}

function Outcome({ title, caught, failures, fa, tone }: { title: string; caught: number; failures: number; fa: number | null; tone: 'amber' | 'brand' }) {
  return (
    <div className={`rounded-xl border px-3 py-2 ${tone === 'brand' ? 'border-[#BFD3FB] bg-[var(--evo-brand-50)]' : 'border-amber-200 bg-amber-50'}`}>
      <div className="text-[11px] text-[var(--evo-muted)]">{title}</div>
      <div className={`evo-mono text-xl font-bold ${tone === 'brand' ? 'text-[var(--evo-brand)]' : 'text-amber-600'}`}>
        {caught}/{failures}
      </div>
      <div className="text-[10.5px] text-[var(--evo-muted)]">提前捕获 · 误报 {fa ?? '—'}</div>
    </div>
  );
}

function Legend({ cls, text }: { cls: string; text: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className={`size-2 rounded-[2px] ${cls}`} /> {text}
    </span>
  );
}

function RemoteControls({ remote }: { remote: RemoteState }) {
  const llm = useLlmStatus().data;
  const actions = useRemoteActions();
  const [mode, setMode] = useState<'demo' | 'real'>('demo');
  const [provider, setProvider] = useState<'qwen' | 'codex'>('qwen');
  const [generations, setGenerations] = useState(3);
  const codexReady = !!llm?.codex.login?.ok;
  const running = remote.running;
  const start = () => actions.start.mutate({ mode, provider: mode === 'real' ? provider : undefined, generations });
  const best = remote.remote.best;

  return (
    <div className="evo-card p-4">
      <div className="flex items-center justify-between">
        <div className="text-xs font-semibold text-[var(--evo-muted)]">远端自进化</div>
        <span className="evo-mono text-[10.5px] text-[var(--evo-subtle)]">{remote.session_id ?? '尚未启动'}</span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <button className="evo-chip" data-active={mode === 'demo'} onClick={() => setMode('demo')} disabled={running}>
          演示回放
        </button>
        <button className="evo-chip" data-active={mode === 'real'} onClick={() => setMode('real')} disabled={running}>
          真实运行
        </button>
        {mode === 'real' && (
          <>
            <button className="evo-chip" data-active={provider === 'qwen'} onClick={() => setProvider('qwen')} disabled={running}>
              Qwen · {llm?.qwen.model ?? 'qwen3.8-max-0902'}
            </button>
            <button
              className="evo-chip"
              data-active={provider === 'codex'}
              onClick={() => setProvider('codex')}
              disabled={running || !codexReady}
              title={codexReady ? 'Codex 本地登录' : llm?.codex.hint ?? 'Codex 未登录'}
            >
              Codex{codexReady ? '' : '（未登录）'}
            </button>
          </>
        )}
        <label className="evo-chip">
          代数
          <input
            type="number"
            min={1}
            max={20}
            value={generations}
            disabled={running}
            onChange={(e) => setGenerations(Math.max(1, Math.min(20, Number(e.target.value) || 1)))}
            className="evo-mono w-9 bg-transparent text-center outline-none"
          />
        </label>
      </div>
      <div className="mt-3 flex items-center gap-2">
        {running ? (
          <button className="evo-btn evo-btn--ghost" onClick={() => actions.stop.mutate()} disabled={actions.stop.isPending}>
            <Icon name="pause" size={14} /> 停止
          </button>
        ) : (
          <button className="evo-btn evo-btn--primary" onClick={start} disabled={actions.start.isPending}>
            <Icon name="play" size={14} /> 启动远端进化
          </button>
        )}
        <div className="ml-auto text-right">
          <div className="text-[10.5px] text-[var(--evo-muted)]">当前最佳 ROS</div>
          <div className="evo-mono text-lg font-bold text-[var(--evo-brand)]">{best ? <AnimatedNumber value={best.score} /> : '—'}</div>
        </div>
      </div>
      {remote.error && <div className="mt-2 rounded-lg bg-red-50 px-3 py-1.5 text-[11.5px] text-[var(--evo-bad)]">{remote.error}</div>}
      {actions.start.data && !actions.start.data.started && (
        <div className="mt-2 rounded-lg bg-amber-50 px-3 py-1.5 text-[11.5px] text-amber-700">{actions.start.data.reason}</div>
      )}
    </div>
  );
}

function candidateTone(c: RemoteCandidate): string {
  if (c.status === 'evaluating') return 'border-[var(--evo-brand)] bg-[var(--evo-brand-50)]';
  if (c.status === 'invalid') return 'border-slate-200 bg-slate-50 opacity-70';
  return 'border-[var(--evo-border)] bg-white';
}

function shortError(err: string | null | undefined): string {
  if (!err) return '运行失败';
  const lines = err.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  const exc = [...lines].reverse().find((l) => /^\w+(Error|Exception)\b/.test(l));
  return exc ?? lines[lines.length - 1] ?? err;
}

function CandidateList({ remote }: { remote: RemoteState }) {
  const bestId = remote.remote.best?.id;
  return (
    <div className="evo-card flex min-h-0 flex-1 flex-col p-4">
      <div className="mb-2 text-xs font-semibold text-[var(--evo-muted)]">候选 · 平板场景上的本机 GPU 评估</div>
      <div className="evo-scroll min-h-0 flex-1 space-y-1.5 overflow-auto">
        <AnimatePresence initial={false}>
          {[...remote.candidates].reverse().map((c) => (
            <motion.div
              key={c.id}
              layout
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              className={`flex items-center gap-3 rounded-xl border px-3 py-2 ${candidateTone(c)}`}
            >
              <EvoBot size={24} mood={c.status === 'evaluating' ? 'eval' : c.status === 'invalid' ? 'fail' : c.id === bestId ? 'best' : 'happy'} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="evo-mono text-[12px] font-semibold">{c.id}</span>
                  <span className="text-[10.5px] text-[var(--evo-subtle)]">← {c.parent ?? 'seed'} · {c.origin ?? ''}</span>
                </div>
                <div className="line-clamp-2 text-[11px] break-all text-[var(--evo-muted)]" title={c.error ?? undefined}>
                  {c.status === 'evaluating'
                    ? '本机 GPU 评估中…'
                    : c.status === 'invalid'
                      ? `无效：${shortError(c.error)}`
                      : `捕获 ${c.scene?.caught ?? '—'}/${c.scene?.failures ?? '—'} · 误报 ${c.scene?.false_alarms ?? '—'} · GPU 峰值 ${c.gpu?.peak_util ?? '—'}% · ${c.elapsed_s?.toFixed(0) ?? '—'}s`}
                </div>
              </div>
              <span className={`evo-mono text-[15px] font-bold ${c.id === bestId ? 'text-[var(--evo-brand)]' : ''}`}>{c.ros != null ? c.ros.toFixed(2) : '—'}</span>
            </motion.div>
          ))}
        </AnimatePresence>
        {remote.candidates.length === 0 && <div className="py-8 text-center text-xs text-[var(--evo-subtle)]">启动后，服务器写出的候选会逐个出现在这里</div>}
      </div>
    </div>
  );
}

function EventColumn({ edge, remote }: { edge: EdgeState; remote: RemoteState }) {
  const events = [
    ...remote.events.map((e) => ({ at: e.at, text: e.text, tag: e.source === 'server' ? '服务器' : '本机', tone: e.source === 'server' ? 'bg-violet-50 text-violet-600' : 'bg-[var(--evo-brand-50)] text-[var(--evo-brand)]' })),
    ...edge.events.map((e) => ({ at: e.at, text: e.text, tag: '平板', tone: e.kind === 'failure' ? 'bg-red-50 text-[var(--evo-bad)]' : 'bg-sky-50 text-sky-600' })),
  ]
    .sort((a, b) => b.at - a.at)
    .slice(0, 40);
  const lastUpload = edge.uploads[edge.uploads.length - 1];
  return (
    <div className="flex min-h-0 flex-col gap-3">
      <div className="evo-card p-4">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-[var(--evo-muted)]">
          <Icon name="shield" size={14} /> 数据边界
        </div>
        <div className="mt-1.5 text-[11.5px] leading-relaxed">
          留在本机：{edge.data_boundary.kept_local.slice(0, 3).join('、')} 等
        </div>
        <div className="mt-1 text-[11.5px] leading-relaxed text-[var(--evo-muted)]">
          最近一次回传 {lastUpload ? `${lastUpload.bytes_allowed} B，拦截 ${lastUpload.blocked.length} 个字段` : '—'}
        </div>
      </div>
      <div className="evo-card flex min-h-0 flex-1 flex-col p-4">
        <div className="mb-2 text-xs font-semibold text-[var(--evo-muted)]">三端事件</div>
        <div className="evo-scroll min-h-0 flex-1 space-y-1.5 overflow-auto">
          {events.map((e, i) => (
            <div key={`${e.at}-${i}`} className="flex items-start gap-2 text-[11.5px]">
              <span className={`evo-mono mt-px shrink-0 rounded px-1.5 text-[10px] font-semibold ${e.tone}`}>{e.tag}</span>
              <span className="leading-snug">{e.text}</span>
            </div>
          ))}
          {events.length === 0 && <div className="text-xs text-[var(--evo-subtle)]">暂无事件</div>}
        </div>
      </div>
    </div>
  );
}
