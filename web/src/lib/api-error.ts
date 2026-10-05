/**
 * 把后端错误（以及网络/未知异常）归一化成前端可展示的结构。
 *
 * 依据 PRD 15.3：错误必须包含「用户可理解摘要 + 稳定错误码 + 是否可重试 +
 * 建议处理方式 + 可折叠技术详情」，且**优先显示 error_code 对应的中文文本**
 * （TODO 3.5）。
 */
import type { ApiErrorResponse } from '@/generated/api';

export interface ApiError {
  /** 稳定错误码，例如 `run.not_found`。未知错误固定为 `unknown`。 */
  errorCode: string;
  /** 面向用户的中文摘要。 */
  message: string;
  /** 是否可以安全重试。 */
  retryable: boolean;
  /** 建议的下一步处理方式。 */
  hint: string;
  /** 折叠区里的技术详情（已做路径/密钥兜底脱敏）。 */
  detail?: string;
  /** HTTP 状态码，网络层失败时为空。 */
  status?: number;
}

/** 错误码 → 中文文案。键必须与 `src/faultevolve/webapi/errors.py::ErrorCode` 一致。 */
const MESSAGES: Record<string, { message: string; retryable: boolean; hint: string }> = {
  not_found: { message: '接口不存在', retryable: false, hint: '请确认后端版本与前端契约一致。' },
  method_not_allowed: {
    message: '该接口不支持这个请求方法',
    retryable: false,
    hint: '这通常是前端调用写错了，请反馈给开发者。',
  },

  'request.invalid': {
    message: '请求参数不合法',
    retryable: false,
    hint: '请检查填写的内容后重试。',
  },
  'path.not_allowed': {
    message: '该路径不在允许范围内',
    retryable: false,
    hint: '只能访问配置的工作目录，请重新选择。',
  },
  'path.not_found': { message: '路径不存在', retryable: false, hint: '请确认目录是否已创建。' },
  'path.not_directory': {
    message: '该路径不是目录',
    retryable: false,
    hint: '请选择一个目录而不是文件。',
  },

  'run.not_found': {
    message: '找不到这个运行',
    retryable: false,
    hint: '运行可能已被清理，请回到总览重新选择。',
  },
  'run.unreadable': {
    message: '该运行的制品损坏或不可读',
    retryable: false,
    hint: '运行仍会列出，但内容无法解析；请检查制品目录。',
  },
  'artifact.missing': {
    message: '制品尚未生成',
    retryable: false,
    hint: '运行可能还没跑到该阶段，稍后刷新再看。',
  },
  'artifact.invalid_json': {
    message: '制品 JSON 解析失败',
    retryable: false,
    hint: '文件存在但内容损坏，请检查该制品文件。',
  },
  'artifact.not_downloadable': {
    message: '该制品不支持下载',
    retryable: false,
    hint: '该目录或类型被排除在下载白名单之外。',
  },
  'node.not_found': {
    message: '找不到这个节点',
    retryable: false,
    hint: '请回到进化树重新选择节点。',
  },

  'task.not_found': {
    message: '找不到该任务',
    retryable: false,
    hint: '任务可能未在配置的任务目录中，请回到总览重新选择。',
  },
  'task.not_ready': {
    message: '该任务尚未就绪',
    retryable: false,
    hint: '按就绪检查补齐缺失的工件后再继续。',
  },
  'server.not_found': {
    message: '找不到该服务器配置',
    retryable: false,
    hint: '该配置可能已被删除，请重新选择。',
  },
  'preset.unknown': {
    message: '未知的进化强度预设',
    retryable: false,
    hint: '请从三档预设（快速/标准/深度）中选择。',
  },
  'preset.invalid': {
    message: '配置合并后不合法',
    retryable: false,
    hint: '请检查修改过的字段取值后重试。',
  },

  not_supported: {
    message: '该能力当前版本尚未实现',
    retryable: false,
    hint: '界面会禁用对应操作，不会用假数据替代。',
  },

  'backend.unavailable': {
    message: '执行后端不可用',
    retryable: true,
    hint: '请检查服务器连接后重试。',
  },
  'backend.auth_failed': {
    message: '执行后端认证失败',
    retryable: false,
    hint: '请在设置中检查凭据配置。',
  },
  'backend.host_key_mismatch': {
    message: 'SSH 主机指纹不匹配',
    retryable: false,
    hint: '请确认目标主机身份后再连接。',
  },
  'environment.not_ready': {
    message: '运行环境未就绪',
    retryable: true,
    hint: '请检查 Conda 环境与依赖安装。',
  },
  'llm.key_missing': {
    message: '未配置 Qwen API Key',
    retryable: false,
    hint: '请在服务端环境变量里配置后重启服务。',
  },

  internal: { message: '服务内部错误', retryable: true, hint: '请稍后重试；若持续出现请查看服务端日志。' },
  network: {
    message: '无法连接到 Web API',
    retryable: true,
    hint: '请确认后端服务已启动，且网络可达。',
  },
  unknown: { message: '发生未知错误', retryable: true, hint: '请稍后重试。' },
};

/** 把疑似绝对路径的片段替换掉，作为展示层的最后一道兜底（PRD 15.3）。 */
export function redactPaths(text: string): string {
  return text
    .replace(/[A-Za-z]:[\\/][^\s"'`)]*/g, '<本地路径>')
    .replace(/\/(?:home|Users|root|mnt|srv|opt)\/[^\s"'`)]*/g, '<本地路径>');
}

/** HTTP 状态码 → 兜底错误码（当响应体不是标准 ApiErrorResponse 时使用）。 */
function codeFromStatus(status?: number): string {
  if (status === 404) return 'not_found';
  if (status === 405) return 'method_not_allowed';
  if (status === 401 || status === 403) return 'backend.auth_failed';
  if (status === 422) return 'request.invalid';
  if (status && status >= 500) return 'internal';
  return 'unknown';
}

/** 从一个未知异常里尽力取出 ApiErrorResponse。 */
function asApiErrorResponse(value: unknown): ApiErrorResponse | null {
  if (!value || typeof value !== 'object') return null;
  const candidate = value as Partial<ApiErrorResponse>;
  if (typeof candidate.error_code === 'string' && typeof candidate.message === 'string') {
    return candidate as ApiErrorResponse;
  }
  return null;
}

export function normalizeApiError(input: {
  error?: unknown;
  response?: { status?: number } | undefined;
}): ApiError {
  const status = input.response?.status;
  const body = asApiErrorResponse(input.error);

  if (body) {
    const entry = MESSAGES[body.error_code] ?? MESSAGES.unknown;

    // TODO 3.5：必须**优先显示 error_code 对应的中文文本**；
    // 服务端返回的英文 message 只在有额外信息时降到详情区。
    const detailParts: string[] = [];
    if (body.message && body.message !== entry.message) {
      detailParts.push(`服务端原文：${redactPaths(body.message)}`);
    }
    if (body.detail) {
      detailParts.push(redactPaths(body.detail));
    }

    return {
      errorCode: body.error_code,
      message: entry.message,
      retryable: entry.retryable,
      hint: entry.hint,
      detail: detailParts.length > 0 ? detailParts.join('\n') : undefined,
      status,
    };
  }

  // 网络层失败：fetch 抛错，没有任何响应对象。
  if (input.error instanceof Error && status === undefined) {
    return {
      errorCode: 'network',
      message: MESSAGES.network.message,
      retryable: true,
      hint: MESSAGES.network.hint,
      detail: redactPaths(input.error.message),
    };
  }

  const errorCode = codeFromStatus(status);
  const entry = MESSAGES[errorCode] ?? MESSAGES.unknown;
  return {
    errorCode,
    message: entry.message,
    retryable: entry.retryable,
    hint: entry.hint,
    detail: input.error ? redactPaths(String(input.error)) : undefined,
    status,
  };
}
