/**
 * 三个必填卡（TODO 4.2 / PRD §7.3）：数据集 / evaluator / 初始算法。
 *
 * 阶段 4 的录入流从任务目录选任务，因此三张卡展示的是**该任务的实测
 * 就绪状态**（`/api/tasks/{id}/card`），不是自由上传表单。
 * 每张卡五态：未填写 / 检查中 / 通过 / 警告 / 失败；只有全部 `pass|warn`
 * 才允许继续（TODO §6 的三条阻塞测试项）。推导逻辑在 task-artifacts-logic。
 */
import { ApiErrorPanel } from '@/components/states/ApiErrorPanel';
import type { ApiError } from '@/lib/api-error';
import { CardValidationBadge } from '@/features/intake/badge';
import type { ArtifactCard } from '@/features/intake/task-artifacts-logic';

function ArtifactCardView({ card }: { card: ArtifactCard }) {
  return (
    <div
      data-artifact-card={card.id}
      className="flex flex-col gap-2 fe-card p-3"
    >
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-xs font-medium text-fg">{card.title}</h4>
        <CardValidationBadge state={card.state} />
      </div>
      <dl className="space-y-0.5">
        {card.facts.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-2 text-[11px]">
            <dt className="text-fg-subtle">{label}</dt>
            <dd className="text-right text-fg">{value}</dd>
          </div>
        ))}
      </dl>
      {card.reason ? (
        <p className={card.state === 'fail' ? 'text-[11px] text-danger-700' : 'text-[11px] text-warning-700'}>
          {card.reason}
        </p>
      ) : null}
    </div>
  );
}

export function TaskArtifactsForm({
  cards,
  error,
  onRetry,
}: {
  cards: ArtifactCard[];
  error: ApiError | null;
  onRetry: () => void;
}) {
  return (
    <section className="flex flex-col gap-2" data-artifacts-form="true">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-fg">任务工件（三项必填）</h3>
        <p className="text-[11px] text-fg-subtle">任一项失败即不能继续；警告可继续但需在下方确认。</p>
      </div>
      {error ? (
        <ApiErrorPanel error={error} onRetry={onRetry} />
      ) : (
        <div className="grid gap-3 md:grid-cols-3">
          {cards.map((card) => (
            <ArtifactCardView key={card.id} card={card} />
          ))}
        </div>
      )}
    </section>
  );
}
