# 阶段 8 设计：实时事件通道（SSE）

> 状态：**设计已定，代码内核已落地，端点未开**
> 本文同时是「阶段 7 期间预先完成的实时推送准备工作」的交付说明。

---

## 1. 决策与冲突解决

| 议题 | 结论 | 依据 |
|---|---|---|
| 传输方式 | **SSE**，不用 WebSocket / Socket.IO | 灵梦 2026-10-02 拍板「统一 SSE」，覆盖 PRD §16 WebSocket 与 §19 Socket.IO 的分歧 |
| 为什么 SSE 够用 | 事件是**单向**的（引擎 → 浏览器）；控制操作用 REST（阶段 7 已提供） | PRD §9.3 的控制操作全是有请求-响应的语义，不需要双向通道 |
| 端点 | `GET /api/runs/{run_id}/stream?after_id=123` | TODO §8.2 原文 |
| 线上格式 | `id: / event: / data:` 三段 + 空行 | TODO §8.2 原文（见 §3） |
| 断线补拉 | 浏览器自动带 `Last-Event-ID`，语义**等同** `?after_id=` | PRD §16.3 |
| 降级 | SSE 不可用时回落到已有的 `GET /api/runs/{id}/events?after_id=` 轮询 | PRD §9.4「WebSocket 不可用时降级为轮询」——我们把这句改成 SSE 版，**语义不变** |

**如果以后真要换 WebSocket**：本期内核是**传输无关**的（§2），换传输只需再写一个把
`SseFrame` 换成消息对象的适配器，游标/去重/分类都不动。所以这个决定不是单向门。

---

## 2. 本期已落地的准备工作（不需要起服务就能测的部分）

新增 `src/faultevolve/webapi/event_stream.py`，**刻意不接任何路由**——
和当初 `execution_backend.py` 在阶段 4 的暂存方式完全一致
（「已实现 + 已单测，但没有 HTTP 路由暴露」，等阶段 7 接）。

| 符号 | 作用 |
|---|---|
| `sse_frame(*, event_id, event_type, data)` | 单事件 → SSE 帧，逐字节对齐 TODO §8.2 |
| `heartbeat_frame()` | 保活注释帧 `: keep-alive`（注释**不会**触发前端 `onmessage`，避免幽灵事件） |
| `coerce_last_event_id(v)` | `Last-Event-ID` / 查询串解析 |
| `select_after(events, after_id)` | 游标语义（严格大于），与轮询端点**共用同一规则** |
| `split_page(selected, limit)` | 分页 + `has_more` |
| `SSE_MEDIA_TYPE` / `SSE_HEADERS` / `HEARTBEAT_INTERVAL_SECONDS` | 端点要用的常量 |

**测试**：`tests/webapi/test_event_stream.py`，**40 条**。webapi 全量从 234 → **274 passed**。

### 2.1 这些测试钉住的都是「会静默出错」的点

- **游标严格大于**：`after_id=2` 必须只回 `>2`。写成 `>=` 会让重连的客户端收到重复事件。
- **垃圾游标不能被当成 0**：`coerce_last_event_id("abc")` → `None`（= 从头补拉），
  绝**不能**退化成 `0`——那会让客户端拿着一个看似合法的游标，以为自己拿到的是完整时间线。
- **`id` 缺失就省略，不发 `id: 0`**：否则浏览器会把重连点记在一个从未存在过的游标上。
- **`has_more` 用切片前的长度算**：刚好填满一页时 `has_more=False`，否则前端会白等一轮。
- **帧尾必须有空行**——SSE 是靠空行派发事件的，少一个 `\n` 事件就永远不触发。
- **事件名只能是标识符** `[A-Za-z0-9_.-]`：这是唯一能被外部文本污染进帧的字段，
  现在换行/冒号/空格一律变 `_`，**任何名字都无法伪造帧边界**。
- **中文 payload 保持可读**（`ensure_ascii=False`），不变成 `\uXXXX`。
- **单个不可序列化字段不会打断整条流**（`default=str`）——运行中途流断掉比字段难看严重得多。
- **心跳是注释不是事件**：`event:` 一行都不能出现在心跳帧里。

---

## 3. 线上格式（TODO §8.2 原文）

```text
id: 124
event: iteration_complete
data: {"node_id":"n0","score":-22.45}

```

`data` 一律**单行**紧凑 JSON。若载荷仍含裸换行（正常路径不可能，因为
`json.dumps` 会转义），会按 SSE 规范拆成多条 `data:` 行，而不是原样吐出——
一条裸换行会提前终止帧，剩下的内容会被当成新的字段解析。

---

## 4. 游标与补拉：两条路径必须同一语义

| 场景 | 客户端动作 |
|---|---|
| 首次进入 | `GET .../stream`（不带游标）→ 从最早事件开始 |
| 断开重连 | 浏览器自动带 `Last-Event-ID: <最后收到的 id>` → 只收之后的事件 |
| SSE 不可用 | `GET .../events?after_id=<最后收到的 id>` 轮询（阶段 7 已可用的端点） |
| 重复投递 | 前端按 **事件 id** 去重（PRD §16.3「同一事件重复投递不会产生重复节点」） |

`select_after` 就是为「轮询与流不会各写一套规则」而存在的。**阶段 8 应把
`replay_service.events_page` 也切到它上面**，让两条路径物理上共用一份实现
（本期没动 `replay_service`，避免在阶段 7 中途改动阶段 2 的既有行为）。

---

## 5. 事件分类：PRD 的 12 类是**粗类**，引擎吐的是**细名**

PRD §16.2 列了 12 类，但引擎实际发出的是细粒度的类型名。**这不是一一映射，
前端要按「粗类 → 具体类型集合」处理**，不要去凑一一对应。

已核实的真实类型（AST 扫描 `log_event(...)` 字面量 + grep 交叉验证）：

| PRD §16.2 粗类 | 引擎真实类型（已核实） |
|---|---|
| 运行状态改变 | `run_finished`、`objective_brief_failed`、`objective_spec_failed`、`value_mode_fallback`、`budget_stop`、`budget_stage_cap_hit`、`selection_failed`、`expand_redirected_budget` |
| 初始化完成 | `init_evaluated`、`smoke_data_built`、`smoke_data_build_failed`、`smoke_passed`、`smoke_fix_success` |
| 节点创建 | `iteration_complete`（携带新节点）—— 见下方 ⚠️ |
| 节点状态改变 | `analysis_complete`、`analysis_failed`、`precheck_fix`、`perf_self_fix_success`、`llm_error` |
| 评估开始/完成 | `init_evaluated`、`iteration_complete` |
| 迭代完成 | `iteration_complete` |
| 最佳节点改变 | 由 `iteration_complete` 的 `best_node_id`/`best_score` 字段承载 |
| Qwen 调用状态 | `llm_error`、`discovery_llm_error` |
| 洞察提取 | `claim_proposed`、`claim_graded`、`claim_tested`、`claim_sandbox_failed`、`claim_sandbox_finished`、`claim_stats_started`、`claim_stats_finished`、`card_promoted`、`card_rejected`、`mechanism_card_promoted` |
| claim/机制/锦标赛更新 | `discovery_round_started`、`discovery_controls`、`discovery_controls_failed`、`tournament_preregistered`、`tournament_skipped`、`tournament_no_fresh_slice` |
| 预算更新 | `budget_stop`、`budget_stage_cap_hit` |
| 运行完成或失败 | `run_finished`、`discovery_error`、`discovery_skipped`、`discovery_jev_entailment_unavailable` |

⚠️ **两个必须由阶段 8 落实的诚实性要求**：

1. **「节点创建」没有独立事件类型**——它搭在 `iteration_complete` 里。
   PRD 要的独立事件当前**不存在**。要么阶段 8 在引擎补一个 `node_created`，
   要么前端承认「一次迭代即可产生节点」，**不许在文档里假装它存在**。
2. **必须加一条「类型清单漂移测试」**：把 `log_event` 的字面量扫出来，
   断言每一个都在分类表内。否则引擎以后新增事件类型，前端会**静默地不认识它**
   ——这类漏事件不会报错，只会让时间轴看起来少了东西。

---

## 6. 数据来源分两段（TODO §8.1 / §8.3）

**运行中**：`tree.json` / `events.jsonl` 可能还没写出来 ⇒ 读 `fe.db`：

| 表 | 用途 |
|---|---|
| `event` | 按自增 id 增量查询（游标来源） |
| `node` | 节点快照 |
| `experiment` | 状态与最佳分数 |
| `llm_call` | 成本 |

硬约束：**只读连接 + busy timeout**，不得阻塞引擎写入
（沿用 `webapi/sqlite_ro.py` 的既有姿势，别新起一套）。

**收到 `run_finished` 后收敛**（TODO §8.3 五步）：停止轮询 live DB → 等制品写完 →
重读稳定制品 → 发 `snapshot_ready` → 前端使相关 Query 失效并重新获取。

---

## 7. 其余约束

- **心跳**：`HEARTBEAT_INTERVAL_SECONDS = 15`，靠代理层不要因为长时间无字节而掐断连接。
- **多运行隔离**：同时观察两个运行不能串事件 ⇒ 事件必须带 `runId`，前端按 run 分键（阶段 8 测试项）。
- **缓冲**：`X-Accel-Buffering: no` + `Cache-Control: no-store`，否则流会被缓冲成「看起来死了」。
- **payload 一律先过 `sanitize_value`**（沿用 `replay_service._event_response` 的做法），
  这是保证 key / 绝对路径不进流的**唯一**关口。

---

## 8. 阶段 8 还要写的测试（TODO 原文 7 条）

`after_id` 补拉 / 重复事件去重 / SSE 断线重连 / SQLite busy / 运行结束切换快照 /
同时观察两个运行不串事件 / payload 脱敏。

**外加本文提出的两条**：事件类型清单漂移测试；`Last-Event-ID` 与 `?after_id=` 语义等价的对照测试。

---

## 9. 明确不做（本期与阶段 8 的边界）

- **本期不开端点、不写生成器、不碰前端**——只交付内核 + 测试 + 本文档。
- 混合模式 / 纯本地 Worker（PRD P2/P3）。
- 给 `webui-ci` 接 CI（灵梦 10-03「先不动」）。
