# PR-KD：新知识发现（只做后端功能）方案

> 编写：2026-09-28（UTC+8）。依据：
> - `houchenfeng/FaultEvolve-ResearchAssistant`（下称 RA）树 864b11d。已读：README、`docs/discovery_plan_v2.md`、`docs/design/{architecture,backend-api,dev-plan,frontend,skills}.md`。**未读**：`docs/项目说明书_v1.1.md/.docx`（59KB）。
> - `houchenfeng/Self-evolution-optimization-agnet`（下称 FE）：main = `b59c39e`（已核实，截至 2026-09-28 仍是最新提交）；PR #3 `cursor/knowledge-injection-c879`，head `4114286`，**仍为 open draft、未合并**（已核实）。
>
> 标注约定：【已核实】= 本次读代码或文档确认；【推算】= 由已核实事实推出；【未核实】= 来自 RA 文档或假设，本次没有独立验证。
>
> 范围规则（用户指定）：**只实现后端功能，不做任何前端/UI**。不改仓库，不改服务器，不启动 cloud agent。

---

## 0. 结论速览

1. RA 里的"新知识发现"指**三层可证伪知识**：现象层 → 机理层 → 原理层【已核实，discovery_plan_v2】。
   - 进化树里得分高的程序被翻译成可检验的 **Claim**（现象）。
   - Claim 在本地数据上经过分组 bootstrap CI、时间一致性、FDR、阴/阳性对照、新颖性检查，被分级为 确认/修正/发现/已否证。
   - 成立的现象再进入**机制竞争**：数据裁决锦标赛、e 值、ICP 不变性、否证证书。
   - 原理层只在 ≥2 个成立机制同构时才触发。
2. RA 目前**没有任何代码**（`src/` 不存在，README 写明"设计阶段，代码待开发"）【已核实】。所以这里不是"移植代码"，而是**按 RA 设计在 FE 引擎里实现**。
3. 前后端划分：
   - React 前端、Navivisor 复用、NestJS Web 服务（REST/Socket.IO、fe.db 轮询、回放）都是为 UI 服务的，**全部剔除**。
   - 保留的只有引擎侧功能，以及机器可读的产物（JSON/JSONL + CLI `--json`），供将来任何服务消费。
4. 建议拆成 **2 个 PR**：
   - **PR-KD1**：现象层发现 + 发现卡回灌。这是对进化有直接收益的闭环。
   - **PR-KD2**：机理层 + 数据裁决锦标赛 + 否证证书 + 报告生成。
   - 两个 PR 都**硬依赖 PR #3**（知识卡、card_stats、retriever），必须等 PR #3 合入 main 后再启动。
5. 本次发现一个前置 bug【已核实，main 与 PR #3 都有】：`_apply_reflection` 的分支顺序导致**正向提升几乎进不了 `_reflect_positive`**。它会被 `layer=="design"` 截到 `_reflect_design_issue`，被 `layer=="hypothesis"` 截到 `_reflect_hypothesis_refuted`。PR #3 上后者还会把采纳的卡标为 refuted。发现流程依赖正向 insight，所以 KD1 必须先修这个 bug。

---

## 1. RA 设计摘要（"新知识发现"是什么）

### 1.1 输入
- **进化树**（fe.db：node/insight/event/card_stats）以及 top-K 程序代码、父子 diff、反思结果【已核实，字段见 FE store.py】。
- **51 张文献卡**。RA 的 `knowledge/cards.jsonl` 与 PR #3 的是同一 blob【已核实】。它们是新颖性判定的 K0 基准。
- **数据**。RA 设计使用 Backblaze Iceberg 长面板（`s3://drivestats-iceberg/drivestats`，DuckDB，744,525,690 行 × 197 列）【未核实，RA 自称"已核实 2026-09-28"】。FE 仓库内现有的是 `benchmark/hdd_mvp/data/public/{train_history.csv.gz, train_labels.csv, val_history.csv.gz, val_index.csv}` 和 `data/eval_only/val_labels.csv`【已核实】：
  - train cutoff 2024-07-14~09-23，31,093 样本，其中 1,104 正例
  - val cutoff 2024-10-14~12-24，30,754 样本，其中 756 正例
  - test 为 2025Q1，不在仓库内（holdout）
- 云端 LLM：Qwen 负责生成 claim/机制/检验。Jev 可选，做相关性/蕴含检查。

### 1.2 流水线（RA 原设计）
| 层 | 阶段 | 产物 |
|---|---|---|
| 现象 | translate_claim：程序/insight → Claim C=⟨条件 S，X 代码，结果 Y，方向/幅度 θ±CI，适用范围 R，否证条件⟩ → 预注册 sha256 → 按盘 bootstrap CI → 时间外推方向一致 → BH/e-BH → 打乱标签阴性对照 → 3 档植入信号阳性对照 → 新颖性（语义：盲推导 + Jev 蕴含；功能：相对 F(K0) 的增量、max\|ρ\|/R² 阈值）→ 分级 | 现象卡（确认/修正/发现/已否证），血统 node→card→DOI |
| 机理 | propose_rivals（≥1 个对手，必须含非因果：混杂 M_confound、厂商计数伪迹 M_artifact、删失 M_censor〔Backblaze 在 187>0 时换盘〕、M_other）→ derive_tests（只保留两机制预测符号相反的检验，按 EIG 排序）→ 瑞士制配对 → 预注册预测矩阵 → 只在确认切片上运行 → e 值裁决 → Elo（只用于排赛程）→ 败者 revise_mechanism（算补丁，必须在未用过的数据上重检） | 机制卡（成立/未定/已否证）、否证证书、锦标赛结果 |
| 原理 | ≥2 个成立机制同构时 unify → 至少 1 条预注册的新预测，只在远端 holdout 或 SmartMem 上检验一次 → MDL、补丁数 | 理论卡 |

- **否证证书**：`{mechanism_id, rival_id, test_id, test_type, env/slice, stat+CI, e_value, prereg_hash, date}`【已核实，RA 文档】。
- **最终判定**：E=∏e ≥ 1/α、**且**通过 ICP、**且**经 e-BH 后仍显著。Elo 不参与判定【已核实，RA 文档】。
- **价值函数**只用于选择：V = 超过 δ 的 ROS 增益 + λ1·log E + λ2·贝叶斯惊讶（只计跨 0.5 的信念翻转）+ λ3·不变环境数。**报告分数永远是真实 ROS 或预注册检验结果**【已核实，RA 文档】。这一点与 FE 的 AGENTS.md"LLM/Jev 输出不得成为节点分数"一致。
- **数据纪律**：每个切片/检验在同一比赛族内只用一次；远端 holdout 只开一次。
- **自检**：植入机制、LLM 裁判与数据裁判的 Kendall τ、打乱环境标签。
- **云/本地分工**：云端只生成文本；本地负责评估、锦标赛、ICP、e 值，只回传聚合量【已核实，RA 文档】。

### 1.3 数据结构（RA 设计 → FE 落地名）
- 节点类型：Program（已有）、Claim、Mechanism、Test、Theory。
- 模型：Claim、Mechanism、Prediction、TestResult、Theory、FalsificationCertificate。
- `HypothesisStatus` 新增 CORROBORATED、UNDETERMINED。
- 表：claim、mechanism、test_result、theory、certificate、match。
- 产物：`phenomena.json`、`mechanisms.json`、`theories.json`、`certificates.json`、`tournament_results.json`、`preregistration.json`（skills.md 中 `fe-knowledge-discovery` 的输出清单）【已核实】。
- 报告汇总字段：phenomenaCount、confirmedCount、discoveredCount、refutedCount、negativeControlFalsePositives、plantedSignalRecoveryRate（backend-api.md）【已核实】。FE 中改用 snake_case。

### 1.4 RA 文档与 FE 实际代码的不一致（实现时**不要照抄**）【已核实】
- backend-api.md 把 F1_p10 写成"Precision=10% 时的 F1"，实际是 bootstrap F1 的第 10 百分位；R@FAR 写成 FAR=0.1%，实际是 0.2%。
- backend-api.md 的 DDL 和字段名不是 FE `store.py` 的真实 schema。以 FE 代码为准。
- frontend.md 的节点 `operator` 枚举包含 `inject`/`discover`，状态包含 `pending|evaluated|failed`，与 FE 的 `OperatorType`/`NodeStatus` 不完全一致，以 FE 为准。前端本身不做。

---

## 2. 前后端划分（剔除前端）

| RA 组件 | 归类 | 处理 |
|---|---|---|
| React 页面（演化树、分数曲线、三层知识页、锦标赛对阵图、Elo 图、文献页、Skills 页、报告预览、设置、科研科普四模块）、Zustand/TanStack、Socket.IO 客户端、Navivisor 组件复用（AGPL） | 前端 | **剔除** |
| NestJS 11 + Fastify（Evolution/Replay/Skills/SSH/File/Knowledge/Tournament 服务、REST、Socket.IO 推送、fe.db 轮询、回放控制） | 为 UI 供数的 Web 服务 | **剔除/延后**（见未决问题 1）。以"机器可读产物 + CLI `--json`"替代 |
| dev-plan 的 MVP（回放、树可视化） | 前端 | **剔除** |
| discovery_plan_v2 的 Claim/Mechanism/Test/Theory、统计检验、锦标赛、否证证书、价值函数、数据切分纪律 | 后端功能 | **保留**，落到 FE 引擎 |
| skills.md：`fe-knowledge-discovery`、`fe-data-checkup`、`fe-report-generation`、更新 `fe-knowledge-injection` | 后端技能 | **保留**。§6"Skills 前端展示"剔除 |
| SCHEMA_NOTES 建议：修 `repair_count`、`tree.json` 加 adopted_cards、事件复合索引 | 后端 | 保留：修 bug、加字段；索引可选 |
| 可选 HTTP sidecar | 服务 | 延后 |

---

## 3. FE 现状与钩子（逐条核实）

| 钩子 | main b59c39e | PR #3 4114286 | 用途 |
|---|---|---|---|
| `EvolutionEngine._run_one_iteration` | 有；算子固定为 `OperatorType.REFINE` | 有；已接入 `_retrieve_knowledge_cards`、`adopted_cards`、`update_card_stats(_invalid)`、`precheck` | 定期触发发现轮；DISCOVER 算子调度 |
| `_apply_reflection` 分支顺序 | `delta<-hyp or layer=="hypothesis"` → refuted；`delta<-design or layer=="design"` → design；最后才 `delta>design` → positive | 相同，并把 adopted_cards 传给 refuted | **前置 bug**：正向提升几乎进不了 `_reflect_positive`（LLM 只能输出 implementation/design/hypothesis） |
| `_reflect_positive` | 创建 `Insight(z=delta/noise)`，调用 `BranchMemoryManager.propagate_insight`，记录 `insight_extracted` 事件 | 相同 | 候选 claim 的主要来源；发现轮收割高 z insight |
| `_reflect_hypothesis_refuted` | 无卡片逻辑 | 调 `add_branch_refuted_card` + `increment_card_refuted_count` | 发现卡与文献卡同样受反证惩罚 |
| `_attempt_repair` | `repair_failed` 事件引用未定义的 `repair_count`（会 NameError） | 已改用 `tree.increment_repair_count`；是否仍有未定义引用**需实现者 grep 确认** | 顺手修 |
| `run_local_evolution` | 写死 `HDDAdapter`，无 `adapter` 参数；`add_llm_call(gen_metrics,"refine")` | 有 `task_dir`、`adapter` 参数；`_get_knowledge_dir()` = `task_dir / config.knowledge.dir` | 发现模块从 `task_spec.task_dir` 取数据；产物写 art_dir |
| `LayeredReflector._parse_reflection_json` | 把 layer 强制限定在 implementation/design/hypothesis | 相同 | KD2 新增 `mechanism` 层要改这里 |
| `get_foreign_insights` | 读 insight 表，取其他分支中 polarity<0 的作为 negatives，按 \|z\| 排序 | 相同 | KD2：被否证机制以 `[MECH]` 前缀、polarity=-1 的 insight 写入，**无需改接口**就会进入 negatives |
| `update_insight_reputation` | `pass` | `pass` | KD2 实现 Beta 更新 |
| `knowledge/loader.py` | 无 | `REQUIRED_FIELDS={id,title,category,claim,source_ids,tags}`；`VALID_CATEGORIES` 为 9 类；**多余字段不报错、解析时忽略**；`load_cards_from_dir` **只读 `cards.jsonl`** | KD1：发现卡须满足这个 schema；loader 需扩展以同时读取发现卡文件 |
| `store.card_stats` | 无 | 主键 `(experiment_id, card_id)`，字段 n/sum_delta/sum_sq/refuted_count/invalid_count；另有 `branch_offered_cards`、`branch_refuted_cards`、`node_adopted_cards` | 发现卡采纳/效果统计直接复用；**按实验隔离**，跨实验先验需另做 |
| `TaskAdapter` | Protocol | `@runtime_checkable Protocol`，含 context_keywords/constraints/api_notes | 新增能力**不要加进 TaskAdapter**（会破坏 isinstance 检查），改为另立可选 Protocol |
| CLI | typer：`fe evolve local <task_dir> --mock -n N --json --runs-dir --artifacts-dir --env-file`、`fe doctor` | 相同 | 新增 `fe discover …`、`fe data checkup …` |
| 知识包位置 | 无 | `benchmark/hdd_mvp/knowledge/{cards.jsonl(51), sources.yaml, expert.md, README.md}` | 发现卡**不写进仓库文件**，写进 runs 目录 |
| 测试 | — | PR 描述称共 218 个，全部通过【已核实为 PR 描述；未在本机运行】 | 基线 |

---

## 4. PR-KD1：现象层发现 + 发现卡回灌

### 4.1 新增/修改文件
| 文件 | 内容 |
|---|---|
| `src/faultevolve/discovery/__init__.py` | 包入口 |
| `discovery/schemas.py` | pydantic 模型：`Claim`（id、experiment_id、origin_node_id、source∈{insight, discover_op, manual}、condition、feature_code、outcome、direction∈{+,-}、scope、falsifier、prereg_hash、status、grade）、`ClaimTestResult`（split、effect、ci_low、ci_high、p、e、n_pos、n_neg）、`ControlReport`、`Grade` 枚举（CONFIRMED/REVISED/DISCOVERED/REFUTED/UNDETERMINED）。单独建文件，不改 `EvaluationResult`（其 `extra="forbid"`） |
| `discovery/claims.py` | `translate_claim(parent, child, insight, llm)`：用 `chat_for_reasoning` 生成 JSON；`extract_claim_from_response(text)` 解析 `<claim>…</claim>` 块，格式错误返回 None；`preregister(claim)` 计算 canonical JSON 的 sha256 |
| `discovery/sandbox.py` | 在子进程中运行 claim 的特征代码：签名 `def feature(history: pd.DataFrame) -> pd.Series`，按样本键索引；复用 `codecheck` 的禁用 import 规则，禁止网络和文件 IO，设超时 |
| `discovery/stats.py` | 纯 numpy/pandas 实现：按组（盘序列号）bootstrap CI；单特征效应（默认 AUROC−0.5 与分位组失效率比，方向取符号）；p 值（组置换或 bootstrap）；p→e 校准 `e = κ·p^(κ−1)`（κ=0.5）；BH 与 e-BH；增量检验（在 K0 基线特征的 logistic 上加 X，看 ΔAUPRC 或 Δlog-lik 的 bootstrap CI）；max\|Spearman ρ\| |
| `discovery/controls.py` | 阴性对照：在机型分层内打乱标签后重跑同一检验；阳性对照：植入 `X_plant = f(label)+噪声`，3 档强度 |
| `discovery/novelty.py` | 功能新颖性：K0 基线特征库（由 51 张卡中常见的 SMART 原值、14 天差分、非零计数构成，代码写在 `discovery/baseline_features.py`），判据为 max\|ρ\| < `rho_max` 且增量 CI 下界 > 0；语义新颖性：reasoning LLM 盲判"是否被某卡 claim 蕴含，返回卡 id 或 none"；若 PR #4 的 Jev 已合入则可选调用，fail-open |
| `discovery/grading.py` | 分级规则表（§4.3） |
| `discovery/promotion.py` | Claim → 发现卡（§4.4），追加写入 `discovered_cards.jsonl`，按 claim 哈希去重 |
| `discovery/pipeline.py` | `DiscoveryRound.run(engine_ctx)`：收割 → 翻译 → 预注册 → 沙箱 → 探索切片检验 → 确认切片检验 → 时间方向检验 → FDR → 对照 → 新颖性 → 分级 → 晋升；只返回聚合量 |
| `discovery/splits.py` | 按序列号哈希切分：exploration 70%、confirmation 30%（固定盐）。时间方向检验默认用 **train 内部按 cutoff 前后两段**，不碰 val/test |
| `tasks/protocol.py` | 新增**独立的**可选 `@runtime_checkable class DiscoveryDataProvider(Protocol)`：`discovery_frames(task_spec) -> DiscoveryFrames(features_input: DataFrame, labels: Series, group: Series, time: Series, env: DataFrame)`。引擎用 `isinstance(adapter, DiscoveryDataProvider)` 判断；不满足时发 `discovery_skipped` 事件并继续跑 |
| `tasks/hdd_adapter.py` | 实现 `discovery_frames`：**只读 `data/public/train_*`**；不读 `eval_only/`，不读 test |
| `worker/runner.py` 的 `FakeAdapter` | 实现合成数据版 `discovery_frames`，含可控植入信号，供测试 |
| `knowledge/loader.py` | 新增 `load_all_cards(knowledge_dir, extra_paths)`：先读 `cards.jsonl`，再读 `discovered_cards.jsonl`（若存在）和 `discovery.extra_card_paths`；**id 冲突时拒绝后者**并返回 error；`load_cards_from_dir` 保持原签名和行为不变，以兼容现有测试 |
| `cloud/selection.py` 的 `get_era_knowledge_cards` | 改用 `load_all_cards`。发现卡与文献卡同池检索，同受 category 多样性约束和 branch-refuted 过滤 |
| `cloud/engine.py` | ① **修 `_apply_reflection` 路由**：先按 delta 符号分流，正向且 > design_threshold 时走 `_reflect_positive`，layer 只用来细分负向；② 每 `discovery.every_n_iterations` 次和 `run()` 结束前各调用一次 `DiscoveryRound`（受 `enabled` 和 token 份额上限约束）；③ 可选 DISCOVER 调度：每 `discover_op_every` 次迭代，把本次 REFINE 的指令附加为"同时输出 `<claim>`"，节点的 `operator` 仍记为 REFINE（避免改枚举引起迁移）；OperatorType.DISCOVER 留给 PR #7 的算子老虎机；④ 发现 LLM 调用记为 `add_llm_call(m, "discover")` 并写入 `llm_call` 表，purpose 为 `discover`；⑤ 若 `repair_count` 的未定义引用仍在，一并修复 |
| `cloud/store.py` | **只加新表**：`claim`、`claim_test`、`discovered_card(card_id, claim_id, experiment_id, grade, created_at)`；方法 `create_claim`/`update_claim`/`get_claims`/`create_claim_test`/`get_claim_tests`/`record_discovered_card`/`get_discovered_cards`。不改 node 表 |
| `common/metering.py` | `RunMetrics`/`RunSummary` 新增字段（§4.6） |
| `config.py` + `benchmark/hdd_mvp/evolve.yaml` | 新增 `discovery:` 段，**默认 `enabled: false`**（§4.5） |
| `cli.py` | `fe discover run <task_dir> --run-id EXP [--mock] [--max-claims N] [--runs-dir] [--artifacts-dir] [--json]`（离线对已有 run 执行一轮）；`fe discover report <task_dir> --run-id EXP --json`；`fe data checkup <task_dir> --json [--out DIR]` |
| `_write_artifacts` | art_dir 下写 `discovery/phenomena.json`、`discovery/preregistration.json`、`discovery/controls.json`、`discovery/discovered_cards.snapshot.jsonl`；`tree.json` 的节点导出增加 `adopted_cards`（SCHEMA_NOTES 建议，只加字段） |
| `skill/…` | 见 §7 |

### 4.2 候选来源（收割）
1. `insight` 表中 polarity=+1、z ≥ `min_insight_z` 的记录（依赖路由修复）。结合 `origin_node` 的父子 diff，由 translate_claim 生成 Claim。
2. top-K 有效节点（按真实 ROS）中尚未翻译过的节点。
3. DISCOVER 调度产生的 `<claim>` 块。

每轮最多处理 `max_claims_per_round` 个候选。在沙箱运行前先预注册（写入 sha256 和时间），之后不可修改。

### 4.3 分级规则（落地为表驱动）
| 等级 | 条件（全部满足） |
|---|---|
| 发现 DISCOVERED | 确认切片 CI 不跨 0 且方向与预注册一致；时间方向一致；BH q ≤ α **且** e-BH 通过；功能新颖（max\|ρ\|<rho_max 且增量 CI 下界>0）；语义上不被任何卡蕴含；本轮阴性对照假阳性率 ≤ `max_neg_control_fpr` |
| 确认 CONFIRMED | 统计条件同上，但被某张文献卡蕴含且方向一致 → 记录 `confirms: <card_id>` |
| 修正 REVISED | 被某卡蕴含，但方向相反，或条件/幅度显著不同 → 记录 `revises: <card_id>` |
| 已否证 REFUTED | 确认切片 CI 跨 0、方向翻转，或时间方向不一致 |
| 未定 UNDETERMINED | 其他情况（功效不足；记录最小可检测效应） |

本轮阴性对照不达标时，**整轮不晋升任何卡**，并发 `discovery_controls_failed` 事件。

### 4.4 发现卡如何生成并回灌
- **生成**：只有 DISCOVERED 和 REVISED 晋升为卡。CONFIRMED 不生成新卡，只在 `phenomena.json` 里记入"对原卡的数据佐证"。
  - `id`：`D-<exp_id>-<3位序号>`，与文献卡 id 空间不重叠，冲突时 loader 拒绝。
  - `title`、`claim`：取自 Claim。
  - `category`：必须在 `VALID_CATEGORIES` 内，默认 `feature_engineering`，由 LLM 在枚举内选择并校验。
  - `rationale`：效应、CI、q、e、样本量。
  - `applicability`：scope。
  - `expected_effect`：带 CI。
  - `risk`：必含"数据驱动发现，未经文献验证；仅在 <切片> 上检验"。
  - `source_ids`：`["run:<exp>", "node:<id>", "claim:<claim_id>"]`。
  - `tags`：包含 SMART 属性名，以便 `context_keywords` 命中。
  - `impl_hint`：特征代码，截断至约 600 字符。
  - `priority`：DISCOVERED=2，REVISED=3。
  - `evidence`：`"run"`。
  - 附加字段（loader 忽略，但保留在文件中作为血统）：`grade`、`prereg_hash`、`revises`、`created_at`。
- **存放**：`<runs_dir>/knowledge/discovered_cards.jsonl`，可用 `discovery.cards_path` 覆盖。**绝不写仓库内的 `cards.jsonl`**，测试中用 sha256 断言它不变。若要固化进仓库，由人工或 skill 通过单独 PR 合入。
- **回灌**：
  - 同一 run 内：晋升后引擎清空检索缓存（若有），下一次 `_retrieve_knowledge_cards` 即可检索到发现卡；由 `inject_same_run: true` 控制。
  - 跨 run：新实验的 `get_era_knowledge_cards` 通过 `load_all_cards` 自动加载。
  - 采纳沿用 PR #3 的 `<adopted_cards>` 与 `node_adopted_cards`/`card_stats`。反证沿用 `_reflect_hypothesis_refuted`。
- **跨实验先验（可选，KD1 做最小版）**：run 结束时把发现卡的 card_stats 汇总写入 `<runs_dir>/knowledge/card_priors.json`（n、mean_delta）。retriever 只把它当 Bayesian 先验，不覆盖本实验统计。若 PR #3 的 retriever 不便接入，则延到 KD2，并在 PR 描述中写明。

### 4.5 配置（`discovery:`，全部带默认值）
```yaml
discovery:
  enabled: false
  every_n_iterations: 5
  run_at_end: true
  max_claims_per_round: 3
  min_insight_z: 2.0
  top_k_programs: 3
  discover_op_every: 0          # 0 = 关闭 DISCOVER 调度
  alpha: 0.05
  bootstrap_b: 500
  e_calibrator_kappa: 0.5
  rho_max: 0.8
  planted_strengths: [0.2, 0.5, 1.0]   # 效应量（Cohen d），推算值，可调
  neg_control_repeats: 5
  max_neg_control_fpr: 0.10
  confirmation_fraction: 0.3
  split_salt: "fe-kd-2026"
  sandbox_timeout_s: 120
  max_token_share: 0.2          # 发现 token 占总 token 的上限；超过则跳过本轮
  inject_same_run: true
  cards_path: null              # 默认 <runs_dir>/knowledge/discovered_cards.jsonl
  extra_card_paths: []
  use_jev_entailment: false
```

### 4.6 指标（写入 `run_summary.json` 和 `run_finished` 事件）
| 字段 | 含义 |
|---|---|
| `discovery_tokens`、`discovery_token_share` | purpose=discover 的 prompt+completion token 数及其占比 |
| `discovery_rounds`、`discovery_rounds_skipped` | 实际执行/因预算或数据跳过的轮数 |
| `claims_proposed`、`claims_tested`、`claims_sandbox_failed` | 候选/完成检验/沙箱失败数 |
| `claims_confirmed`、`claims_revised`、`claims_discovered`、`claims_refuted`、`claims_undetermined` | 各等级数量 |
| `discovered_cards_count` | 本 run 新晋升卡数 |
| `discovered_cards_offered`、`discovered_cards_adopted`、`discovered_card_adoption_rate` | 发现卡被检索提供/被采纳次数，以及采纳率 |
| `discovered_card_mean_delta`、`literature_card_mean_delta` | 由 card_stats 计算的采纳后平均 Δscore，两者对比 |
| `score_delta_after_discovery` | 首张发现卡晋升后 best_score 的增量（相对晋升时刻的 best） |
| `neg_control_false_positives`、`neg_control_fpr` | 阴性对照假阳性数与假阳性率 |
| `planted_recovery_rate`（按强度分项） | 阳性对照回收率 |

事件：`discovery_round_started`、`claim_proposed`、`claim_tested`、`claim_graded`、`card_promoted`、`discovery_controls`、`discovery_skipped`、`discovery_round_finished`。

### 4.7 安全与纪律
- claim 代码是 LLM 生成的不可信代码：只在沙箱子进程运行，只接收传入的 DataFrame，禁止 IO/网络，设超时。
- 不读 `data/eval_only/`、test、远端 holdout；不改 `benchmark/hdd_mvp/{evaluator.py, init.py, problem.md, prompt.md}` 和 `data/`（AGENTS.md）。
- LLM/Jev 的输出只用于生成文本与判断蕴含，**绝不作为节点分数或检验统计量**。
- 发现流程出错时 fail-open：记录事件后继续进化，不中断 run。

---

## 5. PR-KD2：机理层 + 数据裁决锦标赛 + 否证证书 + 报告

| 文件 | 内容 |
|---|---|
| `discovery/mechanisms.py` | `Mechanism`（结构化因果图：节点/边/方向，以及预测表）；`propose_rivals(claim)`：LLM 生成 1–2 个对手，**固定加入** M_confound（机型/厂商混杂）、M_artifact（厂商计数语义伪迹）、M_censor（187>0 换盘导致的标签删失）、M_other；`revise_mechanism` 计为补丁并记补丁数 |
| `discovery/tests_catalog.py` | 检验类型：环境不变性（env 默认为机型族 × 季度；数据含 datacenter 列时才用，RA 称 vault 字段从 2023Q3 起才有【未核实】）、时间先后、剂量反应（分箱单调）、中介、异质性。`derive_tests(m_i, m_j)` 只保留两者预测符号相反的检验，按 EIG 近似排序 |
| `discovery/tournament.py` | 瑞士制按 Elo/EIG 配对 → 预注册预测矩阵 sha256 → 只在 confirmation 切片上运行（生成机制的 LLM 只看 schema）→ e ≥ 阈值判胜，否则判"功效不足"并记录最小可检测效应 → Elo：`R_i += K·(S−E_i)`，`K = K0·min(1, |log e| / log(1/α))`；信誉账本用截断 log BF ∈ [1/10, 10]；E=∏e；数据预算账本保证每个切片在每个比赛族内只用一次 |
| `discovery/icp.py` | 简化 ICP：在各环境内效应方向一致、且异质性检验不拒绝 |
| `discovery/certificates.py` | 否证证书模型与写入；`certificates.json` |
| `discovery/prereg.py` | 预注册登记簿（KD1 已有雏形，KD2 统一），`preregistration.json` |
| `cloud/insights.py` | `LayeredReflector` 允许 `mechanism` 层；实现 `update_insight_reputation`（Beta α/β） |
| `cloud/operators.py` | `OperatorContext.set_mechanism_context()`，在 `USER_MESSAGE_TEMPLATE` 中新增 `<mechanism_context>` 段（为空时不输出） |
| `cloud/engine.py` | `_apply_reflection` 路由 mechanism 层；锦标赛出结果后：**被否证的机制**写一条 `[MECH]` 前缀、polarity=-1 的 insight（`get_foreign_insights` 会自动把它作为 negatives 提供给其他分支）；**成立的机制**写入相关节点 `branch_memory.summary`，并晋升为 `category=pitfalls` 或 `feature_engineering` 的发现卡（`D-…-M…`），priority=1 |
| `cloud/store.py` | 新表 `mechanism`、`match`、`test_result`、`certificate`、`theory`（theory 只建表） |
| `common/schemas.py` | `HypothesisStatus` 新增 CORROBORATED、UNDETERMINED。只追加枚举值，确认旧数据仍可读 |
| `discovery/report.py` + `cli.py` | `fe report <task_dir> --run-id EXP --json/--md`：**数字只来自 manifest**（run_summary、phenomena、mechanisms、certificates 等 JSON） |
| 原理层 | **不在 KD2 验收范围**。只留接口 `unify()` 和 `theories.json`（空列表） |

KD2 指标：`mechanisms_proposed`、`matches_played`、`decisive_matches`、`underpowered_draws`、`certificates_issued`、`mechanisms_established`、`mechanisms_refuted`、`mechanism_patches`、`planted_mechanism_recovered`、`llm_vs_data_kendall_tau`、`shuffled_env_false_pass`、`tournament_tokens`。

---

## 6. 测试与验收

### 6.1 KD1 测试（全部离线，使用 MockLLM、FakeAdapter 和合成数据）
1. `test_discovery_stats.py`
   - 按组 bootstrap 的 CI 覆盖真值（合成数据，20 个种子，覆盖率 ≥ 0.85）
   - BH/e-BH 对已知向量的结果
   - p→e 校准单调且 E[e] ≤ 1 的数值检查
2. `test_claim_extraction.py`：`<claim>` 合法/缺字段/非 JSON 三种情况；预注册哈希稳定（字段顺序无关）。
3. `test_discovery_sandbox.py`：禁用 import/IO 被拒；超时被杀；返回长度不匹配被拒。
4. `test_discovery_controls.py`：打乱标签时假阳性率 ≤ 0.10（20 个种子）；强植入信号回收率 ≥ 0.9；零强度信号不被判为发现。
5. `test_novelty.py`：与 K0 特征相同的 X（ρ≈1）判为不新颖；独立植入特征判为新颖。
6. `test_grading.py`：规则表逐行参数化测试。
7. `test_card_promotion.py`
   - 生成的卡通过 `validate_card`
   - id 前缀为 `D-`
   - 仓库 `cards.jsonl` 的 sha256 不变
   - 去重
   - `load_all_cards` 同时加载两类卡；id 冲突时被拒并报错
8. `test_reflection_routing.py`
   - delta>design_threshold 且 layer=design/hypothesis 时走 `_reflect_positive` 并生成 insight
   - 负向路径的行为与原来相同
   - PR #3 场景下正向时**不**给采纳卡计 refuted
9. `test_engine_discovery.py`
   - FakeAdapter 带植入信号 + MockLLM 脚本化 claim，运行 N 次迭代后：产生发现卡、事件序列正确、run_summary 字段齐全
   - 发现卡在下一次检索中可被提供，采纳后写入 card_stats
10. `test_discovery_disabled.py`：默认配置下事件类型集合、run_summary 原有字段、LLM 调用次数与未启用时一致。
11. `test_cli_discover.py`：`fe discover run/report --json` 和 `fe data checkup --json` 的输出结构。

### 6.2 KD1 验收标准
- `pytest -q` 全部通过，且数量 ≥ 起始基线（启动时先记录基线数；PR #3 描述中为 218）。**不得删除或跳过已有测试**。若修复路由改变了某个已有测试的预期，必须在 PR 描述中逐条说明原因。
- `ruff`/格式检查：若仓库已配置则必须通过。
- 离线端到端：`fe evolve local benchmark/hdd_mvp --mock -n 6 --json` 在启用发现的临时 evolve.yaml（复制到临时 task 目录，不改仓库文件）下，生成 `discovery/phenomena.json`、`preregistration.json`、`controls.json`，且 run_summary 含 §4.6 全部字段。
- 发现流程抛异常时 run 仍然完成，并记录 `discovery_skipped` 或 `discovery_error` 事件。
- `grep -rn "eval_only" src/faultevolve/discovery` 无结果；HDD 的 `discovery_frames` 只读 `data/public/train_*`。
- 真实运行（用户手动，不进 CI）：Qwen、20 次迭代、`every_n_iterations: 5`，报告 §4.6 指标。**不设"发现 N 张卡"的数量目标**，因为效果未知【推算】。

### 6.3 KD2 测试与验收（要点）
- 植入机制：合成数据中 X→Y 真因果，外加一个混杂对手；锦标赛应判真机制胜，混杂败并生成证书。
- 打乱环境标签时 ICP 不通过率 ≥ 0.9。
- Elo 与 K 公式的数值测试；数据预算账本拒绝重复使用切片。
- 固定对手（M_confound/M_artifact/M_censor）每场都在池中。
- 被否证的机制出现在其他分支的 `get_foreign_insights` negatives 中。
- `fe report` 的数字与 manifest 逐一相等（解析后比对）。
- 已有测试全部通过。

---

## 7. 技能（全自动标准：Codex，无人值守）

每个 SKILL.md 必须包含：何时使用 / 输入 / 精确命令 / 成功检查（可执行断言）/ 故障处理 / 禁止操作。PR 描述中必须列出新增和更新的技能。

### 7.1 新增 `skill/fe-knowledge-discovery/SKILL.md`（KD1 建，KD2 扩充机理章节）
- **何时使用**：run 完成后，对已有实验离线挖掘可证伪的新现象；或需要在 evolve.yaml 中开启进化中发现时。
- **输入**
  - `.env`：`DASHSCOPE_API_KEY`（非 mock 时必须）；可选 Jev 密钥，变量名取自 `evolve.yaml` 的 `judge.api_key_env`
  - `FE_RUNS_DIR`（可选）
  - `evolve.yaml` 的 `discovery:` 段（§4.5）
  - 已有的 `--run-id`
- **命令**
  ```bash
  fe doctor --json --task-dir benchmark/hdd_mvp
  fe data checkup benchmark/hdd_mvp --json --out "$FE_RUNS_DIR/datacheck"
  fe discover run benchmark/hdd_mvp --run-id <EXP> --json [--mock] [--max-claims 3]
  fe discover report benchmark/hdd_mvp --run-id <EXP> --json > /tmp/kd_report.json
  ```
- **成功检查**
  ```python
  import json; r = json.load(open("/tmp/kd_report.json"))
  assert r["claims_tested"] >= 1
  assert r["neg_control_fpr"] <= 0.10
  assert all(c["id"].startswith("D-") for c in r["promoted_cards"])
  ```
  另外检查仓库 `cards.jsonl` 的 sha256 与运行前一致。
- **故障处理**
  - 401/403：密钥错误，停止并报告
  - 429/超时：按 PR #3 的重试策略（4s/8s/16s）；仍失败则跳过本轮
  - 沙箱失败率 > 50%：降低 `max_claims_per_round`，检查 claim prompt
  - `discovery_controls_failed`：不晋升，报告 fpr，改大 `bootstrap_b` 或 `neg_control_repeats` 后重跑
  - `discovery_skipped(no_provider)`：adapter 没有实现 `DiscoveryDataProvider`
  - token 份额超限：调低频率
- **禁止操作**
  - 手工编辑 `cards.jsonl` 或 `discovered_cards.jsonl`
  - 读取 `eval_only/`、test 或远端 holdout
  - 用 LLM 结论替代统计检验
  - 把发现数写进报告而不附 manifest 路径

### 7.2 新增 `skill/fe-data-checkup/SKILL.md`（KD1）
- **何时使用**：首次在某个任务目录上启用发现之前；或数据更新后。
- **命令**：`fe data checkup <task_dir> --json --out DIR`
- **输出**：`data_facts.json`/`.md`、`field_coverage.csv`、`silent_subset_stats.csv`（S0：失效当日 5/187/197/198 全为 0 或 NULL 的比例，**仅对本地 train 切片计算**；RA 文档称 Iceberg 上 HDD 2024Q3–2026Q2 为 21.2%【未核实】）。只输出聚合量，计数 < 10 的格子做抑制。
- **成功检查**：`data_facts.json` 含 `n_samples`、`n_positive`、`label_semantics`、`env_columns`、`min_detectable_effect`，且 `n_positive` 与 `meta.json` 中 train 的 1104 一致。
- **故障处理**：文件缺失时提示先运行 `prepare_data.py`（**不自动下载**）；列缺失时写入 coverage=0。
- **禁止操作**：读取 eval_only/test；输出逐盘明细。

### 7.3 更新 `skill/fe-knowledge-injection/SKILL.md`（KD1）
- 说明发现卡命名空间 `D-*`、存放位置、`load_all_cards` 的加载顺序和冲突规则
- 发现卡的 `evidence: run` 与附加血统字段
- 如何通过单独 PR 把发现卡固化进仓库（人工审核）
- 成功检查：`load_all_cards` 无 error，且文献卡仍为 51 张

### 7.4 更新 `skill/fe-evolve-manager/SKILL.md`（KD1）
- 说明 `discovery:` 配置、新事件类型、run_summary 新字段、路由修复带来的 insight 数变化
- 故障表中新增 discovery 相关行

### 7.5 新增 `skill/fe-report-generation/SKILL.md`（KD2）
- `fe report … --json/--md`
- 成功检查：报告中的每个数字都能在 manifest 中找到同名字段且相等
- 禁止操作：手写数字

---

## 8. 拆分建议与路线图位置

- **拆成 2 个 PR**。理由：
  - KD1 已有明确收益路径（新卡进入检索 → 采纳 → Δscore），并且修复了阻塞 insight 的路由 bug
  - KD2 的统计机制复杂、改动面大（insights/operators/schemas），与 KD1 同时提交会让评审和回滚都困难
  - 答辩在 2026-10-06（RA README：MVP 截止 10-05 20:00）【已核实，RA 文档】。KD1 可以在答辩前完成并展示"发现卡 + 对照 + 血统"，KD2 视时间而定
- **依赖**：PR #3 必须先合入 main。KD1 与 PR #4（Jev）文件冲突小，Jev 只作为可选蕴含检查。KD1 修改了 `selection.get_era_knowledge_cards` 的加载入口，PR #5 也会改 `selection.py`，需要约定合并顺序。
- **路线图 `/workspace/plans/改进路线图-调研.md` 调整建议**（本次**未改**该文件，待用户确认）：
  - 原第 6 位的"PR #9 知识发现闭环"拆为 **PR #9a = KD1**、**PR #9b = KD2**
  - 若答辩要展示发现能力：把 KD1 **提前到 PR #4 之后、PR #5 之前**（或与 PR #6 并行，两者改动文件基本不重叠）；KD2 放在 PR #8 之后
  - 若以 10-31 的竞赛 ROS 为先：保持 PR #4–#8 在前，KD1/KD2 后置
  - 路由修复（`_apply_reflection`）价值独立，建议无论如何尽早合入。可以并入 KD1，也可以作为一个极小的前置 PR
- **工作量**【未核实，agent 执行估计】：KD1 约 3–4 天，KD2 约 4–5 天。

---

## 9. 未决问题
1. NestJS Web 后端是否算"前端"而一并剔除？本方案按"为 UI 供数 → 剔除/延后"处理，只提供 JSON 产物和 CLI。
2. RA 设计依赖的 Backblaze Iceberg 长面板、按序列号留出的确认切片、远端 holdout（2025Q2–2026Q2）放在哪台机器？服务器能否联网？KD1 默认只用仓库内的 train 切片（探索/确认按序列号切分，时间方向用 train 内前后两段），不下载任何数据。是否需要在后续 PR 中加入 DuckDB/Iceberg 数据准备脚本？
3. 时间方向检验是否允许使用 val（`eval_only/val_labels.csv`，仅用于聚合方向）？默认**不允许**。
4. 发现卡在**同一 run 内**立即回灌（默认 `inject_same_run: true`），还是只跨 run 生效？
5. 卡 id 命名空间 `D-<exp>-<nnn>` 以及发现卡存放在 `<runs_dir>/knowledge/` 是否可以接受？是否要固化进仓库？
6. 是否把 KD1 提前到 PR #5–#8 之前（答辩 10-06 与竞赛 10-31 的优先级取舍）？
7. `_apply_reflection` 路由修复会改变 insight 和 refuted 的统计，可能影响 PR #3 的真实运行对比口径。是单独做前置 PR，还是并入 KD1？
8. `docs/项目说明书_v1.1.md` 未读，其中可能有额外的后端细节。
