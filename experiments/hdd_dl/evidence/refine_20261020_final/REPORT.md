# HDD 深度学习实验进度

已完成 120 个候选。验证集参与搜索；尚未进行独立复验。

按 ROS 选择的当前最优：候选 83，结构 tcn。

| 指标 | 当前 DL | ML 对照 0 | ML 对照 1 | ML 对照 2 |
|---|---|---|---|---|
| combined_score | 41.52921669434177 | 22.807355886970594 | 40.72413860816145 | 38.139345971596875 |
| precision | 0.37336 | 0.19826 | 0.38198 | 0.33178 |
| recall | 0.50794 | 0.33598 | 0.47751 | 0.4828 |
| f1 | 0.43037 | 0.24937 | 0.42444 | 0.39329 |
| f1_p10 | 0.40529 | 0.22935 | 0.39583 | 0.36672 |
| auprc | 0.38519 | 0.19546 | 0.37148 | 0.36117 |
| recall_at_far | 0.48545 | 0.27381 | 0.48942 | 0.44841 |
| quality | 0.41529 | 0.22807 | 0.40724 | 0.38139 |
| false_alarm_rate | 0.002133 | 0.0034 | 0.001933 | 0.002433 |
| missed_detection_rate | 0.49206 | 0.66402 | 0.52249 | 0.5172 |
| f1_boot_std | 0.02071 | 0.01652 | 0.02141 | 0.02047 |
| run_time_s | 5.41 | 1.87 | 6.02 | 7.28 |
| alarms_per_1k_disks | 3.396 | 4.23 | 3.121 | 3.633 |

基线来源：
- ML 对照 0：`/home/hcf/faultevolve-dl/code/benchmark/hdd_mvp/init.py`
- ML 对照 1：`/home/hcf/faultevolve/three_island_20261008-200410/formal/artifacts/hdd_mvp_formal2b_20261009/programs/4016914b.py`
- ML 对照 2：`/home/hcf/nas_hcf_data/faultevolve/runs/final_B/f9752fcd/programs/d8f34173.py`

逐项差距：
- 对照 0 尚未严格超过：f1_boot_std, run_time_s。
- 对照 1 尚未严格超过：precision, recall_at_far, false_alarm_rate。
- 对照 2 尚未严格超过：f1_boot_std。
