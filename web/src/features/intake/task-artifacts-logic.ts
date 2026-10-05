/**
 * 三张必填卡的推导逻辑（TODO 4.2 / PRD §7.3）。
 *
 * 与 TaskArtifactsForm 组件分文件：react-refresh 要求组件文件只导出组件；
 * 这些纯函数与 hook 要被测试直接引用。
 */
import { useQuery } from '@tanstack/react-query';

import { getTaskCardApiTasksTaskIdCardGet } from '@/generated/api';
import { toApiError, unwrap } from '@/lib/api';
import { queryKeys } from '@/lib/query-keys';
import type { CardValidationState } from '@/features/intake/badge';

export type ArtifactCardId = 'dataset' | 'evaluator' | 'init';

export interface ArtifactCard {
  id: ArtifactCardId;
  title: string;
  state: CardValidationState;
  /** 阻塞原因（state=fail 时必有）；warn 时为提醒文案。 */
  reason: string | null;
  /** 卡片正文的事实行。 */
  facts: Array<[string, string]>;
}

/** 把任务卡数据折算成三张必填卡的状态。字段按 DTO 可选性收（undefined = 未就绪）。 */
export function deriveArtifactCards(
  card: {
    data_ready?: boolean | null;
    data_missing?: string[] | null;
    evaluator_ready?: boolean | null;
    init_ready?: boolean | null;
    metrics?: { initial_score?: number | null; primary_metric?: string | null } | null;
    knowledge_card_count?: number | null;
  } | null,
  pending: boolean,
  error: boolean,
): ArtifactCard[] {
  const datasetState: CardValidationState = error
    ? 'fail'
    : pending
      ? 'checking'
      : card
        ? card.data_ready
          ? 'pass'
          : 'fail'
        : 'empty';
  const evaluatorState: CardValidationState = error
    ? 'fail'
    : pending
      ? 'checking'
      : card
        ? card.evaluator_ready
          ? 'pass'
          : 'fail'
        : 'empty';
  const initState: CardValidationState = error
    ? 'fail'
    : pending
      ? 'checking'
      : card
        ? card.init_ready
          ? 'pass'
          : 'fail'
        : 'empty';

  const missing = card?.data_missing ?? [];

  return [
    {
      id: 'dataset',
      title: '数据集',
      state: datasetState,
      reason: card && !card.data_ready
        ? missing.length > 0
          ? `缺少数据文件：${missing.join('、')}`
          : '数据目录未就绪'
        : null,
      facts: [
        ['数据状态', card ? (card.data_ready ? '已就绪' : '未就绪') : '—'],
        ['缺失文件', missing.length > 0 ? `${missing.length} 个` : '无'],
      ],
    },
    {
      id: 'evaluator',
      title: 'evaluator',
      state: evaluatorState,
      reason: card && !card.evaluator_ready ? '仓库内未找到可解析的 evaluator.py' : null,
      facts: [
        ['来源', '仓库内置（只读，不可修改）'],
        ['解析检查', card ? (card.evaluator_ready ? '通过' : '未通过') : '—'],
      ],
    },
    {
      id: 'init',
      title: '初始算法',
      state: initState,
      reason: card && !card.init_ready ? '仓库内未找到可解析的 init.py' : null,
      facts: [
        ['来源', '仓库内置 init.py'],
        [
          '初始基线分',
          card?.metrics?.initial_score != null
            ? String(card.metrics.initial_score)
            : '待评估（未试跑不显示假定分数）',
        ],
      ],
    },
  ];
}

export function useTaskArtifactCards(taskId: string | null) {
  const query = useQuery({
    queryKey: queryKeys.taskCard(taskId ?? ''),
    queryFn: () => unwrap(getTaskCardApiTasksTaskIdCardGet({ path: { task_id: taskId ?? '' } })),
    enabled: taskId !== null,
    retry: 1,
  });
  return {
    cards: deriveArtifactCards(query.data ?? null, query.isPending, query.isError),
    error: query.isError ? toApiError(query.error) : null,
    retry: () => void query.refetch(),
  };
}
