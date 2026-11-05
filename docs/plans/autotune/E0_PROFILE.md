# E0 资源画像

## analysis_calls=0

默认配置 `analysis.enabled=false`（见 `EvolveConfig`），因此历史 run 中 `analysis_calls=0` 为**配置使然**，非故障。

若启用分析仍为 0，再检查 `_should_analyze_node` 触发条件（`on_new_best`、`top_k`）。

## 墙钟 / CPU / RSS

账本启用前历史 run 无分阶段墙钟与 RSS 细账；`autotune.ledger.enabled=true` 后由 `cost_ledger` 表记录。
