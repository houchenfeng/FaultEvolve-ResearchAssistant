# SmartMem 第二版需求：内存故障预测完整闭环

> 日期：2026-10-03。类型：待实现需求，本文中的命令和接口除明确标注“现有”外均为开发目标。
>
> 前置：[第一版需求](SMARTMEM_PHASE1_IMPL_PLAN.md) 验收完成。执行顺序见 [第二版 TODO](SMARTMEM_PHASE2_TODO.md)。
>
> “完整实现”定义：用户数据接入 → 时间切分 → 内存知识包 → 初始算法 → 本地可信评价 → 现有树状进化 → 恢复与制品 → 最终冻结集报告 → 服务器新目录验证 → 提交格式导出。

## 1. 范围与依赖

第二版复用第一版通用事件数据处理模块、manifest 与知识卡，不重写另一套数据流水线。复用 FaultEvolve 现有 `EvolutionEngine`、`TaskAdapter`、SQLite Store、算子、预算和反思接口。

| 功能 | 第二版要求 |
|---|---|
| 数据处理/知识包 | 复用 V1，补全候选可见数据快照 |
| Task 四件套 | 新建 SmartMem 的 evaluator/init/problem/prompt |
| 评分 | 实现并冻结可审计的事件告警评分 |
| 候选生成和进化 | 接入现有本地引擎，支持知识检索和修复 |
| 初始算法 | 有确定性基线；复用用户已有实现需留来源与协议 |
| 错例画像 | 内存专用聚合画像，供反思和知识检索 |
| 多目标/算子 | 通过已有协议接入，保守默认配置 |
| Mock | 使用内存候选和真实 toy evaluator |
| 恢复/报告 | 可追溯 commit、数据、评分、配置及成本 |
| 官方格式 | 导出告警 CSV，校验列与身份，不自动提交 |
| 服务器 | 新代码目录、新结果目录，使用 yolo26 与用户跳板配置 |
| KD1/KD2 | 研究扩展，不作为核心闭环验收；默认关闭 |
| Web UI / FastAPI 控制面 | 不属于这版 SmartMem 适配范围 |

不要求为“完整实现”重建原总体设计尚未实现的云端 API，也不要求改造所有知识发现算法。若后续加入 KD，必须处理同一 DIMM 重复预测的统计相关性，不能把 sample 当独立硬件单元。

## 2. 开始前用户需提供的内容

开发 AI 必须先取得或确认：

1. V1 已验收 commit、数据 contract、manifest、split manifest 和知识包；
2. 原始数据本地目录或用户提供的下载链接及下载说明；AI 不代替用户登录数据平台；
3. 用户已有内存代码路径/链接、运行入口、依赖与代码版本；
4. 用户已有结果、预测文件位置、评分源码或评分定义，以及使用的数据阶段；
5. 时间单位、时区、ticket 覆盖期、更换 DIMM 规则；
6. 评价指标：用户没有定义时查官方来源；名称 F1 不等于完整评分实现；
7. 目标阶段 Phase 1/Phase 2，硬件类型字段的真实含义；
8. 本地/服务器 CPU、内存、磁盘、单次评价超时；
9. 初次真实进化的迭代数、Token 上限、墙钟上限；缺失时只做离线验证；
10. 服务器跳板机说明、目标 Host/用户/端口、可读数据路径和新工作根目录。

用户没有现成指标定义时，官方来源为 [SmartMem 说明](https://hwcloud-ras.github.io/SmartMem.github.io/) 和 [SmartHW](https://github.com/hwcloud-RAS/SmartHW)。官方说明给出 15 分钟 lead、lead 之后 7 天预测窗和 F1；完整重复告警计数要另外核实评分代码。

用户信息未齐时可以开发 toy 实现和独立测试；真实数据评分、付费进化与服务器阶段依赖相应输入。报告中用 `pending` 标缺项，不以猜测填数。

## 3. 数据与评估集合角色

V1 生成的三段数据在 V2 中固定用途：

| 集合 | 候选是否可见标签 | 用途 |
|---|---|---|
| train | 是 | 模型拟合，训练内部时序交叉验证、阈值选择 |
| dev | 否 | 本地 evaluator 评分，进化选择、反思和经验反馈 |
| val | 否 | 选定最优代码后一次最终时间外推裁决 |
| 官方 test | 无官方隐藏标签 | 如用户要求，仅推理/导出，不进行调参 |
| cold-unit audit | 否 | 可选新单元泛化报告，身份与训练单元隔离 |

dev 经进化反复评分会被间接优化，不能再称完全独立验证集。最终 val 指标不写入 node 分数，不用于重新选节点或调整阈值。若最终裁决后要继续开发，必须登记 val 已被使用并制定新的未查看验证区间。

用户历史结果只有在时间切分、采样覆盖、评分协议、权重与数据版本一致时才能直接比较。无法对齐时并列展示并标记 `not_comparable`。

## 4. 候选可见数据与 CLI

### 4.1 从 V1 数据生成只读快照

新增 `benchmark/smartmem/build_candidate_data.py`。输入是 V1 分区目录，输出是一个全新的候选数据快照，不修改 V1 产物。候选不依赖目录遍历，公开文件清单固定：

```text
<candidate-data>/public/
  candidate_manifest.json
  train_features.parquet
  train_labels.parquet
  train_index.parquet
  dev_features.parquet
  dev_index.parquet
  val_features.parquet
  val_index.parquet

<candidate-data>/scoring-private/
  dev_outcomes.parquet
  dev_coverage.parquet
  val_outcomes.parquet
  val_coverage.parquet
  score_manifest.json
```

说明：这些是本地新建 SmartMem 文件，不是 HDD `holdout*`；仍不得向候选、LLM、Git 暴露 scoring-private 内容。必要真实 ID 只保留在本地数据与导出中。

`candidate_manifest.json` 只包含 schema 版本、允许文件名、特征列名、lead/horizon、时区、anchor 策略和采样配置。它不得包含 dev/val 标签数、故障时间、ticket 来源路径。模型只按 allowlist 取特征，`sample_id/unit_id/prediction_time/split/label` 不能成为特征。

features 每行包含唯一 `sample_id` 与特征，index 每行包含 `sample_id,unit_id,prediction_time,serial_number_type`。train_labels 为 `sample_id,label`，只包括通过删失审计的样本。features、index、labels 必须使用 key join，不能假设行顺序一致。

核心版使用预计算特征，进化的范围为列选择、变换、模型、阈值、集成和告警策略。修改原始事件聚合规则需重新生成 manifest 和独立实验，不允许候选私自读取原始 ticket 或另一版本数据。

单文件只是候选 API，不要求一次全部读入内存；Parquet 可用 row groups。构建快照如触发内存/磁盘上限，应失败并给出估算，不能静默改采样。模型训练必须有记录过的可运行任务数据规模。

### 4.2 候选 CLI

```bash
python solution.py --data-dir <ABS_PUBLIC_SNAPSHOT> --split dev --out <ABS_PREDICTION_CSV>
```

`--split` 接受 `dev|val|test`；test 仅在快照确有用户提供的无标签 test 文件时可用。候选代码仍可带同接口的 toy fixture。

输出固定列：

```text
sample_id,score,alarm
```

每个 index 中 sample_id 恰好一行；无额外、重复、缺失 key。score 必须有限，alarm 必须为整数 0/1。score 用于诊断排序；alarm 才是事件评分输入。evaluator 自行将 sample_id join 到本地 index，候选不得伪造告警时刻或硬件类型。

禁止候选访问 scoring-private、原始 ticket、源仓库、外部网络、目录遍历、工作目录、子进程和环境密钥。不得删改 `common/codecheck.py` 的已有防护来迁就候选代码。

## 5. 计分协议与不可虚报边界

### 5.1 冻结 MetricSpec

新增 `benchmark/smartmem/metric_spec.yaml` 和 `src/faultevolve/tasks/smartmem_metrics.py`。

```python
@dataclass(frozen=True)
class MetricSpec:
    protocol_id: str
    status: Literal["verified", "local_provisional"]
    lead_minutes: int
    horizon_days: int
    matching_rule: str
    duplicate_alarm_rule: str
    type_aggregation: str
    zero_division: int
    score_scale: float
    reference_source: str
    reference_hash: str | None


def score_alerts(
    predictions: pd.DataFrame,
    index: pd.DataFrame,
    outcomes: pd.DataFrame,
    coverage: pd.DataFrame,
    spec: MetricSpec,
) -> dict[str, object]:
    ...
```

所有 `matching_rule/duplicate_alarm_rule/type_aggregation` 必须来自用户评分代码或已核实官方 scorer。取得源码时记录 commit/hash 与许可证，自己计算的若干边界 case 与参考 scorer 输出逐项比较。

没有参考 scorer 时，提供下列明确本地协议供 fixture 和开发：

- 对通过随访覆盖审计的告警与首次故障做确定性一对一时间匹配；
- 告警时间 `t` 满足故障时间在 `[t+lead,t+lead+horizon]` 才允许匹配；
- 按时间及稳定 key 排序，用时间匹配实现最大合法匹配；
- 一个故障最多计一个 TP，一个告警最多匹配一个故障；
- 未匹配告警计 FP，未被任何合法告警匹配的合格故障计 FN；
- 重复告警不会增加 TP，重复未匹配告警按 FP 计；
- 不具完整随访的未匹配告警标 censored，从计分排除并报告计数；
- 合格故障由独立 coverage/at-risk 清单确定，即使该 DIMM 没有候选样本也可能构成 FN，不能只在有预测的单元中取分母；
- 第一版默认首故障截断；多故障身份未明确时拒绝多故障正式评分；
- `F1 = 2TP/(2TP+FP+FN)`，分母为 0 时为 0；按类型报告，整体以 micro 汇总作为本地暂定口径。

该规则标 `local_provisional`，名称使用 `local_event_f1`，禁止声称是 Codabench 复现分。完整官方一致性验收要求 `verified`；如用户选择独立本地协议，名称、版本和差异必须在报告明确。

### 5.2 主分与辅助分

引擎的 score 采用百分制，避免沿用默认 0.5 噪声阈值时对 0–1 F1 不敏感：

```text
combined_score = 100 * event_f1
metric.event_f1 = event_f1                 # 0..1
metric.f1 = event_f1                       # 兼容现有提示/反思
metric.sample_f1 = ordinary sample F1      # 仅诊断
metric.score_scale = 100
metric.score_name = event_f1_pct
```

目标分使用百分制，如用户目标 F1 为 0.30，配置 target_score 为 30；不能照搬 HDD 33.7。时间成本单独报告，不加 ROS 的时间惩罚。`auprc`、sample recall 等普通逐样本指标必须标清统计单元。

若用户正式指标不是事件 F1，要求以显式 MetricSpec 改合同并补测试；不能由模型自行更换评分指标。

### 5.3 Bootstrap 与噪声

在 DIMM 单元层分组重采样，保留每个单元的完整告警、故障与覆盖记录，每次重算事件计分。禁止对高度相关的时间样本逐行 bootstrap。

结果写 `event_f1_boot_std`（0..1），兼容键 `f1_boot_std` 指向同值，注明 unit。adapter 计算：

```text
noise_delta = max(min_noise_delta, kappa * 100 * event_f1_boot_std)
```

`min_noise_delta` 以百分制点数计。bootstrap 用显式 seed，空/小样本明确返回诊断。主 score 不用 bootstrap 下分位替换；统计用于不确定性和选择，不篡改官方指标。

## 6. evaluator 运行规范

在 SmartMem 任务中新建：

```python
def static_check(code: str) -> str:
    ...


def evaluate(
    program_path: str,
    timeout: int = 900,
    split: str = "dev",
    *,
    data_root: str | None = None,
    seed: int = 20260926,
) -> dict[str, object]:
    ...
```

默认数据根通过 `SMARTMEM_DATA_ROOT` 获取。只能评价配置快照的指定 split。不得修改全局环境变量来给并发 worker 切 data root；adapter 显式传 `data_root`。

执行顺序：语法/静态检查 → 校验 manifest 和评分版本 → 构建候选可见临时目录 → 执行候选 → 校验预测 → key join → 评分与 bootstrap → 生成脱敏结果 → 清理当前临时目录。

返回与既有 `EvalResult` 一致：

```json
{
  "validity": 1.0,
  "combined_score": 25.0,
  "cost_time": 1.0,
  "error_info": "",
  "metric": {
    "event_f1": 0.25,
    "f1": 0.25,
    "precision": 0.25,
    "recall": 0.25,
    "f1_boot_std": 0.01,
    "protocol_id": "local-example-v1",
    "metric_status": "local_provisional",
    "split": "dev",
    "score_scale": 100
  }
}
```

示例数字是结构说明，不是项目结果。任何候选错误返回 validity=0、score=0 和脱敏 error_info，不能把运行异常记成合法低分。

子进程执行器使用 `sys.executable` 和 argv 列表，设置超时及 stdout/stderr 上限，终止超时时需处理整个候选进程组。Linux 下用用户限制的内存/CPU 配额。候选环境只传必要变量，删除 LLM/SSH 凭证；临时目录位于新 runtime 根。

静态检查和临时目录不能作为安全沙箱的充分证据。真实 LLM 生成代码要在无网络、只读数据、不可访问 scoring-private/旧目录的容器或受约束 runner 中执行。未有该运行环境时报告 `sandbox_status=limited`，只执行审查过的 fixture/基线，不做不受控真实进化。

## 7. SmartMemAdapter 具体实现

将继承从 `StubDatasetAdapter` 改为 `FamouAdapter`，保持 registry 的 `smartmem` 别名；完整任务就绪后从 `STUB_ADAPTER_DOCS` 移除 SmartMem，保留 SSD。

实现现有核心接口：

```python
load_task(task_dir: Path) -> TaskSpec
evaluate(code: str, task_spec: TaskSpec, timeout: int = 900) -> EvalResult
get_noise_delta(eval_result: EvalResult) -> float
static_check(code: str, task_spec: TaskSpec) -> str
constraints(task_spec: TaskSpec) -> str
context_keywords(code: str) -> list[str]
api_notes() -> str
data_status(task_dir: Path) -> DataStatus
```

额外使用已有能力检测接口：

```python
data_schema() -> str
edit_guidance() -> str
objective_brief(task_spec: TaskSpec) -> str
objectives() -> list[str]                    # ["auprc"] 或明确适用排序指标
threshold_objectives() -> list[str]          # ["event_f1"]
noise_metric() -> str                        # "event_f1_boot_std"
analyze(code: str, task_spec: TaskSpec, timeout: int) -> dict[str, object]
```

不要让 adapter 宣称尚未支持的 `DiscoveryDataProvider`。不修改既有 Protocol 的必需方法；新增通用可选协议必须保留所有旧 adapter 兼容。

`evaluate()` 显式调用 evaluator(split="dev", data_root=...)，不是直接继承默认方法后偷偷改环境。`data_status()` 只检查文件存在和 manifest 元信息，不读取私有标签。缺数据保持可读错误。

领域关键词包含 dram/ecc/mcelog/temporal/spatial/bank/row/parity；不从模型代码解析真实单元 ID。约束提示提供 allowlist 文件、特征列、主分、时区、固定样本时刻、禁止未来信息与目录越界。

## 8. 初始程序、smoke 与画像

### 8.1 init.py

优先将用户已有代码的可靠部分适配为自包含候选。没有可用实现时提供 LightGBM 或逻辑回归基线，不声称已跑出用户历史指标。

训练只使用 train 的标签。阈值通过训练内部按时间分段的校准区间选择，留 lead+horizon gap；编码/归一化仅在更早训练段拟合。候选没有 dev 标签，不能在 dev 或 val 上择阈值。配置固定 seed、线程数和轮数，未知类别有明确处理。

基线不得导入源仓库的任务专用函数；必须能在候选临时目录独立执行。模型策略及特征选择可以用现有知识卡解释并记录 source_id。

### 8.2 smoke

实现与引擎已有签名一致的 `build_smoke_data_dir`、`smoke_test`、`cleanup_smoke_data`。抽完整硬件单元及其时间线，不随机抽行；由可信 runner 抽样，候选不读 dev 标签。

smoke 的 score 不入 node 分数或 leaderboard；它只检查执行、输出覆盖和资源。缓存 key 包含数据 hash、采样 seed、比例和评分版本。完成时只清理本次创建的临时目录。

### 8.3 analyze

按 serial type、匿名型号组、错误稀疏程度、空间聚集和 lead 区间报告 FN/FP 聚合。小于 10 单元的组抑制，不输出真实序列号和 ticket 时间。

保留引擎已有结构：

```json
{"fn_groups": [{"dimension": "serial_type", "value": "A", "n": 12,
  "share": 0.5, "group_recall": 0.25}], "fp_groups": [], "summary": "..."}
```

dev 内事件画像由可信 evaluator 生成；图片/提示不得包含私有原始数据。analyze 不能读取 val 或再次择阈值。失败画像只记诊断，不改 score。若重复执行成本高，可使用有代码 hash 的只读评估缓存，不能串用不同候选结果。

## 9. 引擎、Mock 和可选功能

现有 `run_local_evolution(..., adapter=...)` 可注入 adapter；`EvolutionEngine` 可注入 LLM。优先利用这些入口。

现有 `--mock` 的默认候选是 HDD 格式。新增通用 replay mock 入口，例如可选 `--mock-responses <JSON>` 或同等通用工厂注入：按顺序返回预录制内存候选及反思。只在 `--mock` 时允许，不添加 `if adapter == smartmem` 到 cloud 层。mock 返回真正可运行候选，评分仍由 toy evaluator 产生。

SmartMem 默认配置：普通 UCT、scalar value、refine/inject 可用、知识开启、smoke 开启、画像验证后开启、Jev 关闭、crossover/KD 关闭、target_score 未设置。可以先关闭 bandit，验收核心后开启 recall_focus/threshold_calibrate 并测试字段兼容。

Jev 可选 fail-open 行为沿用原实现；不能改变 MetricSpec 或写 score。是否启用由运行配置记录，不硬编码密钥 env。

KD1/KD2 如需后续启用，增加 sample 到 unit 的明确映射和按 DIMM 分组的统计接口，重检 bootstrap/阴性对照/环境划分。`baseline_lag_rows=14` 不是 14 天事件窗口，不得直接照搬。该扩展需要单独需求与验收。

## 10. 恢复、最终裁决和报告

### 10.1 运行指纹

每次运行生成 `run_fingerprint.json`：代码 commit、候选数据/知识包/MetricSpec hash、种子、split 边界、依赖版本、资源限额、score scale、sandbox status。报告匿名摘要，不包含真实事件与原始路径。

resume 前逐项校验；数据、metric 或代码发生不兼容变更时拒绝恢复并提示创建新 run。不默默沿用旧 best_score。写报告使用临时文件和原子重命名，同一实验更新可恢复，但最终报告不得覆盖旧实验的文件。

### 10.2 最终裁决 CLI

新增任务脚本，保留现有 `fe report`（它目前侧重 discovery/tournament）：

```bash
python benchmark/smartmem/finalize.py \
  --db <NEW_LOCAL_RUNS>/<experiment_id>/fe.db \
  --artifacts <NEW_ARTIFACTS>/<experiment_id> \
  --data-root <NEW_CANDIDATE_DATA> \
  --out-dir <NEW_FINAL_DIRECTORY>
```

读取 dev 分数选出的 best_node_id，验证程序 hash，固定代码在 val 评价；程序 hash、data hash、MetricSpec hash 组成 finalize key。同 key 重跑返回已有结果，不反复选模型；新 key 创建新目录。val 分数写独立 `final_evaluation.json`，不能回写 node/evaluation 表参与选择。

报告包括 baseline dev、best dev、baseline val、best val、绝对/相对提升、统计区间、协议状态、precision/recall/F1、TP/FP/FN、按类型指标、候选有效率、轮次、Token 分阶段统计、墙钟、评估时间、知识卡提供/采纳、复现命令和版本指纹。

baseline val 与 best val 是预注册的两个固定程序，不能比较所有候选的 val 后另选最优。没有真实执行的字段写 `not_run`，不拿 mock 数字填真实表。

### 10.3 官方格式导出

新增 `export_submission.py`，只把 alarm=1 的 sample_id join 到用户提供的 test index 后输出 `sn_name,prediction_timestamp,serial_number_type`。样本时间和类型来自可信 index，明确时区及时间格式；不要把完整 score 表直接当官方 submission。

重复告警处理与已确认 MetricSpec 一致；未确认时不擅自施加 cooldown。只生成到新目录，固定输出已存在时拒绝覆盖。不会自动登录或上传 Codabench。

## 11. 测试与验收等级

| 等级 | 必须提供的证据 |
|---|---|
| L0 离线 | toy evaluator、adapter、init、mock 多轮与知识采纳通过 |
| L1 数据 | 用户真实小样本处理、切分、删失与泄漏审计通过 |
| L2 协议 | 用户/官方 scorer parity 或用户明确选择独立本地协议 |
| L3 完整运行 | 新服务器目录，真实 baseline、进化、恢复、val 裁决、报告 |

L0 通过不能宣称 L3 完成。性能验收目标由用户基线决定，不能凭空设 F1 门槛或保证提升；即使未超过基线，完整运行与真实原因报告仍必须交付。

必须测试：

- 评分边界 15min/7d、一个故障多个告警、一个告警多个故障、空告警、空故障、类型汇总、未覆盖单元；
- 覆盖不足、身份重置、时区和故障后样本；
- 缺/重复/额外 sample_id、NaN/Inf score、非法 alarm、非零退出、超时与路径越界；
- adapter 协议、data_root 并发无全局串用、完整 toy CLI；
- smoke 分数不入树、图片/画像不改变评价分、private 不出提示；
- mock 确实生成内存数据合同程序，且只调用真实本地 scorer；
- 卡片被提供/声明采纳、统计反馈更新、无 HDD 卡硬编码；
- resume 指纹校验、finalize 幂等、不回写 val score；
- SQLite DB、run summary、Token 账本一致；
- 原 HDD 受保护文件 hash 和旧 adapter 回归。

## 12. 服务器部署需求

严格复用 V1 保护约束：禁止写入或覆盖 `/home/hcf/nas_hcf_data/faultevolve` 与 `/home/hcf/faultevolve`，包括其 Git 元数据和历史结果。

新 NAS 根：`/home/hcf/nas_hcf_data/faultevolve_smartmem_v2_<唯一标识>`；无权限时用 `/home/hcf/faultevolve_smartmem_v2_<唯一标识>`。当前版本固定 commit，新结果目录独立命名。

SQLite 数据库位于经过挂载检查的新本地磁盘路径，例如 `/home/hcf/faultevolve_smartmem_v2_<唯一标识>/runs`；NAS 只放 code/data/artifacts/logs。不能在 CIFS/NFS 上用 WAL DB，也不能调用旧工作区 git worktree。

用户须提供跳板机规则；本机 SSH alias 只是连接参考，不能保证下一位 AI 的网络可达。环境用 `yolo26`。已观察到 Python 3.11.15，与当前项目 `requires-python>=3.12` 不一致：先验证真实代码要求、打包要求和依赖。不能执行 `pip install -e .` 后忽视版本错误。若决定支持 3.11，需用户认可的单独兼容改动及 3.11/3.12 测试；不能未经测试改声明。依赖安装方案应保护共享环境。

真实候选执行时对旧目录不可写且不可任意读取；使用新 runner 资源配置。新目录的临时文件、模型、缓存、日志、runs 均显式指定，避免隐式 `.fe` 写回旧仓库。

## 13. 文件改动地图与交付

新增：SmartMem 四件套、metric_spec.yaml、候选快照构建器、finalize.py、export_submission.py、smartmem_metrics.py、运行指纹与报告 helper、toy fixture 和第二版测试。

修改：SmartMemAdapter、registry 的 stub 清单、SmartMem evolve.yaml/README/data contract；通用 mock replay 入口（如需要）、泛化数据/进化 Skill 的 SmartMem 状态；stub 测试迁移。

保留：HDD 四件套与 data、现有评分口径、现有用户运行制品、SSD stub、既有 CLI 的兼容性。

第一版 PR 必须先合并或通过固定 commit 成为第二版基线。第二版分支建议 `feat/smartmem-full-loop`。最终交付包含本地测试证据、协议说明、用户旧结果可比性、服务器新目录清单、真实运行报告和未完成扩展。
