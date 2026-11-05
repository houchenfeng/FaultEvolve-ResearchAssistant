# KD1-I：窗口内顺序敏感机制新家族（`hdd_v4`）规划

日期：2026-10-04。性质：**仅规划文档，不改功能代码，不写新库，不含任何新运行，不改统计判定，不动已有因子库**。
基线：`main` = `ede2cd6db301313035cbd12ba607d8e0f75f733c`（PR #49 已合：`run_summary.total_tokens` 取 `engine.metrics.total_tokens`）。
执行者：后续编码代理（composer-2.5）。
标注：【用户提供】服务器实测；【已核实】读本仓库代码或文档；【本地复核】在本环境对公开 `train_history.csv.gz` 复算，**只读 `serial_number/model/cutoff_date` 与 SMART 列，没有读标签列，没有读 `holdout*`，没有跑服务器**；「未记录」= 没有数据。

## 0. 结论（先看这里）

1. **用户已推翻「HDD3 封存、不开新家族」这个停止点。** 循环继续：本文给出下一个可直接编码的新家族 `hdd_v4`（KD1-I）。HDD3 的结果与判定一律不动。
2. **新家族的理由不是「上次差一点」。** 理由是机制：HDD1–HDD3 的窗口统计全是「水平 / 比值 / 总增量 / 标准差 / 最大值 / 上升天数 / 型号内秩」，几乎不看**窗口内部的先后顺序**；`hdd_v4` 专门做「顺序敏感」的四类机制（前后半窗位移、单日突发、事件时序、最后值在自身窗口中的位置），外加一个从未被任何库用过的新列 `smart_9_normalized`（§3）。
3. **我核实后纠正了上一份计划里两处错误**（§1）：e-BH 的 α 是 0.05 而不是 0.1；F10/F11 的「要求 e」配对没有反，是上一份计划对 e-BH 阈值方向的理解有误。F11 离门不是「差一点」，而是 19.54 对 40。
4. **现有列上「还没试过的新单列」几乎耗尽**（§2 列表）。能推进的是**新机制**，不是新列；所以本轮的主体是机制，新列只有 1 个。
5. **e-BH 校准器是否功效过低**，另起一个**合成数据、不看任何候选结果**的轨道（§7），只对将来新家族生效，**不替代、不阻塞本轮真跑，也不改 HDD3 与 HDD4 的判定**。
6. **不写「停下来等用户」。** 若 KD1-I 预检为 B 或完整 B，下一步已在 §9 写明。

## 1. 对上一份计划的核实与更正【已核实】

### 1.1 e-BH 的 α 与要求 e

- `config.py::DiscoveryConfig.alpha` 默认 **0.05**（`rho_max=0.8`、`max_neg_control_fpr=0.10`、`bootstrap_b=500`、`e_calibrator_kappa=0.5`、`confirmation_fraction` 默认 0.3，HDD3 实跑传 0.5）。`cli.py` 没有覆盖 α 的开关。
- `stats.py::ebh_reject`：把 e 从大到小排，第 k 名要求 `e ≥ m/(k·α)`。**阈值随名次 k 增大而变小**（k=1 最严）。
- `pipeline.py` 的 `order_by_e`：按 e 降序排名，`ebh_required_e = m_tested/(rank·α)`，`m_tested` 是实际进入确认检验的声明数（HDD3 为 2）。
- 代入 m=2、α=0.05：第 1 名要求 e ≥ 40，第 2 名要求 e ≥ 20。与【用户提供】的数完全吻合：F11（e=19.54，排第 1）要求 **40**；F10（e=3.54，排第 2）要求 **20**。

结论：

- 「F10 要 20、F11 要 40 与『e 大的排第 1』方向相反」**不成立，没有反**：e 大的 F11 排第 1，所以要求最严（40）。这一项从「待核」改为**已核实，无记录或展示错误**。
- 上一份计划写「要求 e=20 反推 α=0.1」「F11 的 e=19.54 离 20 很近」是**错的**。F11 要求 40，只有一半；若单独检验（m=1）要求 20。本文记为更正，不回写旧文档。
- 两条都未过的结论不变：F11 的 e=19.54 < 40，F10 的 e=3.54 < 20。**不改任何判定。**
- 校准器含义：`e = 0.5/√p`，k=1 且 m=2 时要求 p ≤ (0.5/40)² = 1.56e-4。F11 的 e=19.54 对应 p ≈ 6.5e-4。这是量级差，不是舍入差。

### 1.2 其余已核实项

- 蕴含 `same` 在 `grade_claim` 中不会把声明降成 undetermined；即使 e-BH 过了，F10/F11 最多是 CONFIRMED，不是 DISCOVERED。
- `fe discover factors` 的 CLI 默认 `--max-confirm 3`，HDD3 实跑显式用了 2。本轮沿用 2，不改。
- 无标签普查脚本、库检查脚本、`hdd_v3` 测试已存在（`skill/fe-knowledge-discovery/scripts/`、`tests/test_factor_library_hdd_v3.py`）。

## 2. 已查过的列与已用机制（为什么现有单列上没有新东西）

### 2.1 各列已被哪些库用过【已核实：读 `hdd_v1/v2/v3.jsonl` 的 `inputs` 与 `family`】

| 列 | v1 | v2 | v3 | 机制 |
|---|---|---|---|---|
| 1 raw / 3 raw / 7 raw | 最后值、波动 | 型号秩、std | — | 水平、秩、std |
| 4 raw | 最后值 | 14 日差 | log1p 水平 | 水平、差分 |
| 5 raw、198 raw | 加速度、联合变化 | — | — | 仅稀有事件 |
| 9 raw、12 raw | 型号内 z | 比值分母 | 比值分母、年龄秩 | 比值、秩 |
| 187/188 raw | 波动、零子群 | 零子群 | — | K0 基线内 |
| 190 raw、196 raw、10 raw | 水平 | 秩 / 差分 | — | 水平、秩、差分 |
| 191/240/241/242 raw | 水平 | 比值、型号秩 | 子群中心化、成员指示 | 子群、比值 |
| 192/193 raw | 水平 | 差分、比值 | 比值、log1p、std、上升天数、相对增量 | 水平、比值、散度、计数 |
| 194 raw | 缺失率 | 秩、max-min、std | 窗口最大、最后减最小 | 热、散度 |
| 1/3/7 normalized | 最后值 | 1、3 的诊断秩 | 7 的最后值 | 水平 |
| 194 normalized | — | — | 最后值（F10） | 水平 |
| **5/9/187/197/198 normalized** | **未用** | **未用** | **未用** | — |

### 2.2 本轮为核对「未用列 / 未用机制」做的无标签普查【本地复核】

口径：公开 train，31093 个带标签单元，每单元取 `date <= cutoff_date` 的最近 14 行（**注意：不是日历 14 天窗，库内实现用日历窗，编码代理须以库检查脚本重算，见 §4**）。`top` = 最频繁取值占比，`rhoK0` = 与 K0 基线最后值列的最大 |Spearman|。

| 候选 | 覆盖 | nunique | top | rhoK0 | 判定 |
|---|---|---|---|---|---|
| 5 normalized 最后值 | 0.998 | 49 | 0.993 | 0.43 | 排除：近常数（top>0.95） |
| 197 normalized 最后值 | 0.978 | 19 | 0.998 | 0.31 | 排除：近常数 |
| 198 normalized 最后值 | 0.998 | 19 | 0.998 | 0.32 | 排除：近常数 |
| 187 normalized 最后值 | 0.365 | 80 | 0.936 | 1.00 | 排除：型号级可观测，且与 K0 重复 |
| 5/197/198 normalized 的 first−last | ≥0.978 | ≤20 | ≥0.997 | ≤0.34 | 排除：近常数 |
| 9 normalized 最后值 | 0.998 | 100 | 0.085 | 0.595 | **采用**（F19） |
| 9 normalized 减型号中位数 | 0.998 | 129 | 0.272 | 0.238 | **采用**（F20） |
| 错误属性 5/197/198/199 非零个数（广度） | 1.0 | 5 | 0.916 | 0.80 | 排除：与 K0 同源，rho 贴近上限 0.8 |
| 5/197/198/199 距最近一次上升天数 | 仅 0.1%–1.6% 单元有上升 | — | — | — | 排除：稀有事件，窗口内几乎没有时序可言 |
| 194 raw 减同日同型号中位数（去季节/共模） | 0.998 | 74 | 0.112 | **0.88** | 排除：与 K0 的 194 基本重复 |
| 194 raw 减同日中位数 | 0.998 | 37 | 0.075 | **0.998** | 排除：同上 |
| 194 窗口后半均值−前半均值 | 0.982 | 339 | 0.171 | 0.056 | **采用**（F01） |
| 193 窗口后半均值−前半均值 | 0.982 | 2275 | 0.311 | 0.162 | **采用**（F02） |
| 192 窗口后半均值−前半均值 | 0.982 | 571 | 0.631 | 0.203 | **采用**（F03） |
| 193 后半增量−前半增量 | 0.984 | 299 | 0.424 | 0.096 | **采用**（F06） |
| 193 单日最大跳升 | 0.994 | 131 | 0.388 | 0.236 | **采用**（F09） |
| 192 单日最大跳升 | 0.994 | 53 | 0.630 | 0.194 | **采用**（F10） |
| 194 单日最大绝对步长 | 0.994 | 16 | 0.536 | 0.178 | **采用**（F11） |
| 194 日间符号翻转次数 | 1.0 | 13 | 0.147 | 0.157 | **采用**（F15） |
| 193 / 192 / 194 距最近一次上升天数（无上升记窗口长度） | 1.0 | 14–15 | 0.52 / 0.62 / 0.23 | 0.17 / 0.19 / 0.16 | **采用**（F12–F14） |
| 193 窗口内首次上升的滞后天数 | 0.682 | 13 | 0.745 | 0.06 | 排除：覆盖 <0.95（R1） |
| 9 raw 后半均值−前半均值 | 0.982 | 1325 | 0.021 | 0.012 | 排除：按构造 ≈ 24×观测天数差，是计量伪影 |

另外两类**明确排除，不是疏漏**：

- 日历特征（cutoff 星期、月份）与 `serial_number` 前缀（批次代理）：前者与确认集的「时间前后半」时序检验混淆，后者让同批次单元跨探索/确认集相关，破坏确认集的独立性，而修正需要改统计（分簇）。本轮不做；若将来做，必须先走 §7 式的方法学 PR。
- 型号级可观测列（190/187/188/196/240/241/242/191）：只剩子群形式，HDD3 的 S/D 族已用过，本轮不重复。

**结论**：现有列上能满足 R1–R3 的未用单列只有 `smart_9_normalized`；除此之外只能靠**新机制**。我没有发现「某一列有极高潜力但没人试过」的证据，所以本文不声称成功概率；风险见 §8。

## 3. `hdd_v4`：机制定义与「不是 HDD3 改写」的论证

### 3.1 与 HDD3 的区别

HDD3 的窗口统计（最后值、最大值、最后减最小、总增量/最后值、std、上升天数、型号秩）要么只用最后一行，要么对窗口内的**顺序不敏感**（最大值、std、总增量对行置换不变）。`hdd_v4` 的候选**对窗口内行的先后敏感**：把窗口内行顺序打乱后值会变。验收时可用单测证明（§5 测试 7）。这是机制上的区别，不依赖任何 HDD3 的探索/确认数字。

与 HDD3 逐条对照：

| HDD3 条目 | 最近的 HDD4 条目 | 区别 |
|---|---|---|
| F11 193 窗口增量/最后值 | F06 193 后半增量−前半增量 | F11 是总增量按水平归一；F06 是增量的**时间分布**，总增量相同、先后不同则值不同 |
| F12/F13 std | F01–F03 后半−前半均值 | std 对顺序不变；位移带符号且对顺序敏感 |
| F14 192 上升天数 | F10 单日最大跳升、F13 距最近上升天数 | F14 数个数；F13 看时点，F10 看幅度的极值 |
| F08/F09 194 最大/最后减最小 | F15–F18 符号翻转、位置 | 位置与方向变化次数，不是幅度极值 |
| F10 194 normalized 最后值 | F19/F20 9 normalized | 不同属性、不同列 |

不得把任何 HDD3 条目的探索或确认效应当作选候选的依据（含 F10/F11/F06 的列与形状）。F01 以 194 为对象但是**位移**而非水平，与 F10（194 normalized 水平）、F08（最大值）不同；它与 K0 的 rho 仅 0.056。

### 3.2 库规格

文件：`src/faultevolve/discovery/factor_library/hdd_v4.jsonl`（新）。**24 行**，id 前缀 `HDD4_`，全为新 id，不得复用 `HDD_`、`HDD2_`、`HDD3_` 任一 id。字段沿用现有格式：`factor_id/family/title/code/inputs/window_days(=14)/direction/condition/outcome/scope/falsifier/lane/confirm_eligible/source`。除控制外 `direction="auto"`、`lane="confirm"`、`confirm_eligible=true`、`source="seed_library"`、`scope="train_labeled_units"`。

窗口：与 `hdd_v3` 一致，用**日历窗** `date >= end − 13 天`（`end` 为该单元窗口内最后一行的日期）；"前半/后半" = 按该窗口内**行数**对半切，奇数时中间行归前半；窗口内行数 <6 时输出 NaN（该单元算缺失，不填补）。差分一律在窗口内相邻行上取。

| id | family | 定义 | 输入列 |
|---|---|---|---|
| HDD4_F01 | half_shift | smart_194_raw：后半均值 − 前半均值 | smart_194_raw |
| HDD4_F02 | half_shift | smart_193_raw：后半均值 − 前半均值 | smart_193_raw |
| HDD4_F03 | half_shift | smart_192_raw：后半均值 − 前半均值 | smart_192_raw |
| HDD4_F04 | half_shift | smart_7_raw：后半均值 − 前半均值（*） | smart_7_raw |
| HDD4_F05 | half_shift | smart_3_raw：后半均值 − 前半均值（*） | smart_3_raw |
| HDD4_F06 | half_shift | smart_193_raw：后半增量 − 前半增量（增量 = 半窗末值 − 半窗首值） | smart_193_raw |
| HDD4_F07 | half_shift | smart_192_raw：后半增量 − 前半增量 | smart_192_raw |
| HDD4_F08 | half_shift | smart_194_raw：后半 std − 前半 std（*） | smart_194_raw |
| HDD4_F09 | burst | smart_193_raw：窗口内相邻行最大单步上升 | smart_193_raw |
| HDD4_F10 | burst | smart_192_raw：窗口内相邻行最大单步上升 | smart_192_raw |
| HDD4_F11 | burst | smart_194_raw：窗口内相邻行最大绝对单步变化 | smart_194_raw |
| HDD4_F12 | event_timing | smart_193_raw：距最近一次上升的行数（无上升记窗口行数） | smart_193_raw |
| HDD4_F13 | event_timing | smart_192_raw：同上 | smart_192_raw |
| HDD4_F14 | event_timing | smart_194_raw：同上 | smart_194_raw |
| HDD4_F15 | event_timing | smart_194_raw：相邻行变化符号翻转次数 | smart_194_raw |
| HDD4_F16 | window_position | smart_194_raw：最后值在自身窗口内的百分位秩 | smart_194_raw |
| HDD4_F17 | window_position | smart_194_raw：窗口最大值距末行的行数 | smart_194_raw |
| HDD4_F18 | window_position | smart_194_raw：窗口最小值距末行的行数 | smart_194_raw |
| HDD4_F19 | normalized_wear | smart_9_normalized 最后值（**新列**） | smart_9_normalized |
| HDD4_F20 | normalized_wear | smart_9_normalized 最后值减同型号中位数（**新列**） | smart_9_normalized, model |
| HDD4_F21 | normalized_shift | smart_7_normalized：窗口首行 − 末行（*） | smart_7_normalized |
| HDD4_F22 | normalized_shift | smart_3_normalized：窗口首行 − 末行（*） | smart_3_normalized |
| HDD4_C01 | negative_control | 同 `HDD3_C01` 的写法，**新种子常量**（与 v1–v3 全不同），`lane=control`，`direction="+"` | smart_1_raw |
| HDD4_C02 | positive_control | smart_197_raw 14 日日历差（K0 边际），`lane=control`，`direction="+"` | smart_197_raw |

标 (*) 的 5 条在我的普查里**未实测**（F04、F05、F08、F21、F22；F21 仅知 7 normalized 的 first−last 为 nunique 50、top 0.81、rhoK0 0.10，但那是按最近 14 行而非日历窗）。它们必须过 §4.1 的离线检查；**冻结前**不过则按 §4.1 的替换规则处理，不得在看到任何探索效应后改。

覆盖**必须在填补之前量**：沙箱会用中位数填补剩余空值，使探索期覆盖恒为 1（见 KD1-H 计划 §1），所以覆盖只以库检查脚本的填补前数字为准。

### 3.3 预注册条数与规则

- 预注册 **24 条**（22 条 confirm 候选 + 2 条控制），与 HDD3 同量级，不为凑数多加：每多一条候选，m 不变（m 是进确认的条数，由 `--max-confirm 2` 决定），但探索期的选择压力增大。
- R1 填补前覆盖 ≥0.95；R2 `nunique ≥ 10` 且最频繁取值占比 ≤0.95；R3 代码 SHA256 与 `hdd_v1/v2/v3` 全部不同且库内两两不同；R4 不引用任何探索/确认效应。规则沿用 KD1-H §2，不放宽。
- **替换规则（仅冻结前、只用无标签检查结果）**：(*) 条目过不了 R1/R2 时，只可以按下列**预先写定的顺序**用备选替换同 family 的位置，不得另选：先 `smart_1_normalized` 窗口首行−末行，再 `smart_4_raw` 后半−前半均值，仅此两个备选。备选也过不了就**删条并把预注册条数降为实际条数**，预检里的 `proposed` 同步改。替换/删除表写进 PR 描述。
- 默认库仍是 `hdd_v1.jsonl`，不改默认，不加默认开启的开关。

## 4. 实现步骤与预检

### 4.1 写入前的离线、无标签检查（编码代理做，结果表贴进 PR）

用 `skill/fe-knowledge-discovery/scripts/check_factor_library.py` 对 `hdd_v4.jsonl` 逐条在公开 train 发现帧上跑，**不读标签**。输出：填补前覆盖、`nunique`、最频繁取值占比、`rhoK0`（与 K0 基线特征列的最大 |Spearman|，**新增列，见 §5**）。通过条件：

- confirm 条目：覆盖 ≥0.95、`nunique ≥10`、top ≤0.95、`rhoK0 < 0.8`（`rho_max` 的值；这只是离线预警，判定仍由流水线做）。
- 控制：沙箱可执行，`nunique > 1`。
- 24 条代码两两哈希不同，且与 v1–v3 不同。
- 库内**顺序敏感性自检**：对 F01–F18、F21、F22，把合成窗口行序反转后输出必须有至少一个单元变化（§5 测试 7）。

冻结后记录库文件 SHA256（写进 PR 描述，不写进库）。冻结后若服务器上仍有条目不可执行，视为本轮结果的一部分，不再修库。

### 4.2 服务器预检（`--explore-only`，零 LLM）

在**副本**库上运行，原 `fe.db` 前后字节与 mtime 不变。通过条件（全部满足）：

1. 退出码 0；`funnel.json`、`funnel_summary.json` 完整且可被 `json.load`。
2. `proposed` = 库实际条数（24，或 §3.3 删条后的数）；`executable ≥ proposed − 2`；`duplicate_code = 0`；`discovery_llm_error = 0`；无 `claim_write_error`。
3. `claims_tested = 0`，没有确认检验事件。
4. 库 SHA256 与 §4.1 记录一致。
5. confirm 泳道功效门通过数 ≥1。

1–4 任一不满足，或 5 为 0 → **B（预检）**，不进全流程，不修库，不换种子或 `split_salt`，不放宽功效门。

### 4.3 一次真跑

命令（门参数与 KD1-H 完全一致，**不改**）：

```bash
cp -r "$FE_RUNS_DIR/<id>" "$DST/<id>"
# 预检
fe discover factors benchmark/hdd_mvp --run-id <id> --runs-dir "$DST" \
  --library src/faultevolve/discovery/factor_library/hdd_v4.jsonl \
  --max-candidates 30 --max-confirm 2 --confirmation-fraction 0.5 \
  --min-explore-effect 0.05 --explore-only --json
# 预检通过后，去掉 --explore-only，加 --env-file，只跑一次
fe discover factors benchmark/hdd_mvp --run-id <id> --runs-dir "$DST" \
  --library src/faultevolve/discovery/factor_library/hdd_v4.jsonl \
  --max-candidates 30 --max-confirm 2 --confirmation-fraction 0.5 \
  --min-explore-effect 0.05 --env-file "$ENV_FILE" --json
fe discover report benchmark/hdd_mvp --run-id <id> --runs-dir "$DST" --json > "$DST/kd_report.json"
python skill/fe-knowledge-discovery/scripts/check_discovery_summary.py "$DST/<id>"
```

`<id>` 沿用 `89f4bdd1` 的副本（探索/确认划分由 `split_salt` 与数据决定，与 HDD3 同一划分是预期的，这是**同一数据上的新预注册**而不是新数据；报告里必须如实写这一点，不得称为独立复现）。

### 4.4 成功 / 失败判定

| 结局 | 条件 |
|---|---|
| **A（完整发现）** | 全流程完成；≥1 条 `confirmed` 或 `discovered`；带**实测**效应、CI、增量 CI、`rho_max_abs`、阴性对照 FPR ≤ 0.10、蕴含结论与卡片 id、产物路径 |
| **A-弱** | 过功效门并冻结但未 confirmed/discovered：只是线索 |
| **B（完整）** | 全流程完成，无 confirmed/discovered：负结果，不是发现 |
| **B（预检）** | §4.2 任一条不满足 |

e-BH 是否通过按 §1.1 的公式核对：报告须列出每条进确认声明的**名次、要求 e、现象 e**，并注明 α=0.05、m 为实际进确认条数。
若 CONFIRMED 且蕴含 `same`，只能写「对已知卡片的再确认」，不得写成新发现；只有 DISCOVERED 才是新知识。

## 5. 编码代理：允许与不许

### 5.1 允许改 / 新增

| 文件 | 用途 |
|---|---|
| `src/faultevolve/discovery/factor_library/hdd_v4.jsonl`（新） | §3.2，24 行 |
| `skill/fe-knowledge-discovery/scripts/check_factor_library.py` | 新增 `rhoK0` 列与 `--family-prefix`/顺序敏感性自检参数；**不带新参数时输出与行为不变**（`hdd_v3` 测试仍须通过） |
| `skill/fe-knowledge-discovery/SKILL.md` | 增 KD1-I 小节（见 §6） |
| `tests/test_factor_library_hdd_v4.py`（新） | 见下 |
| `docs/TODO.md` | 状态行 |

测试（离线、不读标签、不需 API）：

1. 库可被 `load_factor_library` 读取；恰好 24 行；id 全 `HDD4_` 前缀且无重复；不含任何旧库 id。
2. `lane`/`confirm_eligible`/`direction` 与 §3.2 一致；`scope` 为 `train_labeled_units`。
3. 代码 SHA256 与 v1–v3 全库不重，库内两两不重。
4. 输入列均在 `HDD_DISCOVERY_COLUMNS`。
5. 默认库路径仍是 `hdd_v1.jsonl`（沿用已有断言）。
6. `check_factor_library.py` 在合成小数据上通过/失败各一例，且不带新参数时输出键集合与改动前相同。
7. **顺序敏感性**：在合成窗口上，F01–F18、F21、F22 对反转行序后的值至少有一个单元变化；`hdd_v3` 的 F12（std）作对照，反转后应不变（证明测试能区分）。
8. 控制 C01 的种子常量与 v1–v3 的所有控制种子不同。
9. 普查/检查脚本源码不含对 `label`/`weight` 列的读取（沿用已有断言方式）。

### 5.2 明确不许

- 不改 `src/faultevolve/discovery/{stats.py,grading.py,preregister 相关,sandbox.py,pipeline.py,novelty.py}` 的判定逻辑，不改 `config.py` 的任何默认值，不新增改变判定的开关。
- 不放宽或修改 e-BH（`ebh_reject`、`e_from_p`、κ）、alpha、`rho_max`、`max_neg_control_fpr`、`confirmation_fraction`、`min-explore-effect`、`max_confirm`；**不把 `max_confirm` 从 2 改成 3 去补跑 HDD3_F06**，也不为本轮改成 1。
- 不改 `hdd_v1.jsonl`、`hdd_v2.jsonl`、`hdd_v3.jsonl`（SHA256 `c417237500dbf06517e3eb8505f4950f5d807038d9fdc43eb6dc0c6ee1ac3bbd` 须不变）；不删 F10/F11/F06。
- 不重跑 HDD3，不重开 discovery 重跑进化 `89f4bdd1`；不直接确认 F10/F11；不换种子或 `split_salt` 重跑选赢家；不追 38.14（只是历史观察）。
- 不读、不打印、不上传 `benchmark/hdd_mvp/data/holdout*`，不用 `--split test`；不改 `benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md}` 与 `data/`。
- 密钥只来自环境变量（`DASHSCOPE_API_KEY`、`TYPESAFE_API_KEY`、`FE_API_KEY`），不进代码、日志、提交。
- 不在仓库写 `KD1I_RESULT_*.md`；真跑结果由维护者在 PR 描述或服务器产物里记录。
- 不把 `entailment_tokens` 与旧口径 `total_tokens=0` 相加；PR #49 之后新产物的 `total_tokens` 为新口径，需标注。

## 6. Skill 更新要求（与本计划同批合入）

编码 PR 在 `skill/fe-knowledge-discovery/SKILL.md` 增「KD1-I」小节，含：

- **何时用**：HDD3 完整 B 之后要做下一轮因子发现；或要在冻结前核对 `hdd_v4` 的覆盖/退化/顺序敏感性。
- **输入**：公开数据根（`HDD_BENCH_DATA_ROOT` 或 `benchmark/hdd_mvp/data/public`）、`hdd_v4.jsonl`（必须显式 `--library`）、副本 `--runs-dir`、全流程才需 `--env-file`。
- **命令**：普查、`check_factor_library.py --library ...hdd_v4.jsonl`、`--mock` 冒烟、`--explore-only` 预检、一次全流程（§4.3）。
- **成功检查**：§4.1 表全过且 `ok: true`；§4.2 五条；§4.4 结局；报告含 P/R/F1 `n/a（无预测器）`、误报漏报 `n/a`、分阶段 token generate/repair/reflect/knowledge（无则写 0 或「未记录」，不编）、每分 token `n/a`、种子「未核实」时写未核实、e-BH 名次/要求 e/现象 e。
- **失败处理**：预检 B 或完整 B 不修库不换种子；401/403 停止并报告；429/超时按 4/8/16 秒退避；退出码非 0 先看 `<artifacts>/discovery/error.txt`；原 `fe.db` 字节或 mtime 变化则作废。
- **禁止**：同 §5.2。

本规划 PR 同时在 skill 现有 KD1-H 小节末尾加一行「下一步：见 KD1-I 计划」，并更新 `docs/TODO.md`。

## 7. 并行轨道：e-BH 校准器的合成功效研究（可选，不阻塞 §4）

动机：e-BH 在 α=0.05、m=2 时，k=1 需要 p ≤ 1.56e-4（z≈3.8）；同样的数据上 BH 只需 p ≤ 0.05·1/2。HDD3 里 F10/F11 的确认 CI 都排除 0，却过不了 e-BH，说明 κ=0.5 的校准器在 n≈15 千、正例 555 的量级上功效可能很低。这是方法学问题。

规则（硬性）：

- **只用合成数据**：以 n=15418、正例=555 为形状，生成无信号（全局零）与有信号（AUROC−0.5 ∈ {0.01, 0.02, 0.03, 0.04, 0.05, 0.06}）两类，比较 κ 取值或 BH 对照下的 FDR 与功效，m ∈ {1,2,3}。网格在看结果前写入文档。**不得读取任何候选的探索/确认结果，也不得把 F10/F11/F06 的数字当作输入。**
- 产出是一份研究文档与离线脚本，**不改默认值**。若结论支持更换校准器，只能作为**新家族、新预注册、默认关的开关**，对合入后新登记的家族生效；**不得回头适用于 HDD3，也不得用于 HDD4 的这次真跑**。
- 它**不能替代**第 4 节的可执行发现实验；二者互不阻塞。

## 8. 风险与诚实表述

- HDD3 中最好的确认效应是 +0.03～+0.04；§1.1 说明 k=1 需要约 z≥3.8。`hdd_v4` 的候选与 K0 的相关很低（0.06–0.26），这有利于通过 `functional_novel`，但也意味着**可能增量信号弱**。我不声称成功概率，也不用此估算替代真跑。
- HDD4 与 HDD3 在同一数据划分上，探索/确认集与 HDD3 重叠。新预注册、新库 SHA256 避免的是「候选选择偏差」，不是「数据复用」。报告须如实写。
- 22 条候选的探索期选择压力存在；只靠 `max_confirm=2` 与 e-BH 控制，这是现有门的设计，不改。
- (*) 条目未实测，可能被 §4.1 删除或替换，条数可能小于 24。
- 种子：HDD3 的 `split_salt` 默认 `fe-kd-2026`、`bootstrap_b` 默认 500；本轮实际服务器种子**未核实**，以运行日志为准。

## 9. 若 KD1-I 仍是 B：下一步（不是「停下来等用户」）

按顺序，每步都有可执行内容，且每步都不改 HDD3/HDD4 的判定：

1. **完整 B 或预检 B 后**：写一份只含事实的 B 报告（漏斗、主因、对照、token、库 SHA256），然后进入 2。
2. **§7 的合成功效研究**若尚未做则做；结论只对**之后**登记的家族生效。
3. **KD1-J 候选机制（只在 KD1-I 完成后规划，尚无实测结论）**：跨属性顺序关系（如 193 上升先于 194 位移的滞后相关）、窗口内相邻行 `date` 间隔不规则性（报告间隙，不同于 v2 的计数）。进入前须像本文一样先做无标签普查并给出新机制理由；不得以 HDD4 的探索效应选候选。
4. 任何一轮的结局只记 A / A-弱 / B，不改门、不换种子、不事后加测。

## 10. 未记录

- 本文表中带 (*) 的 5 条（F04、F05、F08、F21、F22）以及 §3.2 的 F16–F18、F19 的 `nunique` 等：库检查脚本跑出之前**未实测**。
- 蕴含命中的文献卡片 id、F11 的方向/时序/bh 逐项值：沿用上一份计划，仍未记录。
- 服务器实际种子与 `bootstrap_b`：未核实。
- HDD4 的任何探索/确认结果：尚未运行。
