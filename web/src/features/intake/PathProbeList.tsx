/**
 * 路径检查结果列表（TODO 4.3 / PRD §7.4）。
 *
 * 每行一个目录：存在 / 是目录 / 可写 / 服务端附注（含剩余空间）。
 * 只渲染后端返回的事实，不在前端猜文件系统。
 */
import type { PathProbeResponse } from '@/generated/api';

function probeTone(probe: PathProbeResponse): 'success' | 'danger' | 'warning' {
  if (!probe.exists) return 'danger';
  if (!probe.is_directory) return 'warning';
  if (probe.writable === false) return 'warning';
  return 'success';
}

function probeLine(probe: PathProbeResponse): string {
  if (!probe.exists) return '不存在';
  if (!probe.is_directory) return '存在，但不是目录';
  if (probe.writable === false) return '存在，但不可写';
  return '存在 · 可写';
}

export function PathProbeList({ probes }: { probes: PathProbeResponse[] }) {
  if (probes.length === 0) return null;
  return (
    <ul data-path-probe-list="true" className="space-y-1">
      {probes.map((probe) => (
        <li
          key={probe.path}
          className="flex items-start justify-between gap-3 rounded-card border border-border-subtle bg-surface-muted px-2.5 py-1.5 text-[11px]"
        >
          <span className="min-w-0 break-all font-mono text-fg-muted">{probe.path}</span>
          <span
            className={
              probeTone(probe) === 'success'
                ? 'shrink-0 text-success-700'
                : probeTone(probe) === 'danger'
                  ? 'shrink-0 text-danger-700'
                  : 'shrink-0 text-warning-700'
            }
          >
            {probeLine(probe)}
            {probe.detail ? ` · ${probe.detail}` : ''}
          </span>
        </li>
      ))}
    </ul>
  );
}
