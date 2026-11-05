# HDD Campaign 操作与历史协议

本参考保留用户指定的 NAS 运行 `formal_20261015_194457_qwen38max0902_live/skill/fe-research-agent` 的制作方法。下面先说明当前入口，再保留历史协议；历史模型、150 轮初始预算、24 次 HPO 和资源配额均不自动授权新任务。

## 何时使用

需要复现“冻结快照 → HDD 代码进化 → AST 参数路线 → 分层搜索 → 实评选优 → 结果 Skill 打包”时，选择本路径。其他任务或联合目标优先使用 `fe research`。已有代码结果只补调参时，按 [参数桥接](islands-hpo.md) 承接，不能为了借用 Campaign 接口重复执行代码阶段。

## 当前操作入口

在仓库根目录执行，先将占位符替换为项目契约的真实值：

```bash
.venv/bin/python -m faultevolve.research_campaign prepare \
  --task benchmark/hdd_mvp --config <独立配置.yaml> \
  --env <已有环境文件> --output <新的Campaign目录> \
  --local-runs <本地运行根目录> --hpo-trials <参数评估预算> --cpu-limit <CPU配额>

PYTHONPATH=<Campaign目录>/snapshot/src \
  <仓库绝对路径>/.venv/bin/python -u -m faultevolve.research_campaign run \
  --output <Campaign目录>
```

`prepare` 要求新输出目录、`llm.stream=true`、HPO 预算至少 5、CPU 配额大于 0；模型和代码轮次来自传入配置。若项目预算不足以覆盖这些条件，选择更小的适配路径，不擅自增加额度。环境文件仅用于加载已有变量，不打印或复制其内容。

这个旧执行器会在 output 下保存源码快照、评估器、候选和数据库归档。如果用户只允许结果和 Skill 上 NAS，先把整个 Campaign output 放本地，完成后按 [交付规则](results-and-delivery.md) 选择文件归档，不能直接把 output 指向 NAS。

先确认旧 writer 已退出，再从同一快照执行 `run --output ...` 恢复；该入口没有 `--resume` 参数或项目级跨进程锁。长运行用当前环境实际支持的进程管理方式，记录 PID、日志与启动命令。停止时只控制该 Campaign 的进程，确认退出后再恢复。修改模型、数据或任务身份应建新 Campaign，不改旧快照。

读取 `status.json`、实际存在的 LLM 进展文件、阶段账本与本地评估。进程或请求持续输出不等于完成新评估。只有结果产生后才引用 `results/report.json`、`references/latest-result.json` 和 ZIP；失败时交付已知状态及恢复办法。

## 历史接入协议

| 逻辑角色 | 当前实现 |
|---|---|
| ExperimentSpec | `effective_config.yaml`、快照 SHA256、`hyperparameters/experiment_spec.json` |
| Domain Adapter | `research_campaign.parameter_sites/render_candidate`，只识别显式数值参数 |
| Coordinator | `research_campaign.run/hierarchical_search`，单进程串行协调 |
| Search Worker | 本地 `run_candidate`，真实训练和评估子进程 |
| Evaluator | 原始 HDD 评估器的字节一致快照，仅调用 `split="val"` |
| Experience Store | 三岛 SQLite、参数 TrialLedger、程序与评估 JSON；默认不导入跨任务先验 |
| Holdout Evaluator | 本次禁用；不读取私有数据，报告明确标记未运行 |

## 实验契约

代码进化预算读取冻结配置；本次正式运行使用三岛、全局 150 次、每岛上限 50 次。停滞等既有停止条件可能使实际轮数较少，结果必须报告真实轮数和原因。参数阶段默认最多 24 次评估、12 小时墙钟预算、串行执行、单次评估超时 900 秒。默认对整个 Campaign 的子进程继承最多 8 个 CPU 的亲和性，并统一 BLAS/OpenMP 线程上限，避免 `n_jobs=-1` 引发资源争用；资源配额记录于 manifest，比较时间因子时应使用相同配额。墙钟预算停止新派发，已派发评估可执行至超时。基线、各岛默认节点、参数默认节点和重复验证的评估成本分别记录。

代码路线从每岛真实有效节点中选择具有可识别参数的高分代码。若不足两条路线，则补充仓库既有结构化 logreg/lightgbm 模板，来源写入契约。无法识别的动态参数、连续域和隐藏在运行时对象中的配置不会被自动调参。

参数键由 AST 遍历位置和名称组成。默认域包含原值及原值的 0.5/2 倍；计数取合法正整数，采样比例上界为 1，非正哨兵值保持不变。每次仅修改一个参数，全部参数值在派发前校验。此域是有限的局部搜索，不表示已覆盖完整可行空间。

## 身份与评分

- 路线包含代码 SHA256、来源节点、默认参数和完整离散域。默认参数直接使用原始代码字节；子候选用 AST 生成，不执行候选模块来发现参数。
- Candidate ID 复用参考引擎：契约版本、route ID、完整规范化参数的哈希。完整 ExperimentSpec 的 `contract_hash` 另行记录；任何恢复都要求相同契约与代码 SHA256。
- 参考引擎原生实现默认屏障、Virtual Visit、外层 UCB、Beam、低访问探索和内层 UCT-style。适配器只接受 `validity=1` 且有限的本地 ROS，避免 NaN/Inf 进入前沿。
- 科研接受规则固定为 ROS 最大化、相对当前最佳提升至少 0.01。Reward 仅用于调度。原父节点真实分数不会被后代分数覆盖。
- 最终程序在“原代码进化最佳”和“参数搜索最佳”之间按真实 val ROS 选择；调参失败或无提升不丢失原代码最优产物。

## 恢复与取消

本次采用串行协调，不声明跨进程锁、异步回调幂等或分布式取消能力。进化由子进程组执行，编排器接收 SIGTERM/SIGINT 后向该进程组传播终止信号。参数阶段每次派发前写预留，每次完成后保存真实结果和账本；恢复时对已完成账本确定性重放，对结果已落盘但账本未写完的候选复用结果，对无结果的中断预留记为失败，不重复训练。

SQLite 始终在本地磁盘运行。每五分钟和阶段结束时在本地生成 SQLite 快照，再仅复制文件内容到 NAS；NAS 上的数据库用于归档，禁止直接恢复为运行目录。其他产物直接写 NAS，避免 NAS 对文件时间戳与数据库锁的限制。

## 输出与限制

`status.json` 是阶段进度，`manifest.json` 冻结输入和依赖，`baseline.json` 记录基线，`evolution/` 保存三岛产物，`hyperparameters/` 保存契约与 TrialLedger，`results/` 保存最终程序和报告，`skill/` 与 ZIP 保存可复用 Skill。

`llm/live.json` 每 10 秒更新各请求是否收到分块、正文/推理字符数、首响应耗时与最近分块间隔。`llm/events.jsonl` 追加开始、心跳、分块进展、完成、重试和失败事件。只记录计数及请求标识，不记录提示词、正文、推理文本或密钥。Token 仅使用接口返回的 usage；大多数接口在最后才返回用量，期间用 `null` 表示未知。推理 Token 是输出 Token 的细分，不再次累加。SQL 中的完成调用账本仍是最终成本汇总来源。

研究结论只覆盖当前 HDD val。最终 Skill 的 `latest-result` 引用必须在真实完成后生成；中断或失败不能伪造结果。全流程只保证既有 MVP 静态检查、临时公开数据副本与超时隔离，不额外宣称容器级沙箱或无网络执行保障。
