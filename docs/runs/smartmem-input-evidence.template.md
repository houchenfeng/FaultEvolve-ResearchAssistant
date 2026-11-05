# SmartMem 一阶段输入证据（V1-00）

状态标记约定：`verified` = 本机只读探针直接读到；`user_reported` = 用户口述或组内文档，未独立复算；`pending` = 需要用户或队长确认。

## 1. 输入版本与来源

| 项 | 值 | 状态 |
|---|---|---|
| 数据集 | SmartMem（DRAM mcelog CE 日志 + 故障工单） | verified |
| 本机物理位置 | 用户华为·北航赛工程 `memory-predict/data/`（**不在本仓，禁止写入**） | verified |
| 原始事件 | `data/raw_tmp/type_A/*.feather` 56,403 个、`type_B/*.feather` 5,821 个，合计 62,224 个单元 | verified |
| 官方预计算特征 | `data/features/type_A/*.feather` 64,794 个、`type_B/*.feather` 7,175 个，合计 71,969 个单元 | verified |
| 工单 | `data/raw_tmp/ticket.csv` = `data/features/failure_ticket.csv` 同一份内容，836 行 | verified |
| 下载来源 | 官方 SharePoint 打包 `stage1_feather.7z`（2.91 GB）+ Kaggle `smartmem/smartmem-features` | user_reported |
| 队列身份映射 | `data/sn_meta.csv` 列 `sn, manufacturer, PN`，用于分组 | verified |

关键体积事实：全量原始日志约 130 GB（未压缩口径），单机只下载了 stage1 子集。**任何实现必须逐单元流式/分块、可断点续跑，不得假设能一次性 `read_csv` 全表。**

## 2. 实际格式（与文档/stub 的差异）

### 2.1 原始事件文件

- 文件名规则：`{unit_id}.feather`，父目录名 `type_A` / `type_B` 即 `serial_number_type`。836/836 工单 SN 都能在同名下找到日志文件，零缺失。`verified`
- 列名是 **PascalCase，24 列**：
  `BankId, BankgroupId, Capacity, ChannelId, ColumnId, CpuId, DimmId, FrequencyMHz, LogTime, Manufacturer, MaxSpeedMHz, McaBank, MciAddr, Model, PN, RankId, RetryRdErrLog, RetryRdErrLogParity, RowId, burst_info, deviceID, error_type_full_name, memory_type, region`
- 与 `src/faultevolve/tasks/smartmem_adapter.py` 里 `MCELOG_COLUMNS`（23 列、全小写、含拼写错误的 `manufacturter`）**不是一份 schema**：
  - 多出 `MciAddr`；
  - **没有 `error_type` 整型列**，实际是字符串 `error_type_full_name`，观测到的取值含 `CE.READ`、`CE.SCRUB`；
  - `Manufacturer` 拼写正确，而官方数据说明文档写的是 `manufacturter`；
  - `deviceID` 的大小写与文档的 `deviceid` 不一致。
  ⇒ `smartmem_adapter.py` 的字段表对应的是官方 *样例/Kaggle 文档口径*，本机实际到手的是*另一份导出*。**V1-05 必须实现显式列名映射层，不得假设 23 列直接命中。** `verified`
- `LogTime` 是 `int64` **epoch 秒**（不是毫秒、不是字符串）。`verified`
- 单文件行数跨度极大：探针里从 2 行到 7,519 行不等。`verified`
- **`LogTime` 在文件内不保证单调**：16 个抽样文件中 13 个非单调。排序与去重必须由实现自己保证。`verified`
- 精确重复行存在：120 个抽样故障单元里 20 个含完全重复行，最多 83 行。`verified`
- 同 `LogTime` 不同地址（`RowId/ColumnId/BankId`）的行大量存在：120 个里 99 个受影响，最多 228 行。⇒ 去重只能按「全部字段精确重复」，绝不能按时间戳去重。`verified`

### 2.2 工单文件

- 列名实际为 `sn_name, alarm_time, sn_type`；`TICKET_COLUMNS` 文档口径是 `serial_number, failure_time, serial_number_type`。**又是一份命名不一致**，V1-05 需要映射。`verified`
- `alarm_time` 是 `int64` epoch 秒，范围 `1704077850` ~ `1717170465`。`verified`
- 836 行、`sn_name` 无重复 ⇒ **当前工单表是「每单元至多一次故障」**，没有重复 ticket，也没有一单元多故障样本可用于验证更换/重置规则。`verified`
- `sn_type` 分布：A 768 / B 68。`verified`
- 无空值。`verified`

### 2.3 官方预计算特征文件

- 列：`LogTime`（int64 epoch 秒，事件行时间）+ **99 个特征列**（type_A）/** 66 个**（type_B）。`verified`
- 命名形如 `read_ce_log_num_15m`、`all_ce_count_1h`、`burst_count=8_6h`、`fault_mode_bank_15m`，后缀 `_15m/_1h/_6h` 表示**回看窗口**，即时间上因果（不含未来信息）。`verified`（列名语义）/`pending`（生成源码未读）
- type_B **结构性缺 6h 窗口全部列**，不是随机缺失 ⇒ 缺列必须显式建模，不能静默 NaN 掉。`verified`
- 有特征文件但无原始日志的单元约 9,745 个（71,969 − 62,224）。自建特征对这部分只能回退。`verified`

## 3. 时间范围与删失覆盖

| 项 | 证据 | 状态 |
|---|---|---|
| 官方观察窗 | 2024-01-01 ~ 2024-07-31 | user_reported（官方 FAQ 抄录 `knowledge/官方判分规则_核录0926.md`） |
| 工单覆盖截止 | `max(alarm_time)` = 2024-05-31 15:47:45（按 UTC 解释） | verified |
| 日志实际跨度（抽样） | 2023-12-31 16:20:28 ~ 2024-07-31 01:00:17（按 UTC 解释） | verified |
| 日志实际跨度（200 单元全读） | `--profile-only` 逐行扫完 200 个真实单元：`2023-12-31T16:00:03+00:00` ~ `2024-07-31T15:59:45+00:00`，共 6 281 694 行、0 个空文件 | verified |
| 取值域（200 单元全读） | 不加 `--error-types` 也退 0：`CE.READ` 6 249 429 / `CE.SCRUB` 31 349 / `CE` 916，三行相加正好等于 `row_count` | verified |
| 工单覆盖 vs 事件前沿（200 单元切片） | 切片 140 条工单 `max(alarm_time)` = `2024-05-31T01:13:37+00:00`，事件前沿 = `2024-07-31T15:59:45+00:00`，相差 61 天。按「全局随访前沿」口径产出的 19 540 行样本里，**1 866 行（9.5%）锚点落在工单覆盖之外且全部 `label=0`**（`val` 1 264 / `embargo` 221 / `dev` 191 / `outside` 190），`val` 分区 0 个正样本 ⇒ 这些是「未随访」不是「确认无故障」。**2026-10-04 已按 `min(事件前沿, 工单覆盖终点)` 重出 `split-v2.yaml` 并两条路径复跑**：17 531 行、消失的 2 009 行**全部 `label=0`**（新增 0 行）、正样本总数 4 613 一格未少、`val` 由 0 个正样本变 **608 个（26 个单元）**、载荷里 `rows_beyond_coverage = 0` | verified（口径已定并落地） |
| **时区口径** | 抽样最早时间戳落在 2024-01-01 之前 ⇒ 初判「epoch 按 UTC+8 解释」。**V1-05 复核后修正**：int64 epoch 是绝对时刻，按 `utc=True` 解释不需要时区，UTC 与 UTC+8 说的是**同一个瞬间**（2023-12-31 16:20Z == 2024-01-01 00:20+08），差别只在官方窗口端点怎么写。真正需要人确认的只剩一件事：官方 `2024-01-01 ~ 2024-07-31` 的端点是按 UTC+8 的日历日，还是按 UTC。**pending（仅阻塞 V1-10 的窗口裁剪，不再阻塞 V1-05）** | **pending（已缩小范围）** |
| `outcome_observed_until` | 只读探针不能确认「不在工单 = 该时段无故障」的覆盖到哪天。官方 FAQ 声明工单只到 5-31 且标签完整 ⇒ 候选取 **2024-05-31 当日结束（本地时区）**，其后区间只能判 `censored`。**本地实现口径已由用户拍定**：拿不到逐台真值，按「全局随访前沿」= 数据里最晚观测时刻实现；本轮 200 单元实测前沿 = `2024-07-31T15:59:45+00:00`，`split.yaml` 就按它写，并留住 `val_until + 7d15m ≤ 前沿`。官方真值口径仍是 pending。**2026-10-04 补充**：这条口径的代价已实测（见下一行「工单覆盖 vs 事件前沿」），现口径会把工单覆盖之外的 61 天当成确认负例；合适取值是 `min(事件前沿, 工单覆盖终点)`，机制已支持只是入参没这么给。**2026-10-04 组内已裁定并落地**：本地 `split-v2.yaml` 取 `2024-05-31T01:13:37+00:00`，两条路径复跑后
`rows_beyond_coverage = 0`、`val` 第一次有正样本（608 行正例 / 26 个单元）；官方若给出逐台随访终点，
只改入参、不动机制 | verified（本地口径已落地）+ pending（官方真值） |
| 预测区间 | 6/1 ~ 7/31 出告警，判分窗 `[alarm−7d, alarm−15min]`，`△tl=15min`、`△tp=7d` 为官方固定值 | user_reported |

**实现结论**：`outcome_observed_until` 必须是显式入参（§16.4 已这样规定），禁止从「某单元最后一条日志」推断存活时间。探针证据同时说明：300 个抽样故障单元中 152 个的日志在告警时刻之后仍有行 ⇒ **首故障及其之后的事件必须按 §16.3 默认剔除**，否则特征直接读到故障后信号。`verified`

## 4. metric 状态

| 项 | 值 | 状态 |
|---|---|---|
| 指标名称 | SN 级 F1 | verified（官方 FAQ） |
| 提交格式 | `serial_number,prediction_timestamp,serial_number_type`（baseline.py 自己写 `sn_name`，以 FAQ 为准） | verified |
| 命中定义 | 任一预测落入 `[alarm−7d, alarm−15min]`；P/R 均为 SN 级且只统计窗内预测 | verified |
| 流式约束 | 预测时间戳不得早于所用最后一条日志 | verified |
| **重复告警、故障计数、A/B 汇总细则** | 页面原文已核录到"SN 级去重、命中须落窗"（§3），本地 evaluator 默认已照此实现为 `sn-in-window`；仍缺**可执行评分源码**，且 `serial_number_type` 报错是否作废命中、是否只统计考卷日历窗内预测两项无记载 | **provisional** |
| 官方 baseline / 往届冠军 | 约 0.207 / 约 0.30（Codabench 3586 榜口径） | user_reported |
| 榜可用性 | www 2025 SmartMem 赛道已关闭（`CURRENT ACTIVE PHASE: None`，2025-04-11 已发榜）⇒ 不能提交校准 | verified（浏览器实读） |

⇒ 第一版按 §16.5 记 `metric_spec_status=provisional`；不得把逐样本 F1 写成已复现官方事件 F1。

## 5. 已有方法与结果来源

用户在本机已有一条完整的内存预测线（华为·北航 A 题），详见 `docs/runs/smartmem-existing-attempt-analysis.md`。其结果全部来自**本地自造尺子**，无任何榜单提交可校准。

| 尺子 | F1 | 阈值口径 | 状态 |
|---|---|---|---|
| 6,000 正常单元 | 0.6022 | 评估集 OOF 上扫分位数（上帝视角） | verified（代码 + 日志复算） |
| 20,000 正常单元 | 0.4647 | 同上 | verified |
| 现场口径（71,133 正常，基率 1.16%） | 0.3179 | 同上 | verified（回归逐位复现） |
| 官方规则本地考卷（时间前向留出） | **0.1925** | 按告警预算取 top-1% 分位，全程不看答案 | verified |

对外可引用的只有第四档 0.1925（与官方 baseline 0.207 同量级）；前三档是内部相对比较口径，不可跨协议比较，也不校验告警时刻是否落在判分窗内（是宽松上界）。

## 6. pending 清单（需要用户/队长给的）

1. `LogTime`/`alarm_time` epoch 秒的**时区解释**（UTC 还是 UTC+8）。阻塞 V1-05 与 V1-10。
2. `outcome_observed_until` 的确切值与依据文件（建议 2024-05-31 日终，本地时区）。
3. 官方评分源码或重复告警/故障计数/A-B 汇总细则（§4 表最后一行）。
4. 一单元多故障的处理规则：**当前工单表里没有这种样本**，所以 §16.3 的「多故障需更换/重置身份规则」只能用合成 fixture 覆盖，真实数据无从验证 ⇒ 状态 `pending`。
5. `pyarrow` 是否进 `requirements.txt` / `pyproject`（当前测试环境是我自建 venv 里补装的）。
6. `prepare_data.py` 硬编码 `--train-until 2024-06-30 --val-until 2024-08-31` 与 §V1-07 的时间外推要求冲突，是否可由我改成显式入参。

## 7. 本轮取证方式与边界

- 全程 `C:/Users/Pomelo/Documents/fe-smartmem-venv` 只读脚本，未向该工程写入任何文件，未修改其任何脚本。
- 报告不打印真实序列号；文件名一律以 `sn_#` 掩码形式出现；样本行数/列名/统计量不含身份。
- 代码版本以「文件 + 行号」引用，不复制私有源码到共享报告。
