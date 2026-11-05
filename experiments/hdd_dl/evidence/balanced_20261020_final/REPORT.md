# HDD 深度学习实验进度

已完成 120 个候选。验证集参与搜索；尚未进行独立复验。

按 ROS 选择的当前最优：候选 74，结构 tcn。

| 指标 | 当前 DL | ML 对照 0 | ML 对照 1 | ML 对照 2 |
|---|---|---|---|---|
| combined_score | 42.139307352620094 | 22.807355886970594 | 40.72413860816145 | 38.139345971596875 |
| precision | 0.41773 | 0.19826 | 0.38198 | 0.33178 |
| recall | 0.46825 | 0.33598 | 0.47751 | 0.4828 |
| f1 | 0.44155 | 0.24937 | 0.42444 | 0.39329 |
| f1_p10 | 0.4125 | 0.22935 | 0.39583 | 0.36672 |
| auprc | 0.3944 | 0.19546 | 0.37148 | 0.36117 |
| recall_at_far | 0.48413 | 0.27381 | 0.48942 | 0.44841 |
| quality | 0.42139 | 0.22807 | 0.40724 | 0.38139 |
| false_alarm_rate | 0.001633 | 0.0034 | 0.001933 | 0.002433 |
| missed_detection_rate | 0.53175 | 0.66402 | 0.52249 | 0.5172 |
| f1_boot_std | 0.02164 | 0.01652 | 0.02141 | 0.02047 |
| run_time_s | 10.8 | 1.88 | 6.07 | 8.24 |
| alarms_per_1k_disks | 2.798 | 4.23 | 3.121 | 3.633 |

基线来源：
- ML 对照 0：`/home/hcf/faultevolve-dl/code-v3/benchmark/hdd_mvp/init.py`
- ML 对照 1：`/home/hcf/faultevolve/three_island_20261008-200410/formal/artifacts/hdd_mvp_formal2b_20261009/programs/4016914b.py`
- ML 对照 2：`/home/hcf/nas_hcf_data/faultevolve/runs/final_B/f9752fcd/programs/d8f34173.py`

逐项差距：
- 对照 0 尚未严格超过：f1_boot_std, run_time_s。
- 对照 1 尚未严格超过：recall, recall_at_far, missed_detection_rate, f1_boot_std, run_time_s。
- 对照 2 尚未严格超过：recall, missed_detection_rate, f1_boot_std, run_time_s。

按最弱预测指标差距选择的候选：1，ROS 40.9321，最弱相对差距 -0.0243（正数才表示所有预测指标严格超过）。
- 该候选对照 0 尚未超过：f1_boot_std, run_time_s。
- 该候选对照 1 尚未超过：recall, recall_at_far, missed_detection_rate, run_time_s。
- 该候选对照 2 尚未超过：recall, missed_detection_rate, f1_boot_std, run_time_s。
