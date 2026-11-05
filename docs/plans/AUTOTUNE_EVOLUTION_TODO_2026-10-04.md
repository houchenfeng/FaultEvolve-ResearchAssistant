# 自动调优与进化搜索 实施计划 / TODO

更新时间：2026-10-04（北京时间）。**状态：E0～E2 首版已合入本分支（默认全关）；E3/E4/E5/K1 未开始。NAS 版本差异 BLOCKED，未跑付费真实进化。**
设计入口：[自动调优与进化搜索改进设计](../design/06-自动调优与进化搜索改进设计.md)（服务器检出时文件名为 `04-autotune-design.md`，因 `docs/design/04-*` 已被占用，入库编号为 06）。
Agent 入口：[`skill/fe-autotune-plan/SKILL.md`](../../skill/fe-autotune-plan/SKILL.md)。

最新优先级：**可复现基线（E0）→ 结构化调参（E1）→ 局部编辑与反馈（E2）→ 多样化冷启动/岛屿（E3）→ 本地异步（E4）→ 受限 RSI（E5）→ 恢复 KD1（K1）**。
历史 `docs/TODO.md` 中 9 月的已做/待做状态不能直接作为当前服务器状态。

本文约定：

- **E0、E1、E2 已写到可直接实施的粒度**（文件、接口、开关、测试、禁区）。**E3、E4、E5、K1 只写到设计已经决定的程度**，凡设计未决定处标记为【设计未定】，实施前必须先补设计，不得由实施者自行拍板。
- 凡写成"建议值/默认值"的数字，是本计划为让实施可落地给出的**起始提案**，不是设计结论，也不是实验结果；E0 的冻结协议（§3.7）负责最终确定并写入仓库，之后不得在同一比较内更改。
- 本文**不包含任何实验结果**。所有结果表留空，由真实运行填写。历史最优 ROS 38.14 只是一个**历史观察点**（运行于不同代码/开关/seed/预算，且 NAS aligned 与本地主仓库实现不同），**不是当前基线**，也不是目标上限。当前基线只能由 E0 在冻结版本上重新测得。
- 与伐谋（Famou）的对比、FM Agent 论文数字：不可与 HDD ROS 直接比较；同任务官方分数表尚空，写"未比较"。

---

## 0. 规划阶段已完成的工作

- [x] 核对本地 Git（设计基于 `9a3643f`；本计划写作时 main 为 `d96366e`，与前者仅差一份文档 `KD_WHY_NO_KNOWLEDGE.md`）、NAS aligned、四个主要真实运行摘要（来自设计文档 §2，未在本仓库内复核其原始文件）。
- [x] 明确 ROS 与 FM 的其他 benchmark 指标不可直接比较；当前伐谋同任务对照表未填写。
- [x] 检索 FM、MLE-STAR、AlphaEvolve、ShinkaEvolve、GEPA、autoresearch、DGM 及 2026 年 MGM/AIDE²/PCPO 来源（见设计 §3）。
- [x] 建立设计文档与本计划；**没有**执行新真实进化、HPO 或 RSI。
- [x] 依据当前 main 代码核对本计划引用的接点（见 §1.3），并把设计文档中的"规划路径"落实为具体文件。

---

## 1. 总览、前提与全局不变量

### 1.1 阶段表

| 阶段 | 交付 | 依赖 | 验收后才进入下一步 | 状态 |
|---|---|---|---|---|
| E0 | 版本/指标/预算基线 | 无 | 一个 Git 版本、一个冻结实验协议和可追溯运行摘要（§3.9 退出门） | 进行中（代码+文档；NAS BLOCKED） |
| E1 | 参数空间与 seeded random HPO | E0 退出门通过 | 无 LLM 的参数 trial 可正确计账、复现、导出独立程序（§4.10） | 首版已交付（默认关） |
| E2 | 局部 patch 与结构反馈 | E1 | patch 可定位、拒绝可审计、拒绝成本仍计账（§5.10） | 首版已交付（SEARCH/REPLACE；默认关） |
| E3 | 多起点、档案和 2～3 个逻辑岛 | E2 | 多样性真实存在；同预算不靠免费种子提高结果 | **未开始**（仅粗规格，§6） |
| E4 | 单 writer、本地异步 | E0/E3 | 成本/恢复/资源测试通过，实测吞吐提高 | **未开始**（仅粗规格，§7） |
| E5 | 小型 RSI 策略实验 | E2/E3；E4 可选 | 固定元预算、合格任务集和独立保留任务 | **未开始**（§8） |
| K1 | 恢复现象因子发现 | E2 + KD 验证修复 | 固定强基线、原子假设、独立确认链 | **未开始**（§9） |

最小可交付版本为 **E0～E2**。岛屿、分布式和 RSI 都不是完成最小版本的前提。

### 1.2 全局不变量（每个 PR 都必须满足，违反即回退）

| # | 不变量 | 如何检查 |
|---|---|---|
| G1 | 不修改受保护基准：`benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md}`、`prepare_data.py`、`knowledge/cards.jsonl`、`data/`（含 `data/meta.json`）。 | `python -m pytest tests/test_hdd_protected_files.py -q` 必须通过；`git diff --stat -- benchmark/` 为空（E0 的 manifest 文件不得写入 `benchmark/`）。 |
| G2 | 永不读取、打印、上传 `benchmark/hdd_mvp/data/holdout*`；HPO/dev/消融代码也不得读取 `data/eval_only/`（val 标签）。 | §4.4 的路径守卫 + `tests/test_autotune_data_guard.py`。 |
| G3 | 秘密只来自环境变量（`DASHSCOPE_API_KEY`、`TYPESAFE_API_KEY`、`FE_API_KEY`）；不写入代码、配置、测试、日志、manifest、提交。 | manifest 生成器内置字段白名单 + 测试扫描（§3.6）。 |
| G4 | 分数只来自本地 evaluator（经 adapter 的完整 `val` 评估）。LLM/Jev 输出、dev 代理分、消融分、缓存命中都**不得**写入 `combined_score`、不得更新全局 best。 | §4.6 的存储断言 + §5.9 测试。 |
| G5 | **不改动发现统计**：不修改 `src/faultevolve/discovery/**` 的任何文件；不修改 `DiscoveryConfig` / `TournamentConfig` 的默认值与校验；**不提高** `discovery.tournament.n_slices`（当前默认 4，范围 2～16）和 `discovery.bootstrap_b`（当前默认 500）；也不改 evaluator 的 `N_BOOTSTRAP`（=200，受保护）。本计划里的任何新重采样参数都是独立字段，不得复用、不得别名这两个名字。 | `git diff --stat -- src/faultevolve/discovery tests/test_discovery_*.py tests/test_tournament.py` 为空；`tests/test_config.py` 中现有默认值断言不变。 |
| G6 | 所有新能力**默认关闭**；默认配置下行为、`run_summary` 键集合、DB 既有表结构、CLI 命令集（现有八个命令）与旧制品完全兼容。新增只能是增量表/可选键。 | §3.5/§4.9/§5.9 的"默认关闭不变"测试。 |
| G7 | 不新增第三方依赖。需要的 numpy/pandas/scikit-learn/lightgbm/pydantic/pyyaml 均已在 `requirements.txt`/`pyproject.toml`。TPE 等只留接口。 | `git diff -- requirements.txt pyproject.toml` 为空。 |
| G8 | 不修改既有测试的断言（可新增测试文件；只有当既有测试确因合法的新增字段而需调整时，在 PR 说明里逐条论证）。 | PR 审查。 |
| G9 | 不在文档或代码里写入预测/虚构的实验结果；结果表留空；38.14 只称"历史观察点"。 | PR 审查。 |
| G10 | 用户可见文字与文档用简体中文；代码标识符与代码注释用英文。注释只解释非显然意图。 | PR 审查。 |

### 1.3 已核对的代码接点（实施者不必再探索，但动手前应重读对应函数）

| 事实（均在当前 main 核对） | 位置 |
|---|---|
| `EvolveConfig.from_dict` **逐键手工赋值**：不认识的顶层键会被**静默丢弃**；`with_overrides` 经 `model_dump()` → `from_dict()` 往返。新增 `autotune` 段若漏写 `from_dict` 分支，会在 `with_overrides`/CLI 路径上静默失效。 | `src/faultevolve/config.py` |
| `OperatorsConfig.enabled` 有白名单校验；`bandit=false` 时 `_choose_operator` 恒返回 `REFINE`；`_ENABLED_OPERATOR_MAP` 把名字映射到 `OperatorType`。 | `config.py`、`cloud/engine.py` |
| `OperatorType` 是 `str` 枚举；`node.operator` 以文本存库；`web/openapi/*.json` 镜像了算子枚举（CI 里有 `scripts/check_web_contracts.py`，导出脚本 `scripts/export_web_contracts.py`）。新增枚举值必须同步重新导出契约。 | `common/schemas.py`、`web/openapi/` |
| 存储只有 `CREATE TABLE IF NOT EXISTS` 的 `DDL` 字符串，**没有迁移框架**；既有表不得 `ALTER`，新表以增量方式加入 `DDL`。 | `cloud/store.py` |
| 评估/修复的入口函数：`_create_and_evaluate_init`、`_run_smoke_test`、`_attempt_perf_self_fix`、`_attempt_smoke_self_fix`、`_evaluate_child`、`_attempt_repair`、`_maybe_analyze_node`、`_handle_invalid_generation`、`_meter_llm_call`、`_log_event`。 | `cloud/engine.py` |
| `RunMetrics.valid_rate = valid_count/(valid_count+invalid_count)`，混合了所有节点类型，**不是**"首次生成即有效"。`analysis_calls` 在 `analysis.enabled=false`（默认）时恒为 0。 | `common/metering.py`、`config.py::AnalysisConfig` |
| 现有"开发集"：`HDDAdapter._build_analysis_data` 按 `dev_late_fraction`（0.4）把 `train_labels` 的 `cutoff_date` 分早/晚两段，写临时目录（`train_*` = 早段，`val_index/val_history` = 晚段）。**它不做设备隔离，也不做标签窗口清洗**。E1 的 dev 划分是新模块，不改这里。 | `tasks/hdd_adapter.py` |
| 候选程序 I/O 合同：`python <cand>.py --data-dir <dir> --split <val\|test> --out <csv>`，输出 `serial_number,score,alarm`。evaluator 的 `static_check` 有禁用模式（`FORBIDDEN_PATTERNS`），`TIME_BUDGET_S=600`、`FAR_BUDGET=0.002`、`N_BOOTSTRAP=200`。 | `benchmark/hdd_mvp/evaluator.py`（只读） |
| `fe evolve local` 支持 `--mock`、`--config-file`（不必改 `evolve.yaml`）、`--seed`、`--runs-dir`、`--artifacts-dir`；`MockLLM.set_responses([...])` 可脚本化返回。 | `cli.py`、`cloud/llm.py` |
| 受保护文件测试用 SHA-256 锁定评估器/init/problem/prompt/prepare_data/cards 与四个 public 数据文件。 | `tests/test_hdd_protected_files.py` |
| 现有测试会读 `benchmark/hdd_mvp/data`（如 `test_hdd_evaluator.py`、`test_error_analysis.py`）；这些保持原样。**新测试一律不读该目录**（§1.4）。 | `tests/` |

### 1.4 数据访问矩阵（"哪些数据不得进入公开测试/搜索代码"）

"公开测试"指仓库 `tests/` 下随 CI 运行、随仓库分发的测试。

| 数据 | HPO / dev / 消融代码 | 新增单元测试 | 经 adapter 的完整 evaluator（晋级后） | 报告与 manifest |
|---|---|---|---|---|
| `data/public/train_labels.csv`、`train_history.csv.gz` | 可读（仅此两个文件，且仅通过 §4.4 守卫） | **不读**，用 `tmp_path` 里的合成数据 | 由 evaluator 自行读取 | 只记 sha256 与行数，不记内容 |
| `data/public/val_history.csv.gz`、`val_index.csv` | **不读**（无标签，但属于验证面，HPO 无需使用） | 不读 | evaluator 读取 | 只记 sha256 |
| `data/eval_only/val_labels.csv` | **禁止** | **禁止** | 仅 evaluator 内部读取 | 不记内容 |
| `data/holdout*`（`holdout/`、`holdout_labels/`） | **禁止，永不** | **禁止，永不** | 不在本计划内触发 `--split test` | **不记，不出现路径之外的任何信息** |
| 合成数据（测试夹具） | — | 允许；由 `tests/helpers_autotune.py::make_synthetic_hdd(tmp_path, ...)` 生成，列名与 HDD 公开文件一致（`serial_number,model,cutoff_date,label,weight` + 历史表 `serial_number,date,model,capacity_bytes,smart_*`） | — | — |

附加规则：路径比较前先 `Path.resolve()`（NAS 上 `data` 可能是符号链接；E0 要记录其真实指向，见 §3.2）。`tests/test_autotune_data_guard.py` 扫描新增源码，字符串 `holdout`、`eval_only`、`val_labels` **只允许出现在守卫模块的拒绝名单里**。

---

## 2. 目录与文件总图（规划名即实施名）

```
src/faultevolve/optimization/            # 新包（E0 起）
  __init__.py                            # E0  仅导出稳定符号
  ledger.py                              # E0  成本账本 + 预留/结算
  baseline_metrics.py                    # E0  从 DB/events 重建指标（纯函数）
  manifest.py                            # E0  baseline_manifest 构建器
  candidate_spec.py                      # E1  CandidateSpec / 编译
  parameter_space.py                     # E1  参数类型、条件、约束
  search.py                              # E1  Searcher 协议 + RandomSearch
  trials.py                              # E1  Trial 数据模型与状态
  dev_split.py                           # E1  时间阻断 + 设备隔离 dev 划分，路径守卫
  cache.py                               # E1  评估缓存键与存取
  hpo_runner.py                          # E1  无 LLM 的 HPO 驱动（含晋级）
  patching.py                            # E2  SEARCH/REPLACE 解析与应用
  ablation.py                            # E2  固定 dev 上的小型消融
  feedback.py                            # E2  FeedbackBundle 构建与渲染
  quota.py                               # E2  固定操作配额调度
src/faultevolve/tasks/hdd_templates.py   # E1  两个自包含模板（字符串常量）
src/faultevolve/tasks/hdd_space.py       # E1  HDD 参数空间与特征组定义
src/faultevolve/tasks/hdd_dev.py         # E1  dev 代理指标（只读复用 evaluator 辅助函数）
scripts/autotune_manifest.py             # E0  生成 baseline_manifest.json
scripts/autotune_rebuild_metrics.py      # E0  重建历史运行指标
scripts/autotune_hpo.py                  # E1  hpo_runner 的薄命令行包装（不新增 `fe` 子命令）
docs/plans/autotune/                     # E0 起  报告与冻结协议
  E0_VERSION_DIFF.md
  E0_METRICS.md
  E0_PROFILE.md
  E0_EXIT.md
  protocol_dev_A.evolve.yaml
  baseline_manifest.json                 # 由脚本生成后提交
tests/helpers_autotune.py                # E0 起  合成数据与假 LLM 夹具
tests/test_autotune_*.py                 # 见各阶段
skill/fe-autotune-plan/SKILL.md          # 已随本计划提交
```

不得新建/修改：`benchmark/**`、`src/faultevolve/discovery/**`、`src/faultevolve/webapi/**`（E0～E2 期间 Web 不动；唯一例外是 §5.6 要求的 OpenAPI 契约重导出，且只能是算子枚举增量）。

---

## 3. E0：先冻结基线与真实指标

**目标**：得到一个"当前版本"的可信起点——知道本地 main 与 NAS aligned 差在哪、各项指标按什么分母算、一次运行实际花了什么——并在此之前不写任何搜索增强代码。

**E0 允许改动的运行时代码仅限**：`src/faultevolve/optimization/{__init__,ledger,baseline_metrics,manifest}.py`、`config.py` 中新增 `AutotuneConfig`（仅 `ledger` 子段）、`cloud/engine.py`/`cloud/store.py` 中账本的最小接线。其余一律禁止。

### 3.1 E0 任务清单与交付物

| 编号 | 任务 | 交付物 | 依赖 |
|---|---|---|---|
| E0.1 | local/NAS 版本差异清单 | `docs/plans/autotune/E0_VERSION_DIFF.md` | NAS 可读副本（见 §3.2） |
| E0.2 | 受保护文件与 NAS data 符号链接核对 | 写入 E0.1 报告的独立小节 | E0.1 |
| E0.3 | 指标定义与历史运行重建 | `docs/plans/autotune/E0_METRICS.md`、`baseline_metrics.py`、`scripts/autotune_rebuild_metrics.py`、`tests/test_autotune_baseline_metrics.py` | 历史运行副本 |
| E0.4 | 资源画像与 `analysis_calls=0` 归因 | `docs/plans/autotune/E0_PROFILE.md` | E0.3 |
| E0.5 | 成本账本与预留/结算接口 | `ledger.py`、`AutotuneConfig.ledger`、`store.py` 新表、引擎最小接线、`tests/test_autotune_ledger.py` | E0.3 的阶段枚举 |
| E0.6 | baseline_manifest | `manifest.py`、`scripts/autotune_manifest.py`、`docs/plans/autotune/baseline_manifest.json`、`tests/test_autotune_manifest.py` | E0.1、E0.5 |
| E0.7 | 冻结的开发比较协议 | `docs/plans/autotune/protocol_dev_A.evolve.yaml` + 协议说明（写在 `E0_EXIT.md`） | E0.5、E0.6 |
| E0.8 | 一次可复现的离线运行 | 运行目录副本路径与哈希记入 `E0_EXIT.md` | E0.7 |
| E0.9 | 退出门核对 | `docs/plans/autotune/E0_EXIT.md`（勾选项齐全） | 全部 |

### 3.2 E0.1/E0.2 版本差异与保护文件

输入：本仓库工作树（钉住某个 commit）与 NAS 上的 `work/code_aligned` 的**只读副本**。若实施环境访问不到 NAS：在 `E0_VERSION_DIFF.md` 顶部写 `BLOCKED: 需要 <具体路径/压缩包>`，**停止并上报**，不得凭设计文档里的描述臆测差异，也不得进入 E1。

步骤：

1. `git rev-parse HEAD`、`git status --porcelain` 记入报告；工作树必须干净。
2. 对两棵树做 `diff -rq`，排除：`.git`、`.fe`、`__pycache__`、`benchmark/**/data`、`runs/`、`web/node_modules`。结果按文件逐项列表。
3. 每个差异文件归入三类之一，并写明证据：
   - **迁移**：NAS 版有修复且有证据（某 run 的事件/DB 行/测试）。每一项迁移是**一个独立小提交**，带至少一个能在旧代码上失败、新代码上通过的回归测试；不整体覆盖目录。
   - **拒绝**：NAS 版实验性/无证据；写明理由。
   - **未知**：无法判断；写明需要什么才能判断。未知项不迁移。
4. 钉住：`pip freeze` 中与本项目相关的包（python、numpy、pandas、scikit-learn、lightgbm、pydantic、pyyaml、httpx/openai 客户端等）版本，写进报告并记入 manifest。
5. 受保护文件：记录 `tests/test_hdd_protected_files.py` 通过的输出；记录 NAS 上 `benchmark/hdd_mvp/data` 是否为符号链接及其 `realpath`（只记路径与 sha256，不记内容）；若 NAS 上这些文件哈希与仓库期望值不同，**只报告，不修改任何受保护文件**。

### 3.3 E0.3 指标定义（写入 `E0_METRICS.md`，由 `baseline_metrics.py` 实现）

输入只读：`fe.db`（用 `file:...?mode=ro` 打开**副本**）、`events.jsonl`、`run_summary.json`。历史运行库**只读**，回放一律用副本。

分母必须显式输出。字段（缺失事件导致无法计算时输出 `null` 并带 `unknown_reason`，**不得推断补零**）：

| 字段 | 定义 |
|---|---|
| `n_generation_requests` | 生成类算子（refine/recall_focus/threshold_calibrate/inject/crossover）发起的生成次数（不含 init、不含 Repair 算子）。 |
| `n_pre_eval_reject` | 在首次完整 evaluator 之前被拒绝的数量：生成解析失败、静态检查/预检失败且未修复、smoke 失败且未修复（对应事件 `invalid_generation`、`precheck_fix`、`smoke_failed`、`perf_rejected` 等）。 |
| `n_first_eval` | 到达首次完整 evaluator 调用的候选数（自修复前的那次）。 |
| `valid_rate_first_eval` | 首次完整评估 `validity=1` 的数量 / `n_first_eval`。 |
| `gen_to_first_valid_rate` | 同上分子 / `n_generation_requests`（把预检拒绝算作失败的更严口径）。 |
| `valid_rate_after_selffix` | 经 precheck/perf/smoke 自修复后（**未**使用 Repair 算子）最终有效的候选数 / `n_generation_requests`。 |
| `valid_rate_after_repair` | 经 Repair 算子后最终有效数 / `n_generation_requests`（即"修复后有效率"；与旧 `valid_rate_after_fix` 同义，仅此一个名字对外使用）。 |
| `positive_gain_rate` | 有效子节点中 `delta_score>0`（相对其父节点的完整 val 分）的数量 / 有效子节点数。**运行成功 ≠ 提分**：本指标只数提分。 |
| `significant_gain_rate` | `delta_score > noise_delta`（现有基于 f1 bootstrap std 的工程噪声门）的数量 / 有效子节点数。报告里必须注明"工程噪声门，**不是**父子 ROS 差的置信区间"。 |
| `unique_candidate_rate` | 有效候选中不同 `source_hash` 的数量 / 有效候选数。`source_hash = sha256(code.replace("\r\n","\n").rstrip() + "\n")`。 |
| `legacy_valid_rate` | 原样复制 `run_summary.valid_rate`，并注明其分母。仅供对照，不得与上面各项混用。 |

另输出：best-so-far 对"完整 evaluator 调用序号"的序列（历史运行若无法区分调用类型，则以节点创建序为代理并标注 `proxy=true`）。

### 3.4 E0.4 资源画像与 `analysis_calls=0`

- 按阶段（generation/eval/analysis/repair/smoke/self-fix）汇总墙钟：来源 `llm_call` 表延迟与事件时间戳差；无法拆分的写 `null`。
- 模型拟合次数、CPU、RSS：历史运行**没有**这些数据 → 写 `null`/`unknown`。只有 E0.5 账本启用后的新运行才有。CPU 用 `resource.getrusage(RUSAGE_CHILDREN)` 在子进程评估前后取差；RSS 记录 `ru_maxrss` 高水位（Linux 单位 KB），报告注明它是进程树累计高水位而非逐任务差值。
- `analysis_calls=0`：先读该运行 `experiment.config_json` 的 `analysis.enabled`。当前默认 `analysis.enabled=false`，因此 0 是**配置使然**而非故障；若某运行启用了分析仍为 0，再查 `_should_analyze_node` 的触发条件（`on_new_best`、`top_k`）。把结论写进 `E0_PROFILE.md`，区分"未启用"与"启用但未触发"。

### 3.5 E0.5 成本账本

**配置**（`config.py`，E0 只加这一段；`from_dict` 必须加 `if "autotune" in data: config.autotune = AutotuneConfig(**data["autotune"])`）：

```python
class LedgerConfig(BaseModel):
    enabled: bool = False
    full_eval_cap: int | None = Field(default=None, ge=1)  # None = no cap

class AutotuneConfig(BaseModel):
    ledger: LedgerConfig = Field(default_factory=LedgerConfig)
```

`EvolveConfig.autotune: AutotuneConfig = Field(default_factory=AutotuneConfig)`。后续阶段向 `AutotuneConfig` 增加子段，**各阶段自己加自己的键**。

**接口**（`optimization/ledger.py`，纯 Python，无 I/O 依赖，便于测试）：

```python
Stage = Literal[
    "cold_start", "generate", "reflect", "repair", "self_fix", "smoke",
    "hpo_fit", "hpo_dev_eval", "ablation", "analysis", "crossover",
    "full_eval", "other",
]
Fidelity = Literal["none", "smoke", "dev", "full_val"]

@dataclass(frozen=True)
class CostRecord:
    seq: int                       # monotonically increasing per run, assigned by the ledger
    stage: Stage
    fidelity: Fidelity
    node_id: str | None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model_fit_count: int = 0
    evaluator_calls: int = 0       # 1 per call to the protected evaluator via adapter.evaluate
    cpu_seconds: float | None = None
    rss_peak_mb: float | None = None
    wall_s: float = 0.0
    cache_hit: bool = False
    status: Literal["ok", "failed", "timeout", "rejected"] = "ok"
    reservation_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)   # small, no secrets

@dataclass(frozen=True)
class Reservation:
    id: str
    stage: Stage
    est_tokens: int
    est_evaluator_calls: int
    est_model_fits: int

class CostLedger:
    def reserve(self, stage: Stage, *, est_tokens: int = 0, est_evaluator_calls: int = 0,
                est_model_fits: int = 0) -> Reservation: ...
    def settle(self, reservation: Reservation, record: CostRecord) -> CostRecord: ...
    def record(self, record: CostRecord) -> CostRecord: ...          # un-reserved spend
    def totals(self) -> LedgerTotals: ...                            # includes outstanding reservations
    def would_exceed(self, *, full_evals: int = 0, tokens: int = 0) -> bool: ...
```

规则（均有测试）：

1. **失败不退款**：`settle(..., status in {failed,timeout,rejected})` 仍累计实际花费；预留额度只在 settle 时释放，实际花费以 `record` 为准。
2. **缓存命中**：`cache_hit=True` 的记录 `evaluator_calls=0`、`model_fit_count=0`、tokens 0，**不计新样本**，但单独计数 `cache_hits`。
3. **全局上限**：`full_eval_cap` 非 None 时，`totals().full_eval_calls + 在途预留 >= cap` 则 `would_exceed(full_evals=1)` 为真。引擎在发起任何会调用完整 evaluator 的步骤（含 init 评估之后的所有子节点评估、自修复重评、Repair 重评、晋级复核）前检查；超出则停止并给出 `stop_reason="ledger_full_eval_cap"`。`full_eval_cap=None` 时不改变现有停止逻辑。
4. 账本只**观测**与（在 cap 非空时）**限流**，不得改变搜索随机性：同 seed、同配置，开/关账本（cap 为空）的节点序列、代码、分数必须逐位相同。

**存储**（`cloud/store.py`，`DDL` 增量）：

```sql
CREATE TABLE IF NOT EXISTS cost_ledger (
    experiment_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    stage TEXT NOT NULL,
    fidelity TEXT NOT NULL,
    node_id TEXT,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    model_fit_count INTEGER DEFAULT 0,
    evaluator_calls INTEGER DEFAULT 0,
    cpu_seconds REAL,
    rss_peak_mb REAL,
    wall_s REAL DEFAULT 0,
    cache_hit INTEGER DEFAULT 0,
    status TEXT NOT NULL,
    reservation_id TEXT,
    meta_json TEXT,
    created_at TEXT,
    PRIMARY KEY (experiment_id, seq)
);
```

`Store` 增加 `append_cost_record(experiment_id, rec)`、`list_cost_records(experiment_id)`。写入走既有单连接路径，不新开连接。

**引擎接线**（仅当 `autotune.ledger.enabled`）：在下列函数的**已有**评估/LLM 调用点旁调用 `self._ledger_record(...)`（新增私有方法，未启用时立即返回）：`_create_and_evaluate_init`（full_eval）、`_run_smoke_test`（smoke）、`_attempt_perf_self_fix` 与 `_attempt_smoke_self_fix`（self_fix，含其内重评估）、`_evaluate_child`（full_eval）、`_attempt_repair`（repair，含重评估）、`_maybe_analyze_node`（analysis）、`_meter_llm_call`（按其 stage 参数映射 generate/reflect/repair/crossover 的 tokens）。不改这些函数的控制流和返回值。

**账本启用时的汇总**：`run_summary` 增加键 `cost_ledger_totals`（按 stage × fidelity 汇总、总 evaluator_calls、总 fit、`cache_hits`）；**未启用时该键不存在**。

### 3.6 E0.6 baseline_manifest.json

`manifest.py::build_manifest(repo_root, task_dir, config_path, run_dir|None, env=os.environ) -> dict`，字段：

```json
{
  "schema": 1,
  "git": {"commit": "...", "dirty": false},
  "python": "...", "packages": {"numpy": "...", "pandas": "...", "scikit-learn": "...", "lightgbm": "...", "pydantic": "..."},
  "effective_config": { "...EvolveConfig.model_dump() with secrets-free content..." },
  "config_hash": "sha256:...",
  "task": {"adapter": "hdd", "files": {"evaluator.py": "sha256:...", "init.py": "...", "problem.md": "...", "prompt.md": "..."}},
  "data": {"train_labels.csv": {"sha256": "...", "rows": 0}, "train_history.csv.gz": {"sha256": "..."}, "val_history.csv.gz": {"sha256": "..."}, "val_index.csv": {"sha256": "..."}, "realpath_is_symlink": false},
  "evaluator_hash": "sha256:...",
  "models": {"generate_model": "...", "reason_model": "...", "base_url_host": "dashscope.aliyuncs.com"},
  "seed": 0, "threads": {"OMP_NUM_THREADS": null, "OPENBLAS_NUM_THREADS": null, "MKL_NUM_THREADS": null, "LIGHTGBM_NUM_THREADS": null},
  "budget": {"max_iterations": 0, "max_tokens": 0, "max_wall_hours": 0, "full_eval_cap": null},
  "artifacts": {"run_dir": "...", "db_sha256": "...", "run_summary_sha256": "..."},
  "created_at": "..."
}
```

规则：

- **永不包含** `eval_only/`、`holdout*` 的任何哈希或内容；数据部分只枚举上表四个 public 文件（`val_labels.csv` 不进 manifest——它在 `eval_only/`）。
- 密钥：`effective_config` 来自 `model_dump()`，其中只有环境变量**名称**（如 `api_key_env`）；构建器对最终 JSON 做正则/白名单扫描，出现形如已设置环境变量值的子串则抛错。`base_url` 只记 host。
- `config_hash` 对规范化 JSON（排序键、紧凑分隔符）取 sha256。
- 测试：`tests/test_autotune_manifest.py` 设置假 `DASHSCOPE_API_KEY=sk-test-SECRET123` 环境变量，断言 manifest 序列化文本不含该值；断言不含 `holdout`/`eval_only` 字符串；断言同输入两次调用逐字节相同（除 `created_at`）。

### 3.7 E0.7 冻结的开发比较协议（A 组）

文件 `docs/plans/autotune/protocol_dev_A.evolve.yaml`，经 `fe evolve local ... --config-file` 使用，**不修改** `benchmark/hdd_mvp/evolve.yaml`。起始提案（E0 实施者核对后冻结，冻结后写进 `E0_EXIT.md` 并标注 commit）：

```yaml
seed: 20260926
budget: {max_iterations: 50, max_tokens: 3000000, max_wall_hours: 6}
operators: {bandit: false, enabled: [refine], crossover: {enabled: false}}
discovery: {enabled: false, tournament: {enabled: false}}
analysis: {enabled: false}
judge: {provider: none}
autotune: {ledger: {enabled: true, full_eval_cap: 50}}
```

说明：

- REFINE-only（`bandit=false` 本就恒选 REFINE，`enabled` 仍显式写出）；KD1/KD2（`discovery`、`tournament`）关闭；crossover 关闭。
- `full_eval_cap: 50` 即设计 §8.1/TODO §10.1 的"总完整 evaluator 调用上限 50"。**注意语义**：这与现有 `--iterations 50` **不同**，后者不涵盖自修复、Repair、晋级复核、消融等评估；协议文档必须并列写出两者。
- `analysis.enabled=false` 的取舍（沿用现状 vs 开启）由 E0.4 的结论决定，**决定与理由写入协议说明**，一经冻结，A/B/C 比较均沿用。
- 不在协议里写 n_slices、bootstrap_b（G5）。
- 协议同时给出"什么算同预算"的三视图定义：完整 evaluator 调用数、token、墙钟；以及与伐谋对照时的"原协议同迭代/同工件"视图。伐谋平台预算/计数不可得时写"不可对齐"。

### 3.8 E0.8 一次可复现的离线运行

1. `cd benchmark/hdd_mvp && python evaluator.py init.py`：记录得到的 val ROS（AGENTS.md 给出参考值约 22.81；记录**实测**值与机器，不要照抄 22.81）。
2. `fe evolve local benchmark/hdd_mvp --mock --iterations 3 --seed 20260926 --config-file docs/plans/autotune/protocol_dev_A.evolve.yaml --runs-dir <tmp1> --artifacts-dir <tmp1a>`，再用 `<tmp2>` 重跑一次。比较两次：节点数、每个节点代码 sha256、分数、事件类型序列必须一致（允许 `created_at`、耗时字段不同）。比较脚本写在 `E0_EXIT.md` 引用的命令中。
3. 付费真实运行**不属于 E0 必做项**，只在后续任务明确授权时进行；未授权时不得消耗 API 额度，也不得写入任何"真实运行"结果。

### 3.9 E0 退出门（`E0_EXIT.md` 全部勾选前，禁止在 `src/` 下为 E1 写代码）

- [ ] `E0_VERSION_DIFF.md` 完成，每个差异有"迁移/拒绝/未知"归类；迁移项已各自提交且带回归测试；或明确写出 `BLOCKED` 原因并由人决定是否放行。
- [ ] 受保护文件测试通过；NAS data 符号链接 realpath 已记录。
- [ ] `E0_METRICS.md` 与 `baseline_metrics.py` 完成；四个历史运行（若可读）已重建指标，缺失处为 `null`+原因，没有被推断补零。
- [ ] `E0_PROFILE.md` 完成，`analysis_calls=0` 已归因为"未启用"或"启用但未触发"。
- [ ] 账本代码与接线完成；**默认关闭时行为不变**测试通过；账本开启 vs 关闭的 mock 运行节点序列一致。
- [ ] 漏计回归测试通过（§3.10 中的 L1～L8）。
- [ ] `baseline_manifest.json` 已生成并提交，无密钥、无 holdout/eval_only 信息。
- [ ] 协议 `protocol_dev_A.evolve.yaml` 已冻结，说明里写清 38.14 是历史观察点、当前基线待测。
- [ ] §3.8 离线运行两次一致，且 `python -m pytest tests/ -q` 全绿（记录通过数到 `E0_EXIT.md`）。
- [ ] G1～G10 自检通过。

### 3.10 E0 测试（精确清单）

`tests/test_autotune_ledger.py`

| 编号 | 断言 |
|---|---|
| L1 | `settle` 一个 `status="failed"` 的 repair 记录后，`totals().prompt_tokens` 等于实际花费，不为 0 且不因预留释放而减少。 |
| L2 | `cache_hit=True` 的 full_eval 记录使 `evaluator_calls` 总数不变、`cache_hits` +1。 |
| L3 | 在途预留计入 `totals()` 与 `would_exceed`：`full_eval_cap=2`，已完成 1 次 + 1 个未结算预留 → `would_exceed(full_evals=1)` 为真。 |
| L4 | mock 引擎、`ledger.enabled=true`：一次触发 precheck 自修复的迭代，ledger 里 `self_fix` 与 `full_eval` 记录数与 `RunMetrics` 的 `precheck_fixes`/评估计数一致。 |
| L5 | 触发 Repair 的迭代，`repair` 记录的 tokens 之和等于 `RunMetrics.repair_tokens`。 |
| L6 | smoke 失败并自修复的迭代，`smoke` 记录数 = smoke 调用数。 |
| L7 | `full_eval_cap=3` 时 mock 运行在第 3 次完整评估后停止，`stop_reason == "ledger_full_eval_cap"`，且 ledger 中 `full_eval` 的 `evaluator_calls` 总和 == 3。 |
| L8 | 同 seed、`ledger.enabled` 开/关（cap=None）的 mock 运行：节点 id 集合、每个节点 code sha256、`combined_score` 逐一相等。 |

`tests/test_autotune_default_off.py`（E0 起创建，E1/E2 追加断言）

| 编号 | 断言 |
|---|---|
| D1 | `EvolveConfig().autotune.ledger.enabled is False` 且 `full_eval_cap is None`。 |
| D2 | `EvolveConfig.from_dict({"autotune": {"ledger": {"enabled": True, "full_eval_cap": 7}}})` 往返：`cfg.with_overrides(seed=1).autotune.ledger.full_eval_cap == 7`（验证 `from_dict`/`with_overrides` 完整往返，防静默丢弃）。 |
| D3 | 默认配置的 mock 运行：`run_summary` 键集合 ⊇ 现有 fixture（`tests/fixtures/runs/hdd_mvp_demo_7510f100/run_summary.json`）键集合，且**不含** `cost_ledger_totals`；DB 中 `cost_ledger` 表存在但对该实验为空行。 |
| D4 | `tests/test_hdd_protected_files.py` 与 `tests/test_config.py` 现有断言不改且通过。 |

`tests/test_autotune_baseline_metrics.py`

| 编号 | 断言 |
|---|---|
| M1 | 用合成事件构造一个已知答案的运行（含 1 次 precheck 自修复成功、1 次 Repair 成功、1 次 invalid_generation、1 次提分、1 次无提分），逐项断言 §3.3 每个字段的分子、分母与值。 |
| M2 | 缺少区分首次评估所需事件时，相应字段为 `None` 且 `unknown_reason` 非空。 |
| M3 | `legacy_valid_rate` 原样等于 `run_summary.valid_rate`。 |
| M4 | 以 `file:...?mode=ro` 打开副本；对只读目录运行不抛出写错误，原文件哈希不变。 |
| M5 | `significant_gain_rate` 的输出结构带有说明字符串"工程噪声门"。 |

`tests/test_autotune_manifest.py`：见 §3.6。

**E0 不写**：针对纯文档/字段重命名的重复测试。

---

## 4. E1：结构化自动调参（无 LLM 的参数搜索）

**目标**：在固定结构上，用确定性、可复现、可计账的 random search 找参数，晋级者编译成完整自包含脚本再交原 evaluator 评分。旧路径（`init.py` 原样可运行、`fe evolve local` 原流程）不变。

**前提**：E0 退出门已通过。

### 4.1 配置（`AutotuneConfig` 新增 `hpo`、`cache` 子段；默认全关）

```python
class HpoDevConfig(BaseModel):
    dev_late_fraction: float = Field(default=0.4, gt=0, lt=1)
    purge_days: int = Field(default=7, ge=0)       # equals task horizon_days; see 4.4
    min_dev_pos: int = Field(default=20, ge=1)
    min_train_pos: int = Field(default=20, ge=1)

class HpoConfig(BaseModel):
    enabled: bool = False
    families: list[Literal["logreg", "lightgbm"]] = ["logreg"]
    search: Literal["random"] = "random"           # "tpe" reserved: not accepted in E1
    trials_per_structure: int = Field(default=8, ge=1, le=64)
    max_fits_total: int = Field(default=80, ge=1)  # hard cap across all trials incl. failed
    promote_top_k: int = Field(default=1, ge=1, le=3)
    threads: int = Field(default=1, ge=1, le=8)
    trial_timeout_s: int = Field(default=300, ge=10, le=900)
    dev: HpoDevConfig = Field(default_factory=HpoDevConfig)

class CacheConfig(BaseModel):
    enabled: bool = False
    full_eval: bool = False   # full-evaluator results depend on wall time (time_factor); off by default

class AutotuneConfig(BaseModel):
    ledger: LedgerConfig = ...
    hpo: HpoConfig = Field(default_factory=HpoConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
```

校验：`search="tpe"` 在 E1 内 `ValueError`（接口留口但不启用）。`hpo.enabled=true` 要求 `ledger.enabled=true`（否则不能满足"所有 fit 计数"），违者 `ValueError`。数值默认值是起始提案，E1 合入前由实施者在 PR 说明里确认并冻结。

### 4.2 候选表示与模板

`optimization/candidate_spec.py`

```python
class CandidateSpec(BaseModel):
    spec_version: int = 1
    family_id: Literal["logreg", "lightgbm"]
    template_id: str                        # e.g. "hdd.logreg.v1"
    feature_groups: list[str]               # structure, NOT searched by HPO
    params: dict[str, float | int | str | bool]
    train: TrainSpec                        # seed, weight_policy
    calibration: CalibrationSpec            # threshold rule + quantile grid
    editable_blocks: list[Literal["feature", "model", "train", "calibration"]]
    space_version: int

def config_hash(spec: CandidateSpec) -> str: ...     # canonical JSON of params+train+calibration+seed+space_version
def structure_hash(spec: CandidateSpec) -> str: ...  # family+template+feature_groups only (no params/seed)
def compile_spec(spec: CandidateSpec, templates: Mapping[str, str]) -> CompiledCandidate: ...
@dataclass(frozen=True)
class CompiledCandidate:
    code: str                  # self-contained script, honours the I/O contract
    source_hash: str           # sha256 of normalized code (same normalization as §3.3)
    config_hash: str
    fits_per_run: int          # declared fit count of one script run (see below)
```

`compile_spec` 是确定性的（同 spec → 逐字节相同代码）；参数以 `PARAMS = {...}` JSON 字面量注入到模板的固定占位符，**不**用字符串拼接到逻辑代码里。`source_hash` 因此随参数变化；`structure_hash` 不随参数变。

`tasks/hdd_templates.py`：两个 Python 字符串常量 `HDD_LOGREG_V1`、`HDD_LIGHTGBM_V1`。要求：

- 自包含，遵守 I/O 合同；只读取 `--data-dir` 下 `train_*` 与 `<split>_*`；通过 evaluator 的 `static_check`（不含 `FORBIDDEN_PATTERNS`；用 adapter 的 `static_check` 在测试里验证）。
- 含 `# FE-BLOCK-BEGIN <name>` / `# FE-BLOCK-END <name>` 标记，name ∈ feature/model/train/calibration（E2 的 patch 依赖它）。
- 阈值在脚本内部用**训练数据内部**的时间阻断段/OOF 选出（不得用 `--split` 数据，不得读标签以外的验证信息）；`fits_per_run` 常量声明一次运行的拟合次数（最终模型 1 + 阈值 OOF 折数），测试用打补丁的计数器验证声明属实。
- LightGBM 模板：线程数取 `PARAMS["n_jobs"]`（由 `hpo.threads` 注入），不使用 `early_stopping_rounds=` 旧参数（遵循 adapter `api_notes` 中的 LightGBM 4.x 回调写法）。
- 权重一致性：`weight_policy ∈ {"sample_weight_only","class_weight_only","none"}`，模板内按策略**只**用其中一种补偿类别不平衡；`scale_pos_weight` 与 `class_weight`/样本权重互斥（见 §4.3 约束 C1）。

`tasks/hdd_space.py`：定义 `FEATURE_GROUPS`（起始提案：`snapshot_core`（同 `init.py` 的 10 个特征）、`vendor_onehot`、`delta_7d`（末次快照相对 7 天前的差））、`logreg_space()`、`lightgbm_space()`、`default_spec(family)`。**HDD/SMART/型号名只出现在 `tasks/` 下**，`optimization/` 通用层不得出现（用 `tests/test_autotune_task_agnostic.py` grep 断言：`optimization/` 源码不含 `smart_`、`serial_number`、`hdd`）。

### 4.3 参数空间与约束

`optimization/parameter_space.py`

```python
class ParamDef(BaseModel):
    name: str
    kind: Literal["float", "int", "categorical", "bool"]
    low: float | None = None
    high: float | None = None
    log: bool = False
    choices: list[Any] | None = None
    when: Condition | None = None        # {"param": "penalty", "in": ["l1"]}

class ParameterSpace(BaseModel):
    version: int
    params: list[ParamDef]
    constraints: list[str]               # registered constraint ids, serializable

def validate_values(space: ParameterSpace, values: Mapping[str, Any]) -> list[str]: ...  # [] = ok
def sample(space: ParameterSpace, rng: numpy.random.Generator) -> dict[str, Any]: ...
class ParameterSpaceError(ValueError): ...
```

规则：`float`/`int` 要 `low<high`；`log=True` 要 `low>0`；`categorical` 要非空 `choices`；条件参数仅在 `when` 满足时出现于采样结果与校验，未满足却出现的值判无效；约束 id 在注册表中查找，未知 id 抛 `ParameterSpaceError`。

起始范围（提案；E1 冻结为 `space_version=1`）：

- logreg：`C` log∈[1e-3,1e2]；`penalty`∈{l1,l2}；`solver` 条件于 penalty（l1→liblinear/saga；l2→lbfgs/liblinear）；`max_iter` int∈[200,2000]；`weight_policy`∈三选一。
- lightgbm：`num_leaves` int log∈[8,128]；`learning_rate` log∈[0.02,0.3]；`n_estimators` int∈[100,600]；`min_child_samples` int∈[10,200]；`subsample` ∈[0.5,1.0]；`colsample_bytree` ∈[0.5,1.0]；`reg_lambda` log∈[1e-3,10]；`max_depth` 条件（默认 -1 或 int∈[3,12]）；`weight_policy`；`scale_pos_weight` 仅当 `weight_policy="none"` 时出现，log∈[1,50]。
- 约束：**C1** `scale_pos_weight` 与（`class_weight`、样本权重）不同时生效；**C2** `num_leaves ≤ 2^max_depth`（当 max_depth>0）；**C3** `solver` 与 `penalty` 兼容。

### 4.4 数据划分与路径守卫

`optimization/dev_split.py`（通用，输入为 DataFrame/路径，任务相关列名由调用方传入）：

```python
class DevSplitError(RuntimeError): ...

def assert_public_train_only(path: Path) -> Path:
    """Resolve symlinks, then reject anything that is not exactly train_labels.csv / train_history.csv.gz
    under a directory without 'eval_only' or 'holdout*' components. Raises DataAccessError."""

@dataclass(frozen=True)
class DevSplit:
    train_labels: pd.DataFrame
    dev_labels: pd.DataFrame
    report: dict        # counts: rows/pos per side, dropped_for_device_overlap, dropped_for_purge, cutoff boundary

def make_time_blocked_split(labels, *, serial_col, cutoff_col, label_col, horizon_days, late_fraction,
                            purge_days, min_pos_train, min_pos_dev) -> DevSplit: ...
```

算法（确定性、无随机）：

1. 取 `cutoff_col` 的不同值排序，按 `late_fraction` 切成早段/晚段（与现有 `_build_analysis_data` 的边界取整方式一致，便于对照）。
2. **设备隔离**：晚段（dev）出现过的 `serial` 从训练段**整体移除**。
3. **标签窗口隔离**：训练段中 `cutoff + horizon_days + purge_days >= 晚段最早 cutoff` 的行移除。
4. 任一侧阳性数低于下限 → 抛 `DevSplitError`（该 trial **不执行**、不计 fit，但事件记 `hpo_split_refused`）。
5. `tasks/hdd_dev.py` 负责把 `DevSplit` 物化为一个伪任务目录（`train_labels.csv`、`train_history.csv.gz`=训练段设备、`val_index.csv`、`val_history.csv.gz`=dev 设备），沿用现有 `_build_analysis_data` 流式过滤历史表的方式；**dev 标签留在 Python 进程内存/临时文件，不写进该目录**，由 `hdd_dev.score_dev()` 对预测打分。

守卫：`dev_split` 与 `hdd_dev` 所有读取文件的入口先过 `assert_public_train_only`；该函数拒绝：解析后路径任一分量等于 `eval_only` 或以 `holdout` 开头；文件名不是上述两个 train 文件之一；符号链接解析到上述禁区。测试覆盖符号链接绕过。

`tasks/hdd_dev.py::score_dev(pred, dev_labels)`：**dev 代理分** `dev_proxy`：只读复用 evaluator 的辅助函数（`weighted_auprc`、`recall_at_far`、加权 F1），经 `importlib` 从任务目录里的 `evaluator.py` **按路径加载（不修改、不复制）**；公式与 ROS 同构但**不做 bootstrap、不乘 time_factor**；返回字典带 `fidelity="dev"`。命名与存储上一律叫 `dev_proxy`，**不得**叫 ROS/combined_score。

### 4.5 搜索与 trial

`optimization/trials.py`：

```python
@dataclass
class Trial:
    trial_id: str                # f"{structure_hash[:8]}-{index:04d}-{config_hash[:8]}"
    structure_id: str
    index: int
    spec: CandidateSpec
    seed: int
    fidelity: Literal["dev"]
    status: Literal["proposed", "refused", "running", "ok", "failed", "timeout"]
    fit_count: int = 0
    dev_proxy: float | None = None
    dev_metrics: dict | None = None
    cache_hit: bool = False
    failure_reason: str = ""
```

`optimization/search.py`：

```python
class Searcher(Protocol):
    def propose(self, space: ParameterSpace, *, structure_id: str, start_index: int, n: int) -> list[dict]: ...
    def observe(self, trial: Trial) -> None: ...

class RandomSearch:
    def __init__(self, seed: int): ...
```

可复现性：第 `k` 个 trial 的 RNG = `numpy.random.default_rng(numpy.random.SeedSequence([seed, int(structure_hash[:8], 16), k]))`。**提案 k 与一次请求多少个无关**（请求 8 个与分两次请求 4+4 结果相同）。`observe` 在 random 下为空操作。`TPE` 仅留 `Searcher` 协议，不实现、不安装依赖。

**预算与计账**（`hpo_runner.py`）：

- 每个结构至多 `trials_per_structure` 个 trial；全局至多 `max_fits_total` 次拟合（**每个 trial 开始前**检查 `used + fits_per_run <= max_fits_total`，否则停止，不"透支一次"）。
- 每个 trial 在运行前向账本 `reserve(stage="hpo_fit")`，结束（含失败/超时）`settle`；记录 `model_fit_count=fits_per_run`（失败 trial 若中途崩溃，按**声明值**计，宁可多计）、`evaluator_calls=0`、`fidelity="dev"`。
- 晋级者（dev_proxy 最高的 `promote_top_k` 个）编译 → 经 `adapter.evaluate(code, task_spec)` 完整 val 评估，账本 `full_eval`/`full_val`；`ledger.would_exceed(full_evals=1)` 为真则不晋级并记 `hpo_promotion_skipped`。
- 子进程运行 trial 时设置 `OMP_NUM_THREADS/OPENBLAS_NUM_THREADS/MKL_NUM_THREADS=hpo.threads`，超时用 `trial_timeout_s`。

### 4.6 存储（增量新表，不动既有表）

```sql
CREATE TABLE IF NOT EXISTS candidate_spec (
    id TEXT PRIMARY KEY,               -- config_hash
    experiment_id TEXT NOT NULL,
    structure_id TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    source_hash TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS hpo_trial (
    trial_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL,
    structure_id TEXT NOT NULL,
    trial_index INTEGER NOT NULL,
    config_hash TEXT NOT NULL,
    params_json TEXT NOT NULL,
    seed INTEGER NOT NULL,
    fidelity TEXT NOT NULL,            -- always 'dev' in E1
    status TEXT NOT NULL,
    fit_count INTEGER DEFAULT 0,
    dev_proxy REAL,                    -- NEVER copied into node.combined_score
    dev_metrics_json TEXT,
    cache_hit INTEGER DEFAULT 0,
    failure_reason TEXT,
    promoted_node_id TEXT,             -- set only when promoted to a full evaluation
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS eval_cache (
    key TEXT PRIMARY KEY,
    fidelity TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT
);
```

晋级节点：`Node.operator` 需要一个新值 `OperatorType.HPO = "hpo"`（`common/schemas.py`）；`GENERATIVE_OPERATORS` **不**加入它；`artifact.code` 为编译脚本，`intent`/`hypothesis` 为程序化生成的中文说明（含 trial_id、params 摘要）。**节点分数只来自完整 evaluator**；`hpo_trial.dev_proxy` 与节点分数在存储层物理分离（G4）。新增枚举值后必须运行 `scripts/export_web_contracts.py` 并提交重新生成的 `web/openapi/*`，`scripts/check_web_contracts.py` 通过；除此之外不改 Web。

### 4.7 缓存

`optimization/cache.py`：

```python
def cache_key(*, source_hash, config_hash, data_version, evaluator_hash, fidelity, seed, env_fingerprint) -> str
def env_fingerprint(threads: int) -> dict   # python, numpy, pandas, sklearn, lightgbm versions, thread settings, platform machine, cpu_count
```

键对规范化 JSON 取 sha256。`data_version` 是 `train_labels.csv`+`train_history.csv.gz`（dev）或 +`val_*`（full）的 sha256（以 `(realpath,size,mtime_ns)` 记忆，避免重复哈希大文件）。`cache.enabled=false` 默认不查不写；`cache.full_eval=false` 默认不缓存完整评估（原因见 §4.1 注释）。命中：账本写 `cache_hit=True` 零成本记录，trial 的 `cache_hit=1`，**不增加新样本、不重复计 fit**；任一键成分变化即未命中。

### 4.8 导出与入口

- `hpo_runner.run_hpo(task_dir, config, *, runs_dir, artifacts_dir, adapter=None, experiment_id=None) -> HpoResult`：创建/复用 experiment 行（沿用 `Store`），先做 init 评估记录（不改 init），按 §4.5 执行；在 `artifacts_dir/hpo/` 写 `best.py`（= 最优晋级节点的 `artifact.code` 原文）、`trials.jsonl`、`hpo_summary.json`（含账本汇总、各结构 trial 数、fit 总数、晋级与完整评估分、`stop_reason`）。
- `scripts/autotune_hpo.py`：解析参数后调用 `run_hpo`，**不新增 `fe` 子命令**（保持 CLI 八命令）。`hpo.enabled=false` 时直接以明确消息退出非零，不做任何事。
- **旧路径不变**：`fe evolve local` 在 E1 中不调用 HPO；engine 接入留给 E2 的配额调度（§5.7）。

### 4.9 E1 验收（全部可由命令判定）

1. `python scripts/autotune_hpo.py --task-dir benchmark/hdd_mvp --config <cfg> --mock-eval` 之类**离线**路径：测试用合成数据与假 adapter 跑通，不需 LLM、不需 API key、不读真实 `data/`。
2. 同 seed、同配置运行两次：`trials.jsonl` 中每个 trial 的 `params`、`config_hash` 逐位相同；`best.py` 的 `source_hash` 相同。
3. 导出的 `best.py` 以原任务 I/O 合同独立运行（测试里用合成数据 `python best.py --data-dir ... --split val --out ...` 生成合法 CSV，并通过 adapter `static_check`）。
4. 账本：`sum(model_fit_count) <= max_fits_total`；每个 trial（含 failed/timeout/refused 前已计的）都有记录；`evaluator_calls` 仅出现在晋级的 full_eval。
5. `hpo_trial.dev_proxy` 与任何 `node.combined_score` 无关联；全局 best 只在完整评估后更新。
6. 默认配置下 §3.10 的 D1～D4 仍通过，并追加 D5/D6（见下）。
7. 付费真实比较（B 组）**不属于 E1 合入条件**；仅在后续明确授权的任务中按冻结协议执行，结果写入 `docs/plans/autotune/RESULTS_B.md`（新建时留空表头，不预填）。

### 4.10 E1 测试（精确清单）

`tests/test_autotune_parameter_space.py`

| 编号 | 断言 |
|---|---|
| P1 | 每个参数的边界值（low/high）通过 `validate_values`，略超出者返回非空错误列表。 |
| P2 | `log=True` 且 `low<=0` 构造 `ParamDef` 抛 `ParameterSpaceError`。 |
| P3 | 条件参数：`when` 不满足时采样结果不含该键；手工传入则校验失败。 |
| P4 | 约束 C1：`weight_policy` 与 `scale_pos_weight` 同时生效 → 校验失败；C2、C3 同理。 |
| P5 | 采样 2000 次，全部通过 `validate_values`（空间自洽）。 |
| P6 | 未知约束 id 抛 `ParameterSpaceError`。 |

`tests/test_autotune_search.py`

| 编号 | 断言 |
|---|---|
| S1 | 同 seed、同 structure：`propose(n=8)` 与 `propose(n=4)`+`propose(start=4,n=4)` 结果逐项相同。 |
| S2 | 不同 seed 的提案不同；不同 structure_hash 的提案不同。 |
| S3 | `config_hash`：改任意参数/seed/space_version → 变；仅改 dict 键顺序 → 不变。 |
| S4 | `search="tpe"` 配置构造抛 `ValueError`。 |

`tests/test_autotune_dev_split.py`（合成数据）

| 编号 | 断言 |
|---|---|
| V1 | 训练段与 dev 段 `serial` 集合不相交。 |
| V2 | 训练段每行满足 `cutoff+horizon+purge < dev 最早 cutoff`。 |
| V3 | 某侧阳性数不足 → `DevSplitError`，且 `hpo_runner` 对应 trial 状态为 `refused`、账本无 `hpo_fit` 记录。 |
| V4 | 对同一合成数据，早/晚 cutoff 边界与 `HDDAdapter._build_analysis_data` 的取整一致（对照测试，防漂移）；且调用后 `HDDAdapter` 行为未变。 |
| V5 | `report` 中的丢弃计数与手算一致。 |

`tests/test_autotune_data_guard.py`

| 编号 | 断言 |
|---|---|
| X1 | `assert_public_train_only` 拒绝 `.../eval_only/val_labels.csv`、`.../holdout/x`、`.../holdout_labels/x`、`val_index.csv`、`val_history.csv.gz`。 |
| X2 | 在 `tmp_path` 建指向 `eval_only` 的符号链接，守卫拒绝（解析后判断）。 |
| X3 | 对新增源码做文本扫描：`holdout`/`eval_only`/`val_labels` 只出现在守卫的拒绝名单中；`optimization/` 不含 `smart_`、`serial_number`、`hdd`。 |
| X4 | 全部新增测试文件不含对 `benchmark/hdd_mvp/data` 的路径引用。 |

`tests/test_autotune_leakage.py`

| 编号 | 断言 |
|---|---|
| LK1 | 在合成数据上给模板脚本的 scaler/编码器/`fit` 打补丁记录其看到的 serial 集合：全部 ⊆ 训练段 serial，与 dev 段 serial 交集为空。 |
| LK2 | 模板脚本在 `train_labels.csv` 被置为全随机标签时输出的阈值不依赖 `<split>` 数据（对 `val_history` 内容做置换后阈值不变）。 |
| LK3 | 运行 trial 的子进程无法打开 `eval_only` 路径：测试里把该路径设为不存在目录并确认全流程不触及它（`strace` 不可用时，用 patch `open` 记录路径断言）。 |

`tests/test_autotune_templates.py`

| 编号 | 断言 |
|---|---|
| T1 | 两个模板编译后均通过 adapter `static_check`；含四个 FE-BLOCK 标记且成对。 |
| T2 | 用合成数据运行编译脚本，输出列为 `serial_number,score,alarm`，行数 == 索引行数，`alarm∈{0,1}`。 |
| T3 | 计数器补丁验证 `fits_per_run` 声明属实。 |
| T4 | 同 spec 两次 `compile_spec` 逐字节相同；改一个参数 → `source_hash` 变而 `structure_hash` 不变。 |
| T5 | 导出 `best.py` 与对应节点 `artifact.code` 逐字节相同，且其内嵌 `PARAMS` 与 `hpo_trial.params_json` 解析后相等。 |

`tests/test_autotune_hpo_runner.py`（假 adapter：以确定性函数返回 `EvalResult`，无真实 evaluator）

| 编号 | 断言 |
|---|---|
| R1 | `max_fits_total` 严格不被超过（最后一个 trial 不"透支"）。 |
| R2 | 失败/超时 trial 仍有账本记录且 fit 计入。 |
| R3 | 晋级节点 `operator=="hpo"`，其 `combined_score` 等于假 adapter 返回值，与 `dev_proxy` 无关；把 `dev_proxy` 设成极大值不改变节点分数与全局 best。 |
| R4 | `ledger.full_eval_cap` 到顶后不再晋级，事件 `hpo_promotion_skipped` 存在。 |
| R5 | 缓存：同键第二次运行命中，账本 `cache_hit` 记录，fit/eval 计数不增；改 `evaluator_hash`、数据哈希、seed、线程任一 → 未命中。 |
| R6 | `hpo.enabled=false` 时 `scripts/autotune_hpo.py` 非零退出且不写 DB。 |
| R7 | 同 seed 两次运行 `trials.jsonl` 逐行相同（忽略时间字段）。 |

`tests/test_autotune_default_off.py` 追加：

| 编号 | 断言 |
|---|---|
| D5 | `EvolveConfig().autotune.hpo.enabled is False`、`cache.enabled is False`；`from_dict`/`with_overrides` 往返保留 `hpo.trials_per_structure`。 |
| D6 | 默认配置 mock 运行：DB 中 `hpo_trial`、`candidate_spec`、`eval_cache` 表存在但无行；节点序列与 E0 基线运行一致。 |
| D7 | `hpo.enabled=true` 且 `ledger.enabled=false` → `ValueError`。 |

### 4.11 E1 不得改动

G1～G10，以及：`cloud/selection.py`、`cloud/operators.py`（E1 不接引擎）、`cloud/crossover.py`、`tasks/hdd_adapter.py`（读取/复用其公开方法可以，不改）、既有 `Store` 表结构、`fe` 子命令集合。

---

## 5. E2：局部编辑、消融定位和真实反馈

**目标**：用唯一匹配的 SEARCH/REPLACE 局部编辑取代"每次整文件重写"，被拒绝的编辑可审计且仍计账；给 LLM 的反馈包含真实可得的信息并明确标出缺失项。

**前提**：E1 合入，且 §4.9 全部验收通过。

### 5.1 配置（`AutotuneConfig` 新增 `patch`、`ablation`、`feedback`、`quota`；默认全关）

```python
class PatchConfig(BaseModel):
    enabled: bool = False
    fallback: Literal["reject", "draft"] = "reject"   # reject = no silent full rewrite
    max_hunks: int = Field(default=3, ge=1, le=8)
    max_changed_lines: int = Field(default=60, ge=1)

class AblationConfig(BaseModel):
    enabled: bool = False
    max_units: int = Field(default=6, ge=1, le=12)
    paired_resamples: int = Field(default=200, ge=50)   # independent of discovery.bootstrap_b and evaluator N_BOOTSTRAP

class FeedbackConfig(BaseModel):
    enabled: bool = False
    max_chars: int = Field(default=2500, ge=500)

class QuotaConfig(BaseModel):
    enabled: bool = False
    shares: dict[Literal["hpo", "patch", "draft"], int] = {"hpo": 3, "patch": 5, "draft": 2}  # integer weights
    plateau_evals: int = Field(default=8, ge=2)    # full evals without best improvement before a controlled restart
    max_restarts: int = Field(default=2, ge=0)
    archive_cap: int = Field(default=20, ge=0)
```

校验：`patch.enabled`/`quota.enabled` 要求 `ledger.enabled`；`quota.enabled` 要求 `operators.bandit=false`（本阶段不同时改动 selector、bandit 与模型路由）、`selection.policy` 不变；`quota.shares` 的键只能是 hpo/patch/draft 且和 > 0；`ablation.enabled` 要求 `hpo.enabled`（消融复用 E1 的 dev 基础设施）。所有默认值为起始提案，E2 合入前冻结。

### 5.2 Patch 格式与应用

LLM 响应片段（在现有 `<hypothesis>`/`<intent>` 之外）：

```
<patch parent_hash="sha256:<hex>" module="feature|model|train|calibration">
<<<<<<< SEARCH
...exact text from the parent...
=======
...replacement...
>>>>>>> REPLACE
</patch>
```

一个 `<patch>` 可含至多 `max_hunks` 个 SEARCH/REPLACE 段，**全部落在同一个 `module` 内**。统一 diff 格式：**E2 不实现**（遇到 `---/+++` 按 `unsupported_format` 拒绝）；这是在设计允许的两种格式中选一种的实施决定，记入 PR 说明。

`optimization/patching.py`

```python
class PatchRejectReason(str, Enum):
    PARSE_ERROR = "parse_error"
    UNSUPPORTED_FORMAT = "unsupported_format"
    PARENT_HASH_MISMATCH = "parent_hash_mismatch"
    NO_MATCH = "no_match"
    MULTIPLE_MATCH = "multiple_match"
    OUT_OF_BLOCK = "out_of_block"
    MULTI_MODULE = "multi_module"
    PROTECTED_MARKER_EDIT = "protected_marker_edit"
    TOO_MANY_HUNKS = "too_many_hunks"
    TOO_LARGE = "too_large"
    SYNTAX_ERROR = "syntax_error"
    STATIC_RULE_VIOLATION = "static_rule_violation"
    EMPTY_SEARCH = "empty_search"
    OVERLAP = "overlap"

@dataclass(frozen=True)
class Patch: parent_hash: str; module: str; hunks: list[Hunk]
@dataclass(frozen=True)
class PatchResult:
    ok: bool
    code: str | None
    reason: PatchRejectReason | None
    detail: str
    module: str | None
    changed_lines: int

def parse_patch(response: str) -> Patch | PatchResult: ...
def apply_patch(parent_code: str, patch: Patch, *, static_check: Callable[[str], str],
                max_hunks: int, max_changed_lines: int) -> PatchResult: ...
def module_spans(code: str) -> dict[str, tuple[int, int]]: ...   # from FE-BLOCK markers
def source_hash(code: str) -> str: ...                            # same normalization as §3.3
```

`apply_patch` 校验顺序（先到先拒，原因码即第一个失败项）：`parent_hash` 与 `source_hash(parent_code)` 一致 → 模块标记存在且成对 → 每个 SEARCH 非空、在**原文**中恰好匹配一次（精确文本，统一 `\r\n`）→ 每个匹配区间完全落在声明模块的 `FE-BLOCK` 之内 → 各 hunk 区间互不重叠 → 替换文本不得包含或删除 `FE-BLOCK-*` 标记行 → hunk 数/改动行数上限 → `ast.parse` 通过 → `static_check` 返回空串。任何一步失败即返回 `ok=False`，**不得**回退为整文件重写；父代码字符串不被修改。

父代码没有 `FE-BLOCK` 标记（`init.py`、自由程序）时：patch 算子对该父节点**不可用**（引擎不选它，记 `patch_unavailable` 事件），而不是静默改走 draft；`patch.fallback="draft"` 时才允许走 draft，且事件 `patch_fallback_draft` 明示。

### 5.3 引擎接线（仅 `patch.enabled` 时生效）

- `OperatorType.PATCH = "patch"`；同 E1 重新导出 Web 契约。
- `cloud/operators.py`：新增 `PatchOperator`（与 `RefineOperator` 同构：构造提示 → `llm.chat` → 解析），`OperatorContext.set_target_module(name)`、`set_feedback_text(text)` 两个可选设置器；`build_user_message` 在这些字段为空时输出必须与现状**逐字节相同**（测试 F6）。patch 提示要求：只输出一个 `<patch>`，只改一个模块，说明假设与预期。
- `cloud/engine.py`：在 `_run_one_iteration_inner` 里，算子为 PATCH 时调用 `PatchOperator`→`apply_patch`→得到完整代码后**走与现有子节点完全相同的**预检/性能门/smoke/评估链路；拒绝时写事件 `patch_rejected`（payload：`parent_id`、`reason`、`module`、`detail` 截断到 400 字符）并经 `_handle_invalid_generation(..., operator=OperatorType.PATCH)` 创建 INVALID 节点（沿用既有拒绝记录方式，tree 可见）；**Repair 不对 `patch_rejected` 节点触发**（拒绝是终态，避免把"局部编辑"悄悄变成整文件修复）。被拒 patch 的 LLM tokens 照常入账本（stage `generate`，`status="rejected"`）。
- 事件新增：`patch_proposed`、`patch_applied`（含 `module`、`changed_lines`）、`patch_rejected`、`patch_unavailable`、`patch_fallback_draft`。

### 5.4 模块划分与单模块原则

模板的四个 `FE-BLOCK`（feature/model/train/calibration）已在 E1 就位。PatchOperator 的目标模块选择：优先使用 §5.5 消融报告里 `delta` 最大的模块；无报告时按固定轮转顺序（feature→model→train→calibration）。一个候选只改一个模块；参数 trial（hpo）、改特征（patch:feature）、换模型（draft）在事件与节点 `intent` 中分别标注，不得混在同一未标注变更里。

### 5.5 消融定位（`optimization/ablation.py`）

```python
@dataclass
class AblationEntry: unit: str; kind: Literal["remove", "replace"]; dev_proxy: float | None; delta: float | None; ci: tuple[float, float] | None
@dataclass
class AblationReport: baseline_dev_proxy: float; entries: list[AblationEntry]; fits_charged: int; resamples: int; method: str
def run_ablation(spec: CandidateSpec, *, units: list[str], dev_runner: DevRunner, ledger: CostLedger,
                 max_units: int, paired_resamples: int, seed: int) -> AblationReport: ...
```

- 作用对象：`feature_groups` 的逐组移除；`model` 块替换为同族默认参数模板。**固定在 E1 的 dev 划分上**，不碰 val。
- 每个变体都是一次 dev trial：账本 `stage="ablation"`、`model_fit_count=fits_per_run`；`max_units` 封顶，超出的单位不执行并记录 `skipped_budget`。
- `delta` 与 `ci`：基线与变体在**同一批 dev 行**上做成对差；`ci` 用按设备（serial）整体重采样的 percentile bootstrap，`paired_resamples` 次（默认 200），RNG 种子固定为 `seed`。它是**内部诊断**，不是对 ROS 的统计结论，报告字段 `method="paired_serial_bootstrap(dev_proxy)"`。
- 输出只用于挑选 patch 目标模块和写入反馈；**不更新任何节点分数或全局 best**。

### 5.6 反馈（`optimization/feedback.py`）

```python
@dataclass
class FeedbackBundle:
    components: dict[str, float | None]           # auprc, recall_at_far, f1_p10, time_factor from child eval metric
    parent_delta_components: dict[str, float | None]
    fn_fp_groups: list[dict] | None               # from metric["analysis"] when present, else None
    analysis_status: Literal["computed", "not_computed"]
    error_tail: str | None                        # get_error_tail(...) for failures
    timing: dict[str, float | int | None]         # eval cost_time, fit_count, stage wall
    change_scope: dict                             # module, changed_lines, hunks, operator
    intent: str; hypothesis: str
    paired: dict | None                           # n_common, delta_dev_proxy, ci_low, ci_high, resamples, method
    missing: list[str]                            # e.g. ["analysis", "paired_unavailable", "timing_hotspot"]

def build_feedback(parent: Node, child: Node, *, dev_preds: Mapping[str, Any] | None, config: FeedbackConfig) -> FeedbackBundle: ...
def render_feedback(bundle: FeedbackBundle, *, max_chars: int) -> str: ...   # Chinese text; deterministic
```

规则：

- `analysis_status="not_computed"`（例如默认的 `analysis.enabled=false`，E0.4 已定位原因）时，渲染文本**明确写"错例画像未计算"**，且提示词不得要求"针对画像中的 FN/FP 群体改进"。
- `paired` 仅当父子双方都有同一 dev 划分上的预测（模板谱系节点会把 dev 预测保存到 `artifacts_dir/dev_preds/<node_id>.npz`）才有；否则 `None` 且 `missing` 含 `"paired_unavailable"`。
- 禁止把 `get_noise_delta`（基于 f1 bootstrap std 的工程噪声门）当作父子 ROS 差的置信区间；渲染文本中若出现该量，必须标注"工程噪声门"。
- 关键增量晋级/归因用 `paired`；没有 `paired` 时只说"未提供成对证据"，不得用单边分数差下结论。
- `render_feedback` 截断到 `max_chars`，截断处加固定标记；输出对同输入逐字节确定。

### 5.7 固定配额与 plateau 重启（`optimization/quota.py`，`quota.enabled` 才接入引擎）

```python
def next_operator(counts: Mapping[str, int], shares: Mapping[str, int]) -> Literal["hpo", "patch", "draft"]: ...
```

确定性（无 RNG）：选择"累计配额缺口最大"的算子（最大余数法），平局按固定顺序 hpo→patch→draft。`draft` = 现有 `RefineOperator` 整文件输出（沿用 `OperatorType.REFINE`，事件里标 `quota_slot="draft"`）。`hpo` 槽位调用 E1 的 `hpo_runner` 的单结构一步（对被选父节点所在结构做至多 `trials_per_structure` 个 trial，晋级走完整评估）。父节点选择仍是现有 UCT，不改。

plateau 重启：连续 `plateau_evals` 次完整评估全局 best 无提升 → 触发一次受控 restart：以根节点（init）为父生成一个 draft，事件 `restart_triggered`；总数不超过 `max_restarts`；restart 的评估与所有成本照常入账。

探索档案：新表

```sql
CREATE TABLE IF NOT EXISTS explore_archive (
    experiment_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    reason TEXT NOT NULL,          -- 'valid_but_worse_distinct'
    parent_score REAL, score REAL,
    module TEXT,
    created_at TEXT,
    PRIMARY KEY (experiment_id, node_id)
);
```

收录规则（E2 版，不含行为去重，那是 E3）：节点有效、完整分低于父节点、其 `source_hash`/`config_hash` 与全库已有不同、数量不超过 `archive_cap`。**冠军替换仍只看完整评估分**，档案不参与 best。

### 5.8 E2 对既有行为的约束

`quota.enabled=false` 时 `_choose_operator`、`_available_operators` 路径逐字节不变；`patch.enabled=false` 时 `OperatorContext`/`build_user_message` 输出不变；`feedback.enabled=false` 时不调用 `build_feedback`。`operators.enabled` 白名单**不**扩展（patch/hpo 由 quota 调度，不走 bandit）。

### 5.9 E2 验收（全部可由命令判定）

1. 单元与回归：§5.10 全部测试通过，`python -m pytest tests/ -q` 全绿。
2. 离线 smoke（`ScriptedLLM`/`MockLLM.set_responses` 脚本化，无 API key）：构造 6 次迭代，依次为合法 patch、`parent_hash_mismatch`、`multiple_match`、`out_of_block`、`syntax_error`、合法 patch；最终事件流中 `patch_applied`×2、`patch_rejected`×4，原因码逐一匹配；账本中 6 次生成的 tokens 全部在列；被拒 patch 无 `full_eval` 记录。
3. 默认关闭兼容：§5.10 的 D8～D10 通过；E0 基线协议运行的节点序列不变。
4. 付费真实比较（C 组对 A/B）**不属于合入条件**；结果表 `docs/plans/autotune/RESULTS_C.md` 只建空表头。比较口径（实施时填）：best ROS 对完整评估调用数/token/墙钟三条曲线、`valid_rate_first_eval`、`valid_rate_after_repair`、`positive_gain_rate`、`unique_candidate_rate`、每有效候选 token、拒绝原因分布。工程目标"最终有效率 ≥80%"是**待测目标，不是既得结果**。未提分时报告必须能分类解释：重复（同 source_hash）/ 失效（invalid、patch_rejected 各原因）/ 噪声（未过工程噪声门）/ 无用变更（有效但 delta≤0）。

### 5.10 E2 测试（精确清单）

`tests/test_autotune_patching.py`

| 编号 | 断言 |
|---|---|
| PT1 | 合法单 hunk：`ok=True`，结果代码等于手工替换后的文本；父字符串未被改动。 |
| PT2 | `parent_hash` 不符 → `PARENT_HASH_MISMATCH`。 |
| PT3 | SEARCH 在原文出现 2 次 → `MULTIPLE_MATCH`；出现 0 次 → `NO_MATCH`；空串 → `EMPTY_SEARCH`。 |
| PT4 | SEARCH 匹配在声明模块之外（即便文本唯一）→ `OUT_OF_BLOCK`。 |
| PT5 | 替换文本删除/复制 `FE-BLOCK` 标记行 → `PROTECTED_MARKER_EDIT`。 |
| PT6 | 两个 hunk 区间重叠 → `OVERLAP`；超过 `max_hunks` → `TOO_MANY_HUNKS`；改动行超限 → `TOO_LARGE`。 |
| PT7 | 替换后语法错误 → `SYNTAX_ERROR`；引入 evaluator 禁用模式 → `STATIC_RULE_VIOLATION`（用 adapter 的 `static_check`）。 |
| PT8 | 统一 diff 输入 → `UNSUPPORTED_FORMAT`；缺少 `<patch>` 或残缺 → `PARSE_ERROR`。 |
| PT9 | 父代码无 FE-BLOCK 标记：`module_spans` 为空，引擎侧视为 `patch_unavailable`。 |
| PT10 | 属性测试（固定种子 200 例）：任何拒绝都不返回 `code`，任何接受的结果都通过 `ast.parse`。 |

`tests/test_autotune_engine_patch.py`（`MockLLM.set_responses` 脚本化；合成任务夹具 `tests/fixtures/toy_task` 扩展一个带 FE-BLOCK 的 init 副本，放在测试自己的 `tmp_path`，**不改** `tests/fixtures/toy_task` 既有文件）

| 编号 | 断言 |
|---|---|
| EP1 | §5.9 第 2 条的混合序列：事件类型与原因码逐一匹配。 |
| EP2 | 每个 `patch_rejected` 产生一个 INVALID 节点（`operator=="patch"`），且**没有** repair 事件/LLM 调用。 |
| EP3 | 被拒 patch 的 tokens 在账本中 `status=="rejected"`，`totals().prompt_tokens+completion_tokens` 等于 `llm_call` 表之和。 |
| EP4 | `patch.fallback="reject"` 时父无标记 → 无整文件重写发生；`"draft"` 时出现 `patch_fallback_draft` 事件且走 REFINE。 |
| EP5 | 接受的 patch 子节点经历与普通子节点相同的预检/smoke/评估，`node.combined_score` 来自假 adapter。 |

`tests/test_autotune_ablation.py`

| 编号 | 断言 |
|---|---|
| AB1 | 每个消融单位在账本中恰有一条 `stage="ablation"`、`model_fit_count==fits_per_run` 的记录；超过 `max_units` 的单位被跳过且报告记 `skipped_budget`。 |
| AB2 | 同 seed 两次 `AblationReport` 完全相同（含 `ci`）。 |
| AB3 | 构造"移除特征组 X 使 dev_proxy 明显下降"的合成数据，报告中 X 的 `delta` 最大。 |
| AB4 | 消融不修改任何节点 `combined_score`，不更新全局 best。 |
| AB5 | 变体与基线使用同一批 dev 行（行集合相等）。 |

`tests/test_autotune_feedback.py`

| 编号 | 断言 |
|---|---|
| F1 | `analysis_status="not_computed"` 时渲染文本含"错例画像未计算"，且不含"根据 FN 画像"类指令。 |
| F2 | 缺少成对预测 → `paired is None` 且 `missing` 含 `"paired_unavailable"`。 |
| F3 | 有成对预测时 `n_common` 等于共同样本数；父子预测序错位（行顺序不同）也能按 serial 对齐，结果与按序对齐相同。 |
| F4 | 渲染对同输入逐字节稳定；超长输入被截断到 `max_chars` 并含固定截断标记。 |
| F5 | 文本中出现噪声门数值时必带"工程噪声门"字样。 |
| F6 | `feedback.enabled=false` 且 `target_module` 未设置：`build_user_message(ctx)` 与改动前逐字节相同（以改动前生成并提交到 `tests/fixtures/autotune/user_message_golden.txt` 的黄金文件对照；该黄金文件须在**修改 `operators.py` 之前**由未改动的代码生成）。 |

`tests/test_autotune_quota.py`

| 编号 | 断言 |
|---|---|
| Q1 | `shares={"hpo":3,"patch":5,"draft":2}` 连续 100 次 `next_operator` 的计数恰为 30/50/20；同输入序列逐位相同。 |
| Q2 | `quota.enabled=true` 且 `operators.bandit=true` → `ValueError`。 |
| Q3 | plateau：连续 `plateau_evals` 次无提升触发恰好一次 `restart_triggered`，总次数不超过 `max_restarts`。 |
| Q4 | `explore_archive` 只收录有效、分低于父、`source_hash` 全库唯一者，数量不超过 `archive_cap`；其存在不改变 best。 |

`tests/test_autotune_default_off.py` 追加：

| 编号 | 断言 |
|---|---|
| D8 | 默认配置下 `OperatorType` 新增值不出现在任何运行的事件/节点里；`explore_archive` 表存在但无行。 |
| D9 | `EvolveConfig.from_dict` 往返保留 `patch`、`quota.shares`、`ablation.paired_resamples`；未知 `quota.shares` 键报错。 |
| D10 | `scripts/check_web_contracts.py` 通过（OpenAPI 仅增加算子枚举值）。 |

### 5.11 E2 不得改动

G1～G10，以及：`cloud/selection.py`（UCT/PUCT）、`OperatorsConfig` 的白名单与 bandit 逻辑、`cloud/crossover.py`、`discovery/**`、`analysis` 的默认值（只在反馈里标注"未计算"，不顺手开启）、`webapi/**`（除契约重导出）。

---

## 6. E3：借鉴 FM 的冷启动与逻辑岛（仅设计已定部分；实施前需补设计）

**设计已决定**（设计 §7、§11）：

- 冷启动方向建议 2～3 个：线性与校准、趋势树模型、型号/缺失处理；原 init 是共同任务起点，每个方向生成并评估一个不同的完整结构。**所有种子的生成、调参、评估都计入同一总预算**；与伐谋比较时不得额外免费提供历史 best。
- 树继续作为血统与审计结构；`island_id` 与种群成员关系放**旁路表**，不覆盖 `parent_id`；迁移复制成员关系并引用既有候选，**不伪造新评估/新分数**。
- 去重：exact source hash；AST/模块摘要识别结构（不得过度归一化抹掉数值参数；参数变体用独立 config hash 区分）；train-dev 的预测秩、告警集合、错误群体衡量行为。LLM 新颖性与代码 embedding 只作辅助，不决定分数。
- 每岛约 4～6 个候选，2～3 岛；按**累计完整评估次数**触发迁移和停滞判断；种群小于可辨认结构数时不启用复杂聚类。
- 高分同质的重复方案不长期占满槽位；略低分但结构/错误模式不同的候选保留有限探索配额。
- 交叉：先迁移结构/经验，再做确定性 rank blend 作为集成基线；学习 blend 权重/stacking 只能用 OOF 预测；两份模型的训练/执行成本全计入；仅当父代预测互补、剩余时间预算允许、参数/特征接口兼容时才允许；保留现有 crossover，但增加这些资格与对照。
- 先固定调度，再考虑基于单位成本收益的自适应；不得把"valid"当收益。
- 比较 D（C+冷启动/岛）与 C；无收益则默认保持 C。

**【设计未定】——实施前必须先补设计，不得自拟**：每岛的具体配额与探索比例、迁移间隔与停滞阈值的数值（设计写明"第一轮冻结"）、行为档案的具体距离度量与阈值、岛屿旁路表的列定义、互补性检验的判据、rank blend 的具体形式。

**E1/E2 已为 E3 留下的口子（不要提前做更多）**：`structure_hash`/`config_hash`/`source_hash` 三种哈希、`explore_archive` 表、dev 预测 `.npz` 的保存。E3 之前不创建 `island` 相关任何表或配置键。

**必要测试清单（已由设计决定的范畴）**：种群边界、去重保留参数差异、迁移/多父血统、重启恢复、预算公平、OOF 集成不碰 val 标签。

## 7. E4：本地异步与性能（仅设计已定部分）

**设计已决定**（设计 §9）：

- 先记录 generation/evaluation/analysis/repair 的耗时与峰值内存；起始评估并发 1、生成并发 2，未经 RSS/CPU 证据不提高评估并发；固定 LightGBM/BLAS 线程上限。注意 `llm.max_concurrency=4` 不等于主循环实际并行度，必须从真实任务队列与耗时确认。
- 单调度进程为 SQLite **唯一 writer**；生成/评估 worker 只返回结果，经队列入账；worker 不直接写库。候选独立工作目录、任务只读；SQLite 放本地盘，数据与大产物放 NAS。
- 队列任务有 attempt、lease、幂等结果键和重启恢复；完成结果只入账一次。
- 提交前预留预算（token/调用/算力），完成或失败后结算；已花费不因失败退款；接近预算时停止提交并结算在途任务。（E0 已定义预留/结算接口，E4 直接复用。）
- 保留同步确定性 debug 模式；记录提交序列与完成序列（异步完成顺序会影响搜索）。
- 缓存键含 code/config、数据版本、evaluator、保真度、seed、依赖/环境、线程设置；缓存命中不增加新样本。共享特征缓存只在可信预处理层。
- 做同候选集同步/异步性能比较（吞吐、总 CPU、RSS、最终评分一致性）。Ray 与多机放在本地吞吐证据之后；不得把墙钟下降说成样本效率提高。

**【设计未定】**：lease 时长、重试次数、超时值、队列实现（线程/进程/`asyncio`）、恢复时对在途任务的判定细则。

**必要测试清单**：不重复记分、不丢成本、重启可恢复、并发下预留不超卖、同步/异步结果一致性。

## 8. E5：受限 RSI（仅设计已定部分，满足条件才开启）

**设计已决定**（设计 §10）：

- 外层只允许改：父代选择、提示模板、上下文压缩、操作配额、局部编辑策略。核心 evaluator、数据划分、预算核算、测试预期、最终基准隔离规则固定，运行中不得改 active engine。
- 三个数据层：元开发任务（反馈）、元选择任务（接受提案）、独立保留任务（仅阶段结束评估）。**禁止把 HDD 私有 test 放进外层循环**。
- 每个策略版本用相同任务预算与模型；比较标准化 best-so-far 轨迹面积、终分、有效候选和总成本；跨任务标准化基准在实验前冻结；仅减少实验次数却降低质量不算改进。
- 首批最多 3～5 个提案；至少涵盖多个可运行的独立任务或时间变体，加 repair/预算/恢复专项回归。SSD/SmartMem stub 不算可运行泛化任务。没有合格元任务集就暂停，仅实现轨迹档案。
- 每个提案独立 checkout/运行包；接受后更新版本并可回退。
- 称"递归改进"需多次接受后的新 agent 确实参与后续提案，且收益在未参与选择的任务上保留；只有一次 prompt 优化就如实称策略优化。PCPO 等模型权重训练不纳入当前实施。保存同 agent 跨任务与不同 agent 同任务的对照轨迹。

**【设计未定】**：元任务集具体构成、标准化基准公式、接受阈值、元预算数值、策略插件接口。**当前状态：不具备开启条件，E5 不实施。**

## 9. K1：恢复现象因子发现（仅设计已定的门槛，后置）

> 2026-10-04 更新：89f4bdd1 运行后，K1 的具体执行计划见 [KD_NEXT_RUN_PLAN_2026-10-04](KD_NEXT_RUN_PLAN_2026-10-04.md)（KD1-F，解耦原子因子；discovery 在该次运行中因配置未启用而为 0）。

前置：E2 完成 + KD 验证链修复。

- [ ] 按 KD 文档修真实日期、独立确认、e-BH 与统计校准问题。（**本计划不触碰 `discovery/**` 与其统计参数，见 G5；该修复是 K1 自己的前置任务。**）
- [ ] 从单模块/单因子变更提取 claim；联合换模型的收益不归给某个特征。
- [ ] 新因子与本阶段固定强基线比较，保存成对预测与增量区间。
- [ ] 文献新颖性、预测增量、机制结论分开报告。
- [ ] KD2 锦标赛仍为独立研究，先与固定反证清单做同预算价值比较。
- 原则（设计 §1/§11.3）：已反复使用的 val 是工程搜索/对比信号，不是独立新知识确认集；新的确认数据协议必须先冻结。

**【设计未定】**：新确认数据协议的具体划分、KD 修复项的验收细则。

---

## 10. 实验协议与完成定义

### 10.1 第一批成本口径（设计已定，具体运行需授权）

- 小型协议：总**完整 evaluator 调用上限 50**（含 baseline、冷启动、Repair、晋级复核）；HPO/dev/消融的 fit 与 CPU/token 另设显式上限（E1/E2 的 `max_fits_total` 等）。50 是建议比较预算，不等于现有 `--iterations 50`。
- 先完成离线与合成回归；真实比较按 A→B→C→必要时 D 逐阶段冻结，不一次开启所有新能力。每阶段一次真实比较仅用于功能与成本证据，**不据此声称跨 seed 稳定优越**；进一步重复须在具体实验计划里写明预算与必要性。

### 10.2 比较组

A：当前可复现 REFINE 基线（E0 协议）；B：纯结构化随机 HPO（E1）；C：HPO + patch（E2）；D：C + 冷启动/逻辑岛（E3）；RSI 单列后续。

### 10.3 固定报告字段

`run_id`、Git 与依赖版本、模型、seed、数据/evaluator hash、候选/fit/eval 数、`valid_rate_first_eval` 与 `valid_rate_after_repair`、唯一结构数、操作收益、best-so-far 对三种成本的曲线、终分、运行时间、token、CPU/RSS、错误/停止原因、冠军复现。

接入 FM 对照时必须下载同任务可运行 `best.py` 并用原 evaluator 核对；没有这些证据写"未比较"。确认平台预算与计数方式，不拿论文 aggregate 指标算差距。

### 10.4 结果表（留空，禁止预填）

| 组 | commit | run_id | 完整 eval 数 | best val ROS | 达 33.70 / 35 / 38 的成本 | 备注 |
|---|---|---|---|---|---|---|
| A | | | | | | |
| B | | | | | | |
| C | | | | | | |
| D | | | | | | |

注：33.70 为仓库同任务人工参考；38.14 为历史观察点；二者都不是新系统的承诺值。

### 10.5 最小完成标准

- [ ] E0～E2 有冻结版本、完整账本及有限真实比较证据。
- [ ] 导出 `best.py` 能以原任务接口复现；没有修改受保护基准。
- [ ] 同预算改善可靠性、成本曲线或终分；明确尚未证明的稳定性和泛化。
- [ ] 若纯 HPO 更划算，允许最终采用 HPO 主线；无增益模块默认保持关闭。
- [ ] README、命令示例与本 TODO 记录最终实现状态、版本和真实 run ID，不填预测结果。

---

## 11. 实施纪律与交接

- 每阶段按"源码与合同 → 必要回归 → 离线 smoke → 具体有限真实协议 → 结果报告"完成。
- **提交粒度**：每个编号任务（如 E0.5、E1 的 §4.3）一个或多个逻辑提交；E0.1 中每项迁移单独提交。建议 PR 切分：E0-a（报告/指标/画像，仅 docs+纯函数+脚本）、E0-b（账本+配置+接线）、E0-c（manifest+协议+退出门）、E1-a（空间/搜索/切分/守卫）、E1-b（模板/编译/缓存）、E1-c（runner+存储+晋级）、E2-a（patching+反馈）、E2-b（引擎接线+配额+消融）。
- 新配置默认关闭；所有新 CLI/config 示例标注"已实现/待实现"。秘密只从环境变量加载；历史 run 只读，回放用副本库；SQLite 用本地磁盘。
- 接手者首先读：设计文档、`AGENTS.md`、`tests/test_hdd_protected_files.py`、本计划 §1 与 E0；从 E0 开始，不根据历史 `docs/TODO.md` 的测试数直接跳到岛屿或 RSI。
- 本文件实施项完成后：勾选对应项，并在对应小节末尾追加"提交 `<sha>` / run ID / 证据路径"；失败也要记录。不得修改已冻结协议；如需变更，另起带日期的新协议文件并说明原因。
- 遇到本计划与代码现实冲突（函数改名、接口已变）：以代码为准做最小适配，并在 PR 描述里写明差异；遇到【设计未定】项：停止并上报，不要自拟。
