---
name: fe-data-checkup
description: 对 FaultEvolve 训练数据做聚合体检，输出质量问题分级、处理建议与可复现报告；用于数据理解、清洗方案设计或知识发现前检查。
---

## 何时使用

- 理解训练数据、设计清洗方案，或在 KD1 发现前确认标签与字段覆盖率
- 验证 adapter 已实现 `discovery_frames`

## 命令

```bash
fe data checkup <task_dir> --json --out <dir>
fe data checkup <task_dir> --strict --json --out <dir>
```

## 输出

- `data_facts.json`：样本数、正负例数、历史行数与 `quality_status`；`min_detectable_effect` 为 null，体检不做功效估计
- `data_quality.json`：阻断/需决策/一般问题、计数与依据、处理建议、训练视图指纹、检查范围
- `data_report.md`：数据概况、质量问题、处理建议和限制，面向用户阅读
- `field_coverage.csv`：各列非空率、缺失数、非有限值数、不同值数量，UTF-8 BOM 编码
- `silent_subset_stats.csv`：HDD 可选扩展（无则仅表头）

## 成功检查

- `ok=true` 表示报告生成成功；须另看 `quality_status`：`blocked` 有阻断问题，`review` 需复核，`ready` 仅表示当前检查未发现问题
- `--strict` 遇阻断问题仍先写报告，再退出 2；普通模式保留退出 0，供交互分析使用
- HDD：当前共享基准的 train 正例应为 1104；其他任务依据各自的数据契约核对，不硬编码该数量
- 仅输出聚合量，无逐盘明细
- 缺文件时 exit 1，提示先运行 `prepare_data.py`，不自动下载

## 分析与处理

先对照任务说明解释字段和业务目标，再按严重程度整理建议。区分厂商不支持的 SMART 字段与采集缺失；不能只因缺失比例高就删除列。

体检仅检查 `discovery_frames` 返回的训练视图。适配器可能已经去重、截断历史或转换类型；不能把报告当成原始文件审计、跨划分泄漏验证或 cutoff 验证。

用户要求清洗时，在独立输出目录实现处理脚本，记录输入版本、规则及影响行数，保留原始文件。填补、归一化和特征选择只在训练数据拟合。明确影响标签含义或评估口径的决策后再处理；已有授权范围内的常规变换可直接完成并留痕。

参考 [伐谋数据分析工作流](https://github.com/baidubce/skills/blob/develop/skills/famou-data-analysis/SKILL.md) 的数据理解、质量分级和可解释处理思路；实现与输出契约以本项目为准。

## 禁止

- 读取 holdout/test/eval_only
- 将 SMART 原始序列上传或写入日志
