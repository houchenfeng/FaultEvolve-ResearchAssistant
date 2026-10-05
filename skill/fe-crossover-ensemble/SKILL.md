---
name: fe-crossover-ensemble
description: 启用交叉/集成算子，合并不同分支高分节点的程序，并解读 crossover 运行指标。
---

## 何时使用

- 树中已有 ≥4 个有效节点，且存在不同 depth-1 子树的高分节点
- AUPRC / R@FAR 类指标停滞，需要集成 rank-average 或 stacking
- **不适用**：运行时间已接近上限、`operators.bandit` 关闭、有效节点不足

## 输入

`evolve.yaml` 需同时满足：

| 键 | 默认 | 说明 |
|---|---|---|
| `operators.bandit` | false | **必须为 true**，否则交叉臂不会出现 |
| `operators.crossover.enabled` | false | 开启交叉算子 |
| `operators.crossover.min_valid_nodes` | 4 | 有效节点不足时不提供 CROSSOVER 臂 |
| `operators.crossover.runtime_budget_s` | 300 | prompt 中的运行时间护栏 |
| `operators.crossover.top_quantile` | 0.3 | 伙伴候选仅限高分分位 |
| `operators.crossover.max_code_chars` | 6000 | 每个父代码截断上限 |

依赖 `analysis.enabled`（缺失时伙伴选择降级为 metric 差异近似）。

## 命令

```bash
bash skill/fe-crossover-ensemble/scripts/run_mock_crossover.sh
python skill/fe-crossover-ensemble/scripts/check_crossover_summary.py <artifacts_dir>
python skill/fe-evolve-manager/scripts/report_run.py <fe.db> <run_summary.json>
python -m pytest tests/test_crossover.py -q
```

## 成功检查

- `operator_counts["crossover"] ≥ 1`
- `crossover_tokens > 0`（计入 `total_tokens`，不计入 `generate_tokens`）
- `crossover_valid_rate` 在 [0,1]
- 每个交叉节点在 `node_parents` 有 `primary` + `secondary` 两行
- `timeout` 类 `perf_rejected` 不应异常上升

## 失败处理

- 无效率高或超时：调小 `runtime_budget_s` 或关闭 `crossover.enabled`
- 从未被选中：检查 `bandit`、有效节点数、是否存在不同 depth-1 子树（`branch_key` 基于 depth-1 祖先，**不是** `branch_id`）
- prompt 过长：调小 `max_code_chars`
- **已知限制**：修复交叉失败节点时 repair 只带 `parent_a` 代码

## 禁止事项

- 不读 `eval_only` / `test` / `holdout`
- 不以 LLM 输出代替本地 evaluator 分数
- 不改 `node` 表结构

## 设计要点（PR #8）

- 交叉节点**跳过** Jev 预筛与三层反思（省 token）
- bandit / `delta_score` 基线为两父分数的**最大值**
- `branch_key`：沿 `parent_id` 上溯到 depth==1 的祖先 id；根为 `"root"`
