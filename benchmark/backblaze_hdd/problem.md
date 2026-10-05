## Objective
<!-- READONLY: Prepare init.py, evaluator.py, and prompt.md for a Famou evolutionary task -->

## 1. Task Definition

- 核心问题：数据中心硬盘故障预测。在检查日（cutoff）拿到每块硬盘过去最多 14 天的每日 SMART 快照，预测该盘是否会在未来 7 天内（cutoff 之后第 1~7 天）发生故障，并给出告警决策。误告会造成无谓换盘与迁移，漏告会造成数据风险。
- 输入（CLI）：`python <solution.py> --data-dir <abs_dir> --split <val|test> --out <abs_csv>`
  - `--data-dir` 由 `evaluator.py` 传入的绝对路径，目录内只有以下文件：
    - `train_history.csv.gz`：训练盘的每日 SMART 历史
    - `train_labels.csv`：训练盘标签，列 `serial_number, model, cutoff_date, label, weight`
    - `<split>_history.csv.gz`：待预测盘的每日 SMART 历史（每块盘的最后一行就是它的 cutoff 日）
    - `<split>_index.csv`：待预测盘列表，列 `serial_number, model, cutoff_date`
  - `--split`：评估时为 `val`；最终私有测试时为 `test`（文件结构相同）。
- 输出：`--out` 指定的 CSV，列为 `serial_number, score, alarm`
  - 每个待预测 `serial_number` 恰好一行
  - `score`：有限实数，越大表示越可能故障（用于排序类指标）
  - `alarm`：0/1，1 表示发出故障告警（用于 F1、误告率）
- 主要优化目标：最大化 `combined_score`（稳健运维分，Robust Operational Score, ROS）。
- 指标与公式（按机队加权：每个负样本代表约 10 块健康盘，权重在 `weight` 列）：
  - `F1_p10`：对告警结果做 200 次分层 bootstrap，取加权 F1 的 10% 分位数（惩罚靠运气的阈值）
  - `AUPRC`：`score` 的加权平均精度
  - `R@FAR`：在误告率（健康盘被告警的比例）不超过 0.2% 时，`score` 能达到的最大召回率
  - `time_factor = min(1, 600 / 运行秒数)`
  - `combined_score = 100 * (0.5 * F1_p10 + 0.3 * AUPRC + 0.2 * R@FAR) * time_factor`
  - 辅助观察：precision、recall、false_alarm_rate（误告率）、missed_detection_rate（漏告率）

## 2. Data Description

- 数据来源：Backblaze Drive Stats 公开数据集，容量 ≥ 4TB 的机械硬盘，约 44 个型号（Seagate、Toshiba、HGST、WDC）。
- 划分与样本规模：见 `data/meta.json`；默认变体为 训练 2024Q4 / 验证 2025Q1 / 私有测试 2025Q2。
- （正/负样本数与 cutoff 范围以 `meta.json` 的 `splits` 字段为准。）
- （默认变体：2024Q4 → 2025Q1 → 2025Q2。）
- 历史表字段：`date, serial_number, model, capacity_bytes`，以及 SMART 列：
  - raw：1, 3, 4, 5, 7, 9, 10, 12, 187, 188, 190, 191, 192, 193, 194, 196, 197, 198, 199, 240, 241, 242（列名 `smart_<id>_raw`）
  - normalized：1, 3, 5, 7, 9, 187, 194, 197, 198（列名 `smart_<id>_normalized`）
- 数据质量：不同厂商上报的 SMART 属性集合不同（例如 187/188/190 基本只有 Seagate 有），缺失为空值；个别盘在窗口内有缺天；新盘历史不足 14 天。
- 采样设计：每块盘在每个数据划分中只出现一次，历史在自己的 cutoff 日截止；负样本是从全机队健康盘中抽样的，`weight` 为其代表的盘数。

## 3. Constraints and Evaluation Basis

- 硬约束（任一不满足则 validity=0，combined_score=0）：
  - 程序正常退出，且在 900 秒内完成（含训练）
  - 输出覆盖全部待预测盘、无重复、无多余盘；`score` 为有限数；`alarm ∈ {0,1}`
  - 只能按上文列出的文件名读取 `--data-dir` 中的文件；禁止访问评估器目录、禁止路径回溯（`..`、`.parent`）、禁止目录遍历（`glob/listdir/walk/iterdir`）、禁止读取工作目录、禁止子进程和网络
  - 不得使用 cutoff 之后的任何信息（数据本身已截断，禁止通过任何外部途径获取）
- 软目标：更高的 ROS；同分时更短的运行时间、更简单的模型更好。
- 质量衡量：见第 1 节公式。评估器同时返回 precision/recall/误告率/漏告率/bootstrap 标准差供分析。

## 4. Initial Solution Direction

- 初始解 `init.py`：用 cutoff 当天的 10 个 SMART 值（log1p）加厂商 one-hot 训练加权逻辑回归，在训练集上选使加权 F1 最大的阈值。验证集 ROS ≈ 22.8。
- 对照解 `candidates/rule_baseline.py`：经典 SMART 错误计数（5/187/197/198）非零即告警，验证集 ROS ≈ 12.9。
- 可探索方向（不限于）：时间窗口趋势特征、按厂商或型号的特征与模型、树模型与集成、阈值与告警策略、类别不平衡处理、异常检测与生存分析思路。

## 5. Supplementary Information

- 训练、验证与私有测试按时间外推（季度见 `data/meta.json`），模拟真实部署。
- 私有测试集不会上传到任何进化平台，最终由同一个 `evaluator.py`（`--split test`）在本地统一评分，用于公平对比不同进化系统。
