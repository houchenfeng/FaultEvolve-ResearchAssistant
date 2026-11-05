# E0 指标口径

指标由 `faultevolve.optimization.baseline_metrics.compute_baseline_metrics` 实现，分母显式输出；缺失为 `null` 并附 `unknown_reason`，不推断补零。

| 字段 | 定义 |
|---|---|
| `valid_rate_first_eval` | 首次完整 evaluator 有效数 / `n_first_eval` |
| `valid_rate_after_repair` | Repair 后有效数 / 生成请求数（实现中见代码） |
| `positive_gain_rate` | 有效子节点 `delta_score>0` / 有效子节点数 |
| `unique_candidate_rate` | 不同 `source_hash` / 有效候选数 |
| `legacy_valid_rate` | 原样 `run_summary.valid_rate` |

`significant_gain_rate` 使用工程噪声门，**不是** ROS 差置信区间。

历史运行重建：待 NAS/本地 run 副本可读后填写；当前无新实验结果。
