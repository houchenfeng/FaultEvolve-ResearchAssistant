---
name: fe-autotune-plan
description: 自动调优与进化搜索（E0～E2 已实现首版；E3/E4/E5/K1 未开始）的实施与运行入口。
---

## 状态（2026-10-04 分支）

| 阶段 | 状态 |
|---|---|
| E0 基线/账本/manifest | 代码与 `docs/plans/autotune/*` 已就位；NAS 差异 **BLOCKED**；未跑付费真实进化 |
| E1 结构化 HPO | `optimization/hpo_runner.py`、`scripts/autotune_hpo.py`；**默认 `autotune.hpo.enabled=false`** |
| E2 Patch/反馈/配额 | SEARCH/REPLACE、`OperatorType.patch`、配额调度；**默认全关** |
| Gate H（引擎 HPO 接线） | **已实现**（`quota` 的 `hpo` 槽 + `autotune.hpo/quota.enabled` → dev trial + 完整评估晋级） |
| E3 逻辑岛 | **未实现** |
| E4 本地异步 | **未实现** |
| E5 RSI | **未实现** |
| K1 知识发现恢复 | **未实现** |

## 全量运行任务（2026-10-03 规划，待执行）

目标：HDD 上一次约 150k token 的真实进化，账本 + 随机 HPO + patch 全开，与历史观察点 38.14（Run B `final_B/f9752fcd`）对照。无需向用户提问，按下列顺序执行：

1. 读 `docs/plans/AUTOTUNE_FULL_RUN_PLAN_2026-10-03.md`（范围、配置、报告必填项）与 `docs/design/07-HDD全量自动调优运行-设计备忘.md`（HPO 目前未接入引擎主循环）。
2. 按 `docs/plans/AUTOTUNE_FULL_RUN_TODO_2026-10-03.md` 的 A→G 逐步执行：A 修 CI（`pnpm --dir web sync:contracts`、`webapi/catalog.py` 补六个事件、修 `resolve_key_ref`，测试放最后）；B Gate H 已接线（见上表）；C 服务器 `git fetch` + `git merge --ff-only <合并提交>`；D 配置与 mock 冒烟；E 单次真实运行；F 报告；G 现象级特征检查。
3. `--config-file` 替换而非叠加 `evolve.yaml`，配置必须是完整文件。
4. 报告必含：P/R/F1、false_alarm_rate、missed_detection_rate、按阶段 token 用量；38.14 只称历史观察点。

停止并回报的情形：服务器 `git status` 有已跟踪文件改动；`--ff-only` 失败；HPO 接线需改 DB 既有表或大改主循环；密钥缺失；任何步骤会触及 `data/holdout*`。

禁止：`git clean`、`git reset --hard`、`git stash`；改受保护基准或数据；写入密钥；换 seed 重跑择优；提高 `n_slices`/`bootstrap_b`；开启任何默认关闭的功能（实验配置除外）；E3/E4/E5/K1 与泛化数据集、gitcode 提交。

## 何时使用

- 离线验证账本、HPO、patch 或阅读冻结协议。
- 推进 E3+ 前先读计划 §6～§9（标 **未开始** 的部分不要擅自实现）。

## 阅读顺序

1. `AGENTS.md`
2. `docs/plans/AUTOTUNE_EVOLUTION_TODO_2026-10-04.md` §1 不变量
3. `docs/design/06-自动调优与进化搜索改进设计.md`

## 环境

```bash
pip install -r requirements.txt
pip install -e .
```

## E0：账本与 manifest（默认关）

**开启账本**（示例，会写入 `cost_ledger` 表）：

```bash
fe evolve local tests/fixtures/toy_task --mock --iterations 2 \
  --config-file docs/plans/autotune/protocol_dev_A.evolve.yaml \
  --runs-dir /tmp/fe-runs --artifacts-dir /tmp/fe-art
```

注意：`protocol_dev_A.evolve.yaml` 里 `autotune.ledger.enabled=true` 且 `full_eval_cap: 50`（与 `--iterations` 语义不同，见 `E0_EXIT.md`）。

**生成 manifest**（不读 holdout/eval_only）：

```bash
PYTHONPATH=src python3 scripts/autotune_manifest.py \
  --task-dir benchmark/hdd_mvp \
  --config docs/plans/autotune/protocol_dev_A.evolve.yaml \
  --out docs/plans/autotune/baseline_manifest.json
```

**重建指标**（只读 DB 副本）：

```bash
python3 scripts/autotune_rebuild_metrics.py --db /path/to/fe.db.copy \
  --events /path/to/events.jsonl --run-summary /path/to/run_summary.json
```

成功检查：`python3 -m pytest tests/test_autotune_ledger.py tests/test_autotune_manifest.py -q`

## E1：无 LLM HPO（默认关）

配置需同时：`autotune.ledger.enabled=true` 与 `autotune.hpo.enabled=true`。

```bash
python3 scripts/autotune_hpo.py \
  --task-dir benchmark/hdd_mvp \
  --config /path/to/hpo_enabled.yaml \
  --runs-dir /tmp/hpo-runs \
  --artifacts-dir /tmp/hpo-art \
  --mock-eval
```

合成数据自测：`python3 -m pytest tests/test_autotune_hpo_runner.py -q`（仅用 `tmp_path`）。

`hpo.enabled=false` 时脚本退出码 2，不写 DB。

## E2：Patch / 配额 / 反馈（默认关）

在 evolve 配置中设置：

```yaml
autotune:
  ledger: {enabled: true}
  patch: {enabled: true}
  feedback: {enabled: true}
  quota: {enabled: true}   # 要求 operators.bandit=false
```

单测：`python3 -m pytest tests/test_autotune_patching.py tests/test_autotune_quota.py tests/test_autotune_feedback.py -q`

Patch 仅支持 **SEARCH/REPLACE**（不支持 unified diff）。父代码无 `FE-BLOCK` 标记时 patch 不可用。

## 失败处理

- `hpo.enabled` 但 `ledger.enabled=false` → 配置校验 `ValueError`。
- `quota.enabled` 且 `operators.bandit=true` → `ValueError`。
- `ledger_full_eval_cap` 触顶 → `stop_reason=ledger_full_eval_cap`。
- NAS 不可读 → 勿臆测版本差异；在 `E0_VERSION_DIFF.md` 保持 BLOCKED 并上报。

## 全量回归

```bash
python3 -m pytest tests/ -q --ignore=tests/webapi
```

（受保护基准与 discovery 默认不得改动。）
