# SmartMem 一阶段 MVP 一页可跑清单（2026-10-04 实测）

每一格都是**今天在本机跑过的**：命令、预期输出片段、墙钟、退出码都来自实跑，不是估计。
所有产物只读复用 `D:/sm-slice200`，新产物只写进 `out-demo-profile/` 与 `loop-artifacts/`。

## 60-90 秒讲稿口径

1. **数据可复现**：200 单元真实切片端到端跑通，两条互斥路径（直读原始包 / 消费外排序树）产出的
   **52 个分区文件逐字节相同**，只有 `manifest.json` 因时间戳不同；侧表 200/200/0（declared/rows/
   unresolved），侧表类型全部来自队列目录名、与工单交叉校验 140 个有工单单元零冲突；200 单元那轮
   `--profile-only` 不带 `--error-types` 实测 `row_count 6 281 694 / unit_count 200 / ticket_rows 140`
   （数字出自 `docs/runs/smartmem-v1-dev-log.md`，本轮第 1 行是同一命令在 one-unit 快样上的复跑）。
2. **判分口径可核验**：官方页面原文本地有逐字核录，我们把它从"细则全自定"改成"按核录 + 两点待确认"
   —— 默认 `sn-in-window`（一台机器只计一次、命中必须落在 `[告警−7d, 告警−15min]`），
   另两条留作上下界。**没有拿到官方评分源码，所以每份分数仍带 `provisional`**：本地分数只能跟本地比。
3. **闭环接通**：候选子进程 → 公开快照 → 本地判分，`init.py` 一轮 dev 44.16 / val 34.48（百分制），
   与命令行跑出的 0.441558 / 0.344828 **逐位相同**。这不是模型好坏，是"链路能跑 + 尺子只有一把"。

一阶段交付的是**可复现的数据、可核验的判分口径、一份收窄到三条的缺口清单**，不是一个分数。

## 前置（一次设置）

```powershell
$PY = "C:\Users\Pomelo\Documents\fe-smartmem-venv\Scripts\python.exe"
$env:PYTHONIOENCODING = "utf-8"   # ✓/✗ 这类字符在 GBK 控制台会把 doctor 直接炸掉，实测过
$env:SMARTMEM_DATA_ROOT   = "D:\sm-slice200\out-raw4"
$env:SMARTMEM_TICKET_FILE = "D:\sm-slice200\raw\ticket.csv"
$env:SMARTMEM_TICKET_EPOCH_UNIT = "s"      # 真实工单是 epoch 秒；给了 ms 整段窗会错位
$env:SMARTMEM_SPLIT_FILE  = "D:\sm-slice200\split-v2.yaml"
```

仓库根目录下执行。`& $PY` 里的那个 `&` 是 PowerShell 的调用运算符：**变量当命令名必须加 `&`**，
漏了会当场报「表达式或语句中包含意外的标记」——这个坑本轮实测踩过，所以下面每块都写全。
另两条同款坑：**续行符是反引号（`` ` ``）而不是 `\`**，本项目其他地方常用 bash，`\` 续行在这里不成立；
**高级语法只出现在两处**——第 12 行的 here-string、第 13 行筛测试文件的 `(ls … | ?{ … })`，
两块本轮都真跑过，整块拷贝即可，其余命令一律是最朴素的 `& $PY 参数 参数`。
`fe doctor` / `fe evolve local` 走 `faultevolve.cli`；本轮**不需要** API key
（`--mock` 才需要，见最后一行）。

## 清单

下面每条都是**整块拷进 PowerShell 能直接跑的完整命令**。本页 11 个命令块本轮被逐块从这份 markdown
里抠出来、存成 `.ps1`、用 Windows PowerShell 5.1 真跑了一遍（兜底那块在全新进程里跑），
所以下面的退出码与墙钟就是它跑出来的，不是"看着能跑"。
另记一个坑：**不要用 shell 变量拼参数**——PowerShell 把一个含空格的变量当**一个** argv 传，
`$BASE` 那种写法会把六个参数并成一个，本轮实测过。

**1. `--profile-only` 不填 `--error-types` 也读得动真包**（one-unit 快样，写新目录）

```powershell
& $PY benchmark/smartmem/prepare_data.py --raw-dir D:\sm-slice200\one-unit `
  --out-dir D:\sm-slice200\out-demo-profile --format feather --timezone UTC `
  --epoch-unit s --profile-only --json
```

预期 `"exit_code": 0`、`"ticket_rows": 1`、`config_hash 64b807882e10…`。实测退 **0** / **0.6 s**。
这一格**只能跑一次**：目录里已经有分区时它退 **1** 并提示"pass `--resume`"（实测消息
`the run directory already records 1 partition(s)`）——重跑前先删 `out-demo-profile`，或改成
`--resume`。

**2. 侧表与规模读数**（已产出切片的运行载荷，只读）

```powershell
& $PY -c "import json; d=json.load(open('D:/sm-slice200/raw4.json',encoding='utf-8')); `
print(d['unit_types'], d['events'], d['config_hash'][:12])"
```

预期 `{'declared': 200, 'rows': 200, 'unresolved': 0} raw-files 2472df3d8cc1`。实测退 **0** / **0.0 s**。

**3. 两条路径逐字节相同**（Git Bash 侧命令，对拍 52 个分区文件的 sha256）

```bash
cd /d/sm-slice200
for d in out-raw4 out-sorted4; do
  (cd $d && find partitions -type f | sort | xargs -r sha256sum) > /tmp/$d.sha
done
diff /tmp/out-raw4.sha /tmp/out-sorted4.sha && echo IDENTICAL
```

预期两份各 52 行、`diff` 空、打印 `IDENTICAL`；两目录各有 53 个文件，唯一不同的是 `manifest.json`
（里面记着时间戳）。实测退 **0** / **0.2 s**。

**4-7. 判分三口径 + 队列汇总敏感性**（同一份提交，val 切片）

```powershell
& $PY benchmark/smartmem/evaluator.py --run-dir D:\sm-slice200\out-raw4 `
  --ticket-file D:\sm-slice200\raw\ticket.csv --epoch-unit s `
  --predictions D:\sm-slice200\pred-val-oracle.csv --split val `
  --duplicate-alarm-rule sn-in-window --json
```

把最后一条 `--duplicate-alarm-rule` 依次换成 `each-alarm`、`once-per-unit`，再改成
`--queue-aggregation mean-of-f1`（去掉 `--duplicate-alarm-rule` 即用默认）。这四条本轮逐条跑过；
单个 token 写成变量（`--duplicate-alarm-rule $rule`）没问题，前面那条警告针对的是拼一整串参数。

预期 `f_beta` 依次为 **1.0 / 0.082019 / 1.0 / 1.0**，都带 `rows_scored 2246`、`units_scored 70`、
`metric_spec_status: provisional`；`totals.alarms` 恒为 **26**，`totals.predictions` 在 `each-alarm`
下是 **608**（按告警条数计），另两条是 **26**（SN 级去重）。实测四条各退 **0** / 各 **0.7 s**。

**8. 无可评对象时报错而不是给 0 分**（只含表头的工单，`loop-artifacts/` 里现成一份）

```powershell
& $PY benchmark/smartmem/evaluator.py --run-dir D:\sm-slice200\out-raw4 `
  --ticket-file D:\sm-slice200\loop-artifacts\tickets-header-only.csv --epoch-unit s `
  --predictions D:\sm-slice200\pred-val-oracle.csv --split val --json
```

预期 `"scoreable": false`、`"reason": "the ticket file holds no alarm"`，**不出现 F1=0**。
实测退 **4** / **0.7 s**。（注意：想用 `--split embargo` 演这一格是演不出来的，那条走的是退 1
的"预测行不属于本切片"，本轮实测确认过——差一点写进这页变成现场翻车。）

**9. 复现护栏：配置不符先拒**

```powershell
& $PY benchmark/smartmem/evaluator.py --run-dir D:\sm-slice200\out-raw4 `
  --ticket-file D:\sm-slice200\raw\ticket.csv --epoch-unit s `
  --predictions D:\sm-slice200\pred-val-oracle.csv --split val `
  --expect-config-hash ("0" * 64) --json
```

预期消息同时点出目录记的 `2472df3d8cc1…` 与本次所求的 `000000000000…`。实测退 **1** / **0.5 s**。

**10. 知识包校验**

```powershell
& $PY -m benchmark.smartmem.knowledge_check
```

预期 `"cards": 23 … "sources": 11`（每张卡必须有出处、适用条件与风险）。实测退 **0** / **0.1 s**。

**11. `fe doctor`**

```powershell
& $PY -m faultevolve.cli doctor --task-dir benchmark/smartmem
```

预期三行任务检查 ✓（本轮逐字跑出来的样子）：`✓ task files ok`、
`✓ adapter smartmem -> SmartMemAdapter`、
`✓ data dir D:\sm-slice200\out-raw4; ok (SMARTMEM_DATA_ROOT=D:\sm-slice200\out-raw4)`。
整页退 **1** 是因为没设 API key（三条 ✗），与任务无关。实测 **1.0 s**；
**必须先 `PYTHONIOENCODING=utf-8`**，否则 ✓ 在 GBK 控制台直接把命令炸掉。

**12. 闭环一轮**、**13. 测试账**：见下面两个代码块。

第 12 行的代码块（`@'` 起、`'@` 收的是 PowerShell here-string，整块作为 `-c` 的一个参数交给 python；
四个 `SMARTMEM_*` 变量已在前置里设好）。**里面的 Python 字符串一律用单引号**：这里的双引号会被
PowerShell 的原生命令参数转换吃掉，实测报 `NameError: name 'benchmark' is not defined`——
这块本轮就是靠这个坑从"看着能跑"改成"真能跑"的。

```powershell
& $PY -c @'
from pathlib import Path
from faultevolve.tasks.smartmem_adapter import SmartMemAdapter
adapter = SmartMemAdapter()
spec = adapter.load_task(Path('benchmark/smartmem'))
result = adapter.evaluate(spec.init_code, spec)
print(result.validity, result.combined_score, round(result.cost_time, 2),
      result.metric['duplicate_alarm_rule'], result.metric['metric_status'],
      result.metric['queues'])
'@
```

实测 `1.0 44.1558 2.14 sn-in-window provisional ['A', 'B']`（`cost_time` 在 2.06-2.14 之间抖，
分数不抖）；把 `evaluator.evaluate(..., split='val', ...)` 显式传给 val 给 `34.4828`。
payload 与 stdout 里 `sn_\d+` 匹配 0 处。

第 13 行两条命令（`-k smartmem` 会被 webapi 的收集错误打断，必须显式列文件）：

```powershell
& $PY -m pytest (ls tests/test_*smartmem*.py | ?{ $_ -notmatch "helpers_" }) `
  tests/test_dataset_stubs.py tests/test_adapter_registry.py -q -p no:cacheprovider
& $PY -m pytest tests -q --continue-on-collection-errors -p no:cacheprovider
```

第一行今天实测 **353 passed / ~41 s**（把末尾两个文件去掉就是 SmartMem 家族自己的 **329**）；
第二行 **836 passed, 18 failed, 1 skipped, 19 errors / ~105 s**——那 18 条失败与 19 个收集错误都是
既有基线（`import resource` 在 Windows 上不存在、`fastapi` 没装），失败集合与本轮开工前逐条一致，
本轮新增的测试全在通过的那一侧。

## 判分三口径为什么差一个量级（一页里唯一需要解释的数）

`D:/sm-slice200/raw4.json` 那轮 200 单元的实测（提交 = **只预测 `label=1` 的行，不含任何模型**，
所以它是这份尺子的上界）：

| 细则 | dev F1 | val F1 | 说明 |
| --- | --- | --- | --- |
| `sn-in-window`（默认，官方页面原文） | **1.0** | **1.0** | SN 级去重 + 必须有预测落窗 |
| `once-per-unit` | 1.0 | 1.0 | 点名即算，不看时刻 —— 偏松，只作上界对照 |
| `each-alarm` | 0.08496 | 0.082019 | 分母按告警条数计（§5.1 本地兜底协议）—— 偏紧，只作下界对照 |

拉开量级的是**去重口径**，不是"看不看时刻"。真正没定的是**有没有告警预算**：页面原文口径下一份不含
模型的"跟着标签报"提交就能拿满分，所以 `smartmem-questions-for-leader.md` 第 1 条问的是这个。

## 演示里不要说的话

- 不要说"官方分数"或"跟排行榜/别的队可比"：所有分数带 `provisional`，官方评分源码没拿到。
- 不要引用任何外部数字或另一条赛线的实验编号与分数来对比 —— 本仓的数只能跟本仓的数比。
- 不要说 `init.py` 是官方 baseline：它是本仓自定的起点（balanced 逻辑回归 + 分位数告警线）。
- 不要说"切片分数代表模型水平"：切片正样本密度约 26%，与现场千分位基率差两个量级，换把尺子就不是这个数。

## 本机跑不了的那一条（别在演示现场试）

`fe evolve local --task-dir benchmark/smartmem --mock` 在 **Windows 上起不来**：
`src/faultevolve/discovery/sandbox.py:7` 顶层 `import resource` 是 POSIX-only，
`import faultevolve.cloud.engine` 直接 `ModuleNotFoundError`。这是既有基线问题（那 18 条失败里就有它），
不是本轮接线引入的。闭环因此**验到引擎实际调用的那四个方法**（`load_task` / `static_check` /
`evaluate` / `constraints`，共 21 条测试 + 上面第 12 行实跑），真 CLI 那一轮需要 Linux 服务器 —— 已列进
给队长的一页。

## 现场兜底

- 第 1-11 行全是亚秒级，可当场敲；第 12 行 ~2 秒；只有第 13 行的全量测试（~105 秒）建议提前跑好、当场只放
  家族那 ~41 秒，或者直接引用本页的数字并注明"今日实测"。
- 切片产物是只读复用：`out-raw4` / `out-sorted4` / `raw/ticket.csv` / `split-v2.yaml` / `pred-val-*.csv`
  都已存在，不需要现场重跑 6 分钟的样本模式，更不需要 149 分钟的外排序。
- 如果连切片都不在（换机演示），第 1、4-11 行退化为合成 fixture 测试。下面这一块**不依赖**那四个
  `SMARTMEM_*` 变量（新开的 PowerShell 里只设 `$PY` 即可），今天实测 **127 passed / ~28 s**，
  不碰 `D:` 盘：

```powershell
& $PY -m pytest tests/test_smartmem_prepare_cli.py `
  tests/test_smartmem_evaluator.py tests/test_smartmem_loop.py -q
```

