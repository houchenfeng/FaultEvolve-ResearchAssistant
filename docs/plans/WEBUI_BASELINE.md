# FaultEvolve WebUI — 阶段 0 基线

> 版本：v1.0
> 日期：2026-10-02
> 分支：`feat/webui-p0` @ `9f647ee`（`main` = `origin/main` = `9f647ee`）
> 对应任务书：`docs/plans/FRONTEND_IMPLEMENTATION_TODO.md` §3
> 对应产品文档：`docs/design/05-前端PRD.md`

本文档固定「开工前的环境与测试基线」。**后续所有阶段都以本文档记录的数字为对照基准：只允许不新增失败，不允许用「调整基线」的方式让红灯变绿。**

---

## 1. 工具链基线（实测，非推测）

| 组件 | 版本 | 位置 / 调用方式 |
|---|---|---|
| Python（仓库虚拟环境） | **3.12.14** | `<repo>/.venv/Scripts/python.exe` |
| 虚拟环境创建者 | **uv 0.12.5** | `.venv/pyvenv.cfg` 记录；**该 venv 内没有 pip 模块** |
| uv | 0.12.5 | `C:/Users/A/.local/bin/uv.exe` |
| pytest | 9.1.1 | `.venv/Scripts/python.exe -m pytest` |
| pydantic | 2.13.5 | — |
| httpx | 0.28.1 | — |
| numpy | 2.5.3 | — |
| lightgbm | 4.7.0 | — |
| typer | 0.27.2 | — |
| Node.js | **22.22.2** | 托管版 `C:/Users/A/.workbuddy/binaries/node/versions/22.22.2-3/node.exe`（已在 PATH） |
| npm | 10.9.7 | 同上目录 `npm.cmd` |
| corepack | 0.34.6 | 同上目录 `corepack.cmd` |
| pnpm | **9.15.9** | 见 §3，**必须用绝对路径 `pnpm.CMD` 调用** |
| 引擎 CLI | `fe` 0.1.0 | `.venv/Scripts/python.exe -m faultevolve.cli`（`fe.exe` 亦可用） |

`fe` 可用子命令：`report` / `analyze` / `doctor` / `evolve` / `judge` / `discover` / `data`。

---

## 2. 依赖安装方式（venv 内没有 pip，这一步必须先知道）

`.venv` 由 **uv** 创建，因此：

```bash
# 这条会失败：No module named pip
.venv/Scripts/python.exe -m pip install <pkg>
```

正确装法（二选一）：

```bash
# 推荐：用创建该 venv 的 uv
"C:/Users/A/.local/bin/uv.exe" pip install --python .venv/Scripts/python.exe <pkg>...

# 备选：先给 venv 补 pip
.venv/Scripts/python.exe -m ensurepip --upgrade && .venv/Scripts/python.exe -m pip install <pkg>...
```

`pyproject.toml` 已新增 WebAPI 依赖组（阶段 0.3 交付）：

```toml
[project.optional-dependencies]
web = [
    "fastapi>=0.115",
    "uvicorn>=0.30",
    "pydantic-settings>=2",
]
```

可复现安装命令：

```bash
"C:/Users/A/.local/bin/uv.exe" pip install --python .venv/Scripts/python.exe -e ".[web,dev]"
```

---

## 3. pnpm 基线（本机踩坑最多的一条，务必照抄）

### 3.1 四个已探明的障碍

| # | 现象 | 结论 |
|---|---|---|
| A | `registry.npmjs.org` 用 curl 能返回 200，但在 **Node 的 fetch 栈里直接 `UND_ERR_CONNECT_TIMEOUT`** | Node 侧必须走镜像 `registry.npmmirror.com` |
| B | `corepack prepare pnpm@9 --activate` 直接报 fetch 失败 | 需要 `COREPACK_NPM_REGISTRY=https://registry.npmmirror.com` 才能完成首次拉取 |
| C | corepack 生成的 **bash shim `pnpm` 路径错乱**：报 `Cannot find module 'c:\c\Users\A\...'` | **禁止用裸 `pnpm`**，一律用绝对路径 `pnpm.CMD` |
| D | 不指定版本时 corepack 会去解析 `latest`（实测要下 pnpm **12.8.1**） | 必须在 `package.json` 里**钉死版本**，否则每次调用都要联网 |

### 3.2 固化后的正确配方

1. corepack 缓存已放到 corepack 的**默认位置** `C:/Users/A/AppData/Local/node/corepack`
   （内含 `v1/pnpm/9.15.9`）。放在默认位置后**不再需要**设置 `COREPACK_HOME`。
2. `web/package.json` 必须包含：

   ```json
   { "packageManager": "pnpm@9.15.9" }
   ```

   钉死版本后，shim 直接命中缓存，**离线也能启动**。
3. 调用方式固定为绝对路径，且**必须先 `cd web`**：

   ```bash
   PNPM="C:/Users/A/.workbuddy/binaries/node/versions/22.22.2-3/pnpm.CMD"
   cd web
   "$PNPM" -v              # → 9.15.9
   "$PNPM" generate:api    # → @hey-api/openapi-ts v0.99.0
   ```

   不要用 `"$PNPM" --dir web <script>`：corepack 是按**当前目录最近的
   `package.json`** 选版本的，`--dir` 只改 pnpm 的运行目录、不改 corepack
   选版本的位置。详见 §3.4。
4. 安装依赖必须带镜像（或在 `web/.npmrc` 写 `registry=https://registry.npmmirror.com`）：

   ```bash
   "$PNPM" add <pkg> --registry https://registry.npmmirror.com
   ```

### 3.3 实测证据

```
# 钉版本 + 不设任何环境变量
$ "$PNPM" -v
! Corepack is about to download https://registry.npmjs.org/pnpm/-/pnpm-9.15.9.tgz
9.15.9                     ← 命中缓存，rc=0

# 真实安装
$ "$PNPM" add is-odd --registry https://registry.npmmirror.com
+ is-odd 3.0.1
Done in 1.4s using pnpm v9.15.9     ← rc=0
```

---

### 3.4 `pnpm --dir web` 为什么必然失败（2026-10-02 实测）

从**仓库根目录**调用时，根目录没有 `package.json`，corepack 无从得知该用哪个
pnpm 版本，于是去解析 `latest`：

```bash
$ cd <repo>                     # 根目录，无 package.json
$ "$PNPM" -v
! Corepack is about to download https://registry.npmjs.org/pnpm/-/pnpm-12.8.1.tgz
Downloading the pnpm 12.8.1 binary for win32-x64...
12.8.1                          # ← 拉的是 12.8.1，不是 9.15.9
```

这个 12.8.1 再被 `web/package.json` 里钉死的 `pnpm@9.15.9` 拦下：

```bash
$ "$PNPM" --dir web generate:api
  help: Align the "packageManager" field in package.json with
        "devEngines.packageManager", or invoke pnpm directly (without corepack)...
```

两个直接后果：

1. **每次从根目录调用都要联网**去下 12.8.1 的包（本次就是这样被拖到超时的），
   而 `cd web` 之后是纯缓存命中、离线可用。
2. `--dir` **不解决**这个问题——corepack 选版本只看「当前工作目录最近的
   `package.json`」，与 `--dir` 无关。

**结论（固化）**：所有 pnpm 调用一律 `cd web` 之后再执行；`package.json` 的
`packageManager` 字段继续钉 `pnpm@9.15.9`，它是 `cd web` 路线能离线命中的前提。

---

## 4. 测试基线

### 4.1 命令

```bash
cd <repo>
.venv/Scripts/python.exe -m pytest tests/ -q --no-header -p no:cacheprovider
```

### 4.2 结果（2026-10-02 实测）

**阶段 0 交付时（尚未加入 `tests/webapi/`）：**

| 指标 | 数值 |
|---|---|
| 收集 | **524** |
| 通过 | **516** |
| 失败 | **8** |
| 错误 / 跳过 | 0 / 0 |

**阶段 1 完成后（`tests/webapi/` 已加入，31 个新测试）：**

| 指标 | 数值 | 与阶段 0 的差 |
|---|---|---|
| 收集 | **555** | +31 |
| 通过 | **547** | +31 |
| 失败 | **8** | **±0（同一批 CRLF 假红）** |
| 错误 / 跳过 | 0 / 0 | ±0 |

**结论**：新增 31 个契约测试全部通过，**没有引入任何新失败**。失败进度图案
`FFFFFF.F.F`（第 4 行）与单独运行 `tests/test_hdd_protected_files.py` 得到的
`FFFFFF.F.F` 逐字符一致，即 8 个红全部来自 §4.3 那一处。

**阶段 2 完成后（`tests/webapi/` 增至 120 个测试，全量 644 收集）：**

| 指标 | 数值 | 与阶段 1 的差 |
|---|---|---|
| 收集 | **644** | +89 |
| 通过 | **636** | +89 |
| 失败 | **8** | **±0（仍是 §4.3 那 8 个 CRLF 假红）** |
| 错误 / 跳过 | 0 / 0 | ±0 |
| 耗时 | 22 分 07 秒 | 明显变长，主要是本机 I/O |

**结论**：阶段 2 的 89 个回放/契约测试全部通过，**没有引入任何新失败**；
`grep '^FAILED'` 的结果里 8 行全部是 `tests/test_hdd_protected_files.py::test_hdd_mvp_files_byte_identical[...]`。

**阶段 3–5 合入 `main` 之后（2026-10-02 在 `main` = `d69bcd7` 的干净 worktree 上实测）：**

| 指标 | 数值 | 与阶段 2 的差 |
|---|---|---|
| 收集 | **735** | +91 |
| 通过 | **727** | +91 |
| 失败 | **8** | **±0（仍是 §4.3 那 8 个 CRLF 假红）** |
| 错误 / 跳过 | 0 / 0 | ±0 |
| 耗时 | 13 分 25 秒（805 s） | 比阶段 2 的 22 分钟**短**，说明该耗时主要是本机 I/O 波动，不是测试数量的函数 |

**这是当前对照基准**：后续阶段的全量回归仍以「失败恰好 8 个、且 8 个全在
`test_hdd_protected_files.py`」为门禁。取数用 `--junit-xml` 后解析
`tests / failures / errors / skipped` 四个属性，比数进度点可靠。

> **阶段 2 取数注意（实测）**：把 `pytest -q` 重定向到文件时输出是**块缓冲**的，
> 中途 `tail` 只能看到很久以前的一次 flush（本机曾出现"跑了 14 分钟仍显示 135 个点"
> 的假象）。**不要**据此判断卡住；等进程退出后读最后一行才可靠。
> 另外全量耗时从阶段 1 的 12–13 分钟涨到 **22 分钟**，安排后台任务时要留足时间。

> **取数注意**：本机运行环境下，pytest 末尾的汇总行会被宿主的 safe-delete 拦截器吞掉，
> 落盘日志里只剩进度点和 `exit=1`。可靠的取数方式是：
> ① `pytest --collect-only -q \| tail -1` 拿总数；② 对进度点做字符统计拿通过/失败数；
> ③ 或直接加 `--junit-xml`。
>
> 另注意：全量回归在本机约需 **12–13 分钟**；前台跑容易被中途终止（SIGTERM），
> 建议后台运行后读落盘日志。单文件跑 `tests/test_hdd_protected_files.py` 只需 0.07 秒，
> 是核对那 8 个红的最快手段。

### 4.3 8 个已知红（全部同一函数、同一原因）

全部是 `tests/test_hdd_protected_files.py::test_hdd_mvp_files_byte_identical[...]`：

```
benchmark/hdd_mvp/evaluator.py
benchmark/hdd_mvp/init.py
benchmark/hdd_mvp/problem.md
benchmark/hdd_mvp/prompt.md
benchmark/hdd_mvp/prepare_data.py
benchmark/hdd_mvp/knowledge/cards.jsonl
benchmark/hdd_mvp/data/public/train_labels.csv
benchmark/hdd_mvp/data/public/val_index.csv
```

### 4.4 归因证据（决定性，可复现）

| 检查项 | 结果 |
|---|---|
| 工作区文件 sha256 == 测试期望值 | **0 / 8** |
| `git show HEAD:<path>` 的 sha256 == 测试期望值 | **8 / 8** |
| `git config core.get core.autocrlf` | **true** |
| 仓库根存在 `.gitattributes` | **否** |

**结论**：测试拿「工作区的 CRLF 字节」去比「LF 冻结哈希」。同一份文件在 git blob 里
恰好等于期望值（8/8），说明**不是代码缺陷、不是上游问题、不是保护文件被改动**，
本机 `core.autocrlf=true` 且无 `.gitattributes` 导致的工作区换行符转换产物。
Linux / CI 上这 8 个是绿的。

### 4.5 规则（已与项目负责人确认）

**这 8 个红灯按基线记录，不修改、不豁免、不新增 `.gitattributes`。
后续阶段只保证「不新增失败」；完整回归仍以 524/516/8 为对照。**

（任务书 TODO §0.1 允许「只出现已有、已记录的环境跳过」，本项即属此类已记录项。）

---

## 5. WebAPI 依赖（阶段 0.3 交付）

已在 `.venv` 安装并验证 import 通过：

| 包 | 版本 |
|---|---|
| fastapi | 0.142.2 |
| uvicorn | 0.54.0 |
| pydantic-settings | 2.15.0 |
| starlette | 1.7.0 |

---

## 6. 回放 fixture（阶段 0.4 交付）

### 6.1 位置与内容

`tests/fixtures/runs/hdd_mvp_demo_7510f100/`（15 个文件）

| 内容 | 说明 |
|---|---|
| `run_summary.json` | 3816 B，116 字段 |
| `tree.json` | 2488 B，6 节点 / 5 边 |
| `events.jsonl` | 8135 B，19 行 |
| `fe.db` | 200704 B，`journal_mode=delete`（自带，无 sidecar） |
| `programs/*.py` | 6 个节点程序 |
| `discovery/controls.json`、`phenomena.json`、`preregistration.json` | 各 2 B（`{}`） |
| `discovery/discovered_cards.snapshot.jsonl` | 0 B |
| `logs/.gitkeep` | 源目录 `logs/` 为空，用占位文件保留目录 |

来源：`benchmark/hdd_mvp/.fe/runs/7510f100`（`fe evolve local --mock` 产物）。
源目录在 `.gitignore` 的 `.fe/` 之下，**不会入库**，故必须复制一份脱敏 fixture。

### 6.2 脱敏规则（定死）

1. **文本文件按 JSON 解析后再脱敏**：解析 JSON → 在**解码后的字符串**上匹配绝对路径 →
   把该字符串的 **JSON 转义形式**回填替换为 `<REDACTED_PATH>`。
   这样既保持原文件字节格式不变，又能避免 `"exist:\n"` 被误判成盘符路径这类假阳性。
2. 匹配的绝对路径形态：
   - Windows 盘符路径：`C:\...`（要求盘符字母前不是字母/数字，避免 `t:\n` 误伤）
   - POSIX 路径：`/(home|root|tmp|mnt|media|Users|var|opt|srv|etc)/...`
3. **重复路径一次性全部替换**（`str.replace`），不漏第二处。
4. `fe.db` 需处理 `event.payload_json` / `node.artifact_json` / `insight.text` /
   `llm_call.prompt_digest` 四列；改完必须 `PRAGMA journal_mode=DELETE` + `VACUUM`，
   以回收残留页并把文件做成自包含单文件。
5. **不拷贝** `fe.db-shm` / `fe.db-wal` / `fe.db-journal`。
6. 入库前必须扫描并零命中：绝对路径、`holdout` 字样、密钥形态字符串
   （`sk-…`、`AKIA…`、`DASHSCOPE_API_KEY=…`、`MIYANG_API_KEY=…`、`FE_API_KEY=…`）。

### 6.3 本次校验结果

```
redactions applied : 4      （events.jsonl 2 处 + fe.db 2 行）
remaining path hits: 0
scan clean: no absolute paths, no holdout mentions, no secret-like strings
```

表计数与源库一致（experiment 1 / node 6 / event 21 / llm_call 10 / card_stats 2），
`tree.json` 6 节点 5 边、`events.jsonl` 19 行也与源一致 —— 脱敏只动了路径，未损数据。

### 6.4 生成方法

脱敏+扫描脚本**刻意放在仓库外**（`<workspace>/tools/build_run_fixture.py`），
因为「新增仓库脚本」不在已确认的阶段 0 计划内。如需入库为
`scripts/build_run_fixture.py` 并接入 CI，需另行确认。

用法：

```bash
.venv/Scripts/python.exe <workspace>/tools/build_run_fixture.py <repo_root>
```

### 6.5 本 fixture 的已知局限（直接影响阶段 5 / 6 / 9）

| 局限 | 影响 |
|---|---|
| `improvement = 0.0`（`best_score == initial_score`），`stop_reason = max_iterations` | 结果页「提升」恒为 0，是**如实的平跑**，不适合演示「有改进」 |
| operator 只有 `init`(1) + `refine`(5)，节点状态全为 `done` | **无法测** crossover 第二父边、repair 边、invalid / 失败节点 → TODO §5.1、E2E-04 无料 |
| `node_parents` 表 0 行 | 同上，无第二父边 |
| `logs/` 为空 | TODO §2.5 第 3 条来源（`logs/{node_id}.log` 脱敏错误）**当前无数据** |
| `insight` / `claim` / `discovered_card` / `mechanism` / `match` / `certificate` / `theory` 全 0 行 | 节点详情「知识与记忆」、知识发现、机制辩论赛**只能测空状态** |
| `events.jsonl` 19 行 vs `fe.db` event 表 21 行 | 同一运行内两处事件数不一致，回放/live 一致性必须在阶段 2 显式定义优先级 |

> 已确认的后续动作：阶段 0 之后用 `fe evolve local --mock` 另造一份含 crossover + repair +
> invalid 节点的 fixture，补齐上表第 2、3、5 行。

---

## 7. 其它已知环境坑

| 坑 | 处理 |
|---|---|
| `find` 在本机报「参数格式不正确」 | 列目录一律用 python `os.walk` / `pathlib` |
| 原生 `git` 拒绝 MSYS 路径（`/c/...`） | 一律传 `C:/...` |
| `timeout` 是 Windows 的 `TIMEOUT.EXE` | 不要在 bash 里用 `timeout`，用命令自带的超时参数 |
| `cmd.exe` 被策略禁止从 bash 调用 | 用 `python` 或直接调用 `.exe` / `.cmd` 绝对路径 |
| pytest 汇总行被 safe-delete 拦截器吞掉 | 见 §4.2 |
| 复制 `fe.db` 会带出 WAL sidecar | 见 §6.2 第 4、5 条 |
| **`.git/refs/heads/` 下的嵌套目录会被清掉**（带斜杠的分支名不可用） | 见 §10，**分支名一律不要带 `/`** |

---

## 8. 阶段 0 验收命令

```bash
cd <repo>

# 0.1 测试基线
.venv/Scripts/python.exe -m pytest tests/ -q --no-header -p no:cacheprovider
#     期望：524 收集 / 516 通过 / 8 失败（8 个均为 test_hdd_protected_files.py 的 CRLF 假红）

# 0.2 pnpm
"C:/Users/A/.workbuddy/binaries/node/versions/22.22.2-3/pnpm.CMD" -v
#     期望：9.15.9

# 0.3 WebAPI 依赖
.venv/Scripts/python.exe -c "import fastapi, uvicorn, pydantic_settings; print('ok')"
#     期望：ok

# 0.4 fixture
.venv/Scripts/python.exe <workspace>/tools/build_run_fixture.py <repo_root>
#     期望：remaining path hits: 0 / scan clean
```

---

## 9. 阶段 1 契约产物（阶段 1 交付）

### 9.1 单一真源与四级镜像

```
src/faultevolve/webapi/contracts.py     ← 唯一真源：39 个 DTO
        │  FastAPI create_app().openapi()  +  catalog.py 的枚举/目录
        ▼
web/openapi/                            ← 四份已提交产物
  ├── faultevolve.openapi.json          （101,127 字节；48 个 component schema）
  ├── evolve-config.schema.json         （EvolveConfig.model_json_schema()）
  ├── engine-catalog.json               （枚举 / 适配器别名 / 事件类型 / 预设）
  └── ui-metadata.json                  （123 个叶子字段的 path/group/label_zh/advanced/preset_editable）
        │  openapi-ts v0.99.0
        ▼
web/src/generated/api/                  ← 55 个 TS 类型 + 2 个端点 SDK
```

`web/openapi/` 与 `web/src/generated/` **必须提交**（不是构建缓存）：前端要能在没有
Python 解释器、不联网的情况下构建，并且契约变更必须出现在 diff 里被人看见。

### 9.2 关键实现约束（都写成了测试）

| 约束 | 位置 | 若违反会怎样 |
|---|---|---|
| 39 个 DTO 必须全部进 `components/schemas` | `app.py::_install_contract_schemas` | FastAPI **只**导出路由引用到的模型；不主动注入的话 39 个里只有 2 个进 OpenAPI，前端拿不到类型 |
| 产物一律 LF 落盘 | 导出脚本 `newline=""` | `core.autocrlf=true` 会把工作区文件变 CRLF |
| 漂移比较按 **LF 归一化后**比内容 | `check_web_contracts.py::_normalise` | 逐字节比会在本机**永远假红**（同 §4.3 的病根） |
| 契约里不得出现 `holdout` / 密钥值 / 绝对宿主路径 | `tests/webapi/test_contract_no_secrets.py` | 违反 TODO 第 1358 行验收项与 PRD §385 |
| 事件类型目录必须与 `_log_event("...")` 字面量**双向**一致 | `tests/webapi/test_engine_catalog.py` | 多列一个 = 前端显示幽灵事件；少列一个 = 真实事件前端不认 |
| 运行状态目录必须与引擎源码一致 | 同上 | 已实现 5 个（`created/running/finished/crashed/failed`），PRD §9.2 的另外 6 个必须报 `not_supported` 而非伪造 |

### 9.3 阶段 1 验收命令

```bash
cd <repo>

# 1. 契约测试（TODO 点名的 3 个文件 + 引擎目录）
.venv/Scripts/python.exe -m pytest tests/webapi/ -q -p no:cacheprovider
#     期望：31 passed

# 2. 漂移门禁（CI 用的就是这一条）
.venv/Scripts/python.exe scripts/check_web_contracts.py
#     期望：contract check OK: 4 files match the Python source（exit 0）

# 3. 重新导出（改动 contracts.py / catalog.py 之后）
.venv/Scripts/python.exe scripts/export_web_contracts.py

# 4. 重新生成 TS 客户端（注意：必须先 cd web，原因见 §3.4）
cd web
"C:/Users/A/.workbuddy/binaries/node/versions/22.22.2-3/pnpm.CMD" generate:api
#     期望：@hey-api/openapi-ts v0.99.0 → ✓ ./src\generated\api · 4 files
```

### 9.4 本机已知的两处未处置项（不阻塞阶段 1，需你定夺）

1. **`web/package.json` 的 npm 脚本里裸写 `python`**。本机 `python` 是系统
   3.13.14，**没有 fastapi**，所以 `pnpm check:contracts` / `sync:contracts`
   在本机不可用；用 `.venv/Scripts/python.exe` 直接调脚本则正常。
   这三条脚本是按 TODO §1.5 的原文写的，语义上面向 CI（CI 里会装 `.[web]`）。
   如果要让本机也能跑，建议二选一：① 加一个零依赖的 `web/scripts/python.mjs`
   解析解释器；② 在仓库根建一个带 `packageManager` 的 `package.json`。
2. **TODO §1.6 的 CI 写法 `pnpm --dir web ...` 在本机必然失败**（§3.4 已实测）。
   同一写法在 CI 上也会失败，因为 corepack 选版本只看「当前目录最近的
   `package.json`」。建议把 §1.6 的 CI 三行改成 `cd web && pnpm ...`。
   → **已按此建议落地，见 §11。**

---

## 10. 【高优先级环境缺陷】带斜杠的分支名在本机不可用

**结论先说**：本机上**分支名不要带 `/`**。`feat/webui-p0` 这种名字会让分支 ref
在每次 `git commit` 之后被销毁，`git log` 随即报
`your current branch ... does not have any commits yet`。

### 10.1 症状

阶段 1 提交（`feat(web-contract): add generated frontend contract`）成功后：

```
$ git log --oneline -1
f9d1dad feat(web-contract): add generated frontend contract     ← 看起来一切正常

$ git rev-parse feat/webui-p0
fatal: ambiguous argument 'feat/webui-p0': unknown revision ...
$ git log --oneline -1
fatal: your current branch 'feat/webui-p0' does not have any commits yet
$ git status --short
A  .env.example        ← 整个仓库都变成"待提交"
A  AGENTS.md
...
```

提交对象本身**没有丢**，丢的是指向它的 ref。

### 10.2 证据（都在 `.git` 里，可复核）

| 证据 | 值 | 说明 |
|---|---|---|
| 提交对象存在 | `git cat-file -t f9d1dad` → `commit` | 内容没丢 |
| reflog 有记录 | `.git/logs/refs/heads/feat/webui-p0` 末行<br>`293702e → f9d1dad commit: feat(web-contract)...` | **ref 当时确实被写入了** |
| loose ref 缺失 | `.git/refs/heads/feat/` 目录不存在 | 之后被删掉 |
| 平行目录存活 | `.git/logs/refs/heads/feat/` 仍在 | 删的是 `refs/heads` 这一侧 |

### 10.3 复现（100% 稳定，与代码无关）

```bash
# 无斜杠 ref：成功且持久
$ git update-ref refs/heads/probe-plain <sha>      # → 文件存在，可解析
$ git switch probe-plain && git commit --allow-empty -m x
                                                    # → ref 正常更新为 aea6651

# 带斜杠 ref：静默失败
$ git update-ref refs/heads/probe/slash <sha>      # → 无报错，但目录不存在、无法解析
$ git update-ref refs/heads/feat/webui-p0 <sha>    # → 同上
```

* 在带斜杠分支上 `git commit`：commit 成功、分支名打印正确，**随后 ref 消失**。
* **不是"新目录建不出来"**：先用 bash `mkdir -p .git/refs/heads/feat` 预建目录并手写
  ref 文件，`git rev-parse` / `git log` 都能正常解析；但只要在该分支上再提交一次，
  整个 `feat/` 目录连同 ref 一起消失。
* **连存在多日的嵌套目录也会被清掉**：`refs/heads/qoder/kd-offline-replay-7af0`
  原本存在，一次 `update-ref` 之后整个 `qoder/` 目录消失。
* `git update-ref refs/heads/qoder/newprobe <sha>` **返回 rc=0（声称成功）**，但
  目录和文件都不存在 —— 属于静默假成功，不能用返回码判断。

### 10.4 已排除的原因

| 怀疑对象 | 排除依据 |
|---|---|
| git 钩子 | `.git/hooks/` 只有 `*.sample`；`core.hooksPath` 未设置 |
| 自动 gc / ref 打包 | `gc.auto=0`；`packed-refs` 里只有 `refs/remotes/origin/*`，无任何 `refs/heads/*` |
| 链接 worktree 重定向 | `git rev-parse --git-dir` / `--git-common-dir` 均为 `.git`；`.git` 是真实目录 |
| `GIT_*` 环境变量干扰 | `env | grep '^GIT'` 为空 |
| 换一个 git 就好 | **不成立**。PATH 上是 OpenClaw 内置 PortableGit `2.55.0.windows.5`；换成 WorkBuddy 的 PortableGit `2.55.0.windows.3` 行为**完全一致**。本机没有其它 git（`C:/Program Files/Git` 不存在，无 msys64 git） |

### 10.5 根因：**未确定**

上面每个嫌疑都被排除了，两套 PortableGit 表现一致，`refs/heads/` 平级文件
（`main` 等）读写完全正常，只有**嵌套路径**出问题，并且出现
"返回码为 0 但写入不生效"以及"非本次操作的目录也被清理"这两个用常规 git 行为
解释不通的现象。

**按本项目的资料可靠性规则：不硬猜。** 目前的判断只能是
"本机 git 工具链对 `.git/refs/heads/**` 嵌套路径的处理不可靠"，
具体触发机制需要换机 / 换 git 发行版继续定位。

### 10.6 处置（已采用）

1. 本地工作分支改用**无斜杠**名字：`webui-p0`（已建，指向 `f9d1dad`）。
2. 需要保持远端分支名 `feat/webui-p0` 时，用改名推送：
   `git push origin webui-p0:feat/webui-p0`。
3. 内容零丢失已核实：`git rev-parse HEAD^{tree}` 与 `git write-tree` 同为
   `5a3328c8c59b3b756c521571ba55d662eca208ea`，工作区干净。
4. **每次 commit 后必须核对** `git rev-parse HEAD`、`git status --short`
   和 `.git/refs/heads/` 的实况，不能只看 commit 有没有报错。

---

## 11. CI 门禁（`.github/workflows/web-contracts.yml`）

仓库此前**完全没有 `.github/` 目录**：TODO §1.6「CI 必须执行」与 §13.2「每次针对
`main` 的 PR 执行」都只存在于文档里，没有任何自动执行者。现已补上。

### 11.1 三个 job

| job | 内容 | 对应 TODO |
|---|---|---|
| `contracts` | Python 3.12 → `python scripts/check_web_contracts.py` | §1.6 漂移门禁 |
| `python-tests` | Python 3.12 → `python -m pytest tests/ -q` | §12.1 |
| `web` | Node 22 + pnpm，`working-directory: web` → `install --frozen-lockfile` → `generate:api` → `git diff --exit-code -- src/generated` → `test` → `lint` → `build` | §12.2 |

触发：`pull_request` → `main`、`push` → `main`、`workflow_dispatch`。
`permissions: contents: read`；同 ref 的旧运行由 `concurrency` 取消。

### 11.2 与 TODO §13.2 原文的三处刻意偏离

| 原文 | 实际写法 | 理由 |
|---|---|---|
| `pnpm --dir web test` 等 | `defaults.run.working-directory: web` | §3.4 实测 corepack 按 cwd 选版本，`--dir` 不改 cwd |
| `pnpm --dir web test:e2e --project=chromium` | **不含此步** | 仓库无 Playwright、无 `playwright.config.ts`（属阶段 9）。写一个跑不了的步骤只会永远假绿 |
| `pnpm --dir web generate:api`（仅执行） | 执行后追加 `git diff --exit-code -- src/generated` | `check_web_contracts.py` 只守 §9.1 的第一级镜像 `web/openapi/`；第二级镜像 `web/src/generated/` 此前无人守，加断言才算真门禁 |

依赖安装用 `requirements.txt` + `-e ".[web]"`，**不用** `-e ".[web,dev]"`：
`duckdb>=1.1` 只在 `requirements.txt` 里，而 `tests/test_backblaze_{prepare,task}.py`
用 `pytest.importorskip("duckdb")` 守卫——只装 extras 会让这两个测试**静默跳过**，
与 §4.2 记录的「跳过 0」基线不符。反向的 `respx>=0.21` 只在 pyproject 的 dev extra
里而**全仓无人 import**，是死依赖，故不装。

> 遗留（未在本阶段处置）：`requirements.txt` 与 `pyproject.toml` 的依赖清单不一致，
> `duckdb` / `respx` 各只在一侧。本阶段不改这两个文件，只按现状取并集。

### 11.3 本机验证结果（2026-10-02 实测）

在 `git worktree add` 出的干净副本（`main` = `d69bcd7`）上逐条执行 workflow 里的命令：

| 步骤 | 结果 |
|---|---|
| `scripts/check_web_contracts.py` | `contract check OK: 4 files match the Python source`，**exit 0** |
| `pnpm install --frozen-lockfile` | pnpm 9.15.9，11.4 s，锁文件未变 |
| `pnpm generate:api` + 与 blob 比对 | 16 个 `.ts` **全部字节一致（16/16）** ⇒ 生成器确定性成立，`git diff --exit-code` 门禁可用 |
| `pnpm test` | **13 files / 259 passed**（与阶段 5 基线一致） |
| `pnpm lint` | exit 0，0 error 0 warning |
| `pnpm build` | exit 0，664 modules；一条 chunk >500 kB 的非致命警告 |
| `pytest tests/webapi` | **211 passed / 0 failed / 0 skipped**，47 s |
| `pytest tests/`（全量） | **735 收集 / 727 通过 / 8 失败 / 0 错误 / 0 跳过**，805 s。8 个失败逐条核对即 §4.3 那 8 个 CRLF 假红，**没有新增失败**，符合 §4.5 的门禁 |

> `generate:api` 之后 `git status` 会把 16 个文件标成 ` M`，但 `git diff` 为空——
> 这是 `core.autocrlf=true` 下「工作区是 LF、git 期望 CRLF」的产物，与 §4.3 同一
> 病根。Linux runner 上不存在该转换，门禁按内容比对。

### 11.4 未能验证的部分（不得当成已通过）

**GitHub Actions 无法在本机运行**，以下三点只有推上去才知道：

1. `pnpm/action-setup@v4` 只给 `package_json_file: web/package.json`、不给 `version`
   时能否解析出 9.15.9（根目录无 `package.json`，这正是必须显式指定的原因）。
2. runner 上 `pytest tests/ -q` 是否真的全绿。§4.4 已论证那 8 个 CRLF 假红在 Linux
   上是绿的，但**未实测**。
3. 全量 pytest 在 runner 上是否落在 `timeout-minutes: 45` 内。本机实测 805 s
   （13 分 25 秒，735 个测试），余量充足；但 §4.2 曾记录过 22 分钟的一次，
   本机耗时波动大，45 分钟这个值是留了余量的估计而非实测。

### 11.5 为什么在独立 worktree 上做

本次开发时主工作树里有**另一个会话正在实时写入阶段 6 的未提交改动**
（`contracts.py` / `replay_service.py` / `web/openapi/*` / `types.gen.ts` 等 11 个文件）。
在主工作树里 `git switch` 会换掉共享的 HEAD，导致对方下一次提交落到本分支上。
故用 `git worktree add <path> -b webui-ci main` 取得独立 HEAD 与 index；分支名按
§10.6 保持**无斜杠**，推远端时再改名。

---

## 12. 阶段 B：补做任务详情页（2026-10-03 实测）

阶段 4 只给 `/overview/tasks/$taskId` 留了一个 `StagePlaceholder`，PRD §7.8 的四个区
（任务说明 / 评价契约 / 就绪检查 / 历史运行）没有实现。本节记录补做的结果与门禁读数。

### 12.1 落地内容

| 文件 | 说明 |
|---|---|
| `web/src/features/intake/task-detail-logic.ts` | 新增。四个区的纯推导逻辑，与组件分文件（react-refresh 约束） |
| `web/src/features/intake/TaskDetailPanel.tsx` | 新增。只吃 props、不发请求，渲染测试因此不必 mock SDK |
| `web/src/components/states/NotSupportedNotice.tsx` | 新增。与 `MissingArtifactNotice` 分工：那是「运行没产出该制品」（数据问题），这是「该能力当前版本没实现」（契约问题） |
| `web/src/routes/TaskDetailPage.tsx` | 改写（+64 / −9）。三个 `useQuery` 各自独立，逐个把 `{data,pending,failed}` 传给面板 |
| `web/src/features/intake/task-detail.test.ts` | 新增，29 个用例 |
| `web/src/routes/task-detail-page.test.tsx` | 新增，14 个用例。单独建文件而不加进 `App.test.tsx`：那一处属于另一条工作线正在改的文件 |

**未改动任何契约文件**：`contracts.py`、`web/openapi/*`、`web/src/generated/*` 一个都没碰，
所以本阶段不触发 §9 的三级镜像重新生成。

### 12.2 两处后端缺口按 §一.7 报「暂不支持」，而不是在前端补齐

两者都查证过源码，不是猜的：

1. **该任务的历史运行无法实现。** `RunSummaryResponse` 不含 `task_id`，`/api/runs` 无任务
   过滤参数；运行制品也不记录任务归属（`run_summary.json` 116 个字段里没有 task/adapter/
   dataset，`fe.db` 的 `experiment.config_json` 里没有任务路径）。后端
   `task_service.py:447-451` 自己写明了 `"Until the run→task link exists"`。
   ⇒ 区 4 渲染 `NotSupportedNotice` + 一个指向总览的链接，**不渲染空表格**冒充「没有历史」。
2. **评价契约没有对应 DTO。** 契约里只有 `TaskCardMetrics` 的五个字段；ROS 公式、分项指标
   （F1_p10 / AUPRC / R@FAR / 时间因子）、单候选时间预算都不在其中。Qwen 状态也不在任务
   就绪检查里，它只是服务器探测的 `llm_key_present`（`execution_backend.py:155`）。
   ⇒ 三项写「暂不支持」并给原因；**公式绝不在前端硬编码**，否则就成了第二个评分真源
   （PRD §2.2）。Qwen 那一行永远显示「未检查」，不代替服务器探测下结论。

`initial_score` 后端恒为 `null`、`score_source` 恒为 `"unavailable"`，故初始基线分按
PRD §7.3 显示「待评估」。测试里显式断言页面**不出现 `22.81`**——那是 README 里的真实
初始分，但这次响应里没有，就不能出现。

### 12.3 门禁读数

| 步骤 | 结果 |
|---|---|
| `pnpm typecheck` | exit 0 |
| 阶段 B 两个测试文件 | **43 passed / 43**（29 逻辑 + 14 路由） |
| `pnpm test`（全量） | **15 files / 302 tests：299 passed / 3 failed**。3 个失败全部在 `workbench-performance.test.ts`，见 §12.4 |
| `pnpm lint` | exit 0，无输出 |
| `pnpm build` | exit 0，667 modules（比 §11.3 的 664 多 3 个新源文件）；仍是那条 chunk >500 kB 的非致命警告 |
| `scripts/check_web_contracts.py` | `contract check OK: 4 files match the Python source`，exit 0 |
| `pytest tests/webapi` | **211 passed**，46.14 s（与 §11.3 的 211 / 47 s 一致） |
| `git diff --check` | rc=0，只有 §11.3 记过的 autocrlf 警告 |

未跑全量 `pytest tests/`：本阶段没有改动任何 Python 文件，而且本 worktree 没有自己的
`.venv`，venv 的 editable 安装把 `faultevolve` 解析到**主工作树**（实测
`faultevolve.__file__` → `Desktop\Self-evolution-optimization-agnet\src\...`），而主工作树
的 `contracts.py` 正被另一条工作线改写。此时跑全量 pytest 量到的是别人的未提交改动，
不能当成本阶段的门禁读数。`tests/webapi` 那 211 个通过说明对方目前的改动没有破坏本前端
所依赖的接口面。

### 12.4 新增的 3 个红灯：环境性，不是本阶段引入的

`web/src/features/workbench/workbench-performance.test.ts` 三条失败，两次全量跑 + 一次
只跑 `src/features/workbench` 子集，读数稳定：

| 用例 | 阈值 | 实测 |
|---|---|---|
| 1000 节点的 dagre 布局在 3 秒内完成 | 3000 ms | 超阈值（触发 `budget` 断言失败） |
| 布局是纯函数：同样输入两次调用坐标完全相同 | vitest 默认 5000 ms | **超时**（该用例调 `layoutTree` 两次，单次已 >3 s） |
| 1000 节点的全量筛选在 500 ms 内完成 | 1500 ms | **2568 / 2576 / 2597 ms** |

判定为**环境性**的四条证据：

1. 本阶段的改动（§12.1）不含 `features/workbench/` 下任何文件；该测试文件最后一次被改是
   `c9161ca`（阶段 5），已在 HEAD 里。
2. §11.3 今天早些时候在同一台机器上记录 `pnpm test` = **13 files / 259 passed，0 失败**，
   即当时这 13 条是通过的。
3. 三次读数几乎相同（2568 / 2576 / 2597 ms），且**只跑 workbench 子集、不跑本阶段新增的
   intake 测试时同样失败**⇒ 不是本阶段测试抢 CPU 造成的。
4. 三条都是 dagre 布局的**绝对墙钟阈值**，同一根因（1000 节点布局从约 500–800 ms 退化到
   约 2600 ms，约 3.2 倍）。该文件自己的头注释就写着「绝对阈值会因机器而异」。

**处理方式：不修改、不放宽阈值、不加 skip。** 按 §十三「不要为了绕过测试删除断言或跳过
测试」，也按 §4.5 对已记录红灯的同一态度。放宽阈值会让一个真实的复杂度退化失去告警——
而 §12.4 第 4 条恰好说明这里盯的就是 dagre 的绝对耗时。

> 后续在 CI（Linux runner）上这 3 条大概率是绿的：§11.3 已论证 runner 与本机性能不同源。
> 但**未实测**，不得当成已通过。若 runner 上也红，才说明是真的复杂度退化，届时应当去查
> `tree-adapter.ts` 的 `layoutTree`，而不是改阈值。

### 12.5 一个真实的纵深防御缺陷（本阶段自查发现并修掉）

`deriveReadinessRows` 原先把 `detail.data_dirs` **原样**拼进「数据」行的说明文本
（`已就绪（数据目录：…）`）。而 `deriveFileListing` 只过滤它自己那四个清单，于是
受保护名称仍会经由就绪检查表格渲染出来——`detectProtectedNameLeak` 报缺陷的同时，
名字就印在旁边，防御等于没有。

已修：

- 逻辑层对 `card.data_missing` 与 `detail.data_dirs` 都过一遍 `isProtected` 再拼文本；
- 面板层的 leak 计数改为 `detail` 四个清单 **+** `card.data_missing` 两个来源合并；
- 新增用例分别覆盖这两个来源，断言 `container.textContent` 不含 `holdout`。

这条符合 PRD §7.8 的内容安全边界与 §一.2（永远不打印 holdout 名称）。

## 13. 阶段 6.1：知识卡页（2026-10-03 实测）

TODO 6.1 / PRD 12.1–12.2。`/runs/$runId/knowledge` 原先是整页 `StagePlaceholder`，
本次只把 **12.2「知识卡」** 做实；12.3 现象层、12.4 机制层与辩论赛、12.5 理论与迁移
仍是占位，但占位文案改成只覆盖这三节，并写明「Qwen 论点与数据裁决分区显示」，
免得用户以为整页都没做。

### 13.1 落地内容

| 文件 | 说明 |
|---|---|
| `web/src/features/discovery/card-logic.ts` | 新增。卡片行推导、本地标记读写、采用汇总、空结果解释、暂不支持清单 |
| `web/src/features/discovery/KnowledgeCardList.tsx` | 新增。只吃 props、不发请求（同 §12.1 的分工） |
| `web/src/features/discovery/card-logic.test.ts` | 新增，28 个用例 |
| `web/src/routes/RunKnowledgePage.tsx` | 改写。两个查询：卡片清单 + 复用 `RunLayout` 已取的运行详情 |
| `web/src/routes/run-knowledge-page.test.tsx` | 新增，20 个用例 |

`web/src/features/discovery/` 此前不存在，与另一条工作线**零文件重叠**。
同样**未改动任何契约文件**，不触发 §9 的三级镜像重新生成。

### 13.2 三条会「骗人」的路径，各自的处置

1. **`adopted_count = null` 有两种相反的含义。** `replay_service.py:1307` 写的是
   `adopted_count=len(adopted_nodes) if adopted_nodes else None`——即 `fe.db` 可读但没有
   采纳节点时，它把 **0 写成了 None**。而 `fe.db` 不可读时 `_db_tables` 读不到
   `node_adopted_cards`，同样是 None。两者只能靠 `artifact_states.database` 区分：
   - 可读 ⇒ 显示 `0`（recorded=true）；
   - 缺失/不可解析 ⇒ 显示「未记录」+ 一条警告，明确「未记录表示读不到，不表示没有采纳过」。

   制品状态因此**不能压成布尔**。`RunKnowledgePage.toDatabaseState` 保留了第四个取值
   `unknown`（运行详情没取到 / 生成物落后于后端），此时不渲染任何关于 `fe.db` 的断言。

2. **`mean_delta = null` 不得显示 `0.000`。** `replay_service.py:1292` 自己注明
   「n == 0 表示从未有过有效采纳，均值是未知而不是零」。表格另给一列 `card_stats.n`
   用来解释「为什么没有均值」。

3. **空清单必须解释为什么空（PRD 12.1）。** `cardEmptyState` 分三种成因给不同文案：
   `fe.db` 不可读 ⇒「读不到这次运行的知识卡」；`unknown` ⇒「暂时无法判断」；
   `fe.db` 可读 ⇒「这次运行没有提供过知识卡」，并把 `run_summary.json` 的
   `cards_offered` 原值引出来。三种情况都**不渲染空表格**冒充「没有卡片」。

### 13.3 PRD 12.2 点名的五项字段按 §一.7 报「暂不支持」

`replay_service.py:1280-1317` 的 `knowledge_cards()` 只从 `fe.db` 的四张统计表
（`card_stats` / `branch_offered_cards` / `branch_refuted_cards` / `node_adopted_cards`）
与 `run_summary.json` 的 `card_stats` 拼卡片，**从不合并任务的知识目录**；
`contracts.py:895-899` 也写明 `claim` / `source_kind` / `conditions` 留空是故意的
——「保持 None 而不是填编造的文本」。任务侧只有 `/api/tasks/{id}/card` 的
`knowledge_card_count`（数量），没有卡片清单端点。

⇒ **卡片标题与类别、核心 claim、来源类型与来源链接、适用条件、先验或统计效用** 五项渲染
`NotSupportedNotice`，每项附源码级原因。同时：

- **不做**一个空的「分类筛选」下拉框冒充 PRD 12.2 的分类筛选（契约里没有类别字段），
  筛选只有卡片 ID 搜索 + 本地标记两项；
- 页面上**不存在任何外链**（`a[href^=http]` / `[download]` 均为 0），因为没有真实来源可指。

「信任 / 存疑 / 排除」按 PRD 12.2 只做浏览器本地标记：契约里没有写回端点
（`KnowledgeCardResponse.local_label` 只读，后端从不设置），存 `localStorage`
的 `fe.card-labels.{runId}`，与 `仅浏览器本地标记，不影响真实运行` 同屏出现。
存储内容属系统边界，读回时逐条校验（坏 JSON / 数组 / 未知标记值全部丢弃，不抛异常）。

### 13.4 门禁读数

| 步骤 | 结果 |
|---|---|
| `pnpm typecheck` | exit 0 |
| 阶段 6.1 两个测试文件 | **48 passed / 48**（28 逻辑 + 20 路由） |
| `pnpm test`（全量） | **17 files / 350 tests：350 passed / 0 failed** |
| `pnpm lint` | exit 0，无输出 |
| `pnpm build` | exit 0，669 modules（比 §12.3 的 667 多 2 个新源文件）；仍是那条 chunk >500 kB 的非致命警告 |
| `scripts/check_web_contracts.py` | `contract check OK: 4 files match the Python source`，exit 0 |
| `pytest tests/webapi` | **211 passed**，50.80 s |

两条命令都加了 `PYTHONPATH=<worktree>/src` 才跑：venv 的 editable 安装默认把
`faultevolve` 解析到**主工作树**（§12.3 已记），而主工作树的 `contracts.py` 正被另一条
工作线改成 `1.5.0`；不覆盖就会拿别人的未提交改动当本阶段的门禁读数。覆盖后 worktree 的
`CONTRACT_VERSION` 仍是 `1.3.0`，与 `web/openapi/*` 一致。

未跑全量 `pytest tests/`，理由同 §12.3（本阶段没有改动任何 Python 文件）。

### 13.5 §12.4 的 3 个红灯本次全绿——环境性判定得到实测支持

本次全量 `pnpm test` 中 `workbench-performance.test.ts` **13 passed / 0 failed**，
其中三条此前的失败用例读数为：

| 用例 | 阈值 | §12.4 实测 | 本次实测 |
|---|---|---|---|
| 1000 节点的 dagre 布局在 3 秒内完成 | 3000 ms | 超阈值 | **2046 ms** |
| 布局是纯函数：同样输入两次调用坐标完全相同 | 5000 ms | 超时 | **2877 ms** |
| 1000 节点的全量筛选 | 1500 ms | 2568 / 2576 / 2597 ms | **1194 ms** |

同一台机器、同一份 `features/workbench/` 代码（本阶段未改动其中任何文件），
单次布局从约 2600 ms 回到约 1000–1300 ms。这直接证实 §12.4 的判定：**是机器负载，
不是复杂度退化**。当时**不放宽阈值、不加 skip 的处置是正确的**——阈值本身没问题，
改了就会永久失去这条告警。

§12.4 的最后一条保留意见仍然成立：CI runner 上未实测，不得当成已通过。

## 14. 阶段 6.2/6.3：现象层、机制层与辩论赛、理论与迁移（2026-10-03 实测）

知识发现页的后三节（PRD 12.3–12.5 / TODO 6.2–6.3）。阶段 6.1 只做了 12.1–12.2 的知识卡，
这三节当时是 `StagePlaceholder`。本节记录做完了什么、以及**为什么其中大半只能报暂不支持**。

### 14.1 落地内容

| 文件 | 说明 |
|---|---|
| `web/src/features/discovery/discovery-logic.ts` | 新增。现象/沙箱/对照/证书/计数的纯推导，与组件分文件（react-refresh 约束） |
| `web/src/features/discovery/StatValue.tsx` | 新增。行内 `<span data-stat>`；与 `KnowledgeCardList` 里 `<td>` 版的 `StatCell` 分工 |
| `web/src/features/discovery/PhenomenonList.tsx` | 新增。只吃 props。PRD 说「每张现象卡」，故用卡片而非 18 列宽表 |
| `web/src/features/discovery/MechanismTournament.tsx` | 新增。只吃 props。三组计数 + 对照表 + 证书表 |
| `web/src/routes/RunKnowledgePage.tsx` | 改写。新增 `/discovery` 与 `/events` 两个请求；删掉整页 early return，改成按节内联降级 |
| `web/src/features/discovery/discovery-logic.test.ts` | 新增，43 个用例 |
| `web/src/routes/run-knowledge-page.test.tsx` | 20 → **40** 个用例 |

**未改动任何契约文件**：`contracts.py`、`web/openapi/*`、`web/src/generated/*` 一个都没碰。

### 14.2 关键调研：`DiscoveryResponse` 的六个列表在契约里没有任何字段保证

这一节的取舍全部由此推出，必须先记下来。契约里六个列表都是
`list[dict[str, Any]]`（TS 侧 `Array<{[key: string]: unknown}>`），**生成物给不出任何字段名**。
真实形状只能从写入方逐个读出来（`discovery-logic.ts` 的头注释里有完整出处）：

| 列表 | 真实形状 | 出处 |
|---|---|---|
| `phenomena[]` | `{claim_id, grade, payload}`，`payload` 是 `ClaimTestResult.model_dump()` 的 15 个键 | `pipeline.py:227,303`；`schemas.py:43-58` |
| `preregistration[]` | 只有 `{claim_id, hash}` | `pipeline.py:152` |
| `controls[]` | `ControlReport.model_dump()` | `schemas.py:61-66` |
| `certificates[]` | `Certificate.model_dump()` | `schemas.py:122-132` |
| `theories[]` | **恒为空**：无条件 `json.dump([], f)`，仓库里不存在任何 theory schema | `certificates.py:49-50` |
| `matches[]` | **恒为空**：构造器从不传 `matches=`；`MatchResult` 只写进 SQLite，没有端点读它 | `replay_service.py:1453-1468` |

所以每个读取器都容错，但**绝不补默认值冒充数据**：读不到就是「未记录」。

另外两处查证改变了做法：

1. `Grade` 枚举有**五个**值（`schemas.py:14-19`），比 PRD 12.3 列的四个多一个 `discovered`。
   多出来的这个既不能丢也不能并进 `confirmed`——「新发现」与「已确认」证据强度不同，
   合并就等于替后端下结论。
2. **沙箱错误是拿得到的**，但只能从事件流拿。失败的 claim 被 `pipeline.py:174-178` 写进
   SQLite 后就 `continue`，**从不进入 `phenomena.json`**。而 `catalog.py:41-43` 自己写明
   `EVENT_TYPES` 只用于打 `is_known_type` 标记、不做过滤，`replay_service.py:990-1003`
   对 payload 走 `sanitize_value`。⇒ `claim_sandbox_failed` 事件可用且已脱敏。

### 14.3 四条「不能撒谎」的处置

1. **沙箱失败单列一节，不当成判级。** 按 claim_id 与现象行做分区：`untested`（失败了、
   因此从未进入检验）单独渲染，并明写「没有统计结果，因此没有判级。它们既不是『已否证』
   也不是『未定』——检验根本没跑成」。合成一张表会让沙箱失败看起来像一种判级结果。
2. **`decisive_matches` 是数量，不是胜者。** PRD 12.4 要求胜负只能由预注册检验与
   evaluator/统计证据决定，而逐场证据没有暴露。`MechanismTournament` 开头就是一条
   `data-no-verdict` 声明，测试另外断言该节内**所有** `data-stat` 名都不匹配
   `/胜者|获胜|赢家|最优机制|推荐机制|排名/`。Elo 在 `tournament.py:221,291-292` 被算过
   但从不落盘，也**不用计数反推**。
3. **证书没有状态列。** `Certificate`（`schemas.py:122-132`）没有 `status` 字段；
   不从 `e_value` 或 `stat` 推一个「有效/失效」出来，那等于自设判级标准。
   测试断言表头不含「状态」、每行恰好 9 个 `<td>`。
4. **三种「空」分开解释。** `enabled === false`（运行目录下没有 `discovery/`，是配置选择
   不是失败）／`*_state === 'missing'`（文件从未被写出）／`available + []`（跑完了但一无所获，
   `_read_json_list` 的注释写明引擎用 `[]` 表示这个）。三者文案与下一步各不相同。

### 14.4 PRD 12.5 的「演示卡片」被明确拒绝——**待用户裁决**

PRD 12.5 允许「没有真实跨数据集结果时使用演示卡片，并标记演示数据」。本期**不做**，
理由写在 `THEORY_DEMO_DECLINED` 里并渲染到页面上：理论对象连 schema 都不存在
（`theories.json` 是硬编码的 `[]`），演示卡片将**没有任何一个字段来自真实结构**，
整张卡都是编的——这与 §一.7「不得实现虚假功能」直接冲突，而「标记演示数据」并不能让
一个全编造的对象变成可接受的交付物。

这是 PRD 与仓库规则的真实冲突，不是漏做。**需要用户拍板**：要么接受本节整节报暂不支持，
要么先在后端补 theory schema 与生成逻辑（那要动 `contracts.py`）。

### 14.5 本阶段自查/测试发现并修掉的四个缺陷

前三个是写 6.2/6.3 时自己引入或暴露的，第四个是**测试基础设施**的坑，值得单独记：

| # | 缺陷 | 处置 |
|---|---|---|
| 1 | `CiField` 把效应量 CI 与增量收益 CI 都写成 `data-stat="ci_low"/"ci_high"`，同页两个钩子重名 | 改成与 payload 键名一致（`ci_low` / `incr_ci_low`）。**是新增用例逼出来的** |
| 2 | `partitionSandboxFailures` 算出的 `matched` 桶从未渲染。若某个 claim 既有检验结果又记录过沙箱失败（按 `pipeline.py:174-178` 不该发生），矛盾会被静默丢掉一边 | 补 `data-sandbox-inconsistent` 一节，两边都列出来，并明写「不替后端判断哪一边才是真的」 |
| 3 | 事件流请求失败时页面静默地什么都不渲染，读起来就是「没有沙箱失败」——注释里警告过这件事，但注释阻止不了它 | 补 `data-events-unavailable`：「无法判断是否有 claim 在沙箱阶段失败。这不表示没有沙箱失败。」 |
| 4 | **测试落定信号选错，一次改动打红 31 个用例** | 见下 |

第 4 条的机理值得留在文档里，因为它会再犯：

6.1 时知识卡的 pending/error 是**整页 early return**，所以 `[data-card-summary]` 只在
请求落定后才存在，`waitLoaded` 拿它当信号是对的。6.2/6.3 为了让「fe.db 读不到」不再连带
抹掉现象层与辩论赛，把 early return 改成**按节内联降级**——`[data-card-summary]` 于是
三态都渲染，`waitLoaded` 立刻返回，31 个用例在 pending 阶段就读断言。

处置不是把 early return 改回去（那会重新引入「一个请求挂了整页消失」），而是给两节各加一个
**稳定的三态钩子** `data-cards-state` / `data-phenomena-state`，测试助手改成：
先断言钩子元素存在（路由是懒加载的，首帧整页都还没挂上），再断言它不等于 `pending`。
`waitPhenomena` 顺带返回落定后的状态，失败路径的用例可以直接断言 `'error'`。

> 教训：**把降级从整页改成按节内联时，必须同时检查所有以「元素存在」为落定信号的测试助手。**
> 内联降级会让原本只在成功态渲染的元素变成三态都渲染。

### 14.6 门禁读数

| 步骤 | 结果 |
|---|---|
| `pnpm typecheck` | exit 0 |
| 阶段 6.2/6.3 三个测试文件 | **111 passed / 111**（28 卡片逻辑 + 43 发现逻辑 + 40 路由） |
| `pnpm test`（全量） | **18 files / 413 tests：412 passed / 1 failed**，见 §14.7 |
| `pnpm lint` | exit 0，无输出 |
| `pnpm build` | exit 0，**673 modules**（比 §13.4 的 669 多 4 个新源文件）；仍是那条 chunk >500 kB 的非致命警告 |
| `scripts/check_web_contracts.py` | `contract check OK: 4 files match the Python source`，exit 0 |
| `pytest tests/webapi` | **211 passed**，23.53 s（与 §13.4 的 211 / 50.80 s 同一批用例） |
| `git diff --check` | rc=0，只有 §4.5 记过的 autocrlf 警告 |

两条 Python 命令同样加 `PYTHONPATH=<worktree>/src`（理由见 §13.4）。
未跑全量 `pytest tests/`，理由同 §12.3（本阶段没有改动任何 Python 文件）。

### 14.7 环境红灯第三次读数：仍是机器负载

全量跑时 `workbench-performance.test.ts` 的「1000 节点的全量筛选在 500 ms 内完成」失败，
实测 **1682 ms**（阈值 1500 ms）。**单独跑同一个文件：13 passed / 13，该用例 1220 ms。**

| 读数来源 | 全量筛选 | dagre 布局 |
|---|---|---|
| §12.4（阶段 B） | 2568 / 2576 / 2597 ms ✗ | 超阈值 ✗ |
| §13.5（阶段 6.1） | 1194 ms ✓ | 2046 ms ✓ |
| §14.7 全量 | **1682 ms ✗** | 2198 ms ✓ |
| §14.7 单跑该文件 | **1220 ms ✓** | 1426 ms ✓ |

判定为环境性的证据与 §12.4 相同，并且这次多了一条最直接的：**同一份代码、同一台机器，
全量跑 1682 ms、单跑 1220 ms**，差值来自并发抢 CPU，不来自代码。本阶段也没有改动
`features/workbench/` 下任何文件（`git diff --name-only HEAD` 只有两个 `routes/` 文件）。

**处理方式不变：不修改、不放宽阈值、不加 skip。** 这已经是第三次读数落在阈值附近上下浮动，
说明 1500 ms 这个绝对阈值对本机偏紧；但按 §十三「不要为了绕过测试删除断言或跳过测试」，
调整它需要一次独立的、有 runner 实测数据支撑的决定，不能顺手在功能阶段里做。



## 15 阶段 6.4：结果与报告 + 数据边界审计（PRD 13.1–13.5 / TODO 6.4）

### 15.1 交付内容

**结果与报告页**（`/runs/$runId/results`）：
- `RunResultsPage.tsx` 从占位符重写为真实路由，编排六个查询（detail / leaderboard / tree / artifacts / report / node）
- `use-results-data.ts` 提取查询逻辑，最佳节点缺失时不发节点详情请求
- 四节组件：`OutcomeSection` / `TopKSection` / `ComparisonSection` / `ReportSection`
- `results-logic.ts`：`outcomeRows`（11 行，每行标出处）、`metricRows`（按后端实际返回的键渲染，不预置名字）、`noiseVerdict` / `noiseSummary`（委托 `classifyNoiseBand`，不重判波动带）、`topKRows`（不重排后端排序）、`reportRows`
- 制品清单读不到时，下载入口一律显示「未知」而不是「不可下载」

**数据边界与审计页**（`/runs/$runId/audit`）：
- `RunAuditPage.tsx` 从占位符重写，三个查询（meta / artifacts / detail）
- `audit-logic.ts`：`deploymentRows` / `metaFacts`（八项固定标签，不含 nav_modules / preset_names）/ `artifactStateRows` / `boundaryRows` / `kindRows` / `scanProtectedNames`（只报数量，不渲染名字）
- `MetaFacts.tsx` / `AuditFacts.tsx` 两节有据内容 + 五项暂不支持
- 边界声明用「受控云端环境」，不宣称「零数据出域」

**共享模块**：
- `artifact-url.ts`：`artifactDownloadUrl(runId, artifactId)`
- `section-state.ts`：`SectionState` 三态类型与 `sectionState()` 推导函数
- `significance.ts`：新增 `classifyNoiseBand`，只判波动带，不看 `is_best`

### 15.2 关键纪律

1. **PRD 13.4 七项里只有两项有据**：当前部署模式（`MetaResponse.deployment_modes`）与制品边界（`ArtifactResponse`）。其余五项（数据区域 / 发送给 Qwen 的信息 / evaluator 白名单 / 错误脱敏状态 / 留出集是否被调用）没有任何端点支撑，必须报暂不支持。
2. **制品清单读不到 ≠ 不可下载**：`downloadable: null` 渲染为「未知（制品清单未取到）」，「不可下载」是后端的一个明确决定，前端无权替它下。
3. **最佳节点缺失 ≠ 分项指标为 0**：`metricsState === 'skipped'` 时渲染「未记录」，不显示 0。
4. **树读不到时波动判定节仍然渲染计数**：把整节换成错误面板会让人以为「没有波动判定这回事」，而真相是这一次没读到。
5. **禁止字段扫描只报数量**：`scanProtectedNames` 返回 `{scanned, leaked}`，名字本身不进入返回值，否则组件一旦渲染整个对象，页面上就有了 holdout 字样。
6. **`supported_transports` 是后端命名缺陷**：`app.py:221,230,243` 往里填的是 `[mode]`（模式名本身），不是传输方式。前端按字面名渲染，不改叫「传输方式」，否则把命名缺陷讲成了事实。

### 15.3 测试覆盖

| 文件 | 用例数 | 覆盖点 |
|---|---|---|
| `results-logic.test.ts` | 27 | 数值格式、13.1 结果总览、13.1 分项指标、13.3 波动判定、13.2 Top-K 候选、13.5 报告 manifest |
| `audit-logic.test.ts` | 22 | 部署模式、部署事实、制品状态、制品边界、制品分类、禁止字段扫描、PRD 13.4 口径 |
| `run-results-page.test.tsx` | 2 | 四节 + 审计入口 + 侧栏四项、最佳节点缺失时分项指标显示「未记录」 |
| `run-audit-page.test.tsx` | 3 | 边界声明 + 两节有据 + 五项暂不支持 + 返回结果页入口、边界声明用「受控云端环境」、禁止字段扫描只报数量 |

### 15.4 门禁读数

| 门禁 | 结果 |
|---|---|
| `pnpm typecheck` | exit 0 |
| `pnpm test` | **467 passed**（22 files） |
| `pnpm lint` | exit 0，无输出 |
| `pnpm build` | exit 0，**688 modules**（比 §14.6 的 673 多 15 个新源文件） |
| `scripts/check_web_contracts.py` | `contract check OK: 4 files match the Python source`，exit 0 |
| `pytest tests/webapi` | **211 passed**，43.91 s |

两条 Python 命令加 `PYTHONPATH=<worktree>/src`（理由见 §13.4）。
