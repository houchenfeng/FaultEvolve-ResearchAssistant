/**
 * 进化工作台的“本地评估域”子窗口：跟着进化树上的节点走。
 *
 * 服务器每写出一个候选，本机就把它放到平板推来的机房场景上用 GPU 评估；窗口展示该节点的
 * 四步流水（收到程序 → 平板场景 → GPU 评估 → 白名单回传）、它在平板场景上预警了哪些盘，
 * 以及回传与被拦截的字段。原始遥测与逐盘预警只在本机展示，不出域。
 */
import { motion } from 'motion/react';
import type { RefObject } from 'react';

import type { EdgeState, GpuStatus, RemoteCandidate, RemoteState } from '@/features/hybrid/edge-api';
import { useEdgeActions } from '@/features/hybrid/edge-api';

import { EvoBot } from '../bot/EvoBot';
import { Icon } from '../ui';

type StepState = 'done' | 'active' | 'wait' | 'fail';

function steps(c: RemoteCandidate | undefined, localStep: string | null, edge: EdgeState): { title: string; detail: string; state: StepState }[] {
  const evaluating = c?.status === 'evaluating';
  const finished = c && c.status !== 'evaluating';
  const scene = c?.scene;
  const fromTablet = scene ? scene.source !== 'replay' : edge.stream.phase === 'done';
  const uploadedKeys = Object.keys(c?.uploaded ?? {});
  const activeText = evaluating && localStep ? localStep.replace(/^[^：]*：/, '') : '';
  return [
    {
      title: '收到候选程序',
      detail: c ? `服务器 → 本机 · ${c.lines ?? '—'} 行 · 父代 ${c.parent ?? 'seed'}` : '等待服务器写出候选',
      state: c ? 'done' : 'wait',
    },
    {
      title: '载入平板场景',
      detail: scene
        ? `${fromTablet ? '平板实时推送' : '回放场景'} · ${scene.disks} 块盘 · ${scene.failures} 块实际故障`
        : `${fromTablet ? '平板实时推送' : '平板未推完，用回放场景'} · ${edge.stream.disks || 300} 块盘`,
      state: !c ? 'wait' : evaluating && !scene ? 'active' : 'done',
    },
    {
      title: '本机 GPU 评估',
      detail: evaluating
        ? activeText || '沙箱运行候选，GPU bootstrap 检验中…'
        : c?.status === 'invalid'
          ? `无效：${(c.error ?? '').split(/\r?\n/).filter(Boolean).pop() ?? '运行失败'}`
          : finished
            ? `ROS ${c.ros?.toFixed(2) ?? '—'} · GPU 峰值 ${c.gpu?.peak_util ?? '—'}% · ${c.elapsed_s?.toFixed(0) ?? '—'}s${c.bootstrap ? ` · P(优于父代) ${(c.bootstrap.p_improve_f1 * 100).toFixed(0)}%` : ''}`
            : '—',
      state: !c ? 'wait' : evaluating ? 'active' : c.status === 'invalid' ? 'fail' : 'done',
    },
    {
      title: '白名单回传服务器',
      detail: finished ? `回传 ${uploadedKeys.length} 个标量 · 拦截 ${c.blocked?.length ?? 0} 个字段` : '评估完成后只回传分数',
      state: finished ? 'done' : 'wait',
    },
  ];
}

const DOT: Record<StepState, string> = {
  done: 'bg-[var(--evo-brand)] text-white',
  active: 'bg-white text-[var(--evo-brand)] ring-2 ring-[var(--evo-brand)]',
  wait: 'bg-slate-100 text-[var(--evo-subtle)]',
  fail: 'bg-red-500 text-white',
};

export function LocalEvalWindow({
  edge,
  remote,
  gpu,
  focus,
  following,
  onFollow,
  onClose,
  bounds,
}: {
  edge: EdgeState;
  remote: RemoteState;
  gpu?: GpuStatus;
  focus?: RemoteCandidate;
  following: boolean;
  onFollow: () => void;
  onClose: () => void;
  bounds: RefObject<HTMLDivElement | null>;
}) {
  const actions = useEdgeActions();
  const alarmed = new Set(focus?.alarm_serials ?? []);
  const evaluating = focus?.status === 'evaluating';
  const racks = new Map<number, EdgeState['grid']>();
  for (const d of edge.grid) racks.set(d.rack, [...(racks.get(d.rack) ?? []), d]);
  const device = edge.device;
  const busy = actions.simulate.isPending || edge.stream.phase === 'ingesting';
  const index = focus ? remote.candidates.findIndex((c) => c.id === focus.id) + 1 : 0;

  return (
    <motion.div
      drag
      dragMomentum={false}
      dragConstraints={bounds}
      initial={{ opacity: 0, y: 24, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 24, scale: 0.96 }}
      className="absolute top-11 right-4 z-30 flex max-h-[calc(100%-3.5rem)] w-[440px] flex-col overflow-hidden rounded-2xl border border-[#BFD3FB] bg-white shadow-[0_18px_50px_-12px_rgba(37,99,235,0.35)]"
      data-evo-local-window="true"
    >
      <div className="flex shrink-0 cursor-grab items-center gap-2 border-b border-[var(--evo-border)] bg-[var(--evo-brand-50)] px-3.5 py-2 active:cursor-grabbing">
        <EvoBot size={26} mood={evaluating ? 'eval' : focus?.status === 'invalid' ? 'fail' : focus ? 'happy' : 'idle'} />
        <div className="min-w-0 flex-1">
          <div className="text-[12.5px] font-semibold">本地评估域 · 平板交互</div>
          <div className="evo-mono truncate text-[10.5px] text-[var(--evo-muted)]">
            {device ? `平板 ${device.addr} · ${device.online ? '在线' : '离线'}` : '平板未连接'} · {gpu?.available ? `${gpu.name} ${gpu.util ?? 0}%` : '无 GPU'}
          </div>
        </div>
        {!following && (
          <button className="evo-chip !py-0.5 text-[11px]" onClick={onFollow} onPointerDown={(e) => e.stopPropagation()}>
            跟随最新
          </button>
        )}
        <button className="rounded p-1 text-[var(--evo-muted)] hover:bg-white" onClick={onClose} onPointerDown={(e) => e.stopPropagation()} aria-label="收起">
          <Icon name="close" size={14} />
        </button>
      </div>

      <div className="evo-scroll min-h-0 space-y-3 overflow-auto p-3.5" onPointerDown={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2">
          <span className={`evo-mono rounded-md px-2 py-0.5 text-[12px] font-semibold ${evaluating ? 'bg-[var(--evo-brand)] text-white' : 'bg-slate-100'}`}>
            {focus ? `#${index} ${focus.id}` : '等待候选'}
          </span>
          <span className="text-[11.5px] text-[var(--evo-muted)]">{evaluating ? '正在本机评估' : focus ? (following ? '最近一次评估' : '已选中节点') : '启动远端进化后，每个新节点都会在这里评估'}</span>
          {focus?.ros != null && <span className="evo-mono ml-auto text-lg font-bold text-[var(--evo-brand)]">{focus.ros.toFixed(2)}</span>}
        </div>

        <ol className="space-y-1.5">
          {steps(focus, remote.local_step, edge).map((s, i) => (
            <li key={s.title} className="flex items-start gap-2.5">
              <span className={`mt-0.5 flex size-[18px] shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${DOT[s.state]}`}>
                {s.state === 'active' ? (
                  <motion.span className="size-1.5 rounded-full bg-[var(--evo-brand)]" animate={{ opacity: [1, 0.2, 1] }} transition={{ duration: 1, repeat: Infinity }} />
                ) : (
                  i + 1
                )}
              </span>
              <div className="min-w-0">
                <div className={`text-[12px] font-medium ${s.state === 'wait' ? 'text-[var(--evo-subtle)]' : ''}`}>{s.title}</div>
                <div className={`truncate text-[11px] ${s.state === 'fail' ? 'text-[var(--evo-bad)]' : 'text-[var(--evo-muted)]'}`} title={s.detail}>
                  {s.detail}
                </div>
              </div>
            </li>
          ))}
        </ol>

        <div className="rounded-xl border border-[var(--evo-border)] p-2.5">
          <div className="flex items-center justify-between text-[11px] text-[var(--evo-muted)]">
            <span>平板机房场景 · 该节点的预警</span>
            {focus?.scene && focus.status === 'done' && (
              <span className="evo-mono">
                命中 {focus.scene.caught ?? '—'}/{focus.scene.failures} · 误报 {focus.scene.false_alarms ?? '—'}
              </span>
            )}
          </div>
          <div className="evo-scroll mt-1.5 max-h-[118px] space-y-[3px] overflow-auto">
            {[...racks.entries()].map(([rack, disks]) => (
              <div key={rack} className="flex items-center gap-1">
                <span className="evo-mono w-6 text-[9px] text-[var(--evo-subtle)]">R{rack}</span>
                <div className="flex flex-wrap gap-[2px]">
                  {disks.map((d) => {
                    const hit = alarmed.has(d.sn);
                    const failed = d.failed_day !== null;
                    const cls = failed ? (hit ? 'bg-red-500 ring-2 ring-[var(--evo-brand)]' : 'bg-red-500') : hit ? 'bg-sky-400' : evaluating ? 'bg-slate-200 animate-pulse' : 'bg-slate-200';
                    return <span key={d.sn} title={`${d.sn}${hit ? ' · 预警' : ''}${failed ? ' · 实际故障' : ''}`} className={`size-2 rounded-[2px] ${cls}`} />;
                  })}
                </div>
              </div>
            ))}
            {edge.grid.length === 0 && (
              <div className="flex items-center justify-between gap-2 py-2 text-[11px] text-[var(--evo-subtle)]">
                平板还没推送机房场景，评估会改用回放场景。
                <button className="evo-chip shrink-0" disabled={busy} onClick={() => actions.simulate.mutate(1)}>
                  <Icon name="play" size={11} /> {busy ? '推送中' : '模拟平板推送'}
                </button>
              </div>
            )}
          </div>
          <div className="mt-1.5 flex gap-3 text-[10px] text-[var(--evo-muted)]">
            <Legend cls="bg-sky-400" text="该节点预警" />
            <Legend cls="bg-red-500" text="实际故障" />
            <Legend cls="bg-red-500 ring-2 ring-[var(--evo-brand)]" text="提前命中" />
          </div>
        </div>

        {focus && focus.status !== 'evaluating' && (
          <div className="grid grid-cols-2 gap-2 text-[10.5px]">
            <div>
              <div className="mb-1 font-medium text-[var(--evo-muted)]">回传服务器（白名单）</div>
              <div className="evo-mono flex flex-wrap gap-1">
                {Object.keys(focus.uploaded ?? {}).map((k) => (
                  <span key={k} className="rounded bg-[var(--evo-brand-50)] px-1.5 py-0.5 text-[var(--evo-brand)]">
                    {k}
                  </span>
                ))}
              </div>
            </div>
            <div>
              <div className="mb-1 font-medium text-[var(--evo-muted)]">留在本机（已拦截）</div>
              <div className="evo-mono flex flex-wrap gap-1">
                {(focus.blocked ?? []).map((k) => (
                  <span key={k} className="flex items-center gap-0.5 rounded bg-slate-100 px-1.5 py-0.5 text-slate-500">
                    <Icon name="lock" size={9} /> {k}
                  </span>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </motion.div>
  );
}

function Legend({ cls, text }: { cls: string; text: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className={`size-2 rounded-[2px] ${cls}`} /> {text}
    </span>
  );
}
