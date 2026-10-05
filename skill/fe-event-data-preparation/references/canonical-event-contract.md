# 规范化事件契约（canonical event contract）

这份文档是 `src/faultevolve/data/` 公开契约的文字版。**代码是权威**，文档跟着代码改；
两者漂移由 `tests/test_smartmem_skill.py` 拦（把代码里的常量名从文档里删掉就会变红）。

## 1. schema 角色

`event_schema.CanonicalEventSchema` 是一个 frozen dataclass，六个字段全部是**角色**而不是列名：

| 字段 | 含义 | 约束 |
|---|---|---|
| `unit_col` | 单元标识列（一台设备一个值） | 非空字符串 |
| `time_col` | 事件时刻列 | 非空字符串，且不得同时声明为数值列 |
| `event_type_col` | 事件类型列，可为 `None` | 有则用于过滤类型集合 |
| `static_cols` | 不随时间变的属性列元组 | 元组，元素为列名 |
| `categorical_cols` | 类别列元组 | 同上 |
| `numeric_cols` | 数值列元组 | 不含 `time_col` |

`normalize_events` 做四件事：补齐并校验列存在、把时刻强制转成带时区的 UTC、把 `static_cols` /
`categorical_cols` / `numeric_cols` 落到指定 dtype、检查单元标识非空。
它**不构造特征**。`build_event_profile` 只输出探查报告（行列数、时刻范围、类型取值、缺失率），
供"schema 探查"这一步使用。

## 2. 窗口口径

`event_sampling.EventWindowConfig` 的字段即窗口契约：

| 字段 | 含义 |
|---|---|
| `lookback` | 特征可见区间长度，Timedelta，必须为正 |
| `lead` | 预测时刻到最早允许命中的间隔 |
| `horizon` | 标签窗口长度 |
| `anchor_frequency` | 时间网格步长（`grid` / `hybrid` 策略用） |
| `anchor_strategy` | 取值只能是 `event`、`grid`、`hybrid` 三者之一 |
| `max_samples_per_unit` | 每单元样本上限，`None` 表示不限；只允许出现在快速 fixture 里 |
| `seed` | 抽样种子，决定可复现性 |

三种 anchor 策略的差别：`event` 只在真实事件时刻预测；`grid` 只在固定网格预测；
`hybrid` 两者并集。**没有任何一种允许用告警时刻当 anchor**，因为那等于用标签定义样本。

## 3. 采样管线的调用顺序

```text
normalize_events -> build_labeled_samples -> assign_temporal_splits -> audit_temporal_splits
```

- `make_prediction_times` 产出 anchor 集合；
- `select_history` 只取 `event_time <= anchor` 的历史；
- `label_at_time` 依 `lead` / `horizon` 判正负；
- `censor_at_time` 在随访不足时把样本丢弃，而不是标成负；
- `make_sample_id` 生成稳定样本 id（单元 + 时刻的确定性散列）；
- `build_labeled_samples` 汇总以上步骤并返回输出帧。

## 4. 样本输出列

`event_sampling.OUTPUT_COLUMNS` 逐列含义：

| 列 | 含义 |
|---|---|
| `sample_id` | 稳定样本标识 |
| `unit_id` | 化名后的单元标识，日志与共享产物里只出现这一列 |
| `prediction_time` | anchor 时刻（UTC） |
| `label` | 该样本在标签窗口内的判定结果 |
| `split_key` | `train` / `dev` / `val` / `embargo` / `outside` / `cold_audit` 之一 |
| `history_start` | 特征可见区间起点 |
| `history_end` | 特征可见区间终点，等于 anchor |
| `label_window_start` | `prediction_time + lead` |
| `label_window_end` | `prediction_time + lead + horizon`，删失判定比较的就是它 |

## 5. 丢弃原因计数

`event_sampling.DROP_REASONS` 的每个键**总是出现**（没有发生就是 0），这样两次运行可以直接 diff：

| 键 | 什么时候非零 |
|---|---|
| `post_failure_event` | 首故障之后的事件行被剔除 |
| `no_history_candidate` | 该 anchor 之前没有任何可见事件 |
| `empty_history` | 有历史但窗口内为空 |
| `post_failure` | 样本落在首故障之后 |
| `insufficient_lead` | 距故障时刻不足 `lead`，无法作为样本 |
| `censored` | `label_window_end` 超出随访截止 |
| `max_samples_dropped` | 因每单元上限被裁掉的数量 |

一份报告若只写"丢弃 3 万行"而没有这张表，等于没写。

## 6. 划分与审计

`temporal_split.py` 公开：

- `SCORED_SPLITS` = `train`、`dev`、`val`；
- `NON_SCORED_KEYS` = `embargo`、`outside`、`cold_audit`；
- `SPLIT_PERCENTAGES` = 70 / 85 / 100（边界建议的默认切点，必须经人确认才落成配置）；
- `suggest_split_boundaries` 给出建议边界，`SplitBoundaries` 承载它，并要求
  `reach = 训练可见终点 + embargo` 不得超过随访截止，超了就报错而不是截断；
- `assign_temporal_splits` 按时间轴给每个样本打 `split_key`；
- `select_cold_units` 用固定 seed 抽冷启动单元；
- `audit_temporal_splits` 是闸门：它检查标签窗口跨段、embargo 覆盖、单元重复出现在相邻段等，
  结论 passed=false 时 CLI 必须失败退出，而不是打印警告。

## 7. 读取与分区

`io.py`：

- `FORMATS` = `csv`、`feather`；缺依赖时报错会点名需要哪个可选依赖；
- `iter_file_chunks` 按 `DEFAULT_CHUNK_ROWS` 起分块；`EventWindow` 描述一次读取的区间；
- `carry_forward` 让跨块的窗口特征与整读结果一致（等价性由测试逐位比较）；
- `iter_event_windows` 拒绝时刻乱序的文件；
- 时间列是裸整数时，读法必须由调用方声明：`epoch_unit`（`s` 或 `ms`）与时区缺一不可，因为数字本身
  分不清单位。整数是绝对时刻，所以声明的时区只决定显示，不移动值；naive 文本时间则相反，时区会真的
  改变时刻，所以那时它是必填的；
- `PartitionJob` + `write_partitions` 只由持锁协调者归并，返回 `written` / `reused` / `failed`，
  失败项只带单元化名与异常类型名。

## 8. 外排序与工作区空间

`external_sort.py` 是第 7 节那条拒绝的恢复步骤：`iter_event_windows` 遇到跨块时刻乱序的文件会报错，
而真实文件不保证有序，所以先把文件排成时间序，再交给窗口读取器。排序不把所有行读进内存。

`sort_file_to_time_order(path, *, out_dir, time_column, fmt, chunk_rows, prepare)` 返回
`SortResult`（字段 `path`、`rows`、`runs`、`reused`）：

- 任何一步同时持有的行数都不超过 `chunk_rows`：拆段按块读、按块写，归并把每个游标限制在一个块内；
  是否真的如此由测试数出来的，不是由 `tracemalloc` 比例推出来的；
- 归并阶段最多同时打开 `MAX_OPEN_RUNS` 个文件，超过就分多轮归并，中间文件命名唯一、用完即删；
- 排序键是两列内部字段：纳秒时刻 `__sort_ns` 与流内序号 `__sort_seq`。序号列保证跨段的并列行
  保持原文件顺序，所以结果等于对整文件做一次稳定排序；两列只存在于中间文件，最终输出会剥掉；
- 输入若已带这两列中的任何一列，直接拒绝——否则排序会静默重排调用方自己的数据；
- 时间列必须带时区，naive 时间戳会被拒绝，理由与第 2 节的窗口口径相同。

空间是写之前就算出来的，不是失败之后才发现的：`estimate_space_bytes` 按输入自身大小乘
`COPIES_AT_PEAK`（拆段、最大中间轮次、合并输出三份）再乘 `SPACE_HEADROOM_RATIO` 余量，
feather 输入按 `FEATHER_TEXT_RATIO` 折算成文本体积；`space_report` 给出 `SpaceReport`
（`needed_bytes`、`free_bytes`、`shortfall_bytes`，`sufficient` 属性）。不够时抛 `SortError`，
消息只带这三个字节数，不带任何路径；剩余空间取工作区最近的已存在父目录所在卷。

续跑靠 `SORT_SIDECAR_NAME`（文件名 `sort_manifest.json`，`SORT_VERSION` = `esort-v1`）：里面记
`config_hash`、输入与输出的 sha256 以及行数与段数。三者都对得上才返回 `reused=True` 且不重排；
配置变了抛 `ConfigChangedError`（CLI 退出码 2），输入变了就重排。合并输出就叫 `sorted.csv`
（`MERGED_FILE_NAME`），段文件放在 `runs`（`RUNS_DIR_NAME`）下。工作区目录里已有不属于排序自身的文件时
拒绝写入，输入也不得位于工作区之内。失败路径只删自己写的段文件，因此一次中断的排序不会留下
看起来已完成的输出。

命令行侧由 `--sort-inputs` 使用本节：`--sort-dir` 给出排序树的根，缺失即退 1；排序目录落在
`--raw-dir` 之内也退 1，因为下一次列目录会把排好序的副本当成输入、每个单元数两遍；与
`--profile-only` 同时给出同样退 1。每个单元一个工作区 `<sort-dir>/<queue>/<单元化名>/`，
`--dry-run` 只汇总整棵树的 `needed_bytes` / `free_bytes` / `shortfall_bytes` 并写 `written=False`，
不落一个字节；空间不够时退 1，消息里只有这三个字节数。全部排序完成后写 `<sort-dir>/layout.csv`
（列 `queue`、`unit`、`workspace`、`rows`、`runs`、`reused`、`source_bytes`），它是下一步找回
每个单元工作区的索引——路径里从头到尾没有单元原标识。

排序树是样本模式的一条输入，不只是产物。`--from-sorted <sort-dir>` 按 `layout.csv` 找回每个单元
的 `sorted.csv`，读的是已经规范化的行，原始文件这一趟不再被打开。这条路径上每一步都可证伪：

- `layout.csv` 必须列齐本次列出的每个单元，列名必须等于 `SORT_LAYOUT_COLUMNS`，同一单元出现两次即拒；
- 每个工作区的 `sort_manifest.json` 必须在，且它记的 `input_sha256` 必须仍等于当前原始文件的摘要——
  排完之后原始文件被改动，这一步就会拒绝，此前"layout 没记输入指纹"那条缺口由此补上；
- `sorted.csv` 必须仍等于侧车记的 `output_sha256`，被编辑过的合并文件会被拒绝；
- 只读：一次消费运行之后整棵树的字节逐一相同（由测试锁住）；
- 消息里只出现单元化名，路径与单元原标识都不出现在任何一条拒绝文案中。

跨块重复在这一步补上：分块路径只能看见块内的重复，一对被切到两个块里的重复合对会留在 `sorted.csv`；
`read_sorted_smartmem_file` 对整表重做一遍第 7 节的规范化与去重，所以"消费排序树"与"整读原始文件"
得到同样的行。这条等价由两处锁住：库层逐位比较 `.equals()`，CLI 层比较分区文件字节与 `config_hash`。
其中"直接整读排序树 ≠ 整读原始文件"也被测过一次，否则那组断言可以空过。

`--from-sorted` 与 `--sort-inputs`、`--profile-only` 互斥，一次只走一条路径。payload 的 `events`
字段声明这一趟事件行的来源（`raw-files` 或 `sorted-tree`）。它**不进 config hash**：一棵摘要全对的
排序树只是到达同一批字节的另一条路，两次运行该记同一个配置哈希。

一处已知偏离需求草案：排序树不与运行清单共用目录，它只有自己的 `layout.csv`，所以
`--sort-inputs` 不写 `manifest.json`、也不吃 `--resume`，续跑靠每个工作区的排序检查点。

## 9. 清单与恢复

`manifest.py`：

- `MANIFEST_NAME` = `manifest.json`，`LOCK_NAME` = `writer.lock`，`PARTITIONS_DIR` = `partitions`；
- `MANIFEST_VERSION` = `runmanifest-v1`，CLI 侧另有 `PREP_VERSION` 参与 `config_hash`；
- `config_hash` 拒绝三类内容：像密钥的配置键、像绝对路径的字符串值、非 JSON 标量类型；
- `prepare_run` 在配置变化且未显式续跑时抛 `ConfigChangedError`（CLI 映射为退出码 2），
  清单与磁盘不符时抛 `ManifestError`（退出码 1）；
- `EXIT_CONFIG_CHANGED` = 2 是通用层就认识的唯一退出码，其余由任务 CLI 的契约表决定。

## 10. CLI 参数与默认值

命令行入口是 `benchmark/smartmem/prepare_data.py`，参数分组：

| 组 | 参数 |
|---|---|
| 位置与格式 | `--raw-dir`、`--out-dir`、`--format` |
| 时间口径 | `--timezone`、`--epoch-unit`、`--lead-minutes`、`--horizon-days`、`--lookback-days`、`--sample-every-minutes`、`--anchor-strategy`、`--outcome-observed-until` |
| 标签与划分 | `--split-config`、`--error-types`、`--cold-unit-fraction`、`--max-samples-per-dimm`、`--seed` |
| 运行控制 | `--workers`、`--units-per-partition`、`--max-files`、`--min-free-gb`、`--profile-only`、`--dry-run`、`--resume`、`--json`、`--hash-inputs` |
| 排序输入 | `--sort-inputs`、`--sort-dir`、`--from-sorted` |

`--out-dir` 对除 `--sort-inputs` 外的每种模式都是必填；排序模式只写 `--sort-dir`，所以少了
`--out-dir` 也照常工作，少了 `--sort-dir` 则退 1。缺 `--out-dir` 不会退回 argparse 的用法退出码，
因为那个位置（2）已经归"配置变了"，所以它以退 1 报出。

`--epoch-unit` 默认不给：给了而文件里是文本时间不会改变任何一行（由字节相等锁住），不给而文件里是
裸整数则退 1 并点名是哪一列。它进 config hash——换一种单位读法就是换一个实验。

`--error-types` 默认 `CE.READ,CE.SCRUB,CE`，这是镜像的 460 个单元文件样本实测出来的三种拼写（样本
624 万余行事件，镜像共 62 224 个单元文件；不可纠正的那一类只出现在工单里，样本事件流中一行都没有）。
样本不是全量，所以这个默认值是可被 `--profile-only` 当场证伪的声明，不是官方口径。三条校验各有分工：

- 声明表在**每种模式**的解析阶段就检查，所以退 1 出现在动手之前：一个名字都不剩时退 1（空声明既不
  写任何类型特征，也不把任何行算成未声明，等于静默丢掉整组特征）；两个名字拼成同一个 `*_count`
  列时退 1，例如 `CE.READ` 与 `CE_READ` 都落到 `ce_read_count`，后一个计数会盖掉前一个；
- `--profile-only` 把观测到的取值与声明的取值一起写进 profile 表（scope 为 `error_type`），
  声明了但一次都没出现的名字记 0 行；
- 声明的取值域**一个事件行都盖不住**时 profile 退 1，消息同时点名两边。比较区分大小写，
  所以一份用小写 `ce` / `ue` 的合成 fixture 必须自己声明 `--error-types ce,ue`。
  只盖不住一部分不是错误，那是事实，打印出来由人判断。
  profile 是唯一会读遍事件行的模式，因此这条检查只在它里面做；样本模式只记录
  `unexpected_error_type_rows`，不做二次全量扫描。

`--units-per-partition` 默认 64：它决定一次读多少个单元的文件，是内存上限而不是实验变量，
因此**不参与 config hash**（改它不该让一次续跑看起来像新实验，这一点由测试锁住）。

两处已知偏离需求草案，按需求 16.4 记录：`--max-samples-per-dimm` 保留草案拼写（它映射到
`max_samples_per_unit`），`--units-per-partition` 与 `--profile-only` 是草案未列的新增。
两者都是领域 CLI 的参数，通用层没有器件词汇。
