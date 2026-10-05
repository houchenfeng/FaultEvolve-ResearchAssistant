/**
 * 知识注入选项（TODO 4.5 / PRD §7.6，决策 D-C=C1）。
 *
 * 只提供能映射到真实引擎字段的四项。「选择已有知识类别」在引擎的
 * KnowledgeConfig 里没有对应字段，因此诚实禁用并写明原因——
 * 不做一个看起来能选、实际无效的控件。
 */
import { KNOWLEDGE_MODE_LABEL, useIntakeStore } from '@/stores/intake-store';
import type { KnowledgeMode } from '@/stores/intake-store';

const ORDER: KnowledgeMode[] = ['default', 'auto', 'tournament', 'off'];

export function KnowledgeInjectionForm() {
  const knowledgeMode = useIntakeStore((state) => state.knowledgeMode);
  const setKnowledgeMode = useIntakeStore((state) => state.setKnowledgeMode);

  return (
    <section className="flex flex-col gap-2" data-knowledge-form="true">
      <h3 className="text-sm font-semibold text-fg">知识注入</h3>
      <div className="flex flex-col gap-1.5 fe-card p-3">
        {ORDER.map((mode) => (
          <label key={mode} className="flex items-center gap-2 text-xs text-fg">
            <input
              type="radio"
              name="knowledge-mode"
              value={mode}
              checked={knowledgeMode === mode}
              onChange={() => setKnowledgeMode(mode)}
              className="accent-[var(--fe-brand)]"
            />
            {KNOWLEDGE_MODE_LABEL[mode]}
          </label>
        ))}
        <label className="flex items-center gap-2 text-xs text-fg-subtle" title="引擎尚无类别过滤字段（待确认）">
          <input type="radio" name="knowledge-mode" disabled className="opacity-50" />
          选择已有知识类别 / 知识簇
          <span className="text-[11px]">（引擎尚无类别过滤字段，暂不可用）</span>
        </label>
      </div>
    </section>
  );
}
