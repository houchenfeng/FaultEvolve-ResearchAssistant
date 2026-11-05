# 阶段 7 实施计划：运行创建与进程管理

> 分支：本地 `webui-p4` → 远端 `feat/webui-phase8`
> 契约：`1.5.0` → `1.6.0`（新增写端点）
> 前置：**PR #25 必须先合进 main**（阶段 7 从 main 切分支）

---

## 1. 范围

阶段 7 是 WebUI 第一次获得**写能力**。之前 26 个端点全是只读回放；本期要能真的
起一个进化进程、能看它的状态、能停它、服务重启后还能把它捡回来。

交付四件事：

1. **运行注册表**（`web_runs.sqlite3`）——Web API 自己的一份运行台账。
2. **`POST /api/runs`** —— 校验 → 就绪检查 → 起进程 → 返回 `202 + runId`。
3. **控制端点** —— 取消、从 run_id 恢复；**暂停按 TODO 7.4 明确不做**（见 §3 决策 1）。
4. **进程恢复 + 日志捕获** —— Web 服务重启后重新接管存活进程，或把死掉未完成的标 `interrupted`。

前端把 `NewRunPage` 那个**禁用**的「启动运行」按钮点亮（当前它写着
`运行创建与进程控制由阶段 7 交付`），并在工作台接上控制操作。

---

## 2. 侦察结论：后端已备到什么程度

**结论：比预想的好得多。执行后端已经写完并且单测过了，本期主要是「接线」。**

### 2.1 执行后端已实现（`src/faultevolve/webapi/execution_backend.py`，230 行测试 / 14 个用例）

文件头自己写明了范围边界：

> Phase-4 scope (decision D-A = A1): `start_run` / `poll` / `terminate` are implemented
> and unit-tested, but **no HTTP route exposes them**. Wiring them into the API is
> phase 7, together with the run registry and log capture.

已经满足的安全约束（有测试钉住）：

- `LocalCloudExecutionBackend` 用 `asyncio.create_subprocess_exec`（argv 数组），**永不 `shell=True`**。
- `SSHCloudExecutionBackend` 只传**固定字面量模板**给 SSH exec，profile 字段与自由文本一律不进命令。
- 路径全部过 `check_path` → `WebSettings.ensure_allowed`。
- SSH 凭据是**引用不是值**：`private_key_ref` 经 `FE_WEB_SSH_KEY_<ref>` 解析；
  **没配 known_hosts 视为「不可用」，不是「不安全可用」**。

### 2.2 契约 1.5.0 的端点里，写侧只差「运行」这一块

已有（26 个，全只读 + 3 个服务器写操作）：

```
GET  /api/runs                        GET  /api/runs/{id}
GET  /api/runs/{id}/{tree,events,scores,leaderboard,knowledge/cards,insights,discovery,artifacts,...}
POST /api/servers                     DELETE /api/servers/{id}
POST /api/servers/{id}/{probe,check-path}
POST /api/presets/{name}/merge        GET  /api/tasks/{id}/readiness
```

⇒ **缺的就是运行的生命周期**：创建、取消、恢复、追加轮次、运行态配置/摘要。

`server_profiles.py` 已经是完整 CRUD（`upsert_profile`/`delete_profile`），
`GET /api/tasks/{id}/readiness` 已经是「启动前检查」的服务端实现
（PRD §8 第五步的 11 项检查有依托）。

### 2.3 引擎侧：**没有暂停，但有 `--resume`**

- 全仓 grep `pause|pausing|safe.?point|graceful|checkpoint`（`cloud/engine.py` + `cli.py`）**命中 0** ⇒ 引擎没有安全点，暂停无法诚实实现。
- `cli.py:739` `evolve local` **支持 `--resume ID`**，`cli.py:795` 走 `engine.initialize(resume_id=...)` ⇒ **取消 + 恢复是可做的**。
- 真实启动参数面（`cli.py:evolve_local`）：

  ```
  evolve local <task_dir>
    [--mock] [--iterations/-n N] [--resume ID] [--target-score X]
    [--json] [--seed N] [--runs-dir PATH] [--artifacts-dir PATH] [--env-file PATH]
  ```

  ⚠️ 不设 `DASHSCOPE_API_KEY` 时 CLI 直接报错退出（`cli.py:780-781`，提示用 `--mock`）。

### 2.4 已埋好的开关

`WebSettings.enable_process_control: bool = False`（`settings.py:49`）已存在，
经 `app.py:255` 暴露成健康检查里的 `process_control_enabled`，**但目前没有任何行为**。
本期把它变成真开关（默认仍 `False`，见 §3 决策 4）。

`WebSettings` 还**没有运行注册表的路径字段** ⇒ 本期需要新增（建议 `run_registry: Path | None`）。

---

## 3. 决策（已拍板）

> **2026-10-03 灵梦拍板：5 条全部按下列「决定」执行。** 理由列保留，便于日后回溯为什么这么选。

| # | 议题 | 决定 | 理由 |
|---|---|---|---|
| 1 | **暂停怎么做** | 按 TODO 7.4：**不做暂停**。`POST /pause` 稳定返回 `409` + 明确原因，UI 把「暂停」标为未支持 | 引擎无安全点。伪造暂停 = PRD 22.1 第 8 条直接不成立（「运行状态与后端一致」）。给引擎加安全点是独立工程，会顶掉本期 |
| 2 | **Qwen/DashScope key 怎么给子进程** | 方案 (a)：**子进程继承 Web 服务进程的 env**；注册表只记 `env_file` 路径（不记 key） | TODO 7.2 明写「start command 的结构化参数，**不含密钥**」；PRD 22.2 第 1 条要求响应里不出现 key。远端 SSH 走目标机自己的 env |
| 3 | **「追加轮次」进不进本期** | **进** | PRD §16.1 明确列了「暂停、恢复、取消和追加轮次」，而 **TODO 7.4 没提**（文档分歧）；且 `--resume` 已支持，成本低 |
| 4 | **`enable_process_control` 默认值** | **默认 `False`**，靠环境变量开 | 默认关 = 误点不会真起进程；演示/答辩时显式打开。这也是「真实优先于完整」的安全侧落法 |
| 5 | **演示时是否开放「取消 / 追加预算」** | 开放「取消」，**追加预算仅在专家模式** | 对应 PRD §23 待确认项 2；答辩现场误点追加会让预算失控 |

**文档分歧记录（不藏）**：

- PRD §9.4 / §16.2 以 WebSocket 为主、§9.4 又说「不可用时降级轮询」；灵梦 2026-10-02 已拍板
  **统一 SSE** ⇒ 阶段 8 覆盖，**本期只做 REST，不碰推送**。
- PRD §16.1「追加轮次」vs TODO 7.4 未列 —— 即上表决策 3。

---

## 4. 实施分解

### 4A 后端：运行注册表 + 生命周期端点（契约 → 1.6.0）

新建 `webapi/run_registry.py`：

- 独立 `web_runs.sqlite3`，**不动 `fe.db` 的 DDL**（TODO 7.2）。
- 字段照 TODO 7.2：`run_id / execution_backend / server_profile_id / pid / status /
  task_dir / db_dir / artifacts_dir / start_args(结构化,无密钥) / created_at`。
- 本机 backend 存 pid；**SSH backend 不得只依赖本地 pid**（TODO 7.3 第 8 条）。
- 原子写（沿用 `server_profiles._atomic_write` 的做法，别另起一套）。

新端点：

| 方法 | 路径 | 语义 |
|---|---|---|
| `POST` | `/api/runs` | 校验 → 解析路径 → 生成 `EvolveConfig` 临时快照 → readiness → 建 run_id → 选 backend → 起进程 → **202 + runId**（TODO 7.3 九步） |
| `POST` | `/api/runs/{id}/cancel` | 终止进程，**保留已有制品**（TODO 测试第 13 条） |
| `POST` | `/api/runs/{id}/resume` | 用 `--resume <id>` 重起 |
| `POST` | `/api/runs/{id}/pause` | **恒 `409`** + `reason`（决策 1） |
| `POST` | `/api/runs/{id}/rounds` | 追加轮次（决策 3 若通过） |
| `GET` | `/api/runs/{id}/live` | 运行态摘要（注册表 + `fe.db` 读数），与回放态区分 |

安全硬约束（TODO 7.1，逐条要测试）：argv 数组、禁 `shell=True`；
SSH 只走固定模板 + `shlex.quote` 单参数；**恶意 host/user/path/补充说明不得形成命令注入**。

### 4B 后端：进程恢复 + 日志捕获

- **启动时接管**（TODO 7.5）：服务起来后扫注册表 → pid 存活则恢复监控 → 死亡且未完成标 `interrupted`。
- 日志捕获：`execution_backend` docstring 点名的 phase-7 范围；stdout/stderr 落 `runs_root/<id>/logs/`，
  响应里**只给逻辑名，不给绝对路径**（PRD 22.2 第 3 条）。

### 4C 前端：点亮启动按钮 + 工作台控制

- `NewRunPage`：`LAUNCH_DISABLED_REASON` 那段删掉，接 `POST /api/runs`；
  提交中禁用按钮防重复（PRD §8.1 第六步第 1 条）→ 成功跳 `/runs/$runId`。
- 工作台：取消 / 恢复 / 追加轮次；**暂停按钮显式标「未支持」并禁用**，不假装能点（PRD §9.3 vs TODO 7.4 的差）。
- 契约三次收尾照旧：`export_web_contracts.py` → `check_web_contracts.py`（exit 0）→ `generate:api`。

### 4D 门禁 + 冒烟 + 提交

- tsc / eslint 净；vitest 全绿；`pytest tests/webapi` 全绿；契约漂移 exit 0。
- **真实浏览器验收**（jsdom 测不出布局）：六步流程 → 点启动 → 落工作台；
  **用 `--mock` 起真进程**（零 token）验证整条链，别只测 mock 掉 HTTP 的单测。
- 提交分支 `webui-p4`，推 `feat/webui-phase8`，开 PR。

---

## 5. 风险

| 风险 | 影响 | 处置 |
|---|---|---|
| **起真进程 = 第一次真的能搞坏东西** | 高 | `enable_process_control` 默认关；路径全过 allow-list；验收一律 `--mock` |
| 子进程存活判断不可靠（pid 复用） | 中 | 存 `created_at` + 校验进程身份，不只信 pid |
| 契约漂移（1.6.0 新增 6 个写端点） | 中 | 三步收尾固定跑；`test_contract_stability` 会拦 |
| 服务重启时接管逻辑把已完成运行误标 `interrupted` | 中 | 以 `run_summary.json` 是否存在为准，不只信注册表状态 |
| 等待 `--resume` 的语义边界（追加轮次 vs 全新运行） | 低 | 追加轮次不篡改原始完成摘要（PRD §9.3） |

---

## 6. 不做清单

- **暂停**（引擎无安全点，决策 1）。
- **SSE / WebSocket 端点** —— 阶段 8。⚠️ **但传输无关的内核与设计已在本期预先完成**，见 §8；本期**不开端点、不碰前端推送**。
- **混合模式 / 纯本地 Worker**（PRD P2/P3）。
- **Playwright E2E 与视觉回归矩阵** —— 阶段 9。
- **给 `webui-ci` 接 CI** —— 灵梦 10-03「先不动」。

---

## 7. 决策记录

| 日期 | 决策 | 拍板人 |
|---|---|---|
| 2026-10-03 | 阶段 7 范围为「运行创建与进程管理」，前端点亮启动按钮 | 灵梦 |
| 2026-10-03 | 决策 1：**暂停不做**，`POST /pause` 恒 `409` + UI 标未支持 | 灵梦 |
| 2026-10-03 | 决策 2：Qwen key 靠**子进程继承服务进程 env**，注册表不存密钥 | 灵梦 |
| 2026-10-03 | 决策 3：**「追加轮次」进本期** | 灵梦 |
| 2026-10-03 | 决策 4：`enable_process_control` **默认 `False`** | 灵梦 |
| 2026-10-03 | 决策 5：演示开放「取消」，**追加预算限专家模式** | 灵梦 |
| 2026-10-03 | 前置已执行：**PR #25 合并进 main**（main → `6855610`），本分支从 main 切出 | 灵梦 |
| 2026-10-03 | 额外：**预先完成实时推送的准备工作**（§8） | 灵梦 |

---

## 8. 本期附带完成：实时推送的准备工作

灵梦 2026-10-03：「可以预先做一下 websocket 的准备工作」。

- 设计文档：`docs/plans/WEBUI_PHASE8_SSE_DESIGN.md`（传输选型、线上格式、游标补拉、
  12 类粗类 → 引擎真实类型映射、live DB → 制品收敛、阶段 8 待写测试）。
- 代码内核：`src/faultevolve/webapi/event_stream.py` —— **传输无关、刻意不接路由**，
  沿用 `execution_backend.py` 在阶段 4 的暂存方式。
- 测试：`tests/webapi/test_event_stream.py`，**40 条**；webapi 全量 234 → **274 passed**。

**两条留给阶段 8 的硬要求**（已写进设计文档，别忘了）：

1. PRD 要的「节点创建」独立事件**引擎里并不存在**（搭在 `iteration_complete` 里）——
   要么补事件，要么承认，**不许在文档里假装有**。
2. 补一条**事件类型清单漂移测试**：扫 `log_event` 字面量断言都在分类表内。
   否则引擎新增事件类型时前端会**静默漏掉**，时间轴只是"少了一块"，不报错。
