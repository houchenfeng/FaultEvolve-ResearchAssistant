# Cloud Agent Prompt：新知识发现（后端）

> 本文件包含两段可以独立使用的 prompt：
> - **Prompt A = PR-KD1**：现象层发现 + 发现卡回灌。先做这一段。
> - **Prompt B = PR-KD2**：机理层 + 锦标赛 + 报告。等 KD1 合入后再使用。
>
> 每段都可以原样粘贴给 cloud agent。

---

## Prompt A — PR-KD1：现象层知识发现 + 发现卡回灌（只做后端）

你是在私有仓库 `houchenfeng/Self-evolution-optimization-agnet`（FaultEvolve，Python ≥3.12，typer CLI `fe`）上工作的自主工程 agent。全程无人值守，按下面的说明独立完成，最后开一个 **draft PR**。

### 0. 起点与硬性前提
1. **从最新的 `main` 开始**：`git fetch origin && git checkout -B cursor/knowledge-discovery-kd1 origin/main`。不要基于任何其他分支。
2. 前提检查：本 PR 依赖 PR #3（知识卡注入）已合入 main。
   - 运行 `test -f src/faultevolve/knowledge/loader.py && grep -q "CREATE TABLE IF NOT EXISTS card_stats" src/faultevolve/cloud/store.py`。
   - **若检查失败**，说明 PR #3 尚未合入：**不要写代码，不要 cherry-pick**。开一个只包含 `docs/kd1-blocked.md` 的 draft PR 说明阻塞原因后结束。
3. 先记录测试基线：`pip install -e . && pytest -q 2>&1 | tail -3`，把通过数写进 PR 描述。**必须保留全部已有测试并让它们通过**：不删除、不 skip、不放宽断言。若某个已有测试因本 PR 的 bug 修复而必须改预期，只允许修改该断言，并在 PR 描述中逐条写明原因。
4. 遵守 `AGENTS.md`：
   - 不修改 `benchmark/hdd_mvp/{evaluator.py, init.py, problem.md, prompt.md}` 和 `benchmark/hdd_mvp/data/`
   - 不读取 holdout/test、`data/eval_only/`
   - 密钥只从环境变量读取
   - LLM/Jev 的输出永远不能成为节点分数
5. **不做任何前端/UI/Web 服务**（不写 React/NestJS/REST/WebSocket）。只做引擎功能，以及 JSON 产物和 CLI `--json`。

### 1. 背景（你需要知道的设计）
设计来源是 RA 仓库 `houchenfeng/FaultEvolve-ResearchAssistant/docs/discovery_plan_v2.md`（可用 GitHub 读取；若读不到，以本 prompt 为准）。

"新知识发现"的现象层含义：把进化树中带来真实提升的程序改动，翻译成可证伪的 **Claim** = ⟨条件 S，特征代码 X，结果 Y（7 天内失效），方向 ±，适用范围，否证条件⟩。然后按以下顺序处理：
1. 预注册 sha256
2. 在本地数据上做按盘分组的 bootstrap CI、时间方向一致性检查、BH + e-BH 多重检验校正
3. 打乱标签阴性对照、植入信号阳性对照
4. 相对 51 张文献卡的新颖性检查
5. 分级：确认/修正/发现/已否证/未定

"发现"和"修正"会晋升为新的知识卡，回灌进 PR #3 的检索、采纳、card_stats 闭环。

### 2. 已核实的代码事实（以 main 为准，动手前请自己复核）
- `cloud/engine.py` 的 `EvolutionEngine._apply_reflection` 分支顺序为：
  ```
  if delta < -hyp or layer=="hypothesis": _reflect_hypothesis_refuted(...)
  elif delta < -design or layer=="design": _reflect_design_issue(...)
  elif delta > design: _reflect_positive(...)
  ```
  而 `LayeredReflector` 只允许 layer ∈ {implementation, design, hypothesis}。**结果是正向提升几乎进不了 `_reflect_positive`**，还可能把采纳的卡误标为 refuted。
- `_reflect_positive` 会创建 `Insight(z=delta/noise_delta)`，调用 `BranchMemoryManager.propagate_insight`，并记录 `insight_extracted` 事件。
- `knowledge/loader.py`：
  - `REQUIRED_FIELDS={id,title,category,claim,source_ids,tags}`
  - `category` 必须属于 `VALID_CATEGORIES`（9 类）
  - priority 取值 1–5
  - 多余字段会被忽略
  - `load_cards_from_dir` 只读 `cards.jsonl`
- `store.card_stats` 的主键是 `(experiment_id, card_id)`；另有 `node_adopted_cards`、`branch_refuted_cards`、`branch_offered_cards`。
- `TaskAdapter` 是 `@runtime_checkable Protocol`。**不要往里加方法**，否则会破坏已有的 isinstance 检查。
- `Tree` 按列持久化节点，**不要给 node 表加列**，只加新表。
- `EvaluationResult` 设置了 `extra="forbid"`，不要往里塞新字段。
- 测试工具：`worker/runner.py` 的 `FakeAdapter`/`FakeTaskSpec`、`cloud/llm.py` 的 `MockLLM`（脚本化 `chat`/`chat_for_reasoning`）、`tests/fixtures/toy_task`。HTTP mock 用 `httpx.MockTransport`，不要引入 respx。
- HDD 数据在 `benchmark/hdd_mvp/data/public/`：`train_history.csv.gz`、`train_labels.csv`（train 共 31,093 样本、1,104 正例，cutoff 2024-07-14~09-23）、`val_*`。**发现模块只读 `train_*`。**
- `_attempt_repair` 在旧版本中引用了未定义的 `repair_count`。请 grep 一下，若仍存在则修复。

### 3. 要实现的内容
**3.1 修复反思路由（先做，单独提交）**
- 在 `_apply_reflection` 中先按 delta 符号分流：
  - `delta > design_threshold` 时一律走 `_reflect_positive`
  - 负向时保持原逻辑（按阈值和 layer 区分 hypothesis/design）
- 保证正向时不调用 refuted 逻辑。
- 新增 `tests/test_reflection_routing.py`。

**3.2 新包 `src/faultevolve/discovery/`**
- `schemas.py`：
  - `Claim`（id、experiment_id、origin_node_id、source∈{insight, discover_op, manual}、condition、feature_code、outcome、direction、scope、falsifier、prereg_hash、status、grade）
  - `ClaimTestResult`（split、effect、ci_low、ci_high、p、e、n_pos、n_neg）
  - `ControlReport`
  - `Grade`（CONFIRMED/REVISED/DISCOVERED/REFUTED/UNDETERMINED）
- `claims.py`：
  - `translate_claim(...)`：用 `llm.chat_for_reasoning` 输出 JSON
  - `extract_claim_from_response(text)`：解析 `<claim>…</claim>`，失败返回 None
  - `preregister(claim)`：canonical JSON 的 sha256，字段顺序无关
- `sandbox.py`：在子进程运行 `def feature(history: pd.DataFrame) -> pd.Series`（按样本键索引）。
  - 复用 `common/codecheck.py` 的禁用规则
  - 禁止 IO 和网络
  - 超时由 `sandbox_timeout_s` 控制
  - 返回长度或索引不匹配时判为失败
- `splits.py`：
  - 按 group（序列号）的哈希切分为 exploration/confirmation，比例由 `confirmation_fraction` 控制，盐为 `split_salt`
  - 时间方向检验：把 train 按 cutoff 时间分成前后两段
- `stats.py`（只用 numpy/pandas/scipy 中已有的依赖，**不新增依赖**；先检查 requirements.txt）：
  - 按组 bootstrap CI
  - 单特征效应（AUROC−0.5，以及分位组失效率比）
  - 组置换 p 值
  - p→e 校准：`e = κ·p^(κ−1)`，κ=0.5
  - BH、e-BH
  - 增量检验：在 K0 基线特征的 logistic 回归上加入 X，计算 ΔAUPRC 或 Δlog-lik 的 bootstrap CI
  - max|Spearman ρ|
- `baseline_features.py`：K0 基线特征库。取 51 张卡中常见的做法：`smart_5/187/188/197/198` 等的最后值、14 天差分、非零计数。
- `controls.py`：
  - 阴性对照：在机型分层内打乱标签，重复 `neg_control_repeats` 次
  - 阳性对照：按 `planted_strengths` 植入信号，统计回收率
- `novelty.py`：
  - 功能新颖性：`max|ρ| < rho_max` 且增量 CI 下界 > 0
  - 语义新颖性：reasoning LLM 盲判"是否被某卡 claim 蕴含，返回卡 id 或 none"
  - `use_jev_entailment=true` 且仓库已有 Jev 客户端时可选调用；任何失败都 fail-open
- `grading.py`：表驱动分级。
  - **发现**：确认切片 CI 不跨 0 且方向与预注册一致，且时间方向一致，且 BH q≤α 与 e-BH 都通过，且功能新颖，且不被任何卡蕴含，且本轮阴性对照 fpr ≤ `max_neg_control_fpr`
  - **确认**：统计条件同上，但被某卡蕴含且方向相同
  - **修正**：被某卡蕴含，但方向或幅度不同
  - **已否证**：CI 跨 0、方向翻转或时间方向不一致
  - 其余为**未定**，并记录最小可检测效应
  - 本轮阴性对照不达标时，整轮不晋升任何卡
- `promotion.py`：DISCOVERED 和 REVISED 晋升为卡。
  - `id="D-<exp_id>-<nnn>"`
  - `category` 在 `VALID_CATEGORIES` 内校验，默认 `feature_engineering`
  - `rationale` 写入效应/CI/q/e/样本量
  - `risk` 必须包含"数据驱动发现，未经文献验证"
  - `source_ids=["run:<exp>","node:<id>","claim:<cid>"]`
  - `tags` 含 SMART 属性名
  - `impl_hint` 为特征代码，截断至约 600 字符
  - `priority`：发现=2，修正=3
  - `evidence="run"`
  - 附加字段：`grade`、`prereg_hash`、`revises`/`confirms`、`created_at`
  - 追加写入 `discovery.cards_path`（默认 `<runs_dir>/knowledge/discovered_cards.jsonl`），按 claim 哈希去重
  - **绝不写仓库中的 `cards.jsonl`**
- `pipeline.py`：`DiscoveryRound`，流程为收割 → 翻译 → 预注册 → 沙箱 → 探索检验 → 确认检验 → 时间检验 → FDR（在本 run 内累计全部已检验的 claim）→ 对照 → 新颖性 → 分级 → 晋升。
  - 收割来源：polarity=+1 且 z≥`min_insight_z` 的 insight；top-K 有效节点；DISCOVER 调度产生的 `<claim>`
  - 每轮最多 `max_claims_per_round` 个
  - 只输出聚合量
  - 任何异常都记录 `discovery_error` 事件并 fail-open

**3.3 任务无关的数据接口**
- 在 `tasks/protocol.py` 新增**独立的** `@runtime_checkable class DiscoveryDataProvider(Protocol)`，方法为 `discovery_frames(task_spec) -> DiscoveryFrames`（dataclass：`features_input`、`labels`、`group`、`time`、`env`）。
- `HDDAdapter` 实现该方法，只读 `data/public/train_*`。
- `FakeAdapter` 实现合成数据版本，植入信号强度可控。
- 引擎中若 `not isinstance(adapter, DiscoveryDataProvider)`，记录 `discovery_skipped{reason:"no_provider"}` 事件。

**3.4 接入引擎与知识检索**
- `knowledge/loader.py` 新增 `load_all_cards(knowledge_dir, extra_paths)`：
  - 加载顺序：`cards.jsonl` → 同目录下的 `discovered_cards.jsonl` → `discovery.cards_path` → `extra_card_paths`
  - id 冲突时拒绝后加载的卡，并返回 error
  - `load_cards_from_dir` 的签名和行为**保持不变**
- `get_era_knowledge_cards` 改用 `load_all_cards`，发现卡与文献卡同池检索。若存在缓存，晋升后清空（受 `inject_same_run` 控制）。
- 引擎调用时机：
  - 每 `every_n_iterations` 次迭代运行一轮
  - `run_at_end` 时在结束前运行一轮
  - 发现 token 占比超过 `max_token_share` 时跳过，并记录 `discovery_skipped{reason:"token_budget"}`
- DISCOVER 调度：`discover_op_every>0` 时，在对应迭代的 REFINE 指令末尾追加"额外输出一个 `<claim>` JSON 块"。节点 operator 仍记为 REFINE，**不要**修改 `select_operator`。
- 发现相关的 LLM 调用：`metrics.add_llm_call(m, "discover")`，并以 purpose=`discover` 写入 `llm_call` 表。

**3.5 存储、配置、指标、产物、CLI**
- `store.py` **只新增表**：`claim`、`claim_test`、`discovered_card`，并提供相应的 CRUD 方法。
- `config.py` 新增 `DiscoveryConfig`，默认值如下（`enabled` 默认 **false**），并在 `benchmark/hdd_mvp/evolve.yaml` 中加入 `discovery:` 段，保持 `enabled: false`：
  ```yaml
  discovery: {enabled: false, every_n_iterations: 5, run_at_end: true, max_claims_per_round: 3,
    min_insight_z: 2.0, top_k_programs: 3, discover_op_every: 0, alpha: 0.05, bootstrap_b: 500,
    e_calibrator_kappa: 0.5, rho_max: 0.8, planted_strengths: [0.2, 0.5, 1.0], neg_control_repeats: 5,
    max_neg_control_fpr: 0.10, confirmation_fraction: 0.3, split_salt: "fe-kd-2026",
    sandbox_timeout_s: 120, max_token_share: 0.2, inject_same_run: true, cards_path: null,
    extra_card_paths: [], use_jev_entailment: false}
  ```
- `RunMetrics`/`RunSummary` 新增字段（写入 `run_summary.json` 和 `run_finished` 事件）：
  - token：`discovery_tokens`、`discovery_token_share`
  - 轮次：`discovery_rounds`、`discovery_rounds_skipped`
  - claim 计数：`claims_proposed`、`claims_tested`、`claims_sandbox_failed`、`claims_confirmed`、`claims_revised`、`claims_discovered`、`claims_refuted`、`claims_undetermined`
  - 发现卡：`discovered_cards_count`、`discovered_cards_offered`、`discovered_cards_adopted`、`discovered_card_adoption_rate`
  - 效果：`discovered_card_mean_delta`、`literature_card_mean_delta`、`score_delta_after_discovery`
  - 对照：`neg_control_false_positives`、`neg_control_fpr`、`planted_recovery_rate`（按强度分项的 dict）
- 新事件：`discovery_round_started`、`claim_proposed`、`claim_tested`、`claim_graded`、`card_promoted`、`discovery_controls`、`discovery_controls_failed`、`discovery_skipped`、`discovery_error`、`discovery_round_finished`。
- 产物写入 art_dir：`discovery/phenomena.json`、`discovery/preregistration.json`、`discovery/controls.json`、`discovery/discovered_cards.snapshot.jsonl`。`tree.json` 的节点增加 `adopted_cards` 字段（只加不改）。
- 可选的跨 run 先验：run 结束时把发现卡的 card_stats 汇总写入 `<runs_dir>/knowledge/card_priors.json`，retriever 只把它当先验使用。若接入成本高，就不做，并在 PR 描述里写明。
- CLI（typer，风格与 `evolve local` 一致）：
  - `fe discover run <task_dir> --run-id EXP [--mock] [--max-claims N] [--runs-dir] [--artifacts-dir] [--env-file] [--json]`：对已有 run 的 fe.db 离线执行一轮
  - `fe discover report <task_dir> --run-id EXP --json`：输出汇总，并含 `promoted_cards` 列表
  - `fe data checkup <task_dir> --json [--out DIR]`：输出 `data_facts.json/.md`、`field_coverage.csv`、`silent_subset_stats.csv`（S0 = 失效当日 smart 5/187/197/198 全为 0 或 NULL 的正例占比，只在 train 上计算）。只输出聚合量，计数 <10 的格子做抑制

### 4. 测试（全部离线；不得调用真实 API）
新增以下测试：
- `test_discovery_stats.py`：bootstrap 覆盖率 ≥0.85（20 个种子）；BH/e-BH 已知向量；校准单调
- `test_claim_extraction.py`
- `test_discovery_sandbox.py`：禁用 import/IO、超时、长度不匹配
- `test_discovery_controls.py`：打乱标签时 fpr ≤0.10（20 个种子）；强植入信号回收率 ≥0.9；零强度信号不被判为发现
- `test_novelty.py`
- `test_grading.py`：参数化
- `test_card_promotion.py`：通过 `validate_card`；前缀为 `D-`；仓库 `cards.jsonl` 的 sha256 前后不变；去重；`load_all_cards` 能处理冲突
- `test_reflection_routing.py`
- `test_engine_discovery.py`：FakeAdapter 植入信号 + MockLLM 脚本化 claim，运行后产生发现卡；下一次检索能提供它；采纳后写入 card_stats；run_summary 字段齐全
- `test_discovery_disabled.py`：默认配置下事件类型集合、已有 run_summary 字段、LLM 调用次数都不变
- `test_cli_discover.py`

最终运行 `pytest -q`，**通过数必须 ≥ 基线，且 0 失败**。若仓库配置了 ruff，也要运行并通过。

### 5. 离线端到端验收
```bash
tmp=$(mktemp -d) && cp -r benchmark/hdd_mvp "$tmp/task"
python - "$tmp/task/evolve.yaml" <<'PY'
import sys, yaml
p = sys.argv[1]
c = yaml.safe_load(open(p)) or {}
c.setdefault("discovery", {}).update(enabled=True, every_n_iterations=3)
yaml.safe_dump(c, open(p, "w"), allow_unicode=True)
PY
sha_before=$(sha256sum benchmark/hdd_mvp/knowledge/cards.jsonl)
fe evolve local "$tmp/task" --mock -n 6 --runs-dir "$tmp/runs" --json > "$tmp/out.json"
python - "$tmp" <<'PY'
import json, sys, pathlib
t = pathlib.Path(sys.argv[1])
out = json.load(open(t / "out.json"))
d = pathlib.Path(out["output_dir"])
s = json.load(open(d / "run_summary.json"))
for k in ["discovery_tokens", "claims_proposed", "discovered_cards_count", "neg_control_fpr", "planted_recovery_rate"]:
    assert k in s, k
for f in ["phenomena.json", "preregistration.json", "controls.json"]:
    assert (d / "discovery" / f).exists(), f
print("OK")
PY
test "$sha_before" = "$(sha256sum benchmark/hdd_mvp/knowledge/cards.jsonl)"
! grep -rn "eval_only" src/faultevolve/discovery
```
注意：mock 模式下 MockLLM 可能不产生合法 claim，此时允许 `claims_tested == 0`，但字段和产物文件必须存在。

### 6. 技能（全自动标准；PR 描述中必须列出）
每个 SKILL.md 都要包含六节：何时使用 / 输入（`.env`：`DASHSCOPE_API_KEY`；Jev 密钥变量名取自 `evolve.yaml` 的 `judge.api_key_env`；`FE_RUNS_DIR`；`discovery:` 字段）/ 精确命令（含 `--mock` 离线命令）/ 成功检查（可执行的 python 断言）/ 故障处理（401/403 停止并报告；429/超时重试后跳过本轮；沙箱失败率 >50%；`discovery_controls_failed`；`no_provider`；token 超限）/ 禁止操作（手工编辑卡文件、读取 eval_only/test/holdout、用 LLM 结论替代统计、写出无 manifest 来源的数字）。
- **新增** `skill/fe-knowledge-discovery/SKILL.md`：命令依次为 `fe doctor --json --task-dir …` → `fe data checkup … --json --out …` → `fe discover run … --run-id … --json` → `fe discover report … --json > /tmp/kd_report.json`。成功断言：`claims_tested>=1`（非 mock）、`neg_control_fpr<=0.10`、全部 promoted id 以 `D-` 开头、`cards.jsonl` 的 sha256 不变。
- **新增** `skill/fe-data-checkup/SKILL.md`：成功断言为 `data_facts.json` 中的 `n_positive` 等于 `data/meta.json` 中 train 的 `n_positive`。数据文件缺失时只提示运行 `prepare_data.py`，**不自动下载**。
- **更新** `skill/fe-knowledge-injection/SKILL.md`：说明发现卡命名空间、存放位置、加载顺序和冲突规则、如何人工固化进仓库；成功检查为文献卡仍是 51 张且 `load_all_cards` 无 error。
- **更新** `skill/fe-evolve-manager/SKILL.md`：说明 `discovery:` 配置、新事件、新字段、路由修复的影响，并在故障表中加入相应行。

### 7. 提交与 PR
- 分多次提交：① 路由修复；② discovery 包 + 测试；③ 引擎/检索接入；④ CLI + 技能 + 文档。
- 开 **draft PR**，标题为 `feat: 现象层知识发现 + 发现卡回灌 (KD1)`。描述需包含：
  - 基线测试数与最终测试数
  - 修改了哪些已有测试断言及原因（若有）
  - 新增/更新的技能列表
  - run_summary 新字段示例（来自 mock 运行）
  - 已知限制：只用 train 切片；尚无机理层；没有 Iceberg 长面板
- 不要合并 PR，不要推送到 main，不要修改服务器或其他仓库。

---

## Prompt B — PR-KD2：机理层 + 数据裁决锦标赛 + 否证证书 + 报告（KD1 合入后使用）

你是在私有仓库 `houchenfeng/Self-evolution-optimization-agnet` 上工作的自主工程 agent，全程无人值守。

### 0. 起点与前提
- **从最新的 `main` 开始**：`git fetch origin && git checkout -B cursor/knowledge-discovery-kd2 origin/main`。
- 前提：`src/faultevolve/discovery/pipeline.py` 与 `DiscoveryDataProvider` 已存在（即 KD1 已合入）。否则只开一个说明阻塞原因的 draft PR 后结束。
- 先记录 `pytest -q` 基线。**必须保留全部已有测试并让它们通过**。
- 遵守 AGENTS.md。不做前端/UI/Web 服务。

### 1. 要实现的内容
设计依据为 RA 仓库 `docs/discovery_plan_v2.md` 的机理层部分。
- `discovery/mechanisms.py`：
  - `Mechanism`：结构化因果图，以及它在各检验上的预测符号表
  - `propose_rivals(claim)`：LLM 生成 1–2 个对手，并**固定加入**：
    - `M_confound`：机型/厂商混杂
    - `M_artifact`：厂商 SMART 计数语义伪迹
    - `M_censor`：187>0 时换盘导致的标签删失
    - `M_other`
  - `revise_mechanism`：计为补丁（`patch_count`），修订后必须在未用过的切片上重检
- `discovery/tests_catalog.py`：
  - 检验类型：环境不变性（env 为机型族 × cutoff 季度；数据中有 datacenter 列时才用该列）、时间先后、剂量反应（分箱单调）、中介、异质性
  - `derive_tests(mi, mj)`：只保留两者预测符号相反的检验，按 EIG 近似值排序
- `discovery/tournament.py`：
  - 瑞士制配对，按 Elo 以及 EIG 排序
  - 比赛前预注册预测矩阵 sha256
  - 只在 confirmation 切片上运行；生成机制的 LLM 只看 schema
  - e ≥ 1/α 判胜，否则判为"功效不足"并记录最小可检测效应
  - Elo 更新 `R_i += K·(S−E_i)`，`K = K0·min(1, |log e|/log(1/α))`
  - 信誉账本使用截断 log BF ∈ [1/10, 10]；E=∏e
  - 数据预算账本：同一切片在一个比赛族内只用一次，重复使用时抛异常
  - **最终判定**：E≥1/α **且** 通过 ICP **且** 经 e-BH 后仍显著。Elo 只用于排赛程
- `discovery/icp.py`：简化 ICP，要求各环境内效应方向一致，且异质性检验不拒绝。
- `discovery/certificates.py`：
  - 证书字段 `{mechanism_id, rival_id, test_id, test_type, env, stat, ci, e_value, prereg_hash, date}`
  - 写出 `certificates.json`、`mechanisms.json`、`tournament_results.json`
- `cloud/insights.py`：
  - `LayeredReflector` 允许 `mechanism` 层
  - 实现 `update_insight_reputation`（Beta α/β）
- `cloud/operators.py`：`OperatorContext.set_mechanism_context()`，并在 `USER_MESSAGE_TEMPLATE` 中加入 `<mechanism_context>` 段，为空时不输出。
- `cloud/engine.py`：
  - 路由 mechanism 层
  - 锦标赛结果回灌：
    - **被否证的机制**：写一条 `change_summary` 以 `[MECH]` 开头、polarity=-1 的 insight，使其自动进入 `get_foreign_insights` 的 negatives
    - **成立的机制**：写入相关节点的 `branch_memory.summary`，并晋升为发现卡 `D-<exp>-M<nnn>`，priority=1
- `store.py`：只新增表 `mechanism`、`match`、`test_result`、`certificate`、`theory`（theory 只建表）。
- `common/schemas.py`：`HypothesisStatus` 追加 CORROBORATED、UNDETERMINED，并确认旧数据仍可读取。
- 原理层**只留接口**：`unify()` 返回空，`theories.json` 为空列表。
- `discovery/report.py` + CLI：
  - `fe report <task_dir> --run-id EXP --json|--md`，数字只来自 manifest（run_summary、phenomena、mechanisms、certificates、tournament_results）
  - 输出 phenomena/confirmed/discovered/refuted 计数、`neg_control_false_positives`、`planted_recovery_rate`、机制与证书统计
- 新增指标：`mechanisms_proposed`、`matches_played`、`decisive_matches`、`underpowered_draws`、`certificates_issued`、`mechanisms_established`、`mechanisms_refuted`、`mechanism_patches`、`planted_mechanism_recovered`、`llm_vs_data_kendall_tau`、`shuffled_env_false_pass`、`tournament_tokens`。
- `discovery:` 配置中新增 `tournament: {enabled: false, elo_k0: 32, max_rounds: 3, max_rivals: 2}`。

### 2. 测试
- 植入机制：合成数据中 X→Y 为真因果，另有一个混杂对手。真机制应胜出，混杂机制应败并生成证书。
- 打乱环境标签时 ICP 不通过率 ≥0.9（20 个种子）。
- Elo 与 K 公式的数值测试；数据预算账本在重复使用切片时抛异常。
- 三个固定对手每场都在池中。
- 被否证的机制出现在其他分支的 `get_foreign_insights` negatives 中。
- `fe report` 的每个数字都与 manifest 中的数值相等。
- mechanism 层反思的解析测试。
- 最终 `pytest -q` 通过数 ≥ 基线，0 失败。

### 3. 技能
- **更新** `skill/fe-knowledge-discovery/SKILL.md`：增加机理/锦标赛章节，包含命令、证书检查和故障处理（功效不足、数据预算耗尽）。
- **新增** `skill/fe-report-generation/SKILL.md`：
  - 命令：`fe report … --json` 与 `--md`
  - 成功断言：报告中的每个数字都能在 manifest 中找到同名字段且相等
  - 禁止手写数字
- **更新** `skill/fe-evolve-manager/SKILL.md`：新增事件和字段说明。
- 每个技能都要有六节：何时使用、输入、精确命令、成功检查、故障处理、禁止操作。PR 描述中列出新增/更新的技能。

### 4. PR
开 draft PR，标题为 `feat: 机理层数据裁决锦标赛 + 否证证书 + 报告 (KD2)`。描述中写明基线/最终测试数、技能列表和已知限制（原理层未实现、没有远端 holdout）。不要合并。
