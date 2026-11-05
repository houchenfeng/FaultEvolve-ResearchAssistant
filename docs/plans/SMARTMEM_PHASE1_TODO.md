# 第一版开发 TODO：给新 AI 的逐步执行手册

> 日期：2026-10-03。对应需求：[SMARTMEM_PHASE1_IMPL_PLAN.md](SMARTMEM_PHASE1_IMPL_PLAN.md)，必须连同第 16 节阅读。
>
> 本文件描述待开发任务，不代表接口已经存在。一次完成一个步骤：先写会失败的行为测试，再实现，再运行该步骤测试，最后记录证据。第一版范围为数据处理与内存知识包。

## A. 接手时先发给用户的信息清单

使用下列文字一次性收集，不反复询问已经回答的项目：

> 为把您已尝试的内存方案接入 FaultEvolve，请提供：① 原始数据本地路径或下载链接、CSV/Feather 格式与阶段；② 已运行代码路径/仓库链接、入口与依赖；③ 已有结果、运行命令、split/指标定义及评分脚本；④ 日志/ticket 时间格式与时区、故障标签覆盖截止；⑤ DIMM 多次故障或更换规则；⑥ CPU/内存/磁盘/处理时长限制。服务器测试阶段还需要跳板 Host/端口/用户/连接方式和可读数据路径。认证凭证不要写入仓库或日志。

填写输入状态表：

| 输入 | 缺少时如何继续 |
|---|---|
| 数据路径与格式 | 只开发合成 fixture，不转换真实数据 |
| 已有代码 | 先写通用层；知识卡用户运行证据项留 pending |
| 已有结果 | 可以验证流程；不能声称复现/提升 |
| 时间格式/时区 | fixture 用 UTC；真实数据解析暂缓 |
| outcome 覆盖截止 | profile 可做；真实负标签构建暂缓 |
| 指标 | 查官方 F1，细则标 provisional |
| 跳板信息 | 本地可做；服务器阶段暂缓 |

用户私有路径记录到 Git 忽略的工作笔记；共享文档只使用占位符、匿名 run id 和汇总。

## B. 开发前阅读、分支和环境

- [ ] 按根 `AGENTS.md` 顺序读：`docs/dev/MVP开发指南.md`、`docs/design/02-MVP方案-硬盘.md`、`docs/design/01-系统总体设计.md`、`benchmark/hdd_mvp/problem.md`。
- [ ] 读本版需求与第 16 节；再读 `smartmem_adapter.py`、`stub_base.py`、`protocol.py`、`registry.py`、现有 stub 测试和知识 loader/retriever。
- [ ] 执行 `git status --short`，保存基线 hash；若有用户修改，使用独立 clone 或协调后继续，不能清理它们。
- [ ] 在干净工作区执行 `git fetch origin`、`git switch main`、`git pull --ff-only origin main`、`git switch -c feat/smartmem-data-knowledge`。
- [ ] 记录 Python/依赖版本以及现有测试收集结果。当前 Windows 的 `resource` 导入可能导致收集失败，标为已有平台问题，不改测试数伪造通过。
- [ ] 本地 Python 优先满足项目 3.12 要求；服务器仍按用户要求使用 yolo26。两者冲突的处理见服务器步骤。

开始实现前只允许读取公共文档与指定代码，不枚举或读取 HDD `holdout*`，不改 HDD baseline。

## C. 工作顺序总表

| 编号 | 产物 | 前置 |
|---|---|---|
| V1-00 | 输入与既有尝试证据 | A/B |
| V1-01 | 合成数据 fixture | 无真实数据依赖 |
| V1-02 | schema/time 规范化 | fixture |
| V1-03 | anchor/label/censor 采样 | schema |
| V1-04 | 时间切分与审计 | samples |
| V1-05 | SmartMem 字段与特征 | schema/samples |
| V1-06 | 流式 IO/checkpoint | 前述数据合同 |
| V1-07 | prepare CLI | pipeline |
| V1-08 | 知识包与检索 | 既有尝试/来源 |
| V1-09 | Skill/文档/旧测试迁移 | 实现通过 |
| V1-10 | 真实小样本与交付 | 用户输入齐全 |
| V1-11 | 服务器隔离验证 | 本地验收与跳板信息 |

## V1-00：固定用户输入和参考结果

- [ ] 新建 `docs/runs/smartmem-input-evidence.template.md`，包含输入版本、格式、时间范围、metric 状态、已有方法、结果来源和 pending 项。
- [ ] 只读分析用户代码，列出其读取文件、字段、anchor、lookback、标签、划分、特征、模型、阈值与输出格式。
- [ ] 检查其是否用未来事件、官方 test、故障时间选样或全数据编码。
- [ ] 把匿名分析写入 `docs/runs/smartmem-existing-attempt-analysis.md`。未经用户提供不创建虚构结果。
- [ ] 每个结论标 verified/user_reported/pending，保存代码版本而非整个私有源码到共享报告。

通过条件：能够指出旧结果使用的具体协议；有风险时保留记录，但新实现采用需求规定的防泄漏规则。

## V1-01：建立能手算的 fixture

新增 `tests/helpers_smartmem.py` 动态生成数据到 pytest `tmp_path`，不需要真实数据。

- [ ] 使用 `unit-a` 等虚构身份，造至少 6 个单元、120 天时间跨度、A/B 类型、23 个字段。
- [ ] 包含一个无故障、一个有故障、一个重复 ticket、一个乱序/重复事件、一个静态字段缺失、一个随访不足的单元。
- [ ] 不使用实际生产序列号；敏感性测试另设置哨兵字符串，验证它不进入日志/摘要。
- [ ] 设置首故障、紧邻 lead 左右边界、horizon 左右边界和故障后事件。
- [ ] 为 CSV/Feather 生成同一逻辑内容，测试必须实际读写 Feather，缺 pyarrow 作为明确依赖错误，不通过 skip 隐藏。

通过条件：至少一组样本标签和一个空间计数可以纸面手算；fixture 不依赖当前日期或 hash 随机化。

## V1-02：规范化 schema 与时间

文件：`src/faultevolve/data/event_schema.py`。

实现：

```python
def normalize_events(
    frame: pd.DataFrame,
    schema: CanonicalEventSchema,
    *, timezone: str,
    duplicate_policy: str = "drop_exact",
) -> pd.DataFrame:
    ...
```

- [ ] 验证 unit/time 列存在，空或非法 unit 明确报错。
- [ ] 有时区时间转 UTC；无时区时间先按指定 timezone 本地化。DST 歧义和无效时间默认失败。
- [ ] dtype 和类别只做逐字段转换；不能用 label 决定数值填补。
- [ ] 精确重复按全部原始字段判定；不能以相同时间直接丢掉不同错误地址。
- [ ] 稳定排序并返回新 frame，不原地修改用户输入。
- [ ] 生成匿名 profile：缺失率、类型、基数、时间范围；不列出类别中的真实身份或原始行。

测试：无时区缺参数、UTC 往返、秒/毫秒时间不确定时失败、坏时间、重复策略、乱序排序、输入不被改。

完成前执行：`python -m pytest tests/test_event_schema.py -q`。

## V1-03：采样、标签与删失

文件：`event_sampling.py`，按需求第 16.4 节完整签名实现。

按下列顺序实现，不能先写一个聚合大循环：

1. 验证 config：lead/lookback/horizon/frequency 为正，max 样本上限合法。
2. `make_prediction_times()`：只从事件或固定时间网格生成，不能读取 ticket。event 策略用 ceil 后去重。
3. `select_history()`：对每个时刻筛 `(t-lookback,t]`。
4. `label_at_time()`：使用当前单元首次故障，判断 lead/horizon 精确边界。
5. `censor_at_time()`：确定 outcome 覆盖足够；未完成随访且未确认正例时移除。
6. `make_sample_id()`：版本前缀、unit、UTC 纳秒组成稳定 SHA256。
7. 保留被丢弃的理由计数，不保留敏感原始行到报告。

测试例表：

| failure 相对 t | 期望 |
|---|---|
| t 之前或等于 t | 故障后样本移除 |
| t+14m59s | insufficient_lead，移除 |
| t+15m | label=1 |
| t+15m+7d | label=1 |
| t+15m+7d+1ns | 若覆盖足够则 label=0 |
| 无 ticket 且覆盖未到 t+15m+7d | censored，移除 |

anchor 陷阱测试：事件 10:07，15 分钟 bucket。预测时刻 10:00 的特征不得包含该事件；event 策略应在 10:15 才使用它。

- [ ] 上限采样只能在 train 分配后应用；dev/val 固定网格保留，fixture 上限单独标 fast_fixture。
- [ ] 按 unit 的 seed 使用全局 seed + unit 的 SHA256 派生，结果与 worker 数、文件顺序无关。
- [ ] 多故障未有重置身份规则时，只用首次并丢弃之后样本；重复相同 ticket 去重。

完成前执行：`python -m pytest tests/test_event_sampling.py -q`。

## V1-04：切分与 leakage audit

文件：`temporal_split.py`。

```python
def assign_temporal_splits(samples: pd.DataFrame, boundaries: SplitBoundaries) -> pd.DataFrame:
    ...

def audit_temporal_splits(samples: pd.DataFrame, boundaries: SplitBoundaries) -> dict[str, object]:
    ...
```

- [ ] 默认边界按可观察时间跨度 70/15/15，非按行数。边界统一 UTC，并记录实际区间端点。
- [ ] split 区间用 `[start,end)`；label_window_end 不能达到或跨越下一 split start。
- [ ] cutoff 最大值必须满足 outcome coverage。短数据不能凑三个 split，返回具体原因。
- [ ] purge 与 embargo 实现为同一明确 gap 规则，不重复删除两次 horizon。
- [ ] 默认允许 unit 随时间跨 split，阈值和编码不能用 dev/val 标签。
- [ ] cold-unit audit 先按稳定 hash 选出审计单元，把它们从主 train 中排除再构建审计；仅有独立目录但仍参加训练不算隔离。
- [ ] audit 出错就 CLI 非零退出，不能以 warning 代替。

测试：边界等号、跨界标签、短区间、同 unit 时间因果性、sample_id 无重叠、cold-unit 无训练重叠、时间百分比分配。

完成前执行：`python -m pytest tests/test_temporal_split.py -q`。

## V1-05：SmartMem 领域适配和特征

文件：`smartmem_adapter.py`，如超过可读规模把 reader/features 放 `tasks/smartmem_data.py`，通用 data 模块不写领域字段。

- [ ] 保留 `MCELOG_COLUMNS` 的 `manufacturter` 原拼写。
- [ ] 根据用户确认规则实现文件名到 unit 的映射，校验同文件数据身份一致。
- [ ] ticket helper 只给标签函数，禁止把 ticket merge 到可见 features。
- [ ] 给无故障单元的 type 找可信静态来源；不能仅从故障 ticket 推断 A/B，否则缺失会泄露 label。
- [ ] 实现计数、多窗口强度、最近间隔、空间唯一数/集中度、error_type、parity/retry/burst、缺失与覆盖。
- [ ] 静态配置取预测时刻及之前最新值；类别编码/归一化由后续训练处理，V1 不在全 split 拟合。
- [ ] 每特征记录 source field、window、dtype、缺失规则与来源。没有原字段的特征不要伪造零值。
- [ ] `aggregate_events_to_samples()` 封装通用函数；新增 keyword-only 参数传时区/覆盖截止，保持旧位置参数可读错误。

测试：手算空间集中、空窗、缺失静态、未知类别、同地址不同事件、追加未来行后历史特征不变。

## V1-06：分块 IO 和恢复

文件：`io.py`、`manifest.py`。

- [ ] 每文件只读一次或按有界 chunk 读取，跨 chunk 保留 lookback 所需状态；不能遗漏 chunk 边界窗口。
- [ ] 乱序超大文件不能内存全排序，使用新 runtime 目录分区/外排序；失败时报告需要的空间。
- [ ] 公共 manifest 的输入身份只用 opaque file hash；原文件名可能包含真实 unit，不写日志。
- [ ] config hash 来自排序键 JSON，加 schema/算法版本；不包含私有路径和凭证。
- [ ] 分区完成后算输出 SHA256，再原子写 checkpoint。失败 `.tmp` 不能算完成。
- [ ] resume 比较输入内容 hash、config hash 和输出 hash；配置变化退出 2，单分区损坏只重建该分区。
- [ ] 一个数据输出目录同时只允许一个协调 writer，workers 写独立临时分区，最终协调归并。
- [ ] 用户输出目录已存在但无合法 manifest，拒绝覆盖；原始目录等于/包含输出目录时拒绝。

测试：人为中断、损坏文件、输入修改、seed 改变、1/2 workers 一致、分块/整块一致；不能仅对同一个函数调用两次当确定性测试。

## V1-07：组装 prepare CLI

保留 `list_mcelog_files()`/`load_tickets()` 对外 helper，替换 main 的 NotImplementedError。

- [ ] 参数逐项对应需求第 7 节，无隐藏硬编码 2024 日期。
- [ ] profile-only 允许输出小 profile；dry-run 只输出计划、不建数据分区。
- [ ] pipeline 顺序：检查路径 → schema/profile → 确认时间边界 → 分区采样/特征 → split → censor/purge → train 抽样 → audit → manifest 完成。
- [ ] 真实数据缺时区或覆盖截止时停在明确缺项，不能默认 UTC 以掩盖不确定性。
- [ ] 统一退出码；JSON 模式 stdout 只输出一个可解析 JSON，进度走 stderr 且脱敏。
- [ ] 增加 `--outcome-observed-until` 或 split config 同名字段，与接口保持一致。

测试：正常 fixture、非法参数、dry-run、profile-only、resume、失败分区、json、未知 format、空间不足。

## V1-08：构建知识包和验证检索

- [ ] 逐条研究需求中的知识主题，来源写 `sources.yaml`，字段至少含 id/title/url/版本或访问日期/证据类型。
- [ ] 新增 `SM-*` 知识卡；保持现有 loader schema，不为 SmartMem 改全局类别。
- [ ] 用户已运行方法标 `user_run`；未确认原理不写为“已验证因果机制”。
- [ ] 每卡填适用条件、实现提示、潜在风险，具体字段必须在数据 contract 中存在。
- [ ] 采用 `load_cards()` 或 `load_all_cards()` 验证，source_id 外键另写包验证 helper。
- [ ] 检索只加载 SmartMem 包再验证关键词命中；HDD 测试加载原包，确认互不污染。
- [ ] 可更新 evolve.yaml 的 knowledge.enabled/dir；smoke 保持关闭，evaluator 仍未完成。

注意现有 `skill/fe-knowledge-injection/scripts/build_cards.py` 带 HDD 策划内容，不直接运行它生成内存卡片。可复用 validate-only，不把全局默认卡集替换成 SmartMem。

完成前执行：`python -m pytest tests/test_smartmem_knowledge.py tests/test_knowledge.py -q`。

## V1-09：Skill、旧测试与文档

- [ ] 新建通用事件处理 Skill，按需求第 9 节含输入清单、命令、contract、失败处理、审计、resume。
- [ ] Skill 的示例用占位符，不放服务器密码/真实数据。
- [ ] README 说明只完成数据/知识，不宣称 fe doctor 整体通过，因为四件套仍缺。
- [ ] 修改 stub 测试中“aggregate 与 prepare 必须抛 NotImplementedError”的预期，替换为可手算成功输出和缺项错误。
- [ ] 保留 evaluator/smoke 尚未实现的 stub 测试和 SSD 测试，PR 中逐项解释迁移。
- [ ] 根 README/TODO 仅更新实际已实现状态，不重写历史结果。

## V1-10：本地验收和 PR 证据

命令分为小测试、回归和全量；先确认测试文件已创建：

```bash
python -m pytest tests/test_event_schema.py tests/test_event_sampling.py tests/test_temporal_split.py -q
python -m pytest tests/test_smartmem_prepare.py tests/test_smartmem_knowledge.py tests/test_smartmem_data_boundaries.py -q
python -m pytest tests/test_dataset_stubs.py tests/test_adapter_registry.py tests/test_engine_task_agnostic.py tests/test_hdd_protected_files.py -q
python -m pytest tests/ -q
git diff --check
git status --short
```

- [ ] Linux 全量测试通过；本地平台失败有真实记录，不能隐瞒。
- [ ] 用户数据先 profile 2 个文件，再 dry-run，再 10 文件转换；不因为 profile 成功直接全量。
- [ ] 检查 manifests/label 比例/删失/purge 计数，和用户旧方法的差异逐项解释。
- [ ] `git diff -- benchmark/hdd_mvp/evaluator.py benchmark/hdd_mvp/init.py benchmark/hdd_mvp/problem.md benchmark/hdd_mvp/prompt.md benchmark/hdd_mvp/data` 为空。
- [ ] 检查 staged 文件清单，排除 data、raw、run、预测、私有笔记。
- [ ] PR 记录基线/实现 commit、各步骤测试、真实测试层级、known issue、用户尚未提供项。

没有用户真实数据时交付 L0 fixture 证据与待验收项，不把 V1 实验数据验收勾为完成。

## V1-11：服务器新目录验证

复用需求第 13 节，执行前拿到用户跳板说明。已知目标参考为 `hcf@10.61.48.10`，默认 yolo26；不假设另一 AI 已配置同一 SSH。

- [ ] 最终解析新 NAS 根和新本地 runtime 根；验证均不在两个保护目录内，且未存在。保护比较按路径组件与 realpath 做，不能把平级 `faultevolve_smartmem_*` 错当旧目录子目录。
- [ ] code/data/artifacts 可放新 NAS，WAL DB 必须放新本地磁盘。V1 尚无进化 DB，也记录第二版位置计划。
- [ ] `conda activate yolo26` 后记录 Python。3.11 与项目打包 3.12 要求冲突时先报告具体解决方案，不能绕过安装要求。
- [ ] 不在旧代码目录 git pull/checkouts/worktree，不改旧共享环境。
- [ ] 新 code 固定本地验收 commit；原数据只读路径引用，输出显式到新 data/logs。
- [ ] 运行 Linux 小测试/全量测试、profile、10 文件转换，报告资源和产物 hash。
- [ ] 旧目录完整性只检查用户指定的非 holdout 元信息与文件；不递归哈希私有数据。无需为检查而读取 holdout。
- [ ] 服务器报告注明实际步骤、未跑步骤和两个旧目录没有写入。

## D. 新 AI 完成每步后留下的记录

在开发笔记逐步填以下模板：

```text
Step: V1-xx
Input contract/version:
Files changed:
Tests/commands and observed results:
Fixture versus real-data evidence:
Known limitations:
Commit:
Next step and required user input:
```

第一版完成后将正式分支/commit、contract、manifests、知识包版本与真实验证报告交给第二版 AI。第二版不得从老服务器 27cce15 继续开发。
