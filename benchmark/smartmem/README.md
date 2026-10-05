# SmartMem 内存

事件式协议，非 SMART 日快照。见 [`docs/datasets/smartmem.md`](../../docs/datasets/smartmem.md)。

知识包在 [`knowledge/`](knowledge/README.md)：23 张 `SM-*` 卡片 + 11 条出处 + 专家说明，
校验命令 `python -m benchmark.smartmem.knowledge_check`。
事件流样本准备的通用做法见 [`skill/fe-event-data-preparation/SKILL.md`](../../skill/fe-event-data-preparation/SKILL.md)。
MVP 演示用 [`docs/runs/smartmem-mvp-demo.md`](../../docs/runs/smartmem-mvp-demo.md)（每格都是实测过的
命令 + 预期输出 + 墙钟），要给队长的问题收窄在
[`docs/runs/smartmem-questions-for-leader.md`](../../docs/runs/smartmem-questions-for-leader.md)。

**评测器（evaluator）本地版已实现**：`python benchmark/smartmem/evaluator.py --run-dir … --ticket-file …
--predictions … --split dev --json` 给 SN 级命中窗上的 P/R/F。官方页面原文（本地核录于
`官方判分规则_核录0926.md`）说的是**一台机器只计一次、且命中必须落在 `[告警−7天, 告警−15分钟]` 内**，
所以那是这里的默认 `--duplicate-alarm-rule sn-in-window`；`each-alarm`（一条告警一个事件，
`SMARTMEM_PHASE2_REQUIREMENTS.md` §5.1 的本地兜底协议）与 `once-per-unit`（只看点名、不看时刻）
留作上下界对照。**组委会的评分源码我们并没有拿到**（页面原文 ≠ 可执行 scorer，许可也禁止抄入库），
因此每份分数仍带 `metric_spec_status: provisional` - **本地分数只能和本地分数比**，包内仍然没有
任何一张卡片声称在本数据集上验证过指标。

200 单元真实切片上的实测对照（提交=只预测 `label=1` 的行，不含任何模型）：`sn-in-window` dev 1.0 /
val 1.0，`each-alarm` 0.08496 / 0.082019，`once-per-unit` 1.0 / 1.0。⇒ 拉开量级的不是"看不看时刻"，
而是**分母按 SN 去重还是按告警计**；两条去重读法只在本切片没有的"点名但无一落窗" case 上分道，
那条只有合成 fixture 能演（已钉进测试）。

**任务定义三件套已补齐**（2026-10-04）：`problem.md`（简体中文，形状照 `benchmark/hdd_mvp/problem.md`）、
`prompt.md`（英文，给大模型的系统提示）、`init.py`（最小合法种子）。三份的内容全部挂在证据上：
候选 CLI 与 `sample_id,score,alarm` 出自 `docs/plans/SMARTMEM_PHASE2_REQUIREMENTS.md` §4.1-§4.2，
判分口径出自上面那段页面原文，切片规模与实测数字出自 `D:/sm-slice200/out-raw4`。

`init.py` 是本仓自定的起点、**不是官方 baseline**：15 列 CE 特征配 balanced 逻辑回归，一单元只在最紧迫
的一行告警，告警线按**分位数**迁移（绝对概率线在本切片上把 dev 告警全压成 0，实测过）。它在本仓尺子上给
dev 0.4416 / val 0.3448（暂定口径、切片正样本密度约 26%，**不与任何外部数字比较**，也不说明模型好坏 -
它只证明"候选 → 预测 → 评分"这条链能跑）。守护它的是 `tests/test_smartmem_seed.py` 4 条：过本仓静态检查、
填满 index 且一单元至多一次、缺列快照也能跑、无正例训练片明确报错而不是悄悄交零分。

**演化闭环已接好**（2026-10-04）：`fe doctor --task-dir benchmark/smartmem` 的 `task_files`、`task_data`、
`task_adapter` 三项现在都过。接线只动本目录与 adapter 四个文件，通用层一行没改：

- `candidate_runner.py`：候选程序的子进程执行器。把 run 目录渲染成**只含四份公开文件**的快照
  （`train_samples.csv.gz` / `train_labels.csv` / `val_index.csv` / `val_samples.csv.gz`，训练侧与打分侧
  都剥掉 `label`、`split_key`），起子进程跑 `python <候选> --data-dir … --split … --out …`，超时、输出上限、
  密钥变量清除、日志脱敏都在这里。**本文件不评分**，评分永远回到 evaluator。
- `evaluator.py` 的 `evaluate()`：签名是 `evaluate(program_path, timeout=900, split="dev", *,`
  `data_root=None, seed=20260926, ticket_file=None)`；流程为静态检查 → 快照 → 执行 → 校验输出 →
  按 `sample_id` join 告警时刻 → 判分 → 脱敏。
  模块 import 不读数据、不起子进程。返回 `validity / combined_score / cost_time / error_info / metric`。
  打分走**进程内**复用 CLI 的 `_report`，所以闭环分数与命令行分数不可能分叉（已钉测试）。
- `src/faultevolve/tasks/smartmem_adapter.py`：`load_task` 读三件套、`evaluate` 显式传 `data_root`
  （不改全局 env，避免多 worker 互相踩）、`constraints` 给候选生成用。`REQUIRED_DATA_FILES` 已从
  `prepare_data.py` 从没产出过的 `public/*` 改成真实布局 `manifest.json` + `partitions/{samples,audit,
  units/serial_type}`。`smoke_test` 仍抛 `DataNotPreparedError`，因为 `evolve.yaml` 里它就是关掉的。

输入定位靠三个环境变量：`SMARTMEM_DATA_ROOT`（run 目录）、`SMARTMEM_TICKET_FILE`（工单，缺省时复用
`prepare_data.TICKET_NAMES` 扫描）、`SMARTMEM_TICKET_EPOCH_UNIT`（工单时间戳单位，`D:/sm-slice200/raw/ticket.csv`
是秒）。三件都指向上面那份真实切片时，`init.py` 一轮实测 dev 44.16 / val 34.48（百分制，同一个 0.4416/0.3448）、
单个候选约 2 秒。

一条诚实的边界：**`fe evolve local` 在 Windows 本机跑不了**——`src/faultevolve/discovery/sandbox.py` 顶层
`import resource` 是 POSIX-only，这条不是本轮接线的产物（全量测试基线里那 18 条失败就有它）。所以闭环是
验到 adapter 层（`load_task / static_check / evaluate / constraints` = 引擎实际调用的那四个方法 + `fe doctor`
全绿），真 CLI 那一轮要在 Linux 服务器上跑。
