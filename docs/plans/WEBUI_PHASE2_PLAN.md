# FaultEvolve WebUI 阶段 2 实施计划（只读 Web API 与回放模式）

对应任务书：`docs/plans/FRONTEND_IMPLEMENTATION_TODO.md` §5（TODO 2.1–2.6）与 §14 文件清单。

**状态：已确认（D1–D6 全部按建议采用），实施中。**

本计划遵守的硬约束：

- 不写假实现。做不到的能力一律 `not_supported`。
- 一切文件访问先 `resolve()` 再比对允许根；`node_id` / `artifact_id` / `run_id` 只接受白名单字符。
- 不读取 holdout；不泄露密钥、绝对路径、序列号。
- 不在后端"补算"正式分数，分数一律从评测产物读回。

---

## 0. 已探明的事实（已实测，不是推测）

### 0.1 回放数据源实况（=`tests/fixtures/runs/hdd_mvp_demo_7510f100/`）

| 文件 | 实况 |
|---|---|
| `run_summary.json` | 116 字段。`experiment_id=7510f100`、`status=finished`、`iterations_done=5`、`best_node_id=62d6cf09`、`best_score=22.807355886970594`、`initial_score` 同值、`improvement=0.0`、`stop_reason=max_iterations`、`total_tokens=3050` |
| `tree.json` | **6 节点 / 5 边**。节点字段仅 `id/branch_id/depth/operator/score/status/hypothesis_status/intent/visit_count/adopted_cards`；边**只有** `source/target` |
| `events.jsonl` | **19 行**，`id` 1..19 **连续**；7 种类型：`smoke_passed`×5、`hypothesis_refuted`×5、`iteration_complete`×5、`init_evaluated`、`smoke_data_built`、`smoke_fix_success`、`run_finished`。**没有** `node_created` / `node_status_changed` / `best_node_changed` |
| `programs/*.py` | 6 个文件，与 6 个节点 id **一一对应** |
| `logs/` | **空**（只有 `.gitkeep`） |
| `discovery/controls.json`、`phenomena.json`、`preregistration.json` | 各 **2 B**（内容 `[]`） |
| `discovery/discovered_cards.snapshot.jsonl` | **0 B** |
| `reports/` | **不存在**（引擎的 `fe report` 只打到 stdout，从不落盘） |

### 0.2 fixture 数据库实况（以 `mode=ro` 只读探明，探测后目录无新增文件）

20 张表。

**有数据**：`experiment` 1、`node` 6、`event` 21、`llm_call` 10、`card_stats` 2、
`branch_offered_cards` 20、`branch_refuted_cards` 2、`node_adopted_cards` 4、`operator_stats` 1。

**全空（10 张）**：`claim`、`claim_test`、`certificate`、`discovered_card`、`insight`、
`match`、`mechanism`、`node_parents`、`test_result`、`theory`。

`journal_mode` 为 `delete`；只读连接未产生 `-wal`/`-shm`。

### 0.3 三个必须写进实现的事实（不写就会写错）

1. **`Store(db_path)` 一构造就写库**：`db_path.parent.mkdir(parents=True, exist_ok=True)`
   → `executescript(DDL)` → **`PRAGMA journal_mode=WAL`**。
   ⇒ 回放**不得使用 `Store`**。必须自建 `sqlite3.connect("file:...?mode=ro", uri=True)`。
   否则会改写已提交的 fixture，并在仓库里留下 `fe.db-wal` / `fe.db-shm` 垃圾文件。
   （旁证：真实运行目录 `benchmark/hdd_mvp/.fe/runs/7510f100/` 当前就带着这两个 sidecar。）

2. **`events.jsonl` 与 DB `event` 表内容不一致**：jsonl **19** 条 vs DB **21** 条。
   DB 多出 `discovery_round_started`×1、`discovery_round_finished`×1。
   且 `run_summary.discovery_rounds = 0`，与 DB 里存在 discovery 事件**自相矛盾**。

3. **`node_parents` 表为空** ⇒ 父子关系**唯一**来源是 `tree.json` 的 `edges`。

### 0.4 本阶段要实现的接口（权威来源：TODO §5，非 PRD §16.1 的能力描述）

```
GET /api/runs
GET /api/runs/{run_id}
GET /api/runs/{run_id}/tree
GET /api/runs/{run_id}/nodes/{node_id}
GET /api/runs/{run_id}/events?after_id=&limit=
GET /api/runs/{run_id}/scores
GET /api/runs/{run_id}/leaderboard
GET /api/runs/{run_id}/knowledge/cards
GET /api/runs/{run_id}/insights
GET /api/runs/{run_id}/discovery
GET /api/runs/{run_id}/artifacts
GET /api/runs/{run_id}/artifacts/{artifact_id}
GET /api/runs/{run_id}/reports/manifest
```

`/api/health`、`/api/meta` 阶段 1 已交付，本阶段只回归、不改语义。
**SSE 不在本阶段**（属阶段 8，TODO §11 TODO 8.2）。

---

## 1. 阶段划分（4 步，每步独立可验，各自提交）

### 2A 只读数据层（无 HTTP 依赖，纯函数级可测）

新增：

| 文件 | 职责 |
|---|---|
| `src/faultevolve/webapi/paths.py` | id 白名单校验（`^[A-Za-z0-9_-]{1,64}$`）+ 安全拼接。拒绝含 `/`、`\`、`..`、`:`、`%`、NUL 的 id；拼接后必须落在已 `resolve()` 且通过 `ensure_allowed()` 的根之内 |
| `src/faultevolve/webapi/sqlite_ro.py` | 只读 SQLite 连接（`mode=ro` + `uri=True`），**绝不** `mkdir`、建表、改 `journal_mode`。库不存在 → `run.unreadable` |
| `src/faultevolve/webapi/sanitization.py` | 文本脱敏：绝对路径（Windows/UNC/POSIX）、`sk-` 形态密钥、长数字串（序列号）；供日志与事件 payload 复用 |
| `src/faultevolve/webapi/replay_service.py` | 回放数据读取。**只读**以下文件：`run_summary.json`、`tree.json`、`events.jsonl`、`programs/{node_id}.py`、`logs/{node_id}.log`、`discovery/*`；DB 只走 `sqlite_ro` |

完成判据：

- 给定 fixture 根，`replay_service` 能读出 6 节点 / 5 边 / 19 事件，且**整个目录 mtime 与文件清单不变**（这条要写成测试）。
- 目录名与 `experiment_id` **不同**时仍能正确工作（fixture 正是这种：`hdd_mvp_demo_7510f100` vs `7510f100`）。

### 2B 运行发现与详情

新增 `src/faultevolve/webapi/routes/runs.py`；`app.py` 挂载。

行为（TODO 2.4）：

1. 只扫描 `runs_root` / `artifacts_root` 的**下一层**子目录，不递归、不接受用户传入的任意路径。
2. `run_summary.json` 存在 → 读它填 `RunSummaryResponse`。
3. 只有 `fe.db` → `RunDataState.LIVE`（incomplete）。
4. 两者都坏 → `RunDataState.UNREADABLE` + 诊断字段；**列表接口不因此整体失败**。

完成判据：列表返回 1 条（fixture），`/api/runs/hdd_mvp_demo_7510f100` 返回完整详情（116 字段映射到 DTO）；
`/api/runs/..%2f..%2fetc` 一律 404 + `run.not_found`。

### 2C 树 / 节点 / 事件 / 分数 / 排行榜

新增 `routes/tree.py`、`routes/events.py`。

- `parent_id` **由 `tree.json` 的 `edges` 反推**（单入边取唯一父；多条入边取第一条并记 `ContractWarning`）。
- `second_parent_ids` / `repair_parent_id` **留空/None**：无数据源，不编造。
- 节点详情来源优先级（TODO 2.5）：`tree.json` → `programs/{id}.py` → `logs/{id}.log`（脱敏）→ DB 补充。
  明确**不从 `events.jsonl` 反推覆盖节点最终状态**。
- `/events?after_id=&limit=`：分页基于 `events.jsonl` 的 `id`；`after_id` 缺失时返回首批。
- `/scores`：来自 `run_summary.json` 的 `best_score`/`initial_score` 与 `events.jsonl` 的 `init_evaluated`/`iteration_complete`。
  **分数为空时用 `None`，不用 0**（DTO 已按 `float | None` 定义）。
- `/leaderboard`：按 `tree.json` 的 `score` 倒序；`score` 为 `None` 的节点排在末尾并标注未评分。

完成判据：6 节点全可访问、5 条边方向正确、`after_id=5&limit=3` 返回 id 6..8、越界 node_id 返回 `node.not_found`。

### 2D 知识 / 发现 / 制品 / 报告

新增 `routes/knowledge.py`、`routes/artifacts.py`。

- `/knowledge/cards`：`card_stats` + `branch_offered_cards`/`branch_refuted_cards`/`node_adopted_cards`（DB）。
  fixture 下返回 **18 张卡**：17 张在 `branch_offered_cards` 里被"提供过"，加上 FE01（被采用/被否证但**未**进提供表）。
  其中 FE01、M01 各 `adopted=2`、`refuted=2`、`adopted_iterations=[1]`；其余卡的 `adopted/refuted` 为 `null`（不是 0）。
  卡片正文（`claim`/`source_kind`）**不编造**：运行目录只记录"用过哪些卡"，正文在任务知识库里，故一律 `null`。
- `/insights`：`insight` 表为空 ⇒ `available: true` + **空数组**（不是 `available: false`）。
- `/discovery`：读 `discovery/*`。三个 `{}` + 一个 0 B 文件 ⇒ `available: true`、条目为空。
  并**上报** `0.3-2` 的不一致（DB 有 2 条 discovery 事件但 `discovery_rounds=0`）。
- `/artifacts`：服务端扫描 **允许目录内**的已知制品位置生成 `artifact_id`（**不是路径**）。
- `/artifacts/{artifact_id}`：按 id 查表 → 只读转 `FileResponse`；未登记 id → `artifact.missing`；
  数据库/日志类制品标 `downloadable: false`。
- `/reports/manifest`：只列**已存在**的报告文件；不存在 → `available: false`。
  **不实现"生成报告"**（PRD §13.5，属阶段 9）。

完成判据：fixture 下 17+1 张卡、制品清单非空且含 6 个程序文件、未登记 artifact_id → 404；
下载响应不得出现绝对路径（用 `Content-Disposition` 只带 basename）。

---

## 2. 需要你拍板的 6 个决策

| # | 决策 | 我的建议 | 理由 |
|---|---|---|---|
| **D1** | `run_id` 取什么 | **取 artifacts 根下的目录名**，响应里另给 `experiment_id` | 与 TODO 2.4「只扫描下一层运行目录」一致；fixture 里两者不同（`hdd_mvp_demo_7510f100` vs `7510f100`），正好把"这是两个概念"测出来。生产环境下二者相等（`.fe/runs/{experiment_id}`） |
| **D2** | `events.jsonl` 与 DB `event` 不一致怎么办 | **以 `events.jsonl` 为唯一来源**（TODO 2.3），**不合并** DB 那 2 条；差异用 `ContractWarning` 显式上报 | 合并会造出"来源混杂却看起来完整"的假象。PRD §2.3 是「真实优先于完整」 |
| **D3** | 父子关系从哪来 | `parent_id` **从 `edges` 反推**；`second_parent_ids`/`repair_parent_id` **留空** | `node_parents` 表为空；编造 crossover/repair 父节点就是假数据。前端据空值显示"未记录" |
| **D4** | 缺失数据的三种语义 | 文件**不存在** → `available: false`；文件存在但**为空** → `available: true` + 空数组；JSON **损坏** → HTTP 500 + `artifact.invalid_json` | 三者混用会让前端无法区分"没有数据"与"数据坏了"。fixture 的 discovery 恰好是第二种，`logs/` 是第一种 |
| **D5** | 下载与报告范围 | P0 只开放**允许目录内、已登记**的制品；**不做报告生成**（阶段 9）。`reports/manifest` 只列已存在文件 | 不写假实现；PRD §13.4/§13.5 与 §17.2 把高风险动作留给受控入口 |
| **D6** | `fe web serve` CLI 是否本阶段做 | **不做**，先用 uvicorn 手工起服务验证 | TODO §14 把它列在"Python 修改"，但阶段 2 正文只讲 API；放进本阶段属范围蔓延，且不影响任何验收项。留给阶段 9 |

### 2.1 决议结果（2026-10-02）

- **D1–D6 全部按上表建议采用**，无修改。
- 追加一条处置原则：**本阶段内原标为「未实现」的项，先尝试真正实现；单项投入超过
  30 分钟仍做不出来，才降级为 `not_supported`，并在响应与文档里写明具体原因。**

按此原则要尝试的项与最终处置：

| 项 | 初判 | 最终处置 |
|---|---|---|
| 单父节点**代码 diff** | **可做** | **已交付**：`NodeDetailResponse` 新增 `code_diff` / `code_diff_truncated`，用 `difflib.unified_diff` 对比 `edges` 给的唯一父节点；父节点缺失时 `null` + 告警，绝不返回空串（空串会被读成"完全相同"） |
| **日志脱敏端到端**验证 | **可做** | **已交付**：`test_a_log_with_secrets_is_redacted_before_it_leaves` 在 `mutable_run` 里现造一份含绝对路径、`sk-` 假密钥、16 位序列号的 `logs/{node}.log`，真实走完 读→脱敏→序列化 |
| **最佳节点序列** | 可做（须标注派生） | **本阶段不做**（见 §5.3）：它在冻结的 13 端点契约里没有归属，而同样的信息已由 `/scores`（分数时间线）与 `/tree`（`is_best`）给出。新造接口属于范围蔓延，不是能力不足 |
| 引擎 9 状态生命周期（暂停/恢复/取消） | **不可做** | `not_supported`：属阶段 7 的进程控制；在 API 层伪造状态机就是假实现 |
| 事件类型补齐到 PRD §16.2 的 12 类 | **部分可做** | `not_supported`：引擎从未 emit 的类型不得凭空生成 |
| SSE | 不属本阶段 | 阶段 8 |

---

## 3. 与任务书 / 文档的分歧（显式标注）

| 分歧点 | 文档说法 | 我的处理与理由 |
|---|---|---|
| 实时通道 | PRD §16.2 写 **WebSocket** | 按已定决议统一为 **SSE**（`catalog.STREAM_TRANSPORT = "sse"`），且属阶段 8；本阶段不实现 |
| 运行状态 | PRD §9.2 列 **9 个**生命周期状态 | 引擎实际只产出 4 个（`created/running/finished/crashed`）。另外 7 个一律 `not_supported`，**不伪造**。阶段 1 已用测试钉住 |
| 事件种类 | PRD §16.2 要求至少 12 类 | 本次 run 只产生 7 类，且**没有** `node_created` / `node_status_changed` / `best_node_changed`。回放只能给引擎真emit 过的事件，前端需要能显示"该类型无事件" |
| 节点代码 | PRD §10.3 提到"父子 diff" | `tree.json` 只有单父边、`node_parents` 空 ⇒ 多父合并 diff 仍不做；**单父 diff 本阶段已交付**（实现在 `NodeDetailResponse.code_diff`，见 §5.2） |
| `logs/` | TODO 2.3 要求日志脱敏 | fixture 的 `logs/` 为空 ⇒ 端到端验证改为**现造日志文件**（`mutable_run`），已交付，不再是"只能靠单测覆盖" |

---

## 4. 测试清单（8 个文件，与 TODO §5 一致）

| 文件 | 覆盖 |
|---|---|
| `tests/webapi/test_health.py` | `/api/health` 不泄露路径/密钥；`/api/meta` 的 `available=False` 不被写成 True |
| `tests/webapi/test_replay_runs.py` | 正常回放 1 条；只扫一层不递归；只有 fe.db → LIVE；两者皆坏 → UNREADABLE |
| `tests/webapi/test_replay_tree.py` | 6 节点/5 边；`parent_id` 反推正确；`second_parent_ids`/`repair_parent_id` 为空；`score=None` 不被写成 0 |
| `tests/webapi/test_replay_events.py` | 19 条；`after_id`/`limit` 分页；**部分行损坏**时跳过坏行并告警；摘要计数与事件数不一致时不崩 |
| `tests/webapi/test_replay_discovery.py` | `[]` 与 0 B 文件 ⇒ `state: available` + 空列表；删目录 ⇒ `state: missing`；JSON 损坏 ⇒ 500 `artifact.invalid_json`；DB/jsonl 不一致上报告警；insight 空表 ⇒ `available: true` |
| `tests/webapi/test_artifact_download.py` | 已登记 id 下载成功且不含绝对路径；未登记 id → `artifact.missing`；不可下载制品 → `artifact.not_downloadable` |
| `tests/webapi/test_path_security.py` | `node_id`/`artifact_id`/`run_id` 路径穿越（`..`、`%2e%2e`、`/`、`C:`、NUL）全部拒绝；holdout 目录不可达 |
| `tests/webapi/test_sanitization.py` | 绝对路径、`sk-`密钥、长序列号被脱敏；**回放只读性测试**：读完 fixture 后目录 mtime 与文件清单不变 |

每个文件都要「正常路径 + 至少一个失败/边界」（TODO §15 第 2、3 条）。

---

## 5. 验收命令与预期

```bash
cd <repo>

# 1. 本阶段新增测试
.venv/Scripts/python.exe -m pytest tests/webapi/ -q -p no:cacheprovider
#     预期：阶段 1 的 31 + 阶段 2 新增（约 8 文件）全绿

# 2. 契约漂移门禁（新增 endpoint 后必须重新导出）
.venv/Scripts/python.exe scripts/export_web_contracts.py
.venv/Scripts/python.exe scripts/check_web_contracts.py     # 预期 exit 0
cd web && "C:/Users/A/.workbuddy/binaries/node/versions/22.22.2-3/pnpm.CMD" generate:api
#     预期：TS 客户端出现 runs/tree/events/... 的 SDK 函数

# 3. 全量回归（后台跑，约 12–13 分钟）
.venv/Scripts/python.exe -m pytest tests/ -q --tb=no -p no:cacheprovider > out.txt 2>&1
#     预期：555+ 收集 / 通过数 = 547 + 新增 / 失败仍为 8（同一批 CRLF 假红），0 新增失败

# 4. 手工冒烟（可选）
.venv/Scripts/python.exe -c "import uvicorn, faultevolve.webapi.app as a; ..."
#     指向 fixture 根，curl /api/runs 应看到 1 条
```

---

## 6. 明确不做的事（防止范围蔓延）

- **不做** SSE / 实时推送（阶段 8）。
- **不做** 运行创建、暂停、恢复、取消（阶段 7；PRD §7.4 明确 P0 不支持暂停/恢复）。
- **不做** 报告生成与导出（阶段 9）。
- 父子 diff：**改为尝试实现单父 diff**（见 §2.1）；多父（crossover）diff 仍无数据源，报 `not_supported`。
- **不做** 任何写操作：不改 `Store`、不改 `config.py`、不新增 DDL。
- **不动** `.gitattributes`，不改既有测试，不试图"修好"那 8 个 CRLF 假红（已定规则）。

---

## 7. 已知风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| fixture 的 `logs/` 为空、discovery 为空、11 张表全空 | 阶段 6/9 的端到端能力**无法用本 fixture 验证** | 阶段 2 先用空数据把"可用但为空"的语义测准；需要真实非空数据时另造 `--mock` fixture（阶段 0 已记录此局限） |
| 回放读取若误用 `Store` 会写坏 fixture | 仓库出现 `-wal`/`-shm`，fixture 被改写 | `replay_service` 只用 `sqlite_ro`；用「读完目录不变」的测试钉死 |
| 新增 endpoint 后忘了重新导出契约 | 漂移门禁红 | 每步提交前都跑 `check_web_contracts.py` |
| 本机带斜杠分支名不可用 | ref 会被销毁 | 本地分支固定用 `webui-p0`；每次 commit 后核对 `git rev-parse HEAD` |

---

## 8. 实施结果与偏差（2026-10-02 收尾记录）

### 8.1 交付物

新增/修改的源码（全部通过 `python -m pytest tests/webapi/ -q`）：

| 文件 | 内容 |
|---|---|
| `webapi/paths.py` | id 白名单 + 两闸安全拼接；`resolve_run_child` **显式拒绝** `.`/`..`（`Path("..").name` 跨 Python 版本返回值不一致，不能靠推断） |
| `webapi/sqlite_ro.py` | `mode=ro` 连接，绝不建库/建表/改 journal |
| `webapi/sanitization.py` | 绝对路径 / `sk-` 密钥 / 16+ 位序列号脱敏；`sanitize_value` 递归（含键） |
| `webapi/replay_service.py` | 全部 13 个端点的数据层 + 知识/洞见/发现/制品/报告 |
| `webapi/replay_groups.py` | 116 字段摘要 → 7 个分组 DTO |
| `webapi/routes/{runs,tree,events,knowledge,artifacts}.py` | 5 个路由组，`register_all` 统一挂载 |
| `webapi/contracts.py` | 新增 `InsightResponse`/`InsightsResponse`/`ReportFileResponse`/`ReportManifestResponse`；`NodeDetailResponse` 增 `code_diff`/`code_diff_truncated` |
| `webapi/errors.py` | `WebApiError` 体系（400/403/404/500/501 + 稳定 `error_code`） |

测试：`tests/webapi/` 共 **8 个文件、120 项全绿**（阶段 1 的 31 项含在内）。

### 8.2 相对契约的三处**有意修正**（都已重新导出并生成 TS）

| 契约项 | 原定义 | 改为 | 原因 |
|---|---|---|---|
| `DiscoveryResponse.controls` / `.preregistration` | `dict` | `list[dict]` | 引擎 `pipeline.write_artifacts` 写的是 `json.dump(self.controls_history)`，而 `controls_history/preregistrations/phenomena` 在 `pipeline.__init__` 里都是 `list`。原契约与实际产物不符，属**契约错误**而非数据缺失 |
| `KnowledgeCardResponse.claim` / `.source_kind` | 必填 `str` | 可选 `str \| None` | 运行目录**不含**卡片正文（正文在任务 `knowledge/cards.jsonl`，且 `run_summary` 无 `task_id`，无法可靠回连）。填必填字段就只能编造，违反硬约束 |
| `NodeDetailResponse` | 无 diff | 增 `code_diff` / `code_diff_truncated` | 单父 diff 可诚实计算，见 §2.1 |

### 8.3 与初判的偏差

- `/knowledge/cards` 实际返回 **18 张卡**（计划里写 2 张是早期误判：当时只看了 `card_stats`，漏了 `branch_offered_cards` 的 17 张）。18 张是"运行中真正被提供过的卡"集合，更完整也更诚实。
- `/artifacts` 实际返回 **14 条**：`run_summary`、`tree`、`events`、`database`、6 个 `program-*`、4 个 `discovery-*`。其中 `database` 与 `log-*` 一律 `downloadable: false`。
- `/reports/manifest` 在 fixture 下恒为 `available: false`：引擎 `fe report` **只写到 stdout、从不落盘**，所以"已存在的报告文件"这一集合天然为空。测里另造了 `reports/run_report.md` 验证非空路径。

### 8.4 本阶段确认**不做**的（不是做不出来，是不该做）

- **最佳节点序列**：信息已由 `/scores`（时间线）+ `/tree`（`is_best`）给出；新造一个契约外接口属范围蔓延，故记为 `not_supported`。
- 引擎 9 状态生命周期、PRD 的 12 类事件补齐：引擎从未 emit 的状态/事件不生成（阶段 7）。
- SSE（阶段 8）、报告生成（阶段 9）、`fe web serve` CLI（阶段 9）。

