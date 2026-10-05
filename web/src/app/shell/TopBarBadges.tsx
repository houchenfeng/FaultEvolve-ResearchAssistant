/**
 * 顶部栏状态徽章组（TODO 3.2）。
 *
 * Qwen 徽章：未配置时不探测；已配置时展示后端对模型列表的探测结果。
 */
import { StatusBadge } from '@/components/ui/StatusBadge';
import type { MetaResponse } from '@/generated/api';

export interface DataBadgeListProps {
  meta: MetaResponse | undefined;
  metaError: boolean;
  onOpenSettings: () => void;
}

export function qwenBadge(meta: MetaResponse | undefined): {
  tone: 'success' | 'warning' | 'neutral';
  label: string;
  title: string;
} {
  if (meta?.qwen_configured == null) {
    return {
      tone: 'neutral',
      label: 'Qwen 未记录',
      title: '尚未读取到千问状态',
    };
  }
  if (meta.qwen_configured !== true) {
    return {
      tone: 'neutral',
      label: 'Qwen 未配置',
      title: '未配置 DASHSCOPE_API_KEY，没有发起连通探测',
    };
  }
  if (meta.qwen_reachable === true) {
    return {
      tone: 'success',
      label: 'Qwen 已连通',
      title: '模型列表请求成功。只说明接口接受了密钥，不是一次代码生成。',
    };
  }
  if (meta.qwen_reachable === false) {
    return {
      tone: 'warning',
      label: 'Qwen 未连通',
      title: '密钥已配置，但模型列表请求失败。',
    };
  }
  return {
    tone: 'neutral',
    label: 'Qwen 未探测',
    title: '密钥已配置，但还没有连通探测结果。',
  };
}

/** 判断纯云端两种 transport 是否至少有一种可用。 */
function summarizeDeployment(meta: MetaResponse | undefined): {
  tone: 'success' | 'warning' | 'neutral';
  label: string;
  title: string;
} {
  if (!meta) {
    return { tone: 'neutral', label: '纯云端', title: '尚未读取到能力描述' };
  }
  const cloud = meta.deployment_modes.filter(
    (mode) => mode.mode === 'local_cloud' || mode.mode === 'ssh_cloud',
  );
  const available = cloud.filter((mode) => mode.available);
  if (available.length > 0) {
    return {
      tone: 'success',
      label: '纯云端',
      title: `可用 transport：${available.map((m) => m.mode).join('、')}`,
    };
  }
  return {
    tone: 'warning',
    label: '纯云端',
    title: '纯云端执行后端当前不可用（尚未配置或未实现）',
  };
}

export function DataBadgeList({ meta, metaError, onOpenSettings }: DataBadgeListProps) {
  if (metaError) {
    return (
      <StatusBadge tone="danger" title="无法读取 /api/meta">
        能力描述不可用
      </StatusBadge>
    );
  }

  const deployment = summarizeDeployment(meta);
  const qwen = qwenBadge(meta);

  return (
    <>
      <StatusBadge tone={deployment.tone} title={deployment.title}>
        {deployment.label}
      </StatusBadge>

      <button type="button" onClick={onOpenSettings} className="cursor-pointer">
        <StatusBadge tone={qwen.tone} title={qwen.title}>
          {qwen.label}
        </StatusBadge>
      </button>

      <StatusBadge
        tone={meta?.process_control_enabled ? 'success' : 'neutral'}
        title={
          meta?.process_control_enabled
            ? '云端执行器已启用'
            : '本阶段未开放启动/停止进程（process_control_enabled=false）'
        }
      >
        {meta?.process_control_enabled ? '执行器已启用' : '执行器未启用'}
      </StatusBadge>
    </>
  );
}
