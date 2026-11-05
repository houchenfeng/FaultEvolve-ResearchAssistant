# 运行命令与排错

## 命令（仓库根目录）

```bash
# 1. 基线可评估性（期望 val ROS ≈ 22.81）
cd benchmark/hdd_mvp && python evaluator.py init.py && cd ../..

# 2. 冒烟
fe evolve local benchmark/hdd_mvp --config-file examples/experiments/hdd_closed_loop.yaml \
  --env-file .env -n 3 --runs-dir ~/faultevolve/myruns \
  --artifacts-dir <产物目录> --run-id smoke_$(date +%Y%m%d_%H%M)

# 3. 正式（后台运行；数据库放本地盘）
nohup fe evolve local benchmark/hdd_mvp --config-file examples/experiments/hdd_closed_loop.yaml \
  --env-file .env -n 20 --runs-dir ~/faultevolve/myruns \
  --artifacts-dir <产物目录> --run-id full_$(date +%Y%m%d_%H%M) --json > run.console.log 2>&1 &

# 4. 恢复（先确认原进程已退出；配置与任务必须不变，预算可显式更改）
fe evolve local benchmark/hdd_mvp --resume <run-id> --config-file examples/experiments/hdd_closed_loop.yaml --env-file .env \
  --runs-dir ~/faultevolve/myruns --artifacts-dir <产物目录>
```

`--config-file` 替换而非叠加 `evolve.yaml`，必须是完整文件。`.env` 不会被自动加载到子进程之外，用 `--env-file`。SQLite 不能放网络盘（smb2 上会被拒绝）。端口 18765 不可占用。

## 进度与产物

默认 `workflow.hierarchical.mode: per_structure`，20 轮、每结构 24 次最多包含 480 次常规候选调优试验，另有基线、冒烟与可能的修复候选。小规模冒烟应同时降低轮数和 `max_trials`。旧版后置流程须显式指定 `mode: post_evolution`；改变模式请新建运行。

| 看什么 | 去哪看 |
|---|---|
| 当前阶段 | `<产物目录>/<run-id>/status.json`（phase: data_checkup / evolution / hyperparameters / complete） |
| 每轮得分 | `events.jsonl` 里 `iteration_complete` 的 `payload.score` 与 `delta` |
| LLM 请求是否卡住 | `llm/live.json` 的 `active_requests`、`last_chunk_age_s` |
| 最终程序与来源 | `workflow-best.py`、`workflow-result.json` 的 `best_origin` |
| 性能/复杂度/收敛/自动化 | `effect-report.json` |
| 调优账本 | `hyperparameters/ledger.json`、`experiment_spec.json` |
| 单个结构的提案与调优后版本 | `hyperparameters/structures/<node-id>/{proposed.py,selected.json,ledger.json,runs/}` |

## 排错

| 现象 | 原因 | 处理 |
|---|---|---|
| `insight_extracted` 的 mechanism 都是 `Score changed by …` | 反思调用拿到空正文，走了兜底 | 看 `llm/live.json` 里短请求是否 `finish_reason=length` 且 `content_chars=0`；确认代码含 `thinking=False` |
| 首个生成调用长时间无返回 | 推理模型单次生成很慢，可能超客户端读超时 | 保持 `llm.stream: true` 与足够的 `timeout_s`；用 `llm/live.json` 看是否仍有 chunk |
| `工作流配置变化，请创建新运行` | 恢复时改了非预算配置 | 新建 run-id，保留血统 |
| `冻结输入发生变化` | 工作区文件被改 | 不要手改 `workflow/` 下文件；新建运行 |
| 三条路线的 `source_sha256` 相同 | 演化轮数太少，岛屿没有分化 | 增加演化轮数后再看分层调优结论 |
| 数据复检 blocked | 训练数据有需要决策的问题 | 读 `data-checkup/` 报告，解决或在 `accepted_issues` 显式接受，不要静默绕过 |
| 全量测试里有两项历史失败 | `test_hotfix_3_1::…node_created_precedes…`、`test_run_discovery::…no_host_path` | 与调优流程无关，已确认在改动前就存在 |

## 红线

- 不修改 `benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md}` 与 `data/`。
- 不读取、打印或上传 `data/holdout*`。
- 密钥只来自环境变量，不写入代码、配置、日志、提交。
- 不换 seed 反复重跑择优后只报告最好的一次；若做重复运行，要报告全部。
