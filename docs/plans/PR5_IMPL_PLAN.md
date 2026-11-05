# PR #5 实施计划：多目标节点价值 + token 预算控制

基线：`main@b70ecb5`（本地 checkout 需先 `git fetch origin main && git merge --ff-only origin/main`）。分支 `cursor/node-value-budget-9848`。
规范来源：`docs/TODO.md` 步骤 3。以下与 TODO 的偏差已标 **[偏差]**。

## 0. 硬约束
- 默认配置行为、成本与旧版完全一致。不新增任何 LLM 调用，因此没有新 token 阶段；预算只做“降级/停止”。
- 不改 `TaskAdapter`；只新增一个可选 runtime_checkable Protocol。`cloud/` 内不得出现 HDD/SMART/ROS 等领域词（唯一例外：RunSummary 字段名 `tokens_per_ros_point`，由规范指定）。
- 不碰 `benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md,data/}`；测试全离线，不读 eval_only/test/holdout。
- Q 只用于选择；`best_score`、报告、`combined_score` 仍是评估器分数。
- `selection.value.mode: scalar` 时，`UCTSelector` 走**原封不动的旧代码路径**（不要重构旧公式）。

## 1. 文件清单
新建：`src/faultevolve/cloud/budget.py`、`tests/test_node_value_budget.py`、`skill/fe-node-value-budget/SKILL.md`、`skill/fe-node-value-budget/scripts/run_mock_budget.sh`、`skill/fe-node-value-budget/scripts/check_budget_summary.py`。
修改：`config.py`、`cloud/selection.py`、`cloud/engine.py`、`common/metering.py`、`common/schemas.py`（RunSummary）、`tasks/protocol.py`、`tasks/__init__.py`、`tasks/hdd_adapter.py`、`benchmark/hdd_mvp/evolve.yaml`（仅追加默认值段）、`skill/fe-evolve-manager/SKILL.md`、`skill/fe-evolve-manager/scripts/report_run.py`、`docs/TODO.md`（勾选 PR #5）。

## 2. 配置（`config.py`）
```python
class SelectionValueConfig(BaseModel):
    mode: str = Field(default="scalar", pattern="^(scalar|multi)$")
    lambda_rank: float = Field(default=0.3, ge=0)
    lambda_noise: float = Field(default=1.0, ge=0)
    backup: str = Field(default="max", pattern="^(max|softmax)$")
    elite_m: int = Field(default=3, ge=0)
    elite_prob: float = Field(default=0.2, ge=0, le=1)   # 仅 multi 生效
    rank_keys: list[str] = []        # 非空则覆盖适配器 ObjectiveSpec
    threshold_keys: list[str] = []
    noise_key: str = ""
class SelectionConfig:  value: SelectionValueConfig = Field(default_factory=SelectionValueConfig)
class BudgetConfig:  # 保留原三字段，追加：
    stage_caps: dict[str, float] = {}          # 默认空=不限；键仅允许 reflect/repair/knowledge/jev，值 (0,1]，占 max_tokens 比例
    stagnation_window: int = Field(default=0, ge=0)   # 0=关闭 [偏差: TODO 默认 8，为保持旧行为改 0]
    tokens_per_point_cap: float | None = Field(default=None, gt=0)
    min_iterations_before_stop: int = Field(default=5, ge=0)
    safety_factor: float = Field(default=1.5, ge=1)
    expand_gating: bool = False
    cost_window: int = Field(default=5, ge=1)
```
- `stage_caps` 用 `@field_validator` 校验键/值，非法抛 `ValueError`。
- `from_dict` 现有 `SelectionConfig(**data["selection"])`、`BudgetConfig(**data["budget"])` 会自动把嵌套 dict 转成模型，无需改；`with_overrides`（model_dump 往返）必须保持字段不丢——用测试锁定。注意 `data["selection"]` 里可能带 `widening`（被 pydantic 忽略），勿改这段逻辑。
- `benchmark/hdd_mvp/evolve.yaml` 追加（全部等于默认）：`selection.value: {mode: scalar, lambda_rank: 0.3, lambda_noise: 1.0, backup: max, elite_m: 3, elite_prob: 0.2}`；`budget` 下加 `stage_caps: {}`、`stagnation_window: 0`、`tokens_per_point_cap: null`、`min_iterations_before_stop: 5`、`safety_factor: 1.5`、`expand_gating: false`、`cost_window: 5`，注释里写推荐实跑值 `stage_caps {reflect: 0.25, repair: 0.35, knowledge: 0.1, jev: 0.1}`、`stagnation_window: 8`。

## 3. 可选 Protocol（`tasks/protocol.py`，并在 `tasks/__init__.py` 导出）
```python
@runtime_checkable
class ObjectiveSpec(Protocol):
    def objectives(self) -> list[str]: ...            # 排序质量指标 key，越大越好
    def threshold_objectives(self) -> list[str]: ...  # 阈值质量指标 key，越大越好
    def noise_metric(self) -> str: ...                # 噪声指标 key（越小越好）
```
- `HDDAdapter` 新增三方法：`["auprc","recall_at_far"]`、`["f1_p10"]`、`"f1_boot_std"`。**[偏差]** TODO 的“F1_p10 − F1 差”越接近 0 越稳但会奖励低 F1，改用 `f1_p10` 相对增益作为阈值质量。
- 不改 `FamouAdapter`/`FakeAdapter`；它们靠 `selection.value.rank_keys/threshold_keys/noise_key` 配置驱动（优先级：配置非空 > 适配器 > 无）。

## 4. 选择器（`cloud/selection.py`）
新增（同文件，无领域词）：
```python
SOFTMAX_TEMP = 0.1
def _num(metric: dict, key: str) -> float | None   # 仅接受顶层 int/float（排除 bool、nan、inf、dict）；metric["analysis"] 是嵌套 dict，自然被忽略

class EliteArchive:
    def __init__(self, m: int) -> None            # 两个列表 self.rank / self.threshold: list[tuple[float,str]]
    def update(self, node_id: str, rank_q: float | None, thr_q: float | None) -> None
        # 各自按 (-q, node_id) 排序保留 top-m；None 不入档；同 id 重复更新先删旧再插；m==0 不保存
    def ids(self) -> list[str]                     # rank ids + threshold ids（允许重复=重叠者权重更高）
    def sizes(self) -> dict[str, int]              # {"rank": n, "threshold": n}
```
`UCTSelector` 新增：
- `__init__`：`self.value_cfg = config.selection.value`；`self._value_rng = random.Random(config.seed)`（**独立 RNG，不得复用引擎 `_audit_rng`，否则改变 Jev 审计序列**）；`self.elite = EliteArchive(value_cfg.elite_m)`；`self._rank_keys/_thr_keys/_noise_key` 初始取配置；`self._ref_metric: dict = {}`；`self._multi_fallback_logged = False`。
- `set_objective_spec(rank_keys: list[str], threshold_keys: list[str], noise_key: str) -> None`：仅在对应配置为空时采用适配器值。
- `set_reference(node: Node) -> None`：保存 root 的 metric 作为基准 `_ref_metric`（init 后、resume 后调用）。
- `@property multi_active -> bool`：`mode=="multi"` 且 `_ref_metric` 中至少有一个可用 rank 或 noise key；否则 False（**退化为 scalar**）。
- `_rank_gain(metric) -> float`：对每个 rank key，`(m - ref)/max(abs(ref),1e-6)`，缺失/ref 缺失的 key 跳过；无可用 key 返回 0；取均值并 clip 到 [-1,1]。
- `_threshold_quality(metric) -> float | None`：同上但用 threshold_keys，无可用返回 None。
- `_noise_pen(metric) -> float`：`(std-ref_std)/max(ref_std,1e-6)` clip [-1,1]；缺失返回 0。
- `_node_value(node) -> float | None`：无效返回 None（`evaluation is None`、`validity<1`、`status in (INVALID, ABANDONED)`）；否则 `(score-initial_score)/normalizer + lambda_rank*rank_gain - lambda_noise*noise_pen`，`normalizer=max(best_score-initial_score,1.0)`。
- `_subtree_value(node_id, tree) -> float | None`：DFS 遍历子树（含自身，所有有效节点，含 repair 节点）；`backup=="max"` 取最大；`"softmax"` 取 `Σ v·w`，`w=softmax(v/SOFTMAX_TEMP)`（数值稳定：先减 max）；无有效节点返回 None。每次 `select()` 开头清空 `self._memo`。
- `_compute_q` / `_compute_expand_ucb`：
  ```python
  if not self.multi_active: <原代码原样>
  else:
      sub = self._subtree_value(child.id, tree); ref = self._node_value(parent)
      if sub is None or ref is None: return 0.0   # 与旧版“无效节点得 0”一致
      return max(0.0, sub - ref - self.noise_delta/normalizer)
  ```
  `_compute_expand_ucb` 对 `node`/`node` 同样处理（sub 用 node 自己的子树，ref 用 node）。
- `observe_node(node: Node) -> None`：有效节点在评估后调用；仅当 `multi_active and elite_m>0`：`elite.update(node.id, rank_gain, threshold_quality)`。
- `select()` 精英抽取（仅 `multi_active and elite.ids()` 且 `_value_rng.random() < elite_prob` 时）：在循环前 `pick = _value_rng.choice(elite.ids())`，节点存在且 `is_expandable()` 则对根到该节点路径上每个节点调用 `tree.increment_visit_count`，返回 `SelectionResult(node, True, {})`；否则走原逻辑。**必须每次都先调用一次 `_value_rng.random()`（仅 multi_active 时），保证确定性。**
- 新增 `elite_sizes() -> dict[str,int]`。

## 5. BudgetController（`cloud/budget.py`，任务无关）
```python
STAGES = ("reflect", "repair", "knowledge", "jev")
class BudgetController:
    def __init__(self, cfg: BudgetConfig) -> None    # best_history: list[float]; stage_cap_hits: dict[str,int]; _costs: deque(maxlen=cfg.cost_window); _eval_times: deque
    def stage_cap_tokens(self, stage: str) -> int | None   # int(frac * cfg.max_tokens)，未配置 None
    def stage_exceeded(self, stage: str, used_tokens: int) -> bool   # cap 不为 None 且 used_tokens >= cap
    def note_cap_hit(self, stage: str) -> bool               # 计数+1；首次返回 True（引擎据此只打一次事件）
    def record_iteration(self, tokens: int, eval_s: float) -> None
    def expected_iteration_tokens(self) -> float             # 滑动均值；无数据 0.0
    def remaining_tokens(self, used: int) -> int             # max(0, cfg.max_tokens-used)
    def should_expand(self, used_tokens: int, is_top_node: bool) -> bool
        # not expand_gating -> True; is_top_node -> True; 无历史 -> True; 否则 remaining >= expected*safety_factor
    def record_best(self, best_score: float) -> None         # 追加 best_history
    def check_stop(self, *, iterations_done: int, total_tokens: int, best_score: float,
                   initial_score: float, noise_delta: float) -> str   # "" | "stagnation" | "tokens_per_point_cap"
```
`check_stop` 规则：`iterations_done < min_iterations_before_stop` → `""`。
- stagnation：`window>0 and len(best_history) >= window+1 and best_history[-1]-best_history[-1-window] < noise_delta`。
- tokens_per_point_cap：`cap is not None`，`gain=best-initial >= noise_delta`（**避免微小增益导致除数近 0 而误停**）且 `total_tokens/gain > cap`。
- 先判 stagnation 再判 cap。

## 6. 引擎（`cloud/engine.py`）
不要重复展开 `_run_one_iteration` 内部；仅加钩子。
1. `__init__`：`self.budget = BudgetController(config.budget)`；`self._budget_stop_reason = ""`；`self._initial_score = 0.0`。
2. `initialize()`（`_create_and_evaluate_init`/resume 之后、`_sync_selector_priors` 之前）：`if isinstance(self.task_adapter, ObjectiveSpec): self.selector.set_objective_spec(a.objectives(), a.threshold_objectives(), a.noise_metric())`（try/except → 事件 `objective_spec_failed`）；`self.selector.set_reference(root)`；`for n in tree.nodes.values(): _observe_node(n)`（resume 重建精英档案）。若 `mode=="multi" and not selector.multi_active`，`_log_event("value_mode_fallback", {"reason": "no_objective_metrics"})` 一次。
3. `run()`：`RunMetrics` 重建后保持；`initial_score` 变量已有，赋给 `self._initial_score`。注意 resume 时 token 计数本就是“本次会话”，`stage_caps`/`max_tokens` 同口径，不要额外恢复。
4. 新增 `_observe_node(node)`：有效则 `self.selector.observe_node(node)`。在**两处**调用：`_evaluate_child` 的 `if eval_result.is_valid:` 分支（`update_best_score` 旁，`_apply_reflection` 之前）与 `_attempt_repair` 中对应分支（`update_best_score` 旁；此函数是独立的重复评估路径，容易漏）。初始节点在 `initialize` 中已处理。
5. `_run_one_iteration` 重命名为 `_run_one_iteration_inner`，新增同签名包装：
   ```python
   def _run_one_iteration(self) -> bool:
       t0 = self.metrics.total_tokens; e0 = self.metrics.total_eval_time_s
       ok = self._run_one_iteration_inner()
       self.budget.record_iteration(self.metrics.total_tokens - t0, self.metrics.total_eval_time_s - e0)
       self.budget.record_best(self.tree.get_global_best()[1])
       return ok
   ```
   （`selection_failed` 返回 False 时同样记录，避免历史缺口。）
6. 扩展门控：在 inner 中 `parent = result.node` 之后、`increment_expand_count` 之前：
   ```python
   top = self._top_nodes(3)   # 有效且 is_expandable，按 (-score, id) 取前 3
   if not self.budget.should_expand(self.metrics.total_tokens, parent.id in {n.id for n in top}) and top:
       parent = top[0]; self.metrics.expand_skipped_budget += 1
       self._log_event("expand_redirected_budget", {"to": parent.id})
   ```
   **陷阱**：不得“跳过本轮”——`iterations_done` 不增会死循环；只能改派到最优节点。
7. 阶段降级（均为 `_stage_capped(stage) -> bool` 帮助函数：`exceeded = self.budget.stage_exceeded(stage, used)`；命中则 `metrics.stage_cap_hits[stage] += 1` 并在 `note_cap_hit` 首次时 `_log_event("budget_stage_cap_hit", {"stage","used","cap"})`）。已用量：`reflect→metrics.reflect_tokens`，`repair→repair_tokens`，`knowledge→knowledge_tokens`，`jev→jev_tokens`：
   - `reflect`：在 `_apply_reflection` 中 `abs(delta) > design_threshold` 分支、调用 `reflect_with_llm` **之前**判断，命中则走 `_reflect_rule_based(parent, child, delta, design_thr, hyp_thr, adopted_cards)` 并 return：`delta>design_thr` → 仅 `tree.update_hypothesis_status(child.id, SUPPORTED)`（**不得**创建空 Insight，否则污染 branch memory）；`delta<-hyp_thr` → `_reflect_hypothesis_refuted(..., None, adopted_cards)`；`delta<-design_thr` → `_reflect_design_issue(..., None)`。这三个方法已支持 `reflection=None`。implementation 层（无效候选）本就是规则式，不受限。
   - `repair`：`_attempt_repair` 函数第一行；命中直接 return（其递归调用同样经过此处）。
   - `knowledge`：`_retrieve_knowledge_cards` 开头返回 `[]`。
   - `jev`：`_apply_prescreen` 中在 `judge.enabled` 检查之后、`judge.prescreen` 之前返回 `PrescreenResult()`（fail-open=评估，不计 jev_errors，不影响熔断）。
8. 停止：`_should_stop` 末尾（token 检查之后）：
   ```python
   reason = self.budget.check_stop(iterations_done=self.metrics.iterations_done, total_tokens=self.metrics.total_tokens,
       best_score=self.tree.get_global_best()[1], initial_score=self._initial_score, noise_delta=self.selector.noise_delta)
   if reason: self._budget_stop_reason = reason; self._log_event("budget_stop", {"reason": reason}); return True
   ```
   `_get_stop_reason`：在 target 检查之后、`max_iterations` 检查之前 `if self._budget_stop_reason: return self._budget_stop_reason`。（否则会落到 `"unknown"`。）
9. 交互陷阱：
   - PR#4 Jev：先验只走 `_compute_option_priors`，与 Q 无关，勿动；ABANDONED（被筛掉）节点 score=0，multi 的 `_node_value` 必须返回 None 排除；`_flush_deferred` 经 `_evaluate_child`，自动获得 `_observe_node`；`_flush_deferred` 不受停滞停止约束（保持原样）。
   - PR#6：`_maybe_analyze_node` 用新 `NodeEvidence` 覆盖 evidence（metric 带 `analysis` 嵌套 dict）。`_num` 只读顶层数值，且 `_observe_node` 在 analysis 之后/之前均可，因为 rank/noise key 不变。
   - `tree.subtree_best` 只跟踪 score，multi 不使用它；勿改 `tree.py`。
   - `_evaluate_child` 已被 `_flush_deferred` 复用（`count_iteration=False`）；钩子放在其内部而非 `_run_one_iteration_inner`。
10. `run()` 构造 `RunSummary` 追加：
    ```python
    tokens_per_ros_point=(round(total_tokens/(best-initial),2) if best-initial>0 else None),
    stage_cap_hits=dict(self.metrics.stage_cap_hits), budget_stop_reason=self._budget_stop_reason,
    elite_archive_sizes=self.selector.elite_sizes(), expand_skipped_budget=self.metrics.expand_skipped_budget,
    value_mode="multi" if self.selector.multi_active else "scalar",
    ```

## 7. 计量与 schema
- `RunMetrics`：新增 `stage_cap_hits: dict[str,int] = field(default_factory=dict)`、`expand_skipped_budget: int = 0`；`to_dict` 加两键。`stage_cap_hits` 用 `self.metrics.stage_cap_hits[s] = get(s,0)+1`。
- `RunSummary`：`tokens_per_ros_point: float | None = None`、`stage_cap_hits: dict[str,int] = Field(default_factory=dict)`、`budget_stop_reason: str = ""`、`elite_archive_sizes: dict[str,int] = Field(default_factory=dict)`、`expand_skipped_budget: int = 0`、`value_mode: str = "scalar"`。
- 崩溃摘要 `_write_artifacts` 不改。
- 事件：`budget_stage_cap_hit`、`expand_redirected_budget`、`budget_stop`、`value_mode_fallback`、`objective_spec_failed`。

## 8. 测试 `tests/test_node_value_budget.py`
辅助：`store` fixture 用 `tmp_path/"fe.db"`；`_tree(store)` 建 root(score 20, metric `{auprc:.10, recall_at_far:.10, f1_boot_std:.02}`)；`_add(tree, parent, id, score, metric)` 用 `create_child_node` + `update_node_evidence`（validity 1.0）；引擎类测试用 `FakeAdapter`+`MockLLM`+`FakeTaskSpec`（参考 `tests/test_error_analysis.py::_engine`）。多目标配置：`cfg.selection.value.mode="multi"; rank_keys=["auprc","recall_at_far"]; noise_key="f1_boot_std"`；selector `set_initial_score(20)`、`update_best_score(22)`、`set_noise_delta(0.0)`、`set_reference(root)`。
1. `test_q_scalar_default_unchanged`：默认配置，root→A(22)、B(21.6)。断言 `_compute_q(A)==1.0`、`_compute_q(B)==0.8`（=(sub-20-0)/2）；即使调用 `set_objective_spec` 也不变。
2. `test_q_multi_prefers_rank_gain`：multi，A(score22, auprc .10, raf .10, std .02)，B(score21.6, auprc .20, raf .14, std .02)。rank_gain(B)=mean(1.0,0.4)=0.7 → V_B=0.8+0.21=1.01 → 断言 `Q_B==pytest.approx(1.01)`、`Q_A==pytest.approx(1.0)`、`Q_B>Q_A`；同配置 scalar 下 `Q_A>Q_B`。
3. `test_q_noise_discount`：A(22, std .02)，B(22, std .04)，lambda_noise=1 → `Q_A==1.0`、`Q_B==0.0`；lambda_noise=0 → 二者相等。
4. `test_q_softmax_backup`：root 下 X 有两个子孙值 1.0 与 0.0，`backup="softmax"` 时 `0<Q<max 值`，`backup="max"` 时等于 max。
5. `test_elite_archive`：`EliteArchive(2)`；update n1..n4，rank_q `[.1,.5,.3,.4]`、thr_q `[.9,.1,.2,.3]` → `rank ids=[n2,n4]`、`threshold ids=[n1,n4]`、`sizes=={"rank":2,"threshold":2}`、`ids()` 长度 4；重复 update n2 的 rank_q=0 后 n2 被 n3 取代；`m=0` 时 sizes 全 0。
6. `test_elite_selection_deterministic`：`elite_prob=1.0`，档案含 n2；`select(tree)` 返回 n2 且 `should_expand=True`；同 seed 两个 selector 序列一致；scalar 模式下不调用 `_value_rng`（返回值与旧路径一致）。
7. `test_missing_metric_fallback`：multi 但所有节点 metric=`{}` 且无 spec → `multi_active is False`，Q 与 scalar 数值一致；引擎 `initialize()` 后事件里有 `value_mode_fallback`，summary `value_mode=="scalar"`。
8. `test_config_roundtrip_and_validation`：`EvolveConfig.from_dict({"selection":{"value":{"mode":"multi","elite_m":5}},"budget":{"stage_caps":{"reflect":0.25},"stagnation_window":8}}).with_overrides(seed=1)` 保留全部字段；`stage_caps={"bogus":0.1}` 与 `{"reflect":1.5}` 抛 `ValidationError`/`ValueError`；默认 `mode=="scalar"`、`stage_caps=={}`、`stagnation_window==0`。
9. `test_budget_stage_cap_degrades_reflect`：`max_tokens=1000`、`stage_caps={"reflect":0.25}`；`initialize()` 后置 `engine.metrics.reflect_tokens=300`，用会计数的 `MockLLM` 子类（重写 `chat_for_reasoning` 计数）调用 `_apply_reflection(parent, child, delta=5.0, noise_delta=0.5, FakeEvalResult(valid), [])` → LLM 计数为 0、`metrics.stage_cap_hits=={"reflect":1}`、子节点 `hypothesis_status==SUPPORTED`、无 Insight 入库；`reflect_tokens=0` 时计数为 1。
10. `test_budget_stage_caps_repair_knowledge_jev`：repair 超限时 `_attempt_repair` 不调用 `repair_operator.generate`；knowledge 超限时 `_retrieve_knowledge_cards` 返回 `[]`；jev 超限（`judge.provider="mock", prescreen=True`）时 `_apply_prescreen` 返回 `decision=="evaluate"` 且 mock judge 的 `prescreen` 未被调用；各自 `stage_cap_hits` 计数为 1，`budget_stage_cap_hit` 事件仅一条。
11. `test_stagnation_stop`：`stagnation_window=3, min_iterations_before_stop=0, max_iterations=20`，FakeAdapter 恒定 `combined_score=22.0, metric={}`（noise 0.5）；`run()` 后 `summary.stop_reason=="stagnation"`、`summary.budget_stop_reason=="stagnation"`、`len(engine.budget.best_history)==4`。窗口 0（默认）：`max_iterations=5` 时 `stop_reason=="max_iterations"`。
12. `test_tokens_per_point_cap_unit`：`BudgetController(cap=1000, min_iter=0).check_stop(iterations_done=10,total_tokens=5000,best_score=22,initial_score=20,noise_delta=0.5)=="tokens_per_point_cap"`（2500>1000）；`best_score=20.3` → `""`（增益<noise）；`iterations_done=3, min_iter=5` → `""`。
13. `test_expand_gating`：controller 单测——`expand_gating=True,max_tokens=1000,safety=1.5`，`record_iteration(400,1)` 后 `should_expand(used=500,is_top_node=False)` 为 False（剩 500<600），`is_top_node=True` 为 True，`used=100` 为 True；gating 关闭恒 True。引擎级：monkeypatch `selector.select` 返回低分节点，预算不足时 `metrics.expand_skipped_budget==1` 且 `tree.nodes[best].expand_count` 增加，迭代仍推进。
14. `test_tokens_per_ros_point_in_summary`：FakeAdapter 结果 `[22, 24, 24, ...]`，`summary.tokens_per_ros_point==round(summary.total_tokens/(summary.best_score-summary.initial_score),2)`；恒定分数时为 `None`；且 `run_summary.json`（`run_local_evolution` 或 `model_dump`）含 `stage_cap_hits/budget_stop_reason/elite_archive_sizes/expand_skipped_budget/value_mode`。
15. `test_default_summary_unchanged`：默认配置运行后新字段为 `{}`/`""`/`{}`/`0`/`"scalar"`；`total_tokens` 与在同 seed 下 `stage_caps` 未设置的运行一致（不引入额外调用）。
16. `test_hdd_adapter_objective_spec`：`isinstance(HDDAdapter(), ObjectiveSpec)`，三方法返回值如第 3 节；`isinstance(FakeAdapter(), ObjectiveSpec)` 为 False。
17. `test_multi_with_jev_prior`：`policy="jev_puct"`、mock judge、`mode="multi"`，跑 6 次迭代不抛错，`select()` 结果仍含 `prior`；先验项不因 multi 改变（同一 `_compute_option_priors` 输出）。
最后运行 `python -m pytest tests/`，全部原有测试须通过。

## 9. 技能（名称沿用任务约定 `fe-node-value-budget`；TODO 中的 `fe-budget-control` 视为同一技能）
`skill/fe-node-value-budget/SKILL.md`（frontmatter：`name: fe-node-value-budget`，`description: 配置多目标节点价值与 token 预算控制，并核对 run_summary 预算字段。`），章节：
- 何时使用：token 超预算、每分 token 过高、长期停滞、best 不稳定（追噪声）。
- 输入：`selection.value.*`、`budget.*`；`rank_keys/noise_key`（非 HDD 任务必填，HDD 由适配器提供）。
- 命令：`bash skill/fe-node-value-budget/scripts/run_mock_budget.sh`（复制 `tests/fixtures/toy_task`，写入 multi + `max_tokens: 20000` + `stage_caps: {reflect: 0.01}` + `stagnation_window: 4` 的 evolve.yaml，`fe evolve local ... --mock --iterations 12 --json`，随后运行 `check_budget_summary.py`）；`python skill/fe-evolve-manager/scripts/report_run.py <db> <run_summary>`。注意 MockLLM 每次调用约 250 token（cap=200 即首次反思后触发），实现时按实际调整并保证脚本断言稳定。
- 成功检查（`check_budget_summary.py` 断言）：`tokens_per_ros_point` 键存在（增益>0 时为正数）；`value_mode=="multi"`；`stage_cap_hits.get("reflect",0)>0`；`budget_stop_reason in ("", "stagnation", "tokens_per_point_cap")`；`elite_archive_sizes` 两键存在；`best_score` 等于评估器分数（不是 Q）。
- 故障处理：过早停止 → 增大 `stagnation_window`/`min_iterations_before_stop`；`value_mode_fallback` 事件 → 检查 `rank_keys`/评估器 metric 键；搜索偏移或 best 下降 → `mode: scalar`；降级过多 → 调大对应 `stage_caps`；`tokens_per_point_cap` 误停 → 放宽或置 `null`。
- 禁止：用 Q 值报告分数；改评估器/数据；在 cloud 代码中加入领域词；把密钥写入配置。
- 实跑后待报告（现在不执行）：一次真实 `mode: multi` 运行，报告 §4.3 指标 + `tokens_per_ros_point`、`budget_stop_reason`、`stage_cap_hits`、`elite_archive_sizes`、`expand_skipped_budget`、`value_mode`，并与 PR #6 实跑对比每分 token；按合并规则（最优 − 约 2）判断。
`fe-evolve-manager` 更新：`SKILL.md` 在 evolve.yaml 示例加入 `selection.value`/`budget` 新键（注明默认关闭）；“run_summary.json 字段”加新六字段；成功检查代码块加 `if summary.get('value_mode')=='multi': assert 'tokens_per_ros_point' in summary`；故障处理加“预算/停滞停止”小节并链接 `fe-node-value-budget`。`report_run.py`：`tokens_per_ros_point` 优先取 `summ.get("tokens_per_ros_point")`（缺失才回退原计算），并输出 `budget_stop_reason/stage_cap_hits/elite_archive_sizes/expand_skipped_budget/value_mode`。

## 10. 实施顺序与验收
1) config+schemas+metering+protocol → 2) selection → 3) budget.py → 4) engine → 5) hdd_adapter → 6) tests → 7) skills/yaml/docs → 8) `python -m pytest tests/`、`cd benchmark/hdd_mvp && python evaluator.py init.py`（应仍 ≈22.81）、`bash skill/fe-node-value-budget/scripts/run_mock_budget.sh`。
每步跑相关测试；`total_tokens`、默认摘要值在默认配置下须与改动前一致。
