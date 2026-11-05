# FaultEvolve WebUI 代码实现 TODO（面向实现能力有限的 AI）

> 文档版本：v1.0  
> 日期：2026-10-01  
> 对应产品文档：`docs/design/05-前端PRD.md`  
> 当前范围：纯云端模式 P0  
> 目标读者：接手实现的 AI 编程助手或工程师  
> 执行原则：严格按阶段顺序完成；每一阶段必须先通过测试，再进入下一阶段

---

## 0. 开始前必须知道的事实

### 0.1 当前仓库真实状态

当前 `main` 已有：

- Python 3.12 FaultEvolve 引擎。
- Typer CLI：`fe evolve local`、`fe discover`、`fe report`、`fe doctor` 等。
- Pydantic 配置和领域模型。
- SQLite `fe.db`，WAL 模式。
- 任务适配器：`hdd`、`famou`、`backblaze`、`smartmem`、`alibaba_ssd`。
- 运行结束制品：`run_summary.json`、`tree.json`、`events.jsonl`、`programs/`、`logs/`、`discovery/`。
- Qwen DashScope 调用：生成模型默认 `qwen3-coder-plus`，推理模型默认 `qwen3-max`。
- 进化、知识注入、反思、repair、噪声判断、Jev、discovery、tournament 等能力。
- 完整 Python 测试集。

当前 `main` 没有：

- 正式 Web 前端工程。
- 正式 REST API。
- WebSocket/SSE 实时推送服务。
- 服务器配置管理。
- 浏览器登录或多用户系统。
- 混合模式的本地 Worker 协议实现。

不要把设计文档中的 API 当作已实现代码。

### 0.2 禁止事项

实现期间绝对禁止：

- 修改 `benchmark/hdd_mvp/evaluator.py`、`init.py`、`problem.md`、`prompt.md`。
- 读取、打印、上传或通过 API 暴露 `benchmark/hdd_mvp/data/holdout*`。
- 在浏览器、配置文件、测试快照或日志中写入真实密钥。
- 让 Qwen、Jev、前端或 Web API 生成节点分数。
- 前端直接打开 SQLite 文件。
- 前端重新计算 ROS。
- 为了页面好看补齐缺失事件、缺失轮次或缺失指标。
- 在 P0 实现混合模式或纯本地模式的假逻辑。
- 在侧栏增加四个模块之外的入口。

### 0.3 唯一评分链

```text
候选代码
  → TaskAdapter.evaluate(...)
  → 当前任务 evaluator
  → EvalResult / EvaluationResult
  → Store 写入节点证据
  → Web API 只读返回
  → 前端只展示
```

任何偏离此链路的实现都不合格。

---

## 1. 总体技术方案

### 1.1 推荐结构

```text
.
├── src/faultevolve/
│   ├── webapi/                    # 新增：薄 FastAPI 控制与读取层
│   │   ├── __init__.py
│   │   ├── app.py                 # create_app
│   │   ├── auth.py                # 单用户 API token，可选
│   │   ├── contracts.py           # 对外 DTO，禁止直接暴露内部对象
│   │   ├── errors.py              # 稳定错误码
│   │   ├── settings.py            # Web 服务配置
│   │   ├── paths.py               # 路径白名单与解析
│   │   ├── task_service.py        # 任务目录与适配器检查
│   │   ├── run_service.py         # 创建/读取/控制运行
│   │   ├── process_manager.py     # fe 子进程管理
│   │   ├── execution_backend.py   # 同机/SSH 云端执行抽象
│   │   ├── replay_service.py      # 制品回放
│   │   ├── live_service.py        # 运行中读取 fe.db
│   │   ├── server_profiles.py     # 云端服务器/环境配置
│   │   ├── sanitization.py        # 日志、路径、错误脱敏
│   │   └── routes/
│   │       ├── meta.py
│   │       ├── tasks.py
│   │       ├── servers.py
│   │       ├── runs.py
│   │       ├── tree.py
│   │       ├── knowledge.py
│   │       └── reports.py
│   └── ...                        # 现有引擎代码，不移动
├── web/                            # 新增：React 19 独立 WebUI
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html
│   ├── openapi/
│   │   └── faultevolve.openapi.json
│   └── src/
│       ├── app/
│       ├── routes/
│       ├── components/
│       ├── features/
│       ├── generated/api/
│       ├── stores/
│       ├── lib/
│       └── test/
├── scripts/
│   ├── export_web_contracts.py     # 从 Python 源生成契约
│   └── check_web_contracts.py      # CI 漂移检查
└── tests/webapi/                   # 新增：Python Web API 测试
```

### 1.2 技术选择

后端：

- FastAPI。
- Pydantic v2。
- Uvicorn。
- 现有 `sqlite3` Store。
- `asyncio.create_subprocess_exec` 管理本机/同云服务器进程。
- `asyncssh` 管理另一台云服务器上的纯云端执行；凭据仅在服务端使用。
- P0 不引入 ORM，不复制一套业务数据库。
- 实时通道优先 SSE；只有确实需要双向通信时才用 WebSocket。

前端：

- React 19 + TypeScript + Vite。
- Tailwind CSS。
- TanStack Router。
- TanStack Query。
- Zustand，仅存 UI 状态，不复制服务端运行状态。
- Radix UI/shadcn 风格基础组件。
- React Flow 展示进化树。
- Monaco 或 Shiki 展示只读代码与 diff。
- Vitest + Testing Library。
- Playwright 做关键流程 E2E。

### 1.3 为什么不用两套后端

P0 不同时引入 NestJS 和 Python Sidecar。原因：

- 引擎、Store、Pydantic 模型都在 Python。
- 多一层 Node 后端会增加字段漂移、进程管理和错误转译。
- 比赛 MVP 更需要可追溯和稳定，而不是多服务扩展性。

Navivisor 只复用前端设计和组件实现思路，不复制 Codex、写作、投稿等业务。

---

## 2. 总执行顺序

必须严格按以下顺序：

1. 建立契约同步机制。
2. 建立只读回放 API。
3. 建立 Web 前端壳和四模块导航。
4. 完成总览只读 Demo。
5. 完成进化树和节点详情。
6. 完成知识发现与结果报告。
7. 增加运行创建和进程管理。
8. 增加实时事件。
9. 增加暂停、恢复、取消和异常恢复。
10. 完成安全、E2E、视觉和性能测试。

不要先做动画、主题或复杂表单，再补数据契约。

---

## 3. 阶段 0：基线与分支准备

### TODO 0.1：确认仓库基线

执行：

```bash
git status --short
git pull --ff-only origin main
python -m pytest tests/
```

通过条件：

- 工作树无未知改动。
- Python 测试全部通过或只出现已有、已记录的环境跳过。
- 不运行任何 holdout/test 最终裁决。

### TODO 0.2：创建实现分支

```bash
git switch -c feat/webui-p0
```

每个阶段单独提交。推荐提交顺序：

1. `feat(web-contract): add generated frontend contract`
2. `feat(webapi): add replay endpoints`
3. `feat(web): add four-module application shell`
4. `feat(web): add overview demo and task intake`
5. `feat(web): add evolution workbench`
6. `feat(web): add knowledge and report modules`
7. `feat(webapi): add run lifecycle management`
8. `test(web): add e2e and contract drift coverage`

---

## 4. 阶段 1：建立 main → 前端的自动同步能力

这是第一优先级。没有完成本阶段，不得开始手写前端类型。

### TODO 1.1：定义前端公共契约

新增 `src/faultevolve/webapi/contracts.py`。

只在这里定义对前端稳定的 DTO，至少包括：

- `MetaResponse`
- `HealthResponse`
- `DeploymentModeAvailability`
- `TaskSummaryResponse`
- `TaskDetailResponse`
- `TaskReadinessResponse`
- `ServerProfileRequest/Response`
- `ServerProbeResponse`
- `RunCreateRequest`
- `RunSummaryResponse`
- `RunControlRequest`
- `TreeResponse`
- `NodeDetailResponse`
- `EventResponse`
- `ScorePointResponse`
- `KnowledgeCardResponse`
- `DiscoveryResponse`
- `ArtifactResponse`
- `ApiErrorResponse`

规则：

- DTO 可以从内部 `Node`、`RunSummary`、`Event` 转换，但前端不得直接依赖内部模型。
- 所有 DTO 使用明确字段类型，不用无边界的 `dict[str, Any]`，仅事件 payload 等确实动态的字段例外。
- 可缺失数据用 `None`，不要用 0 代表“未记录”。
- 每个响应带 `contract_version` 或由 `/api/meta` 返回全局版本。

### TODO 1.2：生成配置 Schema

从 `EvolveConfig.model_json_schema()` 生成配置 Schema，不要在 TypeScript 中重复手写。

输出：

```text
web/openapi/evolve-config.schema.json
```

额外生成 UI 元数据：

```json
{
  "path": "budget.max_iterations",
  "group": "budget",
  "label_zh": "最大轮次",
  "advanced": false,
  "preset_editable": true
}
```

UI 元数据与业务默认值分开：

- 默认值和约束来自 Pydantic。
- 中文标签、分组、帮助文字来自专用 UI 元数据文件。

### TODO 1.3：生成枚举与目录

由 Python 源生成：

- NodeStatus。
- HypothesisStatus。
- OperatorType。
- 可用任务适配器别名。
- stub 数据集说明。
- RunSummary 字段目录。
- Store 支持的公共事件类型目录。

不要在前端硬编码算子数组：以后 main 新增算子时必须自动发现漂移。

### TODO 1.4：导出 OpenAPI

新增 `scripts/export_web_contracts.py`：

1. 导入 FastAPI `create_app()`。
2. 调用 `app.openapi()`。
3. 排序键并稳定输出 JSON。
4. 写入 `web/openapi/faultevolve.openapi.json`。
5. 写入 `web/openapi/evolve-config.schema.json`。
6. 写入 `web/openapi/engine-catalog.json`。

脚本不得启动服务器，不得访问数据，不得读取 holdout。

### TODO 1.5：生成 TypeScript 客户端

在 `web/package.json` 添加：

```json
{
  "scripts": {
    "generate:api": "openapi-ts",
    "sync:contracts": "python ../scripts/export_web_contracts.py && pnpm generate:api",
    "check:contracts": "python ../scripts/check_web_contracts.py"
  }
}
```

前端业务代码只能从 `web/src/generated/api/` 引用 API 类型。

禁止：

- 在组件中重新声明 `Node`、`RunSummary`。
- 使用 `as any` 绕过字段变化。
- 将 API 响应直接塞进 Zustand 再手工改形状。

### TODO 1.6：契约漂移 CI

新增 `scripts/check_web_contracts.py`：

1. 在临时目录重新生成全部契约。
2. 与仓库内已提交文件逐字节比较。
3. 不一致时列出变化文件。
4. 返回非零退出码，并提示运行 `pnpm --dir web sync:contracts`。

CI 必须执行：

```bash
python scripts/check_web_contracts.py
pnpm --dir web generate:api
pnpm --dir web build
```

这保证你修改 `main` 中的以下内容后，前端必须同步：

- `src/faultevolve/config.py`
- `src/faultevolve/common/schemas.py`
- `src/faultevolve/tasks/registry.py`
- Store 公共字段。
- 新增事件类型。
- discovery/report manifest。

### 阶段 1 测试

新增：

- `tests/webapi/test_contract_export.py`
- `tests/webapi/test_contract_stability.py`
- `tests/webapi/test_contract_no_secrets.py`
- `tests/webapi/test_engine_catalog.py`

至少测试：

1. OpenAPI 可序列化。
2. 重复生成结果完全相同。
3. Pydantic 新增字段时漂移检查失败。
4. `DASHSCOPE_API_KEY`、`MIYANG_API_KEY`、`FE_API_KEY` 的值不进入 schema。
5. 所有 OperatorType 都进入 engine catalog。
6. 所有 adapter alias 都进入 engine catalog。

验收命令：

```bash
python -m pytest tests/webapi/test_contract_*.py -q
python scripts/check_web_contracts.py
```

---

## 5. 阶段 2：只读 Web API 与回放模式

先完成只读回放，再做启动运行。

### TODO 2.1：FastAPI 应用工厂

新增 `src/faultevolve/webapi/app.py`：

```python
def create_app(settings: WebSettings | None = None) -> FastAPI:
    ...
```

要求：

- 测试可注入临时 runs/artifacts 目录。
- 不在 import 时启动后台线程。
- 不在 import 时读取环境密钥。
- 注册统一错误处理器。
- `/api/health` 不泄露路径和密钥。

### TODO 2.2：WebSettings

新增设置：

- `runs_root`
- `artifacts_root`
- `task_roots`
- `allowed_path_roots`
- `poll_interval_ms`
- `api_token_env`
- `enable_process_control`
- `demo_run_ids`
- `server_profile_store`
- `ssh_known_hosts`

路径必须先 `resolve()`，再验证位于允许根目录内。

### TODO 2.3：回放数据读取

`replay_service.py` 只读以下文件：

- `run_summary.json`
- `tree.json`
- `events.jsonl`
- `programs/*.py`
- `logs/*.log`
- `discovery/phenomena.json`
- `discovery/preregistration.json`
- `discovery/controls.json`
- `discovery/discovered_cards.snapshot.jsonl`
- 如果存在：mechanisms/certificates/tournament_results/theories。

读取规则：

- 文件不存在时返回 `available: false`，不要伪造空结果。
- JSON 损坏返回稳定错误码 `artifact.invalid_json`。
- 日志读取必须经过脱敏。
- 节点代码只能通过已知 node ID 访问，禁止任意路径参数。

### TODO 2.4：运行列表

实现：

```text
GET /api/runs
GET /api/runs/{run_id}
```

运行发现顺序：

1. 只扫描配置的 artifacts 根目录下一层运行目录。
2. 不递归扫描任意用户路径。
3. `run_summary.json` 存在则读取。
4. 只有 `fe.db` 时标记为 live/incomplete。
5. 两者都损坏时标记为 unreadable，并返回诊断信息。

### TODO 2.5：树、节点、事件、分数

实现：

```text
GET /api/runs/{run_id}/tree
GET /api/runs/{run_id}/nodes/{node_id}
GET /api/runs/{run_id}/events?after_id=&limit=
GET /api/runs/{run_id}/scores
GET /api/runs/{run_id}/leaderboard
```

节点详情来源优先级：

1. `tree.json` 节点结构。
2. `programs/{node_id}.py` 代码。
3. `logs/{node_id}.log` 脱敏错误。
4. `fe.db` 补充 insight、llm_call、card stats。

不要从 `events.jsonl` 反推并覆盖节点最终状态。

### TODO 2.6：知识与报告 API

实现：

```text
GET /api/runs/{run_id}/knowledge/cards
GET /api/runs/{run_id}/insights
GET /api/runs/{run_id}/discovery
GET /api/runs/{run_id}/artifacts
GET /api/runs/{run_id}/reports/manifest
GET /api/runs/{run_id}/artifacts/{artifact_id}
```

下载使用服务端生成的 artifact ID，不接受原始路径。

### 阶段 2 测试

新增：

- `tests/webapi/test_health.py`
- `tests/webapi/test_replay_runs.py`
- `tests/webapi/test_replay_tree.py`
- `tests/webapi/test_replay_events.py`
- `tests/webapi/test_replay_discovery.py`
- `tests/webapi/test_artifact_download.py`
- `tests/webapi/test_path_security.py`
- `tests/webapi/test_sanitization.py`

覆盖：

- 正常回放。
- 缺文件。
- 空文件。
- 损坏 JSON。
- 事件行部分损坏。
- 轮次摘要多于事件数。
- node ID 路径穿越。
- artifact ID 路径穿越。
- 绝对路径和序列号脱敏。
- API 不读取 holdout。

---

## 6. 阶段 3：前端工程壳

### TODO 3.1：初始化 `web/`

建立 React/Vite/TypeScript 工程。

只安装 P0 必需依赖。不要一次复制整个 Navivisor 仓库。

### TODO 3.2：只实现四个一级导航

左侧栏严格为：

1. 总览
2. 进化工作台
3. 知识发现
4. 结果与报告

测试必须断言只有四项。

设置、系统状态和帮助放在顶部栏：

- Qwen 状态徽章。
- 纯云端模式徽章。
- 云端执行器状态。
- 设置齿轮。
- 帮助按钮。

### TODO 3.3：路由

实现路由：

- `/`
- `/runs/new`
- `/runs/$runId`
- `/runs/$runId/knowledge`
- `/runs/$runId/results`
- `/compare`

树、时间轴、排行榜是工作台页内标签，不增加侧栏。

### TODO 3.4：API 客户端与 Query

- 使用生成客户端。
- 为 runs、tree、events、node、discovery、reports 定义稳定 query key。
- 服务端数据全部由 TanStack Query 管理。
- Zustand 只存：当前 run ID、选中节点、展开面板、主题和本地视图过滤器。

### TODO 3.5：统一错误与空状态

新增组件：

- `ApiErrorPanel`
- `EmptyState`
- `MissingArtifactNotice`
- `ConnectionBanner`
- `DemoDataBadge`

错误必须优先显示 `error_code` 对应中文文本。

### 阶段 3 测试

- 侧栏只有四项。
- 当前路由高亮正确。
- 设置抽屉不占侧栏。
- API 401/404/500 有明确反馈。
- 刷新深链接可恢复当前运行。
- 不存在 run 时不会无限 loading。

---

## 7. 阶段 4：总览与任务输入

### TODO 4.1：HDD Demo 卡

实现两个动作：

- `启动短流程`
- `打开完整回放`

Demo 信息从 API 任务目录读取，不在组件中硬编码 ROS 详情。

### TODO 4.2：任务输入表单

分为三个必填卡片：

1. 数据集。
2. evaluator。
3. 初始算法。

字段见 PRD 7.3。每张卡片独立验证，并显示：未填写、检查中、通过、警告、失败。

### TODO 4.3：服务器和目录

P0 必须实现至少一个真实可用的云端执行目标。支持两种 transport，但都属于“纯云端”：

- `local_cloud`：Web API 与 FaultEvolve 在同一台云服务器。
- `ssh_cloud`：Web API 通过 SSH 连接另一台云服务器运行 FaultEvolve。

界面展示：

- host/port/user。
- repo/data/runs/artifacts/logs 目录。
- 测试连接。
- 测试目录。

服务端实现 `ExecutionBackend` 协议：

```python
class ExecutionBackend(Protocol):
    async def probe(self) -> ServerProbe: ...
    async def check_path(self, path: str) -> PathProbe: ...
    async def start_run(self, spec: RunLaunchSpec) -> ProcessHandle: ...
    async def poll(self, handle: ProcessHandle) -> ProcessStatus: ...
    async def terminate(self, handle: ProcessHandle) -> None: ...
```

分别实现：

- `LocalCloudExecutionBackend`
- `SSHCloudExecutionBackend`

SSH 规则：

- 使用 `asyncssh`，不通过 `shell=True` 拼接命令。
- 默认校验 known_hosts；比赛临时环境如需首次信任，必须在服务端明确确认指纹。
- 私钥路径和密码不返回浏览器。
- 密码不得写入数据库；长期配置优先使用服务端私钥引用。
- 前端只保存 profile ID、显示名、host、port、user 和掩码状态。
- SSH 输出进入脱敏日志。
- 远程路径必须通过 SFTP/stat 检查，不用 `ls` 字符串拼接。

### TODO 4.4：环境配置

结构化字段：

- Conda 环境或 Python 路径。
- CPU。
- GPU 数量、型号和设备号。
- 内存。
- 并发和超时。
- 补充说明。

补充说明永远不能直接传给 shell。后端只存备注。

### TODO 4.5：知识注入

选项：

- 关闭。
- 使用默认知识包。
- 选择已有类别。
- 启用自动发现。
- 启用 tournament。

选项必须映射到真实 `KnowledgeConfig` 和 `DiscoveryConfig` 字段。

### TODO 4.6：三档预设

新增后端预设生成函数，前端不直接拼配置。

建议：

- `quick`
- `standard`
- `deep`

返回完整 `EvolveConfig` 和字段来源说明。用户修改后，前端只提交 patch，后端合并并再次校验。

### 阶段 4 测试

- Demo 可正确打开真实回放。
- evaluator 缺失时不能继续。
- init 缺失时不能继续。
- 数据目录不存在时不能继续。
- holdout 不被探测或列出。
- 自由文本不能变成命令参数。
- 三档预设生成合法 EvolveConfig。
- 修改高级配置后“已自定义”出现。
- 恢复默认后 patch 被清空。

---

## 8. 阶段 5：进化工作台

### TODO 5.1：树数据适配

将 API `TreeResponse` 转成 React Flow nodes/edges。

必须支持：

- 普通 parent edge。
- `node_parents` 中的 crossover 第二父边。
- repair_parent_id/repair 边。
- 最优路径。
- 节点状态。
- 假设状态。

转换函数必须是纯函数，并单独测试。

### TODO 5.2：树节点

展示：

- 短 ID。
- score 或“未评分”。
- Δ 或“未记录”。
- operator。
- status 图标和文字。
- 知识卡数量。

禁止用 `score || 0`；0 分和缺失必须不同。

### TODO 5.3：节点详情

标签：

- 概览。
- 指标。
- 代码差异。
- 知识与记忆。
- 事件与成本。

代码只读。diff 在浏览器计算显示可以，但不能修改运行制品。

### TODO 5.4：评价与噪声

展示：

- 父分数。
- 当前分数。
- delta_score。
- noise_delta。
- 是否超出噪声带。

判断优先使用后端提供的分类字段。若后端还没有，新增纯函数并在后端计算；不要让多个前端组件各自判断。

### TODO 5.5：反思与纠错

展示：

- design reflection。
- implementation reflection。
- hypothesis status。
- repair_count。
- repair_parent_id。
- error_class。
- repair_exhausted。

修复节点必须可追踪到失败节点。

### TODO 5.6：时间轴与事件

- 按事件原始顺序展示。
- `iteration_complete` 才形成一代。
- 缺失代不补齐。
- 事件与树节点双向定位。

### TODO 5.7：预算与算力

来源于 RunSummary 和 metering：

- total_tokens。
- generate/reflect/knowledge/repair/discovery/tournament/crossover tokens。
- wall/eval/smoke time。
- stage cap hits。
- CPU/GPU 运行状态来自服务器探测，不写入节点评分。

### 阶段 5 测试

单元测试：

- tree 转换。
- 第二父边。
- repair 边。
- 最优路径。
- 缺分数。
- 0 分。
- 噪声内上涨。
- 显著上涨。
- 显著下降。
- 节点筛选。
- 事件去重。

组件测试：

- 点击节点打开详情。
- 点击知识卡跳知识发现。
- 点击事件定位节点。
- 代码为只读。
- 缺指标显示“未记录”。
- Jev 不显示在 evaluator 分数区。

性能测试：

- 100 节点流畅缩放。
- 500 节点不冻结主线程超过 200ms。
- 1000 条事件使用虚拟列表。

---

## 9. 阶段 6：知识发现与结果报告

### TODO 6.1：知识卡

- 来源。
- claim。
- 适用条件。
- 提供/采纳/否证次数。
- 平均 delta。
- 采用代和节点。

本地信任/存疑/排除只是 UI 标记，必须显示“不影响运行”。

### TODO 6.2：现象

展示 phenomena 和 claim test：

- condition。
- feature。
- outcome。
- effect/CI。
- scope。
- falsifier。
- grade/status。
- sandbox error。

### TODO 6.3：机制辩论赛

UI 阶段：

1. 主张。
2. 对手机制。
3. 正反论点。
4. 预注册检验。
5. 数据裁决。
6. 证书/否证记忆。

必须把 Qwen 论点与数据裁决分区显示。

### TODO 6.4：结果页

展示：

- 初始/最佳/提升。
- 分项指标。
- Top-K。
- 运行波动和诚实提示。
- 数据边界审计。
- 制品下载。

所有数字直接来自 API DTO。

### 阶段 6 测试

- discovery disabled 空状态。
- claim sandbox failure。
- confirmed/refuted/undetermined 映射。
- tournament 未启用。
- manifest 字段缺失。
- score 差异落在波动区间时显示“未形成明确改进证据”。
- 多数据集不可比较字段显示 N/A。
- 报告下载 MIME 和文件名正确。
- 不允许下载 holdout 或任意路径。

---

## 10. 阶段 7：运行创建与进程管理

### TODO 7.1：不要直接拼 Shell 字符串

使用参数数组：

```python
await asyncio.create_subprocess_exec(
    python_executable,
    "-m", "faultevolve.cli",
    "evolve", "local",
    task_dir,
    "--iterations", str(iterations),
    ...,
)
```

禁止 `shell=True`。

SSH 后端也必须使用经过逐项引用/编码的参数协议。推荐在远端安装 FaultEvolve 后调用固定入口；不要接受用户提供任意启动命令。若 asyncssh 最终仍需命令字符串，必须由固定子命令和经过 `shlex.quote` 的单个参数构造，并为每个恶意输入编写测试。

### TODO 7.2：运行注册表

Web API 维护轻量运行注册信息：

- run_id。
- execution_backend。
- server_profile_id。
- pid。
- status。
- task_dir。
- db_dir。
- artifacts_dir。
- start command 的结构化参数，不含密钥。
- created_at。

建议写入独立 `web_runs.sqlite3`，不要改现有 `fe.db` DDL。

### TODO 7.3：启动

```text
POST /api/runs
```

流程：

1. 校验请求 DTO。
2. 解析并验证路径。
3. 生成 EvolveConfig 临时快照。
4. 运行 doctor/readiness。
5. 创建 run ID。
6. 根据 server profile 选择 local_cloud 或 ssh_cloud backend。
7. 启动本机或远程进程。
8. 记录进程句柄和状态；SSH 句柄不得只依赖本地 PID。
9. 返回 202。

### TODO 7.4：暂停/恢复/取消

P0 如果现有引擎不支持安全暂停：

- 不得伪造暂停。
- 先只实现取消和 resume_id 恢复。
- 页面将“暂停”标为未支持。

若要实现暂停，必须先在引擎增加明确安全点和持久状态，并添加 Python 单元测试，再开放 UI。

### TODO 7.5：进程恢复

Web 服务重启后：

- 检查注册表中的 PID 是否存活。
- 对存活运行恢复监控。
- 对死亡但未完成运行标记 interrupted。
- 允许使用已有 run ID 恢复。

### 阶段 7 测试

- 重复启动幂等性。
- 非法路径。
- shell 注入字符串。
- 环境不存在。
- Qwen Key 未配置。
- 子进程启动失败。
- SSH 主机指纹不匹配。
- SSH 认证失败。
- SSH 连接中断后状态恢复。
- 恶意 host/user/path/补充说明不能形成命令注入。
- 子进程崩溃仍写出已有制品。
- Web 服务重启后恢复监控。
- 取消保留已有制品。
- 不支持暂停时 API 返回稳定 409，而不是假成功。

---

## 11. 阶段 8：实时事件

### TODO 8.1：运行中读取 fe.db

运行结束前，`tree.json` 和 `events.jsonl` 可能尚未写出。实时数据读取 `fe.db`：

- `event` 按自增 ID 增量查询。
- `node` 获取节点快照。
- `experiment` 获取状态和最佳分数。
- `llm_call` 获取成本。

使用只读连接和 busy timeout，不能阻塞引擎写入。

### TODO 8.2：SSE

```text
GET /api/runs/{run_id}/stream?after_id=123
```

事件格式：

```text
id: 124
event: iteration_complete
data: {...sanitized payload...}
```

发送心跳，支持浏览器自动重连。

### TODO 8.3：完成后收敛

收到运行结束后：

1. 停止轮询 live DB。
2. 等待制品写出完成。
3. 重新读取稳定制品。
4. 发送 `snapshot_ready`。
5. 前端使所有相关 Query 失效并重新获取。

### 阶段 8 测试

- after_id 补拉。
- 重复事件去重。
- SSE 断线重连。
- SQLite busy。
- 运行结束切换快照。
- 同时观察两个运行不会串事件。
- payload 脱敏。

---

## 12. 阶段 9：Debug 流程与测试矩阵

测试不是最后补做，而是每个实现步骤的完成条件。

### 12.1 Python 回归

每个阶段执行：

```bash
python -m pytest tests/ -q
```

至少在合并前执行一次完整测试，不只运行新增测试。

### 12.2 前端单元与组件测试

```bash
pnpm --dir web test
pnpm --dir web lint
pnpm --dir web build
```

重点：

- 四模块导航。
- DTO 缺字段。
- 空状态和错误状态。
- 树转换。
- 噪声分类。
- 代码只读。
- 事件去重。
- 跨模块定位。

### 12.3 API 集成测试

使用临时目录和 toy task，不使用真实 holdout。

覆盖：

- 回放完整运行。
- 回放不完整运行。
- live DB。
- 运行创建。
- 崩溃和恢复。
- 下载和路径安全。
- 契约同步。

### 12.4 Playwright E2E

必须覆盖以下路径：

#### E2E-01：HDD Demo 回放

1. 打开总览。
2. 断言侧栏只有四项。
3. 点击 HDD Demo。
4. 打开完整回放。
5. 进入树。
6. 点击节点。
7. 查看代码 diff。
8. 进入知识发现。
9. 进入结果与报告。

#### E2E-02：自定义任务校验

1. 创建自定义任务。
2. 缺 evaluator 时不能继续。
3. 填写有效 toy evaluator/init。
4. 服务器检查通过。
5. 选择标准进化。
6. 启动 mock 运行。

#### E2E-03：实时运行

1. 启动 3 轮 mock。
2. 观察节点增加。
3. 断开 SSE。
4. 重连并补拉。
5. 完成后切换稳定快照。

#### E2E-04：错误恢复

1. 使用故意失败候选。
2. 查看失败原因。
3. 查看 repair 关联。
4. 刷新页面。
5. 状态保持一致。

#### E2E-05：安全

1. 尝试 `../` 路径。
2. 尝试下载 holdout。
3. 尝试脚本注入补充说明。
4. 断言全部被拒绝或仅按普通文本保存。

### 12.5 视觉回归

固定视口：

- 1440×900。
- 1920×1080。
- 1024×768。

截图：

- 总览。
- 进化树。
- 节点详情。
- 知识发现。
- 结果报告。
- 空状态。
- 错误状态。

暗色和亮色各一次。任何新导航项、溢出、截断或状态颜色退化都应阻止合并。

### 12.6 性能检查

- 首屏不加载全部节点代码。
- 节点详情按需请求代码。
- 事件列表虚拟化。
- 树布局放入 worker 或缓存，避免反复计算。
- API 对同一稳定制品使用 ETag。
- 500 节点树初次可交互目标小于 2 秒（开发机基准）。
- 1000 条事件滚动不明显掉帧。

### 12.7 Debug 顺序

发现问题时严格按顺序：

1. 记录复现步骤和 run ID。
2. 检查 API 原始响应。
3. 检查 DTO 转换。
4. 检查 Query 缓存与事件去重。
5. 检查组件显示。
6. 添加失败测试。
7. 修复最小根因。
8. 运行相关测试。
9. 运行完整回归。

禁止只在组件中加特殊判断掩盖后端契约问题。

---

## 13. main 更新后的同步工作流

用户要求主仓库代码修改后能同步前端设计和实现，本节为强制流程。

### 13.1 开发者修改 Python 后

运行：

```bash
python scripts/export_web_contracts.py
pnpm --dir web generate:api
pnpm --dir web test
pnpm --dir web build
python -m pytest tests/ -q
```

检查 Git diff：

- OpenAPI 是否变化。
- EvolveConfig schema 是否变化。
- engine catalog 是否变化。
- TypeScript 生成类型是否变化。
- Demo manifest 是否需要重建。

### 13.2 CI 自动检查

每次针对 `main` 的 PR 执行：

```bash
python scripts/check_web_contracts.py
python -m pytest tests/ -q
pnpm --dir web test
pnpm --dir web lint
pnpm --dir web build
pnpm --dir web test:e2e --project=chromium
```

### 13.3 哪些变更必须更新 PRD

以下变更必须同步检查 `docs/design/05-前端PRD.md`：

- 新增或删除一级产品能力。
- 新增部署模式。
- 改变评分来源或数据边界。
- 新增用户可控算子。
- 修改运行生命周期。
- 新增需要用户输入的任务工件。
- 修改知识发现的证据或裁决逻辑。

字段增加不一定修改 PRD，但必须更新契约和相应 UI。

### 13.4 契约兼容规则

- 新增可选字段：minor contract version。
- 新增必填字段：major contract version。
- 删除/重命名字段：major contract version，并提供迁移说明。
- 新事件类型：minor version，旧前端应显示通用事件而非崩溃。
- 枚举新增值：前端必须有未知值 fallback。

### 13.5 运行制品版本

新运行摘要中建议增加：

- `artifact_schema_version`
- `engine_version`
- `engine_commit`
- `contract_version`

读取旧制品时：

- 先识别版本。
- 通过 adapter 转为当前 DTO。
- 不修改旧制品原文件。
- 无法迁移的字段显示“当前版本未记录”。

---

## 14. 文件级实现清单

### Python 新增

- [ ] `src/faultevolve/webapi/__init__.py`
- [ ] `src/faultevolve/webapi/app.py`
- [ ] `src/faultevolve/webapi/contracts.py`
- [ ] `src/faultevolve/webapi/settings.py`
- [ ] `src/faultevolve/webapi/errors.py`
- [ ] `src/faultevolve/webapi/paths.py`
- [ ] `src/faultevolve/webapi/sanitization.py`
- [ ] `src/faultevolve/webapi/replay_service.py`
- [ ] `src/faultevolve/webapi/live_service.py`
- [ ] `src/faultevolve/webapi/task_service.py`
- [ ] `src/faultevolve/webapi/run_service.py`
- [ ] `src/faultevolve/webapi/process_manager.py`
- [ ] `src/faultevolve/webapi/execution_backend.py`
- [ ] `src/faultevolve/webapi/server_profiles.py`
- [ ] `src/faultevolve/webapi/routes/*.py`
- [ ] `scripts/export_web_contracts.py`
- [ ] `scripts/check_web_contracts.py`

### Python 修改

- [ ] `pyproject.toml`：增加 FastAPI/Uvicorn 和 web serve CLI。
- [ ] `src/faultevolve/cli.py`：增加 `fe web serve`，只负责启动 API/静态前端。
- [ ] 必要时为 Store 增加只读分页查询；不得破坏现有 API。

### 前端新增

- [ ] `web/package.json`
- [ ] `web/vite.config.ts`
- [ ] `web/src/app/*`
- [ ] `web/src/routes/*`
- [ ] `web/src/features/overview/*`
- [ ] `web/src/features/evolution/*`
- [ ] `web/src/features/knowledge/*`
- [ ] `web/src/features/results/*`
- [ ] `web/src/components/ui/*`
- [ ] `web/src/generated/api/*`
- [ ] `web/src/test/*`

### 测试新增

- [ ] `tests/webapi/test_contract_*.py`
- [ ] `tests/webapi/test_replay_*.py`
- [ ] `tests/webapi/test_live_*.py`
- [ ] `tests/webapi/test_run_*.py`
- [ ] `tests/webapi/test_path_security.py`
- [ ] `tests/webapi/test_sanitization.py`
- [ ] `web/src/**/*.test.ts(x)`
- [ ] `web/e2e/*.spec.ts`

---

## 15. 每个 TODO 的完成定义

一个 TODO 只有同时满足以下条件才算完成：

1. 代码已实现，不是空函数或假数据。
2. 有正常路径测试。
3. 有至少一个失败/边界测试。
4. 不读取 holdout。
5. 不泄露密钥和路径。
6. 不在前端重新计算正式分数。
7. 相关契约已重新生成。
8. Python 回归通过。
9. 前端 test/lint/build 通过。
10. 文档与实际行为一致。

如果某能力暂时做不到：

- 明确返回 `not_supported`。
- UI 禁用并解释原因。
- 不写假实现。

---

## 16. 最终交付验收命令

```bash
python scripts/check_web_contracts.py
python -m pytest tests/ -q
pnpm --dir web install --frozen-lockfile
pnpm --dir web generate:api
pnpm --dir web test
pnpm --dir web lint
pnpm --dir web build
pnpm --dir web test:e2e --project=chromium
```

人工验收：

- [ ] 左侧栏只有四个模块。
- [ ] HDD Demo 可回放。
- [ ] 自定义任务必须输入数据集/evaluator/init。
- [ ] 服务器、目录、Conda/GPU 检查真实有效。
- [ ] 进化树显示普通、crossover 和 repair 关系。
- [ ] evaluator 分数与 Qwen/Jev 判断严格分离。
- [ ] 噪声内上涨不标记为可信改进。
- [ ] 反思和纠错有证据链接。
- [ ] 知识辩论由数据裁决。
- [ ] 结果数字与制品一致。
- [ ] 契约漂移检查可以捕获 main 的模型变化。
- [ ] 没有 holdout、密钥、序列号或绝对路径泄露。

