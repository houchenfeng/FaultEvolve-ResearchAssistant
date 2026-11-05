# HDD 服务器上的三岛运行（本项目主机专属）

本页只描述 FaultEvolve 项目当前实验主机（SSH 别名 `3056-hcf-10.61.48.10`，`hcf@10.61.48.10`）的部署方式。**换机器就换本页**：路径、独立 venv、NAS 挂载、密钥文件都是这台机器的配置，不是通用 Skill 的一部分。

> 状态：**S8（真实预检）已执行**——run `hdd_mvp_preflight_20261008`，2026-10-08 20:07:36→20:32:08 +08:00，best 38.2067；实际 ID、路径、结果与失败已回填到 `docs/plans/THREE_ISLAND_IMPLEMENTATION_TODO_2026-10-08.md`（S8 节、A0–A2、B/D/E/F 段）。**S9（正式运行）尚未执行**，下方 S9 章节仍是待执行的方案、不是已跑过的记录（S8 的真实记录见上一节）。本页已按 S8 实际做法修正三处：完整历史 bundle＋服务器 `git clone --branch`（不是增量 bundle）、部署根内独立 `.venv`（不是 conda）、`preflight/{runs,artifacts}` 分家根（不是 NAS 单根）。

---

## 主机事实（README 已核实，不含密钥）

| 项 | 值 |
|---|---|
| SSH | 别名 `3056-hcf-10.61.48.10` = `hcf@10.61.48.10` |
| 专用只读密钥 | `~/.ssh/id_ed25519_faultevolve_3056`（与 GitHub 身份分离，只用于登录核实） |
| 规格 | 约 32 核 / 124G 内存 / 2× RTX 4090 D（24GB×2），无图形桌面 |
| 运行环境 | 部署根内的独立 `.venv`（S8 实测：`$TM/code/.venv`，Python 3.13.11，`pip install -r requirements.txt`＋`pip install -e .`）；不要依赖系统 conda，也不要用旧目录的环境 |
| 代码目录 | 旧目录 `/home/hcf/faultevolve/code`（历史复现，只读，HEAD `dcd2283e`）；三岛运行用 `$TM/code`（每部署根一套 `git clone`） |
| HDD 数据根（NAS） | `/home/hcf/nas_hcf_data/faultevolve/data/hdd_mvp` |
| 运行制品根（S8 实测） | 服务器本地盘部署根内：`$TM/preflight/{runs,artifacts}`、`$TM/formal/{runs,artifacts}`；NAS `runs/` 下是历史冻结成果，只读 |
| 密钥文件 | `/home/hcf/faultevolve/.env`（mode 600；S8 实测经 `--env-file` 注入，只检查存在性与布尔“已配置”，不 `cat`、不打印内容） |
| 磁盘 | 2026-10-08 实测根盘 1.9T 中已用 87%、可用 256G；NAS 为 `//10.62.192.79/public/hcf_data` |

---

## 放置规则（违反即污染历史成果）

1. **数据库不进 NAS。** `fe.db` 不进 NAS——引擎在网络文件系统上建库会直接拒绝，这不是提示而是失败。S8 实测做法：`--runs-dir` 与 `--artifacts-dir` 都落在服务器本地部署根下的分家目录（`$TM/preflight/runs`＋`$TM/preflight/artifacts`），制品同样按 `<root>/<run_id>/` 分目录。
2. **旧目录只读。** NAS `runs/` 下的 `final_A`、`final_B`、`autotune_full_20261004`（实验 `89f4bdd1`）、`kd_relaxed_20261005`、`kd_replay_20261005` 是冻结成果，只追加新实验目录，不写不改不删。冻结 Run B 的 38.14 是历史观测，不是当前 main 基线。
3. **数据软链保持原状。** 服务器上 `benchmark/hdd_mvp/data` 常为指向 NAS 的软链，git 可能显示受跟踪数据「已删除」——这是本机既有状态，不要 `git checkout`、不要 `git clean`。
4. **只用公开 train + val。** 私有 holdout 不在仓库也不在服务器可遍历范围内；不读、不打印、不上传，也不作为发现或调优目标。
5. **服务器 git 红线**：禁止 `git clean` / `git reset --hard` / `git stash` / `git checkout -- .`；只允许快进合并或下面的 bundle 拉取。

---

## 新目录纪律（每次运行一套，唯一时间戳）

三岛运行用 `<timestamp>`（实际用过 `20261008-200410`，即 `YYYYMMDD-HHMMSS`）建一个**新**根目录，绝不复用旧名：

```text
/home/hcf/faultevolve/three_island_<timestamp>/
  code/          # 服务器 git clone 出来的代码副本（内含独立 .venv）
  preflight/     # preflight/runs/（fe.db）与 preflight/artifacts/ 分家，均在服务器本地盘
  formal/        # 同上，正式运行
  deployment/    # 外置配置、bundle 传输与合入记录
  web/           # 前端构建与服务日志
  evidence/      # 截图、API 检查输出、不含密钥的 manifest
```

制品按运行 ID 分子目录（`<artifacts-root>/<exp_id>/`），因此同一目录可以容纳多次运行而不互相覆盖。恢复运行永远指向**同一个** `--artifacts-dir`，否则产物会分裂到两处。

---

## 代码同步：本机打包 → bundle → scp → 服务器 clone

服务器不能直连 GitHub（README 已记录），S8 实测走**完整历史 bundle**：

```bash
# 本机（实现分支已提交并推送）
git bundle create /tmp/faultevolve-three-island-<timestamp>.bundle codex/three-island-real-runs
git bundle verify /tmp/faultevolve-three-island-<timestamp>.bundle
scp /tmp/faultevolve-three-island-<timestamp>.bundle 3056-hcf-10.61.48.10:/tmp/

# 服务器：新目录直接 git clone 出分支（不必手动 init/fetch）
TM=/home/hcf/faultevolve/three_island_<timestamp>
git clone --branch codex/three-island-real-runs /tmp/faultevolve-three-island-<timestamp>.bundle "$TM/code"
```

增量 bundle（`<base>..HEAD`）只用于已含基点的仓库；新目录一律用完整 bundle＋`clone`。核对（S8 实测：两侧 bundle sha256 一致 `93469ba9…`，服务器 HEAD＝本地 `7687df2c…`，status 干净）：

```bash
sha256sum /tmp/faultevolve-three-island-<timestamp>.bundle   # 与本机比对
git -C "$TM/code" rev-parse HEAD
git -C "$TM/code" status --porcelain                          # 应为空
```

**不要在已有长跑的机器上降级/覆盖 `/home/hcf/faultevolve/code`**；新代码写部署根 `$TM/code`，旧目录保持能跑历史复现。依赖装进部署根自己的 venv（S8 实测；不要动服务器公共环境）：

```bash
cd "$TM/code"
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .
```

---

## 三岛配置：用 `--config-file`，不改被保护的 `evolve.yaml`

`benchmark/hdd_mvp/evolve.yaml` 是 Famou 对比的共享基线，禁止修改。三岛参数写在任务目录之外的外置配置文件里（S8 实测：部署根 `$TM/deployment/preflight_evolve.yaml`；正式运行另存 `formal_evolve.yaml`），用 `--config-file` 传入（`fe evolve local` 与 `fe doctor` 都支持，且解析的是同一个文件——这是 `fe doctor` 修过之后的行为，早期版本会退回默认适配器）：

```yaml
# $TM/deployment/preflight_evolve.yaml（预检）／formal_evolve.yaml（正式）
task:
  adapter: hdd
islands:
  enabled: true
  exchange_interval: 1      # 预检用 1；正式按需求 §5 用 5
  eval_concurrency: 1       # 唯一受支持的值，>1 会被引擎拒绝
  islands:                  # 列表键名就叫 islands，嵌在 islands 块里
    - island_id: a
      profile: performance
      max_attempts: 50      # 预检用 2；正式 50
    - island_id: b
      profile: miss_alert
      max_attempts: 50
    - island_id: c
      profile: efficiency
      max_attempts: 50
budget:
  max_iterations: 150       # 三岛 × 50 的全局上限（预检 6）
  max_tokens: null          # 成本不设用户上限
  max_wall_hours: null      # 默认 6.0 是墙钟上限，长跑会撞它
stop:
  target_score: null
```

- `islands.eval_concurrency > 1` 会抛出 `islands.eval_concurrency > 1 is not implemented: islands run serially, got N`。并发不是配置项，而是尚未实现，所以别在计划里写「并发调高试试」。
- 每岛 `max_attempts` 默认 50、`budget.max_iterations` 默认 50。50 次/岛是每岛名额，`max_iterations` 是三条树之和的全局上界——两个都要显式写，别只靠默认，否则正式跑到第 50 个全局迭代就停。
- `budget.max_wall_hours` 默认 `6.0`，按**当前进程**的墙钟计时：长跑会因此以墙钟原因结束，续跑又会重新计时。真实 HDD 评估一次要跑分钟级，正式运行前要么显式设 `null`，要么在计划里记录实际墙钟，别假设「没有上限」。
- profile 必须互不相同；`profile: custom` 必须同时给 `focus`，否则配置校验失败。
- 启动前先跑预检配置，把实际生效的岛环读出来（不要凭记忆）：

```bash
cd "$TM/code"
.venv/bin/fe doctor --task-dir benchmark/hdd_mvp \
  --config-file "$TM/deployment/preflight_evolve.yaml" \
  --env-file /home/hcf/faultevolve/.env --json
```

看 `config_islands`（应为 `islands on: 3 tree(s) [a:performance, b:miss_alert, c:efficiency], exchange every 1 attempts`）、`config_keys`（不认识键会被列出并判失败）、以及数据/密钥检查项。`fe doctor` 不通过就不启动运行。S8 实测：17 项检查全 ✓，唯一 `✗ FE_API_KEY not set` 是 Web 端专用、不影响演化运行（整体退出码因此为 1，属预期）；`adapter hdd -> HDDAdapter` 与数据根（输出含 `HDD_BENCH_DATA_ROOT=…`）都要在输出里确认。

---

## S8 预检（已执行：2026-10-08，run `hdd_mvp_preflight_20261008`）

目标：确认真实 LLM、真实 HDD evaluator、三岛归属与摘要链路，**不追求分数**。S8 实际命令（逐字；密钥仅经 `--env-file`，不出现明文；无 `--mock`、无 `--json`、种子来自配置文件）：

```bash
TM=/home/hcf/faultevolve/three_island_20261008-200410
cd "$TM/code"
HDD_BENCH_DATA_ROOT=/home/hcf/nas_hcf_data/faultevolve/data/hdd_mvp \
nohup .venv/bin/fe evolve local benchmark/hdd_mvp \
  --config-file "$TM/deployment/preflight_evolve.yaml" \
  --env-file /home/hcf/faultevolve/.env \
  -n 6 \
  --runs-dir "$TM/preflight/runs" \
  --artifacts-dir "$TM/preflight/artifacts" \
  --run-id hdd_mvp_preflight_20261008 \
  > "$TM/preflight/console_preflight.log" 2>&1 &
echo $! > "$TM/preflight/pid.txt"
```

结果（20:07:36→20:32:08，约 24m32s）：`finished`，全局 `max_iterations`／各岛 `max_attempts`；best `4c1635ca`（b 岛）38.2067（初始 22.8074）；13 次真实 LLM 调用全 `outcome=ok`、5 次真实 evaluator 执行；5 摘要/10 投递/11 采用，关键链路 `sum-3b709a88`→`dlv-ce915ea4`→`app-d1a808ad`→`f0cd9659`（36.6104）；tokens 76499、`cost_usd=null`（`cost_basis=unknown`）；自然失败如实保留（invalid 2、smoke_failed→fix 1、hypothesis_refuted 2）。逐条证据在计划文档 S8 节与 A1/A2/B/D/E 段。

**S8 教训（S9 启动器必须修正）**：`nohup … &` 直起没有包裹退出码，预检退出码不可回取；S9 启动器用 `sh -c '…; echo $? > exit_code.txt'` 包裹（见下节模板）。

- 数据根用 `HDD_BENCH_DATA_ROOT`（`HDDAdapter` 与 `hdd_mvp/evaluator.py` 都读它，子目录为 `public/`），不设则回退 `task_dir/data`。这个变量与 `backblaze` 任务共用，切换任务前 `export` 或 `unset`。
- 预检必须**没有** `--mock`：出现 mock/fallback 就不算预检。用 `fe doctor` 的输出与 `run_summary.json` 里的 `model`/`cost.cost_basis` 交叉确认真的调用了模型。
- 跑完逐条回写计划文档：实际消息类型（S8 实测：`best` 3＋`failure` 2；`knowledge` 以 `knowledge_injected` 事件计 6 次）、失败清单、token 成本、输出路径。发现问题需要重试时**另建运行 ID**，保留旧的失败记录，不在同一 ID 上覆盖。

## S9 正式运行（待执行模板）

S8 教训：`nohup … &` 直起拿不到退出码。S9 用启动器脚本包裹，后台起、跑完落 `exit_code.txt`：

```bash
TM=/home/hcf/faultevolve/three_island_<timestamp>
cat > "$TM/formal/launch_formal.sh" <<SCRIPT
#!/bin/sh
cd "$TM/code"
export HDD_BENCH_DATA_ROOT=/home/hcf/nas_hcf_data/faultevolve/data/hdd_mvp
.venv/bin/fe evolve local benchmark/hdd_mvp -n 150 \\
  --config-file "$TM/deployment/formal_evolve.yaml" \\
  --env-file /home/hcf/faultevolve/.env \\
  --runs-dir "$TM/formal/runs" --artifacts-dir "$TM/formal/artifacts" \\
  --run-id <formal_run_id> > "$TM/formal/console_formal.log" 2>&1
echo \$? > "$TM/formal/exit_code.txt"
SCRIPT
chmod +x "$TM/formal/launch_formal.sh"
nohup "$TM/formal/launch_formal.sh" > /dev/null 2>&1 &
echo $! > "$TM/formal/pid.txt"
```

（heredoc 未加引号，写文件时展开 `$TM`；`\$?` 转义后留在脚本里，指的是 `fe` 的退出码。运行 ID 用 `--run-id` 指定或让引擎生成 8 位，不得覆盖预检、Run A/B、`89f4bdd1` 或任何冻结产物。）

监控（只读，不改评估公式、不换数据、不放宽 gates）：

```bash
tail -f "$TM/formal/console_formal.log"
python - <<'PY'
import json, pathlib
p = pathlib.Path("/home/hcf/faultevolve/three_island_<timestamp>/formal/artifacts/<run_id>")
print(json.dumps({k: v for k, v in json.loads((p / "run_summary.json").read_text("utf-8")).items()
                  if k in {"islands", "exchange", "cost", "status", "stop_reason"}},
                 ensure_ascii=False, indent=2))
PY
```

三岛进度以 `run_summary.json` 的 `islands` / `exchange` / `cost` 三块为准；每岛 `attempts`、`valid_evaluations`、`stop_reason` 和逐岛 token 都在里面（S8 实测这三块与库中 `island_state`/`llm_call` 可对账）。

中断后续跑（同一份配置、同一个 `--artifacts-dir`）：

```bash
cd "$TM/code"
.venv/bin/fe evolve local benchmark/hdd_mvp --resume <exp_id> \
  --config-file "$TM/deployment/formal_evolve.yaml" \
  --runs-dir "$TM/formal/runs" \
  --artifacts-dir "$TM/formal/artifacts" \
  --env-file /home/hcf/faultevolve/.env
```

身份字段对不上会被拒绝并说明差异；那是保护历史运行的机制，不是需要绕过的报错（详见 [recovery.md](recovery.md)）。注意：S8 预检一次跑完、未发生中断，服务器端 `--resume` 至今仍未实测执行过。

---

## 服务器 WebUI（属 S9）

S8 只建了 `$TM/web/` 目录（仍为空），服务器页面的只读验收至今未做；以下为 S9 待执行事项。

- 在**新目录**构建前端，按仓库真实部署方式启动 API 与页面；参数以 `fe web serve --help` 的输出为准，不要用 E2E fixture 服务代替产品服务。
- 优先绑定回环地址，用 SSH 转发访问：`ssh -L 8765:127.0.0.1:8765 3056-hcf-10.61.48.10`，记录最终地址、端口和启停方法。
- 服务日志写新目录，不改已有服务；运行索引要保存扫描清单和每项处理状态，历史单岛运行与新三岛运行都验证一遍列表页、结果页、交换详情与无数据状态。
- 截图与 API 检查产物存到 `evidence/`，其中不得含密钥。

## 记录什么才算跑过

预检与正式运行各留一份不含密钥的 manifest：代码 SHA、配置哈希、允许的 train/val 文件指纹、评估器哈希、随机种子、环境、时间、运行 ID、`--artifacts-dir` 绝对路径、停止原因、逐岛与全局最优、成本、经验 Skill 草稿路径（S9 正式运行含草稿；S8 预检未导出草稿）。

本轮**不含**单树对照与跨数据集测试：只比较同次运行的初始解与最终结果。不得据此宣称三岛方法优于单树。结果无论提升还是退化都如实记录，写到 `docs/plans/` 的结果表里，并把本页标注为「已执行 + 运行 ID」。S8 预检已按此格式回填（run `hdd_mvp_preflight_20261008`，见计划文档 S8 节与 A1/A2/B/D/E 段）；S9 正式运行同样回填后，本页状态行与计划文档一起更新。
