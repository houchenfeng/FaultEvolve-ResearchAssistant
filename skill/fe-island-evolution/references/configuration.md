# 多岛配置参考

本文件只讲配置字段与其语义；运行、恢复与结果定位的命令在 `../SKILL.md`。

## 配置从哪里读

一次运行只取**一份**配置：`--config-file <path>` 优先，否则 `<task_dir>/evolve.yaml`，都没有就用代码默认值。两者不会合并，所以“我在任务目录里改了一份、又传了 `--config-file`”只生效后者。

已认识的顶层键：`task`、`budget`、`selection`、`widening`、`operators`、`insights`、`stop`、`judge`、`llm`、`reflection`、`knowledge`、`smoke_test`、`analysis`、`discovery`、`autotune`、`islands`、`seed`。

**不认识的键会被静默忽略。** 唯一的防线是预检：

```bash
fe doctor --task-dir <task_dir> --config-file <path> --json
```

`config_keys` 失败即说明有键根本没生效（例如写成 `island:`）；此时引擎跑的是默认岛环而不是你的配置。`config_islands` 会打印实际会启动的岛环。

## 适配器选择（`task`）

| 字段 | 默认 | 说明 |
|------|------|------|
| `task.adapter` | `hdd` | 别名 `hdd`、`famou`、`backblaze`、`alibaba_ssd`、`smartmem`，或 `module:Class` 指向自己的适配器 |

- 不认识的值直接报错并列出可用别名，不会退回默认：
  ```
  Error: unknown task.adapter 'nosuchtask'; aliases: ['alibaba_ssd', 'backblaze', 'famou', 'hdd', 'smartmem'] or 'module:Class'
  ```
- 通用四文件任务（`evaluator.py`/`init.py`/`problem.md`/`prompt.md`，评估器自己打印 JSON 分数）用 `famou`；硬盘专属的滚动窗口/泄漏约束检查在 `hdd`。
- 任务目录缺文件时 `fe evolve local` 打印 `Error: missing required files: ['prompt.md']` 并以退出码 1 结束。

## 指标方向：只有一个标量，且总是越大越好

引擎不知道“主指标名字”，也不接收“方向”参数：

- 适配器 `evaluate()` 返回 `EvalResult(validity, combined_score, cost_time, error_info, metric)`，其中 `combined_score` 是**唯一被优化的标量**，语义固定为越大越好；`validity < 1.0` 即无效，分数不参与选择。
- 因此“越小越好”的指标（时延、误报率、成本）必须由适配器在算分时转换成越大越好（例如取负、取倒数、或转换成 1-x），并把原始指标留在 `metric` 字典里供报告展示。引擎不会替你做这个转换。
- `metric` 里的细分项（`precision`/`recall`/`f1`/`auprc`/`false_alarm_rate`/…）是**展示与诊断用的**，不参与搜索排序；把它们当分数用就是自造分数。
- 键名 `tokens_per_ros_point` 是历史遗留命名，含义是“每提升一分花费多少 token”，与硬盘无关；网页上把该任务标成 “ROS” 属于任务服务层的展示文案，不是引擎的指标。

## 岛环（`islands`）

| 字段 | 默认 | 语义 |
|------|------|------|
| `enabled` | `true` | `false` 时必须是**恰好一个岛**（单树旧行为），否则配置校验失败 |
| `exchange_interval` | `5` | 每完成多少次尝试检查一次交换。想验证交换真的发生，演练时把它调成 `1`～`2` |
| `max_positive_per_exchange` | `1` | 每轮最多发布几条正向摘要 |
| `max_negative_per_exchange` | `2` | 每轮最多发布几条避错摘要 |
| `max_summaries_in_context` | `3` | 一个岛的提示里最多带几条外来摘要 |
| `eval_concurrency` | `1` | 评估并发。**`1` 是唯一受支持的值**：`>1` 在运行开始就抛 `islands.eval_concurrency > 1 is not implemented: islands run serially, got N`，它不是可调优的性能旋钮。串行时不存在在途评估子进程 |
| `min_valid_evals_before_stall` | `10` | 岛至少攒够这么多次**有效**评估，才允许被停滞规则判停 |
| `stall_valid_evals` | `15` | 达标之后，连续多少次有效评估没有进展就把该岛置 `finished`（`stop_reason=stalled`） |
| `infra_fail_pause` | `5` | 连续多少次基础设施失败（不是模型写错，是环境/依赖/超时那类）就把该岛置 `paused`（`stop_reason=infra_failures`） |
| `early_error_share` | `true` | 新出现的错误类型**立刻**发给仍可动作的兄弟岛，不等交换游标到点；关掉它，同一个坑会被兄弟岛再踩一次 |
| `stagnation_request_evals` | `10` | **当前引擎不读这个字段**（只在 `webapi` 的界面元数据里出现）。调它不会改变任何行为；需要“停滞求助”节奏请改 `stall_valid_evals` |
| `islands` | 默认三岛 | 岛清单，见下 |

单个岛（`islands[]` 每一项）：

| 字段 | 默认 | 语义 |
|------|------|------|
| `island_id` | 必填 | 非空、无首尾空格、全运行唯一；空字符串保留给旧运行的隐式单岛（报告里显示为 `legacy`） |
| `profile` | `performance` | 只能是 `performance`/`miss_alert`/`efficiency`/`custom`；**同一运行内不允许重复画像**，加第四个岛必须自带新画像 |
| `focus` | `""` | 策略说明，会进该岛的提示上下文；`profile=custom` 时必填 |
| `operator_bias` | `[]` | 该岛偏好哪些算子。这是软偏好，不是硬限制 |
| `knowledge_keywords` | `[]` | 该岛检索知识卡时用的关键词（按岛独立检索） |
| `max_attempts` | `50` | 该岛的尝试配额；打满记 `island_attempt_cap_hit` |
| `exploration_ratio` | `0.2` | 保留多少比例的选择给本岛偏好之外的策略，防止岛变成单一算子 |

默认三岛（不写 `islands:` 时就是它）：`a:performance`（refine/inject，重整体分数与结构多样性）、`b:miss_alert`（recall_focus/threshold_calibrate，重漏报与误报权衡）、`c:efficiency`（refine/inject，重运行时与模型复杂度）。

校验会拒绝的错误（配置阶段就报出来，不会等到运行中）：空 `island_id`、重复 `island_id`、重复 `profile`、`profile=custom` 却没有 `focus`、`enabled: false` 却给了多个岛、`islands: []`。

## 预算与停止（`budget`、`stop`）

| 字段 | 默认 | 语义 |
|------|------|------|
| `budget.max_iterations` | `50` | 全局轮数上限（`-n`/`--iterations` 覆盖它） |
| `budget.max_tokens` | `3000000`，**可为 `null`** | `null` = 不设成本上限：停止由岛配额、停滞与基础设施规则决定，而不是预算 |
| `budget.max_wall_hours` | `6.0`，可为 `null` | 墙钟上限。**注意：续跑时墙钟重新计时**，它是每进程约束，不是每运行约束 |
| `budget.stage_caps` | `{}` | 各阶段占 `max_tokens` 的比例；`max_tokens` 为 `null` 时这些比例**不生效**，要绝对值请用 `stage_caps_absolute` |
| `budget.stage_caps_absolute` | `{}` | 各阶段绝对 token 上限 |
| `budget.stagnation_window` | `0` | 全局停滞窗口，`0` 为关 |
| `budget.tokens_per_point_cap` | `null` | 每得分点的 token 上限 |
| `budget.min_iterations_before_stop` | `5` | 预算类停止判定在此轮数之前一律返回“不停”，防止第 1 轮就被成本判定掐掉 |
| `budget.expand_gating` | `false` | `true` 时，非最优节点的扩展要先看剩余 token 够不够一次平均开销；`false` 时扩展不受成本门控 |
| `budget.safety_factor` | `1.5` | 上面那道门控用的倍率：剩余 token 需 ≥ 近期单次平均开销 × 该系数 |
| `budget.cost_window` | `5` | 平均单次开销/评估耗时用最近几次迭代估计，这就是窗口长度 |
| `budget.stall_iterations` | `5` | 连续多少轮无进展即停运行 |
| `stop.target_score` | `null` | 目标分 |
| `stop.stop_at_target` | `true` | `true` 时达标即停且 `stop_reason=target_score_reached`；`false` 时跑满轮数，达标只记录在 `target_reached`/`rounds_to_target` |

阶段键只有这些：`reflect`、`repair`、`knowledge`、`jev`、`mechanism`、`crossover`。写别的名字属于会被忽略的键。

停止原因怎么读：

- 运行级 `stop_reason`：为什么整个运行结束（`max_iterations`、`target_score_reached`、`all_islands_stopped` 等），是**权威**解释。
- 预算触发的细分原因在 `budget_stop_reason`，触顶阶段在 `stage_cap_hits`。
- 岛级 `islands[*].stop_reason` / 事件 `island_stopped`：为什么这一个岛不再领任务。岛停下不代表运行停下。四种取值（按代码里的判定顺序）：
  | `stop_reason` | 触发条件 | 结果状态 |
  |---------------|----------|----------|
  | `max_attempts` | 该岛尝试数达到 `islands[].max_attempts`（`rt.exhausted`） | `finished` |
  | `stalled` | 有效评估数 ≥ `min_valid_evals_before_stall` 且此后连续 `stall_valid_evals` 次无进展 | `finished` |
  | `selection_exhausted` | 连续 `budget.stall_iterations` 轮什么都没产出（选择没给出可扩展节点，或生成丢失） | `finished` |
  | `infra_failures` | 连续 `infra_fail_pause` 次基础设施失败 | `paused` |
- `islands[*].status` 只有 `pending|running|paused|finished` 四种。全局轮数到上限时岛可以仍是 `running`（它还有自己的配额）——这不是 bug，也不是“岛还活着”。

## 换数据集要改的东西

只改 `task_dir` 与 `task.adapter`（以及数据根环境变量）即可；`islands`、`budget`、`stop` 的字段与语义不变。若新任务的分数方向不是越大越好，转换放在适配器里，见上面“指标方向”。
