# PR #7 实现计划：召回/阈值算子 + 算子老虎机（基线 main = bfeabed）

分支 `cursor/operators-bandit-52dd`。规范以 `docs/TODO.md` 步骤 4 为准。所有新配置默认值必须保持旧行为：`bandit=false` 时永远选 REFINE，不消耗随机数，不增加 LLM 调用，不增加事件。本 PR 不新增任何 LLM 调用，所以没有新的 token 阶段。回归测试要断言 `total_tokens` 与 bandit 关闭时逐字一致。

## 0. 硬规则
- 不读 `eval_only/test/holdout`。不改 `benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md,data/}`。
- 不改 `TaskAdapter` 协议。只允许新增可选 Protocol，本 PR 不需要新增。
- `cloud/*.py`、`knowledge/retriever.py` 中不得出现 `HDD|SMART|Backblaze|hard disk|disk failure`。现有测试 `test_cloud_modules_remain_task_agnostic` 和 `test_no_hdd_strings_in_operators` 会检查。
- 测试全部离线，使用 `MockLLM` 和 `FakeAdapter`。

## 1. `common/schemas.py`
`OperatorType` 追加：
```python
RECALL_FOCUS = "recall_focus"
THRESHOLD_CALIBRATE = "threshold_calibrate"
```
- `INJECT` 已存在。
- `RunSummary` 末尾追加字段，全部带默认值：
  - `operator_counts: dict[str, int] = {}`
  - `operator_valid_rate: dict[str, float] = {}`
  - `operator_mean_delta: dict[str, float] = {}`
  - `operator_posteriors: dict[str, dict[str, float]] = {}`，内部键为 `alpha`、`beta`、`mean`
  - `operator_tokens: dict[str, int] = {}`
  - `generative_valid_rate: float | None = None`
  - `bandit_active: bool = False`
- 新增常量：
  ```python
  GENERATIVE_OPERATORS = (REFINE, RECALL_FOCUS, THRESHOLD_CALIBRATE, INJECT)
  ```
  放在 schemas.py。`TRANSPLANT` 和 `REPAIR` 不属于生成类算子，不进入 bandit。
- node 表的 operator 列是 TEXT。`store.py:347` 使用 `OperatorType(row["operator"])`，新枚举值无需迁移。旧库只含旧值，可读。

## 2. `config.py`
替换 `OperatorsConfig`：
```python
class OperatorsConfig(BaseModel):
    bandit: bool = False
    enabled: list[str] = ["refine","recall_focus","threshold_calibrate","inject"]
    min_explore: float = Field(default=0.1, ge=0, le=1)
    prior_alpha: float = Field(default=1.0, gt=0)
    prior_beta: float = Field(default=1.0, gt=0)
    fn_keywords: bool = False        # 把 fn_groups 关键词加入检索上下文
    fn_keyword_groups: int = Field(default=3, ge=1, le=5)
```
- 新增 `@field_validator("enabled")`：
  - 每项必须属于 `{"refine","recall_focus","threshold_calibrate","inject"}`。
  - 必须包含 `"refine"`，作为回退。
  - 去重并保持顺序。
  - 违反时 `raise ValueError`。
- `from_dict` 已用 `OperatorsConfig(**data["operators"])`，无需修改。
- 在 `benchmark/hdd_mvp/evolve.yaml` 的 `operators:` 下追加默认值和注释（`bandit: false`）。该文件不在受保护清单里。

## 3. `cloud/store.py`
在 `DDL` 中追加。`CREATE TABLE IF NOT EXISTS` 会让老库自动建表，无需迁移。
```sql
CREATE TABLE IF NOT EXISTS operator_stats (
  experiment_id TEXT, operator TEXT,
  alpha REAL, beta REAL,
  n INTEGER DEFAULT 0, n_valid INTEGER DEFAULT 0, sum_delta REAL DEFAULT 0.0,
  PRIMARY KEY (experiment_id, operator));
```
新增 `Store` 方法：
```python
def record_operator_outcome(self, experiment_id: str, operator: str, *,
    valid: bool, success: bool, delta: float,
    prior_alpha: float = 1.0, prior_beta: float = 1.0) -> None
def get_operator_stats(self, experiment_id: str) -> dict[str, dict[str, float]]
```
- `record_operator_outcome` 首次写入时以 `prior_alpha` 和 `prior_beta` 为初值。
- 每次调用：`n += 1`；`success` 时 `alpha += 1`，否则 `beta += 1`。
- `valid` 时 `n_valid += 1`，且 `sum_delta += delta`。无效不累加 delta。
- `get_operator_stats` 返回 `{op: {alpha,beta,n,n_valid,sum_delta}}`。
- 注意：alpha 和 beta 存的是后验，含先验。之后改 prior 配置不影响已有实验。

## 4. `cloud/operators.py`
### 4.1 指令文本
`OPERATOR_INSTRUCTIONS` 追加（措辞保持任务无关）：
- `RECALL_FOCUS`：
  ```text
  依据"聚合错例画像"中的漏告（fn_groups）分组，只修改特征工程或模型部分，
  以提高这些分组的召回；禁止修改告警阈值、告警数量或告警策略相关代码。
  ```
- `THRESHOLD_CALIBRATE`：
  ```text
  只修改告警/阈值决策部分，保持特征和模型不变。
  可选做法：(a) 在训练集上用折外(OOF)预测选择使评估目标最优的阈值；
  (b) 按待评估数据的无标签得分分布分位数确定告警比例。
  禁止读取任何标签文件，禁止改动特征工程或模型结构。
  ```
- `INJECT`：追加一句"必须采纳下方唯一一张知识卡片并在 adopted_cards 中声明其 ID"。原文保留，只改这一处。

### 4.2 `build_user_message`
仅当 `ctx.operator == OperatorType.INJECT and ctx.knowledge_cards` 时：
- 章节标题改为 `## 知识卡片（必须采纳）`。
- `adopted_cards_instruction` 改为
  `<adopted_cards>{cards[0]['id']}</adopted_cards>（必须采纳，不可留空）\n`。

其它算子和 REFINE 的输出必须逐字不变。

### 4.3 选择函数
签名（保持位置参数兼容 `(node, available_operators)`）：
```python
def select_operator(node: Node | None = None,
    available_operators: list[OperatorType] | None = None, *,
    stats: dict[OperatorType, tuple[float, float]] | None = None,
    rng: random.Random | None = None,
    min_explore: float = 0.1, bandit: bool = False) -> OperatorType
```
逻辑：
1. `available_operators` 为 None 时取 `[REFINE]`。
2. `bandit` 为 False，或可用算子 ≤1，直接返回 `REFINE`。此时不得触碰 `rng`。
3. `rng = rng or random.Random(0)`；`K = len(available)`。
4. 以 `p = min(1.0, min_explore * K)` 的概率在可用算子中均匀选一个。这保证每个算子被选概率至少 `min_explore`。
5. 否则对每个可用算子取 `rng.betavariate(alpha, beta)`，返回 argmax。平局取 `available` 中靠前者。
6. 缺少 stats 的算子使用 `(1.0, 1.0)`。

不改 `get_operator_thompson_sample`，它仍是旧桩，保持兼容。

新增辅助函数：
```python
def operator_posterior_summary(rows: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]
```
返回 `{op: {"alpha":a,"beta":b,"mean":a/(a+b)}}`，数值保留 4 位小数。

`RefineOperator` 类不改，一个类服务所有生成算子，由 `ctx.operator` 决定指令。测试里有 `engine.operator = RefineOperator(llm)` 的写法，所以属性名 `engine.operator` 不能改。

## 5. `knowledge/retriever.py` 与 `cloud/selection.py`（卡片与 FN 画像关联）
- `RetrievalContext` 追加字段 `profile_keywords: list[str] | None = None`。
- `CardRetriever.retrieve`：在现有 `error_classes` 和 `last_reflection` 合并之后追加
  `if context.profile_keywords: context_keywords.update(k.lower() for k in context.profile_keywords)`。
  - 不要把画像关键词并入 `context.keywords`。当 `keywords` 非空时会跳过 `extract_keywords_from_text`；当适配器返回空列表时，并入画像词会改变回退路径。
- `get_era_knowledge_cards`：`RetrievalContext(..., profile_keywords=context.get("profile_keywords"))`。
- 新增 `cloud/operators.py::fn_profile_keywords(analysis: dict, max_groups: int = 3) -> list[str]`：
  - 遍历 `analysis.get("fn_groups", [])[:max_groups]`。
  - 对每个 group 加入 `str(g["dimension"]).lower()` 和 `str(g["value"]).lower()`。
  - 若 value 小写属于 `{"yes","true"}`，只再加一次 dimension 词，不重复添加。
  - 分组是数据驱动的，不含领域硬编码。
  - 去重，保持顺序。缺键时跳过该 group。

## 6. `cloud/engine.py`
### 6.1 `__init__` 与 `initialize`
- `__init__` 新增：
  ```python
  self._op_rng = random.Random(config.seed + 1009)
  self._op_tokens: dict[str, int] = {}   # 仅进程内
  ```
  不要使用 `self._audit_rng`。它被 Jev 审计使用，多消耗一次会改变旧行为。
- `initialize()` 在 `self.tree.load_from_store()` 之后：
  `total_n = sum(int(r["n"]) for r in self.store.get_operator_stats(self.experiment_id).values())`
  `self._op_rng = random.Random(self.config.seed + 1009 + total_n)`。这样 resume 时状态确定，并且后验来自表。

### 6.2 新方法
```python
def _available_operators(self, parent: Node) -> list[OperatorType]
def _choose_operator(self, parent: Node) -> OperatorType
def _record_operator_outcome(self, operator: OperatorType, *, valid: bool, delta: float, noise_delta: float) -> None
def _operator_summary(self) -> dict[str, Any]
```
`_available_operators` 规则，顺序与 `config.operators.enabled` 一致：
- `refine` 总是可用。
- `threshold_calibrate` 总是可用。
- `recall_focus` 仅当 `parent` 的 `evidence.evaluation.metric["analysis"]["fn_groups"]` 非空时可用。分析由 PR #6 产生。
- `inject` 仅当同时满足：
  - `self._is_knowledge_enabled()`；
  - `self._get_knowledge_dir()` 存在且目录存在；
  - `not self.budget.stage_exceeded("knowledge", self.metrics.knowledge_tokens)`。

  **不要调用 `self._stage_capped("knowledge")`**。它会累加 `metrics.stage_cap_hits` 并发出事件，导致与 `_retrieve_knowledge_cards` 内的检查重复计数。

`_choose_operator`：
- `if not self.config.operators.bandit: return OperatorType.REFINE`，不写事件，不用 rng。
- 否则：
  - `stats` 来自 `store.get_operator_stats`，缺失的算子用 `(prior_alpha, prior_beta)`。
  - 调用 `select_operator(parent, avail, stats=stats, rng=self._op_rng, min_explore=cfg.min_explore, bandit=True)`。
  - 写事件 `operator_selected`，payload 为 `{parent_id, operator, available:[...]}`。

`_record_operator_outcome`：
- 仅当 `operator in GENERATIVE_OPERATORS` 才记录。
- `valid` 时 `success = delta > noise_delta`，否则 `success = False`。
- 调用 `store.record_operator_outcome(..., prior_alpha=cfg.prior_alpha, prior_beta=cfg.prior_beta)`。

`_operator_summary()`：从 `store.get_operator_stats` 读表，输出：
- `operator_counts = n`
- `operator_valid_rate = n_valid / n`
- `operator_mean_delta = sum_delta / n_valid`（`n_valid == 0` 时为 0.0）
- `operator_posteriors = operator_posterior_summary(rows)`
- `generative_valid_rate = sum(n_valid) / sum(n)`（无数据时为 None）
- `operator_tokens = dict(self._op_tokens)`
- `bandit_active = config.operators.bandit`

### 6.3 `_run_one_iteration_inner`（约 971–1250 行）
- 顺序必须是：选 parent → `expand_gating` 重定向（第 96–100 行）→ `increment_expand_count` → `operator = self._choose_operator(parent)`。这样 `budget.expand_gating` 改写 `parent` 后，算子按最终 parent 选择。
- 第 1004 行：`OperatorContext(parent, self.task_spec, operator)`。
- 检索卡片之后（第 762 行之后的调用点）：
  - 若 `config.operators.fn_keywords`：在 `_retrieve_knowledge_cards` 的 `context` 字典里加 `"profile_keywords": fn_profile_keywords(analysis, cfg.fn_keyword_groups)`。`analysis` 取 `parent.evidence.evaluation.metric.get("analysis") or {}`。默认关闭，不改现有 context。
  - 若 `operator == INJECT`：
    - `knowledge_cards = knowledge_cards[:1]`。
    - 若为空：`operator = REFINE; ctx.operator = REFINE`，并写事件 `operator_fallback` `{parent_id, requested:"inject", used:"refine", reason:"no_card"}`。
  - `offered_card_ids` 必须在截断之后计算，并且 `add_card_adoption` 也基于截断后的列表。
- 生成后：
  - `self._op_tokens[operator.value] += prompt_tokens + completion_tokens`。这只是 generate 的子集，不新增 LLM 调用。
  - 若 `operator == INJECT` 且 `adopted_cards` 为空，则 `adopted_cards = [knowledge_cards[0]["id"]]`。
- `llm_record` 的 `create_llm_call_record(..., "refine", ...)` 保持字符串 `"refine"` 不变，以免影响 `metering` 的阶段划分。
- 第 1216 行：`create_child_node(parent, code, intent, hypothesis, operator)`。
- 所有 `_handle_invalid_generation(...)` 调用（约 6 处，含 perf_rejected、smoke、静态检查、生成失败）都追加 `operator=operator` 实参。

### 6.4 `_handle_invalid_generation`
签名增加 `operator: OperatorType = OperatorType.REFINE`（默认值保证旧调用和测试兼容）。
- `create_child_node(parent, code or "", intent, hypothesis, operator)`。
- 在写事件前调用 `self._record_operator_outcome(operator, valid=False, delta=0.0, noise_delta=0.0)`。

### 6.5 `_evaluate_child`（PR #4 重构后的公共评估路径）
- 在 `delta` 和 `noise_delta` 算出之后、`update_node_evidence` 之前或之后均可，调用一次：
  `self._record_operator_outcome(child.operator, valid=eval_result.is_valid, delta=delta, noise_delta=noise_delta)`。
- 覆盖三条路径：普通评估、Jev 审计/shadow 抽样、`_flush_deferred` 的延迟评估。三条路径最终都进 `_evaluate_child`，`child.operator` 已随节点持久化，所以这里用 `child.operator`，不要用局部变量。
- Jev 未审计而被跳过的节点：不评估，不记账。bandit 的样本因此有选择偏倚，在 SKILL 里说明。
- `_attempt_repair` 走独立评估路径，不调用 `_evaluate_child`，`create_repair_node` 的 operator 为 REPAIR。不为修复节点记账。原始无效子节点已记为一次失败，这是刻意的保守做法。
- `_evaluate_child` 调用 `_maybe_analyze_node` 早于 `_apply_reflection`，无需调整顺序。

### 6.6 `run()` 汇总
- `RunSummary(...)` 末尾追加 `**self._operator_summary()`。
- `_flush_deferred` 在 `finally` 前已执行，摘要读表发生在其后，正确。
- 崩溃摘要 `_write_artifacts` 不改。

## 7. `common/metering.py`
不新增 token 阶段（本 PR 无新增 LLM 调用），只在 `RunMetrics.to_dict()` 之外通过 `operator_tokens` 汇报（见 6.2）。不改 `add_llm_call`。

## 8. `skill/fe-evolve-manager/scripts/report_run.py`
- 保留 `refine_valid`，语义不变，仅统计 `operator == "refine"`。
- 新增 `generative_valid`：统计 `operator in {refine, recall_focus, threshold_calibrate, inject}`，格式 `"valid/total"`，与 `refine_valid` 并列输出。
- 新增透传：`operator_counts`、`operator_valid_rate`、`operator_mean_delta`、`operator_posteriors`、`operator_tokens`、`generative_valid_rate`、`bandit_active`（`summ.get(key, {})`）。

## 9. 测试
### 9.1 新文件 `tests/test_operators_bandit.py`
用 `FakeAdapter`、`MockLLM(enable_repair_scenario=False)`、`Store(tmp_path/"fe.db")`，仿照 `tests/test_node_value_budget.py::_engine`。

| 测试 | 输入 | 预期 |
|---|---|---|
| `test_select_operator_default_refine_when_bandit_off` | `select_operator(None, [REFINE, RECALL_FOCUS, INJECT], stats={RECALL_FOCUS:(50,1)}, rng=random.Random(1), bandit=False)`；并传入 `rng` 的 mock 断言未被调用 | 返回 REFINE，未消耗 rng |
| `test_thompson_prefers_rewarded_operator` | `stats={REFINE:(1,20), RECALL_FOCUS:(20,1)}`，`min_explore=0`，`random.Random(7)`，200 次 | RECALL_FOCUS ≥ 190 次 |
| `test_min_explore` | 4 个算子，`stats` 使一个算子远优，`min_explore=0.1`，`random.Random(3)`，4000 次 | 每个算子占比 ≥ 0.07 |
| `test_recall_focus_fallback_without_analysis` | 引擎 bandit 开，`FakeAdapter` 无 analysis，`enabled` 含 recall_focus；调用 `_available_operators(parent)` | 结果不含 RECALL_FOCUS；运行 6 轮后没有任何 `operator == "recall_focus"` 的节点 |
| `test_recall_focus_available_with_fn_groups` | 给 parent 的 `metric["analysis"]={"fn_groups":[{"dimension":"a","value":"x","n":12}]}` | `_available_operators` 含 RECALL_FOCUS |
| `test_operator_stats_persist_resume` | bandit 开、`enabled=[refine,threshold_calibrate]`、`min_explore=0.5`，运行 6 轮；新建 `Store` 同一路径；新引擎 `initialize(resume_id=...)` 再跑 4 轮 | `get_operator_stats` 的 `n` 总和等于两次运行的生成节点数；resume 前后 `alpha+beta` 单调不减；`operator_counts` 之和 = 累计 |
| `test_inject_forces_card` | 临时 `knowledge_dir`（`tests/test_knowledge.py` 里有造卡片的 helper，复用同样的 YAML 写法）；用 `MockLLM.set_responses` 返回不含 `<adopted_cards>` 的代码；用 monkeypatch 让 `select_operator` 返回 INJECT | 该轮 prompt（`llm` 记录的 messages）含卡片 ID 与"必须采纳"；子节点 `operator == inject`；`child.card_ids == [该卡ID]`；`offered_card_ids` 长度为 1 |
| `test_inject_fallback_no_cards` | 同上但知识目录不存在，monkeypatch 强制 INJECT | 子节点 operator 为 refine；出现 `operator_fallback` 事件 |
| `test_operator_enum_backward_compat` | `OperatorType("refine")`、`OperatorType("recall_focus")`；用旧 DDL 创建库（无 `operator_stats`）后 `Store()` 打开；写入 operator 为 `refine` 的节点并读取 | 都成功；`get_operator_stats` 返回 `{}`；node 读取无异常 |
| `test_operator_prompts_isolated` | 分别为 REFINE / RECALL_FOCUS / THRESHOLD_CALIBRATE 构造 `build_user_message` | REFINE 输出与改动前基线字符串完全一致（用同一构造再比对固定片段）；另两个含各自指令；THRESHOLD 的指令含"禁止读取任何标签文件" |
| `test_fn_profile_keywords` | `{"fn_groups":[{"dimension":"silent","value":"yes"},{"dimension":"model","value":"AB-1"}]}` | 返回 `["silent","yes","model","ab-1"]`（去重、顺序稳定）；空输入返回 `[]` |
| `test_retriever_profile_keywords_boost` | 两张卡，其中一张 tags 含 `silent`；`RetrievalContext(keywords=["x"], profile_keywords=["silent"])` | 含 `silent` 的卡排在前 |
| `test_default_behavior_unchanged` | 与 `test_default_summary_unchanged` 相同的双跑（固定 seed 42） | 所有节点 operator 均为 refine；`total_tokens` 相同；`summary.bandit_active is False`；事件中无 `operator_selected` |
| `test_bandit_summary_fields` | bandit 开、`enabled=[refine,threshold_calibrate]`、`min_explore=0.5`，12 轮，`FakeAdapter` 分数序列递增 | `operator_counts` 至少两个键；`operator_posteriors[op]` 含 `alpha/beta/mean`；`generative_valid_rate` ∈ [0,1]；`operator_tokens` 之和 ≤ `generate_tokens`；总 tokens 中没有新增阶段 |
| `test_reward_uses_noise_delta` | 直接调用 `_record_operator_outcome` 三次：`valid,delta=0.4,noise=0.5`；`valid,delta=0.6,noise=0.5`；`invalid` | 表中 alpha 增 1、beta 增 2；`n_valid=2`；`sum_delta=1.0` |
| `test_jev_deferred_updates_bandit` | 复用 `tests/test_jev_screening.py` 的 defer 装置，让一个 threshold_calibrate 子节点被 defer 后 flush | flush 之前该算子无记账；flush 之后记账 1 次 |
| `test_config_operators_validation` | `enabled=["recall_focus"]`、`enabled=["bogus"]`、`prior_alpha=0` | 均抛 `ValidationError`；默认值 `bandit=False` |
| `test_cloud_modules_agnostic_pr7` | 读取 `operators.py`、`engine.py`、`retriever.py`、`selection.py` | 正则 `HDD|SMART|Backblaze|hard\s*disk|disk failure` 无匹配 |

### 9.2 需更新的既有测试
- `tests/test_config.py`：加断言 `EvolveConfig().operators.bandit is False`、`min_explore == 0.1`。
- 全量 `python -m pytest tests/` 必须通过。

## 10. 技能
### 新增 `skill/fe-operators/SKILL.md`
- frontmatter `name: fe-operators`，`description` 一句话。
- 章节：何时使用 / 输入 / 命令 / 成功检查 / 失败处理 / 禁止事项。
- 何时使用：启用或调整召回/阈值/注入算子及 bandit；某算子无效率高；需要按算子报告。
- 输入：`operators.*` 全部键与默认值；依赖 `analysis.enabled`（recall_focus）和 `knowledge` 目录（inject）。
- 命令：
  - `bash skill/fe-operators/scripts/run_mock_operators.sh`
  - `python skill/fe-operators/scripts/check_operator_summary.py <artifacts_dir>`
  - `python skill/fe-evolve-manager/scripts/report_run.py <fe.db> <run_summary.json>`
  - `python -m pytest tests/test_operators_bandit.py -q`
- 成功检查：`bandit_active` 为 true；`operator_counts` 至少 2 个键；`operator_posteriors` 已写出；`generative_valid_rate` 不低于基线；`operator_tokens` 之和不超过 `generate_tokens`。
- 失败处理：
  - 某算子 `operator_valid_rate` 低：从 `enabled` 移除。
  - `recall_focus` 从未被选：检查 `analysis.enabled` 和 `analysis.top_k`，只有带 `fn_groups` 的父节点才可选。
  - `inject` 回退：检查知识目录和 `knowledge` 阶段 cap。
  - 全被选为 refine：确认 `bandit: true` 与 `enabled`。
  - 数据库缺表：升级后首次打开会自动建表，无需手动处理。
- 禁止：让 `THRESHOLD_CALIBRATE` 读取标签；访问 `eval_only/test/holdout`；用 LLM 输出当分数。
- 说明：跳过（Jev 未审计）的节点不参与 bandit；`refine valid` 口径见下节。
- 脚本：
  - `scripts/run_mock_operators.sh`：复制 `tests/fixtures/toy_task`，写入 `operators: {bandit: true, enabled: [refine, threshold_calibrate], min_explore: 0.4}` 和 `smoke_test.enabled: false`，跑 12 轮 mock，然后调用检查脚本。仿照 `skill/fe-node-value-budget/scripts/run_mock_budget.sh`。
  - `scripts/check_operator_summary.py`：读取 `run_summary.json`，断言字段存在、`operator_counts` 非空、`sum(operator_counts.values()) > 0`、`bandit_active` 为 true。

### 更新
- `skill/fe-knowledge-injection/SKILL.md`：新增小节"卡片与错例画像关联"，说明 `operators.fn_keywords` 与 `fn_keyword_groups`，以及 `INJECT` 强制采纳 1 张卡（含 `adopted_cards` 自动补齐的语义）。
- `skill/fe-evolve-manager/SKILL.md`：命令区新增算子 mock 与 `report_run.py` 新字段；成功检查里加 `operator_*` 字段；故障处理里加"算子无效率高"。在"读取结果"里说明 `refine_valid` 与 `generative_valid` 的口径区别。

## 11. 文档
- `docs/TODO.md` 步骤 4：勾选各项，更新表格里 PR #7 的状态和 PR 链接位置。
- 在 PR 描述中说明 `refine valid` 口径。建议以 `generative_valid_rate`（所有生成类算子）为准，`refine_valid` 仅保留兼容。

## 12. 已知陷阱（实现时逐条核对）
1. **随机数隔离**：不得使用或推进 `_audit_rng`。bandit 关闭时不得创建任何 rng 调用。
2. **`_stage_capped` 副作用**：会改 `stage_cap_hits`。可用性判断只能用 `budget.stage_exceeded`。
3. **retriever 关键词回退**：画像词只能走新的 `profile_keywords`，不要并入 `keywords`（见第 5 节）。
4. **PR #6 覆盖率**：`analyze` 只对 top-k 与 new-best 节点运行，多数父节点没有 `fn_groups`，因此真实运行中 `recall_focus` 可用比例偏低。这是预期行为，报告里要写明每个算子被选次数。不要为此新增额外的 analyze 调用（会增加成本）。
5. **`_evaluate_child` 是唯一的评估记账点**：普通路径、Jev 审计/shadow、延迟 flush 都要通过它，且用 `child.operator`。修复路径不记账。
6. **无效生成**：`_handle_invalid_generation` 的所有调用点都要传 `operator`，否则无效率会全部记到 refine 上。
7. **Jev 延迟队列在 resume 时的 `offered_card_ids` 为空**（`_restore_jev_state` 现有限制）。本 PR 不修复，只在 SKILL 里备注。
8. **PR #5**：`expand_gating` 会改写 parent，所以必须在其后选算子；bandit 奖励用 `delta > noise_delta`，不使用多目标 Q（Q 只用于选择，不写回评分）。
9. **`llm_call` 记录的 purpose 保持 `"refine"`**，避免破坏现有按阶段统计与测试。
10. **`select_operator` 默认参数**：任何现有调用者（当前只有定义处，无调用）传位置参数时要继续可用。
11. **INJECT 自动补齐 `adopted_cards`**：仅在 INJECT 且 LLM 未声明时补齐，且要在 `child.card_ids` 赋值前完成。`card_stats` 的归因仍走既有 `_evaluate_child` 逻辑。
12. **`THRESHOLD_CALIBRATE`**：无法在程序层面证明不读标签，只靠提示词约束和技能里的禁止事项；不要为此加入新的静态检查。
13. **摘要字段全部有默认值**，并且 `RunSummary` 用 `model_dump()` 写盘，旧读取脚本不受影响。

## 13. 验证清单（提交前）
```bash
python -m pytest tests/test_operators_bandit.py -q
python -m pytest tests/ -q
bash skill/fe-operators/scripts/run_mock_operators.sh
cd benchmark/hdd_mvp && python evaluator.py init.py   # val ROS 约 22.81，确认未被改动
git diff --stat -- benchmark/hdd_mvp/evaluator.py benchmark/hdd_mvp/init.py benchmark/hdd_mvp/problem.md benchmark/hdd_mvp/prompt.md benchmark/hdd_mvp/data   # 必须为空
```

## 14. 实跑（推迟到最后，现在不做）
一次真实运行，`operators.bandit: true`，同时启用 `analysis.enabled: true`、`operators.fn_keywords: true`。之后需要汇报：
- `TODO.md` §4.3 的全部指标，包括 ROS、P、R、F1、AUPRC、总 token、各阶段 token、`tokens_per_ros_point`、墙钟、`stop_reason`。
- `operator_counts`、`operator_valid_rate`、`operator_mean_delta`、`operator_posteriors`、`operator_tokens`。
- `refine_valid` 与 `generative_valid`，以及与基线的对比。
- `recall_focus` 因缺少画像而回退的次数，以及 `inject` 回退的次数。
- 每个算子产生的最佳节点数量、是否触发过 Jev 跳过。
- 是否触碰受禁数据：确认没有。
