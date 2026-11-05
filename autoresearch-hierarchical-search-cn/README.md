# 分层 AutoResearch 实验搜索方法

这是一套面向 AutoResearch、AutoML 和实验型 Agent 的可执行中文 Skill。它适用于存在多条有限方法路线、每条路线内部又有离散或条件参数，并且能够通过真实 Evaluator 获得可比较指标的任务。

核心目标不是让 LLM 自由尝试一切，而是在固定指标与预算下回答两个问题：

1. 下一份实验预算应该投给哪条方法路线？
2. 在选中的路线里，应该从哪个参数父节点继续扩展？

为此，本方法组合使用：

- 默认配置阶段屏障，确保所有合法路线先获得一次真实观测；
- 外层 UCB，在不同方法路线之间平衡利用与探索；
- Top-K Beam，限制仍可继续扩展的高价值父节点；
- 低访问探索通道，避免 Beam 过早淘汰潜在路线；
- 内层 UCT-style，在参数树中选择下一条父路径；
- Virtual Visit，减少异步 Worker 重复涌向同一路线；
- 冻结 Evaluator、Keep/Reject 和隐藏 Holdout，保证实验结论可审计。

## 适用条件

同时满足以下条件时再使用这套策略：

- 至少存在两条有限的方法、模型、模块或策略路线；
- 路线内部参数是离散的，或能够明确枚举合法取值；
- Validation Evaluator 可重复执行并返回预声明指标；
- 已声明 Trial、墙钟时间或成本预算；
- Validation 与最终 Holdout 之间存在明确隔离。

以下情况不应强行套用：

- 只有一条线性代码补丁流：使用 Baseline、Keep/Reject 和 TrialLedger 即可；
- 只有连续参数：优先使用贝叶斯优化等连续域方法；
- 搜索对象是 epoch、数据比例或训练步数：只有定义 fidelity 与 checkpoint 契约后才适合 Hyperband/ASHA；
- 没有可信 Evaluator：应先修复评测契约，搜索算法无法弥补错误指标。

## 总体流程

```text
冻结 ExperimentSpec
        ↓
运行 Baseline 与所有路线默认配置
        ↓
等待默认配置阶段屏障
        ↓
为每条路线建立惰性参数树
        ↓
Top-K Beam + 低访问探索通道形成活跃前沿
        ↓
外层 UCB 选择方法路线
        ↓
内层 UCT-style 选择参数父路径
        ↓
Coordinator 原子预留候选并登记 Virtual Visit
        ↓
异步 Worker 真实执行 Evaluator
        ↓
记录 Score、Reward、Keep/Reject 与 TrialLedger
        ↓
达到目标、预算耗尽、空间耗尽或取消
        ↓
冻结全局最佳配置并在隐藏 Holdout 上复验
```

## 快速运行

要求 Python 3.11 及以上，不依赖第三方 Python 包。

```bash
cd autoresearch-hierarchical-search-cn

uv run python scripts/run_search.py \
  --spec examples/experiment-spec.json \
  --output-dir output/demo
```

Windows PowerShell 可以写成一行：

```powershell
uv run python scripts/run_search.py --spec examples/experiment-spec.json --output-dir output/demo
```

输出包括：

- `output/demo/ledger.json`：完整 TrialLedger 和每次策略决策；
- `output/demo/summary.json`：停止原因、最佳候选和 Holdout 结果；
- `output/demo/runs/`：每个候选的输入、Evaluator 输出和执行证据。

运行测试：

```bash
uv run python -m unittest discover -s tests -v
```

Evaluator 接口很小：读取 `{candidate_file}` 指向的 JSON，并向 `{result_file}` 写入：

```json
{
  "score": 0.82,
  "integrity_passed": true
}
```

完整示例见 [`examples/toy_evaluator.py`](examples/toy_evaluator.py)。

## 最重要的设计边界

### Reward 不等于 Keep/Reject

Reward 用来决定以后优先搜索哪里，可以包含相对提升、执行耗时和失败惩罚。Keep/Reject 是冻结的科学接受规则，只能根据完整性、Evaluator 状态、主指标方向和最小提升阈值判断。

### Holdout 不参与搜索

Holdout 的样本、标签、错误信息和分数都不能进入 UCB、UCT、Beam、Prompt 或候选生成。它只在搜索结束、最佳候选冻结后进行最终验收。

### UCT-style 不等于完整 MCTS

本方法没有模拟 Rollout、随机 Playout 或价值网络。每一个 Reward 都来自真实实验，所以准确称呼应为“真实 Validation 驱动的 UCT-style 参数树搜索”。

### LLM 只能提出候选

LLM 可以提出路线、参数、假设或代码，但不能自行宣布实验成功。候选是否合法、是否执行、是否 Keep，必须由确定性 Harness 和冻结 Evaluator 决定。

## 如何接入现有 Agent

将现有系统映射到以下逻辑角色，不要求使用特定框架或语言：

| 角色 | 职责 |
|---|---|
| ExperimentSpec | 冻结候选空间、指标、预算、Evaluator 和 Holdout 边界 |
| Domain Adapter | 把规范化候选转换成实际配置、命令或文件 |
| Coordinator | 唯一管理候选预留、策略状态、账本和停止条件 |
| Search Worker | 执行一个已预留候选，返回真实证据 |
| Evaluator | 从真实执行结果计算 Validation 指标 |
| Experience Store | 提供兼容且已验证的历史先验，并保存本轮结果 |
| Holdout Evaluator | 在搜索结束后独立验收冻结的最佳候选 |

这些角色可以位于同一进程。多个 Search Worker 也不必是多个 LLM 或多个容器，它们只是并发执行槽位。

## 目录

- [`docs/implementation-protocol.md`](docs/implementation-protocol.md)：公式、状态、候选生成、并发与经验复用协议。
- [`docs/verification-checklist.md`](docs/verification-checklist.md)：实现和发布前的验证清单。
- [`SKILL.md`](SKILL.md)：供其他 Agent 加载的中文操作指令。
- [`scripts/search_engine.py`](scripts/search_engine.py)：分层搜索状态机。
- [`scripts/run_search.py`](scripts/run_search.py)：可执行 CLI 和 Evaluator 调度器。
- [`examples/`](examples/)：可以直接运行的确定性示例。
- [`tests/`](tests/)：默认屏障、去重、契约和端到端 Holdout 测试。
- [`templates/experiment-spec.example.json`](templates/experiment-spec.example.json)：实验契约模板。
- [`templates/trial-record.example.json`](templates/trial-record.example.json)：单次 Trial 账本模板。
- [`REFERENCES.md`](REFERENCES.md)：思想来源和可声明边界。

## 可以诚实声明什么

可以描述为：

> 一种面向有限方法路线与离散参数空间的分层实验搜索策略。它先完整评测各路线默认配置，再通过外层 UCB 分配路线预算，使用 Top-K Beam 与探索通道构造树内前沿，并以 UCT-style 分数选择父路径；候选由真实 Evaluator 评分，最终最佳配置在未参与搜索的 Holdout 上独立复验。

不要声明：

- 找到了数学意义上的全局最优；
- 实现了完整 MCTS；
- 实现了 Q-learning 或通用强化学习策略；
- 离散枚举等价于贝叶斯优化；
- 没有 fidelity/checkpoint 契约时已经实现 Hyperband；
- 在单一数据集上的历史经验已经证明跨数据集泛化。

## 发布说明

本目录是框架无关的中文 Skill 和可执行参考实现，不依赖 Codex、LangChain、LangGraph 或特定 AutoResearch 项目。参考 CLI 已实现核心搜索闭环，但生产使用仍需要接入目标系统的持久化恢复、进程级取消、分布式锁、沙箱和权限控制。正式公开前，请根据你的发布方式补充作者信息和 LICENSE；不要在未选择许可证前默认他人可以复制或再分发。
