/**
 * 稳定 query key 工厂。
 *
 * 手写常量而不是自动生成：key 的形状一旦变化会让全部缓存失效，
 * 必须受控且可审查（TODO 3.4「为 runs、tree、events、node、discovery、reports
 * 定义稳定 query key」）。
 */
export const queryKeys = {
  meta: () => ['meta'] as const,
  health: () => ['health'] as const,

  tasks: () => ['tasks'] as const,
  taskList: () => [...queryKeys.tasks(), 'list'] as const,
  task: (taskId: string) => [...queryKeys.tasks(), 'detail', taskId] as const,
  taskCard: (taskId: string) => [...queryKeys.tasks(), 'card', taskId] as const,
  taskReadiness: (taskId: string) => [...queryKeys.tasks(), 'readiness', taskId] as const,

  servers: () => ['servers'] as const,
  serverList: () => [...queryKeys.servers(), 'list'] as const,
  serverProbe: (profileId: string) => [...queryKeys.servers(), 'probe', profileId] as const,
  serverPathProbe: (profileId: string, path: string) =>
    [...queryKeys.servers(), 'path-probe', profileId, path] as const,

  presets: () => ['presets'] as const,
  presetList: () => [...queryKeys.presets(), 'list'] as const,
  presetMerge: (name: string, patch: unknown) =>
    [...queryKeys.presets(), 'merge', name, patch] as const,

  runs: () => ['runs'] as const,
  runList: () => [...queryKeys.runs(), 'list'] as const,
  run: (runId: string) => [...queryKeys.runs(), 'detail', runId] as const,
  /**
   * 进程态（`/live`），与回放态（`run`/`tree`/…）分开。
   *
   * 单独一个 key 而不是复用 `run`：`run` 读的是磁盘上的制品，`live` 读的是
   * 注册表里的进程，二者会不一致（目录有、注册表没有，或反之），混用会让
   * 缓存把两种真相揉成一个。
   */
  runLive: (runId: string) => [...queryKeys.runs(), 'live', runId] as const,
  tree: (runId: string) => [...queryKeys.runs(), 'tree', runId] as const,
  node: (runId: string, nodeId: string) => [...queryKeys.runs(), 'node', runId, nodeId] as const,
  events: (runId: string, afterId: number | null = null, limit: number | null = null) =>
    [...queryKeys.runs(), 'events', runId, { afterId, limit }] as const,
  scores: (runId: string) => [...queryKeys.runs(), 'scores', runId] as const,
  leaderboard: (runId: string) => [...queryKeys.runs(), 'leaderboard', runId] as const,
  knowledgeCards: (runId: string) => [...queryKeys.runs(), 'knowledge-cards', runId] as const,
  insights: (runId: string) => [...queryKeys.runs(), 'insights', runId] as const,
  discovery: (runId: string) => [...queryKeys.runs(), 'discovery', runId] as const,
  artifacts: (runId: string) => [...queryKeys.runs(), 'artifacts', runId] as const,
  reportManifest: (runId: string) => [...queryKeys.runs(), 'report-manifest', runId] as const,
} as const;

/** 一个运行下全部缓存的公共前缀，用于运行结束后批量失效（阶段 8 使用）。 */
export function runScopedKeys(runId: string) {
  return [
    queryKeys.run(runId),
    queryKeys.runLive(runId),
    queryKeys.tree(runId),
    queryKeys.events(runId),
    queryKeys.scores(runId),
    queryKeys.leaderboard(runId),
    queryKeys.knowledgeCards(runId),
    queryKeys.insights(runId),
    queryKeys.discovery(runId),
    queryKeys.artifacts(runId),
    queryKeys.reportManifest(runId),
  ];
}
