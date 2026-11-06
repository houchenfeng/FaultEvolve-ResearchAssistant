import { AnimatePresence, animate, motion } from 'motion/react';
import type { ReactNode } from 'react';
import { useEffect, useRef, useState } from 'react';

import { useLlmStatus, useRemoteState } from '@/features/hybrid/edge-api';

export function BrandMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 120 120" fill="none" aria-hidden="true">
      <rect width="120" height="120" rx="28" fill="#2563EB" />
      <g stroke="#fff" strokeWidth="9" strokeLinecap="round" strokeLinejoin="round">
        <line x1="36" y1="88" x2="36" y2="32" />
        <line x1="36" y1="60" x2="72" y2="60" />
        <line x1="36" y1="32" x2="80" y2="32" />
        <path d="M76 20 L90 32 L76 44" />
      </g>
      <circle cx="36" cy="88" r="10" fill="#fff" />
      <circle cx="76" cy="60" r="9" fill="#2563EB" stroke="#fff" strokeWidth="7" />
    </svg>
  );
}

export function AnimatedNumber({ value, digits = 2, className }: { value: number; digits?: number; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const prev = useRef(value);
  useEffect(() => {
    const from = prev.current;
    prev.current = value;
    const controls = animate(from, value, {
      duration: 0.6,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (v) => {
        if (ref.current) ref.current.textContent = v.toFixed(digits);
      },
    });
    return () => controls.stop();
  }, [value, digits]);
  return (
    <span ref={ref} className={className}>
      {value.toFixed(digits)}
    </span>
  );
}

export function Typewriter({ text, speed = 28, onDone }: { text: string; speed?: number; onDone?: () => void }) {
  const [count, setCount] = useState(0);
  const doneRef = useRef(onDone);
  doneRef.current = onDone;
  useEffect(() => {
    setCount(0);
    const chars = Array.from(text);
    let i = 0;
    const timer = window.setInterval(() => {
      i += 1;
      setCount(i);
      if (i >= chars.length) {
        window.clearInterval(timer);
        doneRef.current?.();
      }
    }, speed);
    return () => window.clearInterval(timer);
  }, [text, speed]);
  const chars = Array.from(text);
  return (
    <span>
      {chars.slice(0, count).join('')}
      {count < chars.length && <span className="ml-0.5 inline-block h-[1em] w-[2px] translate-y-[2px] bg-current opacity-60" />}
    </span>
  );
}

export function Icon({ name, size = 16 }: { name: IconName; size?: number }) {
  const common = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  switch (name) {
    case 'gear':
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
        </svg>
      );
    case 'send':
      return (
        <svg {...common}>
          <path d="M12 19V5M5 12l7-7 7 7" />
        </svg>
      );
    case 'doc':
      return (
        <svg {...common}>
          <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
          <path d="M14 3v6h6M8 13h8M8 17h5" />
        </svg>
      );
    case 'flask':
      return (
        <svg {...common}>
          <path d="M9 3h6M10 3v6L4.5 18.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3" />
          <path d="M7 15h10" />
        </svg>
      );
    case 'seed':
      return (
        <svg {...common}>
          <path d="M12 21v-8M12 13c0-4 3-7 8-7 0 4-3 7-8 7zM12 13c0-3-2-5-6-5 0 3 2 5 6 5z" />
        </svg>
      );
    case 'cloud':
      return (
        <svg {...common}>
          <path d="M17.5 19a4.5 4.5 0 1 0-1.4-8.8A6 6 0 0 0 4.5 12.5 3.5 3.5 0 0 0 6 19z" />
        </svg>
      );
    case 'laptop':
      return (
        <svg {...common}>
          <rect x="4" y="5" width="16" height="11" rx="1.5" />
          <path d="M2 19h20" />
        </svg>
      );
    case 'lock':
      return (
        <svg {...common}>
          <rect x="5" y="11" width="14" height="10" rx="2" />
          <path d="M8 11V7a4 4 0 0 1 8 0v4" />
        </svg>
      );
    case 'server':
      return (
        <svg {...common}>
          <rect x="3" y="4" width="18" height="7" rx="1.5" />
          <rect x="3" y="13" width="18" height="7" rx="1.5" />
          <path d="M7 7.5h.01M7 16.5h.01" />
        </svg>
      );
    case 'check':
      return (
        <svg {...common}>
          <path d="M5 12.5l4.5 4.5L19 7.5" />
        </svg>
      );
    case 'play':
      return (
        <svg {...common} fill="currentColor" stroke="none">
          <path d="M8 5.5v13l11-6.5z" />
        </svg>
      );
    case 'pause':
      return (
        <svg {...common}>
          <path d="M9 5v14M15 5v14" />
        </svg>
      );
    case 'restart':
      return (
        <svg {...common}>
          <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
          <path d="M3 3v5h5" />
        </svg>
      );
    case 'skip':
      return (
        <svg {...common}>
          <path d="M5 5l9 7-9 7zM19 5v14" />
        </svg>
      );
    case 'arrow':
      return (
        <svg {...common}>
          <path d="M5 12h14M13 6l6 6-6 6" />
        </svg>
      );
    case 'close':
      return (
        <svg {...common}>
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      );
    case 'shield':
      return (
        <svg {...common}>
          <path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" />
          <path d="M8.5 12l2.5 2.5 4.5-5" />
        </svg>
      );
  }
}

export type IconName =
  | 'gear'
  | 'send'
  | 'doc'
  | 'flask'
  | 'seed'
  | 'cloud'
  | 'laptop'
  | 'lock'
  | 'server'
  | 'check'
  | 'play'
  | 'pause'
  | 'restart'
  | 'skip'
  | 'arrow'
  | 'close'
  | 'shield';

const SETTINGS_TABS = ['模型服务', '云端服务器', '本地评估', '实验预设', '演示模式'] as const;

export function SettingsPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [tab, setTab] = useState<(typeof SETTINGS_TABS)[number]>('云端服务器');
  const llm = useLlmStatus().data;
  const remoteCfg = useRemoteState().data?.config;
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            className="absolute inset-0 z-40 bg-slate-900/20"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.aside
            className="evo-card absolute top-3 right-3 bottom-3 z-50 flex w-[440px] flex-col overflow-hidden shadow-2xl"
            initial={{ x: 480 }}
            animate={{ x: 0 }}
            exit={{ x: 480 }}
            transition={{ type: 'spring', stiffness: 280, damping: 30 }}
          >
            <div className="flex items-center justify-between border-b border-[var(--evo-border)] px-5 py-4">
              <div>
                <div className="text-base font-semibold">设置</div>
                <div className="text-xs text-[var(--evo-muted)]">实验、模型 API、云端与本地执行环境都在这里</div>
              </div>
              <button className="rounded-lg p-1.5 text-[var(--evo-muted)] hover:bg-slate-100" onClick={onClose} aria-label="关闭">
                <Icon name="close" />
              </button>
            </div>
            <div className="flex gap-1 border-b border-[var(--evo-border)] px-3 py-2">
              {SETTINGS_TABS.map((t) => (
                <button key={t} className="evo-chip !border-transparent" data-active={t === tab} onClick={() => setTab(t)}>
                  {t}
                </button>
              ))}
            </div>
            <div className="evo-scroll flex-1 space-y-4 overflow-auto p-5">
              {tab === '模型服务' && (
                <>
                  <Field label="默认提供方" value={llm ? `${llm.default} · ${llm.qwen.model}` : 'qwen · qwen3.8-max-0902'} />
                  <Field label="Base URL" value={llm?.qwen.base_url ?? 'https://dashscope.aliyuncs.com/compatible-mode/v1'} mono />
                  <Field label="API Key" value={llm?.qwen.key_present ? '已在本机 .env 配置（DASHSCOPE_API_KEY）' : '未配置：在 .env 写入 DASHSCOPE_API_KEY'} />
                  <Field label="Codex" value={llm?.codex.login?.ok ? `已登录 · ${llm.codex.login.text}` : llm?.codex.hint ?? '未检测到 codex CLI'} />
                  <Hint>密钥只存在本机 .env 与服务器 ~/.fe_edge（600 权限），网页不会回显。</Hint>
                </>
              )}
              {tab === '云端服务器' && (
                <>
                  <Field label="跳板机" value={remoteCfg?.jump ?? '未配置 FE_SSH_JUMP'} mono />
                  <Field label="目标服务器" value={remoteCfg?.target ?? '未配置 FE_SSH_TARGET'} mono />
                  <Field label="远端工作目录" value={remoteCfg?.root ?? '—'} mono />
                  <Field label="Python" value={remoteCfg?.python ?? '—'} mono />
                  <Hint>服务器经跳板机运行自进化，只能看到分数与白名单聚合统计；评估数据来自平板场景，留在本机。</Hint>
                </>
              )}
              {tab === '本地评估' && (
                <>
                  <Field label="评估器" value="benchmark/hdd_mvp/evaluator.py · 指标 ROS" mono />
                  <Field label="数据目录" value="benchmark/hdd_mvp/data（不出本地）" mono />
                  <Field label="沙箱资源" value="CPU 8 核 · 内存 16 GB · 单候选超时 120 s" />
                  <Hint>原始遥测、日志与工单只在本地沙箱中读取，评估结果按白名单回传。</Hint>
                </>
              )}
              {tab === '实验预设' && (
                <>
                  <Field label="搜索策略" value="KGTE 三岛 · J-PUCT 选择 · 停滞停止" />
                  <Field label="预算" value="3 岛 × 6 轮 · 每轮每岛 ≤ 3 个候选" />
                  <Field label="知识发现" value="PMP Discovery · 预注册 + BH / e-BH 双轨" />
                </>
              )}
              {tab === '演示模式' && (
                <>
                  <Field label="数据源" value="Demo：回放 hdd_mvp_showcase_c89e2a01" />
                  <Field label="混合云模式" value="确认页选择或工作台切换：平板 ↔ 本机 GPU 评估 ↔ 远端自进化（演示回放 / 真实运行）" />
                  <Hint>
                    切换到真实模式后，同一套页面改读 /api/runs/&#123;id&#125;/stream 事件流与 /api/servers 探测结果；
                    经典工作台仍在 <a className="text-[var(--evo-brand)] underline" href="/overview">/overview</a>。
                  </Hint>
                </>
              )}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <label className="block">
      <div className="mb-1 text-xs text-[var(--evo-muted)]">{label}</div>
      <div className={`rounded-lg border border-[var(--evo-border)] bg-slate-50 px-3 py-2 text-[13px] ${mono ? 'evo-mono' : ''}`}>{value}</div>
    </label>
  );
}

function Hint({ children }: { children: ReactNode }) {
  return <div className="rounded-lg bg-[var(--evo-brand-50)] px-3 py-2 text-xs leading-relaxed text-[#1e40af]">{children}</div>;
}
