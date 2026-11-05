/**
 * 摘要交换层的查询（`/api/runs/{id}/summaries`）。
 *
 * 单独成文件与 `use-run-live.ts` 同理由：一个 queryKey 可能被工作台与结果页
 * 同时需要，轮询所有权必须只有一个 —— 运行在跑时每 3 秒跟着制品一起刷新，
 * 运行结束就不再有理由轮询一个只读回放端点。
 */
import { useQuery } from '@tanstack/react-query';

import { getSummariesApiRunsRunIdSummariesGet } from '@/generated/api';
import { unwrap } from '@/lib/api';
import { queryKeys } from '@/lib/query-keys';

/** 与工作台制品轮询同频：交换记录是随运行一起落盘的。 */
export const SUMMARIES_POLL_MS = 3_000;

export function useRunSummaries(runId: string, options: { poll?: boolean; enabled?: boolean } = {}) {
  const { poll = false, enabled = true } = options;
  return useQuery({
    queryKey: queryKeys.summaries(runId),
    queryFn: () => unwrap(getSummariesApiRunsRunIdSummariesGet({ path: { run_id: runId } })),
    retry: false,
    refetchInterval: poll ? SUMMARIES_POLL_MS : false,
    enabled,
  });
}
