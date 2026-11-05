# 验证清单

## 契约与候选

- [ ] 非法指标方向、空路线、无效预算和非法参数域会被拒绝。
- [ ] 所有默认路线完成或终态失败前，不会派发参数子节点。
- [ ] 等价的规范化参数配置得到相同 Candidate ID。
- [ ] 条件参数和非法组合不会进入执行队列。
- [ ] 未声明重复测量时，相同候选不会重复执行。

## 搜索策略

- [ ] 高 Reward 路线获得更多利用机会。
- [ ] 低访问路线仍能获得探索机会。
- [ ] Top-K Beam 与低访问探索候选都能进入活跃前沿。
- [ ] UCB/UCT 同分时的结果是确定性的。
- [ ] 子节点回传不会覆盖父节点真实 Score。
- [ ] 失败或无可信指标的 Trial 不能进入高分 Beam。

## 并发与恢复

- [ ] 并发预留不会选择相同 Candidate ID。
- [ ] Virtual Visit 在派发前登记，并且只移除一次。
- [ ] 重复回调不会重复增加访问次数。
- [ ] `execution_id` 不匹配的过期结果不能修改活动状态。
- [ ] 取消信号能够传播到 Worker 和 Evaluator。
- [ ] Coordinator 重启后能从账本恢复，或明确将未完成 Trial 标为中断。

## Reward 与 Keep/Reject

- [ ] Reward 只影响调度，不直接决定候选是否 Keep。
- [ ] `maximize` 与 `minimize` 的方向处理正确。
- [ ] `min_delta` 与当前最佳候选比较，而不是只与 Baseline 比较。
- [ ] NaN、Inf、Evaluator 失败或完整性失败必定 Reject。
- [ ] Reject 不会破坏当前最佳 Artifact。

## 经验复用

- [ ] 只有通过验证且协议兼容的 Campaign 可以提供先验。
- [ ] 历史先验权重低于当前任务真实观测。
- [ ] 数据、Adapter、指标或 Evaluator 不兼容时不会错误迁移经验。
- [ ] 记录先验来源、伪访问次数和选择概率，方便审计。

## Holdout

- [ ] Holdout 数据、标签和错误信息对搜索过程不可见。
- [ ] Holdout 分数不进入 Reward、UCB、UCT、Beam 或 Prompt。
- [ ] 最佳候选和 Artifact 哈希在 Holdout 前冻结。
- [ ] Holdout 失败不会自动产生新候选。

## 回放与声明

- [ ] 仅依赖 ExperimentSpec 和 TrialLedger 可以重建访问统计、最佳候选和停止原因。
- [ ] 本地 Fallback 与远程 Optimizer 遵守相同合法前沿协议。
- [ ] 文档称其为 UCT-style，而不是完整 MCTS。
- [ ] 文档不声称全局最优、通用 RL 或未经验证的跨数据集泛化。
