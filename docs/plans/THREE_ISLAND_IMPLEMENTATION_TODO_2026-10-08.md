# 三岛演化实施 TODO、测试与结果回填

日期：2026-10-08（初版；本文档持续回填）。截至本次回填：S0–S8 已执行——S0–S7 离线阶段全部通过，S8 真实预检已在服务器完成（run `hdd_mvp_preflight_20261008`，代码 `7687df2c`，2026-10-08 20:07:36→20:32:08 +08:00，best 38.2067）；S9 正式运行与服务器 WebUI、S10 PR 与交付尚未执行（阶段状态以 A2 表为准）。

需求依据：[通用三岛演化需求说明](THREE_ISLAND_REQUIREMENTS_2026-10-08.md)。用户最新确认优先于旧方案：通用 Skill 必须交付；跨岛只传摘要；产品不用 demo，测试 fixture 保留；已有展示文档不改；服务器展示全部真实运行；本轮只做 HDD 闭环。

## 0. 给接手 AI 的执行方式

按 S0 → S10 顺序执行，每一步通过验收再继续。S0–S10 是阶段总览；后面的「逐项操作手册」是同一阶段的细化，不是另一套任务，必须同时执行。不要只完成代码就宣布项目完成。每完成一步立即把本文件对应方框勾选，并填写提交 SHA、测试和产物；有问题写“失败/阻塞”及具体原因，不提前勾选。

示例路径和命令不能不经检查直接照抄。首次读取 `AGENTS.md` 以及它列出的实现契约、设计文档和任务说明；禁止修改受保护基准。所有新命令先实现并验证 `--help`，再写进 Skill。不能在文档里写一个并不存在的 CLI 当作已可用。

本项目实际开发仓库是 `C:/Users/Administrator/faultevolve`；`G:/自进化agent` 本身是另一个 Git 仓库，不要在那里推送 FaultEvolve 修改。另一个 G 盘克隆也不要混用。本文档初始落在 C 盘克隆，实施时保留这些规划修改。

## S0. 核实环境、保留 demo、建立开发分支

- [x] 在上述开发仓库记录 `git status --short`、当前分支、HEAD、origin；核实远端 main，先保留所有现有改动。
- [x] 读取两份新计划，确认没有把用户“不限预算”解释为无限运行，没有把“只传摘要”解释为完整代码迁移。
- [x] 以核实的远端 main SHA 创建 `codex/webui-demo-archive` 并推送；归档树应与基点一致，记录远端 SHA。不得强推或先删除 demo 再归档。
- [x] 从同一基点建立 `codex/three-island-real-runs`，把本次两份文档与 README 更新带入该分支。若 main 有新改动，先检查兼容性并记录差异。
- [x] 只读核实 SSH 别名 `3056-hcf-10.61.48.10`、服务器旧代码 SHA/状态、数据路径和运行根目录；不读取 holdout、不打印环境变量值。
- [x] 记录 Python、依赖环境、磁盘余量和可用计算资源；不按交接说明猜测现状。

验收：归档远端 SHA 已确认，开发位置唯一且正确，原有变更未丢失，服务器历史目录未改动。

执行证据（2026-10-08）：

| 项目 | 实测值 |
|---|---|
| 开发仓库 | `C:/Users/Administrator/faultevolve`，origin `ssh://git@ssh.github.com:443/houchenfeng/Self-evolution-optimization-agnet.git` |
| 远端 main | `0655afec4a62fc403d1f5ec564ca49f457d90cb6`（fetch 后确认，与归档基点一致） |
| 归档分支 | `codex/webui-demo-archive` 已推送，远端 SHA `0655afe`，tree 与基点一致，未强推 |
| 规划分支 | 本地 `codex/three-island-plan`，提交 `2172569`（仅两份计划 + README） |
| 实现分支 | 本地 `codex/three-island-real-runs`，基点 `924f9fc`（含规划提交） |
| 服务器 | `hostname=localhost.localdomain`，代码 `/home/hcf/faultevolve/code` HEAD `dcd2283`；`benchmark/hdd_mvp/data` 是指向 `/home/hcf/nas_hcf_data/faultevolve/data/hdd_mvp` 的软链，git status 因软链显示 data 为 `D`，未改动 |
| 服务器资源 | 32 核 / 124 GB 内存 / `/` 可用 257 GB / Python 3.13.11；无 `/home/hcf/faultevolve/code/.venv`，仅有 `.env.example` |
| 阻塞项（已解除，2026-10-08 补记） | 服务器登录 shell 与非登录 shell 均未配置 `DASHSCOPE_API_KEY`/`TYPESAFE_API_KEY`/`FE_API_KEY`/`MIYANG_API_KEY`（仅检查是否配置，未读取值）。已按用户授权的受控方式解除：经 600 权限的 `/home/hcf/faultevolve/.env` 以 `--env-file` 注入（`fe doctor` 与 `fe evolve local` 同一机制），S8 预检中 `DASHSCOPE_API_KEY`/`MIYANG_API_KEY` 已配置、只输出布尔值；`FE_API_KEY` 未配置仅影响 Web 端模拟对话，与演化运行无关；全程未切 mock（13 次真实 LLM 调用即证据）。 |

## S1. 先确定数据契约，再改引擎

先读 `config.py`、`common/schemas.py`、`cloud/{engine,tree,store,selection,insights,budget,crossover}.py`，以及 CLI 和 WebAPI 的调用点。用搜索找到真实读写入口，不只改类定义。

- [x] 明确采用父运行下三岛的实现；增加岛配置和状态，字段至少包括岛 ID、策略、根节点、局部最优、计数、停止原因。
- [x] 选择与现有存储最相容的持久化实现，写入本文件“实际设计”。默认可在节点/经验增加 `island_id` 并按岛过滤；不要仅复制三个变量指向同一棵树。
- [x] 定义交换摘要和采用事件，包含来源、目标、内容哈希、适用条件、证据、状态和幂等键。
- [x] 为新 schema 设版本；旧运行只读解释为 `legacy-0` 单岛，不改历史 SQLite。旧格式恢复写入新目录的副本，记录来源。
- [x] 配置校验：默认 3；显式 1 可用；岛 ID 唯一；数量与配置一致；评估并发正整数；错误配置启动前失败。
- [x] 成本配置支持显式无上限，检查所有 max_tokens/max_wall_hours 的算术、比较与序列化；不能只让字段允许 null，却让预算计算崩溃。

验收：配置/存储/兼容性测试通过，能保存并加载三个不同岛，旧单树可读。

执行证据（提交 `3d498e7`，2026-10-08）：

- 契约：`IslandSpec`/`IslandsConfig`（`config.py`）、`IslandState`/`ExchangeSummary`/`ExchangeDelivery`/`SummaryApplication`/`SchedulerState`（`common/schemas.py`）、`OperatorType.SUMMARY_CROSS`、`Node.island_id`。
- 存储：`cloud/store.py` 新增 `island_state`、`exchange_summary`、`exchange_delivery`、`summary_application`、`scheduler_state` 与 `node(experiment_id, island_id)` 索引；`SCHEMA_VERSION = 2`，旧库 `ALTER TABLE` 加列后写入 `user_version`。幂等键：`(experiment_id, kind, content_hash)`、`(summary_id, target_island_id)`、`(delivery_id, candidate_node_id)`、`PRIMARY KEY(experiment_id, island_id)`。
- 只读兼容：`Store(db, read_only=True)` 用 `mode=ro` URI 打开，不做迁移；岛相关读方法在缺表时返回空而非报错。对已提交的历史 fixture `tests/fixtures/runs/hdd_mvp_real_38cb38cf/fe.db` 断言 sha256 不变、`user_version` 仍为 0、`node` 仍无 `island_id` 列；恢复场景改为“先复制再迁移”，同样断言源文件哈希不变（T18）。
- 预算：`max_tokens`/`max_wall_hours` 允许 `null`；`budget.token_cap_exceeded` / `wall_cap_exceeded` 统一比较语义，`remaining_tokens` 返回 `int | None`；百分比 `stage_caps` 在无总上限时失效，绝对上限 `stage_caps_absolute` 仍可单独启用；引擎 6 处直接比较已替换（含 deferred 回放、discovery、锦标赛）。
- 测试：`tests/test_island_contract.py` 32 项（T01/T03/T09 部分 + 存储/只读兼容）；`tests/` 相关集合 172 passed；`pnpm --dir web typecheck` 通过；契约已用 `scripts/export_web_contracts.py` + `pnpm generate:api` 重新生成并入库，`tests/webapi/test_contract_stability.py` 通过。
- 未做（留待后续阶段）：引擎按岛拆分运行状态（S2）、摘要生成与投递逻辑（S3）、账本/恢复接线（S4）。本阶段仅契约可提交，不代表三岛已运行。

## S2. 实现独立三树和公平调度

- [x] 将引擎单树状态拆成每岛状态，统一协调器拥有调度与总账本。
- [x] 每岛从受保护 init 创建独立根；初始化代码相同不代表节点相同。若复用同一次确定性初始化评估，必须注明共享证据和实际调用次数，不伪造三次评估。
- [x] 节点查询、选择、树回传、最优更新、修复链、交叉父节点查询都显式检查岛归属。
- [x] 默认轮转、重型评估并发 1；一个岛结束/失败后其他岛继续。LLM 请求也记录所属岛。
- [x] 实现 A/B/C 策略差异及可配置探索比例；用真实算子、提示与知识检索体现，不只在 UI 改标签。（知识检索关键词的实际注入在 D4.1，本阶段只落提示重点＋算子倾向＋带种子探索）
- [x] 全局成绩来自真实 evaluator；辅助选择价值独立存储。统一记录 attempts、valid_evaluations、invalid_evaluations，避免“轮次”含义混乱。
- [x] 实现每岛上限、停滞停止、人工停止、基础设施错误熔断；记录每岛和父运行结束原因。

验收：三个根、三个独立节点集合；一个岛的分数回传不改变其他岛统计；候选归属可追溯；缺失指标不被编造。

实现落地（2026-10-08）：

- 新增 `src/faultevolve/cloud/islands.py`：`IslandRuntime`（岛独立可变状态的容器）＋ `IslandCoordinator`（轮转游标、跳过不可运行岛、状态落盘）。`ISLAND_ATTRS` 即 D2.2 的清单实现：`tree`、`selector`、`_jev_values`、`_deferred`、`_op_tokens`、`_op_rng`、`_crossover_partners`、`_offered_insights`、`error_class_counts`、`_quota_counts`、`_plateau_evals_since_improve`、`_hpo_*`、`_island_focus` 逐岛一份；`store`/`task_adapter`/`task_spec`/`metrics`/`_cost_ledger`/`llm` 客户端仍是运行级共享。
- 单树搜索代码不改：`_activate_island()` 在岛之间交换这些属性槽，因此 UCT、修复链、交叉父选择、Jev 延迟队列天然只看见本岛节点；`Tree` 上不存在跨岛查询入口（全局最优只经 `EvolutionEngine._best_across_islands` 与不带 `island_id` 的 `Store.get_nodes_by_experiment`，且仅用于报告与协调器）。
- 三岛初始化：一次真实 init 评估（evaluator 调用 1 次、账本 1 条 `full_eval`）喂给三个不同 node id 的根，根上记 `shared_initial_evaluation_id`；`_island_stop_summary()` 与 `attempt_started`/`iteration_complete`/`node_created`/`operator_selected`/`operator_bias_applied`/`infra_failure`/`island_stopped`/`all_islands_stopped`/`init_evaluation_invalid`/`run_aborted_invalid_init`/`island_attempt_cap_hit` 载荷均带 `island_id`，`llm_call.island_id` 按发起岛记账（串行调度，活动岛即发起岛）。
- 停止口径按岛独立：`IslandState.attempts` 在生成开始时 +1（repair/HPO 同一单位），评估结束时写 `valid_evaluations`/`invalid_evaluations`/`stall_valid_evals`/`consecutive_failures`/`infra_fail_streak` 并把本岛冠军当场落盘；`_update_island_after_attempt` 依次判 `max_attempts`(默认 50)、`stalled`（≥10 次有效评估后连续 15 次无提升）、`selection_exhausted`、`infra_failures`→`paused`。初始评估无效时三岛一律 `finished`＋`stop_reason=init_evaluation_invalid`，运行不进入搜索（旧行为会空转到上万次 `selection_failed`）。
- 并发与 legacy：`islands.eval_concurrency>1` 在 `initialize()` 直接抛错，不“接受后忽略”；`enabled=False` 或恢复历史单树运行时解析为 `legacy_island_spec()`（`island_id=""`、尝试数不受 50 限制、沿用历史种子公式、提示不含本岛重点），不会把多岛暗中降级成第一岛。
- 契约：`webapi/catalog.py` 的 `EVENT_TYPES` 加上述 8 个新类型（`attempt_started`、`island_stopped`、`all_islands_stopped`、`island_attempt_cap_hit`、`infra_failure`、`operator_bias_applied`、`init_evaluation_invalid`、`run_aborted_invalid_init`），`web/src/features/workbench/event-taxonomy.ts` 把它们归入既有 12 个粗类（不新增第 13 类），`scripts/export_web_contracts.py` 重新生成 `web/openapi/*.json`，`check_web_contracts.py` 通过。
- 父运行结束原因：`run()` 在 `next_runnable()` 返回 `None` 时置 `_all_islands_stopped` 并结束，`_get_stop_reason()` 在全局预算类原因之后、`max_iterations` 之前返回 `all_islands_stopped`（预算先耗尽时仍报预算原因）；`run_finished` 事件载荷在多岛运行时并入 `_island_stop_summary()`，一条事件同时给出父原因与每岛 `status/stop_reason/attempts/valid/invalid`。
- legacy 单岛可构造：`IslandSpec.island_id` 允许恰好空串（引擎内部 legacy 岛的 id，与迁移后 `node.island_id=''` 对齐），空白或带空格的 id 仍拒绝；“配置里的岛必须有名字”上移到 `IslandsConfig` 校验（空岛 id 报 `island_id must be non-empty in a configured run`）。修复前 `enabled=False` 或恢复历史单树运行会在 `initialize()` 直接抛 Pydantic 校验错，属于 D1 契约与 D2 引擎之间的真实断裂，已用引擎级测试固定。
- 测试：新增 `tests/test_island_isolation.py` 16 项（T04 三根/三 disjoint 节点集/缓存=库、T05 外岛父被拒且不污染两树、T06 一个岛推进后其他岛统计与树快照逐项不变、T07 A/B/C/A/B/C 与 B 暂停后 A/C/A/C 及无 runnable 岛即结束、T08 连续无效候选仍消耗配额并触顶，另加 D2.5 提示重点只进本岛提示、算子倾向与带种子探索、`llm_call` 岛归属、并发>1 拒绝，D2.6 修复候选计入本岛配额与到顶拒绝）；`tests/test_run_stall_guard.py` 依新协议重写无效初始评估行为；`tests/test_hotfix_3_1.py` 断言三根三岛；`tests/test_crossover.py` 的合成节点改为落到当前树所属岛；`tests/test_engine.py::test_engine_resume_continues_same_tree` 改为 legacy 单岛口径（同一根、节点续增），另加 `test_resume_continues_every_island_tree_without_new_roots`（T02 多岛面：三岛三根、恢复不新增根、各岛旧节点不丢、活动树即冠军所在岛）。
- 全量门（本阶段）：`.venv/Scripts/python.exe -m pytest tests/ -q` → 1588 passed / 0 failed（822.68s），提交 `151a806`。
- 本阶段仍未接线（如实保留）：`_harvest_discovery_candidates()` 读 insight 时仍走不带 `island_id` 的查询，靠“节点必须在活动岛树内”天然过滤掉外岛来源，显式岛参数化随 D4.1 知识注入一起做；按岛账本/成本汇总属 D4.3。
- 仍未做（不在本阶段）：摘要交换与跨岛交叉（S3）、`knowledge_keywords` 注入与按岛账本汇总、检查点/恢复三边界（S4）。

## S3. 实现摘要交换和跨岛交叉

- [x] 复用现有正负经验抽取，加入任务/评估器指纹和失败分类。
- [x] 每岛默认 5 个尝试检查交换；每对岛最多 1 条最优摘要＋2 条失败摘要；提前错误通知去重；单岛失败不阻塞交换。
- [x] 摘要限定长度、结构与允许字段，禁止完整代码、权重、原始数据和预测明细。LLM 把代码塞进摘要时拒绝或重新抽取并记录原因。
- [x] 目标岛做适用性检索与采用判断；保存投递、接收、实际使用、评估结果或拒绝原因。
- [x] 跨岛交叉只提供本地候选代码和外岛摘要；检查现有 crossover 路径，避免默认读取外岛节点代码。
- [x] 新节点的 parent 留在本岛，外岛关系作为单独 provenance；不能将来源得分复制为新候选成绩。
- [x] 内容/投递去重、消息状态和消费检查点持久化；恢复后不重复应用已完成交换。
- [x] 记录使用摘要后的结果，但不用单次增量声称因果收益。

阶段说明（2026-10-08，提交 9592fe7＋2f368fa，`src/faultevolve/cloud/exchange.py` 新文件＋engine/operators/store/islands/catalog 接线）：正负经验的来源仍是既有抽取（节点 `artifact.intent`/`artifact.hypothesis` 与 `store.get_insights_by_experiment(..., island_id=...)` 的本岛洞察），交换层只负责把它们压成一条结论并附上 `task_fingerprint`/`evaluator_fingerprint` 与错误分类，不新造抽取流程。第 92 行的“LLM 把代码塞进摘要时拒绝”在本设计里不可能发生，因为正文不是 LLM 写的：`_new_summary()` 只接收已入库字段与评估器数字，再经 `sanitize()`，清洗后为空即写 `exchange_summary_failed{reason:"empty_after_sanitize"}` 并且不发布——这就是“拒绝并记录原因”的落点；权重、原始数据与预测明细从未进入 metrics 白名单。第 94 行的既有 crossover 路径已核查：双亲配偶池 `_crossover_partners` 在 S2 就属于 `ISLAND_ATTRS` 属性槽（每岛一份），`_build_crossover_ctx` 只读本岛树；`SUMMARY_CROSS` 不复用该路径，其上下文只有本岛 `parent` 加摘要 DTO，T10 断言嫁接候选的 `get_node_parents()==[]`。第 96 行的“恢复后不重复应用”按事实分层：投递决策一次写死（重放不重决策）、`UNIQUE(delivery_id, candidate_node_id)` 保证同一候选对同一条摘要只有一行 application、游标与已发布最佳都从存储读回；恢复后新候选重新使用同一条已接受摘要**是允许且会新增一行**的，那是新的事实而不是重复应用，与 D3.4“投递去重不等于限制只能使用一次”一致。第 97 行：application 行只记“这个候选用了这条摘要，它自己的评估结果是多少”，不记“因此提升了多少”，代码与提示模板里都不产生因果表述；聚合口径留给 S6/S9 的报告，且必须按 application 计数而非按增量归因。验收状态：受控离线测试已证明正面与负面摘要确实进入目标生成上下文、外岛源代码未进入（`tests/test_island_exchange.py` 22 passed）；真实运行尚未发生，正负事件数量待 S8/S9 按实际填写，没有某类事件就写零。

## S4. 接入知识注入、账本和恢复

- [x] 复用现有知识卡/任务适配器，为各岛提供侧重不同的检索与注入；记录卡 ID、来源、适用性、调用成本和接收岛。（依据 D4.1＋D4.2，提交 bd76846/0eac985；成本按 `llm_call.island_id` 归属，接收岛即提问岛）
- [ ] 冻结知识库只读，新经验写新运行目录；知识建议与统计确认严格分开。（冻结库读取路径已确认无写入点，但“建议/确认分开”本轮只在离线断言里核过，未作为独立验收项实测，故整条保持未勾选）
- [x] 全局账本覆盖生成、反思、摘要、知识、Jev、重试；按岛可汇总，未知账单单独标识。（依据 D4.2；Jev 与知识调用的花费仍以既有 `purpose` 入账，`unknown_outcome`/`cost_basis='unknown'` 为“未知”标识）
- [x] 将根、候选状态、交换队列、检查点、停止状态落盘；修复中断后卡在“评估中”的记录，不重复记已完成结果。（依据 D4.3，提交 91c8203：中断恢复后已带评估结果的 deferred 候选只重报状态与事件、实测评估器调用增量为 0 且不重复加分（`tests/test_island_resume.py::test_a_deferred_candidate_the_evaluator_answered_is_not_charged_twice`），未完成 application 按 `evaluation_id` 为空才重挂（`::test_an_application_recorded_before_the_crash_still_gets_its_result`）；岛状态与停止原因仍由 S2 的 `save_states()` 落盘，交换队列与游标随 D3.3＋D4.3 的 `scheduler_state`（含 `rng_state_json`）落盘。注：`IslandStatus` 未新增中断态，中断落在 `run_interrupted` 事件上，是否要岛级中断态由 D4.4 的“岛 B 暂停时进程退出”用例再定——该用例实测（971f38e）结论是不需要：暂停态由 `save_states()` 落盘、`_prepare_runtime()` 只归一化 PENDING/RUNNING，跨重启原样回来）
- [x] 进程中断/恢复测试覆盖“消息已写但未投递”“已采用未评估”“评估完成未生成报告”三种边界。（依据 D4.4，提交 971f38e，`tests/test_island_fault_injection.py` 9 passed；除这三种外另加“岛 B 暂停时进程退出”与“账本写完但终端输出中断”，共五点。其中第一点是本轮才补的真实缺陷：摘要落库与投递是两次插入，进程死在中间就永远补不回来——内容哈希去重会让下一轮不再重发同一条结论，因此新增 `ExchangeCoordinator.backfill_deliveries()`，在每轮交换开头按库里的缺口补齐投递，靠 `UNIQUE(summary_id, target_island_id)`＋`INSERT OR IGNORE` 保证补齐不会变成重播。注：`IslandStatus` 仍未新增中断态，“B 暂停时退出”实测证明暂停态本就跨重启存活、无需中断态，该判断从 D4.3 的“留给 D4.4”改为在此定案，是否要展示中断态归 S6 的 webapi registry）

阶段说明（2026-10-08，提交 bd76846＋0eac985＋91c8203＋971f38e）：S4 的四步按"每一笔花费与每一次中断都能从库里问出来"推进——D4.1 把知识注入按岛拆成独立检索与独立成本归属，D4.2 把 LLM 花费统一到一张带 `request_id/transport_attempts/island_id/island_attempt/stage/cost_basis` 的账本行上并让失联请求以 `unknown_outcome` 留痕，D4.3 让续跑先核对身份再接手（rng 流、游标、预算计数、未完成的 application 都从库重建，报告可离线重建），D4.4 则把"进程停在半路"的五种具体位置逐一实测并各留一条中断前后的计数断言，其中四处生产逻辑做了反向 mutation 证明断言确实会失败（报告重建一点未做，见 D4.4 范围⑦）。本节实测过的是**可控中断**（fake LLM/evaluator＋临时目录＋在真实提交点抛异常或直连 Store 写半状态），不是真实掉电/kill，后者留给 S8/S9 在真实运行上验证。

验收：恢复前后候选数和已完成成本无重复，所有岛可继续，未知外部调用状态可见。按 D4.4 实测口径逐句对应（提交 971f38e，`tests/test_island_fault_injection.py`）：**成本无重复**——续跑重放后 `run_resumed` 载荷的 `cost_rows/total_tokens` 与中断前库里的行数与 `get_cost_rollup` 完全相等，旧行逐字段未变、行主键集合无重复，`cost_ledger` 的 `seq` 从 `max_cost_seq()` 接续（关掉接续会立刻撞 `UNIQUE constraint failed: cost_ledger.experiment_id, cost_ledger.seq`）；**候选无重复**——评估完成但报告未生成时 `rebuild_run_report()` 全程只读，评估器调用计数前后相等（`FakeAdapter._call_count` 不变），已带结果的 deferred 候选只重报状态不重评；**所有岛可继续**——岛 B 暂停时进程退出后，六次 `next_runnable()` 只给出 `{"a","c"}`，B 的状态/尝试数/最佳分/停止原因原样回来且 `runnable` 为假，兄弟岛不会把摘要投给一个不能行动的岛；**未知花费可见**——失联请求以 `outcome='unknown_outcome'`、token 为 0 留一行，rollup 以 `unresolved_calls` 报告，不进花费也不消失。仍待填：以上都是受控离线数字，真实 HDD 运行的中断/恢复证据属 S8/S9。

## S5. 交付通用 Skill

- [x] 新增 `skill/fe-island-evolution/SKILL.md`，包含 name/description、输入、默认行为、运行步骤、恢复、停止与输出契约。（提交 f21af80；产物侧的 `islands`/`exchange`/`cost` 三块由 df8a346＋b6b6241 先落地，否则“输出契约”只能写成愿望，见 A0）
- [x] 输入通过 task_dir/adapter、配置、运行路径指定；任务指标从任务契约读取，不硬编码 HDD。（`EvalResult.combined_score` 是唯一被优化的标量且固定为越大越好，方向转换归适配器；由 `tests/test_island_skill.py::test_the_skill_states_the_single_scalar_metric_rule` 钉住）
- [x] 将服务器路径、HDD 示例放入 references；将配置、交换协议、结果解释等详细内容按需拆分，入口给出有效链接。（四个参考文件全部从 SKILL.md 的对应步骤可达；`references/hdd-server.md` 是唯一允许含主机路径的文件，其余三＋入口不得含 `/home/…` 或盘符路径，由 `test_the_generic_layer_carries_no_host_paths_or_local_directories` 检查）
- [x] 仅在确有必要时增加 scripts，并实际执行验证；更新 `fe-evolve-manager` 指向新流程，保留旧运行恢复说明。（只新增 `scripts/export_experience_skill.py`，本机实跑两次：5 条规则一次、0 条规则一次，退出码均 0；`skill/fe-evolve-manager/SKILL.md` 加“与 `fe-island-evolution` 的分工”一段，其第 5 步旧运行 `--resume` 原文保留）
- [ ] 导出真实运行经验 Skill 草稿到该运行的新产物目录，记录证据、局限、适用范围和复验方法；无可泛化规则时注明事实。**保持未勾选**：导出机制与两种结局（有可引用证据／无摘要）已用离线 toy 运行实测，草稿也确实写进该运行的 `skills/` 子目录；本条要求的是**真实运行**的经验草稿——S8 预检已是真实三岛运行（run `hdd_mvp_preflight_20261008`），但按计划经验草稿导出绑定正式运行（S9 交付物），预检产物中未导出草稿，故保持未勾选。
- [x] 做 Skill 结构与引用校验，再用一个不含 HDD 字段的离线 toy adapter 验证通用编排。该测试不宣称跨数据集泛化效果。（仓库内没有 Skill 校验工具，所以“校验”以测试形式落地并可重复运行：`tests/test_island_skill.py` 43 passed（f21af80）＋`tests/test_island_skill_walkthrough.py` 7 passed（6 项 f21af80＋第 7 项 6daa23c）；后者用 `task.adapter: famou` 的 toy 任务真实走完步骤 2（预检）／3（演练）／8（导出）。toy 编排只证明“命令真实存在且产物可定位”，不构成跨数据集泛化证据）
- [ ] 在 S8/S9 中实际按照 Skill 操作；发现步骤缺失就修正 Skill 并记录。**保持未勾选（S9 未执行）**：S8 真实预检已按 Skill 步骤 2（`fe doctor --config-file/--env-file` 预检）与步骤 3（`fe evolve local` 真实启动与监控）实际执行，发现三处与实际不符并已写回 `references/hdd-server.md`：①服务器无 GitHub 直连时实际用完整历史 bundle＋服务器 `git clone --branch`（原页只写增量 bundle）；②实际用仓库内独立 `.venv`（原页建议 conda）；③实际运行根为 `three_island_<ts>/` 下 `preflight/{runs,artifacts}` 分家（原页为 NAS 单根）。页面更新后 Skill 两类测试复跑 50 passed（C 段日志 `C:\tmp\s8\gates\pytest_skill_s8.txt`）；S9 按更新后的页面执行完再勾。

验收：新 AI 按 Skill 可找到真实存在的命令、完成配置与结果定位；HDD 路径只出现在任务参考/配置中。

## S6. 真实 WebAPI 和三岛界面

- [x] 读取 `webapi/{settings,run_registry,replay_service,catalog,contracts}.py` 及相关路由，明确运行目录发现机制。（逐文件读过之后，D6.1 的结论是"发现"这一步本身不成立：`paths.list_run_ids` 只扫一层，而服务器会把 run 放在日期/批次目录下；`replay_service` 又假设 `fe.db` 与 artifacts 同目录。改法见下一行，提交 `24438c9`）
- [x] 支持配置范围内所有真实运行，处理 NAS 多层目录；建立来源清单，判断真实/fixture/来源待核实，不以名字判断真伪。（新增 `webapi/run_discovery.py`：以产物标记识别 run、深度有上限、把 `--runs-dir` 的库与 `--artifacts-dir` 的报告配成同一个"位置"；来源按证据判定（fixture 根、运行登记表）而不是按目录名；`GET /api/runs/provenance` 发布来源清单与可对账的计数。`tests/webapi/test_run_discovery.py` 14 项：4 项正向、两台完整副本不合并、软链接只登记不下钻、错误清单自我封顶、不可读分区不影响其余列表）
- [x] 历史产物只读，索引和兼容派生结果写新目录。损坏/不兼容运行显示原因；每个目录有明确索引结果。（旧库一律 `Store(db, read_only=True)` 打开；派生结果写扫描目录之外的 index/registry。损坏或字段类型不对的运行给结构化状态：`test_a_malformed_islands_block_is_invalid_not_zeroed`、`test_a_field_of_the_wrong_type_stays_null_rather_than_a_coerced_one`、Discovery 侧 `test_a_directory_holding_no_run_artifact_is_not_a_run`）
- [x] 产品启动不用 `scripts/e2e_serve.py`；保留测试 fixture 和专用测试入口，与产品路径隔离。（E2E 专用启动器保留，`tests/fixtures` 与 `pnpm test:e2e` 不动；产品路径的配置默认 `demo_run_ids=[]`，且可见性不再由该字段控制——清空字段之外，fixture 目录靠来源判定被排除，见 D6.5 与 `App.test.tsx` 的"空 demo_run_ids 下列表仍显示两条运行"用例）
- [x] 移除正常产品首页按 showcase ID 过滤的逻辑；支持空态、缺失指标、历史单岛和新三岛。（提交 `f3e8259`：删除 `features/showcase/` 四个专用页面与 `SHOWCASE_RUN_ID` 分支，总览改为渲染 `/api/runs` 返回的全部条目；缺失值渲染「未记录」；历史单岛（`islands.state=missing`）给"该运行未记录岛状态"的说明而非编造三岛；空态由知识页空分支与 fixture `hdd_mvp_faildemo_4b81c0d2` 覆盖）
- [x] 增加三岛概览、岛切换/并列树、策略说明、全局最优、摘要交换边和采用详情。（提交 `95d25c4`＋`dcc2fc5`：工作台增「三岛概览」「摘要交换」两个面板，树增岛筛选芯片、节点岛徽标与 `summary_cross` 线型（图例与 `EDGE_STYLE` 同源），结果页增"全局/各岛最优"（岛最优从树重算，不用 run_summary 的转述），知识页增「岛间摘要」。岛树默认并列三岛，跨岛嫁接边不参与布局——`tree-adapter.test.ts` 的 mutation 实测：把该 `continue` 去掉或让嫁接边套用父边样式，各有 1 项断言转红）
- [x] 保留数据路径白名单/鉴权/脱敏，不能将 NAS 数据根作为任意文件下载目录。（`tests/webapi/test_path_security.py` 三项越权请求（run/node/artifact id 穿越）仍为拒绝；新增 `test_no_exchange_response_leaks_a_filesystem_path`、`test_the_provenance_manifest_carries_no_host_path` 钉住新接口不泄露路径；摘要详情只给证据 id 与数字，不给源文件路径）
- [x] 修改契约后在 web 目录执行现有 `pnpm sync:contracts`、`pnpm check:contracts`，提交生成文件。（**本机直接跑被包装的 npm 脚本会失败**：两条脚本调裸 `python`，本机解析到 Windows Store 占位程序，`pnpm sync:contracts` 退出码 9009；等价的两步实测通过——`.venv/Scripts/python.exe scripts/export_web_contracts.py`（导出 4 文件）＋`npx --no-install openapi-ts`（4 文件，227–263 ms），随后 `git status` 为空＝无漂移，`check_web_contracts.py` 输出 `contract check OK: 4 files match the Python source`。契约版本 1.12.0→1.13.0，生成文件已随 `08f9d2e`/`dcc2fc5`/`24438c9` 入库）

验收：正常配置下列表展示全部已核实真实运行；不会自动出现 fixture；三岛数据来自 API；外岛来源边不破坏树布局；历史单树能正常回放。

## S7. 离线检查与测试门

下表测试名称是建议名称，实现者可调整；必须覆盖行为，不写仅检查源码包含关键词的测试。新增测试用 mock 是允许的，不能把 mock 结果写成服务器结果。

| 测试组 | 必须验证的行为 |
|---|---|
| 配置与旧格式 | 默认三岛、显式单岛、非法配置、旧记录只读兼容 |
| 三树隔离 | 独立根/节点/统计，外岛节点不能当普通父节点 |
| 策略与公平性 | 各岛实际调用策略不同，停掉一岛不饿死其他岛 |
| 交换 | 正负摘要投递、采用、适用性拒绝、去重、无源代码泄漏 |
| 跨岛交叉 | 本岛父节点＋外岛摘要生成新候选，必须新评估 |
| 知识与成本 | 来源可追溯、有限/无限配置、汇总与未知账单 |
| 恢复 | 三个中断边界，不重复完成事件、节点或已知成本 |
| API/界面 | 真实/fixture/未知来源混合目录、嵌套目录、空态、缺失值、旧树/三树 |
| Skill | 引用、脚本、非 HDD toy adapter 的编排 |

- [x] 运行针对性 Python 测试，记录命令、通过/失败数量和日志。（`.venv/Scripts/python.exe -m pytest tests/test_island_resume.py tests/test_island_fault_injection.py tests/test_autotune_ledger.py tests/test_island_cost.py tests/test_island_exchange.py -q` → 退出码 0，**86 passed**（39.32s）；日志 `C:\tmp\s7\gates\pytest_targeted_s7.txt`，工作目录/日期/解释器版本（Python 3.12.4）写在日志首部。含 D4.4 五点复跑（`test_island_fault_injection.py` 全部 11 项）与三个新增用例）
- [x] 仓库根运行 `python -m pytest tests/`，区分新增失败与已有失败；不允许删测试规避错误。（**1799 passed / 0 failed**（894.00s，退出码 0，19:39:09→19:54:04）＝S6 门 1796＋3（三个新用例），既有 1796 项无回归；本轮没有新增失败，也没有需要复现的既有失败（S7 起点是 S6 全绿树）。日志 `C:\tmp\s7\gates\pytest_s7_full_final.txt`；19:34 启动的第一次全量在 16% 处被主动停止——回填期补落了 `catalog.py` 标签修正，继续跑所得树将不是终态，残余输出留档 `pytest_s7_full_aborted.txt`，不作证据）
- [x] web 目录运行 `pnpm typecheck`、`pnpm test`、`pnpm lint`、`pnpm build`、`pnpm check:contracts`。（在终态树 `123ac28` 上复跑，退出码全 0：export 4 契约文件再生成与已入库逐字节一致；`check_web_contracts.py` → `contract check OK: 4 files match the Python source`；tsc 无输出；vitest **39 files / 752 passed \| 3 skipped (755)**（13.17s）；eslint 0 error（1 个既有 TopBarBadges warning）；`vite build` ✓ 396ms（872.89 kB 既有 chunk warning）。`pnpm sync:contracts` 直跑仍是 9009（脚本调裸 `python`），按 S6 结论用两步等价命令。日志 `C:\tmp\s7\gates\frontend_chain_s7_final.log`＋`{vitest_s7_final.txt,build_s7_final.txt}`＋`versions_s7.log`（node v24.13.0／pnpm 10.33.0））
- [x] 按现有 E2E 配置运行 `pnpm test:e2e`，覆盖三岛/单岛/空态/真实列表；查看相关页面截图确认布局。（终态树 `123ac28` 上两跑：主链 `npx --no-install pnpm test:e2e` → **76 passed**（2.1m，日志 `C:\tmp\s7\gates\e2e_s7.log`）；因主链第 7 步的 `EXIT=` 取自管道末端 `tail`（非被测命令），19:58 起不经管道复跑取真退出码：**76 passed**（2.0m）、EXIT=0，日志 `e2e_s7_final.txt`（`frontend_chain_s7_final.log` 内追加「更正」段）。E2E 用临时运行根 `C:\Users\ADMINI~1\AppData\Local\Temp\fe_e2e_h60hmlgm`（API 8011／web 4318），未触碰服务器真实运行目录；复跑前杀掉遗留 dev server（node.exe PID 27404，占 4318），避免 `reuseExistingServer` 静默连到旧后端。用例覆盖：三视口×明暗×十画面视觉回归、三岛形态（三张岛卡／六个独立交换计数／岛筛选收窄）、单树形态（21 节点、六层带、显著性四档、双亲标记、修复链）、历史单树明说无岛记账、空态/错误态。截图核对：`web/test-results/visual/1440x900/light/{overview,islands-overview,island-tree,exchange-detail,empty-state}.png`（E2E 产物）＋`C:\tmp\s7\gates\runs-list-scrolled.png`（本地 dev 栈读 `tests/fixtures/runs`，4 条运行 `hdd_mvp_demo_7510f100`／`hdd_mvp_faildemo_4b81c0d2`／`hdd_mvp_islands_15l4nd01`／`hdd_mvp_showcase_c89e2a01`）——布局与读数符合设计，无横向溢出）
- [x] 检查 diff 没有修改受保护基准、冻结库和旧展示文档；运行 `git diff --check`。（`git diff --check` 退出码 0；对照 S6 门提交 `83535ef` 的全部改动＝8 个文件：`src/faultevolve/{cloud/engine.py,cloud/engine_autotune.py,optimization/ledger.py,webapi/catalog.py}`＋`tests/{test_autotune_ledger,test_island_fault_injection,test_island_resume}.py`＋`web/openapi/ui-metadata.json`；`git diff 83535ef -- benchmark/ tests/fixtures/ knowledge/ docs/design/` 为空；密钥/产物形状扫描无命中（唯二匹配为测试代码里的临时库名 `fe.db`）。日志 `C:\tmp\s7\gates\diff_checks_s7.log`）

S4 带入 S7 的补测项（不在 S4 里伪称已完成，逐条来自 D4.3/D4.4 落地说明的范围段）：①T09 的 null 预算**引擎运行级**续跑（现仅判定函数级＋有限预算的恢复实测）；②把 `rebuild_run_report()` 改成会重新评估的版本，验证"评估完成未生成报告"那条 `adapter._call_count` 断言确实会失败（D4.4 唯一未做反向 mutation 的中断点）；③`CostLedger.totals()` 是否改从 `cost_ledger` 行重建——现只汇总本进程内存记录，续跑/重建摘要里的 `cost_ledger_totals` 不含上一进程记录；④恢复后评估侧计数（`valid_count/invalid_count/jev_calls/evaluations_saved`）是否需要从库重建。上表"恢复"行要求的"三个中断边界"已由 D4.4 覆盖为五个点，S7 只需按本表复跑，不重复实现。本轮处置结果：①已补引擎运行级用例（`tests/test_island_resume.py::test_a_resume_without_a_token_cap_keeps_spending`，M2 反向 mutation 验证）；②以引擎级孪生用例（`tests/test_island_fault_injection.py::test_resuming_a_finished_run_rewrites_a_lost_report_without_evaluating`）＋M1 关闭——字面形式的“把 `rebuild_run_report()` 改成会重新评估”不可表达（其调用树 `export_forest`/`get_cost_rollup`/`island_report` 均无评估器引用），可证伪的缝在续跑路径持有评估器处；③`CostLedger.restore_rows()` 落地：`init_ledger()` 与 `rebuild_run_report()` 都从 `cost_ledger` 行重放（`test_l9_a_resumed_ledger_counts_the_rows_the_previous_process_wrote`＋M3a/M3b）；④决定不从库重建评估侧计数（理由见 S7 追加行）。逐条证据在下方 S7 追加行。

验收：相关检查全部通过；环境阻塞或历史失败有明确证据与处理结论。不能写“未运行，但预计通过”。

## S8. 新服务器路径部署与真实预检

- [x] 核实服务器当前状态后生成唯一时间戳目录；新代码、运行数据库、artifacts、日志、索引均写新位置，记录绝对路径。（部署根 `/home/hcf/faultevolve/three_island_20261008-200410/`；新代码 `code/` HEAD `7687df2c…`，运行库 `preflight/runs/hdd_mvp_preflight_20261008/fe.db`，artifacts `preflight/artifacts/hdd_mvp_preflight_20261008/`，控制台 `preflight/console_preflight.log`，manifest `preflight/run_manifest.json`；`formal/`、`web/` 已建仍为空，属 S9）
- [x] 服务器无法直接访问 GitHub 时，在本机打包已提交代码，用 git bundle/scp 等已验证方式传输到新目录，核对 SHA。新目录从空仓库初始化时用完整 bundle；增量 bundle 仅能用于已经拥有基点的仓库。（本机 `git bundle create`（complete history）→ `git bundle verify` → `scp`；服务器 `git clone --branch codex/three-island-real-runs`；bundle sha256 本地与服务器同为 `93469ba9c3de7427c54369cfa6885c32551b09a3143bd72610c8ad582b1d5c18`（61814410B），服务器 HEAD 与本地同为 `7687df2c562cf2cca5258effffe225600cb60024`、status 干净）
- [x] 独立环境安装所需依赖，沿用已授权的模型与环境变量来源，不打印密钥，不复制包含密钥的配置到报告。（`$TM/code/.venv`（Python 3.13.11）`pip install -r requirements.txt`＋`pip install -e .`，冻结 48 包；密钥经授权 `/home/hcf/faultevolve/.env`（600）以 `--env-file` 注入，doctor 只输出布尔；报告与本文档无任何密钥值）
- [x] 使用 `HDD_BENCH_DATA_ROOT` 或仓库已支持方式指定现有只读 HDD 数据，不改旧代码目录的数据软链。（启动时 `HDD_BENCH_DATA_ROOT=/home/hcf/nas_hcf_data/faultevolve/data/hdd_mvp`；doctor 确认数据根正确且归属 hdd_mvp；旧目录 `/home/hcf/faultevolve/code` HEAD `dcd2283e…` 保持不变）
- [x] 保存运行 manifest：代码 SHA、配置哈希、允许使用的 train/val 数据文件指纹、评估器哈希、随机种子、环境与时间。文件清单明确排除 holdout，不遍历读取私有文件。（`$TM/preflight/run_manifest.json`：code_sha `7687df2c…`、config `9be62749…`、resolved `350df2ee…`、evaluator `cddfaaab…`、init `91744b4b…`、seed 20260926、Python 3.13.11；六个允许文件逐一指纹（meta/train/val/eval_only），`holdout_policy: never listed, read, or fingerprinted`）
- [x] 真实预检配置三岛各 2 个候选尝试，交换间隔 1，评估并发 1；确认真实 LLM、真实 HDD evaluator、三岛归属与摘要链路。（resolved 配置：islands 3 `[a:performance, b:miss_alert, c:efficiency]`、max_attempts `[2,2,2]`、exchange_interval 1、eval_concurrency 1、qwen3-coder-plus/qwen3-max @ dashscope；13 次真实 LLM 调用（9 生成＋4 反思，全部 outcome=ok）、5 次真实 evaluator 执行、9 节点全带 island_id、5 摘要/10 投递/11 采用/2 交叉节点）
- [x] 写回预检结果，包括实际消息类型、失败、成本、输出路径；修复后需要重试则另建运行 ID，保留旧记录。（结果与失败全部回填于本节证据块与 A0/A1/A2/B/D/E/F；失败均为自然产生（a 岛 2 个候选 invalid/smoke_rejected、b 岛 1 次 smoke_failed→smoke_fix_success、2 次 hypothesis_refuted），无 mock/fallback；未发生流程性失败需重试，同一 run ID 保留）

验收：不存在 mock/fallback 假结果，评估输出可定位；三岛和交换链路可观察。没有自然产生失败经验不强造失败，失败传播由离线测试保障。

执行证据（2026-10-08，run `hdd_mvp_preflight_20261008`，代码 `7687df2c`，20:07:36→20:32:08 +08:00，约 24m32s；全部取自服务器原始产物，`$TM` = `/home/hcf/faultevolve/three_island_20261008-200410`）：

| 项目 | 实测值 |
|---|---|
| 启动命令 | `cd $TM/code && HDD_BENCH_DATA_ROOT=/home/hcf/nas_hcf_data/faultevolve/data/hdd_mvp nohup .venv/bin/fe evolve local benchmark/hdd_mvp --config-file $TM/deployment/preflight_evolve.yaml --env-file /home/hcf/faultevolve/.env -n 6 --runs-dir $TM/preflight/runs --artifacts-dir $TM/preflight/artifacts --run-id hdd_mvp_preflight_20261008 > $TM/preflight/console_preflight.log 2>&1 &`；PID `1011543`（`preflight/pid.txt`） |
| 结束与成绩 | 状态 `finished`，stop_reason 全局 `max_iterations`／各岛 `max_attempts`；控制台尾部 `Evolution completed: finished / Best score: 38.21`；best 节点 `4c1635ca`（b 岛）38.20668424929315，初始 22.807355886970594，Δ+15.3993 |
| 三岛终态 | a root `8a37fed9` best 22.8074（attempts 2 / valid 1）；b root `ebe9997c` best `4c1635ca` 38.2067（attempts 2 / valid 3）；c root `48c0ffdd` best `f0cd9659` 36.6104（attempts 2 / valid 3）；三岛均 `finished`/`max_attempts`，`shared_initial_evaluation_id=8a37fed9` |
| 交换链路 | 5 摘要（a 3：1 best＋2 failure；b 1；c 1）、10 投递（b 4／c 4／a 2，全部 accepted/applicable）、11 采用（b 5／c 6／a 0，全部 evaluated）、3 次 `summary_cross_selected`（均选自 b 的 `sum-3b709a88`）、2 个 `summary_crossover` 节点（c `f0cd9659`、c `0d7fdc94`）；关键链路 `sum-3b709a88`→`dlv-ce915ea4`→`app-d1a808ad`→候选 `f0cd9659` 得 36.6104 |
| LLM 与成本 | 13 次真实调用（qwen3-coder-plus 9 次 prompt 37711/completion 28361；qwen3-max 4 次 9260/1167），全部 `outcome=ok`、缓存 0、unresolved 0；总 tokens 76499（a 25601／b 29470／c 21428／shared 0）；`cost_usd=null`、`cost_basis=unknown`（未配置价格表，不以 token 猜费用） |
| 数据库计数 | node 9、llm_call 13、event 85、exchange_summary 5、exchange_delivery 10、summary_application 11、scheduler_state 1、cost_ledger 0（账本未启用）；mock 痕迹扫描（event.type / payload_json / node.operator 三处）全 0，judge `none` |
| 输出路径 | `preflight/artifacts/hdd_mvp_preflight_20261008/{run_summary.json 6304B, tree.json 4170B, events.jsonl 31500B}`；库 `preflight/runs/hdd_mvp_preflight_20261008/fe.db` 458752B（wal 0）；doctor 输出、manifest、快照等证据存 `$TM/evidence/`（含 D8.3 权限探针实测） |
| 遗留与诚实边界 | 退出码不可回取——启动用 `nohup … &` 未包裹 `$?` 捕获，完成证据是控制台尾部＋DB `status=finished`；S9 启动器将以 `sh -c '…; echo $? > exit_code.txt'` 包裹。DB `experiment.config_json` 记 `max_wall_hours 6.0` 是 schema 默认值（引擎只传 max_iterations/max_tokens/target_score/c_puct/seed），实际预算为 null 无上限（实际墙钟 1468.32s 远低于 6h）。预检未发生中断，服务器端恢复命令仍未实测执行 |

## S9. 正式 HDD 运行与服务器 WebUI

- [ ] 正式运行使用需求 §5 的有限协议：每岛最多 50 次候选尝试，真实评估并发默认 1，交换默认 5；成本无用户上限，保留停止条件。保存最终配置后再启动。
- [ ] 用新运行 ID，不能覆盖预检、历史 Run B、89f4bdd1 或任何冻结产物。
- [ ] 按 Skill 监控三岛、成本、错误和停止原因，不因暂时成绩不好就改评估公式、换数据或放宽 gates。
- [ ] 运行结束导出各岛与全局最优、候选代码、评估输出、摘要消息与采用记录、成本、停止原因、经验 Skill 草稿和报告。
- [ ] 新服务器目录构建前端，按仓库真实部署方式启动 API 与页面；通过 `fe web serve --help` 核实参数，不用 E2E fixture 服务代替产品服务。
- [ ] 配置历史/新运行索引，保存扫描清单及每项处理状态；服务日志写新目录。优先绑定回环地址并用 SSH 转发访问，记录最终地址、端口和启停方法，不改已有服务。
- [ ] 验证真实列表、旧单岛、新三岛、结果页、交换详情和无数据状态；保存不含敏感数据的截图与 API 检查结果。
- [ ] 记录本轮不含单树对照/跨集测试；只比较同次初始解与最终结果，不声称三岛方法已经优于单树。

验收：真实产物完整，结果无论提升还是退化均如实记录；WebUI 能查看所有已核实且兼容的真实运行，异常记录有说明。

## S10. 回填文档、PR 与交付

- [ ] 填满下面结果表，需求文档 §9 同步状态与证据链接，未发生/不可测项注明原因。
- [ ] README 版本更新把“规划”与“实现/实跑”分条记载，写实际提交、测试和运行 ID；不要把当前规划条目改成虚假的已实现记录。
- [ ] 现有对外展示文档及宣传材料保持不变，除 README 指定版本更新外不做文案清理。
- [ ] 推送实现分支，创建指向 main 的 PR，描述实际完成范围、验证、结果与限制。不得直接推 main 或强推归档。记录 PR 链接；在 Codex 中附加该 PR。
- [ ] PR 检查通过并按仓库流程合入后记录 main SHA；未合并时状态写“PR 待合并”，不能宣称 main 已完成去 demo。
- [ ] 若服务器跑的是 PR 提交而非最终 main，明确两者 SHA；合入后只在新代码目录做安全更新，并检查差异是否需要重新验证，不默默混用版本。
- [ ] 最终交付包括两分支、PR、Skill 路径、服务器新目录、页面访问方法、测试摘要、真实指标和遗留问题。

## 逐项操作手册：按编号执行，不跳过依赖

### 使用说明和命名约定

下面的步骤是给新接手 AI 的执行顺序。每个编号完成后，在文末的逐步日志增加一行。阶段总览只有在该阶段所有细项通过后才能勾选。

“建议新增文件/字段”属于待实现接口，当前不保证存在；“现有入口”已在本机 `dcd2283` 检查过。代码版本变化时先重新定位。不要为了与本文件逐字相同而重复实现已有功能，但替代实现必须在日志解释对应关系。

本计划不要求启用多个编码 AI。三岛指产品的三个搜索状态，不等于三个临时聊天任务。

代码位置基准：下列仓库相对路径均以 `C:/Users/Administrator/faultevolve` 为根；服务器路径只在部署步骤使用。Windows 命令用 PowerShell，服务器命令用 Linux shell，不混用变量和引号语法。

### D0：准备和分支（对应 S0）

#### D0.1 确认你操作的是正确仓库

- [x] 执行以下只读命令，每条单独执行并检查结果：

```powershell
Set-Location -LiteralPath 'C:\Users\Administrator\faultevolve'
git rev-parse --show-toplevel
git remote get-url origin
git status --short
git branch --show-current
git rev-parse HEAD
```

预期：仓库根是 C 盘 FaultEvolve 克隆；origin 属于 `houchenfeng/Self-evolution-optimization-agnet`。如果得到 `FaultEvolve-ResearchAssistant` 或 G 盘资料仓库，停止此步骤，切换到正确目录再检查。

当前两份计划和 README 可能尚未提交，这是本次用户工作，不是垃圾文件。记录它们，不执行 reset/clean/stash 处理。工作区另有修改时列出来源，不能混进归档。

#### D0.2 读取规则并建立保护清单

- [x] 按顺序阅读 `AGENTS.md`、`docs/dev/MVP开发指南.md`、`docs/design/02-MVP方案-硬盘.md`、`docs/design/01-系统总体设计.md`、`benchmark/hdd_mvp/problem.md`，再读新需求。
- [x] 将受保护四个基准文件、冻结知识库和已有展示文档的 Git blob/hash 记录到执行日志；不读取或计算 holdout 的哈希。
- [x] 列出本轮可以改的范围：引擎/配置/契约/CLI/Skill/测试/Web、新计划、README 版本记录。历史产物仅能读取，不能修补。

通过条件：执行者能指出“旧文档用单树”与“新需求用三岛”的差异，并且没有把旧设计全部重写。

#### D0.3 获取远端基点并保存当前规划

- [x] 执行 `git fetch origin main` 后读取 `git rev-parse origin/main`，记为归档基点；读取 `git log -5 --oneline origin/main`，检查是否有新实现。
- [x] 建议在当前 HEAD 创建独立规划分支 `codex/three-island-plan`，只提交这两份计划和 README，记录规划提交 SHA；存在同名分支时先检查，不覆盖。
- [x] 有其他未提交变更时采用独立工作树进行后续开发，保留用户原目录，不移动或清除其文件。

只提交指定三个文件，不能 `git add .` 把服务器信息、数据或其他工作顺带入库。规划分支只是保存当前文档，不是要求新增产品功能。

#### D0.4 归档 demo，随后建立实现分支

- [x] 检查远端是否已有 `codex/webui-demo-archive`。没有时从归档基点建立并推送；已有时核对 SHA，若不一致用带日期的新归档名并记录，不能强推覆盖。
- [x] 比较归档和基点的 tree SHA，必须一致；再从远端读取归档 SHA 证明推送成功。
- [x] 从归档基点创建 `codex/three-island-real-runs`，将规划提交带入。README 冲突只合并版本记录，不用整文件覆盖远端更新。
- [x] 再次执行 status，确保后续功能改动发生在实现分支。填入结果表 B。

通过条件：现有 demo 完整保存在远端；实现分支有两份计划；没有直接修改远端 main。

#### D0.5 只读检查服务器

- [x] 单独执行 SSH 连通检查；使用批处理模式和连接超时，失败时记录错误而不是进入密码交互死等。

```powershell
ssh -o BatchMode=yes -o ConnectTimeout=15 3056-hcf-10.61.48.10 'hostname'
ssh -o BatchMode=yes -o ConnectTimeout=15 3056-hcf-10.61.48.10 'git -C /home/hcf/faultevolve/code rev-parse HEAD'
ssh -o BatchMode=yes -o ConnectTimeout=15 3056-hcf-10.61.48.10 'git -C /home/hcf/faultevolve/code status --short'
```

- [x] 核实 NAS 数据/运行根是否存在、可读、空间足够；记录 CPU/内存/GPU与软件版本，不读取原始数据内容。
- [x] 密钥仅检查“是否配置”，禁止 `env`、`printenv` 或输出 .env 全文。

服务器不可达时可继续 D1–D7 的本地工作，把 D8/D9 标为阻塞；不能声称部署成功。

### D1：定位调用链、固定数据结构（对应 S1）

#### D1.1 建立最小代码地图

- [x] 逐个打开下面现有入口，记录谁调用它、它读写什么状态；补入文末“实际设计”。

| 现有入口 | 必须确认的问题 |
|---|---|
| `EvolutionEngine.initialize` | 恢复如何识别实验，何处创建根与 selector |
| `EvolutionEngine.run`、`_run_one_iteration_inner` | 轮次/预算在哪里增加，失败会不会跳过计数 |
| `Tree.load_from_store` | 当前按 experiment 加载全部节点，必须增加岛过滤 |
| `Tree.add_node`、`_propagate_best_score` | 父子关系和回传怎样限制在本岛 |
| `Store.get_nodes_by_experiment`、`get_insights_by_experiment` | 哪些调用方确实需要全局数据，哪些应改为岛内 |
| `get_foreign_insights`、`BranchMemoryManager.propagate_insight` | 现有“foreign”是跨枝，不等于跨岛授权 |
| `BudgetController.remaining_tokens`、`stage_cap_tokens` | 当前直接做减法/乘法，null 需要适配 |
| `webapi/replay_service.py`、`webapi/paths.py` | 如何从 run_id 找目录，是否只扫描一层 |
| `cli.py`、`webapi/run_control.py` | 配置、resume、子进程参数如何传入 |

不要把主要改动误放到 `optimization/` 的 HPO 模块，而漏掉 `cloud/engine.py` 的真实主循环。

#### D1.2 明确默认存储方案

- [x] 默认采用“一个父实验、一份新运行数据库、三条 island 状态、节点含 island_id、每岛一个 Tree 视图”；若现有实现约束不允许，先在实际设计中解释替代方案，再落代码。
- [x] 新增独立持久化岛状态、摘要消息和采用记录。下面是语义契约，不要求逐字使用这些表名：

| 对象 | 最少字段 | 约束 |
|---|---|---|
| island_state | run_id, island_id, profile, root_id, best_node_id, attempts, valid_evals, status, stop_reason | `(run_id,island_id)` 唯一 |
| node 归属 | island_id | 归属不可在候选运行后更改 |
| exchange_summary | summary_id, source_node_id, kind, payload, content_hash | 摘要内容不可原地覆盖，修订生成新版本 |
| exchange_delivery | summary_id, target_island_id, status, reason | 同一摘要到同一岛最多一条投递记录 |
| summary_application | delivery_id, candidate_id, evaluation_id | 同一候选对同一投递不重复记采用 |
| scheduler_state | next_island, per_island_exchange_cursor, rng_state/schema_version | 重启时可恢复 |

- [x] 明确跨岛来源存独立关系，不滥用现有 `second_parent_id` 让祖先遍历跨岛。
- [x] 加必要索引和参数化查询；单进程串行写优先，不为本任务引入新的数据库框架。

#### D1.3 明确轮次和评估定义

- [ ] 将 `attempt` 定义为一次已开始的候选生成/改进尝试；LLM 重试属于同一 attempt，独立 repair 候选有自己的 attempt。请求失败也要结束并计数，防止无限重试。
- [ ] `valid_evaluations` 只计通过任务评估器有效性检查的完整评估，init 单独记；预筛/静态检查/小样本 smoke 不算完整评估。
- [ ] HPO 若一次生成多个候选，每个实际候选都占 attempt；完整评估调用数另记，不能将 100 个候选藏在一次迭代里。
- [ ] 明确已有 `--iterations` 的兼容行为：保留为全局尝试上限；新每岛上限由岛配置控制，两者同时设置时先到者停止。正式配置使用全局 150、每岛 50，预检全局 6、每岛 2。若实现采用不同兼容策略，须说明理由并覆盖测试。

#### D1.4 实现配置与预算

- [x] 在 `config.py` 增加岛配置，默认 3 个不同 profile；自定义第四岛必须给 profile，不能偷偷复用第三岛配置。
- [x] 区分“新建时未给岛字段”和“恢复旧 run 未给岛字段”：前者三岛，后者 legacy 单岛。
- [x] 配置应能表达交换间隔/条数、探索比例、每岛停止规则和评估并发；集中校验，不在多个模块写不同默认值。
- [x] null 表示无总 Token/墙钟上限；百分比 stage cap 在没有总上限时也不形成隐含成本上限，记录为未启用。仍允许显式绝对 cap，但本次配置不启用。
- [x] 搜索所有 max_tokens、max_wall_hours、remaining_tokens 使用点，处理算术/比较/JSON输出；不要用无限大浮点数导出无效 JSON。

#### D1.5 写配置和存储测试后再接引擎

- [x] 新建离线临时数据库，写三岛各一个根，重载后归属和根不变。
- [x] 给重复岛 ID、0 个岛、负交换间隔、不一致数量、非法 profile，期望启动前明确报错。
- [x] null 预算下 expansion 正常；有限预算下仍按原阈值停止；缺少岛字段的旧运行不会被升级成三岛。
- [x] 旧 fixture 复制到临时目录测试读取/恢复，源 fixture 哈希不变。

通过条件：上述行为断言全过；本阶段可以提交“配置和存储契约”，但不能写三岛已运行。

### D2：将单树循环拆成三岛循环（对应 S2）

#### D2.1 先做真正的 Tree 隔离

- [x] 让 Tree 构造显式知道 island_id；`load_from_store` 使用岛过滤查询，加载前清空旧缓存，防止重复加载残留。
- [x] 每个岛只允许一个根；检测到两个根应报数据不一致，不能保留最后一个根掩盖问题。
- [x] `add_node` 校验父节点存在且属于本岛；repair 父、岛内 crossover 两个父也执行相同检查。
- [x] `get_ancestors`、children、frontier、subtree_best 和 score propagation 都使用本岛节点集合；来源摘要边不参与遍历。
- [x] 保留全局查询入口仅用于报告/协调器，名称明确，不把它传给岛内 selector。

通过条件：向 A 尝试加入父节点属于 B 的普通候选会被拒绝；A 分数更新后 B/C 的访问次数、最优值和孩子集合完全不变。

落地说明（2026-10-08）：`Tree.__init__(experiment_id, store, island_id)`；`load_from_store()` 先清空 `nodes`/`subtree_best`/`root_id` 再按 `Store.get_nodes_by_experiment(experiment_id, island_id=...)` 装载，并拒绝携带他岛 `island_id` 的行；出现两个根直接 `ValueError`（不“取最后一个”）。`add_node` 三道检查：节点岛标签一致、父节点在本岛节点集内、本岛尚无其他根；`create_repair_node` 的岛标签取自失败节点，岛内 crossover 的两个父均来自 `self.tree.nodes`（本岛视图）。类上**没有**跨岛查询方法，全局视图只在 `EvolutionEngine._best_across_islands()`（报告）与不带 `island_id` 的 `Store.get_nodes_by_experiment()`（协调器/导出）处存在，docstring 已写明，selector 拿不到它们。通过条件由 `tests/test_island_isolation.py::test_foreign_parent_is_rejected_without_polluting_either_tree` 与 `::test_an_island_attempt_moves_only_that_island`（B/C 的 `visit_count`、`subtree_best`、`children`、最优与状态快照逐项相等）实测。

#### D2.2 将 mutable 状态归属清单逐项迁移

- [x] 在 engine 中逐项列出可变字段，标为“岛独立”或“全局共享”，不能只处理 self.tree。

| 岛独立 | 全局共享 |
|---|---|
| Tree、selector 的在线统计、算子老虎机、修复记忆、局部停滞计数、延迟评估队列、局部最佳 | 只读 task/evaluator、运行 ID、总账本、只读知识源、调度器、消息总线 |

LLM 客户端可以共享连接，但请求上下文/计量必须带岛 ID；Jev 若共享校准状态须在实际设计说明，不能因切岛错误读到另一岛的父节点。

- [x] 新增 `IslandRuntime` 或等效容器，生成各岛独立实例；不要用三个引用指向同一个 mutable 字典。
- [x] 临时兼容单树 API 可以保留，但必须只服务显式单岛/legacy，不可暗中把多岛降为第一岛。

落地说明（2026-10-08）：岛独立字段清单即 `islands.ISLAND_ATTRS`，逐项与上表对应——`tree`（本岛树视图）、`selector`（UCT 在线统计与参考点）、`_op_tokens`/`_op_rng`（算子老虎机与它的种子流）、`error_class_counts`（修复记忆）、`_plateau_evals_since_improve`/`_quota_counts`/`_hpo_*`（局部停滞与配额游标）、`_deferred`/`_jev_values`（延迟评估队列与本岛 Jev 值）、`_crossover_partners`/`_offered_insights`（本岛交叉伙伴与已提供洞察）、`_island_focus`（本岛提示重点）；局部最佳不另设引擎字段，每岛冠军由 `Tree.get_island_best()` 现算并即时写入 `IslandState.best_node_id/best_score`。每个 `IslandRuntime` 持自己的 `attrs` 字典（`_fresh_island_attrs()` 逐岛新建，三岛不共享同一个可变对象）；运行级共享的只有 `store`/`metrics`/`_cost_ledger`/`task_adapter`/`task_spec`/`llm` 客户端与协调器本身，另有 `_initial_score`（共享 init 的基线，三岛同源故全局一份）与 `_active_island`（当前活动岛游标）。Jev 不共享校准状态：`_jev_values` 与 `_deferred` 属岛，`_restore_jev_state()` 恢复时按事件 `island_id` 过滤，因此不会读到另一岛的父节点。LLM 计量在 `_meter_llm_call()` 统一写 `llm_call.island_id = 活动岛`（串行运行下活动岛即发起岛），实测见 `test_island_focus_reaches_only_its_own_prompts` 末段。legacy 兼容入口是 `legacy_island_spec()`（`island_id=""`、`max_attempts=10**9`、沿用历史种子 `seed+1009+n`、不注入本岛重点），只在「显式 `enabled=False`」或「恢复的历史运行没有岛状态且节点全在 `""`」时解析出来；多岛运行绝不会降级成第一岛，`_resolve_island_specs()` 是唯一决策点。

#### D2.3 初始化三岛

- [x] 为三岛生成不同节点 ID 和 island_id；从同一 init 源读取代码，不修改 init.py。
- [x] 优先真实评估一次共同 init 并共享不可变评估引用；三岛各根标记 shared_initial_evaluation_id，账本仅计一次。若评估不可复用则分别跑并如实计费。
- [x] 初始评估失败时终止新运行并记录，不能把 0 分无效初始化当正常基线继续正式实验。

落地说明（2026-10-08）：`_init_island_roots()` 逐岛调 `_create_root_for_island()`，代码一律读 `task_spec.init_code`（受保护 `benchmark/hdd_mvp/init.py` 未被改动，`git status` 可核）；`create_init_node(island_id=...)` 给每岛一个独立 uuid 节点 id。首个岛做一次 `task_adapter.evaluate`，其余岛复用同一份不可变 `NodeEvidence` 并写 `shared_initial_evaluation_id=首岛根 id`，账本只有一条 `stage=full_eval`（`tests/test_hotfix_3_1.py` 断言三根三岛、`init_evaluated` 载荷带共享标记）；若首岛评估因异常没拿到结果（或账本拒绝），后续岛不会拿到“共享引用”，也绝不写假分数。评估结果为无效（`validity=0`）时不再当基线：三岛一律 `status=finished`、`stop_reason=init_evaluation_invalid`，发 `init_evaluation_invalid` 与 `run_aborted_invalid_init` 事件，`run()` 因没有可运行岛直接结束，`_get_stop_reason()` 优先返回该原因——旧行为（无效根空转到上万次 `selection_failed`）已由 `tests/test_run_stall_guard.py::test_an_invalid_initial_evaluation_stops_before_searching` 固定为 0 次迭代、0 次尝试。

#### D2.4 编写最小调度循环

```text
加载/初始化父运行与各岛状态
while 存在可运行岛:
    持久化选择下一可运行岛的调度游标
    在该岛创建 attempt，读取其树和本岛策略
    选择本岛父节点，加入适用知识和已投递摘要
    生成 -> 预检查 -> 真实评估或记录失败
    原子记录节点结果、attempt 完成和已知成本
    更新本岛统计，再从三岛真实结果汇总全局最优
    检查该岛交换游标，投递新摘要
    计算本岛/全局停止原因，保存检查点
导出结果（含失败/停止状态），关闭运行资源
```

- [x] 将现有 `_run_one_iteration_inner` 的核心流程复用为接受岛上下文的函数，避免复制三份上千行引擎。
- [x] 本阶段先保持串行；参数配置为大于 1 时若尚未支持，启动前明确拒绝，不能表面接受后忽略。完成并发支持不是本轮默认路径的前提。
- [x] 测试 A/B/C/A/B/C 的轮转顺序；B 暂停后变为 A/C/A/C；无 runnable 岛时父运行结束而非忙等待。

落地说明（2026-10-08）：调度循环在 `EvolutionEngine.run()` 内，每轮先 `self._coordinator.next_runnable()` 取岛（内部已推进并 `persist_cursor()` 落 `scheduler_state`），再 `_activate_island()` 换入该岛的属性槽，然后原封不动调既有 `_run_one_iteration()` → `_run_one_iteration_inner()`（选择、算子、生成、预检、真实评估、修复链、账本与检查点全在一处，岛差异只体现在“读到的是哪一份可变状态”）。attempt 起点由 `_count_attempt()` 记一次并发 `attempt_started`；评估结束由 `_record_evaluation_outcome()` 写本岛计数；`_update_island_after_attempt()` 算本岛停止原因；随后 `_best_across_islands()` 汇总全局最优、`_sync_island_states()` 落盘。`eval_concurrency>1` 在 `initialize()` 抛 `ValueError`（不静默降级为 1），实测 `tests/test_island_isolation.py::test_eval_concurrency_above_one_is_refused_not_ignored`。轮转与暂停行为实测见 `::test_rotation_is_round_robin_and_skips_a_paused_island`（严格 A/B/C/A/B/C；B 暂停后 A/C/A/C；恢复后 B 重新入环不被饿死）、`::test_a_paused_island_does_not_stop_the_parent_run`（B 尝试数 0，A/C 各 2，父运行继续）与 `::test_the_run_ends_when_no_island_is_runnable`（0 迭代即结束、恰好一条 `all_islands_stopped`、无 `run_stalled` 空转）。
- 父运行“为什么结束”：无 runnable 岛时置 `_all_islands_stopped`，`_get_stop_reason()` 在 `target_score_reached`/`init_evaluation_invalid`/`selection_stalled`/`ledger_full_eval_cap`/预算类原因之后、`max_iterations` 之前返回 `all_islands_stopped`（成本先耗尽时仍报成本原因，不把预算截断冒充岛耗尽），该断言写在 `::test_the_run_ends_when_no_island_is_runnable`（`summary.stop_reason == "all_islands_stopped"`）；多岛运行的 `run_finished` 载荷并入 `_island_stop_summary()`，同一测试断言其中三岛的 `stop_reason` 逐项可见。修复前该场景 `stop_reason` 落到 `unknown`，属 D2.6“记录每岛和父运行结束原因”的漏项。

#### D2.5 让三种 profile 实际生效

- [ ] 对每种 profile 配置提示重点、算子倾向、知识检索关键词和可用辅助指标；记录本次实际选择原因。
- [x] 将 20% 多样探索做成带种子的策略选择，不用固定每五轮同一种算子冒充随机探索。
- [x] 指标缺失时退回任务主指标和可用特征，不凭空新增数值；所有真实分数仍来自 evaluator。
- [x] fake LLM 捕获三个岛的请求，断言策略差异来自实际上下文，同时输入任务相同。

落地说明（2026-10-08）：已生效的两条通道是提示与算子。提示侧 `OperatorContext.set_island_focus()` 把 `IslandSpec.focus`（默认三岛取自 `config.default_islands()`，`profile=custom` 必须自带 focus）渲染成 `## 本岛优化重点` 段，插在 `USER_MESSAGE_TEMPLATE`/`CROSSOVER_USER_TEMPLATE` 的任务说明之后；实测 `test_island_focus_reaches_only_its_own_prompts`：三岛各自提示含本岛重点、不含兄弟岛重点，且都含同一份任务说明文本（`prompt_md`），因此差异只可能来自策略上下文而不是任务。算子侧 `_apply_island_bias()`（在 `_available_operators()` 之后调，可用性仍是机制、偏好才是画像）把本岛 `operator_bias` 收窄成偏好子集，`exploration_ratio`（默认 0.2）比例的选择用本岛自己的 `_op_rng` 逃逸回全集，事件 `operator_bias_applied` 记下 `profile/preferred/off_bias/exploration_ratio/exploration_draw`，即“本次实际选择原因”可追溯；`_op_rng` 由 `seeded_island_rng(seed, island_id, n)` 构造，实测 `test_exploration_draws_are_island_local_and_reproducible`（同种子两库逐次相等；反复切到 B/C 抽取不改变 A 的序列；0.5 比例确实两种结果都出现）与 `test_profile_bias_narrows_the_pool_unless_the_draw_explores`（比例 0 只剩本岛画像算子，比例 1 回到全集）。分数与指标不受画像影响：本阶段没有为任何岛新增辅助数值，`combined_score` 与 metric 全部来自 evaluator，缺失的辅助指标不会补造。

未完成部分（如实保留未勾选）：`knowledge_keywords` 还没有进入 `_retrieve_knowledge_cards()` 的检索——那是 D4.1 的接线；“可用辅助指标”按岛配置同样属于 D4.1，本阶段只用任务主指标。

#### D2.6 停止与导出

- [x] 每个 attempt 无论成功失败只完成一次；每岛上限 50，repair/HPO 候选计入同一上限。
- [x] 停滞仅由有效评估累计，达到最少 10 次后才检查连续 15 次无提升；按任务得分方向判断，最大化/最小化都支持。
- [x] 连续 5 次基础设施失败暂停该岛，算法无效不算基础设施失败；用户停止应让在途任务有明确状态。
- [x] 全局最优从同一候选读取整组指标；无有效结果输出空值与失败原因，不返回伪造冠军。

落地说明（2026-10-08）：`_count_attempt()` 每轮只在算子确定后调用一次，HPO 配额轮（`run_hpo_quota_iteration`）在同一处计费；修复链另外计费——`_attempt_repair()` 入口先检查本岛剩余额度，额度用尽时拒绝生成修复代码并发 `island_attempt_cap_hit`（带 `island_id/attempts/max_attempts/refused="repair"`），只有真正产出可评估候选、`add_node` 之后才 `self._count_attempt(failed_node, OperatorType.REPAIR)`，因此“链子没成候选”不占额度，而“50 个候选”是硬上限、不能靠修复链绕过。实测 `test_island_budget_is_charged_per_attempt_not_per_operator`（3 岛×3 次共 9 条 `attempt_started`，每岛编号 1/2/3）、`test_consecutive_invalid_candidates_hit_the_attempt_cap`（无效候选照样触顶并以 `max_attempts` 结束）、`test_repair_candidate_spends_an_island_attempt`（`attempt_started` 序列 refine→repair，attempts=2）与 `test_repair_is_refused_once_the_island_cap_is_reached`（上限 1 时无修复节点、一条 `island_attempt_cap_hit`）。停滞：`valid_evaluations ≥ min_valid_evals_before_stall`(10) 且 `stall_valid_evals ≥ stall_valid_evals`(15) 才判 `stalled`；无效评估不计入停滞，只进 `invalid_evaluations`；方向判断依赖任务适配器归一化后的 `combined_score`（越大越好），因此最大化与最小化任务共用同一比较。基础设施熔断：只有评估器本身抛异常才 `_note_infra_failure()`（`evaluate_exception`/`repair_evaluate_exception`/`init_evaluate_exception`），`infra_fail_streak ≥ infra_fail_pause`(5) 时该岛转 `paused`，异常随后照常上抛，不伪装成候选成绩；一次真实评估成功即把 streak 归零。导出：`_best_across_islands()` 从每个岛自己的 `Tree.get_island_best()` 取（id, score）成对比较，冠军 id 与其整组指标始终来自同一节点；运行结束时 `_activate_island_of_best()` 把 `engine.tree` 留在冠军所在岛，`tree.json`/artifacts 因而读到的就是冠军那棵树；没有有效结果时 `best_node_id=None`、`best_score` 取真实值 0.0 并写 `stop_reason`（`init_evaluation_invalid`/`all_islands_stopped`/`max_iterations` 等），崩溃摘要同样只报已有事实，不补造冠军。

### D3：实现摘要消息，而非候选代码复制（对应 S3）

#### D3.1 先实现摘要结构和安全边界

- [x] 建立正面、负面、知识摘要的统一数据模型。正文建议最多 1200 字符，每条事实都有 evidence_ref；超长时重新提炼，不截断成无法理解的半句话。
- [x] summary 只允许方法描述和必要参数结论；metrics 由程序读取评估结果填入，LLM 不能填写或覆盖数字。
- [x] 原始 trace 先由错误分类器处理，摘要不带序列号、原始行、绝对数据路径、密钥或整段程序。
- [x] 将 summary 作为数据放进固定提示模板，不执行其中的路径或指令；不因文本要求“读取源文件”而打开外岛代码。
- [x] 内容检查只是辅助，真正的边界是跨岛上下文构建器只收到摘要 DTO、没有外岛源码字段和自动解析源路径逻辑。

落地说明（2026-10-08，提交 9592fe7＋2f368fa）：统一模型是 `common/schemas.py::ExchangeSummary`，`kind` 取 `best|failure|knowledge` 三值（`EXCHANGE_KINDS`），正文上限是常量 `SUMMARY_TEXT_MAX_CHARS=1200`，`evidence_refs` 逐条记 `node:<id>`；`faultevolve/cloud/exchange.py::sanitize` 把代码块、行内代码、Windows/POSIX 绝对路径、时间戳、≥6 位连续数字（序列号/盘号）替换成占位标记，再丢弃 traceback 框架行与超过 160 字符的单段，超预算时**整段尾部裁撤**而不是切片——2f368fa 之前的实现用 `[:1200]` 截断，会把一句话切成半句，现按 `；`/换行切段后以段为单位计数，实测 `test_an_over_long_body_is_reduced_by_whole_segments_not_mid_sentence`（12 段×155 字符＝1871 字符输入，保留段数变少且每段仍是完整原文）。metrics 只由程序写入：`_scalar_metrics()` 从 `node.evidence.evaluation` 取 `combined_score/validity/cost_time/delta_vs_parent` 与指标白名单，`_failure_stats()` 从存储中的同岛无效候选数出 `occurrences/repair_attempts`，LLM 的输出只贡献 intent/hypothesis/insight 文本、经同一 `sanitize` 进入正文，没有任何路径让模型写数字。错误摘要的原文先过 `error_class_of()`：只取 `error_info` 冒号前的类名（实测 `test_only_the_error_class_is_read_out_of_a_traceback` 对 `/secret/path/holdout.csv` 的 traceback 只得到 `NameError`）。模板侧 `operators.py::_exchange_summary_section` 把摘要渲染成带 `[岛 · 类型 · ROS · 摘要ID]` 前缀的数据行，标题即声明“只有方法描述与评估结论，不含任何源码”，并紧跟一句边界说明：不得据此索要、猜测或重建来源岛程序，也不因摘要文字要求去读取其他文件——这是文本层的辅助，真正的硬边界在结构层：`SummaryContext.as_dict()` 的键固定为 `delivery_id/summary_id/kind/source_island_id/source_node_id/summary_text/conditions/metrics`，没有 code 字段，`OperatorContext` 侧只有 `exchange_summaries: list[dict]`，`operators.py` 里不存在任何把摘要里的路径打开或解析源节点取源码的代码（`test_summary_dto_has_no_place_for_code` 钉住键集）。范围说明：`knowledge` 一类本轮只建模型不入队，其发布归 D4.1 知识注入，未接线不写成已完成。

#### D3.2 定义提炼条件

- [x] 有效候选超过该岛已发布最佳时才发布新最佳摘要；初始根仅用于“基线策略摘要”，不得称为改进。
- [x] 失败摘要只总结明确证据：错误类型、发生条件、已尝试修复、当前结论。退化比较必须指向本岛父节点评估。
- [x] 摘要生成失败不改变 evaluator 分数；记录 exchange_summary_failed，本候选结果仍保留，不返回伪造摘要。
- [x] 相同内容采用规范化后哈希去重，保留多个证据来源关系；跨 run 默认不自动广播，历史经验仅通过显式知识输入加载。

落地说明（2026-10-08）：最佳发布的判据是 `_published_best()` 从**存储**读回该岛已经发布的最高 `combined_score`（不是内存变量，所以重启后不会重复宣布），只有 `score > published_score` 或该岛从未发布过才生成新最佳；岛还没有任何成绩时树上最优就是共享初始根，此时仍允许描述“基线策略”，但因 `published_score < 0` 分支不写 `previous_published_best`/`gain_vs_published_best` 两个字段，措辞上没有把起点说成改进——实测 `test_a_baseline_root_is_described_without_claiming_an_improvement`（`source_node_id == root.id` 且两个 gain 字段不存在；第二轮更差的候选不再产生新摘要，`exchange_check` 第二条 `zero_send=true`）。失败摘要正文固定三段：“错误类型 X／发生条件：在岛 a 的方案上扩展时出现／当前结论：同类写法在该岛不可用，生成新方案时先排除”，其中“已尝试修复”不进正文而进 metrics（`_failure_stats()` 统计同岛同类的 `occurrences` 与该节点 `repair_count` 最大值），渲染时以“同类出现 N 次 · 修复尝试 M 次”随条目前缀出现，这样正文保持稳定、同一错误重复只加证据不加消息；退化/增量比较用的 `delta_vs_parent` 取自本树本岛父节点的评估结果，绝不引用外岛节点。摘要生成的每一步都包在 try/except 里：`_new_summary` 清洗后为空、发布异常、投递异常都只写 `exchange_summary_failed`（带 `error_type/reason/node_id`），候选自己的评估与岛屿计数不受影响——实测 `test_a_broken_summary_channel_never_touches_a_score`：把 `_publish_best` 替换成抛异常后，`_island_states(engine)["a"].best_score` 仍是评估器给的 31.0，摘要表为空、零发送事件在。去重用 `content_hash(kind, text, conditions)`（空白规范化后 sha256 前 24 位），存储上还有 `UNIQUE(experiment_id, kind, content_hash)` 兜底；命中已存在结论时不插入新行，而是 `add_summary_evidence()` 追加 `node:<id>` 证据并把 `confidence_status` 沿 `proposal→single_observation→replicated→statistically_confirmed` 升一级，同时把最新统计随证据一起刷新 metrics（否则读者会看到“出现 1 次”的旧计数）——实测 `test_a_repeat_of_the_same_error_adds_evidence_instead_of_a_second_message`：两次同类生成式失败后摘要仍只有 1 条，`evidence_refs` 两条、状态 `replicated`、投递数不变、`exchange_summary_replicated` 有记录。跨 run 隔离：`IslandExchange` 的每一次读写都以 `experiment_id` 过滤（`get_summaries_by_experiment`/`get_deliveries`/`get_applications_*`），没有任何“扫全部历史摘要”的入口，历史经验只能经 D4.1 的知识卡输入链路进入。

#### D3.3 定义交换游标

- [x] 每岛保存 completed_attempts 和 last_exchange_attempt；差值达到 5 触发检查，检查后更新游标，即使没有可发消息也更新。
- [x] A 达到第 5 次时向 B/C 各检查一轮，不等 B/C 完成 5 次；终止岛不再接收新生成工作。
- [x] 同一轮对每个目标最多 1 正面＋2 负面；无新内容时写零发送事件，不能重复刷消息。
- [x] 每条重要执行错误允许提前投递一次，后续定期交换仍受同一投递去重约束。
- [ ] 停滞请求在新检查点触发，不能每次轮询重复调用 LLM。

落地说明（2026-10-08）：游标是 `IslandState.attempts`（已完成尝试）与 `IslandState.last_exchange_attempt` 两个已落盘字段，判据 `due()` 即 `attempts - last_exchange_attempt >= islands.exchange_interval`（默认 5，测试配置里压到 1 以便观察）；`_maybe_exchange(rt)` 挂在主循环 `_update_island_after_attempt()` 之后、按协调器选出的**本岛**状态执行，所以是“谁的第 5 次到了就交换”，不等兄弟岛——`_exchange_targets(rt)` 只返回状态为 `PENDING/RUNNING` 的其他岛，`FINISHED/PAUSED` 岛不再收到新生成工作（实测 `test_a_stopped_island_is_neither_a_reader_nor_a_writer`：c 置为 finished 后投递目标只有 `{b}`，且 c 的 attempts 仍为 0）。无论有没有发出去，检查完都把游标推进到 `rt.state.attempts` 并 `save_state()` 落盘（否则“无事可发”的岛会每次轮询都重扫收件箱）；恢复时游标从存储读回，实测 `test_the_same_lesson_is_published_once_even_across_a_restart`：第一次尝试后 `(摘要数, 投递数)==(1,2)`，同一轮再调 `_maybe_exchange` 不新增，重启后的引擎 `last_exchange_attempt==attempts`，再强行按到期轮跑一次 `checkpoint()` 仍只有 1 条摘要、2 条投递。零发送可观测：`checkpoint()` 结尾无条件写 `exchange_check{island_id,published,delivered,zero_send}`，`zero_send = delivered==0`，于是“检查过但没话说”与“没检查”在事件流里是两件事。每轮上限由配置控制而非硬编码：正面只在 `max_positive_per_exchange>0` 时发布且一次至多一条（本岛当前最优只有一条），负面取 `failed_nodes[:max_negative_per_exchange]`（默认 2）；投递唯一性另有 `UNIQUE(summary_id, target_island_id)` 保证。提前投递：`islands.early_error_share` 为真时，`_maybe_exchange` 先取本岛“尚未被摘要覆盖过”的无效候选（`_unpublished_failures()`，用 `exchange.summarized_nodes(island,"failure")` 从存储反查已发布集合，排除 repair 节点，按 `created_at` 新→旧）并调 `share_error()` 立刻发 1 条，不等游标；随后照常进入游标判定，因此同一条错误在定期轮里会被去重，不会变成每轮广播（实测见 T11 与 D3.2 的 replicated 用例）。**未实现且保持未勾选**：`islands.stagnation_request_evals` 目前只有配置字段与 UI 元数据，引擎里没有任何“停滞求助”调用点（全仓 `grep stagnation_request` 仅命中 `config.py:165` 与 `webapi/catalog.py:207`），因此本轮不存在“每次轮询重复调用 LLM”的风险，但也不得声称求助机制已落地——它不在 S3 的四个必须可见测试之内，归入后续阶段。

#### D3.4 投递和采用分开实现

- [x] 保存 offered 表示目标可看到，accepted 表示适用且愿意尝试，applied 表示确实进入某候选上下文，evaluated 表示该候选已有真实结果。
- [x] rejected 保存原因，例如任务不匹配、过时、重复、违反目标约束；不能将所有收到消息自动标为采用。
- [x] 一个投递可影响多个新候选时，每次 application 单独关联 candidate_id；投递去重不等于限制只能使用一次。
- [x] 目标队列设置每次上下文最大摘要条数，建议 3；按相关性和新颖度排序，避免把全部历史塞进每次提示。

落地说明（2026-10-08）：四个事实落在两张表上，`exchange_delivery.status` 只走 `offered→accepted|rejected`（`DELIVERY_STATUSES`），applied/evaluated 由 `summary_application` 行表示——`record_applications()` 在候选入树之后、按“本轮真正被渲染进提示的摘要”逐条插行（`UNIQUE(delivery_id, candidate_node_id)` 去重），`complete_applications()` 在候选自己评估完成后把 `evaluation_id` 与 `score` 写回；无效候选只写 `evaluation_id`、`score=None`，从未评估的候选则停在 `evaluation_id=''、score=None` 的 pending 态，四种组合互不推导。实测 `test_offered_accepted_applied_and_evaluated_are_not_counted_as_one` 按同一条摘要分阶段核对：A 发布后 `{delivered:2, offered:2, accepted:0, applied:0, evaluated:0}`，B 生成后 `{offered:1, accepted:1, applied:1, evaluated:1}`，C 生成后 `{offered:0, accepted:2, applied:2, evaluated:2}`——一条 delivery 被两个岛各用一次，`accepted` 数读者、`applied` 数注入次数，两者都不是投递数。采用判定发生在**生成时**而不是投递时（`engine._accepted_summaries()` 在主循环取父节点之后、`_choose_operator()` 之前调用），因为“是否适用”取决于本岛此刻的最优；每个 `offered` 只决策一次并落盘，重启后按收件箱现状重放，不会二次决策（`test_an_overtaken_best_is_rejected_as_superseded` 里第二次读取 `exchange_rejected` 事件计数仍为 2）。拒绝原因目前四种且都写进 `exchange_rejected` 事件与 delivery 行：`target_island_not_runnable`（岛已停）、`task_fingerprint_mismatch`（`task_fingerprint()` 由 problem+instruction 文本哈希）、`evaluator_fingerprint_mismatch`（`evaluator_fingerprint()` 由评估器字节哈希，读不到时留空并且**不假装**匹配）、`superseded_by_newer_best`（同一来源岛已宣布更高分时，旧最佳视为过时）——实测 `test_a_summary_from_another_task_or_evaluator_is_rejected_with_reason` 对 b/c/d/e 四个目标分别命中前三种与“同任务同评估器则接受、且 `exchange_rejected` 为空”。队列上限是 `islands.max_summaries_in_context`（默认 3，测试压到 2）：先按 `created_at` 新→旧稳定排序，再按 `_rank()` 做二级稳定排序——`(0, -gain)` 给“仍然领先本岛最佳”的正面结论、`(1, -gain)` 给其余，于是领先者在前、同组保持到达顺序，`test_the_context_queue_is_capped_at_the_configured_size` 断言 3 条待选（1 正面＋2 避错）只留 2 条且首位是 `best`。

#### D3.5 接入跨岛交叉

- [x] 在已有 `_available_operators` / `_choose_operator` 路径增加摘要交叉选择，只有存在适用外岛摘要才可选。
- [x] 获取本岛父代码，读取摘要 DTO，生成新代码；不要调用获取 foreign second parent source 的旧路径。
- [x] 记录 operator 为可识别的摘要交叉类型；来源关系包含 summary_id/source island/source node，但树父节点仍在本岛。
- [x] 新候选执行同一静态检查、评估和错误处理链；无评估结果时只能显示 pending/invalid，不能继承来源 ROS。

落地说明（2026-10-08）：算子用 S1 就存在的 `OperatorType.SUMMARY_CROSS`（在 `GENERATIVE_OPERATORS` 内，因此天然走生成式候选的全部后续链路）。可用性来自收件箱而非本树：`_summary_cross_candidates()` 只取本轮已 `accepted` 且 `kind=="best"` 的上下文，`_available_operators()` 仅在它非空时把 SUMMARY_CROSS 放进算子池，因此“没有适用外岛摘要”时该算子根本不可选。选择规则：默认配置 `operators.bandit=False`，旧代码在非 bandit 分支直接 `return REFINE`，那会让一条被采纳的摘要读进提示却被无声丢弃，所以这里加了一条前置判据——存在 `metrics.combined_score` 严格高于本岛 `_local_best_score()` 的正面摘要时选 SUMMARY_CROSS 并写 `summary_cross_selected{island_id,parent_id,summary_id,source_island_id,reason:"sibling_ahead"}`；本岛一旦追平或反超，判据自己失效，不需要额外开关。bandit 打开时走同一条 UCB 路径，摘要交叉作为普通可用算子参与采样。岛屿画像不会吞掉它：`_apply_island_bias()` 在收窄算子池时把 SUMMARY_CROSS 保留进 `narrow`（`operator_bias_applied` 事件加 `exchange_kept` 字段），否则“有兄弟领先”与“画像偏好”同时成立的轮次会静默丢弃交换；实测 `test_profile_bias_narrows_the_pool_unless_the_draw_explores` 仍然只断言画像集合。安全兜底：若算子已定为 summary_cross 但渲染前发现没有可用正面摘要（例如收件箱在两次读取之间被更新），当场降级为 REFINE 并写 `operator_fallback{requested:"summary_cross",used:"refine",reason:"no_applicable_summary"}`，不生成一个自称嫁接却无来源的候选。生成路径只读本岛父代码：`OPERATOR_INSTRUCTIONS[SUMMARY_CROSS]` 明确要求“只能依据摘要文字，不得索要、猜测或重建来源岛的源码；来源分数只是线索，最终成绩由本地评估器决定；摘要中的避错条目同样必须遵守”，`USER_MESSAGE_TEMPLATE` 与 `CROSSOVER_USER_TEMPLATE` 都新增 `{exchange_summary_section}` 插槽，代码里没有任何取 foreign second parent 的调用——`engine._build_ctx` 之后走的是与 REFINE 相同的 `generate_with_adoption(ctx)`，父节点仍是本树 `select_parent()` 的结果，存储上 `get_node_parents(child.id) == []`（实测 `test_a_positive_summary_reaches_the_sibling_prompt_and_is_evaluated_locally`：B 的嫁接节点 `parent_id` 在 B 树内、`!= ` 摘要来源节点 id，且 `summary_crossover{node_id,parent_id,sources:[{summary_id,delivery_id,source_island_id,source_node_id}]}` 记下来源关系；provenance 在 application 行与事件里，不在树上）。后续链完全同一：预筛/`_evaluate_child`/错误处理/修复/预算都不区分摘要交叉与普通 refine，唯一差别是 LLM 记录 `record_purpose="summary_cross"`。分数不继承：`_finish_summary_applications()` 只把候选**自己**的评估结果写进 application 行，`test_a_grafted_candidate_never_inherits_the_source_score` 里来源摘要是 31.0 而候选抛 `ZeroDivisionError`，application `score is None` 且 `evaluation_id==candidate_node_id`，节点状态由评估器判为无效（`validity=0.0`，评估器自报 `combined_score=0.0`），树上没有 31.0 这个数；`test_an_application_is_pending_until_its_own_candidate_is_evaluated` 钉住未评估时是 pending（`evaluation_id=''`、`score=None`），同一摘要在同一候选里也只有一行。

#### D3.6 四个必须看得见的测试

- [x] 正面摘要测试：A 生成已知提升，B 收到摘要并生成候选；fake LLM 捕获 B 的输入，断言存在摘要内容。
- [x] 负面摘要测试：A 出现预设执行错误，C 输入中出现归纳后的避错条件，原始 traceback 敏感字段不出现。
- [x] 源码隔离测试：A 源码加入唯一标记，B 上下文中不存在该标记；同时验证 B 没有读取 A 源码文件的调用。
- [x] 幂等测试：同一消息投递两次、重启后投递一次，目标仍只有一条 delivery；同一 candidate 的 application 只有一条。

落地说明（2026-10-08，`tests/test_island_exchange.py` 22 个用例，全部离线：`MockLLM`/`_RecordingLLM`＋`FakeAdapter`＋临时库＋临时任务目录，不碰 `benchmark/hdd_mvp/data/`）：

1. 正面：`test_a_positive_summary_reaches_the_sibling_prompt_and_is_evaluated_locally`。A 的候选由 fake 评估器给 31.0（起点 22.0），`_RecordingLLM` 按岛重点文本给提示打标签后断言 B 的提示里出现该摘要正文；B 的嫁接节点分数是它自己的 18.0。摘要发布按岛作用域读取（B 也会宣布自己的基线最佳，所以断言按 `source_island_id=="a"` 取，不把两作者的行混成一条）。
2. 负面：`test_a_failure_lesson_reaches_a_sibling_without_the_raw_trace`。预设错误原文里埋了 `holdout` 路径、`disk_serial_1234567890`、`2026-10-08T09:12:33`、`9876543210`、```np.roll``` 代码块与 traceback 框架行；C 的提示里必须出现归纳后的避错条目，而上述每个片段在摘要正文和 C 的全部提示里都不得出现。
3. 源码隔离：`test_a_sibling_source_never_enters_the_receiving_prompt` 在 A 的最优节点源码里追加唯一标记 `A-ONLY-SOURCE-MARKER-8842`，断言该标记确实是已发布摘要的 `source_node_id` 所属节点（否则“没有出现”是空转），再断言 B 的所有提示与 B 树中所有节点代码都不含标记。局限如实写明：本轮是离线 mock，无法在文件系统层拦截“读取源码”的动作，真正的保证来自结构层——摘要 DTO 没有源码字段、`operators.py` 没有从摘要解析路径或外岛节点取码的调用点；这条边界在真实运行（S8/S9）里只能靠产物与日志复核，不能声称已在文件系统层验证。
4. 幂等：`test_the_same_lesson_is_published_once_even_across_a_restart`（重启后游标一致，再按到期轮强跑一次 `checkpoint()` 仍只有 1 条摘要、2 条投递）＋`test_a_summary_is_delivered_once_per_target_island`（存储层对同一 `(summary,target)` 第二次插入返回 False）＋`test_an_application_is_pending_until_its_own_candidate_is_evaluated`（同一 `delivery×candidate` 第二次调用返回空列表、行数仍为 1）。另加 T26（`test_offered_accepted_applied_and_evaluated_are_not_counted_as_one`）钉住四种事实不混计。

这些测试只在临时 toy 数据下进行。真实实验的正负事件数量按实际发生报告。

### D4：知识注入、账本和断点恢复（对应 S4）

#### D4.1 接入知识，不重造发现流程

- [x] 从 `_get_knowledge_dir`、`_retrieve_knowledge_cards`、`_extra_card_paths` 找实际输入路径，使用任务配置提供知识源。
- [x] 加 island/profile 到检索上下文，读取冻结库和运行新增经验时分别记录 source_type。
- [x] 在候选 provenance 中记录实际注入 card_ids，不能只记录“功能开关为真”。
- [x] 没有适用知识时记录空选择和原因，继续正常生成；知识服务失败不得改成 CONFIRMED。
- [x] 不为本任务扩大 KD 发现/锦标赛统计实验，本轮验证知识进入演化链路即可。

落地说明（2026-10-08，提交 bd76846）：输入路径未另起炉灶——仍是 `_get_knowledge_dir()`（需 `engine.task_dir` 与 `config.knowledge.dir`）→ `_retrieve_knowledge_cards()` → `knowledge/selection.get_era_knowledge_cards()` → `loader.load_all_cards()`＋`retriever.CardRetriever`，本轮只把“哪个岛在问”接进去。岛画像的 `knowledge_keywords` 以 `context["island_keywords"]` 进入检索上下文（`default_islands()` 三岛各 4 个关键词），实测 `test_each_island_reads_the_library_for_its_own_keywords`（6 卡 6 类库、`max_per_category=1`：岛 a 取到特征工程/模型类，岛 c 取到冗余特征/稳定性类，三岛选择互不相同）。来源类型在**加载处**打标（`loader.ORIGIN_FROZEN` / `loader.py:235` 的 `ORIGIN_RUN_NEW`），不是在这里按卡 id 猜；`KnowledgeSelection.sources_by_origin()` 只分组实际出现的来源，实测 `test_a_card_this_run_produced_is_labelled_run_new` 与 `test_experience_promoted_on_one_island_is_knowledge_for_the_others`——本运行新增经验写的是 `_discovery_card_path()`，它是**实验级共享目录**（三岛同一个池），岛 b 产出的卡在检索时以 `run_new` 出现且不与冻结库混淆（`load_cards_from_dir` 只读 `cards.jsonl`，所以运行池不会被当成冻结库）。provenance 记的是实际注入：`knowledge_injected` 在**每一次尝试检索**时都写（空选择与失败也写），载荷含 `island_id/profile/parent_id/operator/selected/card_ids/sources/island_keywords/reason/error_type`，INJECT 算子取 `[:1]`；实测 `test_an_injected_card_reaches_the_prompt_and_the_candidate_record`（提示里 `<knowledge_cards>` 出现 `- **K-A1**: …`，候选 `card_ids == ["K-A1"]`）——注意 MockLLM 的 canned 回复自带 `<adopted_cards>FE01,M01`，而 `common/codecheck.py::extract_adopted_cards_from_response` 取第一个标记，故测试用 `_DeclaringLLM` 正则替换该标记，断言才指向真实注入的卡而不是模型默认声明。空选择/失败原因清单固定为 `knowledge_disabled|stage_capped|no_knowledge_source|retrieval_failed|no_applicable_card`；检索异常整段包 try/except，只记原因与 `error_type`，生成照常继续，实测 `test_a_library_that_will_not_parse_selects_nothing_and_says_why`（库文件损坏 → 空选择＋原因，候选仍有真实评估分）与 `test_a_broken_knowledge_service_changes_no_score`（把检索替换成抛异常后，岛 best 仍是评估器给的分数，不产生任何 CONFIRMED）。发现流程未扩大：只把 `_harvest_discovery_candidates()` 的 insight 读取改成按活动岛过滤（`store.get_insights_by_experiment(experiment_id, island_id=…)`），实测 `test_a_discovery_round_harvests_only_the_island_that_asked`，未新增 KD 锦标赛/统计实验。范围说明（如实保留，不写成已完成）：`ExchangeSummary.kind="knowledge"` 本轮**不**接入发布队列——本运行新增经验的跨岛共享已由实验级 `_discovery_card_path()` 池完成，再建一条摘要通道是重复接线；这条判断同时补全 D3.1 的“`knowledge` 一类只建模型”注记。

#### D4.2 成本事件化

- [x] 从 `_meter_llm_call` 和所有新摘要/知识调用进入统一计量；每条至少有 request_id、attempt/island、stage、token usage、时间和是否重试。
- [x] 已知费用只有可信账单/费率依据时写入；否则保留 Token 和 unknown，不凭经验估价。
- [x] 总计等于各岛直接成本＋共享成本；共享初始化/摘要不要在源岛和目标岛重复计两遍。
- [x] 请求发出后失联时保存 unknown_outcome，不假装没有花费；重复恢复只重试有明确策略的请求并记录关联。

落地说明（2026-10-08，提交 0eac985）：统一入口仍是 `_meter_llm_call(metrics, purpose, node_id, model, db_purpose, persist)`，新增模块级 `LLM_STAGE_MAP`（generate/refine→`generate`、repair、reflect、crossover、self_fix，其余 `other`），账本行与 `llm_call` 行**共用同一 stage 命名**，避免两处对同一次调用起两个名字。每条成本行至少含 `request_id`、`transport_attempts`、`island_id`＋`island_attempt`（`_island_attempt_index()` 取 `IslandState.attempts + 1`，即“正在跑的那一次”；无活动岛的运行级工作记 null 而不是第 0 次）、`stage`、token usage、`created_at`、`outcome`：`CallMetrics` 加 `request_id/attempts`，`DashScopeLLM.chat` 为每个逻辑请求生成 `uuid4().hex[:12]`，成功时带 `attempts=attempt+1`，重试耗尽的 `LLMTransientError` 带 request_id 与 `attempts=len(RETRY_DELAYS)+1`；缓存命中没有发出请求因而不带 request_id，靠 `cached` 标志在 rollup 里单列 `cached_calls`，与真实新花费区分。算子的格式重试链合成一行并说明真相：`RefineOperator`/`RepairOperator` 的多次发送记**第一个** request_id 与发送次数，累加器必须从 `CallMetrics(attempts=0)` 起算——初版沿用默认 1 使两次发送报成三次，由 `test_a_generation_that_needed_two_sends_says_so` 首先暴露；`PatchOperator` 单次发送直接复制 `request_id/attempts`。失联请求不再凭空消失：六处 except（两处 self_fix、generate、repair、reflect、discover、mechanism）改调 `_record_lost_llm_call()`，写入 `outcome='unknown_outcome'`、token 为 0、request_id 与 transport 次数，并写 `llm_call_lost` 事件＋账本 `status="failed"`；`RunMetrics` 不动（它的总数只累加客户端确实看到的 token），rollup 以 `unresolved_calls` 报告这笔“花了但不知道多少”的请求，实测 `test_a_request_that_never_came_back_is_recorded_as_unresolved`。关于“只重试有明确策略的请求”：本轮的明确策略是**不自动重放**已失联的请求（没有“恢复时重放未决请求”的机制），恢复后由调度器按正常策略继续下一次尝试，而该次花费以 request_id 留痕供关联——不写成“已实现幂等重放”。不估价：`cost_usd` 默认 NULL、`cost_basis='unknown'`，`create_llm_call_record` 与 `get_cost_rollup` 都写明只有带真实账单/费率的调用才填 `cost_usd`（全库无费率表，已核实），实测 `test_money_is_never_guessed_from_tokens`。恒等式按行分桶校验：`get_cost_rollup()` 把 `island_id=''` 单独作为 shared 桶返回（不悄悄加给最后一个提问的岛），断言 `sum(各岛)+shared == 总计 == metrics.total_tokens == SUM(行内 prompt+completion)`，实测 `test_the_run_total_is_the_islands_plus_the_shared_bucket` 与 `test_one_request_is_never_counted_under_two_islands`——后者最初写成“任何名字含 summary 的行都不许存在”，这把 `summary_cross` 误当成路由开销：嫁接兄弟结论是一次**真实生成**，必须计费且由读取摘要的接收岛付（行的 `island_id` 即接收岛），断言据此改为“投递/接受/应用不产生成本行”。顺带修掉两个真实缺陷：(1) `cost_ledger` 没有岛列，且恢复时 `init_ledger()` 新建的内存账本从 seq=1 重新计数，与已落库的 `UNIQUE(experiment_id, seq)` 冲突 → 加 `island_id` 列＋`idx_cost_ledger_island`，`CostLedger(full_eval_cap=…, start_seq=store.max_cost_seq(experiment_id))`，`ledger_record()` 带活动岛，实测 `test_a_resumed_ledger_continues_the_stored_sequence`；(2) `Store.get_llm_calls` 原先静默丢掉新增列 → 改为 `_llm_call_from_row()` 逐列 `.get()`，缺列读作“未记录”（stage `''`、outcome `ok`、`island_attempt` null、`cost_usd` NULL）而不是 0，同时把加列迁移提到 `executescript(DDL)` **之前**——DDL 里新增的 `idx_cost_ledger_island` 引用 `island_id`，旧库该列还不存在时一打开就 OperationalError；两条由 `test_an_old_run_directory_still_opens_and_reads` 钉住（用 `DROP COLUMN` 造出 D4.2 之前的文件，先以 `read_only=True` 读未迁移原件，再开写库确认迁移前后行数与 token 一致）。`run_finished` 载荷新增 `"cost": get_cost_rollup(...)`，从存储读回而非内存计数器，重启后仍是同一口径；新事件类型 `llm_call_lost` 入 `webapi/catalog.py::EVENT_TYPES`，前端归入既有 `llm` 粗类（不新增第 13 类）。

#### D4.3 保存、恢复与旧运行复制

- [x] 恢复先读取保存配置/版本；拒绝在不说明的情况下换数据指纹、任务、岛数、代码 schema。
- [x] 旧运行写模式恢复先复制 SQLite（在线库用备份接口或一致性快照，不直接忽略 WAL），再复制所需产物到新目录；源目录只读。
- [x] 恢复 selector/算子统计、rng、交换游标、已用摘要、预算计数、deferred 候选，不能只恢复 Tree 节点。
- [x] 已评估但报告未写时只重建报告；有 evaluation_id 的完成结果不重新评估或重复加分。
- [x] 在途 worker/子进程先核实存活与任务身份；不启动第二份竞争执行。不能恢复时标记 interrupted 并按明确策略重试新 attempt。

落地说明（2026-10-08，提交 91c8203）：新增 `cloud/resume.py`（身份记录、运行声明、rng 快照、副本机制四件事都在这一处）与 `common/proc.py`（`pid_alive`：Windows 用 `OpenProcess`+`GetExitCodeProcess` 的 `STILL_ACTIVE=259`，POSIX 用 `os.kill(pid,0)`，判不了返回 `None`；从 `webapi/run_control.py` 原位抽出，后者改为 `_pid_alive = pid_alive`，纯搬迁无行为变化）。`store.py` 加 `run_identity`/`run_claim` 两表和 `put_run_identity/get_run_identity/get_run_claim/take_run_claim/release_run_claim`（两个读方法在**表不存在**时返回 None 而不是抛，所以 D4.3 之前的库照样能打开；释放只删自己 `holder_id` 那一行，晚退出的旧持有者不会给新持有者解锁）。`initialize()` 的顺序是本轮的关键约束：`_resolve_island_specs(resuming)` → `_verify_run_identity()` → `_take_run_claim()` → 协调器（挂 `rng_snapshot` 后 `restore_cursor()`）→ 每岛 `_prepare_runtime()` → `_apply_restored_rng()`，即**任何写入之前**就要拒绝，而不是跑到第一个岛上才拒。身份比较八项 `CHECKED_FIELDS`（`identity_version/schema_version/task_fp/evaluator_fp/init_fp/data_fp/seed/island_ids`）：不匹配 → `run_resume_refused` 事件（逐字段 `stored/now`）＋`ResumeRefused`（消息同样逐字段命名，CLI 打给 stderr 并退出码 1）；空串/空环/零版本按"未描述"处理，与"匹配"是两回事，实测 `test_check_identity_treats_absent_fields_as_unverified`。**数据指纹不读数据**：只对 `task_dir/data` 下的 `meta.json`/`descriptor.json` 求摘要，并且跳过任何名为 `holdout` 的路径段（既避免读 40 GB，也不碰私有测试集），实测 `test_the_data_fingerprint_reads_only_descriptors`（加数据文件不改摘要、`data/holdout/meta.json` 不改摘要）；描述文件消失算变化（`lost`），实测 `test_a_data_descriptor_that_disappeared_counts_as_a_change`。岛环由已落库的岛状态推出，`island_ids` 只是交叉核对：配置此刻少写一个岛不会把三岛运行缩成两岛，实测 `test_the_island_ring_is_the_one_the_run_was_built_with`；换任务/换评估器/换 seed 各自被拒且 `run_resumed` 不出现，实测 `test_a_changed_task_is_refused_and_names_the_field` 等三条。没有身份记录的旧运行**不是免检**：仍拿 experiment 行的任务文本对比（换任务照样拒），其余字段记 `unverified` 并在本次续跑时补写，供下次核对，实测 `test_a_run_without_an_identity_record_still_refuses_a_changed_task`（这条是最后补的——初版只写了注释说要比对却没真比对，代码与注释不一致本身就是缺陷）与 `test_a_run_without_an_identity_record_resumes_and_says_what_is_unverified`。副本：`fe evolve local … --resume ID --resume-from 源目录 --runs-dir 新家` → `run_local_evolution(resume_source=)` 在打开目标库之前 `clone_run_directory()`——库走 SQLite 的 `backup` 接口且源库以 `mode=ro` URI 打开（首版把 URI 拼成两个 `file:` 前缀，报 `sqlite3.OperationalError: unable to open database file`，用 `/tmp/probe_wal{,2,3,4}.py` 四次探针确认 `Path.resolve().as_uri()+"?mode=ro"` 才既只读又读得到 WAL），产物走 `copy_run_artifacts()`：数据库及其 `-wal/-shm/-journal` 永不按文件复制（`_DATABASE_SUFFIXES`），目标已有同名文件不覆盖，实测 `test_a_clone_carries_the_wal_and_leaves_the_source_readable`（活动写连接留在 WAL 里的一行确实进了副本，且副本是单个一致文件）、`test_artifacts_travel_as_files_and_a_database_never_does`、`test_a_clone_never_overwrites_a_database_that_exists`；源目录就是目标目录 → 直接拒（`test_resume_from_a_directory_the_run_would_write_into_is_refused`），CLI 实测副本续跑后原目录逐文件 sha256 全等且 WAL 为空（`test_resume_from_continues_a_copy_and_leaves_the_original_files_alone`，`_run_files`/`_wal_settled` 两个 helper 把"排除临时边车文件"的理由写在 docstring 里，因为只读打开本身可能造出 `-shm`）。rng：`persist_cursor()` 除游标外还写 `SchedulerState.rng_state_json`（每岛 `_op_rng.getstate()` 的 JSON），`restore_cursor()` 容错解析（坏 JSON/非 dict 当作没有，重派种子而不是接一条错流），`_apply_restored_rng()` 在 `_prepare_runtime()` 之后覆盖，因为准备岛时先用种子造了一条新流，实测 `test_the_rotation_cursor_and_operator_stream_come_back_together`（续跑接着同一次抽取）、`::test_the_stream_snapshot_survives_json_and_a_bad_payload`、`::test_the_coordinator_keeps_reading_a_cursor_without_a_stream`。预算：`_restore_run_cost()` 把 `llm_call` 行经 `add_llm_call` 重放（`_COST_ROW_TO_BUCKET` 把行名 `refine/summary_cross/jev_prescreen` 折回预算桶 `generate/jev`，否则这些 token 存在于账本却不计入任何上限），知识 stage 从 `knowledge_injected` 事件的**新增** `estimated_tokens` 字段求和（不记就接不回来），`run()` 在第一次预算检查之前发 `run_resumed`（载荷含 `cost_rows/total_tokens/knowledge_tokens/iterations_done/island_states/identity/previous_holder`），实测 `test_a_resume_carries_the_tokens_the_run_already_spent`、`::test_a_resumed_stage_counter_matches_the_rows_of_that_stage`、`::test_the_knowledge_stage_is_restored_from_what_was_injected`、`::test_the_budget_stop_uses_the_restored_spend`；失联请求重放后仍是"花了但不知道多少"，不进花费也不丢（`test_a_lost_request_is_not_counted_as_spend_but_stays_visible`）。已用摘要侧：`_pending_summary_applications()` 只重挂 `evaluation_id` 为空且候选确在本岛树上的 application 行，实测 `test_an_application_recorded_before_the_crash_still_gets_its_result`（同候选两行：完成的不重挂、未完成的挂回，两行都还在库里）。deferred 候选：`_restore_jev_state()` 本就按活动岛过滤，本轮补两处并修一处真实缺陷——`_flush_deferred()` 遇到节点已带评估结果（进程死在评估之后、事件之前）只重报状态与事件、带 `rebuilt_from_node: true` 且**不调评估器**（实测 `test_a_deferred_candidate_the_evaluator_answered_is_not_charged_twice`：`adapter._call_count` 不变、状态回到 DONE、队列清空），flush 过的项从队列剪掉（实测 `test_a_deferred_candidate_that_was_never_evaluated_is_evaluated`：第二次 flush 不再花一次评估），`jev_deferred_evaluated` 加 `island_id`（缺它恢复时分不清"只筛过"与"已评估"，会让同一候选重评一次并重复加分）。报告：`rebuild_run_report(store, id, art_dir)` 全程只读库（`Store(..., read_only=True)`），导出 `run_summary.json/tree.json/events.jsonl/programs/` 与失败节点的 `logs/`，成本取 `get_cost_rollup` 而非内存计数，并显式写 `rebuilt_from_store: true` 以免和活运行的账混淆，实测 `test_a_report_is_rebuilt_from_the_database_without_another_evaluation`（`adapter._call_count` 前后相等，节点数/事件数不变）；`--report-only` 走这条路（顺带修掉 `get_base_artifacts_dir` 返回 None 时的 `TypeError: None / str`，产物目录改为与运行同一规则 `(artifacts or runs)/ID`）、不存在的 id 明确报错（`test_a_rebuild_refuses_an_id_that_does_not_exist`、`::test_report_only_writes_a_missing_report_from_the_database`、`::test_the_copy_and_rebuild_switches_name_a_run_that_has_to_exist`）。归属：`_take_run_claim()`＋`run()` 的 `finally: _release_run_claim()`；别的活进程持有 → `RunBusy`（消息含 holder/pid，且不写 `run_interrupted`，实测 `test_a_live_claim_from_another_process_blocks_the_resume`）；死持有者先写 `run_interrupted`（含 `previous_holder` 与 `iterations_done`）再接手（`::test_a_dead_claim_is_recorded_as_an_interrupted_attempt`）；同进程第二个引擎是重启不是竞争（`::test_two_engines_in_one_process_are_a_restart_not_a_competing_run`）；pid 判不了不永久占库（`::test_an_unknowable_pid_does_not_hold_a_run_forever`）；正常结束不留声明（`::test_a_finished_run_leaves_no_claim`）。新事件 `run_interrupted/run_resumed/run_resume_refused` 入 `webapi/catalog.py::EVENT_TYPES` 并归既有 `run_state` 粗类（仍 12 类，未新增第 13 类），`web/openapi/engine-catalog.json` 已重导。范围说明（如实保留，不写成已完成）：①"标记 interrupted"落在事件与 `run_resumed` 载荷上，`IslandStatus` **未**新增 `interrupted` 值（会牵动 schema/契约/前端分类，是否要一个岛级中断态由 D4.4 的"岛 B 暂停时进程退出"用例再定），硬杀后 experiment 行状态仍是 running，运行状态展示归 webapi registry；②串行评估（`eval_concurrency>1` 启动即拒）意味着没有跨进程在途 worker 可核实，恢复不认领上一进程遗留的评估子进程，只保证不会再有第二个写库者；③墙钟预算 `max_wall_hours` 每进程重新计时，恢复不接回已耗墙钟；④评估侧计数（`valid_count/invalid_count/jev_calls/evaluations_saved/analysis_*`）不从库重建，只有 token 预算与知识估计重建，引擎运行级 null 预算续跑未实测（T09 仍是判定函数级）；⑤幂等重放仍未实现（沿用 D4.2 的"不自动重放，恢复后由调度器按正常策略继续下一次尝试"）；⑥`--artifacts-dir` 与 `--runs-dir` 分家的旧运行用 `--resume-from` 时只搬库（恢复所需状态都在库里），产物在新家重新写出；⑦webapi 的 resume 端点仍走原地 `--resume`，未接 `--resume-from`/`--report-only`，属 D6.3/S6；⑧`discover run|factors` 因为同样调用 `initialize(resume_id=…)`，现在会拒绝把发现结果写进一个任务身份不同的运行——这是本轮新增的行为，不是既有能力的回归；⑨Windows 上 pid 被复用时 `pid_alive` 可能把已死持有者判成活，代价是多拒一次启动（不会双写）。全量门：`.venv/Scripts/python.exe -m pytest tests/ -q` → **1666 passed / 0 failed**（856.07s，`/tmp/s4_full1.log`）＝S3 门 1610 ＋ D4.1 9 ＋ D4.2 8 ＋ D4.3 39，S3 的 1610 项无一回归。首跑为 1 failed / 1665 passed（887.18s）：`tests/test_discovery_preflight_crash_fix.py::test_discover_factors_writes_error_txt_on_failure`——该用例的 CLI 调用没有打 `create_benchmark_adapter` 补丁，attach 到运行库时用的是真实 HDD 适配器，任务/初始代码指纹与该 mock 运行不符，被新加的拒绝路径在先（断言看到的 error.txt 因此是拒绝消息而不是 `synthetic boom`），属测试环境错而非实现缺陷，补上同一 adapter 的补丁后 `pytest tests/test_discovery_preflight_crash_fix.py tests/test_cli_discover.py -q` → 12 passed。

#### D4.4 故障注入验证

在临时目录使用可控 fake LLM/evaluator，分别在下列点中断并恢复，记录中断前后计数对比：

| 中断点 | 恢复后期望 | 实测（中断前 → 恢复后，提交 971f38e） |
|---|---|---|
| summary 已落库但未投递 | 恰有一条目标投递 | `tests/test_island_fault_injection.py::test_a_summary_written_but_never_offered_is_offered_once`：投递行 0 → 每目标恰 1 条（`{(sum,b,offered),(sum,c,offered)}`），摘要仍 1 条（去重不重发），再跑一轮 delivered=0 且行数仍 2；`::test_the_repair_only_offers_siblings_that_can_still_act` 只给仍活动岛补投；`::test_a_resumed_round_offers_what_the_interrupted_round_never_sent` 走引擎恢复路径 |
| application 已记但候选未评估 | 恢复/重试状态明确，不能宣称 evaluated | `::test_an_application_recorded_before_the_evaluator_stays_unfinished`：中断时 1 行 `evaluation_id==""`/`score is None` 且候选无评估结果、状态非 DONE/INVALID → 恢复后该行仍为空（不谎称已评估），未完成行只重挂回本岛（B 拿到 `{child:[app]}`，A 拿到 `{}`）→ 重试评估后 `evaluation_id==child.id`、`score==本次评估器返回值` 且 ≠ 来源分，评估器调用数 +1 |
| 评估完成但报告未生成 | 不再调用 evaluator，只重建报告 | `::test_a_run_that_lost_its_report_rebuilds_it_without_paying_again`：产物目录不存在 → 重建后 `adapter._call_count` 不变、`llm_call` 行数不变、事件数不变，节点数/有效数/最佳分/总 token 与库内一致且 `rebuilt_from_store: true`；第二次重建结果与文件内容逐字节相同 |
| 岛 B 暂停时进程退出 | A/C 可继续，B 不被无意重置为 running | `::test_a_paused_island_comes_back_paused_with_its_own_counters`：`paused`/attempts/best_score/stop_reason 四项跨重启不变，`runnable=False`，六次轮转只出 A/C，A/C 各跑一次尝试后 B 仍是 paused；`::test_a_paused_island_is_not_sent_work_by_its_siblings`：新最佳摘要的投递目标只含 C |
| 账本写完但终端输出中断 | 汇总不重复追加相同 request_id | `::test_the_interrupted_run_committed_one_row_per_request`：一个进程内 row id 与 request_id 都不重复；`::test_a_resume_replays_the_committed_ledger_and_appends_nothing`：`run_resumed` 恰 1 条且 `cost_rows==` 中断前已提交行数、`total_tokens==` 中断前 rollup，恢复后行数只增不改（旧行逐字段等值）、rollup 恒等式与 `metrics.total_tokens` 相符，`cost_ledger` 的 `(experiment_id, seq)` 无重复且新 seq 全部大于旧最大值 |

验收：五种中断点各有中断前后计数对比；其中四种的修复逻辑做过反向 mutation（去掉即对应用例失败，见 C 段“关掉修复”三行＋D4.4 缺陷行），第五种“评估完成未生成报告”只由 `adapter._call_count` 前后相等的断言钉住、未做 mutation，留作 S7 补测。

落地说明（2026-10-08，提交 971f38e）：唯一的产品侧改动在 `cloud/exchange.py`——`checkpoint()` 的文档由“publish then deliver”改为“repair, publish, then deliver”，`try` 内第一条语句调用新增的 `backfill_deliveries(source, target_islands)`，它扫本岛已落库的摘要，对**当前仍可动作**的目标补写缺失的投递行并记 `exchange_delivery_backfilled` 事件。之所以必须补：摘要写入与投递是两次 insert，进程可以死在两者之间；而 `_new_summary()` 的 `content_hash` 去重让下一轮不再重发同一条结论（命中的分支只并证据、不再返回摘要），`_deliver()` 又只处理本轮新产出的摘要——缺了补投，那条结论永久无人可读。补投靠“查库而不是记内存”定位缺口，`create_delivery()` 的 `INSERT OR IGNORE` 与 `UNIQUE(summary_id, target_island_id)` 使其天然幂等，因此补投不会变成重播，`_exchange_targets()` 只给 PENDING/RUNNING 的兄弟岛，停下的岛也不会被硬塞任务。新事件入 `webapi/catalog.py::EVENT_TYPES` 并归既有 `insight` 粗类（仍 12 类），`web/openapi/engine-catalog.json` 重导、`pnpm --dir web generate:api` 无 diff。其余四点复用 D4.3 已落地的机制（`_pending_summary_applications()`、`_flush_deferred()` 的 `rebuilt_from_node` 分支、`rebuild_run_report()`、`_prepare_runtime()` 只归一化 PENDING/RUNNING、`init_ledger(start_seq=max_cost_seq)`），本轮把它们写成“中断点级”用例；反向 mutation 只覆盖其中四处生产逻辑（去掉补投、application 不重挂、PAUSED 被归一化、`start_seq=0`，逐条结果见 C 段），报告重建一点未做 mutation（见范围⑦）。范围说明（如实保留）：①中断在测试里用“评估器抛异常使循环就地终止”表达，不是真杀进程，因此跨进程遗留的评估子进程仍无人认领（沿用 D4.3 范围②，串行评估下不存在在途 worker）；②岛级中断态仍未引入，`IslandStatus` 保持四值——D4.4 的用例证明“暂停的岛恢复后仍是暂停”不需要中断态即可成立，硬杀时岛状态由 `run_interrupted` 事件表达，是否新增岛级中断态留待 S6 的 webapi 运行状态展示一并决策；③`request_id` 的唯一性只在单进程内成立（客户端自己的计数，恢复后新客户端从 1 重新编号），因此行主键 `llm_call.id` 才是账本的去重键，`cost_ledger` 靠 `(experiment_id, seq)`；④账本重放的“不重复”靠 `run()` 先重置 `RunMetrics` 再单次重放保证，`_restore_run_cost()` 自身对同一 metrics 对象不是幂等的，恢复路径没有第二次调用点；⑤`CostLedger.totals()` 仍只汇总本进程内存中的记录，恢复后 `run_summary.json` 里的 `cost_ledger_totals` 不含上一进程的记录（耐久事实在 `cost_ledger` 行与 `get_cost_rollup()` 里，重建报告走后者），要接回需从行重建，属 S6/S7 待办；⑥真实运行目录上的断电/强杀实测属 S8/S9，本轮只有离线证据；⑦“评估完成但报告未生成”一点没有做反向 mutation——断言是 `adapter._call_count` 前后相等，它由 D4.3 的 `rebuild_run_report()` 全程只读库（`Store(..., read_only=True)`）保证，本轮只补了计数对比，把该机制改成会重评的版本以验证断言确实会失败留作 S7。全量门：`pytest tests/ -q` → **1675 passed / 0 failed**（1067.28s，`/tmp/s4_full2.log`）＝D4.3 收尾 1666 ＋ D4.4 的 9；D4 回归集合（13 文件＋`tests/webapi`）574 passed / 0 failed（89.86s）；`check_web_contracts.py` 与 `pnpm --dir web typecheck` 退出码 0，`pnpm --dir web test` → `Tests 1 failed | 660 passed | 3 skipped (664)`，该项为既有失败（见 F 段）。

### D5：让 Skill 能指导真实操作（对应 S5）

#### D5.1 先写用户入口，再填真实命令

- [x] 建立 `skill/fe-island-evolution/SKILL.md`，前置元数据描述“通过任务适配器运行和管理多岛演化”。
- [x] 输入列出 task_dir、任务主指标/方向、配置、数据引用、runs/artifacts 路径、可选 resume ID；不要求用户提供 HDD 专属字段。**方向这一项的实测结论与需求措辞不同**：任务契约里根本没有方向字段（`EvalResult` 只带 `combined_score` 一个标量，引擎固定按越大越好处理），所以入口写的是“方向必须由适配器在 `evaluate()` 内转换”，而不是向用户要一个方向参数；`references/configuration.md` 的“指标方向”一节给出转换口径。
- [x] 指明先读任务契约，再检查配置，不能因为示例是 HDD 就把所有任务当硬盘。步骤 1 读 `problem.md`/`evaluator.py`，步骤 2 强制 `fe doctor --config-file` 打印实际岛环；两条都是已跑过的命令而非建议。
- [x] 输入缺失且已有上下文可推断时使用已知值并记录；缺关键任务适配器时给具体错误，不生成一个虚构 adapter。入口原文照抄两条真实错误：`Error: unknown task.adapter 'nosuchtask'; aliases: ['alibaba_ssd', 'backblaze', 'famou', 'hdd', 'smartmem'] or 'module:Class'` 与 `Error: missing required files: ['prompt.md']`（本机实跑得到，别名清单来自 `src/faultevolve/tasks/registry.py` 的 `ADAPTER_ALIASES`）。

#### D5.2 需要交付的参考和辅助文件

| 建议文件 | 具体内容 |
|---|---|
| `references/configuration.md` | 默认三岛、配置字段、指标方向、停止和无成本上限语义 |
| `references/exchange.md` | 摘要字段、投递/采用解释、负结果边界 |
| `references/hdd-server.md` | 本项目主机与路径、只读数据、新目录部署、模型配置来源 |
| `references/recovery.md` | 新运行恢复、旧运行复制、检查点、失败后的继续方式 |
| `scripts/` 内必要辅助脚本 | 预检/报告/经验 Skill 导出；只添加实际用到的脚本 |

- [x] 每个参考文件在 SKILL.md 对应步骤可找到；脚本帮助、参数和退出码与文档一致。由 `tests/test_island_skill.py` 检查：四个参考文件都从入口可达、所有相对链接落地存在、fenced 命令里出现的 `fe` 参数必须是 `cli.py` 真正声明的选项、导出脚本参数必须是它自己的 argparse 声明、脚本退出码与文档一致（实测只有 0 与 2）。
- [x] 不依赖只有当前聊天才知道的信息：如配置路径、任务目录或如何找结果。配置来源写成“`--config-file` 优先，否则 `<task_dir>/evolve.yaml`，两者不合并”，产物路径按 `<artifacts>/<exp_id>/` 说明，服务器主机事实全部集中到 `references/hdd-server.md` 并标注来源是仓库 README 的已核实段落。

#### D5.3 经验 Skill 导出

- [x] 输出到新 run 的 `skills/` 子目录，禁止直接覆盖项目 Skill。默认输出目录就是 `run_summary.json` 同级的 `skills/`；`--out-dir` 落在项目 `skill/` 之内直接退出码 2（`test_the_exporter_refuses_to_write_into_the_project_skill_dir` 实测）。
- [x] 每条规则包含：适用任务/数据条件、操作、证据 run/node/summary ID、观察结果、失败条件、复验命令。离线 toy 运行 `2ab57008` 导出 5 条，逐条含 run/summary/node/application ID 与评估器读数；复验命令是可直接执行的 `fe evolve local … --report-only --resume <id>`。
- [x] 无正面可泛化结果时可交付“操作与避错 Skill 草稿”，明确局限；不能把一次失败写成普遍禁止。用一个 `exchange_interval: 10` 的 3 轮 toy 运行实测“零摘要”分支：草稿写“未得到可泛化规则”，仍如实列出各岛尝试/有效评估数与交换计数，并以“单凭一次运行无法区分‘策略无效’与‘预算太小’，因此不据此给出避错规则”收尾（`test_a_run_that_exchanged_nothing_delivers_facts_instead_of_rules`）。
- [x] 保留机器可读 evidence index，正文只引用脱敏证据，不嵌入原始数据或候选完整源码。`evidence_index.json`（`schema: fe-experience-evidence/1`）带 `run_identity` 指纹、岛画像、报告三块快照、`rule_count` 与 `sanitization` 声明；草稿正文不含代码围栏（断言 `"```" not in draft`）。

#### D5.4 实际验收 Skill

- [x] 在临时输出目录按 Skill 运行 toy adapter，不硬编码 SMART/ROS；验证字段缺失时错误明确。`tests/test_island_skill_walkthrough.py` 用 `tests/fixtures/toy_task` ＋ `task.adapter: famou` 在 `tmp_path` 下走完演练→报告三块→只读重建→导出；配置文本里 `hdd`/`smart`/`ros`/`disk` 一个都不出现（`test_the_rehearsal_needs_no_hdd_specific_input`）。
- [x] 对新增辅助脚本运行帮助和实际最小用例；结构校验工具可用则运行，不能只凭“格式看起来对”。`export_experience_skill.py --help` 退出码 0；实跑两次（5 条规则／0 条规则）退出码均 0。**仓库内没有 Skill 结构校验工具**（`scripts/` 只有 web 契约与 fixture 类脚本，逐条确认过），因此结构校验以测试形式实现并可重复执行，而不是声称跑过某个不存在的校验器。
- [x] 记录一次从“读 Skill”到“找到结果”的完整步骤日志，后续服务器实跑继续沿用该入口。见本阶段 A0 的 D5 各行与 C 段两条新测试记录；`references/hdd-server.md` 把同一入口接到服务器（S8/S9 未执行，已在该文件与本阶段表内如实标注）。

**D5 范围内本轮不做**：`fe-evolve-manager` 之外的旧 Skill 文案清理；`--resume-from`/`--report-only` 的 webapi 与界面接入（属 D6.3/S6）；经验草稿合入通用 Skill（需求要求第二次运行复现，本轮无第二次真实运行）。

### D6：服务器真实运行目录到 WebUI 的完整链路（对应 S6）

#### D6.1 先查清真实产物布局

- [x] 只在已授权 runs 根查看目录结构，抽取少量真实 run 的文件名/元数据，识别数据库与 artifacts 是否同目录；不扫描数据根。（本阶段只碰两种已授权根：仓库内 `tests/fixtures/runs/` 与 `scripts/e2e_serve.py` 每轮新建的 scratch；服务器真实根未触碰，属 S8。查清的布局结论：`fe.db` 与报告可以同目录，也可以分居 `--runs-dir`／`--artifacts-dir`，两层都要支持）
- [x] 分别识别普通 evolve、autotune、discovery/replay 类型；非树型运行仍应能显示类型/状态/已有报告，不能伪造一棵树。（`test_a_database_only_run_is_listed_and_admits_it_has_no_tree`：只有库、没有树的运行照样入列，并如实说明没有树；历史单树与三岛两种形态分别由 `test_a_single_tree_run_says_the_ring_was_never_recorded` 与 `test_the_api_returns_the_islands_the_engine_wrote` 覆盖）
- [x] 为每种布局记录”运行 ID 在哪里、结果文件是什么、缺文件时如何处理”。（记录落在 `run_discovery.py` 的模块注释与常量上：目录名即 run id；`RUN_MARKERS` 九项命中任一项才算 run，`_classify()` 按标记组合给出 `evolve`/`discovery`/`autotune`/`database` 类型；缺树、缺报告分别由回放层的 `missing` 状态陈述而不是靠猜测。这些约定由 `test_run_discovery.py` 与 `tests/webapi/test_replay_*` 的用例名逐条对应）
- [x] 当前 `paths.list_run_ids` 与 `artifacts_for` 若假设单层目录，一起调整；不能列表显示出来但详情找错位置。（两者都改到与 `run_discovery` 同一套位置解析：列表里出现过的 run，详情用同一位置约定打开；`test_split_run_and_artifact_roots_read_as_one_run` 与 `test_the_bare_id_names_the_first_hit_and_the_suffix_the_second` 钉住”列表即能打开”）

#### D6.2 建立可审计真实运行索引

- [x] 新索引至少保存 external_id、source_root、source_relative_path、原 run_id、类型、origin(real/fixture/unknown)、可读状态和失败原因。（`RunLocation` 就带这些字段；origin 值域是 `real`/`fixture`/`unverified`——“unknown” 落在 `unverified` 这个名字上：未证实的一律这么标，不冒充 real，也不静默丢弃）
- [x] 同一 run_id 出现在不同历史目录时生成稳定外部 ID，保留原 ID；不能静默覆盖。（`_external_id(run_id, relative_path)` 取相对路径的 `sha256[:8]` 作后缀，重启后同一布局得到同一 id，原 run id 留在 `RunLocation.run_id`；`test_two_complete_copies_of_a_run_id_are_not_merged` 与 `test_the_bare_id_names_the_first_hit_and_the_suffix_the_second` 钉住两条都可访问、裸 id 命中第一个并给出第二个的后缀名）
- [x] 限制扫描根、深度和产物文件类型，避免软链循环；扫描错误写 manifest，不能整个列表 500。（深度默认 4（`DEFAULT_MAX_DEPTH`）、总访问上限 20 000、错误清单封顶 200 条且把封顶本身报出来；`test_the_depth_limit_is_a_real_limit`、`test_a_symbolic_link_is_recorded_and_never_descended`、`test_the_error_manifest_caps_itself`、`test_an_unreadable_part_of_the_volume_is_reported_and_the_rest_still_lists`）
- [x] 明确 fixture 标记一律排除产品结果；旧真实 run 没有新标记时依据原数据库/评估记录核实，无法核实的进入待核实清单。（fixture 根下的目录从产品清单排除并计数；本服务自己启动过的 run 依据登记表判为 real；其余进 `unverified` 并附理由。三者的用例：`test_a_fixture_root_leaves_the_product_listing`、`test_a_run_this_service_started_is_reported_real`、`test_a_directory_holding_no_run_artifact_is_not_a_run`）
- [x] 报告四个数量：扫描到、真实展示、fixture 排除、待核实/损坏；数量关系可对账。（`ScanOutcome` 的 `scanned`／`listed`／`excluded_fixtures`／`paired` 满足 `scanned == len(locations) + paired` 与 `len(locations) == listed + excluded_fixtures`，由 `test_the_provenance_counts_reconcile` 校验；`GET /api/runs/provenance` 原样发布）
- [x] 新索引写自己的 registry，旧 DB 以只读方式打开；产品”启动新运行”的写目录仅指向本轮新目录。（D6.2 的扫描本身不开库、不写文件（模块注释第 4 段：scan 只看名字）；索引与来源清单走独立的 provenance 端点；启动路径的写目录来自 `--runs-dir`/`--artifacts-dir` 参数，E2E 启动器每轮新建 scratch 目录）

#### D6.3 API 逐项接入

- [x] 列表 API 返回所有可识别真实运行，支持旧单岛和不同 run 类型；不得由 demo_run_ids 控制可见性。（列表来自扫描结果；`demo_run_ids` 默认 `[]` 且产品路径不再有按该字段的过滤——`web/src/app/App.test.tsx` 与 `e2e_serve.py`（同为空列表）在"字段为空"的前提下断言列表仍显示两条运行）
- [x] 详情 API 返回 islands、global_best、停止原因、来源与缺失状态。（契约 1.12.0 的 `RunIslandsResponse` 分组；`tests/webapi/test_replay_islands.py` 16 项覆盖"分数取本岛树内最优""四类交换计数分开""尝试数与全局对账""按岛成本平衡""单树运行 state=missing 且不编岛""字段类型错时留 null 不强制转换"）
- [x] 树 API 明确节点 island_id 和普通树边/摘要交换边；旧运行补出单岛展示层，不改源文件。（契约 1.13.0 加 `TreeNodeDTO.island_id` 与 `summary_cross` 边类型；`tests/webapi/test_replay_tree_edges.py`、`test_replay_exchange.py::test_tree_nodes_carry_their_island`、`::test_graft_edges_cross_islands_and_are_not_parenthood`；旧运行按 `island_id=""`（`LEGACY_ISLAND`）单树展示；回放一律走 `webapi/sqlite_ro.py::connect_ro` 的 `mode=ro` 连接（该模块注释写明"回放绝不碰 `Store`"，因为 `Store.__init__` 会建目录、跑 DDL、改 WAL 模式，指向已提交的 fixture 会把 fixture 重写））
- [x] 摘要详情 API 返回摘要、证据、投递/采用记录；不提供越权的源文件路径读取能力。（`/api/runs/{id}/summaries` 与 `/summaries/{sid}`：`test_the_summary_detail_carries_evidence_not_paths`、`test_an_unknown_summary_is_a_structured_missing`、`test_no_exchange_response_leaks_a_filesystem_path`）
- [x] 对错误/未知来源给结构化状态，不用零值补齐不存在的指标。（`state: available|missing|invalid` 三态：`test_a_malformed_islands_block_is_invalid_not_zeroed`、`test_an_empty_ring_is_reported_as_invalid`、`test_exchange_without_islands_is_invalid_rather_than_a_half_shown_ring`、`test_absent_counters_stay_null`、`test_a_run_without_a_summary_has_no_islands_group`）
- [x] 同步 OpenAPI 和生成客户端，检查前端没有手写另一套不一致类型。（三次契约变更都重导了 `web/openapi/*` 与 `web/src/generated/api/*`；`tests/webapi/test_engine_catalog.py` 21 项里含 SSE 事件名与前端订阅表的两向一致（`test_all_known_event_names_are_subscribed`／`test_known_event_names_invent_nothing`），前端侧由 `iteration-logic.test.ts` 的穷举断言确保每个订阅事件都有中文标签；未手工改过 `src/generated/`）

#### D6.4 前端逐页完成

| 页面 | 按顺序完成的改动 | 检查方式 |
|---|---|---|
| OverviewPage | 去固定 showcase 过滤，展示真实列表与空态 | 混合来源测试目录只展示真实项 |
| RunWorkbenchPage | 显示三个岛的状态、策略、尝试数、局部最优 | 数字与 API 响应逐项相同 |
| RunTreePage | 先能切换岛，再展示跨岛摘要关联 | 三个根可分别访问，交换边不当 parent |
| RunTimelinePage | 展示交换/采用/拒绝/中断事件 | 同一事件刷新不重复 |
| RunResultsPage | 全局最优与各岛最优，缺失值有状态 | 同一候选指标不被拼接 |
| RunKnowledgePage | 区分知识卡、运行经验与外岛摘要 | 单次观察不显示 CONFIRMED |

- [x] 为历史单岛保持原入口；没有树的真实 discovery run 显示报告视图/不适用提示。（历史单树仍在通用页面回放：`hdd_mvp_showcase_c89e2a01` 的 21 节点树、显著性四档、双亲/最优/修复链在视觉回归里逐条断言；无树运行由 `test_a_database_only_run_is_listed_and_admits_it_has_no_tree` 在 API 层如实说明）
- [x] 截图至少覆盖三岛概览、岛树、交换详情、历史单树和空态；页面不能引用 fixture 的固定节点数/分数。（截图目录 `web/test-results/visual/<视口>/<主题>/`，3 视口 × 2 主题 × 10 画面共 60 张，本轮已逐张看过其中五类：`islands-overview`（三张岛卡＋六计数＋"全局最优 落在岛 a"）、`island-tree`（默认并列三岛、21 节点全在视口内）、`exchange-detail`（四计数分开＋投递与采用＋12 条采用候选）、`tree`（历史单树 5 层全展开）、`empty-state`（知识页空态说明"是真空、不是读取失败"）。页面数字全部来自 API，fixture 固定的 7/7/7、22.81 只出现在测试断言里）

#### D6.5 正常入口和测试入口隔离

- [x] 保留 e2e_serve 作为测试启动器，不删除依赖 fixture 的单测。（`scripts/e2e_serve.py` 仍在，且收紧了：曾整目录复制 fixture 根，会把手工调试留下的目录一起带进测试；现在按四个具名 run 逐个 `copytree`，`pnpm test:e2e` 的 76 项全部靠它拉起后端）
- [x] 正常服务配置 `demo_run_ids=[]`，同时后端真实来源过滤；仅清空该字段不足以防止 fixture 通过目录扫描出现。（两侧都做了：产品默认 `WebSettings.demo_run_ids = []`；fixture 排除靠 `run_discovery` 的来源判定（fixture 根 → `excluded_fixtures` 并计数），不靠该字段。E2E 启动器同样用空值，于是"空字段下列表照常显示运行"被 76 项 E2E 持续验证）
- [x] 测试 mock 请求只在测试构建/用例中使用，生产 bundle 不自动回退到 mock。（展示数据的唯一来源是 `src/generated/api` 对 `/api/*` 的请求，代码里没有"请求失败就换本地假数据"的分支——grep `fallback|fixture|mock` 后逐个确认：`mock` 全是 intake 的 `mockLlm` 运行参数与注释，`fixture` 全是注释里的说明文字。E2E 里启动的运行靠用例勾选 `data-mock-llm="true"`，那是后端参数，不是前端数据源；D6.5 删掉 showcase 页面后，前端也不再有硬编码的运行数据）
- [x] 路径白名单只覆盖必要产物根；禁止借下载接口读取数据、holdout、环境文件或任意数据库。（`tests/webapi/test_path_security.py` 19 项（run/node/artifact 越权路径、下载白名单）＋`test_no_holdout_exposure.py` 保持通过；新增的摘要与来源清单接口不返回路径，见 D6.3 两条）

### D7：按用例执行测试，而非只跑一个总命令（对应 S7）

#### D7.1 建立离线用例清单

为下列用例编写可执行测试；名称可调整，但回填时保留 T 编号与实际测试函数对应。

| 编号 | 输入/操作 | 必须观察到的结果 |
|---|---|---|
| T01 | 新任务未传岛配置 | 恰好三岛且 profile 不同 |
| T02 | 显式一岛、旧 run 恢复 | 保持单岛，不新增根 |
| T03 | 重复岛 ID/负间隔 | 启动前失败，无半成品运行 |
| T04 | 三岛各根及子节点 | 每树只加载自己的节点 |
| T05 | A 子节点指定 B parent | 拒绝，不污染两树 |
| T06 | 更新 A 分数和 visits | B/C 统计逐项不变 |
| T07 | B 暂停 | A/C 继续，B 不被饿死问题掩盖为完成 |
| T08 | 连续无效生成 | attempts 递增并到上限结束 |
| T09 | null 预算与有限预算 | 前者不被隐含成本上限停掉，后者仍有效 |
| T10 | 同一正面摘要重复投递 | 目标 delivery 只有一条 |
| T11 | 负面摘要含原始敏感片段 | 片段不进入共享消息，分类仍可理解 |
| T12 | 外岛代码唯一标记 | 接收岛提示和代码读取调用均无外岛源码 |
| T13 | 摘要交叉候选未评估 | 无成绩，不能继承来源得分 |
| T14 | 不兼容任务摘要 | 拒绝并记录理由 |
| T15 | 知识卡注入 | 实际候选 provenance 有 card_id |
| T16 | 知识提炼解析失败 | 候选真实分不变，错误如实记录 |
| T17 | 中断于三种关键边界 | 恢复不重复完成事件/成本/评估 |
| T18 | 旧 SQLite 读取/恢复 | 原件哈希不变，写入只发生在新副本 |
| T19 | 两目录 run_id 相同 | 两项均可访问，无覆盖 |
| T20 | 真实/fixture/未知混合 | 真实展示、fixture 排除、未知可解释 |
| T21 | 空根/损坏产物 | 空态或错误状态，API 不整体崩溃 |
| T22 | 历史非树型真实运行 | 报告可见，不伪造树 |
| T23 | API 越权路径请求 | 拒绝，不能读数据/环境文件 |
| T24 | 通用 toy adapter 按 Skill 跑 | 不要求 HDD 字段，产物可定位 |
| T25 | 三岛/单岛/交换页 | UI 数字与对应真实 API 结构一致 |
| T26 | 摘要采用数汇总 | offered/accepted/applied/evaluated 不混计 |

#### D7.2 保存可读测试日志

- [x] 每条命令保存工作目录、解释器/包管理器版本、退出码、日志路径；用运行实际输出填写，不能从测试文件数量估算通过数。（Python 3.12.4／node v24.13.0／pnpm 10.33.0 与工作目录、日期见 `C:\tmp\s7\gates\versions_s7.log`；针对性测试的命令行与解释器版本写在 `pytest_targeted_s7.txt` 首部；S7 追加行逐条给出退出码与日志路径，全部数字取自运行输出）
- [x] 先跑新改模块针对性测试，失败则只修相关问题；通过后跑 Python 全量与前端全量。（先 86 项针对性切片（19:29 首跑 35.53s／19:36 复录 39.32s，两次均 86 passed）→ 再前端链与 E2E（19:24–19:31 一过；因回填期补落标签修正，最终树 123ac28 上整套重跑）→ 最后全量门 19:39 在冻结树上 **1799 passed**；开发期没有出现“为修测试而改实现”的失败，反向 mutation 的转红属预期并已留档）
- [x] 前端命令按顺序执行并独立记录：sync:contracts → check:contracts → typecheck → test → lint → build → test:e2e。（七步在终态树 `123ac28` 按序复跑，退出码全 0；其中第 4/6/7 步一度借管道取数使 `EXIT=` 取自 tail，随后以不经管道的复核补记真实退出码，日志内已注明该更正；`pnpm sync:contracts` 直跑 9009 为已知的裸 `python` 问题）
- [x] E2E 使用自己的临时运行根；服务器真实实例只做只读页面验收，不用破坏性测试污染历史运行。（本轮两次 E2E 的日志首行均为 `runs_root=…\Temp\fe_e2e_h60hmlgm` 一类的临时目录，web 4318／API 8011 由 Playwright 自拉自停；本轮未接触任何服务器实例——真实页面的只读验收属 S8/S9）
- [x] 有原有失败则在改前版本同环境复现，保存两份证据；不能未经比较写“历史问题”。（**不适用**：S7 起点为 S6 全绿树（1796 passed / 0 failed，`C:\tmp\s6\gates\pytest_s6_full.txt`），本轮全量 1799/0 亦无失败，故没有“原有失败”需要复现；更早的既有红——`App.test.tsx` 的 SmartMem 用例——已在 S6 于门内修复并复验，不存在仍带红的“历史问题”）

#### D7.3 提交前检查门

- [x] 检查 `git diff --check` 和受保护路径差异；确认新增文件也纳入检查。（`git diff --check` 退出码 0；受保护路径对照 S6 门提交 `83535ef` 为空；本轮无新增文件，8 个改动文件全部在检查范围内；日志 `C:\tmp\s7\gates\diff_checks_s7.log`）
- [x] 查看 staged diff，确保没有 .env、密钥、数据库、原始数据、候选大产物或服务器日志。（逐次提交前查看 staged：`d26c532` 六个文件＋158/−1、`123ac28` 两个文件＋5/−3；密钥/产物形状扫描无命中——唯二匹配是测试代码里的临时库名 `fe.db`；无 .env、无数据库文件、无大产物、无服务器日志）
- [x] 保存 D7 测试矩阵结果后提交；若后续 D8 修代码，重新运行受影响测试并更新 SHA，不能沿用旧 SHA 的通过声明。（矩阵与日志保存在 `C:\tmp\s7\gates\`（针对性 86／全量 1799／前端链与 E2E／四处 mutation／契约复跑 33／diff 检查），随后提交：`d26c532`（账本重放与三个用例）＋`123ac28`（停滞字段标签）；阶段门跑在 `83535ef`＋这两次提交内容构成的冻结树（工作树指纹 sha256 `9abb0241…`）上，提交后工作树与门树逐字一致（`git diff HEAD` 为空）。D8 若改代码，须以新 SHA 重跑受影响测试并更新本表）

### D8：服务器部署和真实预检，逐条执行（对应 S8）

#### D8.1 冻结待部署提交

- [x] 本地实现分支提交完毕，记录完整 SHA；工作区有未提交代码则不能声称服务器运行该提交。（`codex/three-island-real-runs` HEAD `7687df2c562cf2cca5258effffe225600cb60024`，`git status --short` 为空；manifest 记录 `code_status_porcelain: <clean>`）
- [x] 推送实现分支后读取远端 SHA，确认与本地一致。（`git ls-remote --heads origin` 的 `codex/three-island-real-runs` = `7687df2c…`，与本地一致；未推送 main）
- [x] 为预检选择唯一时间戳，记录计划代码目录和运行根，确认均不存在；存在则换新名字，不清空旧目录。（时间戳 `20261008-200410`；`/home/hcf/faultevolve/three_island_20261008-200410/` 部署前核实不存在后创建；旧代码目录 `/home/hcf/faultevolve/code` 未动（HEAD `dcd2283e…`））

#### D8.2 完整 bundle 传输

以下是可采用的命令形态，执行前确认分支已存在。`$bundlePath` 仅保存普通代码 bundle 路径，不含密钥。

```powershell
$bundlePath = Join-Path $env:TEMP ('faultevolve-three-island-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.bundle')
git bundle create $bundlePath codex/three-island-real-runs
git bundle verify $bundlePath
scp $bundlePath 3056-hcf-10.61.48.10:/tmp/
```

- [x] 每条命令单独检查退出码；传输失败不继续 clone。（`git bundle create`／`git bundle verify`／`scp` 各步退出码 0 后才继续；bundle 本地 sha256 与服务器端复算一致 `93469ba9c3de7427c54369cfa6885c32551b09a3143bd72610c8ad582b1d5c18`（61814410B））
- [x] 在服务器用 `git clone --branch codex/three-island-real-runs <传入bundle绝对路径> <新代码目录>` 创建新副本；占位符必须替换成已记录值。（`git clone --branch codex/three-island-real-runs /tmp/faultevolve-three-island-preflight.bundle $TM/code`；`$TM` = `/home/hcf/faultevolve/three_island_20261008-200410`）
- [x] 读取服务器 HEAD，与本地完整 SHA 一致；读取 status，检查无意外改动。（服务器 `git rev-parse HEAD` = `7687df2c562cf2cca5258effffe225600cb60024`；`git status --porcelain` 为空）
- [x] 不向 `/home/hcf/faultevolve/code` 合并本次开发代码，不处理它的既有数据软链和未跟踪文件。（旧目录只做只读核实；其 HEAD 仍为 `dcd2283e6396fc70f60678319a7549d404970bad`，`data` 软链原样未动）

#### D8.3 创建新产物布局

```text
three_island_<timestamp>/
  preflight/             真实预检运行根
  formal/                正式运行根
  deployment/            版本、环境与启动信息
  web/                   新 registry、索引、服务日志
  evidence/              测试与验收摘要，不含原始数据
```

- [x] 按实际 CLI 的 runs/artifacts 行为落盘，不能多套一层导致 API 找不到文件。两者根是否相同写入 deployment manifest。（`--runs-dir $TM/preflight/runs`、`--artifacts-dir $TM/preflight/artifacts` 两个根分家、均在 `three_island_<ts>/` 下；落盘结构 `<root>/<run_id>/{fe.db,…}` 与 `<root>/<run_id>/run_summary.json`，无多余层级；manifest 已记录两个根，S9 的 Web 索引按此配对）
- [x] 在新目录进行一个临时写入/删除探针验证权限，只操作自己创建的探针文件。（`$TM/evidence/.perm_probe_1791463033`：创建→列举→删除均成功，复查 `ls` 确认不存在；未触碰任何他人文件）
- [x] 建立独立环境并安装仓库声明依赖；记录 Python/依赖版本。不要随意升级服务器公共环境。（`$TM/code/.venv`（`python -m venv`）Python 3.13.11；`pip install -r requirements.txt`＋`pip install -e .`（日志 `pip_requirements.log`/`pip_editable.log`），冻结 48 包 `requirements_frozen_preflight.txt`；未动服务器公共 Python 与旧目录环境）

#### D8.4 数据和密钥检查

- [x] 指定现有 NAS HDD 路径；列举任务明确允许的 train/val 文件，逐一检查存在和可读；不使用全目录递归读取。（`HDD_BENCH_DATA_ROOT=/home/hcf/nas_hcf_data/faultevolve/data/hdd_mvp`；逐一列举六个允许文件（public 四＋eval_only 一＋meta.json）确认存在可读；`holdout` 从未被列举/读取/指纹）
- [x] 仅对允许文件和评估器计算指纹；报告保存文件名、大小、hash，不保存原始行。（六个文件指纹入 manifest：`meta.json b573de80…`（1761B）、`public/train_history.csv.gz f033f35b…`（10566701B）、`public/train_labels.csv 64b79841…`（1827880B）、`public/val_history.csv.gz 0b8e75b4…`（10164097B）、`public/val_index.csv 9abf34bc…`（1208459B）、`eval_only/val_labels.csv 60c1647a…`（953259B）；评估器 `cddfaaab…`、init `91744b4b…`；只存名称/大小/hash，无原始行）
- [x] 通过已有受控方式让进程获得所需环境变量，预检只输出布尔“已配置”；没有 key 时停在此处，不切 mock 继续冒充真跑。（`--env-file /home/hcf/faultevolve/.env`（600）；doctor 仅输出 `DASHSCOPE_API_KEY set`／`MIYANG_API_KEY set`／`FE_API_KEY not set` 等布尔；13 次真实 LLM 调用即“未切 mock”的直接证据）
- [x] 运行现有 doctor，保存脱敏输出；确认 adapter=hdd、评估器路径和数据根均正确。（17 项检查全 ✓ 除 `FE_API_KEY not set`（Web 专用）；`task files ok`、`adapter hdd -> HDDAdapter`、`data dir /home/hcf/nas_hcf_data/faultevolve/data/hdd_mvp/public (HDD_BENCH_DATA_ROOT=…)`、`islands on: 3 tree(s) [a:performance, b:miss_alert, c:efficiency], exchange every 1 attempts`；退出码 1 仅因未设的 FE_API_KEY）

#### D8.5 配置真实预检

- [x] 生成外置配置副本，不直接覆盖任务原 evolve.yaml；CLI 若不支持外置配置，先实现并测试 `--config` 或等效明确参数，不能在文档凭空使用它。（外置配置部署为 `$TM/deployment/preflight_evolve.yaml`（本机同源副本 sha256 `9be62749edf128a2bbe1b9852a9456d162f437c2b797b217a7dd9927bdb2400c`），未改 `benchmark/hdd_mvp/evolve.yaml`；`--config-file` 为 S5 已实现并测试的参数）
- [x] 预检设置 3 岛、每岛 2/global 6 attempts、交换间隔 1、并发 1、无 mock、无成本上限；禁用会提前停掉 2 次预检的停滞规则。（resolved：`max_iterations 6`（各岛 `max_attempts 2`）、islands 3、`exchange_interval 1`、`eval_concurrency 1`、无 mock；`min_iterations_before_stop 6`、`stall_valid_evals 15`/`min_valid_evals_before_stall 10` 使 2 次/岛的预检不会被停滞规则提前停掉；`max_tokens`/`max_wall_hours` 均 null 即无成本上限）
- [x] 保存最终解析配置和哈希；检查 LLM 模型、知识源、runs/artifacts 均不是 placeholder。（resolved 配置 `350df2ee9815022a97adbecf5beaa5a68ecca79797f4d0df1d2cbc48c61ee164`；`generate_model qwen3-coder-plus`、`reason_model qwen3-max`、`llm_base_url https://dashscope.aliyuncs.com/compatible-mode/v1`、`knowledge_dir knowledge`、runs/artifacts 为 `$TM/preflight/...` 实路径；judge `none`）
- [x] 从 `fe evolve local --help` 核实最终命令，填入实际命令表再执行。（A1「服务器预检启动」行；`--config-file/--env-file/-n/--runs-dir/--artifacts-dir/--run-id` 均为核实的实参数，无凭空参数；命令由会话记录逐字留存）

#### D8.6 启动和验收预检

- [x] 使用可靠的后台/终端管理方式启动，记录 PID、开始时间和日志；避免 SSH 断开导致运行丢失，不使用未验证的后台命令猜测成功。（`nohup .venv/bin/fe evolve local … > console_preflight.log 2>&1 &`，PID `1011543` 写入 `preflight/pid.txt`；开始 `preflight/started_at.txt`=`2026-10-08T20:07:36+08:00`、结束 `ended_at.txt`=`2026-10-08T20:32:08+08:00`；日志 `$TM/preflight/console_preflight.log`）
- [x] 观察 init 真实评估完成，三个根不同；第一轮三个岛各出现 attempt。（`init_evaluated` 事件 3 次（共享首评：实际评估器执行 1 次后两岛复用证据）；三根 `8a37fed9`/`ebe9997c`/`48c0ffdd` 互异；6 次 `attempt_started`＝三岛各 2）
- [x] 检查数据库/事件：真实 evaluator 调用数、LLM 调用、消息投递和来源；出现 mock 标记立即判失败。（实际 evaluator 执行 5 次（a 1／b 2／c 2，单次 1.87/102.01/207.54/321.0/58.23s）；13 次真实 LLM 调用（9 生成＋4 反思，全 outcome=ok）；10 投递全部 `accepted`/`applicable` 且来源可追溯；mock 痕迹扫描 event.type/payload_json/node.operator 三处全 0，judge `none`）
- [x] 预检结束保存退出码、stop_reason、各岛 attempts、真实评分和成本。（stop_reason 全局 `max_iterations`／各岛 `max_attempts`；attempts a 2／b 2／c 2；best 38.2067；tokens 76499、`cost_usd=null`/`cost_basis=unknown`；**退出码不可回取**——nohup 直起未包裹 `$?`，完成证据是控制台尾部＋DB `status=finished`，不伪填 0；S9 启动器改为 `sh -c '…; echo $? > exit_code.txt'`）
- [x] 至少确认摘要交换和采用链路；自然没有改进时可用明确标为基线的策略摘要验证，不伪称最佳改进；仍无法验证则先修流程再正式跑。（真实链路成立：`sum-3b709a88`（b `4c1635ca` 38.2067）→ `dlv-ce915ea4`（→c）→ `app-d1a808ad` → 候选 `f0cd9659` 评估 36.6104；另有 a 岛被 c 的 `sum-2c1ca67a` 选中；11 次采用全部 evaluated；两条负例（20.7573、29.3627）如实保留未替换岛最优）

失败处理：记录失败预检 ID，定位最早错误，修代码并重新提交、部署到新的版本目录；新建预检 run，不删除失败证据。不能在服务器临时修完而忘记回传代码。S8 实际未触发该流程：预检一次完成、无流程性失败需重试；引擎内自然失败（a 岛 2 个候选 invalid/smoke_rejected、b 岛 smoke_failed→smoke_fix_success、2 次 hypothesis_refuted）如实保留在失败证据中，未另建 run ID，也未在服务器上临时改代码。

### D9：正式实验与服务验收（对应 S9）

#### D9.1 正式启动前的五项核对

- [ ] 代码：预检通过的 SHA，后续有改动则相关检查已重跑。
- [ ] 数据：允许文件指纹与预检一致，受保护评估器未变。
- [ ] 配置：3 岛、每岛 50/global 150 attempts、间隔 5、并发 1、停滞和错误停止规则明确、无隐含 Token/墙钟 cap。
- [ ] 路径：formal 新运行目录，不复用 preflight，不碰历史路径。
- [ ] 证据：运行 manifest 和最终命令已保存，模型/配置/种子可以追溯。

#### D9.2 运行监控和故障分流

- [ ] 按候选结束事件监控，不高频轮询整个 NAS；记录周期快照中的三岛 attempts、valid、best、tokens、last_event_time。
- [ ] 单候选超时按原 evaluator 处理，计无效候选并继续；不扩大 900 秒基准限制来让候选通过。
- [ ] API/磁盘/环境问题按基础设施分类，连续阈值触发暂停；只读诊断，不伪造成算法负面知识。
- [ ] 得分低但流程正常则继续到协议终点；不得临时换种子、改分数或重新定义成功。
- [ ] 父进程异常先核实是否有存活 worker，再按 Skill 恢复；恢复操作和影响写日志。

#### D9.3 结束后先核对数据，再写总结

- [ ] 读取每岛有效候选列表，按任务主指标重新计算局部和全局最佳，核对 summary 指向同一节点。
- [ ] 统计 attempts 与候选/失败事件一致；共享 init 单列；Token 汇总与 request 账本一致。
- [ ] 抽查至少一条实际采用摘要，从源节点→summary→delivery→application→新节点评估能完整追踪；缺事件如实标记缺口。
- [ ] 导出候选代码、评估输出、账本、摘要事件、运行报告和经验 Skill；敏感产物仅留服务器。
- [ ] 结果表分别填“初始同次分”“本次最佳”“增量”；历史 38.14 不填入本次任何指标格。

#### D9.4 构建和启动服务器 WebUI

- [ ] 在新代码目录构建前端，确认产物由何种服务提供。`fe web serve` 若只提供 API，不能把 API 成功启动当作前端已经部署；复用仓库已有静态服务方式或新增明确的前端服务。
- [ ] 端口先检查占用；选择新端口，不停止未知旧服务。记录前端/API 各自绑定地址和进程。
- [ ] 通过实际 `FE_WEB_*` 配置或新增已验证参数指定新 registry 和只读历史运行根；`demo_run_ids` 为空，来源过滤开启。
- [ ] 原始 HDD 数据目录不加入通用下载 allow-list；服务密钥从环境读取。
- [ ] 优先回环监听，Windows 使用 `ssh -N -L <本机端口>:127.0.0.1:<服务器端口> 3056-hcf-10.61.48.10` 转发。将占位符替换后保存可复制命令；有 API 独立端口时配置同源代理或相应第二转发。

#### D9.5 用真实页面完成验收

| 操作 | 预期结果 | 保存证据 |
|---|---|---|
| 打开运行总览 | 已核实真实历史+新运行可见，无 showcase fixture | 列表截图、索引清单 |
| 打开本次正式运行 | 三岛状态、全局最佳与报告一致 | 页面/API响应摘要 |
| 分别打开三棵树 | 根不同，节点归属正确 | 三个岛视图 |
| 点击摘要交换事件 | 来源、正文、目标采用候选及结果可追踪 | 详情截图 |
| 打开历史单树 | legacy 单岛正确，无伪造另外两岛 | 页面截图 |
| 打开真实 discovery 运行 | 实际报告可见，树不适用说明清楚 | 页面截图 |
| 空运行根的隔离测试服务 | 空态，无自动 demo | 测试截图 |
| 损坏/未知来源记录 | 有明确状态和原因，无捏造指标 | 索引诊断 |

- [ ] 对账“所有运行”：扫描清单中每项都有展示、排除或待核实原因，不能只展示本次一个好看的运行。
- [ ] 填写准确访问地址、启动/停止方式和日志位置；停止命令只针对本次已记录 PID/服务，不按模糊进程名杀整个服务器。

### D10：结果回填和最终交接（对应 S10）

#### D10.1 三层结果都要写

- [ ] 工程结果：实现了哪些模块，提交 SHA 和测试结果；未实现项不能因计划写过就算完成。
- [ ] 实验结果：预检与正式运行分别记录，包括失败尝试；每个指标有产物来源。
- [ ] 产品结果：demo 归档远端 SHA、服务器地址、真实索引覆盖、三岛页面和 Skill 操作证据。

#### D10.2 文档回填顺序

1. 追加本文件逐步日志，填完测试 C、部署 B、真实结果 D、交换/Skill E。
2. 在本文件 F 写结论与未完成项，保留未知/未测说明。
3. 更新需求文档 §9 状态与证据链接，不把未完成改成已完成。
4. README 版本更新新增“实现/验证”记录，原规划记录保留其历史性质。
5. 查看 diff，确认没有改既有展示文档或宣传视频材料。

#### D10.3 PR 与 main 的状态必须区分

- [ ] 创建 PR 前记录最终测试对应代码 SHA；PR 描述包含真实问题、行为变化、测试、运行 ID、限制和结果链接。
- [ ] 若用 gh 创建 PR，正文写临时 UTF-8 文件，通过 `--body-file` 提交，避免引号和换行破坏正文。
- [ ] 将 PR 附加到当前 Codex 任务；记录链接后检查 CI。
- [ ] 合并依现有仓库流程完成；未合并时交接写“实现分支完成，main 待合并”，不能写 main 已去 demo。
- [ ] 合并后记录 main SHA；服务器运行 SHA 与 main 不同则列出差异。只有文档差异不需要重跑耗时实验，功能差异则针对性验证并记录。

#### D10.4 最终给用户的交付清单

- [ ] 需求文档、TODO 回填记录、README 版本条目。
- [ ] 通用 Skill 的路径与调用示例、经验 Skill 草稿的位置和适用范围。
- [ ] demo 归档分支、实现分支、PR、合并状态。
- [ ] 服务器代码/运行/日志/索引绝对路径与访问方式。
- [ ] 测试摘要、各岛与全局真实分数、成本、失败和停止原因。
- [ ] 明确未做单树对照与跨数据集验证，不声称三岛性能优势已被证明。

## 故障处理速查：遇到问题先定位到步骤

| 现象 | 先检查 | 修复方向 | 禁止做法 |
|---|---|---|---|
| 三个岛最后都变成同一个根 | D2.1 load_from_store/对象引用 | 岛过滤与独立实例 | 前端复制三张同树图 |
| 总预算不限但几轮就停 | D1.4、D2.6、旧 target/stop逻辑 | 明确停止配置与原因 | 随便增大一个常数掩盖 |
| 交换日志有消息但生成未用 | D3.4 application/上下文 | 修复实际注入与采用计量 | 把 offered 改名 adopted |
| B 直接继承 A 的高分 | D3.5 评估链 | 新候选重新真实评估 | 复制源节点 evidence |
| 重启后摘要和费用翻倍 | D3.3、D4.2 幂等键 | 事务/唯一键/检查点 | 删除旧日志假装没重复 |
| Web 列表只有一个 showcase | D6.2、D6.4 首页过滤 | 真实来源索引+去固定 ID | 换另一个固定 run ID |
| 列表有 run 但详情 404 | D6.1 路径映射 | ID 与实际路径一致 | 把原始路径直接暴露给前端 |
| API 正常但页面打不开 | D9.4 静态前端服务 | 构建与启动实际前端 | 宣称 API URL 就是完整 UI |
| bundle 无法用于新 clone | D8.2 是否增量 bundle | 创建含基点历史的完整 bundle | 在旧服务器目录 reset |
| 真实 LLM 不可用 | D8.4 密钥/网络/模型配置 | 记录并解决环境问题 | 切 mock 后报告真实实验 |
| 正式分数低于历史最高 | D9.3 同次基线与真实数据 | 如实报告与局限 | 复制历史分数/挑掉失败 |

## 结果回填：必须持续更新

填写规则：真实执行后才填写。每个数据必须有来源路径/日志/提交；不得把示例值、历史 38.14、fixture 指标写入本轮结果。远程原始产物保留服务器，仓库只提交脱敏摘要和证据索引，不提交原始数据、密钥或大模型权重。

### A. 实际设计与执行进度

实际存储方案（D1.2，落地于提交 `3d498e7`）：一个父实验（`experiment_id`）对应一份运行数据库；`node` 增加 `island_id TEXT NOT NULL DEFAULT ''` 并有 `(experiment_id, island_id)` 索引；新增 `island_state`（主键 `(experiment_id, island_id)`）、`exchange_summary`、`exchange_delivery`、`summary_application`、`scheduler_state` 五张表；引擎侧每岛一个 `Tree` 视图（S2 落地）。表名与本文件建议的 `run_id` 改为 `experiment_id`：现有代码里父运行标识即 `experiment_id`，不新造同义字段。跨岛来源不写入 `parent_id`/`second_parent_id`，通过 `summary_application(delivery_id, candidate_node_id)` 与 `exchange_delivery` 单独追溯（S3 接线）。旧库以 `Store(db, read_only=True)` 打开，不迁移、不写 WAL 变更；写模式只作用于新目录副本。

实际新增命令：本阶段无新增 CLI 命令；三岛配置通过任务目录 `evolve.yaml` 的 `islands:` 段进入 `EvolveConfig.from_yaml`，`EvolveConfig()` 默认即三岛。契约再生成沿用既有 `pnpm --dir web sync:contracts`（本轮实测需拆成 `python scripts/export_web_contracts.py` 与 `pnpm --dir web generate:api`，因为本机 `python` 解析到 Windows Store 占位程序，必须用 `.venv/Scripts/python.exe`）。

与需求差异及理由：无功能裁剪。`IslandsConfig.enabled=False` 表示显式单岛（legacy 兼容入口），默认 `enabled=True` 且恰三岛，与需求 §3 一致；“不限预算”实现为 `max_tokens=None`/`max_wall_hours=None`，停止仍由尝试上限、停滞与基础设施熔断规则决定，未改成无限运行。

### A0. 逐步日志（每个 D 编号至少一行）

| 时间 | 步骤编号 | 执行动作/修改文件 | 验证命令和退出码 | 产物/提交 | 状态与下一步 |
|---|---|---|---|---|---|
| 2026-10-08 | D0.1 | 只读核实仓库根/origin/分支/HEAD | `git rev-parse --show-toplevel`、`git remote get-url origin`、`git status --short`、`git rev-parse HEAD` 均退出码 0 | 仓库 `C:/Users/Administrator/faultevolve`，origin ssh.github.com:443/houchenfeng | 通过 |
| 2026-10-08 | D0.2 | 读 AGENTS.md 与两份计划，列保护清单 | 受保护四文件与 fixture 未出现在 `git status` 改动中 | 见 S0 证据表 | 通过 |
| 2026-10-08 | D0.3 | `git fetch origin main`，建规划分支提交两份计划+README | `git rev-parse origin/main` = 0655afe；规划提交 2172569 | `codex/three-island-plan` | 通过 |
| 2026-10-08 | D0.4 | 推送 demo 归档分支；建实现分支 | `git ls-remote --heads origin` 显示 `codex/webui-demo-archive` = 0655afe，与基点 tree 一致；未强推 | 归档 0655afe / 实现分支基点 924f9fc | 通过 |
| 2026-10-08 | D0.5 | SSH 只读检查服务器（BatchMode+ConnectTimeout） | `hostname`/`nproc`/`free -g`/`df -h`/`python3 --version` 退出码 0；`git -C code rev-parse HEAD` = dcd2283 | 32 核、124 GB、根分区余 257 GB、Py 3.13.11 | 通过（密钥缺失见 S0 阻塞项） |
| 2026-10-08 | D1.1 | 逐点读 engine/tree/store/selection/insights/budget/crossover 与 cli、webapi 调用点 | 结果写入「实际设计」；主循环确认为 `cloud/engine.py::_run_one_iteration_inner` | 提交 3d498e7 | 通过 |
| 2026-10-08 | D1.2 | 新增 island_state / exchange_summary / exchange_delivery / summary_application / scheduler_state 与 node.island_id | `.venv/Scripts/python.exe -m pytest tests/test_island_contract.py -q` → 32 passed | 3d498e7 | 通过 |
| 2026-10-08 | D1.3 | attempt / valid_evaluations 口径写入 IslandsConfig 与 IslandState 字段命名（attempts、valid_evaluations、invalid_evaluations） | 同上 | 3d498e7 | 通过（引擎侧计数改造已在 D2.6 落地，提交 151a806：`_count_attempt`/`_record_evaluation_outcome`＋`tests/test_island_isolation.py` 实测） |
| 2026-10-08 | D1.4 | 岛配置与 null 预算（含 stage_caps 百分比失效、绝对上限、remaining_tokens 可空） | 同上 + 172 passed 定向集合 | 3d498e7 | 通过 |
| 2026-10-08 | D1.5 | 临时库三岛读写、非法配置、null 预算、旧 fixture 只读与复制恢复 | 同上；fixture 源文件 sha256 断言不变 | 3d498e7 | 通过 |
| 2026-10-08 | D2.1 | `tree.py` 加 `island_id` 作用域（load/add/`get_island_best`/导出带岛标记），`islands.py` 新增 `IslandRuntime`/`IslandCoordinator` | `.venv/Scripts/python.exe -m pytest tests/test_island_isolation.py -q`（仓库根）→ 退出码 0，16 passed / 0 failed（12.41s，终端输出；同一提交后的全量结果见 `/tmp/s2_full5.log`） | 提交 151a806 | 通过；下一步 D2.2 |
| 2026-10-08 | D2.2 | `ISLAND_ATTRS` 属性槽逐项迁移；`store.py` 为 node/insight/llm_call/operator_stats 加岛列与岛作用域读，operator bandit 改按岛后验；`insights.py` 三处岛作用域读 | 同上 + `.venv/Scripts/python.exe -m pytest tests/webapi/ tests/test_adapters.py tests/test_run_stall_guard.py tests/test_hotfix_3_1.py -q` → 退出码 0，395 passed | 151a806 | 通过；`_harvest_discovery_candidates()` 的岛参数化随 D4.1 做 |
| 2026-10-08 | D2.3 | `_init_island_roots()`：一次真实 init 评估共享给三根，`shared_initial_evaluation_id` 与账本单次计费；无效初始评估三岛齐停 | `.venv/Scripts/python.exe -m pytest tests/test_hotfix_3_1.py tests/test_run_stall_guard.py -q`（含于上面 395 passed 集合）→ 退出码 0 | 151a806 | 通过 |
| 2026-10-08 | D2.4 | `run()` 改为协调器驱动的最小调度循环；`eval_concurrency>1` 启动即拒；补父运行结束原因 `all_islands_stopped` | `pytest tests/test_island_isolation.py -q` → 16 passed（含 `::test_the_run_ends_when_no_island_is_runnable` 断言 `stop_reason`）| 151a806 | 通过 |
| 2026-10-08 | D2.4（失败记录） | 首轮全量：`pytest tests/ -q` → 退出码 1，6 failed / 1579 passed（862.82s，`/tmp/s2_full2.log`）；`test_adapters.py` 核心模块禁用词命中注释里的 `serial`；`test_engine.py::test_engine_resume_continues_same_tree` 断言恢复后同一根失败 | 保留本行；修复见下行 | 提交前工作树（后随 151a806） | 失败 → 已修复 |
| 2026-10-08 | D2.4（修复） | 改写引擎注释避开受保护词；把 legacy 单岛与多岛恢复拆成两个测试；`config.py` 允许 `island_id=""` 为 legacy 内部岛、把“必须命名”上移到 `IslandsConfig`（修 `legacy_island_spec()` 构造即抛 Pydantic 错的断裂） | `pytest tests/test_engine.py tests/test_island_contract.py -q` → 退出码 0，46 passed | 151a806 | 通过 |
| 2026-10-08 | D2（第二次全量，失败记录） | `pytest tests/ -q` → 退出码 1，4 failed / 1583 passed（872.55s，`/tmp/s2_full3.log`）：`test_adapters` 禁用词、`test_engine_resume_continues_same_tree`、`tests/webapi/test_contract_stability.py` 两项（`web/openapi/*.json` 落后于当前源码生成结果） | 保留本行；契约在 `config.py` 修正后重新导出，另跑 `pytest tests/webapi/ tests/test_adapters.py tests/test_run_stall_guard.py tests/test_hotfix_3_1.py -q` → 395 passed | 提交前工作树（后随 151a806） | 失败 → 已修复 |
| 2026-10-08 | D2.5 | profile 落地为提示重点（`{island_focus_section}`）＋算子倾向（`_apply_island_bias`）＋带种子 20% 探索；`operator_bias_applied` 记选择原因 | `pytest tests/test_island_isolation.py -q` → 16 passed（`::test_island_focus_reaches_only_its_own_prompts`、`::test_profile_bias_narrows_the_pool_unless_the_draw_explores`、`::test_exploration_draws_are_island_local_and_reproducible`） | 151a806 | 进行中→通过（`knowledge_keywords` 注入未接线，转 D4.1 并保持未勾选） |
| 2026-10-08 | D2.6 | 每岛 attempts/valid/invalid/stall/infra 计数与冠军当场落盘；修复候选计额度；停止与导出（`_best_across_islands`、`_activate_island_of_best`、无有效结果不造冠军）；契约 8 事件类型＋前端 12 类映射；重导 `web/openapi/*.json` | `scripts/export_web_contracts.py` + `scripts/check_web_contracts.py` → 退出码 0「contract check OK: 4 files match the Python source」；`pnpm --dir web generate:api` → `src/generated` 无 diff；`pnpm --dir web typecheck` → 退出码 0 | 151a806 | 通过 |
| 2026-10-08 | D2 阶段门 | 全量离线测试（S2 收尾） | `.venv/Scripts/python.exe -m pytest tests/ -q`（工作目录 `C:/Users/Administrator/faultevolve`，`.venv` Python 3.12.4；原文写 3.13 系误写，更正依据见 S6 阶段门行）→ 退出码 0，1588 passed / 0 failed（822.68s） | `/tmp/s2_full5.log`；提交 151a806 | 通过；下一步 S3（D3） |
| 2026-10-08 | D3.1 | 新增 `cloud/exchange.py`：`sanitize()`/`content_hash()`/`task_fingerprint()`/`evaluator_fingerprint()`/`error_class_of()`/`SummaryContext`（无 code 字段）；`operators.py` 加 `{exchange_summary_section}` 插槽与 `set_exchange_summaries()` | 命令见 D3.6 行（同一验收集合，退出码 0）；本步函数：`test_summary_dto_has_no_place_for_code`、`test_only_the_error_class_is_read_out_of_a_traceback`、`test_fingerprints_describe_task_and_evaluator`、`test_content_hash_is_normalized_but_kind_sensitive` | 9592fe7、2f368fa | 通过；`knowledge` 一类只建模型，发布归 D4.1 |
| 2026-10-08 | D3.1（修复） | 发现 1200 字符上限用 `[:1200]` 切片会把结论截成半句，且“先 join 再清洗”使多段正文被当成一条超长行整段丢弃：改为按 `\n`/`；` 切段计数、超预算只从尾部丢整段 | 该缺陷由 `test_an_over_long_body_is_reduced_by_whole_segments_not_mid_sentence` 首次暴露（1 failed / 21 passed，退出码 1）；修复后并入 D3.6 行的 38-passed 集合 | 2f368fa | 通过（原始实现随 9592fe7 提交，本行为其后修复，记录不覆盖） |
| 2026-10-08 | D3.2 | `_new_summary()` 哈希去重＋`store.add_summary_evidence(metrics=...)`（重复结论并证据、升 confidence、同步刷新计数）；`_publish_best()` 仅在本岛已发布最佳被超过时发布，基线根不带 gain 字段；`checkpoint()`/`share_error()` 全程 try/except 只写 `exchange_summary_failed` | 命令见 D3.6 行，22 用例全通过（`test_a_repeat_of_the_same_error_adds_evidence_instead_of_a_second_message`、`test_a_baseline_root_is_described_without_claiming_an_improvement`、`test_a_broken_summary_channel_never_touches_a_score`、`test_content_hash_is_normalized_but_kind_sensitive`） | 9592fe7、2f368fa | 通过 |
| 2026-10-08 | D3.3 | `engine._maybe_exchange()` 挂到主循环 `_update_island_after_attempt()` 之后；`due()` 游标判定、零发送也推进并 `save_state()`；`_exchange_targets()` 只含 PENDING/RUNNING；`_unpublished_failures()`＋`share_error()` 提前投递；`exchange_check{published,delivered,zero_send}` 事件 | 命令见 D3.6 行，22 用例全通过（`test_the_same_lesson_is_published_once_even_across_a_restart`、`test_a_stopped_island_is_neither_a_reader_nor_a_writer`）；另 `pytest tests/test_island_isolation.py -q` 16 passed 未回归 | 9592fe7 | 通过；停滞求助机制未实现（`stagnation_request_evals` 无调用点），该行保持未勾选 |
| 2026-10-08 | D3.4 | `accept_for()` 生成时决策并一次写死（4 种拒绝原因）、`_best_ceiling()` 判过时、`_rank()`＋`max_summaries_in_context` 截断；`record_applications()`/`complete_applications()` 把 applied 与 evaluated 分离 | 命令见 D3.6 行，22 用例全通过（`test_a_summary_from_another_task_or_evaluator_is_rejected_with_reason`、`test_an_overtaken_best_is_rejected_as_superseded`、`test_the_context_queue_is_capped_at_the_configured_size`、`test_a_summary_is_delivered_once_per_target_island`、T26 `test_offered_accepted_applied_and_evaluated_are_not_counted_as_one`） | 9592fe7 | 通过 |
| 2026-10-08 | D3.5 | `_summary_cross_candidates()`＋`_available_operators()` 门控；`_choose_operator()` 非 bandit 分支加“兄弟领先即嫁接”的 `summary_cross_selected`，无可用摘要时 `operator_fallback` 降级 REFINE；`_apply_island_bias()` 保留 SUMMARY_CROSS（事件加 `exchange_kept`）；`summary_crossover` 事件记来源；`record_purpose="summary_cross"` | 命令见 D3.6 行，22 用例全通过（`test_a_positive_summary_reaches_the_sibling_prompt_and_is_evaluated_locally`、`test_a_grafted_candidate_never_inherits_the_source_score`、`test_a_sibling_source_never_enters_the_receiving_prompt`）；核查既有双亲路径：`_crossover_partners` 属 `ISLAND_ATTRS`（每岛一份），摘要交叉不读外岛节点代码 | 9592fe7 | 通过 |
| 2026-10-08 | D3.6 | 新建 `tests/test_island_exchange.py`（22 用例，全离线：临时库＋`FakeAdapter`＋`_RecordingLLM`，不碰 `benchmark/hdd_mvp/data/`）；四个必须可见测试与 T26 齐备；源码隔离测试补“标记确实存在于摘要来源节点”的正向对照 | `.venv/Scripts/python.exe -m pytest tests/test_island_exchange.py tests/test_island_isolation.py -q` → 退出码 0，38 passed（19.25s） | 9592fe7、2f368fa | 通过；文件系统层拦截无法在离线 mock 验证，边界靠 DTO 无源码字段保证（已在 D3.6 注明局限） |
| 2026-10-08 | D3（契约与前端） | `webapi/catalog.py::EVENT_TYPES` 新增 9 个交换事件类型；`web/src/features/workbench/event-taxonomy.ts` 把它们归进既有 12 粗类（`insight` 收 7 个交换生命周期事件，`node_state` 收 `summary_cross_selected`/`summary_crossover`），不新增第 13 类 | `.venv/Scripts/python.exe scripts/export_web_contracts.py`＋`scripts/check_web_contracts.py` → 退出码 0「contract check OK: 4 files match the Python source」；`.venv/Scripts/python.exe -m pytest tests/webapi -q` → 退出码 0，357 passed；`pnpm --dir web generate:api` → `src/generated` 无 diff；`pnpm --dir web typecheck` → 退出码 0；`pnpm --dir web test` → 660 passed / 1 failed（既有 SmartMem 用例，见 F 段） | 9592fe7 | 通过 |
| 2026-10-08 | D3（中止记录） | 对 9592fe7 启动全量门：`pytest tests/ -q` | 运行至约 40% 时人工中止——同一阶段的 D3.1 修复（2f368fa）使该次结果失效，不作为门 | `/tmp/s3_full1.log`（空，中止） | 中止 → 以 2f368fa 重跑，见下一行 |
| 2026-10-08 | D3 阶段门 | 全量离线测试（S3 收尾，代码 2f368fa） | `.venv/Scripts/python.exe -m pytest tests/ -q` → 退出码 0，**1610 passed / 0 failed**（828.25s，13:48）；较 S2 门（1588）净增 22 条，正是 `tests/test_island_exchange.py` 的用例数，S2 的 1588 项无一回归 | `/tmp/s3_full2.log` | 通过 |
| 2026-10-08 | D4.1 | `_retrieve_knowledge_cards()` 返回 `KnowledgeSelection`（cards＋island_id/profile/island_keywords/reason/error_type），岛画像 `knowledge_keywords` 进检索上下文；来源在 `loader.py` 打 `ORIGIN_FROZEN/ORIGIN_RUN_NEW`；每次尝试检索都写 `knowledge_injected`（含空选择与失败）；INJECT 取 `[:1]`；`_harvest_discovery_candidates()` 改按活动岛读 insight | `.venv/Scripts/python.exe -m pytest tests/test_island_knowledge.py -q` → 退出码 0，9 passed（新增文件，全离线：临时库＋`FakeAdapter`＋`_DeclaringLLM`，6 卡 6 类库） | bd76846 | 通过；`kind="knowledge"` 的摘要发布本轮不接线（跨岛共享已由实验级 `_discovery_card_path()` 完成），已在 D4.1 落地说明写明 |
| 2026-10-08 | D4.1（测试自身修正） | 三条属测试写错而非实现缺陷：①断言 `child.card_ids == ["K-A1"]` 实得 `['FE01','M01']`——MockLLM canned 回复自带 `<adopted_cards>`，而 `extract_adopted_cards_from_response` 取第一个标记，改为 `_DeclaringLLM` 正则替换该标记；②收紧为 `payload["sources"] == {"frozen": […]}` 时报 `KeyError: 'run_new'`——`sources_by_origin()` 只输出实际出现的来源，改为断言确切字典；③`k=2` 时本运行新卡选不中——`CardRetriever` 无分数阈值且排序把本岛两类排在前，改 `k=7`（每类 1 张）并把 docstring 措辞从“排名优先”降为“可达且来源标注正确” | 逐条修复后并入上一行的 9-passed 集合（首次运行为 3 failed / 6 passed） | bd76846 | 通过（原始失败保留，不覆盖） |
| 2026-10-08 | D4.2 | `LLM_STAGE_MAP` 统一账本与 `llm_call` 的 stage 命名；`llm_call` 加 7 列（request_id/transport_attempts/island_attempt/stage/outcome/cost_usd/cost_basis）与 `_llm_call_from_row()` 容错读；`CallMetrics` 加 request_id/attempts，`DashScopeLLM` 为每个逻辑请求生成 id 并在重试耗尽时带 `attempts=len(RETRY_DELAYS)+1`（当前三次退避即 4 次发送）；六处 except 改调 `_record_lost_llm_call()`（`unknown_outcome`＋`llm_call_lost` 事件＋账本 `status="failed"`）；`get_cost_rollup()` 按岛分桶并单列 shared/unresolved/cached；`run_finished` 载荷加 `"cost"`；顺带修 `cost_ledger` 缺岛列与恢复时 seq 冲突（`start_seq=max_cost_seq`） | `.venv/Scripts/python.exe -m pytest tests/test_island_cost.py -q` → 退出码 0，8 passed；回归集合 `pytest tests/test_autotune_ledger.py tests/test_island_contract.py tests/test_island_cost.py tests/test_island_exchange.py tests/test_island_isolation.py tests/test_island_knowledge.py tests/test_llm.py tests/test_metering.py tests/test_operators_bandit.py tests/test_store.py tests/test_adapters.py tests/webapi -q` → 退出码 0，526 passed（61.48s） | 0eac985 | 通过；幂等重放未实现（策略为不自动重放，已记账并留 request_id），D4.2 落地说明如实标注 |
| 2026-10-08 | D4.2（修复） | 四条实现缺陷按发现顺序保留：①`Store.get_llm_calls` 里引用了未定义常量 `_LLM_CALL_ADDED_FIELDS`（实为 `_LLM_CALL_ADDED`）→ 6 failed/`NameError`，改为模块级 `_llm_call_from_row()`；②`LLMCall` Pydantic 模型没有 `stage` 等新字段而 DDL 已有 → 29 处 `AttributeError`，补齐 schema 字段；③算子重试累加器沿用 `CallMetrics()` 默认 `attempts=1`，两次发送报成三次 → 改 `CallMetrics(attempts=0)`；④DDL 的 `idx_cost_ledger_island` 引用 `island_id`，而加列迁移原先排在 `executescript(DDL)` 之后，打开一个 D4.2 之前的库即 OperationalError → 迁移提到建索引之前 | ①②③由 `tests/test_island_cost.py` 首次暴露（分别 6 failed / 29 failed / `assert 3 == 2`），④由新增的 `test_an_old_run_directory_still_opens_and_reads` 钉住（`DROP COLUMN` 造旧库＋`read_only=True` 先读原件）；四条修复后同一集合 526 passed | 0eac985 | 通过（原始失败保留，不覆盖） |
| 2026-10-08 | D4.2（测试自身修正） | `test_one_request_is_never_counted_under_two_islands` 初版断言“任何 `purpose` 含 summary 的行都不许存在”，把 `summary_cross` 误判成路由开销——嫁接兄弟结论是一次真实生成，必须计费且由接收岛付 | 首跑 1 failed（实得一条 `purpose='summary_cross', island_id='b', stage='generate'`）后改为“投递/接受/应用不产生成本行＋`summary_cross` 行必须归接收岛并带 island_attempt” | 0eac985 | 通过（原始断言保留，不覆盖） |
| 2026-10-08 | D4.2（契约与前端） | `webapi/catalog.py::EVENT_TYPES` 新增 `llm_call_lost`；`web/src/features/workbench/event-taxonomy.ts` 把它归入既有 `llm` 粗类，仍是 12 类 | `scripts/export_web_contracts.py`＋`scripts/check_web_contracts.py` → 退出码 0「contract check OK: 4 files match the Python source」；`pnpm --dir web generate:api` → `src/generated` 无 diff；`pnpm --dir web typecheck` → 退出码 0；`pnpm --dir web test` → 660 passed / 1 failed（既有 SmartMem 用例，见 F 段，归 S6） | 0eac985 | 通过 |
| 2026-10-08 | D4.3 | 新增 `cloud/resume.py`（`RunIdentity`/`CHECKED_FIELDS`/`check_identity`/`ResumeRefused`/`RunBusy`/`run_claim` 判定/`snapshot_rng`/`clone_run_directory`/`copy_run_artifacts`）与 `common/proc.py`（`pid_alive`，自 `webapi/run_control.py` 搬迁）；`store.py` 加 `run_identity`/`run_claim` 两表与五个读写方法；`engine.initialize()` 改为 specs → `_verify_run_identity()` → `_take_run_claim()` → 协调器 → `_prepare_runtime()` → `_apply_restored_rng()`；`_restore_run_cost()`＋`run_resumed`；`persist_cursor()` 写 `rng_state_json`；`_pending_summary_applications()`；`_flush_deferred()` 的 `rebuilt_from_node` 与队列剪除；`rebuild_run_report()`；`cli.py` 加 `--resume-from`/`--report-only` | `.venv/Scripts/python.exe -m pytest tests/test_island_resume.py -q` → 退出码 0，**39 passed**（14.21s）；五岛集合 `pytest tests/test_island_contract.py tests/test_island_cost.py tests/test_island_exchange.py tests/test_island_isolation.py tests/test_island_knowledge.py -q` → 87 passed（36.01s）；D4 回归集合（12 个文件＋`tests/webapi`，含新文件）→ 退出码 0，565 passed（93.66s）；`pytest tests/test_island_resume.py tests/test_engine.py -q` → 53 passed | 91c8203 | 通过；D4.4 与 S4 阶段门未开始 |
| 2026-10-08 | D4.3（修复） | 四条实现缺陷按发现顺序保留：①`clone_run_database` 把只读 URI 拼成两个 `file:` 前缀 → `sqlite3.OperationalError: unable to open database file`；②`--report-only` 在 `get_base_artifacts_dir` 返回 None 时做 `None / str` → `TypeError`；③`jev_deferred_evaluated` 没有 `island_id`，恢复时无法区分"只筛过"与"已评估"，已评估候选会重评一次并重复加分，且 flush 过的项留在队列里会被再次 flush；④`_verify_run_identity()` 的"无身份记录"分支注释声称会比对任务文本，代码里并没有比 | ①用 `/tmp/probe_wal{,2,3,4}.py` 四次探针确认 `Path.resolve().as_uri()+"?mode=ro"` 才既只读又读到 WAL，改生产代码后 `test_a_clone_carries_the_wal_and_leaves_the_source_readable` 通过；②改为 `(resolved_artifacts_dir or resolved_runs_dir) / resume`，由 `test_report_only_writes_a_missing_report_from_the_database` 钉住；③由 `test_a_deferred_candidate_the_evaluator_answered_is_not_charged_twice` 与 `::test_a_deferred_candidate_that_was_never_evaluated_is_evaluated` 钉住；④补上 `task_fingerprint(experiment)` 比对与 `run_resume_refused` 的 `reason` 字段，由新增 `test_a_run_without_an_identity_record_still_refuses_a_changed_task` 钉住 | 91c8203 | 通过（原始缺陷保留，不覆盖） |
| 2026-10-08 | D4.3（测试自身修正） | ①`test_a_run_without_an_identity_record_resumes_and_says_what_is_unverified` 仍断言 `verified == []`，与补上任务比对后的 `["task_fp"]` 冲突（1 failed）；②`tests/test_discovery_preflight_crash_fix.py::test_discover_factors_writes_error_txt_on_failure` 的 CLI 调用没打 `create_benchmark_adapter` 补丁，attach 用真实 HDD 适配器，指纹与该 mock 运行不符 → 被新的身份拒绝路径在先，error.txt 里是拒绝消息而非 `synthetic boom` | ①断言改为 `["task_fp"]` 并新增"拒绝时不补写记录"的对照；②在同一 `with` 里补 `patch("faultevolve.tasks.create_benchmark_adapter", return_value=adapter)` 并注明 attach 即 resume → 单文件 39 passed；`pytest tests/test_discovery_preflight_crash_fix.py tests/test_cli_discover.py -q` → 12 passed | 91c8203 | 通过（原始失败保留，不覆盖） |
| 2026-10-08 | D4.3（契约与前端） | `webapi/catalog.py::EVENT_TYPES` 新增 `run_interrupted`/`run_resumed`/`run_resume_refused`；`event-taxonomy.ts` 归入既有 `run_state` 粗类（仍 12 类）；重导 `web/openapi/engine-catalog.json` | `scripts/export_web_contracts.py`＋`scripts/check_web_contracts.py` → 退出码 0「contract check OK: 4 files match the Python source」；`pnpm --dir web generate:api` → `src/generated` 无 diff、`pnpm --dir web typecheck` → 退出码 0；`pnpm --dir web test` → 1 failed / 660 passed / 3 skipped（12.36s，失败仍是既有 `src/app/App.test.tsx > 应用外壳 > 评委总览只呈现可用的 HDD 任务入口`，见 F 段，归 S6）；`pytest tests/webapi -q` 含于上面 565 passed | 91c8203 | 通过；`--resume-from`/`--report-only` 的 API 与界面接入属 D6.3/S6 |
| 2026-10-08 | D4.3 全量（阶段门之前） | 全仓库离线套件（含 `tests/webapi`） | 首跑 `pytest tests/ -q` → 退出码 1，1 failed / 1665 passed（887.18s）——失败为上一条 D4.3（测试自身修正）②；修好后 `.venv/Scripts/python.exe -m pytest tests/ -q` → 退出码 0，**1666 passed / 0 failed**（856.07s，`/tmp/s4_full1.log`）＝S3 门 1610＋D4.1 9＋D4.2 8＋D4.3 39，无回归 | `/tmp/s4_full1.log` | 通过（D4.4 仍需重跑 S4 阶段门） |
| 2026-10-08 | D4.4 | 新建 `tests/test_island_fault_injection.py`（9 用例，五组：未投递／未评估／未出报告／B 暂停／账本重复）；`exchange.py` 新增 `backfill_deliveries()` 并把 `checkpoint()` 改成"先补缺、再发布、后投递"；`webapi/catalog.py::EVENT_TYPES` 加 `exchange_delivery_backfilled`，`event-taxonomy.ts` 归入既有 `insight` 粗类（仍 12 类）；重导 `web/openapi/engine-catalog.json` | `.venv/Scripts/python.exe -m pytest tests/test_island_fault_injection.py -q` → 退出码 0，**9 passed**（11.03s，首跑即绿）；新文件与既有交换／恢复集合同跑（`tests/test_island_fault_injection.py tests/test_island_exchange.py`、`tests/test_island_fault_injection.py tests/test_island_resume.py`）均退出码 0；岛屿＋webapi 七项集合 `pytest tests/test_island_fault_injection.py tests/test_island_exchange.py tests/test_island_resume.py tests/test_island_cost.py tests/test_island_isolation.py tests/test_island_knowledge.py tests/webapi -q` → 退出码 0，460 passed（106.88s） | 971f38e（5 文件，＋587/−1） | 通过；下一步 S4 阶段门 |
| 2026-10-08 | D4.4（缺陷与修复） | 本轮新发现的真实缺陷只有第一种（账本那一点在 D4.2/0eac985 已修，本轮只补计数对比与 mutation）：摘要落库与投递是两次插入，进程死在中间后**永远补不回来**——`_new_summary()` 内容哈希命中时只并证据并返回 None，下一轮不会再发同一条结论，而 `_deliver()` 只处理本轮新产出的摘要，缺口无人知晓。改为按库查询缺口：本岛已发布的摘要 × 当前仍可行动的兄弟岛，缺 `(summary_id,target_island_id)` 就补一条 delivery | 反向 mutation 证明断言不是摆设：去掉 `checkpoint()` 里的 `backfill_deliveries()` 调用 → `pytest tests/test_island_fault_injection.py tests/test_island_exchange.py -q` → 退出码 1，**3 failed / 28 passed**（26.07s，正是三种"未投递"断言）；还原后 9 passed | 971f38e | 通过（补齐动作写 `exchange_delivery_backfilled` 事件留痕） |
| 2026-10-08 | D4.4（反向 mutation） | 除上一行的"去掉补齐调用"外，另三点各关掉一条生产逻辑，确认对应断言确实会失败：①`_pending_summary_applications()` 直接返回 `{}`（已采用未评估不再重挂）；②`_prepare_runtime()` 把 PAUSED 也归一化成 RUNNING（岛 B 中断后被无意重启）；③`init_ledger()` 的 `start_seq` 固定为 0（续跑账本从头计数） | ①`pytest tests/test_island_fault_injection.py tests/test_island_resume.py -q` → 退出码 1，**2 failed / 46 passed**（30.86s；其中一条是 D4.3 既有的 `test_an_application_recorded_before_the_crash_still_gets_its_result`，说明两种中断共用同一重挂逻辑）；②`pytest tests/test_island_fault_injection.py -q` → 退出码 1，**2 failed / 7 passed**（11.72s，即 B 的暂停态与"兄弟不派活给停着的岛"两条）；③按 `-k "ledger or request"` 只选账本相关两条 → 退出码 1，**1 failed / 1 passed / 7 deselected**（5.83s），失败信息 `sqlite3.IntegrityError: UNIQUE constraint failed: cost_ledger.experiment_id, cost_ledger.seq`（`store.py:1973`） | 971f38e | 通过（四处生产逻辑各被至少一条断言钉住；全部还原后 `git status --short` 只剩本步五个文件，`test_island_exchange.py`／`test_island_resume.py` 复跑仍绿）。**未做 mutation 的一点**："评估完成但报告未生成"只由 `adapter._call_count` 前后相等这条断言自身钉住，没有把 `rebuild_run_report()` 改成会重评的版本来验证断言会失败——它是 D4.3（91c8203）实测过的机制，本轮只补计数对比，留作 S7 的补测项 |
| 2026-10-08 | D4.4（契约与前端） | `exchange_delivery_backfilled` 入 `EVENT_TYPES`；前端归 `insight` 粗类；重导 `web/openapi/engine-catalog.json`（7304 字节） | `scripts/export_web_contracts.py`＋`scripts/check_web_contracts.py` → 退出码 0「contract check OK: 4 files match the Python source」；`pnpm --dir web generate:api` → `src/generated` 无 diff；`pnpm --dir web typecheck` → 退出码 0；`pnpm --dir web test` → 退出码 1，660 passed / 1 failed（仍是既有 `src/app/App.test.tsx` SmartMem 用例，见 F 段，归 S6） | 971f38e | 通过（既有失败不在本阶段修复，保留记录） |
| 2026-10-08 | D4.4 阶段门＝S4 阶段门 | 全仓库离线套件重跑（代码 971f38e） | `.venv/Scripts/python.exe -m pytest tests/ -q` → 退出码 0，**1675 passed / 0 failed**（1067.28s）＝D4.3 收尾 1666＋D4.4 的 9；D4 回归集合（13 文件＋`tests/webapi`）`pytest tests/test_autotune_ledger.py tests/test_island_contract.py tests/test_island_cost.py tests/test_island_exchange.py tests/test_island_fault_injection.py tests/test_island_isolation.py tests/test_island_knowledge.py tests/test_island_resume.py tests/test_llm.py tests/test_metering.py tests/test_operators_bandit.py tests/test_store.py tests/test_adapters.py tests/webapi -q` → 退出码 0，**574 passed / 0 failed**（89.86s）＝D4.3 的 565＋9 | `/tmp/s4_full2.log` | S4 阶段门通过；下一步 S5（`skill/fe-island-evolution`）。真实运行的中断／恢复仍属 S8／S9 |
| 2026-10-08 | D5.1（产物契约前置） | 让 Skill 的“输出契约”有实物可写：`cloud/engine.py` 新增 `island_report(store, experiment_id)` 投影，实时运行 `_write_artifacts`、`rebuild_run_report()` 与崩溃摘要三个写入口共用同一份 `islands`/`exchange`/`cost`；`tests/test_island_fault_injection.py` 新增 `test_the_run_directory_names_every_island_without_any_sql`（该文件 9→10 条，S4 记录的 9 passed 是 971f38e 时的事实） | `.venv/Scripts/python.exe -m pytest tests/test_island_fault_injection.py -q` → 退出码 0，10 passed | df8a346（2 文件，＋123/−11） | 通过 |
| 2026-10-08 | D5.1（缺陷与修复：岛状态字面量） | `island_report()` 首版用 `str(state.status)` 写状态，产物里落的是 `IslandStatus.RUNNING` 而不是 `running`；此前**没有任何测试钉住这个字符串**，所以它从未被暴露。改为 `state.status.value`，并在测试里断言状态取值 `<= {pending,running,paused,finished}` | 修前实测产物为枚举 repr；修后同一文件 10 passed | df8a346＋b6b6241 | 通过（原始缺陷保留，不覆盖） |
| 2026-10-08 | D5.1（缺陷与修复：逐岛成本不在产物里） | 逐岛 token 花费当时只存在于一条 SQL 查询，运行目录的第一份文件回答不了“哪个岛烧了多少”；`cost` 块改从 `store.get_cost_rollup()` 读（即恢复路径读的同一事实），使跨进程累计能进报告。实测同一 toy 运行续跑前后：岛 a tokens 2200→3300、calls 8→12，岛 c 保持 2200，`sum(by_island)+shared_tokens == total_tokens(8550)`；重建报告与实时报告的 `cost` 逐字段相等 | `pytest tests/test_island_fault_injection.py -q` → 10 passed；`pytest tests/test_island_resume.py tests/test_island_cost.py -q` → 57 passed（25.95s） | b6b6241（2 文件，＋46/−4） | 通过；`CostLedger.totals()` 仍只汇总本进程内存记录（属 S6 议题），已在 Skill 的恢复参考里如实写明 |
| 2026-10-08 | D5.1（缺陷与修复：doctor 查的不是要跑的配置） | 写 Skill 步骤 2 时发现真实操作陷阱：配置放在任务目录之外时 `fe doctor` 仍解析默认 `hdd` 适配器，而运行用的是配置里的 `famou`——预检通过≠要跑的东西通过；同时引擎对不认识的顶层键**静默忽略**（`island:` 拼错就退回默认三岛，无任何提示）。`doctor` 加 `--config-file`（只给 `--config-file` 不给 `--task-dir`、或文件不存在 → 退出码 2）与 `config_keys`/`config_islands` 两项检查 | `.venv/Scripts/python.exe -m pytest tests/test_doctor_task_checks.py -q` → 退出码 0，9 passed（5→9，新增“配置选中的适配器与运行一致”“打印实际岛环”“点出被忽略的键”“打不开的配置直接拒绝”四条） | 6f0fb04（2 文件，＋143/−9：`cli.py` ＋67/−9、`test_doctor_task_checks.py` ＋76/−0，`git show --numstat` 实测） | 通过 |
| 2026-10-08 | D5.1＋D5.2（入口与四个参考） | 新增 `skill/fe-island-evolution/SKILL.md`（224 行：何时使用／输入契约／缺输入规则／执行顺序 1-8／输出契约／完成标准／经验回流／禁止操作／参考）与 `references/configuration.md`（110 行）、`references/exchange.md`（77 行）、`references/hdd-server.md`（204 行）、`references/recovery.md`（95 行）；README 技能索引加一行；`skill/fe-evolve-manager/SKILL.md` 加“与 `fe-island-evolution` 的分工”并原样保留其第 5 步旧运行 `--resume` | `fe doctor --task-dir benchmark/hdd_mvp --config-file C:	mp\s5\cfg\preflight.yaml --json` → 退出码 1（本机未设模型密钥环境变量，`all_ok` false，属预期），其中 `config_keys`、`config_islands` 两项 `ok=true`，消息逐字为 `islands on: 3 tree(s) [a:performance, b:miss_alert, c:efficiency], exchange every 1 attempts`；日志 `C:	mp\s5\gates\doctor_config.txt` | f21af80（10 文件，＋1558） | 通过 |
| 2026-10-08 | D5.2（文档自纠，保留原始错误） | 四处写作错误在成为声明之前被实测推翻：①`hdd-server.md` 首版把岛清单写成 `islands.specs:`，而 `IslandsConfig` 的字段就叫 `islands`——`specs` 属“会被静默忽略的键”，照抄会静默丢岛环；用 `EvolveConfig.from_dict()` 实跑该 YAML 后改回 `islands.islands`。②首版把轮数上限写成 `stop.max_iterations: 150`，`StopConfig` 并无此字段（应为 `budget.max_iterations`），且漏了 `budget.max_wall_hours` 默认 6.0 会掐断长跑。③经验草稿首版把“投递 2 次／采纳 2 次”与“采纳后生成的 3 个候选”混写成一句，改为分层表述“采纳 N 次…采纳后生成的已评估候选 M 个”。④`islands.stagnation_request_evals` 一度按字段名描述成“停滞求助节奏”，grep 全 `src/` 确认只有 `config.py:165` 的定义与 `webapi/catalog.py:213` 的界面元数据两处、引擎不读 → 文档改称“当前引擎不读这个字段”，不编造行为 | ①②由 `EvolveConfig.from_dict()`／`fe doctor` 实跑证伪；③由 `export_experience_skill.py` 输出的四层计数对照证伪；④由全 `src/` 检索证伪 | f21af80 | 通过（原始写法保留，不覆盖） |
| 2026-10-08 | D5.2＋D5.4（结构与命令漂移测试） | 仓库内**没有** Skill 结构校验工具（`scripts/` 只有 web 契约与 fixture 类脚本，逐条确认；前端 `package.json` 亦无 skill lint），故校验以测试形式落地：`tests/test_island_skill.py` 43 项，把本页/参考里的每条相对链接、每个 `fe` 参数、每个导出脚本参数、每个事件名、每个配置默认值、每个岛状态字面量都对着 `cli.py`／`engine.py`／`exchange.py`／config 模型核对 | `pytest tests/test_island_skill.py -q` → 退出码 0，43 passed（0.26s） | f21af80 | 通过 |
| 2026-10-08 | D5.2（反向 mutation） | 两处各改一处文档再跑，确认断言不是摆设：①把 `configuration.md` 的 `exchange_interval` 默认写成 `6` → `pytest tests/test_island_skill.py -q -k defaults` 退出码 1，**1 failed / 42 deselected**；②在 SKILL.md 演练命令里插入假参数 `--island-workers 3` → `pytest tests/test_island_skill.py -q -k flags` 退出码 1，**1 failed / 9 passed / 33 deselected**（`test_documented_fe_flags_are_real_cli_flags`）。两处还原后 43 passed，且 `grep island-workers` 无残留 | 另记一次测试自身的缺陷：事件名检查首版正则 `"type": "([a-z_\|]+)"` 漏掉文档里 `"(a\|b\|c)"` 的括号，取到空集合——靠函数内的 `assert names` 立即失败（2 failed）而不是空清单静默通过 | f21af80 | 通过（原始失败保留，不覆盖） |
| 2026-10-08 | D5.3（导出脚本实跑） | `skill/fe-island-evolution/scripts/export_experience_skill.py`（413 行，仅 stdlib：`argparse/json/sqlite3/pathlib`；只读 URI 打开库）：从 `exchange_summary`→`exchange_delivery`→`summary_application`→`node.evidence_json` 四层事实组装规则，写 `experience_skill_draft.md` 与 `evidence_index.json` | `--help` → 退出码 0；对离线 toy 运行 `2ab57008`（16 迭代、5 条摘要）实跑 → `rules: 5`、退出码 0，两份文件落在 `<artifacts>/2ab57008/skills/`；对 `exchange_interval: 10` 的 3 轮运行（`exchange.summaries == 0`）实跑 → `rules: 0`、退出码 0，草稿写“未得到可泛化规则”并逐岛列出尝试/有效评估数与交换计数；六类拒绝（缺库、缺摘要、非法 JSON、库不含岛运行、试图写进项目 `skill/`、草稿已存在未加 `--force`）退出码均为 2 | f21af80 | 通过；日志 `C:	mp\s5\gates\export_help.txt`、`C:	mp\s5\gates\zero_draft.txt` |
| 2026-10-08 | D5.4（T24 端到端走查） | 新增 `tests/test_island_skill_walkthrough.py`：按 SKILL.md 步骤 2（预检实际岛环与适配器）→3（`--mock -n 6` 演练，断言三岛各自有尝试、`sum(attempts)==iterations_done`、`exchange.summaries>0`、成本三数自洽）→报告只读重建（三块与实时逐字段相等、`rebuilt_from_store` true）→步骤 8（导出草稿与索引）走完，全程 `task.adapter: famou` 的 toy 任务，配置文本不含 `hdd`/`smart`/`ros`/`disk` | 首跑 1 failed（断言 `evidence["run_id"]`，索引实际键名是 `experiment_id`，且 `sanitization` 还含 `summary_text_max_chars` 使全等断言失败）→ 改按实测键名断言；次跑 1 failed（断言草稿含“仅凭一次”，脚本原文是“单凭一次运行无法区分”）→ 按原文改断言。两条均属测试写错而非实现缺陷。首提交 `pytest tests/test_island_skill_walkthrough.py -q` → 退出码 0，**6 passed**（11.6s，f21af80）。随后补第 7 条 `test_a_run_that_exchanged_nothing_delivers_facts_instead_of_rules`（`exchange_interval: 10`、`-n 3` 的真实零交换运行：`exchange.summaries == 0`、`rule_count == 0`、草稿写“未得到可泛化规则”“单凭一次运行无法区分”并逐岛点名三个 profile）→ 退出码 0，**7 passed**（11.10s） | f21af80（6 条）＋6daa23c（第 7 条） | 通过（原始失败保留，不覆盖） |
| 2026-10-08 | D5.1＋D5.4（按 Skill 的命令逐条真跑，供 A1 引用） | 不只靠测试：在最终代码上把 SKILL.md 步骤 2→3→7→8 逐条实跑（toy 任务、`task.adapter: famou`、配置 `C:\tmp\s5\cfg\drill.yaml`） | `fe doctor --task-dir tests/fixtures/toy_task --config-file C:\tmp\s5\cfg\drill.yaml --json` → 退出码 1，`all_ok: false` 只由三项模型密钥检查造成，`task_files` ok、`task_adapter`＝`adapter famou -> FamouAdapter`、`config_keys`＝`config drill.yaml: all keys recognised`、`config_islands`＝`islands on: 3 tree(s) [a:performance, b:miss_alert, c:efficiency], exchange every 1 attempts`；同一命令换 HDD 形状配置（`preflight.yaml`，`task.adapter: hdd`）时 toy 目录的 `task_data` 变 false 并点出缺 `train_history.csv.gz`/`train_labels.csv`/`val_history.csv.gz`/`val_index.csv`，说明这项检查读的确实是所选适配器要求的数据；`fe evolve local tests/fixtures/toy_task --mock -n 6 --config-file … --runs-dir C:\tmp\s5\runs_a1 --artifacts-dir C:\tmp\s5\art_a1 --json` → 退出码 0、`experiment_id 497713ef`，三岛各 2 次尝试（`sum(attempts)=6==iterations_done`）、`exchange.summaries=6`、`cost` 1100+850+1100+共享 0＝总量 3050；`--mock --report-only --resume 497713ef` → 退出码 0，实时报告 119 键 vs 重建 12 键，`islands`/`exchange`/`cost` 三块逐字段相等且 `rebuilt_from_store: true`；`export_experience_skill.py <runs>/497713ef/fe.db <art>/497713ef/run_summary.json --task-dir tests/fixtures/toy_task` → 退出码 0、`rules: 6`，两份文件落在 `<artifacts>/497713ef/skills/`；`skill/fe-evolve-manager/scripts/report_run.py` 对同一次演练 → 退出码 0（节点级证据与 `tokens_per_ros_point`，键名是历史遗留、与硬盘无关）；日志 `C:\tmp\s5\gates\{doctor_toy_s5,doctor_drill,rehearsal_a1,rebuild_a1,export_a1,report_run_a1}.txt`；拒绝路径同批实测且退出码均为 2：`--config-file` 不给 `--task-dir`（`Error: --config-file needs --task-dir …`）、配置文件不存在（`Error: config file not found: …`）、导出 `--out-dir` 指向项目 `skill/`（`Error: refusing to write into the project skill tree …`），另 `export_experience_skill.py --help` → 退出码 0 | 6daa23c | 通过（A1 的预检／演练／重建／导出四行改用这些实测命令） |
| 2026-10-08 | D5（回填自身的修正，保留原错） | 两处 A0 记录写得不实，实测后更正：①6f0fb04 的行差写成“＋65/−5”，`git show --numstat` 实为 `cli.py` ＋67/−9、`test_doctor_task_checks.py` ＋76/−0（合计 ＋143/−9）；②走查测试的“7 passed”当时实际提交的是 6 项（第 7 条在门跑完後才以 6daa23c 提交），现按 f21af80（6 条）＋6daa23c（第 7 条）分开归属 | 另记一次工具侧的静默失败：用 heredoc 传给 `python -` 的编辑脚本没有真正执行（空 stdin、退出码 0），使前一次“已修”根本没落地；改用脚本文件＋编辑工具重做，并逐条 `grep` 复核落地。同批删掉第 7 条走查用例未使用的 `skill_config` 形参后复跑 → 退出码 0，7 passed（11.46s） | 6daa23c（第 7 条）＋6de9707（删未用形参）＋本次 docs 回填 | 通过（原写法保留在本行，不覆盖） |
| 2026-10-08 | D5 阶段门＝S5 阶段门 | 全仓库离线套件重跑。注：收集时工作树为 f21af80＋未提交的第 7 条走查用例（随后以 6daa23c 提交；该用例未使用的 fixture 形参在其后的 6de9707 才删去，用例名与断言不变，不影响计数），故计数对应最终代码 | `.venv/Scripts/python.exe -m pytest tests/ -q` → 退出码 0，**1730 passed / 0 failed**（925.27s）＝S4 门 1675＋D5 的 55（`test_doctor_task_checks.py` 新增 4＋`test_island_fault_injection.py` 新增 1＋`test_island_skill.py` 43＋`test_island_skill_walkthrough.py` 7）；S5 切片 `pytest tests/test_island_skill.py tests/test_island_skill_walkthrough.py tests/test_doctor_task_checks.py tests/test_island_fault_injection.py -q` → 退出码 0，**69 passed**（19.56s） | `C:\tmp\s5\gates\pytest_s5_full.txt` | 通过（S5 阶段门）；下一步 S6。真实运行的经验草稿属 S9，S5 保留未勾选的两项不因阶段门而勾选 |

状态限用：未开始、进行中、通过、失败、阻塞、不适用（须给理由）。失败后保留本行，再追加修复行。离开任务前写明最后通过步骤和下一条未完成编号，接手 AI 不需要重猜进度。

S6 追加行（2026-10-08，接 S5 阶段门之后）：

| 时间 | 步骤编号 | 执行动作/修改文件 | 验证命令和退出码 | 产物/提交 | 状态与下一步 |
|---|---|---|---|---|---|
| 2026-10-08 | D6.1（结论：发现层不成立） | 读 `webapi/{settings,run_registry,replay_service,catalog,contracts}.py` 与路由后发现：`paths.list_run_ids` 只扫一层、`replay_service` 假设 `fe.db` 与报告同目录，而真实布局是日期/批次子目录、库与报告可分开 | 本轮无独立命令：结论来自逐文件阅读＋`tests/webapi` 既有用例暴露的单层假设；`tests/webapi/test_replay_discovery.py`（既有 8 项）只覆盖同目录单层形态 | 无提交（仅阅读与分析） | 通过（产出 D6.2 的实现范围） |
| 2026-10-08 | D6.1（缺陷与修复：`Store` 只收 `Path`） | `tests/test_island_forest_export.py` 首跑红了：`rebuild_run_report(Store(str(db_path), read_only=True), …)` → `AttributeError: 'str' object has no attribute 'exists'`——只读分支直接对入参调 `Path` 方法。修 `cloud/store.py:__init__` 先归一化为 `Path` | `.venv/Scripts/python.exe -m pytest tests/test_island_forest_export.py -q` → 首跑 **1 failed / 4 passed**（4.38s），修后 **5 passed**（4.35s）。日志 `C:\tmp\s6\gates\pytest_forest_export.txt`、`…_export2.txt` | `dcc2fc5` 内 | 通过（失败记录保留） |
| 2026-10-08 | D6.2 | 新增 `webapi/run_discovery.py`（489 行）：`RUN_MARKERS` 九项、深度上限 4、访问上限 20 000、软链只登记不下钻、来源按证据判定（fixture 根／运行登记表／unverified）、`_split_pair`＋`_pair_split_layouts` 把库与报告配成一个位置、`_external_id`＝相对路径 sha256 前 8 位；`paths.py` 与 `replay_service.py` 改用同一套位置解析；`GET /api/runs/provenance` 发布来源清单；契约加 provenance 字段 | `.venv/Scripts/python.exe -m pytest tests/webapi/test_run_discovery.py -q`（新文件 14 项）→ 退出码 0；整个 `.venv/Scripts/python.exe -m pytest tests/webapi -q` → **372 passed**（32.31s，收集时点 `pytest_webapi_islands.txt` 记 372，本阶段末为 413）。日志 `C:\tmp\s6\gates\pytest_full_discovery.txt`（1777 passed / 917.32s，含全套） | `24438c9` | 通过 |
| 2026-10-08 | D6.2（反向 mutation，回填期实测复跑并更正原写法） | `C:\tmp\s6\mutate_discovery.py` 的五个 mutant 逐个应用→跑 `tests/webapi/test_run_discovery.py`→`restore`：M1 关掉"库＋报告配对"，M2 允许任意配对，M3 把深度上限放宽 +3，M4 按名字判来源，M5 去掉产物标记门 | M1、M2 各 **2 failed / 12 passed**（`test_split_run_and_artifact_roots_read_as_one_run`、`test_the_provenance_counts_reconcile`）；M3 再加 `test_the_depth_limit_is_a_real_limit`，**3 failed / 11 passed**；M4、M5 各 **10 failed / 4 passed**（含 `test_two_complete_copies_of_a_run_id_are_not_merged`、`test_a_symbolic_link_is_recorded_and_never_descended`、`test_a_fixture_root_leaves_the_product_listing` 等）；`restore` 后 **14 passed**，`git status` 只剩本文件。日志 `C:\tmp\s6\gates\mutations_discovery.log` | `24438c9`（断言集与实现同源） | 通过（原写法按记忆写成"①两台完整副本合并为一条②软链被跟随下钻③错误清单不封顶"三个 mutant，与脚本实际的五个、失败用例均不符；按实测改写，原写法保留于此括号内，不覆盖） |
| 2026-10-08 | D6.3 | `webapi/replay_groups.py` 新增 islands 分组（158 行）、`contracts.py` 加 `RunIslandsResponse`（契约 1.12.0）；单树运行给 `state=missing`＋说明，字段类型不对给 `invalid`＋路径，缺字段留 null；重导 `web/openapi/*` 与 `web/src/generated/api/*` | `.venv/Scripts/python.exe -m pytest tests/webapi/test_replay_islands.py -q` → 16 passed；整个 `tests/webapi` → 372 passed（32.31s）。日志 `C:\tmp\s6\gates\pytest_replay_islands.txt`、`pytest_webapi_islands.txt` | `08f9d2e` | 通过 |
| 2026-10-08 | D6.3（反向 mutation：单树不许编岛） | 把 `islands()` 的 `missing` 分支改成返回 `AVAILABLE`＋一个凭空造的岛 a，跑 `tests/webapi/test_replay_islands.py`，随后恢复 | **2 failed / 14 passed**（4.90s）：`test_a_single_tree_run_says_the_ring_was_never_recorded`、`test_no_island_of_a_single_tree_run_is_invented` 同时转红；恢复后 16 passed。日志 `C:\tmp\s6\gates\mutations_replay.log` | 2026-10-08 复跑留档（与 `08f9d2e` 同一断言集） | 通过 |
| 2026-10-08 | D6.3（缺陷与修复：三岛树只导出一棵） | 用真实三岛运行读回时发现 `tree.json` 只带了 9 个节点里的 3 个（只有 islands a），`programs/` 也缺另外两岛的代码——`_write_artifacts` 导出的是 `engine.tree`。改为按岛从 store 读（与 `rebuild_run_report()` 同源），并加 `tests/test_island_forest_export.py` 5 项 | 首跑 1 failed / 4 passed → 修后 5 passed（见本表 D6.1 行）；正反向 mutation：M1 让实时导出退回单树 → **4 failed / 1 passed**；M2 让重建退回单树 → **1 failed**；恢复后 5 passed。日志 `C:\tmp\s6\gates\mutations_replay.log` | `dcc2fc5` | 通过 |
| 2026-10-08 | D6.3（缺陷与修复：摘要与采用的连接键） | `summary.applications` 一直是空数组而 `application_count` 报 12：采用记录被按"投递的目标岛"连接，而应按摘要连接。修 `replay_service.py` 的连接键，并让测试要求两者一致 | 反向 mutation 两个：M6 按目标岛连接 → **1 failed / 10 passed**（3.91s）；M7 干脆全丢掉 → **1 failed / 10 passed**（4.13s）；恢复 byte-identical。日志 `C:\tmp\s6\gates\mutations_replay.log` | `dcc2fc5`＋`0808f94` | 通过 |
| 2026-10-08 | D6.3（摘要交换层接线） | `replay_service.py` 加 summaries/应用/证据投影（230 行）、`routes/exchange.py` 两个只读端点、契约 1.13.0 加 `TreeNodeDTO.island_id` 与 `summary_cross` 边类型；重导契约与生成客户端 | `.venv/Scripts/python.exe -m pytest tests/webapi/test_replay_exchange.py -q` → 首跑 **1 failed / 10 passed**（`test_a_single_tree_run_has_no_exchange_layer` 断言 `missing` 实得 `available`），中途为 **1 failed / 26 passed**，修后 **32 passed**（7.96s，新增岛屿与树边用例一并跑）；整个 `tests/webapi` → **389 passed**（52.14s）。日志 `C:\tmp\s6\gates\pytest_exchange_*.txt`、`pytest_webapi_exchange.txt` | `dcc2fc5` | 通过（失败记录保留） |
| 2026-10-08 | D6.3（前端线型与图例漂移） | `tree-adapter.ts` 把 `EDGE_STYLE` 导出、图例改为从该表生成；`workbench-components.test.tsx` 加图例↔`EDGE_STYLE` 漂移断言 | 反向 mutation：①嫁接边参与布局（去掉 `continue`）→ vitest **1 failed / 53 passed**；②嫁接边套用父边同款样式 → **1 failed / 53 passed**；恢复后 54 passed。日志 `C:\tmp\s6\gates\mutations_graft.log` | `95d25c4` | 通过 |
| 2026-10-08 | D6.4（三岛 fixture：真实引擎＋真实评估器，仅 LLM mock） | `scripts/make_island_demo_run.py`（321 行）生成 `hdd_mvp_islands_15l4nd01`：三岛各 7 节点、18 次尝试＝`iterations_done`、发布 1/投递 2/接受 2/拒绝 0/采用 12/已评估 12、成本 10200 tokens（a 3300/b 3300/c 3600，shared 0）、`cost_basis=unknown`；九项形状门不全拒写入；脱敏复用 `build_run_fixture.py` | 生成演练两次留档（种子 7、18 轮）：`--exchange-interval 2` → `applications=10`；`--exchange-interval 1`（＝脚本默认，`DEFAULT_EXCHANGE_INTERVAL=1`）→ `applications=12`（即入库那份）。日志 `C:\tmp\s6\gates\island_fixture_dryrun{,_i1}.txt`；`PROVENANCE.md` 记全部事实与局限（mock 候选 0.30~0.36，全部不超初始 22.8074，故无上升路径） | `0808f94`（含 `tests/test_build_run_fixture.py` 5 项） | 通过 |
| 2026-10-08 | D6.4（缺陷与修复：脱敏正则吃掉半个转义） | JSON 转义的主机路径每个分隔符写作两个反斜杠，旧模式只消费盘符后的第一个，剩下的 `\Users` 成了非法 JSON 转义，脱敏后的 `events.jsonl` 解析失败。改为每次消费 1–4 个分隔符，并加 `tests/test_build_run_fixture.py` | 反向 mutation 三个：M1 旧截断模式 → **2 failed / 3 passed**；M2 只允许单反斜杠 → **2 failed / 3 passed**；M3 去掉裸盘符规则 → **1 failed / 4 passed**；恢复 byte-identical。日志 `C:\tmp\s6\gates\mutations_replay.log`；该文件现共 5 项，全绿 | `0808f94` | 通过 |
| 2026-10-08 | D6.4（前端：三岛概览、岛切换、交换详情、岛最优） | `features/islands/{island-view.ts,IslandOverview,ExchangePanel,SummaryDigest,use-islands}`、结果页 `IslandBestsSection`、树页岛筛选芯片与节点岛徽标、抽屉岛行；工作台加两个面板 | 前端离线：`npx --no-install vitest run` → 收集时工作树为 **1 failed / 660 passed / 3 skipped**（既有 `src/app/App.test.tsx` 评委总览用例，见 F 段）→ D6.3 收尾时为 1 failed / 663 passed | `95d25c4`；日志 `C:\tmp\s6\gates\vitest_after_graft.txt`、`vitest_exchange.txt` | 通过（那条既有失败在 D6.5 处理） |
| 2026-10-08 | D6.4（事件流只订阅了引擎 82 类事件中的 47 类） | SSE 是命名事件，未 `addEventListener` 的类型永远不会到达浏览器：交换、岛生命周期、补丁事件全部看不见。`use-event-stream.ts` 的 `KNOWN_EVENT_NAMES` 改为与 `catalog.EVENT_TYPES` 双向字节一致，Python 侧加两项漂移测试，前端加"每个订阅事件都有中文标签"的穷举断言（当场补出 6 个 HPO/锦标赛标签） | `.venv/Scripts/python.exe -m pytest tests/webapi/test_engine_catalog.py -q` → 21 passed；`npx --no-install vitest run` 全绿（见 D6.4e 行） | `95d25c4` | 通过 |
| 2026-10-08 | D6.5（产品路径去 showcase） | 删除 `features/showcase/` 四页＋`hdd-showcase-data.ts`＋其 fixture 测试；四个运行页面去掉 `SHOWCASE_RUN_ID` 分支；总览渲染 `/api/runs` 全部条目、任务卡直接来自 `/api/tasks`；`RunLayout` 统一渲染 run 标题/状态/全部页签；`scripts/e2e_serve.py` 改按四个具名 fixture 复制、`demo_run_ids=[]`；E2E-01 定位器由已失效的「打开回放」改为运行行的「查看证据」 | `npx --no-install vitest run` → **39 files / 752 passed \| 3 skipped**；`npx --no-install eslint src e2e` → 0 error（1 个既有 warning）；`npx --no-install vite build` → 退出码 0；顺手修掉既有的 `components/ui/input.tsx` 空接口 lint 错误 | `f3e8259` | 通过（该提交同时清掉了 App.test.tsx 的既有红） |
| 2026-10-08 | D6.4e（契约再生成与前端检查门） | 按 D7.2 的顺序跑前端链路；E2E 门本身先是死的：1.11 合并把 `@playwright/test` 从 devDependencies 里丢了，脚本还在 | ①`npx --no-install pnpm sync:contracts` → **退出码 9009**（脚本调裸 `python`，本机解析到 Windows Store 占位程序）→ 拆成等价两步：`.venv/Scripts/python.exe scripts/export_web_contracts.py`（4 文件）＋`npx --no-install openapi-ts`（4 文件，227 ms），随后 `git status` 为空；②`check_web_contracts.py` → `contract check OK: 4 files match the Python source`；③`tsc --noEmit` → 退出码 0；④`vitest run` → 752 passed \| 3 skipped（39 文件）；⑤`eslint src e2e` → 0 error；⑥`vite build` → 退出码 0（433 ms，仅既有 872.81 kB 分块警告）；⑦补回 `@playwright/test@1.55.0`（离线 store 已有该版本，chromium-1187 也在本机缓存里，无需下载）后 `npx --no-install pnpm test:e2e` → 退出码 0，**76 passed**（2.4m） | `49b830d`；日志 `C:\tmp\s6\gates\e2e_full_pass1.log` | 通过 |
| 2026-10-08 | D6.4e（缺陷与修复：E2E 门不可运行） | 首次 E2E 尝试 `npx --no-install playwright test …` 报"不是内部或外部命令"：`node_modules/.bin/playwright` 不存在，因为依赖被合并提交移除（lockfile 里也没有）。`pnpm-lock.yaml` 与 `package.json` 补回 `1.55.0`（`pnpm install --offline`，1.3s） | `node node_modules/@playwright/test/cli.js --version` → `Version 1.55.0`；随后 E2E-01 单跑 1 passed（9.6s）、全量 76 passed | `49b830d` | 通过 |
| 2026-10-08 | D6.4e（缺陷与修复：60 个视觉用例全红在一次定位器上） | 首次全量 E2E：**61 failed / 15 passed**。60 项失败同为 `getByRole('button', { name: '设置' })` 命中两个按钮（顶栏「设置」与侧栏「项目设置」）的 strict mode 违例；第 61 项是三岛概览用例里 `getByText('7')` 同时命中"尝试"与"树内节点"两个 7 | 修法：前者 `exact: true`；后者给树内节点值加 `data-island-tree-count`（沿用卡上 `data-island-best` 的惯例）。修后全量 **76 passed**（2.4m） | `49b830d` | 通过（原失败计数保留在本行） |
| 2026-10-08 | D6 收尾（webapi 与针对性复跑） | 最终代码上复跑 S6 相关集合 | `.venv/Scripts/python.exe -m pytest tests/webapi -q` → **413 passed**（44.07s）；`… tests/webapi/test_run_discovery.py tests/webapi/test_replay_islands.py tests/webapi/test_replay_exchange.py tests/webapi/test_engine_catalog.py -q` → **62 passed**（8.22s）；`… tests/test_island_forest_export.py tests/test_build_run_fixture.py -q` → **10 passed**（5.01s） | `49b830d` | 通过 |
| 2026-10-08 | D6 收尾（截图人工验收） | 逐张看 `web/test-results/visual/1440x900/light/` 下五个画面，核对布局与数字来源 | 见 S6 勾选项与 F 段：三岛概览/岛树/交换详情/历史单树/空态全部符合预期，无横向溢出、无 `role="alert"`（60 项截图用例各自断言过） | `49b830d` | 通过；下一步 S7 |
| 2026-10-08 | D6 阶段门＝S6 阶段门 | 全仓库离线套件，19:10:47 启动，工作树即 9c1ee7f（启动时无未提交改动）；S7 的三份源文件与三份测试文件于收集之后的 19:13–19:18 才落盘，因此本次进程内用例跑的是收集时点的 9c1ee7f 源码与用例集，仅晚段子进程用例可能读到 S7 源码；S7 终态由 S7 阶段门另行全量覆盖。版本注：A 段本机行原写「`.venv` Python 3.13」，本轮实测 `.venv/Scripts/python.exe --version` → **Python 3.12.4**（Anaconda 基底，venv 建于 2026-10-05），3.13 系误写，第 854 行与 A1 表头已就地更正 | `.venv/Scripts/python.exe -m pytest tests/ -q`（仓库根）→ 退出码 0，**1796 passed / 0 failed**（945.78s，19:26:30）＝S5 门 1730＋66；净增按文件实测归因：tests/webapi ＋56（run_discovery 14、replay_islands 16、replay_exchange 11、fixture_island_run 12、replay_runs 净 +1、engine_catalog 19→21）＋`test_island_forest_export.py` 5＋`test_build_run_fixture.py` 5；既有 1730 项无回归 | `C:\tmp\s6\gates\pytest_s6_full.txt`（2059 字节，全点无 F/E） | S6 阶段门通过；下一步 S7（D7） |

S7 追加行（2026-10-08，接 S6 阶段门之后）：

| 时间 | 步骤编号 | 执行动作/修改文件 | 验证命令和退出码 | 产物/提交 | 状态与下一步 |
|---|---|---|---|---|---|
| 2026-10-08 | D7.1（S4 补测①：T09 null 预算引擎运行级续跑） | 新增 `tests/test_island_resume.py::test_a_resume_without_a_token_cap_keeps_spending`：去掉 token 上限后中断续跑，断言仍继续花费、引擎未早停；反向 mutation M2 把 `cap is None` 当"已达上限"处理（改 `budget.py`） | `.venv/Scripts/python.exe -m pytest tests/test_island_resume.py -q` → **40 passed**；M2 下 **1 failed / 39 deselected**（2.59s），断言 `tests/test_island_resume.py:480`（`RunMetrics` 未增长）；`restore` 后 engine/budget/autotune 三个文件 byte-identical | `d26c532`；日志 `C:\tmp\s7\gates\mutations_s7.log`、`pytest_targeted_s7.txt` | 通过 |
| 2026-10-08 | D7.1（S4 补测②：重建不评估的字面 mutation 不可表达，改以引擎级孪生用例关闭） | 逐行确认 `rebuild_run_report()` 的调用树（`export_forest`／`get_cost_rollup`／`island_report`）无评估器引用，"把它改成会重新评估"没有可落点；可证伪的缝在续跑路径持有评估器处：新增 `tests/test_island_fault_injection.py::test_resuming_a_finished_run_rewrites_a_lost_report_without_evaluating`（续跑重写丢失报告不得再调评估器）；M1 mutant 让续跑重跑一个 iteration（改 `engine.py`） | `.venv/Scripts/python.exe -m pytest tests/test_island_fault_injection.py -q` → **11 passed**；M1 下 **1 failed / 10 deselected**（5.28s），`tests/test_island_fault_injection.py:399`（`_call_count` 4≠3）；`restore` 后 byte-identical | `d26c532`；日志 `C:\tmp\s7\gates\mutations_s7.log` | 通过（字面 mutation 不可表达一事按实记录，理由见 D7.1 处置说明） |
| 2026-10-08 | D7.1（S4 补测③：`CostLedger.totals()` 改从 `cost_ledger` 行重放） | `optimization/ledger.py` 新增 `CostLedger.restore_rows()`（逐行重建含 seq／island_id／meta）；`engine_autotune.init_ledger()` 与 `engine.rebuild_run_report()` 都从 `cost_ledger` 行重放（后者以一次性 `CostLedger().restore_rows()` 产出 `summary["cost_ledger_totals"]`，`if ledger_rows` 守卫）；新增 `tests/test_autotune_ledger.py::test_l9_a_resumed_ledger_counts_the_rows_the_previous_process_wrote`；M3a 续跑时丢弃行（改 `engine_autotune.py`）、M3b 重建不投影账本视图（改 `engine.py`） | `.venv/Scripts/python.exe -m pytest tests/test_autotune_ledger.py -q` → **5 passed**；M3a → **1 failed / 4 deselected**（2.34s，`tests/test_autotune_ledger.py:132`）；M3b → **1 failed / 4 deselected**（2.25s，`KeyError: 'cost_ledger_totals'`@128）；两次 `restore` 后 byte-identical | `d26c532`；日志 `C:\tmp\s7\gates\mutations_s7.log` | 通过 |
| 2026-10-08 | D7.1（S4 补测④：决定不从库重建评估侧计数） | 源码核对：`RunMetrics.invalid_count` 含尝试级失败（`engine.py:2660/2706/2738/2753/2769/2791/2835/2850` 的 `add_eval(0, False)` 无对应可评估行）；`jev_calls` 是本进程计数（`engine.py:2990`），JEV provider 默认 `"none"`（`config.py:288`）；运行摘要 `valid_count` 是节点派生 `len(scored)`（`engine.py:4612`）——三者都没有精确的库侧重建来源，强行重建会引入与内存口径不一致的第三个数；岛上真值 `valid_evaluations／invalid_evaluations` 本就持久化（`common/schemas.py:405-406`）并已恢复 | 本行无独立命令：结论来自逐处源码核对（位置如上）；进程内计数不重建的边界如实写入 F 段，不伪称"已重建" | 无提交（决策行） | 通过（决策＋理由） |
| 2026-10-08 | D7.1（针对性离线复跑：五文件切片） | `tests/test_island_resume.py`＋`test_island_fault_injection.py`＋`test_autotune_ledger.py`＋`test_island_cost.py`＋`test_island_exchange.py` | `.venv/Scripts/python.exe -m pytest tests/test_island_resume.py tests/test_island_fault_injection.py tests/test_autotune_ledger.py tests/test_island_cost.py tests/test_island_exchange.py -q` → 退出码 0，**86 passed**（39.32s）＝resume 40＋fault_injection 11＋autotune_ledger 5＋cost 8＋exchange 22（D4.4 五点复跑即 fault_injection 全部 11 项） | 日志 `C:\tmp\s7\gates\pytest_targeted_s7.txt`（首部含工作目录/日期 19:36:13/Python 3.12.4） | 通过 |
| 2026-10-08 | D7.2（前端链路七步，终态树 `123ac28`） | 按顺序：export→check→tsc→vitest→eslint→build→e2e；环境记录 node v24.13.0／pnpm 10.33.0 | ①`export_web_contracts.py` 4 文件（含 `ui-metadata.json` 52227 字节）与已入库逐字节一致；②`contract check OK: 4 files match the Python source`；③tsc EXIT=0；④vitest **39 files／752 passed \| 3 skipped (755)**（13.17s）；⑤eslint 0 error（1 个既有 TopBarBadges warning）；⑥`vite build` ✓ 396ms（872.89 kB 既有 chunk warning）；⑦e2e **76 passed**（2.1m）。更正：第 4/6/7 步原 `EXIT=` 取自管道末端 `tail`，19:58 起不经管道复核 → vitest EXIT=0（12.53s）／build EXIT=0（368ms）／e2e EXIT=0（76 passed，2.0m） | `123ac28`；日志 `C:\tmp\s7\gates\frontend_chain_s7_final.log`＋`{vitest_s7_final.txt,build_s7_final.txt,e2e_s7_final.txt}`＋`versions_s7.log` | 通过（管道 EXIT 取值缺陷已更正并复跑） |
| 2026-10-08 | D7.2（E2E 覆盖与截图人工验收） | `pnpm test:e2e` 全量 76 项：三视口×明暗×十画面视觉回归＋三岛形态（岛卡、六交换计数、岛筛选收窄）＋单树形态（21 节点、六层带、显著性四档、双亲标记、修复链抽屉）＋历史单树明说无岛记账＋空态/错误态；运行于临时根 `C:\Users\ADMINI~1\AppData\Local\Temp\fe_e2e_h60hmlgm`（API 8011／web 4318），未触碰服务器真实运行目录；复跑前杀掉遗留 dev server（node.exe PID 27404 占 4318），避免 `reuseExistingServer` 静默连错后端 | 见上行第 ⑦ 项；截图核对：`web/test-results/visual/1440x900/light/{overview,islands-overview,island-tree,exchange-detail,empty-state}.png`＋`C:\tmp\s7\gates\runs-list-scrolled.png`（本地 dev 栈读 `tests/fixtures/runs`：4 条运行 `hdd_mvp_demo_7510f100`／`hdd_mvp_faildemo_4b81c0d2`／`hdd_mvp_islands_15l4nd01`／`hdd_mvp_showcase_c89e2a01`）——布局、读数与设计一致，无横向溢出 | `123ac28` | 通过 |
| 2026-10-08 | D7.3（diff 与受保护路径核对） | `git diff --check`；对照 S6 门提交 `83535ef` 的全部改动范围；`benchmark/`、`tests/fixtures/`、`knowledge/`、`docs/design/` 逐一 diff；密钥/产物形状扫描 | `git diff --check` 退出码 0；vs `83535ef` 改动＝8 个文件（`cloud/engine.py`、`cloud/engine_autotune.py`、`optimization/ledger.py`、`webapi/catalog.py`、三个测试文件、`web/openapi/ui-metadata.json`）；`git diff 83535ef -- benchmark/ tests/fixtures/ knowledge/ docs/design/` 为空；扫描仅命中测试代码里的临时库名 `fe.db`（无密钥） | 日志 `C:\tmp\s7\gates\diff_checks_s7.log` | 通过 |
| 2026-10-08 | D7.1（S6→S7 遗留：`islands.stagnation_request_evals` 处置） | 决定：不接线（需求文档对"停滞/求助"确为 0 命中）、不删字段（避免破坏配置面），如实改标签：`catalog.py` 该行改为「停滞求助间隔（引擎未读取）」＋说明"该字段当前没有引擎调用点；接入前配置它不会有任何效果"；重导 `ui-metadata.json`（仅 2 行变化，52227 字节），`web/` 无任何读取点（grep 0 命中） | `check_web_contracts.py` → `contract check OK`；`.venv/Scripts/python.exe -m pytest tests/webapi/test_contract_stability.py tests/webapi/test_engine_catalog.py -q` → **33 passed**（6.56s） | `123ac28`；日志 `C:\tmp\s7\gates\catalog_relabel_s7.log` | 通过（D3.3 勾选项继续按"未接线"保留未勾） |
| 2026-10-08 | D7 阶段门＝S7 阶段门 | 冻结工作树＝`83535ef`＋8 文件脏 diff（指纹 sha256 `9abb0241…`，19:39:06 留档）；全仓库离线套件 | `.venv/Scripts/python.exe -m pytest tests/ -q`（仓库根）→ 退出码 0，**1799 passed / 0 failed**（894.00s，19:39:09→19:54:04）＝S6 门 1796＋3（三个新用例）；既有 1796 项无回归；19:34 首跑因回填期补落 `catalog.py` 修正于 16% 处主动停止，残余输出改名 `pytest_s7_full_aborted.txt`（不作证据） | `C:\tmp\s7\gates\pytest_s7_full_final.txt`；冻结指纹 `tree_fingerprint_s7.txt` | S7 阶段门通过；提交 `d26c532`＋`123ac28`；下一步 S8（D8） |
| 2026-10-08 | D8.1（冻结与唯一时间戳） | 核实本地分支干净与远端一致；选定时间戳 `20261008-200410`，核实部署根不存在后创建 | `git status --short` 空、`git rev-parse HEAD`＝`7687df2c562cf2cca5258effffe225600cb60024`、`git ls-remote --heads origin` 同 SHA；服务器 `test -e` 确认新目录原不存在 | manifest `$TM/preflight/run_manifest.json`（`code_status_porcelain: <clean>`）；`$TM`＝`/home/hcf/faultevolve/three_island_20261008-200410` | 通过 |
| 2026-10-08 | D8.2（完整 bundle＋clone） | 本机 `git bundle create`（complete history）→ `git bundle verify` → `scp` 到 `/tmp/`；服务器 `git clone --branch codex/three-island-real-runs <bundle> $TM/code` | 各步退出码 0 后才继续；bundle sha256 本地/服务器同为 `93469ba9c3de7427c54369cfa6885c32551b09a3143bd72610c8ad582b1d5c18`（61814410B）；服务器 HEAD `7687df2c…`、`git status --porcelain` 空 | `$TM/code`（旧目录 `/home/hcf/faultevolve/code` 未动，HEAD 仍 `dcd2283e…`） | 通过 |
| 2026-10-08 | D8.3（布局、权限探针、独立环境） | 创建 `preflight/{runs,artifacts}` 分家根；`$TM/evidence/.perm_probe_1791463033` 创建→列举→删除；`python -m venv` 建独立 `.venv`＋`pip install -r requirements.txt`＋`pip install -e .` | 探针创建/删除成功且复查不存在；Python 3.13.11；pip 退出码 0、冻结 48 包 | `pip_requirements.log`/`pip_editable.log`/`requirements_frozen_preflight.txt` | 通过 |
| 2026-10-08 | D8.4（数据指纹与 doctor） | 逐一列举六个允许文件并计算 sha256；运行 `fe doctor --task-dir benchmark/hdd_mvp --config-file $TM/deployment/preflight_evolve.yaml --env-file /home/hcf/faultevolve/.env` | doctor 17 项全 ✓ 除 `FE_API_KEY not set`（Web 专用）；退出码 1（仅因该缺项）；`adapter hdd -> HDDAdapter`；`islands on: 3 tree(s) … exchange every 1 attempts` | 六个指纹入 manifest；doctor 输出存 `$TM/evidence/`；`holdout` 未列举/读取 | 通过 |
| 2026-10-08 | D8.5（外置配置与启动命令） | 部署 `preflight_evolve.yaml`（与本地同源 sha256 `9be62749…`）；保存 resolved 配置 `350df2ee…`；按 `fe evolve local --help` 组装启动命令 | 各键与计划一致（3 岛 ×2、interval 1、并发 1、budget null、judge none）；无 placeholder | A1「服务器预检启动」行；resolved 摘要存证据目录 | 通过 |
| 2026-10-08 | D8.6（启动、观测、完成） | `nohup .venv/bin/fe evolve local … -n 6 --runs-dir $TM/preflight/runs --artifacts-dir $TM/preflight/artifacts --run-id hdd_mvp_preflight_20261008`；PID 1011543；20:07:36→20:32:08 | 控制台尾部 `Evolution completed: finished / Best score: 38.21`；DB `status=finished`、6 iterations、best `4c1635ca` 38.2067（Δ+15.3993）；13 LLM 调用全 ok、5 次评估器执行、10 投递/11 采用可追溯；mock 扫描三处全 0 | artifacts 三文件＋`fe.db` 458752B＋console 日志；汇总 `$TM/evidence/` | 通过（退出码不可回取，如实记录；S9 启动器包裹 `$?`） |
| 2026-10-08 | D8.6（自然失败记录，不重试） | a 岛候选 `4e6045f9`（语法错误→`invalid_generation`）与 `c91350ce`（`smoke_rejected`）均未进入评估；b 岛 `4c1635ca` 一次 `smoke_failed`→pandas `to_numeric` 修复成功（`smoke_fix_success`）；`7361c1f3`（Δ-17.449）与 `0d7fdc94`（Δ-7.249）`hypothesis_refuted` | 事件计数：`invalid_generation` 2、`smoke_failed` 1、`smoke_fix_success` 1、`perf_self_fix_success` 1、`hypothesis_refuted` 2；smoke_tests 7 / failures 2 / fixes 1 | 失败证据在 `events.jsonl`＋`fe.db`；未另建 run ID（失败为引擎内自然产生且已被自愈/淘汰，不属“预检流程失败需重试”） | 通过 |
| 2026-10-08 | S8 回填（本文件＋Skill 页面） | 勾选 S8/D8 全部方框并写证据；A1/A2/B/D/E/F 回填；`references/hdd-server.md` 写回三处实际做法（完整历史 bundle＋`git clone --branch`／独立 `.venv`／`preflight` 分家根）；Skill 两类测试复跑 | `.venv/Scripts/python.exe -m pytest tests/test_island_skill.py tests/test_island_skill_walkthrough.py -q` → **50 passed**，退出码 0（日志 `C:\tmp\s8\gates\pytest_skill_s8.txt`） | 回填提交（docs-only，SHA 见 git log；服务器运行代码仍为 `7687df2c`） | 通过；下一步 S9 |

### A1. 实际命令表（不得保留假参数）

| 用途 | 工作目录/环境 | 已验证的完整命令（密钥仅变量名） | 对应 SHA/日志 |
|---|---|---|---|
| 本地针对性测试 | `C:/Users/Administrator/faultevolve`，`.venv` Python 3.12.4（Windows） | `.venv/Scripts/python.exe -m pytest tests/test_island_contract.py -q`（仓库根，密钥不参与） | 3d498e7；32 passed / 0 failed |
| 本地三岛验收集合 | 同上，仓库根 | `.venv/Scripts/python.exe -m pytest tests/test_island_isolation.py tests/test_engine.py tests/test_island_contract.py -q` | 151a806；16 passed＋46 passed（两批，退出码 0） |
| 本地摘要交换验收集合 | 同上，仓库根 | `.venv/Scripts/python.exe -m pytest tests/test_island_exchange.py tests/test_island_isolation.py -q` | 2f368fa；38 passed / 0 failed（19.25s，退出码 0）；9592fe7 时为 36 passed |
| 本地知识注入验收集合 | 同上，仓库根 | `.venv/Scripts/python.exe -m pytest tests/test_island_knowledge.py -q` | bd76846；9 passed / 0 failed（6.32s，退出码 0） |
| 本地成本账本验收集合 | 同上，仓库根 | `.venv/Scripts/python.exe -m pytest tests/test_island_cost.py -q`；回归集合 `.venv/Scripts/python.exe -m pytest tests/test_autotune_ledger.py tests/test_island_contract.py tests/test_island_cost.py tests/test_island_exchange.py tests/test_island_isolation.py tests/test_island_knowledge.py tests/test_llm.py tests/test_metering.py tests/test_operators_bandit.py tests/test_store.py tests/test_adapters.py tests/webapi -q` | 0eac985；8 passed（6.08s）；回归 526 passed / 0 failed（61.48s，退出码 0） |
| 本地故障注入验收集合 | 同上，仓库根 | `.venv/Scripts/python.exe -m pytest tests/test_island_fault_injection.py -q`；岛屿＋webapi 七项集合 `.venv/Scripts/python.exe -m pytest tests/test_island_fault_injection.py tests/test_island_exchange.py tests/test_island_resume.py tests/test_island_cost.py tests/test_island_isolation.py tests/test_island_knowledge.py tests/webapi -q`；D4 回归集合（13 文件＋`tests/webapi`）`.venv/Scripts/python.exe -m pytest tests/test_autotune_ledger.py tests/test_island_contract.py tests/test_island_cost.py tests/test_island_exchange.py tests/test_island_fault_injection.py tests/test_island_isolation.py tests/test_island_knowledge.py tests/test_island_resume.py tests/test_llm.py tests/test_metering.py tests/test_operators_bandit.py tests/test_store.py tests/test_adapters.py tests/webapi -q` | 971f38e；9 passed（11.03s）；七项集合 460 passed（106.88s）；D4 回归 574 passed / 0 failed（89.86s，退出码 0）。全部离线：临时库＋`FakeAdapter`＋MockLLM，不碰 `benchmark/hdd_mvp/data/` |
| 本地全量离线门 | 同上，仓库根 | `.venv/Scripts/python.exe -m pytest tests/ -q` | 151a806；1588 passed / 0 failed（822.68s），日志 `/tmp/s2_full5.log`。2f368fa（S3 代码收尾）：1610 passed / 0 failed（828.25s，退出码 0），日志 `/tmp/s3_full2.log`。91c8203（D4.3 收尾）：1666 passed / 0 failed（856.07s），日志 `/tmp/s4_full1.log`。971f38e（**S4 阶段门**）：**1675 passed / 0 failed**（1067.28s，退出码 0），日志 `/tmp/s4_full2.log`。df8a346→b6b6241→6f0fb04→f21af80→6daa23c（**S5 阶段门**）：**1730 passed / 0 failed**（925.27s，退出码 0），日志 `C:\tmp\s5\gates\pytest_s5_full.txt`。9c1ee7f（**S6 阶段门**）：**1796 passed / 0 failed**（945.78s，退出码 0），日志 `C:\tmp\s6\gates\pytest_s6_full.txt`。`83535ef`＋`d26c532`/`123ac28` 的合并内容（冻结工作树指纹 sha256 `9abb0241…`）（**S7 阶段门**）：**1799 passed / 0 failed**（894.00s，退出码 0，19:39:09→19:54:04），日志 `C:\tmp\s7\gates\pytest_s7_full_final.txt` |
| 契约再生成与漂移检查 | 同上，仓库根 + `web/` | `.venv/Scripts/python.exe scripts/export_web_contracts.py`；`.venv/Scripts/python.exe scripts/check_web_contracts.py`；`pnpm --dir web generate:api`；`pnpm --dir web typecheck`；`pnpm --dir web test` | 151a806；`contract check OK: 4 files match the Python source`，generated 无 diff，tsc 退出码 0。971f38e 重跑（新增 `exchange_delivery_backfilled`）：同样退出码 0、`src/generated` 无 diff、tsc 0；`pnpm --dir web test` → 退出码 1，`Tests 1 failed \| 660 passed \| 3 skipped (664)`（既有 SmartMem 用例，见 F 段，归 S6） |
| Skill 步骤 2：配置预检（本机，含岛环与适配器） | `C:/Users/Administrator/faultevolve`，`.venv`（控制台脚本 `.venv/Scripts/fe.exe`） | `fe doctor --task-dir tests/fixtures/toy_task --config-file C:\tmp\s5\cfg\drill.yaml --json` | 6daa23c；退出码 1（`all_ok: false` 仅因 `env_DASHSCOPE_API_KEY`/`env_MIYANG_API_KEY`/`env_FE_API_KEY` 三项未设，属预期），`task_files`／`task_adapter`／`config_keys`／`config_islands` 均 `ok: true`，岛环消息逐字 `islands on: 3 tree(s) [a:performance, b:miss_alert, c:efficiency], exchange every 1 attempts`；日志 `C:\tmp\s5\gates\doctor_drill.txt`。HDD 形状配置的预检：`fe doctor --task-dir benchmark/hdd_mvp --config-file C:\tmp\s5\cfg\preflight.yaml --json` → 退出码 1，`config_keys`／`config_islands` ok、`task_data` 指向 `benchmark\hdd_mvp\data\public`（日志 `doctor_config.txt`，f21af80 时实测）。拒绝路径：`--config-file` 缺 `--task-dir`、配置文件不存在 → 各退出码 2（`doctor_no_taskdir.txt`／`doctor_missing_cfg.txt`） |
| Skill 步骤 3：三岛离线演练（本机） | 同上，仓库根 | `fe evolve local tests/fixtures/toy_task --mock -n 6 --config-file C:\tmp\s5\cfg\drill.yaml --runs-dir C:\tmp\s5\runs_a1 --artifacts-dir C:\tmp\s5\art_a1 --json` | 6daa23c；退出码 0，`experiment_id 497713ef`、`iterations_done 6`、`best_score 24.9`，`run_summary.json` 119 键：三岛各 2 次尝试、`exchange.summaries 6`、成本自洽（日志 `C:\tmp\s5\gates\rehearsal_a1.txt`）。Skill 输出契约里那份数字来自更早一次 16 轮演练 `2ab57008`（f21af80） |
| Skill 步骤 7：只读重建报告（本机） | 同上，仓库根 | `fe evolve local tests/fixtures/toy_task --mock --report-only --resume 497713ef --runs-dir C:\tmp\s5\runs_a1 --artifacts-dir C:\tmp\s5\art_a1b --json` | 6daa23c；退出码 0，重建报告 12 键，`islands`／`exchange`／`cost` 与实时报告逐字段相等、`rebuilt_from_store: true`（日志 `C:\tmp\s5\gates\rebuild_a1.txt`）；同一语义由 `tests/test_island_skill_walkthrough.py::test_the_report_can_be_rebuilt_from_the_database_without_new_scores` 钉住 |
| Skill 漂移与端到端走查测试（本机） | 同上，仓库根 | `.venv/Scripts/python.exe -m pytest tests/test_island_skill.py tests/test_island_skill_walkthrough.py -q`；S5 切片加跑 `.venv/Scripts/python.exe -m pytest tests/test_island_skill.py tests/test_island_skill_walkthrough.py tests/test_doctor_task_checks.py tests/test_island_fault_injection.py -q` | f21af80＋6daa23c＋6de9707；单跑 43 passed（0.26s）与 7 passed（11.10s／删未用形参后 11.46s），合跑 50 passed；S5 切片 69 passed（19.56s，退出码 0）。反向 mutation（写错默认值、插入假参数）见 A0 的 D5.2 行 |
| S6 发现层与回放（本机，实测） | `C:/Users/Administrator/faultevolve`，`.venv` | `.venv/Scripts/python.exe -m pytest tests/webapi -q`；S6 切片 `.venv/Scripts/python.exe -m pytest tests/webapi/test_run_discovery.py tests/webapi/test_replay_islands.py tests/webapi/test_replay_exchange.py tests/webapi/test_engine_catalog.py -q`；fixture 侧 `.venv/Scripts/python.exe -m pytest tests/test_island_forest_export.py tests/test_build_run_fixture.py -q` | 49b830d（终态复跑）；**413 passed**（45.83s）、**62 passed**（8.00s）、**10 passed**（4.67s），退出码均 0；日志 `C:\tmp\s6\gates\{pytest_webapi_s6_final.txt,pytest_s6_slice_final.txt,pytest_forest_fixture_final.txt}` |
| 契约再生成与前端检查门（S6，本机） | 仓库根＋`web/` | 失败路径 `npx --no-install pnpm sync:contracts` → 退出码 9009（脚本调裸 `python`，本机解析到 Windows Store 占位程序）；等价两步 `.venv/Scripts/python.exe scripts/export_web_contracts.py`（4 文件）＋`npx --no-install openapi-ts`（4 文件，221ms），随后 `git status` 无生成文件改动；`.venv/Scripts/python.exe scripts/check_web_contracts.py` → `contract check OK: 4 files match the Python source` | 49b830d；契约 1.12.0→1.13.0 的生成文件已入库，再生成无漂移；日志 `C:\tmp\s6\gates\contracts_s6_final.log` |
| 前端离线门（S6，本机） | `C:/Users/Administrator/faultevolve/web` | `npx --no-install tsc --noEmit`；`npx --no-install vitest run`；`npx --no-install eslint src e2e`；`npx --no-install vite build` | 49b830d；tsc 退出码 0；vitest 39 files / **752 passed \| 3 skipped**（15.51s）；eslint 0 error（1 个既有 warning）；build 退出码 0（438ms）；日志 `C:\tmp\s6\gates\frontend_chain_s6_final.log` |
| E2E 门（S6，本机） | `C:/Users/Administrator/faultevolve/web` | `npx --no-install pnpm install --offline`（补回 `@playwright/test@1.55.0`，1.3s，无下载）；`node node_modules/@playwright/test/cli.js --version` → `Version 1.55.0`；`npx --no-install pnpm test:e2e`（Playwright 自行拉起 `scripts/e2e_serve.py --port 8011` 与 `pnpm dev --port 4318 --host 127.0.0.1`） | 49b830d；**76 passed**（2.4m，退出码 0）；日志 `C:\tmp\s6\gates\e2e_full_pass1.log` |
| 三岛 fixture 生成（本机） | 仓库根，`.venv` | `.venv/Scripts/python.exe scripts/make_island_demo_run.py --no-install --exchange-interval 2`（→ applications 10）；`.venv/Scripts/python.exe scripts/make_island_demo_run.py --no-install --exchange-interval 1`（＝脚本默认；→ applications 12，即入库那份）；`… --check`（只校验九项形状门） | 0808f94；种子 7、18 轮，两次演练输出留档；日志 `C:\tmp\s6\gates\island_fixture_dryrun{,_i1}.txt` |
| 反向 mutation（S6 发现层，本机） | 仓库根，`.venv` | `.venv/Scripts/python.exe C:\tmp\s6\mutate_discovery.py M1_pairing_off／M2_merge_any_pair／M3_depth_bound_off／M4_origin_by_name／M5_no_marker_gate` → `… -m pytest tests/webapi/test_run_discovery.py -q` → `… mutate_discovery.py restore` | 49b830d（回填期复跑）；M1/M2 2 failed、M3 3 failed、M4/M5 10 failed，恢复后 14 passed；日志 `C:\tmp\s6\gates\mutations_discovery.log`；详见 A0 的 D6.2 行 |
| 服务器预检启动 | 服务器 `$TM/code`（独立 `.venv`，Python 3.13.11）；`HDD_BENCH_DATA_ROOT=/home/hcf/nas_hcf_data/faultevolve/data/hdd_mvp` | `cd $TM/code && HDD_BENCH_DATA_ROOT=/home/hcf/nas_hcf_data/faultevolve/data/hdd_mvp nohup .venv/bin/fe evolve local benchmark/hdd_mvp --config-file $TM/deployment/preflight_evolve.yaml --env-file /home/hcf/faultevolve/.env -n 6 --runs-dir $TM/preflight/runs --artifacts-dir $TM/preflight/artifacts --run-id hdd_mvp_preflight_20261008 > $TM/preflight/console_preflight.log 2>&1 & echo $! > $TM/preflight/pid.txt`（`$TM`＝`/home/hcf/faultevolve/three_island_20261008-200410`；密钥仅经 `--env-file` 注入，不出现在命令行） | `7687df2c`（运行代码）；run `hdd_mvp_preflight_20261008`，PID 1011543，20:07:36→20:32:08，best 38.2067；日志 `$TM/preflight/console_preflight.log`，证据汇总 `$TM/evidence/` |
| 服务器正式启动 | 待填 | 待填 | 待填 |
| 恢复指定 run | 本机选项形式见下两行（副本恢复／只重建报告） | 服务器端命令未实测执行——S8 预检一次跑完、无中断，未发生恢复；不用假命令填坑，S9 如中断按 `--resume`＋`--resume-from` 形式执行并回填 | 91c8203：`fe evolve local … --resume ID [--resume-from 源目录 --runs-dir 新家]` 与 `--report-only` 已在本机离线实测；服务器真实运行至今没有发生过需要恢复的中断 |
| Web API / 前端启动 | 待填 | 待填 | 待填 |
| 本次服务停止 | 待填 | 待填 | 待填 |
| 本机访问转发 | 待填 | 待填 | 待填 |
| 报告/经验 Skill 导出（本机，实测） | `C:/Users/Administrator/faultevolve`，`.venv` | `.venv/Scripts/python.exe skill/fe-island-evolution/scripts/export_experience_skill.py <runs>/<exp_id>/fe.db <artifacts>/<exp_id>/run_summary.json --task-dir <task_dir>`；竞赛指标复核 `.venv/Scripts/python.exe skill/fe-evolve-manager/scripts/report_run.py <runs>/<exp_id>/fe.db <artifacts>/<exp_id>/run_summary.json` | 6daa23c；导出对演练运行 `497713ef` → 退出码 0、`rules: 6`，`experience_skill_draft.md` 与 `evidence_index.json` 写入 `<artifacts>/497713ef/skills/`（日志 `C:\tmp\s5\gates\export_a1.txt`）；`--help` → 退出码 0（`export_help_a1.txt`）；零交换运行 → `rules: 0` 且草稿写“未得到可泛化规则”（`zero_draft.txt`，运行 `664800e6`）；`--out-dir` 指向项目 `skill/` → 退出码 2（`export_refused.txt`）；`report_run.py` 对同一次演练 → 退出码 0（`report_run_a1.txt`，该脚本属 `fe-evolve-manager`，本轮未改） |
| 旧运行副本恢复（本机，选项形式） | `C:/Users/Administrator/faultevolve`，`.venv` Python 3.12.4 | `fe evolve local <task_dir> --mock -n <N> --resume <RUN_ID> --resume-from <RUNS_DIR>/<RUN_ID> --runs-dir <NEW_HOME>`（`--resume-from` 必须配 `--resume`；源目录与目标同目录直接拒绝） | 91c8203；选项组合与断言经 `typer.testing.CliRunner` 实测（`tests/test_island_resume.py::test_resume_from_continues_a_copy_and_leaves_the_original_files_alone`、`::test_resume_from_a_directory_the_run_would_write_into_is_refused`），shell 端真实 HDD 副本恢复命令属 S8/S9；`fe evolve local --help` 已确认 `--resume-from` 存在 |
| 只重建报告（本机，选项形式） | 同上 | `fe evolve local <task_dir> --resume <RUN_ID> --report-only --runs-dir <RUNS_DIR>`（不调评估器、不调 LLM、不产生新分数） | 91c8203；`tests/test_island_resume.py::test_report_only_writes_a_missing_report_from_the_database`、`::test_the_copy_and_rebuild_switches_name_a_run_that_has_to_exist`；`--help` 已确认 `--report-only` 存在 |

命令不得包含密钥明文。配置与脚本路径必须存在；未实现参数不能填为已验证。说明暂停/停止与删除产物不同，交付后保留产物。

### A2. 阶段汇总

| 步骤 | 状态 | 提交 SHA | 证据/阻塞 |
|---|---|---|---|
| S0 归档与环境 | 通过 | 924f9fc（分支基点）/ 归档 0655afe | 远端 `git ls-remote` 已核实；服务器只读检查见 S0 证据表；阻塞（已于 S8 解除：经授权 `.env` 以 `--env-file` 注入、只输出布尔，见 S0 阻塞项行） |
| S1 契约 | 通过 | 3d498e7 | tests/test_island_contract.py 32 passed；契约再生成并通过 test_contract_stability；typecheck 通过 |
| S2 三树 | 通过 | 151a806 | `tests/test_island_isolation.py` 16 passed（T04–T08＋D2.5/D2.6 附加项）；全量 `pytest tests/ -q` 1588 passed / 0 failed（822.68s，`/tmp/s2_full5.log`）；`check_web_contracts.py` 与 `pnpm --dir web typecheck` 退出码 0；`git status` 确认 `benchmark/hdd_mvp/*` 与 fixture 未改动。过程中两次全量失败已按 A0 记录并修复（含 legacy `island_id=""` 构造断裂）。真实三岛运行证据属 S8/S9，本阶段仅离线 |
| S3 交换 | 通过 | 9592fe7（实现）＋2f368fa（整段预算修复） | `tests/test_island_exchange.py` 22 passed：正/负摘要进入兄弟岛生成上下文、外岛源码不进提示（DTO 无 code 字段＋`_exchange_summary_section` 边界文案）、`get_node_parents()==[]` 无第二亲本、application 记接收岛自己的分而非来源分、投递/采用/应用/评估四轴分开计数、过时最佳与跨任务指纹被拒且原因落库、摘要通道异常不动评估器分数。全量门 1610 passed / 0 failed（`/tmp/s3_full2.log`）；`check_web_contracts.py` 与 `pnpm --dir web typecheck` 退出码 0，9 个交换事件已归进既有 12 粗类。未勾选保留项：D3.3 的“停滞求助”（`stagnation_request_evals` 仍为纯配置，无调用点）。交换层零 LLM 调用，成本不变；真实三岛正/负摘要事件数量属 S8/S9，本阶段仅离线 |
| S4 知识/恢复 | 阶段门通过（D4.1–D4.4 完成；一条既有未独立实测项保持未勾选） | bd76846（D4.1）＋0eac985（D4.2）＋91c8203（D4.3）＋971f38e（D4.4） | 离线证据：`tests/test_island_knowledge.py` 9 passed、`tests/test_island_cost.py` 8 passed、`tests/test_island_resume.py` 39 passed、`tests/test_island_fault_injection.py` 9 passed；D4 回归集合（13 文件＋`tests/webapi`）574 passed / 0 failed（89.86s，退出码 0）；S4 阶段门全量 `pytest tests/ -q` → **1675 passed / 0 failed**（1067.28s，`/tmp/s4_full2.log`）＝S3 门 1610＋D4.1 9＋D4.2 8＋D4.3 39＋D4.4 9，无回归；`check_web_contracts.py` 与 `pnpm --dir web typecheck` 退出码 0，`src/generated` 无 diff，`pnpm --dir web test` 仍是既有 1 项失败（App.test.tsx，见 F 段，归 S6）。本阶段发现并修复两处真实缺陷：`cost_ledger` 恢复时 seq 冲突（0eac985）、摘要已落库却永不投递（971f38e 的 `backfill_deliveries()`）。未勾选保留项：S4 第 104 行"冻结知识库只读＋建议/确认分开"作为独立验收项仍未单独实测。范围边界（不构成 S4 失败，但不得写成已完成）：中断是可控 fake 异常而非真实 kill；`CostLedger.totals()` 仍只汇总当前进程的内存记录，重建/续跑摘要里的该项不含上一进程的记录（持久事实在 `cost_ledger` 行与 `get_cost_rollup`）；墙钟预算每进程重新计时；评估侧计数不从库重建；幂等重放未实现；`IslandStatus` 无中断态。真实三岛运行的中断/恢复证据属 S8/S9，本轮不得据离线绿测宣称恢复已在生产环境验证 |
| S5 Skill | 阶段门通过（D5.1–D5.4 完成并勾选；两条验收项按理由保留未勾选） | df8a346（产物契约投影）＋b6b6241（逐岛成本进产物）＋6f0fb04（doctor 解析要跑的配置）＋f21af80（Skill 本体＋导出脚本＋两类测试）＋6daa23c（零交换走查用例）＋6de9707（删该用例未使用的形参） | 交付 `skill/fe-island-evolution/`：`SKILL.md` 224 行＋`references/{configuration,exchange,hdd-server,recovery}.md`（110/77/204/95 行）＋`scripts/export_experience_skill.py`（413 行，仅 stdlib、只读 URI 打开库）；README 技能索引加一行、`skill/fe-evolve-manager/SKILL.md` 加分工段并原样保留其旧运行 `--resume`。输入契约取自任务适配器而非 HDD 字段；主指标按引擎事实写成“唯一标量 `combined_score`、总是越大越好，越小越好的指标由适配器转换”。需求 §6“仅写 SKILL.md 或仅通过结构校验不算完成”按可执行测试落实（仓库无 skill lint，已逐条确认）：`tests/test_island_skill.py` 43 项核对参数、事件名、配置默认值、岛状态字面量、相对链接与通用层的主机路径/密钥形状；`tests/test_island_skill_walkthrough.py` 7 项按步骤 2/3/7/8 在 `famou` toy 任务上真跑（T24，全程无 SMART/ROS 字段）；两处反向 mutation 证明断言会失败。文档自纠四处保留原始写法（`islands.specs:`、`stop.max_iterations:`、投递/采纳/应用混写、`stagnation_request_evals` 当成生效字段）。S5 阶段门 `.venv/Scripts/python.exe -m pytest tests/ -q` → **1730 passed / 0 failed**（925.27s，退出码 0，`C:\tmp\s5\gates\pytest_s5_full.txt`）＝S4 门 1675＋55。**故意未勾选两项**：S5 第 5 项（真实运行的经验草稿——至今没有一次真实三岛运行，属 S9）、第 7 项（服务器实跑沿用该入口，属 S8/S9）。范围边界：`references/hdd-server.md` 只写主机事实与命令模板并标注 S8/S9 未执行；导出产物是 `draft_not_cross_run_verified` 草稿，规则须第二次运行复现才可升级；`islands.stagnation_request_evals` 引擎不读（全 `src/` 检索），已在文档标注为死配置（接入或从界面移除归 S6/S7）；`CostLedger.totals()` 仍只汇总本进程内存记录，跨进程事实在 `cost_ledger` 行与 `get_cost_rollup`，恢复参考已如实写明 |
| S6 Web | 通过 | `24438c9`（发现层）＋`08f9d2e`（islands 分组）＋`dcc2fc5`（森林导出＋摘要连接键）＋`0808f94`（三岛 fixture）＋`95d25c4`（前端三岛）＋`f3e8259`（去 showcase）＋`49b830d`（E2E 门可运行且全绿） | 发现层 `webapi/run_discovery.py`（产物标记识别、深度 4／访问 20 000／错误清单 200 三重上限、软链只登记、库＋报告配对、来源按证据：fixture 根／运行登记表／unverified）＋`GET /api/runs/provenance` 可对账计数；回放层 islands/exchange 投影＋森林导出与摘要连接键修复；契约 1.12.0／1.13.0 重导无漂移；三岛 fixture `hdd_mvp_islands_15l4nd01`（真实引擎＋真实评估器、仅 LLM mock）；前端三岛概览/岛树/交换详情/全局最优/历史单树/空态；E2E 门复活。终态数字：`.venv/Scripts/python.exe -m pytest tests/webapi -q` → **413 passed**（45.83s）；S6 webapi 切片 **62 passed**（8.00s）；森林/建 fixture **10 passed**（4.67s）；`tsc --noEmit`／`eslint`／`vite build` 退出码 0、vitest **752 passed \| 3 skipped**；`npx --no-install pnpm test:e2e` → **76 passed**（2.4m）；日志 `C:\tmp\s6\gates\{pytest_webapi_s6_final.txt,pytest_s6_slice_final.txt,pytest_forest_fixture_final.txt,contracts_s6_final.log,frontend_chain_s6_final.log,e2e_full_pass1.log}`。S6 阶段门 `pytest tests/ -q` → **1796 passed / 0 failed**（945.78s，退出码 0，`C:\tmp\s6\gates\pytest_s6_full.txt`）＝S5 门 1730＋66（tests/webapi +56、森林导出 5、建 fixture 5，按文件实测），既有 1730 项无回归。**边界**：fixture 是离线 mock（候选 0.30~0.36 全不超初始 22.8074），只证明三岛编排与界面读数正确，不证明算法提升；真实运行证据属 S8/S9；`CostLedger.totals()` 与 `islands.stagnation_request_evals` 的处置 S6 未做，转 S7（见 F 段） |
| S7 离线检查 | 通过 | `d26c532`（`CostLedger.restore_rows()` 行重放＋两个引擎级补测）＋`123ac28`（死配置标签如实化） | 三个新用例：T09 null 预算引擎运行级续跑（`test_island_resume.py::test_a_resume_without_a_token_cap_keeps_spending`）、重建不评估的引擎级孪生（`test_island_fault_injection.py::test_resuming_a_finished_run_rewrites_a_lost_report_without_evaluating`）、续跑账本跨进程重放（`test_autotune_ledger.py::test_l9_a_resumed_ledger_counts_the_rows_the_previous_process_wrote`）；四个反向 mutation M1／M2／M3a／M3b 全部咬住并 byte-identical 恢复（日志 `C:\tmp\s7\gates\mutations_s7.log`）；针对性切片 **86 passed**（39.32s，含 D4.4 五点复跑）；S7 阶段门 `pytest tests/ -q` → **1799 passed / 0 failed**（894.00s，退出码 0，19:39:09→19:54:04）＝S6 门 1796＋3，无回归（`C:\tmp\s7\gates\pytest_s7_full_final.txt`）；前端链路七步在终态树 `123ac28` 全部退出码 0（契约再生成字节一致、`contract check OK`、tsc 0、vitest **752 passed \| 3 skipped**、eslint 0 error、build ✓、e2e **76 passed**；管道 EXIT 缺陷已更正复跑）；`git diff --check` 0、受保护路径（benchmark／tests/fixtures／knowledge／docs/design）diff 为空、无密钥。**边界**：本轮全部证据离线（mock／fixture／临时运行根），真实三岛运行证据属 S8/S9；`--report-only` 重建报告仍不含 `stop_reason` 的既有边界未变；评估侧计数不从库重建为已记录决策（`invalid_count` 含尝试级失败、`jev_calls` 进程内、摘要 `valid_count` 为节点派生，无精确重建来源）；`islands.stagnation_request_evals` 以"不接线＋如实标注（引擎未读取）"处置，D3.3 勾选项保持未勾 |
| S8 真实预检 | 通过 | `7687df2c`（运行代码；回填提交为 docs-only，SHA 见 git log） | run `hdd_mvp_preflight_20261008`（2026-10-08 20:07:36→20:32:08 +08:00）：三岛各 2 尝试、`exchange_interval=1`、并发 1；真实 LLM＋真实 evaluator（13 次 LLM 调用全 ok、5 次评估器执行），mock 扫描三处全 0；best `4c1635ca` 38.2067（初始 22.8074，Δ+15.3993）；5 摘要/10 投递/11 采用/2 交叉节点（关键链路 `sum-3b709a88`→`dlv-ce915ea4`→`app-d1a808ad`→`f0cd9659` 36.6104）；tokens 76499、费用未知（`cost_basis=unknown`，不以 token 猜费用）；自然失败全部如实保留（invalid 2／smoke_failed→fix 1／hypothesis_refuted 2）；退出码不可回取（启动未包裹 `$?`），完成证据＝控制台尾部＋DB `status=finished`，S9 启动器改为捕获 `$?`。完整证据见 S8 节、D8.1–D8.6、B/D/E 段 |
| S9 正式运行 | 未执行 | 待填 | 待填 |
| S10 PR/交付 | 未执行 | 待填 | 待填 |

### B. 分支与部署

| 项目 | 实际值 |
|---|---|
| 归档基点与远端归档 SHA | 基点 `0655afec4a62fc403d1f5ec564ca49f457d90cb6`；远端归档分支 `codex/webui-demo-archive` SHA `0655afe`（S0 已核实并推送，未强推） |
| 实现分支 SHA / PR / 合并 SHA | `codex/three-island-real-runs` @ `7687df2c562cf2cca5258effffe225600cb60024`（本地＝远端；服务器预检运行代码即此 SHA）；回填 docs-only 提交追加于其上；PR 未创建（属 S10） |
| 服务器代码路径与 SHA | `/home/hcf/faultevolve/three_island_20261008-200410/code`，HEAD `7687df2c562cf2cca5258effffe225600cb60024`，`git status --porcelain` 空；旧目录 `/home/hcf/faultevolve/code` 未动（HEAD `dcd2283e6396fc70f60678319a7549d404970bad`） |
| 数据路径及允许文件指纹清单 | `HDD_BENCH_DATA_ROOT=/home/hcf/nas_hcf_data/faultevolve/data/hdd_mvp`；六文件 sha256：`meta.json b573de80…`、`train_history.csv.gz f033f35b…`、`train_labels.csv 64b79841…`、`val_history.csv.gz 0b8e75b4…`、`val_index.csv 9abf34bc…`、`eval_only/val_labels.csv 60c1647a…`（完整值和大小在 `$TM/preflight/run_manifest.json`）；评估器 `cddfaaab…`、init `91744b4b…`；`holdout` 从未列举/读取/指纹 |
| 新运行根 / 数据库 / artifacts / 日志 / 索引 | 运行根 `$TM/preflight/runs`，库 `$TM/preflight/runs/hdd_mvp_preflight_20261008/fe.db`（458752B，wal 0）；artifacts `$TM/preflight/artifacts/hdd_mvp_preflight_20261008/{run_summary.json,tree.json,events.jsonl}`；日志 `$TM/preflight/console_preflight.log`；索引待 S9 Web 构建（`$TM/web/` 已建待用） |
| 环境、模型标识与配置哈希 | Python 3.13.11（独立 `.venv`，48 包冻结）；生成 `qwen3-coder-plus`＋反思 `qwen3-max` @ `https://dashscope.aliyuncs.com/compatible-mode/v1`；config `9be62749…`、resolved `350df2ee…`、bundle `93469ba9…`、evaluator `cddfaaab…`、init `91744b4b…`、seed 20260926；不含密钥 |
| Web 地址、端口、启停和访问方式 | 待填 |
| 真实运行索引数量 / fixture 排除数 / 待核实或异常数 | 待填 |

### C. 测试记录

每次失败后保留原记录并追加修复后的记录，不覆盖历史。

另逐行填写 T01–T26 与实际测试函数的映射：每行包含用例编号、测试文件/函数、执行时间、SHA、PASS/FAIL/未测及日志。没有实际映射的用例不得仅在汇总里写“全覆盖”。

| 时间 | 代码 SHA | 精确命令/工作目录 | 结果和退出码 | 日志位置 | 失败处理 |
|---|---|---|---|---|---|
| 2026-10-08 | 工作树（提交 151a806 前） | `.venv/Scripts/python.exe -m pytest tests/ -q`；`C:/Users/Administrator/faultevolve` | 6 failed / 1579 passed；退出码 1（862.82s） | `/tmp/s2_full2.log` | 核心模块禁用词命中注释 `serial` → 改写注释；`test_engine_resume_continues_same_tree`、契约陈旧、事件目录缺类型 → 逐条修复 |
| 2026-10-08 | 工作树（提交 151a806 前） | 同上 | 4 failed / 1583 passed；退出码 1（872.55s） | `/tmp/s2_full3.log` | 余 `test_adapters` 禁用词、`test_engine` 恢复断言、`test_contract_stability` 两项 → 见下一行 |
| 2026-10-08 | 工作树（中止） | 同上 | 约 25% 处人工中止（改动使结果失效，不作为门） | `/tmp/s2_full4.log` | 重启全量 |
| 2026-10-08 | 151a806 | `.venv/Scripts/python.exe -m pytest tests/test_island_isolation.py -q`；仓库根 | 16 passed / 0 failed；退出码 0（12.41s） | 终端输出（本阶段 S2 验收集合） | — |
| 2026-10-08 | 151a806 | `.venv/Scripts/python.exe -m pytest tests/test_engine.py tests/test_island_contract.py -q` | 46 passed；退出码 0（9.58s） | 同上 | legacy `island_id=""` 构造断裂的回归位 |
| 2026-10-08 | 151a806 | `.venv/Scripts/python.exe -m pytest tests/webapi/ tests/test_adapters.py tests/test_run_stall_guard.py tests/test_hotfix_3_1.py -q` | 395 passed；退出码 0（39.10s） | 同上 | — |
| 2026-10-08 | 151a806 | `.venv/Scripts/python.exe scripts/export_web_contracts.py && .venv/Scripts/python.exe scripts/check_web_contracts.py` | 导出 4 文件；`contract check OK: 4 files match the Python source`；退出码 0 | 同上 | `evolve-config.schema.json` 随 IslandSpec 描述变更重导出 |
| 2026-10-08 | 151a806 | `pnpm --dir web generate:api`；`pnpm --dir web typecheck`；`pnpm exec vitest run src/features/workbench/event-taxonomy.test.ts`（`web/`） | 生成 0 diff；tsc 退出码 0；6 passed | 同上 | — |
| 2026-10-08 | 151a806 | `.venv/Scripts/python.exe -m pytest tests/ -q`；仓库根 | **1588 passed / 0 failed**；退出码 0（822.68s） | `/tmp/s2_full5.log` | S2 阶段门通过 |
| 2026-10-08 | 工作树（提交 9592fe7 前） | `.venv/Scripts/python.exe -m pytest tests/test_island_exchange.py -q`；仓库根 | 7 failed / 13 passed；逐条改断言过程中再跑为 5 failed / 15 passed；两次退出码均为 1 | 终端输出 | 五条都是**测试断言口径错**而非实现错：① 期望“全场只有 1 条最佳摘要”，实际 B 在接受 A 的摘要后也会宣布自己的基线最佳（两作者各一条，属正确的多岛语义）→ 按 `source_island_id=="a"` 作用域取；② T12 原断言“标记必须出现在 A 自己的提示里”按构造不成立（标记是在 A 的尝试之后植入的）→ 改为断言标记确实存在于已发布摘要的 `source_node_id` 节点代码，并同时检查 B 的全部提示与 B 树内所有节点代码都无该标记；③ T14 少把 e 列为投递目标，读者自然为空 → 补目标；④ 同一错误复现实验里第二条 `_invalid` 被 A 的 repair 链消耗，第二次尝试产出的是有效候选 → 改为每条候选后配一条修复结果，并把 `occurrences` 断言放宽为 `>=2`；⑤ legacy 单岛 `island_id` 写成 `"default"`，实际是 `""` → 用 `engine._coordinator.order[0]` |
| 2026-10-08 | 工作树（提交 9592fe7 前） | 同上，单例复查 `::test_a_positive_summary_reaches_the_sibling_prompt_and_is_evaluated_locally`、`::test_a_repeat_of_the_same_error_adds_evidence_instead_of_a_second_message` | 两次各 1 failed；退出码 1 | 终端输出 | 复现出两条真实的实现缺陷：① 有效评估链里 repair 节点也报同类错误，但 `_unpublished_failures()` 只取生成式无效候选（正确，避免把一次失败的两次尝试当成两条独立结论），断言据此重写；② 重复结论命中去重时只追加证据、**不刷新 metrics**，读者会看到“同类出现 1 次”的旧计数 → `store.add_summary_evidence()` 增加 `metrics` 参数并随新证据写入 `metrics_json` |
| 2026-10-08 | 工作树（提交 9592fe7 前） | `.venv/Scripts/python.exe -m pytest tests/test_island_exchange.py tests/test_island_isolation.py -q` | 36 passed；退出码 0（15.32s） | 终端输出 | S3 交换集合与 S2 隔离集合同时绿（隔离未回归） |
| 2026-10-08 | 工作树（提交 9592fe7 前） | `.venv/Scripts/python.exe -m pytest tests/ -q -x --ignore=tests/webapi` | 1251 passed / 0 failed；退出码 0（793.93s） | 终端输出 | `tests/webapi`（357 项）另计，见下一行；两批相加 1608＝S2 的 1588＋S3 新增 20 项 |
| 2026-10-08 | 9592fe7 | `.venv/Scripts/python.exe -m pytest tests/webapi -q` | 首轮 2 failed / 355 passed；退出码 1（`test_contract_stability.py` 两项：`web/openapi/engine-catalog.json` 落后于新增的 9 个事件类型） | 终端输出 | `.venv/Scripts/python.exe scripts/export_web_contracts.py`（4 文件）＋`pnpm --dir web generate:api`（`src/generated` 无 diff）＋`scripts/check_web_contracts.py` 退出码 0 → 重跑 357 passed / 0 failed |
| 2026-10-08 | 9592fe7 | `pnpm --dir web test`；`pnpm --dir web typecheck`；`C:/Users/Administrator/faultevolve/web` | vitest 660 passed / 1 failed（既有 `src/app/App.test.tsx` SmartMem 用例，见 F 段）；`tsc --noEmit` 退出码 0 | 终端输出 | 事件分类漂移测试通过，证明 12 粗类与 `catalog.EVENT_TYPES` 一致；既有失败不在本阶段修复 |
| 2026-10-08 | 9592fe7（中止记录） | `.venv/Scripts/python.exe -m pytest tests/ -q`；仓库根 | 约 40% 处人工中止，结果不作为门 | `/tmp/s3_full1.log`（空） | 同一阶段随后的 D3.1 修复（2f368fa）使该次运行失效，按 2f368fa 重跑 |
| 2026-10-08 | 2f368fa | `.venv/Scripts/python.exe -m pytest tests/test_island_exchange.py -q`（先只跑新加的用例） | 1 failed / 21 passed；退出码 1 | 终端输出 | `sanitize()` 把先 join 再清洗的多段正文当作一条超长行**整段丢弃**（`len(clean)==0`）→ 改为按 `\n`/`；` 切段计数（2f368fa） |
| 2026-10-08 | 2f368fa | `.venv/Scripts/python.exe -m pytest tests/test_island_exchange.py tests/test_island_isolation.py -q` | 38 passed；退出码 0（19.25s） | 终端输出 | S3 交换 22 项＋S2 隔离 16 项 |
| 2026-10-08 | 2f368fa | `.venv/Scripts/python.exe -m pytest tests/ -q`；仓库根 | **1610 passed / 0 failed**；退出码 0（828.25s） | `/tmp/s3_full2.log` | S3 阶段门通过（较 S2 门 1588 净增 22 项，即 `tests/test_island_exchange.py`） |
| 2026-10-08 | 工作树（提交 91c8203 前） | `.venv/Scripts/python.exe -m pytest tests/test_island_resume.py -q`；仓库根 | 首跑 1 failed / 37 passed（`assert ['task_fp'] == []`）；退出码 1（14.15s） | 终端输出 | `_verify_run_identity()` 的"无身份记录"分支补上 `task_fingerprint(experiment)` 比对后，该用例的旧断言（`verified == []`）不再成立——是代码终于做了注释承诺的事；断言改为 `["task_fp"]`，并新增 `test_a_run_without_an_identity_record_still_refuses_a_changed_task` 钉住"无记录仍拒换任务、且拒绝时不补写记录"。第二次运行为 1 failed / 38 passed（`assert ''`）：新增的拒绝用例把原成功续跑用例的尾部断言（"记录已补写"）错接了过来，两条语义相反，把该断言移回续跑用例并改为从全新连接读回 → 39 passed |
| 2026-10-08 | 91c8203 | `.venv/Scripts/python.exe -m pytest tests/test_island_resume.py -q` | **39 passed / 0 failed**；退出码 0（14.21s） | 终端输出 | 身份 12 项（含 2 项纯函数）、成本 5 项、状态与 deferred 6 项、归属 6 项、报告 2 项、副本 4 项、CLI 4 项，合计 39；全部离线（临时库＋`FakeAdapter`＋MockLLM），不碰 `benchmark/hdd_mvp/data/` |
| 2026-10-08 | 91c8203 | `.venv/Scripts/python.exe -m pytest tests/test_island_contract.py tests/test_island_cost.py tests/test_island_exchange.py tests/test_island_isolation.py tests/test_island_knowledge.py -q`；仓库根 | 87 passed；退出码 0（36.01s） | 终端输出 | S1–S4 既有五集合未回归（加 `test_island_resume.py` 的 39 项即 126 项岛验收集合） |
| 2026-10-08 | 91c8203 | `.venv/Scripts/python.exe -m pytest tests/test_island_resume.py tests/test_engine.py -q` | 53 passed；退出码 0（25.18s） | 终端输出 | 引擎既有恢复用例（legacy 单岛、三岛不新增根）在身份校验与声明机制下仍通过 |
| 2026-10-08 | 91c8203 | `.venv/Scripts/python.exe -m pytest tests/test_autotune_ledger.py tests/test_island_contract.py tests/test_island_cost.py tests/test_island_exchange.py tests/test_island_isolation.py tests/test_island_knowledge.py tests/test_island_resume.py tests/test_llm.py tests/test_metering.py tests/test_operators_bandit.py tests/test_store.py tests/test_adapters.py tests/webapi -q` | **565 passed / 0 failed**；退出码 0（93.66s） | 终端输出 | D4.2 时的同一验收集合（当时 526）＋D4.3 的 39 项 |
| 2026-10-08 | 工作树（提交 91c8203 前） | `.venv/Scripts/python.exe -m pytest tests/ -q`；仓库根 | 1 failed / 1665 passed；退出码 1（887.18s） | 终端输出 | `tests/test_discovery_preflight_crash_fix.py::test_discover_factors_writes_error_txt_on_failure`——该用例的 `runner.invoke` 未打 `create_benchmark_adapter` 补丁，`discover factors` attach 到 mock 运行时用的是真实 HDD 适配器，任务与初始代码指纹不符，被本轮新增的 `ResumeRefused` 在先，error.txt 内容是拒绝消息而非预期的 `synthetic boom`；判定为测试环境错（拒绝本身是 D4.3 要的行为），补补丁后 12 passed |
| 2026-10-08 | 91c8203 | `.venv/Scripts/python.exe -m pytest tests/ -q`；仓库根 | **1666 passed / 0 failed**；退出码 0（856.07s） | `/tmp/s4_full1.log` | D4.3 收尾全量（非 S4 阶段门，阶段门待 D4.4 后重跑）＝S3 门 1610＋D4.1 9＋D4.2 8＋D4.3 39，无回归 |
| 2026-10-08 | 91c8203 | `.venv/Scripts/python.exe scripts/export_web_contracts.py`；`scripts/check_web_contracts.py`；`pnpm --dir web generate:api`；`pnpm --dir web typecheck`；`pnpm --dir web test`；仓库根＋`web/` | `contract check OK: 4 files match the Python source`；`src/generated` 无 diff；tsc 退出码 0；vitest 1 failed / 660 passed / 3 skipped（12.36s） | 终端输出 | 三个新事件归入既有 `run_state` 粗类，12 类漂移测试通过；失败仍是既有 `src/app/App.test.tsx > 应用外壳 > 评委总览只呈现可用的 HDD 任务入口`（F 段，归 S6） |
| 2026-10-08 | 971f38e | `.venv/Scripts/python.exe -m pytest tests/test_island_fault_injection.py -q`；仓库根 | **9 passed / 0 failed**；退出码 0（11.03s） | 终端输出 | 首跑即绿（新文件写完后没有实现侧失败）；五组分别对应计划的五个中断点，全部离线（临时库＋`FakeAdapter`＋MockLLM），不碰 `benchmark/hdd_mvp/data/` |
| 2026-10-08 | 工作树（提交 971f38e 前，反向 mutation ①） | 去掉 `checkpoint()` 里的 `backfill_deliveries()` 调用后：`.venv/Scripts/python.exe -m pytest tests/test_island_fault_injection.py tests/test_island_exchange.py -q`；仓库根 | 3 failed / 28 passed；退出码 1（26.07s） | 终端输出 | 失败正是三种"摘要已落库未投递"断言（补齐数、恢复轮修复、目标作用域），证明补齐逻辑不是被别的用例顺带满足；还原后 9 passed |
| 2026-10-08 | 工作树（提交 971f38e 前，反向 mutation ②） | `_pending_summary_applications()` 改为返回 `{}` 后：`.venv/Scripts/python.exe -m pytest tests/test_island_fault_injection.py tests/test_island_resume.py -q`；仓库根 | 2 failed / 46 passed；退出码 1（30.86s） | 终端输出 | 一条来自新文件（中断后未完成的 application 不再重挂），一条是 D4.3 既有的 `test_an_application_recorded_before_the_crash_still_gets_its_result`——两种中断共用同一重挂逻辑，还原后两文件全绿 |
| 2026-10-08 | 工作树（提交 971f38e 前，反向 mutation ③） | `_prepare_runtime()` 归一化范围加入 PAUSED（等价于中断后把暂停岛误置为 running）后：`.venv/Scripts/python.exe -m pytest tests/test_island_fault_injection.py -q`；仓库根 | 2 failed / 7 passed；退出码 1（11.72s） | 终端输出 | 失败为"暂停态与自身计数跨重启原样回来"与"兄弟岛不给停着的岛派活"两条，正是计划要求的"B 不被无意重置为 running" |
| 2026-10-08 | 工作树（提交 971f38e 前，反向 mutation ④） | `init_ledger()` 的 `start_seq` 固定为 0 后：`.venv/Scripts/python.exe -m pytest tests/test_island_fault_injection.py -q -k "ledger or request"`；仓库根 | 1 failed / 1 passed / 7 deselected；退出码 1（5.83s） | 终端输出 | 失败信息 `sqlite3.IntegrityError: UNIQUE constraint failed: cost_ledger.experiment_id, cost_ledger.seq`（`src/faultevolve/cloud/store.py:1973`）——续跑确实会撞已落库的 seq，`max_cost_seq()` 接续不是多余的防御；四处 mutation 全部还原后 `git status --short` 只剩 D4.4 的五个文件 |
| 2026-10-08 | 971f38e | `.venv/Scripts/python.exe -m pytest tests/test_island_fault_injection.py tests/test_island_exchange.py tests/test_island_resume.py tests/test_island_cost.py tests/test_island_isolation.py tests/test_island_knowledge.py tests/webapi -q`；仓库根 | 460 passed / 0 failed；退出码 0（106.88s） | 终端输出 | 新增的 `checkpoint()` 前置补齐调用不回归既有交换/恢复/成本/隔离/知识／webapi |
| 2026-10-08 | 971f38e | `.venv/Scripts/python.exe -m pytest tests/test_autotune_ledger.py tests/test_island_contract.py tests/test_island_cost.py tests/test_island_exchange.py tests/test_island_fault_injection.py tests/test_island_isolation.py tests/test_island_knowledge.py tests/test_island_resume.py tests/test_llm.py tests/test_metering.py tests/test_operators_bandit.py tests/test_store.py tests/test_adapters.py tests/webapi -q`；仓库根 | **574 passed / 0 failed**；退出码 0（89.86s） | 终端输出 | D4 回归集合（D4.3 时 565）＋D4.4 的 9 项 |
| 2026-10-08 | 971f38e | `.venv/Scripts/python.exe scripts/export_web_contracts.py`；`scripts/check_web_contracts.py`；`pnpm --dir web generate:api`；`pnpm --dir web typecheck`；`pnpm --dir web test`；仓库根＋`web/` | `contract check OK: 4 files match the Python source`；`engine-catalog.json` 重导（7304 字节）；`src/generated` 无 diff；tsc 退出码 0；vitest `Test Files 1 failed \| 37 passed (38)`、`Tests 1 failed \| 660 passed \| 3 skipped (664)` | 终端输出 | `exchange_delivery_backfilled` 归入既有 `insight` 粗类，事件分类漂移测试通过（仍是 12 类）；失败仍是既有 `src/app/App.test.tsx > 应用外壳 > 评委总览只呈现可用的 HDD 任务入口`（F 段，归 S6），本阶段不修复 |
| 2026-10-08 | 971f38e | `.venv/Scripts/python.exe -m pytest tests/ -q`；仓库根 | **1675 passed / 0 failed**；退出码 0（1067.28s） | `/tmp/s4_full2.log` | **S4 阶段门通过**＝S3 门 1610＋D4.1 9＋D4.2 8＋D4.3 39＋D4.4 9，无回归；下一步 S5 |
| 2026-10-08 | 工作树（提交 f21af80 前） | `.venv/Scripts/python.exe -m pytest tests/test_island_skill.py -q`；仓库根 | 首跑 2 failed / 41 passed；退出码 1 | 终端输出 | 失败在事件名检查：正则 `"type": "([a-z_\|]+)"` 漏掉文档里 `"(a\|b\|c)"` 的括号，取到空集合——靠函数内 `assert names` 立即失败而不是空清单静默通过；改正则为 `"type": "\(([a-z_\|]+)\)"` 后 43 passed（0.26s） |
| 2026-10-08 | 工作树（提交 f21af80 前） | `.venv/Scripts/python.exe -m pytest tests/test_island_skill_walkthrough.py -q`；仓库根 | 首跑 1 failed（断言 `evidence["run_id"]`，索引实际键名是 `experiment_id`；同用例的 `sanitization` 全等断言又因该字典含 `summary_text_max_chars: 400` 失败）；次跑 1 failed（断言草稿含“仅凭一次”，脚本原文是“单凭一次运行无法区分”）；两次退出码均为 1 | 终端输出 | 两条都是测试自身写错而非实现缺陷：改按实测键名与三个 `is False` 断言、按脚本原文改措辞 → 6 passed（11.6s） |
| 2026-10-08 | 工作树（提交 f21af80 前，反向 mutation） | ①`configuration.md` 把 `exchange_interval` 默认写成 `6` 后 `.venv/Scripts/python.exe -m pytest tests/test_island_skill.py -q -k defaults`；②SKILL.md 演练命令插入假参数 `--island-workers 3` 后 `... -q -k flags`；仓库根 | ①退出码 1，**1 failed / 42 deselected**；②退出码 1，**1 failed / 9 passed / 33 deselected**（`test_documented_fe_flags_are_real_cli_flags`） | 终端输出 | 两处还原后 43 passed；`grep -rn island-workers` 无残留，证明文档与测试都回到实测状态 |
| 2026-10-08 | 6daa23c／6de9707 | `.venv/Scripts/python.exe -m pytest tests/test_island_skill_walkthrough.py -q`；仓库根 | 新增第 7 条 `test_a_run_that_exchanged_nothing_delivers_facts_instead_of_rules` 后 7 passed（11.10s）；删去该用例未使用的 `skill_config` 形参后复跑 7 passed（11.46s）；退出码均 0 | 终端输出 | 零交换运行（`exchange_interval: 10`、`-n 3`）实测 `exchange.summaries == 0`、`rule_count == 0`，草稿仍逐岛给出尝试/有效评估数与三个 profile |
| 2026-10-08 | 6daa23c | `.venv/Scripts/python.exe -m pytest tests/test_island_skill.py tests/test_island_skill_walkthrough.py -q`；`.venv/Scripts/python.exe -m pytest tests/test_island_skill.py tests/test_island_skill_walkthrough.py tests/test_doctor_task_checks.py tests/test_island_fault_injection.py -q`；仓库根 | 50 passed；退出码 0；S5 切片 **69 passed**（19.56s）；退出码 0 | `C:\tmp\s5\gates\s5_slice.txt` | Skill 两类测试与 D5.1 的 doctor／故障注入集合同时无回归 |
| 2026-10-08 | 6daa23c | `fe doctor --task-dir tests/fixtures/toy_task --config-file C:\tmp\s5\cfg\drill.yaml --json`；`fe evolve local tests/fixtures/toy_task --mock -n 6 --config-file … --json`；`… --mock --report-only --resume 497713ef --json`；`.venv/Scripts/python.exe skill/fe-island-evolution/scripts/export_experience_skill.py …`；`.venv/Scripts/python.exe skill/fe-evolve-manager/scripts/report_run.py …`；仓库根 | 退出码依次 1（缺模型密钥，属预期）、0、0、0、0；演练得到 `497713ef`（三岛各 2 次尝试、`exchange.summaries 6`、`total_tokens 3050`），重建 12 键且三块与实时逐字段相等，导出 `rules: 6` | `C:\tmp\s5\gates\{doctor_drill,rehearsal_a1,rebuild_a1,export_a1,report_run_a1}.txt` | 三条拒绝路径退出码均为 2（`doctor_no_taskdir.txt`、`doctor_missing_cfg.txt`、`export_refused.txt`）；同一 doctor 用 HDD 形状配置跑 toy 目录时 `task_data` 确实变 false（`doctor_toy_s5.txt`） |
| 2026-10-08 | 6daa23c | `.venv/Scripts/python.exe -m pytest tests/ -q`；仓库根 | **1730 passed / 0 failed**；退出码 0（925.27s） | `C:\tmp\s5\gates\pytest_s5_full.txt` | **S5 阶段门通过**＝S4 门 1675＋doctor 4＋故障注入 1＋Skill 43＋走查 7；收集时第 7 条走查用例尚未提交（后以 6daa23c 提交；6de9707 只删该用例未使用的形参，两者都不改变计数）。下一步 S6 |
| 2026-10-08 | 工作树（提交 dcc2fc5 前） | `.venv/Scripts/python.exe -m pytest tests/test_island_forest_export.py -q`；仓库根 | 首跑 1 failed / 4 passed；退出码 1（4.38s） | `C:\tmp\s6\gates\pytest_forest_export.txt`、`…_export2.txt` | `rebuild_run_report(Store(str(db_path), read_only=True), …)` → `AttributeError: 'str' object has no attribute 'exists'`（只读分支直接对入参调 `Path` 方法）→ `cloud/store.py` 先归一化为 `Path`，重跑 5 passed（4.35s） |
| 2026-10-08 | 工作树（提交 dcc2fc5 前） | `.venv/Scripts/python.exe -m pytest tests/webapi/test_replay_exchange.py -q`；仓库根 | 首跑 1 failed / 10 passed（`test_a_single_tree_run_has_no_exchange_layer` 断言 `missing` 实得 `available`）；中途 1 failed / 26 passed；退出码 1 | `C:\tmp\s6\gates\pytest_exchange_*.txt` | 修后 32 passed（7.96s）；同批 `pytest tests/webapi -q` → 389 passed（52.14s） |
| 2026-10-08 | 工作树（D6.4 前端收尾） | `npx --no-install vitest run`；`web/` | 1 failed / 660 passed / 3 skipped（既有 `src/app/App.test.tsx > 评委总览只呈现可用的 HDD 任务入口`）→ D6.3 收尾 1 failed / 663 passed；退出码 1 | `C:\tmp\s6\gates\vitest_after_graft.txt`、`vitest_exchange.txt` | 该既有失败随 D6.5（`f3e8259`）移除产品路径 showcase 后消失：`vitest run` → 39 files / **752 passed \| 3 skipped**（15.51s），退出码 0 |
| 2026-10-08 | 工作树（D6.4e） | `npx --no-install pnpm sync:contracts`；`web/` | 退出码 9009（脚本调裸 `python`，本机解析到 Windows Store 占位程序） | 终端输出 | 拆成两步等价命令 `.venv/Scripts/python.exe scripts/export_web_contracts.py`＋`npx --no-install openapi-ts` → 退出码 0、`git status` 无生成文件改动；`check_web_contracts.py` → `contract check OK: 4 files match the Python source`；49b830d 回填期复跑日志 `C:\tmp\s6\gates\contracts_s6_final.log` |
| 2026-10-08 | 工作树（D6.4e，E2E 首跑） | `npx --no-install pnpm test:e2e`；`web/` | **61 failed / 15 passed**；退出码 1 | 终端输出（失败明细在终端） | 60 项死于 `getByRole('button', { name: '设置' })` strict mode 违例（顶栏「设置」＋侧栏「项目设置」）→ `exact: true`；第 61 项是三岛概览用例 `getByText('7')` 同时命中「尝试」「树内节点」→ 给树内节点值加 `data-island-tree-count` 钩子；修后 **76 passed**（2.4m，退出码 0），日志 `C:\tmp\s6\gates\e2e_full_pass1.log` |
| 2026-10-08 | 工作树（E2E 依赖缺失） | `npx --no-install playwright test …`；`web/` | 报「不是内部或外部命令」：`node_modules/.bin/playwright` 不存在（1.11 合并提交把 `@playwright/test` 从 devDependencies 移除，lockfile 里也没有） | 终端输出 | `package.json`＋`pnpm-lock.yaml` 补回 `@playwright/test@1.55.0`（`pnpm install --offline`，1.3s：离线 store 已有该版本、chromium-1187 本机已缓存）→ `Version 1.55.0`、E2E-01 单跑 1 passed（9.6s）→ 全量 76 passed |
| 2026-10-08 | 49b830d（回填期复跑） | 五个 mutant 逐个 `.venv/Scripts/python.exe C:\tmp\s6\mutate_discovery.py M<n>` → `.venv/Scripts/python.exe -m pytest tests/webapi/test_run_discovery.py -q` → `… restore`；仓库根 | M1/M2 2 failed / 12 passed、M3 3 failed / 11 passed、M4/M5 10 failed / 4 passed；恢复后 14 passed；退出码 0 | `C:\tmp\s6\gates\mutations_discovery.log` | 脚本自还原，`git status` 只剩 docs 回填（原 A0 行按记忆写错，已按本记录改写） |
| 2026-10-08 | 49b830d | `.venv/Scripts/python.exe -m pytest tests/webapi -q`；S6 切片 `… pytest tests/webapi/test_run_discovery.py tests/webapi/test_replay_islands.py tests/webapi/test_replay_exchange.py tests/webapi/test_engine_catalog.py -q`；fixture 侧 `… pytest tests/test_island_forest_export.py tests/test_build_run_fixture.py -q`；仓库根 | **413 passed**（45.83s）／**62 passed**（8.00s）／**10 passed**（4.67s）；退出码均 0 | `C:\tmp\s6\gates\{pytest_webapi_s6_final.txt,pytest_s6_slice_final.txt,pytest_forest_fixture_final.txt}` | S6 终态复跑（回填期），替代此前的终端计时 |
| 2026-10-08 | 49b830d | `npx --no-install tsc --noEmit`；`npx --no-install vitest run`；`npx --no-install eslint src e2e`；`npx --no-install vite build`；`web/` | tsc 退出码 0；vitest 39 files / **752 passed \| 3 skipped**（15.51s）；eslint 0 error（1 warning）；build 退出码 0（438ms） | `C:\tmp\s6\gates\frontend_chain_s6_final.log` | S6 终态复跑（回填期） |
| 2026-10-08 | 7687df2c（工作树；Skill 页面与测试 docstring 更新后、S8 回填提交前） | `.venv/Scripts/python.exe -m pytest tests/test_island_skill.py tests/test_island_skill_walkthrough.py -q`；仓库根 | **50 passed**（9.58s）；退出码 0 | `C:\tmp\s8\gates\pytest_skill_s8.txt` | S8 回填：`references/hdd-server.md` 按实际做法更新（完整历史 bundle＋`git clone --branch`、独立 `.venv`、`preflight` 分家根、S8 已执行记录与退出码教训）后复跑；`test_island_skill.py` 仅改一处过期 docstring（“S8/S9 are still open”→“S9 is still open”），断言未动，`test_the_hdd_reference_marks_the_stages_it_has_not_run` 仍以「S9 尚未执行／待执行」＋「不是已跑过的记录」两条断言钉住页面 |

T01–T26 与实际测试函数的映射（只写真实存在的函数；未落地的一律标未测并指明归属阶段，不写“全覆盖”）：

| 用例 | 测试文件::函数 | 层级 | 状态 |
|---|---|---|---|
| T01 | `tests/test_island_contract.py::test_default_config_has_three_distinct_islands`、`::test_island_defaults_are_audit_friendly` | 配置 | PASS |
| T02 | `tests/test_engine.py::test_engine_resume_continues_same_tree`（`IslandsConfig.legacy_single()`，恢复后同根、节点续增）、`::test_resume_continues_every_island_tree_without_new_roots`（三岛三根、恢复不新增根、各岛节点不丢）、`tests/test_island_contract.py::test_explicit_single_island_config_allowed`、`::test_legacy_single_factory`、`::test_legacy_db_migrates_and_reads_single_island` | 引擎＋配置＋存储 | PASS |
| T03 | `tests/test_island_contract.py::test_duplicate_island_ids_rejected`、`::test_invalid_exchange_interval_and_concurrency_rejected`、`::test_empty_island_id_rejected`、`::test_empty_islands_rejected`、`tests/test_island_isolation.py::test_eval_concurrency_above_one_is_refused_not_ignored` | 配置＋引擎启动 | PASS |
| T04 | `tests/test_island_isolation.py::test_every_island_loads_only_its_own_nodes`、`::test_island_view_refuses_a_second_root` | 引擎＋Tree | PASS |
| T05 | `tests/test_island_isolation.py::test_foreign_parent_is_rejected_without_polluting_either_tree` | Tree | PASS |
| T06 | `tests/test_island_isolation.py::test_an_island_attempt_moves_only_that_island`、`::test_island_best_does_not_leak_into_a_sibling_backup` | 引擎 | PASS |
| T07 | `tests/test_island_isolation.py::test_rotation_is_round_robin_and_skips_a_paused_island`、`::test_a_paused_island_does_not_stop_the_parent_run`、`::test_the_run_ends_when_no_island_is_runnable` | 协调器＋引擎 | PASS |
| T08 | `tests/test_island_isolation.py::test_consecutive_invalid_candidates_hit_the_attempt_cap`、`::test_island_budget_is_charged_per_attempt_not_per_operator` | 引擎 | PASS |
| T09 | `tests/test_island_contract.py::test_null_budget_accepted_and_never_triggers_caps`、`::test_finite_budget_still_triggers`、`::test_fraction_stage_cap_inert_without_total_cap`、`::test_absolute_stage_cap_active_without_total`、`::test_finite_stage_caps_keep_previous_semantics` | 预算判定函数（非引擎运行级） | PASS——有限预算的引擎运行级续跑已由 D4.3 实测：`tests/test_island_resume.py::test_a_resume_carries_the_tokens_the_run_already_spent`（重放后总数等于账本）、`::test_a_resumed_stage_counter_matches_the_rows_of_that_stage`、`::test_the_budget_stop_uses_the_restored_spend`（恢复后立刻按已花额度停）。null 预算的引擎运行级续跑在 S7 已补：`tests/test_island_resume.py::test_a_resume_without_a_token_cap_keeps_spending`（去掉上限续跑仍继续花费、`_should_stop` 为 False；M2 mutation 使 `tests/test_island_resume.py:480` 转红），提交 `d26c532` |
| T10 | `tests/test_island_contract.py::test_delivery_and_application_dedup`（存储唯一键）＋`tests/test_island_exchange.py::test_a_summary_is_delivered_once_per_target_island`（同一 `(summary,target)` 第二次插入返回 False）＋`::test_a_positive_summary_reaches_the_sibling_prompt_and_is_evaluated_locally`（引擎级：A 发布→B 提示含摘要→B 候选走自己的评估）＋`::test_the_same_lesson_is_published_once_even_across_a_restart` | 存储＋引擎 | PASS（引擎级“同一正面摘要重复投递目标只一条”已实测，S3/D3.4） |
| T11 | `tests/test_island_exchange.py::test_a_failure_lesson_reaches_a_sibling_without_the_raw_trace`（埋 `holdout` 路径、序列号、时间戳、代码块、traceback 框架行，C 提示只有归纳后的避错条目）、`::test_only_the_error_class_is_read_out_of_a_traceback`、`::test_sanitize_removes_programs_paths_and_identifiers_but_keeps_the_lesson`、`::test_an_over_long_body_is_reduced_by_whole_segments_not_mid_sentence` | 引擎＋纯函数 | PASS |
| T12 | `tests/test_island_exchange.py::test_a_sibling_source_never_enters_the_receiving_prompt`（A 最优节点源码植入唯一标记，断言标记确在该节点、B 的全部提示与 B 树全部节点代码均无标记）＋`::test_summary_dto_has_no_place_for_code`（DTO 键集固定，无 code 字段） | 引擎＋结构边界 | PASS——离线 mock 无法在文件系统层拦截“读取源码”，边界靠 DTO 无源码字段＋`operators.py` 无外岛取码调用点保证；已如实记录局限，S8/S9 需以真实产物复核 |
| T13 | `tests/test_island_exchange.py::test_a_grafted_candidate_never_inherits_the_source_score`（来源 31.0、候选 `ZeroDivisionError` → application `score is None`）、`::test_an_application_is_pending_until_its_own_candidate_is_evaluated`（未评估停在 pending，同候选同摘要只一行）；中断侧另见 `tests/test_island_fault_injection.py::test_an_application_recorded_before_the_evaluator_stays_unfinished`（跨重启仍为 pending，重试后分数是接收岛自己的评估值且 ≠ 来源分） | 引擎＋存储 | PASS |
| T14 | `tests/test_island_exchange.py::test_a_summary_from_another_task_or_evaluator_is_rejected_with_reason`（四种拒绝：`target_island_not_runnable`/`task_fingerprint_mismatch`/`evaluator_fingerprint_mismatch`/同任务同评估器接受且无拒绝事件）、`::test_an_overtaken_best_is_rejected_as_superseded`（过时最佳，重放不重决策） | 交换层 | PASS |
| T15 | `tests/test_island_knowledge.py::test_an_injected_card_reaches_the_prompt_and_the_candidate_record`（提示 `<knowledge_cards>` 含 `- **K-A1**: …` 且候选 `card_ids == ["K-A1"]`、`knowledge_injected.sources` 标 `frozen`）、`::test_each_island_reads_the_library_for_its_own_keywords`、`::test_a_card_this_run_produced_is_labelled_run_new`、`::test_experience_promoted_on_one_island_is_knowledge_for_the_others` | 引擎＋知识检索＋存储 | PASS（S4/D4.1，提交 bd76846；成本侧由 `llm_call.island_id` 归属，见 D4.2） |
| T16 | `tests/test_island_knowledge.py::test_a_library_that_will_not_parse_selects_nothing_and_says_why`（库文件损坏 → 空选择＋`reason`，候选仍拿评估器真实分）、`::test_a_broken_knowledge_service_changes_no_score`（检索抛异常 → 岛 best 不变、无 CONFIRMED）、`::test_knowledge_switched_off_is_recorded_as_off`、`::test_a_task_without_a_knowledge_source_says_so` | 引擎＋知识检索 | PASS（S4/D4.1） |
| T17 | `tests/test_island_fault_injection.py::test_a_summary_written_but_never_offered_is_offered_once`（未投递 → 恰一条目标投递，且再跑一轮 delivered=0 不重复）、`::test_the_repair_only_offers_siblings_that_can_still_act`、`::test_a_resumed_round_offers_what_the_interrupted_round_never_sent`（引擎恢复路径）、`::test_an_application_recorded_before_the_evaluator_stays_unfinished`（未评估不谎称 evaluated，重试后才带 `evaluation_id`/本岛分数）、`::test_a_run_that_lost_its_report_rebuilds_it_without_paying_again`（`adapter._call_count` 与 `llm_call` 行数、事件数前后相等）、`::test_a_paused_island_comes_back_paused_with_its_own_counters`、`::test_a_paused_island_is_not_sent_work_by_its_siblings`、`::test_the_interrupted_run_committed_one_row_per_request`、`::test_a_resume_replays_the_committed_ledger_and_appends_nothing`（旧行逐字段等值、`cost_ledger` seq 接续） | 引擎＋交换＋存储＋报告 | PASS（S4/D4.4，提交 971f38e；"完成事件/成本/评估不重复"三项分别由事件计数、`llm_call`/`cost_ledger` 行计数、评估器调用计数三条独立断言覆盖。真实 kill/掉电下的复核属 S8/S9） |
| T18 | `tests/test_island_contract.py::test_read_only_store_never_touches_the_original`、`::test_resumed_copy_migrates_without_touching_source`、`::test_read_only_store_rejects_writes`＋`tests/test_island_resume.py::test_resume_from_continues_a_copy_and_leaves_the_original_files_alone`（CLI：源目录逐文件 sha256 全等，且 `*.db-wal` 为空使该比较有意义）、`::test_an_old_run_is_resumed_from_a_copy_not_from_the_original`、`::test_a_clone_carries_the_wal_and_leaves_the_source_readable`（活动写连接留在 WAL 的提交确实进副本，副本是单个一致文件）、`::test_artifacts_travel_as_files_and_a_database_never_does`、`::test_a_clone_never_overwrites_a_database_that_exists`、`::test_resume_from_a_directory_the_run_would_write_into_is_refused` | 存储＋引擎＋CLI | PASS（S4/D4.3，提交 91c8203；原件哈希与"写入只在新副本"已按副本路径实测，服务器真实大库副本恢复属 S8/S9） |
| T19 | `tests/webapi/test_run_discovery.py::test_two_complete_copies_of_a_run_id_are_not_merged`（两份完整副本各成一条、都不被覆盖）、`::test_the_bare_id_names_the_first_hit_and_the_suffix_the_second`（裸 id 与带后缀 id 各指其一，两项均可访问） | WebAPI 发现层 | PASS（S6/D6.2，提交 24438c9；终态在 413 passed 内复跑） |
| T20 | `tests/webapi/test_run_discovery.py::test_a_fixture_root_leaves_the_product_listing`（名字像 demo 但位于正常根：仍列出；位于 fixture 根：排除；书签仍可打开）、`::test_a_run_this_service_started_is_reported_real`（登记表有记录＝real，否则 unverified，不按名字冒充）、`::test_the_provenance_counts_reconcile`（`scanned = runs + paired`、`runs = listed + fixtures`） | WebAPI 发现层 | PASS（S6/D6.2） |
| T21 | `tests/webapi/test_run_discovery.py::test_a_directory_holding_no_run_artifact_is_not_a_run`（空目录不算运行）、`::test_an_unreadable_part_of_the_volume_is_reported_and_the_rest_still_lists`（错误写 manifest，其余照常列出，不整体 500）、`::test_the_error_manifest_caps_itself`（封顶并自报封顶）、`tests/webapi/test_replay_islands.py::test_a_malformed_islands_block_is_invalid_not_zeroed`、`::test_an_empty_ring_is_reported_as_invalid`、`::test_a_field_of_the_wrong_type_stays_null_rather_than_a_coerced_one` | WebAPI 发现层＋回放层 | PASS（S6/D6.2＋D6.3） |
| T22 | `tests/webapi/test_run_discovery.py::test_a_database_only_run_is_listed_and_admits_it_has_no_tree`（只有库的运行仍列出并承认无树）、`tests/webapi/test_replay_islands.py::test_a_single_tree_run_says_the_ring_was_never_recorded`、`::test_no_island_of_a_single_tree_run_is_invented`（历史单树不编三岛）；UI 侧由 T25 的单树形态 E2E 复验 | WebAPI 发现层＋回放层 | PASS（S6/D6.2＋D6.3） |
| T23 | `tests/webapi/test_path_security.py`（19 项：run/node/artifact id 穿越、盘符、兄弟目录、未配置根）、`tests/webapi/test_run_discovery.py::test_the_provenance_manifest_carries_no_host_path`、`tests/webapi/test_replay_exchange.py::test_no_exchange_response_leaks_a_filesystem_path` | WebAPI 路由＋发现＋回放 | PASS（S6/D6.2＋D6.3；终态在 413 passed 内复跑） |
| T24 | `tests/test_island_skill_walkthrough.py::test_the_preflight_names_the_ring_this_config_will_start`、`::test_the_rehearsal_needs_no_hdd_specific_input`、`::test_the_rehearsal_produces_the_three_blocks_the_skill_documents`、`::test_the_report_can_be_rebuilt_from_the_database_without_new_scores`、`::test_the_experience_draft_exports_into_the_run_directory`、`::test_the_exporter_refuses_to_write_into_the_project_skill_dir`、`::test_a_run_that_exchanged_nothing_delivers_facts_instead_of_rules`（文档↔代码漂移另由 `tests/test_island_skill.py` 43 项核对） | Skill＋CLI＋产物（离线 toy 任务，`task.adapter: famou`） | PASS（2026-10-08，6daa23c＋6de9707，7 passed／11.46s；`tests/fixtures/toy_task` 不要求任何 HDD 专属字段，产物可在运行目录定位；服务器端入口属 S8/S9，本行不构成其证据） |
| T25 | `web/src/features/islands/islands-components.test.tsx`（每岛一卡与中文策略说明、六个交换计数分列、「未记录/未评分」）、`web/src/features/islands/island-view.test.ts`（岛最优只在本岛节点里算、运行时岛数与 run_summary 矛盾时报出、legacy 不编岛、成本差额如实呈现）、`web/src/features/workbench/workbench-components.test.tsx`（岛筛选芯片、节点岛徽标、抽屉岛行；legacy 空串不显示）、`web/e2e/visual-regression.spec.ts`：`三岛形态` 3 项（三张岛卡＋六个独立交换计数＋全局最优落在岛 a；岛筛选收窄到 7 节点；历史单树明说无岛记账）与 `单树形态` 5 项（21 节点、六层、四档显著性、双亲、修复链） | 前端组件＋E2E（真实 webapi 进程跑入库 fixture） | PASS（S6/D6.4，提交 95d25c4＋49b830d；E2E 76 passed，日志 `C:\tmp\s6\gates\e2e_full_pass1.log`） |
| T26 | `tests/test_island_exchange.py::test_offered_accepted_applied_and_evaluated_are_not_counted_as_one`（同一条摘要分三阶段核数：`(delivered 2, offered 2, accepted 0, applied 0, evaluated 0)`→`(offered 1, accepted 1, applied 1, evaluated 1)`→`(offered 0, accepted 2, applied 2, evaluated 2)`，且两个 application 分数是接收岛的 18.0/19.0 而非来源 31.0）、`::test_the_context_queue_is_capped_at_the_configured_size`、`::test_a_repeat_of_the_same_error_adds_evidence_instead_of_a_second_message`、`::test_a_baseline_root_is_described_without_claiming_an_improvement`、`::test_a_broken_summary_channel_never_touches_a_score`、`::test_a_stopped_island_is_neither_a_reader_nor_a_writer`、`::test_a_single_island_run_has_no_summary_channel` | 引擎＋存储 | PASS |

### D. 真实运行结果（预检、正式分别一份）

#### D-预检（2026-10-08，run `hdd_mvp_preflight_20261008`）

运行类型/ID：真实预检 `hdd_mvp_preflight_20261008`（`fe evolve local benchmark/hdd_mvp`，真实 LLM＋真实 evaluator，无 mock）。起止时间：2026-10-08 20:07:36→20:32:08（+08:00，约 24m32s；`wall_time_s=1468.32`）。代码 SHA `7687df2c`／配置 `9be62749…`（resolved `350df2ee…`）／种子 20260926。数据与评估器指纹：六文件 sha256 见 B 段，evaluator `cddfaaab…`、init `91744b4b…`；`holdout` 从未列举/读取。实际停止原因：全局 `max_iterations`；各岛 `max_attempts`。

| 指标 | 岛 A | 岛 B | 岛 C | 全局 |
|---|---|---|---|---|
| 初始 ROS / 最优 ROS / 相对初始增量 | 22.8074 / 22.8074 / ±0（2 尝试未改进） | 22.8074 / 38.2067 / +15.3993 | 22.8074 / 36.6104 / +13.8031 | 22.8074 / 38.2067（`4c1635ca`，b 岛）/ +15.3993 |
| 最优节点 ID / 评估证据 | `8a37fed9`（＝共享初始根） | `4c1635ca`（单次评估 102.01s） | `f0cd9659`（321.0s，summary_cross 嫁接候选） | `4c1635ca`；证据 `preflight/artifacts/hdd_mvp_preflight_20261008/{run_summary.json,tree.json,events.jsonl}`＋`fe.db` |
| precision / recall / F1 / F1_p10 | 0.19826 / 0.33598 / 0.24937 / 0.22935 | 0.36533 / 0.45238 / 0.40422 / 0.37761 | 0.29800 / 0.51455 / 0.37742 / 0.35397 | 同 b 岛最优（0.36533 / 0.45238 / 0.40422 / 0.37761） |
| AUPRC / R@FAR / FAR / 漏告率 | 0.19546 / 0.27381 / 0.003400 / 0.66402 | 0.34174 / 0.45370 / 0.001967 / 0.54762 | 0.33674 / 0.44048 / 0.003034 / 0.48545 | 同 b 岛最优（0.34174 / 0.45370 / 0.001967 / 0.54762） |
| 尝试 / 有效 / 无效 / 评估调用次数 | 2 / 1 / 0 / 1（共享首评） | 2 / 3 / 0 / 2 | 2 / 3 / 0 / 2 | 6 尝试 / 岛内有效合计 7 / 无效 0 / 真实评估器执行 5（见下方口径注） |
| Token / 可核实费用 / 未知账单 | 25601 / 未知 / 0 | 29470 / 未知 / 0 | 21428 / 未知 / 0 | 76499 / `cost_usd=null`（`cost_basis=unknown`，未配置价格表，不以 token 猜费用）/ `unresolved_calls` 0 |
| 最优候选耗时 / 总墙钟时间 | 1.87s（＝初始评估；岛内无更优候选） | 102.01s | 321.0s | 总评估 688.77s；总墙钟 1468.32s |
| 发出/接收/采用的正面、负面摘要数 | 发出 3（best 1＋failure 2）／接收 2／采用 0 | 发出 1（best）／接收 4／采用 5 | 发出 1（best）／接收 4／采用 6 | 发布 5（best 3／failure 2）／投递 10（全部 accepted/applicable）／采用 11（全部 evaluated） |
| 跨岛摘要交叉 / 完成评估数 | — | — | — | `summary_cross_selected` 3（均选自 b 的 `sum-3b709a88`：c×2、a×1，reason `sibling_ahead`）；`summary_crossover` 节点 2（c `f0cd9659` 源 [b,a]、c `0d7fdc94` 源 [b]）；采用完成评估 11/11 |
| 知识卡采用数 / 来源 | 0 | 5（M01/T01/E01 于正例节点 `4c1635ca`；FE01/FE03 于被证伪节点 `7361c1f3`） | 5（M01/T01/FE01 于正例节点 `f0cd9659`；E05/FE09 于被证伪节点 `0d7fdc94`） | 注入 6 次／提供 24 张／采用 10 张（41.7%）；knowledge tokens 3453（占 prompt 7.35%） |
| 停止原因 | `max_attempts`（2/2） | `max_attempts`（2/2） | `max_attempts`（2/2） | `max_iterations`（全局 6） |

全局性能列填写全局最优候选（`4c1635ca`）自己的指标，不把各岛的不同指标拼成一个虚构最优候选。费用无法核实则写未知，不用 Token 猜费用。无效候选（生成失败/冒烟拒绝 2 个，a 岛）不混入有效改进率分母。

口径注：岛表“有效”是 `island_state.valid_evaluations` 的岛内累计（a 1／b 3／c 3＝7），其中首评（初始解 `8a37fed9`）只真实执行了一次、三个岛共享证据（`shared_initial_evaluation_id=8a37fed9`），因此**真实评估器执行次数是 5**（a 1／b 2／c 2，实测 1.87/102.01/207.54/321.0/58.23s）。两数不同不是矛盾，报告不把它抹平。

#### D-正式（S9）

待正式运行后另填（运行 ID、起止时间、SHA/配置/种子、指纹、停止原因与同名各列；不得把上一节的预检数字复制成正式结果）。

### E. 交换与 Skill 证据

下表全部来自 2026-10-08 的一次**离线 `--mock` toy 三岛演练**（`task.adapter: famou`、`tests/fixtures/toy_task`、运行 `497713ef`：6 次尝试＝三岛各 2 次，`exchange` 为 `summaries 6`／`deliveries 12`／`accepted 9`／`rejected 0`／`applications 11`／`evaluated_applications 11`）。模型是 MockLLM、任务不含任何硬盘字段，所以这张表证明的是**编排与记账真实存在**，不是真实数据上的经验有效性；真实 HDD **预检**运行的交换证据见下方「S8 真实预检交换证据」一节，正式运行（S9）仍待另填一份。

| 摘要 ID / 类型 | 来源岛/节点 | 目标岛/新节点 | 采用或拒绝原因 | 新评估结果 | 证据路径 |
|---|---|---|---|---|---|
| `sum-b057fd44` / best | a（performance）/ 节点 1ebc000d，来源读数 21.61 | b：`app-7a363b4b`→07392606、`app-a1253e04`→cb518fc8；c：`app-335032d4`→e0a1a572 | 两条投递（`dlv-61efcad9`→b、`dlv-c78e6ac9`→c）都被采用，无拒绝；采用的机制是引擎按 `max_summaries_in_context` 把外来摘要放进接收岛的生成上下文，离线演练里不存在人工确认 | b 侧 23.16（Δ+0.09，未超噪声带 0.5）与 23.07（Δ+7.02，超噪声）；c 侧 17.2（Δ+1.15，超噪声）。分数全部由接收岛自己的本地评估器产生，不继承来源分 | 证据：`C:\tmp\s5\art_a1\497713ef\run_summary.json`＋`skills\evidence_index.json`（库 `C:\tmp\s5\runs_a1\497713ef\fe.db`） |
| `sum-5d68dda2` / best | b（miss_alert）/ cb518fc8，23.07 | a：`app-c69d3046`→d7089962；c：`app-58d93835`→4b2ba14d、`app-db6525b2`→e0a1a572 | `dlv-1bbe37e5`→a、`dlv-ba11dfb9`→c 各被采用一次，无拒绝 | a 侧 24.9（Δ+3.29，超噪声，成为本次运行全局最佳）；c 侧 19.96（Δ+2.76）与 17.2（Δ+1.15） | 证据：`C:\tmp\s5\art_a1\497713ef\run_summary.json`＋`skills\evidence_index.json`（库 `C:\tmp\s5\runs_a1\497713ef\fe.db`） |
| `sum-70b15a26` / best | c（efficiency）/ e0a1a572，17.2（正文含“故意使用错误 LightGBM 参数以触发修复”的方法描述） | a：`app-5efb66f8`→d7089962；b：`app-f7b53224`→07392606 | `dlv-5f0cbb26`→a、`dlv-f2a5c046`→b 均被采用 | a 侧 24.9（Δ+3.29）；b 侧 23.16（Δ+0.09，噪声内） | 证据：`C:\tmp\s5\art_a1\497713ef\run_summary.json`＋`skills\evidence_index.json`（库 `C:\tmp\s5\runs_a1\497713ef\fe.db`） |
| `sum-20672abf` / best | a（performance）/ d7089962，24.9（本运行全局最佳节点） | b：`app-274bf8b9`→07392606；c：`app-4a21c421`→4b2ba14d | `dlv-abec74d3`→b、`dlv-3487afcd`→c 均被采用 | b 侧 23.16（Δ+0.09，噪声内）；c 侧 19.96（Δ+2.76，超噪声） | 证据：`C:\tmp\s5\art_a1\497713ef\run_summary.json`＋`skills\evidence_index.json`（库 `C:\tmp\s5\runs_a1\497713ef\fe.db`） |
| `sum-f257c85e` / best | b（miss_alert）/ 07392606，23.16（运行未记录适用条件） | c：`app-d5053215`→4b2ba14d | 两条投递只有 1 条被采用（`dlv-411a0cf1`→c）；另一条既无采用也无拒绝记录，说明它是“未被采用”而不是“被拒绝”——两者在库里是不同事实 | c 侧 19.96（Δ+2.76，超噪声） | 证据：`C:\tmp\s5\art_a1\497713ef\run_summary.json`＋`skills\evidence_index.json`（库 `C:\tmp\s5\runs_a1\497713ef\fe.db`） |
| `sum-4c510650` / best | c（efficiency）/ 4b2ba14d，19.96 | 无（`adopted_by` 为空） | 两条投递都未产生采用，也没有拒绝原因落库。本行只能证明“发布并投递”，不构成“经验生效” | 无新评估结果 | 证据：`C:\tmp\s5\art_a1\497713ef\run_summary.json`＋`skills\evidence_index.json`（库 `C:\tmp\s5\runs_a1\497713ef\fe.db`） |

**S8 真实预检交换证据**（run `hdd_mvp_preflight_20261008`，代码 `7687df2c`；来源＝`fe.db` 的 `exchange_summary`/`exchange_delivery`/`summary_application` 三表与 `events.jsonl`，与 A0/D 段同一份产物）：

| 摘要 ID / 类型 | 来源岛/节点（读数） | 目标岛与投递 | 采用（应用）与新评估结果 | 证据路径 |
|---|---|---|---|---|
| `sum-8a7e36c6` / failure | a（performance）/ `4e6045f9`（语法错误，未评估；同类出现 1 次） | b：`dlv-ef7a8869`；c：`dlv-8d17a365`（均 accepted/applicable） | b 侧 2 次：`app-781bd6f6`→`4c1635ca`、`app-95f801f9`→`7361c1f3`；c 侧 2 次：`app-827ebded`→`f0cd9659`、`app-fdcca46c`→`0d7fdc94` | `$TM/preflight/runs/hdd_mvp_preflight_20261008/fe.db`＋artifacts `events.jsonl` |
| `sum-d277a90e` / best | a / `8a37fed9`（22.8074，基线最优） | b：`dlv-4694fa46`；c：`dlv-6df379dd`（均 accepted/applicable） | b 侧 `app-3f6f98df`→`4c1635ca`；c 侧 `app-d499e55e`→`f0cd9659` | 同上 |
| `sum-3b709a88` / best | b（miss_alert）/ `4c1635ca`（38.2067；条件“历史数据中存在可学习的退化趋势信号…”） | a：`dlv-56a7cab9`（该投递下 a 无采用）；c：`dlv-ce915ea4`（均 accepted/applicable） | c 侧 2 次：`app-d1a808ad`→`f0cd9659` 得 **36.6104**（成为 c 岛最优）、`app-3d9e92d2`→`0d7fdc94` 得 29.3627；被 3 次 `summary_cross_selected` 选中（c×2、a×1，reason `sibling_ahead`） | 同上 |
| `sum-2c1ca67a` / best | c（efficiency）/ `f0cd9659`（36.6104；条件“数据中存在可学习的非线性趋势信号，且 OOF 估计可靠”） | a：`dlv-d1e4be0f`（a 无采用）；b：`dlv-0de079c8`（均 accepted/applicable） | b 侧 `app-f088a5f5`→`7361c1f3` 得 20.7573（Δ-17.45，`hypothesis_refuted`，未超过 b 最优） | 同上 |
| `sum-f6926205` / failure | a / `c91350ce`（`smoke_rejected`，未评估） | b：`dlv-1d32f13b`；c：`dlv-ad242093`（均 accepted/applicable） | b 侧 `app-0d87625d`→`7361c1f3`；c 侧 `app-50b68838`→`0d7fdc94` 得 29.3627（Δ-7.25，`hypothesis_refuted`） | 同上 |

计数与关键链路：发布 5（best 3／failure 2）、投递 10（全部 accepted/applicable）、采用 11（全部 evaluated；b 5／c 6／a 0）、`summary_cross_selected` 3、`summary_crossover` 节点 2（c 的 `f0cd9659` 源 [b,a]；c 的 `0d7fdc94` 源 [b]）。关键成功链路：`sum-3b709a88`（b 最优 38.2067）→ `dlv-ce915ea4` → `app-d1a808ad` → c 候选 `f0cd9659` 由 c 岛自己的本地评估器评得 36.6104（不继承来源分）。负例如实保留：`7361c1f3` 与 `0d7fdc94` 均低于本岛最优（`hypothesis_refuted`），岛最优未被替换；a 岛两个失败候选自然产生了两条 failure 摘要并被 b/c 采用（失败经验确实进入兄弟岛上下文）。

通用 Skill 路径/校验结果：`skill/fe-island-evolution/`（`SKILL.md` 224 行＋`references/configuration.md` 110／`exchange.md` 77／`hdd-server.md` 204／`recovery.md` 95 行＋`scripts/export_experience_skill.py` 413 行），README 技能索引已收录。仓库内**没有** Skill 结构校验工具（`scripts/` 只有 web 契约与 fixture 类脚本、前端 `package.json` 无 skill lint，已逐条确认），因此“校验结果”指可重复运行的测试而不是人工目测：`pytest tests/test_island_skill.py tests/test_island_skill_walkthrough.py -q` → 退出码 0，50 passed（43 项文档↔代码漂移核对＋7 项按步骤 2/3/7/8 的端到端走查，T24）；两处反向 mutation（把 `exchange_interval` 默认写成 `6`、在演练命令里插入假参数 `--island-workers 3`）各让对应用例失败，还原后 43 passed 且 `grep island-workers` 无残留。经验 Skill 草稿路径/证据/局限：演练运行 `497713ef` → `C:\tmp\s5\art_a1\497713ef\skills\{experience_skill_draft.md,evidence_index.json}`（`rules: 6`，每条 `confidence_status` 均为 `single_observation`，`review_status: draft_not_cross_run_verified`，`sanitization` 三项均为 false）；零交换运行 `664800e6` → 同结构目录（`rules: 0`，草稿写“未得到可泛化规则”并逐岛列出尝试数、有效评估数与三个 profile）。局限：两份都来自 `--mock` 模型与 toy 任务，未经第二次运行复现，按需求 §6 不得升级为通用规则，也不得当成真实 HDD 经验——真实运行的经验草稿按计划属 S9 正式运行交付物。按 Skill 操作时发现的问题及修正：①步骤 2 的预检原先查的不是要跑的配置（配置放在任务目录之外时 `fe doctor` 仍按默认 `hdd` 适配器检查），且引擎对不认识的顶层键静默忽略 → 6f0fb04 加 `--config-file` 与 `config_keys`/`config_islands`；②输出契约当时答不出“哪个岛烧了多少”，岛状态还落的是枚举 repr → df8a346＋b6b6241；③参考文件初稿把岛清单写成 `islands.specs:`、把轮数写成 `stop.max_iterations:`，被 `EvolveConfig.from_dict()` 与 `fe doctor` 实跑证伪，改为 `islands.islands` 与 `budget.max_iterations`，并补写 `budget.max_wall_hours` 默认 6.0 会掐断长跑；④`islands.stagnation_request_evals` 经全 `src/` 检索确认引擎不读 → 文档标为死配置；⑤导出草稿一度把投递／采纳／应用混成一句 → 改为四层分开计数。S8 真实预检按本 Skill 操作发现的三处与实际不符（完整历史 bundle＋`git clone --branch`、独立 `.venv`、`preflight/{runs,artifacts}` 分家根）已写回 `references/hdd-server.md`，Skill 两类测试复跑 50 passed（`C:\tmp\s8\gates\pytest_skill_s8.txt`）；S9 正式运行按更新后的页面执行再验。

S6 补充（三岛 fixture 与界面证据）：提交 `0808f94` 入库的 `tests/fixtures/runs/hdd_mvp_islands_15l4nd01` 是**真实引擎＋真实评估器、只有 LLM 是 mock** 的三岛运行（`scripts/make_island_demo_run.py` 生成，种子 7、18 轮、`exchange_interval=1`），其 `PROVENANCE.md` 记录全部事实：experiment_id `15l4nd01`；三岛 a `performance`／b `miss_alert`／c `efficiency`；每岛 6 次尝试合计 18＝`iterations_done`；21 节点（各 7，其中 `summary_cross` 7 个）；initial＝best＝22.8074；交换发布 1／投递 2／接受 2／拒绝 0／采用 12／已评估采用 12；成本 10200 tokens（a 3300／b 3300／c 3600，shared 0），`cost_basis=unknown`、`cost_usd=null`；三岛 `stop_reason` 为空、`status=running` 而运行 `finished`——这个矛盾不藏起来：界面把它显示为「岛还在跑 / 运行已结束」的矛盾说明。界限（`PROVENANCE.md` 明写）：mock 候选 0.30~0.36 全部不超初始 22.8074，所以没有上升路径、`best_path` 只剩根节点；这份 fixture 只能验证「三岛结构与数字被正确读出与渲染」，**不能**用来声称算法有提升，真实提升数据属 S9。生成时九项形状门（缺一不写入）与脱敏（`build_run_fixture.py`：主机路径→`<REDACTED_PATH>`，命中私有集名称或密钥形状即拒收）如实执行；两次演练留档：`--exchange-interval 2` → applications=10、`--exchange-interval 1`（脚本默认）→ applications=12（取后者入库）。历史单树形态用另一份 fixture `hdd_mvp_showcase_c89e2a01`（21 节点、6 层）验证，界面在旧运行上明说「该运行没有产出 islands / exchange 记账」而不是编出三个岛。

### F. 结论与遗留

进度快照（截至提交 971f38e）：S0、S1、S2、S3 通过并勾选——三岛各自一棵树、协调器轮转与持久游标、每岛配额/停滞/基础设施熔断、共享一次真实 init 评估、提示与算子画像按岛生效、父运行 `all_islands_stopped` 原因可追溯；S3 在其上加了摘要通道（新文件 `cloud/exchange.py`）：正文只由已入库的方法描述与评估器数字组装并经 `sanitize()`，投递/采用/应用/评估记成四个独立事实，`SUMMARY_CROSS` 嫁接后仍由接收岛本地评估器重新打分且不继承来源分，全量离线门 1610 passed / 0 failed（`/tmp/s3_full2.log`，828.25s）。S4 通过：D4.1（提交 bd76846，9 用例）、D4.2（提交 0eac985，8 用例）、D4.3（提交 91c8203，新文件 `cloud/resume.py`＋`common/proc.py`＋`tests/test_island_resume.py` 39 用例）与 D4.4（提交 971f38e，新文件 `tests/test_island_fault_injection.py` 9 用例＋`exchange.backfill_deliveries()`）均已完成并勾选；S4 阶段门为 `.venv/Scripts/python.exe -m pytest tests/ -q` → **1675 passed / 0 failed**（`/tmp/s4_full2.log`，1067.28s，退出码 0）＝下面一行的 1666＋D4.4 的 9，D4 回归集合（13 文件＋`tests/webapi`）574 passed（89.86s）。D4.4 的五点里：其一"账本写完但终端输出中断"依赖的 `start_seq=max_cost_seq()` 接续是 D4.2（0eac985）修的真实缺陷，本轮用反向 mutation 重新证明它必要；其二"summary 已落库但未投递"是本轮新发现、且此前**永远补不回来**的真实缺陷——`_new_summary()` 命中内容哈希去重时只并证据并返回 None，下一轮不会再发同一条结论，而 `_deliver()` 只处理本轮新产出的摘要，于是缺口无人知晓；修法是新查询而非新记忆：`backfill_deliveries()` 每轮交换开头按库补齐（本岛已发布摘要 × 仍可行动的兄弟岛，缺 `(summary_id,target_island_id)` 就补一条 delivery），靠 `INSERT OR IGNORE`＋`UNIQUE(summary_id, target_island_id)` 保证补齐不会变成重播，并写 `exchange_delivery_backfilled` 事件留痕；其余三点（已采用未评估、评估完成未出报告、岛 B 暂停时退出）在 D4.3 的机制下按构造成立，本轮为每一点补了中断前后的计数对比。四处生产逻辑做过反向 mutation（去掉补齐调用→3 failed；`_pending_summary_applications()` 返回 `{}`→2 failed，其中一条是 D4.3 既有用例，说明两种中断共用同一重挂逻辑；PAUSED 被归一化成 RUNNING→2 failed；`start_seq=0`→`sqlite3.IntegrityError: UNIQUE constraint failed: cost_ledger.experiment_id, cost_ledger.seq`）；**未做 mutation 的一点**："评估完成未生成报告"只由 `adapter._call_count` 前后相等的断言自身钉住，转 S7 补测。S4 保留未勾选的第 104 行（冻结库只读＋建议/确认分开作为独立验收项）不随阶段门通过而勾选。D4.3 收尾的全仓库离线为 1666 passed / 0 failed（`/tmp/s4_full1.log`，856.07s）＝S3 门 1610＋D4.1 的 9＋D4.2 的 8＋D4.3 的 39，S3 的 1610 项无一回归。已核实的既有失败：`web/src/app/App.test.tsx > 评委总览只呈现可用的 HDD 任务入口`（SmartMem 卡片显示「检查中…」未被过滤）——在把 `web/src/generated` 与 `tree-adapter.ts` 回退到 924f9fc 状态后仍以同样断言失败，判定为本轮改动前的既有失败，留待 S6 处理并保留证据。S2 期间的失败与重试（保留原始记录，不覆盖）：核心模块禁用词命中注释、`test_engine_resume_continues_same_tree` 在多岛语义下不再成立（拆成 legacy 与三岛两条）、`legacy_island_spec()` 因 S1 校验器不接受空岛 id 而构造失败、`web/openapi/*.json` 落后于源码导致契约稳定性两项失败——四条均已修复并重跑，见 A0 与 C 段。S3 期间的失败与修复（同样保留原始记录，不覆盖）：D3.1 首版用 `[:1200]` 切片做预算，会把一句结论切成半句，且在“先把多段 join 起来再清洗”的写法下整段正文被当成一条超长行丢弃（测试实测清洗后长度为 0）——改为按换行/`；` 切段计数、超预算只从尾部丢整段（2f368fa）；D3.2 首版命中去重时只并证据、不刷新 metrics，读者会看到“同类出现 1 次”的过期计数——`store.add_summary_evidence()` 增加 `metrics` 参数并在去重分支传入最新统计。另有五条是测试自身写错而非实现缺陷（未按岛与来源过滤摘要、要求在标记产生之前就出现在本岛提示里、目标岛清单少一个 id、MockLLM 修复链使一次尝试消耗多个评估结果、legacy 岛 id 不是 `"default"` 而是 `""`），逐条见 C 段。D4.3 期间的失败与修复（同样保留原始记录，不覆盖）：`clone_run_database` 首版把只读 URI 拼成两个 `file:` 前缀，报 `unable to open database file`——四次 `/tmp/probe_wal*.py` 探针确认 `Path.resolve().as_uri()+"?mode=ro"` 才既只读又读得到 WAL；`--report-only` 在 `get_base_artifacts_dir` 返回 None 时做 `None / str` 抛 `TypeError`；`jev_deferred_evaluated` 事件缺 `island_id`，恢复时分不清"只筛过"与"已评估"，已评估候选会重评一次并重复加分；`_verify_run_identity()` 的"无身份记录"分支注释声称会比对任务文本而代码没有比（注释与实现不一致本身按缺陷处理，补比对后旧断言 `verified == []` 失败，改断言并新增拒绝用例）；既有 `tests/test_discovery_preflight_crash_fix.py` 一条用例的 CLI 调用没打 `create_benchmark_adapter` 补丁，attach 到 mock 运行时用真实 HDD 适配器，被新的身份拒绝路径在先——拒绝是本轮要的行为，测试环境补补丁。逐条见 A0 与 C 段。真实结论：仍待填——本轮至今只有离线证据，尚无任何真实三岛 HDD 运行结果，不得据 S2/S3 绿测宣称三岛优于单树（本轮无对照运行）；E 段的交换证据表仍为空，因为至今没有发生过一次真实投递，只有离线断言。未通过的验收项：S5–S10 未开始；S4 内保留一条未勾选（第 104 行"冻结知识库只读＋知识建议与统计确认严格分开"作为独立验收项未单独实测）；T19–T25 未测，T15/T16/T17 已 PASS，T18 已含引擎与 CLI 的副本路径（D4.3），T09 仍缺 null 预算的引擎运行级续跑用例（D4.4 未涉及，转 S7）。已完成部分：D4.1 把岛画像 `knowledge_keywords` 接进 `_retrieve_knowledge_cards()` 的检索上下文，候选 provenance 记实际注入的 card_id 与“冻结库/本运行新增”来源类型，无适用知识时记空选择与原因；D4.2 成本事件化——S3 期间记录的 `cost_ledger` 真实缺陷（主键 `(experiment_id, seq)`，恢复时 `init_ledger()` 新建的内存账本从 seq=1 重新计数，续跑与已落库行冲突）已随 0eac985 修复（`start_seq=store.max_cost_seq(...)`＋`island_id` 列与索引），同时发现并修掉 `Store.get_llm_calls` 静默丢列、DDL 建索引早于加列迁移使旧库打不开两条缺陷，逐条见 A0。D4.3 断点恢复——恢复在任何写入之前比较任务/评估器/初始代码/数据描述/种子/岛环/schema 并逐字段拒绝（数据指纹只读 `meta.json`/`descriptor.json`，跳过 `holdout`，既不读 40 GB 也不碰私有测试集），旧运行按 SQLite 备份接口复制后继续副本（源以只读 URI 打开、原件逐文件 sha256 不变、WAL 的提交随副本一起走），token 预算从 `llm_call` 行重放、每岛 rng 流与交换游标在同一 `scheduler_state` 快照里接回、deferred 候选带 `island_id` 且已评估的只重报不重评不重复加分，报告可只从库重建（`--report-only`，实测评估器调用数为 0），一个运行同一时刻只有一个活持有者（`run_claim`＋`pid_alive`，死声明先记 `run_interrupted` 再接手）。下一步：S5 通用 Skill（`skill/fe-island-evolution`）——按 D5.1/D5.2 先写用户入口再填真实命令，输入只要求 task_dir/任务适配器、任务主指标与方向、配置、数据引用、runs/artifacts 路径与可选 resume ID，不把 HDD 专属字段当通用输入，缺适配器时给具体错误而不是编造一个；S5 之后是 S6（webapi 与三岛界面：`--resume-from`/`--report-only` 的接口化、既有 SmartMem 前端失败、以及 `CostLedger.totals()` 是否改从库行重建——后者目前只汇总当前进程的内存记录，续跑/重建摘要里的该项不含上一进程的记录）与 S7 离线门（含 T09 的 null 预算引擎运行级续跑，以及 D4.4 未做 mutation 的"报告重建不再次付费"一项）。本轮仍不覆盖、留给后续阶段的恢复相关事实已在 D4.3 落地说明逐条列出（墙钟预算每进程重新计时、评估侧计数不从库重建、幂等重放未实现、`--artifacts-dir` 分家时产物在新家重写、webapi resume 端点未接 `--resume-from`/`--report-only`、`IslandStatus` 未新增中断态——D4.4 的"岛 B 暂停时进程退出"用例实测该态本就跨重启存活，故确认不需要中断态，是否要在界面展示中断归 S6 的 registry），D4.4 自己的边界另列在 D4.4 落地说明（可控异常而非真实 kill、`request_id` 只在单进程内唯一因而去重键是 `llm_call.id` 与 `(experiment_id, seq)`、`_restore_run_cost()` 对同一 metrics 对象不幂等、`CostLedger.totals()` 不从库行重建、报告重建一点未做 mutation、真实掉电属 S8/S9）。后续范围仍包括 Backblaze、质询解析、内存/光放大器及 GitCode，不得以这些尚未完成为理由伪称本轮已经覆盖。

进度快照增补（截至提交 6daa23c，S5 阶段门通过）：S5 交付 `skill/fe-island-evolution`（`SKILL.md` 224 行＋`references/{configuration,exchange,hdd-server,recovery}.md`＋`scripts/export_experience_skill.py` 413 行），并先为它补了三处支撑代码——`island_report()` 统一投影（df8a346，实时／重建／崩溃摘要共用同一份 `islands`/`exchange`/`cost`）、岛状态写成枚举 repr 且逐岛成本只存在于一条 SQL 查询（df8a346＋b6b6241，实测续跑后岛 a 2200→3300 tokens、`sum(by_island)+shared_tokens==total_tokens`）、`fe doctor` 原先查的不是要跑的配置（6f0fb04 加 `--config-file` 与 `config_keys`/`config_islands`，使“不认识的键被静默忽略”从此可见）。需求 §6 的“仅写 SKILL.md 或仅通过结构校验不算完成”落成两类可执行测试：`tests/test_island_skill.py` 43 项漂移核对（每个 `fe` 参数、导出脚本参数、事件名、配置默认值、岛状态字面量、相对链接、通用层不得出现主机路径与密钥形状）与 `tests/test_island_skill_walkthrough.py` 7 项端到端走查（T24：步骤 2 预检→步骤 3 `--mock -n 6` 演练→只读重建→步骤 8 导出，外加零交换运行必须交付事实而非规则），两处反向 mutation 证明断言不是摆设。Skill 的输入契约不写 HDD 字段，主指标按引擎事实表述为“唯一标量 `combined_score`、总是越大越好”，方向相反的指标由适配器在 `evaluate()` 内转换；写作过程中的四处错误（`islands.specs:`、`stop.max_iterations:`、投递/采纳/应用混写、把 `stagnation_request_evals` 当成生效字段）在提交前被 `EvolveConfig.from_dict()`、`fe doctor`、导出脚本的四层计数与全 `src/` 检索推翻，原始写法保留在 A0。S5 阶段门 `.venv/Scripts/python.exe -m pytest tests/ -q` → **1730 passed / 0 failed**（925.27s，退出码 0，`C:\tmp\s5\gates\pytest_s5_full.txt`）＝S4 门 1675＋55。**尚未做实的事**：一次真实三岛 HDD 运行至今没有发生过，因此经验草稿只有离线 toy 产物（`497713ef` 的 6 条、`664800e6` 的 0 条），`references/hdd-server.md` 的 S8/S9 命令是模板而非记录，S5 第 5、7 两项验收保持未勾选；E 段本轮填入的是离线 `--mock` toy 演练（`497713ef`）的六条摘要与其采用/未采用事实，表头已写明该层级，D 段（真实运行结果）与真实投递仍待 S9 另填。本轮新增的遗留项：`islands.stagnation_request_evals` 是引擎不读的死配置（S6 是否从界面移除、S7 是否接进引擎需做决定，不能再按生效字段描述）；`CostLedger.totals()` 仍只汇总本进程内存记录（跨进程事实在 `cost_ledger` 行与 `get_cost_rollup`，Skill 的恢复参考已写明，是否改从库行重建归 S6）；`--report-only` 的重建报告不含 `stop_reason`（上一次进程的停止原因不会被重放，Skill 已标注）；回填自身也记了一次不实（A0 的 D5 修正行：6f0fb04 行差写错、走查“7 passed”当时实为 6 项，另 heredoc 编辑静默空跑导致一次“已修”未落地，改用脚本文件＋编辑工具重做并 grep 复核）。既有失败仍在：`web/src/app/App.test.tsx > 评委总览只呈现可用的 HDD 任务入口`（1 failed / 660 passed / 3 skipped，S4 收尾记录，归 S6）。下一步 S6：webapi 暴露三岛投影并把 `--resume-from`/`--report-only` 接口化、修该前端失败、决定 `CostLedger.totals()` 与岛中断态在界面的呈现；S7 离线门补 T09 的 null 预算引擎运行级续跑、`rebuild_run_report()` 的反向 mutation（D4.4 唯一未做 mutation 的一点）与 D4.4 五点的复跑。真实结论仍待 S8/S9，本轮不得据离线绿测宣称三岛优于单树或恢复已在生产环境验证。

进度快照增补（截至提交 49b830d，S6 阶段门通过）：S6 完成了从“服务器真实运行目录”到“界面”的整条链路。①D6.1 逐文件读后发现“发现”环节本身不成立——`paths.list_run_ids` 只扫一层，而服务器会把运行放在日期/批次目录下，`replay_service` 又假设库与报告同目录——于是新增 `webapi/run_discovery.py`：以产物标记识别运行、深度 4／总访问 20 000／错误清单 200 三重上限、软链只登记不下钻、把 `--runs-dir` 的库与 `--artifacts-dir` 的报告配对成一个位置，来源按证据判定（fixture 根／运行登记表／unverified），并由 `GET /api/runs/provenance` 发布可对账的计数（`scanned = runs + paired`、`runs = listed + fixtures`）。②回放层加 islands/exchange 投影（契约 1.12.0／1.13.0）：单树运行给 `missing`＋说明、字段类型不对给 `invalid`＋路径、缺字段留 null，六个交换事实不合并，外岛来源边以 `summary_cross` 表达且不参与树布局。③修四处真实缺陷：森林导出只带 9 个节点里的 3 个（原先只导出 `engine.tree`，改为按岛从库读）、摘要采用连接键接在“投递目标岛”上（改为按摘要连接）、`Store` 只读分支只收 `Path`（`rebuild_run_report(Store(str(...)))` 直接 AttributeError）、脱敏正则只吃半个转义（JSON 转义主机路径残留 `\Users` 使 `events.jsonl` 解析失败）。④三岛 fixture 入库＋脱敏（`0808f94`，事实与界限见 E 段两处补充）。⑤前端：三岛概览／岛切换与并列树／交换详情／岛最优／历史单树与空态（`95d25c4`），产品路径去 showcase（`f3e8259`，同时清掉了 S4 起就存在的 `App.test.tsx` 既有红——它本来就等这次去 showcase）。⑥E2E 门先是被 1.11 合并丢掉的 `@playwright/test` 依赖弄死，补回（离线 store 已有 1.55.0＋chromium-1187，无需下载）；再修两个定位器缺陷（顶栏「设置」与侧栏「项目设置」strict mode 冲突、fixture 里「尝试」与「树内节点」都是 7 导致 `getByText('7')` 命中两个元素）后全量 76 passed。终态数字（49b830d，回填期以新日志复跑）：`pytest tests/webapi -q` → **413 passed**（45.83s）；S6 webapi 四文件切片 **62 passed**（8.00s）；`test_island_forest_export.py`＋`test_build_run_fixture.py` **10 passed**（4.67s）；契约两步再生成无漂移、`check_web_contracts.py` → `contract check OK: 4 files match the Python source`（`pnpm sync:contracts` 直跑退出码 9009 是脚本调裸 `python` 的本机问题，非仓库缺陷）；`tsc --noEmit` 退出码 0、vitest **752 passed \| 3 skipped**（15.51s）、eslint 0 error（1 个既有 warning）、`vite build` 退出码 0；`pnpm test:e2e` → **76 passed**（2.4m）。五个 discovery 反向 mutant（关配对／任意配对／放宽深度／按名字判来源／去掉标记门）各有断言转红，恢复后 14 passed。**没做的事与边界**：D 段（真实运行结果）仍是待填——本轮全部证据都在离线 mock／fixture 层，E 段新补的三岛行来自已入库的 mock fixture 而不是真实运行，真实投递与真实提升仍待 S9；`CostLedger.totals()` 只汇总本进程内存记录、`islands.stagnation_request_evals` 是引擎不读的死配置，两项 S6 均未处置，按原计划转 S7 决定（前者或改从 `cost_ledger` 行重建，后者或接入或从界面/配置移除）；`--report-only` 重建报告不含 `stop_reason` 的既有边界仍在。T19–T23、T25 已从"未测"改为 PASS（逐一映射真实函数，见 C 段映射表）；T09 的 null 预算引擎级续跑、`rebuild_run_report()` 的反向 mutation、D4.4 五点复跑仍按 S7 清单执行。下一步：S7 离线检查与测试门（全量 `pytest tests/ -q`＋`pnpm typecheck/test/lint/build/check:contracts`＋E2E＋`git diff --check`＋受保护路径 diff 核对），随后 S8 服务器部署与真实预检、S9 正式 HDD 运行与服务器 WebUI、S10 PR 与交付。

进度快照增补（2026-10-08，S7 阶段门通过）：S7 是纯离线阶段，四条 S4 遗留（①–④）＋一条 S6 遗留（⑤）＋D4.4 五点复跑全部落地。①T09 的 null 预算补了引擎运行级用例（`test_island_resume.py::test_a_resume_without_a_token_cap_keeps_spending`：去掉 token 上限后中断续跑仍继续花费、引擎未早停），反向 mutation M2 把 `cap is None` 当"已达上限"处理时 `tests/test_island_resume.py:480` 转红。②"把 `rebuild_run_report()` 改成会重新评估"这条字面 mutation 经逐行核对不可表达（其调用树 `export_forest`／`get_cost_rollup`／`island_report` 均无评估器引用），改为在可证伪的缝上补引擎级孪生用例——续跑重写丢失报告不得再调评估器（`test_island_fault_injection.py::test_resuming_a_finished_run_rewrites_a_lost_report_without_evaluating`）——M1 让续跑重跑一个 iteration 时 `_call_count` 断言（4≠3）在 `tests/test_island_fault_injection.py:399` 转红。③`CostLedger.restore_rows()` 落地：`init_ledger()` 与 `rebuild_run_report()` 都从 `cost_ledger` 行重放（后者经一次性账本产出 `summary["cost_ledger_totals"]`），续跑／重建摘要里的逐岛成本不再只含本进程记录；新用例 l9＋M3a（续跑丢弃行）／M3b（重建不投影账本视图）双 mutant 咬住。④评估侧计数（`valid_count/invalid_count/jev_calls/evaluations_saved`）决定不从库重建：`invalid_count` 含尝试级失败（`engine.py:2660/2706/2738/2753/2769/2791/2835/2850` 的 `add_eval(0, False)` 无对应可评估行）、`jev_calls` 是本进程计数（`engine.py:2990`）且 JEV 默认 `"none"`（`config.py:288`）、运行摘要 `valid_count` 是节点派生 `len(scored)`（`engine.py:4612`）——没有精确的库侧来源，强行重建会造出口径不一致的第三个数；岛上真值（`valid_evaluations／invalid_evaluations`，`common/schemas.py:405-406`）本就持久化并已恢复。⑤`islands.stagnation_request_evals` 按"不接线、不删字段、如实标注"处置：需求文档对"停滞/求助"0 命中、`web/` 无读取点，界面标签改为「停滞求助间隔（引擎未读取）」并注明当前无调用点，重导 `ui-metadata.json`（仅 2 行变化），契约检查＋33 项相关测试复跑全绿；D3.3 勾选项保持未勾。S7 阶段门：全量 `.venv/Scripts/python.exe -m pytest tests/ -q` → **1799 passed / 0 failed**（894.00s，退出码 0，19:39:09→19:54:04，`C:\tmp\s7\gates\pytest_s7_full_final.txt`）＝S6 门 1796＋3（三个新用例），既有 1796 项无回归；运行前冻结工作树（`83535ef`＋8 文件脏 diff，sha256 `9abb0241…`），提交 `d26c532`＋`123ac28` 后 `git diff HEAD` 为空；19:34 首跑因回填期补落 `catalog.py` 修正于 16% 处主动停止，残余输出留档 `pytest_s7_full_aborted.txt`（不作证据）。前端链路在终态树上七步全 0（vitest **752 passed \| 3 skipped**、e2e **76 passed**；第 4/6/7 步管道 `EXIT=` 取值缺陷已在日志内更正并以不经管道的复跑取真退出码）。**边界**：S7 全部证据离线——E2E 跑在临时运行根、页面读的是 fixture／mock，真实服务器部署与真实三岛运行属 S8／S9，不得据此宣称生产环境已验证；`--report-only` 重建报告仍不含 `stop_reason`（既有边界未变）；`CostLedger.totals()` 跨进程重放只覆盖续跑与重建两处入口，恢复后评估侧计数按 ④ 的口径以岛上真值为准。下一步：S8 新服务器路径部署与真实预检（三岛各 2 候选尝试、`exchange_interval=1`、并发 1），随后 S9 正式 HDD 运行与服务器 WebUI、S10 PR 与交付。

进度快照增补（2026-10-08，S8 真实预检完成）：S8 在新部署根 `/home/hcf/faultevolve/three_island_20261008-200410/` 执行了第一次真实三岛 HDD 预检（run `hdd_mvp_preflight_20261008`，代码 `7687df2c`，20:07:36→20:32:08 +08:00）：完整历史 bundle＋服务器 `git clone --branch`（两侧 sha256 `93469ba9…`）、独立 `.venv`（Python 3.13.11，48 包）、`preflight/{runs,artifacts}` 分家根、`--env-file` 注入已授权 `.env`（只输出布尔值）、`HDD_BENCH_DATA_ROOT` 指向 NAS 只读 HDD 数据（六个允许文件逐一指纹、`holdout` 从未列举/读取）。三岛各 2 尝试、`exchange_interval=1`、并发 1：best `4c1635ca`（b 岛）38.2067，初始 22.8074（Δ+15.3993）；b 岛在两次尝试内产生真实改进，c 岛也改进到 36.6104（Δ+13.8031），a 岛 2 尝试未改进（1 个语法错误候选＋1 个 smoke_rejected，均未进入评估）。a 岛两个失败候选自然产生两条 failure 摘要并投递到兄弟岛；10 投递全部 accepted/applicable、11 采用全部 evaluated；关键链路 `sum-3b709a88`→`dlv-ce915ea4`→`app-d1a808ad`→`f0cd9659`（36.6104）证明“跨岛摘要→嫁接候选→接收岛本地重评”在真实运行里成立。13 次真实 LLM 调用（qwen3-coder-plus×9＋qwen3-max×4）全部 `outcome=ok`，5 次真实评估器执行（评估合计 688.77s），tokens 76499，`cost_usd=null`/`cost_basis=unknown`（未配价格表，不以 token 猜费用）；mock 痕迹扫描三处全 0，judge `none`。**未做与边界**：退出码不可回取（`nohup … &` 直起未包裹 `$?`；完成证据是控制台尾部 `Evolution completed: finished / Best score: 38.21`＋DB `status=finished`），S9 启动器将以 `sh -c '…; echo $? > exit_code.txt'` 包裹；预检未发生中断，服务器端恢复命令仍未实测执行；经验 Skill 草稿未在预检导出（按计划属 S9 正式运行交付物）。正式运行（每岛 ≤50 尝试、`exchange_interval=5`）与服务器 WebUI 属 S9，PR 与交付属 S10。按 Skill 操作发现的三处与实际不符（bundle 方式、环境、运行根布局）已写回 `references/hdd-server.md`，测试复跑 50 passed（`C:\tmp\s8\gates\pytest_skill_s8.txt`）。
