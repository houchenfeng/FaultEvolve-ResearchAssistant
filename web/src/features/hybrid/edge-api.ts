/**
 * 混合模式（本地评估域）接口。`/api/edge/*` 不在 OpenAPI 契约快照里，
 * 这里用手写类型 + fetch，只服务这一个面板。
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

export interface GridDisk {
  sn: string;
  rack: number;
  slot: number;
  model: string;
  before: boolean;
  after: boolean;
  failed_day: number | null;
}

export interface FailureRow {
  sn: string;
  day: number;
  rack: number | null;
  slot: number | null;
  model: string | null;
  caught_before: boolean;
  caught_after: boolean;
  lead_days: number;
}

export interface SideOutcome {
  alarms: number;
  failures: number;
  caught: number;
  missed: number;
  false_alarms: number | null;
  pending: number;
}

export interface GatePacket {
  kind: string;
  at: number;
  allowed: Record<string, string | number | boolean | null>;
  allowed_labels: Record<string, string>;
  blocked: Array<{ field: string; reason: string; size: string }>;
  bytes_allowed: number;
}

export interface EdgeState {
  device: null | {
    name: string;
    addr: string;
    online: boolean;
    connected: boolean;
    frames: number;
    bytes: number;
    connected_at: number;
    last_seen: number;
  };
  stream: {
    phase: 'idle' | 'ingesting' | 'scoring' | 'observing' | 'done';
    day: number;
    history_days: number;
    horizon_days: number;
    start_date: string;
    frames: number;
    bytes: number;
    rows: number;
    disks: number;
    rate_bps: number;
    scored_in_s: number | null;
  };
  grid: GridDisk[];
  failures: FailureRow[];
  outcome: { before: SideOutcome; after: SideOutcome };
  models: {
    status: 'idle' | 'training' | 'ready' | 'error';
    error: string | null;
    fit_seconds?: number;
    before?: { label: string; threshold: number; sha: string };
    after?: { label: string; threshold: number; sha: string; ensemble: number };
  };
  events: Array<{ at: number; kind: string; text: string }>;
  uploads: GatePacket[];
  evaluation_status: string;
  endpoints: string[];
  tablet_urls: string[];
  data_boundary: { kept_local: string[]; whitelist: string[] };
}

export interface GpuStatus {
  available: boolean;
  name?: string;
  util?: number | null;
  mem_used_mb?: number | null;
  mem_total_mb?: number | null;
  power_w?: number | null;
  temp_c?: number | null;
}

interface Band {
  mean: number;
  lo: number;
  hi: number;
  p10: number;
}

export interface Evaluation {
  status: 'idle' | 'running' | 'done' | 'error';
  step?: string;
  error?: string;
  official?: Record<'before' | 'after', { combined_score: number; validity: number; metric: Record<string, number>; error: string }>;
  bootstrap?: {
    device: string;
    n_boot: number;
    n_disks: number;
    elapsed_s: number;
    resamples_per_s: number;
    f1: Record<'before' | 'after' | 'delta', Band>;
    auprc: Record<'before' | 'after' | 'delta', Band>;
    p_improve_f1: number;
    p_improve_auprc: number;
  };
  packet?: GatePacket;
}

export interface CloudReplay {
  run_id: string;
  replay: boolean;
  note: string;
  initial_score: number;
  best_score: number;
  best_node_id: string;
  total_tokens: number;
  wall_time_h: number;
  islands: Record<string, { profile: string; attempts: number; valid_evaluations: number; best_score: number; stop_reason: string }>;
  best_path: Array<{ id: string; score: number; operator: string; island: string; intent: string }>;
  timeline: Array<{ order: number; id: string; island: string; operator: string; status: string; score: number | null; best_so_far: number; on_best_path: boolean }>;
  packets: GatePacket[];
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} → HTTP ${res.status}`);
  return (await res.json()) as T;
}

async function postJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { method: 'POST' });
  if (!res.ok) throw new Error(`${url} → HTTP ${res.status}`);
  return (await res.json()) as T;
}

export function useEdgeState() {
  return useQuery({ queryKey: ['edge', 'state'], queryFn: () => getJson<EdgeState>('/api/edge/state'), refetchInterval: 700 });
}

export function useGpu() {
  return useQuery({ queryKey: ['edge', 'gpu'], queryFn: () => getJson<GpuStatus>('/api/edge/gpu'), refetchInterval: 1500 });
}

export function useEvaluation(poll: boolean) {
  return useQuery({
    queryKey: ['edge', 'evaluation'],
    queryFn: () => getJson<Evaluation>('/api/edge/evaluation'),
    refetchInterval: poll ? 800 : false,
  });
}

export function useCloudReplay() {
  return useQuery({ queryKey: ['edge', 'cloud'], queryFn: () => getJson<CloudReplay>('/api/edge/cloud'), staleTime: Infinity });
}

export function useEdgeActions() {
  const client = useQueryClient();
  const refresh = () => void client.invalidateQueries({ queryKey: ['edge'] });
  return {
    evaluate: useMutation({ mutationFn: () => postJson('/api/edge/evaluate'), onSuccess: refresh }),
    simulate: useMutation({ mutationFn: (daySeconds: number) => postJson(`/api/edge/simulate?day_seconds=${daySeconds}`), onSuccess: refresh }),
    prepare: useMutation({ mutationFn: () => postJson('/api/edge/models/prepare'), onSuccess: refresh }),
  };
}
