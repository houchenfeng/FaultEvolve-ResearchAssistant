import { describe, expect, it } from 'vitest';

import { qwenBadge } from '@/app/shell/TopBarBadges';
import type { MetaResponse } from '@/generated/api';

function meta(patch: Partial<MetaResponse>): MetaResponse {
  return patch as MetaResponse;
}

describe('qwenBadge', () => {
  it('没有读取到 meta 时显示未记录', () => {
    expect(qwenBadge(undefined).label).toBe('Qwen 未记录');
  });

  it('没有密钥时不把未探测说成未连通', () => {
    const badge = qwenBadge(meta({ qwen_configured: false, qwen_reachable: null }));
    expect(badge.label).toBe('Qwen 未配置');
  });

  it('模型列表成功才显示已连通', () => {
    const badge = qwenBadge(meta({ qwen_configured: true, qwen_reachable: true }));
    expect(badge.label).toBe('Qwen 已连通');
    expect(badge.tone).toBe('success');
  });

  it('密钥在但模型列表失败时显示未连通', () => {
    const badge = qwenBadge(meta({ qwen_configured: true, qwen_reachable: false }));
    expect(badge.label).toBe('Qwen 未连通');
    expect(badge.tone).toBe('warning');
  });
});
