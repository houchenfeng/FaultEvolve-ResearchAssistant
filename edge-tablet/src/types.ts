export interface ReplayDisk {
  sn: string;
  model: string;
  cap: number;
  rack: number;
  slot: number;
  fail_day: number | null;
  days: (Array<number | null> | null)[];
}

export interface Replay {
  version: number;
  seed: number;
  source: string;
  history_days: number;
  horizon_days: number;
  racks: number;
  slots_per_rack: number;
  start_date: string;
  columns: string[];
  disks: ReplayDisk[];
}

export type DiskState = 'ok' | 'alarm-before' | 'alarm-after' | 'alarm-both' | 'failed';

export type Phase = 'ready' | 'ingest' | 'scoring' | 'observe' | 'done' | 'evolve';

export interface AlarmSet {
  before: Set<string>;
  after: Set<string>;
}
