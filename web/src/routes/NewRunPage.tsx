/**
 * New-run wizard (PRD §8.1). Existing fields only, regrouped into six steps.
 * The create request is fired from the last step after preflight passes.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from '@tanstack/react-router';
import { useMemo, useState } from 'react';

import { ApiErrorPanel } from '@/components/states/ApiErrorPanel';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/states/EmptyState';
import { DeploymentModeCards } from '@/features/intake/DeploymentModeCards';
import { KnowledgeInjectionForm } from '@/features/intake/KnowledgeInjectionForm';
import { PreflightPanel } from '@/features/intake/PreflightPanel';
import { PresetSelector } from '@/features/intake/PresetSelector';
import { ServerProfileForm } from '@/features/intake/ServerProfileForm';
import { TaskArtifactsForm } from '@/features/intake/TaskArtifactsForm';
import { derivePreflightChecks } from '@/features/intake/preflight-logic';
import { useTaskArtifactCards } from '@/features/intake/task-artifacts-logic';
import type { ArtifactCard } from '@/features/intake/task-artifacts-logic';
import { canAdvanceFromWizardStep } from '@/features/intake/wizard-step-logic';
import {
  createRunApiRunsPost,
  getTaskApiTasksTaskIdGet,
  listPresetsApiPresetsGet,
  listServersApiServersGet,
  listTasksApiTasksGet,
  metaApiMetaGet,
} from '@/generated/api';
import type { TaskSummaryResponse } from '@/generated/api';
import { toApiError, unwrap } from '@/lib/api';
import type { ApiError } from '@/lib/api-error';
import { queryKeys } from '@/lib/query-keys';
import {
  KNOWLEDGE_MODE_LABEL,
  composeConfigPatch,
  selectIsCustomized,
  useIntakeStore,
} from '@/stores/intake-store';

const STEPS = [
  { id: 'task', label: '选择任务', short: '任务' },
  { id: 'target', label: '执行目标', short: '目标' },
  { id: 'knowledge', label: '知识注入', short: '知识' },
  { id: 'intensity', label: '进化强度', short: '强度' },
  { id: 'advanced', label: '高级设置', short: '高级' },
  { id: 'launch', label: '确认并启动', short: '启动' },
] as const;

function taskSelectable(task: TaskSummaryResponse): boolean {
  return !task.is_stub && task.has_evaluator && task.has_init;
}

function TaskOption({
  task,
  selected,
  onSelect,
}: {
  task: TaskSummaryResponse;
  selected: boolean;
  onSelect: (taskId: string) => void;
}) {
  const selectable = taskSelectable(task);
  return (
    <label
      data-task-option={task.task_id}
      className={`fe-card fe-card-interactive flex cursor-pointer gap-2 p-3 ${
        selected
          ? 'border-brand-500 bg-brand-50 dark:bg-brand-500/10'
          : 'border-[#e1e1e1] bg-white'
      } ${selectable ? '' : 'cursor-not-allowed opacity-60'}`}
    >
      <input
        type="radio"
        name="intake-task"
        value={task.task_id}
        checked={selected}
        disabled={!selectable}
        onChange={() => onSelect(task.task_id)}
        className="mt-0.5 accent-[var(--fe-brand)]"
      />
      <span className="min-w-0">
        <span className="block text-xs font-medium text-fg">{task.display_name}</span>
        <span className="mt-0.5 block font-mono text-[11px] text-fg-subtle">{task.task_id}</span>
        {selectable ? null : (
          <span className="mt-1 block text-[11px] text-warning-700">
            示例或工件未就绪，不能用于新建运行。
          </span>
        )}
      </span>
    </label>
  );
}

function TaskStep({
  cards,
  error,
  onRetry,
}: {
  cards: ArtifactCard[];
  error: ApiError | null;
  onRetry: () => void;
}) {
  const taskId = useIntakeStore((state) => state.taskId);
  const setTask = useIntakeStore((state) => state.setTask);
  const tasksQuery = useQuery({
    queryKey: queryKeys.taskList(),
    queryFn: () => unwrap(listTasksApiTasksGet()),
    retry: 1,
  });
  const tasks = tasksQuery.data ?? [];

  return (
    <section className="flex flex-col gap-4" data-wizard-panel="task">
      <div>
        <h2 className="text-sm font-semibold text-fg">选择任务</h2>
        <p className="mt-1 text-xs text-fg-muted">从已注册的任务中挑选一项。这里不提供自由输入路径。</p>
        {taskId === null ? <p className="mt-2 text-xs text-fg-subtle">尚未选择任务</p> : null}
      </div>

      {tasksQuery.isPending ? (
        <p className="text-xs text-fg-subtle">正在读取任务目录…</p>
      ) : tasksQuery.isError ? (
        <ApiErrorPanel error={toApiError(tasksQuery.error)} onRetry={() => void tasksQuery.refetch()} />
      ) : tasks.length === 0 ? (
        <EmptyState
          title="任务目录中没有任务"
          reason="配置的任务目录下一层没有发现可识别的任务，这里不提供自由输入路径。"
          nextStep="检查 FE_WEB_TASK_ROOTS 是否指向 benchmark/ 一类的任务根目录。"
        />
      ) : (
        <div className="grid gap-2 md:grid-cols-2">
          {tasks.map((task) => (
            <TaskOption
              key={task.task_id}
              task={task}
              selected={taskId === task.task_id}
              onSelect={setTask}
            />
          ))}
        </div>
      )}

      {taskId !== null ? <TaskArtifactsForm cards={cards} error={error} onRetry={onRetry} /> : null}
    </section>
  );
}

function SelectionSummary({ taskName }: { taskName: string }) {
  const taskId = useIntakeStore((state) => state.taskId);
  const serverProfileId = useIntakeStore((state) => state.serverProfileId);
  const preset = useIntakeStore((state) => state.preset);
  const knowledgeMode = useIntakeStore((state) => state.knowledgeMode);
  const customized = useIntakeStore(selectIsCustomized);
  const serversQuery = useQuery({
    queryKey: queryKeys.serverList(),
    queryFn: () => unwrap(listServersApiServersGet()),
    retry: 1,
  });
  const presetsQuery = useQuery({
    queryKey: queryKeys.presetList(),
    queryFn: () => unwrap(listPresetsApiPresetsGet()),
    retry: 1,
  });
  const serverName =
    serversQuery.data?.profiles?.find((profile) => profile.profile_id === serverProfileId)
      ?.display_name ?? null;
  const presetName =
    presetsQuery.data?.presets?.find((item) => item.name === preset)?.display_name_zh ?? preset;

  const rows: Array<[string, string]> = [
    ['任务', taskId ? taskName : '尚未选择'],
    ['执行目标', serverProfileId ? (serverName ?? serverProfileId) : '尚未选择'],
    ['知识注入', KNOWLEDGE_MODE_LABEL[knowledgeMode]],
    ['进化强度', customized ? `${presetName}（已自定义）` : presetName],
    ['部署模式', '纯云端'],
  ];

  return (
    <section className="fe-card p-3" data-launch-summary="true">
      <h3 className="text-sm font-semibold text-fg">确认摘要</h3>
      <dl className="mt-2 grid grid-cols-[5.5rem_1fr] gap-y-1.5 text-xs">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-fg-muted">{label}</dt>
            <dd className="text-fg">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export function NewRunPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const taskId = useIntakeStore((state) => state.taskId);
  const serverProfileId = useIntakeStore((state) => state.serverProfileId);
  const presetPreview = useIntakeStore((state) => state.presetPreview);
  const preset = useIntakeStore((state) => state.preset);
  const patch = useIntakeStore((state) => state.patch);
  const knowledgeMode = useIntakeStore((state) => state.knowledgeMode);
  const [mockLlm, setMockLlm] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);
  const [maxReached, setMaxReached] = useState(0);

  const taskQuery = useQuery({
    queryKey: queryKeys.task(taskId ?? ''),
    queryFn: () => unwrap(getTaskApiTasksTaskIdGet({ path: { task_id: taskId ?? '' } })),
    enabled: taskId !== null,
    retry: 1,
  });

  const metaQuery = useQuery({
    queryKey: queryKeys.meta(),
    queryFn: () => unwrap(metaApiMetaGet()),
    retry: 1,
  });

  const artifact = useTaskArtifactCards(taskId);
  const cards = taskId === null ? [] : artifact.cards;
  const cardsPending = taskId !== null && artifact.cards.some((card) => card.state === 'checking');

  const serversQuery = useQuery({
    queryKey: queryKeys.serverList(),
    queryFn: () => unwrap(listServersApiServersGet()),
    enabled: taskId !== null,
    retry: 1,
  });

  const presetsQuery = useQuery({
    queryKey: queryKeys.presetList(),
    queryFn: () => unwrap(listPresetsApiPresetsGet()),
    enabled: taskId !== null,
    retry: 1,
  });

  const canGoNext = canAdvanceFromWizardStep(stepIndex, {
    taskId,
    cards,
    cardsPending,
    serversPending: serversQuery.isPending,
    serversErrored: serversQuery.isError,
    serverProfileId,
    presetsPending: presetsQuery.isPending,
    presetsErrored: presetsQuery.isError,
    presetCount: presetsQuery.data?.presets?.length ?? 0,
  });

  const configPatch = useMemo(
    () => composeConfigPatch(patch, knowledgeMode),
    [patch, knowledgeMode],
  );

  const launch = useMutation({
    mutationFn: async () => {
      if (taskId === null || serverProfileId === null) {
        throw new Error('尚未选择任务或执行目标');
      }
      return unwrap(
        createRunApiRunsPost({
          body: {
            task_id: taskId,
            server_profile_id: serverProfileId,
            preset,
            config_patch: configPatch,
            mock_llm: mockLlm,
            seed: null,
          },
        }),
      );
    },
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.runList() });
      void navigate({ to: '/runs/$runId', params: { runId: created.run_id } });
    },
  });

  const checks = derivePreflightChecks({
    taskSelected: taskId !== null,
    artifactCards: cards,
    serverSelected: serverProfileId !== null,
    presetValid: presetPreview === 'invalid' ? false : null,
    qwenConfigured: metaQuery.isSuccess ? (metaQuery.data.qwen_configured ?? null) : null,
    mockLlm,
  });

  const blockedReason = (() => {
    if (metaQuery.isPending) return '正在读取服务端能力信息…';
    if (metaQuery.isError) return '无法读取服务端能力信息，请确认后端已启动。';
    const meta = metaQuery.data;
    if (!meta.process_control_enabled) {
      return '服务端未启用进程控制（FE_WEB_ENABLE_PROCESS_CONTROL=true）。当前只能查看历史运行。';
    }
    if (!meta.run_registry_configured) {
      return '服务端未配置运行注册表（FE_WEB_RUN_REGISTRY），启动的运行无法被记录。';
    }
    if (serverProfileId === null) return '尚未选择执行目标（服务器配置）。';
    return null;
  })();

  const goTo = (index: number) => {
    if (index < 0 || index > maxReached) return;
    setStepIndex(index);
  };

  const goNext = () => {
    const next = Math.min(stepIndex + 1, STEPS.length - 1);
    setMaxReached((reached) => Math.max(reached, next));
    setStepIndex(next);
  };

  const goBack = () => {
    setStepIndex((current) => Math.max(0, current - 1));
  };

  const taskName = taskQuery.data?.display_name ?? taskId ?? '尚未选择任务';

  return (
    <div className="flex flex-col gap-4" data-new-run-wizard="true">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h1 className="text-base font-semibold text-fg">新建运行</h1>
        <p className="text-xs text-fg-muted">{taskId ? taskName : '先选择任务'}</p>
      </div>

      <nav aria-label="新建运行步骤">
        <ol className="flex flex-wrap items-center gap-1">
          {STEPS.map((step, index) => {
            const current = index === stepIndex;
            const reached = index <= maxReached;
            return (
              <li key={step.id} className="flex items-center gap-1">
                {index > 0 ? (
                  <span aria-hidden className="text-fg-subtle">
                    /
                  </span>
                ) : null}
                <button
                  type="button"
                  data-wizard-step={step.id}
                  aria-label={step.label}
                  aria-current={current ? 'step' : undefined}
                  disabled={!reached}
                  onClick={() => goTo(index)}
                  className={`rounded px-1.5 py-1 text-xs ${
                    current
                      ? 'bg-brand-50 font-medium text-brand-700 dark:bg-brand-500/10 dark:text-brand-300'
                      : reached
                        ? 'text-fg hover:bg-surface-muted'
                        : 'text-fg-subtle'
                  } disabled:cursor-not-allowed disabled:opacity-60`}
                >
                  <span className="tabular">{index + 1}</span>
                  <span className="ml-1">{step.short}</span>
                </button>
              </li>
            );
          })}
        </ol>
      </nav>

      <div className="min-w-0">
        {stepIndex === 0 ? (
          <TaskStep cards={cards} error={artifact.error} onRetry={artifact.retry} />
        ) : null}
        {stepIndex === 1 ? <ServerProfileForm /> : null}
        {stepIndex === 2 ? <KnowledgeInjectionForm /> : null}
        {stepIndex === 3 ? <PresetSelector section="intensity" /> : null}
        {stepIndex === 4 ? <PresetSelector section="advanced" /> : null}
        {stepIndex === 5 ? (
          <div className="flex flex-col gap-5 lg:flex-row" data-wizard-panel="launch">
            <div className="flex min-w-0 flex-1 flex-col gap-5">
              {metaQuery.data ? <DeploymentModeCards modes={metaQuery.data.deployment_modes} /> : null}
              <SelectionSummary taskName={taskName} />
            </div>
            <PreflightPanel
              checks={checks}
              onLaunch={() => launch.mutate()}
              launching={launch.isPending}
              launchError={launch.isError ? toApiError(launch.error).message : null}
              blockedReason={blockedReason}
              mockLlm={mockLlm}
              onMockLlmChange={setMockLlm}
            />
          </div>
        ) : null}
      </div>

      <div className="sticky bottom-0 z-10 flex items-center justify-between gap-3 border-t border-[#e1e1e1] bg-canvas/90 py-3 backdrop-blur-xl">
        <Button variant="secondary" onClick={goBack} disabled={stepIndex === 0}>
          上一步
        </Button>
        {stepIndex < STEPS.length - 1 ? (
          <Button
            onClick={goNext}
            disabled={!canGoNext}
            title={canGoNext ? undefined : '请先完成本步必填项或等待加载结束'}
          >
            下一步
          </Button>
        ) : (
          <p className="text-[11px] text-fg-muted">检查通过后，点击「启动运行」。</p>
        )}
      </div>
    </div>
  );
}
