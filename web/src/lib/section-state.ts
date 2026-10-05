/**
 * 一节内容的三态。
 *
 * 放在 `lib/` 而不是某个 feature 里，是因为结果页与审计页都要用：
 * 跨 feature 互相借用类型会让「审计依赖结果」这种假关系出现在 import 图上。
 *
 * 挂在 `data-*-state` 属性上给测试当**落定信号**：一节内容在 pending / error /
 * ready 三种状态下渲染的东西完全不同，靠文案猜会在 pending 阶段读到占位值
 * （知识卡页最初 31 个红就是这个成因，见 docs/plans/WEBUI_BASELINE.md §14.5）。
 */
export type SectionState = 'pending' | 'error' | 'ready';

export function sectionState(isPending: boolean, isError: boolean): SectionState {
  return isPending ? 'pending' : isError ? 'error' : 'ready';
}
