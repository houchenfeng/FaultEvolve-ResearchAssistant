# FaultEvolve 开发 TODO / 交接文档

> **2026-10-05 冻结声明 C-89f4bdd1-0010（HDD3_F10 窗口末 smart_194_normalized）审讯/对局/跨集复验：** 规划见 [C89_WINDOW_END_SMART194_CAUSAL_DEBATE_TRANSFER_PLAN](plans/C89_WINDOW_END_SMART194_CAUSAL_DEBATE_TRANSFER_PLAN.md)。编码：`fe discover replay-claim`（`discovery/replay.py`）；NAS 真跑另做。

> **2026-10-05 KD 放宽轨（R1+R3）代码已合入待 PR：** opt-in `--track-label` / `--explore-incr-rule` / `--min-incr-ci-low` / `--fdr-mode`；默认严格轨与 `hdd_v1.jsonl` 不变；真跑见 README「KD 放宽轨」与 NAS `kd1i_20261004` 预检 `funnel.json`。

> **2026-10-04 WebUI + SmartMem 已按 [`MERGE_WEBUI_SMARTMEM_PLAN_2026-10-04`](plans/MERGE_WEBUI_SMARTMEM_PLAN_2026-10-04.md) 选择性合入 main**（契约 1.11.0、SmartMem 数据层与评测器、引擎停跑与任务无关因子加载；未带入 `556ca01` 发现大块与 `hdd_v1` 库改写）。

> **2026-10-04 KD1-I `hdd_v4` 离线实现（冻结 23 条，原预注册 24）：** 顺序敏感因子库、`rhoK0`/家族前缀/顺序敏感性离线检查、9 项测试与 Skill 操作说明已合入；§4.1 无标签检查 `ok: true`（库 SHA256 见 PR #51）。`HDD4_F22` 经备选 2 仍不过 R2 已删条。默认库仍为 `hdd_v1.jsonl`；服务器 `--explore-only`/全流程**还没跑**。见 [KD1I_ORDER_SENSITIVE_FAMILY_PLAN_2026-10-04](plans/KD1I_ORDER_SENSITIVE_FAMILY_PLAN_2026-10-04.md)。

> **2026-10-04 KD1-H 完整负结果之后的下一轮规划：** 记为完整的 B，不是发现；F10/F11 只是线索，被 e-BH 拦住（蕴含 `same` 未起作用），不放宽任何门、不补跑 F06、不换种子；仅建议一个不改判定的计量小修（`total_tokens` 漏计 `entailment_tokens`）。见 [KD1H_NEXT_ROUND_AFTER_FULL_B_PLAN_2026-10-04](plans/KD1H_NEXT_ROUND_AFTER_FULL_B_PLAN_2026-10-04.md)。仅文档。

> **2026-10-04 KD1-H 新家族 `hdd_v3`（24 条预注册）：** 库 `src/faultevolve/discovery/factor_library/hdd_v3.jsonl`、离线普查/库检查脚本与 `tests/test_factor_library_hdd_v3.py` 已合入；默认库仍为 `hdd_v1.jsonl`。服务器预检/全流程由维护者按 [KD1H_NEW_FACTOR_FAMILY_PLAN_2026-10-04](plans/KD1H_NEW_FACTOR_FAMILY_PLAN_2026-10-04.md) §4.2–§5 执行，不在仓库写 `KD1H_RESULT_*.md`。

> **2026-10-04 下一轮因子发现规划（KD1-H，新家族 `hdd_v3`，24 条预注册）：** 依据无标签覆盖普查，不复用上一轮 9 条 id，不用探索效应选候选；含子群家族（191/240/241）的采用决定、预检通过条件、完整发现定义、编码代理允许/禁止范围与 skill 要求，见 [KD1H_NEW_FACTOR_FAMILY_PLAN_2026-10-04](plans/KD1H_NEW_FACTOR_FAMILY_PLAN_2026-10-04.md)。**编码 PR 已交付库与脚本；服务器结果未记录。**

> **2026-10-04 KD1-G 预检未通过（outcome B）：** `executable=18<24`，9 条不可执行均为数据覆盖/构造常数，**不使用修库名额**；另需修 mock 的 `claim.id` 撞键与 funnel 的 numpy 序列化两个退出 bug。见 [KD1G_PREFLIGHT_B_AND_CRASH_FIX_PLAN](plans/KD1G_PREFLIGHT_B_AND_CRASH_FIX_PLAN_2026-10-04.md)。仅规划，未改功能代码。

> **2026-10-03 规划入口（HDD 全量自动调优运行）：** 先修 CI 与 HPO 接线，再拉服务器代码并做一次约 150k token 的真实运行（账本 + 随机 HPO + patch），见 [计划](plans/AUTOTUNE_FULL_RUN_PLAN_2026-10-03.md)、[执行 TODO](plans/AUTOTUNE_FULL_RUN_TODO_2026-10-03.md)、[设计备忘](design/07-HDD全量自动调优运行-设计备忘.md)。仅规划，尚未执行；38.14 只是历史观察点。

> **2026-10-04 kd1f 完整负结果之后（下一次发现 KD1-G）：** 代码已合入（方向 `auto`、功效门、泳道、`hdd_v2.jsonl`、`--explore-only` 等）；**服务器真实跑**与结果表见 [KD1G_NEXT_DISCOVERY_PLAN_2026-10-04](plans/KD1G_NEXT_DISCOVERY_PLAN_2026-10-04.md) §6–§7（合并后由维护者执行，不在本仓库写 `KD1G_RESULT_*.md`）。
> **2026-10-04 运行后规划入口（89f4bdd1 之后）：** HDD 自动调优真实运行已完成（best 25.23，初始 22.81，+2.4275；discovery 全 0）。下一步是解耦的原子因子发现 KD1-F，不是重跑进化。诊断、成功定义、命令、失败处理、token 报告和给 composer-2.5 的 TODO 见 [KD_NEXT_RUN_PLAN_2026-10-04](plans/KD_NEXT_RUN_PLAN_2026-10-04.md)。仅规划，尚未实现。

> **2026-10-04 规划入口：** 当前优先推进自动调优与可靠进化，见 [改进设计](design/06-自动调优与进化搜索改进设计.md) 和 [执行 TODO](plans/AUTOTUNE_EVOLUTION_TODO_2026-10-04.md)。知识发现后续见 [KD 建议](plans/KD_NEXT_STEP_RECOMMENDATION_2026-10-04.md)。这些是待实施规划；以下 9 月 29 日进度表作为历史交接记录，其版本、测试数和服务器状态需重新核查。

> 用途：让任何 AI 编码代理（Codex 等）或新成员**只读本文件**就能接着开发。本文件提交为 `docs/TODO.md`，方案文件放在 `docs/plans/`。
> 更新时间：2026-09-29（UTC）。
> **Cursor cloud agent 额度已于 2026-09-28 23:05 用完**，后续可能由其他 AI 接手，所以本文件必须能独立使用。
> 仓库：`houchenfeng/Self-evolution-optimization-agnet`（私有）。
> 基线：main = **`112b73a`**（433 tests）；泛化 PR 分支 `cursor/dataset-generalization-e0a1-7930`。
> 标注约定：
> - **【已核实】**：通过 GitHub 读取代码、PR 描述或文件确认。
> - **【用户提供】**：来自用户给出的运行结果或决定。
> - **【推算】**：由已核实事实推出。
> - **【未核实】**：估计、假设或需要确认的内容。
>
> **不得编造结果**。表中所有"待填"项都必须用真实运行结果填写。

---

## 0. 进度表（总览）

最终顺序（用户决定）：PR #3.1 hotfix → PR #4 → PR #6 → PR #5 → PR #7 → KD1+KD2 → PR #8 → 泛化 → 最终 README。

| 顺序 | 步骤 | 分支（建议名） | 状态 | 依赖 | 实跑最优 ROS | refine valid | 备注 |
|---|---|---|---|---|---|---|---|
| — | PR #1 本地最小进化循环 | `cursor/local-evolution-loop-fc6f` | ✅ 已合并（`e750157`） | — | 34.96 | 待补 | 128 个测试 |
| — | PR #2 repair 算子 + 可配置存储 + Jev 中继配置 | `cursor/pr2-repair-storage-config-98f2` | ✅ 已合并（`b59c39e`） | PR #1 | 32.57（run `3efade04`） | 7/10 | 169 个测试 |
| — | PR #3 ERA 知识注入 + 预检/性能门/smoke test | `cursor/knowledge-injection-c879` | ✅ 已合并（squash `f7678c4`） | PR #2 | **36.50**（run 5A `07aaa958`） | 3/10 | 236 个测试 |
| 0 | **PR #3.1 搜索修复（hotfix）** | `fix/search-hotfix-3-1` | ✅ 已合并（`63ed5d1`） | PR #3 | 真实运行统一延后 | 待填 | 反思路由、stop_reason、错误尾部、smoke 计时、事件计数 |
| 1 | PR #4 Jev 快速判断（预筛 + UCT 先验） | `cursor/jev-quick-screening-348a` | ✅ 已合并（`63394c1`） | PR #3.1 | 真实运行统一延后 | 待填 | 用户决定所有真实运行最后统一执行 |
| 2 | PR #6 dev 集错例画像 + 评估器感知提示 | `cursor/pr6-error-profiling-934d` | ✅ 已合并（`b70ecb5`） | PR #4 | 真实运行统一延后 | 待填 | 290 个测试；实跑延后 |
| 3 | PR #5 多目标节点价值 + token 预算控制 | `feat/node-value-budget` | ✅ 已合并（`bfeabed`） | PR #6 | 真实运行统一延后 | 待填 | 308 个测试；实跑延后 |
| 4 | PR #7 召回/阈值算子 + 算子老虎机 | `cursor/operators-bandit-622d` | ✅ 已合并（`fb18475`） | PR #6、PR #5 | 真实运行统一延后 | 待填 | 327→398 测试；实跑延后 |
| 5a | KD1 现象层知识发现 + 发现卡回灌 | `cursor/knowledge-discovery-kd1-f6c2` | ✅ 已合并（`6bbc040`） | PR #3、PR #7 | 真实运行延后 | 待填 | 后端完成；**真实运行统一延后** |
| 5b | KD2 机理层 + 数据裁决锦标赛 + 否证证书 + 报告 | `cursor/knowledge-discovery-kd2-1a9d` | ✅ 已合并（`a37f88f`） | KD1 | 真实运行延后 | 待填 | 417 测试；实跑统一延后 |
| 6 | PR #8 交叉/集成算子 | `cursor/crossover-ensemble-a189` | 🔄 PR 中 | PR #7（最好也有 PR #6） | 真实运行延后 | 待填 | 417→433 测试；实跑统一延后 |
| 7 | 泛化：Backblaze 真实 + SSD/内存 stub | `cursor/dataset-generalization-e0a1-7930` | 🔄 PR 中 | PR #3 / #8 | 真实运行统一延后 | 待填 | 2026-09-29：仅硬盘数据；Backblaze 真实适配器，SSD+SmartMem stub；433→492 tests |
| 8 | 最终 README（框架、结果指标表、技能表） | `docs/final-readme` | ⬜ | 全部 | — | — | 竞赛截止 2026-10-31 |

分支名前缀不限于 `cursor/`，接手的 AI 可以自定。每个 PR 合并后必须更新本表：状态、合并提交、测试数、实跑 run id、各项指标。

---

## 1. 项目背景

### 1.1 竞赛
- 赛题：北航 × 华为，A 题「基于大模型 Agent 的器件故障预测算法及自动化调优」。赛题名称见 `docs/design/01-系统总体设计.md`【已核实】；主办方为北航 × 华为【用户提供】。
- 截止日期：**2026-10-31**【用户提供】。
- 评审维度（`docs/design/01-系统总体设计.md` §10）【已核实】：
  | 维度 | 证据 |
  |---|---|
  | 预测性能 | 私有测试集 ROS、F1、误告率、漏告率 |
  | 复杂性 | 最优解运行时间、特征数、模型大小；每轮 token；每单位提升的 token |
  | 自动化 | 人工介入次数；达到目标分所需的轮次和时间；本地评估次数 |
  | 泛化 | 同一套 Skill 用于多种器件；val/test 间隙 |
- 对标对象：百度伐谋（FAMOU / FM Agent，arXiv:2510.26144）。对照方案见 `docs/design/03-伐谋对照实验方案.md`，网页端提交说明见 `benchmark/hdd_mvp/FAMOU_任务说明.md`【已核实，文件存在】。
- 设计文档中原计划的消融实验（每组 3 个种子）与用户最新规则冲突。**以最新规则为准**：每个 PR 只做一次真实运行，不做消融或稳定性实验（§4）。

### 1.2 系统一句话
FaultEvolve 是一个以 Skill 为入口的自演化算法系统：
- LLM（千问 qwen3-coder-plus 负责生成，qwen3-max 负责推理/反思）在**解树**上用 UCT 选节点、refine/repair 生成候选程序；
- 本地评估器 ROS 打分；
- 三层反思（实现/设计/假设）+ 分支记忆 + 跨枝经验传播；
- ERA 风格知识卡注入（PR #3）；
- 计划中：Jev 先验与预筛（PR #4）、错例画像、多目标价值、算子老虎机、知识发现、交叉算子、跨数据集泛化。

### 1.3 评估器事实（`benchmark/hdd_mvp/evaluator.py`，受保护，禁止修改）【已核实】
- `ROS = 100 × (0.5·F1_p10 + 0.3·AUPRC + 0.2·R@FAR) × time_factor`，其中 `time_factor = min(1, 600 / 运行秒数)`，默认 900 s 超时。
- `F1_p10`：正负分层 bootstrap 200 次后，取机队加权 F1 的第 10 百分位（**不是**"Precision=10% 时的 F1"）。
- `R@FAR`：按 score 排序，在健康盘误告率 ≤ **0.2%**（`FAR_BUDGET = 0.002`）时可达到的召回。
- 输出的 `metric` 键：`precision, recall, f1, f1_p10, f1_boot_std, auprc, recall_at_far, false_alarm_rate, missed_detection_rate, alarms_per_1k_disks, quality, run_time_s, time_factor, split`。**没有 `analysis` 字段**。
- 候选程序契约：`python cand.py --data-dir <dir> --split <val|test> --out <csv>`，输出列为 `serial_number, score, alarm`。
- 静态检查禁止：`eval_only|holdout|val_labels|test_labels`、`.parent`/`..`、`listdir/glob/walk`、`getcwd/chdir`、`subprocess/os.system/socket/urllib/requests`。这些字符串即使出现在字符串或注释中也可能被拒（只剥离 `#` 之后的部分）。
- 数据根目录可用环境变量 **`HDD_BENCH_DATA_ROOT`** 覆盖（默认 `benchmark/hdd_mvp/data`）。
- 数据划分（`data/meta.json`）：
  | 划分 | cutoff 范围 | 样本数 | 正例 | 负样本权重 |
  |---|---|---|---|---|
  | train | 2024-07-14~09-23 | 31,093 | 1,104 | ≈9.86 |
  | val | 2024-10-14~12-24 | 30,754 | 756 | ≈10.07 |
  | test | 2025-01-14~03-24（holdout，仓库中没有） | — | — | — |
  - 共 31 个 SMART 列；history 14 天，horizon 7 天。
- 基线：规则基线 ROS ≈ 12.9，初始解 `init.py` ROS ≈ 22.8（README）【已核实】；mock 运行最优 22.81【已核实，PR #1 描述】。

---

## 2. 当前状态

### 2.1 真实运行结果汇总【用户提供】
| PR / run | run id | 最优 ROS | P | R | F1 | AUPRC | 误告率 | 漏告率 | refine valid | 总 tokens | 每 ROS 点 tokens | 墙钟 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PR #1 | 待补 | 34.96 | .272 | .558 | .366 | 待补 | 待补 | 待补 | 待补 | 待补 | 待补 | 待补 |
| PR #2 | `3efade04` | 32.57 | .268 | .439 | .333 | .319 | 0.30% | 56.1% | 7/10 | 84,649 | 待补 | 待补 |
| PR #3 run 1 | `7f959947` | 35.93 | .279 | .515 | .362 | .348 | 0.33% | 48.5% | 0/7 | 131,895 | 待补 | 待补 |
| PR #3 run 2 | `c2621658` | 36.33 | .307 | .478 | .374 | .339 | 0.27% | 52.2% | 2/10 | 172,003 | 待补 | 待补 |
| PR #3 run 3 | `b40af888` | 32.23 | .252 | .542 | .344 | .275 | 0.40% | 45.8% | 5/10 | 149,948 | 待补 | 待补 |
| PR #3 run 4 | `dc791631` | 32.35 | .261 | .536 | .351 | .258 | 0.38% | 46.4% | 2/10 | 189,686 | 待补 | 待补 |
| **PR #3 run 5A（知识开，head 824c64a，即合并版本）** | `07aaa958` | **36.50**（最优节点 `80036f59`） | .281 | .537 | .369 | .340 | 0.34% | 46.3% | 3/10 | 119,205 | 8,704 | 2,024 s |
| PR #3 run 5B（知识关） | `1e95f28e` | 29.81 | .274 | .382 | .319 | .266 | 0.25% | 61.8% | 9/10 | 101,487 | 14,495 | 2,424 s |

- run 5A 分阶段 tokens：generate 63,253、repair 45,257（含 smoke/性能门自修复）、reflect 10,695、knowledge 5,114。第 2 轮达到目标 33.7（5.4 分钟，27.5k tokens）。
- **当前基线 = run 5A：ROS 36.50**。合并规则（§4.4）以此为参照。
- 观察【推算】：
  - 知识开/关的单次对比（36.50 vs 29.81）支持知识注入有效，但每组只有一次运行，而单次噪声约在 32–36 之间，还不算定论。
  - 知识开时 refine valid 很低（3/10），知识关时为 9/10。这说明卡片引导的改动更容易出错，也是 PR #3.1 要改进的点。
  - PR #1 最优高于 PR #2，同样可能来自单次运行方差。

### 2.2 PR #3 状态与运行史
- **已 squash 合并为 `f7678c4`**【用户提供】。
- 内容【已核实，PR 描述与代码】：
  - `src/faultevolve/knowledge/{loader.py, retriever.py}`
  - `benchmark/hdd_mvp/knowledge/{cards.jsonl(51 张), sources.yaml(41 个来源), expert.md, README.md}`
  - 检索：优先级 + 标签匹配 + 贝叶斯 Δ + UCB 探索、类别多样性、排除本分支被否证卡和祖先已采纳卡
  - `<adopted_cards>` 解析；`card_stats` / `branch_offered_cards` / `branch_refuted_cards` / `node_adopted_cards` 表
  - 无效采纳惩罚（`-2·noise_delta`）
  - `common/precheck.py` 自动重写：`fillna(method=)`→`ffill/bfill`、删除 `verbose_eval`/`early_stopping_rounds`、`--data_dir`→`--data-dir`、移除没有 `eval_set` 的 early_stopping
  - `HDD_DATA_SCHEMA` 注入真实列名
  - **性能门**：检测 `for sn in df['serial_number'].unique()`、`groupby().apply(lambda)`，LLM 自修复一次，仍不通过则拒绝，计入 `perf_rejections`
  - **smoke test**：约 2% 序列号采样（服务器上为 616/31,093 盘），60 s 超时，使用 `sys.executable`，失败时走同一自修复路径，计入 `smoke_failures/smoke_fixes`；repair 路径同样经过性能门与 smoke test
  - LLM 瞬态错误重试（4/8/16 s）
  - 崩溃时也写出产物（`status: "crashed"`）
  - `knowledge.enabled` 开关
  - `run_local_evolution(adapter=…, task_dir=…)` 参数
  - `evolve.yaml`：`target_score: 33.7`、`stop_at_target: false`、`reflection.max_repair_attempts: 1`
- 各次运行暴露的问题与修复：
  | run | 暴露的问题 | 修复 |
  |---|---|---|
  | run 2 | `fillna(method=)`、`verbose_eval`、argparse `--data_dir` | precheck 自动重写 |
  | run 4 | 逐盘 for 循环 / groupby-apply 超时 | 性能门、schema 注入 |
  | 76c2556 服务器检查 | smoke test 用了全量数据；pandas 3 下 `pd.np` 报错；裸 `python3` 缺依赖 | 采样公式、`numpy.random.default_rng`、`sys.executable` |
- 遗留问题 → PR #3.1（§5 步骤 0）和 §6。

### 2.3 仓库架构地图（main `f7678c4`，即 PR #3 合并后）【已核实，按 PR #3 head 824c64a 读取】
```
AGENTS.md                      给 AI 的硬规则（不改受保护文件、不读 holdout、密钥只从环境变量读取）
.env.example                   环境变量模板（不要提交真实 .env）
pyproject.toml / requirements.txt   Python ≥3.12；numpy、pandas、pydantic、typer、openai、httpx、pyyaml 等；控制台命令 fe
benchmark/hdd_mvp/
  evaluator.py init.py problem.md prompt.md   受保护：禁止修改
  data/{public,eval_only}/, meta.json          受保护：禁止修改；eval_only 禁止读取
  prepare_data.py              从 Backblaze 原始数据生成本基准（泛化时参考）
  candidates/rule_baseline.py  规则基线
  evolve.yaml                  进化配置（budget/selection/widening/insights/stop/judge/llm/reflection/knowledge/seed；PR #3 另有 smoke_test）
  knowledge/                   PR #3：cards.jsonl、sources.yaml、expert.md、README.md
  FAMOU_任务说明.md、config.yaml
src/faultevolve/
  cli.py                       typer：fe doctor、fe evolve local（--mock -n --resume --target-score --runs-dir --artifacts-dir --env-file --json --seed）
  config.py                    EvolveConfig（from_yaml、with_overrides）；各子配置 BudgetConfig/SelectionConfig/JudgeConfig/LLMConfig/ReflectionConfig/KnowledgeConfig…
  cloud/engine.py              EvolutionEngine：initialize/run/_run_one_iteration/_attempt_repair/_apply_reflection/_reflect_*/_retrieve_knowledge_cards(PR3)/_log_event；run_local_evolution、_write_artifacts(PR3)
  cloud/selection.py           UCTSelector（_compute_q：子树 max 回传，_get_prior：均匀）；get_jev_prior、compute_tau_weighted_prior（未使用）；get_era_knowledge_cards（PR3 已实现，main 返回 []）
  cloud/operators.py           OperatorContext（set_error_profile/set_branch_memory/set_refuted_hypotheses/set_foreign_insights…）、RefineOperator、RepairOperator、OPERATOR_INSTRUCTIONS(REFINE/INJECT/TRANSPLANT/REPAIR)、USER_MESSAGE_TEMPLATE、select_operator（固定返回 REFINE）、get_operator_thompson_sample（未使用）、classify_error
  cloud/insights.py            LayeredReflector（layer 仅限 implementation/design/hypothesis）、InsightExtractor、BranchMemoryManager（沿父链保留 top-5 |z|）、get_foreign_insights（其他分支的正/负 insight）、update_insight_reputation（pass）
  cloud/judge.py               JudgeClient 全是桩（node_prior/prescreen/…）、PrescreenResult、should_defer_candidate
  cloud/llm.py                 DashScopeLLM（chat/chat_for_reasoning，重试）、MockLLM（脚本化）、create_llm_call_record
  cloud/store.py               SQLite（WAL）表：experiment、node（按列存储）、insight、llm_call、event；PR3 加 card_stats、branch_offered_cards、branch_refuted_cards、node_adopted_cards
  cloud/tree.py                Tree（load_from_store、add_node、get_global_best、repair 链、get_regular_children_count…）、create_child/init/repair_node
  common/schemas.py            Node/NodeArtifact/NodeEvidence/EvaluationResult(extra=forbid)/Insight/BranchMemory/OperatorType/NodeStatus/HypothesisStatus/RunSummary…
  common/metering.py           RunMetrics（add_llm_call(metrics, purpose) 按 generate/reflect/repair(/knowledge) 分类；to-target 统计）
  common/codecheck.py          full_check、extract_adopted_cards_from_response(PR3)
  common/precheck.py           PR3：precheck_and_fix、is_api_compat_error、get_error_fix_hint
  common/textutil.py           extract_json_from_response、unified_diff、sanitize_error_info、truncate_text
  knowledge/loader.py          PR3：REQUIRED_FIELDS、VALID_CATEGORIES(9 类)、load_cards、load_cards_from_dir（只读 cards.jsonl）
  knowledge/retriever.py       PR3：CardRetriever、CardStats、RetrievalContext
  tasks/protocol.py            TaskSpec、EvalResult、@runtime_checkable TaskAdapter(load_task/evaluate/get_noise_delta/static_check/constraints/context_keywords/api_notes)
  tasks/hdd_adapter.py         HDDAdapter（噪声阈值、约束、schema、smoke_test(PR3)）
  tasks/famou_adapter.py       通用伐谋四件套适配器
  worker/runner.py             FakeAdapter/FakeTaskSpec（测试用）
skill/
  fe-evolve-manager/           SKILL.md、scripts/run_mock.sh、references/
  fe-knowledge-injection/      PR3：SKILL.md、scripts/build_cards.py（卡片生成的唯一来源）、references/{expert.md,sources.yaml}
tests/                         test_adapters/codecheck/config/engine/hdd_evaluator/insights/knowledge(PR3)/llm/metering/pr2_features/selection/store + fixtures/toy_task
docs/design/01~04、docs/dev/MVP开发指南.md、sessions/*.json（AI 开发会话记录）
```
- PR #3 合并后，旧 main（b59c39e）的三个问题已解决【已核实，PR #3 代码】：`run_local_evolution` 写死 HDDAdapter（现已有 `adapter` 参数）、`_attempt_repair` 引用未定义的 `repair_count`、`generate_tokens` 不累计。

---

## 3. 如何运行

### 3.1 服务器布局【用户提供，已在服务器上验证】
| 项 | 路径 / 值 |
|---|---|
| 代码 | `/home/hcf/faultevolve/code`（当前在 `f7678c4`） |
| conda 环境 | `faultevolve`：pandas **3.0.6**，LightGBM 4.x。基础 `python3` 没有 pandas/lightgbm，必须先激活环境 |
| 数据 | NAS `/home/hcf/nas_hcf_data/faultevolve/data/hdd_mvp`。代码目录中的 `benchmark/hdd_mvp/data` 是指向它的**软链**；smoke test 也通过这个软链读数据（已验证） |
| fe.db | 本地默认位置 `/home/hcf/faultevolve/code/benchmark/hdd_mvp/.fe/runs/<exp>/fe.db`（每个几 MB）。**不要设置 `FE_RUNS_DIR` 或 `--runs-dir` 指向 NAS**：SQLite 不能放网络文件系统，CLI 会拒绝启动 |
| 运行产物 | NAS `/home/hcf/nas_hcf_data/faultevolve/runs/<name>`，通过 `--artifacts-dir` 指定 |
| 根盘 | 剩余约 **4 GB**。不要在根盘缓存数据副本或大产物 |
| 密钥 | `/home/hcf/faultevolve/.env`（**永远不要 cat/echo/打印**，只用 `fe doctor` 检查是否存在）：`DASHSCOPE_API_KEY`，PR #4 起加 `MIYANG_API_KEY` |
| Jev 参考实现与密钥来源 | `/home/hcf/geolocate-fast-code`（**只读**，不要修改） |

- 评估器每次评估都会把数据复制到临时目录【已核实】，每次约几十 MB，结束后删除。根盘紧张时可以把 `TMPDIR` 指向非根分区（可选）【推算】。

### 3.2 标准命令
```bash
# 0. 进入环境（每次都要）
cd /home/hcf/faultevolve/code
conda activate faultevolve
git fetch origin && git checkout <branch> && git pull --ff-only
pip install -e . -q
ls -l benchmark/hdd_mvp/data        # 应为指向 NAS 的软链

# 1. 密钥只检查存在性，不打印值
fe doctor --env-file /home/hcf/faultevolve/.env --task-dir benchmark/hdd_mvp --json

# 2. 测试（离线，不需要密钥）
python -m pytest tests/ -q 2>&1 | tail -3         # main f7678c4：236 passed

# 3. 离线 mock 冒烟
fe evolve local benchmark/hdd_mvp --mock -n 3 --json

# 4. 真实运行（每个 PR 一次，10 轮；<name> 例如 pr31_hotfix）
ART=/home/hcf/nas_hcf_data/faultevolve/runs/<name>
mkdir -p "$ART"
nohup fe evolve local benchmark/hdd_mvp -n 10 --env-file /home/hcf/faultevolve/.env \
  --artifacts-dir "$ART" --json > "$ART/run.log" 2>&1 &
echo $! > /tmp/fe_run.pid
tail -3 "$ART/run.log"
```

### 3.3 恢复中断的运行
```bash
cd /home/hcf/faultevolve/code
fe evolve local benchmark/hdd_mvp --resume <exp_id> \
  --artifacts-dir /home/hcf/nas_hcf_data/faultevolve/runs/<name> \
  --env-file /home/hcf/faultevolve/.env
# fe.db 在默认位置 benchmark/hdd_mvp/.fe/runs/<exp_id>/fe.db，不要传 --runs-dir
```

### 3.4 产物
| 路径 | 内容 |
|---|---|
| `<runs_dir>/<exp>/fe.db` | SQLite |
| `<artifacts>/<exp>/run_summary.json` | 运行摘要 |
| `tree.json` | 进化树 |
| `events.jsonl` | 事件日志 |
| `programs/<node>.py` | 所有候选程序 |
| `logs/<node>.log` | 错误日志 |

### 3.5 真实运行报告提取脚本（在 PR #3.1 或 PR #4 中固化为 `skill/fe-evolve-manager/scripts/report_run.py`）
```python
# 用法：python report_run.py <runs_dir>/<exp>/fe.db <artifacts>/<exp>/run_summary.json
import json, sqlite3, sys
db, summ = sys.argv[1], json.load(open(sys.argv[2]))
con = sqlite3.connect(db); con.row_factory = sqlite3.Row
best = con.execute("SELECT evidence_json FROM node WHERE id=?", (summ["best_node_id"],)).fetchone()
m = json.loads(best["evidence_json"])["evaluation"]["metric"]
rows = con.execute("SELECT operator, status, evidence_json FROM node").fetchall()
ref = [r for r in rows if r["operator"] == "refine"]
ref_valid = sum(1 for r in ref if (json.loads(r["evidence_json"] or "{}").get("evaluation") or {}).get("validity", 0) >= 1)
timeouts = sum(1 for r in rows if "timeout" in ((json.loads(r["evidence_json"] or "{}").get("evaluation") or {}).get("error_info") or "").lower())
gain = summ["best_score"] - summ.get("initial_score", 0)
print(json.dumps({
  "ROS": summ["best_score"], "P": m.get("precision"), "R": m.get("recall"), "F1": m.get("f1"),
  "AUPRC": m.get("auprc"), "false_alarm_rate": m.get("false_alarm_rate"), "miss_rate": m.get("missed_detection_rate"),
  "total_tokens": summ.get("total_tokens"),
  "tokens_by_stage": {k: summ.get(k) for k in ["generate_tokens","repair_tokens","reflect_tokens","knowledge_tokens","jev_tokens","discovery_tokens"] if k in summ},
  "tokens_per_ros_point": (summ.get("total_tokens", 0) / gain) if gain > 0 else None,
  "wall_time_s": summ.get("wall_time_s"),
  "refine_valid": f"{ref_valid}/{len(ref)}", "timeouts": timeouts,
}, ensure_ascii=False, indent=2))
```
- 字段名依据 `store.py` DDL 与 `RunSummary`【已核实】。`initial_score` 在 main 的 `RunSummary` 中存在【已核实】。
- `status == "invalid"` 的节点可能没有 evaluation（生成失败），统计时按无效处理。

---

## 4. 全局开发规则（每个 PR 都必须遵守）

### 4.1 分支与合并
- [ ] **从最新 main 开分支**：`git fetch origin && git checkout -B <branch> origin/main`。
- [ ] 合并前检查：
  1. `git merge-base HEAD origin/main` 等于 `git rev-parse origin/main`。不相等就先 rebase 或合并 main 再测。
  2. 之前 PR 的代码与测试完好：`git diff origin/main --stat -- tests/` 中**不得删除测试文件**。修改已有断言必须在 PR 描述中逐条说明原因。
  3. 测试数**不减少**：`pytest -q` 的通过数 ≥ main 上的通过数，且 0 失败。
- [ ] 受保护文件零改动：
  ```bash
  git diff --stat origin/main -- benchmark/hdd_mvp/evaluator.py benchmark/hdd_mvp/init.py benchmark/hdd_mvp/problem.md benchmark/hdd_mvp/prompt.md benchmark/hdd_mvp/data
  ```
  输出必须为空。
- [ ] 不读 holdout/test/`eval_only`（系统代码只有评估器可以读 val 标签）。
- [ ] 密钥只从环境变量读取，不写入日志、事件或异常信息。
- [ ] LLM/Jev 输出**永远不作为节点分数**。
- [ ] 引擎中不出现 HDD 专有字符串，领域信息只来自 adapter 和任务文件（已有测试会断言）。
- [ ] 新功能默认关闭或向后兼容：旧 `evolve.yaml` 必须能加载。
- [ ] 给 node 表加列需要迁移，**优先新增表或写事件**。`EvaluationResult` 是 `extra="forbid"`，不要往里塞新字段。`TaskAdapter` 是 `runtime_checkable` Protocol，不要往里加方法，另立可选 Protocol。
- [ ] PR 用 draft 提交，由用户合并。PR 描述用中文。

### 4.2 技能（Skill）
- [ ] 每个 PR 至少新增或更新一个 `skill/<name>/SKILL.md`，达到**全自动标准**（Codex 无人值守也能照做），包含六节：
  1. **何时使用**
  2. **输入**：`.env` 变量（`DASHSCOPE_API_KEY`、Jev 密钥变量名取自 `judge.api_key_env`、`FE_ARTIFACTS_DIR`（服务器上不要设置 `FE_RUNS_DIR`，见 §3.1）、`HDD_BENCH_DATA_ROOT`）；`evolve.yaml` 字段
  3. **精确命令**：包含 `--mock` 离线命令
  4. **成功检查**：可执行的 python 断言，针对 `run_summary.json` 或产物
  5. **故障处理**：401/403、429、超时、熔断、无效率过高、画像为空等
  6. **禁止操作**
- [ ] PR 描述中列出"新增/更新的技能"。

### 4.3 每次真实运行必须报告
| 类别 | 字段 |
|---|---|
| 性能 | 最优 ROS、P、R、F1、AUPRC、误告率（false_alarm_rate）、漏告率（missed_detection_rate） |
| 成本 | 总 tokens；分阶段 tokens（generate/repair/reflect/knowledge/jev/discovery/…，有什么报什么）；**每 ROS 点 tokens** = total_tokens / (best − initial) |
| 效率 | 墙钟时间；refine valid（有效 refine / 全部 refine）；超时次数 |
| 标识 | run id、分支 head、iterations |
| 本 PR 专属 | 本 PR 新增的指标（见各节） |

### 4.4 合并规则（用户确认）
- [ ] 测试全部通过，数量不减少。
- [ ] **一次**真实运行无回退：最优 ROS ≥ 上一个已合并 PR 的最优 − **约 2**。单次运行噪声约在 32–36 之间。当前参照为 run 5A 的 36.50，所以门槛约为 34.5。
- [ ] refine valid ≥ **40%**。
- [ ] 超时 ≤ **1** 次。
- [ ] 每个 PR **只做一次真实运行**，不做消融或稳定性实验。

### 4.5 资源
- [ ] 根盘只剩约 4 GB【用户提供】：产物放 NAS（`--artifacts-dir /home/hcf/nas_hcf_data/faultevolve/runs/<name>`）；fe.db 留在默认的本地 `benchmark/hdd_mvp/.fe/runs`（每个几 MB）；不在根盘缓存数据副本；smoke 采样目录在运行结束时自动清理（PR #3 已实现）；每次运行前用 `df -h /` 检查空间。
- [ ] 服务器版本：pandas 3.0.6【用户提供】、LightGBM 4.x。新代码或提示词中不得使用 `pd.np`、`fillna(method=)`、`verbose_eval`、`early_stopping_rounds` 等已移除的 API。

---

## 5. 分步 TODO（按最终顺序）

> 每一步的"提示词摘要"可以直接交给 AI。每段提示词都默认包含以下公共前缀，粘贴时请带上：
> 「从最新 main 开分支；保留并通过全部已有测试（数量不减少）；遵守 AGENTS.md 与本 TODO §4；只开 draft PR，不合并；PR 描述用中文，列出新增/更新的技能、基线与最终测试数、run_summary 新字段示例。」

### 步骤 0：PR #3.1 搜索修复（hotfix，最先做）

**目标与预期收益**
- 修复 PR #3 运行中暴露、直接影响搜索与报告正确性的 5 个问题。
- 预期：
  - 正向 insight 能正常产生，改进的子节点不再被误判为已否证；
  - 报告字段真实可信；
  - 排错信息可用；
  - refine valid 回升到 ≥ 40%。

**依赖**：PR #3（已合并，main `f7678c4`）。

**具体改动**
- [ ] **(1) 反思路由**（`cloud/engine.py::_apply_reflection`）【已核实，main 上的代码】：
  - 现状：`if delta < -hypothesis_threshold or layer == "hypothesis"` 会把**分数提升**的子节点判为已否证；`elif delta < -design_threshold or layer == "design"` 会截走正向的 design 层。结果是 `_reflect_positive` 几乎不被调用；而当同一假设第二次被判 hypothesis 时，改进的子节点会被标为 REFUTED，采纳的卡也会被计入 refuted。
  - 修复：**先判 `delta > design_threshold` → `_reflect_positive`**；只有 `delta < -design_threshold` 时才进入负向分支，再在负向分支内用 `delta < -hypothesis_threshold or layer == "hypothesis"` 区分 hypothesis 与 design；`|delta| ≤ design_threshold` 时维持原逻辑（不做 LLM 反思）。**任何 `delta > 0` 的子节点都不得被标记为 REFUTED**，也不得给它采纳的卡计 refuted。
- [ ] **(2) stop_reason**（`_get_stop_reason`）：当前先判 `target_reached`。`stop_at_target: false` 时即使跑完全部轮次，也会报 `target_score_reached`。
  - 修复：只有 `stop_at_target: true` 且因达标而提前停止时才报 `target_score_reached`；跑满轮次时报 `max_iterations`。
  - 达标信息改由 `target_reached`、`rounds_to_target` 等字段表达。
- [ ] **(3) 错误信息保留尾部**：`smoke_failed`、`invalid_generation` 事件以及节点 `error_info` 中的 traceback 目前截取的是**开头**。
  - 修复：统一保留**末尾约 800 字符**（异常类型和最后几帧在末尾）。
  - 修改点：`common/textutil.sanitize_error_info`，或新增 `tail_text(s, 800)` 并在各处调用。注意不能破坏已有测试对 `sanitize_error_info` 的预期；如需改签名，新增参数即可。
- [ ] **(4) smoke 计时与 token 拆分**：
  - 每个候选的 smoke 耗时写入事件（`smoke_passed/smoke_failed` 带 `duration_s`）；run_summary 新增 `smoke_time_s_total`、`avg_smoke_time_s`、`smoke_tests`。
  - smoke/性能门的自修复 LLM 调用改用 purpose `self_fix`，单独统计为 `self_fix_tokens`，**不再计入 `repair_tokens`**。run 5A 中 repair 的 45,257 tokens 就混入了这部分。
  - `total_tokens` 口径不变（仍是全部 token 之和）。
- [ ] **(5) 事件计数**：`iteration_complete` 事件数与 `iterations_done` 不一致。
  - 排查所有增加 `iterations_done` 的路径：invalid_generation、perf_rejected、smoke 失败后拒绝、llm_error 跳过等。
  - 保证每次计入 `iterations_done` 的迭代恰好发一个 `iteration_complete`（payload 带 `outcome: evaluated|invalid|perf_rejected|smoke_rejected|llm_error`）；不计入的路径不发。
  - run_summary 新增 `iteration_events` 用于自检。

**设计要点与边界情况**
- (1) 会改变 insight 数量、`HypothesisStatus.SUPPORTED` 比例和卡片 refuted 统计。在 PR 描述中说明：运行对比口径与 PR #3 不同。
- (1) 若已有测试断言了旧的错误路由，只修改该断言，并逐条说明原因。
- (4) 旧 run_summary 没有新字段，读取方应使用 `.get`。

**测试**（新增 `tests/test_hotfix_3_1.py`）
- [ ] `test_positive_delta_goes_to_reflect_positive_even_if_layer_hypothesis`（layer 为 hypothesis 或 design 时都应走正向）
- [ ] `test_positive_child_never_refuted`（同一假设第二次出现 + delta>0 → 不是 REFUTED，采纳的卡 refuted_count 不增加）
- [ ] `test_negative_delta_routing_unchanged`
- [ ] `test_stop_reason_max_iterations_when_stop_at_target_false`
- [ ] `test_stop_reason_target_when_stop_at_target_true`
- [ ] `test_error_info_keeps_tail`（构造 3000 字符 traceback，保留的末尾包含最后的异常行）
- [ ] `test_smoke_duration_and_avg_in_summary`
- [ ] `test_self_fix_tokens_separate_from_repair`
- [ ] `test_iteration_complete_count_equals_iterations_done`（mock 运行中混合 invalid/perf_rejected/smoke 失败）

**技能**：更新 `skill/fe-evolve-manager/SKILL.md`：
- stop_reason 语义
- 新字段 `self_fix_tokens`、`avg_smoke_time_s`、`smoke_time_s_total`、`iteration_events`
- 成功检查增加断言 `iteration_events == iterations_done`
- 固化 §3.5 的 `scripts/report_run.py`（refine valid、超时计数、分阶段 tokens 含 self_fix）

**实跑验收**（一次，10 轮，知识开）
- [ ] refine valid ≥ **40%**
- [ ] 最优 ROS ≥ **约 34.5**（36.50 − 噪声）
- [ ] 每 ROS 点 tokens 不差于 run 5A 的 8,704（允许在噪声范围内）
- [ ] 超时 ≤ 1 次；测试 ≥ 236 且全部通过
- [ ] 报告 §4.3 全部指标，另加 `self_fix_tokens`、`avg_smoke_time_s`、insight 数量

**风险与回退**
- 路由修复后 insight 增多，reflect tokens 上升 → 可接受，如实报告。
- 回退：revert 本 PR（只涉及 engine/textutil/metering 小范围改动）。

**提示词摘要**
> 在最新 main（f7678c4 或之后）上做 PR #3.1 hotfix：
> ① `_apply_reflection` 先判 delta>design_threshold → `_reflect_positive`，只在 delta<−design_threshold 时进入负向（其中再分 hypothesis/design），delta>0 的子节点绝不标 REFUTED、不计卡片 refuted；
> ② `stop_at_target=false` 跑满轮次时 stop_reason=max_iterations；
> ③ smoke_failed/invalid_generation/节点 error_info 保留 traceback 末尾约 800 字符；
> ④ 每个候选记录 smoke 耗时，run_summary 加 avg_smoke_time_s/smoke_time_s_total，自修复 token 单独记为 self_fix_tokens（不计入 repair）；
> ⑤ 每次计入 iterations_done 的迭代恰好一个 iteration_complete 事件。
>
> 新增 tests/test_hotfix_3_1.py，保留并通过全部 236 个已有测试；更新 fe-evolve-manager 技能并固化 report_run.py。开 PR，不合并。

---

### 步骤 1：PR #4 Jev 快速判断（候选预筛 + UCT 扩展先验）

**目标与预期收益**
- 全量评估是每轮最慢的一步。让 Jev（MiYang 中继，模型 `miyang/jev-1.13`，endpoint `https://miyang.cn/api/v1/decisions`；来自 PR4 方案，端点可用性**未核实**）在评估前给候选打分，用于：
  - (a) 预筛：跳过或延后"大概率无效/低价值"的候选；
  - (b) 扩展先验：作为 UCT/PUCT 的 prior。
- 预期收益：评估次数和评估耗时下降，ROS 不降【推算，未实测】。对应评审维度：自动化、复杂性。

**依赖**：PR #3.1 已合并（`63ed5d1`）。

**具体改动**
- [x] 新增 `src/faultevolve/cloud/jev_client.py`：
  - `JevClient(config, transport=None).decide(state, questions) -> JevResponse`：`POST base_url`，header `Authorization: Bearer $<api_key_env>`，body `{model, state, questions}`，使用 httpx。
  - `JevResponse(answers, prompt/completion/total_tokens, latency_ms)`：解析要宽容（probabilities / noul / score，score 按 0–1、0–10、0–100 三种量纲归一化；usage 缺失时补 0）。
  - `JevError`：所有失败统一抛出。
  - `MockJevClient`：按 `sha256(code)` 给出确定性结果，约 1/3 候选判为低价值。
- [x] `cloud/judge.py`：保留原签名，替换桩。
  - `JudgeClient(config, client=None)`：provider=none 时禁用；缺密钥时警告一次后禁用。
  - `prescreen(parent, code, intent, ctx) -> PrescreenResult{ok, p_invalid, p_improve, value, tokens, latency_ms, error}`。
  - `should_defer_candidate()` 返回 `evaluate | skip_invalid | skip_low_value | defer`。
  - `record_outcome()` 做审计回写；`node_prior()` 基于缓存的 value 计算，不额外调用 Jev。
  - 连续失败达阈值后熔断。
- [ ] 问题设计（任务无关）：一次调用问 3 个问题：
  - `valid`（noul）→ `p_invalid = 1 − p_true`
  - `improve`（choice：better/same/worse）→ `p_improve`
  - `value`（score 0–1）

  state 由 problem 摘要、`adapter.constraints()`、父节点 intent/hypothesis/分数、候选 intent/hypothesis、unified diff 拼成，截断到 `max_state_chars`。
- [x] `engine._run_one_iteration`：在 `static_check`（以及 PR #3 的 precheck/性能门/smoke）**通过之后**、`create_child_node` 与 `evaluate` **之前**插入预筛。
  - 被筛且未抽中审计的候选：状态记 `ABANDONED`，不评估，`iterations_done += 1`，不调用 `add_eval`。
  - 按 `audit_rate` 抽样审计。
  - warmup 期内只做影子记录，不筛。
  - defer 队列在主循环结束后按 `defer_flush_evals` 补评。
  - repair 节点不预筛。
  - `tree.get_regular_children_count()` 追加排除 `ABANDONED`。
- [x] `cloud/selection.py`：`UCTSelector.set_node_priors(values, tau, enabled)`；在 `select()` 中对同一父节点的 children + expand 计算 `compute_tau_weighted_prior(jev, uniform, tau)`。`get_jev_prior()` 接入。resume 时从 `jev_prescreen` 事件重建先验。
- [x] `config.py` 的 `JudgeConfig` 新增（均有默认值）：`provider: none|jev|mock`、`base_url`、`api_key_env: MIYANG_API_KEY`、`model`、`timeout_s: 5`、`prescreen: false`、`invalid_threshold: 0.85`、`low_value_threshold: 0.15`、`low_value_action: skip|defer`、`defer_flush_evals: 0`、`warmup: 10`、`audit_rate: 0.1`、`prior: true`、`prior_tau: 0.5`、`max_calls: 500`、`max_consecutive_errors: 3`、`max_state_chars: 6000`、`retries: 0`。先验需同时满足 `selection.policy: jev_puct`。
- [x] 计量：`add_llm_call(..., "jev")`，`jev_tokens` 计入 `total_tokens`。`RunSummary` 新增：`jev_calls, jev_errors, jev_fail_open, jev_prompt_tokens, jev_completion_tokens, jev_tokens, jev_latency_ms, jev_disabled_reason, candidates_screened, evaluations_saved, eval_time_saved_est_s, screen_audited, screen_audit_bad, screen_shadow, screening_precision, jev_prior_active`。
- [x] CLI：`fe judge ping [--task-dir] [--env-file] [--json]`，exit 0/1，绝不打印密钥。`.env.example` 增加 `MIYANG_API_KEY=`。
- [ ] 若 PR #3.1 没有固化 `report_run.py`（§3.5），在本 PR 补上。

**设计要点与边界情况**
- 可选、配置驱动、fail-open：任何 Jev 错误都按正常评估处理；`provider: none` 时零 HTTP 请求，行为与 PR #4 之前完全一致。
- 事件中不包含 state 原文和密钥。
- 被筛节点不能占用渐进展宽名额，也不影响 valid_rate。
- 注意 PR #3 新增的 precheck/性能门/smoke 路径：预筛放在它们之后，避免给注定失败的代码付 Jev 费用。

**测试**（`tests/test_jev_screening.py`，使用 `httpx.MockTransport` 或 `MockJevClient`，不依赖 respx）
- [ ] `test_request_format`（URL、Bearer 假 key、body、noul 的 criteria）
- [ ] `test_response_parsing_variants`
- [ ] `test_fail_open_timeout_500_badjson_missing_key`
- [ ] `test_circuit_breaker_after_3_errors`
- [ ] `test_prescreen_skip_reduces_evaluations`（ABANDONED、不占展宽）
- [ ] `test_audit_precision_exact`
- [ ] `test_warmup_shadow`
- [ ] `test_defer_flush`
- [ ] `test_prior_non_uniform_sums_to_one`、`test_prior_uniform_when_disabled`、`test_prior_rebuild_on_resume`
- [ ] `test_default_off_zero_http`
- [ ] `test_e2e_mock_summary_fields`
- [ ] `test_old_yaml_loads`
- [ ] `test_no_key_in_events_logs`

**技能**
- [x] 新增 `skill/fe-jev-screening/`：
  - `SKILL.md`：何时用；输入 `MIYANG_API_KEY`、`DASHSCOPE_API_KEY`、`judge.*`；命令 `fe judge ping …`、`bash skill/fe-jev-screening/scripts/run_mock_jev.sh`；成功检查 `jev_calls>0, evaluations_saved>0, screening_precision 非 null`；故障处理：401 时停止、429/超时依赖熔断、精度低时调高阈值或关闭；禁止事项
  - `scripts/run_mock_jev.sh`、`scripts/check_jev_summary.py`、`references/judge-config.md`
- [x] 更新 `skill/fe-evolve-manager/SKILL.md`：环境变量、judge 配置示例（MiYang）、jev 字段表、故障条目、report_run.py 用法。

**Jev 接入信息**【用户提供】
- MiYang 中继：`POST https://miyang.cn/api/v1/decisions`，模型 `miyang/jev-1.13`。
- 服务器上 `/home/hcf/geolocate-fast-code` 有可运行的参考调用代码和密钥（**只读**，只能参考，不要修改）。
- 把密钥**复制**到 `/home/hcf/faultevolve/.env`，变量名为 `MIYANG_API_KEY`。复制方式：用编辑器，或写一行不回显值的脚本。**任何时候都不要打印密钥**。
- `evolve.yaml` 中设置 `judge.api_key_env: MIYANG_API_KEY`（PR #3 的默认值是 `TYPESAFE_API_KEY`，要改）。
- 请求与响应格式以参考代码为准；本文 3 个问题的设计如与之不符，按参考代码调整。

**实跑验收**（用户决定统一延后到全部功能完成后；本 PR 不发起真实 Jev/LLM 调用）
- [ ] 按 §4.3 报告，另加 `jev_tokens`、`evaluations_saved`、`eval_time_saved_est_s`、`screening_precision`。
- [ ] 满足合并规则。与 PR #3 最终运行对比：评估次数或评估耗时应下降（期望，不作硬门槛）。
- [ ] 若 MiYang 不可用：用 `provider: mock` 完成离线验收，真实运行以 `provider: none` 通过合并规则，并在 PR 中写明 Jev 真实效果未验证。

**风险与回退**
- Jev 误筛好候选 → 调高 `low_value_threshold` 严格度或改为 `defer`，或直接 `prescreen: false`。
- 中继接口形状与方案不符 → 解析宽容 + fail-open。
- 回退：`judge.provider: none`。

**提示词摘要**
> 实现 PR #4：新增 `cloud/jev_client.py`（JevClient/JevResponse/JevError/MockJevClient，httpx），改造 `cloud/judge.py` 桩为可用实现（fail-open、熔断、审计、warmup、defer）；在 `_run_one_iteration` 的静态检查/precheck/性能门/smoke 之后、评估之前插入预筛，被筛节点标 ABANDONED 且不占展宽；`UCTSelector` 接入 tau 加权 Jev 先验（需 `selection.policy: jev_puct`）；`JudgeConfig` 新字段全部有默认值且 `provider: none` 零请求；jev_tokens 计入总 token；`fe judge ping`；测试用 httpx.MockTransport；新增技能 fe-jev-screening，更新 fe-evolve-manager；密钥变量 MIYANG_API_KEY，参考服务器 /home/hcf/geolocate-fast-code（只读）。完整设计见 docs/plans/PR4-Jev快速判断-方案.md。

---

### 步骤 2：PR #6 dev 集错例画像 + 评估器感知提示

**目标与预期收益**
- 修复"错例画像始终为空"：`_run_one_iteration` 读取 `metric.get("analysis", {})`，但评估器从不输出 `analysis`【已核实】，而 refine 指令又要求针对错例画像改进。
- 让 LLM 知道**漏告/误告集中在哪里**，并理解 ROS 的构成。
- 预期：召回↑、F1↑。这是路线图中预期收益最大的一项【推算】。对应评审维度：预测性能。

**依赖**：PR #4 合并（避免同时改 engine 同一段；逻辑上只依赖 PR #3）。

**具体改动**
- [x] `tasks/protocol.py` 新增**独立的**可选 Protocol（不要加进 TaskAdapter）：
  - `@runtime_checkable class ErrorProfiler(Protocol)`：`analyze(code, task_spec, timeout) -> dict`
  - `@runtime_checkable class ObjectiveBriefProvider(Protocol)`：`objective_brief(task_spec) -> str`
  - 引擎用 `isinstance` 判断，未实现时跳过。
- [x] `tasks/hdd_adapter.py` 实现 `analyze`：
  - 只用**公开 train 数据**构造 dev 划分：按 cutoff 切为 train_early（前约 60%）和 train_late（后约 40%）。
  - 在临时目录生成与候选契约兼容的文件：`train_history.csv.gz/train_labels.csv` = early，`val_history.csv.gz/val_index.csv` = late。late 的标签只保存在 adapter 内存或临时目录中，不交给候选。
  - 用同一 CLI 运行候选：`python cand.py --data-dir <dev> --split val --out <csv>`，使用 `sys.executable`。
  - 计算分组 FN/FP 统计：按厂商/型号（model）、按 k（距失效天数；需要 labels 中有失效日期列或可推导，**未核实**，缺失则跳过该分组）、按"SMART 静默"（失效当日 5/187/197/198 全为 0 或空）、按容量段。
  - 输出 `{"dev_metrics": {...}, "fn_groups": [...top5], "fp_groups": [...top5], "silent_share": x, "notes": "..."}`。
  - 计数 < 10 的组做抑制。
- [x] `tasks/hdd_adapter.py` 实现 `objective_brief`，写入以下事实：
  - ROS 公式与各项边际（F1_p10 +0.01 → ROS +0.5；AUPRC +0.01 → +0.3；R@FAR +0.01 → +0.2）
  - FAR 预算 0.2% 只作用于 R@FAR
  - 负样本权重约 10
  - 机队正例率约 0.25%（推算，写明是推算）
  - 概率校准时 F1 最优阈值约为 F1*/2
- [x] `cloud/engine.py`：
  - 在新 best 节点、或 top-k（`analysis.top_k`）有效节点评估后调用 `analyze`，把结果写入该节点 `evidence.evaluation.metric["analysis"]`。metric 是 dict，可以放；通过 `tree.update_node_evidence` 写回。
  - 子节点生成时，`ctx.set_error_profile(parent 的 analysis)` 现有逻辑自动生效。
  - analyze 失败或超时只记事件 `analysis_failed`，不影响主流程。
  - analyze 耗时计入墙钟和 `analysis_time_s`。
- [x] `cloud/operators.py`：`USER_MESSAGE_TEMPLATE` 增加 `<objective_brief>` 段（为空不输出）；错例画像段的格式化与截断。
- [x] `cloud/insights.py`：`LayeredReflector` 的 prompt 增加父子 analysis 差分（新增漏告组 / 修复漏告组），提示反思给出可证伪的假设。
- [x] 配置 `analysis:`：`enabled: false`、`top_k: 3`、`on_new_best: true`、`dev_late_fraction: 0.4`、`timeout_s: 600`、`min_group_count: 10`。
- [x] 指标：`analysis_calls, analysis_failures, analysis_time_s, analysis_nonempty_rate`。

**设计要点与边界情况**
- 绝不读 `eval_only`、val 标签或 test。dev 标签来自 train_labels（公开）。
- dev 运行会多耗时（每次最多一次候选运行时间，约 < 300 s）。只对少数节点运行，并受 `timeout_s` 限制。
- 静态检查词表：画像文本中不要出现 `val_labels` 等禁词（它们会进入 prompt → LLM 可能照抄进代码 → 被静态检查拒绝）。
- 任务无关：引擎只看到 dict/str。

**测试**
- [x] `test_error_profiler_protocol_optional`（FakeAdapter 没有 analyze 时引擎正常）
- [x] `test_hdd_dev_split_no_eval_only_access`（monkeypatch open 或路径断言）
- [x] `test_analysis_groups_small_cell_suppression`
- [x] `test_analysis_written_to_metric_and_prompt`
- [x] `test_objective_brief_in_prompt`
- [x] `test_analysis_failure_nonfatal`
- [x] `test_reflection_includes_fn_diff`

**技能**
- [x] 新增 `skill/fe-error-analysis/SKILL.md`：
  - 何时用：召回低、画像为空
  - 输入：`analysis.*`、`HDD_BENCH_DATA_ROOT`
  - 命令：`fe evolve local … --mock -n 3` 后检查 `metric.analysis`；另提供 `fe analyze <task_dir> --program <file.py> --json`（建议新增的 CLI，对单个程序出画像）
  - 成功检查：`analysis_nonempty_rate > 0`，且 prompt 中含画像段
  - 故障处理：dev 运行超时、分组全被抑制、列缺失
  - 禁止：读 eval_only
- [x] 更新 `fe-evolve-manager`。

**实跑验收**：一次真实运行，`analysis.enabled: true`。按 §4.3 报告，另加 `analysis_*` 字段和 best 节点的 fn_groups 摘要。满足合并规则；期望召回较 PR #4 运行上升（不作硬门槛）。**本 PR 未做真实运行（用户决定统一延后）。**

**风险与回退**
- dev 运行拖慢墙钟 → 降低 `top_k` 或只在 new-best 时运行。
- 画像误导 LLM 过拟合某型号 → 在 prompt 中注明"只作线索"。
- 回退：`analysis.enabled: false`。

**提示词摘要**
> 实现 PR #6：新增可选 Protocol ErrorProfiler/ObjectiveBriefProvider（不改 TaskAdapter）；HDDAdapter 用公开 train 按 cutoff 切 early/late 构造 dev 目录，以候选原 CLI 运行并计算按型号/k/静默/容量分组的 FN/FP（小格抑制），写入节点 metric["analysis"]；refine 提示新增 objective_brief 段（ROS 分解与边际）；反思加入 FN 差分；配置 `analysis:` 默认关；新增技能 fe-error-analysis。绝不读 eval_only/test。

---

### 步骤 3：PR #5 多目标节点价值 + token 预算控制

**目标与预期收益**
- 节点价值目前只看 `combined_score` 的子树最大值【已核实，`UCTSelector._compute_q`】，容易追逐噪声或一次侥幸的阈值。
- 改为多目标 Q，并按剩余 token/墙钟预算决定扩展与停止。
- 预期：排序质量上升、单次 best 更可靠、每 ROS 点 token 下降【推算】。对应评审维度：复杂性、自动化。

**依赖**：PR #6（Q 可以使用 analysis 与 AUPRC/R@FAR）。

**具体改动**
- [x] `cloud/selection.py`：`_compute_q(node)`（仅用于**选择**，报告分数仍为 ROS）：
  ```
  Q = ROS_norm + λ_rank·(ΔAUPRC_rel + ΔR@FAR_rel) − λ_noise·f1_boot_std
  ```
  - 取子树最大值或 softmax 回传（可配置）。
  - 维护精英档案：按"排序质量（AUPRC、R@FAR）"和"阈值质量（F1_p10 − F1 的差）"两个维度各保留 top-m，扩展时按比例抽取。
- [x] 新增 `cloud/budget.py`：`BudgetController`
  - 跟踪各阶段 token 与评估耗时；估计每次迭代的期望成本（滑动平均）。
  - `should_expand(node)`：剩余预算 < 期望成本 × 安全系数时，只扩展 top 节点。
  - `should_stop()`：新增停止条件 `stagnation`（`budget.stagnation_window` 轮内最优提升 < noise_delta）与 `tokens_per_point_cap`。
  - 分阶段上限：`budget.stage_caps: {reflect: 0.25, repair: 0.35, knowledge: 0.1, jev: 0.1}`，按比例计；超限时降级，例如跳过 LLM 反思、改用规则。
- [x] `config.py`：
  - `selection.value: {mode: scalar|multi, lambda_rank: 0.3, lambda_noise: 1.0, backup: max|softmax, elite_m: 3}`
  - `budget: {stage_caps: {...}, stagnation_window: 8, tokens_per_point_cap: null, safety_factor: 1.5}`
  - 默认 `mode: scalar`，保持旧行为。
- [x] 计量：`tokens_per_ros_point`（直接写入 run_summary）、`stage_cap_hits`、`budget_stop_reason`、`elite_archive_sizes`、`expand_skipped_budget`。
- [x] `_get_stop_reason()` 增加 `stagnation`、`tokens_per_point_cap`。

**设计要点与边界情况**
- 无效节点、ABANDONED 节点、repair 节点的 Q 处理方式与旧版一致。
- metric 缺字段（非 HDD 任务）时退化为 scalar，保持任务无关：多目标字段名由 adapter 提供（可选 Protocol `ObjectiveSpec.objectives() -> list[str]`）。
- 与 PR #4 先验兼容：先验只影响 prior 项，Q 只影响 value 项。

**测试**
- [x] `test_q_scalar_default_unchanged`
- [x] `test_q_multi_prefers_rank_gain`
- [x] `test_q_noise_discount`
- [x] `test_elite_archive`
- [x] `test_budget_stage_cap_degrades_reflect`
- [x] `test_stagnation_stop`
- [x] `test_tokens_per_ros_point_in_summary`
- [x] `test_missing_metric_fallback`

**技能**
- [x] 新增 `skill/fe-node-value-budget/SKILL.md`（原 `fe-budget-control` 同名）：
  - 何时用：token 超预算、停滞
  - 输入：`budget.*`、`selection.value.*`
  - 命令：mock 运行 + 读取 `budget_stop_reason`
  - 成功检查：`tokens_per_ros_point` 存在；stage_caps 生效
  - 故障处理：过早停止时调大 window
  - 禁止：用 Q 替代 ROS 报告
- [x] 更新 `fe-evolve-manager`。

**实跑验收**：一次真实运行，`mode: multi`。报告 §4.3 指标，另加 `tokens_per_ros_point`、`budget_stop_reason`、`stage_cap_hits`。满足合并规则；期望每 ROS 点 tokens 低于 PR #6 的运行。

**风险与回退**：λ 不当导致搜索偏移 → `mode: scalar`。

**提示词摘要**
> 实现 PR #5：UCTSelector 支持 `selection.value.mode: multi` 的多目标 Q（ROS + λ·排序增益 − λ·f1_boot_std，仅用于选择）与精英档案；新增 `cloud/budget.py` BudgetController（分阶段 token 上限、期望成本、停滞停止、每 ROS 点 token 上限）；默认保持旧行为；run_summary 新增 tokens_per_ros_point 等；新增技能 fe-budget-control。

---

### 步骤 4：PR #7 召回/阈值算子 + 算子老虎机

**目标与预期收益**
- 当前只有 REFINE：`select_operator()` 固定返回 REFINE，`get_operator_thompson_sample()` 未使用【已核实】。
- 新增针对召回与阈值的专用算子和卡片驱动的 INJECT，用 Thompson 采样按效果自动分配。
- 预期：召回↑、F1_p10 稳定性↑【推算】。

**依赖**：PR #6（RECALL_FOCUS 需要 FN 画像）、PR #5（奖励可用 Q）。

**具体改动**
- [x] `common/schemas.py`：`OperatorType` 追加 `RECALL_FOCUS`、`THRESHOLD_CALIBRATE`，并确认 `INJECT` 可用。node 表中 operator 以 TEXT 存储，追加枚举值不需要迁移；需确认旧数据可读。
- [x] `cloud/operators.py`：
  - `OPERATOR_INSTRUCTIONS` 增加：
    - `RECALL_FOCUS`：输入 FN 画像，只改特征/模型，不动告警策略
    - `THRESHOLD_CALIBRATE`：只改告警策略，例如用 train 的 OOF 选阈值使加权 F1 最优，禁止改特征
    - `INJECT`：强制采纳 1 张指定卡（来自 PR #3 检索）
  - `select_operator(node, stats, rng)` 调用 `get_operator_thompson_sample()`：每个算子一个 Beta(α, β)，奖励为 `delta > noise_delta`；每个算子至少探索 `operators.min_explore` 比例。
- [x] `cloud/store.py`：新表 `operator_stats(experiment_id, operator, alpha, beta, n, sum_delta)`。
- [x] `cloud/engine.py`：
  - 在 `_run_one_iteration` 中用 `select_operator` 取代写死的 REFINE；`create_child_node(..., operator)`。
  - 评估后更新 operator_stats。
  - RECALL_FOCUS 在父节点没有 analysis 时回退为 REFINE。
- [x] PR #3 卡片与 FN 画像关联：retriever 的 context 加入 `fn_groups` 关键词（例如型号、静默），用于匹配 tags。
- [x] 配置 `operators: {bandit: false, enabled: [refine, recall_focus, threshold_calibrate, inject], min_explore: 0.1, prior_alpha: 1, prior_beta: 1}`。
- [x] 指标：`operator_counts`、`operator_valid_rate`、`operator_mean_delta`、`operator_posteriors`（写入 run_summary）。

**设计要点与边界情况**
- THRESHOLD_CALIBRATE 可以用两种方式：train OOF 选阈值，或按**查询集无标签 score 分布**的分位数定告警率。**用户已确认第二种可接受**。但绝不读取任何标签文件。
- 算子必须任务无关：领域描述来自 adapter 的 brief 或画像。
- resume 时从表中恢复老虎机状态。

**测试**
- [x] `test_select_operator_default_refine_when_bandit_off`
- [x] `test_thompson_prefers_rewarded_operator`（固定种子）
- [x] `test_min_explore`
- [x] `test_recall_focus_fallback_without_analysis`
- [x] `test_operator_stats_persist_resume`
- [x] `test_inject_forces_card`
- [x] `test_operator_enum_backward_compat`

**技能**
- [x] 新增 `skill/fe-operators/SKILL.md`：
  - 何时用：启用或调整算子与老虎机
  - 命令：mock 运行 + 读取 `operator_counts`
  - 成功检查：多个算子被使用，posteriors 已写出
  - 故障处理：某算子无效率高时从 `enabled` 中移除
  - 禁止：让 THRESHOLD_CALIBRATE 读取标签
- [x] 更新 `fe-knowledge-injection`（卡片与 FN 关联）和 `fe-evolve-manager`。

**实跑验收**：一次真实运行，`bandit: true`。报告 §4.3 指标，另加按算子分项的有效率和平均 Δ。满足合并规则。**【用户提供】实跑统一延后至全部 PR 完成后执行。**

**风险与回退**：新算子的无效率高会拉低 refine valid。"refine valid"的统计口径需在 PR 中说明：建议统计所有生成类算子。回退：`bandit: false`。

**提示词摘要**
> 实现 PR #7：OperatorType 追加 RECALL_FOCUS/THRESHOLD_CALIBRATE（INJECT 可用），OPERATOR_INSTRUCTIONS 增加对应指令；select_operator 接入 Beta-Thompson 老虎机（奖励 delta>noise，min_explore），operator_stats 新表并支持 resume；engine 用 select_operator 代替固定 REFINE；retriever 上下文加入 FN 画像关键词；配置 `operators.bandit` 默认关；新增技能 fe-operators。

---

### 步骤 5：知识发现 KD1 → KD2（只做后端）

来源：`houchenfeng/FaultEvolve-ResearchAssistant` 的 `docs/discovery_plan_v2.md` 与 `docs/design/*.md`【已核实】。RA 仓库**没有代码**，只有设计。前端（React）与 NestJS Web 服务全部不做，只输出 JSON 产物和 CLI `--json`。

"新知识发现"= 三层可证伪知识：
- **现象层**：Claim = ⟨条件、特征代码 X、结果 Y、方向/幅度±CI、适用范围、否证条件⟩
- **机理层**：竞争机制 + 数据裁决锦标赛 + 否证证书
- **原理层**：≥2 个成立机制同构时才做，不在本期范围

#### 5a. KD1 现象层发现 + 发现卡回灌

**目标与预期收益**：把带来真实提升的改动翻译成可检验的 Claim，经统计检验与对照后晋升为"发现卡"，回灌到 PR #3 的检索、采纳和 card_stats 闭环。预期：答辩展示可证伪的新知识及其血统（node→claim→card）；对 ROS 的影响**未知**。

**依赖**：PR #3（强依赖：loader、card_stats、retriever）；排在 PR #7 之后。反思路由已在 PR #3.1 修复，KD1 依赖正向 insight 作为 claim 来源。

**具体改动**（新包 `src/faultevolve/discovery/`）
- [x] `schemas.py`：`Claim`、`ClaimTestResult`、`ControlReport`、`Grade{CONFIRMED, REVISED, DISCOVERED, REFUTED, UNDETERMINED}`。
- [x] `claims.py`：
  - `translate_claim`（`chat_for_reasoning` 输出 JSON）
  - `extract_claim_from_response`（解析 `<claim>…</claim>`，失败返回 None）
  - `preregister`（canonical JSON 的 sha256）
- [x] `sandbox.py`：在子进程中运行 `def feature(history) -> pd.Series`。复用 codecheck 禁用规则，禁止 IO 和网络，有超时限制。
- [x] `splits.py`：按序列号哈希切分 exploration/confirmation（`confirmation_fraction: 0.3`，`split_salt`）；时间方向检验用 train 内按 cutoff 分的前后两段。**只读 `data/public/train_*`。**
- [x] `stats.py`：
  - 按盘分组 bootstrap CI
  - 单特征效应（AUROC − 0.5、分位组失效率比）
  - 组置换 p 值
  - p→e 校准 `e = κ·p^(κ−1)`（κ = 0.5）
  - BH、e-BH
  - 相对 K0 基线特征的增量检验
  - max |Spearman ρ|
- [x] `baseline_features.py`：K0 特征 = 51 张卡中常见的 SMART 原值、14 天差分、非零计数。
- [x] `controls.py`：打乱标签（分层）阴性对照；3 档强度的植入信号阳性对照。
- [x] `novelty.py`：
  - 功能新颖：`max|ρ| < rho_max` 且增量 CI 下界 > 0
  - 语义新颖：推理 LLM 盲判是否被某卡蕴含；若 PR #4 可用，可选用 Jev，fail-open
- [x] `grading.py`（表驱动）：
  | 等级 | 条件 |
  |---|---|
  | 发现 | 确认切片 CI 不跨 0 且方向与预注册一致；时间方向一致；BH 与 e-BH 均通过；功能新颖；不被任何卡蕴含；本轮阴性对照 fpr ≤ 0.10 |
  | 确认 | 统计条件同上，但被某卡蕴含且方向一致 |
  | 修正 | 被某卡蕴含，但方向或幅度不同 |
  | 已否证 | CI 跨 0、方向翻转或时间方向不一致 |
  | 未定 | 其余情况 |

  阴性对照不达标时，整轮不晋升任何卡。
- [x] `promotion.py`：发现和修正晋升为卡。
  - `id = D-<exp>-<nnn>`；category 必须属于 `VALID_CATEGORIES`，默认 `feature_engineering`
  - `risk` 含"数据驱动发现，未经文献验证"
  - `source_ids = [run:…, node:…, claim:…]`
  - `impl_hint` = 特征代码（约 600 字符）
  - priority：发现 2、修正 3；`evidence: "run"`
  - 附加血统字段：`grade`、`prereg_hash`、`revises`/`confirms`
  - 写入 `<runs_dir>/knowledge/discovered_cards.jsonl`，**绝不写仓库中的 cards.jsonl**
- [x] `pipeline.py`：`DiscoveryRound`，流程为收割（z ≥ 2 的正向 insight、top-K 节点、`<claim>`）→ 预注册 → 沙箱 → 检验 → FDR → 对照 → 新颖性 → 分级 → 晋升。fail-open。
- [x] `tasks/protocol.py`：独立的可选 `DiscoveryDataProvider.discovery_frames(task_spec)`；HDDAdapter 与 FakeAdapter（合成数据 + 植入信号）实现它。
- [x] `knowledge/loader.py`：新增 `load_all_cards(knowledge_dir, extra_paths)`（cards.jsonl → discovered_cards.jsonl → 配置路径，id 冲突时拒绝后者）；`load_cards_from_dir` 保持不变。`get_era_knowledge_cards` 改用 `load_all_cards`。
- [x] `engine.py`：
  - 每 `every_n_iterations` 轮及结束前各跑一轮发现，受 `max_token_share` 限制
  - 可选：每 `discover_op_every` 轮在 REFINE 指令末尾追加"输出 `<claim>`"
  - `add_llm_call(m, "discover")`
- [x] `store.py`：只新增表 `claim`、`claim_test`、`discovered_card`。
- [x] 配置 `discovery:`：
  ```yaml
  discovery:
    enabled: false
    every_n_iterations: 5
    run_at_end: true
    max_claims_per_round: 3
    min_insight_z: 2.0
    top_k_programs: 3
    discover_op_every: 0
    alpha: 0.05
    bootstrap_b: 500
    e_calibrator_kappa: 0.5
    rho_max: 0.8
    planted_strengths: [0.2, 0.5, 1.0]
    neg_control_repeats: 5
    max_neg_control_fpr: 0.10
    confirmation_fraction: 0.3
    split_salt: fe-kd-2026
    sandbox_timeout_s: 120
    max_token_share: 0.2
    inject_same_run: true
    cards_path: null
    extra_card_paths: []
    use_jev_entailment: false
  ```
- [x] 指标：
  - token：`discovery_tokens`、`discovery_token_share`
  - 轮次：`discovery_rounds`、`discovery_rounds_skipped`
  - claim：`claims_proposed`、`claims_tested`、`claims_sandbox_failed`，以及 `claims_{confirmed, revised, discovered, refuted, undetermined}`
  - 发现卡：`discovered_cards_count`、`discovered_cards_offered`、`discovered_cards_adopted`、`discovered_card_adoption_rate`
  - 效果：`discovered_card_mean_delta` 与 `literature_card_mean_delta` 对比、`score_delta_after_discovery`
  - 对照：`neg_control_false_positives`、`neg_control_fpr`、`planted_recovery_rate`（按强度分项）
- [x] 产物：`discovery/{phenomena.json, preregistration.json, controls.json, discovered_cards.snapshot.jsonl}`；`tree.json` 节点加 `adopted_cards`。
- [x] CLI：
  - `fe discover run <task_dir> --run-id EXP [--mock] [--max-claims N] --json`
  - `fe discover report <task_dir> --run-id EXP --json`
  - `fe data checkup <task_dir> --json [--out DIR]`

**测试**
- [x] `test_discovery_stats`：bootstrap 覆盖率 ≥ 0.85（20 个种子）；BH/e-BH；校准
- [x] `test_claim_extraction`
- [x] `test_discovery_sandbox`
- [x] `test_discovery_controls`：打乱标签 fpr ≤ 0.10；强植入信号回收率 ≥ 0.9；零强度信号不被判为发现
- [x] `test_novelty`
- [x] `test_grading`
- [x] `test_card_promotion`：通过 `validate_card`；`cards.jsonl` sha256 不变；去重；id 冲突
- [x] `test_engine_discovery`：发现卡被检索并采纳，写入 card_stats
- [x] `test_discovery_disabled`：默认行为不变
- [x] `test_cli_discover`

**技能**
- [x] 新增 `fe-knowledge-discovery`：命令为 doctor → data checkup → discover run → discover report；断言 `neg_control_fpr ≤ 0.10`、promoted id 以 `D-` 开头、cards.jsonl sha256 不变。
- [x] 新增 `fe-data-checkup`：输出 `data_facts.json`、`field_coverage.csv`、`silent_subset_stats.csv`；只输出聚合量；断言 `n_positive` 等于 meta.json 中 train 的 1104；不自动下载数据。
- [x] 更新 `fe-knowledge-injection`（发现卡命名空间、加载顺序）与 `fe-evolve-manager`。

**实跑验收**：一次真实运行，`discovery.enabled: true, every_n_iterations: 5`。报告 §4.3 指标 + 上述发现指标。**不设发现卡数量目标**。满足合并规则（发现 token 计入总 token）。

**风险与回退**
- LLM 生成的特征代码不安全 → 沙箱。
- 多重检验导致假发现 → BH + e-BH + 阴性对照门槛。
- token 过高 → `max_token_share`。
- 回退：`discovery.enabled: false`。

**提示词摘要**：见 `docs/plans/PR-knowledge-discovery-cloud-agent-prompt.md` 的 Prompt A。要点：前提检查（`src/faultevolve/knowledge/loader.py` 与 card_stats 表存在，main f7678c4 已满足）；确认 PR #3.1 的路由修复已在 main（`grep -n "_reflect_positive" src/faultevolve/cloud/engine.py` 并检查分支顺序）；只读 train_*；发现卡不写仓库文件。

#### 5b. KD2 机理层 + 数据裁决锦标赛 + 否证证书 + 报告

**目标**：对成立的现象提出竞争机制并用数据裁决，产出机制卡和否证证书；报告中的数字只来自 manifest。

**依赖**：KD1 合并。

**具体改动**
- [x] `discovery/mechanisms.py`：
  - `Mechanism`（因果图 + 各检验的预测符号）
  - `propose_rivals`：LLM 生成 1–2 个对手，并**固定加入** `M_confound`（机型/厂商混杂）、`M_artifact`（计数语义伪迹）、`M_censor`（187>0 换盘导致删失）、`M_other`
  - `revise_mechanism`：计为补丁，修订后必须在未用过的切片上重检
- [x] `discovery/tests_catalog.py`：
  - 检验类型：环境不变性（机型族 × 季度；有 datacenter 列时才用）、时间先后、剂量反应、中介、异质性
  - `derive_tests`：只保留两机制预测符号相反的检验，按 EIG 近似排序
- [x] `discovery/tournament.py`：
  - 瑞士制配对；预注册预测矩阵 sha256；只在 confirmation 切片上运行
  - e ≥ 1/α 判胜，否则判"功效不足"并记录最小可检测效应
  - Elo 更新 `K = K0·min(1, |log e| / log(1/α))`；截断 log BF ∈ [1/10, 10]；E = ∏e
  - 数据预算账本：同一切片在一个比赛族内只用一次
  - **最终判定**：E ≥ 1/α 且通过 ICP 且经 e-BH 后仍显著。Elo 只用于排赛程
- [x] `discovery/icp.py`（简化 ICP）；`discovery/certificates.py`（证书字段 `{mechanism_id, rival_id, test_id, test_type, env, stat, ci, e_value, prereg_hash, date}`）。
- [x] `cloud/insights.py`：`LayeredReflector` 允许 `mechanism` 层；实现 `update_insight_reputation`（Beta）。
- [x] `cloud/operators.py`：`OperatorContext.set_mechanism_context()` + `<mechanism_context>` 段。
- [x] `engine.py` 回灌：
  - 被否证的机制 → 写入 `[MECH]` 前缀、polarity = −1 的 insight，`get_foreign_insights` 会自动把它作为 negatives
  - 成立的机制 → 写入 `branch_memory.summary`，并晋升为发现卡 `D-<exp>-M<nnn>`（priority 1）
- [x] `store.py`：新表 `mechanism`、`match`、`test_result`、`certificate`、`theory`（theory 只建表）。
- [x] `schemas.HypothesisStatus` 追加 `CORROBORATED`、`UNDETERMINED`。
- [x] 原理层只留接口（`unify()` 返回空，`theories.json` 为 `[]`）。
- [x] `discovery/report.py` + `fe report <task_dir> --run-id EXP --json|--md`：数字只来自 manifest。
- [x] 配置 `discovery.tournament: {enabled: false, elo_k0: 32, max_rounds: 3, max_rivals: 2}`。
- [x] 指标：`mechanisms_proposed, matches_played, decisive_matches, underpowered_draws, certificates_issued, mechanisms_established, mechanisms_refuted, mechanism_patches, planted_mechanism_recovered, llm_vs_data_kendall_tau, shuffled_env_false_pass, tournament_tokens`。

**测试**
- [x] `test_planted_mechanism_wins_confound_loses`
- [x] `test_icp_shuffled_env_rejects`（≥ 0.9，20 个种子）
- [x] `test_elo_k_formula`
- [x] `test_data_budget_ledger_rejects_reuse`
- [x] `test_fixed_rivals_always_present`
- [ ] `test_refuted_mech_in_foreign_negatives`
- [ ] `test_report_numbers_match_manifest`
- [ ] `test_mechanism_layer_parse`

**技能**：更新 `fe-knowledge-discovery`（机理章节）；新增 `fe-report-generation`（断言报告中的每个数字都能在 manifest 中找到且相等，禁止手写数字）；更新 `fe-evolve-manager`。

**实跑验收**：一次真实运行，`tournament.enabled: true`。报告 §4.3 指标 + 锦标赛指标。满足合并规则。

**风险与回退**：统计功效不足导致全是平局 → 如实报告最小可检测效应。回退：`tournament.enabled: false`。

**提示词摘要**：见 `docs/plans/PR-knowledge-discovery-cloud-agent-prompt.md` 的 Prompt B。

---

### 步骤 6：PR #8 交叉/集成算子

**目标与预期收益**：选两个来自不同分支、FN 集合互补的高分节点，让 LLM 合成 rank-average 或 stacking 程序。预期 AUPRC、R@FAR 上升【推算】。

**依赖**：PR #7（算子框架与老虎机）、PR #6（FN 画像用于衡量互补）。

**具体改动**
- [x] `OperatorType.CROSSOVER`。
- [x] `cloud/operators.py`：`CrossoverOperator.generate(parent_a, parent_b, ctx)`。prompt 中放两份代码（按 token 预算截断），要求输出一个自包含程序，运行时间 < 300 s（两者运行时间之和估计 > 300 s 时，要求共享特征计算或只保留一个模型）。
- [x] 选择伙伴：`select_crossover_partner(node)`，条件为不同 branch、有效、ROS ≥ 前 30%、FN 组重叠最低（需要 analysis；缺失时用 metric 差异近似）。
- [x] 第二父节点：**不改 node 表**，新表 `node_parents(node_id, parent_id, role)` 与事件 `crossover_parents`。树结构仍以 parent_a 为 parent_id。
- [x] 老虎机中加入 crossover 臂；节点数过少时（有效节点 < 4）禁用。
- [x] 配置 `operators.crossover: {enabled: false, min_valid_nodes: 4, runtime_budget_s: 300, top_quantile: 0.3, max_code_chars: 6000}`。
- [x] 指标：`crossover_count, crossover_valid_rate, crossover_mean_delta, crossover_best_gain, crossover_tokens`。

**设计要点**：两份代码可能超出 LLM 上下文 → 截断或只给关键函数。运行时间超限 → 性能门和 smoke test 拦截（PR #3 已有）。

**测试**
- [x] `test_partner_selection_diff_branch_complementary`
- [x] `test_crossover_disabled_small_tree`
- [x] `test_node_parents_recorded_no_schema_change`
- [x] `test_crossover_in_bandit`
- [x] `test_prompt_truncation`
- [x] 其余用例见 `tests/test_crossover.py`（共 16 个）

**技能**：更新 `fe-operators`、`fe-evolve-manager`；新增 `fe-crossover-ensemble`。

**实跑验收**：一次真实运行，`crossover.enabled: true`。报告 §4.3 指标 + crossover 指标。满足合并规则（超时 ≤ 1 次）。**真实 HDD 运行统一延后**（用户决定全部实跑最后执行）。

**风险与回退**：运行时间或超时上升 → `runtime_budget_s` 调小或关闭。

**提示词摘要**
> 实现 PR #8：OperatorType.CROSSOVER + CrossoverOperator（两父代码合成单程序，运行时间 <300s），伙伴选择为不同分支且 FN 互补的高分有效节点，第二父节点记录在新表 node_parents（不改 node 表），接入算子老虎机，默认关；更新技能 fe-operators。

---

### 步骤 7：泛化到其他可靠性数据集

**目标**：证明"同一套 Skill 和引擎、只换任务目录和 adapter"即可迁移。对应评审维度：泛化。
- 顺序：**Backblaze 变体（第一）→ Alibaba SSD（第二）**。
- **Codabench 3586（SmartMem）不适合**【已核实，此前调研】：
  - 属于事件流式协议（15 min lead / 7 d 窗口、同一 SN 多次预测）
  - Phase 2 已结束，不能再提交
  - 数据许可为 CC BY-NC-SA，禁止再分发
  - Stage1 解压约 40 GB
  - 需要自写事件式评估器

**依赖**：PR #3 的 `run_local_evolution(adapter=…)`。最好在 PR #8 之后，以便用最终系统跑新数据。

**具体改动**
- [x] 通用化 adapter 选择：`evolve.yaml` `task.adapter` + `tasks/registry.py`；`fe analyze` 走注册表。默认 `hdd` 行为不变。
- [x] **7a Backblaze 变体**（`benchmark/backblaze_hdd/`）：
  - 目录 `benchmark/backblaze_hdd/`：`evaluator/init/prompt` 与 hdd_mvp 字节相同；`download_data.py` + 参数化 `prepare_data.py`；数据 **不入库**。
  - 默认季度 2024Q4→2025Q1→2025Q2；`HDD_BENCH_DATA_ROOT` 与 MVP 共用（doctor 提示确认）。
  - **真实下载/转换/进化：统一延后至最终服务器阶段**【用户提供，2026-09-29】。
- [x] **7b Alibaba SSD / SmartMem stub**：
  - `benchmark/ssd_alibaba/`、`benchmark/smartmem/`：README、`evolve.yaml`、`prepare_data.py` 骨架；**无 evaluator**。
  - `AlibabaSSDAdapter` / `SmartMemAdapter` + schema 辅助函数；`aggregate_events_to_samples` / `build_split` 未实现。
  - SmartMem 文档化事件式评估需求；**不尝试 Codabench 下载**。
- [x] 引擎无新 adapter 硬编码（`test_engine_task_agnostic.py`）；`test_hdd_protected_files.py` 锁定 hdd_mvp 哈希。
- [ ] 每个数据集的报告字段：val ROS 与 init ROS（**待服务器实跑**）。

**测试**（492 passed，基线 433）
- [x] `test_adapter_registry` / `test_backblaze_*` / `test_dataset_stubs` / `test_doctor_task_checks` / `test_hdd_protected_files` / `test_engine_task_agnostic`

**技能**
- [x] 新增 `skill/fe-dataset-adapters/SKILL.md`（替代原 fe-task-onboarding 计划名）：
  - 何时用：接入新数据集
  - 输入：原始数据路径、horizon、history、划分日期
  - 命令：prepare → 用 evaluator 评 init → `fe evolve local <new_task> --mock -n 3` → 真实运行
  - 成功检查：init ROS > 0、mock 运行完成、引擎无领域字符串
  - 故障处理：列缺失、正例过少、运行超时
  - 禁止：修改已有任务的受保护文件、提交大数据文件、把测试集放进 public
- [x] 更新 `fe-evolve-manager`（`task.adapter` + 链接 fe-dataset-adapters）。

**实跑验收**：每个数据集一次真实运行，报告 §4.3 指标及 init 对比。HDD 回归运行不需要重跑，除非改动了引擎。

**风险与回退**
- 天池下载受阻 → 只交付 7a，SSD 改用 Alibaba `ssd_open_data`（GitHub 上的小文件，单日快照）做冒烟泛化，并注明限制。
- 时间不足 → 只做 7a。

**提示词摘要**
> 实现泛化：evolve.yaml `task.adapter` 驱动 adapter 选择；prepare_data.py 参数化（默认行为不变）生成 Backblaze 变体任务目录 benchmark/hdd_bb_<variant>/（evaluator 原样复用，数据不入库）；若数据已由用户下载，则新增 benchmark/ssd_alibaba/ 与 tasks/ssd_adapter.py；新增技能 fe-task-onboarding。不要尝试 Codabench 3586。

---

### 步骤 8：最终 README

**目标**：面向评委的一页式总览。

**依赖**：全部完成（至少完成的部分）。

**TODO**
- [ ] 框架图：更新 `docs/images/` 中的架构图（可参考 RA 仓库 `docs/images/fe_architecture_v1.png`）。内容包括 Skill 入口 → 进化引擎（UCT/Jev 先验 → 算子老虎机 → 生成 → precheck/性能门/smoke → Jev 预筛 → 评估 → 三层反思/错例画像 → 分支记忆/跨枝传播 → 知识卡/发现卡）→ 本地评估。
- [ ] 结果指标表（**数字只来自各 PR 最终运行的 run_summary/fe.db**，用 report_run.py 生成）：
  | PR | run id | ROS | P | R | F1 | AUPRC | 误告率 | 漏告率 | 总 tokens | 每 ROS 点 tokens | 墙钟 | refine valid |
  |---|---|---|---|---|---|---|---|---|---|---|---|---|

  加上 init、规则基线、伐谋对照（若有）；泛化数据集单独一张表。
- [ ] 技能表：
  | Skill | 用途 | 入口命令 |
  |---|---|---|

  至少包括 fe-evolve-manager、fe-knowledge-injection、fe-jev-screening、fe-error-analysis、fe-budget-control、fe-operators、fe-knowledge-discovery、fe-data-checkup、fe-report-generation、fe-task-onboarding（按实际完成情况填写）。
- [ ] 评审维度对照表（预测性能/复杂性/自动化/泛化 → 证据位置）。
- [ ] 快速开始（§3 命令精简版）、目录结构、队伍信息（README 中目前是"（填写）"占位）。
- [ ] 可选：用 `fe report` 自动生成结果表（KD2），确保与 manifest 一致。

**验收**：README 中的每个数字都能追溯到某个 run 的产物文件；链接有效；不包含密钥和内部路径（服务器路径可写为示例）。

---

## 6. 已知问题与 backlog（来自 PR #3 及代码审阅）

### 6.1 必须修复
1. **反思路由 bug**、stop_reason 错误、traceback 只保留开头、smoke 计时缺失、自修复 token 混入 repair、`iteration_complete` 计数不一致 → **全部移到 PR #3.1**（§5 步骤 0）。
2. **错例画像始终为空**【已核实】：评估器不输出 `analysis`，而 refine 指令要求"针对错例画像"。→ PR #6。
3. 旧 main 的 `_attempt_repair` 引用未定义的 `repair_count`。PR #3 已改用 `current_attempt`【已核实，PR #3 代码】；PR #3.1 中再用 `grep -n "repair_count" src/faultevolve/cloud/engine.py` 复查一遍。

### 6.2 需要改进
4. **refine 整文件重写**：生成算子每次让 LLM 输出完整程序，导致 token 高、容易引入无关错误（PR #3 的 `fillna`/`verbose_eval`/argparse 问题都与此有关）【用户提供 + 推算】。建议：diff 或 EVOLVE-block 局部编辑模式（可选配置 `operators.edit_mode: full|diff`），可以并入 PR #7，或单独做一个小 PR。
5. **卡片有效性只有初步证据**【用户提供 + 推算】：run 5A（知识开）36.50 vs run 5B（知识关）29.81，召回 .537 vs .382。但每组只有一次运行，而且知识开时 refine valid 只有 3/10（关时为 9/10），说明卡片引导的改动更容易出错。建议：run_summary 中对比采纳卡节点与未采纳节点的平均 Δ（同一次运行内的观察性比较），由 KD1 的 `literature_card_mean_delta` 等指标延续；卡片 `impl_hint` 要注意 pandas 3 / LightGBM 4 兼容。
6. `update_insight_reputation` 是 `pass`【已核实】→ KD2。
7. `get_foreign_insights` 注释写"Hook for KGTE… will be implemented with Jev applicability scoring"，当前只按 |z| 排序【已核实】。可在 PR #4 之后加入 Jev 适用性判断（backlog）。
8. `select_operator` 固定返回 REFINE，`INJECT/TRANSPLANT` 是桩【已核实】→ PR #7。
9. `card_stats` 按 experiment_id 隔离，没有跨运行先验【已核实】→ KD1 可选 `card_priors.json`。
10. RA 的 `backend-api.md` 中 F1_p10 与 FAR 的定义写错（见 §1.3）。**不要照抄 RA 文档中的指标定义和 DDL**。
11. 单次运行方差大（PR #3 同一代码的多次运行在 32.23–36.50 之间）【用户提供】。合并规则因此采用"最优 − 约 2"（§4.4）。PR #5 的多目标 Q 可部分缓解。
12. `docs/design/01` 中规划的云端控制面、worker、`simplify` 算子、光放大器迁移不在本 TODO 范围。时间允许时作为 backlog。

---

## 7. 参考与交接清单

### 7.1 方案文件（`docs/plans/`，与本文件一起提交）
| 文件 | 内容 |
|---|---|
| `PR4-Jev快速判断-方案.md`、`PR4-cloud-agent-prompt.md` | PR #4 完整设计与 prompt（其中"10 轮开/关对照"已被最新规则取代：只做一次运行） |
| `改进路线图-调研.md` | 数据集调研（Backblaze/Alibaba/SmartMem/SMD）、评估器推算、杠杆 L1–L8、文献（其中 RA 仓库"为空"的结论已过时） |
| `PR-knowledge-discovery-方案.md`、`PR-knowledge-discovery-cloud-agent-prompt.md` | KD1/KD2 完整设计与 prompt（其中"先单独提交反思路由修复"已被 PR #3.1 取代，KD1 不再做这项修复；与本文件冲突时以本文件为准） |

### 7.2 新 AI 接手时的第一步
1. [ ] 读 `AGENTS.md`、本文件 §4、`skill/fe-evolve-manager/SKILL.md`。
2. [ ] `git fetch origin && git log origin/main --oneline -5`，确认 main 至少包含 `f7678c4`，并对照 §0 进度表找出已合并的步骤。
3. [ ] `pip install -e . && python -m pytest tests/ -q`，记录基线测试数。
4. [ ] 选取 §0 中第一个"⬜"步骤，按该节 TODO 开分支实现。
5. [ ] 完成后：draft PR → 用户在服务器上做一次真实运行 → 按 §4.3 报告 → 满足 §4.4 后合并 → 更新 §0。

### 7.3 待用户确认的问题
1. Backblaze 原始数据能否在服务器上直接下载（服务器是否联网、NAS 空间）？
2. Alibaba SSD 数据（天池 dataId 95044）由谁用天池账号下载？agent 无法自行登录。
3. （次要）PR #1 的 run id、AUPRC、FA、miss、tokens 未提供，§2.1 中对应格子暂标"待补"。
