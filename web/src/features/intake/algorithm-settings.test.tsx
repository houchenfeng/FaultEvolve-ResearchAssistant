import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { PresetSelector } from './PresetSelector';
import { useIntakeStore } from '@/stores/intake-store';
import { mergePresetApiPresetsNameMergePost } from '@/generated/api';

vi.mock('@/generated/api', () => ({
  listPresetsApiPresetsGet: vi.fn(async () => ({ data: { presets: [{
    name: 'standard', display_name_zh: '标准', config: {
      islands: { enabled: true }, workflow: { enabled: true, hierarchical: { enabled: true } },
    },
  }] } })),
  mergePresetApiPresetsNameMergePost: vi.fn(async () => ({ data: { name: 'standard', config: {} } })),
}));
beforeEach(() => { useIntakeStore.getState().setPreset('standard'); vi.clearAllMocks(); });
afterEach(cleanup);

it('sends algorithm overrides through server validation and invalidates a stale preview', async () => {
  render(<QueryClientProvider client={new QueryClient()}><PresetSelector /></QueryClientProvider>);
  const islands = await screen.findByRole('checkbox', { name: /多岛协作/ });
  expect(islands).toBeChecked();
  fireEvent.click(islands);
  const preview = screen.getByRole('button', { name: /生成配置预览/ });
  fireEvent.click(preview);
  await waitFor(() => expect(useIntakeStore.getState().presetPreview).toBe('valid'));
  expect(mergePresetApiPresetsNameMergePost).toHaveBeenLastCalledWith({ path: { name: 'standard' }, body: { islands: { enabled: false } } });
  fireEvent.click(screen.getByRole('checkbox', { name: /分层参数调优/ }));
  expect(useIntakeStore.getState().presetPreview).toBe('idle');
  expect(useIntakeStore.getState().patch).toEqual({ islands: { enabled: false }, workflow: { enabled: true, hierarchical: { enabled: false } } });
  fireEvent.click(screen.getByRole('button', { name: '恢复默认' }));
  expect(islands).toBeChecked();
  expect(useIntakeStore.getState().patch).toEqual({});
});
