const STEPS = [
  ['01', '现象抽取', '窗口末端 smart_194_normalized 与短期故障呈同向变化'],
  ['02', '预注册主张', '冻结特征、方向、确认切分与统计检验协议'],
  ['03', '确认集检验', '增量效应约 0.03，置信区间排除 0'],
  ['04', '多重比较控制', '通过 BH 确认轨；未通过更严格的 e-BH 发现轨'],
  ['05', '机制辩论赛', '16 场均为欠功率平局，未建立因果机制证书'],
  ['06', '跨切片外推', 'train_late 符号同向，但置信区间仍包含 0'],
] as const;

const DEBATE_ROUNDS = [
  { round: '开场陈述', side: 'Proponent · 支持方', point: '窗口末端的厂商归一化 SMART 194 捕获评估截止前的热/健康状态，应当对短期失效产生正向增量。', record: '预注册方向为正；禁止确认后翻转符号。', result: '主张进入确认集检验' },
  { round: '第一轮质询', side: 'Confounder · 混杂方', point: '盘龄、型号批次、负载尖峰、其他 SMART 与采样缺口可能同时影响该特征和故障标签。', record: '要求在固定确认切分上检验，并保留型号与时间切片结果。', result: '共同原因解释仍成立' },
  { round: '数据举证', side: 'Statistician · 统计裁判', point: '确认集 n=9,262，其中正例 327、负例 8,935。原始效应统计量 0.3124，95% CI [0.2781, 0.3459]。', record: 'p=1.0×10⁻²⁴；e-value=4.2×10¹²；CI 完全高于 0。', result: '拒绝 H₀：Δ≤0' },
  { round: '第二轮反驳', side: 'Proponent · 支持方', point: '方向、时间顺序与确认集效应均符合预注册，说明该信号并非确认集上的随机涨点。', record: 'direction_ok=true；temporal_ok=true；通过 BH 确认轨。', result: '关联主张获得确认' },
  { round: '机制追问', side: 'Critic · 批评方', point: '统计确认不等于因果识别。若它只是温度、健康评分或型号编码的代理，机制解释仍无法唯一确定。', record: '16 场机制对局均未达到预设判决功率，decisive=0。', result: '机制证书不签发' },
  { round: '最终判词', side: 'Judge · 总裁判', point: '允许表述为可复现的近端热/健康关联指示；禁止表述为已建立的物理因果定律。', record: 'BH 通过；e-BH 未升级；train_late 同向但 CI 含 0。', result: 'CONFIRMED，保留升级路径' },
] as const;

const CONFIRM_STATS = [
  ['确认切分', 'confirm', '冻结后执行'], ['样本量', '9,262', '正例 327 · 负例 8,935'],
  ['原始效应统计量', '0.3124', '对外增量刻度约 0.03'], ['95% CI', '[0.2781, 0.3459]', '完全高于 0'],
  ['p-value', '1.0 × 10⁻²⁴', '拒绝 H₀：Δ≤0'], ['e-value', '4.2 × 10¹²', '强确认支持'],
  ['方向约束', 'direction_ok = true', '冻结方向 +'], ['时间约束', 'temporal_ok = true', '时序顺序通过'],
] as const;

export function HddKnowledgeCase() {
  return <div className="flex flex-col gap-5" data-knowledge-case>
    <header className="grid gap-4 rounded-xl border border-border-subtle bg-gradient-to-r from-brand-50 to-white p-5 lg:grid-cols-[1fr_auto]">
      <div><p className="font-mono text-xs font-semibold text-brand-700">C-89f4bdd1-0010 · HDD3_F10</p><h1 className="mt-2 text-xl font-semibold text-fg">窗口末端归一化 SMART 194 的确认式知识主张</h1><p className="mt-2 max-w-4xl text-sm leading-6 text-fg-muted">系统从大规模 HDD SMART 时序中完成现象抽取、预注册、确认检验、多重比较控制、机制对局与跨切片外推。结论是可审计的近端热/健康关联指示，不扩写为尚未建立的因果定律。</p></div>
      <div className="self-start rounded-lg border border-success-500/30 bg-success-50 px-5 py-3 text-center"><span className="block text-[11px] text-success-700">知识等级</span><strong className="mt-1 block text-xl text-success-700">CONFIRMED</strong><span className="mt-1 block text-[10px] text-fg-muted">确认式关联主张</span></div>
    </header>

    <section><div className="mb-3 flex items-end justify-between"><div><h2 className="text-base font-semibold text-fg">知识生产证据链</h2><p className="mt-1 text-xs text-fg-muted">每一步均可回放，并保留未通过环节的边界。</p></div><div className="flex gap-4 text-xs"><span><strong className="text-fg">n=9,262</strong> 确认样本</span><span><strong className="text-success-700">≈0.03</strong> 增量效应</span><span><strong className="text-fg">BH 通过</strong></span></div></div>
      <div className="grid gap-2 lg:grid-cols-6">{STEPS.map(([n,title,detail], index) => <article key={n} className="relative rounded-lg border border-border-subtle bg-surface p-3 shadow-sm"><div className="flex items-center gap-2"><span className="font-mono text-xs font-semibold text-brand-600">{n}</span><h3 className="text-xs font-semibold text-fg">{title}</h3></div><p className="mt-2 text-[11px] leading-5 text-fg-muted">{detail}</p>{index < STEPS.length-1 ? <span className="absolute -right-2 top-1/2 z-10 hidden -translate-y-1/2 text-brand-500 lg:block">›</span> : null}</article>)}</div>
    </section>

    <section className="rounded-lg border border-border-subtle bg-surface p-4"><div className="flex flex-wrap items-end justify-between gap-2"><div><h2 className="text-base font-semibold text-fg">确认集检验 · Confirmatory Test</h2><p className="mt-1 text-xs text-fg-muted">H₀：纳入窗口末 smart_194_normalized 后增量 Δ≤0；H₁：Δ&gt;0 且确认区间排除 0。</p></div><span className="rounded-full bg-success-50 px-3 py-1 text-[11px] font-semibold text-success-700">H₀ rejected · CONFIRMED</span></div><div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">{CONFIRM_STATS.map(([label,value,note])=><article key={label} className="rounded-lg border border-border-subtle bg-surface-muted p-3"><p className="text-[10px] text-fg-subtle">{label}</p><strong className="mt-1 block font-mono text-sm text-fg">{value}</strong><p className="mt-1 text-[10px] text-fg-muted">{note}</p></article>)}</div><div className="mt-3 grid gap-2 md:grid-cols-3"><div className="rounded-md border border-success-500/30 bg-success-50 p-3 text-xs"><strong className="text-success-700">确认轨 · BH</strong><p className="mt-1 text-fg-muted">通过多重比较控制，知识等级进入 CONFIRMED。</p></div><div className="rounded-md border border-warning-500/30 bg-warning-50 p-3 text-xs"><strong className="text-warning-700">发现轨 · e-BH</strong><p className="mt-1 text-fg-muted">未达到更严格发现阈值，不升级为 DISCOVERED。</p></div><div className="rounded-md border border-brand-500/30 bg-brand-50 p-3 text-xs"><strong className="text-brand-700">预注册指纹</strong><p className="mt-1 break-all font-mono text-[9px] text-fg-muted">a1b2c3d4…abcdef123456</p></div></div></section>

    <section className="rounded-lg border border-border-subtle bg-surface p-4"><div className="flex flex-wrap items-end justify-between gap-2"><div><h2 className="text-base font-semibold text-fg">机制辩论赛 · Mechanism Debate</h2><p className="mt-1 text-xs text-fg-muted">完整记录提出、质询、举证、反驳、机制追问与最终判词；模型论点不能覆盖统计裁决。</p></div><div className="flex gap-3 text-[11px] text-fg-muted"><span><strong className="text-fg">16</strong> 场对局</span><span><strong className="text-warning-700">16</strong> 欠功率平局</span><span><strong className="text-fg">0</strong> 机制证书</span></div></div><div className="mt-4 overflow-hidden rounded-lg border border-border-subtle">{DEBATE_ROUNDS.map((item,index)=><article key={item.round} className="grid gap-3 border-t border-border-subtle p-3 first:border-t-0 lg:grid-cols-[92px_155px_1.25fr_1fr_150px]"><div><span className="font-mono text-[10px] text-brand-600">ROUND {index+1}</span><h3 className="mt-1 text-xs font-semibold text-fg">{item.round}</h3></div><p className="text-xs font-semibold text-fg">{item.side}</p><p className="text-xs leading-5 text-fg-muted">{item.point}</p><div className="rounded-md bg-surface-muted p-2 text-[11px] leading-5 text-fg-muted"><span className="font-semibold text-fg">记录：</span>{item.record}</div><div className="self-start rounded-full border border-border-subtle px-2 py-1 text-center text-[10px] font-medium text-fg-muted">{item.result}</div></article>)}</div></section>

    <section className="grid gap-4 xl:grid-cols-[1fr_0.7fr]">
      <div className="rounded-lg border border-border-subtle bg-surface p-4"><h2 className="text-base font-semibold text-fg">机制对局复盘</h2><div className="mt-3 grid gap-3 md:grid-cols-2"><article className="rounded-lg border border-brand-500/25 bg-brand-50 p-3"><h3 className="text-xs font-semibold text-brand-700">生成机制：近端热/健康指示</h3><p className="mt-2 text-[11px] leading-5 text-fg-muted">窗口末值位于预测截止前，能够表示最后可见的器件状态。热应力、冷却余量下降或厂商健康评分变化均可能与临近失效同向。</p></article><article className="rounded-lg border border-warning-500/25 bg-warning-50 p-3"><h3 className="text-xs font-semibold text-warning-700">竞争机制：共同原因与代理变量</h3><p className="mt-2 text-[11px] leading-5 text-fg-muted">负载、盘龄、型号、其他 SMART 和采样缺口可能共同驱动 X 与 Y。当前细切片功率不足，无法判定哪一种机制胜出。</p></article></div><div className="mt-3 rounded-md bg-surface-muted p-3 text-xs leading-5 text-fg-muted"><strong className="text-fg">为何判为平局：</strong>效应可以在总体确认集上稳定排除 0，但分配到固定机制切片后，最小可检效应接近判决阈值。统计裁判因此拒绝签发“机制已建立”证书。</div></div>
      <aside className="rounded-lg border border-border-subtle bg-surface p-4"><h2 className="text-base font-semibold text-fg">统计裁决总表</h2><dl className="mt-3 divide-y divide-border-subtle text-xs">{[
        ['确认集增量','≈ 0.03；CI 不含 0','通过'],['方向冻结','正向（+）','通过'],['确认轨 FDR','BH','通过'],['发现轨 FDR','e-BH','未升级'],['机制对局','16 场；decisive=0','欠功率平局'],['时间外推','符号同向；CI 含 0','待补功率'],['跨数据集','Backblaze 公开季','尚未开庭'],
      ].map(([label,value,status]) => <div key={label} className="grid grid-cols-[92px_1fr_auto] gap-2 py-2.5"><dt className="text-fg-muted">{label}</dt><dd className="font-medium text-fg">{value}</dd><dd className={status === '通过' ? 'text-success-700' : 'text-warning-700'}>{status}</dd></div>)}</dl></aside>
    </section>

    <section className="rounded-lg border border-success-500/30 bg-success-50 px-5 py-4"><h2 className="text-sm font-semibold text-success-700">可对外复述的结论</h2><p className="mt-2 text-sm leading-6 text-fg">窗口末端的 <code className="font-mono font-semibold">smart_194_normalized</code> 对短期 HDD 失效呈现可复现的正向增量信号，并通过确认轨统计控制。当前证据支持将其作为近端热/健康关联指示器；机制对局与跨切片检验明确记录了结论边界，为后续补功率、跨季复验和知识升级提供可执行路径。</p></section>
  </div>;
}
