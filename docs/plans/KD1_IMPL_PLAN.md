# KD1 实现计划（现象层知识发现 + 发现卡回灌）

基线：origin/main = fb18475。分支 `feat/knowledge-discovery-kd1`。只做后端。全部新配置默认关闭，默认行为不变，额外成本为 0。
本计划已对照代码核实。以下 `路径:行` 均指 fb18475。

## 0. 硬约束（实现时逐条自检）
- 不改 `TaskAdapter` Protocol，只新增可选 Protocol `DiscoveryDataProvider`。不改 `benchmark/hdd_mvp/{evaluator,init,problem,prompt}` 和 `data/`。
- 不读 `data/eval_only`、test 或 holdout。发现只读 `data/public/train_*`。
- `src/faultevolve/discovery/` 内不得出现 HDD 词（smart、serial、hdd、vendor）。测试 `test_discovery_task_agnostic` 用 `rg -i` 扫描该目录源码，断言无匹配。HDD 专属逻辑只放 `tasks/hdd_adapter.py`。
- 发现产生的 LLM token 一律走 `metrics.add_llm_call(m, "discover")`，并写 `llm_call` 表（purpose=`discover`）。
- 分数只来自本地 evaluator。LLM 输出只生成 claim 文本和蕴含判断，绝不作为统计量或节点分数。
- 发现卡只写 `<runs_dir>/knowledge/discovered_cards.jsonl`，绝不写仓库 `cards.jsonl`。
- 全部 fail-open：发现流程任何异常 → 记 `discovery_error` 事件 → 继续进化。
- KD2（机理层、锦标赛、否证证书、报告）只留钩子：`grading.py` 顶部 `# KD2 hook:`、`pipeline.py` 的 `RoundResult.extras: dict`、CLI 无 KD2 命令。不实现。
- 反思路由已在 PR #3.1 修复：`_apply_reflection` 里正向走 `_reflect_positive`（`engine.py:2124`）。本 PR 不再动。

## 1. 现有代码事实与陷阱（必读）
1. `EvolutionEngine.run()`（`engine.py:353`）循环为 `_run_one_iteration()` → `update_experiment`。`_run_one_iteration`（`:1101`）用 token 差值喂 `budget.record_iteration`。**发现必须在 `_run_one_iteration` 之外调用**，否则发现 token 会污染 `expected_iteration_tokens` 和 `should_expand`。
2. `iterations_done` 只在 `_evaluate_child(count_iteration=True)` 和 Jev 屏蔽分支递增。`llm_error` 分支 `return True` 但不递增。因此用 `_last_discovery_iter` 去重，触发条件为 `iterations_done>0 and iterations_done%N==0 and iterations_done!=_last_discovery_iter`。恢复运行时初始化 `_last_discovery_iter = metrics.iterations_done`。
3. `MockLLM.chat_for_reasoning` 按顺序消费脚本化 `set_reasoning_responses`，默认返回反思 JSON。发现也走 `chat_for_reasoning`，会抢占反思的脚本响应。因此 system prompt 首行放标记 `KD_TRANSLATE` / `KD_ENTAIL`。测试用 `ScriptedDiscoveryLLM(MockLLM)` 按标记分发。
4. `_evaluate_child`（`:1517`）被 `_run_one_iteration_inner` 和 `_flush_deferred` 两处调用。card_stats 更新只在其中做，已按 `child.card_ids` 循环，发现卡 id 自动生效。**不要在 `_evaluate_child` 里计数 offered/adopted**（flush 会重复）。offered 在选卡后统计，adopted 在 `child.card_ids = adopted_cards` 处统计（`:281` 附近，`cards_adopted_count += ...` 旁边）。
5. Jev 屏蔽的 child 状态为 ABANDONED，无有效 evaluation。收割时要求 `evidence.evaluation.validity>=1`，自然排除。deferred 节点在 `run()` 结束时 `_flush_deferred` 才被评估，因此最终轮必须放在 `_flush_deferred` **之后**。Jev/LLM 值永不进入 claim 检验。
6. PR #6 analysis 的 `metric["analysis"]` 体积大，不放入 claim prompt。PR #6 的适配器缓存靠 `cleanup_analysis_data`（`run()` 的 finally 里），发现同理新增可选 `cleanup_discovery_data`，在同一 finally 里 `hasattr` 调用。
7. PR #5：`budget.check_stop`/`tokens_per_point_cap` 用 `metrics.total_tokens`，发现 token 会计入，这是预期。`_BUDGET_STAGE_KEYS`（`config.py:14`）不加 `discover`，发现用自己的 `max_token_share`。`tokens_per_ros_point` 同样含发现 token。
8. PR #7：INJECT 只取 `knowledge_cards[:1]`（`engine.py:61-77`），可能是发现卡，行为正常。`_available_operators` 的 INJECT 只检查 knowledge_dir 存在，不涉及卡加载，无需改。`operator` 枚举不加 DISCOVER，discover_op 产生的节点仍记 REFINE。
9. `EvolveConfig.from_dict`（`config.py:200+`）逐段手工赋值，`with_overrides` 经 `model_dump→from_dict` 往返。**必须在 `from_dict` 里加 `if "discovery" in data`**，否则 `run_local_evolution` 会丢配置。
10. 分数不含 discovery：`_write_artifacts` 在 finally 内且 summary 可能为 None（崩溃）。发现产物写入必须 try/except，且对 None 安全。
11. `Store.DDL` 用 `CREATE TABLE IF NOT EXISTS`，新表直接追加，旧库自动兼容。`Node` 表不动，`EvaluationResult` 是 `extra=forbid`，不要往里塞字段。
12. 有效性：LLM 出的特征代码不可信，必须走沙箱子进程。子进程输出用 CSV 回读，**不要 unpickle 子进程产物**。
13. **e-BH 功效陷阱**：每轮 m≤3 个 claim，e-BH 要求 `e_(1) >= m/α = 60`（α=0.05, m=3），即 `p <= (κ/60)^2 ≈ 6.9e-5`。但 B=500 的经验置换 p 最小只有 1/501≈0.002，e 最大≈11，永远过不了。因此 `permutation_p` 在极端计数 <5 时改用"置换分布拟合正态"的尾部 p（见 §3 stats）。必须有测试覆盖强信号 e-BH 通过。

## 2. 配置（`config.py`）
新增 `class DiscoveryConfig(BaseModel)`，字段和默认值与 `docs/TODO.md` 5a 的 yaml 完全一致：
`enabled=False, every_n_iterations=5(ge=1), run_at_end=True, max_claims_per_round=3(ge=1), min_insight_z=2.0, top_k_programs=3(ge=0), discover_op_every=0(ge=0), alpha=0.05(gt0,lt1), bootstrap_b=500(ge=50), e_calibrator_kappa=0.5(gt0,lt1), rho_max=0.8, planted_strengths=[0.2,0.5,1.0], neg_control_repeats=5(ge=1), max_neg_control_fpr=0.10, confirmation_fraction=0.3(gt0,lt1), split_salt="fe-kd-2026", sandbox_timeout_s=120(gt0), max_token_share=0.2(gt0,le1), inject_same_run=True, cards_path: str|None=None, extra_card_paths: list[str]=[], use_jev_entailment=False`。
- 接入 `EvolveConfig.discovery` 和 `from_dict`。
- `use_jev_entailment` 在 KD1 只是钩子：为 true 时发一次 `discovery_jev_entailment_unavailable` 事件，仍用推理 LLM 判定，不调用 Jev。
- `benchmark/hdd_mvp/evolve.yaml` 追加注释掉的 `discovery:` 段（该文件不在保护列表）。默认值不变。

## 3. 新包 `src/faultevolve/discovery/`（每个文件的精确接口）
- `__init__.py`：空 docstring。
- `schemas.py`（pydantic v2）：
  - `class Grade(str, Enum)`：`CONFIRMED="confirmed", REVISED="revised", DISCOVERED="discovered", REFUTED="refuted", UNDETERMINED="undetermined"`。
  - `Claim`：`id, experiment_id, origin_node_id, source: Literal["insight","top_node","discover_op"], title, condition, feature_code, outcome, direction: Literal["+","-"], scope, falsifier, category="feature_engineering", tags: list[str]=[], prereg_hash="", status="proposed", grade: Grade|None=None, confirms: str|None=None, revises: str|None=None`。
  - `ClaimTestResult`：`split, n, n_pos, n_neg, effect, ci_low, ci_high, p, e, direction_ok: bool, temporal_ok: bool|None, rho_max_abs: float|None, incr_gain: float|None, incr_ci_low: float|None`。
  - `ControlReport`：`neg_trials, neg_false_positives, neg_fpr, planted: dict[str, dict[str,float]]`（键 `str(strength)`，值 `{trials, recovered, rate}`），`passed: bool`。
  - `DiscoveryStats`（dataclass，引擎持有）：`rounds, rounds_skipped, claims_proposed, claims_tested, claims_sandbox_failed, confirmed, revised, discovered, refuted, undetermined, cards_promoted, neg_control_false_positives, neg_control_trials, planted_trials: dict[str,int], planted_recovered: dict[str,int], best_at_first_promotion: float|None`。
- `claims.py`：
  - `TRANSLATE_MARKER = "KD_TRANSLATE"`。
  - `translate_claim(parent_code: str, child_code: str, insight: dict, frames_note: str, llm_call: Callable[[list[dict[str,str]]], str]) -> Claim | None`。用 `difflib.unified_diff` 截断到 4000 字符，要求模型输出 JSON `{title,condition,feature_code,outcome,direction,scope,falsifier,category,tags}`。校验：`feature_code` 含 `def feature(`；`direction∈{"+","-"}`；`category` 不在 `VALID_CATEGORIES` 则回落 `feature_engineering`；解析失败返回 None。返回的 Claim 未填 id/experiment_id（由 pipeline 填）。
  - `extract_claim_from_response(text: str) -> dict | None`：取第一个 `<claim>…</claim>`，`json.loads`，缺任一必填键或 direction 非法返回 None，绝不抛异常。
  - `preregister(claim: Claim, cfg: DiscoveryConfig) -> str`：对 `{condition,feature_code,outcome,direction,scope,falsifier,split_salt,confirmation_fraction,alpha}` 做 `json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False)`，返回 sha256 hex。
- `sandbox.py`：
  - `@dataclass SandboxResult: ok: bool; series: pd.Series|None; error: str; duration_s: float`。
  - `run_feature(code: str, history: pd.DataFrame, unit_col: str, expected_units: Sequence, timeout_s: int) -> SandboxResult`。
  - 静态预检：复用 `codecheck.syntax_check` 和 `pattern_check`，再加 AST 检查。import 根白名单 `{numpy,pandas,math,scipy,statistics,itertools,functools,collections}`；禁用名 `open exec eval compile __import__ input globals locals getattr setattr delattr vars breakpoint`；禁止 dunder 属性访问；禁止属性名 `read_csv to_csv read_parquet to_parquet read_pickle to_pickle read_sql read_json to_json`。
  - 执行：`subprocess.run([sys.executable,"-I","-c",_RUNNER])`，`cwd=tempfile.mkdtemp()`，最小 env（`PATH, PYTHONHASHSEED=0, OMP_NUM_THREADS=1`），`timeout=timeout_s`，POSIX 下 `preexec_fn` 设 `RLIMIT_AS=4GiB`。输入 `history.pkl` 由父进程写（可信），子进程 exec 代码并调用 `feature(history)`，把结果写成 `out.csv`（index,value）。
  - 返回值校验：必须是 Series；`inf→NaN`；reindex 到 `expected_units`；非 NaN 覆盖率 <0.8 → `error="low_coverage"`；方差为 0 → `error="constant"`；其余 NaN 用中位数填充。超时 `error="timeout"`。
  - 任何失败都返回 `ok=False`，不抛异常。
- `splits.py`（只用传入的 DataFrame，不做任何文件 IO）：
  - `assign_split(unit_id: str, salt: str, confirmation_fraction: float) -> Literal["explore","confirm"]`：sha256(f"{salt}|{unit_id}") 前 8 字节 /2^64 < fraction → confirm。
  - `split_masks(labels, unit_col, salt, fraction) -> tuple[np.ndarray, np.ndarray]`（explore, confirm 布尔掩码）。
  - `temporal_halves(times: pd.Series) -> tuple[np.ndarray, np.ndarray]`：按唯一时间值排序，在中位数处分前后两段。
- `stats.py`（全部接收 `rng: np.random.Generator`，禁止用全局随机）：
  - `auroc(x,y)`：`scipy.stats.rankdata`，ties 取平均。`signed_effect(x,y) = auroc-0.5`。
  - `group_bootstrap_ci(x,y,groups,b,alpha,rng) -> (lo,hi)`：按 group 有放回重采样，百分位 CI；缺少某一类的重采样跳过。KD1 要求 labels 每个 unit 一行，因此 group=unit。
  - `permutation_p(x,y,b,rng) -> float`：双侧。计数 ≥5 时用 `(1+count)/(1+b)`；否则用置换统计量的 sd 做正态尾部 `2*(1-Φ(|T|/sd))`，下限 1e-300。
  - `e_from_p(p,kappa=0.5) = kappa*max(p,1e-300)**(kappa-1)`。
  - `bh_reject(pvals,q) -> list[bool]`，`ebh_reject(evals,alpha) -> list[bool]`（取最大 k 使第 k 大的 e ≥ m/(k·α)，拒绝前 k 个）。
  - `rate_ratio_top_quantile(x,y,q=0.9) -> float`（次要，仅上报）。
  - `max_abs_spearman(feature, baseline_df) -> float`。
  - `incremental_auroc(feature, baseline_df, y, groups, b, alpha, rng) -> (gain, lo, hi)`：3 折分层 CV 的 `LogisticRegression(max_iter=200)` 折外预测，标准化后比较"基线"与"基线+特征"的 AUROC，对折外预测按 unit 做 bootstrap 求增量 CI。
  - `test_feature(x,y,groups,direction,cfg,rng) -> ClaimTestResult`：`direction_ok = sign(effect)==(+1 if "+" else -1)`。
- `baseline_features.py`：`build_baseline_features(history, unit_col, time_col, cols, lag_rows=14) -> pd.DataFrame`（index=unit）。每个 col 生成 `{c}__last`、`{c}__diff{lag_rows}`（最后一行减 lag_rows 行之前，不足则 0）、`{c}__nz`（非零非 NaN 计数），NaN 补 0。列名清单由 adapter 通过 `DiscoveryFrames.baseline_cols` 提供。
- `controls.py`：
  - `is_stat_positive(res: ClaimTestResult, alpha) -> bool`：CI 不跨 0 且 `direction_ok` 且 `p<=alpha`。
  - `run_negative_controls(features: dict[str,np.ndarray], y, groups, strata: np.ndarray, direction_by_id, cfg, seed) -> tuple[int,int]`：每个 claim 特征做 `neg_control_repeats` 次分层打乱标签（在 strata 内置换），返回 (false_positives, trials)。
  - `run_planted_controls(y, groups, cfg, seed, strengths=None, repeats=None) -> dict[str, dict[str,float]]`：合成特征 `x = N(0,1) + d·y`，其余同上，`recovered` 用 `is_stat_positive`。
  - `run_controls(...) -> ControlReport`：`neg_fpr = fp/max(trials,1)`，`passed = neg_fpr <= cfg.max_neg_control_fpr`。
  - 随机种子：`int(sha256(f"{split_salt}|{claim_id}|{round}").hexdigest()[:8],16)`。
- `novelty.py`：
  - `ENTAIL_MARKER = "KD_ENTAIL"`。
  - `functional_novel(rho_max_abs, incr_ci_low, cfg) -> bool`：`rho_max_abs<cfg.rho_max and incr_ci_low>0`。
  - `@dataclass Entailment: relation: Literal["same","opposite","different_magnitude","none","unknown"]; card_id: str|None`。
  - `judge_entailment(claim: Claim, cards: list[KnowledgeCard], llm_call) -> Entailment`：先盲判，只给卡的 `id/title/claim`，不给 claim 的检验结果。要求 JSON `{card_id|null,relation}`。JSON 非法或 card_id 不在卡库 → `unknown`（走 UNDETERMINED，不晋升，避免误报"发现"）。
- `grading.py`（表驱动，顶部 `# KD2 hook: 机理层裁决在此之后接入`）：
  - `@dataclass GradeInputs: ci_low, ci_high, direction_ok, temporal_ok: bool|None, bh_pass, ebh_pass, functional_novel, entailment: Entailment, controls_ok`。
  - `grade_claim(inp) -> tuple[Grade, str|None, str|None]`，返回 (grade, confirms, revises)。顺序：
    1. CI 跨 0 或 `direction_ok` 为假或 `temporal_ok is False` → REFUTED。
    2. `temporal_ok is None` 或 `not (bh_pass and ebh_pass)` 或 `relation=="unknown"` → UNDETERMINED。
    3. `relation=="same"` → CONFIRMED（confirms=card_id）。
    4. `relation in {"opposite","different_magnitude"}` → REVISED（revises=card_id）。
    5. `relation=="none"`：`functional_novel and controls_ok` → DISCOVERED，否则 UNDETERMINED。
- `promotion.py`：
  - `promote_claims(items: list[tuple[Claim,dict]], controls: ControlReport, cards_path: Path, experiment_id: str, run_best_score: float) -> list[dict]`。
  - `controls.passed` 为 False → 返回 []（整轮不晋升）。只晋升 DISCOVERED/REVISED。
  - 卡字段：`id=f"D-{exp}-{seq:03d}"`（seq=文件内该 exp 前缀已有卡数+1，冲突则递增）。`title, claim=claim.outcome, category, rationale`（含效应、CI、q、e、n 的文本），`applicability=scope`，`expected_effect`（带 CI），`risk` 含"数据驱动发现，未经文献验证；仅在训练集确认切片上检验"，`source_ids=[f"run:{exp}",f"node:{origin}",f"claim:{claim.id}"]`，`tags`=claim.tags ∪ 特征代码中命中数据列名的标识符，`impl_hint=feature_code[:600]`，`priority=2 if DISCOVERED else 3`，`evidence="run"`。附加血统字段 `grade, prereg_hash, confirms, revises, created_at`（loader 会忽略这些字段）。
  - 写入前用 `validate_card`。校验失败则跳过并发 `card_rejected` 事件。按 `prereg_hash` 去重。
  - 拒绝 `cards_path.name=="cards.jsonl"`（`ValueError`）。追加写，每卡一行 flush。
- `pipeline.py`：
  - `class DiscoveryRound`，构造 `(cfg, store, adapter, task_spec, experiment_id, card_path, knowledge_dir, llm_call, log_event, stats)`。
  - `run(round_idx, final, candidates: list[Candidate]) -> RoundResult`；`Candidate = (origin_node, parent_code, child_code, insight_dict|None, source, raw_claim|None)`。
  - `RoundResult`：`promoted_ids, graded: list[dict], controls: ControlReport|None, skipped_reason: str, extras: dict`（KD2 钩子）。
  - 流程：
    1. `isinstance(adapter, DiscoveryDataProvider)` 否则 `skipped_reason="no_provider"`（发 `discovery_skipped`，计 `rounds_skipped`）。
    2. `frames=adapter.discovery_frames(task_spec)`，缓存在 round 对象上。
    3. 逐候选：`raw_claim` 有则直接用，否则 `translate_claim`。生成 id、算 `prereg_hash`，`store.create_claim`，发 `claim_proposed`。`claims_proposed+=1`。
    4. 沙箱：对 explore+confirm 全部 unit 一次算出特征。失败 `claims_sandbox_failed+=1`，status=`sandbox_failed`，不计 tested。
    5. 检验：confirm 切片做 `test_feature`（含 `temporal_ok`：按 `temporal_halves` 分前后段各算 `signed_effect`，方向都一致才为 True）。explore 切片算 `rho_max_abs` 和 `incr_*`。`store.create_claim_test`，`claims_tested+=1`。
    6. 本轮内 FDR：对 tested 的 p 与 e 分别做 BH 与 e-BH（m=本轮 tested 数）。
    7. 对照：`run_controls`。写 `discovery_controls` 事件；`not passed` 时发 `discovery_controls_failed`。
    8. 蕴含：`load_all_cards` 取文献卡（不含 `D-`）→ `judge_entailment`。
    9. 分级 → `store.update_claim` → 发 `claim_graded`，更新 stats。
    10. 晋升 → `store.record_discovered_card` → 发 `card_promoted`。
    - 整个 `run` 用 try/except 包裹：异常发 `discovery_error` 并返回 `skipped_reason="error"`。
  - `phenomena`、`preregistrations`、`controls` 三个列表累积在对象上，供 `write_artifacts(dir)` 落盘。

## 4. 修改现有文件
- `tasks/protocol.py`：新增 `@dataclass DiscoveryFrames`（字段 `labels: Any, history: Any, unit_col: str, time_col: str, label_col: str="label", baseline_cols: list[str]=[], baseline_lag_rows: int=14, schema_note: str=""`，labels 每 unit 一行，history 每 unit 只含 ≤ 该 unit 时间点的行）。新增 `@runtime_checkable class DiscoveryDataProvider(Protocol): def discovery_frames(self, task_spec: TaskSpec) -> DiscoveryFrames`。`tasks/__init__.py` 导出它们。
- `tasks/hdd_adapter.py`：`HDDAdapter.discovery_frames`。用 `_get_data_dir` 读 `train_labels.csv`（按 serial 去重，unit_col=`serial_number`，time_col=`date`，label_col=`label`）；分块流式读 `train_history.csv.gz`，只保留 labels 里的 serial 且 `date<=cutoff` 的行，只保留数值列以控制内存。常量 `HDD_K0_COLUMNS`（`smart_5/9/12/187/188/194/197/198/199_raw` 中实际存在的列；实现时先读表头核对）。`schema_note` 写列说明。结果缓存于 `self._discovery_cache`，新增 `cleanup_discovery_data()` 释放缓存。
- `worker/runner.py`：`FakeAdapter.discovery_frames`。合成数据用 `np.random.default_rng(20260926)`：600 个 unit、正例率 0.3、列 `unit,t,m0..m3`、每 unit 20 行。类属性 `discovery_planted_strength=1.0`：正例的 `m1` 整体加该值（Cohen d），其余列为噪声。`baseline_cols=["m0","m2","m3"]`。`FakeAdapter` 的其他行为不变。
- `knowledge/loader.py`：新增 `load_all_cards(knowledge_dir: Path | None, extra_paths: Sequence[Path] = ()) -> tuple[list[KnowledgeCard], list[str]]`。
  - 顺序：`knowledge_dir/cards.jsonl` → 各 extra path（按传入顺序）。
  - extra 文件不存在则静默跳过；id 与已加载的冲突则拒绝后者并追加 error 字符串 `Duplicate card id '<id>' rejected from <path>`。
  - 每个文件走 `load_cards`（保留校验）。
  - `load_cards_from_dir` 原样保留。`knowledge/__init__.py` 导出 `load_all_cards`。
- `cloud/selection.py:get_era_knowledge_cards`（`:550`）：`load_cards_from_dir(knowledge_dir)` 改为 `load_all_cards(knowledge_dir, [Path(p) for p in context.get("extra_card_paths") or []])`。`retriever.retrieve_knowledge_cards` 不动。每次检索都重读文件，因此同一 run 内晋升后下一轮即可检索到，无需缓存失效。
- `common/metering.py`：`RunMetrics` 新增 `discovery_prompt_tokens, discovery_completion_tokens, discovery_tokens, discovery_latency_ms, discovered_cards_offered, discovered_cards_adopted`。`add_llm_call` 新增 `purpose=="discover"` 分支（累加上述 discovery_* 字段；`total_*` 已在函数开头累加）。新增 property `discovery_token_share`（`total_tokens==0` 时为 0）和 `discovered_card_adoption_rate`（offered==0 时为 0）。`to_dict` 追加这些键。
- `common/schemas.py:RunSummary`：追加字段并全部带默认值：`discovery_tokens:int=0, discovery_token_share:float=0.0, discovery_rounds:int=0, discovery_rounds_skipped:int=0, claims_proposed/claims_tested/claims_sandbox_failed:int=0, claims_confirmed/claims_revised/claims_discovered/claims_refuted/claims_undetermined:int=0, discovered_cards_count/discovered_cards_offered/discovered_cards_adopted:int=0, discovered_card_adoption_rate:float=0.0, discovered_card_mean_delta:float|None=None, literature_card_mean_delta:float|None=None, score_delta_after_discovery:float|None=None, neg_control_false_positives:int=0, neg_control_fpr:float|None=None, planted_recovery_rate:dict[str,float]={}`。
- `cloud/store.py`：`DDL` 追加三张表（`CREATE TABLE IF NOT EXISTS`）：
  - `claim(id PK, experiment_id, origin_node_id, source, round INTEGER, payload_json, prereg_hash, status, grade, created_at)`
  - `claim_test(id INTEGER PK AUTOINCREMENT, claim_id, experiment_id, split, payload_json, created_at)`
  - `discovered_card(card_id PK, claim_id, experiment_id, grade, created_at)`
  - 方法：`create_claim(experiment_id: str, claim: dict, round_idx: int)`、`update_claim(claim_id: str, **fields)`（只允许 `status, grade, payload_json`）、`get_claims(experiment_id) -> list[dict]`、`create_claim_test(claim_id, experiment_id, split, payload: dict)`、`get_claim_tests(claim_id) -> list[dict]`、`record_discovered_card(card_id, claim_id, experiment_id, grade)`、`get_discovered_cards(experiment_id) -> list[dict]`。不改现有表和方法。
- `cloud/tree.py:to_export`：节点字典追加 `"adopted_cards": list(node.card_ids)`（纯新增键）。
- `cloud/operators.py`：
  - `OperatorContext` 新增属性 `discover_claim: bool = False` 与 `set_discover_claim(flag)`。
  - `DISCOVER_CLAIM_SUFFIX` 常量：要求在 `<intent>` 之后、代码块之前额外输出 `<claim>{JSON}</claim>`，JSON 键同 `translate_claim`。
  - `build_user_message`：仅当 `ctx.discover_claim` 为真时把后缀拼到 `operator_instruction` 后。flag 为假时 prompt 必须逐字节不变（测试断言）。
  - `GenerationResult` 新增 `claim: dict | None = None`（带默认值，不破坏现有构造）。`generate_with_adoption` 仅在 `ctx.discover_claim` 时调用 `extract_claim_from_response`。
- `cloud/engine.py`：
  - `__init__` 新增：`self._discovery: DiscoveryRound | None = None`、`self._dstats = DiscoveryStats()`、`self._pending_claims: list[tuple[str,dict]] = []`、`self._last_discovery_iter = 0`、`self.artifacts_dir: Path | None = None`（不改构造函数签名）。
  - `_discovery_card_path() -> Path`：`cfg.cards_path` 或 `self.store.db_path.parent.parent / "knowledge" / "discovered_cards.jsonl"`。
  - `_extra_card_paths() -> list[str]`：`[str(_discovery_card_path())]`（仅当 `cfg.enabled and cfg.inject_same_run`）加上 `cfg.extra_card_paths`。默认返回 []，因此默认检索行为不变。
  - `_retrieve_knowledge_cards`：`context["extra_card_paths"] = self._extra_card_paths()`。
  - `run()`：
    - 构造 `self.metrics` 后，若 `cfg.enabled` 则创建 `DiscoveryRound`，并从 `store.get_claims` 恢复 claim 序号。
    - 循环内 `if success:` 更新 experiment 之后调用 `self._maybe_run_discovery(final=False)`。
    - `_flush_deferred` 之后调用 `self._maybe_run_discovery(final=True)`（需 `run_at_end`）。
    - `finally` 里对适配器 `hasattr(...,"cleanup_discovery_data")` 调用。
  - `_maybe_run_discovery(final)`：
    - 频率检查（见陷阱 2）。
    - token 守卫：`discovery_tokens/max(total_tokens,1) >= max_token_share`（首轮 discovery_tokens=0 不受限）或 `total_tokens>=budget.max_tokens` → `rounds_skipped+=1`，发 `discovery_skipped(reason=token_share|token_budget)`。
    - 否则 `_harvest()` 收集候选，调用 `round.run`，`rounds+=1`。
    - 首次晋升时记录 `best_at_first_promotion`，并发 `discovery_round_finished`。
  - `_harvest()`：
    1. `_pending_claims` 中对应节点已有效且 `delta>0` 的（source=`discover_op`）。
    2. `store.get_insights_by_experiment`：`polarity==1 and z_score>=min_insight_z`，节点未出现在已有 claim 的 `origin_node_id` 中，按 z 降序（source=`insight`）。
    3. `self._top_nodes(top_k_programs)`：排除无 parent 的根节点、已被 claim 的节点（source=`top_node`）。
    - 去重后取前 `max_claims_per_round`，取父子代码用 `self.tree.nodes`。
  - `llm_call` 包装器：调用 `self.llm.chat_for_reasoning`，`add_llm_call(m,"discover")`，写 `create_llm_call_record(exp,"discover",cfg.llm.reason_model,m,node_id="")`。捕获 `LLMTransientError` → 抛内部 `DiscoveryLLMError` 由 pipeline 按候选跳过（发 `discovery_llm_error`）。
  - discover_op：`_run_one_iteration_inner` 里选完 operator 后，`flag = cfg.enabled and every>0 and operator==REFINE and (iterations_done+1)%every==0`，调用 `ctx.set_discover_claim(flag)`。child 创建后若 `gen_result.claim` 则 `_pending_claims.append((child.id, claim))`。
  - 指标：`offered_card_ids` 确定后（含 INJECT 切片后）`discovered_cards_offered += count(id.startswith("D-"))`；`child.card_ids = adopted_cards` 处 `discovered_cards_adopted += ...`。
  - `_discovery_summary() -> dict`：返回 RunSummary 的全部新字段（未启用时为零值）。
    - `discovered_card_mean_delta` 和 `literature_card_mean_delta` 用 `store.get_all_card_stats` 按前缀 `D-` 分组，计算 `Σn·mean_delta/Σn`，n=0 → None。
    - `score_delta_after_discovery = best_score - best_at_first_promotion`，无晋升 → None。
    - `neg_control_fpr = fp/trials`（trials=0 → None）。
    - `planted_recovery_rate` 按强度分项。
  - `RunSummary(...)` 末尾追加 `**self._discovery_summary()`。仅启用时把这些字段并入 `run_finished` 事件 payload。
  - `write_discovery_artifacts(art_dir)`：写 `discovery/{phenomena.json, preregistration.json, controls.json, discovered_cards.snapshot.jsonl}`（快照是把发现卡文件复制过来）。未启用则不写。
  - `run_local_evolution`：创建 engine 后 `engine.artifacts_dir = art_dir`；`_write_artifacts` 的 finally 里对 `engine._discovery` 非空时 try/except 调用 `write_discovery_artifacts`。
- `cli.py`（typer；新增 `discover_app`、`data_app`，仿 `judge_app` 挂载）：
  - `fe discover run <task_dir> --run-id EXP [--mock] [--max-claims N] [--runs-dir] [--artifacts-dir] [--env-file] --json`：离线打开已有 run 的 `fe.db`，用 `HDDAdapter` 构造引擎最小上下文，强制 `discovery.enabled=True`，跑一轮 `DiscoveryRound`，收割源为该 run 已有 insight 和 top 节点。`--mock` 用 `MockLLM`。输出 JSON：`ok, claims_proposed, claims_tested, neg_control_fpr, promoted_cards[{id,grade}]`。run-id 不存在 → exit 1 且 `{"ok":false,"error_type":"RunNotFound"}`。
  - `fe discover report <task_dir> --run-id EXP --json`：读取 `store.get_claims/get_claim_tests/get_discovered_cards`，输出 `claims_tested, neg_control_fpr, planted_recovery_rate, grades{}, promoted_cards[{id,grade,prereg_hash,claim_id,origin_node_id}]`。
  - `fe data checkup <task_dir> --json [--out DIR]`：调用 `adapter.discovery_frames`，只输出聚合量 `data_facts.json`（`n_samples, n_positive, label_semantics, columns, min_detectable_effect`）、`field_coverage.csv`（各列非空率）、`silent_subset_stats.csv`（HDD adapter 提供可选 `checkup_extras()`；无则该文件只有表头）。计数 <10 的格子输出 `"<10"`。缺文件 → exit 1，提示先运行 `prepare_data.py`，不自动下载。
  - 所有命令失败一律输出 `{"ok":false,"error_type":...}`，不打印异常正文（避免泄露路径或密钥）。

## 5. 事件与 run_summary 字段
- 事件：`discovery_round_started, claim_proposed, claim_tested, claim_graded, card_promoted, discovery_controls, discovery_controls_failed, discovery_skipped, discovery_llm_error, discovery_error, discovery_round_finished, discovery_jev_entailment_unavailable`。
- `run_summary.json` 字段见 §4 `RunSummary`，与 docs/TODO.md 5a 指标清单一一对应。
- `tree.json` 节点新增 `adopted_cards`。

## 6. 测试（全部离线；新文件路径固定；共享 fixture 放各文件内，不新建 conftest）
1. `tests/test_discovery_stats.py`
   - `test_bootstrap_coverage`：20 个种子，n=400，`x~N(d·y,1)`，d=0.8，真值 `Φ(d/√2)-0.5`，B=200，覆盖 ≥17/20。
   - `test_bh`：`[0.001,0.02,0.04,0.3]`,q=0.05 → `[T,T,F,F]`。
   - `test_ebh`：`[100,50,10,1]`,α=0.05 → `[T,T,F,F]`。
   - `test_e_calibrator`：`e_from_p(0.01)==5.0`；`e_from_p(1.0)==0.5`；κ=1 或 0 抛 ValueError。
   - `test_permutation_p_tail`：强信号（d=1.5,n=300）`p<1e-6`；`e>=60`（陷阱 13）。
   - `test_auroc_ties`：全等特征 → 0.5。
   - `test_max_spearman`：特征等于基线某列 → ≈1.0。
2. `tests/test_claim_extraction.py`：合法 `<claim>`；缺 `feature_code` → None；非 JSON → None；无标签 → None；多个标签取第一个；direction 非法 → None。`preregister` 对键顺序不敏感（两种字典顺序哈希相同），改任一字段哈希变化。
3. `tests/test_discovery_sandbox.py`：
   - 合法特征返回覆盖 100% 的 Series。
   - `import os`、`open("x")`、`__import__`、`eval` → ok=False（静态拒绝）。
   - `while True: pass`（timeout_s=2）→ error 含 "timeout"。
   - 常量特征 → "constant"。
   - 超过 20% NaN → "low_coverage"。
   - 沙箱工作目录内没有仓库文件。
4. `tests/test_discovery_splits.py`：确定性（同 salt 同结果）；salt 改变后分配不同；2000 个 id 的 confirm 占比在 0.30±0.04；`temporal_halves` 前后段不相交且并集为全部。
5. `tests/test_discovery_controls.py`（用 FakeAdapter 合成数据，seed 固定）
   - `test_negative_control_fpr`：噪声特征 `neg_control_repeats=20` × 5 个特征，fpr ≤ 0.10。
   - `test_planted_strong_recovery`：d=1.0，repeats=20，rate ≥ 0.9。
   - `test_zero_strength_not_discovered`：d=0，repeats=40，rate ≤ 0.15。
6. `tests/test_novelty.py`：`functional_novel` 四象限（ρ 高/低 × 增量下界正/负）；`judge_entailment` 合法 JSON → 对应关系；非法 JSON → `unknown`；card_id 不在库 → `unknown`。
7. `tests/test_grading.py`：表驱动，每个 `Grade` 至少 1 例，外加：CI 跨 0 → REFUTED；`temporal_ok=False` → REFUTED；`temporal_ok=None` → UNDETERMINED；`bh_pass=True, ebh_pass=False` → UNDETERMINED；`relation=same` → CONFIRMED 且 `confirms` 正确；`opposite` → REVISED 且 `revises` 正确；`none` 且 `controls_ok=False` → UNDETERMINED；`relation=unknown` → UNDETERMINED。
8. `tests/test_card_promotion.py`
   - 晋升的卡通过 `validate_card`；`id` 匹配 `^D-<exp>-\d{3}$`。
   - priority：DISCOVERED=2，REVISED=3；`evidence=="run"`；`risk` 含"数据驱动发现"。
   - `controls.passed=False` → 返回 []。
   - 同 `prereg_hash` 不重复写入；id 冲突时序号递增。
   - `cards_path.name=="cards.jsonl"` → ValueError。
   - `benchmark/hdd_mvp/knowledge/cards.jsonl` 的 sha256 前后不变。
   - `load_all_cards(dir,[discovered])` 无 error、总数=文献卡数+发现卡数；构造与文献卡同 id 的发现卡 → 被拒且 error 含 "Duplicate"；`load_cards_from_dir` 行为与原来一致。
9. `tests/test_engine_discovery.py`（`ScriptedDiscoveryLLM` 按标记分发：`KD_TRANSLATE` 返回 `feature=m1 last`、direction "+" 的 JSON；`KD_ENTAIL` 返回 `{"card_id":null,"relation":"none"}`；其余走 MockLLM。`FakeAdapter` 提供植入信号；临时 knowledge_dir 里放 3 张文献卡）
   - `test_discovery_end_to_end`：`enabled=True, every_n_iterations=2, run_at_end=True`，跑 6 轮。断言：`discovery_rounds>=1`、`claims_tested>=1`、`claims_discovered>=1`、`discovered_cards_count>=1`、`discovered_cards.jsonl` 存在、事件序列含 `discovery_round_started→claim_proposed→claim_tested→claim_graded→card_promoted`、`discovery_tokens>0` 且已计入 `total_tokens`、`llm_call` 表存在 purpose=`discover` 的行、`discovery/` 四个产物文件存在。
   - `test_discovered_card_adopted_feeds_card_stats`：晋升后让脚本化生成器在 `<adopted_cards>` 中声明 `D-...`。断言 `store.get_card_stats` 里该 id 的 n≥1，`discovered_cards_offered>=1`、`discovered_cards_adopted>=1`，`tree.json` 的节点 `adopted_cards` 含该 id。
   - `test_final_round_after_flush`：Jev mock + deferred 场景下，最终轮发生在 `_flush_deferred` 之后。
   - `test_llm_transient_error_fail_open`：`chat_for_reasoning` 对 `KD_TRANSLATE` 抛 `LLMTransientError` → run 正常结束，有 `discovery_llm_error` 事件。
   - `test_token_share_skip`：`max_token_share=0.0001` 时第二轮起 `discovery_rounds_skipped>=1`。
   - `test_discover_op_prompt`：`discover_op_every=1` 时 REFINE 的 prompt 含 `<claim>`；INJECT 的不含。
   - `test_resume_no_duplicate_claims`：resume 后同一节点不重复翻译。
10. `tests/test_discovery_disabled.py`
    - 默认 `EvolveConfig().discovery.enabled is False`。
    - 同 seed、同脚本的 mock 运行，启用前后 `run_summary` 中除新增字段外逐项相等（用 `model_dump` 去掉新增键对比）；`total_tokens` 相等；无 `discovery_*` 事件；无 `claim` 行；无 `discovery/` 目录；无 `discovered_cards.jsonl`。
    - `build_user_message` 在 `discover_claim=False` 时输出与改动前快照逐字相同（快照用当前 main 生成，存为测试内字符串）。
    - `EvolveConfig.from_dict({"discovery":{"enabled":True}})` 与 `with_overrides` 往返后仍为 True。
11. `tests/test_cli_discover.py`（`typer.testing.CliRunner`）：先用 mock 运行产出一个 run，再执行 `discover run --mock --json` 和 `discover report --json`。断言 JSON 键齐全、`promoted_cards[*].id` 以 `D-` 开头、不存在的 run-id 返回 exit 1 和 `RunNotFound`；`data checkup` 在 FakeAdapter 或 toy 数据上输出三份文件，计数 <10 的格子被打码。
12. `tests/test_discovery_task_agnostic.py`：对 `src/faultevolve/discovery/**/*.py` 做大小写不敏感匹配 `smart|serial|hdd|vendor`，无命中。
13. 更新：`test_config.py` 增加 discovery 默认值断言；`test_store.py` 增加三张新表的 CRUD 与旧库兼容（对已有 db 再次实例化 Store 不报错）；`test_knowledge.py` 若有对 `load_cards_from_dir` 的 monkeypatch，改为同时 patch `load_all_cards`。
- 全部测试必须在 `python -m pytest tests/` 下离线通过，无网络、无真实密钥。

## 7. 技能（`skill/`，每个 SKILL.md 含：何时使用 / 输入 / 精确命令 / 成功检查（可执行断言）/ 故障处理 / 禁止操作）
1. 新增 `skill/fe-knowledge-discovery/SKILL.md` + `scripts/run_mock_discovery.sh`（toy 任务 mock 跑通）+ `scripts/check_discovery_summary.py <artifacts_dir>`。
   - 命令顺序：`fe doctor --json --task-dir <task>` → `fe data checkup <task> --json --out "$FE_RUNS_DIR/datacheck"` → `fe discover run <task> --run-id <EXP> --json [--mock]` → `fe discover report <task> --run-id <EXP> --json > /tmp/kd_report.json`。
   - 成功检查：`neg_control_fpr <= 0.10`；`promoted_cards[*].id` 均以 `D-` 开头；`claims_tested>=1`；`cards.jsonl` 的 sha256 与运行前一致；`run_summary.json` 中 `discovery_tokens` 已计入 `total_tokens`。
   - 故障处理：401/403 停止并报告；429/超时按 4s/8s/16s 退避后跳过本轮；沙箱失败率 >50% 则降低 `max_claims_per_round` 并检查 claim prompt；`discovery_controls_failed` 时不晋升，报告 fpr，调大 `bootstrap_b` 或 `neg_control_repeats` 后重跑；`discovery_skipped(no_provider)` 表示 adapter 未实现 `DiscoveryDataProvider`；token 份额超限则调低频率。
   - 禁止：手工编辑 `cards.jsonl` / `discovered_cards.jsonl`；读 `eval_only`/test/holdout；用 LLM 结论替代统计检验；写入密钥；把发现数写进报告而不附 manifest 路径。
2. 新增 `skill/fe-data-checkup/SKILL.md`：命令 `fe data checkup`；输出三份文件；成功检查 `n_positive` 等于 `meta.json` 中 train 的 1104；只输出聚合量；数据缺失时提示 `prepare_data.py`，不自动下载。
3. 更新 `skill/fe-knowledge-injection/SKILL.md`：新增"发现卡命名空间 `D-*`"章节，说明存放路径、加载顺序（`cards.jsonl` → 发现卡 → `extra_card_paths`）、id 冲突规则、`evidence:run` 与血统字段、如何经单独 PR 人工固化进仓库；成功检查为 `load_all_cards` 无 error 且文献卡仍为 51 张。
4. 更新 `skill/fe-evolve-manager/SKILL.md`：新增 `discovery:` 配置说明；新事件类型；新 run_summary 字段；发现 token 计入总 token 且可能触发 `tokens_per_point_cap`；故障表新增 discovery 行；`report_run.py` 输出 discovery 字段（缺失时忽略，向后兼容）。

## 8. 实现顺序（每步跑一遍 `python -m pytest tests/`）
1. config + schemas + store 新表 + metering。
2. loader `load_all_cards` + selection 接入（测试 8 的加载部分）。
3. discovery 包各模块（stats → splits → sandbox → baseline → controls → novelty → grading → promotion → claims）与对应测试。
4. protocol + FakeAdapter + HDDAdapter.discovery_frames。
5. pipeline + engine 接线 + operators 的 discover_op（测试 9、10）。
6. CLI（测试 11）。
7. 技能 + `docs/TODO.md` 5a 状态更新 + README 中文说明。
8. 提交：`git add`、`git commit`、`git push -u origin feat/knowledge-discovery-kd1`，再开 PR。

## 9. 实跑（稍后，不在本 PR 里做）
一次真实运行：`discovery.enabled: true, every_n_iterations: 5`。报告：
- §4.3 常规指标：best_score、valid_rate、total_tokens、tokens_per_ros_point。
- 全部发现指标：`discovery_tokens/share`、`discovery_rounds/skipped`、各 `claims_*`、`discovered_cards_count/offered/adopted/adoption_rate`、`discovered_card_mean_delta` 与 `literature_card_mean_delta` 对比、`score_delta_after_discovery`、`neg_control_false_positives/fpr`、`planted_recovery_rate`（按强度）。
- 不设发现卡数量目标。要求发现 token 已计入总 token。

## 10. 明确不做
`card_priors.json`（可选，延到 KD2 并在 PR 描述说明）；Jev 蕴含调用（仅留钩子）；机理层、锦标赛、否证证书、报告（KD2）；前端；`OperatorType.DISCOVER`。
