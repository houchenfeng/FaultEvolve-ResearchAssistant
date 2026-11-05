# PR #6 实施计划：dev 集错例画像 + 评估器感知提示

## 1. 边界与验收口径
- 基线固定为 `main@63394c1`；不修改 `benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md}` 或任何 `data/` 文件。
- 画像只读取公开 `train_history.csv.gz`、`train_labels.csv`；禁止读取、探测或复制 `eval_only`、`test`、`holdout`。
- `analysis.enabled` 默认 `false`；关闭时不建 dev 数据、不启动候选子进程、不增加 LLM/评估成本，现有行为和摘要字段值保持兼容。
- 不修改 `TaskAdapter`；能力通过两个独立、`@runtime_checkable` 的可选 Protocol 暴露。`cloud/` 只处理通用 `dict/str`，不得出现 HDD/SMART/Backblaze 等领域词。
- 画像、画像差分和 objective brief 均确定性生成，不新增 LLM 调用。增加的生成 prompt token 仍计入 `generate_tokens`，反思 prompt token 仍计入 `reflect_tokens`；不得把任何调用漏出 `total_tokens`。
- 所有新增测试使用合成数据、FakeAdapter/MockLLM/MockJev，不访问真实数据和网络。

## 2. 配置与接口
### `src/faultevolve/tasks/protocol.py`
- 新增：
  ```python
  @runtime_checkable
  class ErrorProfiler(Protocol):
      def analyze(self, code: str, task_spec: TaskSpec, timeout: int) -> dict[str, Any]: ...

  @runtime_checkable
  class ObjectiveBriefProvider(Protocol):
      def objective_brief(self, task_spec: TaskSpec) -> str: ...
  ```
- `TaskAdapter` 原样保留；引擎只用 `isinstance(adapter, ErrorProfiler/ObjectiveBriefProvider)` 探测能力。

### `src/faultevolve/tasks/__init__.py`
- 导出 `ErrorProfiler`、`ObjectiveBriefProvider`，保持已有导出不变。

### `src/faultevolve/config.py`
- 新增 `AnalysisConfig(BaseModel)`：
  ```python
  enabled: bool = False
  top_k: int = Field(default=3, ge=0)
  on_new_best: bool = True
  dev_late_fraction: float = Field(default=0.4, gt=0, lt=1)
  timeout_s: int = Field(default=600, gt=0, le=900)
  min_group_count: int = Field(default=10, ge=10)
  ```
- `EvolveConfig.analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)`；`from_dict()` 显式解析 `analysis`，确保 `with_overrides()` 往返不丢字段。

### `benchmark/hdd_mvp/evolve.yaml`
- 增加以下默认关闭段：
  ```yaml
  analysis:
    enabled: false
    top_k: 3
    on_new_best: true
    dev_late_fraction: 0.4
    timeout_s: 600
    min_group_count: 10
  ```

## 3. HDD dev 画像实现
### `src/faultevolve/tasks/hdd_adapter.py`
- 扩展构造函数：
  ```python
  def __init__(
      self,
      min_noise_delta: float = 0.5,
      kappa: float = DEFAULT_KAPPA,
      dev_late_fraction: float = 0.4,
      analysis_min_group_count: int = 10,
  ) -> None
  ```
- 新增实例缓存 `_analysis_data_dir: Path | None`、`_analysis_labels: pd.DataFrame | None`、`_analysis_features: pd.DataFrame | None`，同一进程只构建一次 dev 划分。
- 新增 `_build_analysis_data(task_spec: TaskSpec) -> tuple[Path, pd.DataFrame, pd.DataFrame]`：
  1. `_get_data_dir()` 后只拼接两个白名单文件名 `train_labels.csv`、`train_history.csv.gz`；代码中不得出现受禁数据目录名。
  2. 按 `cutoff_date` 的有序唯一日期选择 `(1-dev_late_fraction)` 分位切点；早期日期作训练、晚期日期作 dev 查询，拒绝空划分。
  3. 临时候选目录只写四个契约文件：early → `train_labels.csv/train_history.csv.gz`，late → `val_index.csv/val_history.csv.gz`；`val_index` 只含 `serial_number/model/cutoff_date`。
  4. late 标签只保留在 adapter 内存；绝不写入候选可见目录。历史文件用 `pd.read_csv(..., chunksize=200_000)` 单次流式过滤，避免整表入内存。
  5. 从 late 每盘 cutoff 前最后一行构造仅供聚合的特征表；不返回序列号或原始值。
- 新增 `analyze(code, task_spec, timeout) -> dict[str, Any]`：
  1. 将代码写临时 `.py`，用 `sys.executable <candidate> --data-dir <dev_dir> --split val --out <tmp.csv>`；`subprocess.run(..., timeout=timeout, cwd=task_spec.task_dir, capture_output=True, text=True)`。
  2. 校验输出列恰为所需集合、序列号无重/无缺/无多、`score` 有限、`alarm∈{0,1}`；失败抛出 `ValueError`，超时保留 `TimeoutExpired`。
  3. 按 `weight` 计算 `precision/recall/f1/false_alarm_rate` 和 `n_positive/n_negative_weighted`。
  4. 生成分组：厂商前缀、完整型号、容量段 `<6TB/6-<10TB/10-<14TB/>=14TB`、错误计数静默与否；若公开标签未来新增 `days_to_failure/failure_date/fail_date` 才生成距失效天数组，否则在 notes 说明跳过。当前标准 `train_labels.csv` 无失效日期，不能臆造 k。
  5. `fn_groups` 条目固定为 `{dimension,value,n,share,group_recall}`；`fp_groups` 固定为 `{dimension,value,n,weighted_n,share,group_far}`。按 `n >= analysis_min_group_count` 抑制小格，分别按 `n`/`weighted_n` 降序取全局前 5。
  6. `silent_share` 为 FN 中 cutoff 最新快照的 5/187/197/198 raw 全部为 0 或缺失的比例；返回：
     `{"dev_metrics": {...}, "fn_groups": [...], "fp_groups": [...], "silent_share": float|null, "notes": str}`。
  7. `finally` 删除候选和预测临时文件；画像中不得包含路径、序列号、原始 SMART 值。
- 新增 `cleanup_analysis_data() -> None`，删除缓存临时目录并清空 DataFrame 引用；引擎与 CLI 均在 `finally` 调用。
- 新增 `objective_brief(task_spec) -> str`，固定说明 ROS 公式、三项 +0.01 的边际收益 `+0.5/+0.3/+0.2`、0.2% FAR 只约束 R@FAR、负样本权重约 10、机队正例率约 0.25%（标注“推算”）、概率校准时 F1 最优阈值约 `F1*/2`，并提醒画像只是 dev 线索、不能针对单一组过拟合。

## 4. 引擎数据流与 PR #4 兼容
### `src/faultevolve/cloud/engine.py`
- `initialize()` 用 `ObjectiveBriefProvider` 读取一次 `_objective_brief`；异常时记录 `objective_brief_failed{error_type}` 并使用空串，不中断。
- `run()` 重置 `RunMetrics` 后、进入主循环前调用 `_ensure_root_analysis()`：分析已评估的 init 节点，使第一轮生成即可获得画像；resume 时若 root 已有非空 `metric.analysis` 则不重复。
- 新增：
  ```python
  def _should_analyze_node(self, node: Node, previous_best_score: float) -> tuple[bool, str]: ...
  def _maybe_analyze_node(self, node: Node, previous_best_score: float) -> None: ...
  ```
  - 前置：配置开启、adapter 实现 `ErrorProfiler`、节点有效、尚无非空 analysis。
  - `new_best = score > previous_best_score`；`top_k` 按当前所有有效节点 `combined_score` 降序（同分按 node id）判断，`top_k=0` 禁用该触发器。
  - 触发条件为 `(on_new_best and new_best) or in_top_k`；每节点最多调用一次。
  - 调用前 `analysis_calls += 1`；耗时累加 `analysis_time_s`；非空则 `analysis_nonempty_count += 1`，复制 metric、写入 `metric["analysis"]`，再用 `tree.update_node_evidence()` 持久化；记录不含画像正文的 `analysis_complete{node_id,trigger,duration_s,nonempty}`。
  - 超时/异常只增加 `analysis_failures` 并记录 `analysis_failed{node_id,error_type,duration_s}`；不改 validity/score、不增加 iteration、不阻断反思或 Jev。
- `_run_one_iteration()` 创建 `OperatorContext` 后设置 `_objective_brief`；父节点画像仍由 `metric["analysis"]` 注入。
- `_evaluate_child()` 在更新 child evidence 前保存全局 best；更新 evidence 后、`selector.update_best_score()` 和 `_apply_reflection()` 前调用 `_maybe_analyze_node()`。这是 PR #4 的统一正常/审计/deferred 评估路径，不能把画像逻辑移回 `_run_one_iteration()`。
- `_attempt_repair()` 的评估未走 `_evaluate_child()`；在 repair evidence 落库后同样调用 `_maybe_analyze_node()`，再反思，避免 repair 刷新 best 却无画像。
- Jev 筛掉的 `ABANDONED` 节点不画像；deferred 只有真正由 `_flush_deferred()` 进入 `_evaluate_child()` 后才画像，且 `count_iteration=False` 语义保持不变。画像不进入 Jev prescreen state，不改变 prior、审计和 `evaluations_saved`。
- `run()` 的 `finally` 同时清理 smoke 与 analysis 临时目录。

## 5. 生成提示与反思
### `src/faultevolve/cloud/operators.py`
- `OperatorContext` 增加 `objective_brief: str` 和链式 `set_objective_brief(brief: str) -> OperatorContext`。
- `USER_MESSAGE_TEMPLATE` 在父方案前增加 `{objective_brief_section}`；仅非空时渲染 `## 评估目标与权衡`，用 `truncate_text(..., 2000)`。
- 画像 JSON 使用稳定键排序、`truncate_text(..., 3000)`，标题保持通用；附一句“聚合画像只作改进线索，不代表因果关系”。不得在本文件写领域词。

### `src/faultevolve/cloud/insights.py`
- 新增 `summarize_error_profile_diff(parent_analysis, child_analysis) -> dict[str, Any]`：以 `(dimension,value)` 比较通用 `fn_groups`，输出 `new_top_fn_groups`、`no_longer_top_fn_groups`、共同组 `share_delta`，并输出 `dev_metrics` 中共有数值字段的 child-parent 差；缺失画像返回空 dict。
- `LAYERED_REFLECTION_PROMPT` 增加 `## 聚合错例画像变化` JSON 段，并明确“不再位于 top 列表仅表示可能修复，不证明因果”；`reflect_with_llm()` 确定性生成并截断至 2000 字符。此处不新增推理调用，token 继续计入现有 `reflect` stage。

## 6. 计量、摘要、CLI
### `src/faultevolve/common/metering.py`
- `RunMetrics` 增加 `analysis_calls=0`、`analysis_failures=0`、`analysis_time_s=0.0`、`analysis_nonempty_count=0`。
- 增加属性 `analysis_nonempty_rate = analysis_nonempty_count / analysis_calls`（无调用为 `0.0`）；`to_dict()` 输出四个要求字段：`analysis_calls`、`analysis_failures`、`analysis_time_s`（3 位小数）、`analysis_nonempty_rate`（3 位小数）。
- 不把 analysis 子进程时间加入 `total_eval_time_s`；它自然包含在 wall time，并由独立字段报告。

### `src/faultevolve/common/schemas.py`
- `RunSummary` 增加同名字段及默认值；engine 构造 summary 时逐项赋值。旧摘要读取方继续用 `.get()`。

### `src/faultevolve/cli.py`
- 新增顶层命令：
  ```python
  @app.command("analyze")
  def analyze(
      task_dir: Path = typer.Argument(...),
      program: Path = typer.Option(..., "--program"),
      json_output: bool = typer.Option(False, "--json"),
  ) -> None: ...
  ```
- 加载 `EvolveConfig`，按 analysis 参数构造 `HDDAdapter`，先 `load_task()` 和 `static_check()`，再调用 `analyze(..., timeout_s)`；JSON 成功输出 `{"ok":true,"analysis":...,"analysis_time_s":...}`，失败只输出 `{"ok":false,"error_type":...}` 并 exit 1，绝不回显异常路径/子进程 stderr；`finally` 清理缓存。
- `run_local_evolution()` 构造默认 `HDDAdapter` 时传入 `dev_late_fraction/min_group_count`。

### `skill/fe-evolve-manager/scripts/report_run.py`
- 输出 `analysis_calls/failures/time_s/nonempty_rate`，并保持 Jev、smoke、token 分阶段字段兼容。

## 7. 离线测试
### 新增 `tests/test_error_analysis.py`
- `test_error_profiler_protocol_optional`：`analysis.enabled=true` + 无 `analyze` 的 FakeAdapter 跑 1 轮；完成且 calls/failures 均 0。
- `test_hdd_dev_split_no_eval_only_access`：合成 5 个 cutoff 日期、早晚均含正负例；spy 所有父进程读取路径，断言仅两个公开 train 文件；候选目录恰有四个契约文件且无 late 标签。
- `test_hdd_analysis_expected_groups`：20 FN（型号 A 12、B 8）、10 FP，期望 A 入 `fn_groups`、B 被抑制、指标按权重精确相等、返回中无任何 synthetic serial。
- `test_analysis_groups_small_cell_suppression`：9 个错误的组不输出，10 个输出。
- `test_days_to_failure_group_skipped_when_unavailable`：标准五列标签返回 notes，且无该 dimension。
- `test_analysis_written_to_metric_and_prompt`：FakeProfiler 返回固定画像；节点持久化 `metric.analysis`，`build_user_message()` 含画像 JSON 和线索免责声明。
- `test_analysis_top_k_and_new_best_gating`：构造 5 个有效节点、`top_k=2`；只有新 best 或当前 top2 被调用，同节点第二次不调用。
- `test_analysis_failure_nonfatal`：profiler 抛 `TimeoutError`；迭代仍完成，score 不变，`analysis_failed` 存在，failures=1。
- `test_jev_screened_candidate_not_analyzed`：MockJev skip 后 profiler calls 不变；`test_deferred_evaluation_analyzed_once`：flush 后恰调用一次且 iteration 数不增加。
- `test_objective_brief_in_prompt`：断言 ROS 边际、FAR 限定和“推算”出现；空 brief 不渲染标题。
- `test_reflection_includes_fn_diff`：父/子 top 组各一增一减，捕获 reasoning messages，断言 diff 段包含两类变化；反思仅一次调用。
- `test_analyze_cli_json`：patch profiler 返回固定画像，exit 0 且 JSON schema 精确；异常时 exit 1 且不含路径。
- `test_cloud_modules_remain_task_agnostic`：扫描 `engine.py/operators.py/insights.py`，禁止 HDD 领域词。

### 修改 `tests/test_config.py`
- `test_analysis_config_defaults_off`：旧 YAML 得到 `enabled=false/top_k=3`。
- `test_analysis_config_round_trip`：六个键经 YAML 与 `with_overrides()` 保留；越界 timeout、fraction、min count 校验失败。

### 修改 `tests/test_metering.py`
- `test_analysis_metrics_in_summary`：2 calls、1 failure、1 nonempty、1.25s → rate 0.5，字段精确。
- `test_analysis_does_not_change_token_or_eval_totals`：只加 analysis 指标时 `total_tokens==0`、`total_eval_time_s==0`。

### 修改 `tests/test_insights.py`
- 增加纯函数画像差分的空输入、增/减组、共同组 share delta 测试。
- 全量验证：`python -m pytest tests/`；不得运行真实 LLM/Jev，不读取真实 benchmark 数据。

## 8. Skill
### 新增 `skill/fe-error-analysis/SKILL.md`
- frontmatter 仅 `name/description`；正文依次为：何时使用、输入、前置检查、步骤、成功检查、失败处理、禁止事项。
- 何时用：召回偏低、`metric.analysis` 为空、refine 缺少定向依据。
- 输入：任务目录、候选程序、`analysis.*`、可选 `HDD_BENCH_DATA_ROOT`（仅指向含 public 文件的根）。
- 精确命令：
  1. `fe doctor --task-dir benchmark/hdd_mvp --json`
  2. `fe analyze benchmark/hdd_mvp --program benchmark/hdd_mvp/init.py --json`
  3. 开启配置后 `fe evolve local benchmark/hdd_mvp --mock -n 3 --json`
  4. `python skill/fe-evolve-manager/scripts/report_run.py <run>/fe.db <run>/run_summary.json`
  5. `python -m pytest tests/test_error_analysis.py -q`
- 成功检查：单程序 JSON 的 `fn_groups/fp_groups` 存在；摘要断言 `analysis_calls>0`、`analysis_nonempty_rate>0`；tree 至少一个有效节点有 `metric.analysis`；提示注入由指定 pytest 用例验证。
- 失败处理：超时则降低 `top_k` 或提高 timeout（不得超过 900）；全被抑制则保留聚合指标/增大 dev fraction，禁止把 `min_group_count` 降到 10 以下；列缺失只跳过对应分组；画像失败不重跑真实实验。
- 禁止事项：不得读取受禁数据、不得输出序列号/原始值、不得把 dev 指标写成节点 score、不得开启网络或真实 LLM。

### 更新 `skill/fe-evolve-manager/SKILL.md`
- 增加默认关闭的 analysis 配置、启用前先跑 `fe analyze`、额外墙钟成本说明、四个摘要字段及故障处理；保留 PR #4 Jev 命令和字段，不改筛选/审计流程。

## 9. 实施顺序与后续真实运行
1. Protocol/config → HDD profiler/objective brief → operator/reflection → engine 挂接 → metering/summary/CLI → 测试 → 两个 Skill/报告脚本。
2. 先跑新增定向测试，再跑全量离线测试；本 PR 不做真实 LLM/Jev/benchmark 进化运行。
3. 全部功能完成后的真实运行才报告：通用 §4.3 指标、`analysis_calls/failures/time_s/nonempty_rate`、best 节点 `fn_groups` 摘要、recall/F1/ROS 相对 PR #4、Jev 筛选与审计字段、各 stage token 和总 token；召回上升仅作期望，不设合并硬门槛。
