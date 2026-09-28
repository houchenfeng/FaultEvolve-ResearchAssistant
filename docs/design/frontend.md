# 前端设计文档

> 文档版本：v1.1  
> 最后更新：2026-09-28  
> **本版本根据 FaultEvolve 主仓库 main@b59c39e 源码同步数据结构**

## 1. 设计原则

1. **新主界面优先**：主界面是全新的"可靠性研究助手"，围绕演化树、分数曲线、三层知识展开
2. **旧模块收纳**：研途启航原有的开题/实验/写作/投稿四模块收到"科研全流程科普"入口下
3. **回放优先**：优先保证能用已有 `events.jsonl`/`tree.json`/`fe.db` 回放演示
4. **复用优先**：尽可能复用 Navivisor-webui 的组件和布局

## 2. 信息架构

```
可靠性研究助手 (FaultEvolve-ResearchAssistant)
├── 主界面 (/)
│   ├── 演化树面板
│   ├── 分数曲线面板
│   ├── 节点详情面板
│   │   ├── 代码 Diff
│   │   ├── 反思笔记
│   │   └── 引用的文献卡
│   └── 控制栏 (模式、运行状态)
│
├── 三层知识 (/knowledge)
│   ├── 现象层 (Phenomena)
│   ├── 机理层 (Mechanisms)
│   │   └── 数据裁决锦标赛
│   └── 原理层 (Theories)
│
├── 文献依据 (/references)
│   └── 51 张知识卡浏览与搜索
│
├── Skills (/skills)
│   ├── Skills 列表
│   └── 跨设备复用展示 (HDD → 内存)
│
├── 实验报告 (/report)
│   └── 自动生成报告预览与导出
│
├── 设置 (/settings)
│   ├── 模式切换 (混合云/完全本地)
│   ├── Qwen 配置
│   └── 数据路径配置
│
└── 科研全流程科普 (/research-demo)
    ├── 开题 (/research-demo/topic)
    ├── 实验 (/research-demo/experiment)
    ├── 写作 (/research-demo/writing)
    └── 投稿 (/research-demo/submission)
```

## 3. 页面与路由

| 路由 | 页面名称 | 说明 |
|------|---------|------|
| `/` | 主界面 | 演化树 + 分数曲线 + 节点详情 |
| `/knowledge` | 三层知识 | 现象/机理/原理面板 |
| `/knowledge/phenomena` | 现象层 | 现象卡列表 |
| `/knowledge/mechanisms` | 机理层 | 机制卡 + 锦标赛 |
| `/knowledge/theories` | 原理层 | 理论卡 + 预测 |
| `/references` | 文献依据 | 51 张知识卡 |
| `/skills` | Skills 面板 | 通用 Skills |
| `/report` | 实验报告 | 报告生成与预览 |
| `/settings` | 设置 | 配置 |
| `/terminal` | 终端 | SSH 终端（复用） |
| `/research-demo` | 科研全流程入口 | 收纳四模块 |
| `/research-demo/topic` | 开题探索 | 完整复用 |
| `/research-demo/experiment` | 实验验证 | 完整复用 |
| `/research-demo/writing` | 论文写作 | 完整复用 |
| `/research-demo/submission` | 投稿启航 | 完整复用 |

## 4. 主界面布局

```
┌──────────────────────────────────────────────────────────────────┐
│  Logo  可靠性研究助手                    [模式: 混合云] [运行状态] │
├────────────┬─────────────────────────────────────────────────────┤
│            │                                                     │
│  侧边栏    │            演化树可视化区域                          │
│            │                                                     │
│  ○ 主界面  │     ┌─────┐                                        │
│  ○ 三层知识│     │root │                                        │
│  ○ 文献依据│     └──┬──┘                                        │
│  ○ Skills │    ┌───┴───┐                                       │
│  ○ 报告   │   ┌┴┐    ┌┴┐                                       │
│  ○ 设置   │   │ │    │ │   ...                                  │
│            │   └─┘    └─┘                                       │
│  ─────────│                                                     │
│  科研全流程│─────────────────────────────────────────────────────│
│  科普入口  │  分数曲线                                           │
│            │  ┌───────────────────────────────────────────────┐ │
│  (展开后)  │  │ ROS ▲                                         │ │
│  • 开题    │  │     │    ·····                                │ │
│  • 实验    │  │     │ ···                                     │ │
│  • 写作    │  │     │·                                        │ │
│  • 投稿    │  │     └─────────────────────────────────→ 轮次  │ │
│            │  └───────────────────────────────────────────────┘ │
├────────────┴─────────────────────────────────────────────────────┤
│  节点详情面板 (选中节点后展开)                                     │
│  ┌─────────────────┬─────────────────┬─────────────────────────┐ │
│  │ 代码 Diff       │ 反思笔记         │ 引用的文献卡            │ │
│  │                 │                  │                        │ │
│  └─────────────────┴─────────────────┴─────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

## 5. 三层知识页面布局

```
┌──────────────────────────────────────────────────────────────────┐
│  三层知识                                     [筛选] [搜索]       │
├──────────────────────────────────────────────────────────────────┤
│  [现象层]  [机理层]  [原理层]                                     │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ 现象卡 #1: 窗口增量特征                                     │ │
│  │ 等级: 确认 | 效应量: 0.23 [0.18, 0.28]                      │ │
│  │ 代码: smart_5_d14 = last - first                           │ │
│  │ 血统: 节点 #23 → 卡片 FE01 → Backblaze2016                  │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ 现象卡 #2: 首次非零标志                                     │ │
│  │ 等级: 发现 | 效应量: 0.15 [0.10, 0.20]                      │ │
│  │ ...                                                         │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

## 6. 数据裁决锦标赛页面

```
┌──────────────────────────────────────────────────────────────────┐
│  数据裁决锦标赛                                                   │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                      对阵图                                │  │
│  │                                                           │  │
│  │     ┌─────────┐         ┌─────────┐                      │  │
│  │     │ 主机制M1│         │ 对手M2  │                      │  │
│  │     │ Elo:1250│   VS    │ Elo:1180│                      │  │
│  │     └────┬────┘         └────┬────┘                      │  │
│  │          │                   │                            │  │
│  │          │  检验: 时间先后    │                            │  │
│  │          │  e-value: 5.3     │                            │  │
│  │          │  结果: M1 胜      │                            │  │
│  │          └───────────────────┘                            │  │
│  │                                                           │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Elo 排名                                                  │  │
│  │  1. M1 (主机制) - 1250 [+70]                               │  │
│  │  2. M_censor (删失) - 1180 [-30]                           │  │
│  │  3. M_confound (混杂) - 1120 [-40]                         │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  否证证书                                                  │  │
│  │  [展开查看详情...]                                          │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

## 7. 组件设计

### 7.1 新增组件

| 组件 | 路径 | 说明 |
|------|------|------|
| `EvolutionTree` | `components/evolution/evolution-tree.tsx` | D3.js 演化树可视化 |
| `TreeNode` | `components/evolution/tree-node.tsx` | 单个节点组件 |
| `ScoreChart` | `components/evolution/score-chart.tsx` | Recharts 分数曲线 |
| `NodeDetail` | `components/evolution/node-detail.tsx` | 节点详情面板 |
| `CodeDiff` | `components/evolution/code-diff.tsx` | Monaco Editor 代码差异 |
| `ReflectionNotes` | `components/evolution/reflection-notes.tsx` | 反思笔记展示 |
| `KnowledgeCard` | `components/knowledge/knowledge-card.tsx` | 知识卡片（现象/机理/原理） |
| `PhenomenonCard` | `components/knowledge/phenomenon-card.tsx` | 现象卡 |
| `MechanismCard` | `components/knowledge/mechanism-card.tsx` | 机制卡 |
| `TheoryCard` | `components/knowledge/theory-card.tsx` | 理论卡 |
| `Tournament` | `components/knowledge/tournament.tsx` | 锦标赛可视化 |
| `EloChart` | `components/knowledge/elo-chart.tsx` | Elo 排名图 |
| `ReferenceCard` | `components/references/reference-card.tsx` | 文献卡 |
| `ReferenceList` | `components/references/reference-list.tsx` | 文献列表 |
| `SkillCard` | `components/skills/skill-card.tsx` | Skill 卡片 |
| `SkillUsage` | `components/skills/skill-usage.tsx` | Skill 复用展示 |
| `ModeIndicator` | `components/mode/mode-indicator.tsx` | 模式指示器 |
| `DataFlowDiagram` | `components/mode/data-flow-diagram.tsx` | 数据流向图 |
| `ReportPreview` | `components/report/report-preview.tsx` | 报告预览 |
| `ReportExport` | `components/report/report-export.tsx` | 报告导出 |
| `ResearchDemoEntry` | `components/research-demo/entry.tsx` | 科研全流程入口 |

### 7.2 复用组件（从 Navivisor）

| 组件 | 原路径 | 用途 |
|------|--------|------|
| 全套 UI 组件 | `components/ui/*` | 按钮、对话框、表格等 |
| Terminal | `components/terminal/*` | SSH 终端 |
| Login | `components/login.tsx` | 登录（如需） |
| Settings | `components/settings/*` | 设置面板 |
| ResearchTopic | `components/research-topic/*` | 开题模块 |
| ResearchExperiment | `components/research-experiment/*` | 实验模块 |
| ResearchWriting | `components/research-writing/*` | 写作模块 |
| ResearchSubmission | `components/research-submission/*` | 投稿模块 |

## 8. 状态管理

### 8.1 Zustand Stores

```typescript
// stores/evolution-store.ts

// 节点结构（来自 tree.py Tree.to_export()，9 字段）
interface TreeNode {
  id: number;
  branch_id: number;
  depth: number;
  operator: 'init' | 'refine' | 'repair' | 'inject' | 'discover';
  score: number | null;
  status: 'pending' | 'evaluated' | 'failed';
  hypothesis_status: 'confirmed' | 'refuted' | null;
  intent: string;
  visit_count: number;
}

// 事件结构（来自 fe.db event 表）
interface FaultEvolveEvent {
  id: number;
  experiment_id: string;
  type: EventType;
  payload: Record<string, unknown>;
  ts: string;
}

interface EvolutionState {
  // 当前运行
  experimentId: string | null;
  mode: 'replay' | 'realtime';
  deploymentMode: 'hybrid' | 'local';
  
  // 演化树（来自 tree.json 或 fe.db node 表）
  nodes: TreeNode[];
  edges: Array<{from: number; to: number}>;
  selectedNodeId: number | null;
  
  // 分数
  bestScore: number;
  bestNodeId: number | null;
  
  // 事件流
  events: FaultEvolveEvent[];
  lastEventId: number;  // 用于增量轮询
  
  // 操作
  loadReplay: (runDir: string) => Promise<void>;
  selectNode: (nodeId: number) => void;
  setDeploymentMode: (mode: 'hybrid' | 'local') => void;
  appendEvents: (events: FaultEvolveEvent[]) => void;
}

// stores/knowledge-store.ts
interface KnowledgeState {
  // 三层知识
  phenomena: PhenomenonCard[];
  mechanisms: MechanismCard[];
  theories: TheoryCard[];
  
  // 锦标赛
  tournament: TournamentState;
  
  // 否证证书
  certificates: FalsificationCertificate[];
}

// stores/reference-store.ts
interface ReferenceState {
  // 51 张知识卡
  cards: LiteratureCard[];
  
  // 搜索与筛选
  searchQuery: string;
  selectedCategories: string[];
}
```

### 8.2 TanStack Query 使用

```typescript
// hooks/use-evolution.ts
export function useEvolutionTree(runId: string) {
  return useQuery({
    queryKey: ['evolution', 'tree', runId],
    queryFn: () => api.getTree(runId),
  });
}

export function useEvolutionEvents(runId: string) {
  return useQuery({
    queryKey: ['evolution', 'events', runId],
    queryFn: () => api.getEvents(runId),
  });
}

export function useNodeDetail(nodeId: string) {
  return useQuery({
    queryKey: ['evolution', 'node', nodeId],
    queryFn: () => api.getNodeDetail(nodeId),
  });
}
```

## 9. 实时更新

### 9.1 实时数据流说明

> **关键**：`events.jsonl`、`tree.json`、`run_summary.json` 只在运行结束后写出。
> 实时模式下，后端轮询 `fe.db`（WAL 模式），通过 WebSocket 推送事件。

### 9.2 Socket.IO 事件（11 种事件类型）

```typescript
// 事件基础类型
interface FaultEvolveEvent {
  id: number;
  experiment_id: string;
  type: EventType;
  payload: Record<string, unknown>;
  ts: string;  // UTC ISO 8601
}

type EventType =
  | 'init_evaluated'
  | 'selection_failed'
  | 'invalid_generation'
  | 'repair_failed'
  | 'repair_success'
  | 'reflection_design'
  | 'hypothesis_refuted'
  | 'insight_extracted'
  | 'reflection_implementation'
  | 'iteration_complete'
  | 'run_finished';

// 订阅演化事件
socket.on('evolution:event', (event: FaultEvolveEvent) => {
  switch (event.type) {
    case 'init_evaluated':
      // 初始节点评估完成，更新树和分数
      break;
    case 'repair_success':
    case 'repair_failed':
      // 修复结果，更新节点状态
      break;
    case 'reflection_design':
    case 'reflection_implementation':
      // 反思事件，更新反思笔记面板
      break;
    case 'insight_extracted':
      // 洞见提取，显示洞见卡片
      break;
    case 'iteration_complete':
      // 迭代完成，更新分数曲线
      break;
    case 'run_finished':
      // 运行结束，切换到回放模式
      break;
  }
});

// 树结构增量更新（后端从 fe.db node 表轮询）
socket.on('evolution:tree_update', (data: {
  nodes: TreeNode[];  // 9 字段
  edges: Array<{from: number; to: number}>;
}) => {
  // 增量更新演化树
});
```

### 9.2 回放模式

```typescript
// 回放控制器
interface ReplayController {
  play: () => void;
  pause: () => void;
  seek: (timestamp: number) => void;
  setSpeed: (speed: number) => void; // 1x, 2x, 4x
}
```

## 10. 科研全流程科普入口设计

原四模块完整保留，通过折叠入口收纳：

```
侧边栏底部:
┌─────────────────────────┐
│ 📚 科研全流程科普       │ ← 点击展开
│   └─ 开题探索          │
│   └─ 实验验证          │
│   └─ 论文写作          │
│   └─ 投稿启航          │
└─────────────────────────┘
```

点击后跳转到 `/research-demo/*` 路由，UI 与原 Navivisor 完全一致，仅修改：
- 顶部添加返回主界面按钮
- 说明文字标明"这是科研全流程的演示/科普"

## 11. 线框图：演化树节点

> 节点显示 9 字段（来自 `tree.py` Tree.to_export()）

```
ASCII 线框：单个节点

┌─────────────────────────────┐
│  #42  branch:3  depth:5     │  ← id, branch_id, depth
│  ─────────────────────────  │
│  ROS: 34.96                 │  ← score
│  算子: refine               │  ← operator
│  状态: ✓ evaluated          │  ← status
│  假设: —                    │  ← hypothesis_status (null)
│  ─────────────────────────  │
│  意图: 改进窗口特征计算      │  ← intent
│  访问: 12                   │  ← visit_count
└─────────────────────────────┘
         │
         ▼
    (子节点 via edges)
```

节点颜色编码（建议）：

| status | 颜色 | 说明 |
|--------|------|------|
| `evaluated` + 高分 | 绿色 | 成功评估且分数高 |
| `evaluated` + 低分 | 浅绿 | 成功评估但分数低 |
| `pending` | 灰色 | 等待评估 |
| `failed` | 红色 | 评估失败 |

| hypothesis_status | 标记 |
|------------------|------|
| `confirmed` | ✓ 绿勾 |
| `refuted` | ✗ 红叉 |
| `null` | 无标记 |

## 12. 响应式设计

| 断点 | 布局调整 |
|------|---------|
| `< 768px` | 侧边栏收起为汉堡菜单；演化树和分数曲线垂直堆叠 |
| `768px - 1024px` | 侧边栏折叠为图标；节点详情浮层展示 |
| `> 1024px` | 完整布局；节点详情在底部展开 |

## 13. 待定设计决策

| 决策点 | 选项 | 建议 |
|--------|------|------|
| 演化树可视化库 | D3.js / React Flow / vis.js | 建议 React Flow（与 React 集成好） |
| 代码高亮编辑器 | Monaco / CodeMirror | 建议 Monaco（功能更全） |
| 图表库 | Recharts / Chart.js / ECharts | 建议 Recharts（React 原生） |
