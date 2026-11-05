# KD1-H 完整负结果之后的下一轮规划

日期：2026-10-04。性质：**仅规划文档，不改功能代码，不写新库，不含新运行**。
上游：[KD1H_NEW_FACTOR_FAMILY_PLAN_2026-10-04](KD1H_NEW_FACTOR_FAMILY_PLAN_2026-10-04.md)（库与脚本已由 PR #47 合入，HEAD `418510b`）。
标注：【用户提供】服务器实测，数字原样抄录，缺的写「未记录」；【已核实】读本仓库代码；【推算】由代码和实测推出。

## 0. 结论（先看这里）

1. **KD1-H 记为完整的 B，不是发现。** F10、F11 是线索，F06 过功效门但没被选中，三条都不是发现。
2. **拦住 F10/F11 的是 e-BH（`grade_undetermined:ebh`），不是蕴含。** 蕴含 `same` 在代码里本来就不会把一条声明降成 undetermined（§2）。
3. **不用同一套门再碰这两条。** 不放宽任何门，不补跑 F06，不换种子，不直接确认。HDD3 家族在当前门下就此封存。
4. **唯一建议做的代码改动是一个不改统计判定的计量小修：** `fe discover factors` 写的 `run_summary.total_tokens` 只等于 `discovery_tokens`，漏掉了 `entailment_tokens`（§4）。它不是知识发现。
5. **暂不启动下一轮因子发现。** 连续 KD1-F、KD1-G、KD1-H 三轮都没有 confirmed/discovered。若以后再做，必须是新家族、新 id、新预注册、新库 SHA256，并且先写出独立于这次数字的理由（§5）。

## 1. 本次服务器实测【用户提供】

| 项 | 值 |
|---|---|
| 代码 HEAD | `418510b526191bc07dd6a9e216d0518121d92a40` |
| 库 `hdd_v3.jsonl` SHA256 | `c417237500dbf06517e3eb8505f4950f5d807038d9fdc43eb6dc0c6ee1ac3bbd`，跑前跑后一致 |
| 原库 `benchmark/hdd_mvp/.fe/runs/89f4bdd1/fe.db` | 跑前跑后都是 7180288 字节，mtime `2026-10-04 13:35:54.276235368 +0800` |
| 产物 | `/home/hcf/nas_hcf_data/faultevolve/runs/kd1h_20261004/preflight/89f4bdd1`、`.../full/89f4bdd1` |

**预检（`--explore-only`）**：17:32:10–17:38:23（北京时间），退出码 0，墙钟 372.771 秒。漏斗 proposed 24 / executable 24 / coverage_ok 24 / deduped 24 / explore_incr 4 / power_gate 3 / frozen 2 / confirmed_stats 0 / discovered_or_confirmed 0。duplicate_code 0，discovery_llm_error 0，无 claim_write_error，claims_tested 0。generate/repair/reflect/knowledge token 均 0，每分 token n/a。阴性对照 FPR 未记录（预检未做）。

**功效门**：confirm 泳道过 3 条。

| 因子 | 探索效应 | 增量 CI 下界 | 结局 |
|---|---|---|---|
| HDD3_F06 | +0.06507745382021135 | +0.000027583162697253415 | `not_selected_explore_gate`（max_confirm=2，没冻结） |
| HDD3_F10 | +0.057104776465425666 | +0.00558111701814995 | 冻结 |
| HDD3_F11 | +0.05422845186047398 | +0.00021507530485437884 | 冻结 |

其余候选 F01、F02、F04、F05、F07–F09、F12–F16、S01–S03、D01–D03、C01、C02 主因都是 `explore_no_increment`；F03 是 `explore_below_power_gate`。C02 效应 +0.1162640619042905，增量 CI 下界为负；对照不是发现。

**全流程（只跑一次）**：17:42:42–17:52:03（北京时间），退出码 0，墙钟 559.807 秒。漏斗前段与预检相同，confirmed_stats 2，discovered_or_confirmed 0。没有 confirmed 或 discovered；两条进确认后都是 undetermined，原因 `grade_undetermined:ebh`。没有 error.txt。

| 项 | HDD3_F10（C-89f4bdd1-0010） | HDD3_F11（C-89f4bdd1-0011） |
|---|---|---|
| 确认集 n / 正例 | 15418 / 555 | 15418 / 555 |
| 确认效应 | +0.029594924939068123 | +0.0409636845349689 |
| 确认 CI | [+0.0041280550911533, +0.054387149843128584] | [+0.018626732285030236, +0.06417494217321389] |
| 探索增量 | +0.012267068777080286 | +0.007385917140996114 |
| 增量 CI | [+0.00558111701814995, +0.02012232908040724] | [+0.00021507530485437884, +0.014400195612876148] |
| rho_max_abs | 0.1749786749257025 | 0.1621918809140578 |
| 方向 / 时序 / bh | 过 / 过 / 过 | 报告中仅 e-BH 为未过原因；方向、时序、bh 的逐项值未记录 |
| e-BH 要求 e | 20 | 40 |
| e1 / e2 | 0.033613201471327736 / 0.02262251013573069 | 0.04191864081828289 / 0.04049476215658132 |
| 现象 e | 3.5390676738372777 | 19.54380904342485 |
| 蕴含 / controls_ok / functional_novel | `same` / true / true | `same` / true / true |

**对照与计量**：阴性对照 FPR 0.0（10 次，0 次误报），controls passed true。S 族没进确认。P/R/F1 与误报漏报 n/a（无预测器）。分阶段 token generate/repair/reflect/knowledge 仍全是 0；另记 `entailment_tokens` 7951，`total_tokens` 记为 0。**这两个数不要加成一个总数写进结果。** 每分 token n/a。蕴含命中的文献卡片 id：未记录。

## 2. 代码解读：e-BH 与蕴含各拦住了什么【已核实】

### 2.1 分级顺序（`discovery/grading.py::grade_claim`）

1. 先判 REFUTED：确认 CI 跨 0、方向不符、或时序为 False。F10、F11 都没触发。
2. 再判 UNDETERMINED：时序为 None，**或 `bh_pass` 与 `ebh_pass` 任一未过**，或蕴含为 `unknown`。
3. 通过上面之后才看蕴含：`same` → CONFIRMED（挂到该文献卡片）；`opposite`/`different_magnitude` → REVISED；`none` 且 `functional_novel` 且 `controls_ok` → DISCOVERED。

`pipeline.py::_grade_primary_failure` 的主因顺序是：时序 None、蕴含 unknown、`ebh` 未过。F10、F11 时序有值、蕴含不是 unknown，所以主因落到 `ebh`，与实测一致。

### 2.2 e-BH 拦住了什么

- `stats.py::e_from_p`：`e = κ·p^(κ-1)`，κ 默认 0.5，即 `e = 0.5/√p`。`ebh_reject`：把 e 从大到小排，第 k 名要 `e ≥ m/(k·α)`。
- `pipeline.py` 的 m 是**实际进入确认检验的声明数**（`len(tested_claims)`），这里 m=2，不是 24。所以多重比较惩罚已经是最小的；要求 e=20 反推 α=0.1（20 = 2/(1·0.1)，【推算】），第 2 名要求 40。
- 因此 e-BH 的难度主要来自**校准器本身**：第 1 名要 e≥20，等价于置换 p ≤ (0.5/20)² = 6.25e-4；第 2 名要 e≥40，等价于 p ≤ 1.5625e-4。确认效应只有 +0.03 到 +0.04 的量级，n=15418、正例 555，这个量级的 p 到不了。
- F11 的现象 e=19.54 离 20 很近，但**近不是过**。不得因此放宽。
- 注意：`e1`、`e2` 在代码里是确认集按时间前后两半各自算的效应（`signed_effect`），用于时序检查，**不是 e 值**。结果表里沿用了用户提供的名字，读时别与 e-BH 的 e 混淆。
- 【待核】按 `order_by_e` 的实现，e 更大的应当拿到更低的要求。用户提供的配对是 F10 要求 20、e=3.54，F11 要求 40、e=19.54，与「按 e 降序排名」的期望方向相反。无论哪种配对，两条都不够：最大的 e 19.54 < 20。编码代理应只读 `funnel.json`/`funnel_summary.json` 核对配对（见 §6 的核对项）；若确有排名与展示不一致，那是**展示/记录问题**，不改变 `ebh_reject` 的判定，也不得借此改判。

### 2.3 蕴含 `same` 没有拦住什么，也不会产生什么

- `same` 没有拦住 F10/F11。它们是被 e-BH 拦在前面的，蕴含的结果根本没用上。
- 若 e-BH 过了，`same` 会得到 **CONFIRMED（对已有文献卡片的再确认）**，不是 DISCOVERED（新知识）。所以即使门被放宽，F10/F11 最好也只是「确认了一条已知知识」。这是**不应为它们放宽门**的另一个理由：放宽得到的至多是已知结论的再确认，换不来新发现。
- 蕴含判断来自 LLM（`novelty.py::judge_entailment`），它**只决定 confirms/revises/discovered 的标签，不产生分数**，与「LLM 输出不当节点分数」的硬规则一致。
- `functional_novel`（`rho_max_abs < rho_max` 且增量 CI 下界 > 0）两条都为 true，说明它们在统计上相对基线有增量；这与「文献上是否已知」是两个维度。

## 3. 三条路的比较与决定

| 路径 | 内容 | 决定 | 理由 |
|---|---|---|---|
| (a) 同库同门补跑/改门 | 放宽 e-BH 或 alpha、max_confirm 改 3 补跑 F06、换种子重跑、直接确认 F10/F11 | **不做** | 都是在看到结果后调门或重抽样选赢家；F06 增量下界只有 2.8e-5，也不是强线索；`same` 最多得到再确认 |
| (b) 立刻开新家族 KD1-I | 新库、新预注册、一次真跑 | **暂不做** | 连续三轮 B；没有独立于这次数字的新理由前，再开一轮只是在增加试验次数。条件见 §5 |
| (c) 记为终点 + 不改判定的计量小修 | HDD3 封存；修 `total_tokens` | **采用** | 负结果完整、可复现、没有被门外的东西污染；小修只让后续报告更准 |

结论：**本次记为终点。** F10、F11 保留为线索写进报告，不再用这套门做任何后续检验。不做 (a) 中的任何一项。

## 4. 计量小修（可选，单独一个编码 PR，不改统计判定）

**问题【已核实】**：`cli.py` 的 `discover factors` 写 `run_summary.json` 时，`"total_tokens": engine.metrics.discovery_tokens`。而 `common/metering.py::add_llm_call` 对 `entailment` 用途只累加 `entailment_*` 与 `total_prompt/completion_tokens`，**不累加 `discovery_tokens`**。所以本次 `discovery_tokens=0`，`total_tokens=0`，而 `entailment_tokens=7951`。这是「总计漏计蕴含 token」的记录错误，不是蕴含没有发生。`discovery_token_share` 用 `metrics.total_tokens` 作分母，口径也因此与写入的 `total_tokens` 不一致。

**修法（最小）**：`total_tokens` 改取 `engine.metrics.total_tokens`（即 prompt+completion 的全部），其余字段不动。**不**改 `discovery_tokens` 的含义，**不**把 `entailment_tokens` 并进 `discovery_tokens`。

**边界**：

- 只影响 `run_summary.json` 的计量字段，不碰 `stats.py`、`grading.py`、`preregister`、`sandbox.py`、阈值或门。
- 已有产物（包括本次 `89f4bdd1` 两次）**不回写、不重算**；结果仍按实测记 `total_tokens=0`、`entailment_tokens=7951`，并注明「旧口径」。
- 修后若新运行得到 total 与 entailment 数字，另行记录，不拿它当知识发现，也不与旧数字相加。
- 测试：用 mock LLM 触发 entailment 调用，断言 `total_tokens == generate+repair+reflect+discovery+entailment+...` 的实际总和即 `metrics.total_tokens`，且 `discovery_tokens` 不变。现有 `tests/test_discovery_disabled.py` 比较 on/off 的 `total_tokens` 须仍通过（先核对该测试走的是哪条路径）。

## 5. 下一轮因子发现的前置条件（暂不启动）

只有同时满足下列条件才可新开一轮，且需先有单独的规划 PR：

1. **新家族**：新 id 前缀、新库文件、新预注册、新库 SHA256；不复用 `HDD3_` 的 id；不把这次任何探索效应、确认效应或功效门结果当选候选依据（包括 F10/F11/F06 的列和形状）。
2. **覆盖依据仍是不看标签的普查**，规则可复算，离线检查表在 PR 里。
3. **说明独立于这次数字的理由**，例如新的数据列、新的物理机制，而不是「上次差一点」。
4. **门全部沿用现状**。若有人认为 e-BH 校准器对该样本量功效过低，那是方法学问题：必须在不看任何候选结果的条件下，用合成数据单独论证并另起 PR，对未来新家族生效，**不得回头适用于 HDD3**，也不得与某一轮真跑绑定。
5. 一次真跑；只用 HDD；不读 holdout，不用 `--split test`。

## 6. 编码代理：允许与不许

**本 PR（文档）改动**：`docs/plans/KD1H_NEXT_ROUND_AFTER_FULL_B_PLAN_2026-10-04.md`（本文件）、`docs/TODO.md` 顶部一行。

**后续编码 PR 允许改（仅 §4 的小修）**：

| 文件 | 用途 |
|---|---|
| `src/faultevolve/cli.py` | `discover factors` 的 `run_summary.total_tokens` 取 `engine.metrics.total_tokens` |
| `tests/` 下新增或修改的发现摘要计量测试 | §4 的测试 |
| `docs/TODO.md` | 状态行 |

可选核对（只读，不改代码）：用 `funnel.json`/`funnel_summary.json` 核对 §2.2 的配对；结果以文字写进 PR 描述，不写 `KD1H_RESULT_*.md`。

**明确不许**：

- 不放宽或修改 e-BH（`ebh_reject`、`e_from_p`、κ）、alpha、`rho_max`、`max_neg_control_fpr`、`confirmation_fraction`、`min-explore-effect`、`max_confirm`；不把 `max_confirm` 从 2 改成 3 去补跑 F06。
- 不改 `stats.py`、`grading.py`、`preregister` 逻辑、`sandbox.py` 的门，不改默认库与默认开关。
- 不用同一份库换种子或 `split_salt` 重跑；不把 F10/F11 直接确认；不改 `hdd_v3.jsonl`（库已冻结，SHA256 见 §1）。
- 不重跑进化，不追 38.14（只是历史观察，不作因果）。
- 不读、不打印、不上传 `benchmark/hdd_mvp/data/holdout*`，不用 `--split test`；不改 `benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md}` 与 `data/`。
- 不把 `entailment_tokens` 7951 与 `total_tokens` 0 相加成总数；不回写旧产物；不把本地数字当服务器实测。
- 密钥只来自环境变量，不进代码、日志、提交；不在仓库写 `KD1H_RESULT_*.md`。

## 7. 预检与完整发现的定义（沿用，不改）

- **预检算过**（沿用 KD1-H 计划 §4.2）：退出码 0；`funnel.json`、`funnel_summary.json` 可被 `json.load`；`proposed` 与 `executable` 达标，`duplicate_code=0`，`discovery_llm_error=0`，无 `claim_write_error`；`claims_tested=0`；库 SHA256 与冻结记录一致；confirm 泳道功效门通过数 ≥1；原 `fe.db` 字节与 mtime 不变。**HDD3 的预检已按此通过**，不再重做。
- **完整发现（A）**：至少一条 `confirmed` 或 `discovered`，带**实测**效应、CI、增量 CI、`rho_max_abs`、阴性对照结果、蕴含结论和产物路径；S 族另附成员指示量参照。
- **A-弱**：过功效门并冻结但未 confirmed/discovered，只是线索。F10、F11 属于此类；F06 连冻结都没有。
- **完整的 B 不是发现**，只是带诊断的负结果。本轮属于此类。

## 8. Skill

本计划不需要新 skill。已有 `skill/fe-knowledge-discovery/SKILL.md` 的 KD1-H 小节足够；若 §4 的小修合入，仅在该小节补一句「`total_tokens` 口径自该修复起含 entailment；旧产物为旧口径」。

何时用、输入、命令、成功检查、失败处理，仅在将来新开一轮因子发现时按 KD1-H 计划 §7 执行：成功检查为离线检查表全过 + 预检条件满足；失败（预检 B、功效门为 0、原 `fe.db` 变化）一律记 B 或作废，不修库、不换种子；401/403 停止并报告；429/超时按 4/8/16 秒退避；退出码非 0 先看 `<artifacts>/discovery/error.txt`。

## 9. 未记录

- 蕴含命中的文献卡片 id、F11 的方向/时序/bh 逐项值：未记录。
- §2.2 的配对核对结果：未核对。
- 修复后的 token 数字：尚未运行。
