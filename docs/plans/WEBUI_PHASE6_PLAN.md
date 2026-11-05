# 阶段 6 实施计划：知识发现与结果报告

> 计划写于 2026-10-02，基线 `main` = `d69bcd7`（含 PR #23 阶段 5）。
> 分支 `webui-p2`（本地无斜杠），推远端写 `feat/webui-phase6`。
> 本文件只写计划，**不含任何实现代码**。

---

## 1. 范围

TODO §9「阶段 6：知识发现与结果报告」四页：

| TODO | 页面 | 落点（见 §4C 的路由说明） |
|---|---|---|
| 6.1 | 知识卡 | `/runs/$runId/knowledge` 的「知识卡」标签 |
| 6.2 | 现象（claim test） | 同页「现象」标签 |
| 6.3 | 机制辩论赛 | 同页「机制辩论赛」标签 |
| 6.4 | 结果报告 | `/runs/$runId/results` |

**纯只读**。与阶段 5 同一条边界：暂停/恢复/追加轮次归阶段 7，WebSocket 归阶段 8。

---

## 2. 侦察结论：后端已备到什么程度

已实现 **25 个端点**（从 `web/src/generated/api/sdk.gen.ts` 读真实契约，不靠记忆），
阶段 6 需要的四个全在：

| 端点 | 状态 | 备注 |
|---|---|---|
| `GET /api/runs/{run_id}/knowledge/cards` | ✅ 可用 | 实测 **18 张卡** |
| `GET /api/runs/{run_id}/discovery` | ⚠️ 三个字段是死路 | 见 §2.2 |
| `GET /api/runs/{run_id}/reports/manifest` | ✅ 可用 | 报告文件清单 |
| `GET /api/runs/{run_id}/artifacts` | ✅ 可用 | 制品清单 + 下载 |
| `GET /api/runs/{run_id}` | ✅ 可用 | `budget` 22 键挂在 `RunDetailResponse` 上 |

### 2.1 知识卡：唯一有真实数据的页

实测 `hdd_mvp_demo_7510f100`：**18 张卡**，`KnowledgeCardResponse` 15 个字段。
但**绝大多数字段是 `null`**（第一张卡实测）：

```
card_id: 'E01'          source_kind: None    source_detail: None
claim: None             conditions: None     offered_count: 2
adopted_count: None      refuted_count: None  invalid_count: None
mean_delta: None         adopted_iterations: []   adopted_node_ids: []
local_label: None        affects_run: False
```

⇒ **契约字段 ≠ 数据可得性**。UI 必须把「有值 / 未记录 / 不适用」三态分开显示，
这是 TODO 6.1 的核心难点，不是把 null 渲染成 0。

### 2.2 机制辩论赛：发现三个后端死路

这是本阶段**唯一的后端缺陷**，逐条实测（不是读代码猜的）：

| 契约字段 | 实际情况 | 证据 |
|---|---|---|
| `theories` | 读 `theories.json`，而 `discovery/certificates.py:50` **硬编码 `json.dump([], f)`** | 真数据在 `mechanisms.json`，被丢弃 |
| `matches` | `replay_service.py` 里 **grep 零命中**，从没赋值 | 契约声明了字段，实现不填 ⇒ 永远 `[]` |
| `certificates` | 读 `certificates.json`，**这个是对的** | 但 demo 里同样 0 条 |

而 `mechanisms.json` 里是有真数据的 —— 引擎侧 `Mechanism` 数据类字段完整：
`id / claim_id / role / title / nodes / edges / predictions / patch_count / status / parent_id`。
`role` 有 6 种（`claim`/`llm_rival`/`confound`/`artifact`/`censor`/`other`），
**这正是 TODO 6.3「主张 / 对手机制 / 正反论点」分区显示的依据**。

### 2.3 现象页：state 与内容不一致

demo 运行实测：`enabled=True`、四个 `*_state` 全是 `ArtifactState.AVAILABLE`，
但 `phenomena` / `controls` / `preregistration` / `discovered_card_ids` **全是 `[]`**。

引擎侧数据类（`discovery/schemas.py`）字段齐全，TODO 6.2 要的每一项都有来源：
- `Claim`：condition / feature_code / outcome / direction / scope / falsifier / grade / status
- `ClaimTestResult`：n / n_pos / n_neg / effect / ci_low / ci_high / p / e / direction_ok / temporal_ok
- `Grade` 五档：`confirmed` / `revised` / `discovered` / `refuted` / `undetermined`

⚠️ **`state=AVAILABLE` + 空数组是矛盾的**，UI 不能信 `state` ——
TODO §9 测试明确要求「discovery disabled 空状态」与「manifest 字段缺失」两条，
说明空态处理是本阶段的重点。

---

## 3. 三个待拍板决策

| | 问题 | 建议 |
|---|---|---|
| **D-A** | `theories` 死路怎么修 | **后端改读 `mechanisms.json`**，并把 `matches` 从 `tournament_results.json` 补上。契约升 1.3.0 → **1.4.0**。理由：TODO 6.3 明写要显示"主张/对手机制/正反论点/数据裁决"，没有数据这三样都画不出来 |
| **D-B** | 6.2/6.3 真实数据为 0，UI 怎么验证 | **加一个合成 discovery fixture**（往 `discovery/*.json` 写 Claim/Mechanism/MatchResult/Certificate），前端组件测试用它。理由：阶段 5 已用同样办法（`node_parents` 表 0 行 ⇒ 合成 db 测三种边），有先例 |
| **D-C** | 知识卡的 null 怎么显示 | 三态显式区分「未记录」（null）与「不适用」（该字段在此卡类型下无意义）。不做 0 兜底 —— TODO 5.2 已有同类硬要求 |

**D-A 决定工作量级别**（后端 +15 行 vs 该页降级），D-B 决定测试能不能真跑通。

---

## 4. 实施分解

### 4A 后端：补全 discovery 三个死路 ✅ 已完成

> **实施后修正了计划里的方案。** 原计划写「`theories` 改读 `mechanisms.json`、
> `matches` 从 `tournament_results.json` 读」—— 动手时发现**两个文件都是死路**：
> `theories.json` 被 `discovery/certificates.py` 硬编码写成 `[]`；
> `tournament_results.json` 的源头 `engine._tournament_results` 初始化成 `{}`
> 后**从没被赋值**。所以两个字段都改成**直接读数据库表**（`mechanism` / `match`），
> 不动引擎。详见下方「实际做法」。

**实际做法**：

| 字段 | 改法 | 依据 |
|---|---|---|
| `theories` | 读 `mechanism` 表的 `payload_json` | `Mechanism.role` 六种取值正是 6.3 的分区依据；`payload_json` 存整个对象 |
| `matches` | 读 `match` 表（按 `experiment_id` 过滤） | `store.create_match` 一直在写这张表，只是从没落成文件 |
| `mechanisms_state` / `matches_state` | 新增两个 `ArtifactState` 字段 | 保持「每个产物都有 state」的对称性 |
| `_table_state` | 新增助手，用 `has_table` 而非 `fetch_all` | ⚠️ `fetch_all` 对缺表返回 `[]` 不抛错，用它判存在性会得到恒为 `available` 的常量 |

**`ArtifactState` 只有三态**（`AVAILABLE` / `MISSING` / `INVALID`，无 `EMPTY`）：

- **0 行 = `available`**（与 `_read_json_list` 对空文件的处理一致）——"比赛跑了但没产出"是合法状态
- **表不存在 / 库不可读 = `missing`**——"这个 bundle 压根没有比赛数据"
- 前端必须能分开说这两句话，**不能只看数组长度反推 state**

**测试**（`tests/webapi/test_replay_discovery_mechanisms.py`，18 条）：
真实基线（表在 0 行 → `available` + `[]`）/ role 六值全透传 / 4 个 role 分区 /
matches 读出 / payload 覆盖镜像列 / `experiment_id` 隔离 / 无该列时不误杀 /
`DROP TABLE` → `missing` / 坏 JSON 跳过不致命 / `_experiment_id` 全函数 /
`run_summary.json` 缺失容错。

**门禁实测**：`tests/webapi` **229 全绿**（211 → +18）· 契约漂移 exit 0 ·
`tsc` 净 · `eslint` 净 · `vite build` 通过 · 前端 `pnpm test` 257+2 skipped /
`pnpm test:perf` 259 全绿。

**顺带修掉一个阶段 5 遗留的口径错误**：`workbench-performance.test.ts` 里
「1000 节点的全量筛选在 500ms 内」实际量的是「筛选 + dagre 布局」——
筛选判定本身只要 **2ms**，1800ms 全在布局。已拆成只量筛选（阈值 200ms），
布局归它自己那条（3000ms）。详见 skill `vitest-perf-budget-noise`。

#### D-D：`claims` 也没有暴露（4B 开工时发现，同类死角）

TODO 6.2 要显示 `condition` / `feature` / `outcome` / `scope` / `falsifier`。
这五个字段**不在任何 discovery 产物文件里**：`phenomena.json` 的条目只有
`{claim_id, grade, payload}`，而 `payload` 是 `ClaimTestResult`（effect/CI/p/e）。
散文在 `claim` 表里，webapi **从没读它**（`grep '"claim"'` 零命中）。

按 D-A 的同一做法补上：`claims` + `claims_state`，读 `claim` 表的 `payload_json`，
契约 1.4.0 → **1.5.0**。**没碰引擎**。

**顺带修了一个过滤 bug**：`_payloads_from_table` 的 `{**row, **decoded}` 让
payload 里的 `experiment_id`（`Claim` 有这个键，且可能是空串）**覆盖镜像列**，
导致合并后再按 `experiment_id` 过滤会静默失效（测试立刻抓到）。
已改成**合并前按列过滤** —— 列是权威索引，payload 里的只是散文。

#### D-E：散文在评分时被引擎覆盖掉（**引擎侧数据丢失，本阶段不修**）

**这是本阶段最坏的消息，但必须说清楚。**

`discovery/pipeline.py` 里 `update_claim(payload_json=...)` 被调两次，
**后写覆盖先写**：

| 时机 | 写入内容 |
|---|---|
| `create_claim` | `json.dumps(claim)` —— 散文在 |
| 沙箱失败（`pipeline.py:177`） | `{"error": sb.error}` —— 散文**被覆盖** |
| 评分（`pipeline.py:291`） | `{**ClaimTestResult, "grade": grade}` —— 散文**又被覆盖** |

事件流里也没有：`claim_proposed` 只记 `{claim_id, source}`。

⇒ **跑完一轮之后，凡进过第 2 或第 3 步的 claim，散文在任何制品里都不存在了。**
所以 `claims` 字段能给出的是：`status` / `grade` / `source` / `origin_node_id` /
`round` / `prereg_hash`（镜像列，全都有），加上 **未评分**那些 claim 的散文。

**为什么不修**：修它要改 `discovery/pipeline.py` 的 `update_claim` 调用点
（引擎范围，本阶段边界明确是"只读 webapi"），而且**只对之后的运行有效** ——
已有运行的数据已经没了。要修应作为独立的引擎任务（顺手可加：把散文在
`claim_proposed` 时就写进事件或单独产物）。

**前端已经按诚实方式处理**：`claim-logic.ts` 把"散文未记录"做成显式状态，
区分 `status='graded'`（被覆盖，附原因）与其他情况，并给整页横幅
（`proseLossNote`）。**绝不编标题。**

### 4B 前端：四个纯函数模块 + 单测 ✅ 已完成

> **实施中发现第三个同类死角（D-D）**，与 D-A 同源：TODO 6.2 要显示的
> `condition` / `feature` / `outcome` / `scope` / `falsifier` 在 `Claim` 里，
> 而 `/discovery` 只给 `{claim_id, grade, payload=ClaimTestResult}` ——
> webapi **从没读过 `claim` 表**。已按 D-A 的做法补 `claims` / `claims_state`，
> 契约 1.4.0 → 1.5.0。详见 4A 下方「D-D」。

**实际产出**（`web/src/features/discovery/`）：

| 文件 | 职责 | 单测 |
|---|---|---|
| `types.ts` | 把契约的开放字典（`list[dict[str,Any]]`）实名化 —— 字段名与 `discovery/schemas.py` 逐字一致 | — |
| `card-logic.ts` | 三态（有值 / 未记录 / 不适用）、提供·采纳·否证、采纳结局、本地信任标记 + 「不影响运行」 | 28 条 |
| `claim-logic.ts` | `Grade` 五值映射、status 三值、effect/CI 跨零判定、沙箱失败、三源配对成行 | 30 条 |
| `tournament-logic.ts` | `role` 六值分区（主张 vs 对手）、`supports` a/b/none → 胜方、家族分组、证书 | 35 条 |
| `report-logic.ts` | 初始/最佳/提升（方向感知）、波动区间、分项指标、Top-K、多数据集对比、边界审计、**下载拒绝** | 41 条 |

**九条测试要求逐条对到**（134 条新测试，`Test Files 17 passed / Tests 391 passed`）：

| TODO §9 要求 | 落点 |
|---|---|
| discovery disabled 空状态 | `phenomenaEmptyReason` —— 三句不同的话（未启用 / 无文件 / 无产出） |
| claim sandbox failure | `sandboxFailure` —— 含"状态失败但详情缺失"这一支 |
| confirmed/refuted/undetermined 映射 | `gradeVerdict` 五值 + `undetermined ≠ 未评级` |
| tournament 未启用 | `tournamentEmptyReason` 四种空态 |
| manifest 字段缺失 | `metricRows` → 缺字段报未记录且 `comparable=false` |
| 落在波动区间 → 未形成明确改进证据 | `noiseBandVerdict` + `NO_CLEAR_EVIDENCE_TEXT` |
| 多数据集不可比较 → N/A | `comparisonTable` —— **整行** N/A，且不同数据集 `rankable=false` |
| 报告下载 MIME 和文件名正确 | `downloadDescriptor` —— MIME/文件名只取自 DTO，路径只取 basename |
| 不允许下载 holdout 或任意路径 | `downloadDescriptor` 四种拒绝；`holdout/eval_only/val_labels/test_labels` 纵深防御 |

**门禁**：`tsc` 净 · `eslint` 净 · 前端 `391 passed | 2 skipped`。

**⚠️ 两处实现必须记住的口径**（测试盯着）：

1. `comparisonTable` 里"有一个运行缺指标" ⇒ **整行** N/A，不是只打码缺的那格 ——
   否则会诱导读者拿剩下不同口径的数字横着比。
2. `partitionMechanisms` 的 `unknown` 组标签要**带原始 role 值**（一种时点名，
   多种时报个数）—— 笼统写"未识别"会让引擎新增的 role 彻底看不出来。

### 4C 前端：组件 + 四页 ✅ 已完成

| 文件 | 覆盖 |
|---|---|
| `KnowledgeCardList.tsx` | TODO 6.1 六项 + 本地标记与「不影响运行」同屏；`state` 区分「统计表不存在 / 本轮没卡」 |
| `PhenomenaPanel.tsx` | TODO 6.2 八项；散文丢失横幅、沙箱失败横幅、缺主张行横幅；三态空态文案 |
| `TournamentBracket.tsx` | TODO 6.3 六阶段；**两个显式分区**（`data-zone="arguments"` 模型论点 / `data-zone="verdicts"` 数据裁决） |
| `ReportPanel.tsx` | TODO 6.4 六项 + 制品下载四种拒绝 |
| `RunKnowledgePage.tsx` | 重写：页内三标签（知识卡 / 现象 / 机制辩论赛） |
| `RunResultsPage.tsx` | 重写：结果与报告 |

#### 【决定】路由：按 TODO §3.3 收口，不新增路由

计划初稿写过 `/phenomena`、`/tournament` 两条独立路由，**与既有惯例冲突**：

- TODO §3.3 明写「树、时间轴、排行榜是工作台页内标签，不增加侧栏」，且路由清单里
  运行作用域下只有 `/knowledge` 与 `/results`；
- `app/navigation.ts` 的 `resolveActiveModule` 只认 `knowledge` / `results` 两段；
- `RailNav.tsx` 的链接本来就在 `/runs/$runId/knowledge` 与 `/runs/$runId/results`。

⇒ **6.1/6.2/6.3 做成 `/knowledge` 的页内三标签，6.4 用已有的 `/results`。** 计划里
`/report` 那个名字作废（与已有 `/results` 重复表达同一件事）。

#### 【决定】「模型论点 vs 数据裁决」的固定口径

分区不是排版偏好，而是归因正确性：机制 `title` 由模型生成，`matches` / `status` /
`certificates` 由数据给出。两处必须遵守：

1. **裁决区只印机制 id，不印标题**（写了标题就等于把模型假设混进数据结论）；
2. 机制卡上**不显示 `status`** —— `status` 是裁决，一律去裁决区看。

#### 【发现】`test:perf` 门禁不稳定（已修，非本阶段引入）

症状：同一份代码连续跑，`workbench-performance.test.ts` 一会儿红一会儿绿
（1000 节点布局 850 ms 独占 → 3363 ms 在同进程里跑完另外 17 个文件之后）。

- **证伪归属**：单独跑该文件 850 ms 通过 ⇒ **不是代码退化**，是测量方式问题。
- **两处修**：
  1. `test:perf` 原本把**全部 18 个测试文件**塞进同一个进程跑（`--no-file-parallelism`
     只是不并行，不是隔离），墙钟测量被自身进程的堆污染 ⇒ 收口成只跑含墙钟断言的
     两个文件（`workbench-performance.test.ts` + `tree-adapter.test.ts`）。
  2. 单次采样改**每个规模取 3 次最小值**（抢占只会让样本变大、不会变小）：
     比值从 ×26（假信号）回到稳定的 ×12.3 / ×12.7。
- 环境侧的诱因另记：`%TEMP%\pytest-of-A` 堆了 **35,013 个文件**（历次全量 pytest
  没清掉的临时目录），实时杀毒扫描会造成间歇性 3–4 倍降速。**未清理，待灵梦决定。**

### 4D 门禁 + 冒烟 + 提交

- Python 回归（F = 8）、契约漂移、tsc/vitest/eslint/build 四门禁
- 起后端 + 前端做人工冒烟（重点验空态与下载）
- 提交 → 推 `feat/webui-phase6` → 灵梦开 PR

---

## 5. 风险

| 风险 | 应对 |
|---|---|
| ~~`tournament_results.json` 真实结构未核~~ | **已证伪**：该文件源头 `engine._tournament_results` 是恒 `{}`，永远没有数据；真数据在 `match` 表（见 4A） |
| 6.2/6.3 真实数据为 0 ⇒ UI 看起来"永远是空的" | 合成 fixture（4A 已建 23 条 claim/机制/比赛测试）+ 空态文案分三种说清（`phenomenaEmptyReason` / `tournamentEmptyReason`） |
| `state=AVAILABLE` 但数组空 | UI **不信任 `state`** 推断数量：`tableAvailableButEmpty` 与 `tableMissing` 分开报 |
| ~~4 个 `*_state` 不覆盖 `mechanisms`/`matches`~~ | **已修**：新增 `mechanisms_state` / `matches_state` / `claims_state`（1.4.0 / 1.5.0） |
| **散文在评分时被引擎覆盖（D-E）** | 本阶段不修（引擎范围 + 只对后续运行有效）；前端做成显式"未记录"状态 + 整页横幅，不编内容 |
| 阶段 5 刚合，PR #23 之后 main 可能又前进 | 提交前 `git fetch` + 核 `origin/main` 是否前进 |

---

## 6. 不做清单

- 运行控制（暂停/恢复/追加轮次）→ 阶段 7
- 实时推送 → 阶段 8
- 下载 holdout / 任意路径 → **永久不做**（TODO §9 明确「不允许下载 holdout 或任意路径」）
- 改引擎侧的 `theories.json` 硬编码 → **不在本阶段动引擎**（只改 webapi 读哪個文件）

---

## 7. 决策记录（已随实施落定）

- **D-A**：后端补 `theories` / `matches` —— **已实施**（4A，改为直接读 `mechanism` / `match` 表）。
- **D-B**：加合成 fixture —— **已实施**（4A 的合成 DB 夹具 + 4B/4C 的合成 DTO 夹具）。
- **D-C**：知识卡三态显示 —— **已实施**（4B 的 `card-logic.ts` + 4C 的 `KnowledgeCardList`）。
- **路由**：不新增 `/phenomena`、`/tournament`、`/report`；按 TODO §3.3 收口为
  `/knowledge`（三标签）+ `/results`。见 §4C。
- **D-E（引擎侧散文覆盖）**：本阶段**不修**。已在前端做成显式「未记录」+ 整页横幅。
