/**
 * 演示案例：一次可回放的运行。页面只依赖这里的形状，具体案例（KGTE 三岛进化、
 * 论文组合发现新算法……）各自把自己的运行产物整理成 `DemoCase`。
 */
import type { BotShape } from '../bot/shapes';
import type { IconName } from '../ui';
import type { RunReport } from '../report';

export type CaseId = 'paper' | 'kgte';

export interface Transfer {
  from: string;
  to: string;
  label: string;
  success: boolean;
  gain: string;
}

export type DemoStep =
  | { kind: 'propose'; round: number; nodeIds: string[]; injects: Transfer[] }
  | { kind: 'evaluate'; round: number; nodeIds: string[] }
  | { kind: 'result'; round: number; nodeId: string; bestScore: number; isNewBest: boolean }
  | { kind: 'finish'; bestScore: number };

export interface DemoEvent {
  id: string;
  tag: string;
  text: string;
  tone: 'info' | 'good' | 'bad' | 'cloud' | 'inject';
}

/** 云端 / 本地分离演示面板的文案与流向。 */
export interface PipelineConfig {
  cloud: { title: string; host: string; command: (round: number) => string };
  local: { title: string; file: string; note: string };
  boundary: string;
  /** 传送通道上下两端的说明文字。 */
  lanes: { cloud: string; local: string };
  stages: [string, string, string, string, string];
  /** 候选从哪一侧出发：cloud = 云端生成、本地评估；local = 本地冻结协议、服务器运行。 */
  origin: 'cloud' | 'local';
  candidateLabel: (id: string) => string;
  result: (id: string) => { label: string; ok: boolean };
}

export type DebateRole = 'proponent' | 'confounder' | 'statistician' | 'critic' | 'judge';

export interface DebateScript {
  eyebrow: string;
  /** 标题里用 `highlight` 包住的片段会高亮。 */
  title: string;
  highlight?: string;
  rounds: { round: string; speaker: DebateRole; line: string }[];
  cast: Record<DebateRole, { name: string; en: string; shape: BotShape; color: string }>;
  verdict: { label: string; value: string; round: number; good?: boolean }[];
  outcome: { title: string; sub: string };
  /** 证据链；最后若干项可以在辩论结束时仍未点亮（例如尚待独立确认）。 */
  chain: string[];
}

export interface ConfirmConfig {
  checks: { icon: IconName; title: string; value: string; ok: string }[];
  seedNote: string;
  budget: { label: string; min: number; max: number; initial: number; describe: (n: number) => string };
  privacy: string;
  /** 右侧“即将进入”的预览清单；缺省时展示分岛占位动画。 */
  preview?: { title: string; rows: { label: string; sub: string; ok: boolean }[] };
}

export interface DemoCase {
  id: CaseId;
  name: string;
  badge: string;
  seed: string;
  sampleTask: string;
  evaluation: string;
  confirm: ConfirmConfig;
  steps: DemoStep[];
  transfers: Transfer[];
  describeStep: (step: DemoStep, index: number) => DemoEvent | null;
  pipeline: PipelineConfig;
  debate: DebateScript;
  report: RunReport;
}
