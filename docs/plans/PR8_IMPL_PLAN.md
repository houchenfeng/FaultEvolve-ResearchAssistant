# PR #8 实现计划：交叉/集成算子（CROSSOVER）

基线：main = a37f88f。规则：默认关闭且行为/成本零变化；不改 TaskAdapter 协议；`cloud/`、`common/` 不出现 HDD/SMART 等词；测试全离线；不读 eval_only/test/holdout；分数只来自本地 evaluator。
分支名：`cursor/crossover-ensemble-<suffix>`（按环境要求带后缀）。

## 0. 已核实的代码事实（坑）

1. **所有节点 `branch_id` 都是 `"main"`**（`create_child_node` 继承父节点；仅 `engine.py:300` 建根）。不能用 `branch_id` 判断“不同分支”。必须自定义 `branch_key(node, tree)`：沿 `parent_id` 上溯到 depth==1 的祖先，返回其 id；根节点（depth 0）返回 `"root"`。
2. `select_operator` 在 `bandit=False` 时恒返回 REFINE。所以交叉算子只在 `operators.bandit: true` 时生效；配置校验必须强制这一点。
3. `_record_operator_outcome` 只记录 `GENERATIVE_OPERATORS` 内的算子；`CROSSOVER` 必须加入该元组，否则不进 bandit。`_operator_summary` 已按 `operator_stats` 全部行汇总，`generative_valid_rate` 会自动包含 crossover。
4. `select_operator` 探索概率 `min(1, min_explore*k)`：加入第 5 个臂会提高探索率，仅在启用交叉时发生，可接受。
5. `_evaluate_child` 用 `delta = score - parent.get_score()`，同一 delta 同时用于 bandit、`NodeEvidence.delta_score`、reflection、卡片统计。交叉节点的基线必须是两父分数的最大值，否则“比弱父强”也算成功。
6. Jev 预筛（`_apply_prescreen`）只看 parent_a，会误判集成程序 → 交叉节点**跳过预筛**（返回 `PrescreenResult()`，decision 为 `evaluate`），因此也不会进入 `_deferred`；`_flush_deferred` 无需改动。
7. PR #6 分析只对新最优/top_k 节点做，所以候选伙伴常无 `metric["analysis"]`；必须有降级路径（metric 差异近似）。`fn_groups` 元素为 `{dimension,value,n,share,group_recall}`，且只保留前 5 个。
8. KD1 `_harvest_discovery_candidates` 的 insight/top_node 分支用 `node.parent_id` 取父代码做“父→子”对比；交叉节点会被错误归因 → 这两个分支要跳过 `operator == CROSSOVER` 的节点。
9. `_apply_reflection` 会调用 LLM 生成 insight、可能把假设标记为 REFUTED（使节点不可扩展）。交叉节点**跳过反思**（不花 token，不产生 insight），并记事件。
10. `_attempt_repair` 的修复节点 `parent_id = failed.parent_id`（parent_a），算子为 REPAIR，不写 `node_parents`；修复时只给 parent_a 代码，属已知限制，写入技能。
11. `Store._init_db` 每次都执行整份 `DDL`（`CREATE TABLE IF NOT EXISTS`），新表旧库自动创建，无需迁移。
12. `_engine()` 测试辅助会把 `engine.operator` 换成 `RefineOperator`；交叉算子必须放在**独立属性** `engine.crossover_operator`，避免互相覆盖。
13. 知识卡检索、foreign insights 会增加 prompt；交叉节点不检索卡（`knowledge_cards=[]`、`offered_card_ids=[]`），不用 foreign insights。
14. `run_summary` 里 `operator_tokens` 之和目前 ≤ `generate_tokens`；交叉 token 走新阶段 `crossover`，不再计入 `generate_tokens`，需同步改技能里的检查语句与 `check_operator_summary.py`。

## 1. 配置（`src/faultevolve/config.py`）

新增类（放在 `OperatorsConfig` 之前）：

```python
class CrossoverConfig(BaseModel):
    enabled: bool = False
    min_valid_nodes: int = Field(default=4, ge=2)
    runtime_budget_s: float = Field(default=300.0, gt=0)
    top_quantile: float = Field(default=0.3, gt=0, le=1)
    max_code_chars: int = Field(default=6000, ge=500)   # 每份父代码的字符上限
```

`OperatorsConfig` 增加 `crossover: CrossoverConfig = Field(default_factory=CrossoverConfig)`，并加：

```python
@model_validator(mode="after")
def _crossover_requires_bandit(self) -> "OperatorsConfig":
    if self.crossover.enabled and not self.bandit:
        raise ValueError("crossover requires operators.bandit")
    return self
```

- 不改 `enabled` 白名单与默认值（交叉臂由 `crossover.enabled` 控制，不由 `enabled` 列表控制）。
- 需 import `model_validator`（文件已有则复用）。
- `_BUDGET_STAGE_KEYS` 增加 `"crossover"`（允许 `stage_caps.crossover`）；`cloud/budget.py::STAGES` 同步增加 `"crossover"`。默认不设 cap。
- `from_dict` 无需改（`OperatorsConfig(**data["operators"])` 会解析嵌套 dict；`with_overrides` 的 `model_dump` 往返也成立）。

## 2. 枚举与 schema

`common/schemas.py`：
- `OperatorType.CROSSOVER = "crossover"`（放在 `TRANSPLANT` 之后、`REPAIR` 之前或末尾均可，值不变）。
- `GENERATIVE_OPERATORS` 追加 `OperatorType.CROSSOVER`。
- `RunSummary` 追加（均有默认）：
  `crossover_count: int = 0`、`crossover_valid_rate: float | None = None`、`crossover_mean_delta: float | None = None`、`crossover_best_gain: float | None = None`、`crossover_tokens: int = 0`。
- `node` 表与 `Node` 模型**不改**。

`common/metering.py`：
- 字段 `crossover_tokens: int = 0`（同 `jev_tokens` 定义处）。
- `add_llm_call` 新分支：`elif purpose == "crossover": self.crossover_tokens += prompt + completion`（仍累加总 prompt/completion，故 `total_tokens` 已含）。
- `to_dict()` 输出 `"crossover_tokens"`。

## 3. Store（`cloud/store.py`）

DDL 追加：

```sql
CREATE TABLE IF NOT EXISTS node_parents (
    experiment_id TEXT,
    node_id TEXT,
    parent_id TEXT,
    role TEXT,
    PRIMARY KEY (node_id, parent_id, role)
);
CREATE INDEX IF NOT EXISTS idx_node_parents_node ON node_parents(node_id);
```

方法：
- `add_node_parent(self, experiment_id: str, node_id: str, parent_id: str, role: str) -> None`（`INSERT OR IGNORE`）。role 取 `"primary"`（parent_a）与 `"secondary"`（parent_b）。
- `get_node_parents(self, node_id: str) -> list[tuple[str, str]]`：返回 `[(parent_id, role)]`，按 role 排序（primary 在前）。
- 交叉节点的 `Node.parent_id` 仍为 parent_a（树结构不变）。

## 4. 伙伴选择（新文件 `src/faultevolve/cloud/crossover.py`，任务无关）

```python
def branch_key(node: Node, nodes: dict[str, Node]) -> str: ...
def fn_group_keys(node: Node) -> set[str]: ...
def complementarity_overlap(a: Node, b: Node) -> float: ...
def select_crossover_partner(
    node: Node,
    nodes: dict[str, Node],
    *,
    top_quantile: float = 0.3,
) -> Node | None: ...
def valid_node_count(nodes: dict[str, Node]) -> int: ...
def estimate_runtime_s(*nodes: Node) -> float: ...
```

规则（全部确定性，无随机）：
- `valid_node_count`：`n.is_expandable()` 的节点数（含根）。
- `branch_key`：从 node 沿 `parent_id` 上溯（用 `nodes` 字典，防环最多循环 `len(nodes)` 次）；若 `depth==0` 返回 `"root"`；否则返回 depth==1 祖先的 id。找不到祖先则返回 node.id。
- `fn_group_keys`：读 `node.evidence.evaluation.metric.get("analysis") or {}` 的 `fn_groups`，元素非 dict 则忽略；键 `f"{dimension}={value}"`；缺 analysis 返回空集。
- `complementarity_overlap(a, b)`（越小越互补）：
  - 两者 `fn_group_keys` 都非空：Jaccard = `|A∩B| / |A∪B|`。
  - 否则降级：对两节点 `metric` 中共有的数值键（排除 `"analysis"`，排除 bool，排除 nan），`dist = mean(|x-y| / (max(|x|,|y|)+1e-9))`，`overlap = 1 - min(1.0, dist)`；无共有数值键则 `overlap = 1.0`。
- `select_crossover_partner(node, nodes, top_quantile)`：
  1. 候选池 = `is_expandable()` 且 `depth >= 1` 且 `operator != INIT` 的节点；有效节点总数用于分位数：把所有 `is_expandable()` 节点按 `(-score, id)` 排序，`k = max(1, ceil(top_quantile * n_valid))`，`eligible = 前 k 个`。
  2. 过滤：`id != node.id`，`branch_key(c) != branch_key(node)`，`c.id in eligible ids`。
  3. 排序键 `(overlap 升序, -score, id)`，返回首个；无候选返回 `None`。
  4. 若 parent 本身是根（branch_key 为 `"root"`），候选仍按 2 过滤（根已因 depth>=1 被排除，其他节点 branch_key 不同）。
- `estimate_runtime_s(*nodes)`：各节点 `evidence.evaluation.cost_time` 之和（缺失按 0）。

## 5. 算子与 prompt（`cloud/operators.py`）

- `OPERATOR_INSTRUCTIONS[OperatorType.CROSSOVER]`：要求把两份程序合成**一个自包含程序**（rank-average 或 stacking，优先共享特征计算），保持输出格式与约束，禁止读取标签文件外的数据；文本中含 `{runtime_budget_s}` 占位由代码格式化（用 `.format` 或 f-string，避免与其他 dict 值冲突）。
- `OperatorContext` 新增属性 `partner: Node | None = None`、`runtime_budget_s: float = 300.0`、`crossover_max_chars: int = 6000`；新增 setter `set_partner(node, runtime_budget_s: float = 300.0, max_chars: int = 6000) -> OperatorContext`。
- 新模板 `CROSSOVER_USER_TEMPLATE`（占位：objective_brief_section、score_a、metric_a、code_a、score_b、metric_b、code_b、complement_section、runtime_section、constraints_section、operator_instruction）。输出格式段与 `USER_MESSAGE_TEMPLATE` 相同（`<hypothesis>`、`<intent>`、python 代码块），**不含** adopted_cards。
- 新函数 `build_crossover_message(ctx: OperatorContext) -> str`：
  - `code_a/code_b = truncate_text(code, ctx.crossover_max_chars)`（每份独立截断；截断后 prompt 中加一行“代码已截断，请保留关键函数并补全为可运行程序”）。
  - `complement_section`：列出两个节点各自 `fn_groups` 前 3 个（`dimension=value, group_recall`），无 analysis 则写“无画像，按分项指标互补”。
  - `runtime_section`：`est = estimate_runtime_s(parent, partner)`；若 `est > ctx.runtime_budget_s`，写明“两者运行时间之和约 {est:.0f}s，超过 {budget:.0f}s，必须共享特征计算或只保留一个模型”；否则写“总运行时间必须小于 {budget:.0f}s”。
  - 不放 error_profile、knowledge、foreign insights。
- `build_user_message`：开头 `if ctx.operator == OperatorType.CROSSOVER and ctx.partner is not None: return build_crossover_message(ctx)`（其他算子路径字节不变）。
- 新类：

```python
class CrossoverOperator:
    def __init__(self, llm: DashScopeLLM | MockLLM) -> None: ...
    def generate(
        self,
        parent_a: Node,
        parent_b: Node,
        ctx: OperatorContext,
        max_retries: int = 1,
    ) -> GenerationResult: ...
```

  `generate`：`ctx.set_partner(parent_b, ctx.runtime_budget_s, ctx.crossover_max_chars)`（保留 ctx 已设的值），`ctx.operator = CROSSOVER`，然后 `return RefineOperator(self.llm).generate_with_adoption(ctx, max_retries)`。`parent_a` 用于校验 `ctx.node is parent_a`（否则 `ValueError`）。返回的 `adopted_cards` 忽略。

## 6. 引擎（`cloud/engine.py`）

1. import：`CrossoverOperator`、`select_crossover_partner`、`valid_node_count`、`branch_key`。`__init__`：`self.crossover_operator = CrossoverOperator(llm)`；`self._crossover_partners: dict[str, str] = {}`（child_id → partner_id，仅内存缓存）。
2. `_stage_used_tokens("crossover")` 返回 `self.metrics.crossover_tokens`。
3. `_available_operators`：循环结束后，若 `cfg.crossover.enabled` 且 `valid_node_count(self.tree.nodes) >= cfg.crossover.min_valid_nodes` 且未超阶段 cap（`self.budget.stage_exceeded("crossover", self.metrics.crossover_tokens)`）且 `select_crossover_partner(parent, self.tree.nodes, top_quantile=cfg.crossover.top_quantile) is not None`，则 `available.append(OperatorType.CROSSOVER)`。`cfg.crossover.enabled` 为 False 时不调用任何新逻辑。
4. `_run_one_iteration_inner`（在 `_choose_operator` 之后、构建 ctx 之前）：
   ```python
   partner = None
   if operator == OperatorType.CROSSOVER:
       partner = select_crossover_partner(parent, self.tree.nodes, top_quantile=...)
       if partner is None:
           operator = OperatorType.REFINE
           self._log_event("operator_fallback", {"parent_id": parent.id, "requested": "crossover", "used": "refine", "reason": "no_partner"})
   ```
   交叉时：`ctx.set_partner(partner, cfg.runtime_budget_s, cfg.max_code_chars)`；`knowledge_cards = []`，跳过 `_retrieve_knowledge_cards`；不调用 `get_foreign_insights`（用空列表）；`discover_flag` 保持仅 REFINE。
5. 生成调用：交叉用 `self.crossover_operator.generate(parent, partner, ctx)`，其余保持 `self.operator.generate_with_adoption(ctx)`。`add_llm_call(..., "crossover")`；`_op_tokens["crossover"]` 照旧累加；`create_llm_call_record(..., purpose "crossover" if crossover else "refine", ...)`。
6. 建节点后（`self.tree.add_node(child)` 之后，仅交叉）：
   ```python
   self.store.add_node_parent(self.experiment_id, child.id, parent.id, "primary")
   self.store.add_node_parent(self.experiment_id, child.id, partner.id, "secondary")
   self._crossover_partners[child.id] = partner.id
   self._log_event("crossover_parents", {"node_id": child.id, "parent_id": parent.id, "partner_id": partner.id, "est_runtime_s": estimate_runtime_s(parent, partner)})
   ```
   无效生成路径（`_handle_invalid_generation`）不写 node_parents，但 bandit 仍按无效记账（保持现有行为）。
7. `_apply_prescreen`：函数开头 `if child.operator == OperatorType.CROSSOVER: return PrescreenResult()`。
8. `_evaluate_child` 新增关键字参数 `baseline_score: float | None = None`；`delta = score - (baseline_score if baseline_score is not None else parent.get_score())`。交叉调用处传 `baseline_score=max(parent.get_score(), partner.get_score())`。其他调用（含 `_flush_deferred`）不传，行为不变。
9. `_apply_reflection`：开头 `if child.operator == OperatorType.CROSSOVER: self._log_event("crossover_reflection_skipped", {"node_id": child.id}); return`（确认签名后放在函数首行）。
10. `_harvest_discovery_candidates`：insight 与 top_node 两个循环中，`node.operator == OperatorType.CROSSOVER` 则 `continue`。
11. `_operator_summary` 之外新增 `_crossover_summary(self) -> dict[str, Any]`（并入 `RunSummary(**...)` 与 `run_finished` 事件）：
    - 遍历 `self.store.get_nodes_by_experiment` 中 `operator == CROSSOVER` 的节点；`crossover_count` = 这些节点数（含无效）；有效 = `is_expandable` 或 `evaluation.validity >= 1`（用 `evaluation and evaluation.validity >= 1.0`）。
    - `gain = score - max(score of parents from get_node_parents)`（无 node_parents 记录的节点跳过 gain）。
    - `crossover_valid_rate = valid/count`（count=0 → `None`）；`crossover_mean_delta = mean(gain of valid)`（无则 `None`）；`crossover_best_gain = max(gain of valid)`（无则 `None`）；`crossover_tokens = self.metrics.crossover_tokens`。
    - 关闭时返回 count=0 与 None，不做额外查询。
12. `run_summary` 的 `RunSummary(...)` 与 `run_finished` 事件均展开 `_crossover_summary()`。`operator_counts` 中会自动出现 `"crossover"` 键。

## 7. 报告与脚本

- `skill/fe-evolve-manager/scripts/report_run.py`：`generative_ops` 集合加入 `"crossover"`；输出增加 `crossover_count/crossover_valid_rate/crossover_mean_delta/crossover_best_gain/crossover_tokens`（缺失时 `None`/0，沿用现有取值方式）。
- `skill/fe-operators/scripts/check_operator_summary.py`：不强制 crossover 字段（保持 mock 脚本可过）；新增 `skill/fe-crossover-ensemble/scripts/check_crossover_summary.py`（见 §9）。

## 8. 测试（新文件 `tests/test_crossover.py`，全部离线）

辅助：`_node(id, parent_id, depth, score, operator=REFINE, fn_groups=None, metric=None, cost_time=1.0)` 构造 `Node`（`branch_id="main"`，`evaluation.validity=1.0`，`metric["analysis"]={"fn_groups": [...]}`），并用 `{id: node}` 字典。引擎测试沿用 `test_operators_bandit.py` 的 `_engine`、`FakeAdapter`、`MockLLM` 写法（`cfg.smoke_test.enabled=False`）。

必需用例（名称固定）：
1. `test_partner_selection_diff_branch_complementary`：树 root(0)→A1(d1,80)→A2(d2,90)；root→B1(d1,85, fn={x=1,y=2})；root→C1(d1,84, fn={x=1,z=3})；A2 的 fn={x=1,y=2}。`select_crossover_partner(A2, nodes, top_quantile=1.0)` 返回 C1（B1 重叠 Jaccard=1，C1 = 1/3）；断言返回节点 `branch_key != branch_key(A2)`；断言所有节点 `branch_id` 都是 `"main"` 时仍成立。
2. `test_partner_fallback_metric_difference`：无 analysis，metric 分别为 `{"a":0.8,"b":0.1}` 与 `{"a":0.8,"b":0.1}`（overlap=1）和 `{"a":0.2,"b":0.9}`（overlap 小），选后者。
3. `test_partner_top_quantile_excludes_low_scores`：6 个有效节点，`top_quantile=0.3` → `k=2`；分数低于前 2 的互补节点不被选；全部同分支时返回 `None`。
4. `test_crossover_disabled_small_tree`（引擎）：`crossover.enabled=True, bandit=True, min_valid_nodes=4`，树只有 3 个有效节点 → `_available_operators(parent)` 不含 `CROSSOVER`；补到 4 个且有合格伙伴后含 `CROSSOVER`。另断言默认配置（`enabled=False`）下永不含。
5. `test_node_parents_recorded_no_schema_change`：跑一次强制交叉（monkeypatch `_choose_operator` 返回 CROSSOVER，预置树含另一分支高分节点）；断言 `store.get_node_parents(child.id)` 为 `[(parent_a,"primary"),(parent_b,"secondary")]`；`child.parent_id == parent_a`；`PRAGMA table_info(node)` 的列名集合与 DDL 中 node 表原有列完全一致（不含 parent2 类新列）；事件 `crossover_parents` 存在；旧库（只建原 DDL 的 sqlite 文件）打开 Store 后 `node_parents` 表被创建。
6. `test_crossover_in_bandit`：`select_operator(None, [REFINE, CROSSOVER], stats={CROSSOVER:(50.0,1.0)}, rng=random.Random(0), min_explore=0.0, bandit=True)` 返回 CROSSOVER；引擎跑完后 `operator_stats` 出现 `"crossover"` 行，`run_summary.operator_counts["crossover"] >= 1`，`CROSSOVER in GENERATIVE_OPERATORS`。
7. `test_prompt_truncation`：两份各 20000 字符代码，`crossover_max_chars=1000`；`build_user_message` 结果长度 < 2×1000 + 4000，且含 `[truncated]` 两次；未截断的短代码不含该标记。
8. 补充用例：
   - `test_crossover_runtime_guard_prompt`：`cost_time` 之和 200/200、预算 300 → prompt 含“共享特征计算”；100/100 → 不含该句。
   - `test_crossover_baseline_is_max_parent`：伙伴 90、parent_a 80、子 85 → 节点 `delta_score == -5`，bandit 记失败。
   - `test_crossover_skips_jev_prescreen`：启用 judge 的 mock，交叉节点不触发 `prescreen`（mock 未被调用）。
   - `test_crossover_tokens_own_stage`：`run_summary.crossover_tokens > 0` 且 `generate_tokens` 不含该部分；`total_tokens` 含之。
   - `test_crossover_summary_fields`：`crossover_count/valid_rate/mean_delta/best_gain` 数值与手工计算一致；关闭时为 0/None。
   - `test_crossover_excluded_from_discovery_harvest`：交叉节点不出现在 `_harvest_discovery_candidates` 输出。
   - `test_crossover_requires_bandit`：`OperatorsConfig(crossover={"enabled": True})` 抛 `ValidationError`；`enabled=True, bandit=True` 通过；默认值与 §1 一致；`EvolveConfig.from_dict({"operators": {"bandit": True, "crossover": {"enabled": True}}})` 与 `with_overrides` 往返不丢字段。
   - `test_default_behavior_unchanged_pr8`：默认配置两次运行 `total_tokens` 相同、无 `crossover_*` 事件、所有节点算子为 REFINE；`operator_counts` 无 `"crossover"` 键。
   - `test_cloud_modules_agnostic_pr8`：正则 `HDD|SMART|Backblaze|hard\s*disk|disk failure` 扫描 `cloud/crossover.py`、`cloud/operators.py`、`cloud/engine.py`、`common/metering.py`。
- 更新已有测试：`tests/test_config.py`/`test_operators_bandit.py` 若断言 `GENERATIVE_OPERATORS` 长度或 `RunSummary` 字段全集，改为包含新项；跑 `python -m pytest tests/ -q` 必须全绿（当前基线 417+）。

## 9. 技能

- 新增 `skill/fe-crossover-ensemble/SKILL.md`（中文，含 frontmatter `name: fe-crossover-ensemble`, `description`）：
  - 何时使用：树中已有 ≥4 个有效节点、存在不同分支的高分节点、AUPRC/召回类指标停滞；不适用于运行时间已接近上限、bandit 关闭、有效节点不足。
  - 输入：`operators.bandit: true` 与 `operators.crossover.{enabled,min_valid_nodes,runtime_budget_s,top_quantile,max_code_chars}` 表；依赖 `analysis.enabled`（缺失时降级为指标差异）。
  - 命令：`bash skill/fe-crossover-ensemble/scripts/run_mock_crossover.sh`；`python skill/fe-crossover-ensemble/scripts/check_crossover_summary.py <artifacts_dir>`；`python skill/fe-evolve-manager/scripts/report_run.py <fe.db> <run_summary.json>`；`python -m pytest tests/test_crossover.py -q`。
  - 成功检查：`operator_counts["crossover"] ≥ 1`；`crossover_tokens > 0`；`crossover_valid_rate` 在 [0,1]；`node_parents` 每个交叉节点有 primary+secondary 两行；`timeout` 类 perf_rejected 不上升。
  - 失败处理：无效率高/超时 → 调小 `runtime_budget_s` 或关闭；从未被选中 → 检查 bandit、有效节点数、是否存在不同 depth-1 子树；prompt 过长 → 调小 `max_code_chars`；修复交叉节点时只带 parent_a 代码（已知限制）。
  - 禁止事项：不读 eval_only/test/holdout；不以 LLM 输出代替本地分数；不改 node 表。
  - 记录 §0 中的设计选择：交叉节点跳过 Jev 预筛与反思、基线为两父最大值、branch 定义为 depth-1 祖先。
- `scripts/run_mock_crossover.sh`：仿 `run_mock_operators.sh`（toy 任务，`operators.bandit: true`、`crossover.enabled: true`、`min_valid_nodes: 3`、`min_explore: 0.4`，iterations 15，`FakeAdapter`/`--mock`），末尾调用 check 脚本。
- `scripts/check_crossover_summary.py`：读 `run_summary.json`，必须含 `crossover_count/crossover_valid_rate/crossover_mean_delta/crossover_best_gain/crossover_tokens`；`crossover_count > 0`；`crossover_tokens > 0`；`crossover_valid_rate` 在 [0,1]；失败 `SystemExit`；成功打印 JSON。
- 更新 `skill/fe-operators/SKILL.md`：新增“交叉算子”章节（启用条件、运行时间护栏、故障处理，指向新技能）；把 `generative_valid` 定义扩为含 crossover；把“operator_tokens 之和 ≤ generate_tokens”改为“≤ generate_tokens + crossover_tokens”。同步修改 `check_operator_summary.py` 无需改（未检查该不等式）。
- 更新 `skill/fe-evolve-manager/SKILL.md`：命令区加入 mock crossover 命令；“算子无效率”处加交叉排障要点；`generative_valid` 说明加 crossover；新增小节“交叉/集成算子（PR #8）”（配置、新指标、事件 `crossover_parents`/`crossover_reflection_skipped`/`operator_fallback(reason=no_partner)`、常见故障）。
- `README`/`docs`：`docs/TODO.md` 中把步骤 5b（KD2）行状态改为已合并（a37f88f）、PR #8 行改为“🔄 PR 中”并填分支；勾选步骤 6 已完成项；在设计文档中如有算子表则补 crossover 一行（简体中文）。

## 10. 事件与 run_summary 新字段汇总

- 事件：`crossover_parents{node_id,parent_id,partner_id,est_runtime_s}`、`crossover_reflection_skipped{node_id}`、`operator_fallback{requested:"crossover",used:"refine",reason:"no_partner"}`、既有 `operator_selected.available` 会含 `"crossover"`。
- run_summary：`crossover_count, crossover_valid_rate, crossover_mean_delta, crossover_best_gain, crossover_tokens`；`operator_counts/valid_rate/mean_delta/posteriors/tokens` 自动含 `crossover`。
- `stage_cap_hits` 支持 `crossover` 阶段（仅配置 cap 时出现）。

## 11. 实施顺序

1. schemas/config/metering/budget → 2. store 表与方法 → 3. `cloud/crossover.py` → 4. operators（模板、setter、`CrossoverOperator`） → 5. engine（可用性、分支、生成、记录、预筛跳过、baseline、反思跳过、harvest 过滤、summary） → 6. 测试 → 7. 技能与脚本 → 8. TODO 行 → 9. 全量 `python -m pytest tests/ -q` 与 `bash skill/fe-crossover-ensemble/scripts/run_mock_crossover.sh` → 10. 提交并推送，创建 PR。

## 12. 延后实跑时需要汇报的内容（现在不跑）

一次真实运行，`operators.bandit: true` + `crossover.enabled: true`（+ `analysis.enabled: true`）：
- §4.3 合并规则指标：best/ROS 提升、valid_rate、`perf_rejections`/超时次数（须 ≤ 1）、总 token 与 `tokens_per_ros_point`。
- crossover 指标：`crossover_count / crossover_valid_rate / crossover_mean_delta / crossover_best_gain / crossover_tokens`，及 `operator_counts/valid_rate/posteriors`。
- 最佳节点是否为交叉节点；其 `node_parents` 与两父分数；AUPRC、R@FAR 相对两父的变化；运行时间（`cost_time`）相对 `runtime_budget_s`。
- 与关闭交叉的同预算对照（若有）。

## 13. 验收清单

- 默认配置下：`python -m pytest tests/` 全绿，`init.py` 评估 val ROS ≈ 22.81 不受影响，无新增事件、无额外 token。
- `benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md,data/}` 未改动；无密钥写入；`cloud/`、`common/` 无 HDD 词。
