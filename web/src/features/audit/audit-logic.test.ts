import { describe, expect, it } from 'vitest';

import type { ArtifactResponse, MetaResponse } from '@/generated/api';

import {
  ARTIFACT_LIST_NOTE,
  DATA_BOUNDARY_STATEMENT,
  artifactStateRows,
  boundaryRows,
  deploymentRows,
  kindRows,
  metaFacts,
  scanProtectedNames,
} from './audit-logic';

function meta(overrides: Partial<MetaResponse> = {}): MetaResponse {
  return {
    auth_required: false,
    contract_version: '1.3.0',
    default_deployment_mode: 'local_cloud',
    deployment_modes: [],
    engine_version: '0.4.1',
    nav_modules: ['overview', 'workbench'],
    process_control_enabled: false,
    stream_transport: 'sse',
    ...overrides,
  };
}

export function artifact(overrides: Partial<ArtifactResponse> = {}): ArtifactResponse {
  return {
    artifact_id: 'run-summary',
    display_name: 'run_summary.json',
    downloadable: false,
    kind: 'summary',
    media_type: 'application/json',
    run_id: 'r1',
    size_bytes: 2048,
    state: 'available',
    ...overrides,
  };
}

describe('部署模式（/api/meta）', () => {
  it('meta 缺失时是空列表，不编一个默认模式出来', () => {
    expect(deploymentRows(null)).toEqual([]);
    expect(deploymentRows(undefined)).toEqual([]);
  });

  it('supported_transports 按字面透传：后端填的是模式名本身，不是传输方式', () => {
    const rows = deploymentRows(
      meta({
        deployment_modes: [
          { available: true, detail: '纯云端', mode: 'local_cloud', supported_transports: ['local_cloud'] },
          { available: false, mode: 'local_desktop', supported_transports: [] },
        ],
      }),
    );

    expect(rows.map((row) => row.mode)).toEqual(['local_cloud', 'local_desktop']);
    // app.py:221,230,243 往里塞的是 [mode]，所以读出来就是模式名。
    // 前端不改叫「传输方式」，否则把命名缺陷讲成了事实。
    expect(rows[0].supportedTransports).toBe('local_cloud');
    // 空数组不能渲染成空字符串，那看起来像「有但没写」。
    expect(rows[1].supportedTransports).toBe('未记录');
    expect(rows[0].available).toEqual({ value: '可用', recorded: true });
    expect(rows[1].available).toEqual({ value: '不可用', recorded: true });
    expect(rows[1].detail).toEqual({ value: '未记录', recorded: false });
  });

  it('默认模式只标一个，且取自 default_deployment_mode', () => {
    const rows = deploymentRows(
      meta({
        default_deployment_mode: 'ssh_cloud',
        deployment_modes: [
          { available: true, mode: 'local_cloud', supported_transports: ['local_cloud'] },
          { available: true, mode: 'ssh_cloud', supported_transports: ['ssh_cloud'] },
        ],
      }),
    );
    expect(rows.map((row) => row.isDefault)).toEqual([false, true]);
  });
});

describe('部署事实（metaFacts）', () => {
  it('八项固定标签，且不含 nav_modules / preset_names', () => {
    const labels = metaFacts(meta()).map((row) => row.label);
    expect(labels).toEqual([
      '契约版本',
      '引擎版本',
      '引擎提交',
      '流式传输方式',
      '需要鉴权',
      '允许浏览器控制进程',
      '任务目录已配置',
      '服务器档案已配置',
    ]);
    // 功能清单不是边界事实，列出来会让这页看起来比实际查到的更多。
    expect(labels.some((label) => /导航|预设|nav|preset/i.test(label))).toBe(false);
  });

  it('meta 缺失时八项全部未记录', () => {
    const rows = metaFacts(null);
    expect(rows).toHaveLength(8);
    expect(rows.every((row) => row.cell.recorded === false)).toBe(true);
    expect(rows.every((row) => row.cell.value === '未记录')).toBe(true);
  });

  it('布尔三态：true→是、false→否、缺失→未记录', () => {
    const rows = metaFacts(
      meta({ auth_required: true, process_control_enabled: false, server_profiles_enabled: undefined }),
    );
    const byLabel = Object.fromEntries(rows.map((row) => [row.label, row.cell]));
    expect(byLabel['需要鉴权']).toEqual({ value: '是', recorded: true });
    expect(byLabel['允许浏览器控制进程']).toEqual({ value: '否', recorded: true });
    expect(byLabel['任务目录已配置']).toEqual({ value: '未记录', recorded: false });
    expect(byLabel['服务器档案已配置']).toEqual({ value: '未记录', recorded: false });
  });

  it('stream_transport 原样透传，不拿它推断数据位置', () => {
    const rows = metaFacts(meta({ stream_transport: 'websocket' }));
    expect(rows.find((row) => row.label === '流式传输方式')?.cell.value).toBe('websocket');
  });
});

describe('运行制品状态（artifact_states）', () => {
  it('按名字排序，值原样渲染不翻译', () => {
    const rows = artifactStateRows({ tree: 'available', run_summary: 'missing', fe_db: 'invalid' });
    expect(rows.map((row) => row.name)).toEqual(['fe_db', 'run_summary', 'tree']);
    expect(rows.map((row) => row.state)).toEqual(['invalid', 'missing', 'available']);
  });

  it('缺失时是空列表', () => {
    expect(artifactStateRows(null)).toEqual([]);
    expect(artifactStateRows(undefined)).toEqual([]);
    expect(artifactStateRows({})).toEqual([]);
  });
});

describe('制品边界（boundaryRows）', () => {
  it('清单未取到时是空列表，与「取到了但一件制品都没有」分开', () => {
    expect(boundaryRows(undefined)).toEqual([]);
    expect(boundaryRows([])).toEqual([]);
  });

  it('先按 kind 再按 display_name 排序，与后端返回顺序无关', () => {
    const rows = boundaryRows([
      artifact({ artifact_id: 'b', display_name: 'tree.json', kind: 'tree' }),
      artifact({ artifact_id: 'a', display_name: 'b.log', kind: 'log' }),
      artifact({ artifact_id: 'c', display_name: 'a.log', kind: 'log' }),
    ]);
    expect(rows.map((row) => row.displayName)).toEqual(['a.log', 'b.log', 'tree.json']);
  });

  it('downloadable 只认严格 true，尺寸与媒体类型缺失记为未记录', () => {
    const rows = boundaryRows([
      artifact({ artifact_id: 'x', media_type: '', size_bytes: null }),
      artifact({ artifact_id: 'y', downloadable: true, size_bytes: 512 }),
    ]);
    const byId = Object.fromEntries(rows.map((row) => [row.artifactId, row]));
    expect(byId['x'].downloadable).toBe(false);
    expect(byId['x'].mediaType).toEqual({ value: '未记录', recorded: false });
    expect(byId['x'].sizeBytes).toEqual({ value: '未记录', recorded: false });
    expect(byId['y'].downloadable).toBe(true);
    expect(byId['y'].sizeBytes).toEqual({ value: '512 B', recorded: true });
  });
});

describe('制品分类（kindRows）', () => {
  it('按实际数据算 是 / 部分 / 否，不把后端的不可下载清单硬编码到前端', () => {
    const rows = kindRows([
      // program 在后端属于 `_NON_DOWNLOADABLE_KINDS`，但这一条 downloadable=true。
      // 前端必须照数据说「是」，否则就是在替后端下结论。
      artifact({ artifact_id: 'p1', display_name: 'a.py', downloadable: true, kind: 'program' }),
      artifact({ artifact_id: 'l1', display_name: 'a.log', downloadable: true, kind: 'log' }),
      artifact({ artifact_id: 'l2', display_name: 'b.log', downloadable: false, kind: 'log' }),
      artifact({ artifact_id: 's1', display_name: 'run_summary.json', kind: 'summary' }),
    ]);
    const byKind = Object.fromEntries(rows.map((row) => [row.kind, row]));
    expect(rows.map((row) => row.kind)).toEqual(['log', 'program', 'summary']);
    expect(byKind['program'].downloadable.value).toBe('是');
    expect(byKind['log'].downloadable.value).toBe('部分');
    expect(byKind['summary'].downloadable.value).toBe('否');
    expect(byKind['log'].count).toEqual({ value: '2', recorded: true });
  });

  it('清单未取到时是空列表', () => {
    expect(kindRows(undefined)).toEqual([]);
  });
});

describe('禁止字段扫描（scanProtectedNames）', () => {
  it('同时扫 display_name 与 artifact_id，所以扫过的名字数是制品数的两倍', () => {
    const result = scanProtectedNames([
      artifact({ artifact_id: 'run-summary', display_name: 'run_summary.json' }),
      artifact({ artifact_id: 'tree', display_name: 'tree.json' }),
    ]);
    expect(result.scanned).toEqual({ value: '4', recorded: true });
    expect(result.leaked).toBe(0);
  });

  it('命中时只报数量：返回值里没有任何字段能把名字带出去', () => {
    const result = scanProtectedNames([
      artifact({ artifact_id: 'holdout-set', display_name: 'holdout_labels.csv' }),
    ]);
    // display_name 与 artifact_id 各命中一次。
    expect(result.leaked).toBe(2);
    expect(Object.keys(result).sort()).toEqual(['leaked', 'scanned']);
    // 这条断言才是重点：命中内容本身不得出现在返回值里，
    // 否则组件一旦渲染整个对象，页面上就有了 holdout 字样（PRD §7.8）。
    expect(JSON.stringify(result)).not.toContain('holdout');
  });

  it('额外名字一并计入扫描范围，null 不崩', () => {
    const result = scanProtectedNames([], ['holdout.parquet', null, undefined, 'train.csv']);
    expect(result.scanned).toEqual({ value: '4', recorded: true });
    expect(result.leaked).toBe(1);
  });

  it('清单未取到时扫过 0 个，不谎称「干净」', () => {
    const result = scanProtectedNames(undefined);
    expect(result.scanned).toEqual({ value: '0', recorded: true });
    expect(result.leaked).toBe(0);
  });
});

describe('PRD 13.4 的口径', () => {
  it('边界声明用「受控云端环境」，并明确不宣称零数据出域', () => {
    expect(DATA_BOUNDARY_STATEMENT).toContain('受控云端环境');
    expect(DATA_BOUNDARY_STATEMENT).toContain('不宣称「零数据出域」');
  });

  it('制品清单说明区分「清单里没有」与「state = missing」', () => {
    expect(ARTIFACT_LIST_NOTE).toContain('state 恒为 available');
    expect(ARTIFACT_LIST_NOTE).toContain('清单里没有');
  });
});
