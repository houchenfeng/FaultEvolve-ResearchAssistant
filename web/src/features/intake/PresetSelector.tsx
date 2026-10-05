/**
 * 进化强度预设选择（TODO 4.6 / PRD §7.6）。
 *
 * 三档预设来自 /api/presets（每档是完整、已校验的 EvolveConfig）。
 * 「已自定义」以 patch 非空为唯一判据；「恢复默认」清空 patch。
 * 「生成配置预览」把 patch 交给后端 merge 端点合并重校验——
 * 前端不本地拼最终配置，校验永远在服务端（TODO 4.6 后端合并再校验）。
 */
import { useMutation, useQuery } from '@tanstack/react-query';

import { ApiErrorPanel } from '@/components/states/ApiErrorPanel';
import { StatusBadge } from '@/components/ui/StatusBadge';
import type { PresetResponse } from '@/generated/api';
import { listPresetsApiPresetsGet, mergePresetApiPresetsNameMergePost } from '@/generated/api';
import { toApiError, unwrap } from '@/lib/api';
import { queryKeys } from '@/lib/query-keys';
import {
  buildConfigPatch,
  selectIsCustomized,
  useIntakeStore,
} from '@/stores/intake-store';

const ORDER = ['quick', 'standard', 'deep'] as const;

function presetValue(preset: PresetResponse | undefined, path: string[]): unknown {
  let node: unknown = preset?.config;
  for (const key of path) {
    if (node === null || typeof node !== 'object') return undefined;
    node = (node as Record<string, unknown>)[key];
  }
  return node;
}

function patchNumber(patch: Record<string, unknown>, group: string, field: string): string {
  const groupValue = patch[group];
  if (groupValue === null || typeof groupValue !== 'object' || Array.isArray(groupValue)) return '';
  const value = (groupValue as Record<string, unknown>)[field];
  return typeof value === 'number' && Number.isFinite(value) ? String(value) : '';
}

export function PresetSelector({
  section = 'all',
}: {
  /** `intensity` shows presets, `advanced` shows overrides, `all` shows both. */
  section?: 'intensity' | 'advanced' | 'all';
}) {
  const preset = useIntakeStore((state) => state.preset);
  const patch = useIntakeStore((state) => state.patch);
  const setPreset = useIntakeStore((state) => state.setPreset);
  const applyPatch = useIntakeStore((state) => state.applyPatch);
  const resetToPreset = useIntakeStore((state) => state.resetToPreset);
  const isCustomized = useIntakeStore(selectIsCustomized);

  const listQuery = useQuery({
    queryKey: queryKeys.presetList(),
    queryFn: () => unwrap(listPresetsApiPresetsGet()),
    retry: 1,
  });
  const presets = listQuery.data?.presets ?? [];
  const selectedPreset = presets.find((item) => item.name === preset);

  const previewMutation = useMutation({
    mutationFn: () =>
      unwrap(
        mergePresetApiPresetsNameMergePost({
          path: { name: preset },
          body: buildConfigPatch(useIntakeStore.getState()),
        }),
      ),
    onSuccess: () => useIntakeStore.getState().setPresetPreview('valid'),
    onError: () => useIntakeStore.getState().setPresetPreview('invalid'),
  });

  const maxIterations = presetValue(selectedPreset, ['budget', 'max_iterations']);
  const maxWallHours = presetValue(selectedPreset, ['budget', 'max_wall_hours']);
  const maxTokens = presetValue(selectedPreset, ['budget', 'max_tokens']);

  const preview = previewMutation.data;
  const showIntensity = section !== 'advanced';
  const showAdvanced = section !== 'intensity';

  const advancedFields = (
    <div className="grid gap-3 sm:grid-cols-3" data-advanced-settings="true">
      <label className="flex flex-col gap-1 text-[11px]">
        <span className="text-fg-subtle">迭代上限（默认 {String(maxIterations ?? '—')}）</span>
        <input
          type="number"
          min={1}
          value={patchNumber(patch, 'budget', 'max_iterations')}
          data-advanced-field="budget.max_iterations"
          onChange={(event) =>
            applyPatch({
              budget: { max_iterations: Number(event.target.value) },
            })
          }
          className="fe-input fe-input-sm"
        />
      </label>
      <label className="flex flex-col gap-1 text-[11px]">
        <span className="text-fg-subtle">最长运行时间（小时，默认 {String(maxWallHours ?? '—')}）</span>
        <input
          type="number"
          min={0.1}
          step={0.5}
          value={patchNumber(patch, 'budget', 'max_wall_hours')}
          data-advanced-field="budget.max_wall_hours"
          onChange={(event) =>
            applyPatch({
              budget: { max_wall_hours: Number(event.target.value) },
            })
          }
          className="fe-input fe-input-sm"
        />
      </label>
      <label className="flex flex-col gap-1 text-[11px]">
        <span className="text-fg-subtle">Token 预算（默认 {String(maxTokens ?? '—')}）</span>
        <input
          type="number"
          min={1}
          value={patchNumber(patch, 'budget', 'max_tokens')}
          data-advanced-field="budget.max_tokens"
          onChange={(event) =>
            applyPatch({
              budget: { max_tokens: Number(event.target.value) },
            })
          }
          className="fe-input fe-input-sm"
        />
      </label>
    </div>
  );

  return (
    <section className="flex flex-col gap-2" data-preset-selector="true">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-fg">
          {section === 'advanced' ? '高级设置' : '进化强度'}
        </h3>
        {showAdvanced && isCustomized ? (
          <span className="flex items-center gap-2">
            <StatusBadge tone="warning">已自定义</StatusBadge>
            <button
              type="button"
              data-reset-preset="true"
              onClick={() => resetToPreset()}
              className="rounded-card border border-border-subtle px-2 py-0.5 text-[11px] text-fg-muted hover:bg-surface-muted"
            >
              恢复默认
            </button>
          </span>
        ) : null}
      </div>

      {showIntensity ? (
        listQuery.isPending ? (
          <p className="text-xs text-fg-subtle">正在读取预设…</p>
        ) : listQuery.isError ? (
          <ApiErrorPanel
            error={toApiError(listQuery.error)}
            onRetry={() => void listQuery.refetch()}
          />
        ) : (
          <div className="grid gap-2 md:grid-cols-3">
            {ORDER.map((name) => {
              const item = presets.find((candidate) => candidate.name === name);
              return (
                <label
                  key={name}
                  className={`flex cursor-pointer flex-col gap-1 rounded-card border p-3 ${
                    preset === name
                      ? 'border-brand-500 bg-brand-50 dark:bg-brand-500/10'
                      : 'border-border-subtle bg-surface hover:bg-surface-muted'
                  }`}
                >
                  <span className="flex items-center gap-2 text-xs font-medium text-fg">
                    <input
                      type="radio"
                      name="preset"
                      value={name}
                      checked={preset === name}
                      onChange={() => setPreset(name)}
                      className="accent-[var(--fe-brand)]"
                    />
                    {item?.display_name_zh ?? name}
                  </span>
                  <span className="text-[11px] text-fg-muted">
                    {item?.summary_zh ?? '（后端未提供简介）'}
                  </span>
                </label>
              );
            })}
          </div>
        )
      ) : null}

      {showAdvanced && section === 'all' ? (
        <details className="fe-card p-3">
          <summary className="cursor-pointer text-xs font-medium text-fg">高级字段</summary>
          <div className="mt-2">{advancedFields}</div>
        </details>
      ) : null}
      {showAdvanced && section === 'advanced' ? (
        <div className="fe-card p-3">
          <p className="mb-2 text-[11px] text-fg-subtle">
            改动会覆盖当前档位的模板默认值，并可恢复。
          </p>
          {advancedFields}
        </div>
      ) : null}

      {showAdvanced ? (
      <div className="flex items-center gap-2">
        <button
          type="button"
          data-preview-config="true"
          onClick={() => previewMutation.mutate()}
          disabled={previewMutation.isPending}
          className="fe-btn fe-btn-secondary fe-btn-sm disabled:opacity-50"
        >
          {previewMutation.isPending ? '校验中…' : '生成配置预览（服务端校验）'}
        </button>
      </div>
      ) : null}

      {showAdvanced && previewMutation.isError ? (
        <ApiErrorPanel error={toApiError(previewMutation.error)} />
      ) : null}

      {showAdvanced && preview ? (
        <div
          data-config-preview="true"
          className="fe-card bg-surface-muted p-3 text-[11px] text-fg-muted"
        >
          <p className="font-medium text-fg">
            合并结果：{preview.display_name_zh}
            （迭代 {String(presetValue(preview, ['budget', 'max_iterations']) ?? '—')} ·{' '}
            {String(presetValue(preview, ['budget', 'max_wall_hours']) ?? '—')} 小时）
          </p>
          <p className="mt-1">
            {preview.sources
              ?.filter((source) => source.source === 'user_patch')
              .map((source) => source.field)
              .join('、') || '全部字段来自预设'}
          </p>
        </div>
      ) : null}
    </section>
  );
}
