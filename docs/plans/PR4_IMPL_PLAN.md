# PR #4 实施计划：Jev 快速判断

> 本文件是本次实现的权威计划副本。真实 Jev/LLM 运行按用户决定统一延后。

## 1. 实施边界与确定项

- 基线为 `origin/main@63ed5d1` 或更新版本。
- 不修改 HDD 基准受保护文件和数据，不读取 holdout/eval_only。
- Jev 只影响评估调度和 UCT prior；节点分数只来自 `TaskAdapter.evaluate()`。
- 中继为 `POST https://miyang.cn/api/v1/decisions`，模型 `miyang/jev-1.13`，密钥环境变量为 `MIYANG_API_KEY`。
- 默认 `judge.provider: none`、`judge.prescreen: false`，保持零 HTTP 和旧行为。
- 缺 key 在初始化时禁用：调用和错误均为 0，`jev_disabled_reason="missing_key"`。
- 全部测试离线，使用 `httpx.MockTransport` 或 fake/mock client。

## 2. 配置契约

`JudgeConfig` 默认值：

```yaml
provider: none
base_url: https://miyang.cn/api/v1/decisions
api_key_env: MIYANG_API_KEY
model: miyang/jev-1.13
timeout_s: 5.0
prescreen: false
invalid_threshold: 0.85
low_value_threshold: 0.15
low_value_action: skip
defer_flush_evals: 0
warmup: 10
audit_rate: 0.1
prior: true
prior_tau: 0.5
max_calls: 500
max_consecutive_errors: 3
max_state_chars: 6000
retries: 0
calibration_window: 30
initial_trust: 0.5
```

校验 provider、action、概率范围及非负计数。HDD 配置显式列出这些键但保持关闭；`.env.example` 使用空的 `MIYANG_API_KEY=`。

## 3. Jev HTTP 客户端

新增 `cloud/jev_client.py`：

- `JevResponse` 保存 answers、三类 token 和 latency。
- `JevError` 统一包装缺 key、超时、网络、HTTP、JSON 和 answers 错误，文本不含密钥/header。
- `JevClient.decide()` 精确发送 `{model,state,questions}`；Bearer 在调用时读取；仅 429/5xx 重试。
- usage 兼容 prompt/completion 与 input/output；仅 total 时归入 prompt。
- `parse_noul`、`parse_choice`、`parse_score` 负责裁剪、补项、归一化和三种 score 量纲。
- `MockJevClient` 依据 state SHA-256 与调用序号确定性回答；约三分之一满足筛选条件，usage 非零。

## 4. Judge 层

- `PrescreenResult` 字段：`ok, attempted, p_invalid, p_improve, value, decision, would_screen, prompt_tokens, completion_tokens, total_tokens, latency_ms, error`。
- provider 为 none 时禁用；mock 自动创建；jev 仅有 key 时创建。
- 保存 enabled、调用数、连续错误、熔断、warmup、校准数据和 value cache。
- state 固定包含任务摘要、约束、父节点 intent/hypothesis/真实分数、候选 intent/hypothesis 和 unified diff，从 diff 尾部裁剪。
- 问题固定为 `valid` noul、`improve` choice、`value` score。
- warmup 以成功响应计数，只记录 would-screen；错误 fail-open；达到错误阈值熔断；达到 max_calls 禁用。
- 决策顺序为 evaluate、skip_invalid、skip_low_value 或 defer。
- `record_outcome` 只维护窗口；`node_prior` 只读缓存；trust 返回 prior_tau。

## 5. 引擎数据流

- `EvolutionEngine` 支持注入 `task_dir` 和 `judge`，并维护单个 seeded audit RNG、Jev value cache 和 deferred 队列。
- 新增 `DeferredCandidate` 以及 prescreen context、apply、evaluate child、flush、restore 和 prior sync 方法。
- 固定顺序：选择/生成 → precheck/性能门/static/smoke → 持久化 child → Jev 预筛 → fail-open/warmup/evaluate/audit/screen。
- 未审计的筛除节点标为 `ABANDONED`，不评估、不写 evidence、不做反思/repair/卡片反馈；轮次和 saved 各加一，只发一次 iteration_complete。
- bad 定义为无效或 `delta <= noise_delta`；shadow 属于 audited 子集。
- defer flush 按 value 降序，不重复增加轮次，评估后 saved 减一。
- repair 永不预筛；resume 从事件恢复 value 和尚未 flush 的 deferred 项。
- 事件不得包含 state、完整代码、Authorization、环境变量值或原始响应。

## 6. UCT prior

- `UCTSelector.set_node_priors(values,tau,enabled)`。
- children 与可选 expand 一次联合归一化；无已知 value 或禁用时严格均匀。
- 未知 child/expand 使用已知均值；值裁剪非负；与 uniform 按 tau 混合后再次归一化。
- `get_jev_prior` 使用相同纯计算逻辑，不发请求。
- 仅 policy 为 `jev_puct`、judge enabled 且 prior 开启时激活。
- 渐进展宽同时排除 INVALID、ABANDONED 和 repair。

## 7. 计量、持久化与事件

`RunMetrics` 和 `RunSummary` 新增：

`jev_calls, jev_errors, jev_fail_open, jev_prompt_tokens, jev_completion_tokens, jev_tokens, jev_latency_ms, jev_disabled_reason, candidates_screened, evaluations_saved, eval_time_saved_est_s, screen_audited, screen_audit_bad, screen_shadow, screening_precision, jev_prior_active`。

- Jev token 计入总 token，但不计入 generate/repair/reflect。
- defer flush 的真实评估不重复计算 iteration。
- 每次调用写 `llm_call`，purpose 为 `jev_prescreen`。
- 事件为 `jev_prescreen`、`jev_error`、`jev_screened`、`jev_audited`、`jev_circuit_open`、`jev_deferred_evaluated`。
- 报告脚本输出调用、错误、fail-open、saved、估算时间、precision、prior 和禁用原因。

## 8. CLI、文档与技能

- 新增 `fe judge ping`：先加载 env 和任务 YAML，仅在副本强制 jev；成功输出 ok、latency、token、answer keys；失败只输出 error type 并退出 1。
- 开发指南改为 MiYang/MIYANG_API_KEY 和 MockTransport 离线测试。
- 新增 `skill/fe-jev-screening/`，包含严格六节、mock 脚本、summary 检查和配置参考。
- 更新 `fe-evolve-manager` 的环境变量、配置、摘要字段、成功检查与故障处理。

## 9. 测试计划

`tests/test_jev_screening.py` 离线覆盖：

1. request format；
2. response parsing variants；
3. retry only 429/5xx；
4. missing key disables without HTTP；
5. fail-open timeout/500/bad JSON；
6. circuit breaker；
7. skip reduces evaluations；
8. abandoned does not consume widening；
9. exact audit precision；
10. warmup shadow；
11. defer flush；
12. non-uniform prior sums to one；
13. uniform prior when disabled/UCT；
14. resume rebuild；
15. default-off zero HTTP；
16. e2e mock summary fields；
17. CLI ping success and sanitized failure；
18. no key in events/logs；
19. cloud modules task agnostic。

同时更新 JudgeConfig 和 metering 测试；不得删除或放宽既有测试。

## 10. 验证与验收

依次执行：

1. `python -m pytest tests/ -q`，通过数必须大于 245；
2. `bash skill/fe-jev-screening/scripts/run_mock_jev.sh`；
3. HDD mock 3 轮确认默认关闭时 Jev 字段为 0/null；
4. 检查受保护路径 diff 和云端模块领域词；
5. 不在本 PR 执行真实 Jev/LLM 调用；真实运行统一延后。

## 11. 现有代码陷阱

- 预筛必须在性能门/static/smoke 后，repair 不预筛。
- 使用现有 ABANDONED，不改数据库 schema，不往 `EvaluationResult` 添加字段。
- evaluate 逻辑需抽取，避免 defer flush 漏行为或双计轮次。
- run 会重建 metrics，需重新同步禁用原因和 prior。
- audit RNG 只初始化一次。
- iterations 包含筛除项，valid/invalid 不包含；flush 不重复加轮次。
- precision 只使用最终有真实结果的 audit/shadow。
- prior 必须在同一父节点对 children+expand 联合归一化。
- 事件和异常只记录派生量和错误类型。
