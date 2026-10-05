---
name: fe-dataset-adapters
description: 准备与校验多数据集任务目录（Backblaze、SSD/内存 stub），配置 task.adapter 并离线冒烟。
---

## 何时使用

- 切换或新增 `evolve.yaml` 的 `task.adapter`
- 从原始数据生成与 `hdd_mvp` 同构的 benchmark 目录
- `fe doctor --task-dir` 报缺数据或 stub 任务缺 evaluator

## 输入

- 数据集别名：`hdd` | `backblaze` | `alibaba_ssd` | `smartmem`
- 原始数据目录、horizon/history、季度或月份划分
- 环境变量：`HDD_BENCH_DATA_ROOT`（Backblaze/hdd 同构）、`ALIBABA_SSD_DATA_ROOT`、`SMARTMEM_DATA_ROOT`
- `.env`：`DASHSCOPE_API_KEY` 等（真实进化）

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
