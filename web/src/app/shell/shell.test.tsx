/**
 * 设置抽屉与帮助弹窗测试（TODO 阶段 3 测试：设置抽屉不占侧栏）。
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { HelpDialog } from '@/app/shell/HelpDialog';
import { SettingsDrawer } from '@/app/shell/SettingsDrawer';
import { useUiStore } from '@/stores/ui-store';

beforeEach(() => {
  localStorage.clear();
  useUiStore.setState({ theme: 'light' });
  document.documentElement.dataset.theme = 'light';
});

describe('SettingsDrawer', () => {
  it('关闭时不渲染任何内容', () => {
    const { container } = render(<SettingsDrawer open={false} onClose={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('打开时是 dialog，且不产生任何侧栏导航项', () => {
    const { container } = render(<SettingsDrawer open onClose={() => {}} />);
    expect(screen.getByRole('dialog', { name: '设置' })).toBeInTheDocument();
    expect(container.querySelectorAll('[data-nav-item]')).toHaveLength(0);
  });

  it('切换主题会写入 <html data-theme> 与 store', async () => {
    const user = userEvent.setup();
    render(<SettingsDrawer open onClose={() => {}} />);

    await user.click(screen.getByRole('button', { name: '深色' }));

    expect(useUiStore.getState().theme).toBe('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('Qwen 设置说明连通结果在顶部徽章，而不是在这里配置', () => {
    render(<SettingsDrawer open onClose={() => {}} />);
    expect(screen.getByText(/是否连通看顶部徽章/)).toBeInTheDocument();
  });

  it('按 Esc 会关闭', async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<SettingsDrawer open onClose={onClose} />);

    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe('HelpDialog', () => {
  it('列出四个模块的职责边界', () => {
    render(<HelpDialog open onClose={() => {}} />);
    for (const label of ['总览', '进化工作台', '知识发现', '结果与报告']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it('说明评分只来自 evaluator，前端不重算', () => {
    render(<HelpDialog open onClose={() => {}} />);
    expect(screen.getByText(/前端只展示、不重算/)).toBeInTheDocument();
  });
});
