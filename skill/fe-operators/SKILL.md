---
name: fe-operators
description: 配置召回/阈值/注入算子与 Beta-Thompson 算子老虎机，并按算子解读 run_summary。
---

## 何时使用

- 启用或调整 `recall_focus` / `threshold_calibrate` / `inject` 与 `operators.bandit`
- 某算子长期无效率或几乎不被选中
- 需要按算子统计有效率、平均 Δ 与 token

## 输入

`evolve.yaml` 中 `operators.*`（默认 `bandit: false`）：

| 键 | 默认 | 说明 |
|---|---|---|
| `bandit` | false | 关闭时恒为 REFINE，不消耗算子 RNG |
| `enabled` | refine + recall_focus + threshold_calibrate + inject | 须含 `refine` |
| `min_explore` | 0.1 | 每个算子最低探索比例 |
| `prior_alpha` / `prior_beta` | 1.0 | Beta 先验 |
| `fn_keywords` | false | 将 FN 画像词送入检索 `profile_keywords` |
| `fn_keyword_groups` | 3 | 使用的 fn_groups 条数 |

依赖：`analysis.enabled`（`recall_focus` 需要父节点 `metric.analysis.fn_groups`）；`knowledge` 目录与阶段 cap（`inject`）。

## 命令

```bash
bash skill/fe-operators/scripts/run_mock_operators.sh
python skill/fe-operators/scripts/check_operator_summary.py <artifacts_dir>
python skill/fe-evolve-manager/scripts/report_run.py <fe.db> <run_summary.json>
python -m pytest tests/test_operators_bandit.py -q
```

## 成功检查

- `bandit_active` 为 true（mock 脚本已开启）
- `operator_counts` 至少 2 个键且总和 > 0
- `operator_posteriors` 已写出且含 `alpha`/`beta`/`mean`
- `generative_valid_rate` 在 [0,1]（有样本时）
- `operator_tokens` 之和 ≤ `generate_tokens + crossover_tokens`
- Jev 跳过（未审计）的节点不参与 bandit 记账，属预期选择偏倚

## 失败处理

- 某算子 `operator_valid_rate` 过低：从 `enabled` 移除该算子
- `recall_focus` 从未出现：检查 `analysis.enabled` / `top_k`；仅带 `fn_groups` 的父节点可选
- `inject` 回退为 refine：检查知识目录与 `knowledge` 阶段 cap
- 全部仍为 refine：确认 `bandit: true` 与 `enabled` 列表
- 旧库缺 `operator_stats` 表：升级后首次打开 Store 会自动建表

## 禁止事项

- 不得让 `THRESHOLD_CALIBRATE` 读取标签或 holdout
- 不得访问 `eval_only` / `test` / `holdout` 标签
- 不得用 LLM/Jev 输出代替本地 evaluator 分数

## 交叉算子（PR #8）

- 需 `operators.bandit: true` 且 `operators.crossover.enabled: true`
- 有效节点数 ≥ `min_valid_nodes`，且存在不同 `branch_key` 的高分伙伴
- 运行时间护栏见 `runtime_budget_s`；故障处理见 `skill/fe-crossover-ensemble`

## refine valid 与 generative valid

- `refine_valid`（`report_run.py`）：仅 `operator == refine` 的节点
- `generative_valid`：refine + recall_focus + threshold_calibrate + inject + crossover
- 评估算子体系建议以 `generative_valid_rate` 为准；`refine_valid` 保留兼容

## 备注

- Resume 时 Jev 延迟队列的 `offered_card_ids` 可能为空（已知限制，未在本 PR 修复）
