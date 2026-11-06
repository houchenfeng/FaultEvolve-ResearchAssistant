/**
 * 本地-云端混合模式（`/runs/$runId/hybrid`）。
 *
 * 云端进化来自服务器真实运行的回放；本地评估域是实时的：平板经局域网推送
 * SMART 遥测，笔记本在本机跑进化前/后两个算法和 GPU 评估，只把白名单分数回传。
 */
import { CloudReplayPanel, BoundaryLog, GpuEvaluatorPanel } from '@/features/hybrid/EvalPanels';
import { EdgeDevicePanel, RackHeatmap, StreamOutcome } from '@/features/hybrid/EdgePanels';
import { useCloudReplay, useEdgeActions, useEdgeState, useEvaluation, useGpu } from '@/features/hybrid/edge-api';
import { HybridFlow } from '@/features/hybrid/HybridFlow';

export function RunHybridPage() {
  const stateQuery = useEdgeState();
  const gpuQuery = useGpu();
  const cloudQuery = useCloudReplay();
  const evaluating = stateQuery.data?.evaluation_status === 'running';
  const evaluationQuery = useEvaluation(evaluating);
  const actions = useEdgeActions();
  const state = stateQuery.data;

  if (stateQuery.isError) {
    return (
      <div className="fe-card p-6 text-sm text-fg-muted">
        本地评估域接口不可用：{String(stateQuery.error)}。请用 <code>scripts/edge_demo.ps1</code> 启动后端（含 /api/edge）。
      </div>
    );
  }
  if (!state) return <div className="px-4 py-10 text-center text-xs text-fg-subtle">正在连接本地评估域…</div>;

  return (
    <div className="flex flex-col gap-3" data-hybrid-page="true">
      <HybridFlow state={state} evaluation={evaluationQuery.data} />
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[1fr_1.35fr_1.2fr]">
        <EdgeDevicePanel state={state} onSimulate={() => actions.simulate.mutate(1)} simulating={actions.simulate.isPending || state.stream.phase === 'ingesting'} />
        <RackHeatmap grid={state.grid} />
        <StreamOutcome state={state} />
      </div>
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[1.35fr_1fr]">
        <GpuEvaluatorPanel
          gpu={gpuQuery.data}
          evaluation={evaluationQuery.data}
          onRun={() => actions.evaluate.mutate()}
          starting={actions.evaluate.isPending}
        />
        <CloudReplayPanel cloud={cloudQuery.data} />
      </div>
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[1.35fr_1fr]">
        <BoundaryLog uploads={state.uploads} cloudPackets={cloudQuery.data?.packets ?? []} keptLocal={state.data_boundary.kept_local} />
        <section className="fe-card flex flex-col gap-2 p-4">
          <h3 className="text-sm font-semibold text-fg">本地评估域事件</h3>
          <ol className="flex max-h-72 flex-col gap-1 overflow-y-auto text-[11px]">
            {state.events.map((e) => (
              <li key={`${e.at}-${e.text}`} className="flex gap-2">
                <span className="tabular shrink-0 text-fg-subtle">{new Date(e.at * 1000).toLocaleTimeString()}</span>
                <span className={e.kind === 'failure' || e.kind === 'error' ? 'text-danger-500' : e.kind === 'upload' ? 'text-success-700 dark:text-success-500' : 'text-fg-muted'}>
                  {e.text}
                </span>
              </li>
            ))}
            {state.events.length === 0 ? <li className="text-fg-subtle">暂无事件</li> : null}
          </ol>
        </section>
      </div>
    </div>
  );
}
