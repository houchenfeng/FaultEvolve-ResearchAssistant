# SmartMem 内存故障（stub）

## 0 状态

**stub**：`SmartMemAdapter`、mcelog/ticket 校验与 `prepare_data` 骨架；**无** hdd 式 evaluator（事件式 F1，不复用 ROS 评估器）。

## 1 获取

- Codabench 3586 Data 页（SharePoint / rec.ustc.edu.cn，可能需注册）
- CSV ≈130 GB 或 Feather ≈40 GB；Kaggle `smartmem/smartmem-features`；[SmartHW starter kit](https://github.com/hwcloud-RAS/SmartHW)
- 许可 **CC BY-NC-SA**（禁止再分发、禁止入库）；Phase 2 已结束，仅本地评估

## 2 输入格式

- **mcelog**（每 DIMM 一文件，23 列，含拼写 `manufacturter`）
- **failure_ticket.csv**：`serial_number,failure_time,serial_number_type`（A/B）
- 提交：`sn_name,prediction_timestamp,serial_number_type`

## 3 聚合规则（待实现）

`aggregate_events_to_samples`：样本时间 `t` 为事件 `log_time` 按 15 分钟向下取整；特征窗 `(t-lookback, t]`；标签 1 当 `failure_time ∈ [t+15min, t+15min+7d]`；t 后 15 分钟内故障的样本丢弃。

## 4 转换（骨架）

```bash
python benchmark/smartmem/prepare_data.py --raw-dir R --out-dir benchmark/smartmem/data
```

`main()` 校验输入后 `NotImplementedError`。

## 5 配置与运行

- `task.adapter: smartmem`
- `SMARTMEM_DATA_ROOT`
- `fe doctor --task-dir benchmark/smartmem`（缺 evaluator，退出码 1）

## 6 待办

- 实现 `aggregate_events_to_samples` 与事件式 evaluator（F1）
