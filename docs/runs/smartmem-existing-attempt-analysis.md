# SmartMem 既有尝试匿名分析（V1-00）

分析对象：用户在本机 `memory-predict/` 工程里的内存故障预测线（参加华为·北航 A 题）。**逐条引用「文件:行号」，不复制源码，不打印真实序列号。** 状态标记：`verified` = 直接读到代码或日志；`user_reported` = 组内文档/口述；`pending` = 待确认。

本轮为**只读取证**，未修改该工程任何文件。

## 1. 它读什么

| 项 | 实际行为 | 位置 | 状态 |
|---|---|---|---|
| 输入 | 官方预计算特征 feather，按 `type_A/type_B` 目录建立 `单元 → (目录, 类型)` 索引 | `src/tune_tree.py:55-60` | verified |
| 工单 | `failure_ticket.csv`，列 `sn_name/alarm_time/sn_type`，加载成 `单元 → (告警秒, 类型)` 字典 | `:61-63` | verified |
| 分组元数据 | `sn_meta.csv`（`sn, manufacturer, PN`），来自静态厂商/型号信息 | `:64-67` | verified |
| 逐单元缓存 | 进程内 LRU（按插入序淘汰），上限按**缓存总行数** 3,000,000 而非文件数 | `:70-94` | verified |
| 特征列 | 从参考单元 `sn_1.feather` 反推列清单（除 `LogTime`），type_A 99 列 / type_B 66 列 | `:114-133` | verified |
| 自建特征 | `features_x / _x2 / _x3` 三套可切换，源单元缺文件时自动回退官方特征并对新列补 NaN | `:23-25`, `:74-75`, `:106-111` | verified |

**它没有读原始 24 列 mcelog**（`raw_tmp/` 只在离线特征构造脚本 `src/build_extra*.py` 里用），主训练路径只吃预计算特征。⇒ 对本仓 V1-05 的含义：*事件级 schema 适配* 在旧尝试里根本没被实现过，是全新工作。

## 2. 它的协议（anchor / lookback / 标签 / 划分 / 聚合 / 阈值 / 输出）

| 环节 | 旧实现 | 位置 |
|---|---|---|
| anchor | **以工单告警时刻为锚**：故障单元取 `LogTime ≤ alarm − lead` 的每一行各成一个样本；正常单元随机抽 `rows_per_sn=200` 行、标签全 0 | `:143-166` |
| lookback | 无独立 lookback；特征本身是官方预计算的 `_15m/_1h/_6h` 回看窗口 | `:27` |
| 标签 | 软标签 `0.5 + 0.5·(t−(alarm−W))/W`，`W = window_d·86400 = 10 天`；`label_decay=False` 时退化为 `t ≥ alarm−10d` 的硬 0/1 | `:151-156` |
| 模型 | `label_decay=True` ⇒ `LGBMRegressor`，否则 `LGBMClassifier(objective="binary")`；`pos_weight=0.25` 作样本权重 | `:159-161`, `:177-183` |
| 划分 | **5 折随机按单元分组**（故障单元轮转均分、正常单元随机分配），可再按 `serial_number_type` 分段各训一模型 | `:244-256`, `:287-294` |
| SN 分数 | 行分数按单元聚合：`agg=top5` ⇒ 取该单元分数最高的 5 行均值 | `:297-305` |
| 阈值 | 在**评估集自己的 OOF 分数**上扫 60 个分位数（q=0.5…0.999）取 F1 最大者 | `:186-215` |
| 指标 | SN 级 P/R/F1 + `prec_at_k`（只报前 K 台）+ `prec_b1`（机群 1% 预算）+ `unscored_n`（无可用行的故障单元数） | `:306-319` |
| 输出 | `make_submission.py` 产出 `serial_number,prediction_timestamp,serial_number_type`，时间戳=告警行自身 `LogTime` | `src/make_submission.py` |
| 冠军配置 | `window_d=10, lead_min=15, rows_per_sn=200, n_estimators=400, lr=0.1, num_leaves=31, min_child_samples=50, drop_window="_6h", label_decay=True, group_by="vendor_pn", agg="top5", pos_weight=0.25` | `:331-334` |

## 3. 防泄漏审查结论

### 3.1 没有的问题（可以放心）

1. **特征不含未来信息**：行被截在 `alarm − lead` 之前，且窗口特征都是回看型。`verified`
2. **首故障之后的事件被剔除**：300 个抽样故障单元里 152 个的日志在告警后仍有行，旧代码用 `LogTime ≤ alarm−lead` 全部丢弃，不存在"训练时读到故障后信号"。`verified`（代码）+`verified`（数据探针）
3. **分组键不携带标签**：`group_by=vendor_pn` 用的是静态 `Manufacturer/PN`，不是故障信息。`verified`
4. **没有使用官方 test 数据**：训练与评估都在同一份 stage1 本地子集上；未发现读取 `test.zip` 的路径。`verified`（路径层面）
5. **没有全数据 target encoding**：无按标签统计的编码列。`verified`

### 3.2 与新需求的实质冲突（必须记录，新实现按需求规则走）

| # | 风险 | 旧证据 | 新实现规则 |
|---|---|---|---|
| R1 | **锚点由标签定义**：正样本只有故障单元的行，负样本靠随机抽样 ⇒ 正负样本构造机制不对称，直接违反「避免以 ticket 为锚点定义样本」 | `:143-166` | §16.2：anchor 只能来自事件或固定时间网格，且按 `event_time ≤ t` 选历史 |
| R2 | **无删失处理**：正常单元的每一行都标 0，不检查 `t+lead+horizon ≤ outcome_observed_until` ⇒ 尾部未随访区间被当成确认负例 | `:166` | §16.3：`censor_at_time()`，随访不足即移除 |
| R3 | **阈值在评估集上选**（上帝视角），绝对分系统性偏乐观 | `:192-215` | 阈值只能来自训练期 CV 或固定的告警预算分位 |
| R4 | **随机按单元 5 折，不是时间外推**：训练与评估覆盖同一日历区间 ⇒ 学到的时段特异性无法从分数中剥离 | `:244-256` | V1-04 时间外推 + embargo=lead+horizon |
| R5 | **判分窗曾错用 10 天**（把标签窗当命中窗），2026-09-30 才修为官方 7 天 | `make_submission.py` 修改记录 | `△tl=15min/△tp=7d` 为固定常量，与 `window_d` 解耦 |
| R6 | **内部三把尺子不校验告警时刻**：只看 SN 级 top5 分数是否过阈，不要求告警行落在 `[alarm−7d, alarm−15min]` ⇒ 内部 F1 是协议宽松上界 | `:186-215` | 严格口径与宽松口径并列报告，禁止只报上界 |
| R7 | **行采样两侧不对称**（故障单元不设上限、正常单元截 200 行）造成协变量偏移；旧代码注释里已自认为已知问题 | `:143-145`, `:163-165` | `max_samples_per_unit` 仅用于训练/快速 fixture，正式 dev/val 用完整网格 |
| R8 | `label_decay` 把分类变成回归，阈值语义随目标函数改变；分位数阈值又对单调变换不变 ⇒ 两档开关曾出现"指标逐位相同"的假象 | `:153-156`, `:181-183` | profile 与知识卡须记录「软标签改变分数尺度」这一坑 |

**风险 R1~R8 均保留记录、不复用其协议。** 旧结果只能作历史参考（§16.1），不得与新协议 F1 直接比较后宣称提升。

### 3.3 数据事实层面尚未澄清的（`pending`）

- 时区口径（见 `smartmem-input-evidence.template.md` §3）：旧代码全程把 epoch 秒当**无时区秒数**做减法，从未声明时区，因此它的数字在两种时区解释下都成立、也都无法被搬运到本仓的 tz-aware 实现。`verified`（代码行为）/`pending`（正确解释）
- 官方评分细则里重复告警与 A/B 汇总：旧线同样没有评分源码，`metric_spec_status` 只能记 `provisional`。`pending`

## 4. 它的结果来源与可信度

| 结论 | 数字 | 来源 | 状态 |
|---|---|---|---|
| 四把尺子 | 0.6022 / 0.4647 / 0.3179 / **0.1925** | 本地脚本 `tune_tree.py`、`eval20k.py`、`field_ruler.py`、`make_submission.py` + `trees/*.jsonl` 日志 | verified（含 0926 夜现场档逐位回归复算、两次训练期 CV 阈值复现） |
| 官方 baseline ≈ 0.207、往届冠军 ≈ 0.30 | 榜单 | Codabench 3586 页面 | user_reported（且**榜单已关闭，无法提交校准**，浏览器实读 `CURRENT ACTIVE PHASE: None`）|
| 「7 棵调优树（规则×6 + LLM×1）确认 0.60 平台」 | 定性 | `trees/run_*.jsonl` 11 份 | verified |
| 「自建长窗/局部特征增益不可复现」 | 6k +0.0078 → 20k −0.020 翻转 | `ab_features.py` 等日志 | verified |
| 已证伪维度清单 | `voting / split_type / hard_neg / agg=max / feat_set=x* / rows400 / n_estimators` 等 | 同上 | verified |

对外唯一可引用的是第四把尺子 **0.1925**（全程不看答案，按 1% 告警预算取分位阈值）。旧线自己已把这条口径写进交付文档。`verified`

## 5. 可以带进一/二阶段的东西

1. `sn_meta.csv` 静态身份映射与 `group_by=vendor_pn / serial_number_type` 分段这两个**经 A/B 正增益**的建模事实（−0.072 至 +0.041 量级，口径为 6k 内部尺子）→ 候选知识卡，状态按内部尺子标注。
2. 冠军配置表（§2 末行）作为**参考基线**，不是新实现的默认。
3. 知识库文件 `knowledge/已验证结论.md`（含证伪清单）→ V1-08 知识卡的种子，但**必须重新按新协议复验**才能升 `verified`。
4. 「四把尺子 + 三档递进终审（6k 粗筛 → 20k 复判 → 现场档/官方规则终审）」的方法论 → 直接进需求与本仓评测设计。
5. 教训：**指标异常先查评估代码再怀疑模型**（一次阈值下标比较错误让 5 轮实验数字全部作废）。

## 6. 明确不复用的

- 以 ticket 为锚的采样、无删失的负标签、评估集上扫阈值、随机单元 5 折 —— 全部由 `event_sampling.py` / `temporal_split.py` 的新实现替代。
- 旧线的任何绝对 F1 不进共享报告的"提升"叙事。
