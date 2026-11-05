import { useState } from 'react';

import { ApiErrorPanel } from '@/components/states/ApiErrorPanel';
import type { EffectSolutionResponse as EffectSolution, WorkflowResponse } from '@/generated/api';
import { toApiError } from '@/lib/api';
import { artifactDownloadUrl } from '@/lib/artifact-url';

const number = (value: number | null | undefined) => value == null ? '未记录' : value.toFixed(4);
const labels: Record<string, string> = {
  data_checkup: '数据处理与复检', evolution: '代码演化', hyperparameters: '分层调优', complete: '全部完成',
  running: '运行中', finished: '已完成', failed: '失败', paused: '已中断', passed: '复检通过', blocked: '复检阻断',
  code_evolution: '代码演化', hierarchical_hpo: '分层调优', keep: '保留', reject: '未晋升',
  default_observed: '默认参数评估', default_failed: '默认参数失败', evaluated: '评估成功',
  trial_budget_exhausted: '达到试验预算', wall_time_budget_exhausted: '达到时间预算',
  candidate_space_exhausted: '候选空间已遍历', disabled: '未启用',
  research_goal_reached: '同一候选满足全部科研目标',
  missing_feature: '保留特征缺失', constant_feature: '保留常量特征',
  invalid_labels: '标签取值异常', duplicate_label_units: '设备标签重复',
  duplicate_history_keys: '设备时间记录冲突', units_without_history: '标签设备缺少历史',
  units_without_labels: '历史设备缺少标签', invalid_time: '时间无法解析',
  future_history: '历史超过 cutoff', invalid_weight: '训练权重异常', invalid_cutoff: 'cutoff 日期异常',
  invalid_numeric_feature: '数值特征无法解析', non_finite_feature: '特征存在无穷值',
};
const pct = (value: number | null | undefined, digits = 2) => value == null ? '未记录' : `${(value * 100).toFixed(digits)}%`;
const integer = (value: number | null | undefined) => value == null ? '未估计' : Math.round(value).toLocaleString('zh-CN');
const seconds = (value: number | null | undefined) => value == null ? '未记录' : `${value.toFixed(1)} 秒`;
const clock = (value: number | null | undefined) => {
  if (value == null) return '未记录';
  return value >= 3600 ? `${(value / 3600).toFixed(1)} 小时` : value >= 60 ? `${(value / 60).toFixed(1)} 分钟` : `${value.toFixed(0)} 秒`;
};
const label = (value: string | null | undefined) => value == null ? '未记录' : labels[value] ?? value;

export function WorkflowResults({ runId, data, pending, error, onRetry }: {
  runId: string; data?: WorkflowResponse; pending: boolean; error: unknown; onRetry: () => void;
}) {
  const [route, setRoute] = useState('all');
  const search = data?.search;
  const trials = search?.trials?.filter((trial) => route === 'all' || trial.route_id === route) ?? [];
  const measured = trials.filter((trial) => trial.score != null && Number.isFinite(trial.score));
  const ceiling = Math.max(100, ...measured.map((trial) => trial.score as number));
  const points = measured.map((trial) => {
    const index = trials.indexOf(trial);
    return `${20 + index * 560 / Math.max(1, trials.length - 1)},${135 - (trial.score as number) / ceiling * 115}`;
  }).join(' ');

  return (
    <section className="flex flex-col gap-3 rounded-card border border-border p-4" data-workflow-results>
      <h2 className="text-sm font-semibold text-fg">数据处理与分层调优</h2>
      {pending ? <p className="text-xs text-fg-muted">正在读取工作流记录…</p> : error ? (
        <ApiErrorPanel title="工作流记录读取失败" error={toApiError(error)} onRetry={onRetry} />
      ) : (
        <>
          <p className="text-xs text-fg-muted">阶段：{label(data?.phase)}；状态：{label(data?.state)}</p>
          {data?.data_state === 'invalid' ? <p role="alert">数据处理记录损坏，结果未知。</p> : data?.data ? (
            <div className="text-xs text-fg-muted">
              <p>训练数据：{label(data.data.state)}；样本 {data.data.before_samples ?? '未记录'} → {data.data.after_samples ?? '未记录'}，
                历史行 {data.data.before_rows ?? '未记录'} → {data.data.after_rows ?? '未记录'}。</p>
              <ul className="mt-2 list-disc pl-5">
                {(data.data.transformations ?? []).map((change, index) => <li key={index}>
                  {change.reason}{change.column ? `（${change.column}）` : ''}，影响 {change.affected} 项。
                </li>)}
              </ul>
              {!data.data.transformations?.length ? <p>未应用会改变训练记录的处理。</p> : null}
              <p>明确保留的问题：{data.data.accepted_issues?.map(label).join('、') || '无'}；
                待解决：{data.data.unresolved_codes?.map(label).join('、') || '无'}。</p>
              <details className="mt-2"><summary className="cursor-pointer">数据指纹与比较口径</summary>
                <p>初始解与全部候选使用同一训练副本。跨实验比较须核对处理规则和指纹。</p>
                <pre className="overflow-auto">{JSON.stringify({ source: data.data.source_sha256, derived: data.data.derived_sha256 }, null, 2)}</pre>
              </details>
            </div>
          ) : <p className="text-xs text-fg-muted">这次运行未记录数据处理与复检。</p>}

          {data?.final_best_score != null ? <div className="flex flex-wrap items-center gap-3 text-sm">
            <span>演化最佳：{number(data.evolution_best_score)}</span>
            <strong>最终最佳：{number(data.final_best_score)}</strong>
            <span className="text-xs text-fg-muted">来源：{label(data.best_origin)}</span>
            {data.best_artifact_id ? <a className="fe-btn fe-btn-secondary fe-btn-sm"
              href={artifactDownloadUrl(runId, data.best_artifact_id)} download>下载最终程序</a> : null}
          </div> : null}

          {data?.effect_state === 'invalid' ? <p role="alert">效果记录损坏，预测性能与复杂度未知。</p> : data?.effect?.solutions?.length ? (
            <div className="flex flex-col gap-2" data-effect-report>
              <h3 className="text-sm font-semibold">预测性能与模型复杂度</h3>
              <div className="overflow-auto"><table className="w-full text-left text-xs">
                <caption className="sr-only">各方案的预测性能与模型复杂度对比</caption>
                <thead><tr><th scope="col">指标</th>{data.effect.solutions.map((item) => <th scope="col" key={item.key}>{item.label}</th>)}</tr></thead>
                <tbody>
                  {([
                    ['综合评分（ROS）', (x) => number(x.performance?.combined_score)],
                    ['精确率', (x) => pct(x.performance?.precision)],
                    ['召回率', (x) => pct(x.performance?.recall)],
                    ['F1', (x) => number(x.performance?.f1)],
                    ['误告率（健康盘被告警）', (x) => pct(x.performance?.false_alarm_rate, 3)],
                    ['漏告率（故障盘未告警）', (x) => pct(x.performance?.missed_detection_rate)],
                    ['每千盘告警数', (x) => x.performance?.alarms_per_1k_disks == null ? '未记录' : x.performance.alarms_per_1k_disks.toFixed(2)],
                    ['模型族', (x) => x.complexity?.model_families?.join('、') || '未识别'],
                    ['估计参数量', (x) => integer(x.complexity?.estimated_parameters)],
                    ['集成成员数', (x) => integer(x.complexity?.ensemble_fits)],
                    ['程序行数 / 分支点', (x) => `${integer(x.complexity?.source_lines)} / ${integer(x.complexity?.branch_points)}`],
                    ['单次验证评估耗时', (x) => seconds(x.complexity?.evaluation_seconds)],
                  ] as [string, (x: EffectSolution) => string][]).map(([name, read]) => <tr key={name}>
                    <th scope="row" className="py-1 font-normal text-fg-muted">{name}</th>
                    {data.effect!.solutions!.map((item) => <td key={item.key}>{read(item)}</td>)}
                  </tr>)}
                </tbody>
              </table></div>
              <p className="text-xs text-fg-muted">
                Token：共 {integer(data.effect.token_usage?.total_tokens)}（生成 {integer(data.effect.token_usage?.generate_tokens)}，
                反思 {integer(data.effect.token_usage?.reflect_tokens)}，Jev {integer(data.effect.token_usage?.jev_tokens)}，
                知识 {integer(data.effect.token_usage?.knowledge_tokens)}）；分层调优 {integer(data.effect.token_usage?.hierarchical_tokens)}，只调用本地评估器。
                墙钟 {seconds(data.effect.token_usage?.wall_time_s)}，每提升 1 分约 {integer(data.effect.token_usage?.tokens_per_score_gain)} token。
              </p>
              {data.effect.convergence ? (() => {
                const c = data.effect.convergence;
                const points = [...(c.evolution_curve ?? []).map((x) => ({ name: `演化第 ${x.round} 轮`, best: x.best_so_far, at: x.elapsed_s })),
                  ...(c.hpo_curve ?? []).map((x) => ({ name: `调优第 ${x.trial} 次`, best: x.best_so_far, at: null as number | null }))];
                return (
                  <div className="flex flex-col gap-1" data-effect-convergence>
                    <h3 className="text-sm font-semibold">迭代收敛速度</h3>
                    <p className="text-xs">
                      {c.target_score == null ? '未设置目标分。' : c.target_reached
                        ? `目标分 ${number(c.target_score)}：第 ${c.rounds_to_target} 轮达到，用时 ${clock(c.time_to_target_s)}，累计 ${integer(c.tokens_to_target)} token。`
                        : `目标分 ${number(c.target_score)}：本次未达到。`}
                      代码演化共 {c.evolution_rounds ?? '未记录'} 轮（{label(c.evolution_stop_reason)}）；
                      分层调优 {c.hpo_trials ?? '未记录'} 次，用时 {clock(c.hpo_elapsed_s)}，最佳出现在第 {c.hpo_best_trial ?? '未记录'} 次（{label(c.hpo_stop_reason)}）。
                    </p>
                    <div className="overflow-auto"><table className="w-full text-left text-xs">
                      <caption className="sr-only">逐轮最佳评分</caption>
                      <thead><tr><th scope="col">阶段</th><th scope="col">截至此刻最佳评分</th><th scope="col">已用时</th></tr></thead>
                      <tbody>{points.map((x) => <tr key={x.name}><td>{x.name}</td><td>{number(x.best)}</td><td>{x.at == null ? '—' : clock(x.at)}</td></tr>)}</tbody>
                    </table></div>
                  </div>
                );
              })() : null}
              {data.effect.automation ? (
                <p className="text-xs" data-effect-automation>
                  <strong>自动化覆盖率 {pct(data.effect.automation.automatic_coverage, 1)}</strong>：
                  共 {integer(data.effect.automation.total_steps)} 步（{integer(data.effect.automation.stages)} 个阶段、
                  {integer(data.effect.automation.evolution_attempts)} 次演化尝试、{integer(data.effect.automation.hpo_trials)} 次调优试验），
                  人工介入 {integer(data.effect.automation.manual_interventions)} 次，
                  {data.effect.automation.end_to_end_unattended ? '全流程无人值守' : '全流程含人工介入'}；
                  自动自愈 {integer(data.effect.automation.self_recovered_failures)} 次，未恢复适配器错误 {integer(data.effect.automation.unrecovered_adapter_errors)} 次。
                </p>
              ) : null}
              <p className="text-xs text-fg-subtle">参数量为静态估计：{data.effect.solutions[0]?.complexity?.parameter_note ?? '未记录'}{data.effect.note}</p>
            </div>
          ) : null}

          {data?.search_state === 'invalid' ? <p role="alert">分层搜索记录损坏，试验数量与评分未知。</p> : search ? (
            <>
              <p className="text-xs text-fg-muted">分层试验 {search.completed_trials ?? '未记录'} / {search.max_trials ?? '未记录'}；
                默认路线评估：{search.default_barrier_open == null ? '未记录' : search.default_barrier_open ? '已完成' : '进行中'}；
                停止原因：{label(search.stop_reason)}。</p>
              <div className="overflow-auto"><table className="w-full text-left text-xs">
                <caption className="sr-only">方法路线与默认参数对比</caption>
                <thead><tr><th>路线</th><th>来源</th><th>默认评分</th><th>最佳评分</th><th>访问次数</th></tr></thead>
                <tbody>{search.routes?.map((item) => <tr key={item.route_id}>
                  <td className="py-1 font-mono">{item.route_id}</td><td>{item.source ?? '未记录'}</td>
                  <td>{number(item.default_score)}</td><td>{number(item.best_score)}</td><td>{item.visits ?? '未记录'}</td>
                </tr>)}</tbody>
              </table></div>
              <label className="text-xs text-fg-muted">筛选路线：
                <select aria-label="筛选分层搜索路线" value={route} onChange={(event) => setRoute(event.target.value)}
                  className="ml-2 rounded border border-border bg-surface p-1">
                  <option value="all">全部路线</option>
                  {search.routes?.map((item) => <option key={item.route_id} value={item.route_id}>{item.route_id}</option>)}
                </select>
              </label>
              {measured.length ? <svg viewBox="0 0 600 160" role="img" aria-label="分层试验实测评分曲线"
                className="max-h-48 w-full text-brand-600">
                <path d="M20 20V135H580" fill="none" stroke="currentColor" opacity="0.3" />
                <polyline points={points} fill="none" stroke="currentColor" strokeWidth="2" />
                {measured.map((trial) => <circle key={trial.candidate_id}
                  cx={20 + trials.indexOf(trial) * 560 / Math.max(1, trials.length - 1)}
                  cy={135 - (trial.score as number) / ceiling * 115} r="3" fill="currentColor">
                  <title>第 {trial.trial_number} 次：{number(trial.score)}</title>
                </circle>)}
                <text x="20" y="155" fontSize="10" fill="currentColor">试验顺序；纵轴评分 0–{ceiling}</text>
              </svg> : <p className="text-xs text-fg-muted">尚无有效实测评分。</p>}
              <div className="max-h-96 overflow-auto"><table className="w-full text-left text-xs">
                <caption className="sr-only">分层搜索试验记录</caption>
                <thead><tr><th>次序</th><th>路线 / 候选</th><th>深度</th><th>评分</th><th>决策</th><th>参数与依据</th></tr></thead>
                <tbody>{trials.map((trial) => <tr key={trial.candidate_id} className="border-t border-border">
                  <td>{trial.trial_number}</td><td className="py-2 font-mono">{trial.route_id}<br />{trial.candidate_id}</td>
                  <td>{trial.depth ?? '未记录'}</td><td>{number(trial.score)}</td>
                  <td>{label(trial.status)} / {label(trial.decision)}</td>
                  <td><details><summary className="cursor-pointer">{trial.changed_parameter ?? '默认参数'}</summary>
                    <pre>{JSON.stringify(trial.parameters, null, 2)}</pre>
                    <p>父候选：{trial.parent_id ?? '无'}；耗时：{number(trial.duration_seconds)} 秒。</p>
                    <p>调度奖励：{number(trial.reward)}；{trial.reason ?? '未记录依据'}</p>
                  </details></td>
                </tr>)}</tbody>
              </table></div>
              <p className="text-xs text-fg-subtle">评分由本地验证评估器产生；调度奖励用于搜索决策。反复选择验证集尚不能证明独立泛化。</p>
            </>
          ) : <p className="text-xs text-fg-muted">这次运行未记录分层搜索试验。</p>}
          {data?.warnings?.map((warning) => <p key={warning.field} className="text-xs text-warning-700">{warning.reason}</p>)}
        </>
      )}
    </section>
  );
}
