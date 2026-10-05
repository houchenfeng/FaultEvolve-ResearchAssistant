/**
 * 树的搜索与筛选面板（PRD §10.2 第 5–6 条）。
 *
 * 只改显示，不改底层树（PRD §10.5）。筛选条件由父组件持有，
 * 本组件是无状态的受控表单。
 */
import { useState } from 'react';

import type { NodeStatus, OperatorType, TreeNodeDto } from '@/generated/api';
import { significanceCounts, type Significance } from '@/features/workbench/significance';
import { EMPTY_TREE_FILTER, type TreeFilter } from '@/features/workbench/tree-adapter';

const STATUS_OPTIONS: Array<{ value: NodeStatus; label: string }> = [
  { value: 'pending', label: '待评估' },
  { value: 'evaluating', label: '评估中' },
  { value: 'done', label: '已完成' },
  { value: 'invalid', label: '非法' },
  { value: 'abandoned', label: '已放弃' },
];

const OPERATOR_OPTIONS: Array<{ value: OperatorType; label: string }> = [
  { value: 'init', label: '初始程序' },
  { value: 'refine', label: '精炼' },
  { value: 'crossover', label: '交叉' },
  { value: 'repair', label: '修复' },
  { value: 'recall_focus', label: '召回聚焦' },
  { value: 'threshold_calibrate', label: '阈值校准' },
  { value: 'inject', label: '注入' },
  { value: 'transplant', label: '移植' },
];

const SIGNIFICANCE_LABELS: Record<Significance, string> = {
  best: '当前最优',
  progress: '有效改进',
  noise: '噪声内',
  unknown: '无法判断',
};

export interface TreeFiltersProps {
  filter: TreeFilter;
  onChange: (filter: TreeFilter) => void;
  nodes: TreeNodeDto[];
  /** 折叠导致的隐藏节点数（不是筛选造成的）。 */
  collapsedCount: number;
}

export function TreeFilters({ filter, onChange, nodes, collapsedCount }: TreeFiltersProps) {
  const [keyword, setKeyword] = useState(filter.keyword);
  const counts = significanceCounts(nodes);
  const isDefault =
    filter.keyword === '' &&
    !filter.bestPathOnly &&
    !filter.withinBandOnly &&
    !filter.scoredOnly &&
    filter.hiddenStatuses.length === 0 &&
    filter.operators.length === 0;

  const toggle = <K extends keyof TreeFilter>(key: K, value: TreeFilter[K]) => {
    onChange({ ...filter, [key]: value });
  };

  const toggleInArray = <T,>(list: T[], value: T): T[] =>
    list.includes(value) ? list.filter((item) => item !== value) : [...list, value];

  return (
    <div className="flex flex-col gap-2 border-b border-border-subtle bg-surface px-3 py-2">
      <div className="flex items-center gap-2">
        <input
          type="search"
          value={keyword}
          placeholder="搜索节点 ID、算子或意图"
          onChange={(event) => setKeyword(event.target.value)}
          onBlur={() => toggle('keyword', keyword)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') toggle('keyword', keyword);
          }}
          className="min-w-48 flex-1 fe-input fe-input-sm py-1 text-[12px]"
        />
        {!isDefault ? (
          <button
            type="button"
            onClick={() => {
              setKeyword('');
              onChange(EMPTY_TREE_FILTER);
            }}
            className="rounded-card border border-border-subtle px-2 py-1 text-[11px] text-fg-muted hover:border-brand-500 hover:text-brand-600"
          >
            清除筛选
          </button>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
        <FilterChip
          active={filter.bestPathOnly}
          onClick={() => toggle('bestPathOnly', !filter.bestPathOnly)}
          title="只显示当前最优路径上的节点"
        >
          最优路径
        </FilterChip>
        <FilterChip
          active={filter.withinBandOnly}
          onClick={() => toggle('withinBandOnly', !filter.withinBandOnly)}
          title="只显示 Δ 落在噪声带内的节点（不能作为改进证据）"
        >
          仅噪声内
        </FilterChip>
        <FilterChip
          active={filter.scoredOnly}
          onClick={() => toggle('scoredOnly', !filter.scoredOnly)}
          title="隐藏尚未评分的节点"
        >
          仅已评分
        </FilterChip>

        <span className="mx-1 h-3 w-px bg-border-subtle" />

        {STATUS_OPTIONS.map((option) => (
          <FilterChip
            key={option.value}
            active={filter.hiddenStatuses.includes(option.value)}
            onClick={() => toggle('hiddenStatuses', toggleInArray(filter.hiddenStatuses, option.value))}
            title={`隐藏「${option.label}」状态的节点`}
          >
            隐藏{option.label}
          </FilterChip>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
        <span className="text-fg-subtle">算子</span>
        {OPERATOR_OPTIONS.map((option) => (
          <FilterChip
            key={option.value}
            active={filter.operators.includes(option.value)}
            onClick={() => toggle('operators', toggleInArray(filter.operators, option.value))}
          >
            {option.label}
          </FilterChip>
        ))}
      </div>

      {/* `data-testid` 是给 E2E 的：四档显著性必须**每档都有节点**才谈得上
          "分档视觉可辨"，这条断言需要一个稳定的落点，光靠中文文案会被改文案打断。 */}
      <div
        className="flex flex-wrap items-center gap-2 text-[11px] text-fg-muted"
        data-testid="significance-summary"
      >
        <span>显著性分布</span>
        {(['best', 'progress', 'noise', 'unknown'] as const).map((key) => (
          <span key={key} className="inline-flex items-center gap-1">
            <span className="tabular text-fg">{counts[key]}</span>
            {SIGNIFICANCE_LABELS[key]}
          </span>
        ))}
        {collapsedCount > 0 ? (
          <span className="text-fg-subtle">（另有 {collapsedCount} 个节点被折叠隐藏）</span>
        ) : null}
      </div>
    </div>
  );
}

function FilterChip({
  active,
  onClick,
  title,
  children,
}: {
  active: boolean;
  onClick: () => void;
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-pressed={active}
      className={`rounded-pill border px-2 py-0.5 transition-colors ${
        active
          ? 'border-brand-500 bg-brand-50 text-brand-600 dark:bg-brand-500/10 dark:text-brand-300'
          : 'border-border-subtle text-fg-muted hover:border-border-strong hover:text-fg'
      }`}
    >
      {children}
    </button>
  );
}
