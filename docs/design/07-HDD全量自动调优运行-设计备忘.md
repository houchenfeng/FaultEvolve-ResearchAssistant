# HDD 全量自动调优运行：设计备忘

日期：2026-10-03（UTC）。性质：规划备忘，不含任何新实验结果。
上游：[06 自动调优与进化搜索改进设计](06-自动调优与进化搜索改进设计.md)；执行计划见 [`docs/plans/AUTOTUNE_FULL_RUN_PLAN_2026-10-03.md`](../plans/AUTOTUNE_FULL_RUN_PLAN_2026-10-03.md)。

## 1. 本备忘要回答的一个问题

main 在 `43c6cd7`（E0～E2 合入）上，"账本 + 随机 HPO + patch 全开"跑一次完整 HDD 进化，需要哪些前提成立？

## 2. 读代码得到的关键事实（已在 `43c6cd7` 核对，动手前仍应重读）

| 事实 | 位置 | 对运行的影响 |
|---|---|---|
| 随机 HPO 目前是**独立驱动**：`run_hpo()` 只被 `scripts/autotune_hpo.py` 调用，使用自己的 `fe.db`，引擎主循环不调用它 | `optimization/hpo_runner.py`、`cloud/engine*.py` | 仅设置 `autotune.hpo.enabled=true` 跑 `fe evolve local`，**HPO 不会执行** |
| `quota` 的 `hpo` 槽位目前只写 `quota_slot` 事件并返回 `REFINE` | `cloud/engine.py::_choose_operator` | 开 quota 不等于做了 HPO；30% 的槽位实际是普通 REFINE |
| `patch` 在父节点没有 `FE-BLOCK` 标记时不可用，回退为 REFINE（`fallback=draft`）或拒绝 | `engine_autotune.py::parent_has_patch_blocks` | `init.py` 是受保护文件，不能加标记；patch 能否出现取决于生成的节点是否带标记 |
| `--config-file` 是**替换** `<task>/evolve.yaml`，不是叠加 | `cli.py` `evolve_local` | 配置文件必须是完整配置（以 `benchmark/hdd_mvp/evolve.yaml` 为底），不能像 `protocol_dev_A.evolve.yaml` 那样只写几个键，否则其余项回到代码默认值，与历史运行口径不一致 |
| 评估器已输出 precision/recall/f1/`false_alarm_rate`/`missed_detection_rate` | `benchmark/hdd_mvp/evaluator.py::score_predictions` | 报告所需的 P/R/F1、误报率、漏报率可直接取自节点 metric，无需改评估器 |

## 3. 决策

1. **HPO 接线是必须的前置代码步骤（Gate H）**，否则"HPO 开启"这一实验条件不成立。最小接线方案：
   - 在引擎 `hpo` 槽位被选中时，调用 `run_hpo()` 的核心流程（复用现有 dev 划分、缓存、预算），取 `promote_top_k` 个最优 spec 编译为候选程序，经**正常的完整 evaluator 评估**后作为一个普通节点入树；
   - HPO trial 不消耗 LLM token，但必须在账本中以独立阶段（`hpo_trial`）计账，在报告里单列；
   - 默认关闭，只有 `autotune.hpo.enabled && quota.enabled` 同时为真时才生效。
2. 若 Gate H 的代码量超出"小接线"（需要改动 `engine.py` 主循环结构、或改动 DB 既有表），**停止并回报**，由人决定；不得改成"HPO 作为外部阶段"然后仍称之为"HPO 开启的进化运行"。允许的降级写法见计划 §6。
3. 分数只来自本地 evaluator（不变量 G4）。HPO 的 dev 代理分永不写入 `combined_score`。

## 4. 不在本轮范围

E3/E4/E5/K1；泛化数据集；gitcode 提交；完整新 claim 活动（KD 锦标赛、机制层）。
