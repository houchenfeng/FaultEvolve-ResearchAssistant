/**
 * 数据边界与审计页的推导逻辑（PRD 13.4 / TODO 6.4）。
 *
 * 先说结论：**PRD 13.4 列的七项里，只有两项有真实数据源。**
 * 没有 audit 端点，也没有 AuditResponse / BoundaryResponse（`sdk.gen.ts` 全 251 行
 * 无 audit 路由；`contracts.py` 里唯一叫 audit 的字段是评委初筛计数
 * `screen_audited` / `screen_audit_bad`，`contracts.py:634-635`，与数据边界无关）。
 *
 * 能如实展示的两项：
 * 1. **当前部署模式** —— `MetaResponse.deployment_modes`（`/api/meta`）。
 * 2. **制品边界** —— `ArtifactResponse`（`/api/runs/{id}/artifacts`）。这一份是
 *    真材料，而且比 PRD 要的更硬：它逐条给出服务器**愿意**谈哪些制品、
 *    其中哪些**拒绝下载**（`downloadable`），id 由服务器签发、原始路径从不返回
 *    （`contracts.py:977-982`）。
 *
 * 其余 PRD 项无对应端点，本页不展示。
 */
import type { ArtifactResponse, MetaResponse } from '@/generated/api';

import { NOT_RECORDED, countCell, type Cell } from '@/features/discovery/card-logic';
// 跨 feature 复用而不是复制一份：两处必须用同一条判定，
// 否则任务页报缺陷、审计页不报，就成了两套标准。
import { detectProtectedNameLeak } from '@/features/intake/task-detail-logic';
import { sizeCell, textCell } from '@/features/results/results-logic';

// --------------------------------------------------------------------------
// 部署模式（/api/meta）
// --------------------------------------------------------------------------

export interface DeploymentRow {
  mode: string;
  available: Cell;
  detail: Cell;
  /**
   * `supported_transports` 原样透传。**这个字段名是错的**：`app.py:221,230,243`
   * 往里填的是 `[mode]`（模式名本身），不是传输方式——真正的传输方式字段是
   * `MetaResponse.stream_transport`。所以界面上这一列只能按字面名渲染，
   * 不能改叫「传输方式」，那会把一个后端命名缺陷讲成事实。
   */
  supportedTransports: string;
  isDefault: boolean;
}

export function deploymentRows(meta: MetaResponse | null | undefined): DeploymentRow[] {
  return (meta?.deployment_modes ?? []).map((entry) => ({
    mode: entry.mode,
    available: { value: entry.available ? '可用' : '不可用', recorded: true },
    detail: textCell(entry.detail),
    supportedTransports: (entry.supported_transports ?? []).join('、') || NOT_RECORDED,
    isDefault: entry.mode === meta?.default_deployment_mode,
  }));
}

// --------------------------------------------------------------------------
// 部署事实（/api/meta 的其余字段）
// --------------------------------------------------------------------------

function boolCell(value: boolean | null | undefined): Cell {
  if (value == null) return { value: NOT_RECORDED, recorded: false };
  return { value: value ? '是' : '否', recorded: true };
}

export interface MetaFactRow {
  label: string;
  cell: Cell;
}

/**
 * 只挑与「浏览器能碰到什么」有关的字段。`nav_modules` / `preset_names` 不列：
 * 它们是功能清单，不是边界事实，列出来只会让这一页看起来比实际查到的更多。
 */
export function metaFacts(meta: MetaResponse | null | undefined): MetaFactRow[] {
  return [
    { label: '契约版本', cell: textCell(meta?.contract_version) },
    { label: '引擎版本', cell: textCell(meta?.engine_version) },
    { label: '引擎提交', cell: textCell(meta?.engine_commit) },
    { label: '流式传输方式', cell: textCell(meta?.stream_transport) },
    { label: '需要鉴权', cell: boolCell(meta?.auth_required) },
    { label: '允许浏览器控制进程', cell: boolCell(meta?.process_control_enabled) },
    { label: '任务目录已配置', cell: boolCell(meta?.task_catalog_available) },
    { label: '服务器档案已配置', cell: boolCell(meta?.server_profiles_enabled) },
  ];
}

// --------------------------------------------------------------------------
// 运行制品状态（run_summary 视角，与 /artifacts 清单是两个来源）
// --------------------------------------------------------------------------

/**
 * `RunDetailResponse.artifact_states` 的键是自由字符串，值是 `ArtifactState`。
 * 这里按值原样渲染，**不解释**：`missing` 表示这份运行的某个核心制品读不到，
 * 与 `/artifacts` 清单里「不存在的文件根本不出现」是两套语义（见
 * `ARTIFACT_LIST_NOTE`），混为一谈会让读者以为清单在说谎。
 */
export interface ArtifactStateRow {
  name: string;
  state: string;
}

export function artifactStateRows(
  states: Record<string, string> | null | undefined,
): ArtifactStateRow[] {
  return Object.entries(states ?? {})
    .map(([name, state]) => ({ name, state }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

// --------------------------------------------------------------------------
// 制品边界（/api/runs/{id}/artifacts）
// --------------------------------------------------------------------------

export interface BoundaryRow {
  artifactId: string;
  kind: string;
  displayName: string;
  mediaType: Cell;
  sizeBytes: Cell;
  state: string;
  downloadable: boolean;
}

export function boundaryRows(artifacts: ArtifactResponse[] | undefined): BoundaryRow[] {
  return (artifacts ?? [])
    .map((item) => ({
      artifactId: item.artifact_id,
      kind: item.kind,
      displayName: item.display_name,
      mediaType: textCell(item.media_type),
      sizeBytes: sizeCell(item.size_bytes),
      state: item.state,
      downloadable: item.downloadable === true,
    }))
    .sort((a, b) => a.kind.localeCompare(b.kind) || a.displayName.localeCompare(b.displayName));
}

export interface KindRow {
  kind: string;
  count: Cell;
  /** 该 kind 下是否存在可下载条目；同一 kind 不会一半可下载一半不可，
   *  但这里仍按实际数据算，不把 `_NON_DOWNLOADABLE_KINDS` 硬编码到前端。 */
  downloadable: Cell;
}

export function kindRows(artifacts: ArtifactResponse[] | undefined): KindRow[] {
  const byKind = new Map<string, ArtifactResponse[]>();
  for (const item of artifacts ?? []) {
    const bucket = byKind.get(item.kind);
    if (bucket) bucket.push(item);
    else byKind.set(item.kind, [item]);
  }
  return [...byKind.keys()]
    .sort()
    .map((kind) => {
      const bucket = byKind.get(kind) ?? [];
      const any = bucket.some((item) => item.downloadable === true);
      const all = bucket.every((item) => item.downloadable === true);
      return {
        kind,
        count: countCell(bucket.length),
        downloadable: { value: all ? '是' : any ? '部分' : '否', recorded: true },
      };
    });
}

// --------------------------------------------------------------------------
// 禁止字段扫描（客户端对「实际收到的内容」再查一遍）
// --------------------------------------------------------------------------

/**
 * 这是 PRD 13.4「是否检测到禁止字段」唯一能如实回答的做法：
 * 扫**浏览器实际收到的**制品名，而不是去问后端「你干净吗」。
 *
 * 与任务页同一条纪律（§12.5）：查到就大声报缺陷，但**只报数量、不渲染名字**——
 * 名字本身就是不该出现在页面上的内容。
 */
export interface LeakScan {
  /** 实际扫过多少个名字。 */
  scanned: Cell;
  /** 命中数。只报数量，名字本身不渲染。 */
  leaked: number;
}

export function scanProtectedNames(
  artifacts: ArtifactResponse[] | undefined,
  extraNames: Array<string | null | undefined> = [],
): LeakScan {
  const names = [
    ...(artifacts ?? []).map((item) => item.display_name),
    ...(artifacts ?? []).map((item) => item.artifact_id),
    ...extraNames,
  ];
  return {
    scanned: countCell(names.length),
    leaked: detectProtectedNameLeak(names).length,
  };
}

/**
 * PRD 13.4 明确要求：**本期纯云端模式下不得宣称「零数据出域」**，
 * 应表述为「数据位于受控云端环境，浏览器不直接访问原始数据」。
 * 这句话原样渲染，不改写成更强的保证。
 */
export const DATA_BOUNDARY_STATEMENT =
  '数据位于受控云端环境，浏览器不直接访问原始数据。本页面不宣称「零数据出域」。';

/**
 * 关于制品清单的一条真实边界性质，值得写出来因为它反直觉：
 * `_artifact_entries` 的 `add()` 在 `path.is_file()` 为假时直接 return
 * （`replay_service.py:1526-1527`），`artifact_catalog` 又把每条都标成
 * `ArtifactState.AVAILABLE`（`replay_service.py:1591`）。
 * ⇒ 不存在的文件**根本不出现在清单里**，所以 `state` 恒为 available；
 * 「清单里没有」和「state = missing」是两回事，后者在制品清单里不会出现。
 */
export const ARTIFACT_LIST_NOTE =
  '清单只列出运行目录下真实存在的文件：不存在的直接不出现，因此这里的 state 恒为 available。' +
  '「清单里没有某一项」表示服务器根本没有它，不表示它存在但读不到。';
