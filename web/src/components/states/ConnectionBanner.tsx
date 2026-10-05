/**
 * 连接状态横幅（TODO 3.5 / PRD 15.4）。
 *
 * 只负责"连接层"的可见性：Web API 不可达、实时通道断开或恢复。
 * 在线时不渲染任何东西，避免占用页面高度。
 */
export type ConnectionState = 'online' | 'reconnecting' | 'offline';

export interface ConnectionBannerProps {
  state: ConnectionState;
  /** 离线/重连时的补充说明。 */
  detail?: string;
  onRetry?: () => void;
}

const TONES: Record<Exclude<ConnectionState, 'online'>, { text: string; className: string }> = {
  reconnecting: {
    text: '正在重新连接…',
    className:
      'border-warning-500/30 bg-warning-50 text-warning-700 dark:border-warning-500/40 dark:bg-warning-500/10 dark:text-warning-500',
  },
  offline: {
    text: '已断开与 Web API 的连接',
    className:
      'border-danger-500/30 bg-danger-50 text-danger-700 dark:border-danger-500/40 dark:bg-danger-500/10 dark:text-danger-500',
  },
};

export function ConnectionBanner({ state, detail, onRetry }: ConnectionBannerProps) {
  if (state === 'online') return null;
  const tone = TONES[state];

  return (
    <div
      role="status"
      data-connection-state={state}
      className={`flex items-center justify-between gap-3 border-b px-4 py-2 text-xs ${tone.className}`}
    >
      <span className="min-w-0">
        <span className="font-medium">{tone.text}</span>
        {detail ? <span className="ml-2 opacity-80">{detail}</span> : null}
      </span>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 rounded-card border border-current/30 px-2 py-0.5 font-medium hover:opacity-80"
        >
          立即重试
        </button>
      ) : null}
    </div>
  );
}
