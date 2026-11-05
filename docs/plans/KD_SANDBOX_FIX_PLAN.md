# KD 沙箱修复计划：发现帧缺列 + 失败信息丢失

状态：仅计划，未改任何运行时代码。基线：`main` @ `27cce15`（PR #16）。
目标读者：另一个编码模型，照此可直接实现，无需再问。

## 1. 现象与核实结论

2026-09-29 服务器探针（副本库 `f9752fcd`，`--max-claims 2`）：退出码 0、`round_finished: true`，提出 2 条 claim，测试 0 条，沙箱失败 2 条，`skipped=no_tests`。

我读代码后的结论（以代码为准，不再依赖猜测）：

### 1.1 根因 A：发现帧的 history 只有 2 + 9 列，却对生成代码声明了几十列

`src/faultevolve/tasks/hdd_adapter.py` `discovery_frames`（约 963–1036 行）：

- `usecols = ["serial_number", "date"] + numeric_cols`，其中 `numeric_cols = [c for c in HDD_K0_COLUMNS if c in header_cols]`。`HDD_K0_COLUMNS`（约 120 行）只有 9 个 SMART raw 列。所以 `frames.history` 只有 `serial_number`、`date` 和这 9 列。
- `model` 只被用在 `labels`（`labels["model"]`）里造 `env_frame`，没有进 history。
- 同一个函数给出 `schema_note=HDD_DATA_SCHEMA[:800]`。`HDD_DATA_SCHEMA`（约 94 行）写明 history 有 `model`、`capacity_bytes`、22 个 raw 列、9 个 normalized 列。`translate_claim` 会把它喂给 LLM（`pipeline.py` 约 137 行，`mechanisms.py` 约 126 行）。
- 另一个来源：claim 的 `feature_code` 也可能来自进化节点的代码（`raw_claim` / 父子代码差分），这些代码是照完整 `train_history.csv` 写的，会读 `history['model']`。
- `sandbox.run_feature` 把 `frames.history` 原样 pickle 进沙箱（`sandbox.py` 约 175 行），所以 `history['model']` 必然 `KeyError: 'model'`。

结论：C-0001 的 `KeyError: 'model'` 直接由此产生。同类隐患不止 `model`：`capacity_bytes`、`smart_1/3/4/7/10/190/191/192/193/196/240/241/242_raw`、各 `*_normalized` 都在 schema 里、都不在发现帧里。schema 承诺与帧内容不一致，是根本问题。（`HDD_K0_COLUMNS` 里的 `smart_199_raw` 不在 `test_hdd_discovery_frames.py` 的合成数据中，是靠 `if c in header_cols` 过滤的，这一点要保留。）

### 1.2 根因 B：沙箱 runner 对“返回值不是 Series”直接 `sys.exit(3)`，不写 stderr

`sandbox.py` 的 `_RUNNER`（约 82–97 行）：

- `feature is None` → `sys.exit(2)`；`not isinstance(result, pd.Series)` → `sys.exit(3)`。两处都没有任何输出。
- 调用方（约 196–201 行）：`decoded.strip()[-800:] or f"exit {proc.returncode}"`，stderr 为空就存 `exit 3`。
- 所以 C-0002 的 `exit 3` 含义明确：`feature(history)` 正常返回，但返回的不是 `pd.Series`（很可能是单列 DataFrame、dict、ndarray 或 numpy 标量）。这不是“在写 stderr 之前就退出”，也不是空 stderr 覆盖了有用信息；是 runner 自己没写。信息在设计上就丢了。
- 另外：未捕获异常时 Python 会把 traceback 写到 stderr，尾部截断到 800 字。C-0001 这里没问题。但只保留“末尾 800 字”对长 traceback 会丢掉文件/行号的开头，可以接受，见 3.2。

### 1.3 第二条 claim 会不会也是缺列？

不能排除，也不必确定。修 A 之后，如果 C-0002 还会失败，就会带着真实原因（返回类型）失败，这正是 B 要保证的。

## 2. 不能做的事（约束）

1. 不能把 history 收成每序列一行。`labels` 已是每序列一行（`labels.drop_duplicates(subset=["serial_number"])`），claim 的时间语义（跨天差分、滚动、`date` 排序）依赖 history 多行。发现帧仍是每序列至多 `tail_rows` 行的多行帧。
2. PR #16 的成果不回退：
   - bootstrap 同一种子逐位一致（`stats.py`，以及 `seed_util.seed_from` 的确定性种子）；
   - Spearman 跳过常数列；
   - history 按 `history_days` 截尾：`tail_rows = max(history_days, lag_rows + 1) + 1`，`groupby("serial_number").tail(tail_rows)`；
   - 按 `cutoff_date` 过滤（`date <= cutoff`），不读 `eval_only` / holdout；
   - `baseline_cols` 仍是 K0 的 9 列（`baseline_features` 行为不变，避免改变新颖性检验基线）。
3. 不新增配置开关；这是现有发现路径的修复，直接改默认行为。
4. 不修改 `benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md}` 和 `data/`；不读 `data/holdout*`。
5. 得分仍只来自本地评测器；此修复不涉及打分。

## 3. 改动清单

### 3.1 `src/faultevolve/tasks/hdd_adapter.py`：让发现帧的列与 schema 一致

行为：`frames.history` 包含 `serial_number`、`date` 加上 **schema 声明的所有存在于文件头的 history 列**，而不仅是 K0 的 9 列。

具体做法：

1. 新增模块常量 `HDD_DISCOVERY_EXTRA_COLUMNS`（元组），列出 `HDD_DATA_SCHEMA` 中的全部特征列：`model`、`capacity_bytes`、schema 中列出的所有 `smart_*_raw` 与 `smart_*_normalized`。不要凭记忆写，直接对照 `HDD_DATA_SCHEMA` 文本逐个抄，并加单测保证两者一致（见 4.3）。
2. 新增 `HDD_DISCOVERY_COLUMNS = ("serial_number", "date") + 去重后的(HDD_K0_COLUMNS ∪ 额外列)`。
3. `usecols = [c for c in HDD_DISCOVERY_COLUMNS if c in header_cols]`（保持“文件头没有就跳过”的现有容错）。`serial_number`、`date` 必须存在，否则沿用当前报错行为（不新增静默兜底）。
4. 数值转换只作用于数值列：`model` 保持字符串（`astype("category")` 可省内存；沙箱用 pickle，category 可用，但为了让生成代码里 `history['model'].str...` 之类不出意外，**用 `object`/`string` 而非 category**，并在读取时用 `dtype={"model": "string"}` 或读入后 `astype(str)`，缺失值填空字符串 `""`）。`capacity_bytes` 与 SMART 列用 `pd.to_numeric(errors="coerce")`。
5. `numeric_cols` 变量继续只表示 K0 列并传给 `baseline_cols`，不要把新列混进去。新代码里另设变量（如 `numeric_history_cols`）用于转换。
6. 截尾、按 cutoff 过滤、排序、`censor_map` 的逻辑保持不动。`censor_map` 仍用 `smart_187_raw`。
7. `schema_note`：不再用 `HDD_DATA_SCHEMA[:800]`（截断会丢掉多数列名，还会在句中被切断）。改为由实际帧生成一段简短说明，例如新增 `_discovery_schema_note(history_columns)`：
   - 第一行：`history 每序列多行（最近 N 行，date <= cutoff），只含以下列，不要使用其他列：`；
   - 第二行起：`history.columns` 的实际列名（按类别分组：标识/时间、基本信息、raw、normalized）；
   - 说明 `labels` 只有 `serial_number,label`，不在 history 里。
   - 总长度控制在约 1500 字符内；不要再用 `[:800]` 硬切。
   这样“承诺”与“实际”由同一份 `history.columns` 派生，不会再漂移。

内存与耗时：history 已截到每序列约 16 行，列数从 11 增到约 35，`model` 字符串每行重复。按 `test_discovery_frames_performance_guard`（2000 序列 < 5 秒）核对；真实数据规模的内存在服务器探针里确认（见 5）。若探针发现内存或 pickle 体积成为问题，再考虑仅在每序列内保留，不要退回到每序列一行。

### 3.2 `src/faultevolve/discovery/sandbox.py`：失败一定带真实原因

改 `_RUNNER` 与错误汇总，不改静态检查、白名单、超时、覆盖率、常量校验逻辑：

1. runner 整体包进 `try/except BaseException`：出现异常时 `traceback.print_exc()` 写 stderr 后 `sys.exit(1)`。（目前未捕获异常已经写 traceback，这一步让格式和退出码稳定，并覆盖 `exec(open("feature.py").read(), ns)` 阶段的错误。）
2. `feature is None`：向 stderr 打印 `feature() not defined in feature.py` 再 `sys.exit(2)`。
3. 返回值不是 `pd.Series`：向 stderr 打印 `feature() must return pandas.Series indexed by unit, got <类型全名>` ，若是 `DataFrame` 补充 `shape=... columns=[...前 5 个]`，若是 `Series` 之外的有 `len` 的对象补充长度；再 `sys.exit(3)`。**不做自动转换**（不把单列 DataFrame 偷偷转 Series），避免悄悄改变 claim 语义；错误信息里可以提示 `df.iloc[:, 0]` 之类，但只是提示。
4. 调用方：保留 `[-800:]` 的尾部截断，但改为“最后一行异常 + 尽量保留 traceback”：
   - 若 stderr 非空：取 `stderr.strip()`；长度超过 `STDERR_TAIL_CHARS` 时保留末尾（异常行在末尾）。可把 `STDERR_TAIL_CHARS` 提到 2000，让 traceback 更完整；`cli.py` 里 `error_tail` 的 `[-800:]` 与 `pipeline.py` 的 `[-800:]` 保持一致地调整，或保留 800 但保证异常行在其中。二选一，全仓库一致即可，SKILL.md 同步。
   - 若 stderr 为空（现在只可能是 OOM 被杀、`os._exit`、段错误等）：错误文本写成 `exit <code> (no stderr)`，附带 `signal` 信息（`returncode < 0` 时 `-returncode` 是信号号）。不要只写裸 `exit 3`。
5. `returncode == -9` 当前一律判为 `timeout`。`subprocess.run(timeout=...)` 超时是抛 `TimeoutExpired`（已被外层 except 处理），`-9` 更可能是 OOM killer。保持 `error_type` 不变以免破坏现有测试，但错误文本改为 `killed by SIGKILL (timeout or out of memory)`。若现有测试断言 `error == "timeout"`，则不要改这条（见 4.2，先查再动）。
6. 外层 `except Exception as e: str(e)[:200]` 保留，但把 `type(e).__name__` 放进文本前缀，方便读。

### 3.3 `src/faultevolve/discovery/pipeline.py`、`src/faultevolve/cli.py`

- `pipeline.py` 约 162–175 行：日志事件里的 `error` 用 `err_tail`；DB `payload_json` 存完整 `sb.error`（现状即如此，保持）。补充一个字段 `stage="sandbox"`。可选：把 `sb.duration_s` 也记入事件。
- `cli.py` 约 315–325 行的 `sandbox_errors` 结构不变，只随 3.2 的截断长度调整。
- 不改 `round_finished`、`skipped` 语义。全部 claim 沙箱失败时仍是 `no_tests`，探针可以仍然退出码 0。

## 4. 测试计划（新增；不删、不削弱现有测试）

先在**当前代码**上让新测试失败，再实现后通过。提交顺序：先提交测试并确认红，再提交修复。

### 4.1 `tests/test_hdd_discovery_frames.py`（追加，不改已有两个用例）

- 扩展合成数据写入函数为“带 `model`、`capacity_bytes`、`smart_1_raw`、`smart_1_normalized`、`smart_199_raw`”的新 helper（**新增** helper，不修改现有 `_write_synthetic_dataset`，以免影响旧用例）。
- `test_discovery_history_contains_schema_columns`：断言 `frames.history` 含 `model`、`capacity_bytes`、`smart_1_raw`、`smart_1_normalized`；`model` 为字符串；当前行为下失败（缺列）。
- `test_discovery_history_stays_multirow`：每序列行数 > 1 且 `<= tail_rows`，`len(frames.labels) == n_serial`，`labels` 只有 `serial_number,label`（防止被收成一行）。
- `test_discovery_baseline_cols_unchanged`：`frames.baseline_cols` 只含 K0 列（防止新列混入基线）。
- `test_discovery_schema_note_matches_frame`：`schema_note` 中出现的每个列名都在 `history.columns`；`history.columns` 里除 `serial_number`/`date` 外每列都出现在 `schema_note`；长度上限。
- `test_schema_columns_match_hdd_data_schema`：`HDD_DISCOVERY_EXTRA_COLUMNS` 等于用正则从 `HDD_DATA_SCHEMA` 抽出的 history 特征列集合（防止两处漂移）。
- 用例：文件头缺少某个 schema 列（如没有 `capacity_bytes`）时不报错，仅跳过。
- 现有 `test_discovery_frames_performance_guard` 必须仍然通过（< 5 秒）。

### 4.2 `tests/test_discovery_sandbox.py`（追加）

- `test_non_series_return_reports_type`：`feature` 返回 `history.groupby('unit')[['m1']].last()`（DataFrame），断言 `not ok`、`error_type == "SubprocessError"`，`error` 包含 `DataFrame` 和 `pandas.Series`，且**不等于** `exit 3`。当前行为下失败。
- `test_missing_feature_reports_message`：代码里定义 `def feature(` 但通过 `feature = None` 之类使 `ns.get("feature") is None`（静态检查要求含 `def feature(`，可用被覆盖的方式构造），断言错误文本非裸 `exit 2`。
- `test_keyerror_traceback_preserved`：读不存在的列，断言 `error` 含 `KeyError` 与列名。
- `test_silent_exit_reports_signal_or_no_stderr`：构造无 stderr 的非零退出（如 `raise SystemExit(5)` 放在 `feature` 内），断言文本含 `exit 5` 且含 `no stderr`。
- 先查现有测试对 `timeout` 文案的断言（`grep -n timeout tests/test_discovery_sandbox.py`），保持通过。

### 4.3 `tests/test_cli_discover.py` 或 `tests/test_discovery_controls.py` 中的管线级测试（追加）

- 用 mock 适配器（参考 `test_cli_discover.py` 约 225 行的 `discovery_frames` 覆写方式）构造：一条 claim 读取 `history['model']`（帧含该列）→ 应进入 `claim_tested`；一条 claim 返回 DataFrame → `claim_sandbox_failed`，事件 `error` 含 `DataFrame`。断言 `discovery_round_finished` 事件存在，`sandbox_errors[*].error_tail` 不是裸 `exit N`。
- 断言“同一种子 bootstrap 逐位一致”的现有测试保持不变。

### 4.4 回归

`python -m pytest tests/` 全绿；`cd benchmark/hdd_mvp && python evaluator.py init.py` 的 val ROS 仍约 22.81（此处只做确认，本修复不触及评测器）。

## 5. 验收（怎样算修完）

服务器上用副本库重跑同样的短探针：

```bash
timeout 900 fe discover run /home/hcf/faultevolve/tasks/hdd_kd \
  --run-id f9752fcd \
  --runs-dir /home/hcf/faultevolve/kdprobe_runs \
  --artifacts-dir /home/hcf/nas_hcf_data/faultevolve/runs/kd_probe2 \
  --env-file /home/hcf/faultevolve/.env \
  --max-claims 2 --json
echo "exit=$?"
python skill/fe-knowledge-discovery/scripts/check_discovery_summary.py /home/hcf/nas_hcf_data/faultevolve/runs/kd_probe2/f9752fcd
```

（副本里已有旧 claim 会占用 insight 源节点导致 `claims_proposed=0`，需在副本 DB 清理旧 claim 或换新副本，见 SKILL.md。）

通过标准：

- 退出码 0，JSON `round_finished: true`。
- 不再出现“两条都因缺列（`KeyError: '<history 中 schema 承诺的列>'`）死在沙箱”。至少一条 `claim_tested`，或者沙箱失败的原因不是 schema 已承诺的缺列。
- 每条沙箱失败 claim 的库内 `payload_json.error` 与事件 `error` 是真实 traceback 末尾或明确的类型错误说明，**不是**裸 `exit N`。
- 不要求本次探针一定产出机制或证书。

## 6. 更新 `skill/fe-knowledge-discovery/SKILL.md`

让其它智能体能自主跑发现。保留现有章节结构，做以下补充或修改：

1. **何时用**：补一条“沙箱失败排查/修复后复测”场景；说明“已有完成的 evolve run（有 `fe.db`），想在不重跑进化的情况下验证发现路径”。
2. **输入**：列出必需项：任务目录（如 `tasks/hdd_kd`）、`--run-id`、`--runs-dir`（副本，禁止直接用原始 Run）、`--artifacts-dir`、`--env-file`（只经环境变量加载 `DASHSCOPE_API_KEY`）；注明 `HDD_BENCH_DATA_ROOT` 可选。
3. **确切命令**：给出完整可复制的“复制副本 → 跑 → 检查”三步（上文第 5 节的命令，用 `$VAR` 占位而不是硬编码 hcf 路径），含 `timeout 900` 与 `echo "exit=$?"`。
4. **发现帧说明**（新增小节）：history 为每序列多行（截到 `history_days`，`date <= cutoff`），列为 schema 声明的全部列；`labels` 每序列一行；生成代码只能读这些列。
5. **成功检查**：把现有条目里“`error_tail` 含真实异常行（非 traceback 开头）”改为明确说法：`error_tail` 必须包含异常类型与消息（如 `KeyError: 'x'`）或 `feature() must return pandas.Series ... got ...`，出现裸 `exit N` 视为缺陷，需回到 `sandbox.py` 排查；同时更新截断长度描述（与 3.2 保持一致）。
6. **故障处理表**新增行：
   - `KeyError: '<列>'` 且该列在 `HDD_DATA_SCHEMA` 中 → 发现帧缺列，属于本次修复范围的回归，去查 `hdd_adapter.discovery_frames` 的列表；该列不在 schema 中 → 生成代码发明了列，属 claim 质量问题，不要改帧。
   - `must return pandas.Series` → 生成代码返回类型错误，不改代码，记为 claim 失败，必要时降低 `max_claims_per_round`。
   - `exit N (no stderr)` → 进程被杀或 `os._exit`，查内存限制与超时。
7. **禁止**新增两条：不要把 history 聚合成每序列一行来“修” `KeyError`；不要把沙箱失败改成静默成功或跳过。
8. 更新 `scripts/check_discovery_summary.py`（这是 skill 脚本，不是运行时代码）：新增检查——`claims_sandbox_failed > 0` 时每条 `error_tail` 不得匹配 `^exit \d+$`。需先读现有脚本再改，并补一个对应小测试（可放在 `tests/`，纯 JSON 输入）。

## 7. 实施顺序（给实现者）

1. 从最新 `main` 开分支（`git fetch origin main`）。
2. 先写 4.1–4.3 新测试并确认在当前代码上失败。
3. 实现 3.1，跑 `tests/test_hdd_discovery_frames.py`、`tests/test_discovery_*.py`。
4. 实现 3.2、3.3。
5. 改 SKILL.md 与检查脚本（第 6 节）。
6. 全量 `python -m pytest tests/`，再做 val ROS 确认。
7. 提交拆成：测试、帧修复、沙箱修复、skill 更新，四个逻辑提交；开 PR，PR 里贴探针 JSON（不含任何密钥）。

## 8. 风险与开放点

- 列名清单与 `HDD_DATA_SCHEMA` 的一致性靠 4.1 的单测守住；真实数据文件头若缺某列，走跳过逻辑。
- `model` 作为字符串列进入 pickle 会增大沙箱输入；先按规模验证，不要因此改回单行。
- 是否把 stderr 尾部长度从 800 调到 2000：可选，改的话 `sandbox.py`、`pipeline.py`、`cli.py`、SKILL.md 必须同步。
- 本计划不处理 `pipeline.py` 约 188 行 `np.random.default_rng(hash(claim.prereg_hash) % (2**32))` 的问题：`hash()` 对字符串受 `PYTHONHASHSEED` 影响，跨进程不稳定。这与本次故障无关，但与“bootstrap 逐位一致”的目标相关。请实现者先确认 PR #16 的“逐位一致”测试实际覆盖了哪条路径；若发现跨进程不一致，单独开 issue，不要混进本次修复。
