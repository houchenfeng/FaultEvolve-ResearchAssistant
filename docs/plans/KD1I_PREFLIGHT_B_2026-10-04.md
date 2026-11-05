# KD1-I 预检 outcome B（事实记录）

日期：2026-10-04。性质：**仅事实，不含规划与代码改动**。

## 结论

- **预检记为 outcome B，不进全流程。**
- 不修库、不换种子、不放宽门。
- HDD3 仍为**完整 B（负结果，不是新发现）**；本文不把 HDD3 或 HDD4 写成发现。

## 已测事实（用户提供，不改数字）

| 项 | 值 |
|---|---|
| 代码 | `1c395b39ac882d5438a94e5457c635f11b6960d1`（`1c395b3`） |
| 副本目录 | `/home/hcf/nas_hcf_data/faultevolve/runs/kd1i_20261004/preflight/89f4bdd1` |
| 退出码 | 0 |
| `elapsed_s` | 538.202 |
| 因子库 SHA256 | `f46a41a53df996541b94b8b9b86ebac0ed325299bffc5d42717e3499e06d2806` |
| 库条数 | 23 |

### 漏斗

| 阶段 | 计数 |
|---|---|
| proposed | 23 |
| executable | 23 |
| coverage_ok | 23 |
| deduped | 23 |
| explore_incr | 0 |
| power_gate | 0 |
| frozen | 0 |
| confirmed_stats | 0 |
| discovered_or_confirmed | 0 |

- `claims_tested`：0
- `discovery_llm_error`：0
- 确认事件：无

### Token

- 分阶段 token：均为 0
- 每分 token：n/a

### 其它指标

- P/R/F1、误报/漏报：n/a（无预测器）
- 种子 / `split_salt`：**未核实**

## 产物

- 见上表「副本目录」。
