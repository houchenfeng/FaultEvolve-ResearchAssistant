import './style.css';

import { Hud, type Outcome } from './hud';
import { Uplink, type LinkMessage } from './link';
import { DataHall } from './scene';
import type { AlarmSet, Phase, Replay } from './types';

const BASE_DAY_MS = 1500;
const SCORING_TIMEOUT_MS = 45_000;

async function boot(): Promise<void> {
  const replay = (await fetch('./replay.json').then((r) => r.json())) as Replay;
  const totalDays = replay.history_days + replay.horizon_days;
  const hall = new DataHall(document.getElementById('scene') as HTMLCanvasElement, replay.disks);
  const hud = new Hud(document.getElementById('hud') as HTMLElement, totalDays, replay.history_days);
  const start = new Date(`${replay.start_date}T00:00:00`);

  let day = 0;
  let phase: Phase = 'ready';
  let running = false;
  let speed = 1;
  let timer: number | null = null;
  let scoringTimer: number | null = null;
  let alarms: AlarmSet | null = null;
  const failed = new Set<string>();

  const dateOf = (d: number) => {
    const x = new Date(start);
    x.setDate(x.getDate() + Math.max(d - 1, 0));
    return `${x.getMonth() + 1}月${x.getDate()}日`;
  };

  const refresh = () => {
    const shown = Math.min(day, totalDays);
    hud.setClock(shown, phase, dateOf(shown));
    hud.setStats(replay.disks.length - failed.size, failed.size, alarms ? alarms.after.size : null, alarms ? alarms.before.size : null);
    hud.setRunning(running, phase === 'done');
  };

  const link = new Uplink(onMessage, (status) => {
    hud.setLink(status, link.endpoint, link.lastRttMs);
    if (status !== 'online') return;
    hud.log('link', '已连接笔记本本地评估域');
    if (day > 0 && phase !== 'done') resync();
  });

  function telemetry(d: number): { type: 'telemetry'; day: number; rows: Array<[string, (number | null)[]]> } {
    const rows = replay.disks
      .filter((x) => x.days[d - 1] !== null)
      .map((x) => [x.sn, x.days[d - 1]] as [string, (number | null)[]]);
    return { type: 'telemetry', day: d, rows };
  }

  /** (Re)connected mid-run: the laptop needs the inventory and every day sent so far. */
  function resync(): void {
    sendHello();
    const upto = Math.min(day, replay.history_days);
    for (let d = 1; d <= upto; d += 1) link.send(telemetry(d));
    for (const sn of failed) {
      const x = replay.disks[hall.diskIndex(sn)];
      link.send({ type: 'failure', day: x.fail_day, sn });
    }
    if (upto > 0) hud.log('link', `断线补传：第 1–${upto} 天 SMART 窗口已重新送达笔记本`);
    if (upto === replay.history_days && alarms === null) {
      phase = 'scoring';
      refresh();
    }
  }
  hud.setLink('offline', link.endpoint, null);
  link.connect();

  function sendHello(): void {
    link.send({
      type: 'hello',
      device: 'Android 平板 · 机房孪生',
      columns: replay.columns,
      history_days: replay.history_days,
      horizon_days: replay.horizon_days,
      start_date: replay.start_date,
      disks: replay.disks.map(({ sn, model, cap, rack, slot }) => ({ sn, model, cap, rack, slot })),
    });
  }

  function onMessage(msg: LinkMessage): void {
    hud.setLink(link.status, link.endpoint, link.lastRttMs);
    if (msg.type === 'welcome') {
      hud.log('link', `本地评估域确认接入：${msg.disks} 块盘，模型状态 ${msg.models}`);
    } else if (msg.type === 'need_hello') {
      resync();
    } else if (msg.type === 'alarms') {
      applyAlarms(msg.before as string[], msg.after as string[], Number(msg.elapsed_s ?? 0));
    }
  }

  function applyAlarms(before: string[], after: string[], elapsed: number): void {
    if (scoringTimer !== null) window.clearTimeout(scoringTimer);
    scoringTimer = null;
    alarms = { before: new Set(before), after: new Set(after) };
    const all = new Set([...before, ...after]);
    for (const sn of all) {
      const i = hall.diskIndex(sn);
      const inA = alarms.after.has(sn);
      const inB = alarms.before.has(sn);
      hall.setState(i, inA && inB ? 'alarm-both' : inA ? 'alarm-after' : 'alarm-before');
    }
    hall.downlink(after.map((sn) => hall.diskIndex(sn)).filter((i) => i >= 0), 'after');
    hall.downlink(before.filter((sn) => !alarms!.after.has(sn)).map((sn) => hall.diskIndex(sn)).filter((i) => i >= 0), 'before');
    hud.log('eval', `笔记本完成打分（${elapsed.toFixed(1)}s）：进化后预警 ${after.length} 块，进化前预警 ${before.length} 块`);
    phase = 'observe';
    refresh();
    schedule();
  }

  function schedule(): void {
    if (timer !== null) window.clearTimeout(timer);
    timer = running ? window.setTimeout(tick, BASE_DAY_MS / speed) : null;
  }

  function tick(): void {
    timer = null;
    if (!running || phase === 'scoring') return;
    day += 1;
    if (day <= replay.history_days) {
      phase = 'ingest';
      const msg = telemetry(day);
      const rows = msg.rows;
      const sentBytes = link.send(msg);
      const bytes = sentBytes || new Blob([JSON.stringify(msg)]).size;
      hall.uplink(14);
      hud.pushUplink(bytes, link.sentFrames, link.sentBytes, sentBytes > 0);
      if (day === 1 || day % 4 === 0) hud.log('data', `第 ${day} 天 SMART 快照 ${rows.length} 条 → 笔记本（${(bytes / 1024).toFixed(0)} KB）`);
      if (day === replay.history_days) {
        if (link.status === 'online') {
          phase = 'scoring';
          hud.log('eval', '窗口完整，等待笔记本本地评估器打分…');
          scoringTimer = window.setTimeout(() => {
            hud.log('alarm', '评估超时，继续观察（无预警）');
            alarms = { before: new Set(), after: new Set() };
            phase = 'observe';
            refresh();
            schedule();
          }, SCORING_TIMEOUT_MS);
          refresh();
          return;
        }
        hud.log('alarm', '未连接笔记本：本次回放没有算法预警');
      }
    } else if (day <= totalDays) {
      phase = 'observe';
      for (const d of replay.disks) {
        if (d.fail_day !== day) continue;
        failed.add(d.sn);
        const i = hall.diskIndex(d.sn);
        hall.fail(i);
        link.send({ type: 'failure', day, sn: d.sn });
        const hitA = alarms ? alarms.after.has(d.sn) : null;
        const hitB = alarms ? alarms.before.has(d.sn) : null;
        hud.showDisk(d, replay.columns, `⚠ 硬盘故障 · 第 ${day} 天`, [['进化后算法', hitA], ['进化前算法', hitB]], true);
        const lead = day - replay.history_days;
        hud.log('failure', `${d.sn} 故障 · ${hitA ? `进化后已提前 ${lead} 天预警` : '进化后未预警'}${hitB ? ' · 进化前也已预警' : ''}`);
      }
    } else {
      phase = 'done';
      running = false;
      link.send({ type: 'end' });
      hud.showSummary(computeOutcome(), link.status === 'online');
      hall.overview();
    }
    refresh();
    schedule();
  }

  function computeOutcome(): Outcome {
    const count = (set: Set<string>) => {
      let caught = 0;
      for (const sn of failed) if (set.has(sn)) caught += 1;
      return { caught, alarms: set.size, falseAlarms: set.size - caught };
    };
    const empty = new Set<string>();
    return { failures: failed.size, before: count(alarms?.before ?? empty), after: count(alarms?.after ?? empty) };
  }

  function reset(): void {
    running = false;
    if (timer !== null) window.clearTimeout(timer);
    if (scoringTimer !== null) window.clearTimeout(scoringTimer);
    timer = scoringTimer = null;
    day = 0;
    phase = 'ready';
    alarms = null;
    failed.clear();
    hall.resetAll();
    hud.hideDisk();
    hud.hideSummary();
    refresh();
  }

  hud.onStart = () => {
    if (phase === 'done') reset();
    if (running) return;
    if (day === 0) {
      sendHello();
      hud.log('link', link.status === 'online' ? '握手：发送机房清单与 SMART 字段定义' : '离线回放（未连接笔记本）');
    }
    running = true;
    refresh();
    schedule();
  };
  hud.onPause = () => {
    running = false;
    schedule();
    refresh();
  };
  hud.onReset = reset;
  hud.onSpeed = (s) => {
    speed = s;
    schedule();
  };
  hud.onEndpoint = (value) => link.setEndpoint(value);

  hall.onPick = (i) => {
    const d = replay.disks[i];
    const hitA = alarms ? alarms.after.has(d.sn) : null;
    const hitB = alarms ? alarms.before.has(d.sn) : null;
    hud.showDisk(d, replay.columns, failed.has(d.sn) ? '已故障硬盘' : '硬盘详情', [['进化后算法', hitA], ['进化前算法', hitB]], failed.has(d.sn));
  };

  refresh();
  if (new URLSearchParams(location.search).get('autostart') === '1') {
    const startedAt = performance.now();
    const waitForLink = () => {
      if (link.status === 'online' || performance.now() - startedAt > 8000) hud.onStart();
      else window.setTimeout(waitForLink, 250);
    };
    window.setTimeout(waitForLink, 800);
  }
}

void boot();
