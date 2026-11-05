# 这份 fixture 的来源（provenance）

**真实引擎 + 真实评估器，只有 LLM 是 mock**：候选由 `run_local_evolution(mock=True)` 生成，
静态检查与打分走的是仓库里受保护的 `benchmark/hdd_mvp/evaluator.py`（验证集），
所以这里每个分数都是评估器给出的数，不是语言模型自述的成绩。
生成命令、口径与已知局限全部写在本文件里，界面上这份数据一律标注为**离线 mock 运行**。

## 运行事实（全部实测）

| 项 | 值 |
|---|---|
| experiment_id | `15l4nd01` |
| 目录名 | `hdd_mvp_islands_15l4nd01` |
| 任务 | `benchmark/hdd_mvp`，`--mock`，种子 7，18 轮 |
| 岛 | a `performance` / b `miss_alert` / c `efficiency`，`exchange_interval=1` |
| 尝试 | 每岛 6 次，合计 18 = `iterations_done`（引擎恒等式，界面按两值是否相等显示核对状态） |
| 节点 | 21（a/b/c 各 7），其中 `summary_cross` 7 个 |
| 分数 | initial = best = **22.8074**（见下），`best_path` 只有根节点 |
| 交换 | 发布 1、投递 2、接受 2、拒绝 0、采用 12、已评估采用 12 |
| 成本 | 10200 tokens（a 3300 / b 3300 / c 3600，shared 0），`cost_basis=unknown`、`cost_usd=null` |
| 停止原因 | 三岛 `stop_reason` 为空、`status=running`，而运行 `status=finished` |

## 为什么 best 等于基线

mock 生成器不提供真算法：18 次尝试产出的候选在验证集上得分 **0.30~0.36**，
没有一个超过 init 根的 22.8074。因此这棵树没有上升路径，`best_path` 只剩根节点。
这是 mock 的固有结果，不是评估器或岛引擎的故障，也说明**这份 fixture 只能用来验证
"三岛结构是否被正确读出与渲染"，不能用来声称算法有提升**。真实提升数据来自 S9 的服务器运行。

## 为什么只有 1 条摘要

三岛的根是同一个 init 程序，摘要按 `(kind, text, conditions)` 内容去重：
b、c 发布的同一结论被并入 a 那条摘要作为额外证据（`evidence` 因此有 3 个 node 引用），
置信度沿阶梯被推进到 `statistically_confirmed`。界面原样呈现 API 给的 `confidence_status`，
不自行改写；「同一程序的三份证据是否算独立复现」这个问题记在计划文档里，属 S3 语义，本阶段不改。

采用记录 12 条 = 12 个不同候选节点，而 `operator=summary_cross` 的节点只有 7 个：
引擎在摘要进入上下文时就记一次采用，实际选中的算子可能是 inject / refine / threshold_calibrate。
所以「采用次数」与「跨岛交叉算子产出的候选数」是两件事，界面分开显示。

## 复现命令

```bash
.venv/Scripts/python.exe scripts/make_island_demo_run.py            # 生成 + 脱敏入库
.venv/Scripts/python.exe scripts/make_island_demo_run.py --check    # 只校验形状
.venv/Scripts/python.exe scripts/make_island_demo_run.py --no-install --exchange-interval 2
```

`make_island_demo_run.py` 里有一道形状门：三岛、islands 块、摘要、投递、采用、已评估采用、
按岛成本、尝试合计、成本平衡这九项缺任何一项都不会写入 `tests/fixtures/runs/`。
`--exchange-interval 2` 实测只发布 1 条摘要、10 条采用；`1` 是 1 条摘要、12 条采用，
两者的摘要数相同，差别只在采用条数，所以取默认 1。

## 脱敏方式

`scripts/build_run_fixture.py`：文本文件与 `fe.db` 的 TEXT 列里的主机路径 → `<REDACTED_PATH>`，
然后 `journal_mode=DELETE` + `VACUUM`，最后整体扫描；出现主机路径、私有测试集名称或密钥形态
字符串就拒绝入库。本目录生成时该脚本踩到一个真实缺陷：JSON 字符串里的 Windows 盘符路径每个分隔符
写作两个反斜杠，旧模式只吃掉盘符后的第一个反斜杠，剩下的用户目录名就成了非法 JSON 转义，
`events.jsonl` 因此解析失败 —— 已修（见 `tests/test_build_run_fixture.py`），修完后 `--check`
输出 clean。本文件本身也受同一扫描约束，所以这里不写任何真实盘符路径。
