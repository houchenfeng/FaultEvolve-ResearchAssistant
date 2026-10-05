---
name: fe-evolve-manager
description: 管理 FaultEvolve 本地进化实验。当用户要运行、监控、暂停、继续或获取进化结果时使用。
---

## 何时使用本技能

- 运行本地进化循环（mock 或真实 LLM）
- 监控进化进度和结果
- 恢复中断的实验
- 配置存储路径和知识注入
- 排查进化失败问题

## 输入

### 任务目录结构

```
benchmark/<task>/
├── evaluator.py          # 评估脚本（受保护，不要修改）
├── init.py               # 初始解决方案（受保护，不要修改）
├── problem.md            # 问题描述
├── prompt.md             # LLM 系统提示
├── evolve.yaml           # 进化配置
├── data/                 # 数据目录（受保护）
│   ├── train_*.csv
│   ├── val_*.csv
│   └── holdout_*.csv     # 禁止访问
└── knowledge/            # 知识包目录（可选）
    ├── cards.jsonl       # 知识卡片
    └── sources.yaml      # 文献来源
```

`evolve.yaml` 中的 `task.adapter` 选择任务适配器（默认 `hdd`）。换数据集、准备数据或排查 `fe doctor --task-dir` 时，见 [`skill/fe-dataset-adapters/SKILL.md`](../fe-dataset-adapters/SKILL.md) 与 `docs/datasets/*.md`。

### 环境变量 (.env 格式)

```bash
# .env 文件（可通过 --env-file 加载）
DASHSCOPE_API_KEY=sk-xxx          # 必需：DashScope API 密钥
MIYANG_API_KEY=xxx                # 可选：MiYang Jev 中继密钥

# 存储路径配置
FE_RUNS_DIR=/local/ssd/runs       # 可选：SQLite 数据库目录
FE_ARTIFACTS_DIR=/nas/artifacts   # 可选：大文件制品目录
```

## 执行命令

### 1. 环境检查

```bash
# 基本检查
fe doctor

# JSON 输出（适合脚本解析）
fe doctor --json

# 检查特定任务目录
fe doctor --task-dir benchmark/hdd_mvp

# 加载 .env 后检查
fe doctor --env-file .env
```

### 2. 本地进化

```bash
# Mock 模式测试（无需 API Key）
fe evolve local benchmark/hdd_mvp --mock --iterations 5

# 真实 LLM（需要 DASHSCOPE_API_KEY）
export DASHSCOPE_API_KEY="your-key"
fe evolve local benchmark/hdd_mvp --iterations 10

# 指定目标分数（达到后停止）
fe evolve local benchmark/hdd_mvp --iterations 50 --target-score 32

# 自定义存储路径
fe evolve local benchmark/hdd_mvp \
  --runs-dir /local/ssd/runs \
  --artifacts-dir /nas/artifacts

# 恢复中断的实验
fe evolve local benchmark/hdd_mvp --resume <experiment_id>

# JSON 输出
fe evolve local benchmark/hdd_mvp --mock --iterations 3 --json

# 算子老虎机 mock（12 轮 toy 任务，见 skill/fe-operators）
bash skill/fe-operators/scripts/run_mock_operators.sh

# 交叉/集成算子 mock（15 轮 toy 任务，见 skill/fe-crossover-ensemble）
bash skill/fe-crossover-ensemble/scripts/run_mock_crossover.sh
```

### 5. 恢复崩溃的实验

如果进化运行崩溃（LLM 连接错误、超时等），系统会自动在 artifacts 目录保存当前状态。

```bash
# 查看崩溃的实验状态
cat <artifacts_dir>/<exp_id>/run_summary.json | jq '.status'
# 输出: "crashed" 或 "finished"

# 恢复中断的实验继续运行
fe evolve local benchmark/hdd_mvp \
  --resume <exp_id> \
  --runs-dir <original_runs_dir> \
  --artifacts-dir <original_artifacts_dir>
```

**崩溃后的 artifacts 结构**：

即使运行崩溃，以下文件始终会被写入：
- `run_summary.json` - 包含 `status: "crashed"` 和当前进度
- `tree.json` - 已完成的进化树
- `events.jsonl` - 事件日志（包括 `llm_error` 事件）
- `programs/*.py` - 所有已生成的程序
- `logs/*.log` - 错误日志

**LLM 瞬态错误处理**：

系统对瞬态 LLM 错误（连接错误、超时、429、5xx）自动重试最多 3 次，
指数退避（4s、8s、16s）。如果仍然失败，会跳过该迭代并记录 `llm_error` 事件，
而不会终止整个运行。

### 3. 长时间运行（nohup）

```bash
# 后台运行并记录日志
nohup fe evolve local benchmark/hdd_mvp --iterations 100 \
  > fe_evolve.log 2>&1 &

# 记录 PID 用于监控
echo $! > fe_evolve.pid

# 轮询检查进度
while [ -f fe_evolve.pid ]; do
  if ! ps -p $(cat fe_evolve.pid) > /dev/null 2>&1; then
    echo "进化完成"
    break
  fi
  tail -5 fe_evolve.log
  sleep 60
done
```

### 4. 读取结果

```bash
# 查看运行摘要（支持 --runs-dir 或 --artifacts-dir 指定的路径）
cat benchmark/hdd_mvp/.fe/runs/*/run_summary.json

# 或从自定义 artifacts-dir 读取
cat /nas/artifacts/<exp_id>/run_summary.json

# 查看最优代码
cat benchmark/hdd_mvp/.fe/runs/<exp_id>/programs/<best_node_id>.py
```

## 成功检查

运行后验证：

```bash
# 1. 检查退出码
echo "Exit code: $?"  # 预期: 0

# 2. 检查 run_summary.json 存在
ls benchmark/hdd_mvp/.fe/runs/*/run_summary.json

# 3. 验证关键字段
python3 -c "
import json
from pathlib import Path

# 找到最新的运行
runs = sorted(Path('benchmark/hdd_mvp/.fe/runs').glob('*/run_summary.json'))
if not runs:
    print('ERROR: No run_summary.json found')
    exit(1)

summary = json.loads(runs[-1].read_text())

# 检查状态
assert summary['status'] == 'finished', f'ERROR: status={summary[\"status\"]}'

# PR #3.1：事件计数与 stop_reason 自检
assert summary.get('iteration_events') == summary['iterations_done'], (
    f'iteration_events mismatch: {summary.get(\"iteration_events\")} vs {summary[\"iterations_done\"]}'
)

# 检查有效率
assert summary['valid_rate'] > 0, 'ERROR: valid_rate is 0'

# 检查知识指标（如果启用了知识注入）
if summary.get('cards_offered', 0) > 0:
    print(f'Knowledge injection active: {summary[\"cards_offered\"]} cards offered')

# Jev 启用时检查调用、节省量、审计精度和先验
if summary.get('jev_calls', 0):
    assert summary['jev_tokens'] > 0
    assert summary.get('screening_precision') is not None
    print(f'Jev evaluations saved: {summary.get(\"evaluations_saved\", 0)}')

if summary.get('value_mode') == 'multi':
    assert 'tokens_per_ros_point' in summary

if summary.get('bandit_active'):
    assert summary.get('operator_counts'), 'operator_counts missing'
    assert summary.get('operator_posteriors'), 'operator_posteriors missing'

print('SUCCESS: Run completed normally')
print(f'  status: {summary[\"status\"]}')
print(f'  iterations: {summary[\"iterations_done\"]}')
print(f'  best_score: {summary[\"best_score\"]:.2f}')
print(f'  valid_rate: {summary[\"valid_rate\"]:.2%}')
"

# 启用错例画像前建议先单程序诊断（analysis 默认关闭，会额外占用墙钟）
fe analyze benchmark/hdd_mvp --program benchmark/hdd_mvp/init.py --json
# run_summary / report_run 含 analysis_calls、analysis_failures、analysis_time_s、analysis_nonempty_rate

# 4. 从 fe.db + run_summary 提取竞赛报告字段（含 self_fix_tokens、refine valid、generative valid、operator_*）
python3 skill/fe-evolve-manager/scripts/report_run.py \\
  benchmark/hdd_mvp/.fe/runs/<exp_id>/fe.db \\
  /path/to/artifacts/<exp_id>/run_summary.json
```

`report_run.py` 中 **`refine_valid`** 只统计 `operator=refine` 的节点；**`generative_valid`** 统计 refine + recall_focus + threshold_calibrate + inject + crossover。评估算子体系时优先看 `generative_valid_rate`（run_summary）与 `generative_valid`（report）。

## 故障处理

### 预算 / 停滞停止

`stop_reason` 或 `budget_stop_reason` 为 `stagnation`、`tokens_per_point_cap` 时，检查 `budget.stagnation_window`、`tokens_per_point_cap`、`stage_caps` 与 `selection.value.mode`。详见技能 `fe-node-value-budget`。

### 算子无效率高 / 未被使用

- 查看 `run_summary.json` 的 `operator_counts`、`operator_valid_rate`、`operator_posteriors`
- 某算子有效率过低：从 `operators.enabled` 移除
- `recall_focus` 从未出现：父节点需含 `metric.analysis.fn_groups`（`analysis.enabled`）
- `inject` 频繁回退：检查 `knowledge` 目录与 `stage_caps.knowledge`
- **交叉**：从未出现检查 `bandit`、`crossover.enabled`、`min_valid_nodes`、不同 `branch_key` 伙伴；`operator_fallback`（`no_partner`）会回退 refine
- 详见 `skill/fe-operators` 与 `skill/fe-crossover-ensemble`

### 交叉/集成算子（PR #8）

- 配置：`operators.bandit: true`，`operators.crossover.{enabled,min_valid_nodes,runtime_budget_s,top_quantile,max_code_chars}`
- `run_summary` / `report_run` 字段：`crossover_count`、`crossover_valid_rate`、`crossover_mean_delta`、`crossover_best_gain`、`crossover_tokens`
- 事件：`crossover_parents`、`crossover_reflection_skipped`、`operator_fallback`（`requested: crossover`, `reason: no_partner`）
- 第二父节点写入 `node_parents`（`primary` / `secondary`），不改 `node` 表

### 知识发现（KD1）

- `discovery.enabled: false` 为默认；开启后每 `every_n_iterations` 轮及 run 结束（`run_at_end`）触发发现，受 `max_token_share` 限制
- 新事件：`discovery_round_started`、`claim_proposed`、`claim_tested`、`claim_graded`、`card_promoted`、`discovery_controls`、`discovery_skipped`、`discovery_error` 等
- `run_summary.json` 新增 `discovery_*`、`claims_*`、`discovered_cards_*`、`neg_control_fpr`、`planted_recovery_rate` 等字段（旧 summary 缺键时 `report_run.py` 忽略）
- KD2：`discovery.tournament.enabled`（默认 false，需 `discovery.enabled`）；`insights.reputation_enabled`；`mechanism_*` / `tournament_*` 指标只读 `run_summary.json`
- `fe report <task> --run-id <EXP> --json|--md` 生成 manifest 报告；`tournament_skipped` 常见 reason：`no_env`、`token_share`、`max_rounds`、`token_budget`
- 发现 token 计入 `total_tokens`，可能触发 `tokens_per_point_cap`
- 实跑验收延后，见 `docs/TODO.md` §5a

### 网络文件系统错误

```
Error: Database path is on network filesystem (cifs): /mnt/nas/runs
```

**解决**：SQLite 不支持网络 FS，使用本地磁盘：
```bash
export FE_RUNS_DIR=/local/ssd/fe_runs
fe evolve local benchmark/hdd_mvp --runs-dir /local/ssd/fe_runs
```

### database is locked

```
sqlite3.OperationalError: database is locked
```

**可能原因**：
1. 另一个进程正在使用同一数据库
2. 数据库在网络文件系统上

**解决**：
```bash
# 检查是否有其他进程
ps aux | grep "fe evolve"

# 使用不同的 runs-dir
fe evolve local benchmark/hdd_mvp --runs-dir /tmp/fe_runs_$$
```

### API 401/429 错误

```
openai.AuthenticationError: 401 Unauthorized
openai.RateLimitError: 429 Too Many Requests
```

**解决**：
```bash
# 检查 API Key
fe doctor

# 401: 重新设置 API Key
export DASHSCOPE_API_KEY="correct-key"

# 429: 降低并发或等待
# 在 evolve.yaml 中设置 llm.max_concurrency: 2
```

### API 超时

```
openai.APITimeoutError: Request timed out
```

**解决**：重试通常有效（内置重试逻辑），或增加超时：
```yaml
# evolve.yaml
judge:
  timeout_s: 60  # 增加超时
```

### 性能门和烟雾测试（PR #3 新增）

引擎在完整评估前执行两道检查来提前捕获明显错误：

#### 性能门（Performance Gate）

检测会导致超时的代码模式（如 `for sn in df['serial_number'].unique()`），并：
1. 尝试一次 LLM 自动修复
2. 重新检查，如果仍有问题则拒绝评估
3. 计入 `perf_rejections` 统计

**检查指标**：
```bash
grep "perf_rejected\|perf_self_fix" benchmark/hdd_mvp/.fe/runs/<exp_id>/events.jsonl
```

**run_summary.json 字段**：
```json
{
  "perf_rejections": 3    // 因性能问题被拒绝的候选数
}
```

#### 烟雾测试（Smoke Test）

在完整评估前，用小样本数据（默认约 2% 的 serial_numbers）和短超时（默认 60s）快速运行代码，捕获明显的运行时错误：

1. **采样策略**：从训练数据中抽取约 2% 的硬盘序列号，但保留所有正例（或至少 20 个正例），以确保 CV/thresholding 正常工作
2. **确定性**：采样使用固定随机种子，同一运行中所有候选使用相同的采样数据
3. **缓存**：采样数据目录在运行开始时构建一次，运行结束时自动清理
4. 失败或超时时尝试一次 LLM 自动修复（走 perf_rejected 路径）
5. 重新烟雾测试，只有通过才进入完整评估
6. 计入 `smoke_failures` / `smoke_fixes` 统计

**注意**：烟雾测试超时与性能问题被拒绝走相同的处理路径，不会触发额外的完整评估。

**配置**（在 `evolve.yaml` 中）：
```yaml
smoke_test:
  enabled: true           # 是否启用（默认 true）
  timeout_s: 60           # 超时时间（默认 60s）
  sample_fraction: 0.02   # 采样比例（默认 2%）
```

**检查指标**：
```bash
grep "smoke_failed\|smoke_fix_success" benchmark/hdd_mvp/.fe/runs/<exp_id>/events.jsonl
```

**run_summary.json 字段**：
```json
{
  "smoke_failures": 5,    // 烟雾测试失败次数
  "smoke_fixes": 2        // 烟雾测试自动修复成功次数
}
```

### 评估超时

评估超时 (900s) 通常由以下模式引起：

1. **for-loop over serial_number.unique()** — 12M 行数据会超时
   ```python
   # ❌ 会超时
   for sn in df['serial_number'].unique():
       sn_data = df[df['serial_number'] == sn]
       ...
   
   # ✅ 改用向量化
   df.groupby('serial_number').agg(...)
   ```

2. **groupby().apply(lambda)** — 非常慢
   ```python
   # ❌ 很慢
   df.groupby('serial_number').apply(lambda g: g.diff().mean())
   
   # ✅ 改用 transform/agg
   df.groupby('serial_number')['col'].transform('diff').mean()
   ```

**目标运行时间**：< 300 秒。超过 600 秒会有 time_factor 惩罚，超过 900 秒超时失败。

**检查超时**：
```bash
grep "timeout\|timed out" benchmark/hdd_mvp/.fe/runs/<exp_id>/logs/*.log
grep "performance_issue\|serial_number.unique\|groupby.*apply.*lambda" \
  benchmark/hdd_mvp/.fe/runs/<exp_id>/events.jsonl
```

### 所有候选无效

如果连续多轮所有候选都无效（`valid_rate: 0`）：

1. **检查 API 兼容性错误**：
   ```bash
   grep -E "fillna.*method|verbose_eval|early_stopping_rounds" \
     benchmark/hdd_mvp/.fe/runs/<exp_id>/logs/*.log
   ```

   **常见 API 兼容性问题及修复**：
   | 错误模式 | 原因 | 修复 |
   |---------|------|------|
   | `fillna() got unexpected keyword argument 'method'` | pandas>=2 | 用 `df.ffill()` 或 `df.bfill()` |
   | `train() got unexpected keyword argument 'verbose_eval'` | LightGBM>=4 | 删除参数，用 `callbacks=[lgb.log_evaluation()]` |
   | `fit() got unexpected keyword argument 'early_stopping_rounds'` | LightGBM>=4 | 用 `callbacks=[lgb.early_stopping()]` |
   | `--data-dir` → `--data_dir` | CLI 参数错误 | 使用 `--data-dir`（连字符） |

   **CLI 接口合约**：init.py 必须保持原始 CLI 接口：
   - `--data-dir` — 数据目录路径（不是 `--data_dir`）
   - `--split` — 数据分割（train/val）
   - `--out` — 输出路径
   
   预检查会自动将 `--data_dir` 改为 `--data-dir`。

   **预检查自动修复**：引擎会在评估前自动修复 `fillna(method=)` 和 `verbose_eval`/`early_stopping_rounds`，
   并记录 `precheck_fix` 事件。检查 `run_summary.json` 中的 `precheck_fixes` 计数。

2. 检查约束是否过严：
   ```bash
   grep "static_check" benchmark/hdd_mvp/evaluator.py
   ```

3. 检查是否有运行时依赖问题：
   ```bash
   cat benchmark/hdd_mvp/.fe/runs/<exp_id>/logs/*.log | head -50
   ```

4. 尝试增加 repair 限制：
   ```yaml
   # evolve.yaml
   reflection:
     max_repair_attempts: 3
   ```

### API 兼容性错误不惩罚知识卡片

当失败是由于 API 兼容性错误（如上述模式）导致时，系统会：
- 记录为 `adapter_error` 事件而非普通失败
- **不会**惩罚采纳的知识卡片（不增加 invalid_count）
- 在 `run_summary.json` 中报告 `adapter_errors` 计数

### Repair 耗尽

如果日志显示 `repair_exhausted`：

1. 查看失败的错误类型：
   ```bash
   grep "error_class" benchmark/hdd_mvp/.fe/runs/<exp_id>/events.jsonl
   ```

2. 检查是否是系统性错误（如依赖问题）

**注意**：Repair 路径也会经过性能门和烟雾测试。修复后的代码必须：
- 通过性能检查（无超时模式）
- 通过烟雾测试（在采样数据上正常运行）
- 只有都通过才进入完整评估

## 输出文件

进化结果存储在配置的目录中：

| 文件 | 说明 |
|------|------|
| `<runs_dir>/<exp_id>/fe.db` | SQLite 数据库 |
| `<artifacts_dir>/<exp_id>/run_summary.json` | 运行摘要 |
| `<artifacts_dir>/<exp_id>/tree.json` | 进化树结构 |
| `<artifacts_dir>/<exp_id>/events.jsonl` | 事件日志 |
| `<artifacts_dir>/<exp_id>/programs/*.py` | 所有生成的程序 |
| `<artifacts_dir>/<exp_id>/logs/*.log` | 错误日志 |

### run_summary.json 字段

```json
{
  "experiment_id": "abc123",
  "status": "finished",
  "iterations_done": 50,
  "best_score": 28.5,
  "valid_rate": 0.85,
  "total_tokens": 500000,
  "wall_time_s": 1800,
  "stop_reason": "max_iterations",
  
  // PR #3.1：stop_reason 语义
  // - target_score_reached：仅当 evolve.yaml stop.stop_at_target 为 true 且因达标提前结束
  // - max_iterations：跑满 budget.max_iterations（stop_at_target=false 时达标仍继续，结束时为此值）
  // target_reached / rounds_to_target 仍记录是否触及 target_score
  
  // PR #3.1 烟雾与自修复 token
  "smoke_time_s_total": 12.5,
  "smoke_tests": 10,
  "avg_smoke_time_s": 1.25,
  "self_fix_tokens": 8000,
  "iteration_events": 50,
  "jev_calls": 12,
  "jev_errors": 0,
  "jev_fail_open": 0,
  "jev_tokens": 4200,
  "evaluations_saved": 3,
  "eval_time_saved_est_s": 180.0,
  "screening_precision": 0.75,
  "jev_prior_active": true,
  "jev_disabled_reason": "",
  "repair_attempts": 15,
  "repair_successes": 8,
  "repair_tokens": 50000,
  
  // 知识注入统计
  "knowledge_tokens": 25000,
  "cards_offered": 100,
  "cards_adopted": 25,           // 总采纳次数（包括无效）
  "cards_adopted_valid": 18,     // 有效采纳次数
  "card_adoption_rate": 0.25,
  "card_stats": [
    {"card_id": "FE01", "n": 10, "mean_delta": 0.5, "refuted": 0, "invalid": 2}
  ],
  
  // 分阶段 Token
  "generate_tokens": 300000,
  "reflect_tokens": 50000,
  "knowledge_token_share": 0.05,
  
  // 效率指标
  "tokens_per_score_gain": 50000.0,
  "tokens_per_ros_point": 1200.5,
  "stage_cap_hits": {"reflect": 1},
  "budget_stop_reason": "",
  "elite_archive_sizes": {"rank": 2, "threshold": 1},
  "expand_skipped_budget": 0,
  "value_mode": "scalar",
  
  // 预检查和适配器错误
  "precheck_fixes": 5,           // 自动修复的 API 兼容性问题数
  "adapter_errors": 3,           // API 兼容性/harness 错误数（不惩罚卡片）
  
  // 性能门和烟雾测试（PR #3 新增）
  "perf_rejections": 2,          // 因性能问题被拒绝的候选数
  "smoke_failures": 5,           // 烟雾测试失败次数
  "smoke_fixes": 2               // 烟雾测试自动修复成功次数
}
```

## 配置说明

### evolve.yaml 关键配置

```yaml
budget:
  max_iterations: 50      # 最大迭代轮次
  max_tokens: 3000000     # Token 预算
  max_wall_hours: 6       # 墙钟时间上限
  # PR #5（默认关闭/空=不限）：stage_caps、stagnation_window: 0、tokens_per_point_cap: null

selection:
  c_puct: 1.2             # UCT 探索系数
  kappa_noise: 1.0        # 噪声系数
  value:
    mode: scalar          # scalar | multi（默认 scalar，与旧版一致）
    lambda_rank: 0.3
    lambda_noise: 1.0

stop:
  target_score: 32.0      # 目标分数（用于 rounds_to_target 等指标）
  stop_at_target: false   # true 时达标即停；false 时跑满 max_iterations 且 stop_reason=max_iterations

llm:
  generate_model: qwen3-coder-plus
  temperature: 0.7
  max_concurrency: 4

reflection:
  max_repair_attempts: 2  # 每个失败节点的最大修复次数

# 知识注入配置（PR #3）
knowledge:
  dir: knowledge          # 相对于任务目录
  k: 4                    # 每次检索返回的卡片数
  max_per_category: 2     # 每类别最多卡片数

# dev 错例画像（PR #6，默认关闭）
analysis:
  enabled: false
  top_k: 3
  on_new_best: true
  dev_late_fraction: 0.4
  timeout_s: 600
  min_group_count: 10

# Jev 评判器配置（可选）
judge:
  provider: none          # none / jev / mock
  base_url: https://miyang.cn/api/v1/decisions
  api_key_env: MIYANG_API_KEY
  model: miyang/jev-1.13
  timeout_s: 5
  prescreen: false
  prior: true
```

### 存储路径优先级

**数据库路径**：
1. `--runs-dir` CLI 参数
2. `FE_RUNS_DIR` 环境变量
3. 默认值：`<task_dir>/.fe/runs`

**工件路径**：
1. `--artifacts-dir` CLI 参数
2. `FE_ARTIFACTS_DIR` 环境变量
3. 默认值：与数据库路径相同

## 禁止操作

- **不得** 删除或覆盖已有实验数据
- **不得** 读取 `data/holdout*` 或把私有测试分数写入 prompt
- **不得** 在代码或日志中记录 API Key 的值
- **不得** 修改 `benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md}`

## 参考

- 开发指南：`docs/dev/MVP开发指南.md`
- 系统设计：`docs/design/01-系统总体设计.md`
- 知识注入：`skill/fe-knowledge-injection/SKILL.md`
- 数据集适配：`skill/fe-dataset-adapters/SKILL.md`
- 数据集文档：`docs/datasets/backblaze.md`、`docs/datasets/alibaba_ssd.md`、`docs/datasets/smartmem.md`
- HDD 基准：`benchmark/hdd_mvp/`
