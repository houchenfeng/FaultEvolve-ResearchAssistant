/**
 * 任务详情页的推导逻辑（PRD §7.8 四个区）。
 *
 * 与 TaskDetailPanel 分文件：react-refresh 要求组件文件只导出组件，
 * 这些纯函数要被测试直接引用（同 task-artifacts-logic.ts 的分工）。
 *
 * 贯穿全文件的一条规则：**后端没给的字段就写「未记录」或「暂不支持」，
 * 绝不在前端补算**（PRD §2.2 评分唯一来源 / §2.3 真实优先于完整）。
 */
import type {
  TaskDatasetCardResponse,
  TaskDetailResponse,
  TaskReadinessResponse,
} from '@/generated/api';

// --------------------------------------------------------------------------
// 区 3：就绪检查
// --------------------------------------------------------------------------

/** 三态而非五态：本页只陈述事实，不表达「用户还没填」。 */
export type ReadinessState = 'pass' | 'fail' | 'unknown';

export interface ReadinessRow {
  id: 'data' | 'evaluator' | 'init' | 'prompt' | 'knowledge' | 'qwen';
  label: string;
  state: ReadinessState;
  detail: string;
}

/**
 * Qwen 状态永远取不到：它不在任务就绪检查里，而是服务器探测的
 * `llm_key_present`（`execution_backend.py`）。任务页不去猜一个服务器的密钥状态。
 */
const QWEN_ROW_DETAIL =
  '未检查。Qwen 密钥状态属于服务器探测（/api/servers/{id}/probe 的 llm_key_present），' +
  '不是任务属性；本页不代替服务器探测下结论。';

function fileRowState(
  detail: TaskDetailResponse | null,
  filename: string,
): { state: ReadinessState; detail: string } {
  if (!detail) return { state: 'unknown', detail: '未记录' };
  if (!detail.required_files.includes(filename)) {
    return { state: 'unknown', detail: `不是该任务的必需文件（必需项：${detail.required_files.join('、') || '无'}）` };
  }
  if (detail.missing_files.includes(filename)) {
    return { state: 'fail', detail: '文件缺失' };
  }
  return { state: 'pass', detail: '存在' };
}

/**
 * PRD §7.8 区 3 点名的六项：数据、evaluator、init、prompt、知识卡、Qwen。
 *
 * `pending` / `error` 时全部降为 `unknown`：把「还没查到」显示成「失败」
 * 会冤枉任务，显示成「通过」会骗人。
 * 阻塞项清单（`readiness.checks`）另由 `deriveBlockers` 处理，两者不混：
 * 六个检查项是**固定六行的状态表**，阻塞项是后端给出的**变长问题列表**。
 */
export function deriveReadinessRows(input: {
  detail: TaskDetailResponse | null;
  card: TaskDatasetCardResponse | null;
  pending: boolean;
  error: boolean;
}): ReadinessRow[] {
  const { detail, card, pending, error } = input;
  const unavailable = pending || error;

  if (unavailable || !card) {
    // `error` 指的是驱动这六行的那个请求（/api/tasks/{id}/card）失败了。
    const detailText = error ? '任务卡请求失败，无法判定' : '正在读取…';
    return (
      [
        ['data', '数据'],
        ['evaluator', 'evaluator'],
        ['init', '初始算法 init'],
        ['prompt', 'prompt'],
        ['knowledge', '知识卡'],
        ['qwen', 'Qwen'],
      ] as Array<[ReadinessRow['id'], string]>
    ).map(([id, label]) => ({
      id,
      label,
      state: 'unknown' as ReadinessState,
      detail: id === 'qwen' ? QWEN_ROW_DETAIL : detailText,
    }));
  }

  // 这两处会被拼进说明文本，所以也要过一遍受保护名称：
  // `deriveFileListing` 只覆盖 detail 的四个清单，漏掉这里等于留了个出口。
  const missing = (card.data_missing ?? []).filter((name) => !isProtected(name));
  const safeDataDirs = (detail?.data_dirs ?? []).filter((name) => !isProtected(name));
  const promptRow = fileRowState(detail, 'prompt.md');

  const knowledgeDetail = (() => {
    if (!detail) return '未记录';
    if (!detail.knowledge_enabled) return '该任务未启用知识注入';
    return card.knowledge_card_count != null
      ? `${card.knowledge_card_count} 张`
      : '已启用，但卡片数量未记录';
  })();

  return [
    {
      id: 'data',
      label: '数据',
      state: card.data_ready ? 'pass' : 'fail',
      detail:
        missing.length > 0
          ? `缺少 ${missing.length} 个文件：${missing.join('、')}`
          : card.data_ready
            ? `已就绪（数据目录：${safeDataDirs.join('、') || '无'}）`
            : '未就绪',
    },
    {
      id: 'evaluator',
      label: 'evaluator',
      state: card.evaluator_ready ? 'pass' : 'fail',
      detail: card.evaluator_ready
        ? '可解析（仓库内置，只读）'
        : '未找到可解析的 evaluator.py',
    },
    {
      id: 'init',
      label: '初始算法 init',
      state: card.init_ready ? 'pass' : 'fail',
      detail: card.init_ready ? '可解析' : '未找到可解析的 init.py',
    },
    { id: 'prompt', label: 'prompt', state: promptRow.state, detail: promptRow.detail },
    {
      id: 'knowledge',
      label: '知识卡',
      // 知识注入是可选能力：没启用不是缺陷，故永不判 fail；
      // 只有 detail 请求失败（拿不到 knowledge_enabled）才是 unknown。
      state: detail ? 'pass' : 'unknown',
      detail: knowledgeDetail,
    },
    { id: 'qwen', label: 'Qwen', state: 'unknown', detail: QWEN_ROW_DETAIL },
  ];
}

/** `readiness.checks` 只列阻塞项（后端契约如此），空数组 = 没有阻塞。 */
export function deriveBlockers(
  readiness: TaskReadinessResponse | null,
  pending: boolean,
  error: boolean,
): { ready: boolean | null; checks: Array<{ field: string; reason: string }> } {
  if (pending || error || !readiness) return { ready: null, checks: [] };
  return { ready: readiness.ready, checks: readiness.checks ?? [] };
}

// --------------------------------------------------------------------------
// 区 2：评价契约
// --------------------------------------------------------------------------

export interface ScoreContractRow {
  label: string;
  value: string;
  /** `not_recorded` = 契约里有这个字段但没有值。 */
  state: 'value' | 'not_recorded';
}

const TARGET_DIRECTION_LABEL: Record<string, string> = {
  higher: '越大越好',
  lower: '越小越好',
};

/**
 * `score_source` 的取值来自后端；未知取值原样显示而不是映射成中文，
 * 免得把一个新枚举悄悄翻译成「未记录」。
 */
export function scoreSourceLabel(source: string | null | undefined): string {
  if (!source || source === 'unavailable') return '无（尚未有真实评估产生过分数）';
  return source;
}

/**
 * PRD §7.8 区 2：契约里只有 `TaskCardMetrics` 的字段；**不在前端写出公式**，
 * 公式一旦由前端硬编码，就成了第二个评分真源（PRD §2.2 禁止）。
 */
export function deriveScoreContractRows(
  card: TaskDatasetCardResponse | null,
  pending: boolean,
  error: boolean,
): ScoreContractRow[] {
  if (pending || error || !card) {
    return [
      { label: '主指标', value: error ? '请求失败' : '正在读取…', state: 'not_recorded' },
      { label: '目标方向', value: '—', state: 'not_recorded' },
      { label: '目标分数', value: '—', state: 'not_recorded' },
      { label: '初始基线分', value: '—', state: 'not_recorded' },
      { label: '评分来源', value: '—', state: 'not_recorded' },
    ];
  }

  const metrics = card.metrics ?? null;
  const direction = metrics?.target_direction ?? null;

  return [
    {
      label: '主指标',
      value: metrics?.primary_metric || '未记录',
      state: metrics?.primary_metric ? 'value' : 'not_recorded',
    },
    {
      label: '目标方向',
      value: direction ? (TARGET_DIRECTION_LABEL[direction] ?? direction) : '未记录',
      state: direction ? 'value' : 'not_recorded',
    },
    {
      label: '目标分数',
      value: metrics?.target_score != null ? String(metrics.target_score) : '未记录',
      state: metrics?.target_score != null ? 'value' : 'not_recorded',
    },
    {
      label: '初始基线分',
      // PRD §7.3：未试跑时显示「待评估」，不得显示假定分数。
      value: metrics?.initial_score != null ? String(metrics.initial_score) : '待评估',
      state: metrics?.initial_score != null ? 'value' : 'not_recorded',
    },
    {
      label: '评分来源',
      value: scoreSourceLabel(metrics?.score_source),
      state: metrics?.score_source && metrics.score_source !== 'unavailable' ? 'value' : 'not_recorded',
    },
  ];
}

// --------------------------------------------------------------------------
// 区 1：任务说明与安全边界
// --------------------------------------------------------------------------

/**
 * 后端 `_data_dirs` / `data_missing` 已用引擎自己的 `FORBIDDEN_PATTERNS`
 * 过滤掉受保护名称（`task_service.PROTECTED_NAME_RE`）。这里再查一遍：
 * 万一有漏网的，**大声报缺陷**而不是悄悄丢掉——静默过滤会让一个后端
 * 缺陷看起来像「这个任务没有 holdout 目录」。
 */
export function detectProtectedNameLeak(names: Array<string | null | undefined>): string[] {
  return names.filter((name): name is string => Boolean(name) && /holdout/i.test(name as string));
}

function isProtected(name: string): boolean {
  return /holdout/i.test(name);
}

/**
 * 文件清单：只用后端给的名字，前端不拼路径、不提供下载。
 *
 * `leak` 里的名字**已经从四个列表中剔除**，UI 只报数量不渲染名字本身
 * （PRD §7.8：不得展示 holdout 内容——名字也算）。
 */
export function deriveFileListing(detail: TaskDetailResponse | null): {
  required: string[];
  missing: string[];
  candidates: string[];
  dataDirs: string[];
  leak: string[];
} {
  if (!detail) return { required: [], missing: [], candidates: [], dataDirs: [], leak: [] };
  const required = detail.required_files ?? [];
  const missing = detail.missing_files ?? [];
  const candidates = detail.candidate_files ?? [];
  const dataDirs = detail.data_dirs ?? [];
  const all = [...required, ...missing, ...candidates, ...dataDirs];
  const drop = (names: string[]) => names.filter((name) => !isProtected(name));
  return {
    required: drop(required),
    missing: drop(missing),
    candidates: drop(candidates),
    dataDirs: drop(dataDirs),
    leak: detectProtectedNameLeak(all),
  };
}
