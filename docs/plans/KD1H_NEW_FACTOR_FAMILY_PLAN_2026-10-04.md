# KD1-H：新因子家族（`hdd_v3`）规划

日期：2026-10-04。性质：**仅规划，本 PR 不含功能代码、不含新库、不含任何运行结果**。执行者：后续编码代理。
上游：[KD1G_PREFLIGHT_B_AND_CRASH_FIX_PLAN_2026-10-04](KD1G_PREFLIGHT_B_AND_CRASH_FIX_PLAN_2026-10-04.md) §4；崩溃修复已合入 `f8d69eb671151b3e56f12e4e8626f1569ddbd7b9`（PR #45）。
标注：【用户提供】服务器实测；【已核实】读本仓库代码；【本地复核】在本环境对公开 `train_history.csv.gz` 复算，**标签列未读**（`train_labels.csv` 只取 `serial_number`、`model`、`cutoff_date`），未读 `holdout*`，未跑服务器；「未记录」= 没有数据。

## 0. 目标与已定决定

目标：用一个**新家族**做一次可执行的因子发现，让编码代理直接实现，不重跑刚结束的预检。

已定，不改：

1. KD1-G 预检记为 outcome B。不修 `hdd_v2.jsonl`；不复用 F001、F002、F007、F008、F009、F010、F012、F014、F020 这 9 个 id；不用该探索集上的任何效应挑候选。
2. HDD2_F004 只是线索。本库不放它的副本（代码哈希须与 v1/v2 都不同）。若某条新候选碰巧与它同列（见 §2 的 F05，`smart_4_raw` 的水平值而非 14 天差分），它按全新预注册候选从零走完整流程，**不因 F004 过功效门而优待**。
3. 不改 alpha、e-BH、rho_max、max_neg_control_fpr、confirmation_fraction、min-explore-effect、max_confirm；不改 `stats.py` / `grading.py` / 预注册逻辑；不重跑进化，不追 38.14（只是历史观察，不作因果）。
4. 不读 holdout，不用 `--split test`，不把未测数字写成已测。
5. 一次真跑，不换种子或 `split_salt` 再跑选赢家。

## 1. 依据：不看标签的覆盖普查

【已核实】沙箱（`discovery/sandbox.py`）要求输出在全部带标签单元上非空比例 ≥0.8，且 `nunique>1`；通过后**用中位数填补剩余空值**，因此流水线里 `coverage_min_explore=0.30` 看到的覆盖恒为 1，实际覆盖由沙箱 0.8 门把关。结论：「覆盖」必须在填补**之前**度量，不能指望探索阶段发现。

【本地复核】公开 train：31093 个带标签单元、44 个型号；每单元取 `date <= cutoff_date` 的最近 14 行（与 `discovery_frames` 一致）。下表只用 SMART 取值，不用标签。「单元覆盖」= 窗口最后一行有值的单元比例。

| 列 | 单元覆盖 | 说明 |
|---|---|---|
| 1、3、4、5、7、9、12、192、193、194、198、199 raw；1、3、5、7、9、194、198 normalized | 0.998 | 全覆盖 |
| 197 raw / normalized | 0.978 | 全覆盖 |
| 10 raw | 0.998 | 最后值仅 2 种、非零率 0.000，**排除**（近乎常数） |
| 187、188 raw、187 normalized、190 raw | 0.365 | 型号级可观测，见下 |
| 191 raw | 0.383 | 同上 |
| 196 raw | 0.633 | 同上 |
| 240 raw | 0.656 | 同上 |
| 241、242 raw | 0.416 | 同上 |

型号级可观测：对 190/196/240/241/242/191/187/188，凡单元覆盖 <0.8 的列，各型号要么基本全有（≥0.8）要么基本全无，**没有 0.05–0.8 之间的型号**（【本地复核】）。所以「有观测」是型号属性，不是随机缺失；覆盖低的列等价于「只有一部分型号上报这个属性」。

派生量普查（【本地复核】，用于避开退化因子）：`smart_4_raw` 与 `smart_12_raw` 最后值相同的单元占 91.1%，二者近重复，只取其一；`smart_9_raw` 的 14 天差分按构造 ≈ 24×观测天数，**排除**；「距最后记录天数」恒为 0（上一轮已证），**排除**；窗口内「上升步数」「5/7/197/198 normalized 的窗口最大减最后值」等最频繁取值占比 0.98–0.999，**排除**。

## 2. 新家族如何定候选（规则，不是挑效应）

规则（全部只依赖 §1 的普查，写入脚本，可复算）：

- **R1 覆盖**：全人群因子的**填补前**输出覆盖 ≥0.95（门是 0.8，留余量）。
- **R2 非构造常数**：输出 `nunique ≥ 10`，且最频繁取值占比 ≤0.95（比沙箱的 `nunique>1` 严，仅用于本库的离线检查，不改沙箱）；输入里不得只有 `date`，不得是窗口长度、观测天数、距最后记录天数之类的构造量。
- **R3 新**：代码 SHA256 与 `hdd_v1.jsonl`、`hdd_v2.jsonl` 全部不同；不做 kd1f 已禁止的 F004/F017/F018 与 `smart_1`/`smart_3` 最后值类变体；不做上一轮 21 条同列同形（如同列 14 天差分）。
- **R4 不选效应**：本库不引用任何 `explore_effect`、增量 CI；每一条的存在理由只能是 R1–R3 加一个模板。

### 2.1 库：`hdd_v3.jsonl`，共 24 行，id 前缀 `HDD3_`，全部新 id

字段沿用现有格式（`factor_id/family/title/code/inputs/window_days/direction/condition/outcome/scope/falsifier/lane/confirm_eligible/source`），`direction` 除控制外全为 `auto`，`source=seed_library`。

**A 族：全人群，16 条，`lane=confirm`**。覆盖和退化度为【本地复核】（「脚本核」= 本地未算，编码代理用脚本核，核不过则**写入前**改写或删除，见 §4）。

| id | family | 定义 | 填补前覆盖 | 最频繁取值占比 |
|---|---|---|---|---|
| HDD3_F01 | workload_ratio | smart_192_raw / smart_9_raw（最后行，分母 0 视为缺失） | 0.998 | 0.098 |
| HDD3_F02 | workload_ratio | smart_192_raw / smart_12_raw | 0.998 | 0.098 |
| HDD3_F03 | workload_ratio | smart_193_raw / smart_12_raw | 0.998 | 0.013 |
| HDD3_F04 | workload_ratio | smart_192_raw / smart_193_raw | 0.998 | 0.323 |
| HDD3_F05 | cycle_level | log1p(smart_4_raw) 最后值 | 0.998 | 0.079 |
| HDD3_F06 | cycle_level | log1p(smart_193_raw) 最后值 | 0.998 | 0.011 |
| HDD3_F07 | cycle_level | log1p(smart_192_raw) 最后值 | 0.998 | 0.098 |
| HDD3_F08 | thermal | smart_194_raw 窗口最大值 | 0.998 | 0.073 |
| HDD3_F09 | thermal | smart_194_raw 最后值减窗口最小值 | 0.998 | 0.430 |
| HDD3_F10 | thermal | smart_194_normalized 最后值 | 0.998 | 0.312 |
| HDD3_F11 | relative_growth | smart_193_raw 窗口增量 / 最后值 | 0.998 | 0.316 |
| HDD3_F12 | dispersion | smart_193_raw 窗口标准差 | 0.994 | 0.313 |
| HDD3_F13 | dispersion | smart_192_raw 窗口标准差 | 0.994 | 0.630 |
| HDD3_F14 | step_count | smart_192_raw 窗口内上升天数 | 1.000 | 0.632 |
| HDD3_F15 | normalized_level | smart_7_normalized 最后值 | 0.998 | 0.634 |
| HDD3_F16 | model_rank | smart_9_raw 型号内秩百分位（年龄） | 0.998 | 0.001 |

说明：F05 与 HDD2_F004 同列 `smart_4_raw` 但形状不同（水平值 vs 差分）；它只是因为 R1–R3 下该列全覆盖、与 `smart_12_raw` 近重复而二选一，不是因为 F004 过了功效门。F08–F10 与 K0 的 `smart_194_raw` 相关，交给 `rho_max` 与增量门处理，不预先剔除。

**S 族：型号级子群，3 条，`lane=confirm`**（见 §3）。

| id | 群体 | 定义（群体内） | 群体占 train 单元 | 群体内最频繁取值占比 |
|---|---|---|---|---|
| HDD3_S01 | 窗口内 smart_191_raw 有观测 | log1p(smart_191_raw 最后值) 减群体中位数 | 0.383（11918） | 0.295 |
| HDD3_S02 | 窗口内 smart_240_raw 有观测 | smart_240_raw 窗口增量减群体中位数 | 0.656（20388） | 0.443 |
| HDD3_S03 | 窗口内 smart_241_raw 有观测 | smart_241_raw 窗口增量减群体中位数 | 0.416（12926） | 0.002 |

群体外一律填 **0**（= 群体内中心化后的中位数位置，不是「缺失」）。

**D 族：群体成员诊断，3 条，`lane=diagnostic`、`confirm_eligible=false`**：HDD3_D01/D02/D03 分别是 S01/S02/S03 对应群体的 0/1 指示量。用途：判断 S 族的效应是否只是「属于哪类型号」。诊断泳道不得冻结、不得看确认集。

**C 族：对照，2 条，`lane=control`**：HDD3_C01 负对照（置换噪声，新种子字符串，代码与 HDD2_C001 不同）；HDD3_C02 正对照（`smart_197_raw` 14 天差分，K0 边际）。注意：上一轮 C002 因 `explore_no_increment` 被拦，**对照并未证明链路最后一段**（蕴含/分级/晋升仍只有单测）；本轮同样不得声称证明了这一段。

合计 16+3+3+2 = **24 条预注册**（`candidate_registry.jsonl` 24 行；`preregistration.json` 初始 24 条哈希，冻结后同 id 的哈希更新而非新增）。`--max-candidates 30` 不变。

### 2.2 被排除的列与理由

| 列 | 决定 | 理由 |
|---|---|---|
| 10 | 排除 | 近乎常数 |
| 196 | 不用 | 若做子群，群内最频繁取值占比 0.967 >0.95（【本地复核】），退化 |
| 190、187、188 | 不用 | 190 与 194 同属温度、群体相同（0.365）；187/188 已在 K0 基线里，且同群体；本轮不为凑数加入 |
| 242 | 不用 | 与 241 同群体（0.416），不再增加比较数 |
| 241、240、191 | 仅 S 族 | 见 §3 |

## 3. 子群家族的采用决定，以及与上一轮 9 条的区别

**决定：采用，但只限 S 族 3 条，附 3 条诊断，并在预注册里写明这是群体定义。**

区别：

| 方面 | 上一轮 9 条 | 本轮 S 族 |
|---|---|---|
| 目标人群 | 全部带标签单元；缺失表示「该型号没上报」，被沙箱当低覆盖拒绝 | 明确声明的群体：该列有观测的型号；群体外不是缺失，而是中心化后的 0 |
| 写法 | 全人群公式，缺失靠 NaN | `scope`/`condition` 写明群体判据（窗口内该列至少一个非空值），群体外显式填群体中位数 |
| 是否进预注册 | `scope=train_labeled_units` | `scope` 为群体定义文本；`scope` 属于预注册哈希输入，所以群体定义被锁定 |
| 混杂控制 | 无 | 群体内中心化；配套 D 族成员指示量，用来检验「只是型号归属」 |
| 门 | 全部卡在 0.8 | 门不变；S 族靠定义通过，**因此不能把它写成「覆盖 ≥0.8」**，必须同时报：群体占比、群体内覆盖、群体内最频繁取值占比 |

风险与诚实表述：

- 填 0 使沙箱覆盖恒为 1，这是由定义而来，不代表该属性在全人群上有观测。报告里必须同时写「群体占比 0.383/0.656/0.416（本地复核）」。
- 型号归属与故障率可能强相关。S 族若赢，必须同时给出对应 D 族成员指示量的探索效应与增量，作为反证参照；S 族增量不高于其成员指示量时，只记为线索，不写成发现。
- 群体判据用单元窗口内是否有非空值，等价于型号级可观测（【本地复核】无混合型号）。判据不用标签。

## 4. 库的冻结流程（写入前）与预检通过条件

### 4.1 写入前的离线、无标签检查（编码代理做，必须在 PR 里）

对 24 条中每条，用现有 `run_feature` 的同一份静态检查与沙箱，在公开 train 的发现帧上执行，**不读标签**，输出表：填补前覆盖、`nunique`、最频繁取值占比、群体占比（S/D）。通过条件：

- A 族、C02：覆盖 ≥0.95，`nunique ≥10`，最频繁取值占比 ≤0.95。
- S 族：群体占比在 [0.30, 0.80]；群体内覆盖 =1；群体内 `nunique ≥10`，最频繁取值占比 ≤0.95。
- D 族：成员指示量在 [0.30, 0.80] 之间取两种值。
- C01：沙箱可执行，`nunique>1`。
- 24 条代码两两哈希不同，且与 v1/v2 不同。

表中任何一条不过：**在冻结前**直接改写（只可改实现细节，不可换列/换群体）或删除并同步修改条数说明；不允许在看到探索效应后改。冻结后记录库文件 SHA256（写进 PR 描述，不写进库）。冻结后再不可执行视为本轮结果的一部分，不再修库。

### 4.2 服务器预检（`--explore-only`，零 LLM）

在**副本**库上运行（原 `fe.db` 前后字节与 mtime 不变）。通过条件，全部满足：

1. 退出码 0；`funnel.json`、`funnel_summary.json` 完整且可被 `json.load`（修复后的退出路径）。
2. `proposed = 24`；`executable ≥ 22`（≈92%，比上一轮 80% 更严，因为 §4.1 已离线核过）；`duplicate_code = 0`；`discovery_llm_error = 0`；无 `claim_write_error`。
3. `claims_tested = 0`，没有确认检验事件；确认集标签未被访问。
4. 库文件 SHA256 与 §4.1 记录一致。
5. 功效门通过数 ≥1（confirm 泳道）。

结局：1–4 任一不满足 → **outcome B（带诊断）**，不进全流程，不修库。1–4 满足而功效门通过数为 0 → B，同样不进全流程（沿用 KD1-G §8）。1–5 全满足 → 才可做一次全流程。

## 5. 全流程与「什么算完整发现」

命令（一次真跑，固定库与 `split_salt`，不换种子）：

```bash
cp -r "$FE_RUNS_DIR/<id>" "$DST/<id>"
fe discover factors benchmark/hdd_mvp --run-id <id> --runs-dir "$DST" \
  --library src/faultevolve/discovery/factor_library/hdd_v3.jsonl \
  --max-candidates 30 --max-confirm 2 --confirmation-fraction 0.5 \
  --min-explore-effect 0.05 --explore-only --json      # 预检
# 预检通过后，同命令去掉 --explore-only，加 --env-file "$ENV_FILE"，只跑一次
```

开关：除 `--library` 指向新库外，**没有新开关**。默认库仍是 `hdd_v1.jsonl`，不改默认。

结局定义：

| 结局 | 条件 |
|---|---|
| **A（完整发现）** | 全流程完成；≥1 条 `confirmed` 或 `discovered`；该条带**实测**效应、置信区间、增量 CI、`rho_max_abs`、阴性对照 FPR ≤ `max_neg_control_fpr`、蕴含结论、产物路径；S 族的还需附成员指示量参照 |
| **A-弱** | 过功效门并冻结，但未 confirmed/discovered，或蕴含 `unknown`；只是线索，不是发现 |
| **B（完整）** | 全流程完成，无 confirmed/discovered；**完整的 B 不是发现**，只是带诊断的负结果 |
| **B（预检）** | §4.2 任一条不满足 |

分数：LLM/Jev 输出不当节点分数；效应与 CI 只来自本地统计。不追分数变化。

### 报告要求（每次真跑）

必须包含：

- **P/R/F1、误报漏报**：纯发现没有预测器，写 `n/a（无预测器）`，不要编造；若后续另有评估运行，才填实测并注明评估器版本。
- **分阶段 token**：generate / repair / reflect / knowledge（本轮 knowledge 即发现与蕴含，用 `run_summary.json` 的 `discovery_tokens`、`entailment_tokens`；generate/repair/reflect 为 0 也要写 0）。
- **每分 token**：纯发现无分数变化，写 `n/a`。
- 漏斗各阶段计数、每个死亡的主因、功效门分布、对照结果、库 SHA256、HEAD、墙钟、`elapsed_s`。缺的写「未记录」。

## 6. 编码代理：允许与不许

**允许改/新增**：

| 文件 | 用途 |
|---|---|
| `src/faultevolve/discovery/factor_library/hdd_v3.jsonl`（新） | 24 行，§2.1 |
| `skill/fe-knowledge-discovery/scripts/hdd_coverage_census.py`（新） | 无标签覆盖普查：每列、每型号非空率与取值数，只读 `serial_number/model/cutoff_date` 和 SMART 列；产出 JSON/表 |
| `skill/fe-knowledge-discovery/scripts/check_factor_library.py`（新） | 实现 §4.1：对库逐条沙箱执行并输出表，通过/失败退出码；不读标签 |
| `tests/test_factor_library_hdd_v3.py`（新） | 见下 |
| `skill/fe-knowledge-discovery/SKILL.md` | 加 KD1-H 小节，见 §7 |
| `skill/fe-report-generation/SKILL.md` | 仅补「纯发现报告字段 n/a 写法」，若已有则不动 |
| `docs/TODO.md` | 状态行 |

测试（均离线、不读标签、不需 API）：库可被 `load_factor_library` 读取；恰 24 行、id 全 `HDD3_` 前缀且不含上述 9 个旧 id；lane/`confirm_eligible` 组合与 §2.1 一致；`direction` 除 C 族外全为 `auto`；代码哈希与 v1/v2 不重；输入列均在 `HDD_DISCOVERY_COLUMNS`；普查脚本源码不含 `label`/`weight` 列读取（用 `usecols` 断言）；检查脚本在合成小数据上通过/失败各一例；S 族 `scope` 文本含群体判据。

**明确不许**：

- 不改 `hdd_v2.jsonl`、`hdd_v1.jsonl`；不复用 9 个旧 id；不把 HDD2_F004 或 D 泳道当发现或直接确认。
- 不改 `benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md}` 与 `data/`；不读、不打印、不上传 `data/holdout*`；不用 `--split test`。
- 不改 `discovery/stats.py`、`grading.py`、`preregister` 逻辑、`sandbox.py` 的门；不改 alpha、e-BH、`rho_max`、`max_neg_control_fpr`、`confirmation_fraction`、`min-explore-effect`、`max_confirm`；不改默认库与默认开关。
- 不重跑进化；不在看到探索效应后改库；不换 `split_salt`/种子重跑；不为凑条数放宽 §4.1。
- 不把本地复核数字当服务器实测；不在无密钥时伪造真实运行结果；密钥只来自环境变量，不进代码、日志、提交。
- 不在仓库写 `KD1H_RESULT_*.md`；真跑结果由维护者在合并后执行并另行汇报。

## 7. Skill 要求（编码 PR 必须交付）

在 `skill/fe-knowledge-discovery/SKILL.md` 增加 KD1-H 小节，让其他 agent 不读本计划也能自主跑：

- **何时用**：要对 HDD 做新一轮因子发现、且上一轮预检是 B；或要核对一个因子库的覆盖与退化。
- **输入**：公开数据根（`HDD_BENCH_DATA_ROOT` 或默认路径）、库路径、副本 `runs-dir`、`--env-file`（仅全流程需要）。
- **命令**：普查、`check_factor_library.py`、mock 与 `--explore-only` 预检、（预检通过后）一次全流程；每条给完整命令行。
- **成功检查**：§4.1 表全过；§4.2 五条；全流程按 §5 结局表判定；报告字段齐全（含 `n/a` 写法）。
- **失败处理**：离线检查不过 → 冻结前改/删；预检不可执行或功效门为 0 → 记 B，不修库、不换种子；401/403 停止并报告；429/超时按 4/8/16 秒退避；退出码非 0 先看 `<artifacts>/discovery/error.txt`；原 `fe.db` 变化 → 作废并报告。
- 禁止项复述 §6 的「明确不许」中与运行相关的条目。

## 8. 未记录 / 待核

- 24 条里「脚本核」的数字：HDD3 各条的实际填补前覆盖与最频繁取值占比，除 §2.1 表中已标【本地复核】的近似值外，以编码代理脚本输出为准。
- 服务器上本家族的任何结果：未记录（尚未运行）。
- 上一轮 9 条的探索效应：未记录，且按规定不用于选择。
