/**
 * 一个统计值的行内渲染。
 *
 * 与 `KnowledgeCardList` 里的 `StatCell` 分工：那个必须是 `<td>`（表格语义），
 * 这个是行内 `<span>`，用在现象卡与计数组的定义列表里。两者共享同一条规则：
 * `recorded=false` 时值一定是「未记录」，并用弱化颜色 + `data-recorded` 标出来，
 * 让「查不到」在视觉上和 0 明确区分（PRD §2.3）。
 */
import type { Cell } from '@/features/discovery/card-logic';

export interface StatValueProps {
  cell: Cell;
  /** 测试钩子名，例如 `effect` / `ci_low`。省略则不写该属性。 */
  name?: string;
  className?: string;
}

export function StatValue({ cell, name, className }: StatValueProps) {
  return (
    <span
      data-stat={name}
      data-recorded={cell.recorded ? 'true' : 'false'}
      className={`tabular ${cell.recorded ? 'text-fg' : 'text-fg-subtle'} ${className ?? ''}`}
    >
      {cell.value}
    </span>
  );
}
