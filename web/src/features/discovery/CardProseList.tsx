/**
 * 卡片正文（PRD 12.2）：标题、类别、claim、来源、适用条件、优先级与统计效用。
 *
 * 值只来自知识卡响应。空着就写「未记录」。链接只接受 http(s)。
 */
import {
  NOT_RECORDED,
  PROSE_ABSENCE_NOTE,
  categoryLabel,
  httpUrl,
  sourceKindLabel,
  type CardRow,
} from '@/features/discovery/card-logic';

function Field({ label, value }: { label: string; value: string | null }) {
  const recorded = value != null && value !== '';
  return (
    <div>
      <dt className="text-[11px] text-fg-subtle">{label}</dt>
      <dd
        data-prose-field={label}
        data-recorded={recorded ? 'true' : 'false'}
        className={`text-xs ${recorded ? 'text-fg' : 'text-fg-subtle'}`}
      >
        {recorded ? value : NOT_RECORDED}
      </dd>
    </div>
  );
}

export function CardProseList({
  rows,
  catalogMatched,
}: {
  /** 已经按当前搜索和类别筛过。 */
  rows: CardRow[];
  /** 未筛选的清单里是否至少有一张对上了知识库。 */
  catalogMatched: boolean;
}) {
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[11px] text-fg-subtle">{PROSE_ABSENCE_NOTE}</p>
      {!catalogMatched ? (
        <p data-prose-unmatched="true" className="text-xs text-fg-subtle">
          当前这些卡片都没有对上任务知识库，正文各项显示未记录。
        </p>
      ) : rows.length === 0 ? (
        <p data-prose-filtered-empty="true" className="text-xs text-fg-subtle">
          没有卡片符合当前筛选条件。
        </p>
      ) : (
        rows.map((row) => (
          <article
            key={row.cardId}
            data-card-prose-row={row.cardId}
            className="flex flex-col gap-2 fe-card px-3 py-2"
          >
            <h3 className="font-mono text-xs text-fg">{row.cardId}</h3>
            <dl className="grid gap-2 sm:grid-cols-2">
              <Field label="标题" value={row.title} />
              <Field label="类别" value={row.category ? categoryLabel(row.category) : null} />
              <Field label="核心 claim" value={row.claim} />
              <Field
                label="来源类型"
                value={row.sourceKind ? sourceKindLabel(row.sourceKind) : null}
              />
              <Field label="适用条件" value={row.conditions} />
              <Field
                label="知识库优先级"
                value={row.priority != null ? String(row.priority) : null}
              />
              <Field label="样本数" value={row.statN.recorded ? row.statN.value : null} />
              <Field label="平均 Δ" value={row.meanDelta.recorded ? row.meanDelta.value : null} />
            </dl>
            <div>
              <p className="text-[11px] text-fg-subtle">来源</p>
              {row.sources.length === 0 ? (
                <p data-prose-field="来源" data-recorded="false" className="text-xs text-fg-subtle">
                  {NOT_RECORDED}
                </p>
              ) : (
                <ul className="flex flex-col gap-1">
                  {row.sources.map((source) => {
                    const href = httpUrl(source.url);
                    const text = source.title || source.sourceId;
                    return (
                      <li key={source.sourceId} className="text-xs text-fg">
                        {href ? (
                          <a
                            href={href}
                            target="_blank"
                            rel="noopener noreferrer"
                            data-source-link={source.sourceId}
                          >
                            {text}
                          </a>
                        ) : (
                          <span data-source-text={source.sourceId}>{text}</span>
                        )}
                        <p
                          data-source-takeaway={source.sourceId}
                          data-recorded={source.takeaway ? 'true' : 'false'}
                          className={`mt-0.5 ${source.takeaway ? 'text-fg-muted' : 'text-fg-subtle'}`}
                        >
                          {source.takeaway ?? NOT_RECORDED}
                        </p>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </article>
        ))
      )}
    </div>
  );
}
