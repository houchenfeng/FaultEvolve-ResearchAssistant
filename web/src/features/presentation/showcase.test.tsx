import { fireEvent, render, screen, cleanup } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { ShowcasePage } from './ShowcasePage';
import evidence from './evidence.json';

vi.mock('@tanstack/react-router', () => ({
  Link: ({ children, to }: { children: ReactNode; to: string }) => <a href={to}>{children}</a>,
}));
afterEach(cleanup);

describe('competition presentation', () => {
  it('shows archived evidence and discloses validation selection', () => {
    render(<ShowcasePage />);
    expect(screen.getByText(/验证集参与搜索，尚未独立复验/)).toBeInTheDocument();
    expect(evidence.models.find(model => model.id === 'hybrid')?.metrics.combined_score).toBeCloseTo(42.5306813464);
    expect(screen.getByRole('link', { name: /下载实验摘要/ })).toHaveAttribute('href', '/evidence/hdd-results.json');
  });
  it('switches to runtime without hiding the cost tradeoff', () => {
    render(<ShowcasePage />);
    fireEvent.click(screen.getByRole('button', { name: '运行耗时' }));
    expect(screen.getByText('25.80 s')).toBeInTheDocument();
    expect(screen.getByText('越低越好')).toBeInTheDocument();
    expect(screen.getByText(/最佳混合方案耗时更长/)).toBeInTheDocument();
  });
  it('explains independent strategies and summary adoption without inventing run data', () => {
    render(<ShowcasePage />);
    fireEvent.click(screen.getByRole('tab', { name: '三岛协作' }));
    fireEvent.click(screen.getByRole('button', { name: /误漏报优化岛/ }));
    expect(screen.getByText('把错例变成下一轮假设')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /交换经验/ }));
    expect(screen.getByText(/接收岛独立决定是否采纳/)).toBeInTheDocument();
    expect(screen.getByRole('img')).toHaveAccessibleName(/非真实运行轨迹/);
  });
});
