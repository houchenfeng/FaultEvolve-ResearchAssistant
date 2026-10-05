---
name: fe-data-checkup
description: 对 train 公开数据做发现前聚合体检（不含原始序列号明细）。
---

## 何时使用

- KD1 发现前确认 train 标签与字段覆盖率
- 验证 adapter 已实现 `discovery_frames`

## 命令

```bash
fe data checkup <task_dir> --json --out <dir>
```

## 输出

- `data_facts.json`：`n_samples`、`n_positive`、`label_semantics`、`columns`、`min_detectable_effect`
- `field_coverage.csv`：各列非空率
- `silent_subset_stats.csv`：HDD 可选扩展（无则仅表头）

## 成功检查

- HDD：`n_positive` 与 `data/meta.json` train 正例 1104 一致（实跑 HDD 时）
- 仅输出聚合量，无逐盘明细
- 缺文件时 exit 1，提示先运行 `prepare_data.py`，不自动下载

## 禁止

- 读取 holdout/test/eval_only
- 将 SMART 原始序列上传或写入日志
