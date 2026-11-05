# kd1f 完整负结果之后：下一次知识发现（KD1-G）计划

日期：2026-10-04。性质：**仅规划，本 PR 不含功能代码**。执行者：composer-2.5（自主执行）。
基线：`main` @ `46fa09e`（含 #41 解耦因子发现命令）。仅 HDD 数据集。
上游文档：[KD_NEXT_RUN_PLAN_2026-10-04](KD_NEXT_RUN_PLAN_2026-10-04.md)（KD1-F 原计划，已实现并真实运行）、[KD_NEXT_STEP_RECOMMENDATION_2026-10-04](KD_NEXT_STEP_RECOMMENDATION_2026-10-04.md)、[KD_WHY_NO_KNOWLEDGE](KD_WHY_NO_KNOWLEDGE.md)。

标注：【用户提供】运行日志/数字，本环境无服务器产物，无法复核；【已核实】本仓库代码；【推断】由前两者推出，需按 §3 的 D 检查复核。

## 0. 先读结论

1. kd1f 是一次**完整、可信的负结果（B）**：对照通过（负对照 FPR=0，planted 0.2/0.5/1.0 全部检出），流程走完。统计层没有证据显示坏了。
2. 零发现的**首要原因是种子库把方向写死为 `+`**。3 条进入确认的因子里 2 条（`smart_3_raw`、`smart_1_normalized`）确认集效应为**负**且 CI 排除 0（p=1.9e-3、4.7e-5），被 `direction_ok=false` 直接判 `refuted`。这不是「因子无效」，而是「先验方向写错」；而探索阶段的预筛（逻辑回归增量 AUROC）与方向无关，所以没有拦住它。【已核实】`hdd_v1.jsonl` 30 条全部 `direction="+"`；`grade_claim` 在 `direction_ok=false` 时无条件 `REFUTED`。
3. 第 3 条（`smart_3_normalized`，`+` 方向恰好对）是 `undetermined`：BH 过了，**e-BH 没过**（e=16.22；m=3 时头名需要 e≥60）。同时**文献蕴含结果没有被记录**，无法区分它是否也卡在 `entailment=unknown`。
4. **「把 F004/F017 翻成 `-` 再确认一遍」是被禁止的**：这 3 个因子已经看过确认集，翻方向等于用确认集选方向。它们只能作为探索期参照，不得再进确认族（§4.3）。
5. 种子库本身偏弱：30 个里 28 个是「单列最后值」，21 个可执行 → 19 去重 → 仅 4 个探索增量为正。9 个不可执行（含 `smart_10_normalized` 不在发现帧列中）、2 个与 F001 代码重复。
6. **功效是硬约束**：确认集 327 个正例下，单因子要过 e-BH 需要 |AUROC−0.5| ≳ 0.057～0.066（§3.3）。已观测的非 K0 单列效应约 0.05～0.057，处在边缘。所以下一次要同时做三件事：方向由探索集冻结、确认族更小（≤2）、确认集更大（confirmation_fraction 0.3→0.5，预注册）。**不放宽 α、不改 e-BH 公式、不改 `rho_max`、不改 `max_neg_control_fpr`。**
7. 锦标赛、机制层、重跑进化：**不是**当前阻断，本计划不碰。

## 1. kd1f 事实（不得补编）

【用户提供】实验 `89f4bdd1`，运行标签 `kd1f_20261004`，`git_sha=46fa09e`，mode=factors。产物 `/home/hcf/nas_hcf_data/faultevolve/runs/kd1f_20261004/89f4bdd1`；日志 `/home/hcf/faultevolve/runs_copy/kd1f_20261004/kd1f_real.log`（`REAL_EXIT:0`，约 365 s）。

| 漏斗阶段 | 数量 |
|---|---|
| proposed | 30 |
| executable | 21 |
| coverage_ok | 21 |
| deduped | 19 |
| explore_incr | 4 |
| frozen | 3 |
| confirmed_stats | 3 |
| discovered_or_confirmed | 0 |
| literature_dedup | not_done |

claims：proposed 30 / tested 3 / confirmed 0 / discovered 0 / refuted 2 / undetermined 1。对照：neg_trials 15，false_positives 0，FPR=0.0。Token：total 11917，全在 discovery；`tokens_per_candidate_tested=3972.33`；propose/translate/entailment 记 0。

确认集（n=9262，n_pos=327，n_neg=8935）：

| claim | 因子 | 效应 [CI] | p | e | direction_ok | temporal_ok | ρmax | 探索增量 AUROC [CI] | 级别 |
|---|---|---|---|---|---|---|---|---|---|
| C-…-0034 | HDD_F004 `smart_3_raw` last | −0.0494 [−0.0798, −0.0168] | 1.86e-3 | 11.61 | false | false | 0.306 | 0.00841 [0.00146, 0.0169] | refuted |
| C-…-0047 | HDD_F017 `smart_1_normalized` last | −0.0572 [−0.0868, −0.0288] | 4.66e-5 | 73.25 | false | false | 0.250 | 0.00445 [0.00109, 0.00767] | refuted |
| C-…-0048 | HDD_F018 `smart_3_normalized` last | +0.0506 [0.0191, 0.0822] | 9.5e-4 | 16.22 | true | true | 0.138 | 0.00483 [0.000749, 0.00905] | undetermined |

历史 ROS 38.14 只是观察点，本次纯发现无分数变化，**不作因果解释**。

## 2. 诊断（按证据强度排序）

### 2.1 方向先验写错（首要，【已核实】+【用户提供】）

- 种子库 30 条 `direction` 全为 `+`；`FactorEntry.to_raw_claim` 原样传入；`test_feature` 的 `direction_ok = sign(effect)==期望符号`；`grade_claim` 对 `not direction_ok` 直接 `REFUTED`。
- 物理上说得通：normalized 值通常「越低越差」，`smart_1_normalized` 的 `+` 本来就应预期为负；raw 与 normalized 常反向。写库时没有按列区分。
- 探索预筛 `incremental_auroc` 用逻辑回归，系数可正可负，**对方向不敏感**；排序键是 `incr_ci_low`。于是「方向错但信号真」的因子被送进确认并被毙。
- `temporal_ok=false` 很可能是同一个符号错误的副产物（`pipeline.py` 里 `sign_ok = claim.direction=="+"`），但两半各自的 e1/e2 **没有被记录**，【推断】，需在新漏斗里记录而非猜。

### 2.2 undetermined 门槛（【已核实】算术）

e-BH 只对**已冻结且已确认**的 m 条做：条件 `e ≥ m/(k·α)`，α=0.05。κ=0.5 时 `e=0.5/√p`。

| 家族大小 m | 头名需 e ≥ | 对应 p ≤ | 双侧 z ≥ | 第 2 名需 e ≥ | 第 3 名需 e ≥ |
|---|---|---|---|---|---|
| 1 | 20 | 6.25e-4 | 3.42 | – | – |
| 2 | 40 | 1.56e-4 | 3.78 | 20 | – |
| 3 | 60 | 6.94e-5 | 3.98 | 30 | 20 |

C-0048：p=9.5e-4（BH 在 m=3 时 `p ≤ 0.05/3=0.0167` 通过），e=16.22 < 60，e-BH 不通过。C-0047 的 e=73.25 其实越过了头名线 60，**如果方向正确**才有可能走到 `discovered`（但它已看过确认集，不能据此翻案，见 §4.3）。结论：门槛不是 bug，是 α 与 m 的设计结果；合法杠杆是**减小 m**与**增大样本**，不是改阈值。

### 2.3 蕴含结果是黑盒（【已核实】）

`pipeline.run` 对每条已测 claim 都调 `judge_entailment`（约 3 次，约 11.9k token，即 discovery 阶段的全部 token）。`DISCOVERED` 要求 `relation=="none"`；`unknown`（JSON 解析失败/卡片 id 非法）会落成 `undetermined`；`same` 会成 `CONFIRMED`（对 outcome A 同样算数）。但：
- 蕴含关系、解析是否失败**没有写事件/漏斗**；
- CLI 汇总硬编码 `entailment_tokens: 0`，所有 token 记在 `discover`，所以报告里「entailment 0」是**计量归类问题**，不是没调用。

下一次必须把它变成可见的诊断量，并对 `unknown` 做一次重试。

### 2.4 种子库弱（【已核实】文件，漏斗数字【用户提供】）

- 28/30 是单列「最后值」或 K0 列上的 14 步差分。非 K0 的 last 值与 K0 的 last 高度冗余的少，但多数无增量 → 15 条死于 `explore_no_increment`。
- 9 条不可执行：至少 `smart_10_normalized` 不在 `HDD_DISCOVERY_EXTRA_COLUMNS` 中（`KeyError`）；其余需读 `funnel.json` 的 `primary_failure/error` 才能确认。
- 重复：HDD_F001（阳性对照）与 HDD_F022（`smart_197_raw` 14 天加速）代码等价 → `duplicate_code`（【推断】，D 检查验证）。
- 缺少真正「现象级」家族：相对型号归一化、每小时工作量速率、值/缺失分离、窗口内不稳定性、「K0 计数全零」群体内的残差风险（KD 建议 §6.2 列出过，库里每个家族只有 1 条且多死在增量）。
- 阳性对照 F001 本应在探索期死掉（边际显著、增量≈0），所以它**不能**验证「能否走到 discovered」。链路最后一段（蕴含+分级+晋升）没有被任何对照端到端验证过，只有单测。

### 2.5 其他风险（【推断】，D 检查确认）

- **特征含 NaN 进入 `incremental_auroc`**：基线 `fillna(0)`，但特征 `feat` 不填；sklearn 逻辑回归遇 NaN 会抛异常，被外层 `except` 吞成 `discovery_llm_error`。库里「群体内条件」「缺失」类因子最容易触发。D 检查要看 kd1f 的 `discovery_llm_error` 计数。
- **claim 序号从 30 起**（确认集 claim 为 0034/0047/0048，对应 F004/F017/F018 偏移 30）：副本库里很可能已有一次先前 mock/冒烟写入的 30 条 claim。下次必须从**原库重新复制干净副本**。
- 确认集由 train 内哈希切出，不是外部盲测；最高只能称「HDD 公开 train/val 内的复现增量因子」。

## 3. D 检查（只读、零 token，先做）

对象：kd1f 产物与**副本** `fe.db`（`mode=ro`），**不得读 `data/holdout*`**，不得重算确认集统计（避免进一步消耗确认集）。

| # | 检查 | 产出 | 决策 |
|---|---|---|---|
| D1 | `kd1f/.../discovery/funnel.json`：30 条各自 `stage_reached/primary_failure/detail` | 9 个不可执行的具体原因；15 个 `explore_no_increment` 的 `incr_gain/incr_ci_low` 分布 | 不可执行原因决定 §5.3 库修复项 |
| D2 | 事件表 `discovery_llm_error` 计数与首条 | 是否存在被吞异常（尤其 NaN→LR） | >0 → 先修（K6），不算阈值问题 |
| D3 | 事件/`claims` 表：副本里 claim 总数、是否有先前 mock claim | 解释序号偏移 | 确认则 §6 必须用干净副本 |
| D4 | 事件表是否有 `claim_graded`，及 `controls.json` | 对照数字与用户提供一致 | 不一致 → 停，先查 |
| D5 | LLM 蕴含的原始回复是否在任何日志中 | 通常没有 | 没有则在 K3 补上，并明确「本次蕴含结果未知」 |
| D6 | `git rev-parse HEAD` 服务器代码 == `46fa09e`；`fe doctor` | 版本一致 | 否则先同步 |

产物：把 D1～D6 结果写进 `docs/plans/KD1G_RESULT_<日期>.md` 的「诊断」一节（执行者新建；本 PR 不建）。**D 检查不得改变 §4 的预注册设计**（设计在看新运行结果前冻结）。

### 3.3 功效估算（用于预注册，【已核实】来自 CI 宽度反推）

从 kd1f 确认集 CI 反推单因子 AUROC 标准误：(0.0868−0.0288)/(2×1.96)=0.0148，(0.0798−0.0168)/3.92=0.0161，取 SE≈0.015～0.016（327 正例）。最小可检出效应 MDE≈ z×SE：

| 配置（正例数≈） | SE | m=1 (z=3.42) | m=2 头名 (z=3.78) | m=3 头名 (z=3.98) |
|---|---|---|---|---|
| confirm 30%（327） | ~0.0155 | 0.053 | 0.059 | 0.062 |
| confirm 50%（≈545，SE×√(327/545)） | ~0.012 | 0.041 | 0.046 | 0.048 |

要达到约 80% 功效，真实效应需再多约 0.84×SE。所以 50% 确认 + m≤2 时，真实 |AUROC−0.5| 约 ≥0.055 才有较好把握。这是估算，不是保证；新方案**不承诺**一定出 outcome A。

## 4. 预注册设计（本次运行开始前冻结，写入运行报告）

### 4.1 改变了什么、没改什么

| 改变（均是设计选择，不是调阈值） | 理由 |
|---|---|
| 方向 `auto`：在**探索集**上由边际 AUROC 符号决定，冻结后再进确认 | 消除 2.1；确认集一次性使用 |
| 探索功效门：冻结前要求 `incr_ci_low>0` 且探索边际 `|AUROC−0.5| ≥ 0.05` 且探索边际 CI 排除 0 | 确认名额很贵（m 小才能过 e-BH）；达不到 MDE 的因子不占名额 |
| `max_confirm=2`（原 3） | m=2 时头名线 e≥40 |
| `confirmation_fraction=0.5`（原 0.3） | 确认集 SE 降约 22%（§3.3）；explore 仍有约 545 正例 |
| 蕴含重试 + 记录；token 按 entailment 归类 | 2.3 |
| 新种子库 `hdd_v2.jsonl`（含诊断泳道） | 2.4 |

不变：`alpha=0.05`、`e_calibrator_kappa=0.5`、`rho_max=0.8`、`max_neg_control_fpr=0.10`、`planted_strengths`、`bootstrap_b=500`、`split_salt="fe-kd-2026"`、日历前后两半检验、BH+e-BH 同时要求、`use_jev_entailment=false`、`grade_claim` 逻辑。

说明：同 salt 下 `confirm(0.3) ⊂ confirm(0.5)`，kd1f 看过的 30% 确认集被包含在新确认集中，但**新确认因子从未看过任何确认标签**；被烧掉的只是 3 个旧因子（§4.3）。

### 4.2 比较族（计数规则）

- 候选总数 ≤30（含 2 个对照、≤6 个诊断泳道）；全部计入 `candidate_registry.jsonl` 的 `comparison_index`。
- 进入确认 ≤2。m=冻结并确认的条数。探索期筛选不计入 m（探索/确认分离）。
- 若探索期没有合格候选 → **不进确认**，直接 outcome B（功效不足），不为凑数降低功效门。

### 4.3 被烧掉的因子与「知情」泳道

- **烧掉**：F004、F017、F018 已看过确认集。它们及任何 `smart_1_*`、`smart_3_*` 的「最后值」类变体**不得**进入本次确认族。可作为探索期参照（泳道 D）。
- **泳道 D（diagnostic，`confirm_eligible=false`）**：因本计划受 kd1f 确认摘要启发而提出的假设（如：smart_1/smart_3 的效应是否只是型号/厂商代理），只跑到探索阶段并记录统计，**不得冻结、不得查看确认集**。其结论是「诊断」，不是发现。若泳道 D 显示某因子在型号内仍强，**下一轮**（新规划）再用独立确认流程；本轮不确认。
- 泳道 C（confirm eligible）：其余全新家族，方向 `auto`。

### 4.4 outcome 定义

沿用 KD_NEXT_RUN_PLAN §4。补充：
- **A**：≥1 条 claim 为 `confirmed` 或 `discovered`，且 `phenomena.json`/`discovered_cards.jsonl` 有实测数值（效应及 CI、ρmax、探索增量 AUROC 及 CI、确认集正例数）、对照通过、产物包完整。`confirmed`（蕴含 `same`）算 A，但报告要说明它与已有卡片重合，新颖性弱于 `discovered`。
- **A-弱（仅作线索，不叫发现）**：有 claim 通过 BH、方向与时间都对、增量为正，仅因 e-BH 或蕴含 `unknown` 而 `undetermined`。报告需给出所需 m/p/e 数字。
- **B（带诊断的完整负结果）**：漏斗走完，每个死亡有主因，且下面至少一个量被测出：每个候选的探索边际效应与 SE、功效门通过数、MDE。

禁止：改 α/e-BH/ρ/FPR、对 kd1f 因子翻方向后确认、读 holdout、用 LLM 判断代替统计、把泳道 D 当发现。

## 5. 代码与文档改动（最小，composer 执行）

不得改：`benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md}`、`data/`；不读 `data/holdout*`；`discovery/stats.py` 的统计公式不动（K6 仅在调用前补缺失值）。功能先做完，测试放最后且最小化。

### 5.1 代码

| # | 改动 | 文件 | 要点 |
|---|---|---|---|
| K1 | 方向 `auto` | `discovery/factors.py`（`FactorEntry.direction` 允许 `auto`）、`discovery/pipeline.py`（`_run_explore_gated`） | 在探索集算 `signed_effect`，符号为正→`+`，否则`-`；写回 `claim.direction`；**重新计算 `prereg_hash` 并更新 store**，发 `claim_direction_frozen` 事件（含探索效应、CI）。冻结发生在访问确认集之前。`seed_from("claim_stats", prereg_hash)` 在方向冻结后再取。 |
| K2 | 探索统计入漏斗 + 功效门 + 泳道 | `pipeline.py`、`funnel.py`、`factors.py` | `FactorEntry` 增 `lane`（`confirm`/`diagnostic`/`control`）、`confirm_eligible`。`touch(...)` 的 detail 增：`explore_effect`、`explore_ci`、`explore_sign`、`coverage`、`rho_max_abs`、`incr_gain`、`incr_ci_low/high`。新增 `primary_failure`：`explore_below_power_gate`、`diagnostic_only`。排序键仍 `incr_ci_low`，但只在通过功效门且 `confirm_eligible` 的集合内取前 `max_confirm`。 |
| K3 | 蕴含可见 + 重试 + 归类 | `discovery/novelty.py`、`pipeline.py`、`cli.py`、`common/metering.py`、`discovery/report.py` | `judge_entailment` 遇 `unknown` 重试 1 次；`claim_entailment` 事件记录 `relation/card_id/attempts/reply_tail(≤200 字符)`；用 `entailment` 阶段标签计量（LLM 调用处传不同 stage）；CLI 汇总 `entailment_tokens` 取实测值，删除硬编码 0。 |
| K4 | 分级诊断细化 | `pipeline.py`（分级后写漏斗） | 对每个已测 claim 记录：`bh_pass/ebh_pass`、`ebh_required_e`（= m/(k·α)，k 为按 e 降序名次）、`e1/e2`（两半效应）、`temporal_ok`、`relation`、`controls_ok`、`functional_novel`；`primary_failure` 细分：`grade_undetermined:ebh`、`:entailment_unknown`、`:temporal_none`、`grade_refuted:direction`、`grade_refuted:ci`。 |
| K5 | CLI 选项 | `cli.py`（`discover_factors`） | 新增 `--confirmation-fraction`（默认沿用配置）、`--min-explore-effect`（默认 0.05）、`--explore-only`（跑到冻结前，不访问确认集，**不调 LLM**，写完整 `funnel.json`；也用作服务器 preflight）。三者写入 `data_audit.json`。 |
| K6 | 特征 NaN 处理与库校验 | `pipeline.py`（`_run_explore_gated` 内、`incremental_auroc` 调用前）、`factors.py` | 特征 NaN 用**探索集中位数**填充并追加缺失指示列，基线与全模型同样处理；覆盖率仍按原 NaN 计。`load_factor_library` 增校验：输入列 ⊆ `HDD_DISCOVERY_COLUMNS`、代码哈希唯一、≤`max_candidates`、`lane` 合法，违规直接报错（不静默跳过）。 |
| K7 | 库 v2 | `discovery/factor_library/hdd_v2.jsonl`（新） | 见 §5.2。 |
| K8 | 报告 | `discovery/report.py` | 漏斗表增列：探索效应、功效门、MDE 估计、`ebh_required_e`；token 表含 `entailment`。`tokens_per_score_gain` 保持 `n/a`。 |

### 5.2 `hdd_v2.jsonl`（≤30 条；全部 `direction="auto"`，对照除外）

约束：只用 `HDD_DISCOVERY_COLUMNS` 内的列；窗口是日历天（用 `date` 列，不是行数）；缺测不当作 0（除非明说「群体外填 0」）；每条原子，一个 `feature(history)`；不使用 K0 的 `last`/`diff14`/`nz` 原样。每条写明 `family`、`lane`、`inputs`、`window_days`、`falsifier`、`source`。

泳道 C（confirm eligible，目标 18～20 条）：

| 家族 | 候选（每行 1 条） |
|---|---|
| 非 K0 计数的近期变化（最后一天 − 窗口首个有效值，窗口 14 天） | `smart_196_raw`、`smart_10_raw`、`smart_192_raw`、`smart_4_raw`、`smart_193_raw`（5 条） |
| 工作量/老化比率 | `smart_193_raw / max(smart_9_raw,1)`；`smart_241_raw / max(smart_9_raw,1)`；`smart_242_raw / max(smart_9_raw,1)`；`smart_241_raw / max(smart_242_raw,1)`；`smart_240_raw / max(smart_9_raw,1)`（5 条） |
| 型号内相对位置（按 `model` 分组的最后值**秩百分位**，只用特征自身分布，不用标签，不做跨集拟合） | `smart_194_raw`、`smart_190_raw`、`smart_7_raw`、`smart_241_raw` 的型号内秩百分位（4 条） |
| 窗口内不稳定性 | `smart_194_raw` 的 max−min；`smart_194_raw` 的 std；`smart_7_raw` 的 std（3 条） |
| 值与缺失分离 | 窗口内有记录的天数 / 窗口天数；全部 SMART raw 列缺失比例的均值；最后记录距窗口末端的天数（3 条） |
| 「K0 错误计数全零」群体内的残差风险 | 群体 = `smart_5/187/188/197/198/199_raw` 全部**有观测且为 0**；群体内取 `(smart_196_raw>0)+(smart_10_raw>0)+(smart_192_raw 窗口增量>0)`，群体外填 0（1 条） |

泳道 D（diagnostic，不冻结，4～6 条）：`smart_1_raw` / `smart_1_normalized` / `smart_3_raw` / `smart_3_normalized` 的**型号内秩百分位**（不使用标签的型号编码，避免目标泄漏）。目的：判断此前的 smart_1/smart_3 效应是否为型号代理。

对照（`lane=control`，2 条）：F002 同款置换阴性对照（新种子）；一个 K0 边际阳性对照（如 `smart_197_raw` 窗口增量，预期死于 `explore_no_increment`，用来证明漏斗对「已知相关但不新」会拦截）。

执行者在写库时必须先在本地用 `fe discover factors --explore-only --mock`（K5）验证全部可执行，不得用 kd1f 确认集结果挑选候选。

### 5.3 文档与技能（每个落代码的 PR 必须同步）

- `skill/fe-knowledge-discovery/SKILL.md`：加 `--explore-only`、`--confirmation-fraction`、`--min-explore-effect`、`direction=auto`、泳道说明、新的成功检查与失败处理；注明「烧掉的因子不得进确认」。
- `skill/fe-report-generation/SKILL.md`：token 表含 `entailment`；漏斗新列；A/A-弱/B 判定写法。
- 如新增脚本检查（可选）：`skill/fe-knowledge-discovery/scripts/check_discovery_summary.py` 补 `funnel.json` 新字段存在性检查。
- `docs/TODO.md` 顶部入口：已在本 PR 添加指向本文件；落代码/跑完后更新为结果。

## 6. 服务器命令（K1～K8 合并后；严格顺序，不并发第二个 KD 运行）

占位：`$ENV_FILE` 只含 `DASHSCOPE_API_KEY=…`，**不要回显、不要写入日志/仓库**。运行标签 `kd1g_20261005`（若日期不同只改标签，**不要复用 `kd1f_20261004` 目录**）。

```bash
cd /home/hcf/faultevolve/code
git fetch origin main && git checkout <合并后的 main SHA> && git rev-parse --short HEAD
pip install -r requirements.txt

TAG=kd1g_20261005
SRC=/home/hcf/faultevolve/code/benchmark/hdd_mvp/.fe/runs/89f4bdd1      # 原库，只读复制
DST=/home/hcf/faultevolve/runs_copy/$TAG
ART=/home/hcf/nas_hcf_data/faultevolve/runs/$TAG
mkdir -p "$DST/89f4bdd1" "$ART" && cp "$SRC/fe.db" "$DST/89f4bdd1/fe.db"   # 干净副本，不用 kd1f 副本

# 0) 版本与数据体检（只用公开 train/val；不要列出 data/holdout*）
fe doctor --json --task-dir benchmark/hdd_mvp
fe data checkup benchmark/hdd_mvp --json --out "$DST/datacheck"

# 1) 离线 mock（无 API）
fe discover factors benchmark/hdd_mvp --run-id 89f4bdd1 --runs-dir "$DST" --artifacts-dir "$ART/mock" \
  --library src/faultevolve/discovery/factor_library/hdd_v2.jsonl \
  --max-candidates 30 --max-confirm 2 --confirmation-fraction 0.5 --min-explore-effect 0.05 --mock --json

# 2) 真实数据 preflight：只到探索冻结前，零 LLM、不碰确认标签；每条可执行性/覆盖/探索效应
cp "$SRC/fe.db" "$DST/89f4bdd1/fe.db"          # mock 写过 claim，重置副本
fe discover factors benchmark/hdd_mvp --run-id 89f4bdd1 --runs-dir "$DST" --artifacts-dir "$ART/preflight" \
  --library src/faultevolve/discovery/factor_library/hdd_v2.jsonl \
  --max-candidates 30 --max-confirm 2 --confirmation-fraction 0.5 --min-explore-effect 0.05 --explore-only --json \
  | tee "$DST/preflight_summary.json"

# 3) 真实全流程（单次）
cp "$SRC/fe.db" "$DST/89f4bdd1/fe.db"          # preflight 写过 claim，再重置
fe discover factors benchmark/hdd_mvp --run-id 89f4bdd1 --runs-dir "$DST" --artifacts-dir "$ART/run" \
  --library src/faultevolve/discovery/factor_library/hdd_v2.jsonl \
  --max-candidates 30 --max-confirm 2 --confirmation-fraction 0.5 --min-explore-effect 0.05 \
  --env-file "$ENV_FILE" --json | tee "$DST/kd1g_summary.json"

# 4) 报告与数字核对
fe discover report benchmark/hdd_mvp --run-id 89f4bdd1 --runs-dir "$DST" --json > "$DST/kd_report.json"
python skill/fe-knowledge-discovery/scripts/check_discovery_summary.py "$ART/run"
```

注：步骤 2 的 preflight 若发现库有不可执行项，允许**一次**修库（只修可执行性/列名/重复，不按探索效应增删候选），重跑步骤 1～2；之后冻结库的 SHA256 并写进报告。步骤 3 只跑一次。

## 7. 成功检查

preflight（步骤 2）通过条件：
- `executable ≥ 24`（30 条里），每个不可执行有 `error_tail`；`duplicate_code=0`；`discovery_llm_error=0`。
- 泳道 C 通过功效门（`explore_effect ≥ 0.05` 且增量 CI 下界>0）的条数 **≥1**。若为 0：**不要继续步骤 3**，写 outcome B（探索期就无合格候选），附每家族探索效应分布，再规划新家族（不是放宽门）。

全流程（步骤 3）检查表（见 §4.4 的 A/A-弱/B）：
- `funnel_summary.json` 阶段单调；每个失败有唯一主因；`claim_direction_frozen` 事件数 = 冻结数。
- `controls.json`：负对照 FPR ≤0.10；planted 检出符合预期。
- 每个已测 claim 有 `claim_entailment` 事件，`unknown` 比例已报告。
- `run_summary.json`/CLI 汇总 token：`entailment` 单列且非 0（若有已测 claim）；`tokens_per_candidate_tested`、`tokens_per_confirmed_claim`（confirmed=0 时 `n/a`）、`discovery_token_share`。
- `candidate_registry.jsonl` 含代码哈希、输入、窗口、方向（含冻结后的）、基线版本、来源、比较序号、lane。
- 报告写明：烧掉因子名单、确认集 `n/n_pos`、实际 m、`ebh_required_e` 与各 claim 的 e。

## 8. 失败处理

| 现象 | 动作 |
|---|---|
| preflight 大量 `not_executable` | 读 `error_tail`；修列名/空值；一次修库；不重试刷过 |
| `discovery_llm_error`>0 | 打印首条；多为 NaN→LR（K6）或沙箱返回非 Series；修异常本身，不放宽阈值 |
| 通过功效门的 =0 | outcome B；报告探索效应分布与 MDE；转入新规划（新家族/更大样本），不进步骤 3 |
| 冻结 2 条但都 `refuted`/方向或时间不一致 | 合法 B；记录 e1/e2；不翻方向再测 |
| 都 `undetermined` 且 `ebh_required_e` 未达 | 合法 A-弱/B；报告所需 e 与实测 e；不改 e-BH |
| 蕴含 `unknown` 比例高 | 先看 `reply_tail`；修提示/解析；重试已有上限，不手工指定关系 |
| 对照失败（FPR>0.10 或 planted 漏检） | 停；先查统计/对照实现，不报告发现 |
| LLM 限流 | 指数退避 4 次；仍失败保留已完成漏斗并标注未完成 |
| 发现自己读了或要读 `data/holdout*` | 立即停止，不记录内容，在报告中说明 |

## 9. Token 预算估计

| 项 | 估计 | 依据 |
|---|---|---|
| preflight | 0 | `--explore-only` 不调 LLM |
| 蕴含，每个已测 claim 约 4k（kd1f 实测 3972/claim 全为蕴含） | 2 条 ≈ 8k；`unknown` 重试最坏 ≈ 16k | 卡片全文清单进提示 |
| 可选 LLM 提案（`fe discover propose`，≤8 条） | 6k～10k | 本轮默认**不跑**，库为唯一来源；仅当 preflight 通过功效门条数 <1 且用户要求时作为下一轮 |
| 上限 | **20k**（硬护栏，超出停止并报告） | |

总墙钟：kd1f 约 365 s（30 候选，3 条确认）；本轮 preflight 与全流程各预计同量级，确认集更大会略增 bootstrap 时间。【推断】

## 10. 非目标

- 不重跑 kd1f，不换 seed/预算重跑 89f4bdd1，不追 38.14。
- 不改 α/e-BH/ρ/FPR/蕴含逻辑；不开锦标赛/机制层；不接外部数据；不做 SSD/内存。
- 不把泳道 D 的探索统计、不把旧 3 因子当作发现。
- 不做大重构。

## 11. composer-2.5 交接

### 11.1 顺序 TODO（功能先行，测试最后且最小化）

- [ ] **H0** `git fetch origin main`，建分支 `cursor/kd1g-<简述>-<后缀>`，`pip install -r requirements.txt`。先读：`docs/dev/MVP开发指南.md`、本文件、`discovery/{factors,pipeline,funnel,grading,novelty,report}.py`、`cli.py` 的 `discover_factors`。
- [ ] **H1** K1 方向 `auto` + K6 NaN 填充/库校验（先做，决定其他项的数据流）。
- [ ] **H2** K2 功效门/泳道/漏斗 detail；K5 的 `--explore-only`、`--confirmation-fraction`、`--min-explore-effect`。
- [ ] **H3** K3 蕴含重试/事件/归类；K4 分级细化；K8 报告列。
- [ ] **H4** K7 写 `hdd_v2.jsonl`（按 §5.2，自己用 `--explore-only --mock` 验证全部可执行）。
- [ ] **H5** 技能与文档（§5.3），`docs/TODO.md` 顶部入口更新。
- [ ] **H6** 最小测试（最后）：库 schema/校验；`auto` 方向只用探索集且更新 prereg；`--explore-only` 不访问确认掩码、不调 LLM；NaN 特征不抛；`hdd_protected_files` 检查。不跑全量回归，除非用户要求。
- [ ] **H7** 开 PR，提醒用户可跑服务器步骤；**不要**自己在无密钥时伪造真实运行结果。
- [ ] **H8**（有密钥/服务器时）按 §6 执行，单次真实运行；写 `docs/plans/KD1G_RESULT_<日期>.md`（诊断、漏斗、A/A-弱/B、token 表、烧掉名单）；更新 `docs/TODO.md`。

### 11.2 实现细节提醒

- 方向冻结必须发生在**访问确认集之前**；任何 `confirm_mask` 索引都在冻结之后。写测试时用 mock `y` 在确认掩码上全置同值，断言冻结方向不变。
- `preregister(claim, cfg)` 的哈希是否包含 `direction`：先读实现。若不含，需把 `direction_mode` 和冻结后的方向一并纳入，否则「预注册」名不副实。
- `grade_claim` 不改。K4 只是在分级前后多记录数字。
- `e-BH` 的 m 是**已测 claim 数**（`tested_claims`），不要改成候选总数。
- 受保护文件检查：改动后 `git diff --stat` 不得出现 `benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md,data/}`。
- 日志/事件里不得出现密钥；蕴含 `reply_tail` 是 LLM 输出，可记录，但要截断。

### 11.3 结果表（执行者只填真实值）

| 项 | 值 |
|---|---|
| 代码 SHA / 库 SHA256 | |
| D1～D6 结论 | |
| preflight：executable / 通过功效门（泳道 C） | |
| 漏斗：提出/可执行/覆盖/去重/探索增量/功效门/冻结/确认/发现 | |
| 冻结因子：探索效应与冻结方向 | |
| 确认：n / n_pos / m / 各 claim 效应、CI、p、e、ebh_required_e、e1/e2 | |
| 蕴含：relation 分布、unknown 比例 | |
| 对照：负对照 FPR、planted 检出 | |
| token：按阶段（含 entailment）/ 总量 / 每已测 claim | |
| 结论 A / A-弱 / B（主因） | |
