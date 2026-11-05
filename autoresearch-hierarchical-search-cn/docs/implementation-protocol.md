# 实现协议

## 1. 最小实验契约

ExperimentSpec 至少需要冻结：

- 路线集合与每条路线的默认参数；
- 离散参数域、条件参数和非法组合约束；
- 主指标名称、优化方向和 `min_delta`；
- Validation 数据与 Evaluator 的版本或哈希；
- 最大 Trial、墙钟时间和最大并发数；
- 重复测量次数、随机种子与聚合方式；
- Beam 宽度、探索槽位和 UCB/UCT 系数；
- Holdout 的隔离与重复验证规则。

配置示例见 [`experiment-spec.example.json`](../templates/experiment-spec.example.json)。

## 2. 候选身份与参数树

候选至少保存：

```text
candidate_id
route_id
parent_id
canonical_parameters
changed_parameter
depth
status
backprop_path
```

参数键和值必须先规范化，再生成稳定 ID：

```text
candidate_id = hash(
    route_id
    + canonical_json(full_parameters)
    + experiment_contract_version
)
```

参数树按需展开，不一次生成完整笛卡尔积。默认每个子节点只改变一个参数，使分数变化可解释。对于有序离散参数，可以优先向当前值的相邻位置扩展；条件参数只有在父条件满足时才进入候选。

除非契约声明重复测量，同一个规范化配置只能执行一次。

## 3. 默认配置阶段屏障

```text
for route in legal_routes:
    evaluate(route.default_parameters)

wait until every route default is completed or terminally failed
enable parameter search
```

屏障用于防止执行较快的路线在其他路线尚无观测时提前消耗调参预算。默认配置失败必须保存证据；是否禁用路线或允许一次受限修复，应在契约中预先声明。

## 4. Beam 与探索通道

对每条路线，用冻结主指标对所有具有可信分数且仍有合法子节点的父候选排序：

```text
ActiveFrontier(route)
    = TopKEligibleParents
    ∪ LowestVisitEligibleParents(exploration_slots)
```

默认可以从 `beam_width=3`、`exploration_slots=1` 开始，但这些不是通用最优值。

Beam 只决定哪些父节点还能继续生成子节点，不删除历史 Trial。某个候选即使没有击败全局最佳而被 Reject，只要它获得了可信分数并且仍有未探索子节点，也可以保留为路线内部的扩展父节点。

## 5. 外层路线 UCB

把每条方法路线视为一棵参数树。一个可迁移的起始公式是：

```text
quality_i = mean(top_k_scheduling_rewards(route_i))
effective_visits_i = real_visits_i + virtual_visits_i + prior_visits_i
total_visits = sum(effective_visits_j)

route_score_i = quality_i
              + c_route * sqrt(
                    log(max(2, total_visits))
                    / max(1, effective_visits_i)
                )
              - virtual_penalty * virtual_visits_i
```

第一项倾向当前表现较好的路线，第二项给访问较少的路线探索机会，第三项降低正在执行路线的再次选择概率。

同分时必须使用确定性规则，例如：真实访问更少者优先、再按契约路线顺序、最后按 `route_id` 排序。

## 6. 内层 UCT-style 父路径选择

外层选定路线后，在其活跃前沿中计算：

```text
parent_score_p = mean_reward_p
               + c_node * sqrt(
                    log(max(2, route_visits))
                    / max(1, node_visits_p + virtual_visits_p)
                 )
               - virtual_penalty * virtual_visits_p
```

候选真实完成后，沿 `backprop_path` 更新访问次数与 Reward 聚合。回传只能更新调度统计，不能用后代分数覆盖父节点自己的真实 Validation Score。

## 7. 原子预留与异步执行

候选派发必须在 Coordinator 视角下保持原子性：

```text
锁定策略状态
重新计算合法前沿
选择路线与父节点
生成并去重子候选
写入 execution_id 和 reserved 状态
沿路径登记 virtual visit
写入 dispatch event
解锁
派发 Worker
```

Worker 完成后：

```text
校验 execution_id 与 contract_hash
持久化原始执行证据和不可变指标
保证 virtual visit 只移除一次
更新真实访问次数和 Reward 统计
执行 Keep/Reject
写入 completion event
重新判断停止条件
```

回调必须支持幂等键，避免重复结果被统计两次。被取消或已经过期的执行可以保留审计记录，但不能修改当前策略状态。

## 8. Reward 与接受规则

用于调度的方向相关 Reward 可以定义为：

```text
delta = score - baseline_score          # maximize
delta = baseline_score - score          # minimize

normalized_delta = delta /
                   max(abs(baseline_score), metric_scale_floor)

reward = normalized_delta
       - duration_weight * duration_seconds
```

失败或无效 Trial：

```text
reward = -failure_penalty
       - duration_weight * duration_seconds
```

Keep/Reject 使用独立冻结规则：

```text
keep = integrity_passed
   and evaluator_succeeded
   and finite(score)
   and directional_improvement(score, current_best) >= min_delta
```

不能因为 Reward 为正就直接 Keep，因为 Reward 可能包含耗时、探索或归一化项。

## 9. 历史经验

历史经验只能来自已经通过验证、并与当前任务兼容的 Campaign。兼容条件至少包括：

- 领域与 Adapter 版本；
- 指标名称和优化方向；
- 路线身份与参数语义；
- 数据指纹或明确的数据族；
- Evaluator 协议版本。

可以把历史表现转换成较小的 `prior_reward` 和分数型 `prior_visits`。先验权重应低于当前 Campaign 的一次真实观测，确保当前 Validation 可以覆盖历史判断。

Holdout 结果不能作为路线选择特征，也不能写回搜索经验。

## 10. 停止与 Holdout

满足任一条件后停止派发新候选：

- 达到目标指标；
- Trial 预算耗尽；
- 墙钟预算耗尽；
- 候选空间耗尽；
- 用户或系统取消；
- Evaluator 或完整性契约失效。

搜索结束后，先冻结全局最佳候选、配置哈希和执行 Artifact，再启动独立 Holdout Evaluator。Holdout 可以决定最终是否验收，但不得触发新一轮搜索。

## 11. 账本字段

为了能够重放每一次选择，TrialLedger 至少保存：

```text
contract_hash
candidate_id, route_id, parent_id, full_parameters
frontier_kind, beam_rank, changed_parameter
route质量项、探索项、virtual visit项
node质量项、探索项、virtual visit项
历史先验来源、Reward和伪访问次数
execution_id, worker_id, dispatch_order, completion_order
指标原始样本、聚合方式、score、reward、duration
完整性结果、Evaluator状态、Keep/Reject原因
backprop_path、访问统计变化、停止原因
代码、数据、依赖与Evaluator哈希
```

示例见 [`trial-record.example.json`](../templates/trial-record.example.json)。

## 12. 降级策略

如果远程或学习型 Optimizer 不可用，应提供同候选协议的确定性本地 Fallback。Fallback 可以不读取跨任务先验，但必须保留：

- 默认配置阶段屏障；
- Beam 与探索通道；
- UCB/UCT-style 选择；
- 候选规范化和去重；
- Keep/Reject 独立判断；
- Holdout 隔离。

远程 Optimizer 返回的候选必须由 Harness 再次校验，不能绕过合法前沿和预算。
