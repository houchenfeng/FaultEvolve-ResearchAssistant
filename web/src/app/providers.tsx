import { QueryClientProvider } from '@tanstack/react-query';
import type { QueryClient } from '@tanstack/react-query';
import { RouterProvider } from '@tanstack/react-router';
import { useState } from 'react';

import type { createAppRouter } from '@/app/router';
import { router as defaultRouter } from '@/app/router';
import { configureApiClient } from '@/lib/api';
import { createQueryClient } from '@/lib/query-client';

// baseUrl 只在启动时配置一次；SDK 函数默认使用这个 client 实例。
configureApiClient();

export interface AppProvidersProps {
  /** 测试可注入 memory-history 路由器。 */
  router?: ReturnType<typeof createAppRouter>;
  queryClient?: QueryClient;
}

export function AppProviders({ router, queryClient }: AppProvidersProps = {}) {
  const [fallbackClient] = useState(createQueryClient);

  return (
    <QueryClientProvider client={queryClient ?? fallbackClient}>
      <RouterProvider router={router ?? defaultRouter} />
    </QueryClientProvider>
  );
}
