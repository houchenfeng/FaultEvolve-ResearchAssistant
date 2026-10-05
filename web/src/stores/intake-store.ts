/**
 * 任务录入状态（阶段 4 / PRD §15.1）。
 *
 * 只存「非敏感」的当前选择：taskId / serverProfileId / preset / patch / notes。
 * 明确不进 URL、不进 localStorage：notes 可能包含运维细节，刷新即失是特性
 * 而不是缺陷；服务器密钥只存 profile ID 与掩码状态（TODO 4.3）。
 *
 * 「已自定义」的唯一判据是 patch 非空（TODO 阶段 4 测试项），
 * 不从 UI 状态猜——用户改了又改回去，patch 恢复为空就是没自定义。
 */
import { create } from 'zustand';

/** 知识注入选项（D-C=C1）：只提供能映射到真实引擎字段的四项。 */
export type KnowledgeMode = 'off' | 'default' | 'auto' | 'tournament';

export const KNOWLEDGE_MODE_LABEL: Record<KnowledgeMode, string> = {
  off: '不使用知识注入',
  default: '使用任务默认知识包',
  auto: '启用运行中自动发现',
  tournament: '自动发现 + 机制辩论赛',
};

/** 知识选项 → config patch 片段。映射不了引擎字段的选项不在此列（D-C）。 */
export function knowledgePatch(mode: KnowledgeMode): Record<string, unknown> {
  switch (mode) {
    case 'off':
      return { knowledge: { enabled: false } };
    case 'default':
      return {};
    case 'auto':
      return { discovery: { enabled: true } };
    case 'tournament':
      return {
        discovery: { enabled: true, tournament: { enabled: true } },
      };
  }
}

/** 深合并：对象递归，标量与数组整体替换（与后端 presets.merge_patch 同语义）。 */
function deepMerge(base: Record<string, unknown>, patch: Record<string, unknown>): Record<string, unknown> {
  const merged: Record<string, unknown> = { ...base };
  for (const [key, value] of Object.entries(patch)) {
    const current = merged[key];
    if (
      current !== null &&
      typeof current === 'object' &&
      !Array.isArray(current) &&
      value !== null &&
      typeof value === 'object' &&
      !Array.isArray(value)
    ) {
      merged[key] = deepMerge(current as Record<string, unknown>, value as Record<string, unknown>);
    } else {
      merged[key] = value;
    }
  }
  return merged;
}

function isEmptyPatch(patch: Record<string, unknown>): boolean {
  return Object.keys(patch).length === 0;
}

interface IntakeState {
  taskId: string | null;
  serverProfileId: string | null;
  preset: string;
  /** 用户对预设的字段级覆盖。空 = 完全按预设走。 */
  patch: Record<string, unknown>;
  knowledgeMode: KnowledgeMode;
  notes: string;
  /** 服务端 merge 校验的结果（「生成配置预览」驱动）。idle = 还没校验过。 */
  presetPreview: 'idle' | 'valid' | 'invalid';

  setTask: (taskId: string | null) => void;
  setServerProfile: (profileId: string | null) => void;
  /** 切换预设会清空 patch：三档是三套不同的基线。 */
  setPreset: (name: string) => void;
  /** 记录一个字段级覆盖（「已自定义」由此产生）。 */
  applyPatch: (fragment: Record<string, unknown>) => void;
  /** 恢复默认：patch 清空，「已自定义」消失（TODO 阶段 4 测试项）。 */
  resetToPreset: () => void;
  setKnowledgeMode: (mode: KnowledgeMode) => void;
  setNotes: (text: string) => void;
  setPresetPreview: (state: IntakeState['presetPreview']) => void;
}

export const useIntakeStore = create<IntakeState>((set) => ({
  taskId: null,
  serverProfileId: null,
  preset: 'standard',
  patch: {},
  knowledgeMode: 'default',
  notes: '',
  presetPreview: 'idle',

  setTask: (taskId) => set({ taskId }),
  setServerProfile: (serverProfileId) => set({ serverProfileId }),
  setPreset: (name) => set({ preset: name, patch: {}, presetPreview: 'idle' }),
  applyPatch: (fragment) =>
    set((state) => ({ patch: deepMerge(state.patch, fragment) })),
  resetToPreset: () => set({ patch: {}, presetPreview: 'idle' }),
  setKnowledgeMode: (knowledgeMode) => set({ knowledgeMode }),
  setNotes: (notes) => set({ notes }),
  setPresetPreview: (presetPreview) => set({ presetPreview }),
}));

/** 「已自定义」：patch 非空（知识选项走独立字段，不算自定义预算字段）。 */
export function selectIsCustomized(state: IntakeState): boolean {
  return !isEmptyPatch(state.patch);
}

/**
 * 由 patch 与知识模式组合出提交给启动端点的 patch。
 *
 * 与 `buildConfigPatch` 同语义，但只依赖两个字段——启动页要把它放进 `useMemo`，
 * 而 zustand 的 selector 每次返回新对象会触发无谓重渲染，所以按字段取。
 */
export function composeConfigPatch(
  patch: Record<string, unknown>,
  mode: KnowledgeMode,
): Record<string, unknown> {
  return deepMerge(patch, knowledgePatch(mode));
}

/** 提交给 merge 端点的完整 patch：字段覆盖 + 知识注入映射。 */
export function buildConfigPatch(state: IntakeState): Record<string, unknown> {
  return composeConfigPatch(state.patch, state.knowledgeMode);
}
