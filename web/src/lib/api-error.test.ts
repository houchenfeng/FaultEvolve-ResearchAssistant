import { describe, expect, it } from 'vitest';

import { normalizeApiError, redactPaths } from '@/lib/api-error';

describe('normalizeApiError（PRD 15.3 / TODO 3.5）', () => {
  it('优先使用 error_code 对应的中文文案', () => {
    const error = normalizeApiError({
      error: { error_code: 'run.not_found', message: 'Run not found' },
      response: { status: 404 },
    });

    expect(error.errorCode).toBe('run.not_found');
    expect(error.retryable).toBe(false);
    expect(error.message).toContain('找不到');
    expect(error.hint).toBeTruthy();
  });

  it('not_supported 明确表示能力未实现且不可重试', () => {
    const error = normalizeApiError({
      error: { error_code: 'not_supported', message: 'paused runs are not supported' },
      response: { status: 409 },
    });

    expect(error.retryable).toBe(false);
    expect(error.message).toContain('尚未实现');
  });

  it('后端不可用可重试', () => {
    const error = normalizeApiError({
      error: { error_code: 'backend.unavailable', message: 'down' },
      response: { status: 503 },
    });

    expect(error.retryable).toBe(true);
  });

  it('网络层异常归一到 network', () => {
    const error = normalizeApiError({ error: new TypeError('Failed to fetch') });
    expect(error.errorCode).toBe('network');
    expect(error.retryable).toBe(true);
    expect(error.status).toBeUndefined();
  });

  it('没有响应体时用 HTTP 状态码兜底', () => {
    expect(normalizeApiError({ error: 'boom', response: { status: 500 } }).errorCode).toBe(
      'internal',
    );
    expect(normalizeApiError({ error: 'nope', response: { status: 422 } }).errorCode).toBe(
      'request.invalid',
    );
  });

  it('技术详情里的绝对路径被脱敏', () => {
    const error = normalizeApiError({
      error: {
        error_code: 'artifact.invalid_json',
        message: 'bad json',
        detail: 'failed at C:\\Users\\A\\runs\\demo\\tree.json and /home/hcf/faultevolve/fe.db',
      },
      response: { status: 500 },
    });

    expect(error.detail).not.toContain('C:\\Users');
    expect(error.detail).not.toContain('/home/hcf');
    expect(error.detail).toContain('<本地路径>');
  });
});

describe('redactPaths', () => {
  it('替换 Windows 与 POSIX 绝对路径', () => {
    expect(redactPaths('see D:/x/y.json')).toBe('see <本地路径>');
    expect(redactPaths('see /mnt/nas/run')).toBe('see <本地路径>');
  });
});
