/**
 * 必填卡片五态徽章（TODO 4.2）：未填写 / 检查中 / 通过 / 警告 / 失败。
 *
 * 复用 StatusBadge 的语义色，不另起一套色板。
 */
import { StatusBadge } from '@/components/ui/StatusBadge';

export type CardValidationState = 'empty' | 'checking' | 'pass' | 'warn' | 'fail';

const STATE_TONE: Record<CardValidationState, Parameters<typeof StatusBadge>[0]['tone']> = {
  empty: 'neutral',
  checking: 'info',
  pass: 'success',
  warn: 'warning',
  fail: 'danger',
};

const STATE_LABEL: Record<CardValidationState, string> = {
  empty: '未填写',
  checking: '检查中…',
  pass: '通过',
  warn: '警告',
  fail: '失败',
};

export function CardValidationBadge({ state }: { state: CardValidationState }) {
  return (
    <span data-card-state={state}>
      <StatusBadge tone={STATE_TONE[state]}>{STATE_LABEL[state]}</StatusBadge>
    </span>
  );
}
