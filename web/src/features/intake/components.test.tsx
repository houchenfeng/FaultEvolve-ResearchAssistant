/**
 * 录入组件渲染测试：启动前检查面板（D-A：只检查不启动）、
 * 知识注入的诚实禁用项、路径检查列表、备注框的「不成命令」声明。
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { PreflightPanel } from '@/features/intake/PreflightPanel';
import { derivePreflightChecks } from '@/features/intake/preflight-logic';
import { KnowledgeInjectionForm } from '@/features/intake/KnowledgeInjectionForm';
import { NotesTextarea } from '@/features/intake/NotesTextarea';
import { PathProbeList } from '@/features/intake/PathProbeList';
import { deriveArtifactCards } from '@/features/intake/task-artifacts-logic';
import { useIntakeStore } from '@/stores/intake-store';

const READY_CARD = {
  data_ready: true,
  data_missing: [],
  evaluator_ready: true,
  init_ready: true,
};

/** 全通过的检查集：按钮唯一可点的那一种输入。 */
function readyChecks() {
  return derivePreflightChecks({
    taskSelected: true,
    artifactCards: deriveArtifactCards(READY_CARD, false, false),
    serverSelected: true,
    presetValid: null,
  });
}

describe('PreflightPanel（阶段 7 起按钮真的会启动）', () => {
  it('能力缺失时禁用，并把原因说成能力问题而不是输入问题', () => {
    render(
      <PreflightPanel
        checks={readyChecks()}
        onLaunch={() => undefined}
        blockedReason="服务端未启用进程控制（FE_WEB_ENABLE_PROCESS_CONTROL=true）。当前只能查看历史运行。"
      />,
    );
    const launch = screen.getByRole('button', { name: '启动运行' });
    expect(launch).toBeDisabled();
    // 检查项全通过、却点不动 —— 文案必须解释是服务端能力缺失。
    expect(screen.getByText(/服务端未启用进程控制/)).toBeInTheDocument();
    expect(screen.queryByText(/当前有 .* 项未通过/)).not.toBeInTheDocument();
  });

  it('检查全通过且无能力阻塞时按钮可点，点击只回调、组件自己不发请求', async () => {
    const user = userEvent.setup();
    const onLaunch = vi.fn();
    render(<PreflightPanel checks={readyChecks()} onLaunch={onLaunch} />);

    const launch = screen.getByRole('button', { name: '启动运行' });
    expect(launch).toBeEnabled();
    await user.click(launch);
    expect(onLaunch).toHaveBeenCalledTimes(1);
  });

  it('请求进行中禁用并改文案，防重复提交', () => {
    render(<PreflightPanel checks={readyChecks()} onLaunch={() => undefined} launching />);
    expect(screen.getByRole('button', { name: '正在启动…' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: '启动运行' })).not.toBeInTheDocument();
  });

  it('启动失败时显示原因，但按钮恢复可点', () => {
    render(
      <PreflightPanel
        checks={readyChecks()}
        onLaunch={() => undefined}
        launchError="服务端拒绝：任务数据目录不可读"
      />,
    );
    expect(screen.getByText(/启动失败：服务端拒绝：任务数据目录不可读/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '启动运行' })).toBeEnabled();
  });

  it('存在警告时需勾选确认才显示「检查全部通过」', async () => {
    const user = userEvent.setup();
    const cards = deriveArtifactCards(READY_CARD, false, false).map((card) =>
      card.id === 'dataset' ? { ...card, state: 'warn' as const } : card,
    );
    const checks = derivePreflightChecks({
      taskSelected: true,
      artifactCards: cards,
      serverSelected: true,
      presetValid: null,
    });
    render(<PreflightPanel checks={checks} onLaunch={() => undefined} />);
    expect(screen.getByText(/存在 1 条警告/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '启动运行' })).toBeDisabled();
    expect(screen.queryByText('检查全部通过（警告已确认）。')).not.toBeInTheDocument();

    // 两个复选框（确认警告 / mock LLM），按可读名精确定位，别用裸 getByRole。
    await user.click(screen.getByRole('checkbox', { name: /我已知晓并接受/ }));
    expect(screen.getByText('检查全部通过（警告已确认）。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '启动运行' })).toBeEnabled();
  });

  it('有阻塞项时显示失败计数', () => {
    const checks = derivePreflightChecks({
      taskSelected: true,
      artifactCards: deriveArtifactCards(
        { ...READY_CARD, evaluator_ready: false },
        false,
        false,
      ),
      serverSelected: true,
      presetValid: null,
    });
    render(<PreflightPanel checks={checks} onLaunch={() => undefined} />);
    expect(screen.getByText(/当前有 1 项未通过/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '启动运行' })).toBeDisabled();
  });

  it('mock LLM 开关把新值交回页面，并写明它不调用真实模型', async () => {
    const user = userEvent.setup();
    const onMockLlmChange = vi.fn();
    render(
      <PreflightPanel
        checks={readyChecks()}
        onLaunch={() => undefined}
        mockLlm={false}
        onMockLlmChange={onMockLlmChange}
      />,
    );
    expect(screen.getByText(/不调用真实模型/)).toBeInTheDocument();
    await user.click(screen.getByRole('checkbox', { name: /使用 mock LLM/ }));
    expect(onMockLlmChange).toHaveBeenCalledWith(true);
  });
});

describe('KnowledgeInjectionForm', () => {
  it('「选择已有类别」诚实禁用并写明引擎限制', () => {
    render(<KnowledgeInjectionForm />);
    const disabled = screen.getByText('选择已有知识类别 / 知识簇').closest('label');
    expect(disabled).not.toBeNull();
    const input = disabled?.querySelector('input');
    expect(input).toBeTruthy();
    expect(input?.hasAttribute('disabled')).toBe(true);
    expect(screen.getByText(/引擎尚无类别过滤字段/)).toBeInTheDocument();
  });

  it('四档可选且写入 store', async () => {
    const user = userEvent.setup();
    useIntakeStore.setState({ knowledgeMode: 'default' });
    render(<KnowledgeInjectionForm />);
    await user.click(screen.getByLabelText('自动发现 + 机制辩论赛'));
    expect(useIntakeStore.getState().knowledgeMode).toBe('tournament');
  });
});

describe('Qwen 密钥检查', () => {
  it('未配置且未勾选 mock 时不能启动', () => {
    const checks = derivePreflightChecks({
      taskSelected: true,
      artifactCards: deriveArtifactCards(READY_CARD, false, false),
      serverSelected: true,
      presetValid: null,
      qwenConfigured: false,
      mockLlm: false,
    });
    render(<PreflightPanel checks={checks} onLaunch={() => undefined} />);
    expect(screen.getByRole('button', { name: '启动运行' })).toBeDisabled();
    expect(screen.getByText(/未配置 Qwen 密钥/)).toBeInTheDocument();
  });
});

describe('NotesTextarea', () => {
  it('明确标注备注不会作为命令执行', () => {
    render(<NotesTextarea value="" onChange={() => undefined} />);
    expect(screen.getByText('仅作为运行备注保存，不会作为命令执行。')).toBeInTheDocument();
  });
});

describe('PathProbeList', () => {
  it('按后端事实渲染：不存在为红、可写为绿、附注含剩余空间', () => {
    render(
      <PathProbeList
        probes={[
          { path: 'benchmark/hdd_mvp/data', exists: true, is_directory: true, writable: true, detail: '剩余 208.2 GB' },
          { path: 'runs/missing', exists: false, is_directory: false, writable: null, detail: '' },
        ]}
      />,
    );
    expect(screen.getByText(/benchmark\/hdd_mvp\/data/)).toBeInTheDocument();
    expect(screen.getByText(/存在 · 可写 · 剩余 208.2 GB/)).toBeInTheDocument();
    expect(screen.getByText(/runs\/missing/)).toBeInTheDocument();
    expect(screen.getByText(/不存在/)).toBeInTheDocument();
  });
});
