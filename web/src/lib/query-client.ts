/**
 * TanStack Query 客户端工厂。
 *
 * 单独成文件是为了让 `providers.tsx` 只导出组件（react-refresh 约束）。
 */
import { QueryClient } from '@tanstack/react-query';

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // 制品在运行结束后是稳定的，30s 内不重复请求。
        staleTime: 30_000,
        retry: 1,
        refetchOnWindowFocus: false,
      },
    },
  });
}
