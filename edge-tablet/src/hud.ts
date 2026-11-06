import type { LinkStatus } from './link';
import type { Phase, ReplayDisk } from './types';

const PHASE_TEXT: Record<Phase, string> = {
  ready: '待命 · 点击开始回放',
  ingest: '采集 SMART 窗口 · 上报本地评估域',
  scoring: '笔记本本地评估中（进化前 vs 进化后）',
  observe: '观察期 · 等待真实故障发生',
  done: '回放结束',
  evolve: '混合云进化 · 每个候选都在本机评估',
};

const LOG_COLORS: Record<string, string> = {
  link: '#22d3ee',
  data: '#4cc9ff',
  eval: '#a78bfa',
  alarm: '#ffa62b',
  failure: '#ff3b4e',
  ok: '#19f58c',
};

export interface Outcome {
  failures: number;
  before: { caught: number; alarms: number; falseAlarms: number };
  after: { caught: number; alarms: number; falseAlarms: number };
}

function el<T extends HTMLElement>(root: ParentNode, sel: string): T {
  return root.querySelector(sel) as T;
}

export class Hud {
  onStart: () => void = () => {};
  onPause: () => void = () => {};
  onReset: () => void = () => {};
  onSpeed: (speed: number) => void = () => {};
  onEndpoint: (value: string) => void = () => {};

  private root: HTMLElement;
  private bars: number[] = [];
  private startedAt = performance.now();

  constructor(root: HTMLElement, private readonly totalDays: number, private readonly historyDays: number) {
    this.root = root;
    root.innerHTML = `
      <div class="panel brand"><div class="logo">FE</div><div><h1>FaultEvolve · 数据中心孪生</h1><p>边缘数据源 · 存储机房 R01–R10 · 300 块 HDD</p></div></div>
      <div class="panel clock">
        <div class="day num" data-day>第 0 天 <small>/ ${totalDays}</small></div>
        <div class="phase ready" data-phase>${PHASE_TEXT.ready}</div>
        <div class="timeline"><div class="hist"></div><div class="fill" data-fill style="width:0%"></div></div>
        <div class="timeline-labels"><span>SMART 窗口 ${historyDays} 天</span><span>截止日</span><span>故障观察 ${totalDays - historyDays} 天</span></div>
        <div data-cand style="display:none;margin-top:8px;padding:8px 10px;border-radius:10px;border:1px solid rgba(34,211,238,.45);background:rgba(34,211,238,.1)">
          <div class="k" data-cand-title>云端候选</div>
          <div class="num" data-cand-body style="font-size:15px;margin-top:2px"></div>
        </div>
      </div>
      <div class="panel link">
        <div class="row"><span class="dot" data-dot></span><b data-linktext>未连接本地评估域</b><span style="flex:1"></span><button data-settings style="background:none;border:1px solid var(--line);color:var(--fg);border-radius:8px;padding:4px 8px">设置</button></div>
        <div class="ep num" data-ep>—</div>
        <div class="boundary">⛨ 局域网直连笔记本 · 原始遥测不出机房</div>
      </div>
      <div class="panel stats">
        <div class="k">机房概况</div>
        <div class="grid">
          <div><div class="k">在线盘位</div><div class="v num green" data-online>300</div></div>
          <div><div class="k">已故障</div><div class="v num red" data-failed>0</div></div>
          <div><div class="k">进化后预警</div><div class="v num cyan" data-after>—</div></div>
          <div><div class="k">进化前预警</div><div class="v num amber" data-before>—</div></div>
        </div>
        <div class="legend">
          <span style="--c:#19f58c">正常 · 读写指示</span>
          <span style="--c:#22d3ee">进化后算法预警</span>
          <span style="--c:#ffa62b">仅进化前算法预警</span>
          <span style="--c:#ff3b4e">真实故障（抽出 + 告警）</span>
        </div>
      </div>
      <div class="panel uplink">
        <div class="k">上行遥测 → 笔记本本地评估域</div>
        <canvas data-chart width="660" height="128"></canvas>
        <div class="totals num"><span data-frames>0 帧</span><span data-bytes>0 KB</span><span data-rtt>RTT —</span></div>
      </div>
      <div class="panel log"><div class="k">事件</div><ul data-log></ul></div>
      <div class="panel controls">
        <button class="primary" data-start>▶ 开始回放</button>
        <button data-pause>⏸ 暂停</button>
        <button data-reset>↺ 重置</button>
        <span class="sep"></span>
        <button data-speed="0.5">0.5×</button><button data-speed="1" class="active">1×</button><button data-speed="2">2×</button>
      </div>
      <div data-cardslot></div>
      <div data-overlay></div>
    `;
    el<HTMLButtonElement>(root, '[data-start]').onclick = () => this.onStart();
    el<HTMLButtonElement>(root, '[data-pause]').onclick = () => this.onPause();
    el<HTMLButtonElement>(root, '[data-reset]').onclick = () => this.onReset();
    el<HTMLButtonElement>(root, '[data-settings]').onclick = () => this.openSettings();
    root.querySelectorAll<HTMLButtonElement>('[data-speed]').forEach((b) => {
      b.onclick = () => {
        root.querySelectorAll('[data-speed]').forEach((x) => x.classList.remove('active'));
        b.classList.add('active');
        this.onSpeed(Number(b.dataset.speed));
      };
    });
    this.drawChart();
  }

  setRunning(running: boolean, done: boolean): void {
    el<HTMLButtonElement>(this.root, '[data-start]').textContent = done ? '↻ 再来一次' : running ? '● 回放中' : '▶ 开始回放';
  }

  setLink(status: LinkStatus, endpoint: string, rtt: number | null): void {
    el(this.root, '[data-dot]').className = `dot ${status}`;
    el(this.root, '[data-linktext]').textContent =
      status === 'online' ? '已接入本地评估域' : status === 'connecting' ? '正在连接笔记本…' : '未连接（离线回放）';
    el(this.root, '[data-ep]').textContent = endpoint || '点「设置」填写笔记本地址，如 192.168.1.20:8011';
    el(this.root, '[data-rtt]').textContent = rtt !== null ? `RTT ${rtt.toFixed(0)} ms` : 'RTT —';
  }

  setClock(day: number, phase: Phase, date: string): void {
    el(this.root, '[data-day]').innerHTML = `第 ${day} 天 <small>/ ${this.totalDays} · ${date}</small>`;
    const p = el(this.root, '[data-phase]');
    p.className = `phase ${phase}`;
    p.textContent = PHASE_TEXT[phase];
    el(this.root, '[data-fill]').style.width = `${(Math.min(day, this.totalDays) / this.totalDays) * 100}%`;
  }

  /** Hybrid evolution: which cloud candidate this hall is currently serving. */
  setCandidate(title: string | null, body = ''): void {
    const box = el(this.root, '[data-cand]');
    box.style.display = title ? 'block' : 'none';
    if (!title) return;
    el(this.root, '[data-cand-title]').textContent = title;
    el(this.root, '[data-cand-body]').textContent = body;
  }

  setStats(online: number, failed: number, after: number | null, before: number | null): void {
    el(this.root, '[data-online]').textContent = String(online);
    el(this.root, '[data-failed]').textContent = String(failed);
    el(this.root, '[data-after]').textContent = after === null ? '—' : String(after);
    el(this.root, '[data-before]').textContent = before === null ? '—' : String(before);
  }

  pushUplink(bytes: number, frames: number, totalBytes: number, sent: boolean): void {
    this.bars.push(sent ? bytes : -bytes);
    if (this.bars.length > 28) this.bars.shift();
    el(this.root, '[data-frames]').textContent = `${frames} 帧`;
    el(this.root, '[data-bytes]').textContent = `${(totalBytes / 1024).toFixed(1)} KB 已上报`;
    this.drawChart();
  }

  private drawChart(): void {
    const canvas = el<HTMLCanvasElement>(this.root, '[data-chart]');
    const g = canvas.getContext('2d')!;
    g.clearRect(0, 0, canvas.width, canvas.height);
    g.strokeStyle = 'rgba(95,180,255,0.12)';
    for (let y = 0; y <= 4; y += 1) {
      g.beginPath();
      g.moveTo(0, (y * canvas.height) / 4);
      g.lineTo(canvas.width, (y * canvas.height) / 4);
      g.stroke();
    }
    const max = Math.max(1, ...this.bars.map(Math.abs));
    const w = canvas.width / 28;
    this.bars.forEach((b, i) => {
      const h = (Math.abs(b) / max) * (canvas.height - 10);
      const grad = g.createLinearGradient(0, canvas.height - h, 0, canvas.height);
      grad.addColorStop(0, b >= 0 ? '#22d3ee' : '#64748b');
      grad.addColorStop(1, b >= 0 ? 'rgba(59,130,246,0.25)' : 'rgba(100,116,139,0.2)');
      g.fillStyle = grad;
      g.fillRect(i * w + 3, canvas.height - h, w - 6, h);
    });
  }

  log(kind: string, text: string): void {
    const ul = el<HTMLUListElement>(this.root, '[data-log]');
    const li = document.createElement('li');
    li.style.setProperty('--c', LOG_COLORS[kind] ?? '#22d3ee');
    const secs = ((performance.now() - this.startedAt) / 1000).toFixed(0).padStart(3, '0');
    li.innerHTML = `<time class="num">T+${secs}s</time>${text}`;
    ul.prepend(li);
    while (ul.children.length > 9) ul.lastElementChild?.remove();
  }

  showDisk(disk: ReplayDisk, columns: string[], title: string, verdicts: Array<[string, boolean | null]>, failed: boolean): void {
    const slot = el(this.root, '[data-cardslot]');
    const verdictHtml = verdicts
      .map(([name, hit]) => `<div class="verdict"><span>${name}</span><b class="${hit ? 'hit' : 'miss'}">${hit === null ? '尚未评估' : hit ? '✔ 已提前预警' : '✘ 未预警'}</b></div>`)
      .join('');
    slot.innerHTML = `
      <div class="card ${failed ? '' : 'info'}">
        <button class="close" data-close>×</button>
        <h3>${title}</h3>
        <div class="sn num">${disk.sn} · ${disk.model} · R${String(disk.rack + 1).padStart(2, '0')}-${String(disk.slot + 1).padStart(2, '0')}</div>
        <div class="verdicts">${verdictHtml}</div>
        <canvas width="680" height="180" data-spark></canvas>
        <div class="k" style="margin-top:4px">14 天 SMART：5 重映射扇区 · 187 不可纠正 · 197 待映射 · 198 离线不可纠正</div>
      </div>`;
    el<HTMLButtonElement>(slot, '[data-close]').onclick = () => (slot.innerHTML = '');
    this.spark(el<HTMLCanvasElement>(slot, '[data-spark]'), disk, columns);
  }

  hideDisk(): void {
    el(this.root, '[data-cardslot]').innerHTML = '';
  }

  private spark(canvas: HTMLCanvasElement, disk: ReplayDisk, columns: string[]): void {
    const g = canvas.getContext('2d')!;
    const series: Array<[string, string]> = [
      ['smart_5_raw', '#ff3b4e'],
      ['smart_187_raw', '#ffa62b'],
      ['smart_197_raw', '#22d3ee'],
      ['smart_198_raw', '#a78bfa'],
    ];
    g.clearRect(0, 0, canvas.width, canvas.height);
    const n = disk.days.length;
    series.forEach(([col, color]) => {
      const ci = columns.indexOf(col);
      if (ci < 0) return;
      const vals = disk.days.map((d) => (d && d[ci] !== null ? Math.log1p(Math.max(0, d[ci] as number)) : null));
      const max = Math.max(1, ...vals.map((v) => v ?? 0));
      g.strokeStyle = color;
      g.lineWidth = 3;
      g.shadowColor = color;
      g.shadowBlur = 8;
      g.beginPath();
      let started = false;
      vals.forEach((v, i) => {
        if (v === null) return;
        const x = 10 + (i / (n - 1)) * (canvas.width - 20);
        const y = canvas.height - 12 - (v / max) * (canvas.height - 30);
        if (!started) g.moveTo(x, y);
        else g.lineTo(x, y);
        started = true;
      });
      g.stroke();
    });
    g.shadowBlur = 0;
  }

  showSummary(outcome: Outcome, online: boolean): void {
    const slot = el(this.root, '[data-overlay]');
    const pct = (x: number) => (outcome.failures ? Math.round((100 * x) / outcome.failures) : 0);
    slot.innerHTML = `
      <div class="summary">
        <h2>回放结束 · ${outcome.failures} 块盘在观察期内真实故障</h2>
        <div class="muted" style="font-size:13px">预警由笔记本本地评估域在截止日（第 ${this.historyDays} 天）给出；遥测与标签全程留在本地，仅聚合统计回传云端。</div>
        <div class="cols">
          <div class="col"><div class="k">进化前 · init.py（逻辑回归）</div><div class="big num" style="color:var(--amber)">${outcome.before.caught}<small style="font-size:18px">/${outcome.failures}</small></div><div class="muted">提前预警命中 ${pct(outcome.before.caught)}% · 误报 ${outcome.before.falseAlarms}</div></div>
          <div class="col after"><div class="k">进化后 · 云端进化最佳候选</div><div class="big num" style="color:var(--cyan)">${outcome.after.caught}<small style="font-size:18px">/${outcome.failures}</small></div><div class="muted">提前预警命中 ${pct(outcome.after.caught)}% · 误报 ${outcome.after.falseAlarms}</div></div>
        </div>
        <div class="foot">${online ? '本地评估域已收到完整回放；完整验证集上的 ROS 与 GPU 显著性检验见笔记本「本地-云端混合」面板。' : '本次为离线回放，未连接笔记本。'}　<button data-dismiss style="margin-left:8px;padding:6px 12px;border-radius:8px;border:1px solid var(--line);background:rgba(34,211,238,.12);color:var(--fg)">关闭</button></div>
      </div>`;
    el<HTMLButtonElement>(slot, '[data-dismiss]').onclick = () => (slot.innerHTML = '');
  }

  hideSummary(): void {
    el(this.root, '[data-overlay]').innerHTML = '';
  }

  private openSettings(): void {
    const slot = el(this.root, '[data-overlay]');
    const current = el(this.root, '[data-ep]').textContent ?? '';
    slot.innerHTML = `
      <div class="settings"><div class="box">
        <b>笔记本本地评估域地址</b>
        <div class="muted" style="font-size:12px;margin-top:4px">与平板处于同一局域网。可填 IP:端口，例如 192.168.1.20:8011</div>
        <input data-input value="${current.startsWith('ws') ? current : ''}" placeholder="192.168.1.20:8011" />
        <div class="actions"><button data-cancel>取消</button><button data-save>连接</button></div>
      </div></div>`;
    el<HTMLButtonElement>(slot, '[data-cancel]').onclick = () => (slot.innerHTML = '');
    el<HTMLButtonElement>(slot, '[data-save]').onclick = () => {
      this.onEndpoint(el<HTMLInputElement>(slot, '[data-input]').value);
      slot.innerHTML = '';
    };
  }
}
