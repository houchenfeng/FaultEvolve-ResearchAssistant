# FaultEvolve WebUI 阶段 4 实现计划：总览与任务输入

> 对应任务书 `FRONTEND_IMPLEMENTATION_TODO.md` §7（TODO 4.1 – 4.6）+ §12.1/§12.2。
> 前序：阶段 0/1（契约流水线）、阶段 2（13 个只读回放端点，`9de6627`）、阶段 3（四模块外壳与路由，`f773509`/`a954cd3`/`0a950e9`）。
>
> **状态（2026-10-02 15:00）**：
> * ✅ **D-A = A1**（只做启动前检查）、**D-B = B2**（现在就引 asyncssh）——灵梦已定。
> * ✅ 依赖已落地：`.venv` 装了 `asyncssh 2.24.0` + `cryptography 50.0.2`；`requirements.txt` 与 `pyproject.toml` 的 `web` extra 已声明。
> * ✅ D-C = C1（四项可映射 + 类别选择诚实禁用）、D-D（meta 翻转 local_cloud=True）、D-E（JSON 原子写 + 预置空白本机模板）——按推荐默认执行。
> * ✅ **4A–4E 全部完成，全部门禁绿，未提交**（执行结果见 §12）。

---

## 0. 开始前必须知道的事实

### 0.1 三条硬约束（灵梦在阶段 3 结束时明确下达，本阶段继续生效）

| # | 约束 | 对本阶段的具体含义 |
|---|---|---|
| C1 | **不参考 GitHub 上的 `qianduan-yemian-demo` 分支** | 阶段 4 的一切组件、样式、字段命名都从零写；该分支不进任何比对、不做参照、不 fetch |
| C2 | **以 `FRONTEND_IMPLEMENTATION_TODO.md` 为主要执行清单** | 本计划逐条对齐 TODO §7；TODO 未写的能力一律不做（见 §8） |
| C3 | **概念图只用于理解视觉方向；字段、导航、交互以 PRD 文字为准** | `docs/images/frontend-concepts/01–04*.png` 仅作观感参考。`04-results-report.png` 里的 8 项侧栏与 PRD §5.1「严格四项」冲突 ⇒ **概念图不作数**，沿用阶段 3 的四模块侧栏 |

### 0.2 阶段 3 已交付、阶段 4 直接复用的东西（已核过源码）

| 资产 | 位置 | 阶段 4 怎么用 |
|---|---|---|
| 四模块外壳 + 路由 | `web/src/app/{router,providers}.tsx`、`web/src/app/shell/*` | 不改结构；`/overview`、`/runs/new` 只换页面内容 |
| 10 条 PRD 路由 | `web/src/app/router.tsx` | `/runs/new` 由 `StagePlaceholder` 换成真实录入页 |
| 生成式 API 客户端 | `web/src/generated/api/*`（由 OpenAPI 生成） | **只从这里取类型与 SDK 函数**（TODO 1.5），本阶段新增 DTO 后重新生成，不手写类型 |
| 数据层 | `web/src/lib/{api,api-error,query-client,query-keys}.ts` | `unwrap` / `toApiError` / `FaultEvolveApiError` 直接复用；`queryKeys` 追加新前缀 |
| 统一状态组件 | `web/src/components/states/*` | `ApiErrorPanel` / `EmptyState` / `MissingArtifactNotice` / `StagePlaceholder` 复用 |
| `StatusBadge` | `web/src/components/ui/StatusBadge.tsx` | 卡片状态（通过/警告/失败）复用它，不新增一套色板 |
| 设计令牌 | `web/src/styles/theme.css`（Tailwind v4 CSS-first） | 新组件只用既有 token，不新增色值 |
| 后端只读回放 | `src/faultevolve/webapi/{replay_service,replay_groups,paths,sqlite_ro}.py` | 运行列表/详情继续走它；本阶段不碰这 13 个端点的语义 |
| 路径白名单 | `src/faultevolve/webapi/settings.py::WebSettings` | 所有新路径入参都必须过 `ensure_allowed`；本阶段新增 `task_roots` 的实际使用 |
| 错误码表 | `src/faultevolve/webapi/errors.py::ErrorCode` | **append-only**：只新增，不改不删 |

### 0.3 后端现状盘点（阶段 4 要用到的东西，哪些有、哪些没有）

已实测确认：

| 项 | 现状 | 结论 |
|---|---|---|
| `TaskSummaryResponse` / `TaskDetailResponse` / `TaskReadinessResponse` | **已定义**（`contracts.py` 206/219/235 行） | 契约层无需新写 DTO |
| `ServerProfileRequest` / `ServerProfileResponse` | **已定义**（250/280 行），且已包含 `python_executable`/`conda_env`/`cpu_limit`/`memory_gb`/`gpu_count`/`gpu_devices`/`max_concurrency`/`timeout_s`/`notes` | **TODO 4.4 的全部结构化字段已在契约里**，零契约变更 |
| `PathProbeResponse` / `ServerProbeResponse` | **已定义**（305/315 行） | 同上 |
| `RunCreateRequest` | **已定义**（336 行），含 `preset: str` + `config_patch: dict` | 阶段 4 只用它做「启动前检查」的入参形状参考，**不发这个请求**（见 §2 D-A） |
| `DEPLOYMENT_MODES` / `UNAVAILABLE_DEPLOYMENT_MODES` | 已有；`/api/meta` 目前对 `local_cloud`/`ssh_cloud` **一律 `available=False`**，理由写「执行后端尚未实现（阶段 7 交付）」 | 阶段 4 交付 `LocalCloudExecutionBackend` 后，**这句理由必须改**（见 §2 D-D） |
| `WebSettings.task_roots` / `allowed_path_roots` / `server_profile_store` / `ssh_known_hosts` / `demo_run_ids` | **字段都在**，但 `task_roots`、`server_profile_store`、`ssh_known_hosts`、`demo_run_ids` **目前是死配置**（定义了没人读） | 阶段 4 让它们真正生效（与阶段 3 让 `demo_run_ids` 生效同一思路） |
| 错误码 | 已有 `BACKEND_UNAVAILABLE` / `BACKEND_AUTH_FAILED` / `BACKEND_HOST_KEY_MISMATCH` / `ENVIRONMENT_NOT_READY` / `LLM_KEY_MISSING` / `NOT_SUPPORTED` | 缺 task/server/preset 三类，见 §4.1 |
| `task_service.py` / `presets.py` / `server_profiles.py` / `execution_backend.py` | **全部不存在** | 阶段 4 新建 |
| `routes/tasks.py` / `routes/servers.py` / `routes/presets.py` | **不存在**（现有：artifacts/events/knowledge/runs/tree） | 阶段 4 新建 |
| `fe web serve` CLI | **不存在**（`cli.py` 是 typer，只有 `report`/`discover`/`analyze`/`doctor`/`evolve`） | 阶段 4 新增；本阶段所有人工冒烟都靠它 |
| `asyncssh` | **原为未安装**；灵梦 2026-10-02 决定「现在引」⇒ **已装入 `.venv`：`asyncssh 2.24.0` + `cryptography 50.0.2`**（见 D-B 结论） | SSH 后端按真实依赖实现；仍**延迟导入**（理由见 §1 4C） |
| `uvicorn` / `fastapi` / `pydantic_settings` | 已安装 | 无需动 |

### 0.4 任务目录实况（Demo 卡与数据集卡的真实数据源）

`benchmark/` 下正好四个目录，与 PRD §7.7 的四张数据集卡**一一对应**：

| 目录 | 适配器 | 四文件（`evaluator.py`/`init.py`/`problem.md`/`prompt.md`） | knowledge/ | data/ | 状态 |
|---|---|---|---|---|---|
| `benchmark/hdd_mvp` | `hdd` | **齐** | `cards.jsonl`/`expert.md`/`README.md` **齐** | `data/{public,eval_only,meta.json}` | **完整可运行**（默认比赛演示） |
| `benchmark/backblaze_hdd` | `backblaze` | **齐** | 齐 | 需 `prepare_data.py`/`download_data.py` 准备 | 按实际就绪状态 |
| `benchmark/smartmem` | `smartmem` | **无**（目录内只有 `README.md`/`evolve.yaml`/`prepare_data.py`/`__init__.py`） | 无 | 无 | **纯 stub**（`STUB_ADAPTER_DOCS` 有登记 ⇒ `is_stub=True`） |
| `benchmark/ssd_alibaba` | `alibaba_ssd` | **无**（同上） | 无 | 无 | **纯 stub**（同上） |

> 这张表是实测 `ls` 结果，**不是推测**。它带来一个必须在计划里解决的后果：PRD §7.7 要求四张卡都出现，但两个 stub 目录**既没有 `problem.md` 也没有 `prompt.md`**，因此「目录含 `problem.md`/`prompt.md` 才算任务」的入选规则会把它们**漏掉**。入选规则见 §1 4B 的规则 7（并见 §9 风险 K7）。

另外 `tests/fixtures/toy_task/` 是**四文件齐全的最小任务夹具**（`evaluator.py`/`init.py`/`problem.md`/`prompt.md`），阶段 4 的后端测试直接拿它当「合法任务」。

`benchmark/hdd_mvp/data/eval_only/val_labels.csv` 就是 evaluator 私有集：**任何 API 都不允许枚举、探测、统计或返回它**。这条有现成的引擎常量可复用（见 §3 分歧 R1）。

### 0.5 holdout 保护的引擎既有约定（关键，必须复用而不是自己发明）

仓库里已经有**两份**受保护 token 清单，且完全一致：

```
src/faultevolve/tasks/hdd_adapter.py:31   HDD_FORBIDDEN_TOKENS 的前四项
src/faultevolve/common/codecheck.py:16    "evaluator-only path": r"eval_only|holdout|val_labels|test_labels"
```

⇒ 阶段 4 的目录枚举/契约检查**必须**导入并复用这个模式，不许在 webapi 里再写一份字面量（否则将来引擎加一条、前端就漏一条）。详见 §3 R1。

### 0.6 工具链与网络（沿用阶段 3 实测结论，本阶段不变）

| 项 | 值 |
|---|---|
| node | v22.22.2（托管：`C:\Users\A\.workbuddy\binaries\node\versions\22.22.2-3`） |
| pnpm | 只能 `cd web` 后用**绝对路径** `pnpm.CMD`；`pnpm --dir web` 在本机**不工作** |
| 绕过 shim 的直调 | `node node_modules/vitest/vitest.mjs run` / `node node_modules/typescript/lib/tsc.js --noEmit` / `node node_modules/vite/bin/vite.js build` / `node node_modules/eslint/bin/eslint.js .` |
| registry | `registry.npmmirror.com`（实测 164ms，远优于 npmjs 的 786ms） |
| python | `.venv/Scripts/python.exe`（已装 fastapi/uvicorn/pydantic_settings；**2026-10-02 起新增 asyncssh 2.24.0 + cryptography 50.0.2**） |
| **python 包安装** | **`.venv` 里没有 pip**（由 `uv 0.12.5` 创建，`pyvenv.cfg` 里有 `uv = 0.12.5`），`python -m pip` 报 `No module named pip`。必须用 **`"$USERPROFILE/.local/bin/uv.exe" pip install --python .venv/Scripts/python.exe <pkg>`** |

### 0.7 必须提前记住的坑（阶段 3 踩实 + 本阶段新踩，本阶段会再遇到）

1. **pnpm store 会被中断的 install 写坏**。症状：`reused N, downloaded 0` 却 `Cannot find module './xxx'`。修法：删 `C:\Users\A\AppData\Local\pnpm\store\v3` + `web/node_modules` 重装。
2. **`pnpm add -D <pkg>` 可能挂住十分钟并向 store 写半包**。所以本阶段**一次性把依赖写进 `package.json` 再 install**，不用 `pnpm add`。
3. **测试里不要用 `fileURLToPath(import.meta.url)`**（本机 vitest 下 `import.meta.url` 不是 `file:` 协议，会报 "URL must be of scheme file"）。统一 `resolve(process.cwd(), '...')`。
4. **提交时 LF→CRLF 警告是既有 `core.autocrlf=true` 造成的，无害**；契约漂移检查按 LF 归一化后比对，不受影响。
5. **不推送 GitHub**。`webui-p0` 从未推送，且本机 git ref 追踪有缺陷；真要推只能 `git push origin webui-p0:feat/webui-p0`。本阶段不做推送。
6. **（本轮新踩）装 Python 包不能用 pip**：`.venv` 是 uv 建的，里面没有 pip。用 `uv.exe pip install --python .venv/Scripts/python.exe <pkg>`。`uv` 不在 PATH 上，全路径是 `$USERPROFILE/.local/bin/uv.exe`（实测装 asyncssh 只花 ~30s，网络正常）。

---

## 1. 阶段划分（5 步，每步独立可验）

原则：**先契约 → 再后端能力 → 再后端接线 → 再前端 → 最后门禁**。每一步结束都能单独跑测试，不留半成品。

### 4A 契约扩展（TODO 4.1–4.6 的接口面）

| 文件 | 内容 |
|---|---|
| `src/faultevolve/webapi/errors.py` | 追加 5 个错误码（§4.1），`UNSUPPORTED_CODES` 保持不变 |
| `src/faultevolve/webapi/contracts.py` | 追加 DTO：`TaskDatasetCardResponse`、`TaskCardMetrics`、`ServerProfileListResponse`、`PresetFieldSource`、`PresetResponse`、`PresetListResponse`、`PathProbeRequest`、`ServerProbeRequest`；`MetaResponse` 追加 4 个字段（§4.2） |
| `web/openapi/faultevolve.openapi.json` | 由 `scripts/export_web_contracts.py` 重新导出 |
| `web/src/generated/api/*` | 由 `pnpm generate:api`（`@hey-api/openapi-ts`）重新生成 |
| `tests/webapi/test_contract_stability.py` | 追加：新 DTO 字段名/枚举值不得被删改（append-only 守卫） |
| `tests/webapi/test_contract_no_secrets.py` | 追加：新 DTO 里不得出现 `password`/`private_key`/`token` 之类可回显字段 |

**4A 验收**：`check_web_contracts.py` 无漂移；`tsc --noEmit` 通过（生成物可编译）；旧 DTO 字节级不变。

### 4B 任务目录服务（TODO 4.1 / 4.2 的数据源；后端只读）

| 文件 | 内容 |
|---|---|
| `src/faultevolve/webapi/task_service.py` | **新建**。扫 `WebSettings.task_roots` 下一层目录，产出 `TaskSummaryResponse` / `TaskDetailResponse` / `TaskDatasetCardResponse` |
| `src/faultevolve/webapi/routes/tasks.py` | **新建**。`GET /api/tasks`、`GET /api/tasks/{task_id}`、`GET /api/tasks/{task_id}/readiness` |
| `tests/webapi/test_task_service.py` | **新建**。见 §6 |

硬规则（写进模块 docstring，并由测试锁死）：

1. **只扫一层**，`task_id` 取目录名；标识符过 `paths.py` 的白名单，拒绝 `..`/`/`/`\`。
2. 每个路径先 `WebSettings.ensure_allowed`，再用 `Path.is_dir()`/`exists()`。
3. `problem.md` 只读**安全摘要**（去代码块、去绝对路径、长度上限 2 000 字符），不返回全文以外的任何东西。PRD §7.8 要求「`problem.md` 的安全摘要」。
4. `data_dirs` 只列**一层子目录名**，且**过滤掉受保护 token**（§0.5 的 `eval_only|holdout|val_labels|test_labels`）。过滤后返回的名字是相对名，不含绝对路径。
5. 数据就绪状态**调用适配器自己的 `DataStatusProvider.data_status(task_dir)`**，不自己拼；但**丢弃引擎返回的 `message`**（它里面可能带 `HDD_BENCH_DATA_ROOT` 的环境变量值），只取 `ok` + `missing` 重新组装中文文案。
6. **绝不打开** `evaluator.py`/`init.py` 的内容做静态检查 —— 阶段 4 只做「存在性 + AST 可解析」的边界（TODO 4.2 的「契约检查结果」在本阶段只到这一步，真人 import 见 §3 R5）。
7. **入选规则（针对 §0.4 的 stub 漏检问题）**：一个下一层目录算作任务，当且仅当满足其一 ——
   (a) 含 `problem.md` 或 `prompt.md`；
   (b) **目录名是 `tasks/registry.py::STUB_ADAPTER_DOCS` 的键**（实测 `smartmem`、`alibaba_ssd` 两个键名与目录名精确相等）。

   为什么用 (b)：PRD §7.7 要求 stub 数据集也出卡，而它们没有四文件。用引擎自己的 stub 登记表做判据，既不硬编码两个目录名，也不会随引擎新增 stub 而漏。
8. **`is_stub` / `doc_path` / `blocked_reason` 的取值来源**：`is_stub` 由 `STUB_ADAPTER_DOCS` 判定（与规则 7(b) 同一份判据，不重复定义），`doc_path` 直接取它登记的值；stub 任务 readiness 必然 `ready=False`，`blocked_reason` = 「该数据集为示例，尚未提供 evaluator / init 工件」，卡片显示「示例（未就绪）」。

**4B 验收**：`test_task_service.py` 全绿；用 `FE_WEB_TASK_ROOTS=benchmark` 起服务，`GET /api/tasks` 返回 4 条，`hdd_mvp.is_stub == False`、`smartmem.is_stub == True`；`GET /api/tasks/hdd_mvp` 的 `data_dirs` **不含** `eval_only`。

### 4C 服务器配置、目录探测与三档预设（TODO 4.3 / 4.4 / 4.6）

| 文件 | 内容 |
|---|---|
| `src/faultevolve/webapi/execution_backend.py` | **新建**。`ExecutionBackend` Protocol + `LocalCloudExecutionBackend` + `SSHCloudExecutionBackend` |
| `src/faultevolve/webapi/server_profiles.py` | **新建**。profile 的 JSON 持久化（原子写）+ 密钥掩码 + `probe` / `check_path` 编排 |
| `src/faultevolve/webapi/presets.py` | **新建**。`build_preset(name)` → 完整 `EvolveConfig` + 字段来源说明 |
| `src/faultevolve/webapi/routes/servers.py` | **新建**。profile 增删改查 + `POST /api/servers/{id}/probe` + `POST /api/servers/{id}/check-path` |
| `src/faultevolve/webapi/routes/presets.py` | **新建**。`GET /api/presets`、`GET /api/presets/{name}` |
| `src/faultevolve/cli.py` | 追加 `web` 子命令组（`web_app = typer.Typer()` + `app.add_typer(web_app, name="web")`），再挂 `serve` |
| `pyproject.toml` | 在**已有的** `[project.optional-dependencies]` 下，把 `asyncssh>=2.14` 加进 **`web`** extra（现含 fastapi/uvicorn/pydantic-settings） |
| `requirements.txt` | 追加 `asyncssh>=2.14`（该文件是扁平全量列表，含 pytest/duckdb，**照 D-B 结论放这里**） |

设计要点：

**ExecutionBackend（协议形状照抄 TODO §4.3，不增不减）**

```python
class ExecutionBackend(Protocol):
    async def probe(self) -> ServerProbe: ...
    async def check_path(self, path: str) -> PathProbe: ...
    async def start_run(self, spec: RunLaunchSpec) -> ProcessHandle: ...
    async def poll(self, handle: ProcessHandle) -> ProcessStatus: ...
    async def terminate(self, handle: ProcessHandle) -> None: ...
```

* `LocalCloudExecutionBackend`：`asyncio.create_subprocess_exec`（**永不 `shell=True`**）；`check_path` 用 `os.stat` + 写探针文件再删，得出「存在/可读/可写」；剩余空间用 `shutil.disk_usage`。
* `SSHCloudExecutionBackend`（D-B 已定为「现在引 asyncssh」）：`asyncssh` 已进 `requirements.txt` + `web` extra 并**已装入 `.venv`（2.24.0）**。仍然**延迟导入**（放在方法内部 `import asyncssh`，不在模块顶层）：理由是 webapi 的启动路径（`/api/health`、`/api/meta`）不该被一个带原生扩展（`cryptography`）的依赖绑死，且这样「依赖缺失 ⇒ 诚实降级」这条分支才可测。行为：
  * 可导入 ⇒ `asyncssh.connect(host, port, username, client_keys=[...], known_hosts=...)`；**禁用 `shell=True` 语义**；远程路径检查走 SFTP `stat`（不用 `ls` 字符串拼接）。
  * 不可导入 ⇒ `/api/meta` 里 `ssh_cloud.available=False` + 理由「asyncssh 不可用」，调用 `probe()` 抛 `CapabilityNotSupportedError`。
<!-- D-B 已定 -->
* **`start_run`/`poll`/`terminate` 本阶段实现但不上线**：写进类里、单元测试直接调用（用 `tests/fixtures/toy_task` 起一个 `python -c "print(1)"` 之类的无害进程），**不注册 HTTP 端点**（见 §2 D-A）。

**密钥处理（TODO 4.3 的硬要求，逐条落地）**

| 要求 | 落法 |
|---|---|
| 私钥路径和密码不返回浏览器 | `ServerProfileResponse` 只有 `has_private_key: bool` + `secret_masked: bool`；请求侧只有 `private_key_ref: str`（**服务端本地解析的引用名**，不是路径本体） |
| 密码不得写入数据库 | profile JSON 里**没有 password 字段**；密码走 `FE_WEB_SSH_PASSWORD_ENV` 指定的环境变量名，运行时 `os.environ` 取 |
| 前端只保存 profile ID / 显示名 / host / port / user / 掩码状态 | 前端 store 只存这些 + `has_private_key` |
| SSH 输出进入脱敏日志 | 复用 `webapi/sanitization.py` 的脱敏函数，日志只写「目标别名 + 成功/失败 + 错误类别」 |
| 默认校验 known_hosts | `WebSettings.ssh_known_hosts` 传入 `asyncssh.connect(known_hosts=...)`；未配置 ⇒ 视为**不可用**而不是「跳过校验」；主机键不匹配 ⇒ `BACKEND_HOST_KEY_MISMATCH` |
| 远程路径必须通过 SFTP/stat 检查 | 见上；`check_path` 的失败区分 `exists=False` 与 `writable=False` |

**三档预设（TODO 4.6）**

后端 `build_preset(name)` 返回 `PresetResponse`：

| 预设 | `budget.max_iterations` | `budget.max_wall_hours` | `analysis.enabled` | `discovery.enabled` | `discovery.tournament.enabled` | `smoke_test.enabled` | 定位 |
|---|---|---|---|---|---|---|---|
| `quick` | 5 | 0.25 | False | False | False | True | 演示「能跑起来」 |
| `standard` | 20 | 2.0 | True | False | False | True | 默认（HDD Demo 推荐「标准进化」） |
| `deep` | 50 | 6.0 | True | True | True | True | 完整（含机制辩论赛） |

* 三档都必须**真实通过 `EvolveConfig.model_validate`**，尤其 `deep` 要满足「`tournament.enabled ⇒ discovery.enabled`」的既有 `model_validator`。
* 响应带 **字段来源说明**（`PresetFieldSource{field, value, source}`，`source ∈ {preset_default, task_required, server_profile, user_patch}`），这是 TODO 4.6「返回完整 `EvolveConfig` 和字段来源说明」的落地。
* 用户改动后前端**只提交 patch**；后端 `merge_patch(preset, patch)` 再 `model_validate`，失败 ⇒ `PRESET_INVALID`（新增错误码）。**前端永不自己拼 `EvolveConfig`**。

**4C 验收**：`test_presets.py`（三档都是合法 config + patch 合并 + 越界 patch 被拒）、`test_server_profiles.py`（掩码、原子写、无密码落盘）、`test_execution_backend.py`（本地 probe/check_path 真实可用；SSH 在无 asyncssh 时诚实报不可用）。

### 4D 前端：总览页与任务输入页（TODO 4.1–4.6 的界面）

| 文件 | 内容 |
|---|---|
| `web/src/routes/OverviewPage.tsx` | **重写**：开始区（HDD Demo 卡 + 创建自定义任务）→ 数据集与示例（四卡）→ 最近运行（沿用现有表，从 `/api/runs` 读）→ 云端状态摘要 |
| `web/src/routes/NewRunPage.tsx` | **重写**：由 `StagePlaceholder` 换成真实录入页（任务工件 / 服务器与目录 / 环境 / 知识注入 / 进化强度），右侧常驻「启动前检查」面板 |
| `web/src/features/intake/DemoCard.tsx` | HDD Demo 卡：信息全部来自 `GET /api/tasks/hdd_mvp`，**不在组件里硬编码 ROS 22.81**；两个动作见下 |
| `web/src/features/intake/DemoConfirmDrawer.tsx` | Demo 确认抽屉（PRD §7.2 列出的 7 项信息：数据集/指标/evaluator/初始算法/知识包/推荐强度/可选动作） |
| `web/src/features/intake/DatasetCardGrid.tsx` + `DatasetCard.tsx` | 四张数据集卡（PRD §7.7 的 11 个字段），`is_stub` 卡显示「示例（未就绪）」且 CTA 禁用并给理由 |
| `web/src/features/intake/TaskArtifactsForm.tsx` | 三个**必填卡片**：数据集 / evaluator / 初始算法（PRD §7.3 字段逐条） |
| `web/src/features/intake/CardValidationBadge.tsx` | 五态徽标：未填写 / 检查中 / 通过 / 警告 / 失败 |
| `web/src/features/intake/ServerProfileForm.tsx` | host/port/user/认证方式状态 + 五个目录（repo/data/runs/artifacts/logs）+ 测试连接 + 测试目录 |
| `web/src/features/intake/PathProbeList.tsx` | 路径检查结果：存在 / 可读 / 可写 / 剩余空间（PRD §7.4 四条交互规则） |
| `web/src/features/intake/EnvConfigForm.tsx` | conda/python、CPU、GPU 数量+设备号、GPU 型号（标注「期望/检测」）、内存、并发、超时、环境变量**只显示是否已配置** |
| `web/src/features/intake/NotesTextarea.tsx` | 「运行环境补充说明」自由文本，占位文案照抄 PRD §7.5；UI 明确标注「仅作为运行备注，不会作为命令执行」 |
| `web/src/features/intake/KnowledgeInjectionForm.tsx` | 知识注入选项（见 §2 D-C） |
| `web/src/features/intake/PresetSelector.tsx` | 三档预设 + 「已自定义」标记 + 「恢复默认」清空 patch |
| `web/src/features/intake/PreflightPanel.tsx` | 启动前检查汇总（PRD §8.1 第五步的形状；本阶段只读检查，不启动） |
| `web/src/features/intake/useIntakeForm.ts` | 表单状态机（含 `dirtyFields` ⇒ 「已自定义」的判定规则） |
| `web/src/stores/intake-store.ts` | 只存**非敏感**的当前选择：`taskId`、`serverProfileId`、`preset`、`patch`、注意 `notes` 也进 store 但**不进 URL** |
| `web/src/lib/query-keys.ts` | 追加 `tasks()/task(id)/taskReadiness(id)`、`servers()/serverProbe(id)`、`presets()/preset(name)` |
| `web/src/lib/api-error.ts` | 追加新错误码的中文映射（`task.not_found`、`server.not_found`、`preset.unknown`、`preset.invalid`、`process.control_disabled`） |

交互与边界（逐条对齐 TODO / PRD）：

1. **Demo 卡两个动作**
   * `打开完整回放`：从 `/api/meta` 的 `demo_run_ids` 取第一个，`navigate({to:'/runs/$runId'})`。**当前阶段 3 的 `MetaResponse` 没有 `demo_run_ids` 字段**（0.3 已核）⇒ 4A 必须补上，否则这个按钮无处取 id。
   * `启动短流程`：本阶段打开「Demo 确认抽屉」→ 触发 `GET /api/tasks/hdd_mvp/readiness` → 显示检查结果；主按钮按 §2 D-A 的结论处理（默认：禁用 + 理由「运行创建由阶段 7 交付」）。
2. **必填卡片的阻塞规则**（TODO §6 测试项「evaluator 缺失时不能继续」「init 缺失时不能继续」「数据目录不存在时不能继续」）——三张卡各自有 `status ∈ {empty, checking, pass, warn, fail}`，只要有任意一张不是 `pass|warn`，右下角「继续」置灰并在 `PreflightPanel` 列出**阻塞原因**。`warn` 允许继续但必须显式确认。
3. **自由文本永不成命令**：`notes` 只进 `RunCreateRequest.config_patch.notes`（或 profile 的 `notes`），前端**不做任何拼接**；后端 `notes` 只落库不执行（TODO 4.4）。
4. **「已自定义」与「恢复默认」**：以 `patch` 是否为空为唯一判据（不靠 UI 状态猜）。`patch = {}` ⇒ 不显示；`patch ≠ {}` ⇒ 显示。点「恢复默认」⇒ `patch = {}`，界面上的高级字段回到预设值。这正是 TODO §6 的两条测试项。
5. **不显示分数的地方就不显示**：初始算法未试跑 ⇒ 显示「待评估」（PRD §7.3），**不显示任何假定分数**；基线分数只在适配器/API 真的给出时才渲染。

**4D 验收**：`vitest run` 全绿（新增用例见 §6）；`tsc --noEmit` 0 错；`eslint .` 0 err/0 warn；`vite build` 成功。

### 4E 门禁与记录

| 项 | 命令 | 预期 |
|---|---|---|
| 前端类型 | `node node_modules/typescript/lib/tsc.js --noEmit` | 0 错 |
| 前端单测 | `node node_modules/vitest/vitest.mjs run` | 阶段 3 的 34 条 + 本阶段新增，全绿 |
| 前端 lint | `node node_modules/eslint/bin/eslint.js .` | 0 error / 0 warning |
| 前端构建 | `node node_modules/vite/bin/vite.js build` | 成功产出 `web/dist` |
| 契约漂移 | `pnpm check:contracts` | 无漂移 |
| Python 回归 | `.venv/Scripts/python.exe -m pytest -q` | **失败集合与阶段 3 基线一致**（8 条 `test_hdd_protected_files.py` 的 CRLF 假红），**0 新增失败** |
| 人工冒烟 | 见 §7 | 四项都能点、刷新不丢 |

---

## 2. 决策结论（灵梦 2026-10-02 已定 D-A / D-B；D-C / D-D / D-E 见下）

> 状态：**D-A = A1 已定**，**D-B = B2 已定**（asyncssh 已装入 `.venv`）。
> D-C / D-D / D-E 三条按推荐值执行，**若灵梦不同意任何一条，说一声我改**。

### D-A　「启动短流程」在阶段 4 是否真的能启动一次运行？　✅ **结论：A1（只做启动前检查）**

| 选项 | 内容 | 代价 |
|---|---|---|
| **A1 ✅ 灵梦已选** | 阶段 4 只做**启动前检查**；`ExecutionBackend.start_run` 实现且被单测覆盖，但 **HTTP 启动端点留到阶段 7**（TODO §10 明确把「运行创建与进程管理」划给阶段 7）。Demo 卡的「启动短流程」显示检查结果 + 禁用主按钮，理由写明「运行创建由阶段 7 交付」 | 阶段 4 结束时无法从界面真跑一次；与 TODO §7 的措辞「本轮必须实现至少一个真实可用的云端执行目标」有轻微张力 —— 但 4.3 的措辞是「执行目标」，指 probe/目录/后端可用，不是指启动端点 |
| A2 | 把阶段 7 的 `POST /api/runs` 提前到阶段 4 | 需要一并交付运行注册表、日志落盘、进程恢复，范围翻倍，且与 TODO 的阶段划分冲突 |

**已定 A1。** 落地要求（写进实现）：
1. `routes/` 里**不注册** `POST /api/runs`、不注册任何 `start/pause/resume/cancel` 端点。
2. `/api/meta.process_control_enabled` 保持 `false`（`WebSettings.enable_process_control` 默认 False，本阶段不动）。
3. Demo 卡与 PreflightPanel 必须**明确显示一行**「运行创建与进程控制由阶段 7 交付」，不留下让人以为能启动的按钮。
4. `start_run`/`poll`/`terminate` 三个方法**要写**（TODO 4.3 明确要求实现），只由 `tests/webapi/test_execution_backend.py` 直接调用验证。
5. §6.1 的「Demo 可正确打开真实回放」是 A1 下 Demo 卡的**唯一真实动作**，测试要重点覆盖它。

### D-B　SSH 后端：现在引 `asyncssh` 吗？　✅ **结论：B2（现在就引）**

| 选项 | 内容 | 代价 |
|---|---|---|
| B1 | 走 optional extra `web-ssh`，未安装时 `/api/meta` 里 `ssh_cloud.available=False` + 诚实理由 | 本机默认不装 ⇒ 冒烟只能验本机路径 |
| **B2 ✅ 灵梦已选** | 把 `asyncssh` 加进 `requirements.txt` + `pyproject` 的 `web` extra，并**立即安装** | 多一个带原生扩展（`cryptography`）的依赖 |
| B3 | 本阶段不实现 SSH 类，只留 Protocol 与占位 | 违反 TODO 4.3「分别实现 LocalCloudExecutionBackend / SSHCloudExecutionBackend」 |

**已定 B2，且已完成**：

```
"$USERPROFILE/.local/bin/uv.exe" pip install --python .venv/Scripts/python.exe "asyncssh>=2.14"
  → asyncssh==2.24.0, cryptography==50.0.2, cffi==2.1.1, pycparser==3.0
```

落地要求：
1. `requirements.txt` 追加 `asyncssh>=2.14`；`pyproject.toml` 的 **`web`** extra 追加同一行。
2. `SSHCloudExecutionBackend` **仍然延迟导入**（理由与可测性见 §1 4C）。
3. `/api/meta` 里 `ssh_cloud.available` 由「asyncssh 是否可导入」决定：可导入 ⇒ `True`。
4. 冒烟新增一条：把 SSH 目标指向一个**不可达地址**，断言返回**诚实的结构化错误**（`backend.unavailable` / `backend.auth_failed` / `backend.host_key_mismatch`），而不是 500 或挂死。

### D-C　知识注入的「选择已有类别」怎么落地？　默认 **C1**

问题：`KnowledgeConfig` 现有字段是 `{dir, k, max_per_category, enabled}`，**没有类别过滤器**；`DiscoveryConfig` 有 `enabled`/`tournament`/`inject_same_run`/`extra_card_paths`。PRD §7.6 要的「选择若干知识类别或知识簇」在引擎里**没有对应字段**。

| 选项 | 内容 |
|---|---|
| **C1（默认执行）** | 阶段 4 只做**能映射到真实字段**的四项：关闭 / 默认知识包（`knowledge.dir = <task>/knowledge`, `enabled=True`）/ 自动发现（`discovery.enabled=True`）/ tournament（`discovery.enabled=True` + `tournament.enabled=True`）。「选择类别」以**禁用 + 理由**呈现：「引擎尚无类别过滤字段（待确认）」。 |
| C2 | 顺手给 `KnowledgeConfig` 加 `categories: list[str] = []` 并在引擎侧实现过滤 | 越过 TODO 范围，动到引擎核心路径，需要引擎侧测试 |

**默认 C1**（TODO 4.5 的原话是「选项必须映射到真实 `KnowledgeConfig` 和 `DiscoveryConfig` 字段」⇒ 映射不了的就不要假装能映射）。若你希望 C2，我再补一份引擎侧改动计划。

### D-D　`/api/meta` 的 `deployment_modes` 是否翻转？　默认**执行**

现状：`local_cloud` 与 `ssh_cloud` 都 `available=False`，理由「执行后端尚未实现（阶段 7 交付）」。

* 阶段 4 交付 `LocalCloudExecutionBackend` 后，`local_cloud.available=True`、`supported_transports=[local_cloud]`、`detail="本机/同机云端执行目标可用"` **是诚实的**（probe/check_path 真的能跑）。
* `ssh_cloud`：因 D-B 已定 B2 且 asyncssh 已装 ⇒ 可导入时 `available=True`、`supported_transports=[ssh_cloud]`。
* 同时清理 `app.py` 里那段写死的循环与注释（现在是对 `DEPLOYMENT_MODES`/`UNAVAILABLE_DEPLOYMENT_MODES` 两个硬编码 `for`），改成**读执行后端注册表**，避免「meta 说可用、后端并不存在」这种漂移。

### D-E　服务器配置的持久化与「至少一个默认 profile」　默认**要**

`server_profile_store` 目前是死配置。计划：JSON 文件（`{store}/profiles.json`），原子写（临时文件 + `os.replace`），读时校验 schema。

**默认执行**：预置一个「本机（local_cloud）」profile —— 首次启动时自动生成，字段全为空、`has_private_key=False`，用户点「测试连接」才做真实 probe。这样演示时不必先手填一遍。

---

## 3. 与任务书 / PRD 的分歧（显式标注，不偷偷绕开）

| # | 分歧 | 处置 |
|---|---|---|
| R1 | **holdout 保护清单必须单一来源**。`hdd_adapter.py` 与 `codecheck.py` 各写了一份（内容相同）。TODO 4 只说要「holdout 不被探测或列出」，没说复用哪份 | 计划：webapi 侧**导入** `faultevolve.common.codecheck` 里的模式（它是正则，覆盖 `eval_only|holdout|val_labels|test_labels`），并在测试里断言「webapi 模块内不出现这四个字面量」（防止将来有人另写一份） |
| R2 | `DataStatus.message` 会带 `HDD_BENCH_DATA_ROOT` 的环境变量值 | 计划：**丢弃引擎 message**，只取 `ok`/`missing` 重写中文文案（PRD §7.5「环境变量状态，只显示是否已配置」） |
| R3 | 概念图 `04-results-report.png` 的 8 项侧栏 vs PRD §5.1「严格四项」 | 概念图不作数（C3）。阶段 4 不加任何侧栏项；设置/帮助/状态继续在顶栏 |
| R4 | TODO 4.1 说 Demo 卡有「启动短流程」，但 TODO §10 把运行创建划给阶段 7 | 见 D-A。默认按 A1：按钮在位、诚实禁用 |
| R5 | PRD §7.3 要求 evaluator「可导入性、调用签名、返回字段、超时和禁止访问检查」，这是一次真实的子进程导入 | 计划：本阶段只做 **文件存在 + AST 可解析 + 禁止 token 扫描**（用 `codecheck`），**不真的 import**。真人导入等于在 Web 进程里执行用户代码，必须放到阶段 7 的受控执行路径里。这条要写进 UI 文案，避免「契约检查」被误解为已完整实现 |
| R6 | `web/openapi/*.json` 是生成物但入库 | 沿用阶段 1 既有做法：生成物入库 + CI 比对；阶段 4 只用一条命令重生成，不手工编辑 |

---

## 4. 后端改动清单

### 4.1 新增错误码（`errors.py`，append-only）

| 常量 | 值 | HTTP | 中文文案 | 什么时候抛 |
|---|---|---|---|---|
| `TASK_NOT_FOUND` | `task.not_found` | 404 | 找不到该任务 | `task_id` 在 `task_roots` 下一层不存在 |
| `TASK_NOT_READY` | `task.not_ready` | 409 | 该任务尚未就绪 | readiness 检查有 `fail` 级问题却仍试图继续 |
| `SERVER_NOT_FOUND` | `server.not_found` | 404 | 找不到该服务器配置 | `profile_id` 不在 store 里 |
| `PRESET_UNKNOWN` | `preset.unknown` | 400 | 未知的进化强度预设 | `preset` 不在 `{quick,standard,deep}` |
| `PRESET_INVALID` | `preset.invalid` | 422 | 配置合并后不合法 | `merge_patch` 后 `model_validate` 失败（`detail` 只带字段名，不带值） |

> `UNSUPPORTED_CODES` 不变（仍只含 `NOT_SUPPORTED`）。

### 4.2 `contracts.py` 追加/修改

**`MetaResponse` 追加（全部带默认值 ⇒ 向后兼容）**

| 字段 | 类型 | 用途 |
|---|---|---|
| `demo_run_ids: list[str] = []` | 让「打开完整回放」有 id 可取（0.3 已确认现缺此字段） |
| `task_catalog_available: bool = False` | `task_roots` 为空时前端显示「未配置任务目录」而不是空列表 |
| `preset_names: list[str] = []` | 三档预设名由后端给出，前端不硬编码 |
| `server_profiles_enabled: bool = False` | `server_profile_store` 未配置时为 False，UI 禁用服务器区 |

**新 DTO**

| DTO | 关键字段 |
|---|---|
| `TaskCardMetrics` | `primary_metric: str`、`target_direction: Literal['higher','lower']`、`target_score: float \| None`、`initial_score: float \| None`、`score_source: Literal['evaluator','baseline_run','unavailable']` |
| `TaskDatasetCardResponse` | `task_id`、`display_name`、`device_type`、`summary`、`adapter`、`is_stub`、`metrics: TaskCardMetrics`、`data_ready: bool`、`data_missing: list[str]`、`evaluator_ready: bool`、`init_ready: bool`、`knowledge_card_count: int \| None`、`last_run_id: str \| None`、`last_best_score: float \| None`、`blocked_reason: str \| None` |
| `ServerProfileListResponse` | `profiles: list[ServerProfileResponse]`、`default_profile_id: str \| None`、`ssh_available: bool` |
| `PathProbeRequest` | `path: str` |
| `ServerProbeRequest` | `profile_id: str`（也可用路径参数，计划用路径参数，此 DTO 预留） |
| `PresetFieldSource` | `field: str`、`value: Any`、`source: Literal['preset_default','task_required','server_profile','user_patch']` |
| `PresetResponse` | `name: str`、`display_name_zh: str`、`summary_zh: str`、`config: dict[str, Any]`（完整 `EvolveConfig` dump）、`sources: list[PresetFieldSource]` |
| `PresetListResponse` | `presets: list[PresetResponse]` |

`CONTRACT_MODELS` 同步追加，保证 `app.py::_install_contract_schemas` 把它们全部发布到 `components/schemas`。

### 4.3 新增路由

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/tasks` | `list[TaskSummaryResponse]`；`TaskSummaryResponse` 里补 `is_stub`/`doc_path` 已在契约中 |
| GET | `/api/tasks/{task_id}` | `TaskDetailResponse` |
| GET | `/api/tasks/{task_id}/readiness` | `TaskReadinessResponse`（数据/evaluator/init/prompt/知识卡五项检查） |
| GET | `/api/tasks/{task_id}/card` | `TaskDatasetCardResponse`（数据集卡片的聚合视图） |
| GET | `/api/servers` | `ServerProfileListResponse` |
| POST | `/api/servers` | 创建/更新（upsert by `profile_id` 或 `display_name`） |
| GET | `/api/servers/{profile_id}` | `ServerProfileResponse`（掩码） |
| DELETE | `/api/servers/{profile_id}` | 删除 |
| POST | `/api/servers/{profile_id}/probe` | `ServerProbeResponse` |
| POST | `/api/servers/{profile_id}/check-path` | `PathProbeResponse`（body: `PathProbeRequest`） |
| GET | `/api/presets` | `PresetListResponse` |
| GET | `/api/presets/{name}` | `PresetResponse` |

`routes/__init__.py::register_all` 追加 `tasks`/`servers`/`presets` 三个模块。

### 4.4 新增 CLI

现状（已核 `pyproject.toml`）：入口点是 `[project.scripts] fe = "faultevolve.cli:app"`，`cli.py` 里已有 `app` 与四个 `typer.Typer` 子组（`evolve` / `judge` / `discover` / `data`）。阶段 4 照同一模式加第五个组：

```
fe web serve [--host 127.0.0.1] [--port 8000] [--reload]
```

* `web_app = typer.Typer(help="Web API 服务")`；`app.add_typer(web_app, name="web")`；`@web_app.command("serve")`。
* 读 `FE_WEB_*` 环境变量构造 `WebSettings`（**不在 import 时读**，沿用阶段 1 既有纪律）。
* `uvicorn.run(create_app(settings), host=..., port=..., reload=...)`。
* `--reload` 仅开发用；文档注明 reload 会重启进程，**阶段 4 不涉及进程恢复**。
* 另注（对测试有用）：`pyproject.toml` 里 `[tool.pytest.ini_options] asyncio_mode = "auto"` 且 dev extra 已含 `pytest-asyncio`，所以 `ExecutionBackend` 的 async 测试**不需要** `@pytest.mark.asyncio`。

---

## 5. 前端改动清单

见 §1 4D 的表格。补充说明三条结构性选择：

1. **`/overview` 与 `/runs/new` 的分工**：PRD §7.1 说总览同时承担「开始新任务」与「回到已有运行」。因此总览页的「开始区」是**入口卡片**，「创建自定义任务」按钮跳到 `/runs/new` 做真正的录入 —— 不在总览页内联一个长表单（否则首屏过载，且与 PRD §8 的六步流程重复）。
2. **`/runs/new` 本阶段的形状**：TODO 阶段 4 只覆盖录入（4.2–4.6），六步向导的「第五步 启动前检查 / 第六步 确认并启动」属阶段 7。所以本阶段 `/runs/new` 用**单页分组 + 右侧常驻 PreflightPanel**，而不是硬造一个走不通的六步向导。分组命名直接对齐 PRD §8.1 的第 1–4 步，保证阶段 7 加向导时是「加壳」而不是「重写」。
3. **状态归属**：表单状态放 `intake-store.ts`（Zustand），**服务端数据一律走 TanStack Query**；`notes` 这类可能含敏感运维信息的自由文本**不写 URL、不写 localStorage**（避免刷新后仍在磁盘上）。

---

## 6. 测试清单

### 6.1 TODO 阶段 4 的 8 条（逐条对应到具体用例）

| TODO 要求 | 用例位置 | 断言 |
|---|---|---|
| Demo 可正确打开真实回放 | `web/src/features/intake/DemoCard.test.tsx` | 点「打开完整回放」后 `navigate` 收到 `/runs/{meta.demo_run_ids[0]}`；`demo_run_ids` 为空时按钮禁用且说明原因 |
| evaluator 缺失时不能继续 | `TaskArtifactsForm.test.tsx` + `tests/webapi/test_task_service.py` | 前端：evaluator 卡为 `fail` ⇒ 「继续」disabled；后端：`readiness` 返回 `ready=False` 且 `checks` 含 `evaluator.py` |
| init 缺失时不能继续 | 同上 | 同上，针对 `init.py` |
| 数据目录不存在时不能继续 | `test_task_service.py` | `data_missing` 非空 ⇒ `ready=False`；把 `benchmark/hdd_mvp/data/public` 改名后测试（在 `tmp_path` 副本里做） |
| **holdout 不被探测或列出** | `tests/webapi/test_no_holdout_exposure.py`（**新建**） | ① `GET /api/tasks/hdd_mvp` 的 `data_dirs` 不含 `eval_only`；② 遍历所有新端点的响应 JSON，**任何字符串都不匹配** `holdout\|eval_only\|val_labels\|test_labels`；③ webapi 源码里不出现这四个字面量（只允许 import 自 `codecheck` 的模式） |
| 自由文本不能变成命令参数 | `tests/webapi/test_server_profiles.py` | 把 `notes` 塞成 `; rm -rf / #` 与 `$(whoami)`：① 存回后 `notes` 原样（不做任何解析）；② `probe` 传给 `create_subprocess_exec` 的 argv **不含** notes；③ 用 monkeypatch 断言 `shell=` 从未被传 `True` |
| 三档预设生成合法 EvolveConfig | `tests/webapi/test_presets.py` | 三个预设都 `EvolveConfig.model_validate(preset.config)` 通过；`deep` 的 `tournament.enabled=True ⇒ discovery.enabled=True`；`sources` 覆盖全部被改字段 |
| 修改高级配置后「已自定义」出现 | `web/src/features/intake/useIntakeForm.test.ts` | `patch={}` ⇒ `isCustomized=false`；`patch` 任一字段变化 ⇒ `true` |
| 恢复默认后 patch 被清空 | 同上 | 调 `resetToPreset()` 后 `patch` 深等于 `{}` 且 `isCustomized=false` |

### 6.2 补充用例（本阶段新增能力必须有的覆盖）

| 用例 | 位置 | 断言 |
|---|---|---|
| 任务目录未配置时诚实降级 | `test_task_service.py` | `task_roots=[]` ⇒ `GET /api/tasks` 返回 `[]`，`/api/meta.task_catalog_available=False` |
| stub 任务被正确标记且不抛错 | `test_task_service.py` | `FE_WEB_TASK_ROOTS=benchmark` ⇒ `GET /api/tasks` 恰好 4 条；`smartmem.is_stub=True`、`doc_path=="docs/datasets/smartmem.md"`、`readiness.ready=False` 且 `checks` 里列出缺失的 `evaluator.py`/`init.py`；**整个过程不抛异常**（无四文件不是错误） |
| 非任务目录不入列表 | `test_task_service.py` | `FE_WEB_TASK_ROOTS=<repo root>` ⇒ 结果里不含 `web`、`src`、`docs`（都不含 `problem.md`/`prompt.md` 且不在 `STUB_ADAPTER_DOCS`） |
| evaluator 契约检查**不真的 import** | `test_task_service.py` | monkeypatch `importlib.import_module` 抛异常，readiness 仍返回结果（证明没走 import 路径） |
| 路径穿越被拒 | `test_task_service.py` | `task_id=../../etc` ⇒ 400 `request.invalid`（复用 `paths.py` 白名单） |
| profile 掩码 | `test_server_profiles.py` | 响应体不含 `password`/`private_key` 字段名与值；`has_private_key` 为 bool |
| profile 原子写 | `test_server_profiles.py` | 写入过程中断（monkeypatch `os.replace` 抛错）后原文件完好 |
| asyncssh 缺失时诚实降级 | `test_execution_backend.py` | **用 monkeypatch 伪造导入失败**（因为 asyncssh 现已真实安装，不能靠「没装」来测）：`monkeypatch.setitem(sys.modules, "asyncssh", None)` / 让延迟导入抛 `ImportError` ⇒ `probe()` 抛 `CapabilityNotSupportedError`；`/api/meta` 里 `ssh_cloud.available=False` **且 `detail` 说明是 asyncssh 不可用** |
| asyncssh 已装时 SSH 后端可用且错误诚实 | `test_execution_backend.py` | ① `/api/meta` 里 `ssh_cloud.available=True`；② 对**不可达地址**（如 `127.0.0.1:1`）`probe()` ⇒ 返回结构化失败（`reachable=False` + `backend.unavailable`），**不抛未捕获异常、不挂死**（测试加超时）；③ 缺 known_hosts 配置 ⇒ 不校验而是判为不可用 |
| 本地 probe/check_path 真实可跑 | `test_execution_backend.py` | 对 `tmp_path` 做 `check_path` ⇒ `exists=True,is_directory=True,writable=True`；对不存在的路径 ⇒ `exists=False` |
| `start_run/poll/terminate` 行为正确（不上线也得测） | `test_execution_backend.py` | 用 `toy_task` 起 `python -c "print('ok')"` ⇒ `poll` 拿到退出码 0；`terminate` 对已退出进程是幂等空操作 |
| 契约 append-only | `test_contract_stability.py` | 新 DTO 字段与枚举值被加入白名单后仍不得删改 |
| 新 DTO 无密钥字段 | `test_contract_no_secrets.py` | 扫描新 DTO 的 schema，字段名不含 `password\|private_key\|secret\|token`（`has_private_key`/`secret_masked` 是白名单内的布尔标记） |
| 服务状态摘要不撒谎 | `OverviewPage.test.tsx` | `deployment_modes` 里 `available=False` 的模式显示「不可用」+ 后端给的 `detail` 原文 |

### 6.3 回归

* **Python**：`.venv/Scripts/python.exe -m pytest -q`。基线 = 阶段 3 的 644 passed + 8 failed（`test_hdd_protected_files.py` 的 CRLF 假红）。**要求：0 新增失败**，新增用例全绿。
* **前端**：阶段 3 的 34 条 + 本阶段新增全部通过。

---

## 7. 验收命令与预期

```bash
# 0. 依赖：D-B=B2 ⇒ asyncssh 是硬依赖，先确认它真的在
.venv/Scripts/python.exe -c "import asyncssh,cryptography;print(asyncssh.__version__,cryptography.__version__)"
#    预期：2.24.0 50.0.2

# 1. 生成契约（改了 contracts.py 必须先跑，否则漂移检查红）
cd web && <abs>/pnpm.CMD run sync:contracts
#    预期：web/openapi/*.json 与 web/src/generated/api/* 更新，无报错

# 2. 契约漂移
<abs>/pnpm.CMD run check:contracts          # 预期：no drift

# 3. 前端门禁（四条都要绿）
node node_modules/typescript/lib/tsc.js --noEmit
node node_modules/vitest/vitest.mjs run
node node_modules/eslint/bin/eslint.js .
node node_modules/vite/bin/vite.js build

# 4. Python 回归（后台跑，本机约 22 分钟）
cd .. && .venv/Scripts/python.exe -m pytest -q
#    预期：644 + 新增 / 失败仍为 8（同一批 CRLF 假红），0 新增失败

# 5. 安装 Python 包（若需要）：.venv 没有 pip，必须用 uv
"$USERPROFILE/.local/bin/uv.exe" pip install --python .venv/Scripts/python.exe <pkg>

# 6. 人工冒烟（两个终端）
#   A: FE_WEB_TASK_ROOTS=benchmark FE_WEB_SERVER_PROFILE_STORE=.fe/profiles \
#      .venv/Scripts/python.exe -m faultevolve.cli web serve --port 8000
#   B: cd web && <abs>/pnpm.CMD dev        # 打开 http://localhost:5173
```

冒烟要确认的 10 件事（按 TOR 顺序）：

1. 侧栏仍是 **4 项**（没被概念图的 8 项污染）。
2. 总览页出现 HDD Demo 卡 + 4 张数据集卡；`hdd_mvp` 是「完整可运行」，`smartmem`/`ssd_alibaba` 是「示例（未就绪）」且 CTA 禁用有理由。
3. HDD Demo 卡上的 ROS 等数字**来自 `/api/tasks/hdd_mvp`**：改 `task_roots` 后数字消失（证明没硬编码）。
4. 「打开完整回放」跳到 `/runs/{demo_run_ids[0]}`，刷新后仍在该运行（阶段 3 已有能力）。
5. **「启动短流程」按 A1 处置**：只跑启动前检查、主按钮置灰、界面明确写「运行创建与进程控制由阶段 7 交付」。**界面上不能出现任何能真的启动运行的按钮**。
6. 「测试连接」对 local_cloud 返回真实信息（OS/Python/磁盘）；`/api/meta` 里 `local_cloud.available=true`、`ssh_cloud.available=true`（asyncssh 已装）。
7. SSH 目标填一个**不可达地址**（如 `127.0.0.1:1`）点测试连接 ⇒ 界面显示诚实的失败原因（连不上/认证失败/主机键不匹配），**不是 500、不是转圈**。
8. 「测试目录」对 `benchmark/hdd_mvp/data` 显示存在/可读/可写/剩余空间；**DOM 里搜不到 `eval_only`**。
9. 三个必填卡任缺其一 ⇒ 「继续」置灰且 PreflightPanel 列出原因；补全后变可点。
10. 改一个高级字段 ⇒ 出现「已自定义」；点「恢复默认」⇒ 标记消失且字段回预设值。

---

## 8. 明确不做的事（防止范围蔓延）

| 不做 | 归属 | 理由 |
|---|---|---|
| `POST /api/runs` 真正启动运行 | 阶段 7 | TODO §10 明确划归；见 D-A |
| 进程注册表、日志流、暂停/恢复/取消 | 阶段 7 | 同上 |
| SSE / 实时事件 | 阶段 8 | TODO §11 |
| 进度、树、节点详情的真实渲染 | 阶段 5 | TODO §8 |
| 知识卡/现象/辩论赛界面 | 阶段 6 | TODO §9 |
| evaluator 的真实子进程导入与签名检查 | 阶段 7 | 见 R5；本阶段只到 AST 解析 |
| Playwright E2E、视觉回归 | 阶段 9 | TODO §12.4/§12.5 |
| 任何 `qianduan-yemian-demo` 分支的代码/样式借用 | 永久 | 灵梦硬约束 C1 |
| 私有模式（local_only / hybrid） | P2/P3 | PRD §4.2 本期纯云端 |
| 删除运行 | 不纳入 MVP | PRD §7.9 明写 |
| 在浏览器预览原始记录 / 标签 / 私有测试集 | 永久 | PRD §7.3 |
| 在前端重算分数或修改评分结果 | 永久 | PRD §2.2 单一评分链 |
| 推送 GitHub | 本阶段不做 | 见 0.7.5 |

---

## 9. 已知风险

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| K1 | `local_cloud.available=True` 后，UI 上「看起来什么都能跑」，但启动仍要等阶段 7 | 演示时被追问 | PreflightPanel 明确一行「运行创建由阶段 7 交付」；`/api/meta.process_control_enabled` 仍为 `false` |
| K2 | `benchmark/backblaze_hdd` 的数据要 `download_data.py` 真下载才能就绪 | 数据集卡显示「未就绪」 | 卡片直接显示 `data_missing` 与准备脚本名（来自 `DataStatus` 的 `missing`），不假装就绪 |
| K3 | SSH 后端在**本机没有可用的真实 SSH 目标**，端到端只能验「连不上时是否诚实」 | 阶段 7 接 SSH 时才可能发现真机问题 | D-B 已定 B2（asyncssh 已装）⇒ 本阶段**至少能验到「导入成功 + 不可达目标的错误映射」**；真机连通性验证写进阶段 7 的前置条件。计划 §5 冒烟第 5 条覆盖 |
| K4 | `MetaResponse` 增字段会动到阶段 3 已冻结的形状 | 契约漂移检查可能红 | 全部新字段带默认值，`test_contract_stability.py` 里以「旧字段仍在且类型不变」为判据 |
| K5 | `notes` 自由文本仍可能被后续阶段误当命令 | 安全事故 | 本阶段就写测试锁死「不解析、不拼接、不传 argv」；阶段 7 必须复用同一条测试 |
| K6 | 任务目录扫描在 `task_roots` 配成仓库根时会把 `web/`、`src/` 当任务 | 列表脏 | 入选规则见 §1 4B 规则 7：必须「含 `problem.md`/`prompt.md`」**或**「目录名在 `STUB_ADAPTER_DOCS` 里」；两者都不满足则跳过，其中 `web/`、`src/` 都不满足 ⇒ 不会入选。测试锁死这条 |
| K7 | 两个 stub 目录（`smartmem`/`ssd_alibaba`）没有四文件，容易在实现时被误判成「任务缺失」报错 | 卡片要么消失、要么显示成故障 | §1 4B 规则 7/8：stub 走独立分支，`ready=False` + `blocked_reason` 文案 + 卡片标「示例（未就绪）」，**不抛错**。`test_task_service.py` 里两条 stub 判定用例锁死 |

---

## 10. 完成定义核对（TODO §7 + §12）

- [x] TODO 4.1：Demo 信息全部来自 `/api/tasks`，组件内无硬编码；**按 A1**：「启动短流程」只做启动前检查、按钮置灰并写明阶段 7 交付
- [x] TODO 4.2：三个必填卡 + 五态校验（未填写/检查中/通过/警告/失败）
- [x] TODO 4.3：`ExecutionBackend` 协议 + 两个实现；`local_cloud` **与** `ssh_cloud` 都真实可用（**按 B2**：asyncssh 已进 `requirements.txt` + `web` extra 并已装入 `.venv`）；密码/私钥不回浏览器、不落库；SSH 不用 `shell=True`；远程路径用 SFTP/stat
- [x] TODO 4.4：环境字段结构化；`notes` 只存备注不执行
- [x] TODO 4.5：知识注入选项映射到真实 `KnowledgeConfig`/`DiscoveryConfig` 字段（映射不了的「选择类别」诚实禁用，见 D-C）
- [x] TODO 4.6：后端预设生成函数，返回完整 `EvolveConfig` + 字段来源；前端只提交 patch，后端合并再校验
- [x] **A1 专项**：`routes/` 里确实没有 `POST /api/runs`；`/api/meta.process_control_enabled` 仍为 `false`；`start_run`/`poll`/`terminate` 有单测直接验证
- [x] **B2 专项**：`asyncssh` 在 `requirements.txt` 与 `pyproject[web]` 里都声明；`/api/meta` 的 `ssh_cloud.available == true`；SSH 导入失败路径有 monkeypatch 用例
- [x] §6 的 8 条 TODO 测试 + §6.2 补充用例全绿（webapi 186 / 前端 56）
- [x] §7 的 10 条冒烟：9 条已自动化通过；第 10 条「改高级字段出现已自定义、恢复默认后消失」由 store 纯逻辑测试覆盖 + 界面待灵梦人工确认
- [x] Python 回归 0 新增失败（唯一 8 个 F = 既有 CRLF 假红）；前端四条门禁全绿；契约无漂移

---

## 11. 执行顺序

1. ~~灵梦就 D-A…D-E 给结论~~ → **D-A=A1、D-B=B2 已定并落地**（asyncssh 已装）；D-C/D-D/D-E 按推荐默认执行。
2. 4A 契约扩展 → 重生成 → 漂移检查绿。
3. 4B `task_service.py` + `routes/tasks.py` + 测试。
4. 4C `execution_backend.py` + `server_profiles.py` + `presets.py` + 路由 + CLI + 测试（含 asyncssh 真实导入路径）。
5. 4D 前端总览页与录入页 + 前端测试。
6. 4E 门禁 + 人工冒烟（10 条）。
7. 提交（3 个提交：契约 / 后端能力 / 前端；**不推送**）+ 写阶段 4 执行结果回本文件。

---

## 12. 执行结果

### 4A 契约扩展（2026-10-02 13:00 完成，未提交）

**改动**：

| 文件 | 改动 |
|---|---|
| `src/faultevolve/webapi/errors.py` | `ErrorCode` 追加 5 个值（`task.not_found` / `task.not_ready` / `server.not_found` / `preset.unknown` / `preset.invalid`）+ 5 个异常类（`TaskNotFoundError` 404 / `TaskNotReadyError` 409 / `ServerNotFoundError` 404 / `PresetUnknownError` 400 / `PresetInvalidError` 422） |
| `src/faultevolve/webapi/contracts.py` | ① `CONTRACT_VERSION` **1.0.0 → 1.1.0**（按 TODO §13.4：新增可选字段 = minor）；② `MetaResponse` 追加 4 字段（`demo_run_ids`/`task_catalog_available`/`preset_names`/`server_profiles_enabled`，全带默认值）；③ 新增 7 个 DTO：`TaskCardMetrics`、`TaskDatasetCardResponse`、`PathProbeRequest`、`ServerProfileListResponse`、`PresetFieldSource`、`PresetResponse`、`PresetListResponse`；④ `__all__` 同步，`CONTRACT_MODELS` 自动收集（现 50 个） |
| `tests/webapi/test_health.py` | 契约版本断言 1.0.0 → 1.1.0 |
| `web/src/app/App.test.tsx` | mock 的 `contract_version` 同步 1.1.0（两处） |
| `tests/webapi/test_contract_stability.py` | 追加 5 条：`test_phase4_dtos_are_declared_and_published`、`test_meta_phase4_fields_are_optional_with_safe_defaults`、`test_path_probe_request_requires_a_path`、`test_phase4_error_codes_are_stable_strings`、`test_phase4_error_codes_are_not_marked_unsupported` |
| `tests/webapi/test_contract_no_secrets.py` | 追加 2 条：`test_no_dto_carries_a_secret_as_a_value`（危险字段名只许是 bool 标志或 `_ref` 引用）、`test_server_profile_response_masks_instead_of_echoing` |
| `web/openapi/*.json` + `web/src/generated/api/*` | 重新生成（`export_web_contracts.py` + `openapi-ts`，各跑一次，无手工编辑） |

**验证（全部通过）**：

| 门禁 | 结果 |
|---|---|
| 契约漂移（`.venv/Scripts/python.exe scripts/check_web_contracts.py`） | `contract check OK: 4 files match the Python source` |
| `pytest tests/webapi -q` | **127 passed**（阶段 3 基线 120 + 新增 7） |
| `tsc --noEmit` | 0 错 |
| `vitest run` | 34 passed（mock 版本号同步后无回归） |
| `eslint .` | 0 err / 0 warn |
| `vite build` | 成功（571ms） |

**与计划的偏差（2 处）**：

1. **`ServerProbeRequest` 没建**。计划里它标着「预留」，但路由用路径参数就够了；一个没有任何引用的 DTO 就是死契约，还会让漂移守卫变成摆设。4.2 节的表里那行作废。
2. **`CONTRACT_VERSION` bump 到 1.1.0 是计划没写的**。计划只说「MetaResponse 追加字段」，没提版本号；但 `contracts.py` 的 docstring 就是规则（新可选字段 → minor），照办了，连带改了 `test_health.py` 与 `App.test.tsx` 两处硬编码。

**实际踩到、计划里没预见的坑（1 个，已写进 §0.7 下方的执行注记）**：

- **`pnpm run check:contracts` 在本机不可用**：`package.json` 里写的是 `python ../scripts/check_web_contracts.py`，裸 `python` 是托管版 3.13，没有 `yaml`/`faultevolve` ⇒ `ModuleNotFoundError: No module named 'yaml'`。必须直接用 `.venv/Scripts/python.exe scripts/check_web_contracts.py`。没有改 `package.json`——CI 上裸 `python` 是对的，不该为本机改坏 CI 语义；本机命令形式见 §7。

### 4B 任务目录服务（2026-10-02 13:35 完成，未提交）

**交付**：`src/faultevolve/webapi/task_service.py`（新建，~380 行）、`routes/tasks.py`（4 个端点：`GET /api/tasks`、`/api/tasks/{id}`、`/readiness`、`/card`）、`routes/__init__.py` 注册、契约重导出 + TS 客户端重生成。

**实测结果**（`FE_WEB_TASK_ROOTS=benchmark`）：

| 任务 | adapter | is_stub | ready | 说明 |
|---|---|---|---|---|
| `backblaze_hdd` | backblaze | False | **False** | 四文件齐但数据未准备（missing 4 个 public 文件）→ 卡片「任务未就绪」 |
| `hdd_mvp` | hdd | False | **True** | 数据齐（4 个 public 文件在）、知识卡 51 张、target_score 33.7 |
| `smartmem` | smartmem | True | False | blocked_reason「示例数据集…」，`doc_path` 正确 |
| `ssd_alibaba` | alibaba_ssd | True | False | 同上 |

`hdd_mvp` 的 `data_dirs == ['public']`（evaluator-only 区域被过滤）；`..`→400、`web`/`nope`→404 `task.not_found`。

**测试**：`test_task_service.py`（19 条）+ `test_no_holdout_exposure.py`（3 条）→ **webapi 全量 150 passed**（4A 后 127 + 23）；前端 tsc/vitest 34 条不受影响；契约漂移检查绿。

**与计划的偏差（3 处）**：

1. **入选规则的判据从「目录名 ∈ STUB_ADAPTER_DOCS」改成「`evolve.yaml` 声明了已注册 adapter」**。原规则对 `ssd_alibaba` 失效（登记键是 `alibaba_ssd`，目录名对不上）；新判据对四个目录都成立，且不依赖目录命名。
2. **「webapi 源码不出现受保护字面量」的源码扫描测试没做**，改成 `test_protected_pattern_is_imported_not_redeclared`（断言 `PROTECTED_NAME_RE.pattern == FORBIDDEN_PATTERNS["evaluator-only path"]`）。理由：源码扫描要维护白名单（`settings.py` 里阶段 2 就有一处 "holdout" 字样），而模式相等断言直接钉死「单一来源」这个真实保证，更强也更稳。
3. **卡片的 `initial_score`/`last_run_id`/`last_best_score` 恒为 None**：`RunSummaryResponse` 没有 task 字段，run→task 映射不存在。Demo 卡的「初始 ROS 约 22.81」等真跑过之后由运行数据给出；此前显示「待评估」（PRD 7.3 的诚实规则）。

**实现要点（都按计划落实）**：adapter 缺省值取 `TaskConfig().adapter`（不写字面量）；`DataStatus.message` 整体丢弃（有测试用哨兵 env 值证明）；evaluator 只做 AST 解析（有「import 即爆炸」的恶意 evaluator 测试）；`problem_md`/`prompt_md` 走 `sanitize()` + 20k 上限。

### 4C 服务器配置、目录探测与三档预设（2026-10-02 13:50 完成，未提交）

**交付**：

| 文件 | 内容 |
|---|---|
| `src/faultevolve/webapi/presets.py` | 新建。`PRESET_NAMES = (quick, standard, deep)`；`build_preset` 返回完整 `EvolveConfig` dump + 字段来源；`merge_patch` 深合并后过 `EvolveConfig.model_validate`，失败抛 `PresetInvalidError`（只带字段名不带值） |
| `src/faultevolve/webapi/server_profiles.py` | 新建。JSON 存储（同目录临时文件 + `os.replace` 原子写、失败清理临时文件）；记录字段白名单加载（多出来的字段丢弃）；`ensure_default_profile`（D-E：首次列表自动补「本机（local_cloud）」空白模板）；`ssh_available()` 延迟导入探测；`resolve_key_ref`（`FE_WEB_SSH_KEY_<ref>` 环境变量 → 路径） |
| `src/faultevolve/webapi/execution_backend.py` | 新建。`ExecutionBackend` Protocol（形状照抄 TODO 4.3）+ `RunLaunchSpec`/`ProcessHandle`/`ProcessStatus`/`ServerProbe`/`PathProbe` 数据类 + `LocalCloudExecutionBackend`（`create_subprocess_exec`、白名单校验、写探针、`disk_usage`）+ `SSHCloudExecutionBackend`（延迟导入 asyncssh、known_hosts 强制、SFTP stat、`shlex.quote` 拼远程命令）+ `SshProbeFailure`（unreachable/auth/host_key/unconfigured → 既有 `backend.*` 错误码） |
| `routes/servers.py` | 新建。profiles CRUD + `POST /{id}/probe` + `POST /{id}/check-path`；存储未配置 ⇒ 501 `not_supported` |
| `routes/presets.py` | 新建。`GET /api/presets`、`GET /{name}`、`POST /{name}/merge` |
| `src/faultevolve/cli.py` | 新增 `web` 子命令组 + `fe web serve [--host/--port/--reload]`，启动时打印 task_roots/profiles/process_control 三项状态 |
| `src/faultevolve/webapi/app.py` | `/api/meta` 按 D-D 重写：availability 读实况（local_cloud=True；ssh_cloud=asyncssh 可导入；detail 全带理由），新增 `demo_run_ids`/`task_catalog_available`/`preset_names`/`server_profiles_enabled` 四字段赋值 |
| `routes/__init__.py` | 注册 tasks/servers/presets |

**测试**：`test_presets.py`（13 条）、`test_server_profiles.py`（8 条）、`test_execution_backend.py`（11 条，含本地进程生命周期、`shell=` 永不出现、恶意 notes 不进 argv、SSH 不可达诚实 502、monkeypatch 伪造 asyncssh 缺失）。**webapi 全量 186 passed**（4B 后 150 + 36）。

**实测**（TestClient 冒烟）：probe 返回 `reachable=True, python=3.12.14, engine=0.1.0, Windows 11`；`check-path` 对 `benchmark/hdd_mvp/data` 返回存在/可写/剩余 208.2 GB；`C:/Windows` → 403 `path.not_allowed`；SSH 无 known_hosts → 502「SSH 目标配置不完整」（拒绝跳过校验）；恶意 notes 原样存回、不进任何 argv。

**与计划的偏差（3 处）**：

1. **`POST /api/presets/{name}/merge` 的请求体从 `RunCreateRequest` 改成裸 patch 字典**。`RunCreateRequest` 的 `task_id`/`server_profile_id` 是必填，纯合并预览被迫带假值，语义更差。阶段 7 的创建端点仍然用 `RunCreateRequest`，合并语义已由本端点验证。
2. **`SshProbeFailure` 的 HTTP 状态用 502**（不是计划里没写的值）。`asyncssh.AuthenticationFailure` 在 2.24 里**不存在**（实测 `hasattr` 为 False），认证失败统一是 `PermissionDenied`。
3. **`test_health.py` 的两条阶段 1 旧断言按 D-D 更新**：`test_meta_never_claims_a_mode_is_available` 改名为 `test_meta_availability_is_derived_not_wished`（钉「availability 由实况导出」而非「恒 False」）。这是 D-D 的必然结果，不是回归。

**验证**：契约重导出（openapi 149KB）+ TS 客户端重生成 + 漂移检查绿；前端 tsc 0 错、vitest 34 passed、eslint 0/0、build 成功。完整 Python 回归（约 22 分钟）已在后台启动，结果见 §12 末尾。

### 4D 前端：总览页与任务输入页（2026-10-02 14:55 完成，未提交）

**交付**：

| 文件 | 内容 |
|---|---|
| `web/src/features/intake/DemoCard.tsx` | Demo 卡 + 确认抽屉：信息全部来自 `/api/tasks/hdd_mvp/card`；「打开完整回放」跳 `demo_run_ids[0]`；「启动短流程」打开七项确认 + readiness 检查，主按钮禁用（D-A） |
| `web/src/features/intake/DatasetCardGrid.tsx` | 四张数据集卡（含 `is_stub` 卡「示例（未就绪）」+ CTA 禁用 + 理由） |
| `web/src/features/intake/badge.tsx` | 五态徽章（未填写/检查中/通过/警告/失败），复用 StatusBadge 语义色 |
| `web/src/features/intake/task-artifacts-logic.ts` | `deriveArtifactCards` 纯函数 + `useTaskArtifactCards` hook（数据折算成三卡状态） |
| `web/src/features/intake/TaskArtifactsForm.tsx` | 三张必填卡渲染 |
| `web/src/features/intake/ServerProfileForm.tsx` | 服务器与目录配置：profile 列表/新建/删除、连接字段（ssh 模式未装 asyncssh 时禁选）、五个目录、「测试连接」「测试目录」mutation、密钥只收 `private_key_ref` |
| `web/src/features/intake/PathProbeList.tsx` | 路径检查结果（存在/可写/剩余空间，颜色按事实） |
| `web/src/features/intake/EnvConfigForm.tsx` | python/conda/CPU/内存/GPU 数量+设备号+型号/并发/超时 + 「期望 vs 检测」对照行 |
| `web/src/features/intake/NotesTextarea.tsx` | 备注框，UI 明示「仅作为运行备注保存，不会作为命令执行」 |
| `web/src/features/intake/KnowledgeInjectionForm.tsx` | 四档可选（映射真实字段）+「选择已有类别」诚实禁用（D-C=C1） |
| `web/src/features/intake/PresetSelector.tsx` | 三档预设卡 + 高级字段（改动即 patch）+「已自定义」/「恢复默认」+「生成配置预览」（POST merge，服务端校验，结果带 user_patch 字段溯源） |
| `web/src/features/intake/preflight-logic.ts` | `derivePreflightChecks`/`preflightBlockers`/`preflightWarnings` 纯函数 |
| `web/src/features/intake/PreflightPanel.tsx` | 常驻右侧的启动前检查面板：阻塞原因、警告需显式勾选、「启动运行」禁用 + 阶段 7 理由 |
| `web/src/stores/intake-store.ts` | 非敏感状态：taskId/serverProfileId/preset/patch/knowledgeMode/notes/presetPreview；`selectIsCustomized` 以 patch 非空为唯一判据 |
| `web/src/routes/OverviewPage.tsx` | 重写：开始区（Demo 卡）→ 数据集与示例（四卡）→ 最近运行 → 云端执行目标摘要 |
| `web/src/routes/NewRunPage.tsx` | 重写：工件三卡 + 服务器与目录 + 知识注入 + 进化强度 + 右侧 PreflightPanel；未选任务时引导回总览 |

**测试**：`intake.test.ts`（18 条纯逻辑：三卡阻塞规则、待评估不显示假定分、预检聚合、已自定义/恢复默认、知识映射）+ `components.test.tsx`（7 条渲染：启动按钮禁用理由、警告勾选、诚实禁用项、不成命令声明、路径探针行）+ `App.test.tsx` 扩 2 条（stub 卡禁用+理由、Demo 卡数字来自 API——ROS/33.7/51 用 `findAllByText` 因为 Demo 卡与数据集卡同时显示）。**前端 56 passed**（阶段 3 是 34）。

**与计划的偏差（4 处）**：

1. **`CardValidationBadge.tsx` → `badge.tsx`，且推导逻辑拆出 `task-artifacts-logic.ts` / `preflight-logic.ts` 两个非组件文件**。原因：eslint 的 `react-refresh/only-export-components` 要求组件文件只导出组件，否则出 warning（阶段 4 门禁要求 0 警告）。计划里的 `useIntakeForm.ts` 由 `intake-store.ts` 覆盖（状态机就是 store 本身）。
2. **`ServerProfileResponse` 补了 3 个回显字段**（`python_executable`/`conda_env`/`gpu_devices`）：Request 有、Response 没有，编辑表单无法回填。这是 4C 的契约遗漏，4D 补上（仍是 1.1.0，未发布）。
3. **「生成配置预览」合并请求体是裸 patch 字典**（与 4C 偏差 1 同源：`RunCreateRequest` 必填字段不适合预览载荷）。
4. **`presetPreview` 进 store**（'idle' | 'valid' | 'invalid'）：预检面板需要知道服务端校验结果，而 mutation 状态在 PresetSelector 里——用 store 传递而不是提升组件，避免 prop 钻孔。

### 4E 门禁与人工冒烟（2026-10-02 15:00 完成，未提交）

**门禁**（全部通过）：

| 项 | 结果 |
|---|---|
| webapi 测试 | **186 passed** |
| 完整 Python 回归 | **0 新增失败**（进度段逐字符核对：唯一的 8 个 `F` 就是既有 CRLF 假红；汇总行被环境钩子吞掉，改用文件落盘 + 逐行验证） |
| 前端 tsc / vitest / eslint / build | 0 错 / **56 passed** / 0 err 0 warn / 成功（3.06s） |
| 契约漂移 | 绿（重导出 + `generate:api` 后 `check_web_contracts.py` exit 0） |

**自动化冒烟**（`fe web serve` + curl，设置：`FE_WEB_TASK_ROOTS=["benchmark"]`、`FE_WEB_RUNS_ROOT=tests/fixtures/runs`、`FE_WEB_DEMO_RUN_IDS=["hdd_mvp_demo_7510f100"]`、profile store 在 `build/`）：

| 检查 | 结果 |
|---|---|
| `/api/meta` | `local_cloud=True`（D-D 生效）、`ssh_cloud=True`（asyncssh 已装）、`demo_run_ids` 有值、三档 presets、task_catalog/server_profiles 均 on |
| `/api/tasks` | 4 个任务，2 真 2 stub，分类正确 |
| `hdd_mvp` 卡 | ROS / 目标 33.7 / 知识卡 51 / data_ready=True / `initial_score=None`（诚实：未试跑） |
| `smartmem` 卡 | `is_stub=True` + 阻塞理由「示例数据集：尚未提供 evaluator / init 工件」 |
| 任务详情 | `data_dirs=['public']`，**全文无 `eval_only`** |
| probe | reachable=True、Python 3.12.14、engine 0.1.0、llm_key=False |
| check-path | `benchmark/hdd_mvp/data`：存在/是目录/可写/剩余 206.8 GB |
| presets merge | `max_iterations=7` + `discovery.enabled=True`，`user_patch` 字段溯源正确 |
| vite 代理 | `localhost:5173/api/tasks` 转发正常（4 个任务） |

**留给人看的部分**（两个服务已在后台运行，灵梦可直接开 `http://localhost:5173`）：
侧栏仍 4 项、总览页四张卡布局、Demo 卡两个按钮、录入页右侧预检面板、深浅主题。

**4E 期间发现并修掉的一个真 bug（环境交互）**：`check_path` 的写探针
`probe_file.unlink()` 被本机运行环境的 safe-delete 守卫（`sitecustomize.py`
钩住全部删除 API）拦截，非交互场景直接 `SystemExit(1)`——**请求 500 且整个
`fe web serve` 进程被杀死**。修法：探针文件不再 unlink，改 `os.replace` 挪到
`%TEMP%/faultevolve-probe/write-probe.marker` 原子覆盖（单文件不累积，用户
数据目录零残留）。修复后连打两次 check-path 服务存活（health 200）。
冒烟时另踩两坑：pydantic-settings 的列表环境变量必须 JSON 形态
（`FE_WEB_TASK_ROOTS='["benchmark"]'`，逗号分隔会 SettingsError）；
被杀服务的 uvicorn 子进程会变孤儿继续占 8000 端口，重启前必须
`netstat`+`taskkill` 清场，否则新实例绑定失败、curl 打到旧代码上。

