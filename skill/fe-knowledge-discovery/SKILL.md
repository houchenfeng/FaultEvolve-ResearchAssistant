---
name: fe-knowledge-discovery
description: 运行现象层知识发现（KD1）离线流程并核对发现指标与产物。
---

## 何时使用

- 在已有进化 run 上补跑或验证 `DiscoveryRound`
- 检查阴性对照、发现卡晋升与 `discovered_cards.jsonl`
- 确认发现 token 已计入 `total_tokens`
- **真实数据短程 discover**：已有完成的进化 run（有 `fe.db`），不想重跑进化，只想验证 `fe discover run --max-claims 2` 能否在 HDD MVP 公开数据上跑完（先 `fe data checkup`）
- **KD1-F / KD1-G 原子因子发现（与进化解耦）**：自动调优后 `discovery_rounds=0`，在**副本库**上用种子因子库 + 探索预筛；KD1-G 默认库 `hdd_v2.jsonl`（方向 `auto`、确认族≤2、确认比例 0.5），不重跑进化、不追 ROS
- **KD1-G preflight**：`--explore-only` 跑到探索冻结前，零 LLM、不访问确认集标签，用于库可执行性与功效门体检
- **沙箱失败排查 / 修复后复测**：短探针里 claim 全死在沙箱、或 `error_tail` 只有裸 `exit N` 时，修完发现帧或沙箱后按下方命令在**副本库**上重跑

## 输入

- 已完成至少一轮进化的 `fe.db`（`--run-id`）
- `discovery.enabled: true`（仅 `fe discover run` 子命令会强制开启；正常 `fe evolve` 默认仍为 false）
- toy 任务或 HDD MVP（mock 可用）
- 真实短程 run **必需**：任务目录（如 `tasks/hdd_kd`）、`--run-id`、`--runs-dir`（**副本**，禁止直接写原始 Run）、`--artifacts-dir`、`--env-file`（经环境变量加载 `DASHSCOPE_API_KEY`，禁止写入代码/日志/提交）
- 可选：`HDD_BENCH_DATA_ROOT` 指向公开数据根目录

## 命令

```bash
fe doctor --json --task-dir <task>
fe data checkup <task> --json --out "$FE_RUNS_DIR/datacheck"
fe discover run <task> --run-id <EXP> --json --mock
fe discover factors <task> --run-id <EXP> --runs-dir "$DST" \
  --library src/faultevolve/discovery/factor_library/hdd_v2.jsonl \
  --max-candidates 30 --max-confirm 2 --confirmation-fraction 0.5 \
  --min-explore-effect 0.05 --mock --json
fe discover factors <task> --run-id <EXP> --runs-dir "$DST" \
  --library src/faultevolve/discovery/factor_library/hdd_v2.jsonl \
  --max-candidates 30 --max-confirm 2 --confirmation-fraction 0.5 \
  --min-explore-effect 0.05 --explore-only --json
fe discover propose <task> --run-id <EXP> --runs-dir "$DST" \
  --max-candidates 12 --env-file "$ENV_FILE" --json
fe discover report <task> --run-id <EXP> --json > /tmp/kd_report.json
bash skill/fe-knowledge-discovery/scripts/run_mock_discovery.sh
python skill/fe-knowledge-discovery/scripts/check_discovery_summary.py <artifacts_dir>
```

### 发现统计回归（时间切分 + e-BH）

在改 `discovery/splits.py`、`discovery/stats.py`、`discovery/pipeline.py` 或锦标赛 `tests_catalog.py` 后，先跑离线单测（无需 DB、无需 API）：

```bash
pip install -r requirements.txt
python -m pytest tests/test_discovery_splits.py tests/test_discovery_stats.py tests/test_discovery_task_agnostic.py -q
```

**何时使用**：怀疑 `temporal_ok` 按行号折半、ISO 日期被当中位数数值处理，或 e-BH 在并列 e 值时漏拒。

**成功检查**（全部通过）：

- `test_temporal_halves_iso_date_strings`：唯一日历时间中点切分，而非行序或 `np.median`。
- `test_label_times_from_env_when_labels_drop_date` / `test_label_times_from_history_when_labels_drop_date`：`labels` 无日期列时仍从 `env_frame` 或 `history` 取时间。
- `test_ebh_equal_pair_rejects_both`：`ebh_reject([39, 39], 0.05)` 两项均为 True（扫描全部秩取最大可通过前缀，不在首个失败处停止）。
- `test_discovery_sources_task_agnostic`：discovery 包无任务专有硬编码词。

**行为约定（默认，无新配置项）**：

- 确认集 `temporal_ok`：通过 `label_times()` 解析 `labels[time_col]` → `env_frame["time"]` → `history` 按 unit 聚合；三者皆无可用日历时 `temporal_ok=null`（UNDETERMINED），**不会**用 `range(len(y))` 冒充时间。
- 锦标赛 `temporal` 检验：与 KD1 相同，调用 `temporal_halves()`（支持 ISO 字符串日期）。
- e-BH：`ebh_reject` 对降序 e 值扫描每个秩 k，取满足 `e ≥ m/(k·α)` 的最大 k，拒绝前 k 个假设（与 `docs/plans/KD1_IMPL_PLAN.md` §stats 一致）。

**失败处理**：任一条失败则停止晋升/发布结论；对照 diff 是否误恢复 `range(len(y))` 行序回退、`np.median(time)` 或 e-BH 循环中的 `break`。

### 真实数据短程 discover（HDD MVP）

**前置**：复制 run 目录再跑，避免污染原库；若副本里已有 claim 占用 insight 源节点，会出现 `claims_proposed=0`，需在**副本 DB** 内清理旧 claim 后再跑。

```bash
cp -r "$FE_RUNS_DIR/<id>" "$PROBE_RUNS/<id>"
timeout 900 fe discover run "$TASK_DIR" --run-id <id> --runs-dir "$PROBE_RUNS" \
  --artifacts-dir "$ART_DIR" --env-file "$ENV_FILE" --max-claims 2 --json
echo "exit=$?"
python skill/fe-knowledge-discovery/scripts/check_discovery_summary.py "$ART_DIR/<id>"
```

## 发现帧说明

- `history`：**每序列多行**（截到 `meta.json` 的 `history_days`，且 `date <= cutoff_date`），列为 schema 声明且文件头存在的全部列（含 `model`、`capacity_bytes`、SMART raw/normalized 等），**不是**每序列一行。
- `labels`：每序列一行，仅 `serial_number`、`label`；`model` 等不在 labels 帧里供沙箱读取时，必须在 `history` 中。
- 生成/翻译的 `feature_code` **只能**读取 `schema_note` 与 `history.columns` 中列出的列。

## 成功检查

- `neg_control_fpr <= 0.10`（report JSON 或 discover run JSON）
- `promoted_cards[*].id` 均以 `D-` 开头（若有晋升）
- `claims_tested >= 1`，或沙箱失败时每条 `sandbox_errors[*].error_tail` 含**异常类型与消息**（如 `KeyError: 'model'`、`feature() must return pandas.Series ... got ...`）。出现裸 `exit N` 视为缺陷，应查 `sandbox.py`。
- `benchmark/hdd_mvp/knowledge/cards.jsonl` sha256 与运行前一致
- `run_summary.json` 中 `discovery_tokens` 计入 `total_tokens`（完整 evolve 路径）
- **短程 discover 跑完**（discover-only 或无 run_summary 时同样适用）：
  - 进程退出码 **0**（非 124）
  - stdout JSON：`ok: true`、`round_finished: true`
  - 事件中有 **`discovery_round_finished`**；每个 `claim_proposed` 都对应 `claim_tested` 或 `claim_sandbox_failed`（无 claim 停在 `proposed`）
  - `<artifacts_dir>/<run_id>/discovery/` 存在 `phenomena.json`、`preregistration.json`、`controls.json`、`discovered_cards.snapshot.jsonl`
- 沙箱失败时 `error_tail` 为 stderr **末尾约 800 字符**（含 traceback 尾部或类型错误行）

## 故障处理

| 现象 | 处理 |
|------|------|
| 401/403 | 停止并报告密钥/权限 |
| 429/超时 | 4s/8s/16s 退避后跳过本轮 |
| 沙箱失败 | 看 stdout JSON 的 `sandbox_errors[*].error_tail`（stderr 末尾约 800 字符） |
| `KeyError: '<列>'` 且列在 `HDD_DATA_SCHEMA` | 发现帧缺列 → 查 `hdd_adapter.discovery_frames` 列列表 |
| `KeyError: '<列>'` 且列不在 schema | 生成代码发明了列 → claim 质量问题，不要改帧 |
| `must return pandas.Series` | 返回类型错误 → claim 失败，可降低 `max_claims_per_round` |
| `exit N (no stderr)` | 进程被杀或 `os._exit` → 查内存限制与超时 |
| exit 124 | 看 DB/`events.jsonl` 最后进度事件：`claim_sandbox_finished` / `claim_stats_started` / `claim_stats_finished` 判断卡在沙箱或统计 |
| `claims_proposed=0` | insight 源节点已被旧 claim 占用；在**副本**库清理 claim 或换 run |
| 沙箱失败率 >50% | 查 `claim_sandbox_failed` 的 `error_type`/`error`；降低 `max_claims_per_round`，检查 claim prompt |
| `claims_sandbox_failed == claims_proposed` 且无锦标赛 | 同上；events 中应有 `claim_sandbox_failed`，不应只有 `claim_proposed` |
| `discovery_controls_failed` | 不晋升；调大 `bootstrap_b` 或 `neg_control_repeats` |
| `discovery_skipped(no_provider)` | adapter 未实现 `DiscoveryDataProvider` |
| token 份额超限 | 降低 `every_n_iterations` 或 `max_token_share` |

## 机理层（KD2）

- 开启：`discovery.tournament.enabled: true`（需 `discovery.enabled` 与任务 `env_frame`）
- Mock：`bash skill/fe-knowledge-discovery/scripts/run_mock_tournament.sh`
- 核对：`python skill/fe-knowledge-discovery/scripts/check_tournament_summary.py <artifacts_dir>`
- 成功：`mechanism_tokens == tournament_tokens`；`certificates.json` 字段完整；`tournament_skipped` 时查 reason（`no_env` / `token_share` / `max_rounds`）

### 冻结声明复验：`fe discover replay-claim`

**何时用**：已对某条 **CONFIRMED** 库因子声明（如 `C-89f4bdd1-0010` / `HDD3_F10` 窗口末归一化热读数）完成 KD1 漏斗，需要在**不改分级、不重跑全库**的前提下做 LLM 审讯（零分）、KD2 对局、或公开数据转移报告。

**输入**：

- 副本 `fe.db`（`--runs-dir`）与**来源**发现产物中的 `discovery/data_audit.json`（必须含 `split_salt` 与 `confirmation_fraction`；缺则退出码 2，禁止猜测）
- `phenomena.json` 或 `funnel.json` 中该 `claim_id` 的冻结方向（`+`/`-`）
- 因子库行（默认 `hdd_v3.jsonl` 的 `HDD3_F10`）原样执行 `feature()`；禁止 holdout/test

**命令（离线 mock）**：

```bash
cp -a "$FE_RUNS_DIR/89f4bdd1" "$DST/89f4bdd1"
SRC=/path/to/faultevolve/runs/<run-id>
fe discover replay-claim benchmark/hdd_mvp --run-id 89f4bdd1 --runs-dir "$DST" \
  --claim-id C-89f4bdd1-0010 --factor-id HDD3_F10 \
  --library src/faultevolve/discovery/factor_library/hdd_v3.jsonl \
  --source-artifacts-dir "$SRC" \
  --artifacts-dir "$ART" --enable-tournament --interrogate --n-slices 16 --mock --json
fe discover replay-claim benchmark/hdd_mvp --run-id 89f4bdd1 --runs-dir "$DST" \
  --claim-id C-89f4bdd1-0010 --factor-id HDD3_F10 \
  --library src/faultevolve/discovery/factor_library/hdd_v3.jsonl \
  --source-artifacts-dir "$SRC" \
  --artifacts-dir "$ART_T1" --transfer-frame train_late --mock --json
```

**标志**：

- `--enable-tournament`：仅本命令进程内打开 KD2；不写 `DISCOVERED`、不晋升机理卡
- `--interrogate`：三角色 `KD_INTERROGATE_*` → `discovery/interrogation.jsonl`
- `--n-slices`：2–16（默认配置 4；真跑可对局用 16）
- `--transfer-frame`：`train_late` | `backblaze_public_train` | `val`（`val` 需 `--allow-val-transfer` 且日志警告）
- 禁止：`holdout`、`test` 作为转移帧名

**成功检查（管道跑完，非机制成立）**：

- 退出码 0；`cards.jsonl` / `discovered_cards.jsonl` sha256 与运行前一致
- 审讯：`interrogation.jsonl` ≥3 行；对局：`mechanisms_proposed >= 5` 或 `tournament_skipped` 含合法 reason
- 转移：`transfer_summary.json` 含 `ci_low`；Backblaze 数据缺失时 `transfer_skipped: backblaze_data_missing`（退出 0）

规划全文：`docs/plans/C89_WINDOW_END_SMART194_CAUSAL_DEBATE_TRANSFER_PLAN.md`。

## KD1-F：`fe discover factors` / `fe discover propose`

**何时用**：进化 run 已结束且 discovery 未跑（或要在副本上做因子漏斗）；LLM 只提案/翻译，**不打分**。

**输入**：

- 副本 `fe.db`（`--runs-dir` 指向副本，禁止写原库）
- 默认库：`hdd_v1.jsonl`（KD1-F）；KD1-G 用 `hdd_v2.jsonl`（≤30 条，`direction=auto` 除对照外；泳道 `confirm` / `diagnostic` / `control`）
- `--max-candidates 30`、`--max-confirm 2`（KD1-G 预注册）、`--confirmation-fraction 0.5`、`--min-explore-effect 0.05`
- **`--explore-only`**：探索冻结后停止；不写确认检验、不调蕴含 LLM；`data_audit.json` 记录上述选项
- **放宽轨（opt-in，默认与严格轨相同）**：`--track-label relaxed` 仅作审计标签；`--explore-incr-rule ci_low|point_gain`（默认 `ci_low`）；`--min-incr-ci-low`（默认 `0`，仅 `ci_low` 规则）；`--fdr-mode bh_ebh|bh_for_confirm_ebh_for_discover`（默认 `bh_ebh`）。产物 `data_audit.json` 与 `funnel_summary.json` 写入上述字段；stdout JSON 同步。不传则行为与改前一致。
- **禁止再确认**：kd1f 已看过确认集的 F004/F017/F018 及 `smart_1`/`smart_3` 最后值类变体不得进确认族；`lane=diagnostic` 不得冻结、不得看确认集

**命令（离线 mock，无 API）**：

```bash
cp -r "$FE_RUNS_DIR/<id>" "$DST/<id>"
fe discover factors benchmark/hdd_mvp --run-id <id> --runs-dir "$DST" \
  --library src/faultevolve/discovery/factor_library/hdd_v1.jsonl \
  --max-candidates 30 --max-confirm 3 --mock --json | tee "$DST/kd1f_factors.json"
fe discover report benchmark/hdd_mvp --run-id <id> --runs-dir "$DST" --json > "$DST/kd_report.json"
python skill/fe-knowledge-discovery/scripts/check_discovery_summary.py "$DST/<id>"
```

**成功检查**：

- 退出码 0；stdout JSON：`ok: true`、`round_finished: true`、`mode: "factors"`
- 产物：`<artifacts>/discovery/candidate_registry.jsonl`、`funnel_summary.json`、`data_audit.json`、`funnel.json`
- `funnel` 含各阶段计数（含 `power_gate`）；`funnel.json` 的 `detail` 含 `explore_effect`、`power_gate_pass`、`lane` 等
- preflight（`--explore-only`）：`claims_tested=0`；`claim_direction_frozen` 事件数 = 冻结数；`discovery_llm_error.count=0`
- 全流程：`claim_entailment` 事件齐全；`run_summary.json` 的 `entailment_tokens` 为实测值（非硬编码 0）
- `discovery_llm_error.count` 为 0 或带 `first` 摘要（多为 NaN→LR，修 K6 而非放宽阈值）
- 纯发现无 ROS 变化时，报告里 `tokens_per_score_gain` 为 `n/a`（见 fe-report-generation）
- 结局 A / A-弱 / B 写法见 `fe-report-generation`；完整成功（A）需 ≥1 条 confirmed/discovered 且带测得 AUROC/CI

**失败处理（KD1-G）**：见 `docs/plans/KD1G_NEXT_DISCOVERY_PLAN_2026-10-04.md` §8；功效门通过数为 0 时不要进全流程。预检中因子不可执行若因数据覆盖不足或构造性常数（非列名/写法错误），记为 outcome B 的负结果，**不使用修库名额**、不改因子库。

**`fe discover propose`**：仅写 `discovery/factor_proposals.jsonl`，不跑检验；真实运行需 `--env-file` 加载 `DASHSCOPE_API_KEY`。

**失败处理**：见 `docs/plans/KD_NEXT_RUN_PLAN_2026-10-04.md` §7；不得读 `data/holdout*`、不得 `--split test`、不得改 `benchmark/hdd_mvp` 受保护文件。

## KD1-H：`hdd_v3.jsonl` 新因子家族（24 条预注册）

自 §4 计量小修合入后，`fe discover factors` 写入的 `run_summary.total_tokens` 为 `engine.metrics.total_tokens`（含蕴含等全部 LLM token）；`discovery_tokens` 仍仅统计 `discover` 用途。KD1-H 及更早产物若 `total_tokens=0` 而 `entailment_tokens>0`，为旧口径，不回写。

**何时用**：KD1-G 预检为 outcome B 后要做**新一轮** HDD 因子发现；或要在冻结前核对种子库的覆盖/退化（§4.1）；或核对 SMART 列无标签覆盖普查。

**输入**：

- 公开数据根：`HDD_BENCH_DATA_ROOT`（指向 `benchmark/hdd_mvp/data`）或默认 `benchmark/hdd_mvp/data/public`
- 因子库：`src/faultevolve/discovery/factor_library/hdd_v3.jsonl`（**默认 CLI 库仍为 `hdd_v1.jsonl`**，必须显式 `--library`）
- 副本 `fe.db`：`--runs-dir` 指向副本目录（禁止写原库）
- 全流程才需要：`--env-file` 加载 `DASHSCOPE_API_KEY`

**命令（完整）**：

```bash
# 1) 无标签 SMART 覆盖普查（JSON  stdout，可选落盘）
python skill/fe-knowledge-discovery/scripts/hdd_coverage_census.py \
  --task-dir benchmark/hdd_mvp --json-out /tmp/hdd_census.json

# 2) 冻结前离线库检查（§4.1，不读 label；失败 exit 1）
python skill/fe-knowledge-discovery/scripts/check_factor_library.py \
  --library src/faultevolve/discovery/factor_library/hdd_v3.jsonl \
  --task-dir benchmark/hdd_mvp \
  --json-out /tmp/hdd_v3_preflight_table.json

# 3) mock 冒烟（无 API）
cp -r "$FE_RUNS_DIR/<id>" "$DST/<id>"
fe discover factors benchmark/hdd_mvp --run-id <id> --runs-dir "$DST" \
  --library src/faultevolve/discovery/factor_library/hdd_v3.jsonl \
  --max-candidates 30 --max-confirm 2 --confirmation-fraction 0.5 \
  --min-explore-effect 0.05 --mock --json

# 4) 探索预检（零 LLM，不访问确认集标签）
fe discover factors benchmark/hdd_mvp --run-id <id> --runs-dir "$DST" \
  --library src/faultevolve/discovery/factor_library/hdd_v3.jsonl \
  --max-candidates 30 --max-confirm 2 --confirmation-fraction 0.5 \
  --min-explore-effect 0.05 --explore-only --json

# 5) 预检 §4.2 全部满足后：全流程（只跑一次，固定库与 split_salt）
fe discover factors benchmark/hdd_mvp --run-id <id> --runs-dir "$DST" \
  --library src/faultevolve/discovery/factor_library/hdd_v3.jsonl \
  --max-candidates 30 --max-confirm 2 --confirmation-fraction 0.5 \
  --min-explore-effect 0.05 --env-file "$ENV_FILE" --json
fe discover report benchmark/hdd_mvp --run-id <id> --runs-dir "$DST" --json > "$DST/kd_report.json"
python skill/fe-knowledge-discovery/scripts/check_discovery_summary.py "$DST/<id>"
```

**成功检查**：

- §4.1：`check_factor_library.py` 输出 `"ok": true`；记录 `library_sha256`（与冻结库文件一致）
- §4.2 预检（`--explore-only`）：退出码 0；`proposed=24`；`executable≥22`；`duplicate_code=0`；`discovery_llm_error=0`；`claims_tested=0`；库 SHA256 与 §4.1 一致；功效门通过数 ≥1
- 全流程结局：见 `docs/plans/KD1H_NEW_FACTOR_FAMILY_PLAN_2026-10-04.md` §5（A / A-弱 / B）；报告含 P/R/F1 `n/a（无预测器）`、分阶段 token、`tokens_per_score_gain` 为 `n/a`（见 fe-report-generation）
- 离线单测：`python -m pytest tests/test_factor_library_hdd_v3.py -q`

**失败处理**：

- §4.1 任一条不过：**冻结前**仅可改实现细节（不换列/不换群体）或删条目并同步条数；禁止在看到探索效应后改库
- 预检不可执行或功效门为 0 → 记 outcome B，**不修库**、不换种子/ `split_salt`
- 401/403 → 停止并报告密钥/权限
- 429/超时 → 4s/8s/16s 退避
- 退出码非 0 → 先看 `<artifacts>/discovery/error.txt`
- 原 `fe.db` 字节/mtime 变化 → 作废并报告
- **禁止**：读 `holdout*`、`--split test`、把 `HDD2_F004`/诊断泳道当发现、改 `hdd_v1`/`hdd_v2`、改 stats/grading/预注册/沙箱门、重跑进化、伪造服务器结果

规划全文：`docs/plans/KD1H_NEW_FACTOR_FAMILY_PLAN_2026-10-04.md`（§2 库定义、§4 冻结流程、§6 编码范围）。

**下一步：**见 `docs/plans/KD1I_ORDER_SENSITIVE_FAMILY_PLAN_2026-10-04.md`。

## KD1-I：`hdd_v4.jsonl` 顺序敏感家族

**何时用**：HDD3 完整 B 后进行下一轮因子发现；或在冻结前核对 `hdd_v4` 的填补前覆盖、退化、K0 相关性和顺序敏感性。

**输入**：公开数据根 `HDD_BENCH_DATA_ROOT`（或 `benchmark/hdd_mvp/data/public`）；必须显式指定 `hdd_v4.jsonl`；副本 `--runs-dir`；仅全流程需要 `--env-file`。

```bash
python skill/fe-knowledge-discovery/scripts/hdd_coverage_census.py \
  --task-dir benchmark/hdd_mvp --json-out /tmp/hdd_census.json
python skill/fe-knowledge-discovery/scripts/check_factor_library.py \
  --library src/faultevolve/discovery/factor_library/hdd_v4.jsonl \
  --task-dir benchmark/hdd_mvp --family-prefix HDD4_ --order-sensitive HDD4 \
  --json-out /tmp/hdd_v4_preflight_table.json

cp -r "$FE_RUNS_DIR/<id>" "$DST/<id>"
fe discover factors benchmark/hdd_mvp --run-id <id> --runs-dir "$DST" \
  --library src/faultevolve/discovery/factor_library/hdd_v4.jsonl \
  --max-candidates 30 --max-confirm 2 --confirmation-fraction 0.5 \
  --min-explore-effect 0.05 --mock --json
fe discover factors benchmark/hdd_mvp --run-id <id> --runs-dir "$DST" \
  --library src/faultevolve/discovery/factor_library/hdd_v4.jsonl \
  --max-candidates 30 --max-confirm 2 --confirmation-fraction 0.5 \
  --min-explore-effect 0.05 --explore-only --json
# 预检全部通过后仅运行一次：
fe discover factors benchmark/hdd_mvp --run-id <id> --runs-dir "$DST" \
  --library src/faultevolve/discovery/factor_library/hdd_v4.jsonl \
  --max-candidates 30 --max-confirm 2 --confirmation-fraction 0.5 \
  --min-explore-effect 0.05 --env-file "$ENV_FILE" --json
fe discover report benchmark/hdd_mvp --run-id <id> --runs-dir "$DST" --json > "$DST/kd_report.json"
python skill/fe-knowledge-discovery/scripts/check_discovery_summary.py "$DST/<id>"
```

**成功检查**：离线表 `ok: true`，confirm 条目覆盖≥0.95、`nunique≥10`、众数占比≤0.95、`rhoK0<0.8`，控制可执行且非常数，代码哈希不重复；探索预检退出码 0，`proposed` 等于库实际条数、`executable≥proposed-2`、`duplicate_code=0`、`discovery_llm_error=0`、`claims_tested=0`、功效门通过数≥1，且库 SHA256 不变。全流程按 A/A-弱/B 记录；报告中 P/R/F1 为 `n/a（无预测器）`，分阶段 token 无则写 0 或“未记录”，每分 token 为 `n/a`，未核实种子明确写“未核实”，并列出 e-BH 名次、要求 e 和现象 e。

**失败处理**：冻结前仅按计划预写备选替换 (*) 条目，备选仍失败则删条并同步条数；预检 B 或完整 B 后不修库、不换种子；401/403 停止；429/超时按 4/8/16 秒退避；退出码非 0 先查 `<artifacts>/discovery/error.txt`；原 `fe.db` 字节或 mtime 改变则结果作废。

**禁止**：不得读 `holdout*`、使用 `--split test`、改已有因子库或统计判定与默认门；不得跑本计划 §7 合成功效研究；不得把密钥写入代码、日志或提交。

## 禁止

- 手工编辑仓库 `cards.jsonl` 或 run 内 `discovered_cards.jsonl` 冒充晋升
- 读取 `eval_only`/test/holdout
- 用 LLM 结论替代统计检验
- 写入 API 密钥
- 为修 `KeyError` 把 `history` 聚合成每序列一行
- 把沙箱失败改成静默成功或跳过
