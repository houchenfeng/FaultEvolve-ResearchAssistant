# KD2 实施计划：机理层 + 数据裁决锦标赛 + 否证证书 + 报告

基线：main=6bbc040（KD1 已合入）。分支 `cursor/knowledge-discovery-kd2-3f68`。只做后端。默认全关，关闭时行为、prompt、run_summary 内容与现状一致（新增 summary 字段取零值/None），零额外 token。
所有新增 `discovery/*.py` 必须通过 `tests/test_discovery_task_agnostic.py`（禁用词 `smart|serial|hdd|vendor`，大小写不敏感，含注释和 docstring）。

## 0. 已核实的代码事实与陷阱（先读）
1. `pipeline.py` 的 `RoundResult.extras` 目前恒为 `{}`；`graded` 只有 payload 字典，没有 Claim；`feature_map`、`baseline_df`、掩码都是 `run()` 的局部变量。KD2 必须由 `run()` 在 `cfg.tournament.enabled` 时把它们放进 `extras["kd2"]`（`KD2Handoff`）。关闭时 `extras` 仍为 `{}`。
2. `pipeline.py` 用 `np.random.default_rng(hash(claim.prereg_hash) % 2**32)`。`hash(str)` 随进程变化，不可复现。KD2 新代码一律用 `seed_from(*parts) = int.from_bytes(sha256("|".join(parts)).digest()[:4],"big")`。不要改 KD1 那一行（保持 KD1 测试）。
3. HDD 的 `discovery_frames().labels` 只有 `serial_number,label`，没有 model 或日期列。因此 KD1 的 `temporal_ok` 目前按行号折半。不要往 `labels` 里加列（会改变 KD1 行为）。改为在 `DiscoveryFrames` 新增可选字段 `env_frame`（见 §2.2）。
4. `_reflect_positive` 是唯一创建 Insight 的地方，`_reflect_hypothesis_refuted` 不写 insight。所以现在 `get_foreign_insights` 的 negatives 恒为空。KD2 的 `[MECH]` 负向 insight 是它唯一来源。
5. `get_foreign_insights` 按 `branch_id != node.branch_id` 过滤。机制 insight 用哨兵 `branch_id="__mechanism__"`，这样所有分支都能看到。不能走 `BranchMemoryManager.propagate_insight`（它会把 id 挂到祖先的 `top_insight_ids`）。直接用 `store.create_insight`。
6. `_harvest_discovery_candidates` 只取 `polarity==1` 的 insight，所以 polarity=-1 的机制 insight 不会回流成新 claim。禁止为"成立的机制"写 polarity=+1 的 insight（否则会被再次当作 claim 来源）。
7. `_evaluate_child` 有两个调用点：`_run_one_iteration` 和 `_flush_deferred`（PR #4 Jev 延迟评估，`count_iteration=False`）。所有 KD2 对 `_evaluate_child` 的改动不得改签名，不得依赖 `count_iteration`。延迟节点的 insight 也只在 `_evaluate_child -> _apply_reflection` 里产生，因此锦标赛必须在 `_flush_deferred` 之后才看得到完整 insight。最终一轮沿用现有顺序（`run()` 里 flush 之后再 `_maybe_run_discovery(final=True)`），不要挪动。
8. `BranchMemory.summary` 会被 `_handle_implementation_reflection` 覆盖成 `"Repair hint: ..."`。写机制摘要时不得覆盖以 `Repair hint:` 开头的内容；`propagate_insight` 会原样复制 summary，不必处理。
9. `USER_MESSAGE_TEMPLATE` 的每个 section 单独占一行，空 section 也会产生空行。新 section 必须拼在 `{foreign_negative_section}` 同一行末尾（`{foreign_negative_section}{mechanism_context_section}`），空串时输出与现状逐字节一致。
10. `RunSummary` 是 pydantic 模型，`_discovery_summary()` 用 `**` 展开。新增字段必须在 `RunSummary` 里声明并给默认值，否则报错。`test_discovery_disabled.py` 的字段集合检查保持通过（只增不减）。
11. `_BUDGET_STAGE_KEYS`（config.py）与 `budget.STAGES` 校验 `stage_caps` 的键；新增 `"mechanism"`。`stage_caps` 默认为空，行为不变。
12. PR #6 analysis、PR #5 selection/budget、PR #7 operators/bandit、Jev 预筛：KD2 不触碰 selector、bandit、`_choose_operator`、`_available_operators`、Jev 状态。锦标赛发生在 `_maybe_run_discovery` 内部，不影响 `iterations_done`，也不调用 `record_iteration`。
13. 无 API key 时 `MockLLM.chat_for_reasoning` 返回反思模板 JSON。锦标赛的 LLM 解析必须容错：解析失败就只保留固定对手（`propose_rivals` 不抛异常）。
14. 卡片文件：`discovered_cards.jsonl`，绝不写 `cards.jsonl`。`promotion._existing_exp_seq` 只解析 `D-<exp>-<数字>`，`D-<exp>-M001` 不会干扰它。

## 1. 配置（`config.py`）
```python
class TournamentConfig(BaseModel):
    enabled: bool = False
    elo_k0: float = Field(default=32.0, gt=0)
    max_rounds: int = Field(default=3, ge=1)      # 每个 run 最多几轮锦标赛
    max_rivals: int = Field(default=2, ge=0, le=2)   # 仅 LLM 生成的对手数；固定对手不受限
    n_slices: int = Field(default=4, ge=2, le=16)    # confirm 集切成的互斥切片数
    min_env_pos: int = Field(default=5, ge=1)        # 环境内正例数下限
    equiv_margin: float = Field(default=0.02, gt=0)  # 零效应预测用的等价边界（AUROC-0.5 单位）
    icp_gate_p: float = Field(default=0.01, gt=0, lt=1)
    max_token_share: float = Field(default=0.10, gt=0, le=1)
    max_patches: int = Field(default=1, ge=0)        # 每个机制最多修订次数
```
`DiscoveryConfig` 新增 `tournament: TournamentConfig = Field(default_factory=TournamentConfig)`。`from_dict` 已整体构造 `DiscoveryConfig(**data["discovery"])`，pydantic 会解析嵌套 dict，无需改。`InsightsConfig` 新增 `reputation_enabled: bool = False`。
锦标赛的 `alpha`、`e_calibrator_kappa`、`bootstrap_b`、`split_salt` 复用 `DiscoveryConfig`。
`tournament.enabled=true` 而 `discovery.enabled=false` 时：`EvolveConfig` 加 `model_validator`，报 `ValueError("tournament requires discovery.enabled")`。

## 2. 数据结构
### 2.1 `discovery/schemas.py`（追加）
- `MechanismRole = Literal["claim","llm_rival","confound","artifact","censor","other"]`
- `class Mechanism(BaseModel)`：`id: str`（`M-<exp>-<claim_seq>-<role缩写>`）、`claim_id: str`、`role`、`title`、`nodes: list[str]`、`edges: list[tuple[str,str,Literal["+","-"]]]`（因果图）、`predictions: dict[str, Literal[1,-1]]`（key 为检验类型）、`patch_count: int = 0`、`status: Literal["proposed","established","refuted","undetermined"] = "proposed"`、`parent_id: str|None`。
- `class MatchResult(BaseModel)`：`mech_a, mech_b, test_type, test_id, slice_id, stat, ci_low, ci_high, p, e_raw, log_bf_trunc, supports: Literal["a","b","none"], decisive: bool, min_detectable: float|None`。
- `class Certificate(BaseModel)`：`mechanism_id, rival_id, test_id, test_type, env, stat, ci: tuple[float,float], e_value, prereg_hash, date`。
- `class KD2Handoff`（dataclass）：`claims: list[Claim]`（仅 grade 为 CONFIRMED/REVISED/DISCOVERED）、`payloads: dict[str,dict]`、`feature_map: dict[str,np.ndarray]`（与 labels 逐行对齐）、`y: np.ndarray`、`groups: np.ndarray`、`unit_ids: np.ndarray`、`confirm_mask: np.ndarray`、`env_frame: pd.DataFrame|None`、`schema_note: str`、`round_idx: int`。
- `class TournamentStats`（dataclass，全 int/float 零值）：`mechanisms_proposed, matches_played, decisive_matches, underpowered_draws, certificates_issued, mechanisms_established, mechanisms_refuted, mechanism_patches, mechanism_cards_promoted, tournament_rounds, rounds_skipped, planted_mechanism_trials, planted_mechanism_recovered, shuffled_env_trials, shuffled_env_false_pass: int`，`llm_vs_data_kendall_tau: float|None = None`，`min_detectable_effects: list[float]`。
### 2.2 `tasks/protocol.py`
`DiscoveryFrames` 追加可选字段（有默认值，不动 `TaskAdapter`）：`env_frame: Any = None`。语义：DataFrame，行序与 `labels` 一致，列可含 `env`（环境标签，字符串，HDD 用"机型族×季度"）、`conf`（混杂协变量，可选，字符串）、`time`（可比较的时间，用于时间先后检验）、`censor`（0/1，标签删失代理，可选）。缺列则对应检验类型不可用。
### 2.3 `tasks/hdd_adapter.py`（任务特定，允许写领域词）
`discovery_frames` 额外构造 `env_frame`：从 `train_labels.csv` 取 `model`、`cutoff_date`；`env = model_family + "|" + cutoff 季度`（`model_family` = `model` 的第一个空格前 token）；`conf = model_family`；`time = cutoff_date`；`censor` = 该盘在 cutoff 之前历史中 `smart_187_raw>0` 的 0/1（用已读入的 `history` 计算，只读 train）。不要改 `labels`、`history` 的内容。`worker/runner.py` 的 `FakeAdapter` 增加 `env_frame`（见测试）。

## 3. 新模块（`src/faultevolve/discovery/`）
### 3.1 `mechanisms.py`
- `FIXED_RIVALS = ("confound","artifact","censor","other")`；每个有固定 `predictions` 模板：
  - `claim`：`{"env_invariance": +1, "temporal": +1, "dose_response": +1, "mediation": +1, "heterogeneity": -1}`
  - `confound`（环境协变量同时驱动 X 和 Y）：`{"env_invariance": -1, "heterogeneity": +1, "temporal": +1, "dose_response": +1, "mediation": -1}`
  - `artifact`（X 的计数语义在环境间不同，是测量伪迹）：`{"env_invariance": -1, "heterogeneity": +1, "dose_response": -1, "temporal": +1, "mediation": -1}`
  - `censor`（换盘造成标签删失）：`{"temporal": -1, "mediation": -1, "env_invariance": +1, "dose_response": +1, "heterogeneity": -1}`
  - `other`：全部 `-1`（占位，仅在其他对手不足时被抽到）
  含义：`+1` 表示"该检验统计量显著大于 0"，`-1` 表示"统计量不大于 0（零或反向）"。
- `propose_rivals(claim: Claim, schema_note: str, llm_call, max_rivals: int, experiment_id: str) -> list[Mechanism]`：返回 `[claim 机制] + FIXED_RIVALS 四个 + ≤max_rivals 个 llm_rival`。LLM prompt 以标记 `KD_MECH_RIVALS` 开头，只给 `claim.title/condition/outcome/scope` 与 `schema_note`（不给数据）。响应格式 `<rivals>[{"title","edges":[[a,b,"+"|"-"]],"predictions":{...}}]</rivals>`，解析失败或 LLM 异常时返回空 llm_rival 列表（固定对手仍在）。`predictions` 缺失的 key 补 `-1`。
- `revise_mechanism(m: Mechanism, evidence: list[MatchResult], llm_call, max_patches: int) -> Mechanism|None`：若 `m.patch_count >= max_patches` 返回 None；否则 LLM（标记 `KD_MECH_REVISE`）返回新 `predictions`，返回 `m.model_copy(update={"id": m.id+"r", "patch_count": m.patch_count+1, "parent_id": m.id, "status":"proposed"})`。
- `Mechanism` 和预测表的 sha256：`prediction_hash(mechs: list[Mechanism]) -> str`，对 `sorted([(id, sorted(predictions.items()))])` 做 JSON（sort_keys）后 sha256。
- `unify(established: list[Mechanism]) -> list[dict]`：返回 `[]`（原理层接口）。
### 3.2 `tests_catalog.py`
`TEST_TYPES = ("env_invariance","temporal","dose_response","mediation","heterogeneity")`。
`available_tests(env_frame) -> list[str]`：`env` 列存在且≥2 个环境含 ≥`min_env_pos` 正例 → `env_invariance`、`heterogeneity`；有 `time` → `temporal`；恒有 `dose_response`；有 `conf` → `mediation`。
`run_test(test_type, x, y, groups, env_frame_slice, cfg, tcfg, rng) -> tuple[float, float, float, float]`，返回 `(stat, ci_low, ci_high, p_pos)`，其中 `p_pos` 是"stat>0"的单侧 bootstrap p 值，`p_neg` 由 `p_null_margin` 另算。统计量（全部基于 `stats.signed_effect`，按 `groups` 做有放回 bootstrap，B=`cfg.bootstrap_b`）：
- `env_invariance`：各环境（正例数 ≥`min_env_pos`）的 `signed_effect` 按环境样本量加权平均（环境内效应）。
- `heterogeneity`：`pooled_effect - within_env_mean`（pooled 为整片 signed_effect）。
- `temporal`：`time` 后半段 `signed_effect` 减前半段（按 `time` 中位数切分）与 `sign(direction)` 相乘后取值，用于检验"效应随时间不衰减"（预测 `+1` 表示不小于 0）。
- `dose_response`：x 按分位切 5 箱，箱内失败率与箱序号的 Spearman 相关（direction 为 `-` 时取反）。
- `mediation`：`signed_effect(x)` 在按 `conf` 分层后（层内效应加权均值）的残余，即 `within_conf_effect`，`+1` 表示残余显著大于 0。
`bootstrap_dist(stat_fn, groups, b, rng) -> np.ndarray` 是本模块内部辅助函数（不要改 `stats.py`）。`p_pos = (1+#{boot<=0})/(1+B)`；`p_null = (1+#{boot>=equiv_margin})/(1+B)`。
`derive_tests(ma: Mechanism, mb: Mechanism, avail: list[str]) -> list[str]`：只保留 `ma.predictions[t]*mb.predictions[t] == -1` 且在 `avail` 中的检验；按 EIG 近似 `eig(t) = 1 if 对方为 -1 else 0` 之后排序，具体为 `sorted(key=lambda t: (-abs(prior_effect[t]), t))`，其中 `prior_effect` 固定表 `{"env_invariance":1.0,"heterogeneity":0.9,"temporal":0.7,"dose_response":0.6,"mediation":0.5}`（确定性）。
### 3.3 `icp.py`
`@dataclass IcpResult: passed: bool; reason: str; env_effects: dict[str,float]; het_p: float|None; gate_p: float|None`。
`icp_check(x, y, env, direction, alpha, b, gate_p, min_env_pos, rng) -> IcpResult`：
1. 环境标签信息门：x 秩变换后的 η²（组间平方和/总平方和），以及 y 的组间失败率方差；对 `env` 做 b 次置换，得两个 p 值，`min(p_x, p_y) > gate_p` → `IcpResult(False,"env_uninformative",...)`。
2. 环境内效应：正例数 < `min_env_pos` 的环境丢弃；剩余环境 <2 → `False,"too_few_envs"`。
3. 方向一致：所有环境的 `signed_effect` 符号都等于 direction 的符号，否则 `False,"sign_flip"`。
4. 异质性：`het = 加权方差(环境效应)`；对 `env` 置换 b 次，`het_p = (1+#{het_perm>=het})/(1+b)`；`het_p <= alpha` → `False,"heterogeneous"`。
5. 否则 `True,"ok"`。
### 3.4 `tournament.py`
- `class SliceReuseError(RuntimeError)`；`class DataBudgetLedger`：`__init__(self, family_id)`；`use(slice_id: str, purpose: str)`：同一 `slice_id` 在同一 `family_id` 内第二次调用抛 `SliceReuseError`；`used() -> list[str]`；`fresh(all_ids: list[str]) -> list[str]`。
- `slice_masks(unit_ids, confirm_mask, salt, n_slices) -> list[np.ndarray]`：对 confirm 内的单元按 `sha256(f"{salt}|kd2|{unit}")` 取模 `n_slices` 分成互斥布尔掩码（并集等于 `confirm_mask`）。`slice_id = f"S{i}"`。**切片只来自 confirm 集，绝不含 explore 集或评估数据。**
- `elo_k(k0, e_raw, alpha) -> float = k0 * min(1.0, abs(math.log(e_raw)) / math.log(1/alpha))`。
- `elo_update(ra, rb, score_a, k) -> tuple[float,float]`：`ea = 1/(1+10**((rb-ra)/400))`；`ra' = ra + k*(score_a - ea)`；`rb' = rb + k*((1-score_a) - (1-ea))`。`score_a ∈ {1, 0, 0.5}`。初始 Elo 1500。
- `trunc_log_bf(log_e_signed) = float(np.clip(log_e_signed, math.log(0.1), math.log(10)))`（截断 log BF ∈ [log(1/10), log(10)]，仅用于信誉账本和 Elo 强度，不用于判定）。
- `swiss_pairs(mechs, elo, played: set[frozenset]) -> list[tuple[str,str]]`：按 Elo 降序相邻配对，避开 `played` 中已打过的对；总要含 `claim` 机制对每个固定对手至少一场（`test_fixed_rivals_always_present`）。
- `class Tournament`：
  - `__init__(cfg: DiscoveryConfig, store: Store, experiment_id: str, llm_call, log_event, stats: TournamentStats)`。
  - `run_family(handoff: KD2Handoff, family_idx: int) -> FamilyResult`：对 `handoff.claims` 中最多 `max_claims_per_round` 个成立 claim，每个 claim 一个"比赛族"（`family_id = f"F-{exp}-{claim.id}"`，`DataBudgetLedger(family_id)`）：
    1. `mechs = propose_rivals(...)`，写 `mechanism` 表，`mechanisms_proposed += len(mechs)`。
    2. `prereg = prediction_hash(mechs)`，写事件 `tournament_preregistered{family_id, hash}`，此后不得改 `predictions`（revise 产生新机制并单独重新预注册）。
    3. 至多 `tcfg.max_rounds` 轮：每轮 `swiss_pairs` → 每对 `derive_tests` → 对每个检验从 `ledger.fresh(slice_ids)` 取第一个未用切片，`ledger.use()`，在该切片上 `run_test`。切片用尽 → 事件 `tournament_no_fresh_slice`，该对停止（其余机制状态保持 `undetermined`）。
    4. 每场结果：`e_eff = max(e_from_p(p, kappa), 1.0)`，其中 `p = p_pos`（预测 `+1` 的一方胜方向）或 `p_null`（预测 `-1` 的一方）。若 `p_pos` 与 `p_null` 都不满足 `e_eff >= 1/alpha` → `supports="none"`，`underpowered_draws += 1`，并记 `min_detectable = 该切片正负样本量对应的 z_(1-alpha/2)*se`（`se` 取 bootstrap 分布标准差，`min_detectable = 2.0 * se`），写入 `stats.min_detectable_effects`。若 `p_pos` 侧 `e_eff >= 1/alpha` → 预测 `+1` 的机制胜；`p_null` 侧 → 预测 `-1` 的机制胜。胜者 `decisive_matches += 1`，`score_a` 取 1/0；平局 0.5。`log_bf_signed = +log(e_eff)`（a 胜）、`-log(e_eff)`（b 胜）、0（平）；Elo 用 `elo_k(k0, e_eff, alpha)`。
    5. 累积 `E[(a,b)] = ∏ exp(±log e_eff)`（未截断）；写 `match`、`test_result` 表。
    6. 终局判定（对每个非 claim 机制 R）：`E(claim vs R)`；claim 机制 `established` 当且仅当：所有固定对手与 LLM 对手 R 都满足 `E(claim,R) >= 1/alpha`（对手不含 `other`，除非它参与过比赛），且 `icp_check(...)` 通过（对 `handoff.feature_map[claim.id]` 在 confirm 集 + `env_frame["env"]` 上跑，seed 用 `seed_from(family_id,"icp")`），且把该族全部 claim 机制的 `E` 值一起送 `ebh_reject(evals, alpha)` 后仍为 True。`refuted` 当且仅当存在 R 使得 `E(R,claim) >= 1/alpha`。否则 `undetermined`。Elo 不参与判定。
    7. 被否证且 `patch_count < max_patches` 且还有未用切片 → `revise_mechanism` → 新机制重新预注册并只跑一次与原胜者的对局（在新切片）。`mechanism_patches += 1`。修订后仍被否证 → 终态 refuted。
    8. 每个 `(claim 机制, R)` 中通过决定性检验的对局，`certificates.issue(...)`（§3.5）。
  - `FamilyResult`：`mechanisms: list[Mechanism]`，`matches: list[MatchResult]`，`certificates: list[Certificate]`，`elo: dict[str,float]`。
- 相同的 `env_frame is None` 或可用检验为空 → 事件 `tournament_skipped{reason:"no_env"}`，`rounds_skipped += 1`，机制全部 `undetermined`（不写卡）。
### 3.5 `certificates.py`
`issue(mech, rival, match: MatchResult, env: str, prereg_hash: str, claim_prereg: str) -> Certificate`（`date` 用 `datetime.now(timezone.utc).isoformat()`）；`write_json(art_dir, certificates, mechanisms, tournament_results)`：写 `discovery/certificates.json`、`discovery/mechanisms.json`、`discovery/tournament_results.json`、`discovery/theories.json`（固定 `[]`）。
### 3.6 `mech_promotion.py`
`promote_mechanisms(established: list[Mechanism], claims: dict[str,Claim], cards_path: Path, experiment_id: str, log_event) -> list[dict]`：卡 id `D-<exp>-M<nnn>`（nnn 从现有文件里 `D-<exp>-M\d+` 的最大值 +1，3 位补零）；`category="feature_engineering"`（claim.category 若为 `pitfalls` 则沿用）；`priority=1`；`evidence="run"`；`grade="established"`；`source_ids=[f"run:{exp}", f"mechanism:{m.id}", f"claim:{claim.id}"]`；`claim` 用机制标题+适用范围；`impl_hint` 用 `claim.feature_code[:600]`；用 `validate_card` 校验；已存在相同 `prereg_hash` 则跳过；`cards_path.name == "cards.jsonl"` 抛 `ValueError`；追加写。

## 4. 存储（`cloud/store.py`，只加表和方法）
DDL（`CREATE TABLE IF NOT EXISTS`，旧库自动补建，不改 node 表）：
- `mechanism(id TEXT PRIMARY KEY, experiment_id, claim_id, family_id, role, status, patch_count INTEGER, payload_json, created_at)`
- `match(id INTEGER PRIMARY KEY AUTOINCREMENT, experiment_id, family_id, round INTEGER, mech_a, mech_b, slice_id, payload_json, created_at)`
- `test_result(id INTEGER PRIMARY KEY AUTOINCREMENT, match_id INTEGER, experiment_id, test_type, payload_json, created_at)`
- `certificate(id INTEGER PRIMARY KEY AUTOINCREMENT, experiment_id, mechanism_id, rival_id, payload_json, created_at)`
- `theory(id INTEGER PRIMARY KEY AUTOINCREMENT, experiment_id, payload_json, created_at)`（只建表）
方法：`create_mechanism(experiment_id, m: dict, family_id)`、`update_mechanism(mech_id, status=..., patch_count=...)`、`get_mechanisms(experiment_id, status: str|None=None) -> list[dict]`、`create_match(...) -> int`、`create_test_result(match_id, ...)`、`get_matches(experiment_id)`、`create_certificate(...)`、`get_certificates(experiment_id)`、`update_insight_beta(insight_id: str, experiment_id: str, d_alpha: float, d_beta: float)`（原子 `UPDATE insight SET alpha=alpha+?, beta=beta+? WHERE id=? AND experiment_id=?`）。

## 5. 修改现有代码
### 5.1 `common/schemas.py`
`HypothesisStatus` 追加 `CORROBORATED="corroborated"`、`UNDETERMINED="undetermined"`。`RunSummary` 追加（全部有默认值）：`mechanism_tokens:int=0, mechanisms_proposed:int=0, matches_played:int=0, decisive_matches:int=0, underpowered_draws:int=0, certificates_issued:int=0, mechanisms_established:int=0, mechanisms_refuted:int=0, mechanism_patches:int=0, mechanism_cards_count:int=0, tournament_rounds:int=0, planted_mechanism_recovered: float|None=None, llm_vs_data_kendall_tau: float|None=None, shuffled_env_false_pass: float|None=None, tournament_tokens:int=0, min_detectable_effect: float|None=None`。`tournament_tokens` 与 `mechanism_tokens` 同值（TODO 指标名）。
### 5.2 `common/metering.py`
`RunMetrics` 加 `mechanism_prompt_tokens/mechanism_completion_tokens/mechanism_tokens/mechanism_latency_ms`；`add_llm_call` 增加 `purpose == "mechanism"` 分支（同时照常累加 total）；`to_dict` 增加 `mechanism_tokens`、`mechanism_token_share`。`budget.py`：`STAGES` 加 `"mechanism"`；`config._BUDGET_STAGE_KEYS` 加 `"mechanism"`；`engine._stage_used_tokens` 加 `if stage == "mechanism": return self.metrics.mechanism_tokens`。
### 5.3 `cloud/insights.py`
- `_parse_reflection_json`：合法 layer 元组改为 `("implementation","design","hypothesis","mechanism")`。`LAYERED_REFLECTION_PROMPT` 常量不变；新增常量 `MECHANISM_LAYER_HINT`，仅当 `LayeredReflector(llm, exp, mechanism_layer=True)` 时追加到 prompt 末尾（构造函数新增关键字参数，默认 False，所以默认 prompt 逐字节不变）。若 `mechanism_layer=False` 而 LLM 仍返回 `mechanism`，解析时降级为 `design`。
- `get_foreign_insights(..., use_reputation: bool = False)`：`use_reputation` 为真时排序键改为 `abs(z_score) * 2 * alpha/(alpha+beta)`；默认排序不变。
- `update_insight_reputation(insight_id, success, store, experiment_id)`：`store.update_insight_beta(insight_id, experiment_id, 1.0 if success else 0.0, 0.0 if success else 1.0)`；insight 不存在时静默返回。
- 新增 `record_mechanism_insight(store, experiment_id, m: Mechanism, claim_origin_node: str, e_value: float, rival_title: str) -> Insight`：`Insight(id=uuid4()[:8], origin_node=claim_origin_node, branch_id="__mechanism__", polarity=-1, change_summary="[MECH] "+m.title[:80], mechanism=f"被数据否证：优于它的对手 {rival_title}", conditions="", tags=["mechanism"], delta=0.0, z_score=min(math.log(max(e_value,1.0)), 10.0), created_at=now_iso())`，用 `store.create_insight` 写入。
### 5.4 `cloud/operators.py`
`OperatorContext.mechanism_context: list[dict] = []`；`set_mechanism_context(items: list[dict[str,Any]]) -> "OperatorContext"`。`build_user_message` 里 `mechanism_context_section`：空则 `""`；否则 `"## 已成立的机理（数据裁决，可作为设计依据）\n<mechanism_context>\n- {title}（证书 {n} 张）：{text[:200]}\n</mechanism_context>\n"`，最多 3 条。模板：`{foreign_negative_section}{mechanism_context_section}`。**不动** `OPERATOR_INSTRUCTIONS`、INJECT 逻辑和 `adopted_cards_instruction`。
### 5.5 `discovery/pipeline.py`
`run()` 里在 `RoundResult` 返回前，若 `self.cfg.tournament.enabled`：构建 `KD2Handoff`（`claims` 取 `graded_items` 里 grade ∈ {CONFIRMED, REVISED, DISCOVERED} 且 `controls.passed` 的 Claim；`env_frame = getattr(frames, "env_frame", None)`；`unit_ids=labels[unit_col].astype(str).to_numpy()`），放入 `extras={"kd2": handoff}`；否则 `extras={}`（保持现状）。异常分支不变。`write_artifacts` 不动（锦标赛产物由 engine 写）。
### 5.6 `cloud/engine.py`
- `__init__`：`self._tournament: Tournament|None = None`；`self._tstats = TournamentStats()`；`self._tournament_rounds = 0`；`self._offered_insights: dict[str, list[str]] = {}`；`self._tournament_results: dict = {}`（累积供写 artifact）。
- `run()`：`config.discovery.enabled and config.discovery.tournament.enabled` 时构造 `Tournament(cfg, store, exp_id, self._mechanism_llm_call, self._log_event, self._tstats)`；`reflector` 构造处传 `mechanism_layer=tournament.enabled`（`_apply_reflection` 里的 `LayeredReflector(self.llm, self.experiment_id, mechanism_layer=...)`）。
- 新方法 `_mechanism_llm_call(messages) -> str`：复制 `_discovery_llm_call`，`purpose="mechanism"`，`create_llm_call_record(..., "mechanism", ...)`，`LLMTransientError` 包成 `DiscoveryLLMError`。
- `_maybe_run_discovery`：在 `self._discovery.run(...)` 得到 `result` 之后追加 `self._maybe_run_tournament(result, final)`（放在写 `discovery_round_finished` 事件之前或之后均可，保持 KD1 事件不变）。`_maybe_run_tournament`：
  1. 不满足 `tournament.enabled`、无 `result.extras.get("kd2")`、`self._tournament_rounds >= max_rounds` → 直接 return（若是因 `max_rounds` 则 `rounds_skipped+=1` 并写事件 `tournament_skipped{reason:"max_rounds"}`）。
  2. token 份额：`mechanism_tokens>0 and mechanism_tokens/max(total,1) >= tournament.max_token_share` → `tournament_skipped{reason:"token_share"}`；`self._stage_capped("mechanism")` 同理；`total_tokens >= budget.max_tokens` → `reason:"token_budget"`。
  3. `fr = self._tournament.run_family(...)`（每个 claim 一个族），累积到 `_tournament_results`。
  4. 回灌 `_feed_back_mechanisms(fr, handoff)`：
     - refuted：`record_mechanism_insight(...)`，事件 `mechanism_refuted{mechanism_id}`，`mechanisms_refuted += 1`。
     - established：`promote_mechanisms` 写 `discovered_cards.jsonl`，`store.record_discovered_card(card_id, claim_id, exp, "mechanism")`；对 claim 的 `origin_node_id` 及其祖先写 `branch_memory.summary`（规则见 §0.8，格式 `"[MECH] {title}: {claim}"[:200]`，保留 `top_insight_ids` 与 `refuted_hypotheses`）；`tree.update_hypothesis_status(origin_node, CORROBORATED)`（原状态为 REFUTED 时不覆盖）；undetermined → `UNDETERMINED`（同样不覆盖 REFUTED/SUPPORTED/CORROBORATED）。
  5. 写事件 `tournament_round_finished{round, established, refuted, undetermined}`，`_tournament_rounds += 1`，`_tstats.tournament_rounds` 同步。
- 路由 mechanism 层：`_apply_reflection` 里在负向分支中，`elif layer == "mechanism": self._reflect_mechanism_issue(parent, child, delta, reflection)`，放在 `hypothesis` 和 `design` 分支**之后**、且仅当 `mechanism_layer` 开启时才可能出现该 layer。`_reflect_mechanism_issue`：`tree.update_node_status(child.id, NodeStatus.DONE)`；`update_hypothesis_status(child.id, UNDETERMINED)`；写事件 `reflection_mechanism`；**不**增加 `hypothesis_fail_count`，**不**标记卡片 refuted。正向仍走 `_reflect_positive`（顺序由 PR #3.1 保证）。
- 信誉更新：`_run_one_iteration` 里 child 节点创建后 `self._offered_insights[child.id] = [i["id"] for i in positive+negative if i.get("id")]`（只在 `insights.reputation_enabled` 为真时记录）。`_evaluate_child` 在 `eval_result` 确定之后、`_apply_reflection` 之前：`ids = self._offered_insights.pop(child.id, [])`；仅当 `eval_result.is_valid` 时对每个 id 调 `update_insight_reputation(id, delta > noise_delta, ...)`。无效节点不更新（避免把 API 兼容错误算到 insight 头上）；延迟评估的节点走同一路径，键缺失则跳过；不改 `_evaluate_child` 签名。`get_foreign_insights` 调用处传 `use_reputation=self.config.insights.reputation_enabled`。
- 机制上下文：`_run_one_iteration` 里 `ctx.set_foreign_insights` 之后，若 tournament 开启：`ctx.set_mechanism_context(self._mechanism_context_items())`，从 `store.get_mechanisms(exp,"established")` 取最多 3 个（按 E 降序）。未开启不调用。
- `_discovery_summary()`：在 `return {...}` 中合并 `_tournament_summary()`（新方法）。`planted_mechanism_recovered = planted_recovered/planted_trials`（无试验则 None）；`llm_vs_data_kendall_tau`、`shuffled_env_false_pass` 同理（None 表示未测）；`min_detectable_effect = min(min_detectable_effects)` 或 None。`run_finished` 事件与 `RunSummary` 已自动包含。
- `_write_artifacts` 里在 `write_discovery_artifacts` 之后调用 `engine.write_tournament_artifacts(art_dir)`，内部 try/except 后调用 `certificates.write_json(...)`；未启用时不写。
- 三项 KD2 内部对照（写入 stats 供 summary/report）：`Tournament.run_family` 结束后（`tournament.enabled` 时才执行，只用 confirm 数据、不调用 LLM，零 token）：(a) 对每个族的 claim 特征做一次 env 标签置换后的 `icp_check`，累计 `shuffled_env_trials`/`shuffled_env_false_pass`；(b) `llm_vs_data_kendall_tau`：LLM 对手的顺序（`propose_rivals` 响应里给出的 `plausibility` 排名，缺失则跳过）对比数据 Elo 排名的 Kendall τ（用 `scipy.stats.kendalltau`，样本<3 则 None）；(c) planted 恢复只在测试中做，运行时保持 0/None。

## 6. 报告：`discovery/report.py` + CLI
- `build_manifest(art_dir: Path, run_id: str) -> dict`：只读 `run_summary.json`、`discovery/phenomena.json`、`controls.json`、`mechanisms.json`、`certificates.json`、`tournament_results.json`、`theories.json`；缺文件当空。返回 `{"run_id", "numbers": {扁平 key->数值}, "phenomena": [...], "mechanisms": [...], "certificates": [...], "sources": {文件名: sha256}}`。`numbers` 固定包含：`claims_{confirmed,revised,discovered,refuted,undetermined}`、`neg_control_false_positives`、`neg_control_fpr`、`planted_recovery_rate.<strength>`、`mechanisms_{proposed,established,refuted}`、`matches_played`、`decisive_matches`、`underpowered_draws`、`certificates_issued`、`mechanism_patches`、`tournament_tokens`、`best_score`、`initial_score`、`total_tokens`。
- `render_json(manifest) -> str`（`sort_keys=True, indent=2, ensure_ascii=False`）；`render_md(manifest) -> str`：模板里所有数字只能通过内部 `_n(key)` 从 `manifest["numbers"]` 取值格式化（整数 `str(int)`，浮点 `f"{v:.4g}"`）；不得手写任何数字字面量（章节序号除外，用 `1.`, `2.` 之外的中文小标题，避免数字）。
- `verify_md(md: str, manifest: dict) -> list[str]`：用正则 `-?\d+(?:\.\d+)?` 抽取所有数字，逐个检查是否等于 `_n` 格式化后的某个 manifest 值，返回不匹配列表。
- `cli.py` 新增：`@app.command("report")`，签名 `report(task_dir: Path, run_id: Annotated[str, Option("--run-id")], as_json: Annotated[bool, Option("--json")]=False, as_md: Annotated[bool, Option("--md")]=False, artifacts_dir: Optional[Path]=Option("--artifacts-dir"), runs_dir: Optional[Path]=Option("--runs-dir"))`。产物目录解析复用 `get_artifacts_dir`；`--json`/`--md` 二选一（都缺则按 `--json`）；失败输出 `{"ok": false, "error_type": "ReportError"}` 并 `Exit(1)`，不打印路径或异常细节。输出中 `--md` 之后执行 `verify_md`，有不匹配则 `Exit(2)`。

## 7. 测试（全部离线，`tests/`；测试数据用合成 numpy，无外部文件）
新文件 `tests/test_tournament.py`：
1. `test_planted_mechanism_wins_confound_loses`：seed=7；N=6000，`env` 4 个（每个 1500），`x~N(0,1)`，`y~Bernoulli(sigmoid(-2.2+0.9*x))`（真因果，环境内效应相同）；`groups=unit_ids`；`env_frame` 含 `env,conf(=env),time`；`Tournament(...)` 用 `MockLLM` 脚本化（`KD_MECH_RIVALS` 返回空 rivals）；断言：claim 机制状态 `established`；`confound` 与 `artifact` 状态 `refuted`；`len(certificates) >= 1`；`decisive_matches >= 1`。另一个数据（`conf` 驱动：`x=env_shift+N(0,1)`，`y` 只依赖 `env`）：断言 claim 机制状态**不是** established（refuted 或 undetermined）。
2. `test_icp_shuffled_env_rejects`：种子 0..19，各生成 N=3000 数据（`env∈{0..3}`，x 均值随 env 位移，y 概率随 env 变化，环境内效应相同）；对每个种子：真实 env 时 `icp_check(...).passed` 为 True（至少 18/20 通过）；把 env 用 `np.random.default_rng(seed).permutation` 打乱后不通过率 `>= 0.9`（`shuffled_rejected/20 >= 0.9`，断言 reason ∈ `{"env_uninformative","sign_flip","heterogeneous","too_few_envs"}`）。
3. `test_elo_k_formula`：`elo_k(32, e_raw=math.e**3, alpha=0.05) == pytest.approx(32*min(1, 3/math.log(20)))`（=32.0）；`elo_k(32, math.exp(1.0), 0.05) == approx(32*1/math.log(20))`；`elo_k(32, 1.0, 0.05) == 0.0`；`elo_update(1500,1500,1.0,32)==(1516.0,1484.0)`；`trunc_log_bf(10)==approx(math.log(10))`，`trunc_log_bf(-10)==approx(math.log(0.1))`。
4. `test_data_budget_ledger_rejects_reuse`：`DataBudgetLedger("F1").use("S0","t")` 第二次抛 `SliceReuseError`；同 slice 在另一个 `DataBudgetLedger("F2")` 可用；`slice_masks` 输出互斥且并集等于 `confirm_mask`；`run_family` 在 `n_slices=2` 且需要 3 次检验时，第三次触发事件 `tournament_no_fresh_slice` 且不抛异常。
5. `test_fixed_rivals_always_present`：`propose_rivals` 在 LLM 返回垃圾、返回空、抛 `LLMTransientError` 三种情况下，结果 role 集合都包含 `{"claim","confound","artifact","censor","other"}`；`max_rivals=2` 且 LLM 返回 3 个时只保留 2 个 llm_rival；`swiss_pairs` 保证 claim 机制对每个固定对手至少有一对。
6. `test_derive_tests_only_opposite_signs`：两个机制预测表构造成只有 `env_invariance` 和 `heterogeneity` 相反 → 返回 `["env_invariance","heterogeneity"]`；无 env 列时 `available_tests` 不含这两个，`derive_tests` 返回 `[]`。
7. `test_prediction_hash_frozen`：`prediction_hash` 对同一组机制幂等；改一个预测值哈希变化；`revise_mechanism` 后 `patch_count==1`，超过 `max_patches` 返回 None。
新文件 `tests/test_mechanism_feedback.py`：
8. `test_refuted_mech_in_foreign_negatives`：用真实 `Store`（tmp_path）和 `record_mechanism_insight`；再对一个 `branch_id="b1"` 的节点调 `get_foreign_insights`，negatives 含 `change_summary.startswith("[MECH]")`；positives 不含；`build_user_message` 的 `## 其他分支已证伪的做法` 段包含 `[MECH]`。
9. `test_mechanism_layer_parse`：`LayeredReflector(llm, "e", mechanism_layer=True)` 解析 `{"layer":"mechanism",...}` 保持 `mechanism`；`mechanism_layer=False` 时降级为 `design`；默认 prompt 字符串与 `LAYERED_REFLECTION_PROMPT.format(...)` 完全相同（`mechanism_layer=False` 时不含 "mechanism" 提示）。
10. `test_update_insight_reputation_beta`：新 insight (α=β=1)，`success=True` → (2,1)；再 `False` → (2,2)；不存在的 id 不抛；`get_foreign_insights(use_reputation=True)` 让高信誉 insight 排前，`False` 时顺序保持 |z| 序。
11. `test_mechanism_context_section_empty_is_identical`：`build_user_message(ctx)` 与 `set_mechanism_context([])` 相同，且 `"<mechanism_context>" not in msg`；`USER_MESSAGE_TEMPLATE.replace("{mechanism_context_section}","")` 等于改前模板（用测试内嵌的旧模板字面量比较）；非空时含 `<mechanism_context>`。
12. `test_established_mech_card_and_memory`：`promote_mechanisms` 写出 `D-exp-M001`、priority 1、`validate_card` 通过、再次调用同一 `prereg_hash` 不重复、文件名为 `cards.jsonl` 时抛 `ValueError`；`load_all_cards` 能读到该卡；`_feed_back_mechanisms` 对祖先写入 `[MECH]` summary，`Repair hint:` 开头的不被覆盖；`CORROBORATED` 不覆盖 `REFUTED`。
13. `test_hypothesis_status_backward_compat`：旧库里 `hypothesis_status="supported"` 的节点仍可读取；`HypothesisStatus("corroborated")` 有效。
新文件 `tests/test_engine_tournament.py`（`FakeAdapter` + `ScriptedDiscoveryLLM`，参考 `tests/test_engine_discovery.py`；`FakeAdapter.discovery_frames` 增加 `env_frame`）：
14. `test_tournament_disabled_zero_cost`：同一 seed 与配置，`discovery.enabled=True`，`tournament.enabled=False` 与仅 KD1 的基线相比：`run_summary` 中所有旧字段相同；`mechanism_tokens==0`；无 `mechanism` 表行；`discovery/mechanisms.json` 不存在；`run_summary` 里新字段为零或 None。
15. `test_tournament_enabled_accounting`：`tournament.enabled=True`：`run_summary["mechanism_tokens"] == tournament_tokens`，且 `total_tokens` 含它；`llm_calls` 表中 `purpose="mechanism"` 的 token 和等于 `mechanism_tokens`；事件里有 `tournament_preregistered` 和 `tournament_round_finished`；`discovery_tokens` 不含 mechanism。
16. `test_tournament_requires_discovery_config`：`tournament.enabled=True` 且 `discovery.enabled=False` 抛 `ValueError`。
17. `test_tournament_with_jev_deferred_and_resume`：开 `judge` 延迟评估（参考 `tests/test_jev_screening.py` 的写法），验证锦标赛只在 `_flush_deferred` 之后的最终轮处理；再 `resume` 一次，`mechanism` 表不产生重复行（`family_id`+`role` 唯一，重复时跳过族）。
18. `test_report_numbers_match_manifest`：先跑一次 test 15 的 run，`build_manifest` → `render_md`；`verify_md(md, manifest) == []`；再手动在 md 里改一个数字，`verify_md` 返回非空；`render_json` 中每个 `numbers` 值与 `run_summary.json` 对应字段相等；CLI：`CliRunner().invoke(app, ["report", task, "--run-id", exp, "--json"])` 退出码 0，输出可解析。
19. `test_kd2_sources_task_agnostic`：复用 task-agnostic 检查已覆盖新文件；新增断言 `src/faultevolve/cloud/*.py` 的新增代码不含 `smart|serial|hdd|vendor`（对 `insights.py`、`operators.py` 新增函数做字符串检查）。
既有测试：`test_discovery_disabled.py`、`test_engine_discovery.py`、`test_hotfix_3_1.py`、`test_insights.py` 必须原样通过。

## 8. 技能
- 更新 `skill/fe-knowledge-discovery/SKILL.md`：新增"机理层（KD2）"章节：何时使用（`discovery.tournament.enabled: true`；需要 `env_frame`）；输入（fe.db、`evolve.yaml` 中 `discovery.tournament`）；命令（`fe evolve local <task> --mock -n 6`，`bash skill/fe-knowledge-discovery/scripts/run_mock_tournament.sh`，`python skill/fe-knowledge-discovery/scripts/check_tournament_summary.py <artifacts_dir>`）；成功检查（`mechanism_tokens == tournament_tokens` 且计入 `total_tokens`；`certificates.json` 每条含全部 10 个字段；`mechanisms_established + mechanisms_refuted + undetermined == mechanisms_proposed`；`D-*-M*` 卡 priority 为 1；`cards.jsonl` sha256 不变；`underpowered_draws>0` 时报告最小可检测效应）；故障处理表（无 env 列 → `tournament_skipped(no_env)`；全平局 → 如实报告 `min_detectable_effect`，不要调低 α；token 份额 → 调大 `max_token_share` 或减小 `max_rounds`；`tournament_no_fresh_slice` → 调大 `n_slices`；401/403 停止上报；429/超时 4/8/16/32s 退避）；禁止项（不得改预注册后的预测表；不得读 holdout；LLM 结论不得替代统计判定；不得手改证书）。
- 新增 `skill/fe-report-generation/SKILL.md` 与 `scripts/check_report_numbers.py`（读取 md 与 manifest，调用 `verify_md`，非空则退出 1）：何时用（出结果表/答辩材料）；输入（run 的 artifacts 目录）；命令（`fe report <task> --run-id EXP --json`、`--md`、`python skill/fe-report-generation/scripts/check_report_numbers.py <md> <artifacts_dir>`）；成功检查（`verify_md == []`、所有数字可在 `run_summary.json`/`mechanisms.json`/`certificates.json` 里找到）；故障处理（缺产物 → 先跑 `fe evolve local`；不匹配 → 重新生成而不是手改）；禁止手写数字。
- 更新 `skill/fe-evolve-manager/SKILL.md`：配置块 `discovery.tournament.*`、`insights.reputation_enabled`、`analysis`；新增 `fe report`；新增指标字段清单与"只读 run_summary 判断，不要看 LLM 文本"；故障处理里加 `tournament_skipped` 各 reason。
- 更新 `skill/fe-knowledge-injection/SKILL.md`：在"发现卡命名空间 `D-*`"章节新增 `D-<exp>-M<nnn>` 机制卡（priority 1、`grade=established`、`source_ids` 含 `mechanism:`），说明它们自动被检索、计入 `card_stats`，以及"机制卡与 KD1 发现卡的区别"；检查 `cards.jsonl` 不变。
- 脚本 `run_mock_tournament.sh`、`check_tournament_summary.py`：仿照 `run_mock_discovery.sh`/`check_discovery_summary.py`。

## 9. 实施顺序与提交
1. config + schemas + store 表/方法 + metering（测试 13、16、部分 14）。
2. `mechanisms.py`、`tests_catalog.py`、`icp.py`、`tournament.py`、`certificates.py`、`mech_promotion.py`（测试 1–7、12）。
3. `insights.py`、`operators.py`（测试 8–11）。
4. `pipeline.py` handoff、`protocol.py`、`hdd_adapter.py`、`FakeAdapter.env_frame`、`engine.py`（测试 14、15、17）。
5. `report.py` + CLI（测试 18、19）。
6. 技能与脚本。
7. `python -m pytest tests/` 全绿；`cd benchmark/hdd_mvp && python evaluator.py init.py` 仍为 val ROS≈22.81（不修改受保护文件）。

## 10. 待办：延后到最后的真实运行（现在不要跑）
`discovery.enabled: true, every_n_iterations: 5, tournament.enabled: true` 一次真实 HDD run，报告：`best_score/initial_score`、`total_tokens`、`discovery_tokens`、`mechanism_tokens`（份额）、KD1 指标（claims_* 五类、`neg_control_fpr`、`planted_recovery_rate`）、锦标赛指标（`mechanisms_proposed, matches_played, decisive_matches, underpowered_draws, certificates_issued, mechanisms_established, mechanisms_refuted, mechanism_patches, min_detectable_effect, shuffled_env_false_pass, llm_vs_data_kendall_tau`）、`D-*-M*` 卡数及其被采纳率与 `discovered_card_mean_delta`；通过 `fe report --md` 生成表并附 `verify_md` 结果。合并规则：token 全计入、`cards.jsonl` 不变、`neg_control_fpr<=0.10`。回退：`tournament.enabled: false`。
