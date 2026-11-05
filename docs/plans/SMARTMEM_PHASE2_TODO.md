# 第二版开发 TODO：内存预测完整闭环逐步实现

> 日期：2026-10-03。需求合同：[第二版需求](SMARTMEM_PHASE2_REQUIREMENTS.md)。前置实现：[第一版需求](SMARTMEM_PHASE1_IMPL_PLAN.md) 和 [第一版 TODO](SMARTMEM_PHASE1_TODO.md)。
>
> 本文件用于新的能力有限 AI。先实现一个可手算、可运行的 toy 闭环，再接真实数据。不得越过未完成的评分协议或数据边界直接调用真实 LLM。

## A. 开始前向用户收集

复用第一版已经提供的资料，不要求用户重复提供。新增缺项一次性索取：

- [ ] V1 验收 commit、数据 contract、manifest 与输出目录。
- [ ] 用户现有内存尝试代码版本、已有结果和可复现命令。
- [ ] 用户已有或官方评分脚本；如只有 F1 数字，索取告警匹配/重复告警/A-B 汇总/时间边界定义。
- [ ] 用户是否以官方协议复现为验收，或接受明确命名的独立本地协议。
- [ ] 目标阶段与预测格式、标签覆盖截止、身份重置规则。
- [ ] CPU/内存/单候选超时/磁盘限制，以及首次真实运行的轮次、Token、墙钟预算。
- [ ] 跳板机连接说明、目标 SSH 和新工作根目录，原始数据只读路径。
- [ ] 服务器 yolo26 环境版本，是否存在允许真实候选执行的隔离 runner。

缺 scorer 时可实现 local_provisional 评分与 toy 测试，不宣称官方协议一致。缺预算或服务器信息时继续离线开发，真实运行项留 pending。

## B. 分支与阅读

- [ ] 读根 AGENTS.md 和要求的四份文档，再读 V1/V2 需求。
- [ ] 确认 V1 已合并到最新 main；若未合并，只能从用户接受的 V1 固定 commit 开分支，PR 标依赖。
- [ ] 在干净工作区从最新 origin/main 建 `feat/smartmem-full-loop`。保留用户修改，不 reset 或覆盖。
- [ ] 读 `TaskSpec/EvalResult/TaskAdapter`、`FamouAdapter`、registry 和 engine 的 adapter 调用点。
- [ ] 读 `run_local_evolution()`、smoke、analyze、reflection 与知识检索调用；读 `MockLLM`。
- [ ] 读现有 report CLI：它用于 discovery/tournament，不能直接假设已提供完整内存报告。
- [ ] 记录基线 commit、Python、测试收集与 Linux 回归结果。

当前接口事实：引擎允许传 `adapter`，构造器允许传 LLM；`--mock` 默认生成硬盘程序且仍使用真实评估，必须补通用 replay 入口；registry 的 smartmem 仍为 stub，需要在完整 adapter 就绪后迁移。

## C. 实现顺序

| 编号 | 内容 | 硬前置 |
|---|---|---|
| V2-00 | 固定 data/metric 合同 | V1 |
| V2-01 | 候选公开快照 | 固定数据 schema |
| V2-02 | 事件 scorer 与参考对齐 | 明确 MetricSpec |
| V2-03 | evaluator/受约束 runner | 快照/scorer |
| V2-04 | init/problem/prompt | evaluator contract |
| V2-05 | 完整 adapter | 四件套 |
| V2-06 | smoke/画像/关键词 | adapter |
| V2-07 | 内存 mock 与核心进化 | 可运行 toy |
| V2-08 | 恢复/最终裁决/报告 | 核心闭环 |
| V2-09 | 导出官方格式 | 预测 contract |
| V2-10 | 本地全量回归与交付 | 前述均完成 |
| V2-11 | 新服务器真实运行 | 用户输入/环境/预算齐全 |

## V2-00：把设计落实为版本化文件

- [ ] 在 `benchmark/smartmem/data_contract.md` 写清 sample/feature/index/label/coverage/outcome 的列、主键、类型和时区。
- [ ] 固定 dev 为进化集、val 为最终集。所有默认 evaluator 调用评价 dev。
- [ ] 新增 `metric_spec.yaml`，记录 lead/horizon、matching/duplicate/type aggregation、主分比例和 source hash。
- [ ] 源码未知字段填写 local_provisional；拒绝未知规则值，不能默认成自己猜的官方规则。
- [ ] 把用户已有结果和新协议差异填表；没有同 split/metric，不计算“提高了多少”。

MetricSpec 的 config key 名称必须与评分函数一致。协议版本改变后 hash 必变，禁止恢复到旧 run。

## V2-01：构建候选可见快照

文件：`benchmark/smartmem/build_candidate_data.py`；共享逻辑如需复用可放 `tasks/smartmem_data.py`。

```python
def build_candidate_snapshot(
    prepared_root: Path,
    out_root: Path,
    *, metric_spec_path: Path,
) -> dict[str, object]:
    ...
```

逐步实现：

1. 读 V1 manifest，检查 complete/audit/hash，未完整拒绝。
2. 验证输入与输出不是相同路径，输出目录不存在或明确属于同一未完成新快照。
3. 按 split 分离 features/index/train labels；ticket 与 outcome 仅进 scoring-private。
4. 校验 sample_id 唯一且 key 集合一致，不依赖行序。
5. 排除 label、failure_time、未来统计、unit ID、split 和 timestamp 作为模型列。
6. 写固定文件和候选 manifest，完成后生成快照 hash。
7. 报告资源和数据规模，只输出匿名汇总。

测试文件 `tests/test_smartmem_snapshot.py`：

- 合法 fixture 完成；feature/index 顺序打乱仍 join 正确；
- label/failure_time 混进 features 立即拒绝；
- dev/val labels 不存在 public 目录；manifest 不含标签摘要与源路径；
- 重复或缺 sample_id 拒绝；旧 manifest/version 拒绝；
- 未完成输出与完整输出区分；不覆盖已有文件；
- 源数据内容不变；受保护输出路径拒绝。

## V2-02：先写评分器，再写 evaluator

文件：`src/faultevolve/tasks/smartmem_metrics.py`。用需求第 5 节接口 `score_alerts()`，纯函数不执行候选、不联网。

- [ ] 输入先验证预测 key、alarm 类型、index 时间和 outcome/coverage 主键。
- [ ] 使用 UTC timestamp 对比，lead/horizon 等号按合同，不能用字符串排序。
- [ ] 合格故障分母从完整 at-risk/outcome 构建，而非从有预测单元过滤。
- [ ] 实现固定的告警匹配与重复规则，输出 TP/FP/FN、censored、按类型和整体指标。
- [ ] sample_f1 与 event_f1 分开；不要把 sklearn f1_score 直接当事件 scorer。
- [ ] 输出 score=100×event_f1，不混入 AUPRC/ROS/time_factor。
- [ ] bootstrap 以单元为簇，保留整条时间线；重采样同 unit 多次时复制成不同虚拟簇身份，避免重复键校验把重采样当坏数据。
- [ ] std 用 0..1，adapter 噪声阈值再乘 100；写固定 seed。

手算例：同一 unit 故障一次，两个提前合法告警，在 local_provisional 一对一规则下 TP=1、FP=1、FN=0，F1=2/3。参考官方若合并告警得到不同值，新增明确协议分支，不能偷偷改本地算法。

测试 `tests/test_smartmem_metrics.py` 至少覆盖：

| case | 检查 |
|---|---|
| 15min 下边界 | 早 1ns 不匹配，等号匹配 |
| 7d 上边界 | 等号匹配，晚 1ns 不匹配 |
| 仅 10min lead | 不合法提前告警 |
| 一故障多告警 | TP 上限、duplicate 规则 |
| 一告警多故障 | 一对一匹配规则或官方规则 |
| 无告警有故障 | FN 存在，F1=0 |
| 无故障有告警 | FP 存在，F1=0 |
| 空两侧 | zero_division=0 |
| 无预测样本的故障 | 仍按 eligibility 计 FN |
| coverage 未完成 | censored 排除并报告 |
| A/B 各组大小不同 | micro/macro 差异和正式规则 |
| 重采样 | unit cluster std 可复现 |

如取得 scorer：保存匿名 golden 输入，逐项比较 TP/FP/FN/F1/A-B 汇总，固定参考 hash，不仅比较一条 F1 浮点数。

## V2-03：实现 evaluator 与候选运行边界

文件：`benchmark/smartmem/evaluator.py`。保持可 import 的 `evaluate()`/`static_check()`；module import 时不跑数据、不启动子进程。

实现顺序：

1. 检查代码 AST 和既有 forbidden 规则。
2. 校验数据/评分 manifest，明确 split 默认 dev。
3. 创建本次专用 runtime 临时目录，只公开 train 与当前 split 文件。
4. 使用当前 `sys.executable` 执行候选，argv 列表，不拼 shell 字符串。
5. 清除子进程密钥/SSH 凭证，仅给必要环境；设置内存、CPU、超时和输出上限。
6. 读取 out，校验列/key/有限 score/二值 alarm。
7. 调用 scorer、bootstrap，返回 EvalResult 结构。
8. 错误日志脱敏，finally 清理本次创建的 temp。

建议将通用 executor 放独立 runner helper，SmartMem 私有评分 join 仍在可信 evaluator。临时 public 副本的 allowlist 不允许指向 private 的符号链接。Linux 真正 sandbox 需用户已有容器/受限 runner：私有标签只在可信 scorer 中读，候选无网络且无法读旧工作目录。

测试 `tests/test_smartmem_evaluator.py`：

- 成功程序/非零退出/不输出/错列/重复缺 key/额外 key；
- NaN/Inf、alarm=2、浮点非整数、空文件；
- 超时和子进程退出后无遗留，stderr 达上限时保留脱敏尾部；
- static_check 拒绝 ticket/private/越界/网络/子进程；
- 环境密钥哨兵不传给候选；
- parallel data_root A/B 互不串用；
- 候选看不到 dev labels/scoring-private；
- import evaluator 不读取数据。

有限静态规则测试通过只能标 sandbox_status=limited。真实未审查 LLM 候选运行要验证 OS 隔离，不能写成安全保证。

## V2-04：初始程序和任务提示

新增 `init.py/problem.md/prompt.md`。

- [ ] init 自包含，读固定文件名，通过 sample_id join，输出完整 index。
- [ ] 有用户已有可靠代码时记录引用；没有就建确定性 LightGBM/逻辑回归，不强行引入神经网络。
- [ ] train 内部按时间拆 model-fit/calibration，label windows 做 gap，不读 dev/val 标签。
- [ ] 预处理只在 model-fit 数据拟合，未知类别有默认；是否最终全 train 重训要记录，不能重新在最终集择阈值。
- [ ] 固定 seed/线程/训练轮数，限制模型内存，异常不能用全零输出悄悄兜底。
- [ ] problem 写输入/输出、事件 F1、scale=100、固定时刻、资源和禁用项。
- [ ] prompt 写内存领域字段语义、schema 和知识采用标签 `<adopted_cards>`，不要从 HDD prompt 机械复制属性。

测试 `tests/test_smartmem_init.py`：toy 独立运行、无 private 读取、行序置换、未知类别、同 seed 相同预测、阈值无 dev 标签依赖。正式数据无正例或校准区间不足时给明确错误，不能宣称模型训练成功。

## V2-05：替换完整 adapter

修改 `smartmem_adapter.py` 继承 `FamouAdapter`，实现需求第 7 节接口。

- [ ] `__init__` 接受 registry 已传的 min_noise_delta/kappa 等参数，或让 registry 签名过滤保持正确。
- [ ] data_root 优先显式参数/环境 SMARTMEM_DATA_ROOT，再 task_dir/data；不用 HDD_BENCH_DATA_ROOT。
- [ ] `evaluate` 写本次候选文件，显式 evaluator(split="dev",data_root=...)，finally 清理。
- [ ] `get_noise_delta` = max(最小分差,kappa×100×std)，不要将 0..1 std 当百分制。
- [ ] `constraints/data_schema/edit_guidance/api_notes` 返回可理解的候选合同。
- [ ] `context_keywords` 为内存领域通用词/特征标签，不读取标签，不泄漏身份。
- [ ] ObjectiveSpec 的排序/阈值/noise key 与 scorer 返回一致。
- [ ] DataStatusProvider 只读元信息，不打开私有 outcome。
- [ ] 从 registry stub 清单移除 smartmem，保留 alibaba_ssd。

迁移 `test_dataset_stubs.py`：SmartMem evaluator/任务准备由“必须失败”变为完整任务成功与缺文件明确失败；不删除 SSD stub 和 HDD 原测试。

测试 `tests/test_smartmem_adapter.py`：Protocol isinstance、factory alias、自定义 task root、缺数据、静态检查、noise scale、约束提示、data_status 不读 private。

## V2-06：smoke、画像与知识接入

- [ ] build_smoke_data_dir 按完整单元抽样，默认 min positives 要适配 fixture 规模，不能无限循环找正例。
- [ ] smoke_cache key 含 data/metric hash、fraction/seed；不复用不同版本。
- [ ] smoke_test 使用采样数据，不回传 smoke score 作为主分。
- [ ] analyze 使用 dev 可信缓存或重跑，只输出事件 FN/FP 聚合。
- [ ] fn_groups 结构与现有定向算子吻合，样本计数单位明确为单元/故障。
- [ ] 小于 10 单元分组抑制；样本窗口密度不等同硬件样本数。
- [ ] 画像内容不得含 unit、ticket 精确时间或私有路径；采样调试不把数据内容写事件表。
- [ ] 提供/采纳 SmartMem 知识卡，库路径只加载本任务包，不复用 HDD 默认 FE01/M01。

测试 `tests/test_smartmem_analysis.py`：FN/FP 手算、抑制、无敏感哨兵、无 val 读取、分析失败不改 score、卡片关键词关联。

## V2-07：toy 进化与通用 mock replay

先用 Python API 注入 Scripted MockLLM 和 SmartMemAdapter 跑 toy，后补 CLI 通用入口。禁止在 engine 里写 SmartMem 专用分支。

建议接口：

```text
--mock-responses <JSON_FILE>   # 开发目标，必须先实现才可使用
```

JSON 包含有序 `chat` 和 `reasoning` 文本，每个 chat 返回完整内存程序/intent/真实存在的 SM 卡 ID，脚本响应耗尽时明确失败或循环规则，不静默回退硬盘模板。该参数只在 --mock 下生效。

- [ ] mock 使用真实 toy evaluator，不用 FakeAdapter 给伪分。
- [ ] 三轮至少覆盖成功、失败进入 repair、知识注入；反思响应与请求种类匹配。
- [ ] 比较 DB 和 run_summary 的 score/token/eval counts。
- [ ] scalar UCT 主路径通过后测 bandit/recall_focus/threshold_calibrate。
- [ ] 候选有效性、主分、经验只来自本地 evaluator。
- [ ] Jev/KD/crossover 保持默认关闭；开关必须是配置选择，非默认强制实验。

测试 `tests/test_smartmem_evolution.py` 和 `tests/test_mock_replay.py`：离线无 HTTP、输出内存合同、修复、卡片采用、invalid 分数、Token 记账、旧 mock CLI 兼容。

默认 mock 样本量太少时 tiny run 只验证产物结构，不解读指标为真实效果。

## V2-08：恢复、最终裁决和报告

新增运行 fingerprint helper，在首次 initialize 前写指纹，在 resume 时读取并比较。必要的引擎改动使用通用参数或可选 Protocol，不能向 cloud 添加任务字段词。

- [ ] 指纹包含 commit、data/metric/knowledge/config hashes、seed、score scale、资源和环境版本。
- [ ] resume 数据/metric 不一致明确拒绝，不能载入旧 best_score 继续新任务。
- [ ] 同 run 正常中断恢复保留 experiment id，新增 run 分配新 ID/目录。
- [ ] `finalize.py` 从 DB 找 dev best 节点并验证 artifacts 程序 hash，不能仅靠目录最新文件。
- [ ] 固定 baseline 与 best 两个程序评价 val，生成独立 final_evaluation.json；不写入 node evaluation score。
- [ ] finalize key=code/data/metric hash；已完成同 key 返回原结果，配置改变建新目录。
- [ ] 写报告 helper 从 DB/manifest/final JSON 取值，不能复制 README 的历史 HDD 分数。
- [ ] 模板每个数字有来源键；not_run 不填 0 冒充完成；local_provisional 必须显示。
- [ ] 本地 score point、真实 F1、相对提升及 tokens_per_point 的单位一致，零/负提升时不除零、不宣称正收益。

测试 `tests/test_smartmem_resume.py` 和 `tests/test_smartmem_report.py`：正确恢复、变数据/metric 拒绝、程序 hash 冲突、finalize 幂等、val 不回写 DB、预算记账、报告数值对账、评分状态声明。

现有 fe report 不必重写。任务专用报告入口明确给命令，后续如要集成则采用通用 report provider，保持 discovery 报告兼容。

## V2-09：提交格式导出

新增 `benchmark/smartmem/export_submission.py`：

- [ ] 读完整预测和可信 test index，验证 key 集合。
- [ ] 只导出 alarm=1，列 `sn_name,prediction_timestamp,serial_number_type`。
- [ ] 时间输出采用用户/官方指定格式；timezone 清楚，类型未知明确失败。
- [ ] 重复处理只依据已核实协议，不能擅自 cooldown。
- [ ] 输出已有文件拒绝覆盖；压缩包内只放 submission.csv，不打包数据或日志。
- [ ] 序列号只出现在本地正式 submission，stdout/报告不打印。
- [ ] 不登录或自动提交 Codabench。

测试 `tests/test_smartmem_submission.py`：准确列、只保留 alarm、UTC 格式、空告警合法输出、未知身份/类型、重复策略、覆盖拒绝、ZIP 清单无多余文件。

## V2-10：本地完整验收

依次运行本版新测试、旧 adapter/engine 测试与全量：

```bash
python -m pytest tests/test_smartmem_snapshot.py tests/test_smartmem_metrics.py tests/test_smartmem_evaluator.py -q
python -m pytest tests/test_smartmem_init.py tests/test_smartmem_adapter.py tests/test_smartmem_analysis.py -q
python -m pytest tests/test_smartmem_evolution.py tests/test_mock_replay.py tests/test_smartmem_resume.py tests/test_smartmem_report.py tests/test_smartmem_submission.py -q
python -m pytest tests/test_adapter_registry.py tests/test_dataset_stubs.py tests/test_engine_task_agnostic.py tests/test_hdd_protected_files.py -q
python -m pytest tests/ -q
git diff --check
git status --short
```

- [ ] Linux 全量测试证据；Windows 原有 resource 问题单独记录，不能全局 mock resource 假装安全限额有效。
- [ ] CLI 帮助的选项与文档一致。未来选项没实现前不能在交付说明说已可用。
- [ ] toy init 评价 → 3 轮 mock → resume → finalize → report → export 逐条真实运行。
- [ ] 单元测试、toy 与真实小样本结果分开，禁止以 fixture F1 报项目效果。
- [ ] 无受保护 HDD 改动，旧 adapter 无行为变化。
- [ ] 根据需求标 L0/L1/L2/L3 达到的等级，缺 scorer 不标官方复现通过。

## V2-11：服务器隔离测试及真实运行

本节是实际开发后的执行清单。当前撰写 TODO 不等于授权立即连服务器或调用付费 LLM。

### 11.1 SSH 与隔离目录

- [ ] 用户提供跳板或反向隧道说明，确认目标主机；认证凭证只在环境/安全通道。
- [ ] 首选新 `/home/hcf/nas_hcf_data/faultevolve_smartmem_v2_<唯一标识>`；无权限回退新 `/home/hcf/faultevolve_smartmem_v2_<唯一标识>`。
- [ ] 对 final realpath 按组件判断，不在 `/home/hcf/nas_hcf_data/faultevolve` 或 `/home/hcf/faultevolve` 内。
- [ ] 固定 commit 部署新 code，独立 artifacts/data/logs。不得修改旧 Git 或建立依附旧仓库的 worktree。
- [ ] 另建本地磁盘新 runs/runtime/temp；mount 检查排除 CIFS/NFS。SQLite 与 NAS artifacts 分开。
- [ ] 原始数据仅按用户路径只读挂载到准备程序；候选 runner 不挂载旧目录。

### 11.2 yolo26 检查

```bash
conda activate yolo26
which python
python --version
python -m pip --version
```

- [ ] 检查 pandas/numpy/sklearn/lightgbm/pyarrow/openai/httpx/typer/pydantic 是否满足锁定版本。
- [ ] yolo26 3.11 与 requires-python 3.12 的冲突明确报告；不能 `--ignore-requires-python` 安装后隐藏问题。
- [ ] 不擅自激活 faultevolve 环境替代 yolo26。不擅自卸载/升级共享依赖。
- [ ] 若用户认可本版支持 3.11，提交独立兼容变更并测 3.11/3.12；若不支持，真实步骤标 blocked_env，保留本地成果。

### 11.3 命令记录与执行顺序

用户已认可环境和真实运行预算后，显式设置新路径：

```bash
export SMARTMEM_DATA_ROOT='<NEW_CANDIDATE_DATA>'
export FE_RUNS_DIR='<NEW_LOCAL_RUNS>'
export FE_ARTIFACTS_DIR='<NEW_ARTIFACTS>'
```

这些不含密钥；真实 LLM 密钥仅从用户指定的环境读取，不复制旧 .env 到 code 或输出。

执行顺序：

1. Linux offline 全量测试。
2. V1 profile/10 文件处理与泄漏审计；已有正式数据可校验 manifests。
3. 构建新候选快照。
4. 单次 init dev 评价，记录合法性/资源和主分。
5. 3 轮 replay mock，验证新目录产物与恢复。
6. 检查真实 candidate sandbox 能阻止外网和旧目录/私有数据读取。
7. 依用户轮次/Token/时间预算启动真实进化；后台方式使用用户环境已有工具，保存 PID/run id，不结束其他任务。
8. 监控新日志、有效率、预算和 DB，异常保留现场，合法步骤内恢复。
9. 完成后固定 best code，finalize 一次，生成新报告。
10. 如用户要求，对官方 test 做推理和本地导出。

真实启动目标命令（应先实现 replay 选项）：

```bash
fe evolve local benchmark/smartmem --mock --mock-responses <TOY_REPLAY_JSON> --iterations 3 --runs-dir <NEW_LOCAL_RUNS> --artifacts-dir <NEW_ARTIFACTS>
fe evolve local benchmark/smartmem --iterations <USER_ITERATIONS> --runs-dir <NEW_LOCAL_RUNS> --artifacts-dir <NEW_ARTIFACTS>
python benchmark/smartmem/finalize.py --db <NEW_DB> --artifacts <NEW_RUN_ARTIFACTS> --data-root <NEW_CANDIDATE_DATA> --out-dir <NEW_FINAL_DIRECTORY>
```

命令中所有占位符由当次运行输入替换，不复制到旧目录执行。不同实验使用新 ID/新结果目录，resume 只针对同一指纹的 run。

### 11.4 最终证据

- [ ] 记录 SSH alias、code commit、yolo26 实际依赖、data/metric/knowledge hash、sandbox 状态。
- [ ] 记录 baseline/best dev、固定程序 val、指标状态、统计区间、预算与成本。
- [ ] 与用户旧结果在同合同下对比，不能对齐则标不可直接比。
- [ ] 两个旧目录无写入；不为完整性检查递归读取 holdout。
- [ ] 每个新目录、PID、run id、失败日志和可恢复操作均有说明。
- [ ] 未达到性能目标如实分析，不用重选 val 最优掩盖结果。

## D. 提交建议与 AI 交接模板

建议每个模块一个提交：contract/snapshot → scorer → evaluator → init/prompt → adapter/smoke/analysis → mock/engine 接入 → resume/final/report → submission → docs/真实验收证据。

每次提交说明：触发问题、实现行为、测试命令、score 单位、已核实/暂定协议和现有接口兼容性。不要把用户数据、预测、密码、密钥或旧结果拷入 PR。

最终交接至少填写：

```text
V1 base commit:
V2 commit/branch:
Verified user inputs and remaining pending items:
Data/metric/knowledge versions:
Offline tests and real-run acceptance level:
Current score protocol (verified/local_provisional):
New server code/data/runs/artifacts paths:
Conda environment and compatibility status:
Best dev node and final report identity:
Resume command and fingerprint:
Known limitations (KD/UI/cloud APIs):
```

如果核心闭环尚缺评分协议、隔离环境或真实输入，保留完整代码和已通过测试，明确对应未完成的验收等级。不得把缺少真实证据的项目勾为完成。
