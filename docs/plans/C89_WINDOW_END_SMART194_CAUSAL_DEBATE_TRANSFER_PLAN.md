# 窗口末 `smart_194_normalized`：因果审讯、机制对局、跨集复验

日期：2026-10-05。性质：**仅规划**。本文件给后续编码代理（composer-2.5）一次做完，不向用户追问。
本轮不改统计门、不改 `hdd_v3.jsonl`、不把该声明升成 DISCOVERED、不读 holdout/test。

锁定声明（一字不改）：On HDD public discovery data, window-end `smart_194_normalized` has a confirmation-set repeatable positive incremental signal for short-term failure (effect≈0.03, CI excludes 0); mechanistically interpretable as near-horizon vendor-normalized thermal/health level; passed explore increment, confirm tests, temporal & controls; e-BH failed → CONFIRMED not DISCOVERED.

证据运行（用户给定，本仓库未打开 NAS 产物，**不得用本文件数字冒充该次漏斗**）：HEAD `b463c5e`（已核实等于当前 `main`：`feat(discovery): opt-in KD relaxed track (R1 + R3) (#57)`），产物 `/home/hcf/nas_hcf_data/faultevolve/runs/kd_relaxed_20261005/v3_full/`，因子 `HDD3_F10`，声明 `C-89f4bdd1-0010`。

标注：【已核实】读本仓库代码；【用户给定】证据路径与锁定声明；【待从产物抄录】数字只能从漏斗/phenomena 原样抄，禁止编造。

---

## 0. 结论（先看这里）

1. **这是关联增量，不是干预因果。** 仓库没有 do-calculus、没有工具变量、没有随机化。已有「因果味」的模块是 KD2：固定对手预测表 + 切片上的符号检验 + ICP 环境不变性。它们最多否证部分故事，不能证明「温度导致故障」。
2. **现成多主体对局 = KD2 锦标赛，不是聊天辩论。** LLM 只生成对手机制的 `predictions`；胜负由 `tests_catalog.run_test` + Elo（展示）+ `E` 乘积与 `ebh_reject`（判定）决定。`fe discover factors` **从不**打开锦标赛，也**从不**调用 `EvolutionEngine._maybe_run_tournament`。【已核实】
3. **「新数据集」在竞赛约束下的合法含义（按优先级）：**
   - **P0 主复验**：Backblaze 变体任务的**公开 train**（`benchmark/backblaze_hdd`，需 `prepare_data.py`；SMART 194 同构）。
   - **P1 弱复验**：HDD MVP **公开 train 内**按 cutoff 日历后段（与 KD1 确认哈希切片不同；仍同季度舰队）。
   - **P2  evol 评分集（可选、事后、单独标签）**：`data/public/val_history.csv.gz` + evaluator 才读的 `eval_only/val_labels.csv`。只允许在声明与门**全部冻结之后**做一次转移报告，不得回头改分级、不得当发现目标。**不是**独立科学确认。
   - **禁止**：`holdout*`、`--split test`、gitcode、把 SmartMem / 阿里 SSD 硬映射成 SMART 194。
4. **成功不要求「机制成立」。** 小效应 + 默认 `n_slices=4`（上限 16）下，KD2 大概率 `undetermined` / `underpowered_draws`。如实报告即可。不得为凑成立而降 α 或抬 `n_slices` 上限。
5. **编码 PR 与真跑拆开。** 本文件先落地为文档 PR。实现 PR 只加冻结声明的审讯/对局/转移管道与离线测试。真跑只在有公开 history 的机器上执行，并把实测写入独立结果说明（不回写本计划里的数字）。

---

## 1. 声明是什么、代码里对应什么【已核实】

### 1.1 因子

`src/faultevolve/discovery/factor_library/hdd_v3.jsonl` 中 `HDD3_F10`：

- `family`: `thermal`
- `title`: `smart_194_normalized last value`
- `inputs`: `["smart_194_normalized"]`
- `direction`: `auto`
- `lane`: `confirm`，`confirm_eligible`: true
- `code`: 按 `serial_number` 分组，取该列窗口最后一行的 float；全 NaN 则 NaN
- `falsifier`: `effect sign flips on held-out calendar half`
- `window_days`: 14
- `outcome`: `disk_failure`

禁止改这一行库条目。转移与对局必须**原样**执行该 `feature()`。

### 1.2 分级语义（放宽轨）

`grading.py`：

- 默认 `--fdr-mode bh_ebh`：BH 与 e-BH 都要过才可能 CONFIRMED/DISCOVERED。
- 放宽轨 `--fdr-mode bh_for_confirm_ebh_for_discover`：e-BH 失败仍可因蕴含 `same` 得到 **CONFIRMED**；**DISCOVERED 仍要求 e-BH**。
- CLI：`--track-label relaxed` 只写审计标签，不改门。

锁定声明的「e-BH failed → CONFIRMED not DISCOVERED」与放宽轨一致。实现时**不要**把这次 CONFIRMED 说成新发现，也不要在用户叙述里写成「某张知识卡再确认」——谈的是这条 SMART 声明本身。蕴含命中的卡片 id【待从产物抄录】，抄进结果即可，不作为叙事标题。

### 1.3 效应口径

发现层效应是 `signed_effect` = AUROC(feature, label) − 0.5，增量是相对 K0 基线矩阵的 `incremental_auroc`，**不是** evaluator ROS。锁定句中的 effect≈0.03 视为用户锁定的量级描述；漏斗里的精确 CI、n、正例数必须从产物抄录。

历史对照（**另一次**严格轨 KD1-H，HEAD `418510b`，不是本次 relaxed 产物；仅说明量级曾被记录过，不得当作本次数字）：确认效应曾记录为约 +0.03 且 CI 下界为正，当时因 e-BH 判 UNDETERMINED。本次 relaxed 必须以 `kd_relaxed_20261005/v3_full` 为准。

### 1.4 发现帧（转移必须对齐）

`HDDAdapter.discovery_frames`：

- 只读 `data/public/train_labels.csv` 与 `train_history.csv.gz`（`HDD_BENCH_DATA_ROOT` 时根为 `$HDD_BENCH_DATA_ROOT/public`）。
- history 截到 cutoff 且每盘 `tail(history_days)`。
- `labels` 交给沙箱的只有 `serial_number,label`。
- `env_frame`：`env = model_family + "|" + cutoff 年月`，`conf = model_family`，`time = cutoff_date`，`censor =` cutoff 前 `smart_187_raw` 是否曾 >0。

`BackblazeAdapter` 继承同一 `discovery_frames`。SmartMem / 阿里 SSD **没有**该列，转移 CLI 必须因缺列失败而不是编造映射。

---

## 2. 仓库能力地图（审讯/对局/跨集）

| 能力 | 位置 | 现状 | 对本声明 |
|---|---|---|---|
| 原子因子漏斗 | `cli.py` `discover factors`，`discovery/factors.py` | 有；relaxed 开关已合入 `b463c5e` | 来源运行；本计划不再重跑全库 |
| 蕴含 | `novelty.judge_entailment` | LLM，`purpose=entailment`，不打分 | 只解释 CONFIRMED vs DISCOVERED |
| 阴性/种植对照 | `discovery/controls.py` | 有 | 转移时对**冻结** x 再跑阴性对照 |
| 确认哈希切分 | `splits.assign_split`，盐 `DiscoveryConfig.split_salt` 默认 `fe-kd-2026`，比例默认 0.3，KD1-H 真跑用过 `--confirmation-fraction 0.5` | 有 | 对局切片必须来自**原确认掩码**，禁止把探索集并进 KD2 |
| 日历折半 | `splits.temporal_halves` / `label_times` | 有 | 声明的 falsifier；KD2 `temporal` 检验共用 |
| 机制对手 | `mechanisms.py` | claim + confound/artifact/censor/other + ≤2 llm_rival | 固定对手已覆盖混杂/测量伪迹/删失 |
| 机制检验 | `tests_catalog.py` | env_invariance, heterogeneity, temporal, dose_response, mediation | 见 §3 |
| ICP | `icp.py` | 环境信息门、符号一致性、异质性置换 | 机制 `established` 的硬条件之一 |
| 锦标赛 | `tournament.py`，`engine._maybe_run_tournament` | 仅 `evolve` 且 `discovery.tournament.enabled` 且 extras.kd2 | **缺口**：factors CLI 不接线 |
| 证书 | `certificates.py`，`mech_promotion.py` | 有 | 仅当 established；本声明预期多半发不出 |
| 跨任务数据 | `backblaze_hdd` 同构；`smartmem`/`ssd_alibaba` stub | Backblaze 需下载+prepare | P0 转移目标 |
| 公开 val history | `data_status` 要求 `val_history.csv.gz`；标签在 `eval_only/val_labels.csv` | 本工作区未跟踪 history 大文件 | P2 可选，见 §4 |
| 进化用 train 内 late cutoff | `hdd_adapter` 错例分析 dev 切分 | 有 | 可作 P1 日历转移的参照实现 |

**没有的东西（不要假装已有）：** Pearl 识别、DID、断点回归、多 LLM 自由辩论记分、跨数据集自动评测 CLI、`fe discover debate`。

---

## 3. 因果推理：诚实 DAG 与可执行检验

### 3.1 必须写进报告的诚实句

- 观测关联：窗口末厂商归一化 194 与 1–7 天故障标签。
- 已控：相对 K0 列的增量 AUROC、厂商族分层残余（mediation 检验用 `conf=model_family`）、日历半段符号、置换阴性对照。
- **未控/不可控：** 机架与季节（部分进入 `env` 的月份）、负载、盘龄、固件、换盘策略、归一化曲线在型号间的不可比。
- 因此：**即使全部检验支持 claim 机制，结论仍是「与近地平线热/健康读数相容的稳健关联」，不是「降低温度可降低故障」。**

### 3.2 预注册机制（对局前冻结，禁止看完数据再改预测表）

| id | 角色 | 故事 | 对 `TEST_TYPES` 的预测（+1=stat>0） |
|---|---|---|---|
| C | claim | 近地平线厂商归一化热/健康水平携带短时故障信息 | 沿用 `_PREDICTION_TEMPLATES["claim"]`：env_invariance+1, temporal+1, dose_response+1, mediation+1, heterogeneity−1 |
| R_conf | confound | 型号/月份同时驱动 194 与故障 | 模板 confound：env_invariance−1, heterogeneity+1, … |
| R_art | artifact | 归一化刻度跨型号不可比，效应是测量伪迹 | 模板 artifact：dose_response−1, env_invariance−1 |
| R_cen | censor | 换盘/删失（187 代理）制造标签 | 模板 censor：temporal−1 |
| R_oth | other | 占位全 −1 | 仅当抽到 |

LLM 审讯（§4）可以**补充** ≤2 个 `llm_rival`，但不得修改上表。修订机制走既有 `revise_mechanism`（最多 `max_patches=1`），新 id 重新预注册。

### 3.3 检验与故事的对应（实现时直接调现函数）

不要新发明统计量。调用：

- `run_test(...)` → `(stat, ci_low, ci_high, p_pos, p_null)`
- `icp_check(x, y, env, direction, alpha, bootstrap_b, icp_gate_p, min_env_pos, rng)`

解读（报告用，不改代码阈值）：

- **dose_response**：分位箱失败率与箱序 Spearman。支持「水平越高（或越低，视冻结方向）风险单调」。
- **mediation**：按 `conf`（型号族）层内加权 `signed_effect`。仍显著 → 不是「纯型号主效应能解释完毕」。
- **env_invariance vs heterogeneity**：层内均值 vs 层间差。claim 预测异质性不大；confound/artifact 预测异质性。
- **temporal**：后半 − 前半（乘方向）。claim 预测不衰减；censor 预测时间符号相反。
- **ICP**：过关是「环境可信息且符号不翻且异质性置换不显著」，**不是**因果识别定理的 ICP 原文全套。

### 3.4 额外、仍属关联的对比（编码 PR 内、预注册）

在**同一批冻结样本**上评估三个标量，只报告，不参与原声明再分级：

1. `smart_194_normalized` 最后值（本声明）。
2. `smart_194_raw` 最后值（库中 HDD3 热家族近邻形状；**不要**把 HDD3_F08/F09 整条重新发现）。
3. 窗口内 `smart_194_normalized` 的 max−min 或不稳定性（若缺列则跳过并记 missing）。

规则：若 (2) 增量 CI 覆盖 (1) 且符号相同，报告「归一化相对 raw 的增量未分离」；不得据此改写锁定声明。

方向：原因子 `direction=auto`，以**原运行冻结的符号**为准（从 phenomena/payload 抄 `direction`），转移与对局禁止重选符号。

---

## 4. 多主体审讯 / 对局：最小管道

### 4.1 两层，不要混

**层 A — 审讯（LLM，零分）。** 三个角色、三次独立 `chat_for_reasoning`，`purpose="mechanism"`：

1. `proponent`：用锁定声明 + `schema_note` + 因子代码（≤600 字）写出因果故事，并输出 claim 预测表（必须与 §3.2 C 一致，否则丢弃该次输出、回退模板）。
2. `confounder`：只攻击混杂/伪迹/删失，输出 1 个 `llm_rival` 的 title/edges/predictions。
3. `critic`：列出该声明**不能**主张的因果句子；输出另一 `llm_rival` 或空。

产物：`<artifacts>/discovery/interrogation.jsonl`（角色、prompt 哈希、回复尾 800 字、解析后的 predictions）。解析失败则该角色空，固定对手仍在。

**层 B — 数据裁决（唯一记分）。** 复用 `Tournament.run_family`。输入 `KD2Handoff`：只有这一条 claim；`feature_map[claim_id]` 为沙箱 Series 对齐 labels；`confirm_mask` 用**原盐与原 confirmation_fraction** 重建（从 `data_audit.json` 抄；缺则从漏斗/CLI 记录抄；再缺则本管道 exit 2，禁止猜）。

### 4.2 接线缺口（实现必须补）

今日：`discover_factors` 构造 `DiscoveryRound`，`run_factor_discovery` 结束只 `write_artifacts`，**不**看 `result.extras["kd2"]`，且 `config.discovery.tournament.enabled` 默认 false。

实现（最小）：

1. 新子命令 **`fe discover replay-claim`**（名称固定，避免与 `discover run` 收割 insight 混淆）：
   - 参数：`--run-id`、`--claim-id C-89f4bdd1-0010`、`--factor-id HDD3_F10`、`--library hdd_v3.jsonl`、`--artifacts-dir`、`--runs-dir`（**副本**）、`--enable-tournament`、`--interrogate`、`--transfer-task-dir`（可选）、`--transfer-frame {public_train,train_late,backblaze_public_train}`、`--mock`、`--env-file`、`--json`。
   - 禁止参数：`--split test`、任何 holdout 路径、改 alpha/e-BH/κ。
2. 当 `--enable-tournament`：在**本进程**设置 `config.discovery.tournament.enabled=True`（仅该 CLI，不改 yaml 默认），构造 `Tournament`，`run_family`，写 `mechanisms.json` / `tournament_results.json` / `certificates.json`。
3. `n_slices`：用配置默认 4；允许 CLI `--n-slices` 在 **2..16** 内覆盖（pydantic 已限制）。真跑建议 16。禁止改 `le=16`。
4. 切片预算用尽 → 既有 `tournament_no_fresh_slice`；报告 `min_detectable_effect`，**不要**降 α。
5. Elo 不写入成功标准。

### 4.3 审讯 prompt 硬约束

- 标记：`KD_INTERROGATE_PROPONENT` / `_CONFOUNDER` / `_CRITIC`。
- 不提供标签、不提供效应数字、不提供漏斗（防 LLM 迎合）。
- 只给：title、condition、outcome、scope、feature 代码、schema_note 前 500 字。
- 响应必须含 JSON；解析走现有 `_normalize_predictions`。
- 任务无关：新逻辑若放 `discovery/` 不得出现 `smart|serial|hdd|vendor`（`test_discovery_task_agnostic.py`）。HDD 列名只出现在 `tasks/hdd_adapter.py`、CLI 帮助、本计划、skill、测试 fixtures。

### 4.4 对局成功标准（真跑）

全部满足才算「管道跑完」，**不是**「机制成立」：

- 退出码 0；`interrogation.jsonl` 至少 3 行（三角色，解析失败也记）。
- `mechanisms_proposed >= 5`（1 claim + 4 fixed）。
- `matches_played >= 1` 或明确 `tournament_skipped` 且 reason ∈ {`no_env`,`token_share`,`max_rounds`,`no_fresh_slice`}。
- `mechanisms_established + mechanisms_refuted + undetermined == mechanisms_proposed`（undetermined 可含未终裁）。
- `cards.jsonl` sha256 不变；不写 `D-*-M*` 除非 `status=established`（本声明以 undetermined 为预期主结局）。
- 不得把 LLM 文本当作机制成立。

---

## 5. 「新数据集」定义与转移设计

### 5.1 候选矩阵（实现按此拒绝非法目标）

| 代号 | 数据 | 标签来源 | 与发现样本关系 | 允许？ | 结论强度 |
|---|---|---|---|---|---|
| T0 | 原公开 train 确认单元 | 原 `train_labels` | 选择后确认，**已用过** | 只用于对局，不算新集 | — |
| T1 `train_late` | 同一 `train_*`，cutoff 日期 ≥ 该盘训练集日期中位 | `train_labels` | 同舰队、部分单元可能进过探索 | **允许**弱转移 | 弱 |
| T2 `backblaze_public_train` | `benchmark/backblaze_hdd` 的 public train（默认文档：训练季 2024Q4，与 MVP 的 2024Q3 train **不同季**） | 该任务 `train_labels` | 同构 SMART，独立 prepare | **主允许** | 中（仍非干预） |
| T3 val | `public/val_history.csv.gz` + `eval_only/val_labels.csv` | 进化评分标签 | 伐谋对比用 val | **仅冻结后可选**；CLI 默认关，需 `--allow-val-transfer` 且日志打印警告 | 污染进化评分集，报告必须标明 |
| T4 test/holdout | holdout | 私有裁决 | 泄漏 | **禁止** | — |
| T5 SmartMem | mcelog/DIMM | 内存故障 | 无 194 | **禁止当本声明复验**；单测：缺列 → 结构化错误 | — |
| T6 阿里 SSD | stub `n_*/r_*` | SSD | 无 SMART 194 契约 | **禁止硬映射** | — |
| T7 gitcode | 外源 | — | 竞赛禁止 | **禁止** | — |

本工作区当前**没有** `train_history.csv.gz` / `val_history.csv.gz`（仅有部分 labels/index/meta）。真跑必须在 `HDD_BENCH_DATA_ROOT` 指向完整 public 的机器，或先 `prepare_data.py`。编码 PR 只用 `tests/helpers` 合成盘。

### 5.2 转移统计（冻结 x，禁止重跑漏斗）

对每个允许的目标帧：

1. 用同一 `feature()` 沙箱得到 x。
2. `test_feature(x, y, groups, frozen_direction, cfg, rng)` → 效应、CI、p。
3. `incremental_auroc` vs 该帧上现算的 K0 `build_baseline_features`（列集以该 history 实际存在的 `HDD_K0_COLUMNS` 为准；缺列跳过并记）。
4. `temporal_halves` 符号与冻结方向比较。
5. `run_negative_controls`（只对该因子，repeats 用配置默认）。
6. **不**做蕴含 LLM，**不**改 grade，**不**跑探索预筛，**不**看该目标上的其它 HDD3 因子来挑选。

预注册转移成功（**关联复现**，不是因果）：

- 符号与冻结方向一致；
- 边际效应 CI 不含 0；
- 增量 CI 下界 > 0 **或** 明确记 `transfer_increment_failed`（允许失败；失败不是改门的理由）。

若 T2 因数据未准备：exit 0 且 JSON `"transfer_skipped":"backblaze_data_missing"`，不要伪造。

### 5.3 日历 T1 细节

- 用 `label_times` + 训练集全部 cutoff 的唯一日历中点，**不是**行号。
- 评估子集 = 时间后半 **且** 可与原 confirm 的交集单独附表（两行：all-late、late∩original-explore）。late∩explore 有选择偏，只作诊断。
- 禁止换 `split_salt` 重切确认集当「新数据」。

---

## 6. 编码 PR 范围（composer-2.5）

### 6.1 允许改

| 文件 | 做什么 |
|---|---|
| `src/faultevolve/cli.py` | 新增 `discover replay-claim`；tournament/interrogate/transfer 开关；JSON 字段 |
| `src/faultevolve/discovery/replay.py` **新建** | 任务无关：加载一条 raw_claim、跑沙箱+stats、组装 KD2Handoff、调 Tournament、写 interrogation 与 transfer 摘要 |
| `src/faultevolve/cloud/insights.py` 或 `discovery/mechanisms.py` | 仅当审讯 prompt 能保持任务无关地放进 mechanisms；否则 prompt 模板放 `replay.py` |
| `src/faultevolve/tasks/hdd_adapter.py` | 可选：`discovery_frames_from_paths(labels, history)` 供 T1/T2 复用，**默认**仍只 train；val 路径仅当 CLI 显式 `--allow-val-transfer` |
| `tests/test_replay_claim.py` **新建** | 合成数据：缺列失败；tournament extras；interrogation 解析失败回退；禁止 test split 参数 |
| `tests/test_discovery_task_agnostic.py` | 保持通过 |
| `skill/fe-knowledge-discovery/SKILL.md` | 增加「冻结声明审讯/转移」命令与成功检查 |
| `docs/TODO.md` | 一行状态（若文件已有 KD 段） |

### 6.2 明确不许

- 改 `benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md}` 与 `data/`。
- 读、打印、上传 `holdout*`；CLI 接受 `--split test`。
- 改 `hdd_v3.jsonl`、`stats.py` 公式、`ebh_reject`、`grade_claim` 默认、alpha、κ、`rho_max`、`max_neg_control_fpr`。
- 把本声明改判 DISCOVERED，或因 e-BH 失败去放宽发现轨。
- 用 val/test ROS 当节点分数或声明分数。
- 密钥写入文件；把 NAS 漏斗数字写进代码常量。
- 为 SmartMem 编 SMART 194；提 gitcode。
- 修改 `TournamentConfig.n_slices` 上限或默认 α。
- 重跑全库 `fe discover factors` 选新赢家。
- 回写 `kd_relaxed_20261005` 产物。

### 6.3 离线测试（编码 PR 必须绿）

```bash
pip install -r requirements.txt
python -m pytest tests/test_replay_claim.py tests/test_tournament.py tests/test_grading.py tests/test_discovery_task_agnostic.py tests/test_hdd_protected_files.py -q
python -m pytest tests/ -q
cd benchmark/hdd_mvp && python evaluator.py init.py   # val ROS ≈ 22.81，确认未改评估器
```

`test_replay_claim.py` 最低用例：

1. 合成 80 盘、含 `smart_194_normalized`，注入 HDD3_F10 代码，`--mock --enable-tournament`：`ok true`，有 `kd2` 或 tournament 产物；`cards.jsonl` 未改。
2. 去掉该列：error_type 含 `missing_column`，不调用 LLM。
3. `--transfer-frame train_late` 在合成日历上产出 `transfer.ci_low` 字段（可为负，不许崩溃）。
4. 拒绝 `holdout` 字符串作为 frame 名。
5. 审讯 mock 返回非 JSON：固定对手仍 proposed。

---

## 7. 真跑配方（编码合入后，另一轮；本计划不执行）

在 NAS/实验室，**先复制库**：

```bash
# 环境
export HDD_BENCH_DATA_ROOT=/path/to/hdd_mvp/data   # 含 public/train_history.csv.gz
ENV_FILE=/path/to/.env                             # 仅 DASHSCOPE_API_KEY 等，不入库
SRC_RUN=/home/hcf/nas_hcf_data/faultevolve/runs/kd_relaxed_20261005/v3_full
# 原 fe.db 路径以该产物内 data_audit / run_summary 为准【待抄录】
# 假设进化库仍为 89f4bdd1 的副本约定：
cp -a "$FE_RUNS_DIR/89f4bdd1" "$DST/89f4bdd1"

# 0) 只读核对（数字写入结果文件，不改本计划）
python - <<'PY'
import json, pathlib
p = pathlib.Path("$SRC_RUN")  # 实现时换成真实路径
# 打开 funnel.json / funnel_summary.json / phenomena.json / data_audit.json
# 打印 C-89f4bdd1-0010 的 grade, effect, CI, incr, ebh_pass, bh_pass, temporal, direction, fdr_mode, split_salt, confirmation_fraction
PY

# 1) mock 管道
fe discover replay-claim benchmark/hdd_mvp --run-id 89f4bdd1 --runs-dir "$DST" \
  --claim-id C-89f4bdd1-0010 --factor-id HDD3_F10 \
  --library src/faultevolve/discovery/factor_library/hdd_v3.jsonl \
  --artifacts-dir "$ART/mock" --enable-tournament --interrogate --n-slices 16 --mock --json

# 2) 真审讯+对局（原确认集，非新数据）
fe discover replay-claim benchmark/hdd_mvp --run-id 89f4bdd1 --runs-dir "$DST" \
  --claim-id C-89f4bdd1-0010 --factor-id HDD3_F10 \
  --library src/faultevolve/discovery/factor_library/hdd_v3.jsonl \
  --artifacts-dir "$ART/debate" --enable-tournament --interrogate --n-slices 16 \
  --env-file "$ENV_FILE" --json

# 3) 弱转移 T1
fe discover replay-claim benchmark/hdd_mvp --run-id 89f4bdd1 --runs-dir "$DST" \
  --claim-id C-89f4bdd1-0010 --factor-id HDD3_F10 \
  --library src/faultevolve/discovery/factor_library/hdd_v3.jsonl \
  --artifacts-dir "$ART/t1" --transfer-frame train_late --json --mock

# 4) 主转移 T2（数据缺失则 skip）
fe doctor --task-dir benchmark/backblaze_hdd --json
# 若缺数据：
# python benchmark/backblaze_hdd/download_data.py --quarters 2024Q4 2025Q1 2025Q2 --raw-dir "$BB_RAW"
# python benchmark/backblaze_hdd/prepare_data.py --raw-dir "$BB_RAW" --out-dir benchmark/backblaze_hdd/data
# 注意 HDD_BENCH_DATA_ROOT 与 hdd_mvp 共用，切换任务时 export 到 backblaze 的 data 根或不设而用任务目录
fe discover replay-claim benchmark/backblaze_hdd --run-id 89f4bdd1 --runs-dir "$DST" \
  --claim-id C-89f4bdd1-0010 --factor-id HDD3_F10 \
  --library src/faultevolve/discovery/factor_library/hdd_v3.jsonl \
  --artifacts-dir "$ART/t2" --transfer-frame backblaze_public_train --json --mock
```

Wall-clock：单因子沙箱+bootstrap（B=500）在完整 train 上按既有 KD1-H 全流程约 10 分钟量级曾被记录过；锦标赛另加切片×检验。编码代理不在本环境做真数据计时。

401/403 停止；429 用 4/8/16s 退避；非 0 先读 `<artifacts>/discovery/error.txt`。

---

## 8. 报告模板（真跑结束后填写；本计划保持空白数字）

- 产物路径、git SHA、库 SHA256（`hdd_v3.jsonl`）、`fdr_mode`、`track_label`、盐、确认比例。
- 原确认：n、正例、效应、CI、增量 CI、rho_max_abs、temporal、bh、ebh、controls FPR、蕴含 relation（卡片 id 仅作附录）。
- 审讯：三角色是否解析成功；llm_rival 标题（纯文本）。
- 对局：proposed/played/decisive/underpowered、ICP reason、claim status、`min_detectable_effect`。
- T1/T2：效应与增量 CI；是否 `transfer_increment_failed`。
- 一句话结论，三选一，禁止升级：
  - 「关联在 T2 同号且增量 CI 下界>0：跨公开 HDD 季可复现的短窗信号；机制未识别。」
  - 「边际同号但增量失败：水平相关可能被 K0 吸收；机制未识别。」
  - 「符号翻转或 CI 含 0：锁定声明在该转移帧上未复现。」

---

## 9. 实现顺序（编码代理）

1. 读本文件与 `hdd_v3.jsonl` 的 F10 行、`grading.py`、`tournament.py`、`cli.py` `discover_factors`、`engine._maybe_run_tournament`。
2. 新建 `discovery/replay.py` + CLI，先 `--mock` 合成测试绿。
3. 审讯三标记 + 解析回退。
4. `--enable-tournament` 接到 `Tournament`（从 `discover_factors` 抄 metering：`purpose=mechanism`）。
5. `--transfer-frame` 三枚举；val 默认关。
6. 更新 skill；全量 pytest；不跑 NAS。
7. PR 描述用简体中文，说明「不改变原 CONFIRMED 分级；KD2 预期可能 underpowered」。

---

## 10. 给审阅人的验收清单

- [ ] 用户叙述未把结果写成某一知识卡再确认。
- [ ] 无 holdout、无 gitcode、无 SmartMem 当正复验。
- [ ] 无编造的效应数字进代码。
- [ ] `discovery/` 任务无关测试通过。
- [ ] 默认 `fe evolve` / `discover factors` 行为不变（新命令才开 tournament）。
- [ ] 锁定声明不被改判 DISCOVERED。
