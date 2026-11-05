---
name: fe-island-evolution
description: 通过任务适配器运行和管理多岛（默认三岛）算法演化——配置、启动、监控、经验交换解释、成本归属、断点恢复与结果导出。当用户要“让搜索分成独立策略各自演化”“看岛之间交换了什么”“从崩溃的运行接着跑”时使用。
---

## 何时使用本技能

- 把一个任务放到多棵独立搜索树上跑（默认三岛：性能、漏报、效率），并确认它们真的各自独立搜索
- 解释或核对岛间摘要交换：谁发布了什么、谁采纳了、采纳后分数怎么变
- 按岛看花费，找出哪个岛在烧成本
- 运行中断后续跑、复制旧运行改配置、或只从数据库重建报告
- 把一次真实运行的经验导出成可复用的 Skill 草稿

单岛/旧版单树行为仍由 [`skill/fe-evolve-manager/SKILL.md`](../fe-evolve-manager/SKILL.md) 负责；本技能只在“多岛编排”上给出命令。

## 输入契约

| 输入 | 必需 | 说明 |
|------|------|------|
| 任务目录 `task_dir` | 是 | 必须含 `evaluator.py`、`init.py`、`problem.md`、`prompt.md` 四个文件；`evolve.yaml` 可选 |
| 任务适配器 | 是 | 配置项 `task.adapter`（内置别名 `hdd`/`famou`/`backblaze`/`alibaba_ssd`/`smartmem`，或 `module:Class`）；决定数据布局与打分方式 |
| 主指标与方向 | 是 | **从任务契约读取，不在本技能里写死**：适配器返回的 `combined_score` 是引擎唯一优化的标量，且**总是越大越好**。方向为“越小越好”的任务必须由适配器在 `evaluate()` 内完成取负/倒数等转换，本技能不接受“指标方向”参数 |
| 配置 | 否 | `<task_dir>/evolve.yaml`，或运行时用 `--config-file` 指定（两者不会合并，只取其一） |
| 数据引用 | 否 | 由适配器解析（如 `HDD_BENCH_DATA_ROOT`）。本技能不接收原始数据路径，也不读 `holdout*` |
| 运行目录 | 否 | `--runs-dir`（`fe.db`）、`--artifacts-dir`（`run_summary.json`、`tree.json`、`events.jsonl`、`programs/`） |
| 恢复 ID | 否 | `--resume <experiment_id>`；要“先复制再接手”时加 `--resume-from <运行目录>` |
| 模型与密钥 | 真实运行需要 | 只从环境变量或 `--env-file` 读取；`--mock` 演练不需要 |

缺输入时的处理规则：

- 已有上下文能确定的值（例如任务目录、运行目录）**沿用并明确说出来**，不要重复追问。
- 缺**任务适配器**或适配器名字不认识时，停下并给出具体错误，**不要造一个适配器**、不要把任务当成硬盘：
  ```
  Error: unknown task.adapter 'nosuchtask'; aliases: ['alibaba_ssd', 'backblaze', 'famou', 'hdd', 'smartmem'] or 'module:Class'
  ```
- 任务目录四文件不齐时（同样不要猜）：
  ```
  Error: missing required files: ['prompt.md']
  ```
  此时按 `skill/fe-dataset-adapters` 准备任务目录，而不是把缺失的文件内容编出来。

## 执行顺序（先读契约，再检查配置，最后跑）

### 1. 读任务契约

打开 `<task_dir>/problem.md` 与 `<task_dir>/evaluator.py`，确认三件事：主指标是什么、评估器怎么给分、有效/无效的判据。**本技能的示例包含硬盘，但示例不是前提**：换任务就是换 `task_dir` 和 `task.adapter`，其余流程不变。

### 2. 预检配置（含岛环是否真的按你想的启用）

```bash
fe doctor --task-dir <task_dir> --json
# 配置放在任务目录之外时，预检必须看同一份配置，否则检查的是另一个适配器：
fe doctor --task-dir <task_dir> --config-file <effective.yaml> --json
```

读这三条检查：

| 检查名 | 含义 | 失败怎么办 |
|--------|------|-----------|
| `task_files` / `task_adapter` / `task_data` | 任务目录四文件、适配器解析、数据就绪 | 按错误文本补文件或准备数据；`task.adapter` 不认识就是配置错 |
| `config_keys` | 配置文件里的顶层键是否都被引擎认识 | **引擎会静默忽略不认识的键**：出现 `unknown config keys ['island']` 说明你写了 `island:` 而不是 `islands:`，此时岛环用的是默认三岛而不是你的配置 |
| `config_islands` | 实际会启动的岛环，例如 `islands on: 3 tree(s) [a:performance, b:miss_alert, c:efficiency], exchange every 5 attempts` | 与你的意图不一致就改配置再重检 |

`--config-file` 不给 `--task-dir`、或指向不存在的文件时，doctor 以退出码 2 拒绝，不会退化成默认配置假装检查通过。

配置字段、默认值、无成本上限语义见 [`references/configuration.md`](references/configuration.md)。

### 3. 离线演练（不花钱，验证编排本身）

```bash
fe evolve local <task_dir> --mock -n 12 \
  --config-file <effective.yaml> \
  --runs-dir <tmp>/runs --artifacts-dir <tmp>/art --json
```

`--json` 返回 `experiment_id`、`status`、`iterations_done`、`best_score` 与两个目录。演练要看到：`run_summary.json` 里三个岛都有尝试数，且 `exchange.summaries > 0`（交换没发生就把 `islands.exchange_interval` 调小再来一次）。

### 4. 真实运行

真实运行需要模型密钥（环境变量或 `--env-file`）与就绪的数据；长时运行用 `nohup`/`tmux`，服务器上的路径、密钥来源与目录纪律见 [`references/hdd-server.md`](references/hdd-server.md)。

```bash
fe evolve local <task_dir> -n 50 \
  --config-file <effective.yaml> \
  --runs-dir <runs_root>/<name> --artifacts-dir <artifacts_root>/<name> \
  --env-file <env> --json
```

### 5. 监控

```bash
# 岛级与交换事件
grep -E '"type": "(attempt_started|exchange_check|exchange_summary_published|exchange_delivered|exchange_applied|summary_crossover|island_stopped|island_attempt_cap_hit|all_islands_stopped)"' \
  <artifacts_dir>/<exp_id>/events.jsonl | tail -20
```

事件字段的含义、`exchange_*` 四种事实之间的差别、以及负结果为什么单独计数，见 [`references/exchange.md`](references/exchange.md)。

### 6. 停止

- 停整个运行：终止进程即可；已落库的候选、交换、成本都在 `fe.db` 里，下一次 `--resume` 会先核对身份再接手。
- 单个岛停下不等于运行停下：岛可以因配额/停滞/基础设施熔断变成 `paused` 或 `finished`（`stop_reason` 记原因），协调器继续轮转其余岛；父运行的 `stop_reason` 为 `all_islands_stopped` 时才表示全岛停。
- 停止语义与预算字段的对应关系见 [`references/configuration.md`](references/configuration.md)。

### 7. 恢复与复制

```bash
# 接着同一个运行跑
fe evolve local <task_dir> --resume <exp_id> -n <更大轮数> \
  --runs-dir <原 runs> --artifacts-dir <原 artifacts> [--config-file <同一份配置>]

# 保留原运行不动，先整库复制再跑副本（原目录只读）
fe evolve local <task_dir> --resume <exp_id> --resume-from <原 runs>/<exp_id> \
  -n <轮数> --runs-dir <新 runs> --artifacts-dir <新 artifacts>

# 只从数据库重建报告：不评估、不调模型、不产生新分数
fe evolve local <task_dir> --mock --report-only --resume <exp_id> \
  --runs-dir <runs> --artifacts-dir <新输出目录>
```

任务文本、评估器、初始代码、数据描述、种子或岛环与库里记录不一致时，续跑会被拒绝并指名差在哪一项：

```
Error: refusing to resume 2ab57008 as the same experiment (task_fp: stored '47b9316bb63e23ad', now 'a090c3c5878b5658'). Start a new run, or restore the task, data and island configuration the stored experiment was created with.
```

拒绝的退出码是 1。这时要么恢复原任务，要么起新运行，**不要通过删库或改字段绕过校验**。完整检查清单见 [`references/recovery.md`](references/recovery.md)。

### 8. 结果定位与导出

```bash
# 运行目录里有什么
ls <artifacts_dir>/<exp_id>            # run_summary.json tree.json events.jsonl programs/ logs/ skills/
# 报告丢了或想复核：只读库重建（评估器调用次数为 0）
fe evolve local <task_dir> --mock --report-only --resume <exp_id> --runs-dir <runs> --artifacts-dir <out>
# 竞赛指标（节点级证据、算子有效率、超时计数）
python skill/fe-evolve-manager/scripts/report_run.py <runs>/<exp_id>/fe.db <artifacts>/<exp_id>/run_summary.json
# 经验 Skill 草稿 + 机器可读证据索引（只写进该运行目录）
python skill/fe-island-evolution/scripts/export_experience_skill.py \
  <runs>/<exp_id>/fe.db <artifacts>/<exp_id>/run_summary.json --task-dir <task_dir>
```

导出脚本的退出码：0 写出草稿，2 是用法或输入错误（缺文件、非法 JSON、库不是岛运行、试图写进项目 `skill/` 目录、草稿已存在而未加 `--force`）。

## 输出契约：`run_summary.json` 的三个岛视图

这三个块由同一个投影写出，**实时运行与只读重建得到完全相同的内容**，因此可以拿重建结果对账。下面是一次 16 轮 toy 三岛运行（`--mock`）的真实读数：

```json
{
  "islands": {
    "a": {"status": "running", "profile": "performance", "attempts": 6,
          "valid_evaluations": 7, "invalid_evaluations": 0,
          "best_score": 24.9, "stop_reason": ""},
    "b": {"status": "running", "profile": "miss_alert", "attempts": 5,
          "valid_evaluations": 6, "invalid_evaluations": 0,
          "best_score": 24.27, "stop_reason": ""},
    "c": {"status": "running", "profile": "efficiency", "attempts": 5,
          "valid_evaluations": 6, "invalid_evaluations": 0,
          "best_score": 22.9, "stop_reason": ""}
  },
  "exchange": {"summaries": 5, "by_kind": {"best": 5, "failure": 0, "knowledge": 0},
               "deliveries": 10, "accepted": 10, "rejected": 0,
               "applications": 28, "evaluated_applications": 28},
  "cost": {"total_tokens": 8550,
           "by_island": {
             "a": {"tokens": 3300, "calls": 12, "unresolved_calls": 0, "cached_calls": 0,
                   "by_stage": {"generate": 1800, "reflect": 1500}},
             "b": {"tokens": 2500, "calls": 9, "unresolved_calls": 0, "cached_calls": 0,
                   "by_stage": {"generate": 1500, "reflect": 1000}},
             "c": {"tokens": 2750, "calls": 10, "unresolved_calls": 0, "cached_calls": 0,
                   "by_stage": {"generate": 1500, "reflect": 1250}}},
           "shared_tokens": 0, "unresolved_calls": 0,
           "cost_usd": null, "cost_basis": "unknown"}
}
```

读法：

- `islands[*].status` 是岛自身生命周期 `pending|running|paused|finished`。**运行被全局轮数上限停下时，岛可以仍是 `running`**（它还有配额）；判断“为什么结束”看运行级 `stop_reason`，判断“这个岛为什么不再干活”看 `islands[*].stop_reason`。
- `sum(islands[*].attempts) == iterations_done` 是编排正确性的恒等式；不相等就是调度或记账漏了一次尝试。
- `exchange` 是四层独立事实：发布（`summaries`/`by_kind`）→ 投递（`deliveries`）→ 采纳/拒绝（`accepted`/`rejected`）→ 采纳后产出的候选（`applications`，其中 `evaluated_applications` 才是已被本岛评估器打分的）。`applications` 可以大于 `accepted`，因为一条采纳的摘要能生成多个候选。
- `cost.by_island` 的 token 之和加 `shared_tokens` 必须等于 `cost.total_tokens`；`shared_tokens` 是没有岛上下文的调用。`unresolved_calls` 是发出去但没回来的请求：它不进 `total_tokens`，但也不会被当成免费。`cost_basis` 只有 `recorded` 时 `cost_usd` 才是数字——模型不报价就不编金额。
- 只读重建出来的报告只有 12 个键（`experiment_id`、`status`、`iterations_done`、`node_count`、`valid_count`、`best_node_id`、`best_score`、`total_tokens`、`islands`、`exchange`、`cost`、`rebuilt_from_store`），而上面那次 toy 运行的完整报告是 119 个键（真实任务的键更多）；两者都含上述三块，`rebuilt_from_store: true` 表示这份是重建出来的。重建报告里不会有 `stop_reason`，因为停止原因是上一次进程写的，重建只保证不重复付费、不重新打分。

## 完成标准

一次多岛运行算交代清楚，必须逐条满足：

- [ ] `fe doctor` 的 `config_islands` 与意图一致，`config_keys` 通过
- [ ] `run_summary.json` 里每个岛的 `attempts >= 1`，且各岛 `best_score` 来自自己树里的节点
- [ ] `sum(islands[*].attempts) == iterations_done`
- [ ] `exchange.summaries > 0` 且 `evaluated_applications > 0`，否则经验根本没进流程（写清“本轮没有交换”而不是当成成功）
- [ ] `cost` 三数自洽（岛内之和 + 共享 = 总量），`unresolved_calls` 若大于 0 已单独说明
- [ ] `status` 与 `stop_reason` 被解释，不是只贴数字
- [ ] 分数只来自本地评估器：任何模型自述、摘要文字都不算分数

## 经验草稿怎么回到通用技能

`export_experience_skill.py` 写出的 `<artifacts>/<exp_id>/skills/experience_skill_draft.md` 是**草稿**，`evidence_index.json` 是它的机器可读索引。规则：

- 草稿禁止写进项目 `skill/` 目录（脚本会直接拒绝），评审通过后才手工合入。
- 一条经验只有在**第二次运行复现**后才能升级为通用规则；单次观察只能停留在 `single_observation`，跨任务规律一律不写。
- 没有正面可泛化结果时，交付“事实 + 局限”，不要为凑交付编经验；同理一次失败不构成普遍禁止。
- 草稿只引用脱敏证据（run/summary/node/application ID 与评估器读数），不含候选源码、原始数据与密钥。

## 禁止操作

- **不得**读取、打印或上传 `holdout*` 等私有测试集；数据只经任务适配器
- **不得**把 API Key 写进代码、配置、测试、日志或提交
- **不得**修改任务契约（`evaluator.py`、`init.py`、`problem.md`、`prompt.md`）来迎合候选
- **不得**让模型输出充当分数，也不得在报告里把“投递成功”写成“采纳有效”
- **不得**用删除库文件、改 `run_identity` 字段等方式绕过续跑身份校验

## 参考

- [`references/configuration.md`](references/configuration.md)：岛配置字段、默认值、指标方向、停止与无预算上限语义
- [`references/exchange.md`](references/exchange.md)：摘要字段、发布/投递/采纳/应用四层事实、负结果与置信度边界
- [`references/hdd-server.md`](references/hdd-server.md)：本项目服务器主机与路径、只读数据、新目录部署、模型配置来源
- [`references/recovery.md`](references/recovery.md)：续跑、复制、只读重建、检查点与失败后的继续方式
- [`skill/fe-evolve-manager/SKILL.md`](../fe-evolve-manager/SKILL.md)：单岛/旧版运行与旧运行恢复
- [`skill/fe-dataset-adapters/SKILL.md`](../fe-dataset-adapters/SKILL.md)：换数据集、准备数据、适配器选择

维护者参考：`tests/test_island_skill_walkthrough.py` 按本页步骤 2/3/8 在 toy 任务上真实跑一遍（离线、无 HDD 字段），`tests/test_island_skill.py` 把本页与代码之间的漂移（假参数、不存在的事件名、过期默认值）钉成测试。改本页时先让这两个文件通过。
