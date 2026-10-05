/**
 * 知识发现页（PRD 12 / TODO 6.1–6.3，`/runs/$runId/knowledge`）。
 *
 * 四节各自的真实程度不同，不能一概而论：
 * - 12.2 知识卡：计数来自运行制品；正文按卡片 ID 对照已登记任务的知识库。
 * - 12.3 现象层：效应量/CI/p/e/判级/预注册哈希/沙箱错误都是真的；
 *   条件·特征·结果·适用范围·可证伪条件只在 SQLite 的 claim 表里，报暂不支持。
 * - 12.4 机制层与辩论赛：只有计数与证书是真的；逐场对阵、机制结构、Qwen 论点、
 *   Elo、证书状态都不在契约里，报暂不支持，且**不给出任何胜者**。
 * - 12.5 理论与迁移：整节无法实现——theories.json 被硬编码成空列表。
 *
 * 数据来源分三处，别混：
 * - 卡片清单来自 `/knowledge/cards`，读 `fe.db` 的四张统计表；
 * - 发现制品来自 `/discovery`，读 `discovery/*.json`；
 * - 采用汇总、辩论赛计数与制品状态来自 `RunLayout` 已经取好的 `/api/runs/{id}`
 *   （读 `run_summary.json`），同一个 query key，TanStack Query 会复用，不额外发请求。
 */
import { useQuery } from '@tanstack/react-query';
import { useNavigate, useParams } from '@tanstack/react-router';
import { useState } from 'react';

import { ApiErrorPanel } from '@/components/states/ApiErrorPanel';
import { EmptyState } from '@/components/states/EmptyState';
import {
  EMPTY_CARD_FILTER,
  adoptionSummaryRows,
  buildCardRows,
  cardEmptyState,
  cardHasProse,
  filterCards,
  readCardLabels,
  writeCardLabel,
  type CardFilter,
  type CardLabel,
} from '@/features/discovery/card-logic';
import { CardProseList } from '@/features/discovery/CardProseList';
import { KnowledgeCardList, type DatabaseState } from '@/features/discovery/KnowledgeCardList';
import {
  buildCertificateRows,
  buildControlRows,
  buildPhenomenonRows,
  collectSandboxFailures,
  discoveryEmptyState,
  mechanismCounterRows,
  partitionSandboxFailures,
  tournamentCounterRows,
  validityCounterRows,
} from '@/features/discovery/discovery-logic';
import { MechanismTournament } from '@/features/discovery/MechanismTournament';
import { PhenomenonList } from '@/features/discovery/PhenomenonList';
import {
  getDiscoveryApiRunsRunIdDiscoveryGet,
  getEventsApiRunsRunIdEventsGet,
  getKnowledgeCardsApiRunsRunIdKnowledgeCardsGet,
  getRunApiRunsRunIdGet,
} from '@/generated/api';
import { toApiError, unwrap } from '@/lib/api';
import { queryKeys } from '@/lib/query-keys';
import { useUiStore } from '@/stores/ui-store';
import { HddKnowledgeCase } from '@/features/showcase/HddKnowledgeCase';
import { SHOWCASE_RUN_ID } from '@/features/showcase/hdd-showcase-data';

/**
 * 制品状态只在契约的三种取值上断言，其余一律 `unknown`。
 * `artifact_states` 的键是自由字符串，值类型虽然是 `ArtifactState`，
 * 但生成物可能落后于正在跑的后端（这正是契约漂移门禁要抓的情况）；
 * 那时宁可说「没查到」，也不要顺着 `missing` 的文案去冤枉这份运行。
 */
function toDatabaseState(value: string | undefined): DatabaseState {
  return value === 'available' || value === 'missing' || value === 'invalid' ? value : 'unknown';
}

export function RunKnowledgePage() {
  const { runId } = useParams({ from: '/runs/$runId/knowledge' });
  const navigate = useNavigate();
  const setSelectedNodeId = useUiStore((state) => state.setSelectedNodeId);
  const [filter, setFilter] = useState<CardFilter>(EMPTY_CARD_FILTER);
  const [labels, setLabels] = useState<Record<string, CardLabel>>(() =>
    readCardLabels(runId, window.localStorage),
  );

  const cardsQuery = useQuery({
    queryKey: queryKeys.knowledgeCards(runId),
    queryFn: () =>
      unwrap(getKnowledgeCardsApiRunsRunIdKnowledgeCardsGet({ path: { run_id: runId } })),
    retry: false,
  });

  // RunLayout 已经用同一个 key 取过运行详情并拦住了失败，这里只是复用缓存。
  const detailQuery = useQuery({
    queryKey: queryKeys.run(runId),
    queryFn: () => unwrap(getRunApiRunsRunIdGet({ path: { run_id: runId } })),
    retry: false,
  });

  const discoveryQuery = useQuery({
    queryKey: queryKeys.discovery(runId),
    queryFn: () => unwrap(getDiscoveryApiRunsRunIdDiscoveryGet({ path: { run_id: runId } })),
    retry: false,
  });

  /**
   * 只为拿沙箱失败：`claim_sandbox_failed` 事件是「沙箱或检验错误」（PRD 12.3）
   * 唯一真实的来源——失败的 claim 从不写进 phenomena.json。
   * 事件类型不在 catalog 的 EVENT_TYPES 里，但那只是打标不过滤
   * （catalog.py:41-43），payload 已由后端 sanitize_value 脱敏。
   */
  const eventsQuery = useQuery({
    queryKey: queryKeys.events(runId, null, 500),
    queryFn: () =>
      unwrap(getEventsApiRunsRunIdEventsGet({ path: { run_id: runId }, query: { limit: 500 } })),
    retry: false,
  });

  const knowledge = detailQuery.data?.knowledge ?? null;
  const runDiscovery = detailQuery.data?.discovery ?? null;
  const databaseState = toDatabaseState(detailQuery.data?.artifact_states?.database);
  const summary = adoptionSummaryRows(knowledge);
  const rows = buildCardRows(cardsQuery.data ?? [], knowledge?.card_stats, {
    databaseAvailable: databaseState === 'available',
    labels,
  });

  const discovery = discoveryQuery.data ?? null;
  const phenomena = buildPhenomenonRows(discovery?.phenomena, discovery?.preregistration);
  const sandbox = partitionSandboxFailures(
    phenomena,
    // 事件请求失败时给空数组，再由下方 data-events-unavailable 明说「无法判断」，
    // 不能顺势宣称「没有沙箱失败」。
    collectSandboxFailures(eventsQuery.data?.events ?? []),
  );
  const controls = buildControlRows(discovery?.controls);
  const certificates = buildCertificateRows(discovery?.certificates);

  // 知识卡的 pending / error 在下方「知识卡」一节内联处理，不在这里提前 return：
  // 整页返回会让 fe.db 读不到时连带抹掉现象层与辩论赛已经拿到的事实。

  const changeLabel = (cardId: string, label: CardLabel | null) => {
    setLabels(writeCardLabel(runId, cardId, label, window.localStorage));
  };

  const openNode = (nodeId: string) => {
    setSelectedNodeId(nodeId);
    void navigate({ to: '/runs/$runId/tree', params: { runId } });
  };

  if (runId === SHOWCASE_RUN_ID) {
    return <HddKnowledgeCase />;
  }

  return (
    <div className="flex flex-col gap-5">
      {/*
        页面级标题（与结果页同一条理由）：阶段 6 页面合进来后这一层没了，
        整页只剩各节的 <h2> —— 可访问性树里没有 h1，§12.5 与 E2E-01 第 8 步
        也没有落点。见 RunResultsPage 里的同一条注释。
      */}
      <h1 className="text-base font-semibold text-fg">知识发现</h1>
      {/* data-cards-state 与下面的 data-phenomena-state 同理：本节内容在
          pending / error / ready 三态下完全不同，测试需要一个稳定的落定信号。
          `data-card-summary` 不行——它三态都在。 */}
      <section
        className="flex flex-col gap-3"
        data-cards-state={
          cardsQuery.isPending ? 'pending' : cardsQuery.isError ? 'error' : 'ready'
        }
      >
        <header className="flex flex-wrap items-baseline gap-2">
          <h2 className="text-sm font-semibold text-fg">知识卡</h2>
          <span className="text-xs text-fg-subtle">计数来自 fe.db，汇总来自 run_summary.json</span>
        </header>

        <dl data-card-summary className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {summary.map((row) => (
            <div
              key={row.label}
              className="fe-card px-3 py-2"
            >
              <dt className="text-[11px] text-fg-subtle">{row.label}</dt>
              <dd
                data-summary-cell={row.label}
                data-recorded={row.cell.recorded ? 'true' : 'false'}
                className={`tabular text-base font-semibold ${
                  row.cell.recorded ? 'text-fg' : 'text-fg-subtle'
                }`}
              >
                {row.cell.value}
              </dd>
            </div>
          ))}
        </dl>

        {/* 卡片清单失败只降级本节：现象层与辩论赛的数据来自另外两个请求，
            不该因为 fe.db 读不到就一起消失（同 TaskDetailPage 的处理）。 */}
        {cardsQuery.isPending ? (
          <div className="px-4 py-6 text-center text-xs text-fg-subtle">正在读取知识卡…</div>
        ) : cardsQuery.isError ? (
          <ApiErrorPanel
            title="读不到知识卡清单"
            error={toApiError(cardsQuery.error)}
            onRetry={() => void cardsQuery.refetch()}
          />
        ) : rows.length === 0 ? (
          <EmptyState {...cardEmptyState(databaseState, knowledge)} />
        ) : (
          <KnowledgeCardList
            rows={rows}
            filter={filter}
            onFilterChange={setFilter}
            onLabelChange={changeLabel}
            onOpenNode={openNode}
            databaseState={databaseState}
          />
        )}
      </section>

      {/* 四节各有自己的暂不支持清单，测试要能按节断言，所以每节都挂一个钩子。 */}
      <section className="flex flex-col gap-2" data-card-prose>
        <h2 className="text-sm font-semibold text-fg">卡片正文与来源</h2>
        {cardsQuery.isPending ? (
          <div className="px-4 py-6 text-center text-xs text-fg-subtle">正在读取卡片正文…</div>
        ) : cardsQuery.isError ? (
          <p className="text-xs text-fg-subtle">卡片清单没有读到，正文也无法对照。</p>
        ) : (
          <CardProseList
            rows={filterCards(rows, filter)}
            catalogMatched={rows.some(cardHasProse)}
          />
        )}
      </section>

      {/* data-phenomena-state 是给测试的稳定落定信号：本节的内容在 pending /
          error / ready 三种状态下完全不同，靠文案猜会读到占位值。 */}
      <section
        className="flex flex-col gap-3"
        data-phenomena-state={
          discoveryQuery.isPending ? 'pending' : discoveryQuery.isError ? 'error' : 'ready'
        }
      >
        <header className="flex flex-wrap items-baseline gap-2">
          <h2 className="text-sm font-semibold text-fg">现象层</h2>
          <span className="text-xs text-fg-subtle">
            来自 discovery/phenomena.json 与 preregistration.json
          </span>
        </header>

        {discoveryQuery.isPending ? (
          <div className="px-4 py-6 text-center text-xs text-fg-subtle">正在读取发现制品…</div>
        ) : discoveryQuery.isError ? (
          <ApiErrorPanel
            title="读不到发现制品"
            error={toApiError(discoveryQuery.error)}
            onRetry={() => void discoveryQuery.refetch()}
          />
        ) : (
          <>
            {(discovery?.warnings ?? []).map((warning) => (
              <p
                key={`${warning.field}-${warning.reason}`}
                data-contract-warning={warning.field}
                className="rounded-card border border-warning-500/30 bg-warning-50 p-2 text-[11px] text-warning-700 dark:border-warning-500/40 dark:bg-warning-500/10 dark:text-warning-500"
              >
                {warning.reason}
              </p>
            ))}

            {/* 事件流挂了就不能让页面看起来「没有沙箱失败」——那是把一次请求故障
                画成运行健康。沙箱失败只能从事件拿（见 eventsQuery 的注释）。 */}
            {eventsQuery.isError ? (
              <p
                data-events-unavailable
                className="rounded-card border border-warning-500/30 bg-warning-50 p-2 text-[11px] text-warning-700 dark:border-warning-500/40 dark:bg-warning-500/10 dark:text-warning-500"
              >
                事件流读取失败（{toApiError(eventsQuery.error).errorCode}），因此无法判断是否有
                claim 在沙箱阶段失败。这不表示没有沙箱失败。
              </p>
            ) : null}

            {phenomena.length > 0 || sandbox.untested.length > 0 ? (
              <PhenomenonList
                rows={phenomena}
                untestedFailures={sandbox.untested}
                matchedFailures={sandbox.matched}
              />
            ) : (
              <EmptyState
                {...discoveryEmptyState(discovery?.enabled, discovery?.phenomena_state, '现象记录')}
              />
            )}

            {(discovery?.discovered_card_ids ?? []).length > 0 ? (
              <p className="text-[11px] text-fg-subtle" data-discovered-cards>
                本轮沉淀为知识卡：
                {(discovery?.discovered_card_ids ?? []).map((id) => (
                  <code key={id} className="ml-1 font-mono">
                    {id}
                  </code>
                ))}
              </p>
            ) : null}
          </>
        )}
      </section>

      <section className="flex flex-col gap-3" data-tournament>
        <header className="flex flex-wrap items-baseline gap-2">
          <h2 className="text-sm font-semibold text-fg">机制层与辩论赛</h2>
          <span className="text-xs text-fg-subtle">
            计数来自 run_summary.json，证书来自 discovery/certificates.json
          </span>
        </header>

        {/* PRD 12.4 要求 Qwen 论点与数据裁决分区显示。这里只有数据裁决一侧是真的：
            证书、对照与计数全部来自统计检验，Qwen 论点区不存在（见下方暂不支持）。 */}
        <MechanismTournament
          mechanismCounters={mechanismCounterRows(runDiscovery)}
          tournamentCounters={tournamentCounterRows(runDiscovery)}
          validityCounters={validityCounterRows(runDiscovery)}
          controls={controls}
          certificates={certificates}
        />
      </section>
    </div>
  );
}
