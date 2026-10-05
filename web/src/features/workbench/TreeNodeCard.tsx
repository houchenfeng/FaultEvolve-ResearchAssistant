/**
 * 进化树节点卡 + 两种图例（PRD §10.1）。
 *
 * 节点卡显示八项：短 ID / 分数或「未评分」/ Δ 或「未记录」/ 算子 / 状态图标+文字 /
 * 是否最优 / 是否有第二父 / 知识卡数。
 *
 * 三条硬约束：
 * 1. **状态不能只靠颜色**（PRD §10.1 明确）—— 每处状态都带文字或符号。
 * 2. **未评分不是 0**（TODO 5.2 明确禁止 `score || 0`）—— 文案由适配层决定，
 *    组件只负责显示，不做二次判断。
 * 3. **八项一个不能少**。概念图（`docs/images/frontend-concepts/02-evolution-workbench.png`）
 *    的卡片只有三层（ID / 分数 / 算子），照着抄会把状态、最优、双亲、卡数挤掉 ——
 *    theme.css 开头写得很清楚：概念图只定**信息层级、布局密度、配色**，
 *    字段一律以 PRD 为准。所以这里保留概念图的"大分数居中"视觉重心，
 *    把另外几项压到首行与末行的小字里。
 */
import { memo } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';

import { EDGE_KIND_LABELS } from '@/features/workbench/reflection';
import {
  explainSignificance,
  significanceAccent,
  SIGNIFICANCE_DASHED_BORDER,
  type Significance,
} from '@/features/workbench/significance';
import { shortId, type TreeFlowNode } from '@/features/workbench/tree-adapter';

/** 状态 → 符号 + 颜色类。文字之外必须有符号，这是 PRD 的硬要求。 */
const STATUS_MARKS: Record<string, { mark: string; className: string }> = {
  pending: { mark: '○', className: 'text-fg-muted' },
  evaluating: { mark: '◐', className: 'text-info-500' },
  done: { mark: '●', className: 'text-success-500' },
  invalid: { mark: '✕', className: 'text-danger-500' },
  abandoned: { mark: '⊘', className: 'text-fg-subtle' },
};

const SIGNIFICANCE_MARKS: Record<Significance, string> = {
  best: '★',
  progress: '↑',
  noise: '≈',
  unknown: '?',
};

/**
 * React Flow 会把选中态、多选态等字段直接传进来，所以 props 从官方的
 * `NodeProps` 派生 —— 自己凭空声明的形状一旦与实际传入的对不上，
 * 运行时才会炸，类型检查却抓不到。
 *
 * 用 `Omit` 剔掉 `draggable` / `zIndex` / `sourcePosition` 这些**本组件
 * 从不读**的字段：留着它们会让 `NodeProps` 变成"6 个字段全必填"，
 * 于是每个调用点（包括测试）都得编造 `dragging: false` 之类的假值 ——
 * 那是在满足类型系统，不是在描述组件真实的输入。
 *
 * 注意折叠相关字段在 **`data` 里**而不是顶层：`NodeProps` 的 `data` 就是
 * `TreeNodeData`，把它们摊到顶层就得自己维护一份同步，迟早漏。
 */
type CardProps = Omit<
  NodeProps<TreeFlowNode>,
  | 'width'
  | 'height'
  | 'draggable'
  | 'dragging'
  | 'zIndex'
  | 'selectable'
  | 'deletable'
  | 'position'
  | 'isConnectable'
  | 'positionAbsoluteX'
  | 'positionAbsoluteY'
  // `Omit` 之后 selected 仍是必填，而交叉类型无法把它改成可选 ——
  // 所以先从源类型里剔掉，再在下面显式声明成可选。
  | 'selected'
> & {
  /** React Flow 一定会传；这里给默认值以便单独渲染卡片（测试、预览）。 */
  selected?: boolean;
};

function TreeNodeCardImpl({ data, selected = false }: CardProps) {
  const { node, hiddenCount = 0, collapsible = false, collapsed = false, onToggleCollapse } = data;
  const status = STATUS_MARKS[node.status] ?? { mark: '·', className: 'text-fg-muted' };
  const verdict = explainSignificance(node);
  const significance = verdict.significance;

  return (
    <div
      className={`relative w-[176px] rounded-md border bg-surface px-2.5 py-1.5 text-left shadow-[var(--shadow-fluent-sm)] transition-all duration-200 ease-out hover:-translate-y-0.5 hover:shadow-[var(--shadow-fluent-md)] ${
        SIGNIFICANCE_DASHED_BORDER[significance] ? 'border-dashed' : 'border-solid'
      } ${selected ? 'ring-2 ring-[#0078d4]/40 ring-offset-2' : ''}`}
      // 边框色走 `var()` 内联样式：主题切换时立即跟着变，不用重算类名。
      style={{ borderColor: significanceAccent(significance) }}
      title={`${node.id}\n${verdict.reason}`}
      data-testid={`tree-node-${node.id}`}
    >
      <Handle type="target" position={Position.Top} className="!size-1.5 !border-border-subtle !bg-surface" />

      {/* 首行：短 ID（左）与显著性标记、最优/双亲标记（右）。 */}
      <div className="flex items-center gap-1">
        <span className="tabular text-[12px] font-semibold text-fg">{shortId(node.id)}</span>
        {node.is_best ? (
          <span
            className="text-[10px] font-medium text-brand-600 dark:text-brand-300"
            title="当前全局最优节点"
          >
            ★ 最优
          </span>
        ) : null}
        {data.hasSecondParent ? (
          <span
            className="text-[10px] text-brand-500"
            title={`此节点由交叉生成，第二父：${(node.second_parent_ids ?? []).map(shortId).join('、')}`}
          >
            ⑂ 双亲
          </span>
        ) : null}
        <span className="flex-1" />
        {/* 状态：符号与文字同时存在（PRD §10.1），且两者必须是**彼此独立的
            文本节点** —— 合成一个字符串会让"色盲用户能否区分"这件事退化成
            "这个字符串长什么样"，测试也抓不到。 */}
        <span className={`inline-flex items-center text-[10px] ${status.className}`} title={`状态：${data.statusLabel}`}>
          <span aria-hidden>{status.mark}</span>
          <span className="ml-0.5">{data.statusLabel}</span>
        </span>
      </div>

      {/* 中间：分数。概念图里它是节点上最重的视觉元素，锚在正中。 */}
      <div className="tabular mt-1 text-center text-[19px] font-semibold leading-none text-fg">
        {data.scoreLabel}
      </div>

      {/* 末行：Δ + 算子徽标（居中），右侧跟知识卡计数。 */}
      <div className="mt-1 flex items-center justify-center gap-1.5 text-[10px]">
        <span
          className={`tabular ${data.bandState === 'outside' ? 'text-success-500' : 'text-fg-subtle'}`}
          title={verdict.reason}
        >
          <span aria-hidden>{SIGNIFICANCE_MARKS[significance]}</span> Δ {data.deltaLabel}
        </span>
        <span className="rounded-pill bg-surface-muted px-1.5 py-px text-fg-muted">
          {data.operatorLabel}
        </span>
        {data.cardCount > 0 ? (
          <span className="text-fg-muted" title={`采纳 ${data.cardCount} 张知识卡`}>
            卡 {data.cardCount}
          </span>
        ) : null}
        {data.injectedCardIds.length > 0 ? (
          <span
            className="text-warning-500"
            title={`${data.injectedCardIds.join('、')}：知识库预置注入，未经过按轮次投放`}
          >
            预置 {data.injectedCardIds.length}
          </span>
        ) : null}
        {data.cardCount > 0 || data.offeredCardCount > 0 ? (
          <span className="text-fg-subtle" title={`本分支共投放 ${data.offeredCardCount} 张卡`}>
            /{data.offeredCardCount}
          </span>
        ) : null}
      </div>

      {collapsible ? (
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onToggleCollapse?.(node.id);
          }}
          className="absolute -bottom-2 left-1/2 -translate-x-1/2 rounded-pill border border-border-subtle bg-surface px-1.5 text-[10px] text-fg-muted hover:border-brand-500 hover:text-brand-600"
          title={collapsed ? '展开子树' : '折叠子树'}
        >
          {collapsed ? `+${hiddenCount}` : '−'}
        </button>
      ) : null}

      <Handle type="source" position={Position.Bottom} className="!size-1.5 !border-border-subtle !bg-surface" />
    </div>
  );
}

export const TreeNodeCard = memo(TreeNodeCardImpl);

/** 线型样例。长度与线宽对齐概念图（22×8，圆头）。 */
function Sample({
  stroke,
  dash,
  width = 1.5,
}: {
  stroke: string;
  dash?: string;
  width?: number;
}) {
  return (
    <svg width="22" height="8" aria-hidden className="shrink-0">
      <line
        x1="1"
        y1="4"
        x2="21"
        y2="4"
        stroke={stroke}
        strokeWidth={width}
        strokeLinecap="round"
        strokeDasharray={dash}
      />
    </svg>
  );
}

/**
 * 边图例（三种关系 + 最优路径）。
 *
 * 「最佳路径」不进 `EDGE_KIND_LABELS` —— 它不是一种**边类型**，而是叠加在
 * 既有边上的一层高亮（见 `TreeCanvas.flowEdges`）。混进边类型表会让下游
 * 以为契约多了一个 `kind`。
 */
export function TreeEdgeLegend() {
  const kinds = ['parent', 'crossover_second_parent', 'repair'] as const;
  const kindStyle: Record<(typeof kinds)[number], { stroke: string; dash?: string }> = {
    parent: { stroke: 'var(--color-border-strong)' },
    crossover_second_parent: { stroke: 'var(--color-brand-500)', dash: '6 4' },
    repair: { stroke: 'var(--color-warning-500)', dash: '2 3' },
  };

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-fg-muted">
      <span className="inline-flex items-center gap-1.5">
        <Sample stroke="var(--color-success-500)" width={2.5} />
        最佳路径
      </span>
      {kinds.map((kind) => (
        <span key={kind} className="inline-flex items-center gap-1.5">
          <Sample stroke={kindStyle[kind].stroke} dash={kindStyle[kind].dash} />
          {EDGE_KIND_LABELS[kind]}
        </span>
      ))}
    </div>
  );
}

/**
 * 显著性图例（四档）。
 *
 * 用**与节点卡同一个** `significanceAccent` 和 `SIGNIFICANCE_DASHED_BORDER` ——
 * 图例与卡片各写一份颜色/线型，迟早会出现"图例说绿、卡片是蓝"。
 * 虚线也要在这里体现，否则用户看到一个虚线节点会以为是渲染坏了。
 */
export function TreeSignificanceLegend() {
  const order: Significance[] = ['best', 'progress', 'noise', 'unknown'];
  const labels: Record<Significance, string> = {
    best: '当前最优',
    progress: '有效改进',
    noise: '噪声内',
    unknown: '无法判断',
  };

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-fg-muted">
      {order.map((significance) => (
        <span key={significance} className="inline-flex items-center gap-1.5">
          <span
            className={`inline-block size-2.5 rounded-[3px] border ${
              SIGNIFICANCE_DASHED_BORDER[significance] ? 'border-dashed' : 'border-solid'
            }`}
            style={{ borderColor: significanceAccent(significance) }}
            aria-hidden
          />
          {labels[significance]}
        </span>
      ))}
    </div>
  );
}
