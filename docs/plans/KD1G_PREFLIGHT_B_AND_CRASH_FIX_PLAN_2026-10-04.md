# KD1-G 预检未通过之后：库修复裁决与两个退出码 bug 的修复计划

日期：2026-10-04。性质：**仅规划，本 PR 不含功能代码**。执行者：composer-2.5。
上游：[KD1G_NEXT_DISCOVERY_PLAN_2026-10-04](KD1G_NEXT_DISCOVERY_PLAN_2026-10-04.md)（§6 修库规则、§7 预检通过条件、§8 失败处理）。
标注：【用户提供】服务器实测；【已核实】本仓库代码；【本地复核】在本环境只读公开 `train_history.csv.gz` / `train_labels.csv` 复算（未读 `holdout*`，未跑服务器，未用标签算任何效应）；缺的写「未记录」。

## 0. 结论

1. **预检未通过，按预注册记为 outcome B，不进全流程。** 失败项是 `executable=18 < 24`。
2. **不允许使用那一次修库。** 9 条不可执行全部是数据本身的性质（该列在多数单元上没有观测，或该量在构造上恒定），不是列名、空值写法或重复写错。改它们只能是换群体或换定义，即改写因子，计划已禁止。
3. 两个会让命令在写完漏斗后退出的 bug 必须修（§3）。不改任何统计判定。
4. 下一轮改的是**新家族**，不是放宽门，也不是把这 9 条改写后重来（§4）。

## 1. 已测事实（【用户提供】，不改数字）

- 服务器 HEAD `0ab59f8a8fed6598f2950e36d8a49dd14c9e5f71`；库 `hdd_v2.jsonl` SHA256 `5cb8036fb8056476d4105e53f80694248ae7c33c652f48ecd6cf71409b6de93f`，27 行（不是 30）。
- 原库 `benchmark/hdd_mvp/.fe/runs/89f4bdd1/fe.db` 跑前跑后均 7180288 字节，mtime 2026-10-04 13:35:54 +0800，未被改。
- mock：退出码 1，约 180 秒，stdout 仅 `{"ok": false, "error_type": "DiscoverFactorsError"}`；funnel 多条 `discovery_llm_error`，错误 `UNIQUE constraint failed: claim.id`。mock 不算成功。
- 第一次 `--explore-only`（tmux fe-kd1g，16:05:57 CST 起）：退出码 1，同样只有 `DiscoverFactorsError`；`funnel.json` 在 HDD2_F006 的 `power_gate_pass` 处被截断；库事件显示 27 条都算完。原因是结果含 numpy 值无法 JSON 序列化。第二次靠进程内补丁跑通，仓库未改。
- **第二次（以此为准）**：退出码 0，16:21:54–16:28:41 CST，墙钟 407 秒。proposed 27 / executable 18 / coverage_ok 18 / deduped 18 / explore_incr 2 / power_gate 1 / frozen 1 / confirmed_stats 0 / discovered_or_confirmed 0；`duplicate_code` 0；`discovery_llm_error` 0。命令 JSON 的 `elapsed_s` 与 token 分项：未记录。`tokens_per_score_gain`：未记录（纯探索无分数变化）。
- 泳道 C 过功效门 1 条：HDD2_F004，效应 +0.06522581294659768，增量 CI 下界 +0.00012730630492871497，`power_gate_pass=true`，阶段 `frozen`。**这不是发现，没有进确认。**
- 不可执行 9 条：low_coverage 7 条（F001、F007、F008、F009、F010、F012、F014）；constant 2 条（F002、F020）。这 9 条的效应：未记录。
- 其余候选（效应 / 增量 CI 下界）：

| 候选 | 终止原因 | 效应 | 增量 CI 下界 |
|---|---|---|---|
| F003 | explore_no_increment | +0.052515156835586496 | -0.004012362380341949 |
| F005 | explore_no_increment | +0.03336129517517339 | -0.0007359486327965598 |
| F006 | explore_below_power_gate | +0.007236842580610636 | +0.00041983022631656157 |
| F011 | explore_no_increment | +0.01882511132353437 | -0.0026551661089469795 |
| F013 | explore_no_increment | +0.03206405597955919 | -0.004463816055782846 |
| F015 | explore_no_increment | +0.051727841926240914 | -0.003983027699164576 |
| F016 | explore_no_increment | +0.0527652720186258 | -0.003872400325715683 |
| F017 | explore_no_increment | +0.003057859818447972 | -0.001295897491657033 |
| F018 | explore_no_increment | -0.013981643448222558 | -0.0016346622120038206 |
| F019 | explore_no_increment | +0.007236180263082148 | -0.0014404989028411164 |
| F021 | explore_no_increment | -0.010931129333272616 | -0.001050425953281936 |
| D001 | explore_no_increment | +0.009907246644880074 | 小于 0（具体值未记录） |
| D002 | explore_no_increment | -0.02669555093619186 | 小于 0（未记录） |
| D003 | explore_no_increment | +0.021242088617121957 | 小于 0（未记录） |
| D004 | explore_no_increment | -0.01240833826458837 | 小于 0（未记录） |
| C001（负对照） | explore_no_increment | -0.00016606106760286288 | -0.0005858854651381084 |
| C002（K0 阳性对照） | explore_no_increment | +0.12603330566050275 | -0.00022501041705642871 |

- 产物：`/home/hcf/nas_hcf_data/faultevolve/runs/kd1g_20261004/preflight2`（完整）、`.../preflight`（截断）；日志 `runs_copy/kd1g_20261004/preflight.log`、`preflight2.log`。
- 全流程没跑：确认集、蕴含、token 均未记录。历史 ROS 38.14 只是观察点，不作因果解释。
- 对照行为符合设计：C002 已知相关但无增量，被 `explore_no_increment` 拦截；C001 同样被拦。**对照没有被拿来证明链路最后一段（蕴含/分级/晋升）**，该段仍只有单测。

## 2. 为什么 executable=18 低于 24：库是否该修

先说算术：预注册是「30 条里 ≥24」（80%）。实际库只有 27 条，要 ≥24 需 ≥88.9%，实测 66.7%。门不改。

沙箱对每个因子要求：在全部带标签单元上有值的比例 ≥0.8（`low_coverage`），且有效值不止一种（`constant`）。【已核实】`discovery/sandbox.py`。下表为【本地复核】，对象是公开 train 的 31093 个带标签单元（44 个型号）。「单元覆盖」是该列在单元上至少有一个有效值的比例，是因子覆盖的上界（窗口内差分只会更低）。

| 不可执行 | 因子用到的列 | 本地复核 | 性质 |
|---|---|---|---|
| F001 | smart_196_raw | 单元覆盖 0.633 | 数据：多数型号不报这个属性 |
| F007、F008、F014、F009 | smart_241_raw / smart_242_raw | 0.416 | 数据：同上 |
| F010 | smart_240_raw | 0.656 | 数据：同上 |
| F012 | smart_190_raw | 0.365 | 数据：同上 |
| F002 | smart_10_raw | 单元最后值仅 2 种取值，行级非零率 0.0001 | 数据：该列近乎常数，14 天差分按构造恒为 0 的可能性极高（差分本身未单独计算） |
| F020 | 距最后记录天数 | 31093 个单元的「标签日期 − 最后记录日期」全部为 0 | 构造：历史窗口以 cutoff 为终点，该量必然恒定。这是库设计错误，不是写法错误 |

对照：同库能执行的 F003（192）、F004（4）、F005（193）、F006（193/9）、F011（194 型号秩）、F013（7 型号秩）所用列的单元覆盖都在 0.998 左右，说明代码写法本身没问题，分水岭是数据覆盖。

裁决：

- 九条里**没有一条是列名、空值写法或重复**；`duplicate_code=0`、`discovery_llm_error=0` 也印证。
- 能让它们「可执行」的做法只有：把群体限定到「有观测的型号」并在群体外填 0、降低覆盖门、换成别的列。这些都是**改写因子或放宽门**，不属于 §6 允许的「只修可执行性/列名/重复」。
- 因此**那一次修库不使用**，不重跑 mock 与 `--explore-only`。库 SHA256 保持上表所列，作为本次预检的冻结版本。

## 3. 两个必须修的 bug（修复不得改统计判定）

### 3.1 `UNIQUE constraint failed: claim.id`（mock）

【已核实】`DiscoveryRound.__init__` 用 `len(store.get_claims(experiment_id))` 作为序号起点，`claim.id = C-{exp}-{seq:04d}`；`claim` 表的 `id` 是全局主键。`get_claims` 只数能解析 JSON 且 `experiment_id` 匹配的行。只要库里已有序号 ≥ 该计数+1 的 id（序号有空洞、有无法解析的行、残留的前次写入），首个新 id 就撞键，随后每条都撞，被外层 `except` 记成 `discovery_llm_error`（名字误导）。

未记录/未确认：mock 当时所用副本里 `claim` 表的行数与最大 id；为何 mock 撞键而重置副本后的真实 `--explore-only` 为 0 个错误；mock 退出码 1 的最终抛错位置（stdout 被吞）。**执行者不要把任何一条当结论**，先写能复现的最小测试再改。

要做的事：

- 序号起点改为按 `claim` 表中该实验全部 id 的最大数字后缀取值（含无法解析 payload 的行），不再用行数。
- 写入撞键时有限次重试（上限小，如 5），仍失败则抛出带 id 的明确错误，不静默继续。
- 撞键、写入类错误不得归入 `discovery_llm_error` 计数；单独事件类型，避免误导。
- 不改 `preregister`、方向冻结、分级的任何逻辑；claim id 的格式不变。

### 3.2 numpy 值导致 JSON 序列化失败（funnel.json 被截断）

【已核实】`_run_explore_gated` 里 `power_pass = ilo > 0 and abs(marg_eff) >= min_explore_effect and ci_excludes_zero` 的最后一个操作数是 numpy 布尔；`ilo<=0` 时短路返回 Python 布尔，所以只有 `ilo>0` 的第一条（F006）才把 `np.bool_` 写进 `detail["power_gate_pass"]`，与「在 F006 的 `power_gate_pass` 处被截断」吻合。`factors.py` 用 `json.dump` 边算边写，失败即留下半截文件。

要做的事：

- 源头转原生类型：`power_pass`、`ci_excludes_zero` 及 `_explore_detail` 里所有数值/布尔用 `bool()`/`float()` 包裹。值不变，只是类型。
- 序列化出口加通用兜底（`np.generic`/`np.ndarray` 转原生），用于 `FunnelRecord.to_dict` 和各 `json.dump`。
- 写文件先序列化成字符串、再写临时文件后改名，杜绝半截文件；`run_factor_discovery` 在 `kd.run` 抛错时也先把已有 `funnel.json` 写出（`try/finally`）。
- `cli.py` 的 `discover_factors` 在 `except` 里除 `error_type` 外，把异常信息截断（≤200 字符）写到 stderr 和 `<artifacts>/discovery/error.txt`；不得含环境变量或密钥。

### 3.3 成功检查

- 新增测试：（a）库里预置有空洞 id 时不撞键；（b）含 `np.bool_`/`np.float64`/`np.int64` 的 `detail` 能完整写出 `funnel.json` 且可被 `json.load`；（c）修复前后同一输入下 `power_gate_pass`、`stage_reached`、`primary_failure` 的取值逐条相同（只允许类型变化）。
- `git diff --stat` 不含 `benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md,data/}`，也不含 `discovery/stats.py`、`grading.py`。
- 只跑与上述文件相关的测试，不跑进化、不开服务器。

## 4. 这次预检记成 B 之后，下一轮改什么

outcome B（带诊断）：漏斗走完，每个死亡有主因，测出了探索效应与功效门通过数（1/泳道 C）。主因分布：不可执行 9（数据覆盖 7、恒定 2）、探索无增量 14（含 D001–D004、C001、C002）、低于功效门 1（F006）、功效门通过 1（F004，未进确认）。

下一轮（新规划，不在本计划内执行）应当：

1. **新家族，新 id，新预注册，新库 SHA256。** 不复用这 9 条的 id，不把它们「修好」再跑。
2. 设计依据用**不看标签**的覆盖普查（每列、每型号的非空率与取值数），而不是本次的探索效应；本次探索效应不用于挑选候选。库里每个因子在写入前就要保证单元覆盖 ≥0.8 且非构造性常数（避开 F020 这类）。
3. 覆盖不足的属性（190/196/240/241/242）如要使用，必须作为明确声明的新家族（例如「仅有观测的型号子群 + 群体外填 0」），并在预注册里写清楚这是群体定义；它与本次 9 条的区别必须在文档里说明，防止变相改写。是否采用留给下一轮规划决定。
4. F004 的探索结果（效应 +0.0652，增量 CI 下界仅 +0.000127）只是线索：下一轮若要再测，须作为新预注册候选从零走完整流程，不得因为它在本次探索集上过门就直接确认。
5. 不改：alpha、e-BH、rho_max、max_neg_control_fpr、confirmation_fraction、min-explore-effect、max_confirm。不重跑进化，不追 38.14。

## 5. 给 composer-2.5 的交接

意图与文件：

| 文件 | 意图 |
|---|---|
| `src/faultevolve/discovery/pipeline.py` | claim 序号按最大后缀取；撞键有限重试与独立事件；`power_pass` 等原生类型 |
| `src/faultevolve/cloud/store.py` | 新增读取某实验 claim 最大序号的方法（只读 id，不依赖 payload 解析） |
| `src/faultevolve/discovery/funnel.py` | `to_dict` 做 numpy 兜底转换 |
| `src/faultevolve/discovery/factors.py` | 先序列化后原子写；`kd.run` 抛错时先落盘已有漏斗 |
| `src/faultevolve/cli.py` | `discover_factors` 的 `except` 输出截断的错误信息到 stderr 与 `error.txt` |
| `tests/` | 仅 §3.3 三类最小测试 |
| `skill/fe-knowledge-discovery/SKILL.md` | 失败处理里补一句：预检不可执行若属数据覆盖/构造常数，记 B，不修库 |

成功检查：§3.3。

不许做：

- 不改 `alpha`、e-BH、`rho_max`、`max_neg_control_fpr`、`confirmation_fraction`、`min-explore-effect`、`max_confirm`，不改 `stats.py`/`grading.py`/`preregister` 逻辑。
- 不改 `hdd_v2.jsonl`（含增删、改写任何一条）；不改受保护的 `benchmark/hdd_mvp` 文件；不读 `data/holdout*`。
- 不把 HDD2_F004 或泳道 D 当发现；不翻旧因子再确认；不重跑进化。
- 不写密钥到代码、日志或提交；不起服务器；不在无密钥时伪造真实运行结果。
- 服务器重跑由维护者合并后做，不写进执行者步骤。
