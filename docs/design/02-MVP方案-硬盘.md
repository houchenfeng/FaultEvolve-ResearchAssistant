# MVP 方案：硬盘故障预测上的「云端知识注入 + 自主进化 + 本地评估」

> 目标：用最小实现跑通 FaultEvolve 的完整闭环，并与伐谋在**完全相同**的数据、评估器、初始解和迭代预算下对比进化程度。
> 依赖：`01-系统总体设计.md`

---

## 1. MVP 范围

| 包含 | 不包含（后续迭代） |
|---|---|
| 硬盘基准数据集 + ROS 评估器 + 初始解（**已完成**） | 内存、光放大器数据适配 |
| 云端控制面（部署在团队云服务器）：实验 API、解树、任务队列、LLM Gateway（千问）、Judge Service（Jev），单进程 FastAPI + SQLite | 多租户、PostgreSQL、Ray |
| 本地评估 worker：拉取、执行、指标白名单回传、聚合错例画像 | 容器沙箱（MVP 用临时副本 + 静态规则 + 超时） |
| 知识注入：OpenAlex/Semantic Scholar/arXiv 检索 + 引用筛选 + 网络搜索（白名单域名）+ 经典著作书单 + 专家方向文件 + 千问提炼卡片 | 停滞触发的定向检索 |
| KGTE：冷启动多分支 + J-PUCT 选择（Jev 先验）+ Jev 评估前预判与在线校准 + `refine` `inject` `transplant` 三个算子 + 正负经验传播 | `crossover` `diversify` `simplify` 算子；Jev 评判问题的自动修订 |
| 3 个 Skill：`fe-task-builder`（轻量版）、`fe-knowledge-injector`、`fe-evolve-manager`（含 worker 启停） | `fe-diagnosis`、`fe-report` 完整版 |
| Codex 作为宿主调用 Skill | 其它宿主适配 |

---

## 2. 基准数据集（已实现，`benchmark/hdd_mvp/`）

| 划分 | 时间 | 正样本 | 负样本（抽样） | 负样本权重 | 用途 |
|---|---|---|---|---|---|
| train | 2024Q3 cutoff | 1104 | 29989 | 9.86 | 候选程序训练 |
| val | 2024Q4 cutoff | 756 | 29998 | 10.07 | **进化评分**（伐谋与 FaultEvolve 相同） |
| test | 2025Q1 cutoff | 770 | 29989 | 10.32 | **私有裁决**，任何进化系统不可见 |

- 任务：给定 cutoff 前最多 14 天的每日 SMART 快照，预测未来 7 天是否故障；输出 `score` 和 `alarm`。
- 来源：Backblaze Drive Stats（≥4TB 机械盘，约 44 个型号，4 个厂商），`prepare_data.py` 可从原始 CSV 确定性重建。
- 评分：ROS = 100 × (0.5·F1_p10 + 0.3·AUPRC + 0.2·R@FAR≤0.2%) × 时间因子。

| 方案 | val ROS | test ROS | 说明 |
|---|---|---|---|
| 规则基线 `candidates/rule_baseline.py` | 12.94 | — | SMART 5/187/197/198 非零即告警 |
| **初始解 `init.py`** | **22.81** | 25.37 | 最后一天 10 个 SMART + 逻辑回归 |
| 人工参考（不入库） | 33.70 | 33.58 | 14 天趋势特征 + LightGBM；用于确认提升空间 |

---

## 3. MVP 组件设计

### 3.1 代码结构

```
src/faultevolve/
├── cli.py                 # `fe` 命令入口（typer）
├── cloud/
│   ├── api.py             # FastAPI：experiments / workers / jobs / leaderboard / tree / control
│   ├── store.py           # SQLite：node / evaluation / insight / card / llm_call / event
│   ├── engine.py          # 进化主循环（异步）：选择 → 算子 → 生成 → 入队 → 更新
│   ├── selection.py       # J-PUCT、最大值回传、渐进展宽、虚拟损失、停止判断
│   ├── judge.py           # JudgeClient：Jev 调用、问题模板与版本、校准（Brier/ECE/温度缩放）、信任度 τ
│   ├── operators.py       # refine / inject / transplant 的上下文组装与 prompt 模板
│   ├── insights.py        # 正负经验抽取、子树记忆、跨枝检索打分（Jev 适用性）、Beta 信誉
│   ├── llm.py             # 千问（DashScope OpenAI 兼容接口）客户端、Token 记账、缓存、预算熔断
│   └── codecheck.py       # 生成代码的语法与禁用 API 预检（与评估器规则一致）
├── knowledge/
│   ├── openalex.py        # 检索与元数据（引用数、年份、venue）
│   ├── cards.py           # 卡片提炼、适用性打分、聚类、Beta 效用
│   └── expert.py          # expert.md → 高先验卡片
└── worker/
    ├── worker.py          # 注册、心跳、拉取、调用 evaluator.evaluate、回传
    ├── analysis.py        # 本地错例画像：按厂商、型号、SMART 状态聚合的漏告/误告统计
    └── whitelist.py       # 指标白名单与 error_info 脱敏
```

### 3.2 进化配置 `evolve.yaml`

```yaml
budget:
  max_iterations: 50          # 与伐谋 config.yaml 的 max_iterations 相同，公平对比
  max_tokens: 3_000_000
  max_wall_hours: 6
cold_start:
  n_branches: 4               # 方向簇数；每簇一张最高先验卡片 + init.py 作为共同祖先
selection:
  policy: jev_puct            # 对照组：uct（不用 Jev）/ topk（贪心）
  c_puct: 1.2
  kappa_noise: 1.0            # δ = kappa × 评估器返回的 f1_boot_std × 50（换算到 ROS 量纲）
  widening: {C: 2, alpha: 0.5}
judge:
  provider: jev               # jev / qwen_sampling（无 Jev Key 时的退化方案）/ none
  model: jev-latest           # 正式实验固定版本号
  prescreen: true             # 评估前 Score + Noul 预判
  audit_rate: 0.1             # 被暂缓候选的随机复核比例
  calibration_window: 30
  initial_trust: 0.5
operators:
  refine: 0.45
  inject: 0.35
  transplant: 0.20
insights:
  top_k_foreign: 3
  top_k_negative: 3
  summarize_every: 5
stop:
  target_score: 32
  potential_eps: 0.02
llm:
  base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
  api_key_env: DASHSCOPE_API_KEY
  model: ${FE_LLM_MODEL}      # 例如 qwen3-coder-plus；正式实验固定具体版本
  temperature: 0.7
worker:
  max_concurrent: 2
  timeout_s: 900
```

### 3.3 进化主循环（伪代码）

```python
tree = Tree.from_init(init_py, evaluate_first=True)
branches = cold_start(tree, cards.top_per_cluster(n=cfg.n_branches))   # 每个种子 = 一个分支根

while not stop_condition(tree, budget, judge):
    node = select_jev_puct(tree.root, judge, noise=tree.noise())   # 自根向下，Jev Choice 作先验
    op = fuse(thompson(node.branch.operator_stats), judge.choose_operator(node), judge.trust)
    ctx = build_context(node, op,
                        card=cards.sample(node) if op == "inject" else None,
                        foreign=insights.foreign_for(node, k=3),
                        negative=insights.negative_for(node, k=3),
                        error_profile=node.evaluation.analysis)
    code = llm.generate(ctx)                        # 云端（千问）
    if not codecheck.ok(code):
        tree.add_invalid(node, code, reason); continue
    pre = judge.prescreen(node, code)               # Jev：Score 期望改进 + Noul 违规概率
    job = queue.put(code, priority=pre.p_improve, audit=pre.deferred and rng.random() < 0.1)
    result = await queue.result(job)                # 本地 evaluator.py 打分
    child = tree.add(node, code, op, result)
    judge.record_outcome(pre, child.delta)          # 回填真实结果 → Brier/ECE → 信任度 τ
    update_bandits(child)                           # 算子、卡片、经验的 Beta
    if significant(child.delta, tree.noise()):
        insights.extract_and_propagate(child)       # 正/负经验 → 子树记忆 → 跨枝可检索
```

### 3.4 本地错例画像（只回传聚合统计）

worker 在调用 `evaluate()` 后，用预测文件和本地标签计算聚合画像，例如：

```json
{
  "by_vendor": {"ST": {"recall": 0.41, "far": 0.0021}, "TOSHIBA": {"recall": 0.18, "far": 0.0009}},
  "missed_profile": {"share_all_error_counters_zero": 0.62, "share_history_lt_7d": 0.08},
  "false_alarm_profile": {"share_smart5_gt0_stable": 0.55}
}
```

画像中不含任何序列号或原始数值，大模型用它做「错例驱动」的 `refine`。评估器 `metric` 与画像都会经过白名单过滤。

### 3.5 算子 prompt 骨架

```
[系统] prompt.md 全文（任务、数据、硬约束、评分）
[父方案] 代码 + ROS 与分项指标 + 错例画像
[本分支经验] 子树记忆摘要（≤ 5 条）
[其他分支已验证经验] top-3 正经验（变更摘要 / 机制 / Δ分数 / 适用条件）
[其他分支已证伪做法] top-3 负经验
[知识卡片]（仅 inject）标题 / 来源 / 核心思想 / 落地提示 / 风险
[任务] 以最小必要修改提升 ROS；先用 3 行说明变更意图，再输出完整代码
```

### 3.6 知识注入（MVP 版）

1. 由 `problem.md` 生成约 10 条查询，例如 "hard disk failure prediction SMART"、"disk failure prediction imbalanced"、"predictive maintenance survival analysis"、"extreme value theory failure prediction"。
2. OpenAlex 每条取 25 篇，按「同年份引用百分位 ≥ 70%」或「近 3 年且引用 ≥ 20」筛选，合并去重后保留约 40 篇。
3. 大模型只依据标题和摘要提炼卡片，必须摘录证据句；再按与 `problem.md` 的适用性打分，聚成 4~6 个方向簇。
4. `knowledge/expert.md` 中的专家方向（例如「优先按厂商分治」「关注 197/198 从 0 变为非零的时刻」）转成先验 0.9 的卡片。
5. `knowledge/books.yaml` 中的经典著作（可靠性工程、生存分析、不平衡学习等）按章节要点转成原理类卡片；网络搜索只取白名单域名（厂商 SMART 文档、Backblaze 博客、Kaggle/竞赛 Top 方案），每条卡片保留 URL。
6. 输出 `knowledge/cards.jsonl` 与 `knowledge/report.md`，由 Codex 展示给用户确认。

### 3.7 Jev 评判的 MVP 实现

MVP 中 Jev 负责 4 个决策点：选节点（Choice）、选算子（Choice）、评估前预判（Score + Noul）、外枝经验适用性（Noul）。一次预判请求示例：

```json
{
  "model": "jev-latest",
  "state": {
    "task": "硬盘 7 天故障预测，指标 ROS（越高越好）",
    "parent": {"ros": 27.4, "f1": 0.31, "auprc": 0.24, "recall_at_far": 0.33, "summary": "14 天差分特征 + LightGBM"},
    "change_intent": "按厂商分别训练模型，并在各厂商内用 out-of-fold 选阈值",
    "diff": "（截断到 4k tokens 的代码 diff）",
    "hard_constraints": ["只读 4 个指定文件", "900 秒内完成", "禁止路径回溯、目录遍历、子进程与网络"]
  },
  "questions": {
    "gain": {"type": "score", "instructions": "预测该修改对 ROS 的影响",
             "criteria": ["明显变差：降低 >2", "略差：降低 0.5~2", "持平：±0.5 以内", "略好：提升 0.5~2", "明显更好：提升 >2"]},
    "violation": {"type": "noul", "instructions": "该修改是否可能违反任一硬约束或使用 cutoff 之后的信息？"}
  }
}
```

- **校准**：真实评估后，把 Δ 所在等级作为标签，按决策类型维护最近 30 条的 Brier 分数，计算信任度 τ。
- **初始信任度**：τ₀ = 0.5；前 10 轮只做记录，不暂缓任何候选，积累校准数据。
- **退化方案**：没有 Jev Key 时，`judge.provider: qwen_sampling` 用千问对同一问题采样 8 次估计分布；或设为 `none`，此时 J-PUCT 等价于 UCT。
- **噪声阈值 δ**：取父节点评估返回的 `f1_boot_std` 换算到 ROS 量纲（× 50，对应 F1 项权重 0.5 × 100）。
- **消融**：`policy: uct`（不用 Jev）、`policy: topk`（贪心）、`prescreen: false`（不预判），比较达到目标分所需轮次与本地评估次数。

---

## 4. Codex 使用流程（MVP 演示脚本）

```text
你：用 fe-task-builder 检查 benchmark/hdd_mvp 这个任务能不能直接用于进化。
Codex：[运行 fe task validate] 四件套齐全；双候选验证通过（12.94 < 22.81）；私有测试集未被引用。

你：用 fe-knowledge-injector 为这个任务做知识注入，另外加一条专家方向：按厂商分治建模。
Codex：[运行 fe knowledge build + add-expert] 检索 250 篇，筛选 38 篇，提炼 24 张卡片、5 个方向簇……请确认。

你：确认。用 fe-evolve-manager 提交，50 轮，目标 32 分。
Codex：[dry-run] 预计 Token 约 2.1M；上传清单：problem.md / prompt.md / init.py / cards.jsonl / evolve.yaml（不含数据与评估器）。确认提交？
你：确认。
Codex：实验 exp_0001 已创建。请在本地终端运行：
       tmux new -s fe-worker 'fe worker start --experiment exp_0001 --evaluator benchmark/hdd_mvp/evaluator.py'
……
Codex：第 20 轮：最优 31.4（+8.6），有效率 83%，4 个分支中分支 B（厂商分治）领先；
       已传播 6 条正经验、4 条负经验；Jev 预判信任度 τ=0.62，暂缓 5 个低潜力候选（复核 1 个）。
```

---

## 5. 验收标准

| 项 | 标准 |
|---|---|
| 闭环 | 从 Codex 一句话到得到最优解，全程无需手工写代码；人工操作只有「确认」和「启动 worker」 |
| 数据不出域 | 云端数据库中不存在任何序列号、原始 SMART 值或标签；回传字段只来自白名单（有测试） |
| 进化效果 | 50 轮内 val ROS ≥ 30（初始 22.81）；test ROS 与 val 的差距 ≤ 3 |
| 知识注入 | 最优解谱系中至少有 1 张来自文献或专家的卡片；报告列出其来源 |
| 跨枝传播 | 至少 1 条经验在 ≥ 2 个分支移植成功 |
| 可对比 | 与伐谋同为 50 轮，统一在私有测试集上裁决 |
| 留痕 | 导出 `sessions/*.json`、进化树、Token 统计 |

---

## 6. 实施顺序（按依赖）

1. `worker/` + `cloud/api.py` + `store.py`：先用固定的候选列表跑通「云端下发 → 本地评估 → 回传」，验证白名单和数据不出域。
2. `llm.py` + `operators.py`（只实现 `refine`）+ 贪心选择：跑通最小进化。
3. `knowledge/` + `inject` 算子 + 冷启动多分支。
4. `judge.py`（Jev 调用与校准）+ `selection.py`（J-PUCT）+ `insights.py`（`transplant` 与正负经验传播）。
5. 3 个 Skill 的 `SKILL.md` 与 `fe` CLI 串联；Codex 端到端演示并导出 session。
6. 与伐谋对照实验（见 `03-伐谋对照实验方案.md`），以及消融实验：无知识、无传播、UCT、top-k。
