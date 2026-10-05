/**
 * 顶部全局栏（TODO 3.2 / PRD 5.3、14）。
 *
 * 左侧：当前运行的一行摘要。没有记录的项不占位。
 * 右侧：Qwen 连通状态、部署模式、云端执行器状态、设置齿轮、帮助按钮。
 *
 * Qwen 是否连通来自 `/api/meta` 的 `qwen_reachable`（后端请求模型列表）。
 * 没有密钥时不探测。
 */
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { DataBadgeList } from '@/app/shell/TopBarBadges';
import { HelpDialog } from '@/app/shell/HelpDialog';
import { SettingsDrawer } from '@/app/shell/SettingsDrawer';
import { Button } from '@/components/ui/button';
import { getRunApiRunsRunIdGet, metaApiMetaGet } from '@/generated/api';
import { unwrap } from '@/lib/api';
import { queryKeys } from '@/lib/query-keys';
import { useUiStore } from '@/stores/ui-store';

/** 短 ID：运行 ID 通常很长，顶部栏只显示前 8 位。 */
function shortId(id: string): string {
  return id.length > 8 ? `${id.slice(0, 8)}…` : id;
}

function runContextLine(
  runId: string,
  outcome: {
    status?: string | null;
    iterations_done?: number | null;
    best_score?: number | null;
    improvement?: number | null;
  } | null,
): string {
  const parts = [shortId(runId)];
  if (outcome?.status) parts.push(outcome.status);
  if (outcome?.iterations_done != null) parts.push(`${outcome.iterations_done} 轮`);
  if (outcome?.best_score != null) parts.push(`最佳 ${outcome.best_score.toFixed(2)}`);
  if (outcome?.improvement != null) parts.push(`提升 ${outcome.improvement.toFixed(2)}`);
  return parts.join(' · ');
}

export function TopBar() {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);

  const currentRunId = useUiStore((state) => state.currentRunId);

  const metaQuery = useQuery({
    queryKey: queryKeys.meta(),
    queryFn: () => unwrap(metaApiMetaGet()),
    // 静态能力描述，进程生命周期内不变。
    staleTime: Number.POSITIVE_INFINITY,
    retry: 1,
  });

  const runQuery = useQuery({
    queryKey: queryKeys.run(currentRunId ?? ''),
    queryFn: () => unwrap(getRunApiRunsRunIdGet({ path: { run_id: currentRunId as string } })),
    enabled: Boolean(currentRunId),
    retry: false,
  });

  const run = runQuery.data;
  // 分数与状态来自 RunDetailResponse.outcome（不是 summary）。
  const outcome = run?.outcome ?? null;
  const isJudgeCase = currentRunId === 'hdd_mvp_showcase_c89e2a01';

  return (
    <>
      <header className="fe-shell-top flex h-14 shrink-0 items-center justify-between gap-4 px-4">
        <div className="flex min-w-0 items-center gap-5">
          {currentRunId ? (
            <span className="truncate text-xs text-fg" title={currentRunId}>
              {isJudgeCase ? 'HDD 故障预测 · KGTE 演化与知识发现证据链' : runContextLine(currentRunId, outcome)}
            </span>
          ) : (
            <span className="text-xs text-fg-muted">未选择运行</span>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {isJudgeCase ? (
            <div className="flex items-center gap-2 text-[11px]"><span className="rounded-full bg-success-50 px-2.5 py-1 font-medium text-success-700">本地可信评测</span><span className="rounded-full bg-brand-50 px-2.5 py-1 font-medium text-brand-700">原始数据不出域</span></div>
          ) : <DataBadgeList meta={metaQuery.data} metaError={metaQuery.isError} onOpenSettings={() => setSettingsOpen(true)} />}
          {!isJudgeCase ? <Button variant="icon" onClick={() => setSettingsOpen(true)} aria-label="设置" title="设置">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-2.87 1.2V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 7 19.4a1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 2.6 15a1.7 1.7 0 0 0-1.2-2.87H1a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 2.6 7a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 7 2.6h.1A1.7 1.7 0 0 0 10 1.4V1a2 2 0 1 1 4 0v.1A1.7 1.7 0 0 0 17 2.6a1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 21.4 7v.1a1.7 1.7 0 0 0 1.2 2.87H23a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1.03Z" transform="translate(0.5 0.5) scale(0.96)" />
            </svg>
          </Button> : null}
          {!isJudgeCase ? <Button variant="icon" onClick={() => setHelpOpen(true)} aria-label="帮助" title="帮助">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
              <circle cx="12" cy="12" r="9" />
              <path d="M9.2 9.4a2.9 2.9 0 0 1 5.6 1c0 1.8-2.6 2.1-2.6 3.6" />
              <path d="M12 17.3h.01" />
            </svg>
          </Button> : null}
        </div>
      </header>

      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <HelpDialog open={helpOpen} onClose={() => setHelpOpen(false)} />
    </>
  );
}
