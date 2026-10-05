/**
 * 制品下载地址。
 *
 * 只有一种合法形状：`/api/runs/{run_id}/artifacts/{artifact_id}`，其中
 * `artifact_id` 必须由服务器签发（`ArtifactResponse.artifact_id`）。
 * 后端从不接受也不返回原始路径——`ArtifactResponse` 的 docstring 写明这正是
 * 路径穿越与受保护评测数据不可达的原因（`contracts.py:977-982`），
 * `paths.validate_id` 再用 `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$` 挡掉 `..`
 * （`paths.py:28,33`）。
 *
 * 所以前端**永远不拼路径**：这里只把已经拿到的 id 编码进 URL。
 */
import { API_BASE_URL } from '@/lib/api';

export function artifactDownloadUrl(runId: string, artifactId: string): string {
  return `${API_BASE_URL}/api/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(
    artifactId,
  )}`;
}
