# Backblaze HDD 变体

## 1 概览

默认变体：训练 **2024Q4** → 验证 **2025Q1** → 私有测试 **2025Q2**。输出布局与 `hdd_mvp` 同构；`evaluator.py` / `init.py` 与 MVP 字节相同，val ROS 可与 MVP 对照（数据不同）。

## 2 获取数据

- 基址：`https://f001.backblazeb2.com/file/Backblaze-Hard-Drive-Data`
- 每季约 **1 GB** 压缩、解压数 GB；无需登录。
- 命令：

```bash
python benchmark/backblaze_hdd/download_data.py \
  --quarters 2024Q4 2025Q1 2025Q2 \
  --raw-dir /data/backblaze/raw
```

服务器能否联网**未核实**；不通则本机下载后拷贝 `raw-dir`。

## 3 转换

```bash
python benchmark/backblaze_hdd/prepare_data.py \
  --raw-dir /data/backblaze/raw \
  --out-dir benchmark/backblaze_hdd/data
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--train-quarter` | 2024Q4 | 训练季 |
| `--val-quarter` | 2025Q1 | 验证季 |
| `--test-quarter` | 2025Q2 | holdout 测试季 |
| `--horizon` | 7 | 预测窗口（天） |
| `--history-days` | 14 | 历史窗口 |
| `--min-capacity-tb` | 4 | 最小容量 |
| `--n-negatives` | 30000 | 负样本上限 |
| `--disjoint-disks` | 关 | 盘号跨 split 互斥 |

变体示例：`--horizon 30`、`--vendors ST`、`--min-capacity-tb 8`。

输出树：`data/public/`、`data/eval_only/val_labels.csv`、`data/holdout*`、`data/meta.json`（不入库）。

## 4 配置

- `benchmark/backblaze_hdd/evolve.yaml`：`task.adapter: backblaze`
- `export HDD_BENCH_DATA_ROOT=/path/to/data`（指向含 `public/` 的 `data` 根）
- 可选：`FE_RUNS_DIR`、`.env` 中 `DASHSCOPE_API_KEY`

**注意**：`HDD_BENCH_DATA_ROOT` 与 `hdd_mvp` 共用；切换任务前请 `export` 或 `unset`。

## 5 运行

```bash
fe doctor --task-dir benchmark/backblaze_hdd
HDD_BENCH_DATA_ROOT=... python benchmark/backblaze_hdd/evaluator.py init.py
fe evolve local benchmark/backblaze_hdd --mock -n 3
fe evolve local benchmark/backblaze_hdd --iterations 50 --env-file .env
```

私有测试：仅人工本地 `evaluator.py` + `--split test`（不读 holdout 参与进化）。

## 6 报告字段

val ROS、init ROS、`metric` 中 `f1_p10`、`auprc`、`recall_at_far` 等（同 MVP §4.3）。

## 7 常见故障

- 缺 SMART 列：旧季度 CSV 列不全，`prepare_data` 填 NaN。
- 环境变量指向错误任务的数据目录。
- 内存：降低 `--n-negatives`。
