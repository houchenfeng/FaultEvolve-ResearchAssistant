# hdd_mvp：硬盘故障预测基准（FaultEvolve MVP 与伐谋对照共用）

在 cutoff 日拿到每块盘最多 14 天的每日 SMART 快照，预测未来 7 天内是否故障，输出 `score` 和 `alarm`。

| 文件 | 作用 |
|---|---|
| `problem.md` | 任务契约（伐谋模板结构） |
| `evaluator.py` | 评估器，伐谋标准接口；`combined_score` 为稳健运维分 ROS |
| `init.py` | 初始解（逻辑回归），val ROS 22.81 |
| `candidates/rule_baseline.py` | 对照解（SMART 规则），val ROS 12.94 |
| `prompt.md` | 进化系统提示 |
| `config.yaml` | 伐谋实验配置（企业版混合云，50 轮） |
| `FAMOU_任务说明.md` | 伐谋普通版网页端提交：上传清单 + 直接模式指令 |
| `prepare_data.py` | 从 Backblaze 原始 CSV 确定性重建数据 |
| `data/public`, `data/eval_only` | 已提交；进化用 |
| `data/holdout*` | 私有测试集，不入库、不上传 |

## 使用

```bash
pip install -r ../../requirements.txt
python evaluator.py init.py                  # 验证集评分
python evaluator.py init.py --split test     # 私有测试集评分（需要本地 holdout 数据）
```

重建数据（需要约 3.3GB 下载、约 32GB 解压空间）：

```bash
for q in Q3_2024 Q4_2024 Q1_2025; do
  curl -LO https://f001.backblazeb2.com/file/Backblaze-Hard-Drive-Data/data_$q.zip && unzip -q data_$q.zip -x "__MACOSX/*"
done
python prepare_data.py --raw-dir <解压目录>
```

伐谋提交与对照记录见 `docs/design/03-伐谋对照实验方案.md`。
