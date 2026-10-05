/**
 * 全局 UI 状态（Zustand）。
 *
 * 严格边界（TODO 3.4）：**只存**当前 run ID、选中节点、展开面板、主题和本地视图
 * 过滤器。任何服务端数据都由 TanStack Query 持有，禁止复制进这里再手工改形状。
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type ThemeMode = 'light' | 'dark';

/** 工作台页内标签（PRD 5.2：树/时间轴/排行榜不形成侧栏导航项）。 */
export type WorkbenchTab = 'tree' | 'timeline' | 'leaderboard';

interface UiState {
  /** 当前运行。深链接刷新后靠它恢复「进化工作台 / 知识发现 / 结果与报告」。 */
  currentRunId: string | null;
  /** 进化树中选中的节点。 */
  selectedNodeId: string | null;
  /** 已展开的面板标识（节点详情抽屉的分区等）。 */
  expandedPanels: string[];
  /** 亮/暗主题。 */
  theme: ThemeMode;
  /** 工作台当前的页内标签。 */
  workbenchTab: WorkbenchTab;

  setCurrentRunId: (runId: string | null) => void;
  setSelectedNodeId: (nodeId: string | null) => void;
  togglePanel: (panelId: string) => void;
  isPanelExpanded: (panelId: string) => boolean;
  setTheme: (theme: ThemeMode) => void;
  toggleTheme: () => void;
  setWorkbenchTab: (tab: WorkbenchTab) => void;
  resetRunView: () => void;
}

/** 把主题写到 <html data-theme>，样式层据此切换变量（见 styles/theme.css）。 */
export function applyTheme(theme: ThemeMode): void {
  if (typeof document !== 'undefined') {
    document.documentElement.dataset.theme = theme;
  }
}

export const useUiStore = create<UiState>()(
  persist(
    (set, get) => ({
      currentRunId: null,
      selectedNodeId: null,
      expandedPanels: [],
      theme: 'light',
      workbenchTab: 'tree',

      setCurrentRunId: (runId) => set({ currentRunId: runId, selectedNodeId: null }),
      setSelectedNodeId: (nodeId) => set({ selectedNodeId: nodeId }),

      togglePanel: (panelId) =>
        set((state) => ({
          expandedPanels: state.expandedPanels.includes(panelId)
            ? state.expandedPanels.filter((id) => id !== panelId)
            : [...state.expandedPanels, panelId],
        })),
      isPanelExpanded: (panelId) => get().expandedPanels.includes(panelId),

      setTheme: (theme) => {
        applyTheme(theme);
        set({ theme });
      },
      toggleTheme: () => {
        const next: ThemeMode = get().theme === 'light' ? 'dark' : 'light';
        applyTheme(next);
        set({ theme: next });
      },

      setWorkbenchTab: (tab) => set({ workbenchTab: tab }),

      resetRunView: () => set({ selectedNodeId: null }),
    }),
    {
      name: 'faultevolve.ui',
      // 只持久化"跨刷新需要保留"的 UI 选择，不持久化任何服务端数据。
      partialize: (state) => ({
        currentRunId: state.currentRunId,
        theme: state.theme,
        workbenchTab: state.workbenchTab,
        expandedPanels: state.expandedPanels,
      }),
    },
  ),
);
