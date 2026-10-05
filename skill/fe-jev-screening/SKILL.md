---
name: fe-jev-screening
description: 配置、验证并排查 FaultEvolve 的 Jev 候选预筛与 UCT 先验。
---

## 何时使用

需要减少真实评估次数、启用 Jev-PUCT 先验、验证 MiYang 中继，或排查 Jev fail-open/熔断时使用。

## 输入

- `judge.*`：`provider`、`base_url`、`api_key_env`、`model`、`timeout_s`、`prescreen`、`invalid_threshold`、`low_value_threshold`、`low_value_action`、`defer_flush_evals`、`warmup`、`audit_rate`、`prior`、`prior_tau`、`max_calls`、`max_consecutive_errors`、`max_state_chars`、`retries`、`calibration_window`、`initial_trust`
- `MIYANG_API_KEY`：MiYang 中继密钥；`DASHSCOPE_API_KEY`：真实代码生成
- `FE_ARTIFACTS_DIR`：大产物目录；`HDD_BENCH_DATA_ROOT`：HDD 数据根目录
- SQLite 必须放服务器本地磁盘，不要把 `FE_RUNS_DIR` 指向 NAS。

## 执行命令

```bash
fe doctor --task-dir benchmark/hdd_mvp --env-file .env --json
fe judge ping --task-dir benchmark/hdd_mvp --env-file .env --json
bash skill/fe-jev-screening/scripts/run_mock_jev.sh
fe evolve local benchmark/hdd_mvp --iterations 10 --env-file .env --json
```

## 成功检查

检查脚本断言 `jev_calls>0`、`jev_tokens>0`、`candidates_screened>0`、`evaluations_saved>0`、`screening_precision is not None`、`jev_prior_active is True`。

## 故障处理

- HTTP 400：请求体须为 `state: {"text": ...}` 与按问题名键控的 `questions` 对象（非字符串 state、非 questions 数组）；`fe judge ping` 与 `JevClient` 已按此格式发送。
- 401/403：只检查 `MIYANG_API_KEY` 是否存在，随后停止 ping；不要重试错误密钥。
- 429/5xx/timeout：依赖 fail-open 与连续错误熔断，候选仍应正常评估。
- `screening_precision < 0.6`：提高 `invalid_threshold`、降低 `low_value_threshold`，或关闭 `prescreen`。
- `jev_disabled_reason=missing_key`：已安全退化为常规评估和均匀先验。

## 禁止操作

- 不打印密钥，不记录或上传 state、完整代码和 Authorization。
- 不把 Jev value 当成节点分数。
- 不联网运行测试，不读取私有数据或 `data/holdout*`。
