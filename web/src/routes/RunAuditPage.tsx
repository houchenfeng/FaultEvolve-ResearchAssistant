/**
 * 数据边界与审计页（PRD 13.4 / TODO 6.4，`/runs/$runId/audit`）。
 *
 * PRD 13.4 列了七项，**契约只支撑得起两项**：部署模式（/api/meta）与制品边界
 * （/api/runs/{id}/artifacts）。其余 PRD 项不在本页展示。
 *
 * 没有任何 audit 端点：`contracts.py` 里唯一叫 audit 的字段是评委初筛计数
 * `screen_audited` / `screen_audit_bad`（`contracts.py:634-635`），与数据边界无关。
 * 本页因此只做客户端能对「实际收到的内容」负责的那部分。
 */
import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from '@tanstack/react-router';

import { AuditFacts } from '@/features/audit/AuditFacts';
import { MetaFacts } from '@/features/audit/MetaFacts';
import {
  DATA_BOUNDARY_STATEMENT,
  artifactStateRows,
  boundaryRows,
  deploymentRows,
  kindRows,
  metaFacts,
  scanProtectedNames,
} from '@/features/audit/audit-logic';
import {
  getRunApiRunsRunIdGet,
  listArtifactsApiRunsRunIdArtifactsGet,
  metaApiMetaGet,
} from '@/generated/api';
import { unwrap } from '@/lib/api';
import { queryKeys } from '@/lib/query-keys';
import { sectionState } from '@/lib/section-state';

export function RunAuditPage() {
  const { runId } = useParams({ from: '/runs/$runId/audit' });

  const metaQuery = useQuery({
    queryKey: queryKeys.meta(),
    queryFn: () => unwrap(metaApiMetaGet()),
    retry: false,
  });

  const artifactsQuery = useQuery({
    queryKey: queryKeys.artifacts(runId),
    queryFn: () => unwrap(listArtifactsApiRunsRunIdArtifactsGet({ path: { run_id: runId } })),
    retry: false,
  });

  // RunLayout 已经用同一个 key 取过运行详情并拦住了失败，这里只是复用缓存。
  const detailQuery = useQuery({
    queryKey: queryKeys.run(runId),
    queryFn: () => unwrap(getRunApiRunsRunIdGet({ path: { run_id: runId } })),
    retry: false,
  });

  const meta = metaQuery.data ?? null;
  const artifacts = artifactsQuery.data?.artifacts;

  return (
    <div className="flex flex-col gap-5" data-audit-page={runId}>
      {/* PRD 13.4 明确要求：纯云端模式下不得宣称「零数据出域」。这句话原样渲染，
          不改写成更强的保证。 */}
      <p
        data-boundary-statement
        className="rounded-card border border-border-subtle bg-surface-muted px-3 py-2 text-xs text-fg-muted"
      >
        {DATA_BOUNDARY_STATEMENT}
      </p>

      <MetaFacts
        state={sectionState(metaQuery.isPending, metaQuery.isError)}
        error={metaQuery.error}
        onRetry={() => void metaQuery.refetch()}
        facts={metaFacts(meta)}
        deployments={deploymentRows(meta)}
      />

      <AuditFacts
        state={sectionState(artifactsQuery.isPending, artifactsQuery.isError)}
        error={artifactsQuery.error}
        onRetry={() => void artifactsQuery.refetch()}
        artifactStates={artifactStateRows(detailQuery.data?.artifact_states)}
        kinds={kindRows(artifacts)}
        boundary={boundaryRows(artifacts)}
        leak={scanProtectedNames(artifacts)}
      />

      <Link
        to="/runs/$runId/results"
        params={{ runId }}
        data-results-link
        className="self-start fe-btn fe-btn-secondary fe-btn-sm text-brand-600 hover:border-brand-500"
      >
        ← 回到结果与报告
      </Link>
    </div>
  );
}
