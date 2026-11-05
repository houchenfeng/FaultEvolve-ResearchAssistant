import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { DeploymentModeCards } from '@/features/intake/DeploymentModeCards';
import type { DeploymentModeAvailability } from '@/generated/api';

const MODES: DeploymentModeAvailability[] = [
  { mode: 'local_cloud', available: true, supported_transports: ['local_cloud'], detail: '本机可用' },
  { mode: 'ssh_cloud', available: false, supported_transports: [], detail: 'asyncssh 不可用' },
  { mode: 'local_desktop', available: false, supported_transports: [], detail: 'P0 不提供该模式' },
];

describe('部署模式卡片', () => {
  it('默认停在纯云端，点混合模式只打开说明', async () => {
    const user = userEvent.setup();
    render(<DeploymentModeCards modes={MODES} />);

    expect(screen.getByRole('button', { name: /纯云端/ })).toHaveAttribute('aria-pressed', 'true');
    await user.click(screen.getByRole('button', { name: /混合模式/ }));

    expect(screen.getByRole('dialog', { name: '部署模式说明' })).toHaveTextContent('本地私有评估');
    expect(screen.getByRole('button', { name: /纯云端/ })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /混合模式/ })).toHaveAttribute('aria-pressed', 'false');
  });

  it('纯本地说明使用后端给的 detail', async () => {
    const user = userEvent.setup();
    render(<DeploymentModeCards modes={MODES} />);
    await user.click(screen.getByRole('button', { name: /纯本地/ }));
    expect(screen.getByRole('dialog', { name: '部署模式说明' })).toHaveTextContent('P0 不提供该模式');
  });
});
