# 自动科研协议 v1

本文定义单次 `fe research` 实验的执行契约。完整科研任务从问题、文献和结构搭建开始，入口见 [统一科研 Skill](../SKILL.md)；跨实验决策与项目预算见 [科研控制](controller.md)。文献检索、岛屿规划和全项目账本由宿主 AI 按 Skill 执行，不是本 CLI 自动完成的前置阶段。

## 任务契约

任务目录提供 `problem.md`、`prompt.md`、`init.py`、`evaluator.py`；`task.adapter: famou` 适用于 `evaluate(candidate_path, timeout=...)` 返回标准结果的任务。其他领域通过 `TaskAdapter` 接入，接口见 `src/faultevolve/tasks/protocol.py`。候选执行和数据隔离由可信评估器及适配器负责；通用编排器不额外提供容器沙箱。

```yaml
task:
  adapter: famou
research:
  domain: optical-amplifier
  dataset_id: user-optical-dataset-v1
  evidence_level: real
  evaluation_split: val
  targets:
    - {metric: combined_score, op: ">=", value: 80}
    - {metric: metric.recall, op: ">=", value: 0.85}
    - {metric: metric.false_alarm_rate, op: "<=", value: 0.01}
    - {metric: metric.parameter_count, op: "<=", value: 100000}
budget:
  max_iterations: 15
  max_tokens: 1000000
  max_wall_hours: 3
```

该示例只定义接入契约，阈值由用户业务要求确定；仓库没有提供真实光放大器数据或默认评估器。

`combined_score` 保持本地评估器原值，采用既有引擎的非负、越高越好契约；损失等越低越好的指标可配置为验收约束。评估器必须定义适当的主评分以引导搜索。全部目标按 AND 判断，不能将一个候选的高召回与另一个候选的低误告拼接为达标。指标缺失、非数值、NaN/Inf、无效候选或划分不匹配均不能通过。

`evaluation_split` 只允许 `dev` / `val` 或省略；它核对评估器返回的划分，不能改变评估器实际读取的数据。SmartMem 适配器使用 dev 时应配置 dev。`evidence_level` 是使用者声明的证据类型，不能自动验证数据真实性。

## 状态与终止

| 状态 | 判定 |
|---|---|
| `goal_achieved` | 存在一个真实有效评估满足全部目标 |
| `stopped_without_goal` | 运行结束，但预算、停滞或其他原因使目标未达成 |
| `running` / `paused` / `failed` | 沿用实验持久化状态；可保留已有结果并恢复 |

基线已经达标时停止新生成，轮次为 0。每次迭代之后检查完整目标；独立测试不参与搜索。预算控制新迭代派发，已发出的模型请求与评估仍受其自身超时约束，Token 上限可能被最后一次调用越过。

## 恢复与证据

运行目录包括：冻结配置 `research-config.json`、执行身份 `research-manifest.json`、SQLite 账本、既有引擎工件，以及 `research/` 的科研报告和 Skill。编排器使用本地文件锁，引擎另有运行声明；同一实验不得并发写入。

恢复保持目标与非预算配置不变，任务四件套、种子、岛屿配置与已有数据描述符通过既有身份检查。描述符缺失时 `data_fp` 仍为未知，不代表数据一致性已经验证。数据内容不可在相同数据集身份下悄悄替换。

允许显式调整预算，前后值写入 `research_intervention` 事件。已有调用成本由数据库恢复；墙钟预算含暂停时间；科研报告从原始基线及完整迭代事件计算首次达标，避免单进程计时重置。未知用量请求单列，费用无价格证据时保持未知。离线回放的 `cost.usage_source=synthetic`，不是服务端 Token 账单。

## 方法论与证据等级

固定评估协议 → 运行基线 → 提出可执行候选 → 本地验证 → 反思变化 → 调整结构/参数/阈值 → 检查所有目标 → 持久化并迭代 → 导出最优程序和可追溯经验。

1. 合成或回放：验证接口与终止条件。
2. 单任务真实验证：证明该任务验证集上的改进。
3. 独立时间外推、多种子与对照：验证同场景泛化和稳定性。
4. 多器件完整调优、无迁移/有迁移对照：验证跨场景有效性及迁移收益。

框架能接入新任务只属于工程迁移能力。`research compare` 保留每个任务的目标和证据级别，不将分数均值当作跨域泛化证明。跨任务经验默认不自动注入下一任务；用户需要设计迁移对照，防止将任务相关经验误当普适规律。
