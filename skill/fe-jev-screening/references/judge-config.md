# Jev 配置参考

| 字段 | 默认值 | 作用 |
|---|---:|---|
| `provider` | `none` | `none`、`jev` 或离线 `mock` |
| `base_url` | `https://miyang.cn/api/v1/decisions` | MiYang 中继（POST JSON：`state` 为对象、`questions` 为按名键控的对象） |
| `api_key_env` | `MIYANG_API_KEY` | 只读取环境变量 |
| `model` | `miyang/jev-1.13` | 固定模型版本 |
| `prescreen` | `false` | 是否在真实评估前预筛 |
| `invalid_threshold` | `0.85` | 无效概率筛选阈值 |
| `low_value_threshold` | `0.15` | 低价值阈值 |
| `low_value_action` | `skip` | `skip` 或 `defer` |
| `warmup` / `audit_rate` | `10` / `0.1` | 影子期与审计率 |
| `prior` / `prior_tau` | `true` / `0.5` | Jev-PUCT 先验及混合权重 |

决策顺序：warmup 始终评估；随后先判断 `p_invalid`，再判断 `value`；错误、熔断、缺密钥均 fail-open。`defer` 可在结束前按 value 降序补评。

事件：`jev_prescreen`、`jev_error`、`jev_screened`、`jev_audited`、`jev_circuit_open`、`jev_deferred_evaluated`。事件不得包含 state、完整代码、响应原文或密钥。

摘要字段包括调用、错误、token、延迟、筛选、节省评估、审计精度、估算节省时间、先验状态和禁用原因。节点真实分数始终只来自任务评估器。
