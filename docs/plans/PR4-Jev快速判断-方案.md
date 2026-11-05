# PR4：Jev 快速判断（候选预筛 + UCT 扩展先验）

> 基线：以启动时最新 `main` 为准（当前 main = b59c39e，PR #2）；PR #3 `cursor/knowledge-injection-c879` 预计先合并，本方案的文件/函数名已在 PR #3 分支上核对。若启动时 PR #3 尚未合并，钩子位置不变，只是 `RunMetrics/RunSummary` 中没有 knowledge 字段。

## 1. 目标
全量评估（`benchmark/hdd_mvp/evaluator.py`，bootstrap p10 F1 + AUPRC → ROS，>600s 惩罚）是每轮最慢的一步。本 PR 让 Jev（MiYang 中继 `miyang/jev-1.13`）在评估前给候选打先验分：
- (a) **预筛**：Jev 判定“大概率无效 / 低价值”的候选跳过或延后评估；
- (b) **扩展先验**：把 Jev 对每个已评估节点的价值判断作为 UCT/PUCT 的 prior。

硬性原则：**可选、配置驱动、fail-open、全程计量**；Jev 输出永远不作为节点分数（AGENTS.md 规定），只影响“是否评估 / 先探索谁”。引擎保持任务无关。

## 2. 现状（已核对）
- `src/faultevolve/cloud/judge.py`：`JudgeClient` 只有桩（`node_prior/operator_choice/prescreen/insight_applicability/should_continue/record_outcome/get_trust` 全返回均匀/默认值），另有 `PrescreenResult`、`compute_expected_gain`、`should_defer_candidate`。
- `src/faultevolve/cloud/engine.py`：`EvolutionEngine.initialize()` 创建了 `self.judge = JudgeClient(self.config)`，但**全引擎没有任何调用**。
- `src/faultevolve/cloud/selection.py`：`UCTSelector._get_prior()` 返回均匀；`select()` 中 expand 选项也是均匀 `1/(n+1)`；`get_jev_prior()` 与 `compute_tau_weighted_prior()` 存在但未被使用。
- `src/faultevolve/config.py`：`JudgeConfig` 已有 `provider/model/base_url/api_key_env/prescreen/warmup/audit_rate/calibration_window/initial_trust/timeout_s`（PR #2 引入 base_url/api_key_env）。`evolve.yaml` 中 `judge.provider: none`、`selection.policy: uct  # "jev_puct" for Jev-guided selection`。
- `src/faultevolve/common/metering.py`：`RunMetrics.add_llm_call(metrics, purpose)` 按 purpose 累计 `generate/reflect/repair` tokens；`to_dict()`；`schemas.RunSummary` 由 `engine.run()` 组装后由 `run_local_evolution()` 写入 `run_summary.json`。
- `httpx>=0.27` 已在依赖中（可用内置 `httpx.MockTransport` 做 HTTP mock，无需新增依赖）；`respx` 只在 dev extras 中，不在 requirements.txt，**不要依赖它**。
- `tree.get_regular_children_count()` 只排除 repair 与 INVALID 子节点；节点持久化是按列存储（`store.update_node(...)`），**新增 Node 字段需要改表，本 PR 不改 Node schema**，Jev 结果放在 events 中。

## 3. 设计

### 3.1 配置（`evolve.yaml` 的 `judge` 段，扩展 `JudgeConfig`，全部有默认值、向后兼容）
```yaml
judge:
  provider: none            # none | jev | mock（mock = 离线确定性假 Jev，无网络）
  base_url: https://miyang.cn/api/v1/decisions
  api_key_env: MIYANG_API_KEY
  model: miyang/jev-1.13
  timeout_s: 5.0
  prescreen: false          # (a) 预筛开关
  invalid_threshold: 0.85   # P(无效) ≥ 此值 → 硬筛
  low_value_threshold: 0.15 # P(改进) < 此值 → 软筛
  low_value_action: skip    # skip | defer
  defer_flush_evals: 0      # 主循环结束后最多补评多少个 defer 候选（按 Jev 价值降序）
  warmup: 10                # 前 N 个候选只调用 Jev 做影子记录，不真正筛
  audit_rate: 0.1           # 被筛候选中按此比例仍然评估（审计），用于计算筛选精度
  prior: true               # (b) 需同时 selection.policy: jev_puct 才生效
  prior_tau: 0.5            # P = tau*P_jev + (1-tau)*uniform
  max_calls: 500            # 单次运行 Jev 调用上限
  max_consecutive_errors: 3 # 连续失败熔断，本次运行后续不再调用
  max_state_chars: 6000     # state 截断长度
  retries: 0
```
`provider: none`（默认）时行为与 PR4 前**完全一致**，且不发出任何 HTTP 请求。`selection.policy: jev_puct` + `judge.provider != none` + `judge.prior: true` 才启用先验。

### 3.2 新模块 `src/faultevolve/cloud/jev_client.py`
- `JevClient(config: JudgeConfig, transport: httpx.BaseTransport | None = None)`：`decide(state: str, questions: list[dict]) -> JevResponse`。`POST base_url`，header `Authorization: Bearer ${os.environ[api_key_env]}`，body `{model, state, questions}`，`httpx.Client(timeout=timeout_s)`。可选 `retries` 仅对 429/5xx。密钥不进日志/事件/异常信息。
- `JevResponse`：`answers: dict[str, dict]`、`prompt_tokens/completion_tokens/total_tokens`（取 `usage`，缺失时补 0，兼容 `input_tokens/output_tokens` 命名）、`latency_ms`。解析要宽容：`answers[name].probabilities`（choice，dict）、`.noul`（数值或 `{true: p, ...}`）、`.score`（数值，按 0–1 / 0–10 / 0–100 归一化）。
- `JevError`：网络超时、非 2xx、JSON 不合法、缺字段、缺 key 全部统一抛出，由上层 fail-open。
- `MockJevClient`：同接口，按 `sha256(code)` 确定性给出 p_invalid/p_improve（约 1/3 候选被判低价值），`usage` 按 state 长度估算（非零），供 `provider: mock` 与测试使用。

### 3.3 问题设计（task-agnostic）
一次调用问 3 个问题（同一 state）：
1. `valid`（noul）：criteria `{"true": "该候选程序能在任务约束内正常运行并产出合法输出", "false": "该候选程序会报错、违反约束或超时"}` → `p_invalid = 1 - p_true`
2. `improve`（choice）：options `["better", "same", "worse"]`，问“相对父节点的评估分数” → `p_improve = probabilities["better"]`
3. `value`（score）：“该改动的预期价值 0–1” → 作为节点先验值 `jev_value`

state 由通用字段拼接并截断：`task_spec.problem_md` 摘要、`task_adapter.constraints(task_spec)`、父节点 intent/hypothesis/分数、候选 intent/hypothesis、候选与父代码的 unified diff（`difflib`）。**不在引擎中写任何 HDD 字符串**，领域信息只来自 adapter 与任务文件。

### 3.4 `judge.py` 改造（保留原签名，替换桩）
- `JudgeClient.__init__(config, client: JevClient|MockJevClient|None = None)`：provider=none → `enabled=False`；provider=jev 且缺 key → 打一次警告、`enabled=False`（不崩）。
- `prescreen(parent, code, intent, context) -> PrescreenResult`：扩展字段 `ok: bool, p_invalid, p_improve, value, tokens, latency_ms, error`。任何 `JevError` → `ok=False`，返回默认值（不筛），计 `jev_errors`；连续错误达阈值 → 熔断。
- `should_defer_candidate()` 改为基于 `invalid_threshold/low_value_threshold` 与 warmup 给出 `decision ∈ {evaluate, skip_invalid, skip_low_value, defer}`。
- `record_outcome()`：审计/影子样本回写（预测 vs 实际），供精度统计与 `get_trust()`（可选：`tau = prior_tau * clip(precision)`）。
- `node_prior()`：基于缓存的 `jev_value` 计算同胞先验（见 3.6），不额外调用 Jev。

### 3.5 钩子 (a)：预筛 —— `EvolutionEngine._run_one_iteration()`
插入点：`static_check` 通过之后、`create_child_node(...)` / `self.task_adapter.evaluate(code, self.task_spec)` 之前：
1. `pre = self.judge.prescreen(parent, code, intent, ctx)`；`self.metrics.add_jev_call(pre)`；记录 LLMCall（purpose=`jev_prescreen`, model=judge.model）；事件 `jev_prescreen`（node_id、p_invalid、p_improve、value、decision、ok，**不含 state 原文与 key**）。
2. `decision == evaluate` 或 `ok=False` → 原流程不变。
3. 被筛（`candidates_screened += 1`）：用 `random.Random(config.seed)` 以 `audit_rate` 抽样：
   - 抽中 → 照常评估，并标记 audited；评估后判定 bad = `not is_valid` 或 `delta <= noise_delta`（`task_adapter.get_noise_delta`，任务无关），计入 `screen_audited/screen_audit_bad`。
   - 未抽中 → 不评估：`create_child_node` 后 `tree.update_node_status(child.id, NodeStatus.ABANDONED)`，事件 `jev_screened`，`evaluations_saved += 1`，`iterations_done += 1`（避免无限生成消耗 Qwen token），**不调用 `add_eval`**（valid_rate 不受影响）。`defer` 模式时同时放入 `self._deferred`（按 value 排序）。
4. warmup 期内：只调用、不筛；若决策为“应筛”则作为影子样本评估后同样计入精度统计（`screen_shadow`）。
5. `run()` 主循环结束后，若 `defer_flush_evals > 0` 且未超 token/墙钟预算，按 Jev value 降序补评 deferred 候选（评估后走正常反思），`evaluations_saved` 相应减少。
6. repair 节点（`_attempt_repair`）**不预筛**（修复链本身已有次数上限，避免误杀）。
- `tree.get_regular_children_count()` 追加排除 `NodeStatus.ABANDONED`，避免被筛节点占用渐进展宽名额。

### 3.6 钩子 (b)：扩展先验 —— `UCTSelector`
- 引擎维护 `self._jev_values: dict[node_id, float]`（来自该节点预筛时的 `value`/`p_improve`，零额外调用）；resume 时从 `store.get_events(experiment_id)` 中的 `jev_prescreen` 事件重建。
- `UCTSelector.set_node_priors(values, tau, enabled)`；`select()` 中对同一父节点的 `children + expand` 一起计算：Jev 分布 = 对有 value 的子节点按 value 归一化（无 value 的子节点与 expand 取均值填充）→ `compute_tau_weighted_prior(jev, uniform, tau)`；和为 1。未启用时 `_get_prior()` 保持严格均匀（回归测试断言）。
- `get_jev_prior()` 改为调用上述逻辑（保持签名）。可选（默认关）`prior_source: choice`：对 ≥2 子节点的父节点调用一次 Jev choice 问题，结果缓存。

### 3.7 计量（`RunMetrics` → `to_dict()` → `RunSummary` → `run_summary.json`）
新增字段（未启用时全部为 0 / null）：
| 字段 | 含义 |
|---|---|
| `jev_calls` / `jev_errors` / `jev_fail_open` | 调用数、失败数、因失败按正常评估的候选数 |
| `jev_prompt_tokens` / `jev_completion_tokens` / `jev_tokens` | 来自响应 `usage` |
| `jev_latency_ms` | 累计延迟 |
| `jev_disabled_reason` | `""` / `missing_key` / `circuit_open` / `max_calls` |
| `candidates_screened` | 被判定应筛的候选数（warmup 后） |
| `evaluations_saved` | 实际未评估的候选数 |
| `eval_time_saved_est_s` | `evaluations_saved × 平均评估耗时` |
| `screen_audited` / `screen_audit_bad` / `screen_shadow` | 审计/影子样本数与其中确为 bad 的数量 |
| `screening_precision` | `screen_audit_bad / screen_audited`（含影子样本；0 样本时为 null） |
| `jev_prior_active` | 是否启用了先验 |

`jev_tokens` 作为一个阶段与 `generate_tokens/reflect_tokens/repair_tokens/knowledge_tokens` 并列，并计入 `total_tokens`（预算诚实）。`add_llm_call(..., purpose="jev")` 分支即可。

### 3.8 CLI
- `fe judge ping [--task-dir DIR] [--env-file .env] [--json]`：读取任务 `evolve.yaml` 的 judge 配置，发 1 次最小请求，输出 ok/latency/tokens/answers 形状，exit 0/1；从不打印密钥。供自主 agent 做联通性检查。
- `fe doctor --task-dir` 已按 `judge.api_key_env` 检查密钥存在性，无需改动（确认 MIYANG_API_KEY 被检查）。
- `.env.example` 增加 `MIYANG_API_KEY=`（注释：Jev 中继，可选）。

### 3.9 Skills（自主 agent 可用，中文）
- 新增 `skill/fe-jev-screening/`：`SKILL.md`（何时使用 / 输入：`MIYANG_API_KEY`、`DASHSCOPE_API_KEY`、`judge` 配置项 / 精确命令 / 成功检查 / 故障处理：401、429、超时、熔断、精度过低时调高阈值或关闭）、`scripts/run_mock_jev.sh`（离线验证，见验收）、`scripts/check_jev_summary.py`（断言 run_summary 中 jev 指标）、`references/judge-config.md`。
- 更新 `skill/fe-evolve-manager/SKILL.md`：环境变量、`judge` 配置示例改为 MiYang 中继、run_summary 字段表增加 jev 字段、故障处理增加 Jev 条目、参考链接指向新技能。
- 更新 `docs/dev/MVP开发指南.md` 中 judge 章节（中文）。

## 4. 测试（`tests/test_jev_screening.py`，全部用 `httpx.MockTransport` 或 `MockJevClient`，CI 无真实 key）
1. 请求格式：URL、`Authorization: Bearer <monkeypatch 的假 key>`、body 含 model/state/questions，noul 问题含 `criteria.true/false`。
2. 响应解析：probabilities / noul / score / usage（含缺 usage、不同 score 量纲）。
3. fail-open：超时、500、非法 JSON、缺 key → 每个候选都被评估，`jev_errors>0`，`evaluations_saved==0`，运行 `status=finished`。
4. 熔断：连续 3 次失败后不再发请求（transport 计数）。
5. 预筛 skip：假 Jev 返回高 p_invalid → FakeAdapter 评估次数减少，`iterations_done` 仍等于上限，被筛节点状态 ABANDONED 且无分数，不占展宽名额。
6. 审计：`audit_rate=1.0` + 脚本化 FakeAdapter 结果 → `screening_precision` 精确等于期望值。
7. warmup：前 N 个不筛，影子样本计入精度。
8. defer + flush：`defer_flush_evals=1` 时补评 1 个。
9. 先验：`jev_puct` 下同胞先验非均匀且和为 1；`provider: none` 时严格均匀；resume 后从 events 重建。
10. 默认关闭回归：`provider: none` 时 transport 零调用，jev 字段全为 0，已有测试全部通过。
11. `run_local_evolution` 端到端（`provider: mock`）写出的 `run_summary.json` 含全部新字段且非零。
12. 配置：旧 `evolve.yaml`（无新字段）可加载；新字段解析正确。
13. 安全：events.jsonl / 日志中不出现假 key 字符串；引擎源码中无 HDD 专有字符串（沿用 PR3 做法）。

## 5. 验收标准
- `python -m pytest tests/ -q` 全绿（含全部既有测试）；未修改 `benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md}` 与 `data/`（`git diff --stat origin/main -- benchmark/hdd_mvp/evaluator.py benchmark/hdd_mvp/init.py benchmark/hdd_mvp/data` 为空）。
- 离线 mock：`bash skill/fe-jev-screening/scripts/run_mock_jev.sh` 退出 0，并输出 `jev_calls>0, jev_tokens>0, candidates_screened>0, evaluations_saved>0, screening_precision 非 null`。
- `benchmark/hdd_mvp/evolve.yaml` 默认 `provider: none`（行为不变），并附带注释掉的 MiYang 配置示例。
- 有真实 key 时（非 CI，可选）：`fe judge ping --task-dir benchmark/hdd_mvp --env-file .env --json` 返回 ok；10 轮真实对照（PR4 开 vs 关，同 seed）报告评估次数、总评估耗时、best_score、screening_precision。期望：评估耗时下降且 best_score 不低于关闭时 −noise_delta。
- PR 描述（中文）列出：新增技能 `skill/fe-jev-screening`、更新技能 `skill/fe-evolve-manager`；新增 run_summary 字段；fail-open 行为说明。
