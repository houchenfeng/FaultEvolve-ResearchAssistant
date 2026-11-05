---
name: hierarchical-autoresearch-search-cn
description: 为具有多条有限方法路线、离散或条件参数空间、真实 Evaluator 和明确预算的 AutoResearch Agent 设计、接入或审查分层实验搜索。采用默认路线屏障、外层 UCB、Top-K Beam 加低访问探索通道、内层 UCT-style、Virtual Visit、Keep/Reject 与隐藏 Holdout；不适用于无可信评测器、纯连续优化或完整 MCTS 的冒充实现。
---

# 分层 AutoResearch 搜索

把本 Skill 作为可执行参考实现和接入协议使用，而不是只复述算法名。

## 使用前检查

仅在目标系统同时具有以下条件时采用本策略：

- 两条以上有限的方法、模型、模块或策略路线；
- 路线内部参数可离散枚举，条件参数规则明确；
- Validation Evaluator 能真实执行并返回冻结指标；
- Trial、时间或成本预算明确；
- Validation 与 Holdout 严格隔离。

如果只有单一代码补丁流，使用线性 Baseline、Keep/Reject 和 TrialLedger。纯连续参数应使用连续优化器；渐进训练预算只有定义 fidelity 与 checkpoint 后才使用 Hyperband/ASHA。

## 操作步骤

1. 阅读目标 Agent 的候选结构、Evaluator、调度器、持久化、取消和验收逻辑，不擅自替换已有边界。
2. 阅读 [`docs/implementation-protocol.md`](docs/implementation-protocol.md)，把目标系统映射为 ExperimentSpec、Domain Adapter、Coordinator、Search Worker、Evaluator、Experience Store 和 Holdout Evaluator。
3. 复制并修改 [`templates/experiment-spec.example.json`](templates/experiment-spec.example.json)，冻结路线、参数域、指标、预算、并发语义和评测命令。
4. 先运行本包的示例验证环境：

   ```bash
   uv run python scripts/run_search.py \
     --spec examples/experiment-spec.json \
     --output-dir output/demo
   ```

5. 将示例 Evaluator 替换为目标项目的真实 Evaluator。Evaluator 必须读取候选 JSON，并向结果文件写入 `score` 与 `integrity_passed`。
6. 运行搜索，检查生成的 `ledger.json`、候选文件、Evaluator 输出和 `summary.json`。
7. 按 [`docs/verification-checklist.md`](docs/verification-checklist.md) 验证屏障、去重、UCB/UCT、并发预留、Keep/Reject、停止条件和 Holdout 隔离。
8. 接入现有 Harness 时，优先复用 [`scripts/search_engine.py`](scripts/search_engine.py) 的策略状态机；执行器、沙箱和 Artifact 仍由目标系统拥有。

## 强制不变量

- LLM 只能提出候选，冻结 Evaluator 和接受规则决定 Keep/Reject。
- 调度 Reward 与科研接受规则分开计算。
- Holdout 不得更新 UCB、UCT、Beam、Prompt、历史经验或候选生成。
- 真实 Score 不可被回传覆盖；回传只更新访问次数和 Reward 聚合。
- 候选按完整规范化配置哈希去重。
- 异步派发前原子登记 Virtual Visit，完成时只撤销一次。
- 历史先验只能来自兼容且已验证的 Campaign，权重低于当前真实观测。
- 没有 Rollout、Playout 或价值网络时，只称 `UCT-style`，不称完整 MCTS。

## 交付要求

使用本 Skill 改造其他 Agent 时，至少交付：

- 目标组件到七个逻辑角色的映射；
- 冻结 ExperimentSpec 和候选身份规则；
- 可运行 Evaluator 接口；
- 搜索引擎接入代码；
- TrialLedger 与 Holdout 报告；
- 覆盖关键不变量的测试；
- 对连续域、恢复能力、跨任务泛化和全局最优的诚实限制说明。

参考实现是标准库版本，适合作为最小可运行基线。生产接入仍需按目标系统补充持久化恢复、进程级取消、分布式锁和沙箱权限控制。
