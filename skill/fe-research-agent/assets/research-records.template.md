# 项目研究记录模板

复制本模板到项目目录后填写实际内容。以下空集合和 null 是待取得的信息，不能当作已完成的证据。宿主维护这些文件；引擎不会自动生成此项目账本。

## state.json

```json
{"schema":"faultevolve.project-state/v1","project_id":null,"status":"preparing","phase":"problem","execution_mode":null,"started_at":null,"updated_at":null,"active_run_id":null,"active_run_dir":null,"active_pid":null,"completed_artifacts":[],"next_action":null,"blocked_reason":null}
```

## decisions.jsonl 单条格式

```json
{"decision_id":null,"timestamp":null,"phase":null,"evidence_refs":[],"observation":null,"hypothesis":null,"action":null,"reason":null,"expected_test":null,"parent_run_id":null,"next_run_id":null,"remaining_budget":{},"actor":"ai"}
```

## steps.jsonl 单条格式

```json
{"planned_step_id":null,"attempt_id":null,"phase":null,"applicable":true,"actor":null,"status":"planned","started_at":null,"ended_at":null,"interventions":[],"artifact_refs":[],"plan_change_reason":null}
```

actor 使用 ai/human/mixed，status 使用 planned/running/completed/failed/blocked/skipped。不适用步骤说明原因；失败和重试不能从分母中悄悄删除。

phase 使用 problem/data/literature/design/islands/evolution/hpo/validation/visualization/delivery；根据任务选择适用阶段。execution_mode 记录 research/campaign/host_hpo，状态文件不会被 CLI 自动解释或派发。

## 数据处理与检查记录

```json
{"step_id":null,"status":"planned","input_refs":[],"output_refs":[],"input_sha256":null,"output_sha256":null,"input_rows":null,"output_rows":null,"affected_rows":null,"rule":null,"reason":null,"fit_split":null,"code_version":null}
```

```json
{"check_id":null,"scope":null,"status":"not_checked","evidence_refs":[],"reason":null}
```

未执行处理保留只读状态；未检查不等于通过。训练视图指纹和原始文件指纹分开命名，不为生成指纹读取受保护数据。

## runs.jsonl 与 costs.jsonl 单条格式

```json
{"run_id":null,"parent_run_id":null,"phase":null,"config_sha256":null,"evaluator_sha256":null,"data_identity":null,"knowledge_sha256":null,"evidence_path":null,"status":null}
```

```json
{"cost_id":null,"timestamp":null,"run_id":null,"phase":null,"source_ref":null,"tokens":null,"token_scope":null,"wall_seconds":null,"full_evaluations":null,"fits":null,"usage_source":"unknown"}
```

按 cost_id/source_ref 去重；不能把 run 汇总 Token 和其中每次调用再重复累加。模型输出与推理细分遵守服务端 usage 口径。

## design.md / island-plan.md

描述输入 → 特征/表征 → 模型或求解器 → 校准/决策 → 评价。列出基线、可替换模块、参数边界、资源、数据划分和对照。

| 假设ID | 文献/原创来源 | 可证伪预测 | 岛屿/路线 | 算子/关键词 | 预算 | 判定证据 |
|---|---|---|---|---|---|---|

## 项目报告

1. 原始问题、目标及当前结论，明确尚未解决的约束。
2. 数据质量、处理及泄漏检查范围；文献综述和来源，方法选择及被实验推翻的假设。
3. 原始基线、各阶段最佳候选、联合可行性与复验证据。
4. 岛屿结构、调参空间、关键决策和完整运行血统。
5. 性能/复杂性/自动化/泛化四类证据及未知项。
6. 全项目成本和预算、首次达标时间、失败与人工介入。
7. 带真实数据来源的效果、搜索及参数图表，经验及适用边界，下一项关键验证。
8. 证据索引、工件路径与哈希，归档清单和可恢复状态。

## evidence-index.json

从 [证据索引模板](evidence-index.template.json) 创建。数组只追加实际存在的记录，每条主张至少关联一个真实产物；未验证主张进入 missing_evidence。

```json
{"claim_id":null,"statement":null,"status":"unverified","artifact_ids":[],"metric_locators":[],"limitations":[]}
```

```json
{"figure_id":null,"path":null,"sha256":null,"question":null,"artifact_ids":[],"field_locators":[],"run_ids":[],"candidate_ids":[],"evaluation_split":null,"generator_path":null,"missing_value_policy":"unknown"}
```

```json
{"artifact_id":null,"path":null,"sha256":null,"kind":null,"run_id":null,"node_or_trial_id":null,"scope":null,"availability":"not_checked"}
```

relative path 以证据索引所在目录为基准；外部产物用明确位置引用并说明当前是否可访问。不能把另一份运行的图表当作本次证据。

## 可复用经验格式

```json
{"lesson_id":null,"condition":null,"action":null,"hypothesis_ids":[],"source_ids":[],"evidence_refs":[],"observed_effect":null,"counterexamples":[],"scope":null,"evidence_level":null,"next_validation":null,"version":1}
```
