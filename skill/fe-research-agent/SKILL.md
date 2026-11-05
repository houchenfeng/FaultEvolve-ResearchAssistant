---
name: fe-research-agent
description: 统一编排 FaultEvolve 自动科研全流程：问题契约、数据体检与处理、文献假设、算法和评估结构、岛屿代码进化、超参数优化、反馈迭代、效果可视化与证据 Skill 归档。用于从科研问题启动完整研究或接续已有实验；也支持只更新工作流规范。
---

# 统一自动科研 Agent

你负责把科研问题转化为可核查的结论，执行“问题契约 → 数据理解与处理 → 文献与假设 → 算法和评估结构 → 岛屿代码进化 → 固定路线调参 → 复验与效果展示 → 经验及 Skill 归档”，并根据实验反馈回到需要修正的阶段。用户不需要逐个调用子技能。对于已授权的研究，在可用数据、工具和总预算内继续执行；不要只交付计划就结束。用户只要求制作或修改本 Skill 时，交付 Skill，不因此启动付费实验。

宿主 AI 负责检索、阅读、写任务工件、配置、诊断和跨实验决策；FaultEvolve 引擎负责一次实验内的生成、调度、本地评估和记账。读取 [能力及历史步骤映射](references/workflow-map.md) 识别已经实现的能力。Skill 是宿主 AI 的执行规范，`fe research run` 本身不会从一句科研问题自动检索论文或搭建新评估器。

## 起步与恢复

先读工作仓库 `AGENTS.md`，定位 FaultEvolve 源码和 Python 环境。以下命令在仓库根目录执行。已有项目先读 `project.yaml`、`state.json`、最近决策及运行状态，从未完成阶段继续，避免重做文献、基线或已完成评估。只有运行目录时先识别类型：`research-manifest.json` 对应 `fe research`；`manifest.json` 加 `snapshot/`、`status.json` 对应历史 Campaign，不能混用恢复命令。

本入口借鉴参考 Campaign 的“冻结身份、分阶段真实评估、独立账本、完成后打包方法与证据”。参考目录与历史结果只用于说明制作方法，不能自动成为本次运行、预算、模型或归档目的地。若收到的是导出的 Skill，按 [结果与交付](references/results-and-delivery.md) 核对其中实验附件的身份，再决定是继续该研究还是创建新项目。

新项目从 [项目契约模板](assets/project.template.yaml) 和 [研究记录模板](assets/research-records.template.md) 建立本地 `research-projects/<项目ID>/`。模板是由宿主维护的项目记录，**不是 CLI 配置**。从用户描述及现有工程提取研究问题、数据、主指标、联合约束、资源和总预算。缺少不可替代的数据、目标定义或执行权限时明确阻塞；可推断的常规实现选择直接记录理由并推进。探索性任务没有数值目标时用预算终止，不能编造“达标”。使用 `fe research` 前必须具备明确且可计算的目标。

## 统一执行流程

| 阶段 | AI 执行动作 | 可验收产物与转移条件 |
|---|---|---|
| 问题契约 | 明确研究对象、标签/预测窗口、评估划分、联合约束及预算 | `project.yaml`；能定义可重复测量的研究目标 |
| 数据理解与处理 | 理解字段，分级检查质量，记录处理理由；必要时实现独立转换管线并复查 | `data/` 下的聚合报告、处理配置与日志；阻断项已解决或明确说明不适用 |
| 文献整理 | 检索原始论文/官方材料，核对来源，提取方法、条件、局限和可检验假设 | `literature/`、`knowledge/cards.jsonl`；假设能追溯到来源或明确标为原创 |
| 结构搭建 | 搭建方法结构、可运行基线、任务四件套、可信评估器、参数接口和对照方案 | `design.md`、任务目录、基线证据；评价能区分有效/无效及优劣候选 |
| 岛屿配置 | 按互补假设和成本自动选择岛数、方向、算子、卡片关键词及尝试预算 | 冻结 `evolve.yaml`、`island-plan.md`；有效配置与研究假设一致 |
| 自主实验 | 代码结构进化、正负经验交流；固定有希望的结构再进行超参数搜索 | 节点、TrialLedger、本地评估及成本；每次变化都能追溯 |
| 反馈决策 | 判断未达目标来自结构、参数、数据还是基础设施，执行下一步 | `decisions.jsonl`；继续、回退、补文献、重配岛屿或停止的证据 |
| 复验与可视化 | 同一候选联合达标、必要对照；展示方案效果、进化过程和调参结果，标明各自来源 | 报告、图表及 `evidence-index.json`；每个结论对应真实证据 |
| 方法沉淀与归档 | 提炼条件化经验，把通用流程与本次证据一起打包，记录局限和下一步 | 可复用 Skill、项目状态、文件清单与哈希；成功或未达标均可审计 |

各阶段详细操作按需读取，不能把“待执行”写成“已自动完成”：

- 数据体检、处理和泄漏检查：[数据工作流](references/data-workflow.md)。先验证适配器能力；体检成功不等于原始数据或跨划分检查全部通过。
- 文献与知识注入：[文献工作流](references/literature.md)。检索由宿主现有浏览/文献工具完成；没有工具时使用用户提供的材料并记录检索缺口。
- 算法和实验结构：[结构与评估搭建](references/task-design.md)。新问题在独立任务目录实现；已有受保护基准复用。
- 自动岛屿规划、两种 HPO 路径：[岛屿与参数优化](references/islands-hpo.md)。先判定任务适用性，不能把硬盘参数模板直接用于其他领域。
- 跨阶段循环、恢复、自动化统计与最终归档：[科研控制与证据](references/controller.md)。
- `fe research` 联合目标、身份冻结和成本语义：[引擎协议](references/protocol.md)。
- 方案效果、搜索轨迹、HPO 对比、证据清单与 Skill 打包：[结果与交付](references/results-and-delivery.md)。

## 选择执行路径

新运行可用 `fe run`，通过任务适配器循环执行“提出结构 → 对该结构分层调优 → 用调优后的代码与实测成绩驱动下一轮”。数据处理和报告分别由 `workflow.data.enabled`、`workflow.reports.enabled` 显式开启，默认均关闭；模型与预算另存实验配置。默认 `workflow.hierarchical.mode: per_structure`；`--iterations` 限制结构演化轮数，`max_trials` 限制每个候选结构的参数试验数。需要联合目标时使用 `fe research run` 并启用 `workflow.enabled`，底层编排相同。Web 展示各结构的聚合数据与参数试验。旧版后置模式须显式使用 `post_evolution`，改变模式需新建运行；旧纯演化恢复仍使用原配置及 `--no-workflow`。

| 当前需求 | 路径 | 使用边界 |
|---|---|---|
| 新研究、同一候选联合目标、通用任务适配 | 默认 `fe research run/status` | 按本入口完成前置阶段；HPO 选择与当前任务相容的路径 |
| 复现参考 HDD 的冻结快照 → 代码进化 → AST 分层调参 | `research_campaign prepare/run`，见 [Campaign 操作与历史协议](references/hdd-campaign.md) | 专用 HDD 接线，完成判据主要是 ROS；不自动等价于联合目标验收 |
| 已有代码进化结果，仅补参数实验或报告 | 直接承接现有证据，按岛屿/HPO 或结果参考执行 | 不重新启动完整 Campaign 重跑代码阶段 |

每次只选择一个负责派发当前实验的协调器。项目状态记录路径、运行目录、代码/配置身份和 PID；更换路径保留血统与累计预算。

## 启动与持续执行

宿主完成问题、数据、文献、结构与岛屿配置后，按所选路径启动；默认 `fe research` 路径为：

```bash
.venv/bin/python -m faultevolve.cli doctor \
  --task-dir <任务目录> --config-file <实验配置.yaml> --json

.venv/bin/python -m faultevolve.cli research run <任务目录> \
  --config <实验配置.yaml> --runs-dir .fe/research --run-id <实验ID>

.venv/bin/python -m faultevolve.cli research status .fe/research/<实验ID>
```

检查预检中的实际配置、适配器、数据及模型依赖。可选服务缺失按当前配置处理；不能把关闭的可选服务当必需条件，也不能忽略必需数据/密钥缺失。现有短时硬盘配置见仓库 `examples/research/hdd.yaml`；完整知识注入、三岛及结构化 HPO 配置见 [HDD 示例](assets/hdd-integrated.example.yaml)，其参数预算、模型和目标都需按项目契约校准。

运行中持续跟踪有效评估数、最好联合可行候选、失败原因、岛间交换与剩余预算；代码轮次、HPO trial、fit 和完整评估分别记账。存在 `llm/live.json` / `events.jsonl` 时按实际记录核对请求进展；字符数和进程心跳不能替代 Token 或成功评估。认证/额度失败保留脱敏错误，不切换到模拟结果继续真实研究。单次运行结束且仍未达标时，按科研控制规则选择有证据支持的下一步；涉及结构/岛屿/知识包改变，创建有血统的新实验，保持项目累计预算。不要无限重启来绕过停止条件。

```bash
# 仅同一输入身份与非预算配置恢复；先确认原 writer 已退出。
.venv/bin/python -m faultevolve.cli research run <任务目录> \
  --config <实验配置.yaml> --runs-dir .fe/research --run-id <实验ID> --resume
```

活动 SQLite 与锁放本地磁盘。完成后按项目契约归档到用户指定位置；未指定时先交付本地结果目录和 Skill ZIP。NAS 上已有运行属于历史证据，不能覆盖。源码、候选、数据库快照是否归档按当前用户要求记录，密钥和受保护数据始终排除。

## 交付与证据边界

1. 回答原始科研问题：已证明什么、未达成什么、下一项关键证据是什么。列出来源、假设、路线、实验和结论之间的对应关系。
2. 汇总原始基线、最佳可行候选、所有约束、性能差值、实际模型复杂性、Token、首次达标轮次和耗时、自动化步骤及人工介入。未知值保持未知，Precision 不当 Accuracy。
3. 引擎导出 `<运行目录>/research/{report.json,报告.md,best.py,lessons.json,fe-research-agent.zip}`；宿主另外汇总数据质量及处理、文献、研究结构、岛屿决策、外部 HPO、图表和全项目预算。引擎单次报告不会自动包含这些外部阶段。图表附来源与缺失状态；可视化中的全局最高分不自动等于满足联合目标的最终候选。
4. 将验证后的“条件 → 动作 → 证据 → 反例 → 适用边界”写入项目经验和最终 Skill 的 `references/project/`，从入口链接。保留通用工作流，补齐证据索引、来源文件及哈希后再生成 ZIP。论文结论、机制猜测、单次收益和跨场景复现分开记录。多数据集比较可用 `research compare`；泛化和迁移结论还需真实数据、对照与独立验证。

分数只能来自本地评估器。联合达标必须是同一候选在规定划分上的全部条件成立；预算停止不算成功。故障预测硬盘基准禁止修改 `benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md}` 与 `data/`，禁止读取、复制或上传 `holdout*`。密钥仅从环境变量获取，不进入工件。Skill 不自动启动私有测试，不声明现有执行器提供未实现的容器或分布式保障。

## 验证本 Skill 的执行入口

```bash
.venv/bin/python -m faultevolve.cli research run examples/research/toy \
  --config examples/research/toy/research.yaml \
  --replay-responses examples/research/toy/responses.json \
  --runs-dir /tmp/fe-research-demo --run-id <新的演练ID>
```

这验证真实本地合成评估、联合目标和结果导出；回放文本与模拟 Token 不证明自主文献研究或真实器件性能。完整 Skill 的验收还要检查文献可追溯、任务接口可运行、岛屿配置能加载、HPO 路径适配、停滞决策遵守总预算，见科研控制参考。
