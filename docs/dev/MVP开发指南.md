# FaultEvolve MVP 开发指南（面向 AI 实现者）

> 读者：负责实现 MVP 的 AI 编程助手（Codex / Claude Code / Cursor 等）或工程师。
> 目标：读完本文即可**不再询问**地实现 MVP。设计动机见 `docs/design/01-系统总体设计.md`，范围与验收见 `docs/design/02-MVP方案-硬盘.md`。
> 本文是**实现契约**：函数签名、数据表、接口、prompt、配置、测试都以本文为准；与设计文档冲突时以本文为准，并在 PR 中说明。

---

## 0. 必须遵守的规则

1. **不要修改** `benchmark/hdd_mvp/evaluator.py`、`init.py`、`problem.md`、`prompt.md` 和 `data/`。这些文件是与百度伐谋对照实验的公共基准，改动会破坏可比性。如果确实需要改，先停下来说明原因。
2. **永远不要读取、打印、上传** `benchmark/hdd_mvp/data/holdout*`（私有测试集）。只有 `fe report final` 在本地调用 `evaluator.evaluate(..., split="test")` 时才可以使用。
3. **密钥只从环境变量读取**：`DASHSCOPE_API_KEY`（千问）、`MIYANG_API_KEY`（Jev MiYang 中继）、`FE_API_KEY`（云端控制面鉴权）。不得写进代码、配置、测试、日志或提交记录。仓库根目录的 `.env.example` 只放占位符。
4. **数据不出域**：云端进程中不能出现任何序列号、SMART 原始值或标签。worker 回传前必须经过白名单过滤（见 6.4 节），并有测试覆盖。
5. 分数**只由本地评估器产生**；Jev 和千问的输出只能影响「扩展谁、先评估谁、怎么改」，不能写入任何节点的分数。
6. 每完成一个里程碑（第 13 节）就提交一次，提交信息写清楚完成了什么。

---

## 1. MVP 要交付什么

一句话：Codex 通过 3 个 Skill，把 `benchmark/hdd_mvp` 提交给**部署在云服务器上的控制面**；控制面做知识注入，并用「千问生成 + Jev 评判 + J-PUCT 树搜索 + 跨枝经验传播」进化候选程序；**本地 worker** 拉取候选、调用 `evaluator.py` 打分、只回传白名单指标。进行 50 轮后，在本地私有测试集上裁决最优解。

验收标准见 `02-MVP方案-硬盘.md` 第 5 节，核心是：50 轮内 val ROS ≥ 30（初始 22.81），且 test 与 val 之差 ≤ 3。

---

## 2. 技术栈

| 用途 | 选型 | 说明 |
|---|---|---|
| 语言 | Python 3.12 | 与基准一致 |
| 云端 API | FastAPI + Uvicorn | 单进程；后台进化循环用 `asyncio` 任务 |
| 存储 | SQLite（标准库 `sqlite3`，WAL 模式） | 单文件 `fe_cloud.db`；不要引入 ORM |
| 数据校验 | Pydantic v2 | 所有 API 请求/响应模型 |
| HTTP 客户端 | httpx | worker ↔ 云端、Jev、OpenAlex |
| 千问 | `openai` SDK，`base_url=https://dashscope.aliyuncs.com/compatible-mode/v1` | 已验证可用：`qwen3-coder-plus`（生成代码）、`qwen3-max`（抽取经验、摘要、卡片提炼）。国际站 `dashscope-intl` 与当前 Key 不匹配 |
| Jev | httpx 调用 `POST https://miyang.cn/api/v1/decisions`，模型 `miyang/jev-1.13` | 缺密钥或服务异常时 fail-open |
| CLI | Typer | 命令名 `fe`，所有子命令都支持 `--json` |
| 数值 | numpy、scipy | 校准、统计 |
| 配置 | PyYAML | `evolve.yaml` |
| 测试 | pytest、pytest-asyncio、`httpx.MockTransport` | 外部 API 在测试中一律离线 mock |

在 `requirements.txt` 中追加：`fastapi uvicorn[standard] httpx pydantic>=2 openai typer pyyaml pytest-asyncio`。新增 `pyproject.toml`，让 `pip install -e .` 后可以直接使用 `fe` 命令。HTTP 测试统一使用 `httpx.MockTransport`，不得联网。

---

## 3. 目录结构与文件职责

```
src/faultevolve/
├── __init__.py
├── config.py              # 读取 evolve.yaml + 环境变量 → EvolveConfig（Pydantic）
├── cli.py                 # Typer 入口：task / knowledge / evolve / worker / report / doctor
├── common/
│   ├── schemas.py         # API 与内部共享的 Pydantic 模型（第 5 节）
│   ├── codecheck.py       # 生成代码预检：语法 + 复用 evaluator.static_check 的规则
│   └── textutil.py        # 从 LLM 回复中提取代码块、截断 diff、脱敏
├── cloud/
│   ├── app.py             # FastAPI app 工厂；鉴权依赖（Bearer FE_API_KEY）
│   ├── routes.py          # 第 5 节所有接口
│   ├── store.py           # SQLite 访问层（第 4 节 DDL；只用参数化 SQL）
│   ├── engine.py          # 进化主循环（每个实验一个 asyncio 任务）
│   ├── tree.py            # 解树内存视图：父子关系、子树最优、前沿、访问计数
│   ├── selection.py       # J-PUCT、渐进展宽、虚拟损失、停止判断（第 7.1 节）
│   ├── operators.py       # refine / inject / transplant：上下文组装 + prompt（第 7.3 节）
│   ├── insights.py        # 经验抽取、子树记忆、跨枝检索打分、Beta 信誉（第 7.4 节）
│   ├── bandits.py         # Beta-Bernoulli 与 Thompson 采样（算子、卡片、经验共用）
│   ├── judge.py           # JudgeClient：Jev 调用、问题模板、校准、信任度（第 8 节）
│   ├── llm.py             # LLMGateway：千问调用、重试、Token 记账、预算熔断（第 9 节）
│   └── queue.py           # 评估任务队列：优先级、租约、超时重新入队、审计标记
├── knowledge/
│   ├── openalex.py        # 检索与元数据（第 10.2 节）
│   ├── websearch.py       # 可插拔网络搜索（MVP 默认关闭，接口先留好）
│   ├── books.py           # books.yaml → 原理卡片
│   ├── expert.py          # expert.md → 高先验卡片
│   └── cards.py           # 卡片提炼、Jev 相关性与适用性打分、聚类、写 cards.jsonl
└── worker/
    ├── worker.py          # 注册、心跳、拉取、执行、回传主循环（第 6 节）
    ├── runner.py          # 把候选代码写入临时文件并调用 evaluator.evaluate
    ├── analysis.py        # 错例画像：只输出聚合统计（第 6.3 节）
    └── whitelist.py       # 指标白名单与 error_info 脱敏（第 6.4 节）

skill/
├── fe-task-builder/SKILL.md
├── fe-knowledge-injector/SKILL.md
└── fe-evolve-manager/SKILL.md          # 含本地 worker 启停（MVP 合并了 fe-local-evaluator）

tests/
├── test_hdd_evaluator.py               # 已存在，不要改
├── test_store.py  test_selection.py  test_judge.py  test_insights.py
├── test_whitelist.py  test_queue.py  test_api.py  test_worker_e2e.py
```

---

## 4. 数据模型（SQLite DDL）

所有时间戳使用 UTC ISO8601 字符串；JSON 字段存 TEXT。

```sql
CREATE TABLE experiment (
  id TEXT PRIMARY KEY, name TEXT, status TEXT,            -- created|running|paused|finished|cancelled|failed
  config_json TEXT, problem_md TEXT, prompt_md TEXT,
  best_node_id TEXT, best_score REAL, iterations_done INTEGER DEFAULT 0,
  created_at TEXT, updated_at TEXT
);
CREATE TABLE node (
  id TEXT PRIMARY KEY, experiment_id TEXT, parent_id TEXT, second_parent_id TEXT,
  branch_id TEXT, depth INTEGER, operator TEXT,           -- init|seed|refine|inject|transplant
  intent TEXT, code TEXT, code_hash TEXT,
  card_ids TEXT, insight_ids TEXT,                        -- JSON 数组
  status TEXT,                                            -- pending|queued|evaluating|done|invalid|deferred
  created_at TEXT
);
CREATE TABLE evaluation (
  node_id TEXT PRIMARY KEY, validity REAL, combined_score REAL, cost_time REAL,
  error_info TEXT, metric_json TEXT, analysis_json TEXT, worker_id TEXT, created_at TEXT
);
CREATE TABLE job (
  id TEXT PRIMARY KEY, experiment_id TEXT, node_id TEXT, priority REAL, audit INTEGER,
  status TEXT,                                            -- queued|leased|done|expired
  worker_id TEXT, lease_until TEXT, attempts INTEGER DEFAULT 0, created_at TEXT
);
CREATE TABLE worker (
  id TEXT PRIMARY KEY, experiment_id TEXT, capabilities TEXT, last_heartbeat TEXT
);
CREATE TABLE card (
  id TEXT PRIMARY KEY, experiment_id TEXT, cluster TEXT, source_type TEXT,  -- paper|book|web|expert|llm_hypothesis
  payload_json TEXT, prior REAL, alpha REAL DEFAULT 1, beta REAL DEFAULT 1
);
CREATE TABLE insight (
  id TEXT PRIMARY KEY, experiment_id TEXT, origin_node TEXT, branch_id TEXT,
  polarity INTEGER,                                       -- +1 / -1
  payload_json TEXT, delta REAL, z REAL, alpha REAL DEFAULT 1, beta REAL DEFAULT 1,
  created_at TEXT
);
CREATE TABLE branch_memory (node_id TEXT PRIMARY KEY, summary TEXT, top_insight_ids TEXT, updated_at TEXT);
CREATE TABLE operator_stat (experiment_id TEXT, branch_id TEXT, operator TEXT, alpha REAL, beta REAL,
  PRIMARY KEY (experiment_id, branch_id, operator));
CREATE TABLE llm_call (id TEXT PRIMARY KEY, experiment_id TEXT, node_id TEXT, purpose TEXT, model TEXT,
  prompt_tokens INTEGER, completion_tokens INTEGER, latency_ms INTEGER, cached INTEGER, created_at TEXT);
CREATE TABLE judge_call (id TEXT PRIMARY KEY, experiment_id TEXT, node_id TEXT, decision_type TEXT,
  question_version TEXT, request_json TEXT, answer_json TEXT, outcome TEXT, brier REAL,
  latency_ms INTEGER, input_tokens INTEGER, created_at TEXT);
CREATE TABLE event (id INTEGER PRIMARY KEY AUTOINCREMENT, experiment_id TEXT, type TEXT, payload_json TEXT, ts TEXT);
```

---

## 5. 云端 API 规范

所有接口需要请求头 `Authorization: Bearer $FE_API_KEY`；缺失或错误时返回 401。前缀 `/v1`。

| 方法与路径 | 请求体 | 响应 | 说明 |
|---|---|---|---|
| `POST /experiments` | `ExperimentCreate{name, problem_md, prompt_md, init_code, config, cards[]}` | `{experiment_id}` | **拒绝**任何包含 `evaluator`、`data`、`labels` 字段的请求（返回 400） |
| `POST /experiments/{id}/start` | — | `{status}` | 启动进化循环；init 节点先入队评估 |
| `GET /experiments/{id}/status` | — | `ExperimentStatus` | 轮次、最优分、相对初始提升、有效率、队列长度、Jev 信任度、近期改进率 |
| `GET /experiments/{id}/leaderboard?top=10` | — | `[{node_id, score, operator, branch_id, intent}]` | 只读，不含代码 |
| `GET /experiments/{id}/nodes/{node_id}` | — | 节点完整信息，含代码 | 用于下载最优解 |
| `GET /experiments/{id}/tree` | — | 节点与边的精简列表 | 报告可视化用 |
| `GET /experiments/{id}/insights` | — | 经验列表 | |
| `GET /experiments/{id}/events?after=` | — | 事件流 | |
| `POST /experiments/{id}/control` | `{action: pause|resume|cancel|continue, extra_iterations?}` | `{status}` | |
| `POST /experiments/{id}/guidance` | `{text}` | `{card_id}` | 专家指导 → 先验 0.9 的卡片 |
| `POST /workers/register` | `{experiment_id, capabilities[]}` | `{worker_id}` | |
| `POST /workers/{wid}/heartbeat` | — | `{ok}` | 默认每 30 秒一次 |
| `GET /jobs/next?experiment_id=&worker_id=` | — | `Job{job_id, node_id, code, lease_until}` 或 204 | 按 priority 降序领取；租约默认 1200 秒 |
| `POST /jobs/{job_id}/result` | `JobResult`（6.4 节白名单结构） | `{accepted}` | **幂等**：同一 job 重复提交只记一次；不在白名单内的字段一律 422 |

`JobResult` 的 Pydantic 定义使用 `model_config = ConfigDict(extra="forbid")`，这是数据不出域的第二道防线。

---

## 6. 本地 worker 规范

### 6.1 主循环

```
register → 启动心跳线程
loop:
  job = GET /jobs/next；如果 204 则 sleep(5) 后继续
  code → 写入 <workdir>/.fe/candidates/<node_id>.py
  res = runner.run(code_path)            # 内部调用 evaluator.evaluate(path, timeout=cfg.timeout_s)
  analysis = analysis.profile(...)       # 仅当 validity == 1
  payload = whitelist.build(res, analysis)
  POST /jobs/{id}/result（失败时指数退避重试 5 次）
```

- 命令：`fe worker start --experiment <id> --evaluator benchmark/hdd_mvp/evaluator.py --server https://<云服务器> --max-concurrent 2`
- 运行时目录 `.fe/`：`worker.pid`、`eval_trace`（日志）、`candidates/`（候选代码）。
- 并发：`--max-concurrent N` 使用进程池，每个进程独立调用 `evaluate`。

### 6.2 运行候选

`evaluator.evaluate` 会把候选程序写出的预测文件放在临时目录，评估结束即删除。为了做错例画像，`runner.py` 采用**包装方式**，不改 evaluator：

1. 用 `importlib` 加载 evaluator 模块，调用 `evaluate(path)` 得到结果；
2. 另外再用与 evaluator 相同的参数运行一次候选程序，把预测写到 `.fe/preds/<node_id>.csv`，只在本地用于 `analysis.profile`；
3. 在 `evolve.yaml` 中提供 `worker.profile_errors: true/false`；设为 false 时跳过第 2 步，节省一半本地算力。

### 6.3 错例画像（只允许聚合统计）

输入：本地预测文件、`data/eval_only/val_labels.csv`、`data/public/val_history.csv.gz`。输出 JSON（所有值都是比例或计数，**不含序列号、型号全名以外的标识、原始 SMART 值**）：

```json
{
  "by_vendor": {"ST": {"recall": 0.41, "far": 0.0021, "n_pos": 312}, "TOSHIBA": {...}, "HGST": {...}, "WDC": {...}},
  "missed": {"n": 480, "share_all_error_counters_zero": 0.62, "share_history_lt_7d": 0.08,
             "share_vendor": {"ST": 0.35, "TOSHIBA": 0.30, "HGST": 0.20, "WDC": 0.15}},
  "false_alarm": {"n_weighted": 950.2, "share_smart5_gt0": 0.55, "share_counter_stable_14d": 0.48},
  "score_quantiles_pos": [0.01, 0.05, 0.2, 0.6], "score_quantiles_neg": [0.001, 0.003, 0.01, 0.05]
}
```

厂商由 `model` 前缀推断：`ST`、`TOSHIBA`、`HGST`、`WDC`，其余归入 `OTHER`。「错误计数」指 SMART 5/187/197/198 的 raw 值。

### 6.4 白名单与脱敏

`.fe/metric_whitelist.yaml`（缺省内容如下，worker 启动时若不存在就自动生成）：

```yaml
top_level: [validity, combined_score, cost_time, error_info]
metric: [precision, recall, f1, f1_p10, f1_boot_std, auprc, recall_at_far, false_alarm_rate,
         missed_detection_rate, alarms_per_1k_disks, quality, run_time_s, time_factor, split]
analysis: [by_vendor, missed, false_alarm, score_quantiles_pos, score_quantiles_neg]
```

`error_info` 脱敏规则：截断到 500 字符；绝对路径替换为 `<path>`；匹配序列号形态（长度 ≥ 8 的大写字母数字串）的内容替换为 `<id>`。**测试**：构造一个包含路径、序列号和额外字段的结果，断言回传 payload 中都不存在。

---

## 7. 进化引擎

### 7.1 J-PUCT 选择（`selection.py`）

```python
def select(tree, judge, cfg) -> Node:
    n = tree.root                      # 虚拟根：子节点是 init 和各分支种子
    while True:
        options = n.children_expandable() + ([n] if n.can_widen(cfg) else [])
        priors = judge.node_prior(n, options)            # Jev Choice，已按 τ 与均匀分布混合
        best = argmax(options, key=lambda c: U(c, n, priors[c], cfg) - virtual_loss(c))
        if best is n or not best.children:
            return best
        n = best
```

- \( U(c) = Q(c) + c_{puct}\cdot \tilde P(c)\cdot \sqrt{N_n}/(1+N_c) - \lambda_{dup}\cdot dup_c \)。当 `best is n` 时，Q 取 n 自身子树的 Q，访问数用 n 的扩展次数。
- \( Q(c) = \max(0,\ \mathrm{best\_in\_subtree}(c) - s_{parent} - \delta)\ /\ \max(s^* - s_{init}, 1) \)
- \( \delta = \kappa \times \mathrm{f1\_boot\_std}_{parent} \times 50 \)（缺省 κ=1.0；缺失时取 0.5 分）。
- 渐进展宽：`can_widen = len(children) < ceil(C * max(1, N_n) ** alpha)`，缺省 C=2、α=0.5。
- 虚拟损失：节点有未完成的评估任务时，U 减去 `0.5 * c_puct`。
- `dup_c`：候选行为指纹（`by_vendor` 的召回与误告率向量加 ROS）与兄弟节点的最大余弦相似度；缺失时为 0。
- **停止**（每次评估完成后检查）：达到 `target_score`；`iterations_done ≥ max_iterations`；Token 超过预算；或最近 W=15 次评估的显著改进率 Beta(1+成功, 1+失败) 的 90% 分位 < 0.05，且 Jev「是否值得继续」< 0.2。
- **一轮的定义**：一个新候选完成本地评估（validity 为 0 也算一轮）。这与伐谋的 iteration 口径一致，用于 50 轮对齐。

### 7.2 冷启动（`engine.py`）

1. 创建 init 节点（代码为 `init.py`），入队评估。
2. 取 `cards.jsonl` 中每个方向簇里先验最高的卡片（共 `cold_start.n_branches` 个，缺省 4），各执行一次 `inject`（父节点为 init），生成种子节点；每个种子分配一个新 `branch_id`。
3. 种子节点**计入**迭代轮次。

### 7.3 算子与 prompt（`operators.py`）

算子选择：`p_op = τ·P_jev(op) + (1−τ)·Thompson(op)`（Thompson 采样值归一化后再混合），然后按 `p_op` 采样；每个算子最低探索配额 10%。`transplant` 仅在存在适用概率 ≥ 0.5 的外枝经验时可选。

**统一系统消息**：`prompt.md` 全文。

**统一用户消息模板**（按算子填充，缺失的段落整段省略）：

```
## 父方案（ROS={score:.2f}）
分项：F1={f1:.3f} F1_p10={f1_p10:.3f} AUPRC={auprc:.3f} R@FAR={recall_at_far:.3f} 误告率={false_alarm_rate:.4f} 运行={run_time_s:.0f}s
```python
{parent_code}
```
## 错例画像（本地聚合统计）
{analysis_json}
## 本分支经验
{branch_memory}
## 其他分支已验证有效的做法
{foreign_positive}          # 每条：变更摘要 | 机制 | ΔROS | 适用条件
## 其他分支已证伪的做法（避免重复）
{foreign_negative}
## 知识卡片（仅 inject）
标题：{title}；来源：{source}；核心思想：{idea}；落地提示：{impl_hint}；风险：{risk}
## 待移植经验（仅 transplant）
{insight}
## 任务
{operator_instruction}
输出格式（严格遵守）：
<intent>不超过 3 行的变更意图</intent>
```python
完整可运行的程序
```
```

`operator_instruction`：
- `refine`：「针对错例画像中最主要的误告或漏告来源，做最小必要修改以提升 ROS。」
- `inject`：「把知识卡片中的方法落地到父方案中，保留父方案中已经有效的部分。」
- `transplant`：「把待移植经验应用到父方案中，按父方案的技术栈做必要适配。」

生成参数：模型 `qwen3-coder-plus`，temperature 0.7，max_tokens 8000。解析失败（缺少 `<intent>` 或代码块）时重试一次；仍失败则记为 invalid 节点并计入轮次。

**预检**（`codecheck.py`）：`ast.parse` 成功，且 `evaluator.static_check(code) == ""`（直接 import 基准中的 evaluator 复用规则，不要复制一份）。预检失败的节点不入队，但记为 invalid 并计入轮次。

### 7.4 经验抽取与跨枝传播（`insights.py`）

**触发**：子节点评估完成且 `|Δ| > δ`（Δ = 子节点 ROS − 父节点 ROS）。

**抽取**（`qwen3-max`，temperature 0.2，要求只输出 JSON）：输入父子代码的 unified diff（截断到 6000 字符）、两者的分项指标与错例画像，输出：

```json
{"change_summary": "按厂商分别训练 LightGBM", "mechanism": "不同厂商 SMART 语义不同，统一模型被 Seagate 主导",
 "conditions": "父方案为树模型且含厂商信息", "tags": ["model:per_vendor", "model:gbdt"],
 "affects": {"recall": "+", "false_alarm_rate": "0"}}
```

入库时 `polarity = sign(Δ)`，`z = Δ / δ`。

**子树记忆**：沿父链向上，把经验 id 加入每个祖先的 `branch_memory.top_insight_ids`（按 |z| 保留前 5 条）。分支根每新增 5 条经验时，用 `qwen3-max` 重写一次 `summary`（≤ 300 字）。

**跨枝检索**（为节点 m 组装上下文时）：
1. 候选集合：其它分支的经验，且 m 的祖先链中尚未使用过；
2. 粗排：tags 的 Jaccard 相似度取前 20 条；
3. 精排：对每条向 Jev 提 Noul 问题「该经验能否直接用于这个方案？」（20 个问题放在一次请求里），得到 `app`；
4. 得分 \( r = |z|\cdot app\cdot \frac{\alpha}{\alpha+\beta} \)；正经验、负经验各取前 3 条。

**信誉更新**：经验被用于 `transplant`，或出现在上下文中的节点评估完成后：子节点显著提升则 α+1，否则 β+1。卡片与算子采用相同规则。

---

## 8. Jev 评判（`judge.py`）

### 8.1 接口

```
POST https://miyang.cn/api/v1/decisions
Authorization: Bearer $MIYANG_API_KEY
{"model": "<cfg.judge.model>", "state": {...}, "questions": {name: question, ...}}
```

- question 类型：`{"type":"choice","instructions":str,"criteria":{key: desc}}`（≤255 项）；`{"type":"score","instructions":str,"criteria":[低→高 2~10 级]}`；`{"type":"noul","instructions":str}`。
- 响应：`answers[name]` 中，choice 含 `choice/probabilities/confidence`；score 含 `score/probabilities/legend/confidence`；noul 含 `noul`（「是」的概率）。`usage.input_tokens` 记入 `judge_call`。
- 超时 5 秒，重试 2 次；失败时返回**均匀分布**并记事件 `judge_fallback`，进化不因 Jev 故障中断。

### 8.2 问题模板（版本号 v1，存入 `judge_question` 表）

| decision_type | 类型 | instructions | criteria |
|---|---|---|---|
| `node_prior` | choice | 「为了在最少轮次内刷新全局最优 ROS，下一步最值得扩展哪个方案？」 | `{node_id: "ROS=..., 意图=..., 分支记忆=..."}`，另加 `expand_self` |
| `operator` | choice | 「对这个方案，哪种改进方式最可能显著提升 ROS？」 | `{refine: "针对误告/漏告做局部修改", inject: "引入知识卡片中的新方法", transplant: "移植其它分支已验证的做法"}` |
| `gain` | score | 「预测该修改对 ROS 的影响」 | `["明显变差：降低 >2", "略差：降低 0.5~2", "持平：±0.5 以内", "略好：提升 0.5~2", "明显更好：提升 >2"]` |
| `violation` | noul | 「该修改是否可能违反任一硬约束，或使用 cutoff 之后的信息？」 | — |
| `insight_app` | noul | 「该经验能否直接用于这个方案？」 | — |
| `card_relevance` | score | 「该文献与本任务（硬盘 SMART 7 天故障预测）的相关程度」 | 5 级，从「无关」到「直接可用」 |
| `continue` | noul | 「按最近的进化轨迹，再进化 20 轮能否把最优 ROS 提升至少 1 分？」 | — |

state 中只能放：任务一句话描述、分数与分项指标、变更意图、代码 diff（截断 4000 字符）、错例画像、经验或卡片文本、硬约束清单。

### 8.3 预判与排队

- `p_improve = p[略好] + p[明显更好]`；`e_gain = Σ p_k·v_k`，其中 v = [−3, −1.25, 0, 1.25, 3]。
- 任务优先级 `priority = p_improve`。
- 暂缓条件（前 `warmup=10` 轮不暂缓）：`p_improve < 0.15` 且 `violation > 0.8`。暂缓的节点状态为 `deferred`，不入队；但以 `audit_rate=0.1` 的概率仍然入队，并标记 `audit=1`。
- 被暂缓的节点**不计入**轮次（它们没有占用本地评估）。

### 8.4 校准与信任度

- 对 `gain`：评估后把 Δ 映射为 5 级中的真实等级 y；`brier = Σ_k (p_k − 1[k=y])²`，回填到 `judge_call.outcome/brier`。
- 基线：按最近 30 条真实等级的频率预测，得到 `brier_base`。
- 信任度 \( \tau = \mathrm{clip}(1 - \overline{brier}_{jev}/\overline{brier}_{base}, 0, 1) \)，取最近 30 条的均值；样本不足 10 条时 τ = `initial_trust`（0.5）。
- 同一个 τ 用于 `node_prior`、`operator` 和预判（MVP 简化）。
- 温度缩放：样本 ≥ 30 条后，用 `scipy.optimize.minimize_scalar` 在 [0.3, 3] 内拟合温度 T，对 `gain` 概率做 \( p_k \propto p_k^{1/T} \)。
- 评判问题的自动修订不在 MVP 范围内，但 `judge_question` 表和版本号要先实现。

### 8.5 退化方案

`judge.provider`：
- `jev`：缺省；
- `qwen_sampling`：用 `qwen-plus` 对同一问题采样 8 次（temperature 1.0），要求只输出选项 key，按频率估计分布；
- `none`：一律返回均匀分布，此时 J-PUCT 等价于 UCT，用于消融实验。

---

## 9. LLM Gateway（`llm.py`）

```python
class LLMGateway:
    async def chat(self, purpose: str, messages: list[dict], model: str, temperature: float,
                   max_tokens: int, node_id: str | None = None) -> str: ...
```

- 客户端：`AsyncOpenAI(api_key=os.environ["DASHSCOPE_API_KEY"], base_url=cfg.llm.base_url)`。
- 记账：每次调用把响应中的 `usage.prompt_tokens / completion_tokens` 写入 `llm_call`；实验累计 Token 超过 `budget.max_tokens` 时抛出 `BudgetExceeded`，由引擎转为停止。
- 重试：429 与 5xx 错误按指数退避重试 4 次（2、4、8、16 秒）。
- 缓存：以 `sha256(model + messages + temperature)` 为键缓存 `temperature == 0` 的调用结果。
- 并发：`asyncio.Semaphore(cfg.llm.max_concurrency)`，缺省 4。

---

## 10. 知识注入（`knowledge/`）

### 10.1 流程（命令 `fe knowledge build --task benchmark/hdd_mvp --out benchmark/hdd_mvp/knowledge`）

1. `qwen3-max` 读取 `problem.md`，生成 10 条英文检索式（JSON 数组）。
2. OpenAlex 检索，每条 25 篇，合并去重。
3. 高被引筛选：`cited_by_percentile_year.min ≥ 70`，或（`publication_year ≥ 当前年−3` 且 `cited_by_count ≥ 20`）。
4. Jev `card_relevance` 批量打分（每次请求 ≤ 20 篇），保留概率加权分排名前 40% 的文献。
5. `qwen3-max` 逐篇提炼卡片（输入标题与摘要），必须给出 `evidence`（摘要原句）；摘要缺失的文献跳过。
6. 合并 `books.yaml` 与 `expert.md` 生成的卡片。
7. 聚类：用 `tags` 的第一个前缀（`feature:` / `model:` / `imbalance:` / `threshold:` / `transfer:` 等）分组，形成方向簇。
8. 写出 `cards.jsonl` 与 `report.md`（检索式、各阶段数量、每张卡片的来源与引用数）。

### 10.2 OpenAlex 调用（已验证字段）

```
GET https://api.openalex.org/works?search=<query>&per-page=25
    &select=id,doi,display_name,publication_year,cited_by_count,cited_by_percentile_year,primary_location,abstract_inverted_index
    &mailto=<团队邮箱>
```

- `abstract_inverted_index` 需要还原成文本：按位置排序后拼接单词。
- 当前响应中带有 `cost_usd` 字段，说明高频调用可能计费或需要 API Key：在 `evolve.yaml` 中预留 `knowledge.openalex_api_key_env`，并把请求限制在每秒 5 次以内。
- 期刊或会议名称取 `primary_location.source.display_name`。

### 10.3 卡片 schema

以 `docs/design/01-系统总体设计.md` 5.2 节为准，另加字段 `cluster`、`source_type`。`expert.md` 中每条以 `- ` 开头的条目生成一张卡片（`prior=0.9`、`source_type=expert`）；`books.yaml` 格式如下：

```yaml
- title: "Survival Analysis: Techniques for Censored and Truncated Data"
  authors: "Klein, Moeschberger"
  points: ["把故障预测视为带删失的时间到事件问题", "用 Cox 模型或离散时间风险模型估计短期风险"]
```

---

## 11. CLI 与 Skill

### 11.1 `fe` 命令

| 命令 | 作用 | 关键输出（`--json`） |
|---|---|---|
| `fe doctor` | 检查 Python 版本、依赖、环境变量是否存在（**只报告有或无，不打印值**）、云端连通性 | `{checks: [...]}` |
| `fe task validate <dir>` | 四件套齐全；双候选验证（`init.py` 分数 > `candidates/*.py` 分数）；`static_check(init.py)` 通过 | `{ok, scores}` |
| `fe knowledge build/show/add-expert` | 10.1 节 | 卡片数、簇数、报告路径 |
| `fe evolve submit <dir> [--dry-run] [-y]` | dry-run：展示上传清单与预计 Token；提交：只上传 problem、prompt、init、cards、evolve.yaml | `{experiment_id}` |
| `fe evolve status/leaderboard/pause/resume/cancel/continue` | 对应 API | |
| `fe evolve results <id> --top 3 --out <dir>` | 下载 Top-K 代码 | 文件路径 |
| `fe worker start/status/stop` | 第 6 节；`start` 以前台方式运行，由用户放进 tmux 或 nohup | pid、trace 路径 |
| `fe report final <id> --task <dir>` | 在本地用私有测试集为 Top-3 打分，输出 `build/final_report.md` | val/test 分数与间隙 |

**Token 估算**（dry-run）：`max_iterations × (平均 prompt 8k + 输出 4k) × 1.3`，外加知识注入的固定开销 20 万。

### 11.2 Skill 文件（放在 `skill/<name>/SKILL.md`）

要求：YAML frontmatter 只包含 `name`、`description`；正文依次为：前置检查、步骤（每一步写出具体 `fe` 命令）、需要用户确认的节点、禁止事项、失败处理。安装方法：把 `skill/*` 软链接到当前 Codex 版本文档规定的 skills 目录。

- `fe-task-builder`：触发词「检查/创建/修复故障预测任务、生成四件套」。MVP 中只做 `fe task validate` 并解释结果；不生成新任务。
- `fe-knowledge-injector`：触发词「知识注入、找论文、专家方向」。流程：`fe knowledge build` → 展示 `report.md` 摘要 → 询问用户是否补充专家方向（`fe knowledge add-expert "<text>"`）→ 确认。
- `fe-evolve-manager`：触发词「提交/运行/监控/暂停/继续进化、启动 worker」。流程：`fe doctor` → `fe task validate` → `fe evolve submit --dry-run` → **用户确认** → 提交 → 给出 `tmux new -s fe-worker 'fe worker start ...'` 让用户手动启动（说明会话内启动可能被回收）→ 每 30 秒 `fe evolve status` 直到完成 2 轮 → 之后按用户要求汇报。禁止：未经确认取消或重提实验；读取 `data/holdout*`。

---

## 12. 配置

### 12.1 `benchmark/hdd_mvp/evolve.yaml`（MVP 缺省值）

```yaml
budget: {max_iterations: 50, max_tokens: 3000000, max_wall_hours: 6}
cold_start: {n_branches: 4}
selection: {policy: jev_puct, c_puct: 1.2, kappa_noise: 1.0, lambda_dup: 0.1, widening: {C: 2, alpha: 0.5}}
operators: {min_explore: 0.1}
insights: {top_k_foreign: 3, top_k_negative: 3, summarize_every: 5}
stop: {target_score: 32, window: 15, improve_rate_q90: 0.05, continue_prob: 0.2}
judge: {provider: jev, model: jev-latest, prescreen: true, warmup: 10, audit_rate: 0.1,
        calibration_window: 30, initial_trust: 0.5, timeout_s: 5}
llm:
  base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
  generate_model: qwen3-coder-plus
  reason_model: qwen3-max
  max_concurrency: 4
knowledge: {queries: 10, per_query: 25, min_citation_pct: 70, keep_top_frac: 0.4, openalex_api_key_env: OPENALEX_API_KEY}
worker: {max_concurrent: 2, timeout_s: 900, lease_s: 1200, heartbeat_s: 30, profile_errors: true}
seed: 20260926
```

### 12.2 `.env.example`（仓库根目录，已提供）

云服务器与本地 worker 各自配置自己需要的变量；两端的 `FE_API_KEY` 必须一致。

---

## 13. 里程碑（按顺序实现，每个都要有可运行的验证）

| # | 内容 | 完成判据 |
|---|---|---|
| M1 | `store.py` + `schemas.py` + `app.py/routes.py`（实验、worker、job 相关接口）+ `queue.py` | `test_api.py`：创建实验、注册 worker、领取任务、回传结果、幂等、租约过期后重新入队、多余字段返回 422 |
| M2 | `worker/`（runner、analysis、whitelist）| `test_worker_e2e.py`：启动 app（TestClient 或本地端口）→ 手工入队 `init.py` 与 `rule_baseline.py` → worker 回传 22.81 与 12.94；`test_whitelist.py` 通过 |
| M3 | `llm.py` + `operators.py`（只做 refine）+ `tree.py` + 贪心选择 + `engine.py` | 用 mock LLM（返回固定代码）跑 3 轮；真实千问跑 5 轮能产生合法候选 |
| M4 | `knowledge/` + `inject` + 冷启动多分支 | 生成 `cards.jsonl` ≥ 15 张，均有来源；冷启动产生 4 个分支 |
| M5 | `judge.py` + `selection.py`（J-PUCT）+ 预判排队 + 校准 | `test_judge.py`（mock Jev 响应，校验 Brier、τ、退化方案）；`test_selection.py`（构造树，校验 U 值排序与展宽） |
| M6 | `insights.py` + `transplant` | `test_insights.py`：经验抽取 JSON 解析、子树记忆上传、跨枝检索排除本枝与已用经验 |
| M7 | `cli.py` + 3 个 SKILL.md + `fe report final` | Codex 中一句话完成：验证 → 知识注入 → 提交 → 启动 worker → 50 轮 → 私有集裁决 |
| M8 | 消融实验：`policy=uct`、`judge.provider=none`、去掉 `inject`、去掉 `transplant` | `build/ablation.md` 汇总表 |

---

## 14. 常见陷阱

- evaluator 的静态检查会拒绝 `glob`、`.parent`、`os.getcwd`、`subprocess` 等写法；千问经常写 `Path(__file__).parent`。`prompt.md` 已经说明，但仍需在 `refine` 中把上一次的 `error_info` 放进上下文，让模型自己纠正。
- 候选程序运行时间约 3~60 秒，LightGBM 大模型可能更久；worker 的 `timeout_s` 为 900 秒，租约 1200 秒必须大于它。
- `f1_boot_std` 在分数很低时接近 0，δ 需要设下限 0.5 分，否则噪声会被当作改进。
- 同一实验只能有一个 worker 进程组；`fe worker start` 检测到 `.fe/worker.pid` 存活时要拒绝重复启动。
- 进化循环必须能从数据库恢复：云端重启后，`leased` 且租约过期的任务重新入队，`running` 的实验自动恢复。
- 不要在云端保存 worker 发来的预测文件；预测文件只存在于本地 `.fe/preds/`。
