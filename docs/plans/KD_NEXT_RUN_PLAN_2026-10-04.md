# 自动调优运行 89f4bdd1 之后：知识发现下一步计划与 TODO

日期：2026-10-04。性质：**仅规划，不含任何代码实现**。执行者：composer-2.5（由 claude-sonnet-5-5 medium 规划）。
循环规则（用户）：每次真实运行后，先规划，再由 composer-2.5 执行，直到得到一个完整的新知识发现结果。
基线：`main` @ `217e76b`。上游文档：[KD_NEXT_STEP_RECOMMENDATION_2026-10-04](KD_NEXT_STEP_RECOMMENDATION_2026-10-04.md)（主线决策）、[KD_WHY_NO_KNOWLEDGE](KD_WHY_NO_KNOWLEDGE.md)（逐层诊断）、[AUTOTUNE_EVOLUTION_TODO_2026-10-04](AUTOTUNE_EVOLUTION_TODO_2026-10-04.md) §9（K1）。

标注：【用户提供】运行结果，本环境无法复核（NAS 路径不存在）；【已核实】本仓库代码/文档；【推断】由前两者推出，需按 D0 复核。

## 0. 先读结论

1. **本次零发现的最可能原因是配置门控，不是数据不足，也不是锦标赛没跑通。** 【推断】`discovery_tokens=0`、`discovery_rounds=0`、全部 claim 计数为 0。`benchmark/hdd_mvp/evolve.yaml` 中 `discovery:` 整块是注释，默认 `DiscoveryConfig.enabled=False`【已核实】。`EvolutionEngine._maybe_run_discovery` 开头即 `if not self.config.discovery.enabled ... return`；`token_share` 跳过只会在 `discovery_tokens>0` 时触发，本次为 0，所以不是预算门控。锦标赛还要求 `discovery.enabled`（`config.py` 校验）。所以 discovery、crossover、tournament、mechanism 四项为 0 是同一原因的连带结果。
2. **数据不是已知阻断。** 离线核实见 KD_WHY_NO_KNOWLEDGE §3：确认集 327 个正例，足以检出单变量效应；瓶颈是**增量** AUROC（量级 0.001～0.01）以及候选质量。本次运行没有提供反证。
3. **锦标赛不是当前阻断。** 在至少一条 claim 通过沙箱+统计检验+分级前，不讨论锦标赛。
4. **不要用「打开 discovery 后重跑进化」当下一步。** 那会（a）重跑同一实验换种子刷分，被禁止；（b）候选来自程序代码差分，多是 K0 列上的改动，系统性地「显著但不新」（KD_WHY §0.4、KD 建议 §3.1）。
5. **下一步 = 与进化解耦的、有限的、原子的现象级特征因子发现（KD1-F），仅 HDD。** 进化只作为（可选）来源之一，不作为必经路径。

## 1. 已完成运行的事实（不得改动或补编）

【用户提供】实验 `89f4bdd1`；输出 `/home/hcf/nas_hcf_data/faultevolve/runs/autotune_full_20261004/89f4bdd1`；库 `/home/hcf/faultevolve/code/benchmark/hdd_mvp/.fe/runs/89f4bdd1/fe.db`。

| 项 | 值 |
|---|---|
| 状态 | finished；`stop_reason=max_iterations`；`iterations_done=10`；`wall_time_s≈2181` |
| 最优节点 | `27552c2a`（operator refine，采纳 FE01） |
| best_score / initial_score / 提升 | 25.23486863662121 / 22.807355886970594 / +2.4275 |
| 最优节点 val | precision=0.21056，recall=0.42989，f1=0.28267，FAR=0.004034，漏报率=0.57011，auprc=0.21034，quality=0.25235，split=val |
| 历史观察 ROS 38.14 | 差值 25.23−38.14=−12.91；协议/seed 未核实，**只比较，不作因果结论** |
| tokens | total=100959（prompt 63752 / completion 37207）；generate=64484，repair=7030，reflect=7936，knowledge=4272，self_fix=21509，discovery/crossover/tournament/mechanism=0；tokens_per_score_gain≈41589 |
| 质量信号 | valid_rate≈0.455；repair 尝试 1、成功 1；smoke_failures=3；perf_rejections=2；HPO 晋升 2 个 trial；patch 常不可用，回退整文件草稿 |
| 知识发现 | discovery_rounds=0；claims proposed/tested/confirmed/discovered=0；discovered_cards_count=0 |
| 文献卡 | 提供 32，采纳 7（valid 4）；FE01/T02/T03 平均 Δ 为负，部分被反驳 |
| 算子 | refine 为主，另有 hpo、repair；patch 基本不可用 |

注意：「最优节点采纳 FE01」与「FE01 平均 Δ 为负」同时出现，不矛盾（节点级 vs 卡级均值，样本极少），报告里只陈述，不解释因果。

## 2. 诊断（D0，只读，先做）

目标：把 §0.1 的【推断】变成【已核实】，且不花 token、不动数据。

对象：**副本** `fe.db`（禁止直接写原库）。

| # | 检查 | 方法 | 判定 |
|---|---|---|---|
| D0.1 | 运行时 `discovery.enabled` | 看运行产物目录里的 config 快照/`run_summary.json`/事件表；找不到快照则看启动该 run 的 yaml | `false` 或缺失 → 确认为配置门控 |
| D0.2 | 事件表是否有 `discovery_skipped` / `discovery_round_*` / `discovery_llm_error` | `sqlite3` 只读查询副本事件表 | 无 → 从未进入；有 `discovery_llm_error` → 记录内容（它会吞统计层异常，见 KD_WHY §2.1） |
| D0.3 | 可作为候选来源的数据量 | 统计正向 insight 数、`|z|≥min_insight_z(2.0)` 的数量、最优节点代码差分字符数 | 说明「从本次进化收割」能给多少候选；预期很少（10 轮、valid 仅约 45%） |
| D0.4 | 代码版本 | `git rev-parse HEAD` of `/home/hcf/faultevolve/code`，是否含 `62c8690`（日历时间切分、满秩 e-BH） | 不含 → 先同步，否则任何发现结果不可信 |
| D0.5 | 数据路径 | 只确认 `HDD_BENCH_DATA_ROOT` 指向 train/val 公开数据；**不得列出或读取 `data/holdout*`** | — |

产物：`docs/plans/` 下不新增；把结论写入下一份运行报告的「诊断」一节，以及本文件 §9 的结果表（由执行者填）。

结论分支：
- D0.1 为 enabled=true 且仍 0 轮 → 说明有未知 bug，停止本计划后续步骤，单独查 `_maybe_run_discovery` 的调用链并写诊断报告（不要继续花 LLM 预算）。
- 其余（预期）→ 进入 §3。

## 3. 下一步方案：KD1-F（解耦的原子因子发现）

### 3.1 设计原则

- LLM 只**提案**（可执行定义 + 理由）；确定性代码负责计算、去重、检验、分级。LLM 输出永不成为分数或统计结果。
- 每个 claim 是**单个**可执行 `feature(history, ...)` 返回按 serial 对齐的 Series（现有沙箱接口，`discovery/sandbox.py`、`claims.py`），不允许一次换模型、加多项特征。
- 预算护栏：候选总数 ≤30；仅探索区选 ≤3 个进入确认；候选、阈值、窗口变体都计入比较族。
- 不新增 seed 重跑；不开锦标赛；`use_jev_entailment` 保持默认（false），避免把 LLM 判断混入首个结果的统计链，除非 §3.5 明确要求。

### 3.2 候选来源（按优先级）

1. **手写确定性种子库**：`src/faultevolve/discovery/factor_library/hdd_v1.jsonl`（新文件；每行 `factor_id`、`family`、`code`、`inputs`、`window_days`、`direction`、`source`）。家族取自 KD 建议 §6.2：同计数水平下的近期加速、5/197/198 同步变化、波动相对型号常态的偏离、值/缺失模式分离、「关键计数均观测为零」群体内的剩余风险。至少含 K0 列上的**阳性对照**（如 `smart_197_raw` 近 14 天变化：已知边际显著但增量≈0）和**阴性对照**（随机置换列）。
2. **LLM 提案**：`fe discover propose`（新命令）一次调用产出 ≤N 个原子 claim，输入只给列清单、基线 K0 描述、已有卡片标题、已知阳性/阴性对照结果；输出必须通过 `extract_claim_from_response`（要求含 `def feature(`）。
3. **（可选，后置）** 从 `89f4bdd1` 副本收割：只在 D0.3 显示有足够 insight 时使用，并要求拆成原子 claim。

### 3.3 发现帧与列

`HDD_DISCOVERY_COLUMNS`（35 列：22 raw + 9 normalized + serial/date/model/capacity）【已核实】；每盘 history 最多 14 行；基线是 K0 的 9 个 SMART 列（last / 14 步差分 / 非零个数）。新颖性门槛要求与基线 max|Spearman|<0.8 且探索集增量 AUROC CI 下界>0。**只用 K0 列的简单变换几乎注定过不了该门槛**，所以种子库应偏向：未入 K0 的 raw/normalized 列、跨列交互、相对型号归一化、缺测模式。这是候选设计要求，不是已验证事实。

### 3.4 验证链（复用现有，除标注外不改统计参数）

沙箱 → `stats.test_feature`（确认集 AUROC 偏离 0.5、组 bootstrap CI、日历前后两半方向一致、BH+eBH）→ 对照（planted 强度、负对照 FPR≤0.10）→ 分级（`grade_claim`）→ `promote_claims` 写 `discovered_cards.jsonl`。
**已知局限必须写进报告**（KD 建议 §3.2）：确认集由 train 内按 serial 哈希切出，不是严格独立的盲确认；因此本轮最高只能称「HDD 公开 train/val 内的复现增量因子」，不称「已在外部数据确认」或「机制」。

### 3.5 需要的最小代码改动（交给 composer，功能先做完，测试放最后）

| # | 改动 | 文件 | 说明 |
|---|---|---|---|
| C1 | 因子库加载与注册表 | 新增 `src/faultevolve/discovery/factors.py` | 读取 jsonl；写出 `candidate_registry.jsonl`（含代码哈希、输入列、窗口、方向、基线版本、来源、比较序号） |
| C2 | CLI `fe discover factors` | `src/faultevolve/cli.py`（仿 `discover_run`） | 参数：`task_dir`、`--run-id`（副本库，用来挂载 claim/事件/token）、`--library`、`--max-candidates 30`、`--max-confirm 3`、`--runs-dir`、`--artifacts-dir`、`--env-file`、`--json`、`--mock`。不强制 `evolve`。 |
| C3 | 探索区预筛 | `discovery/factors.py` | 在探索集上算增量 AUROC，选 ≤3 个；**选择只用探索集**，确认集此前不访问 |
| C4 | 复用 `DiscoveryRound` 的 claim 处理路径 | `discovery/pipeline.py`（尽量只加入口，不改统计） | 把「候选来源」从 harvest 扩成可注入列表 |
| C5 | 暴露被吞异常 | `discovery/pipeline.py`、`cli.py` | `fe discover ... --json` 汇总中加入 `discovery_llm_error` 计数与首条摘要（KD_WHY §2.1） |
| C6 | 漏斗报告 | `discovery/report.py` | 提出→可执行→覆盖足够→非重复→探索增量→冻结→确认→（文献查重留空，标「未做」）；每个失败给唯一主因 |
| C7 | token 分层报告 | `discovery/report.py`、`common/metering.py` | 见 §6 |
| C8 | skills 更新 | `skill/fe-knowledge-discovery/SKILL.md`、`skill/fe-report-generation/SKILL.md` | 本 PR 已加桩，实现后补命令实测输出 |

不得改：`benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md}`、`data/`；不得读取 `data/holdout*`；`discovery/stats.py` 的 α、`rho_max`、eBH 阈值与 `max_neg_control_fpr` **不得为了出结果而放宽**。

### 3.6 若证据指向「架构/锦标赛」才是阻断

触发条件（全部满足才进入）：KD1-F 至少 1 条 claim 达到 `confirmed` 或 `discovered` 现象卡，但机制层 `mechanisms_established=0`。此时最小路径：

1. `discovery.enabled: true` + `discovery.tournament.enabled: true`，仅对已晋升的现象卡运行；起始值 `n_slices=4`（上限 16）、`max_rounds=3`、`max_rivals=2`、`min_env_pos=5`、`max_token_share=0.10`——这些是 `TournamentConfig` 现有默认，沿用。
2. 先核对 327 个确认集正例按 4 个切片后每片环境内正例数（`min_env_pos=5`）是否够；不够则降 `n_slices`，**不降** `icp_gate_p`/`equiv_margin`。
3. 成功检查：事件里出现 `tournament_*` 与 `mechanism_*`；`mechanisms.json` 非空；`certificates.json` 要么有证书，要么有明确的 `blocked` 原因。
4. 不够 decisive 对局（参考 demo_real2：32 场仅 1 场 decisive）就停，写成「赛制在 HDD 的功效不足」报告，不继续加轮数。

这一步**不在本轮首选**，写在这里只为后续不再讨论。

## 4. 「完整的新知识发现结果」的明确定义

满足下面 **A**，才可对用户宣称本轮发现成功；只满足 B 是「完整的负结果」，必须如实标注，不能叫发现。

**A（成功）** 同时满足：
1. 至少 1 个原子因子 claim，在确认集上达到现有分级的 `confirmed` 或 `discovered`（已通过 BH+eBH、日历前后两半方向一致、`functional_novel`：与 K0 基线 max|ρ|<0.8 且探索集增量 AUROC CI 下界>0）。
2. 该因子在 `phenomena.json`/`discovered_cards.jsonl` 中有**测得的数值**：单因子效应（AUROC−0.5）及 CI、与基线 max|ρ|、增量 AUROC 及 CI、确认集正例数。
3. 阴性/阳性对照通过：负对照 FPR≤0.10，planted 强度的检出符合预期。
4. 有可复现产物包：`candidate_registry.jsonl`、`data_audit` 摘要、代码哈希、git SHA、配置、命令。
5. （加分项，非必需）把该卡注入一次**新的**进化并报告观察性 Δ。若做，必须是新任务设定的一次性运行，且结论写「观察性，无因果」。

**B（完整负结果）** 漏斗全部走完，且每个失败有主因，并给出下列之一：功效不足（所需正例数估计）、候选无增量（CI 排除预设 δ）、验证链不可靠（对照未通过）。

**禁止**把以下当成成功：计数器出现一张卡但无数值；`mechanisms_established` 来自脚本化探针；对 89f4bdd1 换种子/换预算重跑后拿更高 ROS；调低 α/eBH/蕴含判断后得到 discovered。

## 5. 命令（真实运行手册）

环境：服务器 `/home/hcf/faultevolve/code`，需 `DASHSCOPE_API_KEY`（环境变量或 `--env-file`，禁止写入文件/日志/提交）。

```bash
# 0) 同步代码并确认含 62c8690
cd /home/hcf/faultevolve/code && git fetch origin main && git log --oneline -1 && git merge-base --is-ancestor 62c8690 HEAD && echo ok

# 1) 复制原库到本地磁盘副本（SQLite 放本地，不放 NAS）
SRC=/home/hcf/faultevolve/code/benchmark/hdd_mvp/.fe/runs/89f4bdd1
DST=/home/hcf/faultevolve/runs_copy/kd1f_20261004
mkdir -p "$DST/89f4bdd1" && cp "$SRC/fe.db" "$DST/89f4bdd1/fe.db"

# 2) 只读诊断（D0）
sqlite3 "file:$DST/89f4bdd1/fe.db?mode=ro" "select event_type,count(*) from events group by 1 order by 2 desc;"
# 若表名/列名不同，先 .schema，再调整，不要猜。

# 3) 数据体检（只用公开 train/val）
fe doctor --json --task-dir benchmark/hdd_mvp
fe data checkup benchmark/hdd_mvp --json --out "$DST/datacheck"

# 4) 离线 mock 全链路（无 API、无 token）；C2 实现后可用
fe discover factors benchmark/hdd_mvp --run-id 89f4bdd1 --runs-dir "$DST" \
  --library src/faultevolve/discovery/factor_library/hdd_v1.jsonl --mock --json

# 5) 真实运行：先 LLM 提案（小预算），再全链路
fe discover propose benchmark/hdd_mvp --run-id 89f4bdd1 --runs-dir "$DST" \
  --max-candidates 12 --env-file "$HOME/.fe.env" --json
fe discover factors benchmark/hdd_mvp --run-id 89f4bdd1 --runs-dir "$DST" \
  --artifacts-dir /home/hcf/nas_hcf_data/faultevolve/runs/kd1f_20261004 \
  --library src/faultevolve/discovery/factor_library/hdd_v1.jsonl --max-candidates 30 --max-confirm 3 \
  --env-file "$HOME/.fe.env" --json | tee "$DST/kd1f_summary.json"

# 6) 报告与数字核对
fe discover report benchmark/hdd_mvp --run-id 89f4bdd1 --runs-dir "$DST" --json > "$DST/kd_report.json"
python skill/fe-knowledge-discovery/scripts/check_discovery_summary.py /home/hcf/nas_hcf_data/faultevolve/runs/kd1f_20261004
```

注意：`fe discover propose`、`fe discover factors`（及其 `--library/--max-confirm`）**目前不存在**，是 C2 要新增的；已存在的是 `fe discover run`（`--run-id/--mock/--max-claims/--runs-dir/--artifacts-dir/--env-file/--json`）和 `fe discover report`【已核实】。`--env-file` 路径只是占位示例。

## 6. 报告：token 分层与每分数增益 token

真实运行报告（`fe report`/`discover report` 产物及手写总结）必须包含：

1. **按阶段 token 表**：`generate / repair / reflect / knowledge / self_fix / discovery / crossover / tournament / mechanism`，列 prompt、completion、合计，占总量百分比。数字只来自 `run_summary.json`（`common/metering.py` 的计量），`check_report_numbers.py` 必须通过，不得手改。
2. **本次发现运行**的 token 单独成表：`propose`、`translate/claims`、`entailment`（若开启 Jev）。若 `discovery_tokens` 未计入 `total_tokens`，先修计量，不要在报告里手工相加。
3. **tokens_per_score_gain**：定义沿用 `compute_tokens_per_score_gain(best_score, initial_score, eps=0.001)` = total_tokens / (best_score − initial_score)，单位「每 ROS 点」。对 89f4bdd1 的参考值：100959 / 2.4275 ≈ 41589【与用户提供一致】。纯发现运行没有分数变化，**此指标写 `n/a`**，不得用 eps 造出巨大数字。
4. **发现专属效率指标**（新增在报告里，由 C7 计算）：`tokens_per_candidate_tested`、`tokens_per_confirmed_claim`（confirmed=0 时写 `n/a`）、`discovery_token_share`。
5. 对比 89f4bdd1 的 tokens_per_score_gain 与历史 38.14 运行时，必须同列出 seed/协议/代码版本差异，写「仅并列，无因果」。

## 7. 失败处理

| 现象 | 动作 |
|---|---|
| 沙箱失败（`KeyError`、裸 `exit N`） | 读 `error_tail`；先在手写 claim 上跑 `tests/test_kd_sandbox_probe.py` 的同类探针确认环境；LLM claim 失败则记入漏斗主因「不可执行」，不重试刷过 |
| `discovery_llm_error` > 0 | 打印事件内容（C5）；多半是统计层被吞异常，修异常本身，不放宽阈值 |
| 候选全因 `rho_max` 或增量 CI 被拒 | 属于合法 B 结局；报告增量 CI，转换候选空间（下一轮规划），不调阈值 |
| 全部候选 `undetermined` 因 eBH（单条 claim 需 p≤6.25e-4） | 报告所需功效；不改 eBH |
| LLM 调用失败/限流 | 指数退避重试最多 4 次；仍失败则保留已完成漏斗阶段并标记未完成，不伪造 |
| 磁盘/DB 锁 | SQLite 只放本地盘；副本库损坏则重新复制，不改原库 |
| 发现自己读了或要读 `data/holdout*` | 立即停止，不记录内容，在报告中说明 |

## 8. 非目标

- **不对 89f4bdd1 换 seed、换预算、换配置重跑去刷 ROS 或刷 discovered。** 本轮是在其副本库上做 post-hoc 发现，不产生新的节点分数，也不更新其 best_score。
- 不追 38.14；不把 25.23 vs 38.14 的差解释成某个改动的因果。
- 不做锦标赛主线、不调 α/eBH/蕴含、不增加进化轮数。
- 不做 SSD/内存数据集；不接外部新数据（缺独立确认集时如实标注）。
- 不改受保护基准文件，不读 holdout。

## 9. TODO（给 composer-2.5，按序执行）

**测试规则（用户）：先把功能做完，测试放最后，且最小化。**

- [ ] **S0 分支与基线**：`git fetch origin main`，从最新 main 开分支 `cursor/kd1f-factor-discovery-<suffix>`；`pip install -r requirements.txt`。（不先跑全套测试。）
- [ ] **S1 D0 诊断**（§2）：服务器上对副本库只读查询，填下方结果表。
- [ ] **S2 C1 因子库与注册表**：写 `hdd_v1.jsonl`（≥20 个、≤30 个原子因子，含阳性/阴性对照）与 `factors.py`。
- [ ] **S3 C4 入口注入 + C3 探索预筛 + C2 CLI**：`fe discover factors`、`fe discover propose`。
- [ ] **S4 C5 暴露被吞异常**、**C6 漏斗报告**、**C7 token 分层**。
- [ ] **S5 skills**：补全 `fe-knowledge-discovery`、`fe-report-generation` 的命令与成功检查（已有桩）。
- [ ] **S6 离线 mock 全链路**：§5 步骤 4，确认产物齐全。
- [ ] **S7 最小测试（最后）**：只新增/运行与改动直接相关的：因子库 schema、`factors` 探索预筛不访问确认集、CLI mock smoke、`check_report_numbers`；加 `tests/test_hdd_protected_files.py`。不跑全量回归，除非用户要求。
- [ ] **S8 真实运行**（需 `DASHSCOPE_API_KEY`）：§5 步骤 5～6，单次，不重复。
- [ ] **S9 写结果报告**：漏斗、§4 成功判定（A 或 B）、§6 token 表；更新 `docs/TODO.md` 顶部入口与本节结果表；回报用户。

结果表（执行者填写，**只填真实值**）：

| 项 | 值 |
|---|---|
| main / 运行用 git SHA | |
| D0.1 discovery.enabled | |
| D0.2 事件摘要 | |
| 候选：提出/可执行/覆盖足够/非重复/探索增量>0/冻结/确认/发现 | |
| 最佳候选：效应、CI、max\|ρ\|、增量 AUROC CI、确认集正例数 | |
| 对照：负对照 FPR、planted 检出 | |
| discovery tokens / total tokens / 占比 | |
| 按阶段 token | |
| 结论：A / B（主因） | |
