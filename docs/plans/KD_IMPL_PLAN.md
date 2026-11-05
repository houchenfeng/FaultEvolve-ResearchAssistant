# KD 实施计划：让短程 `fe discover run --max-claims 2` 能在 HDD MVP 数据上跑完

基线：`origin/main` = f0d981a（已核实；本地 checkout 旧 3 个提交，已基于 origin/main 建分支）。
只做后端 + skill 文档。本计划不含代码实现，不要求启动服务器 run。
硬约束：不改 `benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md,data/}`；不读 `data/holdout*`；`discovery.enabled` 默认仍为 false；所有 `src/faultevolve/discovery/*.py` 必须通过 `tests/test_discovery_task_agnostic.py`（禁用词 `smart|serial|hdd|vendor`，大小写不敏感，含注释与 docstring；HDD 专属逻辑只能放在 `tasks/hdd_adapter.py`）。

## 0. 调查结论（对 PLAN_TASK 三个假设的核实）

| 假设 | 结论 |
|------|------|
| 1. `discovery_frames` 逐 serial 的 Python 循环很慢 | **成立，但只是次要瓶颈。** `hdd_adapter.py:962` 的 `chunk.apply(axis=1)`（逐行 lambda）和末尾 `for _, row in labels.iterrows(): history[history["serial_number"]==sn]`（每个 serial 全表布尔扫描，O(N_serial × N_rows)）都应向量化。 |
| 2. Spearman + 500 次 bootstrap 在大 frame 上跑不完 | **部分错误。** `max_abs_spearman`（`stats.py:151`）作用于每 serial 一行的特征向量与 baseline 矩阵，只有约 3 万个点，很便宜；`ConstantInputWarning` 只是常数列的警告，不是卡死原因。**真正的卡死点是 bootstrap 的二次复杂度**（见下）。 |
| 3. 沙箱只存 stderr 头部 | **成立。** `sandbox.py:175` 是 `proc.stderr.decode(errors="replace")[:200]`；`pipeline.py:164` 事件里再 `[:200]`。pandas traceback 开头是 `indexes/base.py get_loc`，真正的 `KeyError: '...'` 在末尾。 |

### 0.1 真正的瓶颈：bootstrap 内层 `np.where(groups == g)`
`stats.py` 中 `group_bootstrap_ci`（约 L38–68）和 `incremental_auroc`（约 L169–221）的 bootstrap 循环都是：

```python
sampled = rng.choice(unique_groups, size=len(unique_groups), replace=True)
idx_parts = [np.where(groups == g)[0] for g in sampled]
```

每次重采样对每个被抽中的 group 做一次 `groups == g` 全数组比较，复杂度 O(G²)/次，共 `bootstrap_b`(500) 次。HDD 公开 train_labels 有约 31,094 个 serial（`labels` 已 `drop_duplicates(serial_number)`，所以 **每个 serial 只有一行，groups 即 serial**）；explore 集约 70%≈2.2 万 group：`500 × 2.2e4 × 2.2e4 ≈ 2.4e11` 次元素比较，单核数小时。这与"单核 100% 占用直到被 kill、claim 停在 `proposed`、没有 `claim_tested` 事件"完全吻合（`incremental_auroc` 在 `claim_tested` 事件之前，`pipeline.py` 约 L196–210）。
`tournament.py` 约 L340–365 也通过 `icp_check` / bootstrap 复用这些函数，修完自动受益。

### 0.2 "每个 serial 一行"的建议：检验样本已经是了，不要压扁 history
- 检验读的样本（`feat`、`y_all`、`groups_all`）来自 `labels`，本来就是每 serial 一行；**统计检验的样本不需要再缩**，缩的是 bootstrap 的实现方式。
- `frames.history` 仍是多行时序（沙箱里的 claim `feature_code(history)` 需要时序，例如 groupby 后取斜率）。把 history 压成每 serial 一行会破坏 claim 语义，**不这样做**。只做：向量化构建 + 截尾窗口（见 §2.2）。

### 0.3 其他核实到的事实
1. `cli.py` 的 `discover_run` 接受 `--artifacts-dir`，但**从未使用它，也从未调用 `kd.write_artifacts()`**（`pipeline.py:342`）。所以探针 run 即使跑完，artifacts 目录也是空的。这是"跑完"判定的缺口，必须补。
2. `discover_run` 的 JSON 只有 `claims_proposed/claims_tested/neg_control_fpr/promoted_cards`，没有 `claims_sandbox_failed`、`round_finished`、耗时，短程 run 结束后无法判断是"0 个成功"还是"沙箱全挂"。
3. `pipeline.py` 约 L177 的 `np.random.default_rng(hash(claim.prereg_hash) % 2**32)`：`hash(str)` 随进程变化，不可复现。**不要改**（KD1 测试依赖；KD2 已用 `seed_from`），只在文档里注明。
4. `sandbox.py:173` 的 `"timeout" in str(proc.stderr)` 会把 traceback 里碰巧含 "timeout" 字样的普通异常误判为超时；修 stderr 时一并收紧为仅 `returncode == -9`（真正超时由 L199 的 `subprocess.TimeoutExpired` 分支处理）。
5. `docs/plans/` 已是本仓库存放 `*_IMPL_PLAN.md` 的既定位置，因此本计划放在 `docs/plans/KD_IMPL_PLAN.md`，未新增文档类别。

## 1. 文件与函数改动清单

### 1.1 `src/faultevolve/discovery/stats.py`（行为不变，只换实现）
- 新增私有 `_group_index_parts(groups) -> tuple[np.ndarray, list[np.ndarray]]`：`uniq, inverse = np.unique(groups, return_inverse=True)`；`order = np.argsort(inverse, kind="stable")`；按 `np.bincount(inverse)` 的累计边界 `np.split(order, cuts)` 得到 `parts[k]` = 第 k 个 group 的行下标。**只算一次**，在 bootstrap 循环外。
- 新增私有 `_resample_index(parts, uniq_len, rng) -> np.ndarray`：`sampled = rng.integers(...)` 不可用（会改变 RNG 流）；必须保持 **`rng.choice(unique_groups, size=len(unique_groups), replace=True)` 同样的调用**得到 group 值，再用 `np.searchsorted(uniq, sampled)` 映射到 `parts` 下标，`np.concatenate([parts[i] for i in pos])`。这样每次重采样 O(n)，且**与旧实现逐位相同的重采样序列**。
- `group_bootstrap_ci` 与 `incremental_auroc` 的 bootstrap 循环改用上述两个函数。输出（lo/hi/gain）必须与旧实现完全一致（同一 rng 种子）。
- `max_abs_spearman`：对常数列（`np.ptp` 为 0 或有限值少于 3）直接 `continue`，避免 `ConstantInputWarning`；结果不变（原来常数列得到 NaN 被跳过）。
- 可选（推荐）：`incremental_auroc` 的 `LogisticRegression(max_iter=200)` 在约 2 万行 × 约 75 列上 3 折也是秒级，无需改；只要 bootstrap 修好即可。coding agent 用计时验证，不要先入为主再优化。

### 1.2 `src/faultevolve/tasks/hdd_adapter.py::HDDAdapter.discovery_frames`（约 L962）
- 保持返回的 `DiscoveryFrames` 字段与 `labels`/`env_frame` 语义不变。
- 去掉 `chunk.apply(axis=1)`：`cut = chunk["serial_number"].map(cutoff_map)`；`chunk = chunk[chunk["date"] <= cut]`（日期是 ISO 字符串，字典序比较与原 lambda 一致；`cutoff_map` 缺失时原逻辑是"保留"，用 `cut.fillna(chunk["date"])`）。
- 去掉 `for _, row in labels.iterrows(): history[history["serial_number"]==sn]`：先一次性计算 `censor = history.groupby("serial_number")["smart_187_raw"].max().gt(0)`（无该列或 history 为空则全 0），再用 `labels["serial_number"].map(censor).fillna(False).astype(int)`；`env`/`conf`/`time` 用向量化的字符串操作生成，结果与旧逻辑逐行一致。
- 截尾窗口（**新行为，需测量后决定保留**）：读取 `meta.json` 的 `history_days`（默认 14；`_get_data_dir` 同级 `meta.json` 不存在时用 14），只保留每个 serial 最后 `max(history_days, baseline_lag_rows + 1) + 1` 天内的行（相对该 serial 的 cutoff）。理由：`build_baseline_features` 只用最后 `baseline_lag_rows+1=15` 行；沙箱会把整个 history `to_pickle` 落盘并在 4GB `RLIMIT_AS` 下反序列化，缩小它同时降低沙箱内存/耗时。若 coding agent 测得未截尾时向量化后已能在几十秒内完成且沙箱不吃紧，可只做向量化并在 PR 说明中省略截尾。
- 保留 `self._discovery_cache`。
- 读取 CSV 时给 `read_csv` 传 `dtype={"serial_number": "string"}` 不必要，不要动。

### 1.3 `src/faultevolve/discovery/baseline_features.py::build_baseline_features`
- 现为 `for unit, grp in history.sort_values(time_col).groupby(unit_col)` 且每 unit 循环所有列，Python 层 O(units × cols)。改为向量化：`sort_values([unit_col, time_col])` 后，对每列用 `groupby(unit_col)[c]` 的 `last()`、`nth(-1-lag_rows)`（或 `shift`）与 `apply(lambda s: ((s != 0) & s.notna()).sum())` 替换；输出列名 `{c}__last / {c}__diff{lag} / {c}__nz` 与 NaN→0 规则（`last` NaN→0，前值 NaN→0，行数不足 `diff=0`）**保持一致**。该文件也受任务无关测试约束，不得出现禁用词。
- 这是次要优化：如果计时显示它在 2 分钟内完成，可不改，但需在 PR 里写出实测数字。

### 1.4 `src/faultevolve/discovery/sandbox.py::run_feature`（约 L173–L178）
- 新增模块常量 `STDERR_TAIL_CHARS = 800`。
- `err_msg = decoded_stderr.strip()[-STDERR_TAIL_CHARS:]`，空则 `f"exit {returncode}"`。保留末尾（真正的异常行）。
- 超时判定只用 `proc.returncode == -9`（去掉 `"timeout" in str(proc.stderr)` 与 `"timeout" in err_msg.lower()` 两处基于文本的判定）。`error_type` 仍是 `SubprocessError`。
- `SandboxResult.error` 存 tail；不写入任何环境变量或密钥（沙箱 env 本就只有 PATH 等）。

### 1.5 `src/faultevolve/discovery/pipeline.py`
- `claim_sandbox_failed` 事件的 `"error": (sb.error or "")[:200]` 改为 `[-800:]`；`store.update_claim(... payload_json=json.dumps({"error": sb.error}))` 保持（已是 tail）。
- 在沙箱调用前后、`test_feature` 前后、`incremental_auroc` 前后各加 `self.log_event` 进度事件（只记 claim_id 与耗时秒数，`claim_sandbox_finished`、`claim_stats_started`），使卡在哪一步可从 `events.jsonl` 直接看出；不改统计逻辑、不改 claim 状态机。事件名新增，不影响关闭发现时的输出。
- 不改 `hash(claim.prereg_hash)` 那行。

### 1.6 `src/faultevolve/cli.py::discover_run`（约 L250–L318）
- 使用 `--artifacts-dir`：`art_dir = get_artifacts_dir(artifacts_dir, output_dir, run_id)`（与 `discover report` 的 L231 同一函数），在 `kd.run` 之后调用 `kd.write_artifacts(art_dir / "discovery")`（先核对 `write_artifacts` 期望的目录约定，与 `check_discovery_summary.py` 的 `art/discovery/*` 一致），并把 `art_dir` 写进 JSON。
- JSON 增加字段（只增不减）：`claims_sandbox_failed`、`round_finished: true`、`elapsed_s`、`artifacts_dir`、`sandbox_errors`（每个失败 claim 的 `{claim_id, error_type, error_tail}`，tail ≤800 字符）。
- 异常路径保持 `{"ok": false, "error_type": "DiscoverRunError"}`（不泄露栈/密钥），但在 stderr 不输出内容；可选把 `type(e).__name__` 放进 `detail`。
- 不改 `discover_report`、不改 `evolve` 命令、不改 `config.discovery.enabled` 默认值（`discover run` 内的强制开启是既有行为）。

### 1.7 Skill：`skill/fe-knowledge-discovery/SKILL.md`（更新，非新增）
仓库已有该 skill（KD1/KD2 版本，主要是 mock 用法）。补充"真实数据短程 discover"章节，必须包含：
- 何时使用：已有完成的进化 run，想在不重跑进化的前提下补跑发现；先 `fe data checkup`。
- 输入：`<task_dir>`、`--run-id`、`--runs-dir`、`--artifacts-dir`、`--env-file`（含 `DASHSCOPE_API_KEY`；只通过环境变量，禁止写入文件/日志）、`--max-claims 2`。
- 前置：**先复制 run 的 DB 再跑**（`cp -r <runs>/<id> <probe_runs>/<id>`），原库不动；已被旧 claim 占用 insight 源节点会导致 `claims_proposed=0`（探针第一次 338s 退出 0 的原因），复制库里如需重新提案，只能删除**副本**里的 claims，并在 PR/日志里说明。
- 精确命令：
  ```bash
  timeout 900 fe discover run <task_dir> --run-id <id> --runs-dir <probe_runs> \
    --artifacts-dir <art_dir> --env-file <env> --max-claims 2 --json
  echo "exit=$?"
  python skill/fe-knowledge-discovery/scripts/check_discovery_summary.py <art_dir>/<id>
  ```
- 成功检查（见 §4）。
- 失败处理表增行：sandbox 失败 → 看 `sandbox_errors[*].error_tail`（末尾异常行）；exit 124 → 看 `events.jsonl` 最后一个进度事件判断卡在 sandbox / stats / tournament；`claims_proposed=0` → insight 源节点被占用；401/403 → 停止报告；429 → 4/8/16s 退避。
- 禁止项保留（不读 holdout、不手改 cards、LLM 结论不替代统计检验）。
- 更新 `scripts/check_discovery_summary.py`：当 `run_summary.json` 不存在（discover 单独运行不产生）时，改为检查 `discovery/` 下文件；见 §3.4。

## 2. 行为变化（对外可见的）
1. 统计结果不变：同一 rng 种子下 `group_bootstrap_ci` / `incremental_auroc` 输出与旧实现逐位相同；只是耗时从 O(b·G²) 降到 O(b·n)。
2. `discovery_frames` 输出的 `labels`、`env_frame`、`baseline_cols` 不变；`history` 变为（可选）截尾窗口内的行，行数减少。若做截尾，需在 PR 描述里给出前后行数。
3. 沙箱失败错误保留尾部 ≤800 字符（原为头部 200）；事件与 claim payload 同步。
4. `fe discover run` 真正写 artifacts，JSON 多出若干字段。
5. 正常 `fe evolve` 且 `discovery.enabled: false` 时：无任何变化（`test_discovery_disabled.py` 保持通过）。

## 3. 测试（`python -m pytest tests/`，不需要网络/密钥，不读 holdout）

### 3.1 `tests/test_discovery_stats.py`（追加）
- `test_group_bootstrap_ci_matches_reference`：在测试内保留一份旧的朴素实现（`np.where(groups==g)`）作参照，用 200 个 group、含重复 group（每 group 1–3 行）的合成数据、固定种子，断言新旧 `(lo, hi)` 逐位相等（`==` 或 `np.isclose(rtol=0)`）。
- `test_incremental_auroc_matches_reference`：同上，参照实现只替换 bootstrap 部分，断言 `(gain, lo, hi)` 相等。
- `test_bootstrap_scales`：G=20000、每 group 1 行、`b=50` 时 `group_bootstrap_ci` 完成时间 < 10s（用宽松上限防抖；旧实现在此规模下会超过数分钟）。
- `test_max_abs_spearman_skips_constant_columns`：含常数列的 baseline，用 `warnings.simplefilter("error")` 不抛 `ConstantInputWarning`，结果等于去掉常数列后的结果。

### 3.2 `tests/test_discovery_sandbox.py`（追加）
- `test_stderr_tail_keeps_exception_line`：`feature_code` 里 `raise KeyError("needle_col")` 前先用深层调用/长 traceback（或先向 stderr 写 2000 字符再抛异常）使头 200 字符不含异常行；断言 `res.ok is False`、`"needle_col" in res.error`、`len(res.error) <= 800`、`res.error_type == "SubprocessError"`。
- `test_traceback_containing_word_timeout_is_not_timeout`：抛 `ValueError("timeout-like message")`，断言 `error_type == "SubprocessError"`，不是 `TimeoutExpired`。
- 真正的超时用例保持通过（`time.sleep` 超过 `timeout_s`）。

### 3.3 `tests/test_hdd_discovery_frames.py`（新增，HDD 专属，放 tests/ 不受任务无关测试限制）
- 在 `tmp_path` 里生成一个合成的迷你 `train_labels.csv` + `train_history.csv.gz`（约 50 个 serial，含 cutoff 之后的行、缺失 cutoff 的 serial、含 `smart_187_raw>0` 的 serial），用 `HDD_BENCH_DATA_ROOT` 或伪造 `task_spec.task_dir` 指向它。
- 断言：cutoff 之后的行被过滤；`env_frame.censor` 与朴素参照（逐 serial 循环）一致；`labels` 每 serial 一行；若做截尾，断言每 serial 行数 ≤ 窗口。
- 性能守卫：合成 2000 serial × 20 行时 `discovery_frames` < 5s。
- 不使用 `benchmark/hdd_mvp/data/`（避免依赖大文件；更不碰 holdout）。

### 3.4 `tests/test_cli_discover.py`（追加/调整）
- 用现有的 mock 与 fake adapter 跑 `discover run --mock --max-claims 2 --artifacts-dir <tmp> --json`：断言退出码 0、JSON 含 `round_finished == true`、`claims_sandbox_failed` 与 `artifacts_dir`，`<artifacts_dir>/<id>/discovery/` 下存在 `phenomena.json`、`preregistration.json`、`controls.json`。
- 沙箱失败场景（fake adapter 返回引发异常的 claim）：JSON 的 `sandbox_errors[0].error_tail` 含异常行。
- 保持 `test_discovery_disabled.py`、`test_discovery_task_agnostic.py` 通过。

### 3.5 整体命令
```bash
python -m pytest tests/ -q
cd benchmark/hdd_mvp && python evaluator.py init.py   # val ROS ≈ 22.81（回归确认，未改评估器）
```

## 4. 如何判断短程 discovery run 跑完了
全部满足才算完成（脚本化：扩展 `check_discovery_summary.py` 支持 discover-only 目录）：
1. 进程退出码 0（不是 124），且 stdout 有一行 JSON，`ok: true`、`round_finished: true`。
2. `events.jsonl` / DB 事件里出现 `discovery_round_finished`（`pipeline.py` 既有事件），并且每个 `claim_proposed` 都对应 `claim_sandbox_failed` 或 `claim_tested`（不存在停留在 `proposed` 的 claim）。
3. `claims_tested >= 1`，或 `claims_sandbox_failed == claims_proposed` 且每条都有 `error_tail`（含真实异常行，非 traceback 开头）。
4. `<artifacts_dir>/<id>/discovery/` 下存在 `phenomena.json`、`preregistration.json`、`controls.json`、`discovered_cards.snapshot.jsonl`。
5. `neg_control_fpr <= 0.10`（若阴性对照已运行）；`benchmark/hdd_mvp/knowledge/cards.jsonl` sha256 与运行前一致。
6. 耗时参考：帧构建 + 2 个 claim 的统计检验在服务器上应在 ~10 分钟内（原来 20 分钟仍未完成）。coding agent 在本地用合成数据给出 §3.3、§3.1 的计时数字即可，不要求真实服务器 run；服务器验证由协调者按 skill 命令另行执行。

## 5. 风险与注意事项
- 保证重采样与旧 RNG 流一致是关键：不要换成 `rng.integers`/`rng.multinomial`，否则 p 值、CI 会漂移，使已有证书/晋升卡片不可对比。
- 截尾窗口是唯一可能改变 claim 特征值的地方（依赖长历史的 claim 会不同）。默认保守：先向量化，测量后再决定是否截尾；截尾窗口≥`history_days`。
- `discover run` 现有 `except Exception` 会吞掉所有细节；新增字段不要包含原始栈或环境信息。
- 提交时按逻辑拆分：stats 向量化 → sandbox stderr → hdd_adapter/baseline 向量化 → CLI artifacts/JSON → skill 与文档。
