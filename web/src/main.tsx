import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { AppProviders } from '@/app/providers';
import { applyTheme, useUiStore } from '@/stores/ui-store';

import '@/styles/theme.css';

// 在首帧前应用持久化的主题，避免闪白。
applyTheme(useUiStore.getState().theme);

const container = document.getElementById('root');
if (!container) {
  throw new Error('找不到 #root 挂载点');
}

createRoot(container).render(
  <StrictMode>
    <AppProviders />
  </StrictMode>,
);
