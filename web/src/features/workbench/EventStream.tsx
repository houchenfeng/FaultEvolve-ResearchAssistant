/**
 * 时间轴与事件流（TODO 5.6 / PRD §9.6）。
 *
 * 事件流的三代语义（去重、代际切分、未知类型）全部在 `iteration-logic.ts` 里，
 * 这里只负责渲染与交互。点击事件要在树里定位节点（PRD §10.2 第 12 条），
 * 所以每行都带一个「定位」按钮。
 *
 * **列表是虚拟化的**（TODO §12.6）：一次运行轻松上千条事件，全量进 DOM 之后
 * 滚动就开始掉帧。这里把「代标题 / 事件行 / 被过滤掉的占位行」压平成一份
 * 固定行高的行表，只渲染视口内那一窗口（上下各留一点 overscan），上下用
 * translateY 顶住滚动条高度。
 *
 * 行高写成常量而不是量的：行是单行定高（`py-0.5` + `text-[11px]`，没有换行
 * 也没有图片），量一次再排会在字体加载 / 主题切换时飘。代价是行高写死在两处
 * （这里的常量 + 下面的 className），改样式时必须一起改。
 */
import { useEffect, useMemo, useRef, useState } from 'react';

import type { EventResponse } from '@/generated/api';
import {
  countEventTypes,
  dedupeEvents,
  EMPTY_EVENT_FILTER,
  eventLabel,
  eventTone,
  filterEvents,
  generationStats,
  splitGenerations,
  type EventFilter,
  type Generation,
} from '@/features/workbench/iteration-logic';

const TONE_CLASS: Record<string, string> = {
  normal: 'text-fg-muted',
  muted: 'text-fg-subtle',
  success: 'text-success-500',
  warn: 'text-warning-500',
  error: 'text-danger-500',
};

/** 代标题行与事件行的高度，和下面 className 里的 `py-*` 一一对应。 */
const HEADER_HEIGHT = 26;
const ROW_HEIGHT = 22;
/** 视口上下各多渲染几行，滚动时不至于露出空白。 */
const OVERSCAN = 8;
/**
 * 视口高度的兜底值。真实浏览器里由 ResizeObserver 量出来，但 jsdom 没有布局
 * 引擎（`clientHeight` 恒 0），不兜底的话整个列表会渲染成空 —— 组件测试就
 * 什么都断言不了了。480 大约是一屏 20 行。
 */
const FALLBACK_VIEWPORT_HEIGHT = 480;

type Row =
  | { kind: 'header'; key: string; top: number; height: number; generation: Generation }
  | {
      kind: 'event';
      key: string;
      top: number;
      height: number;
      event: EventResponse;
      generation: Generation;
    }
  | { kind: 'empty'; key: string; top: number; height: number; generation: Generation };

export interface EventStreamProps {
  events: EventResponse[];
  onLocateNode?: (nodeId: string) => void;
  /** 高亮某个节点的事件（从树点过来时）。 */
  highlightNodeId?: string | null;
}

export function EventStream({ events, onLocateNode, highlightNodeId }: EventStreamProps) {
  const [filter, setFilter] = useState<EventFilter>(EMPTY_EVENT_FILTER);
  const [hideUnknown, setHideUnknown] = useState(false);
  // 折叠状态提到这一层：虚拟化的行表必须完整知道每一代有没有展开，
  // 放在子组件里的话父组件算不出总高度，滚动条会跳。
  const [collapsedIds, setCollapsedIds] = useState<ReadonlySet<string>>(() => new Set());
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(FALLBACK_VIEWPORT_HEIGHT);
  const scrollerRef = useRef<HTMLDivElement | null>(null);

  const generations = useMemo(() => splitGenerations(events), [events]);
  const typeCounts = useMemo(() => countEventTypes(events), [events]);
  const unknownCount = useMemo(
    () => dedupeEvents(events).filter((event) => event.is_known_type === false).length,
    [events],
  );
  const effectiveFilter = useMemo(
    () => ({ ...filter, hideUnknown }),
    [filter, hideUnknown],
  );

  const { rows, totalHeight } = useMemo(() => {
    const flat: Row[] = [];
    for (const generation of generations) {
      flat.push({
        kind: 'header',
        key: `header:${generation.id}`,
        top: 0,
        height: HEADER_HEIGHT,
        generation,
      });
      if (collapsedIds.has(generation.id)) continue;
      const visible = filterEvents(generation.events, effectiveFilter);
      if (visible.length === 0) {
        flat.push({
          kind: 'empty',
          key: `empty:${generation.id}`,
          top: 0,
          height: ROW_HEIGHT,
          generation,
        });
        continue;
      }
      visible.forEach((event, index) => {
        flat.push({
          kind: 'event',
          key: `event:${generation.id}:${event.id ?? index}`,
          top: 0,
          height: ROW_HEIGHT,
          event,
          generation,
        });
      });
    }
    let offset = 0;
    for (const row of flat) {
      row.top = offset;
      offset += row.height;
    }
    return { rows: flat, totalHeight: offset };
  }, [generations, collapsedIds, effectiveFilter]);

  // 线性扫一遍找窗口。行数量级是千级，滚动时 O(n) 比二分更好读也更不容易写错，
  // 而且行高不统一（标题行更高）本来也没法纯算术定位。
  const window = useMemo(() => {
    if (rows.length === 0) return { start: 0, end: 0 };
    let start = 0;
    while (start < rows.length && rows[start].top + rows[start].height < scrollTop) {
      start += 1;
    }
    start = Math.max(0, start - OVERSCAN);
    let end = start;
    const limit = scrollTop + viewportHeight;
    while (end < rows.length && rows[end].top < limit) {
      end += 1;
    }
    return { start, end: Math.min(rows.length, end + OVERSCAN) };
  }, [rows, scrollTop, viewportHeight]);

  // 量真实视口高度：折叠/展开、窗口缩放都会变，所以挂 ResizeObserver。
  useEffect(() => {
    const element = scrollerRef.current;
    if (!element) return;
    const measure = () => {
      const height = element.clientHeight;
      if (height > 0) setViewportHeight(height);
    };
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const toggleGeneration = (id: string) => {
    setCollapsedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const visibleRows = rows.slice(window.start, window.end);

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="event-stream">
      <div className="flex flex-wrap items-center gap-1.5 border-b border-border-subtle bg-surface px-3 py-1.5 text-[11px]">
        <input
          type="search"
          value={filter.keyword}
          placeholder="搜索事件类型或内容"
          onChange={(event) => setFilter({ ...filter, keyword: event.target.value })}
          className="min-w-40 flex-1 fe-input fe-input-sm py-0.5 text-[11px]"
        />
        {unknownCount > 0 ? (
          <button
            type="button"
            aria-pressed={hideUnknown}
            onClick={() => setHideUnknown(!hideUnknown)}
            className={`rounded-pill border px-2 py-0.5 ${
              hideUnknown
                ? 'border-brand-500 bg-brand-50 text-brand-600 dark:bg-brand-500/10 dark:text-brand-300'
                : 'border-border-subtle text-fg-muted'
            }`}
            title="隐藏前端不认识的事件类型（引擎新增事件时页面不会突然变乱）"
          >
            隐藏未知类型（{unknownCount}）
          </button>
        ) : null}
        <span className="text-fg-subtle">
          共 {typeCounts.length} 种类型
        </span>
      </div>

      <div
        ref={scrollerRef}
        onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
        className="min-h-0 flex-1 overflow-y-auto"
        data-testid="event-stream-scroller"
      >
        {rows.length === 0 ? (
          <div className="px-3 py-4 text-[11px] text-fg-subtle">这次运行没有事件记录</div>
        ) : (
          <div style={{ height: totalHeight, position: 'relative' }}>
            <div
              style={{ transform: `translateY(${rows[window.start]?.top ?? 0}px)` }}
              data-testid="event-window"
            >
              {visibleRows.map((row) =>
                row.kind === 'header' ? (
                  <GenerationHeader
                    key={row.key}
                    generation={row.generation}
                    collapsed={collapsedIds.has(row.generation.id)}
                    onToggle={() => toggleGeneration(row.generation.id)}
                  />
                ) : row.kind === 'empty' ? (
                  <div
                    key={row.key}
                    className="flex h-[22px] items-center px-3 text-[11px] text-fg-subtle"
                  >
                    该代事件被过滤掉了
                  </div>
                ) : (
                  <EventRow
                    key={row.key}
                    event={row.event}
                    highlight={
                      highlightNodeId !== null && nodeIdOf(row.event) === highlightNodeId
                    }
                    onLocateNode={onLocateNode}
                  />
                ),
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function GenerationHeader({
  generation,
  collapsed,
  onToggle,
}: {
  generation: Generation;
  collapsed: boolean;
  onToggle: () => void;
}) {
  const stats = generationStats(generation);
  return (
    <button
      type="button"
      onClick={onToggle}
      data-testid={`generation-${generation.index}`}
      className="flex h-[26px] w-full items-center gap-2 bg-surface-muted px-3 text-left text-[11px] hover:bg-surface-muted/70"
    >
      <span className="text-fg-subtle">{collapsed ? '▸' : '▾'}</span>
      <span className="font-medium text-fg">第 {generation.index} 代</span>
      <span className="text-fg-muted">{stats.eventCount} 个事件</span>
      {stats.unknownCount > 0 ? (
        <span className="text-warning-500">{stats.unknownCount} 个未知类型</span>
      ) : null}
      <span className="flex-1" />
      {!stats.closed ? <span className="text-info-500">进行中</span> : null}
      {stats.firstTs ? (
        <span className="tabular text-fg-subtle">{stats.firstTs.slice(11, 19)}</span>
      ) : null}
    </button>
  );
}

function EventRow({
  event,
  highlight,
  onLocateNode,
}: {
  event: EventResponse;
  highlight: boolean;
  onLocateNode?: (nodeId: string) => void;
}) {
  const nodeId = nodeIdOf(event);
  return (
    <div
      className={`flex h-[22px] items-center gap-2 px-3 text-[11px] ${
        highlight ? 'bg-brand-50 dark:bg-brand-500/10' : ''
      }`}
      data-event-row=""
    >
      <span className="tabular w-16 shrink-0 text-fg-subtle">
        {(event.ts ?? '').slice(11, 19) || '--:--:--'}
      </span>
      <span className={`w-1.5 shrink-0 rounded-full ${toneDot(eventTone(event.type))}`} />
      <span
        className={`w-40 shrink-0 truncate ${TONE_CLASS[eventTone(event.type)]}`}
        title={event.type}
      >
        {eventLabel(event.type)}
      </span>
      {event.is_known_type === false ? (
        <span className="shrink-0 text-warning-500" title="前端不认识这个事件类型，原样显示">
          ?
        </span>
      ) : null}
      <span className="min-w-0 flex-1 truncate text-fg-subtle">{summarizePayload(event)}</span>
      {nodeId && onLocateNode ? (
        <button
          type="button"
          onClick={() => onLocateNode(nodeId)}
          className="shrink-0 rounded-card border border-border-subtle px-1.5 py-px text-[10px] text-fg-muted hover:border-brand-500 hover:text-brand-600"
        >
          定位
        </button>
      ) : null}
    </div>
  );
}

function nodeIdOf(event: EventResponse): string | null {
  const payload = event.payload as Record<string, unknown> | undefined;
  if (typeof payload?.node_id === 'string') return payload.node_id;
  if (typeof payload?.node === 'string') return payload.node;
  return null;
}

function toneDot(tone: string): string {
  switch (tone) {
    case 'error':
      return 'bg-danger-500';
    case 'warn':
      return 'bg-warning-500';
    case 'success':
      return 'bg-success-500';
    case 'muted':
      return 'bg-neutral-500';
    default:
      return 'bg-border-strong';
  }
}

/** 事件的 payload 一行摘要：只取标量，别把整个 JSON 糊在界面上。 */
function summarizePayload(event: EventResponse): string {
  const payload = event.payload as Record<string, unknown> | undefined;
  if (!payload) return '';
  const parts: string[] = [];
  for (const [key, value] of Object.entries(payload)) {
    if (typeof value === 'number' || typeof value === 'boolean') {
      parts.push(`${key}=${value}`);
    } else if (typeof value === 'string' && value.length <= 24) {
      parts.push(`${key}=${value}`);
    }
    if (parts.length >= 3) break;
  }
  return parts.join(' ');
}
