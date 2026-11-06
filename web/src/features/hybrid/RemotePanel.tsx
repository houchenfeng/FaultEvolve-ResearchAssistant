/**
 * 远端自进化：经跳板机 SSH 驱动服务器上的进化器。
 *
 * 演示模式：服务器回放已落盘候选，不调用 LLM；真实运行：服务器每一代调用
 * Qwen（或经笔记本本地 Codex 登录）生成候选。两种模式下每个候选都在本机用
 * 平板场景数据 + 完整验证集评估，只把白名单分数写回服务器。
 */
import { useState } from 'react';

import { StatusBadge } from '@/components/ui/StatusBadge';

import { useLlmStatus, useRemoteActions, useRemoteState, type RemoteCandidate } from './edge-api';

const PHASE_LABEL: Record<string, string> = {
  idle: '未启动',
  connecting: '连接跳板机',
  deploying: '部署会话',
  evolving: '远端进化中',
  done: '已完成',
  stopped: '已停止',
  error: '出错',
};

function CandidateRow({ c, best }: { c: RemoteCandidate; best: string | undefined }) {
  return (
    <tr className="border-t border-border-subtle">
      <td className="py-1 pr-2 font-mono">
        {c.id}
        {c.id === best ? <span className="ml-1 text-success-700 dark:text-success-500">★</span> : null}
      </td>
      <td className="pr-2 font-mono text-fg-subtle">{c.parent ?? '—'}</td>
      <td className="pr-2 text-fg-subtle">{c.origin}</td>
      <td className="tabular pr-2 text-right">{c.status === 'evaluating' ? '评估中…' : c.ros != null ? c.ros.toFixed(2) : '无效'}</td>
      <td className="tabular pr-2 text-right">
        {c.scene?.caught != null ? `${c.scene.caught}/${c.scene.failures}` : '—'}
        {c.scene?.false_alarms != null ? <span className="text-fg-subtle"> · 误报 {c.scene.false_alarms}</span> : null}
      </td>
      <td className="tabular pr-2 text-right">{c.gpu?.peak_util != null ? `${c.gpu.peak_util}%` : '—'}</td>
      <td className="tabular text-right">{c.bootstrap ? `${(c.bootstrap.p_improve_f1 * 100).toFixed(0)}%` : '—'}</td>
    </tr>
  );
}

export function RemoteEvolutionPanel() {
  const { data: remote } = useRemoteState();
  const { data: llm } = useLlmStatus();
  const actions = useRemoteActions();
  const [mode, setMode] = useState<'demo' | 'real'>('demo');
  const [provider, setProvider] = useState<'qwen' | 'codex'>('qwen');
  const [generations, setGenerations] = useState(2);

  const running = remote?.running ?? false;
  const best = remote?.remote.best ?? undefined;
  const codexReady = Boolean(llm?.codex.installed && llm.codex.login?.ok);

  return (
    <section className="fe-card flex flex-col gap-3 p-4" data-remote-evolution="true">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-fg">远端自进化（跳板机 SSH）</h3>
        <StatusBadge tone={remote?.phase === 'error' ? 'danger' : running ? 'brand' : remote?.phase === 'done' ? 'success' : 'neutral'}>
          {PHASE_LABEL[remote?.phase ?? 'idle'] ?? remote?.phase}
        </StatusBadge>
        <span className="text-[11px] text-fg-subtle">
          {remote?.config.jump ? `${remote.config.jump} → ` : ''}
          {remote?.config.target ?? '未配置'}
        </span>
        <span className="flex-1" />
        <button type="button" className="fe-btn fe-btn-sm px-2 py-1 text-xs" onClick={() => actions.probe.mutate()} disabled={actions.probe.isPending}>
          {actions.probe.isPending ? '探测中…' : '探测服务器'}
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-3 text-xs">
        <div className="flex overflow-hidden rounded border border-border-strong">
          {(['demo', 'real'] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`px-3 py-1 ${mode === m ? 'bg-brand-500 text-white' : 'text-fg-muted'}`}
            >
              {m === 'demo' ? '演示（回放候选）' : '真实运行（LLM 实时生成）'}
            </button>
          ))}
        </div>
        {mode === 'real' ? (
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value as 'qwen' | 'codex')}
            className="rounded border border-border-strong bg-surface px-2 py-1"
          >
            <option value="qwen">Qwen API · {llm?.qwen.model ?? 'qwen3.8-max-0902'}{llm?.qwen.key_present ? '' : '（缺 key）'}</option>
            <option value="codex" disabled={!codexReady}>Codex 本地登录{codexReady ? '' : '（未登录）'}</option>
          </select>
        ) : null}
        <label className="flex items-center gap-1 text-fg-muted">
          代数
          <input
            type="number"
            min={1}
            max={20}
            value={generations}
            onChange={(e) => setGenerations(Number(e.target.value) || 1)}
            className="w-14 rounded border border-border-strong bg-surface px-1 py-0.5"
          />
        </label>
        <button
          type="button"
          className="fe-btn fe-btn-primary fe-btn-sm px-3 py-1 text-xs"
          disabled={running || actions.start.isPending}
          onClick={() => actions.start.mutate({ mode, provider: mode === 'real' ? provider : undefined, generations })}
        >
          启动远端进化
        </button>
        <button type="button" className="fe-btn fe-btn-sm px-3 py-1 text-xs" disabled={!running} onClick={() => actions.stop.mutate()}>
          停止
        </button>
      </div>

      {actions.probe.data ? (
        <pre className="max-h-28 overflow-auto rounded bg-surface-muted p-2 text-[10px] text-fg-muted">{JSON.stringify(actions.probe.data, null, 1)}</pre>
      ) : null}
      {remote?.error ? <div className="text-xs text-danger-500">{remote.error}</div> : null}

      {remote?.session_id ? (
        <div className="grid grid-cols-2 gap-2 text-[11px] md:grid-cols-4">
          <div className="rounded bg-surface-muted p-2">
            <div className="text-fg-subtle">会话</div>
            <div className="font-mono text-fg">{remote.session_id}</div>
            <div className="text-fg-subtle">{remote.mode === 'demo' ? '演示 · 回放' : `真实 · ${remote.provider}/${remote.model ?? ''}`}</div>
          </div>
          <div className="rounded bg-surface-muted p-2">
            <div className="text-fg-subtle">远端进度</div>
            <div className="tabular text-fg">
              {remote.remote.generation ?? 0} 个候选 · {remote.remote.state ?? '—'}
            </div>
            <div className="text-fg-subtle">tokens {remote.remote.tokens ?? 0}</div>
          </div>
          <div className="rounded bg-surface-muted p-2">
            <div className="text-fg-subtle">当前最佳</div>
            <div className="tabular text-fg">{best ? `${best.id} · ROS ${best.score.toFixed(2)}` : '—'}</div>
            <div className="text-fg-subtle">
              {remote.local_step ??
                (remote.remote.current
                  ? remote.remote.current.phase === 'llm'
                    ? `${remote.remote.current.id} · LLM 思考 ${remote.remote.current.reasoning_chars ?? 0} 字 / 代码 ${remote.remote.current.llm_chars ?? 0} 字`
                    : `${remote.remote.current.id} · 等待本地评估`
                  : '空闲')}
            </div>
          </div>
          <div className="rounded bg-surface-muted p-2">
            <div className="text-fg-subtle">服务器 GPU</div>
            {remote.server_gpus.map((g, i) => (
              <div key={i} className="tabular text-fg">
                {g.name.replace('NVIDIA GeForce ', '')} · {g.util}% · {Math.round(g.mem_used_mb)} MB
              </div>
            ))}
            {remote.server_gpus.length === 0 ? <div className="text-fg-subtle">—</div> : null}
          </div>
        </div>
      ) : null}

      {remote && remote.candidates.length > 0 ? (
        <table className="w-full text-[11px]">
          <thead className="text-left text-fg-subtle">
            <tr>
              <th className="pr-2 font-normal">候选</th>
              <th className="pr-2 font-normal">父代</th>
              <th className="pr-2 font-normal">来源</th>
              <th className="pr-2 text-right font-normal">本地 ROS</th>
              <th className="pr-2 text-right font-normal">平板场景命中</th>
              <th className="pr-2 text-right font-normal">GPU 峰值</th>
              <th className="text-right font-normal">P(优于父代)</th>
            </tr>
          </thead>
          <tbody>
            {remote.candidates.map((c) => (
              <CandidateRow key={c.id} c={c} best={best?.id} />
            ))}
          </tbody>
        </table>
      ) : null}

      {remote && remote.events.length > 0 ? (
        <ol className="flex max-h-48 flex-col gap-0.5 overflow-y-auto text-[11px]">
          {remote.events.map((e) => (
            <li key={`${e.at}-${e.text}`} className="flex gap-2">
              <span className="tabular shrink-0 text-fg-subtle">{new Date(e.at * 1000).toLocaleTimeString()}</span>
              <span className={`shrink-0 ${e.source === 'server' ? 'text-brand-600' : 'text-success-700 dark:text-success-500'}`}>
                {e.source === 'server' ? '服务器' : '本机'}
              </span>
              <span className={e.kind === 'error' ? 'text-danger-500' : 'text-fg-muted'}>{e.text}</span>
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}
