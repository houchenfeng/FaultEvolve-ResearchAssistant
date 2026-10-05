---
name: fe-event-data-preparation
description: 为不规则事件流器件准备防泄漏样本：schema 探查、窗口口径、时间切分与 embargo、分块与 resume、退出码和审计。
---

## 何时使用

- 数据是**不规则事件流**（每台设备的事件条数、间隔极不均匀），不是每天一行的等间隔快照；
- 标签是**时间窗**内的事件（"未来 k 天内是否发生故障"），不是行级布尔列；
- 任务是器件故障预测/告警，需要产出 train / dev / val 三段时间外推的样本；
- 见到"以告警时刻为锚点造样本""正常设备全部标 0""在评估集上扫阈值"这类做法时，先用本 Skill 的
  清单否掉再动手。

等间隔快照型数据（日级 SMART 表）不要套本 Skill，走 `skill/fe-dataset-adapters/SKILL.md` 的快照路线。

## 必需输入清单

缺任何一项都应停在明确缺项，**不要用默认值掩盖不确定性**：

| 输入 | 为什么必需 | 缺失时的后果 |
|---|---|---|
| 原始事件目录 + 文件格式 | 决定读取路径 | 无法探查 |
| 单元列与时刻列的真实列名 | 规范化 schema 的入口 | 样本无法对齐 |
| 时刻的时区口径 | 所有减法的基础 | 窗口边界整体偏移一天 |
| lead 与 horizon（官方口径） | 定义"什么时候预测、预测多远" | 指标口径与评分不一致 |
| lookback 与 anchor 策略 | 定义"用多久的历史、在哪些时刻预测" | 样本量与泄漏风险失控 |
| 告警/工单表（单元、告警时刻、类型） | 标签的唯一来源 | 无法判定正负 |
| 每台单元的随访截止（outcome_observed_until） | 删失判定 | 尾部未观察区间被当成确认负例 |
| 划分边界或划分配置文件的生成依据 | 时间切分 | 只能随机分组，等于自欺 |
| 输出目录与最小空闲空间 | 断点续跑的前提 | 写到一半爆盘 |

## 原始数据只读原则

- 原始目录**只读**：不写回、不重命名、不压缩、不删除，哪怕只是"顺手清理"；
- 一切产物落在 `<OUT_DIR>` 下的 `partitions/`，与原始目录分离；
- 需要转换格式时，转换产物与原始数据不同名、不同目录，并在 manifest 的输入指纹里登记原始侧；
- 遇到"看起来是中间产物"的文件先问归属，不要删：它可能是别人正在用的结果。

## schema 探查

先探查再动手，探查不落样本：

```text
python benchmark/smartmem/prepare_data.py --raw-dir <RAW_DIR> --out-dir <OUT_DIR> \
  --format feather --timezone UTC --epoch-unit s --profile-only --json
```

输出给出：单元数、事件行数量级、时刻的最小/最大值、事件类型取值、列存在性。真实包的
`log_time` / `failure_time` 是裸整数秒，读法不猜，所以探查与落样本都要带 `--epoch-unit s`；漏了它会
停在退出码 1 并点名是哪一列。
`error_type` 的取值域同样不许猜：`--error-types` 的默认值是镜像样本实测出的 `CE.READ,CE.SCRUB,CE`，
比较区分大小写，一个事件行都盖不住时探查停在退出码 1 并把两边都印出来；声明了却没出现的名字会在
profile 表里记 0 行，所以"不可纠正的那一类只来自工单"这件事是表里的数字，不是口头约定。
把结果写进 `docs/datasets/`（若目录不存在则新建）下的输入证据文件，逐条标 verified / user_reported /
pending，后续所有争论以这份文件为准。

## 通用规范化字段

规范化只依赖六个角色：`unit_col`、`time_col`、`event_type_col`、`static_cols`、`categorical_cols`、
`numeric_cols`。完整契约、样本输出列、丢弃原因计数键，全部列在
[`references/canonical-event-contract.md`](references/canonical-event-contract.md)。

三条不可让步的规则：

1. 时刻必须带时区落到 UTC，禁止把裸 epoch 当本地时间；
2. 同一单元的事件必须按时刻升序进入采样器；
3. 规范化只做列名/类型/时区映射，**不做任何特征构造**，特征属于领域层。

## anchor、lookback、lead 与 horizon 的口径

- **anchor（预测时刻）**：样本挂靠的时间点。只能来自事件本身或固定时间网格，
  **不能来自标签**；
- **lookback（回看窗）**：`[anchor - lookback, anchor]` 的事件用于构造特征；
- **lead（提前量）**：预测时刻到"最早允许命中故障"的间隔，给运维留出处置时间；
- **horizon（预测窗）**：`(anchor + lead, anchor + lead + horizon]`，故障落在这里才算命中。

带数字的算例（lead 15 分钟、horizon 7 天、lookback 5 天，全部 UTC）：

| 项 | 值 |
|---|---|
| anchor | 2026-01-10 08:00 |
| 特征可见区间 | 2026-01-05 08:00 .. 2026-01-10 08:00 |
| 标签窗口 | 2026-01-10 08:15 .. 2026-01-17 08:15 |
| 该样本可否判负 | 只有随访覆盖到 2026-01-17 08:15 之后才可以，否则丢弃 |

同一单元在网格上会产出多个样本，这是有意的：故障预测按"单元 + 时刻"评估，不按行评估。

## 时间切分与 embargo

按时间轴切 train / dev / val，**不是按单元随机分组**。train 与 dev、dev 与 val 之间必须留出
embargo，长度至少 `lead + horizon`，用来切断"训练集尾部样本的标签窗口伸进评估期"。

```text
train ─────────┤embargo├──── dev ────┤embargo├──── val ────
```

- 落在 embargo 里的候选样本进入 `embargo` 计数，不参与评分；
- 需要考察"冷启动单元"（首次出现即要求预测）时，用固定 seed 抽出的单元集进入 `cold_audit`；
- 边界一旦确定就写进 `--split-config`，让每次运行读同一份 YAML，而不是各自算一遍。

## 分块、checkpoint 与 resume

- 大文件按块读（`io.iter_file_chunks`），历史特征在块间用 carry-forward 接续，保证分块结果与整读
  结果逐位一致；
- 输入**不保证有序**，而窗口读取器会拒绝跨块时刻倒退的文件——它只会报错，不会悄悄丢行。恢复步骤是
  先做外排序（`external_sort.sort_file_to_time_order`）再交给窗口读取器：任何一步同时持有的行数都
  不超过 `chunk_rows`，并列时刻保持原文件顺序（与整文件稳定排序逐位比对过），所需空间在写之前
  按输入字节数估算，不够就带三个数字报错；
- 排序要一个**自己的**工作区目录，不要和分区输出目录共用：目录里已有不属于排序的文件时它拒绝写入，
  排完把段文件删干净，只留合并结果与一份 checkpoint；续跑靠输入与输出的摘要，不靠"文件存在就算完成"；
- 命令行上的形态是 `--sort-inputs --sort-dir <目录>`：每个单元一个工作区，整棵树读完后再写一份
  `layout.csv` 索引（列里只有化名与字节数），空间不够在动手前就退 1，`--dry-run` 只报需求不写盘；
- 反过来 `--from-sorted <目录>` 让样本模式吃这棵树：靠 `layout.csv` 找回单元工作区，靠侧车里的输入
  与输出摘要确认"排完之后没人动过"，任何一条对不上都退 1；它与 `--sort-inputs`、`--profile-only`
  互斥，且不进 config hash——同一批字节换条路读，还是同一个实验；
- 单元是天然的分区键：一个单元的文件在一次运行里**只被读一次**，产出一个分区文件；
- 分区写出由持锁的协调者归并，锁文件与清单同名目录（见契约文档）；
- resume 的判定依据是**输出清单摘要**，不是"文件存在就算完成"；
- `--resume` 必须显式给：不给就是新实验；配置变了则拒绝续跑并退 2，此时要换 `--out-dir`，
  不要改 hash 或删清单；
- 只有 `--hash-inputs` 能发现"同尺寸静默改写"的输入，日常靠"单元名 + 文件大小"指纹。

## 匿名日志规则

日志、报告、manifest、PR 描述里都不得出现：真实序列号、原始事件行、工单内容、任何密钥。

- 单元标识一律经过 `anonymize_unit` 之类的稳定脱敏函数，同一单元跨运行得到同一化名；
- 失败任务只报 `{"name": ..., "error": <异常类型名>}`，不透传异常文本（异常文本里常带路径）；
- 输入清单用指纹（化名 + 大小的哈希），不用绝对路径；
- 密钥只从环境变量读，文档里写变量名和占位符，不写值。

## 泄漏检查清单

动手前后各走一遍 [`references/leakage-checklist.md`](references/leakage-checklist.md)。
它是一份可勾选的清单，不是说明文：每一条都是"没做就别说分数可信"。

## 分层测试：fixture 与真实数据

| 层 | 数据 | 断言什么 |
|---|---|---|
| 单元 | 手工小 fixture（行可手算） | 窗口算术、删失、丢弃计数 |
| 集成 | 几十单元的合成包 | 分区、resume、退出码、审计 |
| 端到端 | 真实小样本（受限规模） | 只验证"能跑通且拒绝项正确" |

原则：**能在 fixture 上手算的断言，不要写成快照**；真实数据的绝对分数不进代码断言，只进运行记录
`docs/runs/`。已有覆盖见 `tests/test_smartmem_prepare_cli.py`、`tests/test_chunked_io.py`、
`tests/test_event_sampling.py`、`tests/test_temporal_split.py`。

## 成功、失败与恢复条件

| 退出码 | 含义 | 正确的下一步 |
|---|---|---|
| 0 | 完成且审计通过 | 把 `audit/summary` 与 manifest 一起归档 |
| 1 | 输入、schema、时间、空间或审计错误 | 补缺项，不要改代码绕过 |
| 2 | 配置变化导致不能安全续跑 | 换新输出目录重跑，或按新配置全量重建 |
| 3 | 部分分区失败 | 保留输出诊断，修复后 `--resume`，未修好不得宣称完成 |

`--json` 模式下 stdout 只有**一个**可解析 JSON 对象，进度与错误行走 stderr；人读模式打印摘要而非
JSON 大块。审计没过的运行不写 `audit/summary`：一份"审计失败的审计摘要"不是证据。

## 数据外发与私有标签禁令

- 禁止上传原始数据、转换产物或任何含真实单元标识的文件到外部服务；
- 不得读取 holdout 目录、私有 test 标签或评分服务的实现细节；只允许本地评估器给分；
- 不自动下载受许可限制的数据：需要数据就让用户放置到指定目录，缺了就在退出码 1 里点名缺项；
- 需要联网校验文献时，只登记"读到了什么"，不把私有路径写进共享文件。

## 领域字段映射由 adapter 提供，不污染通用层

通用层 `src/faultevolve/data/` 只认角色，不认器件词汇；器件词汇一律落在任务目录与领域模块里
（例如 `src/faultevolve/tasks/` 下的事件 schema 映射与 `benchmark/smartmem/` 这套 CLI）。

新增一个事件流任务的正确顺序：

1. 在领域模块里声明 `CanonicalEventSchema`（把真实列名映射到角色）；
2. 声明该任务的 lead / horizon / 网格步长常量，并写进知识包或文档；
3. 复用通用采样、切分、审计、manifest、分区写出，**不复制它们**；
4. 任务测试只测领域差异；泄漏与确定性由通用层测试兜底。

判据：把通用层目录里所有 `*.py` 做一次领域词扫描，必须为空。这条判据本身有测试守着。

## 本阶段还没有建成的东西

- 事件流任务的**官方 evaluator 仍未实现**：`benchmark/smartmem/evaluator.py` 给的是本地暂定口径的分数
  （重复告警与两类队列的汇总都是开关），本 Skill 能产出可复现的样本与审计结论，**不能**给出可与官方
  榜单比较的候选算法分数；
- smoke test 与真实进化闭环还没有就绪，所以任何"提升多少"的表述在这里都不成立；
- 知识检索已就绪不等于评估已就绪，两件事见 `benchmark/smartmem/knowledge/README.md`；
- 排序结果已经可以是样本模式的输入（`--from-sorted`），但**"该排哪几个文件"仍要人判断**：现在靠分块
  读取报错来定位，没有一条命令自动挑出乱序文件；
- 真实包的目录结构已在识别名单里（`type_A` / `type_B` 与 `failure_ticket.csv`），但随访截止日与官方
  评分细则仍需人类确认，缺项时停在退出码 1 是预期行为。

## 最小可复制命令

```text
# 数据放在环境变量指向的目录里，不要把真实路径写进文档或提交
export EVENT_DATA_ROOT=/path/to/raw

# 0) 输入不保证有序：先只报空间需求，确认够了再排
#    时间列是裸整数秒，所以每条命令都带 --epoch-unit s
python benchmark/smartmem/prepare_data.py --raw-dir <RAW_DIR> \
  --format feather --timezone UTC --epoch-unit s --sort-inputs --sort-dir <SORTED_DIR> --dry-run --json
python benchmark/smartmem/prepare_data.py --raw-dir <RAW_DIR> \
  --format feather --timezone UTC --epoch-unit s --sort-inputs --sort-dir <SORTED_DIR> --json

# 1) 探查（不落样本）
python benchmark/smartmem/prepare_data.py --raw-dir "$EVENT_DATA_ROOT" --out-dir <OUT_DIR> \
  --format feather --timezone UTC --epoch-unit s --profile-only --json

# 2) 试算边界（不写分区）
python benchmark/smartmem/prepare_data.py --raw-dir <RAW_DIR> --out-dir <OUT_DIR> \
  --format feather --timezone UTC --epoch-unit s --lookback-days 5 --anchor-strategy hybrid \
  --outcome-observed-until 2026-01-31T00:00:00+00:00 --dry-run --json

# 3) 小样本落盘（受限规模，先确认拒绝项）
python benchmark/smartmem/prepare_data.py --raw-dir <RAW_DIR> --out-dir <OUT_DIR> \
  --format feather --timezone UTC --epoch-unit s --lookback-days 5 --anchor-strategy hybrid \
  --outcome-observed-until 2026-01-31T00:00:00+00:00 --max-files 64 --workers 2 --json

# 4) 续跑（仅在配置未变时允许）
python benchmark/smartmem/prepare_data.py --raw-dir <RAW_DIR> --out-dir <OUT_DIR> \
  --format feather --timezone UTC --epoch-unit s --lookback-days 5 --anchor-strategy hybrid \
  --outcome-observed-until 2026-01-31T00:00:00+00:00 --resume --json

# 5) 同一批样本改从排序树读：分区字节与 config hash 都该和第 3 步一致
python benchmark/smartmem/prepare_data.py --raw-dir <RAW_DIR> --out-dir <OUT_DIR_SORTED>   --format feather --timezone UTC --epoch-unit s --split-config <SPLIT_YAML>   --from-sorted <SORTED_DIR> --json

# 6) 回归
python -m pytest tests/test_smartmem_prepare_cli.py tests/test_event_sampling.py \
  tests/test_temporal_split.py tests/test_external_sort.py -q
```

`<RAW_DIR>` / `<OUT_DIR>` 是占位符，不要提交真实路径；`--max-samples-per-dimm`、
`--cold-unit-fraction`、`--seed`、`--min-free-gb`、`--error-types`、`--split-config`、
`--hash-inputs` 按需追加，全部含义见契约文档。
