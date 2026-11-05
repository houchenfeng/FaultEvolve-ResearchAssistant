---
name: fe-closed-loop-tuning
description: 基于评价结果的闭环反馈自动调优方法：冻结评估器与基线，每轮提出新结构、对该结构分层调优，用调优后的本地评分驱动下一轮生成与反思，直到达到目标或预算与停滞条件触发。用于“让模型自己迭代到达标”“把一次调优过程变成可复用流程”“判断该继续跑、改配置还是停止”。不适用于没有可信评估器或没有明确目标的场景。
---

# 评价驱动的闭环调优

本 Skill 把 FaultEvolve 一次完整调优的经验固化为可重复执行的流程。它只规定**怎样用评价结果驱动下一步**；引擎细节、岛屿配置、数据处理、报告导出分别见 `fe-island-evolution`、`fe-data-checkup`、`fe-report-generation`，更大范围的科研编排见 `fe-research-agent`。本 Skill 的经验来自一次 HDD 20 轮真实运行，数字和适用边界见 [本次证据](references/evidence-hdd-20-rounds.md)。

## 闭环是什么

```text
冻结：评估器、数据口径、基线、目标分、预算
loop:
    生成候选（父节点 + 算子 + 知识卡 + 岛间经验）
    静态检查 / 冒烟 → 仅对该候选结构分层调参（本地评估器是唯一分数来源）
    把调优后选中的代码、指标与评分一起写回节点
    反思：为什么变好/变差 → 写入分支记忆、证伪假设、岛间交流
    用分数更新选择（UCT）与停止判断
    达标且无需继续 / 预算耗尽 / 停滞 → 退出
对比基线、写报告、把可复用经验写回
```

三条硬规则：**分数只来自本地评估器**（LLM、Jev、反思文本不能成为节点分数）；**评估器、基线、数据一经冻结不再改动**（改了就是新的可比基线）；**预算是上限，不是目标**。

每次新运行从当前任务提供的初始模型开始，不预设已有最优方案，不自动导入其他运行的模型或成绩。只在本次运行内保留最佳候选并继续搜索；断点恢复沿用同一次实验。迁移到不同任务时复用评价反馈流程，由新任务提供其初始模型与评估器。

## 执行步骤

1. **确认前置**。读 `AGENTS.md`，用当前任务的本地评估器评估初始模型，记录真实基线。HDD 示例为 `cd benchmark/hdd_mvp && python evaluator.py init.py`，其 val ROS 应约22.81；不能把这个数用于其他任务。
2. **写配置，显式决定停止策略**（见下节“停止与停滞”）。不要沿用“全部为 0/null”的默认值而不自知。
3. **小规模冒烟**。`fe evolve local <任务目录> -n 3` 跑通全链路，检查：显式开启数据处理时复检 passed，否则数据步骤为 disabled；每轮有 `iteration_complete`、`insight_extracted` 里的 mechanism 不是占位文本 `Score changed by ...`（占位说明反思调用失败，见排错）。
4. **正式运行**。命令模板和资源约定见 [运行与排错](references/run-and-troubleshoot.md)；数据库放本地磁盘，产物目录可放 NAS。
5. **看反馈再决策**，不要只等跑完。按下表读事件和 `run_summary.json`。
6. **出报告**。单独运行 `fe report <任务目录> --run-id <ID> --workflow` 导出已有证据；只有显式开启 `workflow.reports.enabled` 才自动导出。报告失败不改变搜索成绩或完成状态。`effect-report.json` 含已知性能、复杂度、token、收敛、自动化；按 [报告模板](assets/report.template.md) 补局限。
7. **沉淀**。把验证过的“条件 → 动作 → 证据 → 反例”追加到本 Skill 的 `references/`，不要把单个数据集的最佳超参数写成默认。

## 导出完整指标与标准交付

在已安装 FaultEvolve 的仓库根目录运行。正式配置显式启用 `workflow.enabled: true` 和
`workflow.hierarchical.mode: per_structure`，并设置结构轮数、每结构试验数、目标与停止条件。
`fe run` 会执行逐结构闭环，宿主不需要手工按每轮成绩改写节点分数。核心通过当前任务适配器评分，不要求 HDD 数据格式。

数据处理与报告是独立可选项：`workflow.data.enabled` 和 `workflow.reports.enabled` 默认均为 false。开启数据处理时，任务适配器必须实现相应能力；否则沿用任务原始输入。模型选择与全局预算放在实验配置的 `llm`、`budget`，每结构预算放在 `workflow.hierarchical`。HDD 完整实验配置示例为仓库 `examples/experiments/hdd_closed_loop.yaml`；不同任务另写实验配置，不把这份配置当作通用默认。

完成后导出各阶段指标并打包包含当前证据的本 Skill：

```bash
python scripts/export_closed_loop_delivery.py \
  --run-id <运行ID> --runs-dir <本地运行根目录> --artifacts-dir <产物根目录>
```

运行中可以增加 `--partial` 查看已完成记录；不能据此声明运行完成。产物包括
`reports/stage-metrics.csv`（基线、各轮默认与调优后）、`parameter-trials.csv`（全部参数试验）、
`token-ledger.csv`（提供商逐次用量）、中文 Markdown/HTML 报告和 `fe-closed-loop-tuning.zip`。

准确率使用机队加权 `(TP+TN)/(TP+FP+FN+TN)`，另报无权样本准确率；precision 为精确率。
误告/漏告数量是加权数量，可能为小数。故障比例低时不能只按准确率决定改进。
参数量与源码复杂度为静态估计，无法确定的值留空；未实测的模型大小、FLOPs、内存不得补造。
逐轮 Token 包含本轮生成、修复和反思，参数试验本身为零；未知用量及缓存命中需分开记录。

## 读反馈、做决策

| 观察到的现象 | 判断 | 下一步 |
|---|---|---|
| 连续多轮最佳分不变，且各轮得分上下波动 | 当前配置下已进入平台期，继续花 token 的边际收益低 | 启用停滞早停，或换岛屿方向/补知识卡，而不是加轮数 |
| 目标分已达，但仍有预算 | 目标是下限不是终点 | 由 `stop_at_target` 决定：要“达标即停”设 true；要“尽量更高”设 false 并配合停滞早停 |
| 首轮得分低于基线 | 单次生成不保证改进 | 正常；看后续轮次，不要据一轮改配置 |
| `finish_reason=length` 且正文为空 | 推理模型把短调用的 token 额度全部用于思考 | 对短 JSON 调用关闭 thinking（已在 `chat_for_reasoning` 修复），不要只加大 max_tokens |
| `hypothesis_refuted` 多发生在“换阈值策略” | 阈值机制失效会让分数崩塌（精确率塌） | 保留已验证的阈值选取，把变化限定在特征/模型上 |
| 岛间只有“最优”摘要，没有失败/知识摘要 | 负向经验没有流动 | 检查交换配置与净化规则，见 `fe-island-evolution` 的 exchange 参考 |
| 分层调优最佳出现在前几次，之后长时间无改进 | 参数空间窄或已饱和 | 缩小 `workflow.hierarchical.max_trials`；要更大收益应扩大可调参数集合，而非加试验数 |
| 最高分与最终选用方案不同 | 需区分代码阶段与调优阶段最佳 | 以 `workflow-result.json` 的 `best_origin` 为准 |
| 分数提升很小且没有独立集验证 | 可能是验证集反复选择 | 报告里必须写“无泛化证据”；私有 holdout 不得读取 |

## 停止与停滞

`budget.stagnation_window = 0` **表示关闭停滞早停**，此时引擎只会在 `max_iterations`、token、时长或（`stop_at_target: true` 时）达标后停止。一次 20 轮运行里，最佳分在第 5 轮之后再没刷新，后 15 轮约 42 万 token 没有换来提升，原因正是该窗口为 0。推荐起点（需按任务校准，不是通用标准）：

```yaml
budget:
  max_iterations: 20
  stagnation_window: 6          # 连续 6 个最佳值增量低于噪声即停
  min_iterations_before_stop: 5
  tokens_per_point_cap: null    # 有成本上限再设
stop:
  target_score: 33.7            # 必须可计算；探索性任务没有目标就不要编造
  stop_at_target: false         # 达标后继续，由停滞早停收尾
```

窗口大小与噪声阈值要结合评估器的 bootstrap 标准差（本任务 `f1_boot_std` 约 0.02，对应评分噪声约 1 分量级）校准：窗口过小会在正常波动里误停。

## 分层调优何时有用

默认 `workflow.hierarchical.mode: per_structure`，每个新结构先在自己的参数域内搜索，再按调优成绩参与外层结构选择；无需等两条路线才开始。`max_trials` 是每个候选结构的预算（含默认参数），不是全运行总数。先检查 `hyperparameters/structures/<node-id>/` 的提案、逐次评分和选中版本，确认 `iteration_complete` 对应的是选中版本。没有可识别参数的结构只评估原程序一次。调优不消耗 LLM token，但每次本地训练仍有成本。

历史 20 轮证据采用“演化结束后统一调优”，只代表旧流程。要复现它，显式设置 `mode: post_evolution` 并新建运行。不要把旧运行报告当作逐结构闭环的实验结果。

## 边界

- 本 Skill 不启动私有测试，不读取 `benchmark/hdd_mvp/data/holdout*`，不修改受保护基准文件。
- 密钥只从环境变量获取，不写入任何工件。
- 跨数据集（内存、光放大器）泛化与迁移**未验证**：仓库内没有相应数据；接入时按 `fe-dataset-adapters` 实现适配器并分别建立基线，不同评分公式不平均。
- 参数量是静态估计，随机森林等依赖数据的模型不估计。
- 自动化覆盖率按事件日志中的中断/恢复计人工介入；线下操作不可见，不能当作“零人工”的证明。
