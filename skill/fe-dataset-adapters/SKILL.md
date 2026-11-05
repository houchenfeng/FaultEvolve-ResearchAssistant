---
name: fe-dataset-adapters
description: 准备与校验多数据集任务目录（Backblaze、SSD/内存 stub 和新器件 manifest），配置 task.adapter 并离线冒烟。
---

## 何时使用

- 切换或新增 `evolve.yaml` 的 `task.adapter`
- 从原始数据生成与 `hdd_mvp` 同构的 benchmark 目录
- `fe doctor --task-dir` 报缺数据或 stub 任务缺 evaluator

## 输入

- 数据集别名：`hdd` | `backblaze` | `alibaba_ssd` | `smartmem`
- 原始数据目录、horizon/history、季度或月份划分
- 新器件 manifest：telemetry 文件、设备列、时间列，可选 events/metadata 与任务口径
- 环境变量：`HDD_BENCH_DATA_ROOT`（Backblaze/hdd 同构）、`ALIBABA_SSD_DATA_ROOT`、`SMARTMEM_DATA_ROOT`
- `.env`：`DASHSCOPE_API_KEY` 等（真实进化）

## 新器件与多格式输入

通用适配器位于 `src/faultevolve/data/universal_adapter.py`。它把 CSV、TSV、Parquet、Feather、Excel、半结构化 JSON、JSONL 和文本日志统一转换成现有 Skill 的稳定契约：

```text
telemetry: sn, LogTime, numeric features...
events:    sn_name, alarm_time, optional sn_type
```

算法、搜索、评估和报告不按文件格式或器件名称分支；差异只写入 manifest。最小 manifest：

```json
{
  "telemetry": [{"path": "telemetry.parquet", "device_col": "device_id", "time_col": "timestamp"}],
  "events": {"path": "events.json", "records_path": "events", "device_col": "device_id", "time_col": "failure_time"},
  "task": {"window_d": 7, "lead_min": 30, "group_by": "vendor_model"}
}
```

运行归一化（原始目录只读，输出是可复用缓存）：

```bash
python scripts/materialize_dataset.py <MANIFEST.json> <OUT_DIR>
```

输出包含按设备划分的 `type_A/*.feather`、`failure_ticket.csv`、`sn_map.csv` 和 `dataset_manifest.json`，随后按目标任务的 adapter 接入 `fe doctor`、数据体检、采样和 `fe evolve`。没有 events 时仍可把同一 telemetry manifest 用于无标签异常检测；有 events 时再按 manifest 的 lead/horizon 和分组口径做监督评估。未知列、缺少数值特征或 JSON 记录路径不明确时，适配器会直接报错，不猜默认值。

格式回归：

```bash
python -m pytest tests/test_universal_adapter.py -q
```

## 命令

```bash
# Backblaze：下载（需联网，约 1 GB/季）
python benchmark/backblaze_hdd/download_data.py --quarters 2024Q4 2025Q1 2025Q2 --raw-dir /data/backblaze/raw

# 转换
python benchmark/backblaze_hdd/prepare_data.py --raw-dir /data/backblaze/raw --out-dir /data/backblaze/out/data

# 评估 init（val）
export HDD_BENCH_DATA_ROOT=/data/backblaze/out/data
cd benchmark/backblaze_hdd && python evaluator.py init.py

fe doctor --task-dir benchmark/backblaze_hdd
fe evolve local benchmark/backblaze_hdd --mock -n 3

# 真实进化（需密钥）
fe evolve local benchmark/backblaze_hdd --iterations 50 --env-file .env
```

Stub（预期失败，仅校验接口）：

```bash
fe doctor --task-dir benchmark/ssd_alibaba    # 缺 evaluator，退出码 1
fe evolve local benchmark/ssd_alibaba --mock  # stderr 含 docs/datasets/alibaba_ssd.md
```

## 成功检查

- `fe doctor --task-dir … --json` 中 `all_ok: true`（stub 目录预期为 false）
- Backblaze：`init` val ROS > 0；`data/meta.json` 各 split 正样本数 > 0
- mock 进化后存在 `run_summary.json`
- `git diff --stat benchmark/hdd_mvp` 为空
- `tests/test_engine_task_agnostic.py` 通过

## 失败处理

| 症状 | 处理 |
|---|---|
| `data not prepared` / stub 错误 | 按 `docs/datasets/*.md` 完成 prepare；stub 勿跑真实进化 |
| SMART 列缺失 | Backblaze `prepare_data` 自动填 NaN；检查 raw CSV |
| 下载失败 / 离线 | 本机下载后拷贝 `raw-dir` |
| `HDD_BENCH_DATA_ROOT` 串用 | 每个任务前 `export` 或 `unset`；doctor 查看 `task_data_root_env` |
| 内存不足 | 减小 `--n-negatives` |

## 禁止操作

- 不读 `holdout*` / `eval_only` 标签用于训练或进化
- 不修改 `benchmark/hdd_mvp` 受保护文件与已入库 evaluator
- 不提交 `data/`、`raw/`、`.fe/`
- 不写密钥入仓；不把 LLM/Jev 输出当分数
- 不登录天池/Codabench 自动下载
- 不在 stub 任务上跑真实进化或依赖 `--mock` 生成 SSD/内存代码
