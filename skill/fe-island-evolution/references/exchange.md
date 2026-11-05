# 岛间摘要交换参考

本文件解释“岛之间到底交换了什么、记成了哪些事实、怎么读”。命令在 `../SKILL.md`。

## 一句话原则

岛之间**只交换方法描述与评估器已经给出的数字**，永远不交换候选源码、原始数据、预测文件或模型权重。任何来自 LLM 的文字在被写入摘要前都要过 `sanitize()`；分数只能来自本地评估器。

## 摘要（`exchange_summary`）

| 字段 | 含义 |
|------|------|
| `summary_id` | `sum-xxxxxxxx`，一条结论的身份证号 |
| `kind` | `best`（有效操作）/ `failure`（避错）/ `knowledge`（知识用法）。只有这三种 |
| `source_island_id` / `source_node_id` | 哪个岛的哪个节点产生的。来源节点是证据锚点，不是可复制的代码 |
| `task_fingerprint` / `evaluator_fingerprint` | 结论是在哪套任务契约与哪个评估器下成立的 |
| `summary_text` | 清洗后的方法描述，上限 1200 字符（超限报“re-distill”，不会截半句） |
| `conditions` | 适用条件，可能为空（空就是“运行未记录条件”，不要替它编） |
| `metrics` | **由程序填的评估器读数**：`combined_score`、`delta_vs_parent`、`validity`、`cost_time`，正向摘要还带 `previous_published_best` / `gain_vs_published_best`，避错摘要带 `occurrences` / `repair_attempts` |
| `evidence_refs` | 形如 `node:<id>` 的引用，不含正文 |
| `confidence_status` | `proposal` → `single_observation` → `replicated` → `statistically_confirmed` |
| `content_hash` | `(kind, summary_text, conditions)` 的哈希，用于去重 |

`metrics` 里出现数字只说明“评估器当时给出这些”，不说明这条结论对该任务普遍成立；普遍性只由 `confidence_status` 表达。

## 四层独立事实

交换是四件事，一件都不能代表另一件：

| 事实 | 表 | 事件 | 说明 |
|------|----|------|------|
| 发布 | `exchange_summary` | `exchange_summary_published` | 本岛产出一条可读的结论 |
| 投递 | `exchange_delivery` | `exchange_delivered` | 结论被放进兄弟岛的收件箱。**投递只表示可见，不表示采纳，更不表示有效** |
| 采纳/拒绝 | `exchange_delivery.status` | `exchange_rejected` | 接收岛在生成前逐条判适用性 |
| 应用 | `summary_application` | `exchange_applied` | 被采纳的摘要真的进了某个新候选的提示 |
| 应用的结果 | `summary_application.evaluation_id/score` | `jev_deferred_evaluated`、`iteration_complete` | 该候选由**接收岛自己的评估器**打分后才回填 |

`run_summary.json` 的 `exchange` 块就是这四层的计数：`summaries` / `deliveries` / `accepted` / `rejected` / `applications` / `evaluated_applications`。`applications` 可以大于 `accepted`（一条采纳的摘要能生成多个候选），也可以小于（采纳了但还没轮到生成）。

## 拒绝原因（`exchange_rejected.reason`）

| 值 | 含义 |
|----|------|
| `target_island_not_runnable` | 目标岛已 `paused`/`finished`，把结论投给它没有意义 |
| `task_fingerprint_mismatch` | 任务契约不是同一份，结论不通用 |
| `evaluator_fingerprint_mismatch` | 评估器换过了，分数不可比 |
| `superseded_by_newer_best` | 来源岛已经发布了更高的 `best`，旧那条被取代 |

采纳时写的 `reason` 是 `applicable`。发布阶段的失败原因在 `exchange_summary_failed` 事件里（例如 `empty_after_sanitize`：清洗后正文为空，宁可不发也不发半句话）。

## 跨岛嫁接（`summary_cross` 算子）

- 队列排序先看“这条 `best` 是否真的比本岛当前最好分更高”，再看到达顺序，最多取 `max_summaries_in_context` 条进提示。
- 采纳不是**一次性令牌**：一条 `accepted` 的摘要每轮生成都可复用，靠条数上限防止历史堆进提示。
- 嫁接出来的候选算子记为 `summary_cross`，成本归到 `generate` 阶段，父节点关系另记，**分数由接收岛的本地评估器重新打**，绝不继承来源岛的分数。
- `exchange_check` 事件记录每轮交换的产出（发了几条、投了几条、为什么是 0）。游标即使什么都没发也会前进，否则空收件箱会被反复扫描付费。

## 负结果怎么读

- `kind: failure` 的正文只讲“错误类型 + 发生条件 + 当前结论”，**发生次数与修复尝试次数放在 `metrics`（`occurrences`、`repair_attempts`）里，不进正文**。这样同一种错误再次出现时是**给同一条摘要加证据**（`exchange_summary_replicated`），而不是每轮广播一遍新结论。
- 一条避错摘要代表“这批候选在这个岛失败过”，不代表“这种写法普遍不可用”。`_next_confidence()` 只在有独立证据时把置信度升一级（`single_observation → replicated`），到 `statistically_confirmed` 需要真正的重复验证。
- 因此报告里允许出现“本岛零失败摘要”这种事实：它可能只是运行太短或全岛没有无效候选，不能写成“没有已知风险”。

## 中断后的补齐（`exchange_delivery_backfilled`）

摘要落库与投递是两次写入，进程可能死在中间。此时下一轮**不会**重新发布同一条结论（内容哈希去重只并证据），所以每轮交换开头会按库里的缺口补投：本岛已发布的摘要 × 仍可动作的兄弟岛，缺 `(summary_id, target_island_id)` 就补一条 delivery。补齐依赖 `INSERT OR IGNORE` 与该唯一索引，因此补齐不会变成重播；已停下的岛不会被硬塞任务。

看到 `exchange_delivery_backfilled` 说明上一次进程中断过，**不是**这一次重复发送。

## 检查一次交换是否真实发生

```bash
grep -E '"type": "(exchange_check|exchange_summary_published|exchange_delivered|exchange_applied|exchange_rejected|exchange_summary_replicated|exchange_delivery_backfilled|summary_cross_selected|summary_crossover)"' \
  <artifacts_dir>/<exp_id>/events.jsonl
```

再对照 `run_summary.json` 的 `exchange` 计数：`evaluated_applications > 0` 才说明外来经验进入了本岛流程并被打过分。只有 `summaries > 0` 而 `applications = 0`，说明经验发布了但没人用；`applications > evaluated_applications`，说明采纳的候选还没评估完（中断过就会这样，续跑会补回填，不会重复加分）。
