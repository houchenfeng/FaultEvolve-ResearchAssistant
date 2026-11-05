# HDD 全量自动调优运行：计划

日期：2026-10-03（UTC）。基线：main = `43c6cd7`（PR #34，E0～E2 合入，开关默认关）。
配套：[执行 TODO](AUTOTUNE_FULL_RUN_TODO_2026-10-03.md)、[设计备忘](../design/07-HDD全量自动调优运行-设计备忘.md)、[Agent 技能](../../skill/fe-autotune-plan/SKILL.md)。
**性质：规划。本文件不含任何新实验结果；表中所有"待填"项只能由真实运行填写。**

## 1. 目标与范围

| 项 | 内容 |
|---|---|
| 目标 | 在 HDD 数据集上做**一次**完整进化运行：账本 + 随机 HPO + patch 全开，预算约 150k tokens |
| 对比对象 | 历史 Run B `final_B/f9752fcd`：最优 val ROS 38.14，10 轮，146,415 tokens，2,113 s（来源：设计 06 §2） |
| 对比口径 | 38.14 只是**历史观察点**：代码、开关、seed 不同，不是保证、不是目标上限、不是当前基线。只报告"新运行 vs 该观察点"的差值与 P/R/F1 等，**不得推断"开关带来增益"**；只有一次运行，无法区分开关效应与运行间波动 |
| 数据 | 仅 `benchmark/hdd_mvp`。不做泛化数据集，不做 gitcode 提交，不跑 `--split test` |
| 新特性默认 | 全部保持默认关闭；唯一开启处是本次实验配置文件 |
| 不在范围 | E3/E4/E5/K1、多种子/消融/稳定性实验、完整新 claim 活动 |

## 2. 阶段总览

| 阶段 | 内容 | 产出 | 通过条件才进入下一阶段 |
|---|---|---|---|
| A | 修 CI：契约漂移、事件目录、webapi 预存失败（代码在前，测试在末） | 一个修复 PR | CI 绿（见 TODO A） |
| B | HPO 接线核查（Gate H）与最小接线 | 同一 PR 或紧随 PR | `hpo` 槽位能产出可评估候选；默认关不变 |
| C | 服务器代码拉到合并提交 | 服务器 HEAD = 合并 commit | 不碰 data/results/.env，无 `reset --hard` / `git clean` |
| D | 预检 + mock 冒烟 | 通过的 `fe doctor` 与 mock 运行 | 事件中能见 `quota_slot`、`patch_*`、HPO 阶段 |
| E | 一次真实运行 | `run_summary.json`、fe.db、事件流 | 正常结束或按预算停止；不重跑择优 |
| F | 报告 | `docs/plans/autotune/FULL_RUN_REPORT.md` | 含 §5 全部必填项 |
| G | 现象级数据特征检查（可选分支） | 结论"有/无可入库特征" | 仅当"有"才出下一步知识发现计划（不执行） |

## 3. 实验配置（唯一开启处）

以 `benchmark/hdd_mvp/evolve.yaml` 为底生成完整配置（`--config-file` 会替换而非叠加该文件），仅覆盖以下键，文件放 `docs/plans/autotune/run_full_hdd.evolve.yaml`：

```yaml
seed: 20260926            # 与 evolve.yaml 同；Run B 的 seed 未核实，不声称一致
budget:
  max_iterations: 10      # 与 Run B 的主循环轮数同量级
  max_tokens: 150000      # 硬上限，约等于 Run B 的 146,415
  max_wall_hours: 6
operators: {bandit: false, enabled: [refine], crossover: {enabled: false}}
judge: {provider: none}
discovery: {enabled: false, tournament: {enabled: false}}
analysis: {enabled: false}
autotune:
  ledger: {enabled: true, full_eval_cap: 24}   # 起始提案：10 轮 + repair/HPO 晋级的余量；超限即 stop_reason=ledger_full_eval_cap
  hpo: {enabled: true, families: [logreg, lightgbm], search: random, trials_per_structure: 8, max_fits_total: 80, promote_top_k: 1}
  patch: {enabled: true, fallback: draft}
  feedback: {enabled: true}
  quota: {enabled: true, shares: {hpo: 3, patch: 5, draft: 2}}
```

要点：`quota.enabled` 要求 `operators.bandit=false`；`hpo/patch/quota` 要求 `ledger.enabled`；`full_eval_cap` 与 `max_iterations` 语义不同（后者数迭代，前者数完整评估）。`full_eval_cap=24`、`shares` 为本计划的起始提案，不是设计结论，一旦写入配置在本次比较内不得更改。

`knowledge`、`selection`、`llm`、`reflection` 等沿用 `evolve.yaml`；其与 Run B 当时配置的差异未逐项核实，报告里按"未核实"写，不要写"同配置"。

## 4. 风险与应对

| 风险 | 应对 |
|---|---|
| HPO 未接入引擎（设计备忘 §2） | Gate H；做不成就按 §6 降级并如实命名 |
| patch 因无 `FE-BLOCK` 标记大量不可用 | 事件 `patch_unavailable` 计数入报告；不为提高 patch 次数而改 `init.py` |
| 150k 预算被 HPO 之外的阶段耗尽 | 账本按阶段计账；触顶即停，不加预算重跑 |
| 单次运行方差大 | 报告写明 n=1；不做"胜负"结论 |
| 服务器 data 为符号链接 | 不触碰 `benchmark/hdd_mvp/data`；`git status` 里它的状态变化不得被"修复" |
| 误读 holdout | 只用 `--split val` 路径下 evaluator 内部读取；报告与脚本不打开 `data/holdout*` |

## 5. 报告必填项（每一份后续报告都适用）

1. 运行标识：commit、配置哈希、seed、experiment id、起止时间、`stop_reason`。
2. 最优节点 val ROS（`quality`）及与 **38.14 历史观察点**的差值（标注为观察点，不是基线）。
3. 最优节点及（可得时）每个有效节点的：**precision、recall、f1、false_alarm_rate、missed_detection_rate**（均取自 evaluator 的 `metric`，不另算）。另附 f1_p10、auprc、recall_at_far、alarms_per_1k_disks。
4. **按阶段的 token 用量**：`generate / reflect / repair / self_fix / jev / knowledge / discovery / crossover` 以及 HPO（无 LLM，标 0 并列出 trial 数与 fits 数），合计与 `max_tokens` 的比例；数据取自 `run_summary.json` 与账本 `by_stage`。
5. 节点统计：有效/无效数、各算子次数、`patch_proposed/applied/rejected/unavailable/fallback_draft` 计数、HPO trial 数与晋级数、完整评估次数、挂钟时间。
6. 限制声明：n=1、与 Run B 代码/开关/seed 不同、未做显著性检验。

缺任一项，报告视为未完成。

## 6. 降级规则（只在 Gate H 失败时使用）

若 HPO 无法小接线进引擎：不改口径，在报告标题与摘要中写明"HPO 以外部阶段运行（`scripts/autotune_hpo.py`），未参与树搜索"，并把 HPO 晋级候选作为一个独立评估记录；此时实验名称不得写成"三项全开的进化运行"。是否采用降级由人决定，agent 先回报。

## 7. 第 G 阶段：现象级特征与知识发现的门槛

在报告 F 完成后，只用**训练侧公开数据**与运行产物（不碰 holdout / eval_only 标签）检查：最优节点与基线相比，是否存在**现象级**数据特征（如某机型/某 SMART 属性窗口在失效前呈现稳定差异），并且：

- 可表述为不依赖具体程序的数据现象；
- 在时间上独立的两段数据都能复现方向；
- 能写成现有知识卡格式（`benchmark/hdd_mvp/knowledge/cards.jsonl` 的字段），且不是已有卡的重述。

三项全满足才算"可入库"。结果只有两种：
- **否**：在报告写"本轮无可入库特征"，结束；
- **是**：写**一页**下一步建议（单个特征的确认检验，沿用 [KD 建议](KD_NEXT_STEP_RECOMMENDATION_2026-10-04.md) 的 KD1 两阶段验证），**不执行**，也不规划多 claim 的锦标赛活动。

调优提分本身不等于新知识。
