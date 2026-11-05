# GEN_IMPL_PLAN：泛化 PR（TODO 步骤 7，仅硬盘数据；Backblaze 真实 + SSD/内存 stub）

基线：main = 112b73a（433 tests）。分支 `cursor/dataset-generalization-<xxxx>-e0a1`。本 PR 不做真实服务器运行。
硬约束：`benchmark/hdd_mvp/**`（含 evaluator/init/problem/prompt/prepare_data/data/knowledge）字节不变；
不读 `eval_only/test/holdout*`；新功能默认关闭；不破坏 `TaskAdapter` 协议；测试全离线；总测试数 ≥ 433，不删不弱化。

## 0. 已核实的现状与坑（编码前必读）
1. `create_benchmark_adapter(config)`（`tasks/__init__.py`）写死 `HDDAdapter`；`run_local_evolution(adapter=None)`、`cli evolve/discover/checkup` 都走它。
   `cli.py:analyze`（约 488-501 行）直接 `from ...hdd_adapter import HDDAdapter` 并构造，需改走注册表。
2. `evolve.yaml` 没有 `task` 段；`EvolveConfig.from_dict` 逐段手工解析，新段必须在 `from_dict` 里加分支，否则被静默忽略。
3. `HDDAdapter._get_data_dir` 与 `hdd_mvp/evaluator.py` 都读 `HDD_BENCH_DATA_ROOT`（子目录 `public/`），否则回退 `task_dir/data`。
   Backblaze 任务复用同一 evaluator 副本，所以**只能沿用该环境变量**；同一 shell 里若为 hdd_mvp 设了它，会让 Backblaze 静默读错数据。
   对策：`fe doctor` 打印解析后的数据目录（见 §3.4），文档强调“每个任务运行前 export 或 unset”。
4. `build_smoke_data_dir` 用 `line.split(",")[1]` 取序列号，假定 `serial_number` 是 history 第 2 列（`date,serial_number,...`）；
   `analyze/discovery_frames` 假定 `train_history.csv.gz` + `train_labels.csv(serial_number,model,cutoff_date,label,weight)` + `date` 列。
   → 所有新任务的**输出接口必须与 hdd_mvp 完全同构**（同文件名、同列、`date,serial_number` 为 history 前两列）。SSD 转换器把 `disk_id→serial_number`，DRAM 例外（见 §6，不套用）。
5. `cloud/llm.py` 的 MockLLM 产出的是 hdd 接口代码（读 `train_history.csv.gz`、`serial_number`）；因此 `--mock` 只对 hdd 同构任务（hdd_mvp/Backblaze）有意义，stub 不可 mock 运行（文档写明）。
6. `common/precheck.py` 有 `serial_number` 专用正则/修复提示、`common/textutil.vendor_from_model` 含 HDD 厂商前缀：**本 PR 不改**（同构接口下仍正确），
   只在新增的任务无关测试里把它们列入 allowlist（§7 `test_engine_sources_task_agnostic`），并在 §9 记为已知限制。
7. `KnowledgeConfig.dir` 是 `task_dir/<dir>`，知识卡晋升会写该目录 → Backblaze 必须用**自己的副本**，不能指向 hdd_mvp/knowledge（否则改到受保护文件）。
8. hdd_mvp 的 `data/` 已入库；新数据目录一律 `.gitignore`，绝不提交大文件。

## 1. 文件清单（新建 N / 修改 M）
```
M src/faultevolve/config.py                 + TaskConfig, EvolveConfig.task, from_dict 分支
N src/faultevolve/tasks/registry.py         适配器注册表/解析/创建
M src/faultevolve/tasks/__init__.py         create_benchmark_adapter 改为薄封装；导出新名字
M src/faultevolve/tasks/protocol.py         + DataStatus, DataStatusProvider（可选协议，追加在文件末尾）
M src/faultevolve/tasks/hdd_adapter.py      + HDDAdapter.data_status()（只读，不改现有方法）
N src/faultevolve/tasks/backblaze_adapter.py
N src/faultevolve/tasks/stub_base.py
N src/faultevolve/tasks/ssd_alibaba_adapter.py
N src/faultevolve/tasks/smartmem_adapter.py
M src/faultevolve/cli.py                    analyze 走注册表；doctor 增加任务检查；evolve local 缺文件时提示 stub 文档
M .gitignore                                + benchmark/backblaze_hdd/data/  benchmark/ssd_alibaba/data/  benchmark/smartmem/data/  benchmark/*/raw/
N benchmark/backblaze_hdd/{evaluator.py,init.py,prompt.md,problem.md,README.md,evolve.yaml,prepare_data.py,download_data.py,knowledge/{cards.jsonl,sources.yaml,expert.md}}
N benchmark/ssd_alibaba/{README.md,evolve.yaml,prepare_data.py}          （stub 模板，无 evaluator）
N benchmark/smartmem/{README.md,evolve.yaml,prepare_data.py}             （stub 模板，无 evaluator）
N docs/datasets/{backblaze,alibaba_ssd,smartmem}.md ; M README.md ; N docs/plans/GEN_IMPL_PLAN.md（本文件）
N skill/fe-dataset-adapters/SKILL.md ; M skill/fe-evolve-manager/SKILL.md
N tests/test_adapter_registry.py, test_backblaze_prepare.py, test_backblaze_task.py, test_dataset_stubs.py,
  test_engine_task_agnostic.py, test_hdd_protected_files.py, test_doctor_task_checks.py   （+ tests/helpers_backblaze.py 造数据）
```

## 2. 配置与注册表
**config.py**
```python
class TaskConfig(BaseModel):
    adapter: str = "hdd"          # alias 或 "pkg.module:ClassName"
```
`EvolveConfig.task: TaskConfig = Field(default_factory=TaskConfig)`；`from_dict` 加 `if "task" in data: config.task = TaskConfig(**data["task"])`。
默认 `hdd` ⇒ 现有 evolve.yaml 行为逐字节不变。`with_overrides` 走 `model_dump()`/重建，确认 `task` 被保留（加断言测试）。

**tasks/registry.py**
```python
ADAPTER_ALIASES: dict[str, str] = {
  "hdd": "faultevolve.tasks.hdd_adapter:HDDAdapter",
  "famou": "faultevolve.tasks.famou_adapter:FamouAdapter",
  "backblaze": "faultevolve.tasks.backblaze_adapter:BackblazeAdapter",
  "alibaba_ssd": "faultevolve.tasks.ssd_alibaba_adapter:AlibabaSSDAdapter",
  "smartmem": "faultevolve.tasks.smartmem_adapter:SmartMemAdapter",
}
STUB_ADAPTER_DOCS: dict[str, str] = {"alibaba_ssd": "docs/datasets/alibaba_ssd.md", "smartmem": "docs/datasets/smartmem.md"}
def resolve_adapter_class(spec: str) -> type          # 别名或 "module:Class"（懒导入 importlib）；
    # 未知别名/无冒号 → ValueError(f"unknown task.adapter '{spec}'; aliases: {sorted(ALIASES)} or 'module:Class'")
    # ImportError/AttributeError → ValueError(同上前缀 + 原因，不含堆栈)
def create_adapter(config: EvolveConfig) -> TaskAdapter
    # cls = resolve_adapter_class(config.task.adapter)
    # 仅传 __init__ 签名里存在的参数：min_noise_delta=0.5, kappa=config.selection.kappa_noise,
    #   dev_late_fraction=config.analysis.dev_late_fraction, analysis_min_group_count=config.analysis.min_group_count
    #   （用 inspect.signature 过滤；FamouAdapter 只收 min_noise_delta）
def stub_doc_for(spec: str) -> str | None
```
`tasks/__init__.py`：`create_benchmark_adapter(config)` 保留名字，函数体 `return create_adapter(config)`（默认 hdd 时构造参数与旧实现完全一致：0.5 / kappa_noise / dev_late_fraction / min_group_count）。`run_local_evolution` 与 `cli` 其它调用点无需改（都走 create_benchmark_adapter）。
`cli.py:analyze`：`adapter = create_adapter(config)`；若 `not hasattr(adapter,"analyze")` → JSON `{"ok":false,"error_type":"NotSupported"}` 退出 1。

## 3. 协议扩展与 CLI
### 3.1 protocol.py（末尾追加，不动现有类）
```python
@dataclass
class DataStatus:
    ok: bool; data_dir: str; missing: list[str]; message: str
@runtime_checkable
class DataStatusProvider(Protocol):
    def data_status(self, task_dir: Path) -> DataStatus: ...
```
### 3.2 HDDAdapter.data_status(task_dir)
只做 `Path.exists()`，**不 open 任何 label/holdout 文件**：`d = self._get_data_dir(TaskSpec-like)`。因 `_get_data_dir` 需要 TaskSpec，构造最小 `TaskSpec(task_dir, "", "", "", task_dir/"evaluator.py")`。
缺失检查 `d/{train_history.csv.gz,train_labels.csv,val_history.csv.gz,val_index.csv}`；ok=全在。message：`"data dir <d>; missing: [...]"`；缺失时追加 `"run: python <task_dir>/prepare_data.py --help"`（仅当该文件存在）。
env 已设时 message 追加 `"(HDD_BENCH_DATA_ROOT=<value>)"`。
### 3.3 BackblazeAdapter(HDDAdapter)
只覆盖：`DATASET_NAME="backblaze_hdd"`；`data_status` 缺失提示指向 `benchmark/backblaze_hdd/prepare_data.py` 与 `docs/datasets/backblaze.md`。其余（constraints/api_notes/data_schema/analyze/smoke/discovery）全部继承——接口同构。
### 3.4 fe doctor（仅当传了 `--task-dir` 时追加检查，无 `--task-dir` 时输出与现在完全相同）
在现有检查之后追加，键名固定：
- `task_files`：`evaluator.py init.py problem.md prompt.md` 是否齐全；stub 目录缺 evaluator 时 ok=False，message 含 `docs/datasets/<x>.md`（用 `stub_doc_for`）。
- `task_adapter`：`EvolveConfig.from_yaml(task_dir/"evolve.yaml")` → `create_adapter`；异常 → ok=False, message=`str(exc)` 首行。message 形如 `"adapter hdd -> HDDAdapter"`。
- `task_data`：adapter 满足 `isinstance(adapter, DataStatusProvider)` 时调用；否则跳过。
- `task_data_root_env`：任务用 `HDD_BENCH_DATA_ROOT` 且已设置时，输出 ok=True, message=`"HDD_BENCH_DATA_ROOT=<v> (确认它属于 <task_dir.name>)"`。
JSON 结构不变（`{"checks":[...],"all_ok":bool}`）。stub 因创建成功但 `data_status.ok=False` ⇒ `all_ok=False`，退出码 1（符合预期）。
### 3.5 fe evolve local
仅改缺文件分支的错误文案：若 `stub_doc_for(config.task.adapter)` 非空，追加 `See <doc>`；其余逻辑不变。

## 4. Backblaze 任务目录 `benchmark/backblaze_hdd/`
- `evaluator.py`、`init.py`、`prompt.md`：**从 hdd_mvp 逐字节复制**（`cp`）。`problem.md`：复制后仅替换“数据来源”段的季度/样本数三行（hdd_mvp/problem.md 第 30-32、57 行）为“见 `data/meta.json`；默认 训练 2024Q4 / 验证 2025Q1 / 私有测试 2025Q2”，其余行不变（测试比较非这些行）。
- `knowledge/` 从 hdd_mvp/knowledge 复制三个文件（副本，见坑 7）。`evolve.yaml`：从 hdd_mvp/evolve.yaml 复制，改首行注释、加
  ```yaml
  task:
    adapter: backblaze
  stop: {target_score: null}   # 仅此处覆盖；其余键保持
  ```
  （若 `target_score: null` 不被 StopConfig 接受，则保留 33.7 并注释“仅用于追踪”。）其它新功能开关保持与 hdd_mvp 相同（默认关）。
- 数据目录布局与 hdd_mvp 完全一致：`data/public/{train_history.csv.gz,train_labels.csv,val_history.csv.gz,val_index.csv}`、`data/eval_only/val_labels.csv`、
  `data/holdout/{train_history.csv.gz,train_labels.csv,test_history.csv.gz,test_index.csv}`、`data/holdout_labels/test_labels.csv`、`data/meta.json`。

### 4.1 `download_data.py`（标准库 only；测试不联网）
```
python benchmark/backblaze_hdd/download_data.py --quarters 2024Q4 2025Q1 2025Q2 --raw-dir <dir> [--dry-run] [--keep-zip] [--base-url URL]
```
- `parse_quarter(s:str)->tuple[int,int]`：正则 `^(\d{4})Q([1-4])$`，否则 `ValueError`。`quarter_dirname(s)->"data_Q{q}_{yyyy}"`。
- `zip_url(s, base_url=DEFAULT_BASE)->str`：默认 base `https://f001.backblazeb2.com/file/Backblaze-Hard-Drive-Data`，结果 `{base}/data_Q1_2025.zip`。
- `plan_downloads(quarters, raw_dir)->list[dict(url, zip_path, extract_dir, skip: bool)]`：`extract_dir` 已含 ≥1 个 csv 则 `skip=True`。
- `extract_zip(zip_path, raw_dir, quarter)`：解到 `raw_dir/data_Qq_yyyy/`，忽略 `__MACOSX/`，只保留 `*.csv`（扁平化：取文件名 basename，防 zip-slip：拒绝含 `..` 或绝对路径的成员 → `ValueError`）。
- `download(url, dest)`：`urllib.request.urlretrieve` 分块 + `.part` 临时文件，成功后 rename；仅 `main()` 调用，`--dry-run` 只打印计划（每行 `URL -> zip_path -> extract_dir`）。
- 每季约 1 GB 压缩、解压数 GB；README/docs 写明。

### 4.2 `prepare_data.py`（duckdb；独立脚本，**不 import hdd_mvp/prepare_data.py，也不改它**）
逻辑逐句对应 hdd_mvp 的 `build_split`（采样/标签/权重规则相同），参数化：
```
python benchmark/backblaze_hdd/prepare_data.py --raw-dir R [--out-dir benchmark/backblaze_hdd/data]
   [--train-quarter 2024Q4] [--val-quarter 2025Q1] [--test-quarter 2025Q2]
   [--horizon 7] [--history-days 14] [--min-capacity-tb 4] [--max-capacity-tb None]
   [--vendors ""]          # 逗号分隔，model 大写后 startswith 任一；空=不过滤
   [--n-negatives 30000] [--seed-base 0] [--disjoint-disks] [--holdout-dir PATH] [--skip-holdout]
```
公开函数（测试直接 import，用 `importlib.util.spec_from_file_location` 加载）：
- `SMART_COLS`（同 hdd_mvp：RAW_ATTRS 22 个 + NORM_ATTRS 9 个）、`quarter_bounds(q:str)->(date_start, date_end)`（自然季度首/末日）。
- `derive_windows(q:str, horizon:int, history_days:int)->(cutoff_start:str, cutoff_end:str)`：`start = q_start + (history_days-1)` 天，`end = q_end - horizon` 天。
  默认参数下 `2024Q3→("2024-07-14","2024-09-23")`、`2024Q4→("2024-10-14","2024-12-24")`、`2025Q1→("2025-01-14","2025-03-24")` 必须与 hdd_mvp `SPLITS` 一致。
- `build_split(con, raw_dir, quarter, role, args, exclude_serials:set[str]|frozen)->(history_df, samples_df, stats)`：
  - life 表：按 serial 聚合 `first_date,last_date,fail_date`，过滤 `capacity>=min_cap` 且 `<=max_cap`（若给）且 vendor 前缀。
  - 正样本：`cutoff = fail_date - (1 + hash(serial||seed) % horizon)`，落在 [cutoff_start,cutoff_end] 且 ≥ first_date；标签 1，权重 1.0。
  - 负样本池：`fail_date IS NULL` 且 `least(cutoff_end, last_date-horizon) >= greatest(cutoff_start, first_date)`；随机 cutoff；取 `min(n_negatives, eligible)`，权重 `eligible/n_sampled`。
  - `--disjoint-disks`：对 val/test，life 中剔除 `exclude_serials`（前面 split 的 samples 序列号）；默认关（与 hdd_mvp 行为一致，同盘可跨季出现）。
  - history：`[cutoff-history_days+1, cutoff]` 的逐日 SMART；缺列处理：先 `DESCRIBE` 读取 CSV 实际列，缺失 SMART 列用 `NULL AS col`（旧季度可能缺列）；剔除 cutoff 当天无记录的样本（同 hdd_mvp）。
  - 种子：`seed = seed_base + {train:11, val:22, test:33}`。
- 输出规则同 hdd_mvp（见目录布局）；`--holdout-dir` 给定时 holdout/holdout_labels 写到该目录下同名子目录，`out-dir` 内不产生 holdout*；`--skip-holdout` 不写 test 相关文件且不读 test 季度。
- `meta.json`：`horizon_days, history_days, min_capacity_bytes, vendors, quarters{train,val,test}, disjoint_disks, smart_columns, splits{name:stats}`；stats 键同 hdd_mvp。
- 校验：`horizon∈[1,30]`，`history_days∈[1,60]`，三个季度互不相同且按时间递增，否则 `SystemExit`（非 0）+ 清晰信息；raw 目录缺 `data_Qq_yyyy/*.csv` → 报错并提示先运行 download_data.py。
- 变体示例（写入 docs）：30 天 horizon `--horizon 30`；厂商 `--vendors ST`；容量段 `--min-capacity-tb 8`。

## 5. 造数据 helper `tests/helpers_backblaze.py`
`make_tiny_raw(raw_dir, quarters, n_stay=40, n_fail=12, n_small=4, seed=0)`：每季度 `data_Qq_yyyy/` 下写 ≥2 个 csv（按日期分文件，列 `date,serial_number,model,capacity_bytes,failure` + `SMART_COLS` 全部；再加一列噪声 `smart_255_raw` 检验列裁剪）。
- 型号：`ST8000DM002`(8TB)、`TOSHIBA MG07`(12TB)、`WDC WD30`(3TB，n_small 块，用于容量过滤)。
- 逐日 90+ 天覆盖整季；n_fail 块盘在季度内某日 `failure=1` 之后不再出现（且日期均匀分布，保证每个 split 至少 8 个正样本）；故障盘故障前 7 天 `smart_197_raw` 递增（保证 init 可训）。
- 一块盘跨两个季度存在（供 disjoint 测试）。返回 `dict(serials_by_quarter, fail_date_by_serial)`。
- 所有测试参数：`--n-negatives 25 --seed-base 0`，运行时间 < 10 s。

## 6. SSD / DRAM stub（只接口+文档，不下载、不运行）
### 6.1 `tasks/stub_base.py`
```python
class DataNotPreparedError(NotImplementedError): ...
class StubDatasetAdapter(FamouAdapter):
    DATASET_NAME: str; DOC_PATH: str; DATA_ROOT_ENV: str; REQUIRED_DATA_FILES: tuple[str,...]
    def __init__(self, min_noise_delta: float = 0.5) -> None
    def _not_ready(self, what: str) -> DataNotPreparedError   # 消息: f"{DATASET_NAME}: {what} not implemented / data not prepared. See {DOC_PATH}"
    def data_root(self, task_dir: Path) -> Path             # env(DATA_ROOT_ENV) 优先，否则 task_dir/"data"；不创建、不读文件
    def data_status(self, task_dir: Path) -> DataStatus     # 仅 exists() 检查 REQUIRED_DATA_FILES（相对 data_root）；ok 恒依据文件是否存在
    def load_task(self, task_dir): 缺 evaluator.py/init.py/problem.md/prompt.md 之一 -> raise self._not_ready("task files")
    def evaluate(...) / smoke_test(...) / build_smoke_data_dir(...): raise self._not_ready("evaluator")
    def constraints(...)->str: 返回 1 段“stub”说明（非空，中文），不引用具体列
```
继承 FamouAdapter，使 `isinstance(x, TaskAdapter)` 为真（其余协议方法沿用基类默认：`static_check/api_notes/get_noise_delta`）。
### 6.2 `AlibabaSSDAdapter`（`ssd_alibaba_adapter.py`）
- `DATASET_NAME="alibaba_ssd"`，`DOC_PATH="docs/datasets/alibaba_ssd.md"`，`DATA_ROOT_ENV="ALIBABA_SSD_DATA_ROOT"`。
- `REQUIRED_DATA_FILES = ("public/train_history.csv.gz","public/train_labels.csv","public/val_history.csv.gz","public/val_index.csv")`（与 hdd 同构目标接口）。
- 常量（供 converter 与测试）：`SMARTLOG_ID_COLS=("disk_id","ds","model")`；`SMARTLOG_ATTR_IDS`（105 列 = 3 + 2×51；写 `# 51 ids per format; verify against dcbrain readme when implementing`，代码里用**前缀规则**校验，不硬编码 ID 列表）；
  `FAILURE_LABEL_COLUMNS=("model","disk_id","failure_time")`；`OPEN_DATA_TAG_COLUMNS`（ssd_failure_tag.csv：`model,failure_time,failure,app,machine_room_id,rack_id,node_id,disk_id`，其余 `r_*/n_*` 及聚合列 `n_blocks,r_program,n_program,r_erase,n_erase,n_wearout` 只做前缀/存在性可选检查）。
- 静态方法：`validate_smartlog_frame(df)->None`（必须含 SMARTLOG_ID_COLS；其余列须全部匹配 `^[nr]_\d+$`；否则 `ValueError` 列出违例列）；`validate_failure_labels(df)->None`；
  `rename_to_task_schema(df)->DataFrame`：`disk_id→serial_number, ds(yyyymmdd 整数/字符串)→date(YYYY-MM-DD 字符串), n_i→smart_i_normalized, r_i→smart_i_raw`，输出列顺序**固定 `date,serial_number,model` + SMART 列**（保持坑 4 的第二列约束）。这是唯一实现了的“纯函数”，供 schema 测试。
- `context_keywords(code)`：正则 `smart_(\d+)` → `ssd_smart_<id>`，其余返回 `[]`。
- `objectives/threshold_objectives/noise_metric`：不实现（缺失即不启用 ObjectiveSpec）。
### 6.3 `benchmark/ssd_alibaba/`
- `README.md`：目录用途、stub 状态、指向 docs。
- `evolve.yaml`：`task: {adapter: alibaba_ssd}`、`knowledge: {enabled: false}`、`smoke_test: {enabled: false}`、`budget: {max_iterations: 10}`，其余不写（默认关）。
- `prepare_data.py`（骨架，argparse 完整，`main()` 校验参数与输入文件存在后 `raise DataNotPreparedError`-类 `NotImplementedError("...not implemented; see docs/datasets/alibaba_ssd.md")`）：
  ```
  python benchmark/ssd_alibaba/prepare_data.py --raw-dir R --out-dir benchmark/ssd_alibaba/data
      [--variant smart_logs|open_data] [--horizon 7] [--history-days 14]
      --train-months 2018-01:2018-12  --val-months 2019-01:2019-06  --test-months 2019-07:2019-12 [--n-negatives 30000] [--skip-holdout]
  ```
  输入：`R/smartlog2018ssd/*.csv|smartlog2019ssd/*.csv`（`yyyymmdd.csv`）+ `R/ssd_failure_label.csv`（open_data：`R/ssd_failure_tag.csv`）。
  输出（目标）：与 hdd_mvp 完全同构，history 列 `date,serial_number,model,smart_<i>_raw,smart_<i>_normalized`；labels 列 `serial_number,model,cutoff_date,label,weight`；抽样/标签规则同 §4.2（label=(c,c+H] 内故障，pos cutoff=fail−k）。
  已实现：`parse_month_range(s)->(str,str)`（`YYYY-MM:YYYY-MM`，非法→ValueError）；`load_failure_labels(path)->DataFrame[serial_number,model,failure_date]`（`pd.to_datetime(...).dt.normalize()`，先调 `validate_failure_labels`）；`build_split(...)` 抛 NotImplementedError。
- 未来 evaluator：文档说明“复制 hdd_mvp/evaluator.py（因输出同构）后视为受保护”；本 PR 不创建。
### 6.4 `SmartMemAdapter`（`smartmem_adapter.py`）
- `DATASET_NAME="smartmem"`，`DOC_PATH="docs/datasets/smartmem.md"`，`DATA_ROOT_ENV="SMARTMEM_DATA_ROOT"`，`REQUIRED_DATA_FILES=("public/train_samples.csv.gz","public/train_labels.csv","public/val_index.csv","public/val_samples.csv.gz")`。
- 常量：`MCELOG_COLUMNS`（23 列，**原样含拼写 `manufacturter`**）：`cpuid,channelid,dimmid,rankid,deviceid,bankgroupid,bankid,rowid,columnid,retryrderrlogparity,retryrderrlog,burst_info,error_type,log_time,manufacturter,model,PN,Capacity,FrequencyMHz,MaxSpeedMHz,McaBank,memory_type,region`；
  `TICKET_COLUMNS=("serial_number","failure_time","serial_number_type")`；`SUBMISSION_COLUMNS=("sn_name","prediction_timestamp","serial_number_type")`；`LEAD_MINUTES=15`；`PREDICT_WINDOW_DAYS=7`；`SERIAL_TYPES=("A","B")`。
- 静态方法：`validate_mcelog_frame(df)`（23 列齐全，多余列容忍，缺列 ValueError）、`validate_ticket_frame(df)`（三列 + `serial_number_type ∈ {A,B}`）、`validate_submission_frame(df)`。
- **聚合规则（写入 docstring 与 docs，`aggregate_events_to_samples` 只声明签名并 `raise NotImplementedError`）**：
  `aggregate_events_to_samples(events: DataFrame, tickets: DataFrame, *, lookback_days: int = 5, sample_every_minutes: int = 15, max_samples_per_dimm: int = 200) -> DataFrame`
  - 一个 DIMM = 一个 mcelog 文件 = 一个 `serial_number`（文件名去扩展名）；`log_time` 解析为 UTC-naive `datetime`。
  - 样本时间 `t`：该 DIMM 每个事件 `log_time` 向下取整到 `sample_every_minutes` 后去重；超出上限时保留最近 `max_samples_per_dimm` 个（时间序 tail）。样本只能用 `log_time <= t` 的事件（流式约束，禁止未来信息）。
  - 特征（窗 `(t-lookback, t]`）：各 `error_type` 计数、`dimmid/rankid/bankid/rowid/columnid/deviceid` 去重计数、`retryrderrlog` 非空计数、总事件数、距上次事件分钟数；静态列 `manufacturter,model,Capacity,FrequencyMHz`。
  - 标签：`1` 当且仅当 `failure_time ∈ [t+15min, t+15min+7d]`（同 SN 的 ticket）；`t` 之后 <15 min 内故障的样本**丢弃**（不可预警）。
  - 输出列固定：`serial_number,sample_time,serial_number_type,label,<features...>`；预测提交 `sn_name=serial_number, prediction_timestamp=sample_time`。
- 因指标为 F1（事件式）且无 SMART 日快照，**不复用 hdd 接口/evaluator**；未来需要写新的事件式 evaluator（不在本 PR）。`benchmark/smartmem/{README.md,evolve.yaml,prepare_data.py}` 结构同 §6.3：
  ```
  python benchmark/smartmem/prepare_data.py --raw-dir R --out-dir benchmark/smartmem/data [--format csv|feather]
      [--lookback-days 5] [--sample-every-minutes 15] [--max-samples-per-dimm 200] [--train-until 2024-06-30] [--val-until 2024-08-31]
  ```
  输入 `R/train/*`（每 DIMM 一个 mcelog 文件）+ `R/failure_ticket.csv`；已实现 `list_mcelog_files(raw_dir, fmt)`、`load_tickets(path)`（调 `validate_ticket_frame`）；`main()` 最终 `raise NotImplementedError`。`--train-until/--val-until` 的具体日期需在实现时按数据实际时间范围确认（不在此臆测）。

## 7. 测试（全部离线；新增文件与用例；预计 +55 左右）
**tests/test_adapter_registry.py**
- `test_task_config_default_is_hdd`：`EvolveConfig().task.adapter=="hdd"`；`from_dict({"task":{"adapter":"famou"}}).task.adapter=="famou"`；`with_overrides(max_iterations=3).task.adapter` 保持。
- `test_adapter_from_config`：parametrize alias→类：hdd→HDDAdapter，famou→FamouAdapter，backblaze→BackblazeAdapter，alibaba_ssd→AlibabaSSDAdapter，smartmem→SmartMemAdapter，`"faultevolve.tasks.famou_adapter:FamouAdapter"`→FamouAdapter。
- `test_create_benchmark_adapter_default_unchanged`：`EvolveConfig()`（kappa_noise=1.0 改 2.0 再测）→ `HDDAdapter`，`kappa/min_noise_delta/dev_late_fraction/analysis_min_group_count` 值与旧实现一致。
- `test_unknown_adapter_errors`：`"nope"`、`"a.b:C"`、`"faultevolve.tasks.hdd_adapter:Nope"` → ValueError，消息含 `aliases`。
- `test_famou_adapter_receives_only_supported_kwargs`。
- `test_hdd_adapter_data_status_uses_env`：monkeypatch `HDD_BENCH_DATA_ROOT` 指向 tmp（含四个空文件）→ ok；删一个 → `missing` 列出该文件；断言未读文件内容（文件为空即可）。
**tests/test_backblaze_prepare.py**（用 helpers_backblaze；`pytest.importorskip("duckdb")`）
- `test_prepare_data_params_default_unchanged`：`derive_windows` 三个默认季度 == hdd_mvp `SPLITS` 的 `cutoff_start/end`；hdd_mvp 的 `HORIZON/HISTORY_DAYS/MIN_CAPACITY_BYTES`==7/14/4e12；`SMART_COLS` 相等；argparse 默认 `horizon=7 history_days=14 min_capacity_tb=4`。
- `test_quarter_parsing`：`"2025Q1"`→`(2025,1)`；`"2025Q5"`、`"25Q1"` ValueError；`quarter_bounds("2024Q4")==(date(2024,10,1),date(2024,12,31))`。
- `test_prepare_tiny_outputs_schema`：跑 train=2024Q4,val=2025Q1,test=2025Q2；断言文件集合与目录布局；`train_labels` 列==`[serial_number,model,cutoff_date,label,weight]`；`val_index` 列==`[serial_number,model,cutoff_date]`（无 label）；`val_labels` 列==`[serial_number,label,weight]`；history 前两列==`[date,serial_number]`，含全部 SMART_COLS；`label∈{0,1}`。
- `test_prepare_label_and_history_rules`：对每个正样本 `fail_date-cutoff ∈ [1,horizon]`（用 helper 返回的 fail_date）；对负样本该盘无 failure 日；history 中每盘 `date<=cutoff` 且行数 ≤ history_days 且含 cutoff 当天；正样本权重 1.0，负样本权重 = `n_eligible/n_sampled`（读 meta.json 核对）；`--horizon 30` 时 `fail_date-cutoff ∈ [1,30]`。
- `test_prepare_capacity_and_vendor_filters`：3TB 盘不出现；`--vendors ST` 后所有 `model` 以 ST 开头；`--min-capacity-tb 10` 后仅 12TB 型号。
- `test_prepare_disjoint_disks`：默认时跨季盘同时出现在 train/val（用例构造保证）；加 `--disjoint-disks` 后 train/val/test 序列号两两交集为空。
- `test_prepare_holdout_separate`：`--holdout-dir X`：`out/holdout*` 不存在，X 下有；`--skip-holdout`：无 test_* 文件且脚本未访问 test 季度目录（raw 里不创建该季目录也能成功）。
- `test_prepare_deterministic`：同参数跑两次，`train_labels.csv` 字节相等；history 用 `pd.read_csv` 内容相等（gzip 头时间戳不同）。
- `test_prepare_missing_smart_column_filled`：某季度 csv 删去一个 SMART 列 → 输出该列全 NaN，不报错。
- `test_prepare_bad_args`：horizon=0/31、重复季度、raw 缺季度目录 → `SystemExit`，非 0。
- `test_download_plan_and_urls`：`zip_url("2025Q1")=="https://f001.backblazeb2.com/file/Backblaze-Hard-Drive-Data/data_Q1_2025.zip"`；`plan_downloads` 在目标目录已有 csv 时 `skip=True`。
- `test_extract_zip_local_fixture`：tmp 内用 zipfile 造含 `__MACOSX/x` 与 `a/b.csv` 的 zip → 解压后仅 `data_Q1_2025/b.csv`；含 `../evil.csv` 成员 → ValueError。
- `test_download_dry_run_no_network`：monkeypatch `socket.socket` 抛错，`main(["--quarters","2025Q1","--raw-dir",tmp,"--dry-run"])` 成功并打印 URL。
**tests/test_backblaze_task.py**
- `test_bb_variant_evaluator_identical_to_hdd`：`evaluator.py/init.py/prompt.md` 的 sha256 与 hdd_mvp 对应文件相等；`problem.md` 除第 30-32、57 行外逐行相等。
- `test_bb_evolve_yaml_valid`：`EvolveConfig.from_yaml` 成功，`task.adapter=="backblaze"`，`discovery.enabled/analysis.enabled/operators.bandit/judge.provider` 的默认值不变（与 hdd_mvp 相同）。
- `test_bb_knowledge_is_copy`：`knowledge/cards.jsonl` 字节等于 hdd_mvp 的，且路径不同。
- `test_bb_tiny_end_to_end_evaluator`：tiny 数据 → 设 `HDD_BENCH_DATA_ROOT=<out>/data`（monkeypatch，同 `test_hdd_evaluator` 里 `importlib` 新加载评估器的做法）→ 对 `init.py` 调 `evaluate()`：`validity==1`，`combined_score` 为 float，`metric` 含 `f1_p10/auprc/recall_at_far`；`BackblazeAdapter().data_status(...)` ok。
- `test_bb_adapter_protocol`：isinstance TaskAdapter / ObjectiveSpec / ErrorProfiler / ObjectiveBriefProvider / DiscoveryDataProvider / DataStatusProvider 均 True；`get_noise_delta` 与 HDDAdapter 同输入同输出。
- `test_bb_mock_evolution_tiny`：`run_local_evolution(task_dir=tmp 复制的 backblaze_hdd(含 tiny data)、mock=True、max_iterations=2、runs_dir=tmp)` 成功，`status` 存在（复制目录时排除 `.fe`；验证跨任务不写回仓库目录）。若耗时 >30 s，缩小 tiny 数据而不是删测试。
**tests/test_dataset_stubs.py**
- `test_ssd_adapter_protocol`：isinstance TaskAdapter；`get_noise_delta` 返回 0.5。
- `test_ssd_stub_raises_clear_error`：`evaluate/smoke_test/build_smoke_data_dir/load_task(空目录)` 均抛 `DataNotPreparedError`（也是 `NotImplementedError`），消息含 `alibaba_ssd` 与 `docs/datasets/alibaba_ssd.md`。
- `test_ssd_validate_smartlog_frame`：合法小表（`disk_id,ds,model,n_1,r_1,n_5,r_5`）通过；缺 `ds`、含未知列 `foo` → ValueError 且消息含列名。
- `test_ssd_rename_to_task_schema`：输入 2 行（ds=20180105, disk_id="d1"）→ 列顺序 `[date,serial_number,model,smart_1_normalized,smart_1_raw,...]`，`date=="2018-01-05"`。
- `test_ssd_prepare_small_fixture`：tmp 写 2 天 smartlog csv + `ssd_failure_label.csv`；`load_failure_labels` 返回三列且 `failure_date` 为 date；`prepare_data.main([...])` 抛 NotImplementedError，消息含 doc 路径；`parse_month_range("2018-01:2018-12")` 正常，非法值 ValueError。
- `test_ssd_data_status_env`：`ALIBABA_SSD_DATA_ROOT` 指向空目录 → `ok=False` 且 `missing` 长度 4；未设置时使用 `task_dir/data`。
- `test_smartmem_adapter_protocol` / `test_smartmem_stub_raises_clear_error`（同上，含 `smartmem`）。
- `test_smartmem_mcelog_schema`：23 列（含 `manufacturter`）通过；把它改成 `manufacturer` → ValueError；`test_smartmem_ticket_and_submission_schema`（`serial_number_type="C"` → ValueError）。
- `test_smartmem_aggregate_is_documented_stub`：`aggregate_events_to_samples` 抛 NotImplementedError；`inspect.getdoc` 含 `t+15` 与 `7 d`（文档不漂移）。
- `test_smartmem_prepare_small_fixture`：tmp 写 2 个 mcelog csv + failure_ticket.csv → `list_mcelog_files`/`load_tickets` 正常；`main` 抛 NotImplementedError。
**tests/test_engine_task_agnostic.py**
- `test_engine_sources_task_agnostic`：扫描 `cloud/ common/ knowledge/ worker/ config.py`，正则 `smart|hdd|vendor|backblaze|alibaba|smartmem|dimm|disk_id|ssd`（忽略大小写），命中集合必须 == allowlist（仅 `common/textutil.py` 的 `vendor_from_model` 两行）；`discovery/` 沿用既有测试不重复。
- `test_new_adapters_not_imported_by_engine`：`cloud/` 下源码不含 `backblaze_adapter|ssd_alibaba_adapter|smartmem_adapter` 字符串（只经注册表）。
**tests/test_hdd_protected_files.py**
- 编码第一步在未改动的 main 上运行 `sha256sum benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md,prepare_data.py,knowledge/cards.jsonl}` 与 `data/public/*`，把结果写进测试常量。只哈希上述脚本/文档/卡片与 `data/public/*`；`data/eval_only`、`data/holdout*` 不读、不哈希。`test_hdd_mvp_files_byte_identical`：逐个比对。
**tests/test_doctor_task_checks.py**（typer `CliRunner`，`from faultevolve.cli import app`）
- `test_doctor_without_task_dir_unchanged`：`--json` 输出的 check 名集合不含 `task_*`。
- `test_doctor_hdd_task_checks`：`--task-dir benchmark/hdd_mvp --json`：含 `task_files/task_adapter/task_data`，`task_adapter` message 含 `HDDAdapter`。
- `test_doctor_backblaze_missing_data`：设 `HDD_BENCH_DATA_ROOT` 指向空 tmp：`task_data.ok==False`，message 含 `prepare_data.py`；`task_data_root_env` 存在。
- `test_doctor_stub_dir`：`--task-dir benchmark/ssd_alibaba --json`：`task_files.ok==False` 且 message 含 `docs/datasets/alibaba_ssd.md`；`task_adapter.ok==True`；退出码 1。
- `test_evolve_local_stub_dir_message`：`fe evolve local benchmark/ssd_alibaba --mock` 退出码 1，stderr 含 `docs/datasets/alibaba_ssd.md`。

## 8. 文档与 Skill（大纲，简体中文）
**docs/datasets/backblaze.md**：1 概览（默认变体：训练 2024Q4 → 验证 2025Q1 → 私有测试 2025Q2；同构接口，evaluator 与 hdd_mvp 字节相同，ROS 可比）；2 获取数据（URL 模板、每季 ≈1 GB 压缩/数 GB 解压、无需登录；`download_data.py` 精确命令 `python benchmark/backblaze_hdd/download_data.py --quarters 2024Q4 2025Q1 2025Q2 --raw-dir /data/backblaze`；服务器能否联网**未核实**，不通则本机下载后拷贝）；3 转换（精确命令 + 参数表 + 变体示例 + 输出目录树 + meta.json）；4 配置（evolve.yaml、`HDD_BENCH_DATA_ROOT=/data/bb/out/data`、`FE_RUNS_DIR`、`.env` 键名）；5 运行（`fe doctor --task-dir benchmark/backblaze_hdd`；`cd benchmark/backblaze_hdd && python evaluator.py init.py`；`fe evolve local benchmark/backblaze_hdd --mock -n 3`；真实：`fe evolve local benchmark/backblaze_hdd --iterations 50 --env-file .env`；私有测试仅在最终由人工执行 `--split test`）；6 报告字段（val ROS、init ROS、§4.3 指标）；7 常见故障（缺列、环境变量串用、内存）。
**docs/datasets/alibaba_ssd.md**：0 状态=stub（哪些已实现/哪些抛 NotImplementedError）；1 获取（`https://tianchi.aliyun.com/dataset/95044`，**需天池账号，agent 无法下载**；`smartlog2018ssd.zip`/`smartlog2019ssd.zip` ≈4.3 GB 各；`ssd_failure_label.csv`；open_data 变体额外 `ssd_failure_tag.csv`、`location_info_of_ssd`；覆盖 2018-01-01..2019-12-31，smart_logs 6 型号 / open_data 11 型号；原始格式 105 列表）；2 目标接口与列映射表（§6.2）+ 抽样/标签规则；3 转换命令（§6.3，标注“骨架，待实现”）；4 配置（`ALIBABA_SSD_DATA_ROOT`、evolve.yaml 示例）；5 运行命令（`fe doctor --task-dir benchmark/ssd_alibaba` 预期失败信息；实现后：`fe evolve local benchmark/ssd_alibaba --mock -n 3` → 真实）；6 待办清单（实现 build_split、复制 evaluator、写 problem/prompt/init、可选 SSD 知识卡）。
**docs/datasets/smartmem.md**：同结构；获取：Codabench 3586 Data 页（SharePoint / rec.ustc.edu.cn 链接，可能需注册）、CSV ≈130 GB 或 Feather ≈40 GB、Kaggle `smartmem/smartmem-features`、`github.com/hwcloud-RAS/SmartHW` starter kit；许可 CC BY-NC-SA（禁再分发，禁止入库）；Phase 2 已结束不能提交（仅本地评估）；3 输入格式表（mcelog 23 列、failure_ticket、submission）、聚合规则 §6.4、事件式评估器需求（F1，UE∈[t+15 min, t+15 min+7 d]，仅用 t 之前数据）；注明这是内存而非硬盘。
**README.md**：新增“## 数据集与泛化”一节（4 行表：数据集/状态/任务目录/文档；一行命令示例；`task.adapter` 说明；stub 状态声明）。
**skill/fe-dataset-adapters/SKILL.md**（frontmatter name/description，章节顺序固定）：何时使用（换数据集、选 `task.adapter`、准备/校验数据）；输入（数据集别名、原始数据目录、horizon/history、季度、`.env` 键、`HDD_BENCH_DATA_ROOT`）；精确命令（download→prepare→`evaluator.py init.py`→`fe doctor --task-dir`→`fe evolve local … --mock -n 3`→真实；stub 命令列出并标注预期失败）；成功检查（doctor `all_ok`、init ROS>0 且 meta.json 各 split 正样本数>0、mock 运行 `run_summary.json` 存在、`git diff --stat benchmark/hdd_mvp` 为空、引擎无领域字符串测试通过）；失败处理（表：症状→处理：`data not prepared`、缺列、下载失败/离线、环境变量串用、内存不足→减小 `--n-negatives`）；禁止操作（不读 `holdout*`/`eval_only`、不改 hdd_mvp 与已入库 evaluator、不提交 data/raw、不写密钥、不把 LLM/Jev 输出当分数、不尝试登录天池/Codabench 下载、不在 stub 上跑真实进化）。
**skill/fe-evolve-manager/SKILL.md**：在“输入/任务目录结构”后加一句 `task.adapter` 说明并链接 `skill/fe-dataset-adapters/SKILL.md`；“参考”列表追加该 skill 与 `docs/datasets/*.md`；不改现有命令。

## 9. 实施顺序、验收、报告
1. 先算并固化 hdd_mvp 哈希（test_hdd_protected_files）；2. config+registry+protocol+cli；3. Backblaze 任务与脚本；4. stub；5. 文档/skill；6. 全量 `python -m pytest tests/ -q`（须 ≥433 + 新增，0 失败）；`git diff --stat -- benchmark/hdd_mvp` 必须为空；`git status` 无 `data/`、无 `.fe/`、无 key。
已知限制（写入 PR 描述）：`precheck.py` 的 `serial_number` 规则和 `textutil.vendor_from_model` 未泛化（同构接口下无影响）；MockLLM 只覆盖 hdd 同构任务；stub 未做真实运行。
**PR 描述须列出“待服务器执行”**：
1. `download_data.py --quarters 2024Q4 2025Q1 2025Q2`（先确认服务器能否联网，否则本机下载再拷贝）；2. `prepare_data.py` 生成数据并记录 meta.json；3. `HDD_BENCH_DATA_ROOT=… python evaluator.py init.py` 得 Backblaze init val ROS；4. `fe doctor --task-dir benchmark/backblaze_hdd`；5. `fe evolve local benchmark/backblaze_hdd --mock -n 3`；6. 真实进化 ≥10 轮，报告 val ROS vs init ROS 及 §4.3 指标（不读 holdout；私有测试由人工最终执行）；7. SSD/DRAM：待用户提供数据后实现 `build_split` / `aggregate_events_to_samples` 与 evaluator，再按各自 docs 运行。
