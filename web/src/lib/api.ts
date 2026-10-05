/**
 * API 客户端薄封装。
 *
 * 业务代码只能从 `@/generated/api` 引用类型与 SDK 函数（TODO 1.5），
 * 这里只做两件事：配置 baseUrl，以及把 `{ data, error, response }` 归一化成
 * 抛出结构化 `ApiError` 的 Promise。
 */
import { client } from '@/generated/api/client.gen';
import type { ApiError } from '@/lib/api-error';
import { normalizeApiError } from '@/lib/api-error';

/** 默认走同源 `/api`（开发期由 Vite proxy 转发到 fe web serve）。 */
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? '';

export function configureApiClient(): void {
  client.setConfig({ baseUrl: API_BASE_URL });
}

/** 携带结构化错误信息的异常，供 TanStack Query 的 error 分支使用。 */
export class FaultEvolveApiError extends Error {
  readonly apiError: ApiError;

  constructor(apiError: ApiError) {
    super(apiError.message);
    this.name = 'FaultEvolveApiError';
    this.apiError = apiError;
  }
}

interface SdkResult<T> {
  data?: T;
  error?: unknown;
  response?: Response;
}

/** 把 SDK 的返回结果摊平成数据或抛错。 */
export async function unwrap<T>(result: Promise<SdkResult<T>>): Promise<T> {
  const settled = await result;
  if (settled.error !== undefined) {
    throw new FaultEvolveApiError(
      normalizeApiError({ error: settled.error, response: settled.response }),
    );
  }
  if (settled.data === undefined) {
    throw new FaultEvolveApiError(
      normalizeApiError({ error: undefined, response: settled.response }),
    );
  }
  return settled.data;
}

/** 把 TanStack Query 的 error 归一化成可直接渲染的 ApiError。 */
export function toApiError(error: unknown): ApiError {
  if (error instanceof FaultEvolveApiError) return error.apiError;
  return normalizeApiError({ error });
}
