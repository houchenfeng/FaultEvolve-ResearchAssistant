/**
 * 确认页的"运行方式"与混合云实时检查：平板数据源、本机 GPU、云端服务器、模型服务。
 */
import { motion } from 'motion/react';
import { useEffect, useRef } from 'react';

import { useEdgeState, useGpu, useLlmStatus, useRemoteActions } from '@/features/hybrid/edge-api';

import type { IconName } from '../ui';
import { Icon } from '../ui';
import type { RunMode } from './hybrid-parts';

const MODES: { key: RunMode; label: string; sub: string }[] = [
  { key: 'replay', label: '回放真实实验', sub: '离线可用，播放已完成实验的完整过程' },
  { key: 'demo', label: '混合云 · 演示回放', sub: '服务器回放真实候选，本机用平板数据 + GPU 实时评估' },
  { key: 'real', label: '混合云 · 真实运行', sub: '服务器调用 Qwen 逐代生成新候选，本机实时评估' },
];

type ProbeResult = { ok?: boolean; error?: string; host?: string[]; gpus?: { name: string }[]; latency_ms?: number };

export function RunModePicker({ value, onChange }: { value: RunMode; onChange: (m: RunMode) => void }) {
  return (
    <div className="rounded-xl border border-[var(--evo-border)] px-3.5 py-3">
      <div className="mb-2 flex items-center gap-3">
        <span className="text-[var(--evo-brand)]">
          <Icon name="cloud" size={18} />
        </span>
        <span className="text-[13px] font-medium">进化怎么跑？</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {MODES.map((m) => (
          <button key={m.key} className="evo-chip" data-active={value === m.key} onClick={() => onChange(m.key)}>
            {value === m.key && <Icon name="check" size={12} />}
            {m.label}
          </button>
        ))}
      </div>
      <div className="mt-2 text-xs leading-relaxed text-[var(--evo-muted)]">{MODES.find((m) => m.key === value)?.sub}</div>
    </div>
  );
}

/** 混合云模式下的四项实时检查；服务器探测在进入确认页时自动发起一次。 */
export function LiveChecks({ mode }: { mode: RunMode }) {
  const edge = useEdgeState().data;
  const gpu = useGpu().data;
  const llm = useLlmStatus().data;
  const { probe } = useRemoteActions();
  const probed = useRef(false);
  useEffect(() => {
    if (mode === 'replay' || probed.current) return;
    probed.current = true;
    probe.mutate();
  }, [mode, probe]);

  if (mode === 'replay') return null;
  const result = probe.data as ProbeResult | undefined;
  const sceneReady = edge?.stream.phase === 'done';
  const rows: { icon: IconName; title: string; value: string; state: 'ok' | 'wait' | 'warn' }[] = [
    {
      icon: 'doc',
      title: '评估数据 · 平板场景',
      value: edge
        ? sceneReady
          ? `${edge.device?.name ?? '平板'} · ${edge.stream.rows} 行遥测 · ${edge.stream.disks} 块盘`
          : `场景未完成（${edge.stream.phase}），将使用同款回放场景`
        : '读取中',
      state: !edge ? 'wait' : sceneReady ? 'ok' : 'warn',
    },
    {
      icon: 'laptop',
      title: '本机评估 · GPU',
      value: gpu ? (gpu.available ? `${gpu.name} · ${gpu.mem_total_mb ?? '-'} MB` : '未检测到 GPU，bootstrap 改用 CPU') : '读取中',
      state: !gpu ? 'wait' : gpu.available ? 'ok' : 'warn',
    },
    {
      icon: 'server',
      title: '云端服务器 · 跳板机 SSH',
      value: probe.isPending
        ? '经跳板机探测中…'
        : result?.ok
          ? `${result.host?.[0] ?? ''} · ${result.gpus?.length ?? 0}× ${result.gpus?.[0]?.name.replace('NVIDIA GeForce ', '') ?? 'GPU'} · ${result.latency_ms ?? '-'} ms`
          : (result?.error ?? '未探测'),
      state: probe.isPending ? 'wait' : result?.ok ? 'ok' : 'warn',
    },
    {
      icon: 'cloud',
      title: '模型服务',
      value: mode === 'demo' ? '演示回放不调用模型' : llm ? `${llm.default} · ${llm.qwen.model} · ${llm.qwen.key_present ? '密钥已配置' : '缺少 DASHSCOPE_API_KEY'}` : '读取中',
      state: mode === 'demo' ? 'ok' : !llm ? 'wait' : llm.qwen.key_present ? 'ok' : 'warn',
    },
  ];

  return (
    <motion.div className="space-y-2" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
      {rows.map((r) => (
        <div key={r.title} className="flex items-center gap-3 rounded-xl border border-dashed border-[#BFD3FB] bg-[#F5F8FF] px-3.5 py-2.5">
          <span className="text-[var(--evo-brand)]">
            <Icon name={r.icon} size={18} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[13px] font-medium">{r.title}</div>
            <div className="evo-mono line-clamp-2 text-xs break-all text-[var(--evo-muted)]" title={r.value}>
              {r.value}
            </div>
          </div>
          {r.state === 'ok' ? (
            <span className="flex items-center gap-1 text-xs text-[var(--evo-good)]">
              <Icon name="check" size={14} /> 就绪
            </span>
          ) : r.state === 'wait' ? (
            <span className="flex items-center gap-1.5 text-xs text-[var(--evo-muted)]">
              <span className="evo-spin inline-block size-3 rounded-full border-2 border-[var(--evo-brand)] border-t-transparent" /> 检查中
            </span>
          ) : (
            <span className="text-xs text-amber-600">需处理</span>
          )}
        </div>
      ))}
      {!probe.isPending && result && !result.ok && (
        <button className="evo-chip" onClick={() => probe.mutate()}>
          <Icon name="restart" size={12} /> 重新探测服务器
        </button>
      )}
    </motion.div>
  );
}
