
---

## 8. 执行结果（2026-10-02 完成）

### 提交

| 提交 | 信息 |
|---|---|
| `f773509` | `docs(webui): 增加阶段 3 前端工程壳的实现计划` |
| `a954cd3` | `feat(web): 增加四模块应用外壳与路由骨架` |

分支：本地 **`webui-p0`**（无斜杠）。提交后已核对 `git rev-parse HEAD` == `git rev-parse webui-p0`，ref 存活。

### 交付物（`web/`）

| 层 | 文件 |
|---|---|
| 工程 | `package.json`、`vite.config.ts`、`tsconfig.json`、`index.html`、`eslint.config.js`、`.gitignore` |
| 设计 token | `src/styles/theme.css`（Tailwind v4 CSS-first，`:root` + `[data-theme=dark]`） |
| 外壳 | `src/app/shell/{AppShell,RailNav,TopBar,TopBarBadges,SettingsDrawer,HelpDialog}.tsx` |
| 路由 | `src/app/router.tsx`（代码式，10 条路由）、`src/app/navigation.ts`（四项权威） |
| 数据层 | `src/lib/{api,api-error,query-client,query-keys}.ts`、`src/stores/ui-store.ts` |
| 页面 | `src/routes/`（总览接真实 `/api/runs`；其余 `StagePlaceholder` 诚实占位） |
| 状态组件 | `src/components/states/{ApiErrorPanel,EmptyState,MissingArtifactNotice,ConnectionBanner,DemoDataBadge,StagePlaceholder}.tsx` |
| 测试 | `src/app/{navigation,App}.test.tsx`、`src/app/shell/shell.test.tsx`、`src/lib/api-error.test.ts` |

### 验证（全部通过）

| 项 | 结果 |
|---|---|
| `tsc --noEmit` | exit 0 |
| `vitest run` | **34 passed**（navigation 15 / api-error 7 / shell 7 / App 集成 5） |
| `eslint .` | **0 error / 0 warning** |
| `vite build` | 成功；`css 17.35 kB`、`js 372.06 kB`（gzip 118.96 kB） |

### 与计划的偏差（3 处，均已按灵梦指示修正）

1. **D2 路由集合**：计划原定「TODO 3.3 的 6 条路由」；实际按 **PRD 5.2 的 10 条**实现
   （多出 `/overview/tasks/$taskId`、`/runs/$runId/tree`、`/runs/$runId/timeline`、
   `/runs/$runId/audit`）。依据：灵梦明确「导航以 PRD 文字为准」。
   树 / 时间轴 / 审计仍是**运行内深链接**，不进入侧栏。
2. **D3 视觉来源**：不再参考 `qianduan-yemian-demo` 分支，改为**从 4 张概念图提取视觉方向**
   （深靛侧栏、indigo 主色、状态语义色、白卡细边圆角、亮暗双主题）。
   **第 4 张概念图的 8 项侧栏与 PRD「严格四项」冲突，不采纳。**
3. **顶部栏徽章**：`/api/meta` 至今**没有 Qwen 字段**，`process_control_enabled=false`，
   因此 Qwen / 执行器徽章如实显示「未接入 / 未启用」（沿用 D6 的诚实原则）。

### 实际踩到、计划里没预见的坑

- **`RunDetailResponse` 没有 `summary` 字段**：分数与状态在 **`outcome`**
  （`best_score` / `improvement` / `iterations_done` / `status`），`data_state` 直接在 detail 上。
- **`listRunsApiRunsGet()` 返回数组**（`RunSummaryResponse[]`），不是包装对象。
- **ESLint 的 `error_code` 文案顺序**：`ApiErrorResponse.message` 是英文原文，
  按 TODO 3.5 必须**优先显示本地中文映射**，服务端英文降到 detail 区。
- **pnpm store 被中断的安装写坏**：表现为 `reused N, downloaded 0` 却仍报
  `Cannot find module './xxx'`（eslint 缺 `lib/eslint/index.js`、ajv 缺 `lib/dotjs/validate`、
  enhanced-resolve 缺 `lib/util/memoize`）。修法：删 store + `node_modules` 后重装。

### TODO 阶段 3 完成定义核对

| 条件 | 状态 |
|---|---|
| 代码已实现，不是空函数或假数据 | ✅（占位页用 `StagePlaceholder` 明示所属阶段，不填假数据） |
| 有正常路径测试 | ✅ |
| 有至少一个失败/边界测试 | ✅（404 运行、未知路由、network 错误、路径脱敏） |
| 不读取 holdout | ✅（前端不接触数据目录） |
| 不泄露密钥和路径 | ✅（`redactPaths` + 错误详情折叠） |
| 不在前端重新计算正式分数 | ✅（只展示 DTO 字段） |
| 相关契约已重新生成 | ✅（本次未改契约，无需重生成） |
| Python 回归通过 | ⏳ 本阶段未改 Python，留待阶段 4 一并回归 |
| 前端 test/lint/build 通过 | ✅ |
| 文档与实际行为一致 | ✅ |

> 且概念图只用于确定信息层级、布局密度与配色方向；
> **字段、导航和交互一律以 PRD 文字为准**。
>
> 经复核，该分支本身也已确认**只有一个静态 `demo/` 目录**，不含 `web/`、不含 `webapi/`
> （全分支普查 24 个远端分支，`src/faultevolve/webapi/` 命中数为 0）。
> 下面这段仅作历史记录保留，**不作为实现依据**。

`demo/`（不在 `main`、不在 `webui-p0`）：`index.html`、`app.css`（529 行）、`app.js`、
`build.py`、`data/*.js`（7 个 run id + `index.js` + `offline-replay.js`）。

`demo/app.css` 开头自述了视觉规范（注释里写"PRD §3.6"，但**当前 PRD 正文里没有这一节**）：

- 主色 **indigo `#4F46E5`** + 强调 **cyan `#06B6D4`**，各带 soft 变体；
- 等级色板：confirmed/revised/discovered/refuted/undetermined/warn 六档，明暗各一套；
- 圆角 12–16px（`--radius-lg: 16px`，`--radius: 12px`，`--radius-sm: 8px`）；
- **Metro 平面风**：用描边分区，不用重阴影；
- 明暗双主题走 `:root` + `[data-theme="dark"]`；
- **明令禁止**：渐变、点阵/纹理背景、单色外壳、只靠颜色区分等级。

**已弃用**：它的侧栏有 **10 项**（新建运行/运行总览/代际时间轴/证据强度/进化树/知识卡/记忆面板/数据边界/对照与稳健性/运行对比），与 PRD §5.1 的"严格四项"直接冲突，
且 TODO §0.2 明令"在侧栏增加四个模块之外的入口"属禁止事项。

概念图在 `docs/images/frontend-concepts/`（`01-overview-new-run.png`、
`02-evolution-workbench.png`、`03-knowledge-discovery.png`、`04-results-report.png`）。
**注意第 4 张概念图的侧栏有 8 项**（项目概览/数据管理/实验配置/运行与监控/结果与报告/模型与候选/系统设置），
同样与"严格四项"冲突 —— 概念图里的导航同样**不作数**，以 PRD §5.1 为准。

### 0.6 工具链与网络（实测）

| 项 | 实测值 |
|---|---|
| node | **v22.22.2**（托管版，路径 `C:\Users\A\.workbuddy\binaries\node\versions\22.22.2-3`） |
| npm | 10.9.7 |
| registry | `https://registry.npmjs.org/` **可达**（`npm view react version` → `19.3.0`） |
| pnpm | `pnpm.CMD` 在托管 node 目录下；`packageManager` 钉 `pnpm@9.15.9` |

registry 上关键包的**当前最新版**：

| 包 | 最新 | 备注 |
|---|---|---|
| `react` | 19.3.0 | 符合 TODO 的 React 19 |
| `vite` | 8.3.2 | |
| `@vitejs/plugin-react` | 6.1.1 | |
| `tailwindcss` / `@tailwindcss/vite` | 4.3.3 | **v4 是 CSS-first**，没有 `tailwind.config.js`，改用 `@theme` 指令 |
| `@tanstack/react-router` | 1.170.41 | |
| `@tanstack/react-query` | 5.104.0 | |
| `zustand` | 5.0.15 | |
| `vitest` | 5.0.3 | |
| `@testing-library/react` | 16.3.3 | 支持 React 19 |
| `typescript` | **7.0.2** | 7 是 Go 原生重写版；`web/package.json` 现钉 **5.9** |

### 0.7 本机两个操作坑（阶段 2 已踩实）

1. **`pnpm --dir web <cmd>` 在本机不可用**：corepack 按"cwd 最近的 `package.json`"挑 pnpm 版本，
   `--dir` 不改变 cwd。必须 `cd web` 后用 **绝对路径 `pnpm.CMD`**。
   ⇒ TODO §13.1/§16 里写的 `pnpm --dir web ...` 全部要落地成本机可执行的形式。
2. 仓库根 `build/` 是 pytest 的 TMPDIR 暂存，已进 `.gitignore`；前端产物用 `web/dist`、`web/.vite`（也已在 `.gitignore`）。

---

## 1. 阶段划分（4 步，每步独立可验）

### 3A 工程初始化与工具链（不含业务界面）

| 文件 | 内容 |
|---|---|
| `web/package.json` | 补 `scripts`：`dev` / `build` / `preview` / `test` / `test:watch` / `lint` / `typecheck`；补依赖 |
| `web/index.html` | 挂载点 `#root`，`lang="zh-CN"`，`<meta name="color-scheme">` |
| `web/vite.config.ts` | `@vitejs/plugin-react` + `@tailwindcss/vite`；`server.proxy['/api'] → http://127.0.0.1:8000`；`test` 段（jsdom、setupFiles、globals） |
| `web/tsconfig.json` / `tsconfig.app.json` / `tsconfig.node.json` | strict + `noUncheckedIndexedAccess` + `verbatimModuleSyntax`；`@/*` 路径别名 |
| `web/eslint.config.js` | flat config：`typescript-eslint` + `react-hooks`；**禁止 `any`**（生成物 `src/generated/**` 豁免） |
| `web/vitest.setup.ts` | 注入 `@testing-library/jest-dom`、`matchMedia`、`ResizeObserver` 打桩 |
| `web/src/styles/tokens.css` | 从 `demo/app.css` 迁移的令牌，写进 Tailwind v4 的 `@theme` + `:root`/`[data-theme="dark"]` |
| `web/src/styles/global.css` | 重置 + 基础排版 + 焦点可见样式 |

完成判据：`pnpm typecheck` / `pnpm lint` / `pnpm build` 三条全绿；`pnpm dev` 能起站点。

### 3B 四模块外壳与路由（TODO 3.2 / 3.3）

| 文件 | 内容 |
|---|---|
| `src/main.tsx` | 挂 `QueryClientProvider` + `RouterProvider` + 主题初始化 |
| `src/app/AppShell.tsx` | 三段布局：左 rail + 顶 bar + `<Outlet/>`；`<main>` 带 `role="main"` |
| `src/app/Sidebar.tsx` | 从 catalog 的 `nav_modules` 渲染**恰好四项**，顺序 overview→workbench→knowledge→results；当前路由高亮用 `aria-current="page"` |
| `src/app/TopBar.tsx` | 左侧：面包屑/当前运行（短 ID）；右侧：Qwen 徽章、纯云端徽章、执行器状态、设置齿轮、帮助按钮 |
| `src/app/SettingsDrawer.tsx` | Radix Dialog 抽屉，**挂在 TopBar 下，不进侧栏**；本阶段只放"外观"分组（主题切换 + 演示/专家模式开关），其余分组显示"阶段 X 交付" |
| `src/app/HelpDialog.tsx` | 帮助弹窗，说明四模块职责与"分数只来自 evaluator" |
| `src/app/ThemeProvider.tsx` | `light`/`dark`/`system` 三态写入 `document.documentElement[data-theme]`，持久化到 localStorage（**只存主题，不存任何密钥**） |
| `src/routes/router.tsx` | 显式路由树（见 §2 D1）；`defaultNotFoundComponent` |
| `src/routes/*.tsx` | 6 条路由的页面壳 |

路由清单（以 TODO 3.3 为准，见 §2 D2）：

| 路径 | 页面 | 阶段 3 交付到什么程度 |
|---|---|---|
| `/` | 总览 | 页面壳 + `EmptyState`（"运行入口在阶段 4 交付"） |
| `/runs/new` | 新建运行 | 页面壳 + `EmptyState`（阶段 4） |
| `/runs/$runId` | 进化工作台 | **真实纵向切片**：用 `/api/runs/{run_id}` 校验运行，成功渲染摘要卡（状态/轮次/best_score/提升），404 → `ApiErrorPanel` |
| `/runs/$runId/knowledge` | 知识发现 | 同上校验运行；内容区 `EmptyState`（阶段 6） |
| `/runs/$runId/results` | 结果与报告 | 同上校验运行；内容区 `EmptyState`（阶段 6） |
| `/compare` | 运行对比 | 页面壳 + `EmptyState`（阶段 6） |

工作台内的**树 / 时间轴 / 排行榜用查询参数**（`?tab=tree|timeline|leaderboard`）表达，
不新增路由、不进侧栏——既满足 TODO"页内标签"，又保留 PRD §5.2 的"刷新可恢复"能力。

完成判据：六条路由都能直达并刷新；深链接 `/runs/<不存在的 id>` 出错误面板而不是转圈。

### 3C 数据层（TODO 3.4）

| 文件 | 内容 |
|---|---|
| `src/lib/apiClient.ts` | 用 `src/generated/api` 的 SDK，`baseUrl` 取 `import.meta.env.VITE_API_BASE ?? '/api'`；统一把非 2xx 归一成 `ApiError { status, errorCode, message, detail, field, retryable }` |
| `src/lib/queryKeys.ts` | 稳定 query key（见下） |
| `src/lib/queries.ts` | 薄封装 hooks：`useMeta`、`useRuns`、`useRun`、（阶段 5/6 再补 tree/events/...） |
| `src/lib/errorMessages.ts` | `error_code` → 中文文案表，覆盖后端 `ErrorCode` 现有全部 **19** 个码（`not_found`/`method_not_allowed`/`request.invalid`/`path.not_allowed`/`path.not_found`/`path.not_directory`/`run.not_found`/`run.unreadable`/`artifact.missing`/`artifact.invalid_json`/`artifact.not_downloadable`/`node.not_found`/`not_supported`/`backend.unavailable`/`backend.auth_failed`/`backend.host_key_mismatch`/`environment.not_ready`/`llm.key_missing`/`internal`） |
| `src/lib/catalog.ts` | 从一个薄的 catalog 端点读取 `nav_modules`/`nav_module_labels_zh`；本项目是**静态导入** `web/openapi/engine-catalog.json`（它是构建期产物，不需要服务端） |
| `src/stores/uiStore.ts` | Zustand，**只**存：当前 runId（镜像）、选中节点、展开面板、主题、本地视图过滤器 |

查询键（与后端 URL 一一对应，写死为常量以保证"稳定"）：

```ts
export const qk = {
  health: ['health'],
  meta: ['meta'],
  runs: ['runs'],
  run: (runId: string) => ['runs', runId],
  tree: (runId: string) => ['runs', runId, 'tree'],
  node: (runId: string, nodeId: string) => ['runs', runId, 'nodes', nodeId],
  events: (runId: string, afterId?: number | null) =>
    ['runs', runId, 'events', { afterId: afterId ?? null }],
  scores: (runId: string) => ['runs', runId, 'scores'],
  leaderboard: (runId: string) => ['runs', runId, 'leaderboard'],
  knowledgeCards: (runId: string) => ['runs', runId, 'knowledge', 'cards'],
  insights: (runId: string) => ['runs', runId, 'insights'],
  discovery: (runId: string) => ['runs', runId, 'discovery'],
  artifacts: (runId: string) => ['runs', runId, 'artifacts'],
  reportManifest: (runId: string) => ['runs', runId, 'reports', 'manifest'],
} as const
```

**URL 是 runId 的唯一真源**：深链接刷新时由路由参数驱动 `useRun(runId)`，
再用 effect 把 runId 镜像进 Zustand（**单向**：URL → store，绝不 store → URL）。
这是"刷新深链接可恢复当前运行"能通过的实现方式。

配套后端小改动（1 个可选字段，minor 契约变更）：

- `MetaResponse` 增 `demo_run_ids: list[str] = Field(default_factory=list)`。
  `WebSettings.demo_run_ids` 目前是**死配置**（定义了没人读），阶段 3 让 `/api/meta` 读它，
  前端据此点亮 `DemoDataBadge`。不这样做就只能靠猜，违反"不编造"。
- `CONTRACT_VERSION`：`1.0.0` → `1.1.0`（新增可选字段 = minor，见 TODO §13.4）。
- 收尾必做：`export_web_contracts.py` → `check_web_contracts.py` → `generate:api`。

### 3D 统一错误与空状态（TODO 3.5）

| 组件 | 行为 |
|---|---|
| `ApiErrorPanel` | 摘要 + **稳定错误码** + 是否可重试 + 建议 + 折叠技术详情；文案优先取 `errorMessages[error_code]` |
| `EmptyState` | 必填 `reason` 与 `nextStep`（PRD §15.2 要求"说明原因和下一步"） |
| `MissingArtifactNotice` | 针对 `artifact.missing` / `state: "missing"`，显示"本次运行未产生该制品"，并保留同页其他区块 |
| `ConnectionBanner` | `/api/health` 探活失败时置顶非阻塞横幅，含"重试"按钮 |
| `DemoDataBadge` | 当前 runId ∈ `meta.demo_run_ids` 时显示"演示数据（已脱敏）" |

错误码 → 文案表要覆盖阶段 2 已定义的 19 个枚举（`errors.py` 里的 `ErrorCode`），
**新增码不认识时**回退到"未知错误（<code>）"而不是崩掉或显示空白。

---

## 2. 需要拍板的 6 个决策

| # | 决策 | 我的建议 | 理由 |
|---|---|---|---|
| **D1** | 路由怎么写 | **代码式**（`createRootRoute` + `createRoute` 手写路由树） | 只有 6 条路由。文件式要额外引 `@tanstack/router-plugin`、生成并 ignore `routeTree.gen.ts`，对"实现能力有限的 AI"是额外魔法；代码式可读、可测、无 codegen |
| **D2** | 路由清单以谁为准 | **以 TODO 3.3 为准**（6 条），把 PRD §5.2 的 `tree/timeline` 降为工作台内的 `?tab=` 查询参数 | 两份文档冲突（PRD 有 `/overview/tasks/:taskId`、`/runs/:runId/tree`、`/runs/:runId/audit`；TODO 没有）。TODO 是实现任务书且明确写了"树/时间轴/排行榜是页内标签"；`?tab=` 保住了深链接能力，又不增加一级导航 |
| **D3** | 视觉令牌用哪套 | **采纳 `demo/app.css` 的令牌**（indigo `#4F46E5` + cyan `#06B6D4`、六档等级色、圆角 12–16px、Metro 平面、明暗双套、禁止渐变/纹理/重阴影），并**回写进 PRD** | 这是团队唯一一套成型的设计规范，且 PRD §13.3 要求"影响产品外观的变更同步检查 PRD"。当前 PRD 正文里根本没有这套规范，属于文档缺口 |
| **D4** | 四项导航硬编码还是读契约 | **从 `engine-catalog.json` 读**（`nav_modules` + `nav_module_labels_zh`） | 契约里已经有权威数据，硬编码就会和生产环境漂移。测试断言"渲染出的数量恰好 4 且顺序固定" |
| **D5** | Query key 手写还是让 openapi-ts 生成 | **手写 `queryKeys.ts` + 薄 hooks** | TODO 3.4 原文就是"定义稳定 query key"。openapi-ts 的 TanStack Query 插件会生成一整套 hooks，与 `features/*` 里的业务 hook 重叠，反而更难收敛；手写 + 一条"键唯一性"测试更可控 |
| **D6** | 顶部栏的 Qwen 徽章与执行器状态 | **如实显示否定状态**："Qwen：未接入"、"执行器：未实现（阶段 7）"、"纯云端：已声明（执行后端未实现）"；设置抽屉里对应分组只显示"阶段 X 交付" | 后端**没有**这些数据源（§0.3）。亮假绿灯违反硬约束，也是 TODO §15"不写假实现"的直接违规 |

### 2.1 工具链版本（并入 D1 一起确认）

| 项 | 建议 | 理由 |
|---|---|---|
| TypeScript | **继续钉 5.9.x**，不升 7.0.2 | TS 7 是 Go 原生重写版，`@hey-api/openapi-ts` 与 `@tanstack/router` 的类型插件尚未验证；阶段 3 不应引入未知变量。升级单独立项 |
| Tailwind | **用 v4.3.3**（CSS-first：`@tailwindcss/vite` + `@theme`） | 直接上 v4，避免先写 v3 的 `tailwind.config.js` 再迁移；D3 的令牌正好落进 `@theme` |
| Vite | 8.3.2 + `@vitejs/plugin-react` 6.1.1 | 都是当前稳定版，node 22.22.2 满足要求 |
| 测试栈 | `vitest` + `jsdom` + `@testing-library/react` + `@testing-library/user-event`；**不引 Playwright** | TODO 3 的 5 条测试都是组件级；Playwright E2E 属阶段 9（TODO §12.4） |
| Lint | `eslint` flat config + `typescript-eslint` + `react-hooks` | TODO §13.2 要求 `pnpm lint`；`src/generated/**` 需豁免 |

---

## 3. 与任务书 / PRD 的分歧（显式标注）

| 分歧点 | 文档说法 | 我的处理与理由 |
|---|---|---|
| 路由集合 | PRD §5.2 有 9 条；TODO 3.3 只有 6 条 | 按 D2 取 TODO，PRD 多出的 `/overview/tasks/:taskId`（阶段 4）、`/runs/:runId/audit`（阶段 6）留到对应阶段 |
| 工作台内视图 | PRD §5.2 把它们做成独立路由 | 按 D2 降为 `?tab=` 参数；TODO 明说"不增加侧栏"，用查询参数同时满足两边 |
| 视觉规范 | PRD 正文**没有**色彩/风格规范；只有 `demo/app.css` 的注释写着"PRD §3.6" | 按 D3 采纳 demo 令牌，并把规范**补写进 PRD §5.4**（新增小节），消除"规范只存在于代码注释里"的缺口 |
| 导航结构 | `demo/` 有 10 项侧栏 | 明确**不复用**：PRD §5.1 要求严格四项，TODO §0.2 把额外入口列为禁止事项。demo 只复用令牌与信息密度思路 |
| 命令形式 | TODO §13.1/§16 写 `pnpm --dir web ...` | 本机实测不可用（§0.7），计划里统一写成 `cd web && <绝对路径 pnpm.CMD> ...`，并在此标注偏差 |
| 401 处理 | TODO 阶段 3 测试要求"API 401/404/500 有明确反馈" | 后端 P0 **没有**鉴权中间件（PRD §17.1 允许单用户不建账户），401 只能靠**打桩响应**测试；这不算假实现，属前端错误表能力 |

---

## 4. 测试清单（TODO 阶段 3 的五条 + 补充）

| 测试文件 | 覆盖 |
|---|---|
| `src/app/Sidebar.test.tsx` | **侧栏恰好四项**、顺序正确、标签来自 catalog、当前路由有 `aria-current` |
| `src/app/TopBar.test.tsx` | 设置齿轮打开抽屉；**抽屉里的入口不出现在 `nav` 内**（"设置抽屉不占侧栏"）；Qwen 徽章在无数据时显示"未接入"而**不是**"已连接" |
| `src/app/ThemeProvider.test.tsx` | 主题切换写入 `[data-theme]`；`localStorage` 里**只有主题**，没有任何 key/secret |
| `src/routes/router.test.tsx` | 六条路由都能渲染；深链接 `/runs/<id>` **刷新后仍能恢复**该运行（URL → store 单向） |
| `src/lib/apiClient.test.ts` | 非 2xx 归一化：404/500/401 分别得到 `error_code`、`retryable`；网络错误有 `ConnectionBanner` 而不是白屏 |
| `src/lib/errorMessages.test.ts` | 后端 19 个 `error_code` 逐个有中文文案；**未知码**回退成"未知错误（code）" |
| `src/lib/queryKeys.test.ts` | 所有键唯一；同一 runId 的不同资源键互不相等（防缓存串味） |
| `src/features/run/RunGuard.test.tsx` | 不存在的 run → `ApiErrorPanel` + `error_code=run.not_found`，**不出现 spinner**（"不存在 run 时不会无限 loading"） |
| `src/components/feedback/*.test.tsx` | 五个反馈组件的正常/边界（无 reason 时禁用渲染） |

每个文件都要"正常路径 + 至少一个失败/边界"（TODO §15 第 2、3 条）。

---

## 5. 验收命令与预期

```bash
cd <repo>

# 1. 后端契约（若采纳 D5/§3C 的 MetaResponse 变更）
.venv/Scripts/python.exe scripts/export_web_contracts.py
.venv/Scripts/python.exe scripts/check_web_contracts.py        # 预期 exit 0

# 2. 前端依赖与生成物
cd web && "C:/Users/A/.workbuddy/binaries/node/versions/22.22.2-3/pnpm.CMD" install
"C:/Users/A/.workbuddy/binaries/node/versions/22.22.2-3/pnpm.CMD" generate:api

# 3. 前端门禁（四条都要绿）
"C:/Users/A/.workbuddy/binaries/node/versions/22.22.2-3/pnpm.CMD" typecheck
"C:/Users/A/.workbuddy/binaries/node/versions/22.22.2-3/pnpm.CMD" lint
"C:/Users/A/.workbuddy/binaries/node/versions/22.22.2-3/pnpm.CMD" test
"C:/Users/A/.workbuddy/binaries/node/versions/22.22.2-3/pnpm.CMD" build

# 4. Python 回归（后台跑，本机约 22 分钟）
cd <repo> && .venv/Scripts/python.exe -m pytest -q > build/tmp/phase3_pytest.log 2>&1
#     预期：644 + 新增 / 失败仍为 8（同一批 CRLF 假红），0 新增失败

# 5. 人工冒烟（两个终端）
#   A: .venv/Scripts/python.exe -m uvicorn --factory faultevolve.webapi.app:create_app --port 8000
#   B: cd web && <pnpm> dev        # 打开 http://localhost:5173
#      侧栏 4 项；点四项都能切换且高亮；刷新 /runs/hdd_mvp_demo_7510f100 仍显示该运行
```

提交信息（TODO §3 推荐顺序第 3 条）：

```
feat(web): add four-module application shell
```

---

## 6. 明确不做的事（防止范围蔓延）

- **不做**任何真实业务页面：树、时间轴、排行榜、知识卡、结果页都留占位（阶段 5、6）。
- **不做**运行创建、进程控制、SSE（阶段 7、8）。
- **不做** Playwright E2E（阶段 9）。
- **不引** Playwright、Monaco、React Flow、Radix 全套——阶段 3 只引"抽屉/弹窗/徽章"，
  重组件等真正用到那一步再引。
- **不引**状态管理之外的数据层（不引 SWR、不引 Redux、不在前端存服务端运行状态）。
- **不改** `demo/` 分支、不从它 merge 代码；只借令牌数值。
- **不动** 阶段 2 的 13 个只读端点语义（只加 `MetaResponse.demo_run_ids` 一个可选字段）。
- **不做**主题的动画/过渡特效（PRD §18.2 要求支持"减少动态效果"，本阶段只保证不阻塞）。

---

## 7. 已知风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| Tailwind v4 是 CSS-first，网上多数示例仍是 v3 写法 | 令牌写错、样式不生效 | 按 v4 官方写法用 `@theme` + `@tailwindcss/vite`；先跑 `build` 验证产物 CSS 里有令牌 |
| 依赖数量一次性膨胀（React/Vite/Tailwind/Router/Query/Zustand/ESLint/Vitest） | `pnpm install` 失败或版本互相不兼容 | 分两批装：先 3A 的构建链，跑通 `build` 再装 3B/3C 的运行时依赖 |
| TS 7.0.2 已发布，容易被"顺手升级" | 生成客户端/路由类型崩 | 显式钉 `typescript@5.9.x`（D2.1），并在 package.json 写死 |
| 后端没有 Qwen/执行器数据源 | 顶部栏徽章没数据可用，容易被写成假绿灯 | 按 D6 如实显示"未接入"，测试钉住"无数据时不得显示已连接" |
| 深链接恢复若把 Zustand 当唯一真源 | 刷新后丢运行，或出现"无限 loading" | URL → store 单向同步；`RunGuard` 单独测试 404 路径 |
| 本机 `pnpm --dir` 不可用 | 照抄文档命令全部失败 | 统一 `cd web` + 绝对路径 `pnpm.CMD`（§0.7） |
| Python 回归 22 分钟 | 迭代慢 | 阶段 3 只改 1 个 DTO，受影响面小；用 `tests/webapi/ -q` 做快循环，全量只跑一次 |
