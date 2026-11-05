# 思想来源与引用边界

这套方法不是对单篇论文的复现，而是对经典搜索算法和自动科研系统设计的组合式工程实现。

## 基础算法

1. Auer, Cesa-Bianchi, Fischer. *Finite-time Analysis of the Multiarmed Bandit Problem*，2002。UCB 用于在有限路线之间平衡利用与探索。
2. Kocsis, Szepesvári. *Bandit Based Monte-Carlo Planning*，2006。UCT 提供树内选择的经典形式。
3. Beam Search。这里用于限制活跃参数前沿，不把完整候选树一次展开。

## 自动科研与 Agent 系统启发

1. [karpathy/autoresearch](https://github.com/karpathy/autoresearch)：固定预算、真实指标、提升则保留否则丢弃的最小实验循环。
2. [Tree of Thoughts](https://arxiv.org/abs/2305.10601)：多候选展开、评估和剪枝思想。
3. [AI Scientist v2](https://github.com/SakanaAI/AI-Scientist-v2)：渐进式 Agent Tree Search 与实验管理方向。
4. [Arbor](https://github.com/RUC-NLPIR/Arbor)：Coordinator/Executor、想法树及开发集与 heldout 分离的工程组织。
5. [ReAct](https://arxiv.org/abs/2210.03629)：推理、动作和环境观察交替，可用于局部执行故障恢复，但不应替代科研指标判定。

## 推荐表述

> 本方法借鉴经典 UCB 与 UCT 的探索-利用思想，并结合 Beam 前沿、显式探索通道、真实 Evaluator 和异步 Coordinator，形成适用于有限方法路线与离散参数空间的分层 AutoResearch 搜索协议。

## 不应过度声明

- 未实现模拟 Rollout 时，不称为完整 MCTS。
- 未训练状态-动作价值函数时，不称为 Q-learning。
- 没有连续域代理模型和采集函数时，不称为贝叶斯优化。
- 没有 fidelity 与 checkpoint 协议时，不称为 Hyperband。
- 单任务或同数据历史有效，不代表跨数据集泛化已经得到验证。
