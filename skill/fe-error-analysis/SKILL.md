---
name: fe-error-analysis
description: 对候选程序做 dev 集错例画像，并在进化中解读 metric.analysis 与反思差分。
---

## 何时使用

- 召回偏低，需要按型号/容量/静默等聚合 FN/FP 线索定向改进
- `metric.analysis` 为空或 refine 缺少画像依据
- 反思阶段需要父子 FN 组变化对照

## 输入

- 任务目录（含 `evolve.yaml`）
- 候选程序路径（通常为某节点 `programs/*.py` 或 `init.py`）
- 配置段 `analysis.*`（默认关闭）
- 可选环境变量 `HDD_BENCH_DATA_ROOT`（仅指向含公开 `train_*` 文件的根）

## 前置检查

1. `analysis.enabled` 为 `true` 时才在进化中自动画像；单程序诊断可始终调用 CLI。
2. 确认未配置读取受禁数据路径；仅使用公开 `train_labels.csv` 与 `train_history.csv.gz`。
3. `fe doctor` 通过基础依赖检查。

## 步骤

1. 环境检查：`fe doctor --task-dir benchmark/hdd_mvp --json`
2. 单程序画像：`fe analyze benchmark/hdd_mvp --program benchmark/hdd_mvp/init.py --json`
3. 开启 `analysis.enabled: true` 后 mock 进化：`fe evolve local benchmark/hdd_mvp --mock -n 3 --json`
4. 摘要：`python skill/fe-evolve-manager/scripts/report_run.py <run>/fe.db <run>/run_summary.json`
5. 定向测试：`python -m pytest tests/test_error_analysis.py -q`

## 成功检查

- CLI JSON 含 `fn_groups` / `fp_groups`（或 `dev_metrics`）
- `run_summary.json` 中 `analysis_calls > 0` 且 `analysis_nonempty_rate > 0`
- 进化树至少一个有效节点 `metric.analysis` 非空
- `tests/test_error_analysis.py` 中提示注入用例通过

## 失败处理

- 超时：降低 `analysis.top_k` 或提高 `analysis.timeout_s`（≤900）
- 分组全被抑制：增大 `dev_late_fraction` 或保留 `dev_metrics`；勿将 `min_group_count` 降到 10 以下
- 列缺失：仅跳过对应 dimension，其余分组仍可用
- 画像失败：查看 `analysis_failed` 事件；勿为画像失败重跑真实 LLM 实验

## 禁止事项

- 不得读取 `eval_only` / `test` / `holdout` 数据
- 不得输出序列号、路径或原始 SMART 值到画像或日志
- 不得将 dev 指标写入节点 `combined_score`
- 不得为画像开启外网或真实 LLM 调用
