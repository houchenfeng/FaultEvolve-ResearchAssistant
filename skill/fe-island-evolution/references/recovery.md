# 恢复、复制与重建参考

## 先决定要哪一种

| 想做的事 | 用哪个参数 | 结果 |
|----------|-----------|------|
| 接着同一个运行跑 | `--resume <exp_id>` | 同一个 `experiment_id`，迭代数继续往上累加 |
| 保留原运行不动，改配置/改轮数再跑 | `--resume <exp_id> --resume-from <runs>/<exp_id>` | 整库（含 WAL 提交）+ 旁边产物复制到**新的** runs/artifacts 目录，继续在副本上跑，原目录只读 |
| 报告丢了/只想从库里要一份结果 | `--resume <exp_id> --report-only` | 只读库重建报告：不评估、不调模型、不产生新分数，`rebuilt_from_store: true` |
| 起一个新运行 | 不加 `--resume` | 新 `experiment_id`；`--run-id` 可以预指定 |

`--resume-from` 与 `--report-only` 都必须带 `--resume <id>`，否则报错退出（不猜 ID，不凭空造运行目录）：

```
Error: --resume-from and --report-only need --resume ID (the run they act on).
```

## 续跑之前必须先核对身份

引擎在任何写入之前比较下面这些字段，任何一项对不上就**拒绝**（退出码 1，并写 `run_resume_refused` 事件）：

| 字段 | 来源 | 说明 |
|------|------|------|
| `task_fp` | `problem.md` + `prompt.md` | 任务文本改一个字就算换任务 |
| `evaluator_fp` | `evaluator.py` 内容 | 评估器换了，历史分数不可比 |
| `init_fp` | `init.py` 内容 | 起点代码换了就是另一棵树 |
| `data_fp` | `data/meta.json` / `descriptor.json` | **只读描述文件**：既不为了算指纹去扫全量数据，也不碰 `holdout*` |
| `seed` | 本次调用 | 重掷随机流等于换了实验 |
| `island_ids` | 本次配置 | 岛环变了（三岛变两岛、岛改名） |
| `identity_version` / `schema_version` | 库与代码 | 库结构或身份格式落后 |

拒绝时错误文本会指名差在哪一项，照着它决定是恢复原任务还是起新运行：

```
Error: refusing to resume 2ab57008 as the same experiment (task_fp: stored '47b9316bb63e23ad', now 'a090c3c5878b5658'). Start a new run, or restore the task, data and island configuration the stored experiment was created with.
```

两类特殊情况：

- 库里**从来没有**记录某个字段（旧运行）：不会因为“无法比较”而拒绝你，本轮把它补齐写回，下次就能校验。报告里体现为 `verified` / `unverified` 两个清单（`run_resumed` 事件的 `identity` 载荷）。
- 库里记过、本轮**读不到**（数据描述消失、评估器不可读）：算作变化，同样拒绝——这是丢了证据，不是没证据。

**绝不用删库、改 `run_identity` 字段、改指纹的方式绕过校验。** 被拒的原因通常就是你无意中改了任务或配置，绕过只会让新旧分数混在同一棵树上。

## 接手时的单持有者规则

一个运行同一时刻只允许一个活持有者：库里的 `run_claim` 记 `holder_id` + `holder_pid`。

- 声明还在、进程还活着 → 拒绝同时第二个执行（避免两棵树写进同一个库）。
- 声明是**别的进程**留下且那个进程已经不在 → 先写 `run_interrupted` 事件（带 `previous_holder` 与当时 `iterations_done`），再接手。
- 声明是**本进程自己**留下的（同一 pid 重开引擎对象，测试与 worker 重建会这样）→ 不算竞争。
- pid 无法判断时按“不活着”处理：过期声明不能永久锁住一个运行。

## 续跑会重建哪些状态

从库里重建，不靠上一个进程的内存：

- **每岛的 rng 流与协调器游标**：存在 `scheduler_state`（含 `rng_state_json`、`next_island_index`），所以探索顺序不会在恢复后重播一遍。
- **token 预算**：从 `llm_call` 行重放得到已花费量，因此预算判断接得上。
- **成本账本序号**：`cost_ledger` 以 `(experiment_id, seq)` 为主键，新账本从 `max_cost_seq()` 接续；不接续会立刻撞 `UNIQUE constraint failed: cost_ledger.experiment_id, cost_ledger.seq`。
- **未完成的摘要应用**：只有 `evaluation_id` 为空的 application 会被重新挂上；已经带结果的候选**只重报状态，不重评、不重复加分**。
- **岛状态**：`island_state` 行原样回来，包括 `paused`（暂停的岛恢复后仍然暂停，兄弟岛也不会把摘要投给它）。

`run_summary.json` 的 `cost.by_island` 每次都从 `llm_call` 行重读，所以续跑后的报告里各岛花费是**跨进程累计**的（实测：某岛 12 次调用/3300 token 中包含上一进程的记录）。

## 续跑不恢复什么（必须如实告诉使用者）

- **墙钟预算**：`budget.max_wall_hours` 是每个进程重新计时，不是每个运行累计。
- **评估侧计数**：评估器内部的计数不从库重建。
- **幂等重放**：没有实现“同一次调用重放两次只算一次”的通用幂等层；`request_id` 的唯一性只在单进程内成立，跨进程去重靠 `llm_call.id` 与 `(experiment_id, seq)`。
- **`CostLedger.totals()`**：内存账本只汇总本进程记录，所以 `cost_ledger_totals` 这类进程内字段不含上一进程；耐久事实看 `cost_ledger` 行与 `run_summary.json` 的 `cost` 块。
- **产物分家**：`--artifacts-dir` 指到别处时，产物写在新家，库仍在 `--runs-dir`；找齐两份要两个路径。
- **中断态**：`IslandStatus` 没有“中断”这个值，跨重启的意外停止由 `run_interrupted` 事件表达，岛状态本身照常存活。
- **真实掉电/强杀**：以上都是可控中断下验证过的；真实断电证据要在真实运行里取。

## 只读重建报告

```bash
fe evolve local <task_dir> --mock --report-only --resume <exp_id> \
  --runs-dir <runs> --artifacts-dir <新输出目录>
```

- `--artifacts-dir` 给一个新目录就不会覆盖原运行的报告。
- 重建出的文档只有 12 个键，其中 `islands`/`exchange`/`cost` 三块与实时运行写的**逐字段相同**（同一个投影函数从库读），因此可以拿它跟旧报告对账。
- 重建不产生新分数：它全程以只读方式打开库，评估器调用次数为 0。
- 重建报告里没有 `stop_reason`（那是上一个进程写的）。

## 中断之后怎么继续（操作顺序）

1. 先确认没有别的进程还持有这个运行：`ps aux | grep "fe evolve"`。
2. 看库在不在、报告在不在：`ls <runs>/<exp_id>/fe.db <artifacts>/<exp_id>/run_summary.json`。报告没了而库在 → 用 `--report-only` 先拿结果，别再花一次钱。
3. 想接着跑：确认任务目录、评估器、数据描述与配置和当初一致（否则会被身份拒绝），然后 `--resume`。
4. 想换配置试另一种走法：用 `--resume-from` 复制，**原运行保持不动**。
5. 跑完对照恒等式：`sum(islands[*].attempts) == iterations_done`，`exchange.applications` 与 `evaluated_applications` 的差是否已经补齐，`cost` 三数是否自洽。
6. 历史运行目录只读：索引与派生结果写到新目录，不覆写旧证据。
