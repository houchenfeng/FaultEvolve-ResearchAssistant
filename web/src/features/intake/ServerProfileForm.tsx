/**
 * 服务器与目录配置（TODO 4.3 / 4.4 / PRD §7.4）。
 *
 * 一个 profile = 一台执行目标（local_cloud / ssh_cloud）。
 * 密钥只回传 private_key_ref（路径引用），密码/私钥本体永不进浏览器；
 * 「测试连接」走 /probe，「测试目录」走 /check-path（白名单内才可达）。
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';

import { ApiErrorPanel } from '@/components/states/ApiErrorPanel';
import { StatusBadge } from '@/components/ui/StatusBadge';
import type {
  PathProbeResponse,
  ServerProfileResponse,
  ServerProbeResponse,
} from '@/generated/api';
import {
  checkPathApiServersProfileIdCheckPathPost,
  deleteServerApiServersProfileIdDelete,
  listServersApiServersGet,
  probeServerApiServersProfileIdProbePost,
  upsertServerApiServersPost,
} from '@/generated/api';
import { toApiError, unwrap } from '@/lib/api';
import { queryKeys } from '@/lib/query-keys';
import { useIntakeStore } from '@/stores/intake-store';
import { EnvConfigForm } from '@/features/intake/EnvConfigForm';
import { NotesTextarea } from '@/features/intake/NotesTextarea';
import { PathProbeList } from '@/features/intake/PathProbeList';

/** 表单草稿：全部字符串，保存时再解析成数字。 */
export interface ProfileDraft {
  display_name: string;
  mode: 'local_cloud' | 'ssh_cloud';
  host: string;
  port: string;
  user: string;
  private_key_ref: string;
  repo_dir: string;
  data_dir: string;
  runs_dir: string;
  artifacts_dir: string;
  logs_dir: string;
  python_executable: string;
  conda_env: string;
  cpu_limit: string;
  memory_gb: string;
  gpu_count: string;
  gpu_devices: string;
  gpu_model: string;
  max_concurrency: string;
  timeout_s: string;
  notes: string;
}

const EMPTY_DRAFT: ProfileDraft = {
  display_name: '',
  mode: 'local_cloud',
  host: '',
  port: '',
  user: '',
  private_key_ref: '',
  repo_dir: '',
  data_dir: '',
  runs_dir: '',
  artifacts_dir: '',
  logs_dir: '',
  python_executable: '',
  conda_env: '',
  cpu_limit: '',
  memory_gb: '',
  gpu_count: '',
  gpu_devices: '',
  gpu_model: '',
  max_concurrency: '',
  timeout_s: '',
  notes: '',
};

function draftFromResponse(profile: ServerProfileResponse): ProfileDraft {
  return {
    display_name: profile.display_name,
    // 表单只提供 local_cloud / ssh_cloud 两档；其他模式按 local 处理。
    mode: profile.mode === 'ssh_cloud' ? 'ssh_cloud' : 'local_cloud',
    host: profile.host ?? '',
    port: profile.port != null ? String(profile.port) : '',
    user: profile.user ?? '',
    private_key_ref: '',
    repo_dir: profile.repo_dir ?? '',
    data_dir: profile.data_dir ?? '',
    runs_dir: profile.runs_dir ?? '',
    artifacts_dir: profile.artifacts_dir ?? '',
    logs_dir: profile.logs_dir ?? '',
    python_executable: profile.python_executable ?? '',
    conda_env: profile.conda_env ?? '',
    cpu_limit: profile.cpu_limit != null ? String(profile.cpu_limit) : '',
    memory_gb: profile.memory_gb != null ? String(profile.memory_gb) : '',
    gpu_count: profile.gpu_count != null ? String(profile.gpu_count) : '',
    gpu_devices: (profile.gpu_devices ?? []).join(','),
    gpu_model: profile.gpu_model ?? '',
    max_concurrency: profile.max_concurrency != null ? String(profile.max_concurrency) : '',
    timeout_s: profile.timeout_s != null ? String(profile.timeout_s) : '',
    notes: profile.notes ?? '',
  };
}

function parseOptionalNumber(text: string): number | null {
  if (text.trim() === '') return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

function requestFromDraft(draft: ProfileDraft): Parameters<
  typeof upsertServerApiServersPost
>[0]['body'] {
  return {
    display_name: draft.display_name.trim() || '未命名执行目标',
    mode: draft.mode,
    host: draft.host.trim() || null,
    port: parseOptionalNumber(draft.port),
    user: draft.user.trim() || null,
    private_key_ref: draft.private_key_ref.trim() || null,
    repo_dir: draft.repo_dir.trim() || null,
    data_dir: draft.data_dir.trim() || null,
    runs_dir: draft.runs_dir.trim() || null,
    artifacts_dir: draft.artifacts_dir.trim() || null,
    logs_dir: draft.logs_dir.trim() || null,
    python_executable: draft.python_executable.trim() || null,
    conda_env: draft.conda_env.trim() || null,
    cpu_limit: parseOptionalNumber(draft.cpu_limit),
    memory_gb: parseOptionalNumber(draft.memory_gb),
    gpu_count: parseOptionalNumber(draft.gpu_count),
    gpu_devices: draft.gpu_devices
      .split(',')
      .map((part) => part.trim())
      .filter((part) => part !== ''),
    gpu_model: draft.gpu_model.trim() || null,
    max_concurrency: parseOptionalNumber(draft.max_concurrency),
    timeout_s: parseOptionalNumber(draft.timeout_s),
    notes: draft.notes,
  };
}

const DIR_FIELDS: Array<[keyof ProfileDraft & string, string, string]> = [
  ['repo_dir', '代码目录', '例如 /srv/faultevolve'],
  ['data_dir', '数据目录', '例如 benchmark/hdd_mvp/data'],
  ['runs_dir', '运行输出目录', '例如 runs'],
  ['artifacts_dir', '制品目录', '例如 artifacts'],
  ['logs_dir', '日志目录', '例如 logs'],
];

export function ServerProfileForm() {
  const queryClient = useQueryClient();
  const serverProfileId = useIntakeStore((state) => state.serverProfileId);
  const setServerProfile = useIntakeStore((state) => state.setServerProfile);

  const listQuery = useQuery({
    queryKey: queryKeys.serverList(),
    queryFn: () => unwrap(listServersApiServersGet()),
    retry: 1,
  });

  const profiles = useMemo(
    () => listQuery.data?.profiles ?? [],
    [listQuery.data],
  );
  const defaultId = useMemo(
    () => listQuery.data?.default_profile_id ?? null,
    [listQuery.data],
  );
  const sshAvailable = useMemo(
    () => listQuery.data?.ssh_available ?? false,
    [listQuery.data],
  );

  // 默认选中：store 已选 > 后端默认 > 第一个。
  useEffect(() => {
    if (listQuery.data === undefined) return;
    if (serverProfileId !== null) return;
    const candidate = defaultId ?? profiles[0]?.profile_id ?? null;
    if (candidate !== null) setServerProfile(candidate);
  }, [listQuery.data, serverProfileId, defaultId, profiles, setServerProfile]);

  const selected =
    profiles.find((profile) => profile.profile_id === serverProfileId) ?? null;
  const editingNew = selected === null;

  const [draft, setDraft] = useState<ProfileDraft>(EMPTY_DRAFT);
  useEffect(() => {
    setDraft(selected ? draftFromResponse(selected) : EMPTY_DRAFT);
  }, [selected]);

  const patchDraft = (patch: Partial<ProfileDraft>) =>
    setDraft((current) => ({ ...current, ...patch }));

  const invalidate = () =>
    void queryClient.invalidateQueries({ queryKey: queryKeys.servers() });

  const saveMutation = useMutation({
    mutationFn: () =>
      unwrap(
        upsertServerApiServersPost({
          body: requestFromDraft(draft),
          query: editingNew ? undefined : { profile_id: serverProfileId ?? undefined },
        }),
      ),
    onSuccess: (saved) => {
      invalidate();
      setServerProfile(saved.profile_id);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (profileId: string) =>
      unwrap(deleteServerApiServersProfileIdDelete({ path: { profile_id: profileId } })),
    onSuccess: () => {
      invalidate();
      setServerProfile(null);
    },
  });

  const probeMutation = useMutation({
    mutationFn: (profileId: string) =>
      unwrap(probeServerApiServersProfileIdProbePost({ path: { profile_id: profileId } })),
  });

  const pathMutation = useMutation({
    mutationFn: (path: string) =>
      unwrap(
        checkPathApiServersProfileIdCheckPathPost({
          path: { profile_id: serverProfileId ?? '' },
          body: { path },
        }),
      ),
  });

  const [pathResults, setPathResults] = useState<PathProbeResponse[]>([]);
  const testDirs = async () => {
    const filled = DIR_FIELDS.map(([key]) => (draft[key] as string).trim()).filter(
      (value) => value !== '',
    );
    const results: PathProbeResponse[] = [];
    for (const dir of filled) {
      try {
        results.push(await pathMutation.mutateAsync(dir));
      } catch {
        // 单个目录失败不阻断其余；错误统一由面板展示。
      }
    }
    setPathResults(results);
  };

  const probeResult: ServerProbeResponse | undefined = probeMutation.data;

  if (listQuery.isPending) {
    return (
      <section className="fe-card-panel p-4 text-xs text-fg-subtle">
        正在读取服务器配置…
      </section>
    );
  }
  if (listQuery.isError) {
    return (
      <section className="p-2">
        <ApiErrorPanel
          error={toApiError(listQuery.error)}
          onRetry={() => void listQuery.refetch()}
        />
      </section>
    );
  }

  return (
    <section className="flex flex-col gap-3" data-server-form="true">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-fg">服务器与目录</h3>
        <p className="text-[11px] text-fg-subtle">
          密钥只保存路径引用，密码与私钥内容不会回传浏览器。
        </p>
      </div>

      {/* profile 选择 + 新建 */}
      <div className="flex flex-wrap items-center gap-2">
        {profiles.map((profile) => (
          <button
            key={profile.profile_id}
            type="button"
            onClick={() => setServerProfile(profile.profile_id)}
            className={`rounded-card border px-2.5 py-1 text-xs ${
              profile.profile_id === serverProfileId
                ? 'border-brand-500 bg-brand-50 text-brand-600 dark:bg-brand-500/10 dark:text-brand-300'
                : 'border-border-subtle bg-surface text-fg-muted hover:bg-surface-muted'
            }`}
          >
            {profile.display_name}
          </button>
        ))}
        <button
          type="button"
          onClick={() => setServerProfile(null)}
          className="rounded-card border border-dashed border-border-subtle px-2.5 py-1 text-xs text-fg-muted hover:bg-surface-muted"
        >
          + 新建执行目标
        </button>
      </div>

      {/* 连接信息 */}
      <div className="grid gap-3 fe-card p-3 sm:grid-cols-2 xl:grid-cols-4">
        <label className="flex flex-col gap-1 text-[11px]">
          <span className="text-fg-subtle">名称</span>
          <input
            type="text"
            value={draft.display_name}
            onChange={(event) => patchDraft({ display_name: event.target.value })}
            placeholder="例如 本机 / Rocky 服务器"
            className="fe-input fe-input-sm"
          />
        </label>
        <label className="flex flex-col gap-1 text-[11px]">
          <span className="text-fg-subtle">模式</span>
          <select
            value={draft.mode}
            onChange={(event) =>
              patchDraft({ mode: event.target.value as ProfileDraft['mode'] })
            }
            className="fe-input fe-input-sm"
          >
            <option value="local_cloud">local_cloud（本机）</option>
            <option value="ssh_cloud" disabled={!sshAvailable}>
              ssh_cloud{sshAvailable ? '' : '（后端未安装 asyncssh）'}
            </option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[11px]">
          <span className="text-fg-subtle">主机</span>
          <input
            type="text"
            value={draft.host}
            disabled={draft.mode === 'local_cloud'}
            onChange={(event) => patchDraft({ host: event.target.value })}
            placeholder="10.x.x.x"
            className="fe-input fe-input-sm disabled:opacity-50"
          />
        </label>
        <label className="flex flex-col gap-1 text-[11px]">
          <span className="text-fg-subtle">端口</span>
          <input
            type="number"
            value={draft.port}
            disabled={draft.mode === 'local_cloud'}
            onChange={(event) => patchDraft({ port: event.target.value })}
            placeholder="22"
            className="fe-input fe-input-sm disabled:opacity-50"
          />
        </label>
        <label className="flex flex-col gap-1 text-[11px]">
          <span className="text-fg-subtle">用户名</span>
          <input
            type="text"
            value={draft.user}
            disabled={draft.mode === 'local_cloud'}
            onChange={(event) => patchDraft({ user: event.target.value })}
            className="fe-input fe-input-sm disabled:opacity-50"
          />
        </label>
        <label className="flex flex-col gap-1 text-[11px]">
          <span className="text-fg-subtle">私钥文件路径（仅引用）</span>
          <input
            type="text"
            value={draft.private_key_ref}
            disabled={draft.mode === 'local_cloud'}
            onChange={(event) => patchDraft({ private_key_ref: event.target.value })}
            placeholder="~/.ssh/id_ed25519（本机路径）"
            className="fe-input fe-input-sm font-mono"
          />
        </label>
        <div className="flex items-end gap-2 sm:col-span-2">
          <button
            type="button"
            onClick={() => void saveMutation.mutate()}
            disabled={saveMutation.isPending}
            className="fe-btn fe-btn-primary fe-btn-sm disabled:opacity-50"
          >
            {saveMutation.isPending ? '保存中…' : editingNew ? '新建配置' : '保存修改'}
          </button>
          {!editingNew ? (
            <>
              <button
                type="button"
                onClick={() =>
                  serverProfileId && probeMutation.mutate(serverProfileId)
                }
                disabled={probeMutation.isPending}
                className="fe-btn fe-btn-secondary fe-btn-sm disabled:opacity-50"
              >
                {probeMutation.isPending ? '测试中…' : '测试连接'}
              </button>
              <button
                type="button"
                onClick={() => serverProfileId && deleteMutation.mutate(serverProfileId)}
                disabled={deleteMutation.isPending}
                className="rounded-card border border-danger-500/40 px-3 py-1.5 text-xs text-danger-700 hover:bg-danger-50 disabled:opacity-50 dark:text-danger-500 dark:hover:bg-danger-500/10"
              >
                删除
              </button>
            </>
          ) : null}
        </div>
      </div>

      {saveMutation.isError ? (
        <ApiErrorPanel error={toApiError(saveMutation.error)} />
      ) : null}
      {deleteMutation.isError ? (
        <ApiErrorPanel error={toApiError(deleteMutation.error)} />
      ) : null}
      {probeMutation.isError ? (
        <ApiErrorPanel error={toApiError(probeMutation.error)} />
      ) : null}
      {pathMutation.isError ? (
        <ApiErrorPanel error={toApiError(pathMutation.error)} />
      ) : null}

      {probeResult ? (
        <div
          data-probe-result={probeResult.reachable ? 'reachable' : 'unreachable'}
          className="flex flex-wrap items-center gap-2 rounded-card border border-border-subtle bg-surface-muted p-2.5 text-[11px] text-fg-muted"
        >
          <StatusBadge tone={probeResult.reachable ? 'success' : 'danger'}>
            {probeResult.reachable ? '连接成功' : '连接失败'}
          </StatusBadge>
          {probeResult.latency_ms != null ? <span>延迟 {probeResult.latency_ms} ms</span> : null}
          {probeResult.python_version ? <span>Python {probeResult.python_version}</span> : null}
          {probeResult.engine_version ? <span>引擎 {probeResult.engine_version}</span> : null}
          {probeResult.gpu_summary ? <span>GPU {probeResult.gpu_summary}</span> : null}
          {probeResult.detail ? <span>{probeResult.detail}</span> : null}
        </div>
      ) : null}

      {/* 五个目录 */}
      <div className="grid gap-3 fe-card p-3 sm:grid-cols-2 xl:grid-cols-3">
        {DIR_FIELDS.map(([key, label, placeholder]) => (
          <label key={key} className="flex flex-col gap-1 text-[11px]">
            <span className="text-fg-subtle">{label}</span>
            <input
              type="text"
              value={draft[key] as string}
              onChange={(event) => patchDraft({ [key]: event.target.value } as Partial<ProfileDraft>)}
              placeholder={placeholder}
              className="fe-input fe-input-sm font-mono placeholder:font-sans"
            />
          </label>
        ))}
        <div className="flex items-end">
          <button
            type="button"
            onClick={() => void testDirs()}
            disabled={pathMutation.isPending || editingNew}
            title={editingNew ? '先保存配置再测试目录' : undefined}
            className="fe-btn fe-btn-secondary fe-btn-sm disabled:cursor-not-allowed"
          >
            {pathMutation.isPending ? '检查中…' : '测试目录'}
          </button>
        </div>
      </div>

      {pathResults.length > 0 ? <PathProbeList probes={pathResults} /> : null}

      <EnvConfigForm
        draft={draft}
        onChange={patchDraft}
        detected={
          probeResult?.reachable
            ? {
                python_version: probeResult.python_version,
                gpu_summary: probeResult.gpu_summary,
              }
            : null
        }
      />

      <NotesTextarea value={draft.notes} onChange={(notes) => patchDraft({ notes })} />
    </section>
  );
}
