import { Link } from '@tanstack/react-router';

import { SHOWCASE_RUN_ID } from './hdd-showcase-data';

const innovations = [
  ['KGTE', '知识引导的岛屿群演化', '多岛并行搜索、岛内树演化与岛间知识交换，形成候选生成到反思改进的闭环。'],
  ['J-PUCT', 'Jev 引导的噪声感知树搜索', '把 Q value、Jev prior 与动态噪声门共同用于节点选择，降低随机涨点带来的误判。'],
  ['PMP Discovery', '现象—机理—原理知识发现', '通过预注册、确认检验、机制对局和迁移检验，把模型改进沉淀为可审计知识。'],
];
const links = [
  ['查看三岛协同进化图', '/runs/$runId/tree'],
  ['查看本地评测结果', '/runs/$runId/results'],
  ['查看 C-89 知识证据链', '/runs/$runId/knowledge'],
] as const;
const knowledgeCards = [
  { id: 'C-89f4bdd1-0010', level: 'CONFIRMED', title: '窗口末 smart_194_normalized 是短期失效的正向增量信号', evidence: '确认集效应约 0.03，置信区间排除 0；通过 BH 确认轨。', tone: 'border-success-500/30 bg-success-50 text-success-700' },
  { id: 'KD2-MECH-001', level: 'MECHANISM OPEN', title: '更接近近端热/健康指示，因果机制仍待补充功率', evidence: '16 场机制对局均为 underpowered draw，未取得机制证书。', tone: 'border-warning-500/30 bg-warning-50 text-warning-700' },
  { id: 'TR-C89-001', level: 'TRANSFER BOUNDARY', title: '跨时间切片方向一致，但尚未达到预注册迁移线', evidence: 'train_late 符号同向、CI 含 0；跨数据集验证等待独立数据。', tone: 'border-brand-500/30 bg-brand-50 text-brand-700' },
];

export function HddCaseOverview() {
  return <div className="space-y-4" data-hdd-case-overview>
    <section className="overflow-hidden rounded-xl border border-brand-200 bg-gradient-to-br from-brand-50 via-white to-success-50 p-6">
      <p className="text-xs font-semibold tracking-[0.16em] text-brand-700">DATA CENTER HDD FAILURE PREDICTION</p>
      <h1 className="mt-2 max-w-3xl text-2xl font-semibold leading-tight text-fg">让故障预测算法在可信边界内持续自我进化</h1>
      <p className="mt-3 max-w-3xl text-sm leading-6 text-fg-muted">FaultEvolve 在本地数据与评测逻辑不出域的前提下，完成候选算法生成、沙箱评估、噪声判定、反思改进与新知识发现。</p>
      <div className="mt-5 grid gap-3 sm:grid-cols-4">
        {[['31,093','训练样本'],['30,754','验证样本'],['36.50','最佳 ROS'],['+13.69','相对提升']].map(([value,label]) => <div key={label} className="rounded-lg border border-white/80 bg-white/85 p-3 shadow-sm"><strong className="tabular text-xl text-fg">{value}</strong><span className="mt-1 block text-[11px] text-fg-muted">{label}</span></div>)}
      </div>
    </section>
    <section className="grid gap-3 lg:grid-cols-3">
      {innovations.map(([term,title,text],index) => <article key={term} className="rounded-lg border border-border-subtle bg-surface p-4"><div className="flex items-center justify-between"><span className="font-mono text-xs font-semibold text-brand-700">{term}</span><span className="text-[10px] text-fg-subtle">0{index + 1}</span></div><h2 className="mt-3 text-sm font-semibold text-fg">{title}</h2><p className="mt-2 text-xs leading-5 text-fg-muted">{text}</p></article>)}
    </section>
    <section className="rounded-lg border border-border-subtle bg-surface p-4">
      <div className="flex flex-wrap items-end justify-between gap-2"><div><h2 className="text-sm font-semibold text-fg">知识卡</h2><p className="mt-1 text-[11px] text-fg-muted">从现象确认、机制边界到迁移检验，保留完整证据等级。</p></div><Link to="/runs/$runId/knowledge" params={{ runId: SHOWCASE_RUN_ID }} className="text-xs font-medium text-brand-600 hover:underline">查看完整知识证据链 →</Link></div>
      <div className="mt-3 grid gap-3 lg:grid-cols-3">{knowledgeCards.map((card)=><article key={card.id} className="rounded-lg border border-border-subtle bg-white p-4"><div className="flex items-center justify-between gap-2"><span className="font-mono text-[10px] text-fg-subtle">{card.id}</span><span className={`rounded-full border px-2 py-0.5 text-[9px] font-semibold ${card.tone}`}>{card.level}</span></div><h3 className="mt-3 text-xs font-semibold leading-5 text-fg">{card.title}</h3><p className="mt-2 text-[11px] leading-5 text-fg-muted">{card.evidence}</p></article>)}</div>
    </section>
    <section className="grid gap-3 lg:grid-cols-[1fr_1.2fr]">
      <div className="rounded-lg border border-border-subtle bg-surface p-4"><h2 className="text-sm font-semibold text-fg">边云协同与数据主权</h2><p className="mt-2 text-xs leading-5 text-fg-muted">云端通过 REST API + SSE 下发候选代码和评估指令；本地仅回传分数与聚合统计。原始数据、评估逻辑和模型权重始终留在本地。</p><div className="mt-4 flex flex-wrap gap-2">{['原始数据不出域','本地沙箱评测','白名单指标回传','全链路可回放'].map((item) => <span key={item} className="rounded-full bg-success-50 px-2.5 py-1 text-[11px] font-medium text-success-700">{item}</span>)}</div></div>
      <div className="rounded-lg border border-border-subtle bg-surface p-4"><h2 className="text-sm font-semibold text-fg">评委查看路径</h2><div className="mt-3 grid gap-2 sm:grid-cols-3">{links.map(([label,to],index) => <Link key={label} to={to} params={{ runId: SHOWCASE_RUN_ID }} className="group rounded-lg border border-border-subtle bg-surface-muted p-3 transition hover:border-brand-400 hover:bg-brand-50"><span className="text-[10px] font-semibold text-brand-600">STEP 0{index + 1}</span><span className="mt-2 block text-xs font-semibold text-fg group-hover:text-brand-700">{label} →</span></Link>)}</div></div>
    </section>
  </div>;
}
