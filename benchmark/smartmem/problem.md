## Objective
<!-- READONLY: Prepare init.py, evaluator.py, and prompt.md for a Famou evolutionary task -->

## 1. Task Definition

- 核心问题：内存条（DIMM）故障预测。每台机器上的每根内存条以序列号（SN）标识，运行中持续上报
  mcelog 事件（绝大多数是可纠正错误 CE）。预测任务：在给定历史事件的前提下，判断这根 SN 是否会在
  未来 7 天内出现不可纠正错误并被工单更换，并给出告警决策。漏告造成宕机与数据风险，误告造成无谓更换。
- 数据形态：**事件流**，不是日快照。一行 = 一个单元在一个 15 分钟网格时刻上的样本，特征列是该回看窗
  内聚合出的 CE 计数、空间分布（CPU/通道/DIMM/rank/bank/row/column 的去重数与集中度）、趋势量
  （前后半窗计数、增长率、距上一条事件的分钟数）与硬件画像列。
- 输入（CLI）：`python <solution.py> --data-dir <abs_dir> --split <dev|val> --out <abs_csv>`
  - `--data-dir`：evaluator 为本次评分从 run 目录切出的**公开快照**目录，只含以下四个文件：
    - `train_samples.csv.gz`：训练切片（`split_key=train`）的样本行与特征列，**不含 label**
    - `train_labels.csv`：`sample_id,label`，只含通过删失审计的训练样本
    - `<split>_index.csv`：待预测行清单，`sample_id,unit_id,prediction_time,history_end,serial_number_type`
    - `<split>_samples.csv.gz`：待预测行的特征列，**无 label、无 split_key**
  - 候选只能按这四个文件名读取；被评切片的标签不在候选可见目录里，是构造上的，不是靠约定。
- 输出：`--out` 指定的 CSV，固定三列 `sample_id,score,alarm`
  - `index` 里每个 `sample_id` 恰好一行：无缺失、无重复、无多余
  - `score`：有限实数，越大表示越可能出 UE（仅作排序与诊断）
  - `alarm`：整数 0/1，**1 才是评分输入**
  - 告警时刻由 evaluator 从 `index` join 得到（取该行的 `prediction_time`）；候选不得自报时刻或硬件类型
- 主要优化目标：最大化 `combined_score = 100 * event_f1`（百分制，事件级 F1，不是逐样本 F1）。
- 指标与公式（判分口径的页面原文见第 5 节出处）：
  - 命中窗：一条告警对某 SN 的故障时刻 `a` 记为命中，当且仅当告警时刻 `t ∈ [a − 7d, a − 15min]`；
    △tl=15min 与 △tp=7d 是官方固定值，观测窗与打标方式由参赛者自定。
  - 计数：一个 SN 只计一次（SN 级去重，多报几条不额外扣分），且**必须至少有一条预测落进窗内**才算 TP；
    `precision = 命中 SN 数 / 被预测 SN 数`，`recall = 命中 SN 数 / 该切片工单 SN 总数`。
  - 汇总：`F = (1 + β²) · P · R / (β² · P + R)`，β 是超参（默认 β=1 即 F1）；A/B 两类队列在页面原文里
    是在整个 SN 集合上算一次 P/R（本仓 `--queue-aggregation sum`），按队列平均降为敏感性检验。
  - `combined_score = 100 * F`，时间成本单独报告，不加 HDD 那种时间惩罚项。

## 2. Data Description

- 数据来源：SmartMem / WWW 2025 竞赛（codabench 3586）的内存器件数据，原始形态是每根 DIMM 一个
  mcelog 事件文件（23 列，官方列名里 `manufacturter` 就是拼错的）加一份更换工单
  `serial_number, failure_time, serial_number_type`（类型 A/B）。许可 **CC BY-NC-SA**：禁止再分发、
  禁止入库，因此本仓不含官方 starter kit 的任何代码副本。榜单已于 2025-04-11 发榜关闭，
  现在**没有任何提交可以校准绝对分数**。
- 本仓产物：`benchmark/smartmem/prepare_data.py` 把事件流聚合成 run 目录
  （`manifest.json` + `partitions/samples/part-*` + `partitions/units/serial_type` +
  `partitions/audit/summary`），样本表实测 44 列 = 9 列键与窗口边界 + 24 列特征
  + 2 列窗覆盖度 + 9 列硬件画像。
  划分按 `prediction_time` 落在 `split-v2.yaml` 的边界里，train/dev/val 之间留 7 天 + 15 分钟的
  embargo，窗尾之后仍无告警的单元进 `outside`，都不参与跨切片混训。
- 已跑通的真实切片（本文所有实测数字的样本）：200 根 SN、17 531 行样本、4 613 正样本行；
  `train` 10 258 行 / 2 329 正 / 130 单元，`dev` 3 094 / 834 / 89，`val` 2 246 / 608 / 70，
  `embargo` 1 463 行被剔除，`outside` 470 行；`config_hash 2472df3d…`。
- 数据质量：这个切片的 140 条告警全部落在队列 A（队列 B 的告警数为 0），所以双队列倾斜的差异在真实
  切片上暂时演不出来；本地镜像的工单文件列名是 `sn_name / alarm_time / sn_type`（时刻是 epoch 秒），
  与官方文档写的三列不同，读入时映射；有 5 根 SN 在整个观测期没有任何可评样本（事件过稀）。
- 采样设计：一行一个（单元, 15 分钟时刻），同一单元在同一切片内出现多行；正样本行密度远高于现场基率，
  本切片约 26%，而现场基率是千分位。**任何跨协议、跨样本密度的分数比较都不成立。**

## 3. Constraints and Evaluation Basis

- 硬约束（任一不满足则 `validity=0`、`combined_score=0`，并返回脱敏 `error_info`）：
  - 程序正常退出，且在 900 秒内完成（含训练）
  - 输出恰好覆盖 `index` 的每个 `sample_id` 一次；`score` 为有限数；`alarm` 为整数 0/1
  - 只按第 1 节列出的四个文件名读 `--data-dir`；禁止路径回溯（`..`、`.parent`）、目录遍历
    （`glob/listdir/walk/iterdir`）、读工作目录、子进程、网络、环境变量里的密钥
  - 不得使用 `prediction_time`（更不得用 `history_end`）之后的信息：数据已按行截断，且 evaluator 会
    拒绝任何早于该行最后一条事件的预测
  - 不得硬编码序列号或单元名；真实序列号不得出现在 stdout、日志与任何提交物里
- 判分口径的状态：本地 evaluator 给的是**页面原文口径**的判分，`metric_spec_status` 仍是
  `provisional` —— 官方**评分源码**从未到手，拿到之后才能把它升成 `verified`。所以
  **本地分数只能和本地分数比**，不能声称是 Codabench 复现分。
- 敏感性检验（都是命令行开关，不改默认）：`--duplicate-alarm-rule` 三值 `sn-in-window`（默认，
  去重 + 必须落窗）/ `each-alarm`（逐告警贪心配对，最紧）/ `once-per-unit`（按单元去重但不看时刻，
  最松、无来源支持）。在 200 单元切片上，"每行都报"与"只报标签行为 1"两份参考提交在
  `sn-in-window` 与 `once-per-unit` 下给出**完全相同**的分数（0.5873/0.5417 与 1.0/1.0），
  在 `each-alarm` 下才是 0.0236/0.0229 与 0.0850/0.0820 —— 也就是说这里拉开一个量级的是**去重与否**，
  不是时刻。
- 已知与官方读法的三处边界（都在 `docs/runs/smartmem-questions-for-leader.md` 第 1 条里待确认）：
  本仓按 `split_key` 切片打分，分母是切片内有窗的工单 SN，不是官方那种全量工单 SN；官方"只统计考卷
  日历窗内预测"这层过滤本仓没有；两个官方页面的窗左端差 15 分钟，本仓取**窄窗**偏保守。
- 退出码：0 评分成功，1 输入问题，**4 该切片没有可评分告警**（不是 0 分，是没得可评）。

## 4. Initial Solution Direction

- 初始解 `init.py`：**本仓自定的起点，不代表方案水平，也不是官方 baseline**。它只读第 1 节那四个文件
  （不碰工单、不碰被评切片的标签，标签只来自 `train_labels.csv`），用 15 列 CE 计数/趋势/空间聚集特征
  配一个 balanced 逻辑回归，然后做两个决定性的选择：每个单元只在它**最紧迫的一行**告警（判分口径下一个
  SN 只计一次，多报不加分也不扣分），以及告警线用**分位数**而不是绝对概率 —— 在训练切片上扫 50–99
  分位、按 SN 级代理 F1（某单元有任一 label=1 行视作会坏）选一档，再把同一档分位数套到被评切片上。
  绝对概率线在本切片上会把 dev 的告警全部压成 0（实测过，两切片行密度不同），分位数迁移是为此。
  在本仓 200 单元切片上它给出 dev 0.4416 / val 0.3448（`sn-in-window` 与 `each-alarm` 同值，因为一单元
  只报一次时两条读法重合）—— 这是**本地暂定尺子上的数**，切片正样本密度约 26%、远高于现场基率，
  不可与任何外部数字比较，也**不校验模型质量**：它只证明"候选 → 预测 → 评分"这条链路能跑通。
- 已知的强 baseline 方向（出处见知识包 `SM-*` 卡片）：把 CE 的**时间聚集**（storm、增长率、距上一条
  的分钟数）与**空间聚集**（同一 row/bank 反复出现 vs 散落在多个 row）分开建特征，是文献里反复验证的
  主线；`First CE Matters` 一支强调长期累计量而非短窗；LightGBM + 每单元一次告警是官方 starter kit 的
  形状。
- 可探索方向（不限于）：回看窗与锚点频率、按 A/B 队列或按硬件画像分模型的阈值、生存分析式的
  "距下一次故障时间"回归再转告警、按告警预算反推阈值（页面原文下这是唯一能压住 precision 的杠杆）、
  删失与随访前沿的处理。

## 5. Supplementary Information

- 逐条证据分级。页面原文（verified，来自官方竞赛主页与 SmartHW 说明，本仓已登记为
  `benchmark/smartmem/knowledge/sources.yaml` 的 `smartmem-homepage` / `smarthw-readme` /
  `codabench-3586`）：△tl=15min、△tp=7d、β 为超参、SN 级只计一次、命中必须落窗、流式三约束、
  许可与榜单关闭。
- 上面这些**逐字原文**本轮读的是本机另存的一份 2026-09-26 核录（`官方判分规则_核录0926.md`，
  它自己声明当天用浏览器实读公告页与 Evaluation 页，非转述）；页面本身本轮未重读。评分**源码**
  仍未到手，因此本任务的指标状态是 provisional 而不是 verified —— 这条区别就是第 3 节那三处边界的来源。
- 本任务目录引用的 `docs/datasets/smartmem.md` 已过期（还写着"无 evaluator"、`prepare_data.py` 抛
  `NotImplementedError`），它被本地 sparse-checkout 排除在工作树之外，实际状态以本文件与
  `docs/runs/smartmem-v1-dev-log.md` 为准。
- 旧尝试（另一条并行赛线的内存预测线）的数字**不在本任务的对照表里**：那把尺子是本地自造的，
  协议不同，唯一被允许引用的口径差异已经写进 `SM-PF-001` 与 `SM-EV-002` 两张卡片。
