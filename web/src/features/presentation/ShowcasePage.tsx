import { useState } from 'react';
import { Link } from '@tanstack/react-router';
import evidence from './evidence.json';
import './showcase.css';

const metrics = {
  combined_score: { label: '综合得分 ROS', digits: 2, suffix: '', factor: 1, lower: false },
  f1: { label: 'F1', digits: 2, suffix: '%', factor: 100, lower: false },
  auprc: { label: 'AUPRC', digits: 2, suffix: '%', factor: 100, lower: false },
  run_time_s: { label: '运行耗时', digits: 2, suffix: ' s', factor: 1, lower: true },
} as const;
type Metric = keyof typeof metrics;
const strategies = [
  { name: '性能探索岛', tag: 'PERFORMANCE', color: '#65d7ff', focus: '寻找更强的预测方案', text: '侧重综合指标，探索特征改进与模型结构。每个候选都由本地评估器验证。', operators: '默认算子偏置：refine · inject' },
  { name: '误漏报优化岛', tag: 'RELIABILITY', color: '#b1a1ff', focus: '把错例变成下一轮假设', text: '依据假阴性分组与错误画像，权衡召回与精确率，注入可检验的领域知识。', operators: '默认算子偏置：recall_focus · threshold_calibrate' },
  { name: '效率与稳健岛', tag: 'EFFICIENCY', color: '#fbb96c', focus: '关注运行代价与稳定性', text: '围绕特征精简、轻量模型与缺失值稳健性展开搜索，保留独立预算与局部最优，避免一个方向占满探索空间。', operators: '默认算子偏置：refine · inject' },
];
const steps = [
  { title: '生成假设', text: '结合父方案、领域知识与错误画像，提出可执行的候选算法。' },
  { title: '本地验证', text: '候选在数据所在环境执行；真实指标由固定评估器返回。' },
  { title: '交换经验', text: '分享方法、适用条件与失败经验；接收岛独立决定是否采纳。' },
  { title: '继续演化', text: '更新搜索树与知识信誉，保存状态；达到预算或停止条件后生成报告。' },
];

function StrategyMap({ selected, stage }: { selected: number; stage: number }) {
  return <svg viewBox="0 0 640 240" role="img" aria-label="三岛轮转与摘要交换机制示意，非真实运行轨迹" className="sc-map">
    <defs><pattern id="sc-grid" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r=".7" fill="#ffffff" opacity=".1" /></pattern></defs>
    <rect width="640" height="240" fill="url(#sc-grid)" />
    {strategies.map((island, row) => {
      const y = 48 + row * 72;
      return <g key={island.tag} opacity={row === selected ? 1 : .38}>
        <text x="18" y={y + 4} fill={island.color} fontSize="11" fontFamily="monospace">0{row + 1}</text>
        <path d={`M 70 ${y} H 185 L 290 ${y - 18} L 405 ${y} H 568 M 185 ${y} L 290 ${y + 18} L 405 ${y}`} fill="none" stroke={island.color} strokeWidth="1.5" />
        {[70, 185, 405, 568].map((x, i) => <g key={x}>
          {i === stage && row === selected && <circle cx={x} cy={y} r="16" fill={island.color} opacity=".13" className="sc-pulse" />}
          <circle cx={x} cy={y} r={i === stage ? 7 : 4} fill={i <= stage ? island.color : '#172638'} stroke={island.color} strokeWidth="1.5" />
        </g>)}
        <circle cx="290" cy={y - 18} r="4" fill={island.color} />
        <circle cx="290" cy={y + 18} r="4" fill="#172638" stroke={island.color} />
      </g>;
    })}
    <path d="M 405 48 C 468 48 342 120 405 120 S 468 192 405 192" fill="none" stroke="#a5b7cc" strokeDasharray="4 5" opacity={stage === 2 ? 1 : .25} />
    <text x="70" y="232" fill="#8da3ba" fontSize="10">独立搜索树</text>
    <text x="390" y="232" fill="#8da3ba" fontSize="10">摘要交换 · 独立采纳</text>
  </svg>;
}

export function ShowcasePage() {
  const [metric, setMetric] = useState<Metric>('combined_score');
  const [island, setIsland] = useState(0);
  const [stage, setStage] = useState(0);
  const [tab, setTab] = useState<'results' | 'mechanism'>('results');
  const [fullscreenError, setFullscreenError] = useState('');
  const best = evidence.models.find(model => model.id === 'hybrid')!;
  const old = evidence.models.find(model => model.id === 'preliminary')!;
  const gain = best.metrics.combined_score - old.metrics.combined_score;
  const spec = metrics[metric];
  const max = Math.max(...evidence.models.map(model => model.metrics[metric]));
  const active = strategies[island]!;
  const fullscreen = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
      setFullscreenError('');
    } catch { setFullscreenError('浏览器未允许全屏，可按 F11 进入展示。'); }
  };

  return <main className="sc-page">
    <div className="sc-shell">
      <header className="sc-header">
        <Link to="/" className="sc-brand" aria-label="FaultEvolve 返回任务中心"><span className="sc-logo">F<span>↗</span></span><span>FaultEvolve<small>自演化故障预测智能体</small></span></Link>
        <div className="sc-header-right"><span className="sc-edition">天猫黑客松 · 进阶展示</span><button onClick={() => void fullscreen()} className="sc-quiet">全屏展示 ↗</button><Link to="/" className="sc-quiet">进入工作台 →</Link></div>
      </header>
      {fullscreenError && <p role="status">{fullscreenError}</p>}
      <section className="sc-hero">
        <div>
          <div className="sc-eyebrow"><span className="sc-dot" /> KNOWLEDGE → EVOLUTION → EVIDENCE</div>
          <h1>让每一次尝试，<br />成为下一次<span>进化的起点。</span></h1>
          <p className="sc-intro">从器件数据到候选算法，从本地评估到知识沉淀。<br />三岛协作，让故障预测的改进过程看得见、查得到。</p>
          <div className="sc-actions"><button className="sc-primary" onClick={() => { setTab('mechanism'); document.getElementById('sc-explore')?.scrollIntoView({ behavior: 'smooth' }); }}>探索演化机制 <span>↗</span></button><a className="sc-secondary" href="/evidence/hdd-results.json" download>下载实验摘要 ↓</a></div>
          <p className="sc-caption">归档实验展示 · 无需模型密钥 · 评分来自本地评估器</p>
        </div>
        <div className="sc-score-card">
          <div className="sc-card-top"><span>HDD / 最佳验证集结果</span><span className="sc-tag">VAL · ROS</span></div>
          <div className="sc-score">{best.metrics.combined_score.toFixed(2)}<span>ROS</span></div>
          <div className="sc-gain">↗ +{gain.toFixed(2)} <span>较初赛历史最佳 · +{(gain / old.metrics.combined_score * 100).toFixed(1)}%</span></div>
          <div className="sc-score-divider" />
          <div className="sc-score-details"><div><span>最佳方案</span><strong>TCN + 树模型融合</strong></div><div><span>归档候选</span><strong>{evidence.trials} 个</strong></div></div>
          <p className="sc-boundary">验证集参与搜索，尚未独立复验。<br />性能增益伴随运行代价，查看下方完整对照。</p>
        </div>
      </section>

      <section id="sc-explore" className="sc-explore">
        <div className="sc-section-head"><div><span className="sc-kicker">01 / EXPLORE</span><h2>从结果，走进演化过程</h2></div><div className="sc-tabs" role="tablist" aria-label="展示内容"><button role="tab" aria-selected={tab === 'results'} aria-controls="sc-results" id="sc-results-tab" onClick={() => setTab('results')}>实验对照</button><button role="tab" aria-selected={tab === 'mechanism'} aria-controls="sc-mechanism" id="sc-mechanism-tab" onClick={() => setTab('mechanism')}>三岛协作</button></div></div>
        {tab === 'results' ? <div id="sc-results" role="tabpanel" aria-labelledby="sc-results-tab" className="sc-results">
          <div className="sc-chart-panel"><div className="sc-chart-heading"><h3>同一 HDD 评估口径</h3><span>{spec.lower ? '越低越好' : '越高越好'}</span></div><div className="sc-metrics" role="group" aria-label="选择对比指标">{(Object.keys(metrics) as Metric[]).map(key => <button key={key} aria-pressed={key === metric} onClick={() => setMetric(key)}>{metrics[key].label}</button>)}</div>
            <div className="sc-bars" aria-live="polite">{evidence.models.map(model => <div key={model.id} className={`sc-bar-row ${model.id === 'hybrid' ? 'sc-highlight' : ''}`}><div className="sc-bar-label"><span>{model.label}</span><small>{model.phase}</small></div><div className="sc-bar-track"><div className="sc-bar-fill" style={{ width: `${model.metrics[metric] / max * 100}%` }} /></div><strong>{(model.metrics[metric] * spec.factor).toFixed(spec.digits)}{spec.suffix}</strong></div>)}</div>
            <p className="sc-chart-note">{metric === 'run_time_s' ? '最佳混合方案耗时更长；三岛 ML 方案保留了更轻量的选择。耗时为归档环境记录。' : '这里对照不同阶段的方案，不是一次运行的逐轮曲线，也不是三岛机制的消融实验。'}</p>
          </div>
          <aside className="sc-result-note"><span className="sc-kicker">THE NEXT STEP</span><h3>更好的预测，<br />更完整的证据。</h3><p>融合时序趋势与树模型能力，同时记录召回、精确率和运行代价。</p><dl><div><dt>Precision</dt><dd>{(best.metrics.precision * 100).toFixed(2)}%</dd></div><div><dt>Recall</dt><dd>{(best.metrics.recall * 100).toFixed(2)}%</dd></div><div><dt>误告率</dt><dd>{(best.metrics.false_alarm_rate * 100).toFixed(3)}%</dd></div></dl><a href="/evidence/hdd-results.json" target="_blank" rel="noreferrer">查看机读证据 ↗</a></aside>
        </div> : <div id="sc-mechanism" role="tabpanel" aria-labelledby="sc-mechanism-tab" className="sc-mechanism">
          <div className="sc-strategies">{strategies.map((item, index) => <button key={item.tag} aria-pressed={island === index} onClick={() => setIsland(index)} style={{ '--island-color': item.color } as React.CSSProperties}><span className="sc-strategy-number">0{index + 1}</span><span><small>{item.tag}</small><strong>{item.name}</strong></span><span>↗</span></button>)}</div>
          <div className="sc-map-panel"><div className="sc-chart-heading"><h3 style={{ color: active.color }}>{active.focus}</h3><span>机制示意 · 非运行轨迹</span></div><StrategyMap selected={island} stage={stage} /><p className="sc-strategy-text">{active.text}</p><code>{active.operators}</code></div>
          <div className="sc-step-panel"><span className="sc-kicker">ROUND-ROBIN / 轮转调度</span><div className="sc-steps">{steps.map((step, index) => <button key={step.title} aria-pressed={stage === index} onClick={() => setStage(index)}><span>0{index + 1}</span>{step.title}</button>)}</div><p aria-live="polite">{steps[stage]!.text}</p><small>每岛维护独立状态；共享策略摘要，接收方自行生成并验证候选。</small></div>
        </div>}
      </section>

      <section className="sc-bottom"><div><span className="sc-kicker">02 / ONE WORKFLOW</span><h2>一套流程，连接不同器件</h2><p>通过数据契约归一化设备、时间、特征和事件，复用演化与评估流程。</p><div className="sc-formats">{['CSV / TSV', 'Parquet / Feather', 'Excel', 'JSON / 日志'].map(label => <span key={label}>{label}</span>)}</div></div><div className="sc-device-list"><article><span>01</span><div><strong>硬盘 HDD</strong><p>验证集搜索 · 有完整指标与候选证据</p></div><span className="sc-device-tag">实验验证</span></article><article><span>02</span><div><strong>内存 SmartMem</strong><p>独立赛事口径 · 不与 HDD 分数横比</p></div><span className="sc-device-tag">任务适配</span></article><article><span>03</span><div><strong>光网络器件</strong><p>公开数据接入冒烟 · 非榜单成绩</p></div><span className="sc-device-tag">链路验证</span></article></div></section>
      <footer className="sc-footer"><span>FaultEvolve <span className="sc-muted">/ 每一个分数，都有出处。</span></span><div><Link to="/">任务与真实运行 →</Link><Link to="/runs/$runId" params={{ runId: 'hdd_mvp_showcase_c89e2a01' }}>初赛历史案例回放 →</Link></div></footer>
      <p className="sc-source">证据：{evidence.source}/summary.json · 历史案例回放需启动展示后端。</p>
    </div>
  </main>;
}
