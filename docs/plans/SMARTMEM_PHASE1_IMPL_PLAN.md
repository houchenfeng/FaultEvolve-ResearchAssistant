# SmartMem 第一阶段实施规格：通用事件数据处理与内存知识注入

> 文档用途：交给新的 AI 编程代理，在本地从最新 `main` 创建新分支并独立完成开发。
>
> 目标读者能力假设：能够读写 Python 和 pytest，但不熟悉 FaultEvolve、SmartMem、事件式故障预测和服务器部署。因此本文给出必须遵循的接口、边界、测试和验收步骤；不得靠猜测省略步骤。
>
> 本阶段只交付两项能力：**SmartMem 数据处理**与**SmartMem 知识注入**。完整候选程序进化、正式 evaluator、Codabench 提交和大规模真实运行属于后续阶段，除非用户另行扩大范围。

配套执行清单：[第一版开发 TODO](SMARTMEM_PHASE1_TODO.md)。后续完整闭环见 [第二版需求](SMARTMEM_PHASE2_REQUIREMENTS.md) 和 [第二版开发 TODO](SMARTMEM_PHASE2_TODO.md)。2026-10-03 补充的接口消歧以第 16 节为准。

---

## 0. 项目目标与事实基线

FaultEvolve 当前以硬盘 SMART 日快照任务为主。SmartMem 是 DRAM 内存不可纠正错误（UE）预测任务，数据协议不同：

- 原始输入是每个 DIMM 的不规则 mcelog 事件流，而不是每日 SMART 快照；
- 在预测时刻 `t` 只能使用 `t` 及之前的事件；
- lead time 为 15 分钟；
- 预测窗口为 lead time 后的 7 天；
- 官方主要指标为 F1；
- 同一个 DIMM 可以在不同时间产生多次预测；
- 数据存在极端类别不平衡、平台异质性、硬件老化和分布漂移。

官方来源：

- 竞赛页：<https://www.codabench.org/competitions/3586/>
- 官方说明：<https://hwcloud-ras.github.io/SmartMem.github.io/>
- 官方代码与 starter kit：<https://github.com/hwcloud-RAS/SmartHW>
- 官方 starter kit 说明：<https://github.com/hwcloud-RAS/SmartHW/tree/main/competition_starterkit>

官方基线包含时间、空间和 parity 特征提取，正负样本生成，以及 LightGBM 训练；CSV 解压规模约 130 GB，Feather 解压规模约 40 GB。实现必须按大数据流式处理设计，不能假定全部数据可一次载入内存。

当前仓库已有但不完整的接口：

- `src/faultevolve/tasks/smartmem_adapter.py`
  - 已定义 23 个 mcelog 字段；
  - 已定义 ticket 与 submission 字段；
  - `aggregate_events_to_samples()` 仍抛出 `NotImplementedError`。
- `benchmark/smartmem/prepare_data.py`
  - 只能列举文件和校验 ticket；
  - 主流程仍抛出 `NotImplementedError`。
- `benchmark/smartmem/evolve.yaml`
  - `knowledge.enabled: false`；
  - `smoke_test.enabled: false`。
- `benchmark/smartmem/` 缺少完整的 `evaluator.py`、`init.py`、`problem.md`、`prompt.md` 和知识包。
- `SmartMemAdapter` 仍继承 `StubDatasetAdapter`，不能真实评估候选。

本阶段不得把这些 stub 描述成“SmartMem 已接入”。

---

## 1. 开始开发前必须向用户收集的信息

AI 在获得以下信息前，只能阅读代码、完善计划和编写不依赖真实数据的 fixture 测试；不得开始真实数据转换，不得宣称复现成功。

### 1.1 必需输入

向用户逐项索取并记录在 PR 描述中，但不得把敏感路径、账号或数据内容提交到公开文件：

1. **原始数据本地路径**
   - 数据由用户在自己的本地或受控服务器下载；AI 不登录 Codabench 代替用户下载。
   - 明确格式：CSV 或 Feather。
   - 明确目录结构：`train/`、`test/`、ticket、submission 模板的真实文件名。
2. **已有尝试代码**
   - 用户提供本地绝对路径、Git 仓库链接或压缩包位置。
   - 至少说明入口脚本、依赖环境、运行命令和输出位置。
3. **已有测试结果或运行说明**
   - 指标名称及数值；
   - 数据阶段（Phase 1/Phase 2）；
   - 训练/验证划分；
   - 随机种子；
   - 特征、模型、阈值；
   - 是否为 Codabench 分数、离线分数或复现分数。
4. **指标口径**
   - 优先使用用户给出的正式指标定义和已有 evaluator。
   - 如果用户没有提供，则采用官方 F1，并在文档中明确这是通过官方说明查得，而非用户确认。
5. **数据时间信息**
   - `log_time` 的格式、时区和范围；
   - `failure_time` 的格式、时区和范围；
   - 是否存在重复 ticket、一个 DIMM 多次故障或缺失时间。
6. **资源上限**
   - 可用内存、CPU 核数、磁盘空间；
   - 单次处理允许的最长时间；
   - 是否允许安装 `pyarrow`。

### 1.2 服务器阶段额外输入

本地第一阶段开发与测试通过后，才向用户索取：

1. 跳板机连接说明：跳板 Host、端口、用户名、`ProxyJump` 或反向隧道用法；
2. 目标服务器 Host、端口、用户名；
3. SSH 密钥或需要用户亲自完成的认证步骤；
4. 新目录命名偏好；
5. 用户确认的真实数据源路径，只读使用；
6. 用户确认可以使用的最大 CPU、内存、磁盘与运行时长。

密码、Token、API Key 不得写入本文、Git、测试、日志或 shell history。只保存非敏感 SSH alias 和路径说明。

### 1.3 输入证据清单

开发分支中新增一个不含敏感信息的模板：

```text
docs/runs/smartmem-input-evidence.template.md
```

模板只记录：来源类型、文件格式、schema 哈希、时间范围摘要、既有方法摘要、既有指标、复现命令占位符。不得记录序列号样本、密码、密钥和真实数据内容。

---

## 2. 分支、工作区和受保护内容

### 2.1 本地开发流程

开始前执行：

```bash
git status --short
git fetch origin
git switch main
git pull --ff-only origin main
git switch -c feat/smartmem-data-knowledge
```

如果工作区不干净，停止并向用户报告；不得 `git reset --hard`，不得覆盖用户修改。

基线信息必须写入 PR 描述：

```bash
git rev-parse HEAD
python --version
python -m pytest --collect-only -q
```

### 2.2 绝对禁止修改

继续遵守仓库根目录 `AGENTS.md`：

- 不修改 `benchmark/hdd_mvp/evaluator.py`；
- 不修改 `benchmark/hdd_mvp/init.py`；
- 不修改 `benchmark/hdd_mvp/problem.md`；
- 不修改 `benchmark/hdd_mvp/prompt.md`；
- 不修改 `benchmark/hdd_mvp/data/`；
- 永远不读取、打印、复制或上传任何 `holdout*`；
- 不把 LLM 或 Jev 输出作为分数；
- 不提交 SmartMem 原始数据、中间数据、标签、预测或大文件。

### 2.3 本阶段不得做的事情

- 不把 HDD evaluator 复制后仅改文件名冒充 SmartMem evaluator；
- 不在没有真实数据 schema 的情况下硬编码列类型；
- 不使用官方 test 数据选择阈值、特征或参数；
- 不用随机行切分事件流；
- 不让同一预测窗口的未来事件进入特征；
- 不把用户已有结果改写成新实现的结果；
- 不启动真实 LLM 进化；
- 不覆盖服务器上的任何原目录或结果。

---

## 3. 第一阶段交付物

### 3.1 必须交付

1. SmartMem 原始数据只读探查与 schema 报告；
2. 通用事件流样本构建接口；
3. SmartMem 的 15 分钟 lead / 7 天 horizon 标签逻辑；
4. 严格时间外推的 train/dev/val 划分和泄漏审计；
5. 可恢复、确定性、分块的数据转换 CLI；
6. SmartMem 内存领域知识包；
7. 一个可复用的数据处理 Skill；
8. 单元测试、集成测试和小规模端到端 fixture；
9. 数据处理 manifest、统计报告和知识卡验证报告；
10. 更新 SmartMem 文档，准确区分“已实现”和“后续阶段”。

### 3.2 明确不在本阶段交付

- 完整 `evaluator.py`；
- 完整 `init.py`；
- FaultEvolve 的 SmartMem 真实进化；
- Codabench 提交；
- 官方 test 标签评估；
- 修改通用进化引擎以适配某个 SmartMem 特例；
- 将 SmartMem 数据上传到云端或代码仓库。

如果为了验证数据处理必须运行用户已有基线，可以调用用户提供的代码，但只能作为**参考复现**，不得把它变成当前阶段隐藏的新产品范围。

---

## 4. 目标目录结构

完成后建议形成：

```text
benchmark/smartmem/
├── README.md
├── evolve.yaml
├── prepare_data.py
├── data_contract.md
└── knowledge/
    ├── README.md
    ├── cards.jsonl
    ├── sources.yaml
    └── expert.md

src/faultevolve/
├── data/
│   ├── __init__.py
│   ├── event_schema.py
│   ├── event_sampling.py
│   ├── temporal_split.py
│   ├── manifest.py
│   └── io.py
└── tasks/
    └── smartmem_adapter.py

skill/
└── fe-event-data-preparation/
    ├── SKILL.md
    └── references/
        ├── canonical-event-contract.md
        └── leakage-checklist.md

tests/
├── fixtures/smartmem_toy/
├── test_event_sampling.py
├── test_temporal_split.py
├── test_smartmem_prepare.py
├── test_smartmem_knowledge.py
└── test_smartmem_data_boundaries.py
```

可以按现有命名习惯微调，但不得把通用事件处理实现塞进 `cloud/engine.py`。引擎必须保持任务无关，现有 `tests/test_engine_task_agnostic.py` 必须继续通过。

---

## 5. 通用数据处理抽象

### 5.1 为什么需要独立抽象

SmartMem 是第一个不规则事件流任务。处理逻辑应抽象成可用于 DRAM、日志告警、器材事件等任务的 Skill 和 Python 接口；SmartMem adapter 只负责字段映射、领域特征和官方时间窗口。

通用层不得出现以下字符串或知识：`DIMM`、`mcelog`、`ECC`、`UE`、`bankid`、`SmartMem`。这些只能出现在 SmartMem adapter、任务目录、知识卡和任务测试中。

### 5.2 规范化事件 schema

新增不可变数据契约 `CanonicalEventSchema`：

```python
@dataclass(frozen=True)
class CanonicalEventSchema:
    unit_col: str
    time_col: str
    event_type_col: str | None = None
    static_cols: tuple[str, ...] = ()
    categorical_cols: tuple[str, ...] = ()
    numeric_cols: tuple[str, ...] = ()
```

要求：

- `unit_col` 标识预测单元；SmartMem 中为 DIMM 序列号；
- `time_col` 必须转换为统一的 UTC `datetime64[ns, UTC]`；
- 原始时间无时区时，必须由用户或 CLI 参数指定，不得默认为本机时区；
- 输入行顺序不可信，处理前按 `(unit_col, time_col)` 稳定排序；
- 重复事件的处理策略必须显式配置：`keep`、`drop_exact` 或 `error`；默认 `drop_exact`；
- schema 报告只能包含列名、dtype、缺失率、基数、时间范围和计数，不得包含真实序列号或原始行样例。

### 5.3 采样与标签接口

新增通用配置和结果类型：

```python
@dataclass(frozen=True)
class EventWindowConfig:
    lookback: pd.Timedelta
    lead: pd.Timedelta
    horizon: pd.Timedelta
    anchor_frequency: pd.Timedelta
    anchor_strategy: Literal["event", "grid", "hybrid"]
    max_samples_per_unit: int | None
    seed: int


@dataclass(frozen=True)
class SplitBoundaries:
    train_end: pd.Timestamp
    dev_end: pd.Timestamp
    val_end: pd.Timestamp
    embargo: pd.Timedelta


def build_labeled_samples(
    events: pd.DataFrame,
    failures: pd.DataFrame,
    schema: CanonicalEventSchema,
    config: EventWindowConfig,
) -> pd.DataFrame:
    ...
```

最小输出列：

```text
sample_id, unit_id, prediction_time, label, split_key,
history_start, history_end, label_window_start, label_window_end
```

其中：

```text
history interval     = (prediction_time - lookback, prediction_time]
label window         = [prediction_time + lead,
                        prediction_time + lead + horizon]
label                = 1 iff failure_time falls inside label window
```

边界必须在测试中逐点验证：

- `failure_time == prediction_time`：不得作为未来标签；
- `failure_time < prediction_time + lead`：样本丢弃，不能标负；
- `failure_time == prediction_time + lead`：标正；
- `failure_time == prediction_time + lead + horizon`：标正；
- 晚于右边界 1 ns：不标正；
- 特征不得读取晚于 `prediction_time` 的事件。

### 5.4 SmartMem 字段适配

保留现有官方字段拼写 `manufacturter`，不得擅自改成 `manufacturer` 破坏兼容性。内部可以新增规范化别名，但 manifest 必须记录映射。

原始每个 DIMM 一个文件时，序列号可能只存在于文件名。新增读取函数：

```python
def read_smartmem_file(
    path: Path,
    *,
    fmt: Literal["csv", "feather"],
    serial_number: str | None = None,
) -> pd.DataFrame:
    ...
```

规则：

- `serial_number` 未显式提供时，从文件名按用户确认的规则提取；
- 提取规则必须有测试，不能简单假设所有扩展名前内容都是序列号；
- 返回 frame 必须增加内部列 `serial_number`；
- 不得把真实序列号写进日志；日志只输出不可逆短哈希或计数；
- `log_time` 解析失败率大于 0 时默认失败，除非用户显式允许并设置阈值；
- `serial_number_type` 的 A/B 语义以真实数据和用户已有代码为准。

`SmartMemAdapter.aggregate_events_to_samples()` 应成为薄封装：构造 schema/config，调用通用 `build_labeled_samples()`，再增加 SmartMem 领域特征。不得在此重复时间切分算法。

### 5.5 特征组

第一版实现应先复现用户已有代码与官方基线中明确存在的特征，不以“看起来合理”为由虚构字段。按以下组组织输出，并允许逐组开关：

1. 时间强度：窗口内事件数、最近事件间隔、不同子窗口计数、增长率；
2. 空间集中度：channel/DIMM/rank/device/bank group/bank/row/column 的唯一数、集中度和重复度；
3. 错误类型：`error_type` 计数、比例、最近一次类型；
4. retry/parity：`retryrderrlogparity`、`retryrderrlog`、`burst_info` 的计数与组合；
5. 静态配置：model、PN、capacity、frequency、max speed、memory type、region；
6. 交互特征：只有用户已有代码或可信来源支持时才加入，并记录来源；
7. 缺失与覆盖：各类字段是否出现、窗口覆盖时长、数据稀疏程度。

所有聚合只允许使用历史窗口。任何使用 `failure_time`、未来事件或 split 统计的特征都应被测试拒绝。

### 5.6 大数据执行约束

禁止：

- `pd.concat()` 一次合并全部 DIMM 文件；
- 先把 40–130 GB 数据完整复制到系统根盘；
- 把所有中间文件写入 Git 工作区；
- 无断点地运行数小时且不写 manifest/checkpoint。

必须：

- 按文件或固定分区流式读取；
- 中间结果写分区文件；
- 原子写入：先写 `.tmp`，完成校验后再重命名；
- 每个分区记录输入哈希、配置哈希、行数、时间范围和完成状态；
- 重跑时复用配置哈希一致且校验通过的分区；
- 提供 `--workers`，默认保守值，不自动占满服务器；
- 提供 `--dry-run`、`--max-files` 和 `--profile-only`；
- 所有随机抽样使用显式 seed，且与文件遍历顺序无关。

推荐的逻辑输出契约：

```text
<out-dir>/
├── manifest.json
├── profile.json
├── split_manifest.json
├── partitions/
│   ├── train/part-*.parquet
│   ├── dev/part-*.parquet
│   └── val/part-*.parquet
├── labels/
│   ├── train.parquet
│   ├── dev.parquet
│   └── val.parquet
└── reports/
    ├── leakage_audit.json
    └── feature_summary.json
```

物理格式默认 Parquet；如果 `yolo26` 缺少 `pyarrow`，先报告依赖差异，由用户确认安装。不得悄悄退化为单个巨型 CSV。

---

## 6. 训练、开发与验证切分

### 6.1 主切分：严格时间外推

用户已选择按建议方案切分。实现采用三段时间外推：

```text
早期 70% 时间：train
中间 15% 时间：dev
最后 15% 时间：val
```

百分比基于可用于建模的时间跨度，而不是基于行数。实际边界必须落到 `anchor_frequency` 的整数边界，并写入 `split_manifest.json`。

在相邻 split 之间设置 purge/embargo：

```text
embargo = lead + horizon = 15 minutes + 7 days
```

任何 label window 穿过 split 边界的样本都必须删除，确保训练标签不观察到 dev/val 时段的故障。

### 6.2 同一 DIMM 跨 split

主评估允许同一 DIMM 随时间进入 train、dev、val，因为这模拟线上持续观察，但必须满足：

- 每个样本只使用预测时刻之前的数据；
- split 统计、编码器和阈值只在 train 或 dev 拟合；
- val 仅用于最后报告，不用于反复调参。

额外生成一个只读审计切分 `cold_unit_audit`：按 DIMM 分组，使审计单元不出现在训练中，用于衡量新硬件泛化。该审计不替代主时间切分，也不作为本阶段优化目标。

### 6.3 切分边界的优先级

1. 用户已有代码中明确且可复现的正式切分；
2. 用户明确指定的时间边界；
3. 本文 70/15/15 自动建议。

如果采用前两项，仍必须运行 embargo 和泄漏审计，不得因为“已有结果”而跳过。

### 6.4 泄漏审计必须检查

- `history_end <= prediction_time`；
- `label_window_start >= prediction_time + lead`；
- train 的 `label_window_end < dev_start`；
- dev 的 `label_window_end < val_start`；
- val 数据未参与特征词典、类别编码、归一化、负采样概率和阈值拟合；
- failure ticket 只用于生成标签，不进入特征列；
- 文件名、目录名或行顺序没有携带 label；
- 用户已有代码若读取 test 或未来信息，必须在报告中标为风险，不能照搬。

审计失败时 CLI 必须非零退出，不得只打印 warning。

---

## 7. CLI 实现规格

扩展 `benchmark/smartmem/prepare_data.py`：

```bash
python benchmark/smartmem/prepare_data.py \
  --raw-dir <USER_LOCAL_RAW_DIR> \
  --out-dir <NON_GIT_OUTPUT_DIR> \
  --format feather \
  --timezone UTC \
  --lookback-days 5 \
  --lead-minutes 15 \
  --horizon-days 7 \
  --sample-every-minutes 15 \
  --anchor-strategy event \
  --max-samples-per-dimm 200 \
  --seed 20260926 \
  --workers 2
```

必须支持：

```text
--profile-only       只生成匿名 schema/profile，不构建样本
--dry-run            校验输入、估算文件数和空间，不写大文件
--max-files N        fixture/冒烟限制
--resume             复用已完成且哈希一致的分区
--split-config PATH  使用用户确认的边界 YAML
--json               机器可读摘要
```

退出码：

- `0`：完成且所有审计通过；
- `1`：输入、schema、时间、空间或审计错误；
- `2`：配置变化导致不能安全 resume；
- `3`：部分分区失败，输出保留供诊断，但不得标记完成。

日志不得出现真实序列号、原始事件行、ticket 内容和密钥。

---

## 8. SmartMem 知识注入

### 8.1 原则

知识卡必须有来源、适用条件和风险。优先级：

1. 用户提供的已有运行代码与结果；
2. SmartMem 官方说明、starter kit、论文和获奖方案；
3. DRAM/ECC/RAS 可信论文；
4. 专家明确提供的经验；
5. LLM 假设只能标为 `llm_hypothesis`，不能伪装成文献事实。

不得直接复制 HDD 的 SMART 卡片并替换名词。HDD 的 SMART 5/187/197/198 等语义不适用于 DRAM mcelog。

### 8.2 知识包文件

新增：

```text
benchmark/smartmem/knowledge/cards.jsonl
benchmark/smartmem/knowledge/sources.yaml
benchmark/smartmem/knowledge/expert.md
benchmark/smartmem/knowledge/README.md
```

卡片沿用现有 loader schema：

```json
{
  "id": "SM-FE-001",
  "title": "...",
  "category": "feature_engineering",
  "claim": "...",
  "rationale": "...",
  "applicability": "...",
  "expected_effect": "...",
  "risk": "...",
  "source_ids": ["smartmem-official-starter"],
  "tags": ["dram", "mcelog", "temporal"],
  "impl_hint": "...",
  "priority": 1,
  "evidence": "paper"
}
```

ID 使用 `SM-*` 命名空间，避免与 HDD 的 `FE*`、`M*`、`T*` 和发现卡 `D-*` 冲突。

### 8.3 第一版知识主题

至少覆盖下列主题；每张卡不必只对应一个主题，但总卡片数不得代替质量验收：

1. CE/ECC 信号到 UE 风险的时序演化；
2. 最近事件间隔、突发性、速率变化和多窗口统计；
3. channel/rank/device/bank/row/column 空间集中模式；
4. retry/parity/burst 信息的语义与组合；
5. DIMM 型号、容量、频率、memory type、region 的异质性；
6. A/B 或多平台域偏移与分层建模；
7. 硬件老化和时间漂移；
8. 极端类别不平衡、负样本选择和概率校准；
9. 15 分钟 lead 与 7 天 horizon 的标签边界；
10. 同一 DIMM 多次告警造成的重复样本和评估偏差；
11. 时间外推、purge/embargo 和未来信息泄漏；
12. LightGBM 及稀疏表格模型的适用性；
13. 阈值选择、F1 与 precision/recall 权衡；
14. 缺失字段、匿名硬件类型和未知类别处理；
15. 可扩展特征计算、缓存和运行时约束。

### 8.4 现有尝试的知识化

用户提供已有代码后，AI 必须先生成一份只读分析：

```text
docs/runs/smartmem-existing-attempt-analysis.md
```

内容包括：

- 已用数据与 split；
- 已用特征；
- 模型和阈值；
- 已知指标；
- 可验证的有效做法；
- 可能的数据泄漏；
- 可以转成知识卡的做法；
- 缺少证据、暂不能入卡的猜测。

只有具有来源或运行证据的结论可以进入正式卡片。用户已有结果应标为 `evidence: user_run`，并在 `sources.yaml` 中使用匿名 run id，不包含私有路径。

### 8.5 配置

知识包完成并通过校验后，可以把 `benchmark/smartmem/evolve.yaml` 改为：

```yaml
knowledge:
  enabled: true
  dir: knowledge
  k: 4
  max_per_category: 2
```

但 README 必须注明：知识检索已就绪，不代表 SmartMem evaluator 或真实进化已就绪。

---

## 9. 可复用 Skill 规格

新增 `skill/fe-event-data-preparation/SKILL.md`，面向后续 AI，至少包括：

1. 触发条件：不规则事件流、时间窗标签、设备故障预测；
2. 用户必需输入清单；
3. 原始数据只读原则；
4. schema 探查命令；
5. 通用规范化字段；
6. anchor、lookback、lead、horizon 的定义；
7. 时间切分与 embargo；
8. 分块、checkpoint、resume；
9. 匿名日志规则；
10. 泄漏检查清单；
11. fixture 与真实数据的分层测试；
12. 成功、失败和恢复条件；
13. 禁止上传数据、禁止读取私有 test 标签；
14. 如何由数据集 adapter 提供领域字段映射，而不污染通用模块。

Skill 不得声称自动下载受许可限制的数据。若引用脚本，脚本必须在仓库内并由测试覆盖。

---

## 10. 测试规格

### 10.1 单元测试

`tests/test_event_sampling.py`：

- 精确验证 lead/horizon 左右边界；
- 验证历史窗口不包含未来事件；
- 验证无事件、单事件、乱序事件、重复事件；
- 验证一个 DIMM 多个 ticket 的明确策略；
- 验证 seed 相同时输出逐行一致；
- 验证文件顺序变化不影响抽样结果；
- 验证真实序列号不出现在日志。

`tests/test_temporal_split.py`：

- 70/15/15 边界按时间计算而非行数；
- embargo 正确删除跨界 label window；
- train/dev/val 无 sample_id 重叠；
- cold-unit audit 与 train unit 无重叠；
- 非 UTC 或无时区输入按配置处理；
- 无法形成三个有效区间时明确失败。

`tests/test_smartmem_prepare.py`：

- CSV 与 Feather fixture 逻辑结果一致；
- 从文件名提取 unit id；
- 严格校验 23 列和 `manufacturter` 拼写；
- `profile-only` 不产生样本分区；
- `dry-run` 不写大文件；
- resume 只复用哈希一致分区；
- 失败分区不被标为完成；
- CLI `--json` 输出可解析。

### 10.2 知识测试

`tests/test_smartmem_knowledge.py`：

- `cards.jsonl` 每行是合法 JSON；
- 所有 id 唯一且以 `SM-` 开头；
- 所有 `source_ids` 都能在 `sources.yaml` 找到；
- 所有 category 被现有 loader 接受；
- 每张卡有 applicability、risk 和 impl_hint；
- 不包含 HDD SMART 属性专用建议；
- 用 SmartMem 关键词能检索到领域卡；
- 用无关 HDD 关键词不会总是返回 SmartMem 卡；
- loader 与已有 HDD 知识包兼容。

### 10.3 安全与回归测试

`tests/test_smartmem_data_boundaries.py`：

- 仓库中不存在 SmartMem 原始数据、大型中间文件和预测结果；
- `.gitignore` 覆盖 SmartMem 数据输出；
- 日志与 manifest 不包含 fixture 中设置的敏感 unit id；
- 不访问 `test` 标签或 `holdout*`；
- `benchmark/hdd_mvp` 四个受保护文件哈希不变。

必须继续通过：

```bash
python -m pytest tests/test_hdd_protected_files.py -q
python -m pytest tests/test_engine_task_agnostic.py -q
python -m pytest tests/test_adapter_registry.py -q
python -m pytest tests/test_dataset_stubs.py -q
python -m pytest tests/test_event_sampling.py tests/test_temporal_split.py -q
python -m pytest tests/test_smartmem_prepare.py tests/test_smartmem_knowledge.py -q
python -m pytest tests/ -q
```

如果在 Windows 上因为 Unix `resource` 模块导致测试收集失败，要在 PR 中准确记录平台问题；不得删除、跳过或弱化相关测试来制造全绿。建议在 Linux CI 或服务器隔离副本中完成最终全量测试。

### 10.4 真实数据测试分层

真实数据测试按顺序执行，每一层成功后才能进入下一层：

1. `--profile-only --max-files 2`；
2. `--dry-run` 全目录；
3. `--max-files 10` 小转换；
4. 单个时间分区；
5. 全量转换；
6. 用用户已有代码在新处理结果上做参考复现。

每一步记录命令、commit、配置哈希、输入 manifest 哈希、耗时、峰值内存、输出大小和结果。不得记录真实序列号。

---

## 11. 验收标准

### 11.1 数据处理

- 用户真实 schema 已确认，而不是仅依赖 stub；
- CSV/Feather 中至少一种真实格式完成小规模转换；
- 15 分钟 lead、7 天 horizon 边界测试通过；
- 时间外推 split 与 embargo 审计通过；
- 同配置同输入可确定性复现；
- 中断后可以安全 resume；
- profile、manifest、split manifest 和 leakage audit 完整；
- 真实数据、序列号和标签未进入 Git 或日志；
- 与用户已有尝试的关键样本计数或结果差异有解释。

### 11.2 知识注入

- 知识包通过现有 loader 校验；
- 来源可追踪，无伪造论文或结果；
- 用户已有代码和结果被分析并正确标注证据等级；
- 主题覆盖第 8.3 节；
- 检索测试通过；
- `knowledge.enabled: true` 只表示知识层就绪，文档没有夸大 evaluator 状态。

### 11.3 回归

- HDD 受保护文件零改动；
- HDD 核心测试通过；
- 通用引擎没有 SmartMem 硬编码；
- 本地工作区只包含预期代码和文档改动；
- PR 描述包含测试证据、未完成项和下一阶段入口。

---

## 12. 提交拆分建议

新的 AI 不应一次提交所有内容。推荐顺序：

1. `docs(smartmem): record verified input contract and existing attempt`
2. `feat(data): add generic event schema and temporal split`
3. `feat(smartmem): implement chunked sample preparation`
4. `test(smartmem): add leakage and deterministic fixtures`
5. `feat(knowledge): add sourced SmartMem knowledge pack`
6. `feat(skill): add reusable event-data preparation skill`
7. `docs(smartmem): document local workflow and phase-1 acceptance`

每次提交前运行对应小测试。最后运行全量测试。不要把真实转换产物加入提交。

---

## 13. 服务器隔离验证与结果保护

本节仅在本地分支完成、代码审查通过、用户明确要求服务器测试后执行。

### 13.1 永久保护的现有路径

下列目录是原有代码、数据和结果，禁止覆盖、删除、移动、清理、原地升级或写入新实验：

```text
/home/hcf/nas_hcf_data/faultevolve
/home/hcf/faultevolve
```

禁止：

```bash
git pull                         # 在旧代码目录内
git checkout                     # 在旧代码目录内切版本
rsync --delete                   # 指向旧目录
cp -r new/* old/                 # 覆盖旧目录
rm -rf                           # 对任何上述父目录
```

### 13.2 新目录策略

首选在 NAS 根目录下创建与原目录平级的新目录：

```text
/home/hcf/nas_hcf_data/faultevolve_smartmem_<YYYYMMDD_HHMMSS>/
├── code/
├── data/
├── artifacts/
├── runs/
└── logs/
```

如果没有权限，回退到：

```text
/home/hcf/faultevolve_smartmem_<YYYYMMDD_HHMMSS>/
├── code/
├── data/
├── artifacts/
├── runs/
└── logs/
```

创建前必须：

1. `readlink -f` 解析最终绝对路径；
2. 确认目标不存在；
3. 确认目标不是两个受保护目录，也不在其内部；
4. `df -h` 检查空间；
5. 记录新目录到当次验证报告。

原始数据如果只能位于旧目录，使用只读符号链接或只读路径参数，不复制、不移动、不修改。创建链接前向用户确认准确源路径。

### 13.3 SSH 与跳板机

不能假设当前 AI 与用户处于相同网络。服务器阶段开始前，必须要求用户提供可执行的跳板说明，例如：

```sshconfig
Host <jump-alias>
  HostName <jump-host>
  User <jump-user>
  Port <jump-port>

Host <target-alias>
  HostName <target-host>
  User hcf
  ProxyJump <jump-alias>
```

若用户使用反向端口转发，必须提供隧道启动方法和目标端口。AI 只能保存非敏感 alias、用户、Host、Port 和路径；不得保存密码。

### 13.4 Conda 环境

服务器验证统一使用：

```bash
conda activate yolo26
```

已知 `yolo26` 可能使用 Python 3.11，而项目声明 Python 3.12。不能直接假设兼容。新目录创建后先执行：

```bash
which python
python --version
python -m pip --version
python -c "import pandas, numpy, sklearn; print('core imports ok')"
python -c "import pyarrow; print(pyarrow.__version__)"
```

缺依赖时先报告，不修改现有 `yolo26`，除非用户明确允许。优先在新目录创建派生环境或使用 `python -m pip install --target <new-dir>/pylibs`，并记录依赖；不得破坏共享环境。

### 13.5 新代码部署

只允许以下方式之一：

1. 在新 `code/` 中从远程 clone 新分支；
2. 将本地已审查 commit 打包后解压到新 `code/`；
3. 从新建的独立仓库创建 `git worktree`。禁止以两个旧目录内的仓库为源，因为这会修改其 `.git/worktrees` 元数据。

部署后核验：

```bash
git status --short
git branch --show-current
git rev-parse HEAD
```

必须与本地审查过的 commit 完全一致。

### 13.6 服务器测试顺序

1. 环境与磁盘只读检查；
2. 新目录权限测试；
3. 单元测试；
4. 全量离线测试；
5. `--profile-only --max-files 2`；
6. 小规模真实转换；
7. 用户确认后再扩大数据范围；
8. 生成只读结果报告。

所有结果写入新目录的 `runs/`、`artifacts/`、`logs/`。不得把输出写进两个旧目录。

### 13.7 服务器验收报告

报告至少包含：

- 跳板与目标 alias，不含密码；
- 新代码目录和新结果目录；
- commit；
- `yolo26` 的 Python 与依赖版本；
- 测试命令与通过数；
- 数据 manifest 哈希；
- 小规模处理的文件数、事件数、样本数、正负比例；
- 时间边界与 leakage audit；
- 耗时、峰值内存、输出大小；
- 与用户已有结果的差异；
- 明确声明两个旧目录未被修改。

---

## 14. 后续阶段入口

第一阶段完成后，下一阶段才讨论：

1. SmartMem `problem.md` 和候选 CLI 契约；
2. 本地 evaluator 与官方 F1 复现；
3. 初始 LightGBM 程序；
4. `SmartMemAdapter` 从 stub 升级为完整 `TaskAdapter`；
5. 错例画像、知识检索关键词和目标说明；
6. mock 进化；
7. 小轮真实进化；
8. 与用户已有方法的公平比较；
9. 是否生成 Codabench 格式 submission，仅生成文件，不自动上传。

进入下一阶段的硬门槛：第一阶段所有数据边界测试通过，真实小样本转换成功，用户确认数据契约，且现有结果已完成可追踪的参考分析。

---

## 15. 新 AI 的最终检查清单

开始前：

- [ ] 已读根目录 `AGENTS.md` 和四份指定文档；
- [ ] 已取得用户的原始数据路径与格式；
- [ ] 已取得已有代码路径或链接；
- [ ] 已取得已有测试结果及其口径；
- [ ] 已确认指标；无用户定义时使用官方 F1；
- [ ] 已记录本地基线 commit 和测试状态；
- [ ] 已从最新 main 创建新分支。

实现中：

- [ ] 通用事件模块无 SmartMem 硬编码；
- [ ] SmartMem adapter 只做领域映射；
- [ ] 标签边界与时区有测试；
- [ ] 时间切分有 embargo；
- [ ] 大数据处理可分块、恢复、确定性复现；
- [ ] 日志不含真实序列号；
- [ ] 知识卡每张都有来源、适用条件和风险；
- [ ] 未修改 HDD 受保护内容。

交付前：

- [ ] 小测试和全量测试均已报告；
- [ ] Windows 平台限制没有被隐藏；
- [ ] 真实数据未进入 Git；
- [ ] 文档未声称 evaluator/进化已经完成；
- [ ] PR 按提交拆分建议组织；
- [ ] 用户审查通过后才进入服务器阶段。

服务器阶段：

- [ ] 用户提供了跳板机说明；
- [ ] 使用 `yolo26`，并记录实际 Python 版本；
- [ ] 新目录位于两个旧目录之外；
- [ ] 两个旧目录未被覆盖或写入；
- [ ] 结果只写新 `runs/artifacts/logs`；
- [ ] 服务器报告包含 commit、manifest、测试和资源数据。

## 16. 接口消歧与第二版衔接（2026-10-03）

以下规定补充并纠正前文可能被误解的部分，两个 TODO 和第二版均须遵守。

### 16.1 已有代码是参考证据，不自动成为正式协议

用户原有切分、指标和代码都应独立记录。正式新切分优先级为用户明确确认的时间边界，然后是第 6 节时间外推建议。原有切分不符合防泄漏要求时，只保留为历史参考；不得因其存在而覆盖正式规则。不能比较不同 split、采样或评分协议的 F1 后宣称提升。

### 16.2 采样时刻不能早于所使用事件

`anchor_strategy=event` 时，先对事件时间按采样频率向上取整并去重生成候选预测时刻，再按 `event_time <= prediction_time` 筛选历史。禁止先向下取整再把同一时间桶内所有事件算入特征。

其他策略必须也保证事件时间不晚于预测时刻。每单元样本上限只用于训练集或明确标注的快速 fixture；正式 dev/val 保留固定、完整的预测时刻网格，不能依据标签或故障距离抽样。避免以 ticket 为锚点定义样本，这会让正负样本的构造携带标签。

### 16.3 删失与故障后数据

无故障 ticket 不能直接等同于所有时刻都健康。只有 `prediction_time + lead + horizon <= outcome_observed_until`，且 ticket 覆盖该区间时，才可标为负样本。已确认标签窗内发生故障的样本可标正。尾部未完成随访的样本标记 `censored` 并从监督训练/评分中移除。

`outcome_observed_until` 必须来自用户确认的 ticket 覆盖截止或数据说明，不能简单以某 DIMM 最后一条错误日志推断其存活时间。没有足够信息时先交付 profile 与待确认清单，不能编造负标签。首次故障及之后的数据默认删除；多故障必须有用户提供的更换/重置身份规则，否则只使用首故障。

### 16.4 通用接口的完整参数

第 5 节签名为设计草案，实现时使用下列明确接口并记录变更：

```python
def build_labeled_samples(
    events: pd.DataFrame,
    failures: pd.DataFrame,
    schema: CanonicalEventSchema,
    config: EventWindowConfig,
    *,
    failure_unit_col: str,
    failure_time_col: str,
    outcome_observed_until: pd.Timestamp,
) -> pd.DataFrame:
    ...
```

`split_key` 在切分步骤填入，采样步骤先不赋 split；`sample_id` 使用显式算法版本加单元与 UTC 预测时刻生成稳定 SHA256，禁止使用 Python `hash()`。local sample/label/index 文件可以保存真实单元 ID 供 join；这些文件不进入日志、共享报告、Git 和 LLM 提示。数据分区保留必要身份信息不等同于允许将身份泄漏到报告。

### 16.5 冻结验证集与第二版评价接口

第一版 dev 用于后续进化，val 留作最后裁决。第二版 `SmartMemAdapter.evaluate()` 默认只评价 dev。val 不参与树选择、卡片信誉、反思或报告后的再次调参。

官方 F1 的“指标名称”已确认，但重复告警、故障计数和 A/B 汇总细则仍需评分源码或用户定义核实。不得把普通逐样本 F1 写成已复现的官方事件 F1。第一版记录 `metric_spec_status=verified|provisional`，第二版再冻结完整计分协议。

### 16.6 测试迁移与路径约束

第一版允许把 `tests/test_dataset_stubs.py` 中断言 SmartMem 聚合/prepare 抛 `NotImplementedError` 的用例替换为正常输出与非法输入测试；保留 SmartMem evaluator 仍未实现的测试。SSD stub 测试不改，HDD 受保护测试不改，不删测试掩盖错误。第二版再迁移 evaluator stub 用例。

NAS 不能存放 WAL SQLite 数据库：服务器可将 code/data/artifacts 放新 NAS 目录，但 `FE_RUNS_DIR` 必须位于新建的本地磁盘目录，必要时额外创建 `/home/hcf/faultevolve_smartmem_<唯一标识>/runs`。以挂载类型实测为准，不能仅凭路径前缀判断。

`yolo26` 是默认执行环境，不擅自改用其他 Conda 环境。若 Python 版本或缺依赖导致不可运行，记录具体冲突和最小补救方案；只有用户明确接受后才安装依赖或采用派生环境。禁止用 pip 忽略 Python 要求或无测试地降低项目要求。
