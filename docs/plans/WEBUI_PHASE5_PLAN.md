# FaultEvolve WebUI 阶段 5 实现计划：进化工作台

> 对应任务书 `FRONTEND_IMPLEMENTATION_TODO.md` §8（TODO 5.1 – 5.7）+ §12.1/§12.2。
> 前序：阶段 0/1（契约流水线）、阶段 2（13 个只读回放端点，`9de6627`）、阶段 3（前端外壳）、阶段 4（总览与任务输入，PR #22 已合并进 main `2ef99c8`）。
> 分支：`webui-p1`（从 `origin/main` 拉出）。
> 本文件只写计划，不含实现。**未获灵梦确认前不动代码。**

---

## 0. 侦察结论（全部实测，标注命令来源）

### 0.1 分支与仓库状态

| 项 | 值 |
|---|---|
| 当前分支 | `webui-p1`，HEAD = `2ef99c8`（= `origin/main`，零差异） |
| 本地 main | 已快进到 `2ef99c8`，与远端一致 |
| `webui-p0` | 保留（阶段 4 里程碑，内容已进 main） |
| origin URL | `ssh://git@github.com/...`（已去掉 `:22`，走 ssh config 的 443） |
| 推送命令 | `git push origin webui-p1:feat/webui-phase5`（本地名无斜杠，远端名带斜杠） |

### 0.2 后端已交付的阶段 5 数据（`src/faultevolve/webapi/`）

**全部 13 个只读端点在阶段 2 就已就绪，阶段 5 的后端增量很小。**

| 端点 | DTO | 关键字段（已核对 `contracts.py`） |
|---|---|---|
| `GET /api/runs/{id}/tree` | `TreeResponse` | `nodes: list[TreeNodeDTO]`、`edges: list[TreeEdgeDTO]`、`best_node_id`、`best_path`、`warnings` |
| `GET /api/runs/{id}/nodes/{nid}` | `NodeDetailResponse` | `node` + `artifact`（只读代码/intent/hypothesis）+ `evaluation` + `insights` + `adopted_card_ids` + `event_ids` + `llm_call_count/llm_tokens` + **`code_diff`（后端算好的 unified diff）** + `code_diff_truncated` |
| `GET /api/runs/{id}/events` | `EventPageResponse` | 增量分页（`after_id`/`limit`），`EventResponse{id,run_id,type,payload,ts,is_known_type}` |
| `GET /api/runs/{id}/scores` | `list[ScorePointResponse]` | `iteration,node_id,score,delta_score,noise_delta,within_noise_band,operator,ts` |
| `GET /api/runs/{id}/leaderboard` | `list[ScoreboardEntryResponse]` | `rank,node_id,score,operator,depth,is_best` |
| `GET /api/runs/{id}/budget` | `RunBudgetResponse` | 24 个字段：`total_tokens` + 7 类分项（generate/reflect/knowledge/repair/discovery/tournament/crossover）+ `self_fix_tokens` + 时间三项 + `stage_cap_hits` + 派生指标 |

**`TreeNodeDTO` 的 24 个字段已覆盖 TODO 5.1 的全部要求**：`id/parent_id/second_parent_ids/branch_id/depth/operator/score/delta_score/noise_delta/status/hypothesis_status/intent/visit_count/adopted_card_ids/insight_ids/repair_parent_id/repair_count/repair_attempted/repair_exhausted/error_class/is_best/is_on_best_path`。

**枚举**（`common/schemas.py`，前端需镜像）：
- `NodeStatus` = pending / evaluating / done / invalid / abandoned
- `HypothesisStatus` = open / supported / refuted / inconclusive / corroborated / undetermined
- `OperatorType` = init / refine / recall_focus / threshold_calibrate / inject / transplant / crossover / repair
- `TreeEdgeKind` = parent / crossover_second_parent / repair

### 0.3 ⚠️ 三个必须先解决的实测缺口

**缺口 A：所有边都被标成 `PARENT`，三种边从未区分。**

`replay_service.py:566` 写死：
```python
kind=TreeEdgeKind.PARENT,   # tree.json has no edge kind; a plain parent edge is all it records.
```
而 TODO 5.1 明确要求支持「普通 parent edge / crossover 第二父边 / repair 边」，PRD §9.8 要求「树上使用不同线型区分普通父子边、crossover 第二父边和 repair 边」。

**数据其实存在**：引擎 `engine.py:1611-1616` 在 crossover 时写 `node_parents(experiment_id, node_id, parent_id, role)`，`role ∈ {primary, secondary}`。`store.add_node_parent` / `get_node_parents` 齐备。**只是 replay_service 从没读过这张表。**
⇒ 阶段 5 必须补：读 `node_parents` → `role=secondary` 产出 `CROSSOVER_SECOND_PARENT` 边；`repair_parent_id` 非空时产出 `REPAIR` 边。
（`repair_parent_id` 已经在 `TreeNodeDTO` 里回填了，见 `replay_service.py:551`。）

**缺口 B：真实 demo 运行里 crossover 与 repair 都没发生过。**

实测 `tests/fixtures/runs/hdd_mvp_demo_7510f100/fe.db`：
- `node_parents` 表 **0 行**
- `tree.json`：**6 节点 / 5 边**
- `events.jsonl`：**19 行**，类型分布 = `iteration_complete`×5、`smoke_passed`×5、`hypothesis_refuted`×5、`init_evaluated`×1、`smoke_data_built`×1、`smoke_fix_success`×1、`run_finished`×1

⇒ 三种边的 UI **在真实数据上无法验证**，必须用合成 fixture 补测试。这是本阶段最大的测试设计难点。

**缺口 C：性能测试的规模与真实数据差两个数量级。**

TODO §8 要求「100 节点流畅缩放 / 500 节点不冻结主线程超过 200ms / 1000 条事件使用虚拟列表」。真实 demo 只有 6 节点 19 事件。
⇒ 性能测试**必须用合成数据**（前端 `buildSyntheticTree(n)` 测试夹具），不能拿真实运行假装通过。

### 0.4 前端现状

| 项 | 状态 |
|---|---|
| 占位页 | `RunTreePage` / `RunTimelinePage` / `RunWorkbenchPage` / `RunKnowledgePage` / `RunResultsPage` 全是 `StagePlaceholder` |
| 真实页面 | 只有 `OverviewPage`（阶段 4）、`NewRunPage`（阶段 4） |
| React Flow | **未安装**（`package.json` 无 `reactflow`/`xyflow`） |
| 布局库 | 未装 dagre / elkjs |
| diff 库 | 未装（但后端已给 `code_diff` 字符串 ⇒ **前端不需要 diff 库**） |
| 虚拟列表 | 未装（`@tanstack/react-virtual` 或 `react-window`） |
| 可复用 | `StatusBadge`（6 种 tone）、`ApiErrorPanel`、`EmptyState`、`MissingArtifactNotice`、`ConnectionBanner`、`DemoDataBadge`、`queryKeys`（含 events/scores/leaderboard/node/tree/budget 全部 key）、`api-error.ts`（含 `node.not_found` 中文映射） |
| store | `useUiStore` 已有 `currentRunId/selectedNodeId/expandedPanels/workbenchTab`（阶段 3 预留，阶段 5 正好用上） |

### 0.5 本机环境坑（阶段 3/4 已踩实）

1. **pnpm 必须用绝对路径**：`C:/Users/A/.workbuddy/binaries/node/versions/22.22.2-3/pnpm.CMD`，且要 `cd web`。`pnpm --dir web` 无效。
2. **pnpm store 会被中断的 install 写坏**：症状是 `reused N, downloaded 0` 却 `Cannot find module`。修法：删 `C:\Users\A\AppData\Local\pnpm\store\v3` + `web/node_modules` 重装。**新增依赖时一次性写进 package.json 再 install，不用 `pnpm add`。**
3. **测试里不要用 `fileURLToPath(import.meta.url)`**：本机 vitest 下 `import.meta.url` 不是 `file:` 协议。用 `resolve(process.cwd(), ...)`。
4. **npm registry 用 `registry.npmmirror.com`**（实测 164ms vs npmjs 786ms）。
5. **eslint 门禁是 0 警告**：`react-refresh/only-export-components` 要求组件文件只导出组件 ⇒ 纯函数拆 `*-logic.ts`。
6. **工具直接用 node 跑**（避免 shim）：`node node_modules/vitest/vitest.mjs run`、`node node_modules/typescript/lib/tsc.js --noEmit`、`node node_modules/vite/bin/vite.js build`、`node node_modules/eslint/bin/eslint.js .`。
7. **pytest 汇总行会被环境钩子吞掉** ⇒ 判回归结果要看**逐进度行的 F 字符**，不是汇总行。

### 0.6 禁止事项（继承 TODO §0.2 + 阶段 3/4 结论）

1. **不参考 GitHub 上的 `qianduan-yemian-demo` 分支**（灵梦明确要求）。
2. **侧栏严格四个模块**（总览 / 进化工作台 / 知识发现 / 结果与报告）。树、时间轴、事件、预算是同一运行上下文内的工作区标签，**不是侧栏项**（PRD §9.5 明确）。
3. **前端不重算分数**：ROS/显著性一律用后端给的 `score`/`delta_score`/`noise_delta`/`within_noise_band`。
4. **`score` 是 `None` 时显示「未评分」，绝不用 `score || 0`**（TODO 5.2 明令）。0 分与缺失必须不同。
5. **不枚举 evaluator-only（holdout）路径**。复用引擎的 `FORBIDDEN_PATTERNS` / `PROTECTED_NAME_RE`，不写第二份字面量。
6. **代码只读**：diff 在浏览器显示可以，但不得提供编辑/覆盖（PRD §10.3）。
7. **Jev 结果不与 evaluator 分数混放**（TODO §8 组件测试项、PRD §9.7）。
8. **不推送 main**：只推 `webui-p1:feat/webui-phase5`，PR 由灵梦开。

---

## 1. 阶段 5 的范围界定

### 1.1 做什么（TODO 5.1 – 5.7）

| TODO | 交付 |
|---|---|
| 5.1 | 树数据适配：`TreeResponse` → React Flow nodes/edges，**纯函数 + 单独测试**；三种边 + 最优路径 + 节点状态 + 假设状态 |
| 5.2 | 树节点视觉：短 ID / score 或「未评分」/ Δ 或「未记录」/ operator / status 图标+文字 / 知识卡数 |
| 5.3 | 节点详情抽屉五标签：概览 / 指标 / 代码差异 / 知识与记忆 / 事件与成本 |
| 5.4 | 评价与噪声：父分数 / 当前分数 / delta_score / noise_delta / 是否超出噪声带 + 可读解释 |
| 5.5 | 反思与纠错：design/implementation reflection / hypothesis_status / repair_count / repair_parent_id / error_class / repair_exhausted |
| 5.6 | 时间轴与事件：按原始顺序 / `iteration_complete` 成一代 / 缺失代不补齐 / 事件↔节点双向定位 |
| 5.7 | 预算与算力：total_tokens + 7 类分项 + 时间三项 + stage cap hits |

### 1.2 不做什么（留给后续阶段）

| 项 | 归属 | 理由 |
|---|---|---|
| 暂停 / 恢复 / 取消 / 追加轮次（PRD §9.3） | **阶段 7** | 需要 `enable_process_control=true` 与进程管理；`/api/meta.process_control_enabled` 仍是 `false` |
| WebSocket 实时流（PRD §9.4） | 阶段 8 | 阶段 2 只做了 SSE 契约；本阶段用轮询 |
| 节点对比（PRD §10.4 双节点 diff） | 阶段 6 或 7 | 需要后端出双节点 diff（现在只有单父 diff） |
| 算子统计与筛选（PRD §9.8） | 阶段 6 | `operator_stats` 表有数据，但 UI 归到结果页更合适 |
| 知识发现页 / 结果页 | 阶段 6 | 本阶段只在节点抽屉里引用知识卡 id 并跳转 |
| 运行创建 | 阶段 7 | 阶段 4 已按 D-A=A1 明确不做 |

**结论**：阶段 5 = **一个只读的工作台**（树 + 时间轴 + 节点抽屉 + 预算面板），不含任何写操作。这与 TODO §8 全是「展示」类需求一致。

---

## 2. 需要拍板的决策（3 个）

### D-A　React Flow 装不装？

| 选项 | 内容 | 代价 |
|---|---|---|
| **A1（推荐）** | 装 `@xyflow/react`（React Flow 12，MIT，维护活跃） | +1 依赖（约 200KB gzip）；TODO 5.1/PRD §10.2 的缩放、拖拽、适配视野、框选全靠它，自己写等于重造一遍 |
| A2 | 不装，用纯 SVG + 自写 pan/zoom | 省一个依赖，但要自己实现缩放/拖拽/框选/边缘裁剪；500 节点性能风险高；PRD §10.2 的 12 条交互要写 1000+ 行 |
| A3 | 装但只用核心（`@xyflow/react` 的 MiniMap/Controls 按需引入） | 同 A1，额外注意按需导入控制包体 |

**推荐 A1**。TODO §8 的「100 节点流畅缩放 / 500 节点不冻结主线程」性能指标，本质上就是 React Flow 这类库的目标场景；自写 SVG 达不到 500 节点还流畅。

### D-B　布局策略：谁来算坐标？

| 选项 | 内容 | 代价 |
|---|---|---|
| **B1（推荐）** | 树用 **dagre**（`@dagrejs/dagre`）做一次性布局，坐标算完存在节点上；React Flow 只负责渲染与交互 | +1 依赖；dagre 是成熟的分层有向图布局，crossover/repair 边用 `rankdir: 'LR'` + 多父节点能正确处理 |
| B2 | 用 React Flow 内置的层级布局（dagre 内置但需开启 `nodeOrigin`/隐藏父节点） | 零额外依赖，但 crossover 双父场景布局质量差（会退化成树） |
| B3 | 不做自动布局，按 `depth` 手工算坐标 | 零依赖，但 500 节点会重叠成一片，违反 TODO 性能与可用性 |

**推荐 B1**，并把布局函数写成**纯函数**（输入 nodes+edges，输出带坐标的 nodes），单独测试。

### D-C　「超出噪声带」的判定放哪？

TODO 5.4 原文：「判断优先使用后端提供的分类字段。若后端还没有，新增纯函数并在后端计算；不要让多个前端组件各自判断。」

**实测**：`ScorePointResponse.within_noise_band`（`bool | None`）**已存在**，但 `TreeNodeDTO` **没有**这个字段。
⇒ **推荐**：阶段 5 在 `TreeNodeDTO` 补 `within_noise_band: bool | None = None`，由 `replay_service` 用节点自己的 `delta_score`/`noise_delta` 与分数点同一套规则算出（`within_noise_band = |delta| <= noise_delta`，两者缺任一 ⇒ `None`），**前端只读不算**。契约 minor 递增到 1.2.0。

这样「不要让多个前端组件各自判断」这条被结构性地满足。

---

## 3. 4A：后端补齐（树的三种边 + 噪声带分类）

### 3.1 `replay_service` 读 `node_parents`

```
新增 _read_second_parents(db_path, run_id) -> dict[node_id, list[parent_id]]
    查 SELECT node_id, parent_id, role FROM node_parents WHERE experiment_id=?
    只取 role='secondary' 的行（primary 已在 parent_id 里）
    表不存在 / 0 行 ⇒ 返回 {}（不是错误）
```

改动点：
1. `TreeNodeDTO.second_parent_ids` 用这个结果回填（现在是硬编码 `[]`，`replay_service.py:535`）。
2. `edges` 构造改为：
   - 现有 raw_edges → `PARENT`
   - 每个 `second_parent_id` → `CROSSOVER_SECOND_PARENT`
   - 每个 `repair_parent_id` → `REPAIR`
   - **去重**：同一 (source,target,kind) 只留一条。
3. 节点有 `second_parent_ids` 但对应父节点不在 nodes 里 ⇒ 加一条 `ContractWarning`（不静默丢弃）。

### 3.2 补 `within_noise_band`

- `TreeNodeDTO` 加 `within_noise_band: bool | None = None`
- `replay_service` 计算：`delta_score` 与 `noise_delta` 都非 None ⇒ `abs(delta) <= noise`；否则 `None`
- 与 `ScorePointResponse` 的算法**必须一致** ⇒ 抽成一个后端纯函数 `_within_noise_band(delta, noise)`，两处共用（这正是 TODO 5.4 要的「不要让多个地方各自判断」）

### 3.3 测试

| 用例 | 文件 | 断言 |
|---|---|---|
| 第二父边正确分类 | `test_replay_tree_edges.py`（新） | 合成 db 写 `role='secondary'` ⇒ 出现 `crossover_second_parent` 边 |
| repair 边正确分类 | 同上 | 节点 `repair_parent_id` 非空 ⇒ 出现 `repair` 边 |
| 三种边互不混淆 | 同上 | 边 kind 集合恰好是这三类的子集，无重复 |
| 第二父指向不存在的节点 ⇒ warning | 同上 | `warnings` 里有对应条目 |
| 0 行 `node_parents` 不报错 | 同上 | 真实 demo fixture：`second_parent_ids == []`、边全是 `parent` |
| `within_noise_band` 三态 | 同上 | 有 delta+noise ⇒ bool；缺任一 ⇒ None；**0 分与 None 不混淆** |
| 与 `ScorePointResponse` 同源 | 同上 | 同一组 (delta, noise) 两处结果相同（同一个纯函数） |
| 回归 | `test_replay_tree.py`（已有） | 阶段 2 的既有断言不破 |

### 3.4 契约同步（固定三步，漏一步就红）

```bash
.venv/Scripts/python.exe scripts/export_web_contracts.py
.venv/Scripts/python.exe scripts/check_web_contracts.py      # 必须 exit 0
cd web && <abs>/pnpm.CMD run generate:api
```
`CONTRACT_VERSION` 1.1.0 → **1.2.0**（新增可选字段 = minor，TODO §13.4 规则）。连带改 `tests/webapi/test_health.py` 与 `web/src/app/App.test.tsx` 里的硬编码版本串。

---

## 4. 4B：前端树适配层（纯函数，TODO 5.1）

### 4.1 文件

| 文件 | 内容 |
|---|---|
| `web/src/features/workbench/tree-adapter.ts` | **纯函数**：`toFlowNodes(tree)`、`toFlowEdges(tree)`、`layoutTree(nodes, edges)`、`buildSyntheticTree(n)`（性能测试夹具） |
| `web/src/features/workbench/tree-adapter.test.ts` | 12 条单测（见 §6） |

**为什么放 `tree-adapter.ts` 而不是 `.tsx`**：没有 JSX，且 eslint 门禁 0 警告；命名不带 `.tsx` 让「这是纯逻辑」一眼可见（沿用阶段 4 的 `*-logic.ts` 惯例，但这里用领域名）。

### 4.2 节点视觉映射（TODO 5.2）

```
label = [
  短 ID（id 前 8 位）
  score != null ? score.toFixed(2) : '未评分'    ← 绝不用 score || 0
  delta_score != null ? (delta>=0 ? '+' : '') + delta.toFixed(2) : '未记录'
  operator
  status 图标 + 文字                              ← 不只靠颜色（PRD §10.1）
  adopted_card_ids.length ? `📚${n}` : ''        ← 知识卡数量
]
```

- **0 分必须显示 `0.00`**，缺失显示「未评分」——两者视觉可区分（阶段 4 已用 `data-*` 属性做测试锚点，本阶段沿用）。
- `is_best` / `is_on_best_path` 用边框区分（不改分数）。
- 状态图标 + 文字的映射表放 `tree-adapter.ts` 导出，测试直接断言映射表本身。

### 4.3 三种边的视觉（PRD §9.8）

| kind | 线型 | 颜色 | 标签 |
|---|---|---|---|
| `parent` | 实线 | 边框主色 | 无 |
| `crossover_second_parent` | 虚线 | info 色 | 「双亲」 |
| `repair` | 点划线 | warning 色 | 「修复」 |

**React Flow 的 edge 不支持点划线** ⇒ 用 `type: 'smoothstep'` + `animated` 区分，或用 SVG `strokeDasharray` 自定义 edge（React Flow 支持自定义 edge 组件）。计划用自定义 edge 组件，测试断言 `data-kind` 属性。

### 4.4 布局（决策 B1）

`layoutTree(nodes, edges)` 用 `@dagrejs/dagre`：
- `rankdir: 'LR'`（树从左到右，depth 递增方向）
- `ranksep: 80`、`nodesep: 24`
- crossover 第二父用 `minlen` 制造折线，不制造额外层级
- **纯函数**：同样的输入必须给出同样的坐标（测试断言两次调用结果相等）

### 4.5 筛选（TODO 5.2 组件测试项「节点筛选」）

筛选**只影响显示，不改底层树**（PRD §10.5）：
```ts
filterTree(tree, { status?: NodeStatus[], operator?: OperatorType[], minScore?, maxScore?, branchId?, query? })
```
- `query` 搜节点 ID / operator / intent
- 返回 `{ visibleNodes, visibleEdges, hiddenCount }`，边只保留两端都可见的

---

## 5. 4C：前端页面与组件

### 5.1 文件清单

| 文件 | 内容 |
|---|---|
| `web/src/routes/RunWorkbenchPage.tsx` | **重写**。工作台容器：顶部运行状态条 + 五个工作区标签（进化树 / 代际时间轴 / 排行榜 / 事件流 / 预算与资源）+ 右侧节点抽屉 + 底部分析区 |
| `web/src/routes/RunTreePage.tsx` | **重写**。树视图（复用工作台的树区，独立路由 `/runs/:runId/tree`） |
| `web/src/routes/RunTimelinePage.tsx` | **重写**。代际时间轴 + 事件流（`/runs/:runId/timeline`） |
| `web/src/features/workbench/TreeCanvas.tsx` | React Flow 容器：缩放、拖拽、适配视野、展开/折叠子树、最优路径高亮、点击开抽屉 |
| `web/src/features/workbench/TreeNodeCard.tsx` | 自定义节点渲染（短 ID / 分数 / Δ / operator / 状态 / 知识卡数） |
| `web/src/features/workbench/TreeFilters.tsx` | 筛选栏：状态 / 算子 / 分支 / 分数区间 / 搜索 + 「显示全部」 |
| `web/src/features/workbench/NodeDrawer.tsx` | 节点详情抽屉，五个标签页 |
| `web/src/features/workbench/tabs/OverviewTab.tsx` | 概览：完整 ID / 状态与原因 / 父节点与第二父 / 分支 / 轮次 / 深度 / 算子 / 意图 / 假设 / ROS / Δ / 噪声带 / 显著性解释 |
| `web/src/features/workbench/tabs/MetricsTab.tsx` | 指标：validity / combined_score / F1 / F1_p10 / AUPRC / R@FAR / precision / recall / 误告率 / 漏告率 / 运行时间 / bootstrap 波动 / **缺失显示「未记录」** |
| `web/src/features/workbench/tabs/CodeTab.tsx` | 代码与差异：只读代码 + 后端给的 `code_diff`（可复制/下载，**不可编辑**）+ `code_diff_truncated` 提示 |
| `web/src/features/workbench/tabs/KnowledgeTab.tsx` | 知识与记忆：`insights` / `adopted_card_ids` / 三层反思 / 被否证假设；知识卡可点击跳 `/runs/:id/knowledge` |
| `web/src/features/workbench/tabs/EventsTab.tsx` | 事件与成本：`event_ids` 列表（点击定位）/ `llm_call_count` / `llm_tokens` / Jev 结果**单独区块且标明「预筛，非 evaluator 分数」** |
| `web/src/features/workbench/TimelinePanel.tsx` | 代际时间轴：按 `iteration_complete` 分代，缺失代不补齐 |
| `web/src/features/workbench/EventStream.tsx` | 事件流：按原始顺序、ID 去重、点击定位节点 |
| `web/src/features/workbench/LeaderboardPanel.tsx` | 排行榜（`/api/runs/{id}/leaderboard`） |
| `web/src/features/workbench/BudgetPanel.tsx` | 预算与算力（`/api/runs/{id}/budget`）：total + 7 类分项 + 时间 + stage caps |
| `web/src/features/workbench/significance.ts` | **纯函数**：把 `(delta, noise, within_noise_band)` 映射成 PRD §9.7 的四类可读解释（有效改进 / 差异不足 / 显著退化 / 无法判断）。**只读后端字段，不自己算阈值** |
| `web/src/features/workbench/reflection.ts` | **纯函数**：从 `NodeDetailResponse` 提取三层反思 + 修复链（`repair_parent_id` → 原失败节点可追踪） |
| `web/src/features/workbench/iteration-logic.ts` | **纯函数**：事件流 → 代际序列（`iteration_complete` 才成一代，缺失代不补齐，ID 去重） |

### 5.2 工作台布局（PRD §9.1 三层）

```
┌─────────────────────────────────────────────┐
│ 顶部运行状态条（run_id / status / 分数 / 轮次）  │
├──────────────────────────────┬──────────────┤
│ 主视图：进化树（React Flow）      │ 节点详情抽屉   │
│                              │ （选中时）     │
├──────────────────────────────┴──────────────┤
│ 底部：代际时间轴 / 事件流 / 预算（可折叠）        │
└─────────────────────────────────────────────┘
```
五个工作区标签在主视图顶部：**进化树 / 代际时间轴 / 排行榜 / 事件流 / 预算与资源**。窄屏降级为页内标签，**侧栏仍四个模块**。

### 5.3 事件去重（TODO 5.6 + PRD §9.4）

`iteration-logic.ts` 的去重规则：以 `EventResponse.id` 为准；`id == null` 时用 `type + ts + node_id` 合成键。**乱序事件按 `id` 排序展示，但保留原始顺序信息**（TODO 说「按事件原始顺序展示」⇒ 展示用 id 升序，去重用 id）。

### 5.4 双向定位（TODO 5.6）

- 事件 → 节点：点事件调 `selectNode(payload.node_id)`，树自动居中并高亮
- 节点 → 事件：抽屉「事件与成本」标签里点 `event_id`，时间轴滚动到该事件
- 排行榜 → 树：点条目定位节点（PRD §10.2）

实现用 `useUiStore` 已有的 `selectedNodeId` + 新增 `focusedEventId`（**存 store 不进 URL**：刷新后选中态丢失可接受，PRD 没要求深链接到节点）。

---

## 6. 4D：测试（TODO §8 逐条对到用例）

### 6.1 单元测试（纯函数）

| TODO 测试项 | 文件 | 断言要点 |
|---|---|---|
| tree 转换 | `tree-adapter.test.ts` | 节点数/边数守恒；字段逐个映射 |
| **第二父边** | 同上 | `second_parent_ids` ⇒ `crossover_second_parent` 边 |
| **repair 边** | 同上 | `repair_parent_id` ⇒ `repair` 边 |
| **最优路径** | 同上 | `is_on_best_path` 节点被标记；`best_path` 顺序保留 |
| **缺分数** | 同上 | `score: null` ⇒ 「未评分」；**不出现 0** |
| **0 分** | 同上 | `score: 0` ⇒ 显示 `0.00`，与「未评分」不同 |
| 噪声内上涨 | `significance.test.ts` | `within_noise_band=true` ⇒ 「差异不足」 |
| 显著上涨 | 同上 | `false` + delta>0 ⇒ 「有效改进」 |
| 显著下降 | 同上 | `false` + delta<0 ⇒ 「显著退化」 |
| 无法判断 | 同上 | `within_noise_band=null` ⇒ 「无法判断」 |
| 节点筛选 | `tree-adapter.test.ts` | 筛选后 `hiddenCount` 正确；边只留两端可见 |
| 事件去重 | `iteration-logic.test.ts` | 重复 id 只留一条；`id=null` 用合成键去重 |
| 代际切分 | 同上 | 只有 `iteration_complete` 成代；缺代不补 |
| 布局确定性 | `tree-adapter.test.ts` | 两次调用坐标相同 |
| 大树合成 | 同上 | `buildSyntheticTree(1000)` 能生成且结构合法 |
| 反思提取 | `reflection.test.ts` | repair 链可追到失败节点；`repair_exhausted` 透传 |
| 后端边分类 | `test_replay_tree_edges.py` | §3.3 的 8 条 |

### 6.2 组件测试

| TODO 测试项 | 断言 |
|---|---|
| 点击节点打开详情 | 抽屉出现，标题是完整 node_id |
| 点击知识卡跳知识发现 | 跳到 `/runs/:id/knowledge`（阶段 6 页面占位，但路由必须通） |
| 点击事件定位节点 | 树选中态变更 + 居中 |
| **代码为只读** | 抽屉里没有 textarea/contenteditable；代码区有「只读」标记；无保存按钮 |
| 缺指标显示「未记录」 | `metric` 缺 key ⇒ 渲染「未记录」；**不渲染 0** |
| **Jev 不显示在 evaluator 分数区** | 分数区只显示 `evaluation.combined_score`；Jev 文本只出现在「事件与成本」标签且带「预筛」字样 |
| 三种边线型不同 | 三条边 `data-kind` 分别为 parent/crossover/repair |
| 0 分 ≠ 未评分 | DOM 里同时存在 `0.00` 与「未评分」且在不同节点上 |
| 警告需确认 | 警告态节点在筛选栏显示计数 |

### 6.3 性能测试（合成数据，决策依据见缺口 C）

| TODO 测试项 | 方法 | 阈值 |
|---|---|---|
| 100 节点流畅缩放 | `buildSyntheticTree(100)` 渲染 + 模拟 zoom | 无长任务 > 50ms |
| 500 节点不冻结主线程 | `buildSyntheticTree(500)` 布局耗时 | **< 200ms**（`performance.now()`） |
| 1000 条事件虚拟列表 | 合成 1000 事件，断言 DOM 中事件行数 | **< 100 行**（虚拟化生效） |
| 布局 1000 节点 | `layoutTree` 耗时 | < 500ms（超过则只对可视区布局） |

**虚拟列表依赖**：装 `@tanstack/react-virtual`（与已有的 TanStack Query 同源，风格一致）。

---

## 7. 依赖变更

| 包 | 用途 | 备注 |
|---|---|---|
| `@xyflow/react` | 树渲染与交互 | 决策 D-A=A1 |
| `@dagrejs/dagre` | 分层布局 | 决策 D-B=B1 |
| `@tanstack/react-virtual` | 事件流虚拟列表 | 1000 条性能项 |

**装法（阶段 3 教训）**：一次性把三个包写进 `web/package.json` 的 `dependencies`，再用绝对路径 pnpm 跑一次 `install`。**不要 `pnpm add -D`**（会挂十分钟并写坏 store）。若 store 报 `Cannot find module`，删 store + node_modules 重装。

---

## 8. 分步执行顺序

1. **4A 后端补齐**：`replay_service` 读 `node_parents`（三种边）+ `within_noise_band` 纯函数 → 补测试 → 契约 1.2.0 重导出 + 漂移检查 + TS 重生成。
2. **4B 前端适配层**：`tree-adapter.ts` / `significance.ts` / `iteration-logic.ts` / `reflection.ts` 四个纯函数 + 全部单测。
3. **4C 页面组件**：`TreeCanvas` → `NodeDrawer`（五标签）→ `TimelinePanel` / `EventStream` / `LeaderboardPanel` / `BudgetPanel` → 重写三个路由页。
4. **4D 门禁 + 冒烟**：
   ```bash
   .venv/Scripts/python.exe -m pytest -q            # 判回归看逐行 F，不看汇总
   .venv/Scripts/python.exe scripts/check_web_contracts.py
   cd web && node node_modules/typescript/lib/tsc.js --noEmit
   node node_modules/vitest/vitest.mjs run
   node node_modules/eslint/bin/eslint.js .          # 0 err / 0 warn
   node node_modules/vite/bin/vite.js build
   ```
5. **人工冒烟**（后端 + 前端同时起）：
   ```bash
   FE_WEB_TASK_ROOTS='["benchmark"]' FE_WEB_RUNS_ROOT=tests/fixtures/runs \
   FE_WEB_DEMO_RUN_IDS='["hdd_mvp_demo_7510f100"]' FE_WEB_SERVER_PROFILE_STORE=build/profiles-smoke.json \
   .venv/Scripts/python.exe -m faultevolve.cli web serve --port 8000
   cd web && <abs>/pnpm.CMD dev
   ```

### 8.1 冒烟要确认的 10 件事

1. 侧栏**仍只有 4 项**（树/时间轴/预算都没混进侧栏）。
2. 树能渲染 6 个真实节点，边全是普通父边（真实数据无 crossover），不报错。
3. 点节点 → 抽屉五个标签都在；「代码与差异」里能看到后端给的 diff。
4. 代码区**没有**输入框/保存按钮（只读）。
5. 节点 `62d6cf09` 显示分数 `22.81`（真实值），不是「未评分」。
6. 指标缺失处显示「未记录」，页面上**搜不到把缺失显示成 0 的地方**。
7. 时间轴按 `iteration_complete` 切成 5 代；缺失代不补。
8. 预算面板显示 total_tokens 与各分项（真实 run_summary 的值）。
9. Jev 字样**只**出现在「事件与成本」标签，且带「预筛」标记。
10. 筛选「invalid」状态后，节点数减少、边只留两端都可见的。

---

## 9. 风险清单

| 风险 | 影响 | 缓解 |
|---|---|---|
| **三种边在真实数据上验证不了** | UI 画错线型也发现不了 | 合成 fixture 写后端 + 前端双侧测试；冒烟时明确「真实运行无 crossover 属正常」 |
| React Flow 12 与 React 19 的 peer 依赖 | 装不上或运行时报错 | 先单独装一个最小 demo 验证；若不兼容退 A2（自写 SVG） |
| dagre 对多父节点布局质量差 | crossover 边视觉混乱 | 只对 `parent` 边做 rank，`crossover`/`repair` 边不参与层级计算 |
| 500/1000 节点布局卡顿 | 违反 TODO 性能项 | 只对可视区布局；布局结果缓存（按 node 数 + 树 hash） |
| 1000 条事件渲染卡 | 同上 | 虚拟列表；若 `@tanstack/react-virtual` 有问题退 `react-window` |
| `within_noise_band` 与分数点算法不一致 | 同一节点两处显示矛盾 | 抽后端纯函数共用 + 一条测试断言两处相同 |
| 阶段 2 的 8 条 CRLF 假红混入判断 | 误判回归失败 | 判回归**只数 F 的个数**（必须恰好 8） |
| 后端被宿主环境回收 | 冒烟中途 500 | 起服务后先 `curl /api/health` 确认；挂了按 §8 命令重启 |

---

## 10. 完成定义（勾完才算阶段 5 交付）

- [ ] TODO 5.1：树适配纯函数 + 独立测试；三种边 + 最优路径 + 状态 + 假设状态
- [ ] TODO 5.2：短 ID / 分数或「未评分」/ Δ 或「未记录」/ 算子 / 状态图标+文字 / 知识卡数；**0 分与缺失可区分**
- [ ] TODO 5.3：抽屉五标签齐；代码只读；diff 用后端值
- [ ] TODO 5.4：父分数 / 当前分 / Δ / 噪声 / 是否超带 + 四类可读解释（只读后端分类）
- [ ] TODO 5.5：三层反思 / 假设状态 / repair_count / repair_parent_id / error_class / repair_exhausted；修复节点可追到失败节点
- [ ] TODO 5.6：事件按原始顺序 / 只有 `iteration_complete` 成代 / 缺失代不补 / 事件↔节点双向定位
- [ ] TODO 5.7：total_tokens + 7 类分项 + 时间三项 + stage cap hits
- [ ] §6.1 的 17 条单元测试全绿
- [ ] §6.2 的 9 条组件测试全绿
- [ ] §6.3 的 4 条性能测试达标（合成数据）
- [ ] 侧栏仍 4 项；5 个工作区是页内标签
- [ ] 契约 1.2.0 无漂移；webapi 全绿；前端四门禁全绿
- [ ] 完整 Python 回归**恰好 8 条**失败（既有 CRLF 假红），0 新增
- [ ] §8.1 的 10 条冒烟全过

---

## 11. 待灵梦拍板

| | 决策 | 我的建议 |
|---|---|---|
| **D-A** | React Flow 装不装 | **A1 装 `@xyflow/react`**（TODO 5.1 明写「转成 React Flow nodes/edges」，PRD §10.2 的 12 条交互不自研） |
| **D-B** | 布局谁算 | **B1 用 dagre**，布局函数纯函数化 |
| **D-C** | 噪声带判定放哪 | **后端算 + 契约 1.2.0 加 `within_noise_band`**，前端只读不算（TODO 5.4 明令「不要让多个前端组件各自判断」） |

D-A 影响最大（决定要不要引 1 个大依赖 + 自研工作量差 1000 行）。D-B/D-C 若无异议我按推荐执行。
