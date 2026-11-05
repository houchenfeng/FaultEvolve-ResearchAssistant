# 阿里天池 SSD（stub）

## 0 状态

**stub**：已实现 `AlibabaSSDAdapter`、schema 校验与 `rename_to_task_schema`；`prepare_data.build_split` 与 evaluator **未实现**（`NotImplementedError`）。`--mock` 进化不可用（MockLLM 仅覆盖 hdd 同构任务）。

## 1 获取

- [天池数据集 95044](https://tianchi.aliyun.com/dataset/95044)（需账号，agent 无法下载）
- `smartlog2018ssd.zip` / `smartlog2019ssd.zip`（各约 4.3 GB）、`ssd_failure_label.csv`
- open_data 变体：`ssd_failure_tag.csv`、`location_info_of_ssd`
- 覆盖 2018-01-01..2019-12-31；smart_logs 6 型号 / open_data 11 型号；原始约 105 列

## 2 目标接口

| 原始 | 任务列 |
|---|---|
| `disk_id` | `serial_number` |
| `ds` (yyyymmdd) | `date` |
| `r_i` / `n_i` | `smart_i_raw` / `smart_i_normalized` |

标签：`serial_number,model,cutoff_date,label,weight`；抽样规则同 Backblaze `prepare_data`（故障在 (c,c+H]）。

## 3 转换（骨架）

```bash
python benchmark/ssd_alibaba/prepare_data.py --raw-dir R --out-dir benchmark/ssd_alibaba/data \
  --train-months 2018-01:2018-12 --val-months 2019-01:2019-06 --test-months 2019-07:2019-12
```

当前运行至校验输入后抛出 `NotImplementedError`，见文档路径。

## 4 配置

- `task.adapter: alibaba_ssd`
- `ALIBABA_SSD_DATA_ROOT` 覆盖 `benchmark/ssd_alibaba/data`

## 5 运行（预期）

```bash
fe doctor --task-dir benchmark/ssd_alibaba   # task_files 失败，含本文档链接
```

实现后：`fe evolve local benchmark/ssd_alibaba --mock -n 3` → 真实进化。

## 6 待办

- 实现 `build_split`、复制 `hdd_mvp/evaluator.py`、`problem.md` / `prompt.md` / `init.py`
- 可选 SSD 知识卡
