/**
 * 共享的进程态查询（`/api/runs/{id}/live`）。
 *
 * 单独成文件有两个理由：
 * 1. 同一个 queryKey 被工作台页与控制条同时需要，而**轮询只能由一方拥有** ——
 *    否则两个 observer 各挂一个 interval，同一个端点被问两次。这里用 `poll`
 *    开关把所有权说清楚：控制条轮询，页面只读同一份缓存。
 * 2. `/live` 会**对账**（后端在发现进程已消失时会顺手把注册表那一行收尾），
 *    所以它不是纯粹的读操作，写在页面里当普通 useQuery 很容易被当成可缓存的
 *    只读数据。这里集中写一次，附上语义。
 */
import { useQuery } from '@tanstack/react-query';

import { getRunLiveApiRunsRunIdLiveGet } from '@/generated/api';
import { unwrap } from '@/lib/api';
import { queryKeys } from '@/lib/query-keys';

/** 进程存活时的轮询间隔。只读端点，代价很小；进程一停就不再轮询。 */
export const LIVE_POLL_MS = 2_000;

export function useRunLive(runId: string, options: { poll?: boolean } = {}) {
  const { poll = true } = options;
  return useQuery({
    queryKey: queryKeys.runLive(runId),
    queryFn: () => unwrap(getRunLiveApiRunsRunIdLiveGet({ path: { run_id: runId } })),
    retry: false,
    refetchInterval: (query) =>
      poll && query.state.data?.process_alive === true ? LIVE_POLL_MS : false,
  });
}
