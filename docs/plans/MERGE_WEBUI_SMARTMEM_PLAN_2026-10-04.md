# 把 WebUI 线与 SmartMem 线合入当前 main 的书面计划

**已于 GitHub main 执行：** PR #54（`29b97a8`）；合入后能力摘要见仓库根目录 [`README.md`](../README.md)「GitHub main 补充（PR #54）」一节。

日期：2026-10-04。性质：**仅规划，本 PR 不含功能代码、不执行合并、不改引擎行为**。执行者：后续编码代理。

绑定规则：**当前 main 赢。** 保留 main 的知识发现引擎、`hdd_v1`/`v2`/`v3`/`v4` 库、KD1-I 预检记录、e-BH、门控和 README 实验事实。不重跑 HDD3/HDD4，不放宽门，不把负结果改写成发现。

## 0. 结论

1. 两条远端分支的 tip **与任务描述一致**，main 也已到 `#52`，没有因 main 再前进而换 SHA。
2. 远端没有名为 `2smart` 的分支。唯一匹配 `smart` 的是 `origin/feat/smartmem-data-knowledge`。没有更合适的替代，按这条规划。
3. **先合 `webui-phase10`，再合 SmartMem。** 理由见 §4。不要对整条 tip 做一次裸 `git merge` 然后「有冲突再看」。
4. Git 对 `main + webui-phase10`、`main + smartmem` 都能算出**无冲突树**。这只说明两边自共同祖先以来很少改同一文件，**不表示结果语义正确**。裸合并会把 WebUI 线上 `556ca01` 的发现/引擎大块带进 main，并改掉 `hdd_v1.jsonl`。这两件事都禁止。
5. 本文件只告诉执行代理：取什么、丢什么、前端还要能用哪些屏、怎样算做完。不规定具体行级补丁。

## 1. 已核实的 tip（2026-10-04，`git fetch` 之后）

| 引用 | SHA | 相对 `origin/main` |
|---|---|---|
| `origin/main` | `05d9f6f0d275285df3fb4763a4f568d355c6e862`（`docs: KD1-I preflight B`，#52） | — |
| 其父 | `1c395b39ac882d5438a94e5457c635f11b6960d1`（`hdd_v4`，#51） | — |
| `origin/webui-phase10` | `ca315f1a7f9327bf8ad4dd1133cdcbc0ad97dea4` | 超前 17，落后 2（#51、#52） |
| `origin/feat/smartmem-data-knowledge` | `f38d496767d44883fd8488cb54e7bcf89c9421dc` | 超前 33，落后 49 |

共同祖先：

- main ∩ webui-phase10 = `cea7283418cb7603d06a7624c1938d363e5776f8`（KD1-I 家族规划，#50）。与「从 `cea7283` 分叉」一致。
- main ∩ smartmem = `a366c92519b121b9203a7cdd2bbd63f6a2d87758`（SmartMem 两阶段需求文档）。webui ∩ smartmem 也是它。

三方 `merge-tree --write-tree` 均退出 0（Git 认为可自动合并）。执行时**仍按下面的「谁赢」表人工取舍**，不要相信自动合并结果。

## 2. 没有更好的 SmartMem 分支

`git branch -r` 里带 `smart` 的只有 `origin/feat/smartmem-data-knowledge`。没有 `2smart`、没有第二条 SmartMem 功能线。本计划只合这一条。

## 3. 各分支相对当前 main 实际多了什么

「多了什么」用三方差异（`git diff origin/main...分支`）：只算该分支在共同祖先之后自己做的事。两边 tip 的两方差异会把「main 有、旧分支没有」也算进去，**不能当要带入的清单**。SmartMem 的两方差异会看起来像要删 `hdd_v4`、自动调优、半个 WebUI，那是它落后 49 个提交，**禁止按两方差异合。**

### 3.1 `webui-phase10`（199 个文件，三方）

main 在 `cea7283` 之后已经有完整 WebUI 阶段 9（`9a3643f` 等）以及契约 **1.7.0**。这条备份线在分叉之后又往前走了一截，**main 还没有**的主要是：

**契约与 WebAPI（应带入）**

- 契约从 1.7.0 加到 **1.11.0**（`src/faultevolve/webapi/contracts.py` 与 `web/openapi/`、`web/src/generated/`）：
  - 1.8.0：`RunSummaryResponse.task_id`、`MetaResponse.qwen_configured`（可选；`task_id` 是任务目录名，不是路径；配置探测不带出密钥）
  - 1.9.0：`MetaResponse.qwen_reachable`（可选；无密钥时为 `None`，不要把「没探测」显示成失败）
  - 1.10.0：知识卡可选 `title` / `category` / `priority` / `sources`；claim 等只在任务目录里对得上目录卡时才填
  - 1.11.0：`KnowledgeSourceResponse.takeaway`（只从 `sources.yaml` 抄，不编）
- 新模块：`etag.py`、`knowledge_catalog.py`、`qwen_status.py`，以及 `app.py` / `catalog.py` / `replay_service.py` / `server_profiles.py` 上为它们接的线
- 相关测试：`tests/webapi/test_etag.py`、`test_knowledge_catalog.py`、`test_qwen_status.py`、`test_run_task_id.py` 等
- `457827c`：key-ref 环境变量名改大写（POSIX 下解析）。这是 WebAPI，不是发现判定。

**回放夹具（应带入）**

main 已有 `hdd_mvp_demo_7510f100`、`hdd_mvp_faildemo_4b81c0d2`。分支上共 5 套，还要带入另外 3 套：

- `tests/fixtures/runs/hdd_mvp_real_38cb38cf`
- `tests/fixtures/runs/hdd_mvp_real_f9752fcd`
- `tests/fixtures/runs/hdd_mvp_treedemo_7c1a2e09`

以及 `scripts/build_run_fixture.py`、`make_demo_run.py`、`make_tree_showcase_fixture.py` 和对应 webapi 回放测试。

**前端（应带入，允许为共存在再改）**

- 新建运行：部署模式卡片（`DeploymentModeCards`）
- 顶栏：Qwen 配置/可达徽章
- 运行对比页：对比逻辑与类型修复
- 时间轴：缺口检测
- 知识卡页：按任务知识库对照正文（`CardProseList` / `knowledge_catalog`）
- 工作台树：展示树夹具、虚拟化/ETag 相关收口（见 `562cdae`）
- `docs/plans/WEBUI_DEBUG_ORDER.md`
- `.gitignore` 忽略仓库根探针产物（`fe_*` / `hdd_eval_*` / `tmp*.py`）

**引擎：两条作者点名的修复（见 §6，不是整文件覆盖）**

- `af01e2a`：选择被拒时有界停跑 + `run_stalled` / `selection_stalled`。当前 main **没有** `stall_iterations`。
- `a1190d2`：因子发现任务无关化；以及改 `hdd_v1.jsonl` 三处（改 F020 列、删 F022/F024）。**库文件本身禁止带入。**

**引擎：作者没当成「两条修复」、但 tip 里确实多出来的（默认不带）**

- `556ca01`（阶段 9 后端半段 + sandbox 回归）改了 `pipeline.py` / `report.py` / `sandbox.py` / `schemas.py` / `stats.py` / `tests_catalog.py` / `tournament.py`，以及 `engine.py` / `judge.py` / `store.py` / `hdd_adapter.py` / `protocol.py` 的配套大块。
- 相对当前 main，这些文件的两方 diff 很大（例如 `sandbox.py` +316、`tournament.py` +218）。共同祖先之后 main **没有**再改它们，所以裸合并会整文件采用 WebUI 侧。
- 其中 sandbox「DataFrame 返回 rc=4、空 stderr」可能是真缺陷，但会改变哪些 claim 算可执行/失败，**可能改变发现结局**。默认留下一笔，另开 PR，不塞进这次合线。
- 随它而来、main 没有的测试（`tests/test_kd2_verdict_gates.py`、`tests/test_discovery_debug_fixes.py` 以及引擎测试里只覆盖该行为的断言）**不要单独合进来**（不是「删 main 的测试」，是不要引入没有对应 main 行为的新锁）。

WebUI 落后 main 的只有 #51、#52：`hdd_v4.jsonl`、`tests/test_factor_library_hdd_v4.py`、`check_factor_library.py`、KD Skill、`KD1I_PREFLIGHT_B_2026-10-04.md`、README/TODO 上的预检事实。合入后这些必须原样留在树上。

### 3.2 `feat/smartmem-data-knowledge`（53 个文件，三方）

main 上 SmartMem 仍是 **stub 适配器**（`StubDatasetAdapter`），`evolve.yaml` 只有任务名和预算，没有本地评测器、知识包、事件流数据层。

这条分支 **main 没有**、应当带入的是任务与数据能力，不是改 HDD 发现引擎：

- `src/faultevolve/data/`：事件模式、分块 IO、外排序、清单/resume、时间切分与泄漏审计
- `src/faultevolve/tasks/smartmem_data.py` + 改过的 `smartmem_adapter.py`（把本地评测接入演化闭环）
- `benchmark/smartmem/`：`evaluator.py`、`candidate_runner.py`、`init.py`、`problem.md`、`prompt.md`、加长的 `prepare_data.py`、知识包（`knowledge/` + `knowledge_check.py`）、README/evolve 更新
- `skill/fe-event-data-preparation/` 及两份 references
- `docs/runs/smartmem-*.md`（演示清单、Linux 冒烟、开发日志、给队长的问题清单等）
- `pyproject.toml` 增加 `pyarrow>=15`（main 自共同祖先未改此文件，Git 会自动带上；应保留）
- 新增测试与 `tests/helpers_smartmem.py`；`tests/test_dataset_stubs.py` 随适配器不再是 stub 而改（不得借机放宽 HDD/其它 stub 断言）

README 三方差异只有两行：技能表和技能目录列表各加 `fe-event-data-preparation`。**实验事实段落一行都不要动。** 执行时把这两行加进 **main 的 README**，不要用分支上的整份 README。

共同祖先之后 SmartMem **没改** `cli.py` / `engine.py` / `config.py` / WebAPI / 发现库。两方差异里那些「旧引擎」全是落后，合并时 Git 会留 main。仍要检查工作树，禁止检出分支上的旧副本。

## 4. 合并顺序

**推荐：先 WebUI，再 SmartMem。**

1. WebUI 只落后 2 个提交，共同祖先就是 #50；先合，#51/#52 留在 first parent 上最清楚。
2. SmartMem 落后 49 个提交。若先合它，工作树会先经历一次大落后合并，再叠 WebUI 契约，审查更差。
3. 两条线几乎不改同一文件（见 §5）。顺序不增加真实冲突，只影响审查。
4. 前端跟进主要发生在 WebUI 契约 1.8–1.11 与现有屏之间；SmartMem 没有自己的页面，后合即可让总览/新建运行看见真实任务。

没有发现需要反过来的理由。

建议工序（仍不规定行级补丁）：

1. 从 `origin/main`（`05d9f6f`，若 main 已前进则以那时的 main 为基，并再对一次两条 tip）拉执行分支。
2. **第一步：有选择地带入 WebUI**，不要 `git merge origin/webui-phase10` 后全盘接受。按路径检出或拣选 §3.1「应带入」；引擎文件按 §5 / §6。
3. 跑 §8 清单，提交。
4. **第二步：有选择地带入 SmartMem**（三方那 53 个文件里属于 SmartMem 的部分 + README 两行技能指针）。不要按两方差异删 main 文件。
5. 再跑 §8，提交。
6. `docs/TODO.md` 只允许在 main 已有 KD 头条之下**追加**一条「WebUI+SmartMem 已按本计划合入」；不得改写 KD 头条或实验数字。

## 5. 冲突与「谁赢」（绑定）

「冲突」包括：Git 标冲突的文件，以及**裸合并会静默采用分支侧、从而改 main 行为**的文件。

### 5.1 先合 WebUI 时

自 `cea7283` 起两边都改过的，只有 `docs/TODO.md`。其余要么只在 WebUI，要么只在 #51/#52。

| 路径 | 谁赢 | 说明 |
|---|---|---|
| `README.md` | **main** | WebUI 三方未改。不要用两方差异覆盖 #51/#52 预检事实。 |
| `docs/TODO.md` | **main 的 KD 头条与实验表述** | Git 可能自动揉进 WebUI 的进度表改写。保留 #51/#52 头条；WebUI 进度只可追加，不覆盖。 |
| `docs/plans/KD1I_PREFLIGHT_B_2026-10-04.md` | **main** | WebUI 没有此文件；禁止删。 |
| `docs/plans/WEBUI_DEBUG_ORDER.md` | WebUI（新增） | main 没有。 |
| `src/faultevolve/discovery/factor_library/hdd_v1.jsonl` | **main** | 禁止 `a1190d2` 的改 F020 / 删 F022 / 删 F024。见 §6.2。 |
| `hdd_v2.jsonl` / `hdd_v3.jsonl` / `hdd_v4.jsonl` | **main** | WebUI 没有 v4；禁止丢 v4。v2/v3 内容保持 main。 |
| `skill/fe-knowledge-discovery/scripts/check_factor_library.py` 与 Skill 文 | **main** | #51 的 `HDD4_` / `rhoK0` / 顺序敏感检查。 |
| `tests/test_factor_library_hdd_v4.py` | **main** | 禁止丢。 |
| `src/faultevolve/discovery/{pipeline,report,sandbox,schemas,stats,tests_catalog,tournament,funnel}.py` | **main** | 不要 `556ca01` 大块。`funnel.py` 在 `a1190d2` 只改了 docstring（「JSON-safe」），若执行时代码已与 main 相同，可只改这一处用词以便任务无关守卫通过；不得改漏斗判定。 |
| `src/faultevolve/cloud/{engine,judge,store}.py`、`common/schemas.py` | **main 为底** | 只把 `af01e2a` 停跑补丁打进 `engine.py`（及为登记 `run_stalled` 所需的最小 catalog/契约字段）。不要整文件换成 WebUI。 |
| `src/faultevolve/config.py` | **main 为底** | 只加 `stall_iterations`（默认 5，`ge=1`），旧配置仍能加载。 |
| `src/faultevolve/discovery/factors.py`、`cli.py`、`tasks/protocol.py`、`tasks/hdd_adapter.py` | **main 为底 + §6.2 代码例外** | 可加任务无关加载/mock 协议；**不**改库 JSONL，**不**改 v3/v4 因子定义。 |
| `src/faultevolve/webapi/**`、`web/**`、`tests/webapi/**`、`tests/fixtures/runs/**`（新增三套）、相关 scripts | **WebUI** | 这是合这条线的目的。与 main 1.7.0 契约并时，以 1.11.0 为合入后版本，且只做加法字段。 |
| `tests/test_run_stall_guard.py` | **WebUI** | 跟着 `af01e2a`。 |
| `tests/test_factor_library.py` | **main 的库条数/id 预期** | 可以**增加**列契约/mock 断言，但不得改成「28 条、已无 F022/F024」。 |
| `tests/test_factor_library_hdd_v3.py`、`tests/test_kd1g_discovery.py`、`tests/test_discovery_preflight_crash_fix.py`、`tests/test_discovery_task_agnostic.py` | **不断言、不改判定** | 若收 §6.2，只改加载 API（例如传入 `allowed_columns`），保持 v3 仍是 24 条、前缀与范围断言不变。preflight 用例仍测 error.txt 路径，不要改弱。 |
| `tests/test_kd2_verdict_gates.py`、`tests/test_discovery_debug_fixes.py` | **默认不带** | 锁的是 `556ca01` 行为。 |

### 5.2 再合 SmartMem 时（基线已是「main + 上一步」）

自 `a366c92` 起 main 与 SmartMem 都改过的，只有 `README.md`。

| 路径 | 谁赢 | 说明 |
|---|---|---|
| `README.md` | **main 全文 + SmartMem 两行技能指针** | 禁止用分支 README 换掉 KD1-I / 预检 B / e-BH / 自动调优事实。 |
| `docs/TODO.md` | **main** | SmartMem 三方未改；不要让落后副本回来。 |
| 发现库、发现引擎、e-BH、门控、`check_factor_library.py`、HDD 评测器 | **main** | SmartMem 三方未改这些；两方差异里的「删除」一律忽略。 |
| `benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md}` 与 `data/` | 不动 | 仓库硬规则。 |
| `src/faultevolve/data/**`、`tasks/smartmem_*.py`、`benchmark/smartmem/**`（新增/该任务下的改动）、`skill/fe-event-data-preparation/**`、`docs/runs/smartmem-*.md`、SmartMem 测试、`pyproject.toml` 的 pyarrow | **SmartMem** | 这是合这条线的目的。 |
| `web/**`、契约 1.11.0 | **上一步结果** | SmartMem 三方未改前端。不要检出落后前端。 |
| `tests/test_dataset_stubs.py` | 保留 main 对其它数据集的断言；只改 SmartMem 不再是 stub 的部分 | 不得放宽。 |

WebUI 与 SmartMem 之间几乎没有共同改动文件。第二步不应再和 WebUI 抢引擎或契约。

## 6. 允许写进计划的引擎例外（必须点名）

默认：引擎文件保持 main。只有下面两条可以带，且不得改发现结局或库定义。

### 6.1 例外 A（建议带）：`af01e2a` 选择被拒时有界停跑

- 缺陷：`iterations_done` 只在成功迭代增加；`select()` 拒绝时返回 False 不计数，可能空转并刷大量 `selection_failed`。
- 改动：`BudgetConfig.stall_iterations`（默认 5）；连续无进展则 `run_stalled` 并 `stop_reason=selection_stalled`。
- 为何算例外：不改 UCT/发现统计/e-BH/库；健康跑满轮次的 `stop_reason` 仍是 `max_iterations`。
- 必须同时登记：`webapi/catalog.py` 的 `EVENT_TYPES` 增加 `run_stalled`，前端 `event-taxonomy.ts` 归入 `run_state`（契约漂移测试要求引擎事件有前端粗类）。带上 `tests/test_run_stall_guard.py`。
- 旧 `evolve.yaml` 无该键仍能加载。

### 6.2 例外 B（建议带代码、禁止带库）：`a1190d2` 的任务无关化

- 缺陷：`discovery/factors.py` 直接 import HDD 适配器、用文件名判断是否校验；`funnel.py` 文档字符串触发任务词守卫。作者称 main 上 `test_discovery_task_agnostic.py` 等会红。
- **可以带的：** `FactorLibraryProvider` 协议、`load_factor_library(..., allowed_columns=)`、调用方提供 mock 特征、CLI 对未实现协议的任务用通用 mock、discovery 包不再 import 具体适配器。这是结构修复，不改 e-BH、切片、门控。
- **禁止带的：** 对 `hdd_v1.jsonl` 的任何改写或删条（F020 改 `smart_5_normalized`、删 F022/F024）。那是改库定义。main 的 v1 在 #51 之后仍是默认库；KD1-G 文档已把 `smart_10_normalized` / 重复代码记成预检事实，不是这次合线要「修好」的发现。
- 测试：可**增加**「传入列契约则拒未知列、不传则仍加载」；**不可**把 v1 条数改成 28，或断言 F022/F024 不存在。v3 仍 24 条，v4 仍 23 条、SHA 见 §8。
- 若任务无关加载在「保留 main 的 v1（含 F020 非法列名）」下让 `test_hdd_factor_library_schema` 在传入 HDD 列契约时失败：失败的是**加载时校验**，不是改库。这时对**已装运的 v1** 不要在默认测试里强制 `allowed_columns=HDD_DISCOVERY_INPUT_COLUMNS` 去卡死整库；列契约测应用玩具行或「缺契约仍能加载」覆盖。不要为了让新断言变绿去改 JSONL。

### 6.3 明确不是例外

- `556ca01` 的 sandbox / 锦标赛 / KD2 门 / 报告管线：默认不带。
- 任何「顺手」改 e-BH、`n_slices`、`bootstrap_b`、功效门、explore 门槛、α。
- 任何重跑或改写 HDD3/HDD4 数字。

## 7. 前端：范围内 / 范围外

不规定组件怎么改行。合完后两条线要能住在同一棵契约（1.11.0）下。

### 7.1 合完后仍必须能用的屏与契约

路由以 `web/src/app/router.tsx` 为准（不要删路由、不要改成另一套信息架构）：

| 路由 | 屏 | 合完后仍要成立 |
|---|---|---|
| `/` | 总览 | 任务卡仍来自目录；HDD MVP 仍在；SmartMem 若已从 stub 变为可适配，应能出现且不把 HDD 卡挤坏 |
| `/overview/tasks/$taskId` | 任务详情（四区） | HDD 详情不回退；SmartMem 详情可以偏薄，但不能 500 或空白死页 |
| `/runs/new` | 新建运行 | 预检、预设、部署模式卡片、演示卡；Qwen 配置/可达与 1.8/1.9 一致（无密钥 → 未探测，不是失败） |
| `/runs/$runId` | 运行外壳 | 演示数据徽章、导航深链仍在 |
| `/runs/$runId/` | 工作台 | 树、事件流、过滤；`run_stalled` 若发生要落在 `run_state` 粗类 |
| `/runs/$runId/tree` | 进化树 | 展示树夹具仍能回放；fitView 不塌高度 |
| `/runs/$runId/timeline` | 时间轴 | 缺口检测不把正常事件打成坏档 |
| `/runs/$runId/knowledge` | 知识卡 / 现象 / 机制赛 | 1.10/1.11：有目录则对照正文与 `takeaway`；无目录则可选字段为 `None`，不编造 |
| `/runs/$runId/results` | 结果与报告 | 对比区、TopK、报告 manifest 仍只渲染契约字段 |
| `/runs/$runId/audit` | 数据边界审计 | 既有事实块仍在 |
| `/compare` | 运行对比 | 1.8 的 `task_id` 可用来对齐任务；类型检查与 build 保持绿 |

契约门：`python scripts/check_web_contracts.py` 退出 0；`web/openapi/*` 与 `web/src/generated/` 相对 Python 源无漂移。CI 工作流 `.github/workflows/web-contracts.yml` 的契约 / Python / 前端三职都要还能跑。

回放：main 原有两套夹具 + 新三套都要能走既有 webapi 回放测试。不要为了新 UI 改旧夹具事件语义。

### 7.2 范围内的前端跟进

- 为 1.8–1.11 加法字段接线（徽章、知识卡对照、对比页 `task_id`）。
- 部署模式卡片与时间轴缺口与现有录入/工作台放在一起。
- SmartMem 出现在总览/新建/任务详情时的展示（名称、文档链、预检是否可跑），用现有任务目录，不新开一套路由。
- E2E/视觉若因文案或徽章失败：只修选择器或可选项断言，不删用例、不把视觉阈值放宽到「等于关掉」。

### 7.3 范围外

- 新页面、新侧栏项、重做设计系统。
- 为 SmartMem 做专用工作台/专用知识可视化。
- 改 PRD 路由树或把对比/审计降级成隐藏实验。
- 规定某个 tsx 的行级写法。
- 把契约降回 1.7.0，或改已有 1.7 字段含义。

## 8. 怎样算做完

执行代理在**动手前**于当时的 `origin/main` 记下：

```text
python -m pytest tests/ --collect-only -q
```

的收集条数（本规划环境未装 pytest，此处不写死数字）。合完后：

1. **测试未删、未改弱。** `git diff origin/main -- tests` 里，main 已有文件只允许加法或为 §6 加载 API 做的机械适配；禁止减少断言、放宽阈值、`pytest.mark.skip`、缩小夹具。测试文件数和收集条数都不得低于动手前的 main。
2. **契约仍过：** `python scripts/check_web_contracts.py` 退出 0；必要时 `pnpm --dir web generate:api` 后对 `web/src/generated` 无意外 diff。
3. **Python 回归：** `python -m pytest tests/` 全绿（含 webapi、发现库、引擎默认关闭路径、SmartMem 新测试）。
4. **前端：** `pnpm --dir web test`、`lint`、`build` 过。E2E 按仓库现有门禁跑；不要为了绿而删 `web/e2e/*`。
5. **main 的 KD 文档与库行为未变：**
   - README 里 #51/#52 的预检漏斗、SHA、`elapsed_s`、outcome B 表述一字不改。
   - `docs/plans/KD1I_PREFLIGHT_B_2026-10-04.md` 仍在。
   - 库字节级保持（2026-10-04 在 `05d9f6f` 上复核）：

     | 文件 | 行数 | SHA256 |
     |---|---|---|
     | `hdd_v1.jsonl` | 30 | `0466699ca7d1859a5ce1ce079788f979162dd272397af612a0747d142abb58b6` |
     | `hdd_v2.jsonl` | 27 | `5cb8036fb8056476d4105e53f80694248ae7c33c652f48ecd6cf71409b6de93f` |
     | `hdd_v3.jsonl` | 24 | `c417237500dbf06517e3eb8505f4950f5d807038d9fdc43eb6dc0c6ee1ac3bbd` |
     | `hdd_v4.jsonl` | 23 | `f46a41a53df996541b94b8b9b86ebac0ed325299bffc5d42717e3499e06d2806` |

     若执行时 main 已前进且库被**另一次已审 PR** 改过，以那时 main 为准并记入执行 PR，不要用本表覆盖更新的 main。
   - `python -m pytest tests/test_factor_library_hdd_v3.py tests/test_factor_library_hdd_v4.py` 仍过；默认 CLI 库仍是 `hdd_v1.jsonl`。
   - 不重跑、不改写 HDD3/HDD4 探索或确认数字。
6. **WebUI 能力在：** 契约 1.11.0；三套新回放夹具在；§7.1 路由仍注册。
7. **SmartMem 能力在：** 数据层、评测器、知识包、准备 Skill、适配器不再是 stub；`pyarrow` 在依赖里。
8. **密钥：** 不写 `DASHSCOPE_API_KEY` / `TYPESAFE_API_KEY` / `FE_API_KEY` 进代码、配置、测试、日志、提交。Qwen 探测只报布尔/`None`。
9. **不读、不打印、不上传** `benchmark/hdd_mvp/data/holdout*`。

## 9. 禁止做

- 实现本计划之外的功能；本规划 PR 尤其不得改引擎或删测试。
- 裸合并 WebUI tip，或按 SmartMem 两方差异删 main 的自动调优 / WebUI / `hdd_v4`。
- 改 `benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md}` 或 `data/`。
- 放宽 e-BH、功效门、explore 门槛、预检通过线；把 HDD3/HDD4 负结果写成发现；重跑 HDD3/HDD4「验证合并」。
- 为让任务无关测试变绿而改任何 `hdd_v*.jsonl`。
- 把 LLM/Jev 输出当成节点分数。
- 把密钥写进仓库。
- 借合并重写 README 实验节或把 main SHA 改成执行分支 SHA（除非维护者另做文档同步 PR）。
- 前端大改版或新开 SmartMem 专用屏。

## 10. 给执行代理的最短命令备忘

```text
# 基线必须是当时的 origin/main，而不是本文件写成时的缓存
git fetch origin main webui-phase10 feat/smartmem-data-knowledge
git rev-parse origin/main origin/webui-phase10 origin/feat/smartmem-data-knowledge

# 先记测试条数，再按 §4–§6 有选择地带入，不要裸 merge tip

python scripts/check_web_contracts.py
python -m pytest tests/
python -m pytest tests/test_factor_library_hdd_v3.py tests/test_factor_library_hdd_v4.py
# 复核四个 hdd_v*.jsonl 的 SHA256（§8）
```

做完后在执行 PR 里对照 §8 逐条打勾，并写明实际采用了例外 A / 例外 B 的哪些文件。
