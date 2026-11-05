# 自动配置岛屿与算法超参数优化

## 从研究假设生成岛屿

宿主读目标约束、文献卡片、基线错例和单次成本，生成 `island-plan.md` 与实际 `evolve.yaml`。不要让用户手写每个岛；也不要仅复制三岛名称就声称已完成自动配置。

1. 将假设按主要作用分组：性能/表达能力、业务约束与错例、效率与稳健性。没有业务告警概念的任务，用适合任务的 `custom` 方向替换告警岛。
2. 对照剩余预算和评估耗时，选择能获得足够有效尝试的岛数。短预算可单岛；15 次演化尝试的三岛起点可分成 5/5/5，并把基线、修复、HPO 和复验的成本另外计入项目预算。5 次不代表已充分搜索或能可靠判断停滞。
3. 每岛写 `island_id,profile,focus,operator_bias,knowledge_keywords,max_attempts,exploration_ratio`。focus 必须能对应假设；关键词来自其文献/方法，而不是任意分配同一组卡片。
4. 使用当前模型允许的 profile：`performance/miss_alert/efficiency/custom`。当前配置校验不允许重复 profile，custom 必须有 focus；因此不能直接生成多个 custom 岛或任意数量的同类岛。无法表达时合并相关方向或安排关联的后续实验，不绕过校验。
5. 算子偏好必须来自实际启用且适配任务的算子；通用起点 `refine/inject`，告警任务可用 `recall_focus/threshold_calibrate`。当前 enabled 白名单只有这四项，设计文档中的 transplant/simplify 等不能直接加入。经验交流通过引擎已有机制完成。profile 是偏好而非硬限制，保留少量方向外探索。
6. `islands.eval_concurrency` 必须为 1，当前引擎不支持岛屿并发评估。`exchange_interval` 按有效搜索空间和总轮数设置；短 run 可用 2，使正负经验有机会交换。检查实际事件，配置开关不证明交流发生。

`island-plan.md` 至少记录“岛 → 假设/来源 → 方向 → 算子/关键词 → 尝试额度 → 为什么这样分配”。先用 `EvolveConfig.from_yaml` 和 `fe doctor` 检查生效配置，避免未知键被静默忽略。参数定义以仓库 `src/faultevolve/config.py` 为准。

当前引擎可在既有岛配置内选择算子、交流经验及按规则停滞；**运行中重新拆岛、改 profile 或预算分配由宿主规划新的 run**，不是已实现的热更新功能。新 run 留 parent_run_id、变化理由与预算扣减。

## 结构与参数的两层循环

先验证结构性假设（特征、模型族、损失、集成），再固定结构与数据口径优化数值参数。HPO 未改善时仍保留代码进化的最佳可行候选；参数搜索达到边界或所有结构停滞时返回方法设计/文献阶段，而非无止境扩大数值域。

每个 HPO 候选需记录 route_id、来源代码哈希、完整参数、默认值、有限域/类型/条件、数据与评估器身份、种子、资源、父候选及真实评估。不能将不同结构/数据切片的代理分数直接混排。适配器只接受有效、有限的本地指标。

### 路径 A：引擎内 HDD 结构化 HPO

用于 HDD logreg/lightgbm 模板，并确认当前 `hpo_engine.prepare_hpo_dev_context` 所需的公开训练输入与 dev 切分条件可用。它生成模板候选，不是对当前演化父程序任意调参。启用条件：

```yaml
operators:
  bandit: false
autotune:
  ledger: {enabled: true}
  hpo:
    enabled: true
    families: [logreg, lightgbm]
    search: random
    trials_per_structure: 2
    max_fits_total: 24
    promote_top_k: 1
    threads: 1
    trial_timeout_s: 120
  quota:
    enabled: true
    shares: {hpo: 1, patch: 0, draft: 2}
```

这里只是关键片段；完整起点在 `../assets/hdd-integrated.example.yaml`。`max_fits_total` 是拟合数上限，不是 24 个候选承诺；一个候选可包含多个 fit。晋级完整评估、基线、代码生成和修复还有额外成本。支持 `random`，不能把 `tpe` 写成已实现。检查 hpo 事件、实际 trial 与晋级结果；持续 `hpo_skipped` 表示该路径未工作，应诊断或转路径 B。

### 路径 B：已演化路线的层级 HPO

HDD 新运行由 `fe run` 或启用 `workflow.enabled` 的科研/Web 入口自动执行。默认 `workflow.hierarchical.mode: per_structure`：提出一个候选结构后，固定为该结构的单条路线完成参数树搜索，将选中的代码与实测成绩写回节点，再选择下一轮结构。`max_trials`、`max_wall_seconds` 按候选结构计算；`hyperparameters/structures/<node-id>/` 保存各结构的契约、账本和程序，顶层账本汇总展示。恢复先完成未评分结构，再继续生成；完成的试验不重跑。该模式不与路径 A 的配额 HPO 同时启用。

显式 `mode: post_evolution` 可复现“演化结束后选择多条路线再统一调优”，此时预算按后置阶段总量计算。历史运行属于该模式，不是逐结构闭环的实验证据。科研报告检查每个参数候选的联合目标。

历史硬盘“15 轮代码进化 → 24 次调参”由同一桥接器实现；其 HDD evaluator、AST 参数规则和 fallback 模板不能未经适配用于内存/光放大器。

其他任务可复用 `autoresearch-hierarchical-search-cn/scripts/search_engine.py` 的 SearchEngine，并由宿主实现任务桥接器：

1. 从各岛有效候选中选结构不同的高分/联合可行路线；保存来源哈希、默认参数和合法离散域。采用明确配置接口或静态语法解析，不通过执行未知候选发现参数。
2. 包含原值、限制参数的范围与条件，固定随机性。先验证默认参数渲染与源代码语义一致，并用本地 evaluator 检查。
3. 构建 ExperimentSpec：routes、metric、budgets、search、evaluation 身份与命令；禁用 holdout。通用示例 `autoresearch-hierarchical-search-cn/examples/experiment-spec.json` 含合成 holdout 演示，不得不加修改套到真实任务。
4. 评估桥接器读取 candidate.json 的 route_id/parameters，渲染候选、调用冻结的本地 evaluator、持久化全部原始指标，并写搜索器需要的 `score` 与 `integrity_passed`。score 必须对应预先定义的本地主指标，不能由 LLM 或硬编码结果替代。
5. 对需要恢复或联合目标即时停止的项目，用 Python SearchEngine 的 `reserve_next → record_result → ledger` 循环实现协调，参考原 Campaign 的预留与确定性重放。每个 trial 后用 `assess_goals` 检查完整指标，在预算内达标即停止；记录首次达标和全部成本。
6. 简单单次批处理可用下列已有 CLI，但它不会自动合并 `research.targets`，也没有 `--resume`。其标量 target 不能代表联合达标；多约束项目使用上一步协调循环。

```bash
.venv/bin/python autoresearch-hierarchical-search-cn/scripts/run_search.py \
  --spec <项目目录>/hpo/experiment-spec.json \
  --output-dir <项目目录>/hpo/<新批次ID>
```

Spec 的评估命令按该脚本规定的基目录解析，优先使用已核对的绝对路径。脚本输出已有目录不会自动恢复，不能把它当断点续跑入口。参数 ledger 独立于 `fe research` 的 SQLite；最终由宿主合并证据，不伪装成已入库节点。

## HPO 晋级与全项目验收

训练内 dev 结果仅用于调参选择；最终候选按冻结完整评估比较。选择最高主评分且满足全部约束的候选，不能只选最高分。若没有可行候选，报告离目标的缺口。若业务要求可靠性/泛化验证，将复验、消融和迁移实验列入项目交付条件，不能只因一个 val 分数达标就称科研问题已解决。
