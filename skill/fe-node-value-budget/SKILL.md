---
name: fe-node-value-budget
description: 配置多目标节点价值与 token 预算控制，并核对 run_summary 预算字段。
---

## 何时使用

- token 总预算或分阶段预算即将耗尽
- `tokens_per_ros_point` 过高、性价比变差
- 长期停滞（`budget_stop_reason: stagnation`）
- best 分数波动大、疑似追逐噪声（可尝试 `mode: multi`）

## 输入

- `selection.value.*`：多目标 Q（仅影响选择，报告仍用评估器 ROS）
- `budget.*`：`stage_caps`、`stagnation_window`、`tokens_per_point_cap`、`expand_gating` 等
- 非 HDD 任务需在配置中设置 `rank_keys` / `threshold_keys` / `noise_key`；HDD 由 `HDDAdapter` 提供

## 命令

```bash
# Mock 预算演示（toy 任务 + multi + 极低 reflect cap）
bash skill/fe-node-value-budget/scripts/run_mock_budget.sh

# 竞赛报告字段（含预算相关键）
python skill/fe-evolve-manager/scripts/report_run.py <fe.db> <run_summary.json>
```

`run_mock_budget.sh` 会复制 `tests/fixtures/toy_task`，写入 multi + `max_tokens: 20000` + `stage_caps.reflect: 0.01` + `stagnation_window: 4`，运行 12 轮 mock 进化后执行 `check_budget_summary.py`。

## 成功检查

`check_budget_summary.py` 断言：

- `tokens_per_ros_point` 键存在（增益 > 0 时为正数）
- `value_mode == "multi"`
- `stage_cap_hits.reflect > 0`
- `budget_stop_reason` 为 `""`、`stagnation` 或 `tokens_per_point_cap` 之一
- `elite_archive_sizes` 含 `rank` 与 `threshold` 键
- `best_score` 来自评估器（不要用 Q 值）

## 故障处理

| 现象 | 处理 |
|------|------|
| 过早停止 | 增大 `stagnation_window` / `min_iterations_before_stop` |
| `value_mode_fallback` 事件 | 检查 `rank_keys` 与评估器 `metric` 键是否一致 |
| 搜索偏移或 best 下降 | 回退 `selection.value.mode: scalar` |
| 分阶段降级过多 | 调大对应 `stage_caps` 比例 |
| `tokens_per_point_cap` 误停 | 放宽或置 `null` |

## 禁止

- 用 Q 值替代 ROS 报告分数
- 修改评估器或 `benchmark/hdd_mvp/data/`
- 在 `cloud/` 代码中加入 HDD/SMART 等领域词
- 将 API 密钥写入配置或脚本

## 实跑后待报告（当前不执行）

一次真实 `mode: multi` 运行：报告 §4.3 指标，以及 `tokens_per_ros_point`、`budget_stop_reason`、`stage_cap_hits`、`elite_archive_sizes`、`expand_skipped_budget`、`value_mode`，并与 PR #6 实跑对比每 ROS 点 token（合并规则：最优 − 约 2）。
