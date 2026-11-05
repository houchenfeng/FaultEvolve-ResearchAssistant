/**
 * 知识发现与结果报告组件测试（TODO 6.1–6.4 的组件半边）。
 *
 * 断言的是**行为**而不是快照，重点就是 TODO §9 九条测试要求里属于界面层的那些：
 *
 * | TODO §9 要求 | 本文件落点 |
 * |---|---|
 * | discovery disabled 空状态 | 「现象」「辩论赛」两处空态文案必须不同 |
 * | claim sandbox failure | 沙箱错误原文 + 横幅计数 |
 * | confirmed/refuted/undetermined 映射 | 五个 grade 的中文标签，且 `未定 ≠ 未评级` |
 * | tournament 未启用 | 空态文案点名"未启用" |
 * | manifest 字段缺失 | 分项指标显示「未记录」而不是 0 |
 * | 落在波动区间 → 未形成明确改进证据 | 横幅必须出现那句话 |
 * | 报告下载 MIME 和文件名正确 | `<a download>` 的名字与 MIME 文本 |
 * | 不允许下载 holdout 或任意路径 | 四类拒绝，且**不渲染链接** |
 *
 * 「多数据集不可比较 → N/A」由 `report-logic.test.ts` 的 `comparisonTable`
 * 用例覆盖（本阶段的对比只有纯函数，不构成独立页面）。
 */
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type {
  ArtifactResponse,
  ReportManifestResponse,
  RunDetailResponse,
  ScoreboardEntryResponse,
} from '@/generated/api';
import { PhenomenaPanel } from '@/features/discovery/PhenomenaPanel';
import { ReportPanel } from '@/features/discovery/ReportPanel';
import { TournamentBracket } from '@/features/discovery/TournamentBracket';
import { NO_CLEAR_EVIDENCE_TEXT } from '@/features/discovery/report-logic';
import type { DiscoveryResponse } from '@/features/discovery/types';

// --------------------------------------------------------------------------
// 夹具
// --------------------------------------------------------------------------


function discovery(overrides: Partial<DiscoveryResponse> = {}): DiscoveryResponse {
  return {
    contract_version: '1.5.0',
    run_id: 'run-1',
    enabled: true,
    phenomena: [],
    claims: [],
    theories: [],
    matches: [],
    certificates: [],
    controls: [],
    ...overrides,
  };
}

function runDetail(overrides: Partial<RunDetailResponse> = {}): RunDetailResponse {
  return {
    contract_version: '1.5.0',
    run_id: 'run-1',
    data_state: 'complete',
    artifact_states: {},
    warnings: [],
    outcome: {
      initial_score: 22.81,
      best_score: 33.7,
      improvement: 10.89,
      iterations_done: 18,
      valid_rate: 0.75,
      stop_reason: 'target_reached',
    },
    ...overrides,
  };
}

function artifact(overrides: Partial<ArtifactResponse> = {}): ArtifactResponse {
  return {
    artifact_id: 'tree',
    display_name: 'tree.json',
    downloadable: true,
    kind: 'data',
    media_type: 'application/json',
    run_id: 'run-1',
    size_bytes: 2048,
    state: 'available',
    ...overrides,
  };
}

// --------------------------------------------------------------------------
// TODO 6.2 现象
// --------------------------------------------------------------------------

describe('PhenomenaPanel（TODO 6.2）', () => {
  it('discovery disabled 时给出「未启用」这条专属原因', () => {
    render(<PhenomenaPanel discovery={discovery({ enabled: false })} />);
    expect(screen.getByText('知识发现未启用，本次运行没有进行假设检验')).toBeInTheDocument();
  });

  it('启用但没产出，与「未启用」用不同的话说', () => {
    render(<PhenomenaPanel discovery={discovery({ enabled: true, phenomena_state: 'available' })} />);
    expect(screen.getByText('知识发现已启用，但本次运行没有产生任何现象记录')).toBeInTheDocument();
  });

  it('沙箱失败：错误原文与横幅计数都不能丢', () => {
    render(
      <PhenomenaPanel
        discovery={discovery({
          phenomena: [{ claim_id: 'c-1', grade: 'undetermined', payload: { effect: 0.02 } }],
          claims: [
            {
              id: 'c-1',
              status: 'sandbox_failed',
              error: 'ModuleNotFoundError: no module named x',
            },
          ],
        })}
      />,
    );
    const block = screen.getByTestId('sandbox-failure');
    expect(within(block).getByText('ModuleNotFoundError: no module named x')).toBeInTheDocument();
    expect(screen.getByText(/有 1 条主张在沙箱里执行失败/)).toBeInTheDocument();
  });

  it('grade 五值映射成中文，且「未定」不等于「未评级」', () => {
    const row = (claimId: string, grade?: string) => ({
      claim_id: claimId,
      ...(grade ? { grade } : {}),
      payload: { effect: 0.01 },
    });
    render(
      <PhenomenaPanel
        discovery={discovery({
          phenomena: [
            row('c-ok', 'confirmed'),
            row('c-rev', 'revised'),
            row('c-new', 'discovered'),
            row('c-no', 'refuted'),
            row('c-und', 'undetermined'),
            row('c-none'),
          ],
          claims: [
            { id: 'c-ok', status: 'graded' },
            { id: 'c-rev', status: 'graded' },
            { id: 'c-new', status: 'graded' },
            { id: 'c-no', status: 'graded' },
            { id: 'c-und', status: 'graded' },
            { id: 'c-none', status: 'proposed' },
          ],
        })}
      />,
    );

    for (const label of ['已证实', '已修正', '新发现', '被否证', '未定', '未评级']) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    // 「未定」是跑完了证据不足，「未评级」是压根没评 —— 两条不同的路。
    const undetermined = screen.getByText('c-und').closest('article') as HTMLElement;
    expect(within(undetermined).getByText('未定')).toBeInTheDocument();
    expect(within(undetermined).queryByText('未评级')).toBeNull();
  });

  it('散文被引擎覆盖时出横幅说明原因，并点名这是引擎侧行为', () => {
    render(
      <PhenomenaPanel
        discovery={discovery({
          phenomena: [{ claim_id: 'c-1', grade: 'confirmed', payload: { effect: 0.05 } }],
          // status=graded ⇒ payload 已被检验结果覆盖 ⇒ 散文没了
          claims: [{ id: 'c-1', status: 'graded' }],
        })}
      />,
    );
    expect(screen.getByText(/1 条主张的散文未记录/)).toBeInTheDocument();
    // 「覆盖式写入」在横幅里出现两次（原因常量 + 补充说明），用 getAllByText
    expect(screen.getAllByText(/覆盖式写入/).length).toBeGreaterThan(0);
  });

  it('置信区间跨 0 的效应不被读成"有正向作用"', () => {
    render(
      <PhenomenaPanel
        discovery={discovery({
          phenomena: [
            { claim_id: 'c-1', payload: { effect: 0.001, ci_low: -0.02, ci_high: 0.03 } },
          ],
          claims: [{ id: 'c-1', status: 'graded', direction: '+' }],
        })}
      />,
    );
    expect(screen.getByTestId('effect-verdict')).toHaveTextContent('[-0.0200, 0.0300]');
    expect(screen.getByText('95% 置信区间跨 0，这个效应不能当作证据')).toBeInTheDocument();
  });
});

// --------------------------------------------------------------------------
// TODO 6.3 机制辩论赛
// --------------------------------------------------------------------------

describe('TournamentBracket（TODO 6.3）', () => {
  it('未启用与「表都没有」是两句不同的话', () => {
    const { unmount } = render(
      <TournamentBracket discovery={discovery({ enabled: false })} />,
    );
    expect(screen.getByText('知识发现未启用，本次运行没有进行机制辩论')).toBeInTheDocument();
    unmount();

    render(
      <TournamentBracket
        discovery={discovery({ enabled: true, mechanisms_state: 'missing', matches_state: 'missing' })}
      />,
    );
    expect(screen.getByText(/没有机制\/比赛表/)).toBeInTheDocument();
  });

  it('模型论点与数据裁决硬分区：机制进 arguments，比赛进 verdicts', () => {
    const { container } = render(
      <TournamentBracket
        discovery={discovery({
          theories: [
            { id: 'mech-claim-1', role: 'claim', title: '断电导致盘片划伤', status: 'established' },
          ],
          matches: [
            { mech_a: 'mech-claim-1', mech_b: 'mech-rival-1', test_type: 'holdout', supports: 'a', decisive: true },
          ],
          certificates: [
            { mechanism_id: 'mech-claim-1', rival_id: 'mech-rival-1', e_value: 12.5, test_type: 'holdout' },
          ],
        })}
      />,
    );

    const args = container.querySelector('[data-zone="arguments"]') as HTMLElement;
    const verdicts = container.querySelector('[data-zone="verdicts"]') as HTMLElement;
    expect(args).not.toBeNull();
    expect(verdicts).not.toBeNull();

    // 模型提出的机制只在论点区
    expect(within(args).getByText('断电导致盘片划伤')).toBeInTheDocument();
    expect(within(verdicts).queryByText('断电导致盘片划伤')).toBeNull();

    // 数据裁决（数据支持 / 证书）只在裁决区
    expect(within(verdicts).getByText('数据支持')).toBeInTheDocument();
    expect(within(verdicts).getByText('a 方胜')).toBeInTheDocument();
    expect(within(args).queryByText('a 方胜')).toBeNull();
    expect(within(args).queryByText('数据支持')).toBeNull();
  });

  it('六个阶段块都在，且顺序与 TODO 6.3 一致', () => {
    const { container } = render(
      <TournamentBracket
        discovery={discovery({
          theories: [{ id: 'm-1', role: 'claim', title: 'T' }],
          matches: [{ mech_a: 'm-1', mech_b: 'm-2', supports: 'a', decisive: false, test_type: 'holdout' }],
        })}
      />,
    );
    const stages = [...container.querySelectorAll('[data-stage]')].map((node) =>
      node.getAttribute('data-stage'),
    );
    expect(stages).toEqual(['1', '2', '3', '4', '5', '6']);
    // 未达决定性阈值的不能当证据
    expect(screen.getByText('a 方略胜（未达决定）')).toBeInTheDocument();
  });

  it('未知 role 不丢：原样点名，而不是笼统写「未识别」', () => {
    render(
      <TournamentBracket
        discovery={discovery({ theories: [{ id: 'm-x', role: 'novel_role', title: '新机制' }] })}
      />,
    );
    expect(screen.getByText('未识别机制（novel_role）')).toBeInTheDocument();
  });
});

// --------------------------------------------------------------------------
// TODO 6.4 结果与报告
// --------------------------------------------------------------------------

describe('ReportPanel（TODO 6.4）', () => {
  it('manifest 字段缺失 → 分项指标显示「未记录」，不是 0', () => {
    render(<ReportPanel runId="run-1" run={runDetail({ outcome: {} })} />);
    const rows = screen.getByText('完成代数').closest('[data-metric]') as HTMLElement;
    expect(within(rows).getByText('未记录')).toBeInTheDocument();
    expect(screen.getAllByText('未记录').length).toBeGreaterThanOrEqual(7);
  });

  it('提升落在波动区间内时，必须显示「未形成明确改进证据」', () => {
    render(
      <ReportPanel
        runId="run-1"
        run={runDetail({ outcome: { improvement: 0.012, initial_score: 22.8, best_score: 22.812 } })}
        noiseDelta={0.4}
      />,
    );
    const verdict = screen.getByTestId('noise-verdict');
    expect(verdict).toHaveAttribute('data-within-band', 'true');
    expect(verdict).toHaveTextContent(NO_CLEAR_EVIDENCE_TEXT);
    expect(NO_CLEAR_EVIDENCE_TEXT).toBe('未形成明确改进证据');
  });

  it('噪声带取不到时只说「无法判断」，绝不说「超出波动」', () => {
    render(
      <ReportPanel
        runId="run-1"
        run={runDetail({ outcome: { improvement: 10.89 } })}
        noiseDelta={null}
      />,
    );
    const verdict = screen.getByTestId('noise-verdict');
    expect(verdict).toHaveAttribute('data-within-band', 'unknown');
    expect(verdict).toHaveTextContent('缺少噪声带估计');
    expect(verdict).not.toHaveTextContent('超出运行波动');
  });

  it('目标方向不可得时明说按「越大越好」展示，不假装知道方向', () => {
    render(<ReportPanel runId="run-1" run={runDetail()} />);
    expect(screen.getByTestId('direction-unknown-note')).toBeInTheDocument();
    expect(screen.getByText(/未记录（按「越大越好」展示）/)).toBeInTheDocument();
  });

  it('方向为 lower 时按反号算提升（越负越好）', () => {
    render(
      <ReportPanel
        runId="run-1"
        run={runDetail({ outcome: { initial_score: 100, best_score: 80 } })}
        targetDirection="lower"
      />,
    );
    // 缺 improvement，由 initial-best 推得 +20（lower 任务里下降才是提升）
    expect(screen.getByText('越小越好')).toBeInTheDocument();
    const improvement = document.querySelector('[data-headline="improvement"]') as HTMLElement;
    expect(improvement).toHaveTextContent('+20.0000');
  });

  it('报告文件：下载名取 basename、MIME 与体积一并显示', () => {
    const manifest: ReportManifestResponse = {
      available: true,
      contract_version: '1.5.0',
      run_id: 'run-1',
      files: [
        {
          artifact_id: 'report_md',
          display_name: 'reports/run-1/summary.md',
          media_type: 'text/markdown',
          size_bytes: 1536,
          state: 'available',
        },
      ],
    };
    const { container } = render(
      <ReportPanel runId="run-1" run={runDetail()} reportManifest={manifest} />,
    );
    const link = within(container).getByRole('link', { name: 'summary.md' });
    expect(link).toHaveAttribute('href', '/api/runs/run-1/artifacts/report_md');
    expect(link).toHaveAttribute('download', 'summary.md');
    expect(screen.getByText('text/markdown')).toBeInTheDocument();
    expect(screen.getByText('1.5 KB')).toBeInTheDocument();
  });

  it('恢复报告不可得时说明原因，而不是渲染空清单', () => {
    render(
      <ReportPanel
        runId="run-1"
        run={runDetail()}
        reportManifest={{ available: false, contract_version: '1.5.0', run_id: 'run-1', files: [] }}
      />,
    );
    expect(screen.getByTestId('report-unavailable')).toBeInTheDocument();
  });

  it('holdout 制品即使 downloadable=true 也拒绝下载，且不渲染链接', () => {
    const { container } = render(
      <ReportPanel
        runId="run-1"
        run={runDetail()}
        artifacts={[artifact({ artifact_id: 'holdout_labels', display_name: 'holdout_labels.csv' })]}
      />,
    );
    expect(container.querySelector('[data-download-refusal="protected_name"]')).not.toBeNull();
    expect(within(container).queryByRole('link')).toBeNull();
  });

  it('路径穿越 / 非铸 id 一律拒绝', () => {
    const { container } = render(
      <ReportPanel
        runId="run-1"
        run={runDetail()}
        artifacts={[artifact({ artifact_id: '../../etc/passwd', display_name: 'passwd' })]}
      />,
    );
    expect(container.querySelector('[data-download-allowed]')).toBeNull();
    expect(container.querySelector('[data-download-refusal="invalid_id"]')).not.toBeNull();
  });

  it('引擎内部制品（downloadable=false）不提供入口', () => {
    const { container } = render(
      <ReportPanel
        runId="run-1"
        run={runDetail()}
        artifacts={[artifact({ artifact_id: 'fe', display_name: 'fe.db', downloadable: false })]}
      />,
    );
    expect(container.querySelector('[data-download-refusal="non_downloadable"]')).not.toBeNull();
    expect(within(container).queryByRole('link')).toBeNull();
  });

  it('Top-K 用服务端的名次，点节点能回连树', async () => {
    const user = userEvent.setup();
    const onLocateNode = vi.fn();
    const entries: ScoreboardEntryResponse[] = [
      { rank: 1, node_id: 'best-node-1', score: 33.7, is_best: true },
      { rank: 2, node_id: 'second-node', score: 30.1, is_best: false },
    ];
    render(
      <ReportPanel
        runId="run-1"
        run={runDetail()}
        leaderboard={entries}
        onLocateNode={onLocateNode}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'best-node-' }));
    expect(onLocateNode).toHaveBeenCalledWith('best-node-1');
  });

  it('数据边界审计把 missing 标出来，并透传契约警告', () => {
    render(
      <ReportPanel
        runId="run-1"
        run={runDetail({
          artifact_states: { run_summary: 'available', tree: 'missing', discovery: 'invalid' },
          warnings: [{ field: 'discovery_rounds', reason: '与事件流矛盾' }],
        })}
      />,
    );
    expect(screen.getByText('不存在')).toBeInTheDocument();
    expect(screen.getByText('不可解析')).toBeInTheDocument();
    expect(screen.getByText(/discovery_rounds/)).toBeInTheDocument();
  });
});
