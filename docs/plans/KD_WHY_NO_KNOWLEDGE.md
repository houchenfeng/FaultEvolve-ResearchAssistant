# 为什么还测不出新知识：诊断与最小下一步实验

状态：仅计划，未改任何运行时代码，未开真实进化。基线：`main` @ `9a3643f`。
目标读者：另一个编码模型，照此可直接做最小实验，无需再问。

## 0. 结论（先读这一节）

1. **失败卡在最前面的两层：「提出 claim」的质量和「沙箱」。** 到目前为止，没有任何一条由 LLM 生成的 claim 走到过统计检验。统计检验、现象卡、机制、锦标赛这四层，对真实 LLM claim 来说都是「还没走到」，不是「测过且失败」。
2. **数据够做现象级特征因子，不需要降级到换数据集。** 我在本仓库的 train 数据上离线核实：确实存在不在基线里、且通过全部统计门槛的特征（见 3.3）。所以「数据不够」不是当前失败原因。
3. **锦标赛不是当前失败原因。** 默认关闭；Run B 和短探针都在锦标赛之前就停了；代码上也不可能跑到（见 4）。在至少一条 claim 通过沙箱并拿到统计结果之前，不要讨论锦标赛有没有用。
4. **现在的架构有一个值得警惕的设计张力，但不是 bug：** 新颖性门槛要求特征和基线（K0 的 9 个 SMART 列）不冗余。凡是只用 K0 列做的特征，几乎注定过不了新颖性门槛。如果 LLM 的 claim 主要来自已进化程序的代码差分（多半在 K0 列上做文章），会系统性地得到「显著但不新」的结果。这要靠最小实验验证，不要先改架构。

## 1. 已核实的事实与来源

| 事实 | 来源 |
|---|---|
| train 31093 serial / 428921 行，正例 1104；val 30754 / 422167，正例 756；test 30759，正例 770 | `benchmark/hdd_mvp/data/meta.json`（本地核实） |
| 每盘 history 最多 14 行（实测中位数 14，均值 13.8，最小 1） | 本地跑 `HDDAdapter.discovery_frames` 核实 |
| 标签：cutoff 之后 7 天内故障为 1；每个 serial 只有一行标签 | `meta.json` 的 `horizon_days=7`，`train_labels.csv` 列为 `serial_number,model,cutoff_date,label,weight` |
| 发现帧 history 现为 35 列：`serial_number`、`date`、`model`、`capacity_bytes`、22 个 raw、9 个 normalized（含 K0 的 9 列） | `src/faultevolve/tasks/hdd_adapter.py` `HDD_DISCOVERY_COLUMNS` 与 `discovery_frames`；本地实测 shape `(428921, 35)` |
| PR #17 的修复已在 main：缺列、runner 写 stderr、`schema_note` 由实际列派生 | `sandbox.py` `_RUNNER`、`hdd_adapter._discovery_schema_note` |
| 修复后的合成 claim 探针在真实数据上通过（2 passed，约 43 秒） | `tests/test_kd_sandbox_probe.py`，我本地跑了 |
| 确认集/探索集：按 serial 哈希切分，`confirmation_fraction=0.3`。train 上确认集 9262 个 serial / 327 正例，探索集 21831 / 777 正例 | `discovery/splits.py` + 本地核实 |
| Run B `f9752fcd`：ROS 38.14，3 条 claim 全部沙箱失败，机制 0，对战 0，证书 0；2026-09-29 短探针 2 条 claim、0 条测试 | 任务说明给出；**制品路径 `/home/hcf/...` 在本环境不存在，我无法复核，以下按任务说明采信** |

**无法核实的部分：** Run B 当时的 `evolve.yaml`（是否开了 tournament）和 3 条 claim 的具体代码与错误。下面第 4 节的结论不依赖这个，因为代码路径本身已足以说明问题。

## 2. 逐层判断：测到了，还是没走到

流水线（`src/faultevolve/discovery/pipeline.py` `DiscoveryRound.run`）依次是：

```
收集候选 → 提出 claim → 沙箱 → 统计检验 → 对照实验 → 分级(含 LLM 蕴含判断) → 现象卡 → [锦标赛交接 → 机制 → 对战 → 证书]
```

| 层 | 代码位置 | Run B / 短探针的结果 | 判断 |
|---|---|---|---|
| 收集候选 | `engine._harvest_discovery_candidates`（来源：`discover_op` 的原始 claim、正向 insight、top 节点；后两者要 `translate_claim` 从代码差分译成 claim） | 提出了 3 / 2 条 | **走到了。** 但 claim 的内容质量是未知数，见 5.3 |
| 提出 claim | `claims.py` `translate_claim` / `extract_claim_from_response`（要求含 `def feature(`） | 同上 | **走到了** |
| 沙箱 | `sandbox.py` `run_feature` | 全部失败：`KeyError: 'model'`、裸 `exit 3` | **测到了，且失败原因已定位并修复**：history 缺列、runner 不写 stderr。修复后的验证只用了**手写 claim**，**LLM 生成的 claim 过沙箱的情况从未被观察过** |
| 统计检验 | `stats.test_feature`，在 `pipeline.py` 沙箱成功之后 | 0 条 | **没走到**（`skipped: no_tests`） |
| 对照实验 | `controls.run_controls`，在 `tested_claims` 非空之后 | 0 | **没走到** |
| 分级 | `grading.grade_claim` + `novelty.judge_entailment`（调 LLM） | 0 | **没走到** |
| 现象卡 | `promotion.promote_claims` | 0 | **没走到** |
| 机制 / 对战 / 证书 | 见第 4 节 | 0 / 0 / 0 | **没走到** |

关键代码：`pipeline.py` 在 `if not tested_claims:` 处直接 `return RoundResult(..., "no_tests", {})`，之后所有层都不会执行。

### 2.1 一个会让下次失败难以诊断的隐患

`pipeline.py` 每条 claim 的处理被一个宽泛的 `except Exception` 包住，只记一个名为 `discovery_llm_error` 的事件，然后 `continue`。这意味着：沙箱通过之后，**任何统计层的异常**（reindex、bootstrap、sklearn 报错等）都会被记成「LLM 错误」，claim 状态停在 `proposed`，`claims_tested` 不加。`fe discover run` 的 JSON 输出（`cli.py` `discover_run`）只汇总 `claim_sandbox_failed`，**不会展示 `discovery_llm_error`**。

所以下一步实验必须直接读事件表里的 `discovery_llm_error` 事件，不能只看 CLI 的 JSON；成功标准里也要写「`discovery_llm_error` 为 0，或者明确记录其内容」。本计划不要求修这个（不改运行时代码）；是否修由后续决定。

## 3. 数据够不够做现象级特征因子

### 3.1 规模

- 确认集只有 **327 个正例**（train 的 30%）。探索集 777 个正例。
- 统计门槛（`grade_claim` + `stats.py`）对一条 claim 的实际要求：
  - 确认集上 `signed_effect = AUROC − 0.5` 的组 bootstrap CI 不含 0，且方向与预注册一致；
  - 确认集按 cutoff 日期分前后两半，两半符号都与方向一致（`temporal_ok`）；
  - BH 与 eBH 同时通过。**单条 claim 时 eBH 要求 e ≥ 20，即 p ≤ 6.25e-4**（`e = 0.5 / √p`），比 α=0.05 严得多。边缘显著的特征（p≈0.002）会被判 `undetermined`；
  - 与基线（K0 的 9 列，每列取 last / 14 步差分 / 非零个数）的最大 |Spearman| < 0.8，**并且**探索集上增量 AUROC 的 bootstrap CI 下界 > 0（`functional_novel`）；
  - 负对照假阳性率 ≤ 0.10；LLM 蕴含判断结果为 `none`（否则是 `same`→confirmed、`opposite/different_magnitude`→revised、`unknown`→undetermined）。
- 327 个正例足以检出 AUROC 偏离 0.5 约 0.03 以上的单变量效应；但**增量** AUROC 的量级只有 0.001–0.01，是真正的瓶颈。

### 3.2 离线核实方法（可复现）

只用 train 数据（不碰 holdout，不碰 val），调用仓库自带的 `discovery_frames`、`split_masks`、`test_feature`、`incremental_auroc`、`build_baseline_features`，对一批简单特征算：确认集 AUROC/CI/p，以及探索集 `rho_max_abs`、增量 AUROC 及 CI。缺失值按沙箱的规则用中位数填。脚本是一次性的，没有提交；实验阶段由执行者重写（见 6.1）。

### 3.3 结果摘要（bootstrap_b=500，单次种子，仅作量级参考）

**K0 列上的简单特征：边际很显著，但没有任何增量。**

| 特征 | 确认集 AUROC | p | 与基线 max\|ρ\| | 增量 AUROC [CI] |
|---|---|---|---|---|
| `smart_197_raw` last | 0.773 | <1e-4 | 1.00 | −0.0002 [−0.0009, 0.0002] |
| 197 在 14 天内的变化 | 0.630 | <1e-4 | 0.42 | −0.0000 [−0.0014, 0.0008] |
| 5 的变化 | 0.626 | <1e-4 | 0.52 | −0.0002 [−0.0005, 0.0001] |
| 187 的变化 | 0.608 | <1e-4 | 0.62 | −0.0013 [−0.0050, 0.0017] |
| `smart_9_raw`（通电时长） | 0.608 | <1e-4 | 1.00 | −0.0000 [−0.0002, 0.0001] |

这些全都会被判「显著但不新」。

**非 K0 列（不在基线里）：有几个同时通过所有数值门槛。**

| 特征 | 确认集 AUROC | p | 与基线 max\|ρ\| | 增量 AUROC [CI] |
|---|---|---|---|---|
| `smart_240_raw` last | 0.566 | <1e-4 | 0.49 | +0.0056 [0.0007, 0.0105] |
| `smart_4_raw` 14 天变化 | 0.566 | <1e-4 | 0.11 | +0.0029 [0.0009, 0.0057] |
| `smart_196_raw` 14 天变化 | 0.547 | <1e-4 | 0.31 | +0.0012 [0.0004, 0.0021] |
| `smart_3_raw` last（方向为负） | 0.451 | 0.0023 | 0.31 | +0.0082 [0.0008, 0.0167]，但 p 过不了 eBH |
| `smart_1_raw` last | 0.546 | 0.0023 | 0.30 | +0.0048 [0.0006, 0.0087]，但 p 过不了 eBH |

另一些非 K0 特征（如 `smart_193_raw`）增量为负。

### 3.4 对数据问题的判断

- **数据够检验现象级特征因子，不需要降级，也不需要换数据集。** 至少 3 个非 K0 特征在数值上能通过 CI、新颖性与 eBH 的全部门槛。
- 但**这些数字是我在确认集上直接看出来的**，不能直接当预注册 claim 使用（会污染确认集）。执行者必须先在**探索集**上选特征并锁定方向，再到确认集上检验（见 6.1）。
- 效应都很小（增量 AUROC 个位数千分点）。即使过了门槛，也只是「现象级的弱因子」，不是强结论。这与计划要求的「先发现现象级新特征因子并测试是否有效」一致，不要夸大。
- 「方向必须预注册」意味着：LLM 或人猜错符号（如 `smart_3` last）会直接被判 refuted。实验里要把这个记下来，它是 claim 质量的一部分。

## 4. 锦标赛

事实（均已读代码核实）：

1. **默认关闭。** `config.py` `TournamentConfig.enabled = False`；`DiscoveryConfig.enabled` 也默认 False；`benchmark/hdd_mvp/evolve.yaml` 里 `discovery:` 整段是被注释掉的。不能改这些默认。
2. **交接条件很靠后。** `pipeline.py` 末尾：只有 `cfg.tournament.enabled and controls.passed` 且存在等级为 CONFIRMED / REVISED / DISCOVERED 的 claim 时，才生成 `extras["kd2"]`。`engine._maybe_run_tournament` 在没有 `kd2` 时直接 `return`。
3. **前面任何一层断了，就走不到。** 无沙箱成功 → `no_tests` 提前返回；有统计结果但全部 refuted / undetermined → 没有交接。
4. **`fe discover run` 永远走不到锦标赛。** `cli.py` `discover_run` 只调 `kd.run(...)`，不调 `engine._maybe_run_tournament`，且不打开 tournament。所以「短探针」这类命令即使把 claim 全部修好，也不会产生机制。要看锦标赛，必须单独在引擎循环里开（见 7）。
5. Run B 的 3 条 claim 全部沙箱失败，按第 3 条，**无论 Run B 是否开了 tournament，都不可能跑到锦标赛**。

结论：**当前没有任何证据说明锦标赛有用或没用。** 不要把它当成当前失败的原因，也不要为了「让它被跑到」而放宽前面的门槛。

## 5. 失败原因的总判断

### 5.1 数据不够？— 否（对现象级特征而言）

见第 3 节。

### 5.2 锦标赛赛制有问题？— 无法判断，还没走到

见第 4 节。

### 5.3 真正的嫌疑（需最小实验验证，不要先改代码）

按可能性从高到低：

1. **LLM 生成的 claim 的质量。** `translate_claim` 把「父子代码差分 + insight」翻成「一个 `feature(history)` 函数」。进化出来的改动常常是模型超参、采样、融合，不是特征；译成特征后可能读不存在的列、返回类型不对、或只是 K0 列上的变换。PR #17 只保证「读 schema 里承诺的列」能过沙箱，不保证 LLM 会写出合格的特征。
2. **新颖性门槛对 K0 衍生特征的结构性不友好**（3.3 第一张表）。若 claim 多半来自 K0 列，会得到一批「显著、不新」的结果，仍然看不到 `discovered`。
3. **eBH 对单条或少量 claim 很严**（p ≤ 6.25e-4），弱因子容易落在 `undetermined`。这不是缺陷，但判读结果时要区分「undetermined 是因为 eBH」还是「因为 LLM 蕴含返回 unknown」。
4. **第 2.1 节的错误掩盖**：下次若出现「沙箱通过但 `claims_tested` 仍为 0」，应首先查 `discovery_llm_error`。

## 6. 最小下一步实验（只跑发现，不跑进化，不要求机制/证书）

总原则：不改 `src/`；不改 `benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md}` 与 `data/`；不读 `data/holdout*`；密钥只来自环境变量；得分仍只来自本地评测器；不改任何默认开关；不删任何测试。

### 6.1 实验 E0：无 LLM 开销，手写现象级特征，走完 claim → 沙箱 → 统计 → 分级

目的：隔离出「数据与统计门槛」这一层，回答「如果 claim 写得好，系统能不能给出 discovered」。

做法：

1. 新增一个**非运行时**脚本 `scripts/kd_phenomenon_probe.py`（不放在 `src/`，不被任何入口调用，不影响测试）。仿照 `tests/test_kd_sandbox_probe.py`：构造 `DiscoveryRound`，通过 `candidates` 的 `raw_claim` 路径（第 6 个元素）直接注入 claim，`source="top_node"`，`HDDAdapter`、`TaskSpec` 取自 `benchmark/hdd_mvp`，`card_path` 用临时目录里的 `knowledge/cards.jsonl` 副本（仓库里的 `cards.jsonl` 受字节保护，不许写）。
2. `llm_call` 用桩：对 `KD_ENTAIL` 返回 `{"card_id": null, "relation": "none"}`。**在输出里明确标注「语义新颖性未被检验，仅检验统计与对照」**（与 `test_kd_sandbox_probe.py` 的约定一致）。
3. 配置：`DiscoveryConfig(enabled=True, max_claims_per_round=8, ...)`，`bootstrap_b=500`、`neg_control_repeats=5`、`planted_strengths` 用默认值（这次要看真实的 p 与对照，不要缩水）；`tournament` 保持默认关闭。
4. 选特征的流程（避免污染确认集）：
   - 第一步：只在探索集（`split_masks` 的 explore 部分）上，对一份候选清单算单变量 AUROC，**确定每个特征的方向**，并记录下来；
   - 第二步：把方向写进 claim，再让 `DiscoveryRound` 在确认集上检验。
   - 候选清单至少包含：（a）3 个以上非 K0 列特征：`smart_240_raw`、`smart_4_raw` 的 14 天变化、`smart_196_raw` 的 14 天变化、`smart_1_raw`、`smart_3_raw`、`smart_192_raw`；（b）2 个以上 K0 衍生的对照特征（如 `smart_197_raw` 的 last、变化），用来验证「显著但不新」会被正确判掉；（c）1 个纯噪声特征（如 `smart_10_raw`，几乎常数；或对 `smart_5_raw` 做随机置换后的特征），用来验证不会被误判。
5. 每条 claim 的 `feature_code` 只用 `history` 里的列（`serial_number`、`date`、`model`、`capacity_bytes`、22 个 raw、9 个 normalized），返回以 `serial_number` 为索引的 `pd.Series`，用 `groupby` 聚合，不做 `.to_frame()`。
6. 输出一张表（写入 `docs/` 之外的临时目录或实验记录，不进入仓库的受保护目录）：每条 claim 的等级、确认集 AUROC/CI/p、`rho_max_abs`、增量 AUROC CI、`temporal_ok`、`bh_pass`/`ebh_pass`、`controls.passed`、`neg_fpr`、planted 恢复率，以及**哪一道门槛挡住了它**。

成功标准（任一即成功，其余为有价值的负结果）：

- 至少一条现象级特征通过沙箱并有完整统计结果（`claims_tested ≥ 1`，有 `claim_tests` 记录），**并且**表中能说清每条 claim 被哪一道门槛放行或拒绝；
- 对照特征（K0 衍生）被判为非 discovered，噪声特征被判为 refuted 或 undetermined；
- 若有 claim 得到 `discovered`，记录它的所有数值，注明「语义新颖性未检验」。

失败时必须记录：真实错误文本（沙箱 `error` 字段、`discovery_llm_error` 事件内容），不要只写「失败了」。

### 6.2 实验 E1：真实 LLM，在已有运行的副本上只跑发现

目的：回答「LLM 生成的 claim 现在能不能过沙箱并拿到统计结果」——这是第 2 节中唯一还没观察过的环节。

前提：需要服务器上的 Run B 制品（`/home/hcf/nas_hcf_data/faultevolve/runs/final_B/f9752fcd/`）和 `DASHSCOPE_API_KEY` 等环境变量；本环境没有。执行者在服务器上做。

做法：

1. 把 `f9752fcd` 的运行目录**复制**一份（`fe discover run` 会写库，不要在原件上跑）。
2. 在 `main` 上运行 `fe discover run benchmark/hdd_mvp --run-id <副本id> --runs-dir <副本目录> --max-claims 3 --json`（参数以 `cli.py` `discover_run` 为准）。不要加 `--mock`（`MockLLM` 不产出可解析 claim，会得到 0 条 claim）。
3. 运行后**直接查事件表**，不只看 JSON：
   - `claim_proposed`、`claim_sandbox_failed`（含 `error_type`、`error`）、`claim_sandbox_finished`、`claim_stats_finished`、`claim_tested`、`claim_graded`；
   - **`discovery_llm_error`**（见 2.1，统计层异常会记在这里）；
   - 每条 claim 的 `feature_code` 与它依据的 `origin_node_id`、`source`（`insight` / `top_node` / `discover_op`）。
4. 保存：claim 的 `feature_code`、状态、`claim_tests` 行。

成功标准（二选一即算完成）：

- 至少一条 LLM claim 通过沙箱并写入 `claim_tests`（有统计结果）；
- 或者每条失败的 claim 都有**真实、非空、非裸 `exit N`** 的错误记录，并且该错误能归到某一类（缺列 / 返回类型 / 语法 / 超时 / 覆盖率 / 常量 / 统计层异常 / LLM 解析失败）。

**不要求**产出机制、证书或 discovered 卡。

### 6.3 判读规则（E0 与 E1 做完后）

| 观察 | 说明 | 下一步 |
|---|---|---|
| E0 有 discovered，E1 里 LLM claim 仍大量失败 | 瓶颈在 claim 生成 | 改进 claim 来源与提示（例如更明确地要求「只用 history 里的列」「返回 Series」），不动统计与锦标赛 |
| E0 有 discovered，E1 里 LLM claim 过沙箱但全是「显著、不新」 | 瓶颈在 claim 内容偏向 K0 衍生 | 考虑让 `discover_op` 路径引导 LLM 看非 K0 列（另开计划） |
| E0 里非 K0 特征也全部过不了门槛 | 统计门槛过严，或数据对这类特征确实不足 | 此时才讨论降低 eBH 门槛/换统计量，并且要先写计划 |
| E1 出现 `discovery_llm_error` 且内容不是 LLM 相关 | 2.1 的隐患成真 | 另开修复，把统计层异常单独记账 |
| 以上都没问题且有 `discovered` 等级的 claim | 现象级知识发现已经打通 | 才进入第 7 节 |

## 7. 锦标赛：之后再谈

只有当 E0 或 E1 里出现至少一条 `confirmed / revised / discovered` 等级的 claim，且 `controls.passed` 为真，才有东西可交给锦标赛。那时：

- 在**配置副本**里把 `discovery.enabled=true`、`discovery.tournament.enabled=true`（引擎要求锦标赛必须依附于发现，`EvolveConfig._tournament_requires_discovery`），在**引擎循环**里小预算跑一次；`fe discover run` 做不到这一点（4.4）。
- 不改默认开关，不改 `benchmark/hdd_mvp/evolve.yaml`。
- 对照问题是「有锦标赛 vs 没锦标赛」，用已有的 `tests/test_engine_tournament.py`、`tests/test_kd_offline_replay.py` 的结构做参考，但这是另一份计划的内容，本计划不展开。

## 8. 约束清单（执行者逐条核对）

- [ ] 没有修改 `src/` 下任何文件。
- [ ] 没有修改 `benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md}` 与 `benchmark/hdd_mvp/data/`；没有读取 `data/holdout*`。
- [ ] 没有删除任何测试；没有把任何默认开关改为开启（`discovery.enabled`、`discovery.tournament.enabled` 都保持 False）。
- [ ] 没有把密钥写进代码、配置、日志、提交。
- [ ] 实验用的 `cards.jsonl` 是副本，仓库内的 `benchmark/hdd_mvp/knowledge/cards.jsonl` 字节未变（可参照 `test_kd_sandbox_probe.py` 的断言）。
- [ ] 没有拿 LLM 的输出当作任何节点的分数。
- [ ] 文档与面向用户的文字用简体中文，代码标识符与注释用英文。
