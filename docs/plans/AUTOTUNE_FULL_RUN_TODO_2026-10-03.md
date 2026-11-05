# HDD 全量自动调优运行：执行 TODO

日期：2026-10-03（UTC）。给 composer-2.5 等执行代理。先读 [计划](AUTOTUNE_FULL_RUN_PLAN_2026-10-03.md)、[设计备忘](../design/07-HDD全量自动调优运行-设计备忘.md)、`AGENTS.md`。
前提：本 TODO 的 PR 已合并，下文 `<MERGE>` 指合并后 main 的 HEAD 提交。每一步完成后在方括号打勾并附真实输出摘要；不得编造数字。

## 全局禁止

- 不改 `benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md}`、`data/`、`prepare_data.py`、`knowledge/cards.jsonl`。
- 不读、不打印、不上传 `benchmark/hdd_mvp/data/holdout*`；不用 `--split test`。
- 不打印或写入密钥（`DASHSCOPE_API_KEY`、`TYPESAFE_API_KEY`、`FE_API_KEY`）；`fe doctor` 只看存在性。
- 不提高 `discovery.tournament.n_slices`、`discovery.bootstrap_b`；不改 `src/faultevolve/discovery/**`。
- 不改既有测试断言；不新增第三方依赖。
- 不在服务器上 `git clean`、`git reset --hard`、`git stash`、`git checkout -- .`；不动 data、results、`.env`、无关目录。
- 新功能默认保持关闭；只有 `run_full_hdd.evolve.yaml` 打开。
- 只跑**一次**真实运行；失败也不"换 seed 重跑择优"，回报即可。
- 不写 E3/E4/E5/K1 代码，不做泛化数据集，不做 gitcode 提交。

## A. 修 CI（先改代码，最后跑测试）

分支：`cursor/autotune-ci-fix-<suffix>`（按当前环境的分支命名规则）。

- [ ] A1 契约漂移：在仓库根执行 `pnpm --dir web install --frozen-lockfile && pnpm --dir web sync:contracts`。预期更新 `web/openapi/*.json` 与 `web/src/generated/api/*`，且 `OperatorType` 出现 `hpo`、`patch`。只提交生成物，手改生成文件无效。
- [ ] A2 引擎事件目录：编辑 `src/faultevolve/webapi/catalog.py`，补齐 `patch_applied`、`patch_fallback_draft`、`patch_proposed`、`patch_rejected`、`patch_unavailable`、`quota_slot` 六个事件的条目，格式照同文件已有条目（含中文说明文字）。核对事件名与 `cloud/engine.py`、`cloud/engine_autotune.py` 的 `_log_event` 调用一致。
- [ ] A3 `OperatorType` 缺 `hpo/patch`：先看 `src/faultevolve/common/schemas.py` 是否已有；若已有则问题在导出，A1 解决；若 webapi 另有手写枚举镜像（`rg "threshold_calibrate" src/faultevolve/webapi`），同步补 `hpo`、`patch`。
- [ ] A4 预存失败 `tests/webapi/test_server_profiles.py::test_private_key_ref_resolves_through_the_environment`：先 `python -m pytest tests/webapi/test_server_profiles.py -k private_key_ref -x -q` 复现并读报错，再读 `src/faultevolve/webapi/server_profiles.py::resolve_key_ref`。**修实现，不改测试断言**；若确认测试本身与规格矛盾，在 PR 说明里逐条论证并停下回报。
- [ ] A5 最后跑测试：
  ```bash
  python -m pytest tests/ -q
  python scripts/check_web_contracts.py
  pnpm --dir web test
  cd benchmark/hdd_mvp && python evaluator.py init.py   # val ROS ≈ 22.81，仅用于确认未破坏基线
  ```
  成功检查：全部通过；`git diff --stat -- benchmark/` 为空。不新增实验，不跑真实 LLM。
- [ ] A6 PR 说明列出：修了哪几项、各自对应的 CI 失败名。

## B. Gate H：HPO 接线核查

- [ ] B1 核查：`rg -n "run_hpo|hpo_runner" src scripts`；若引擎主循环（`cloud/engine.py`）已调用则跳到 B4。
- [ ] B2 若未接线，按设计备忘 §3 做最小接线：`engine.py::_choose_operator` 的 `hpo` 槽位 → 新增 `engine_autotune.py` 中的函数，复用 `optimization/hpo_runner.py` 的 dev 划分/缓存/预算，晋级 spec 经 `compile_spec` 编译为代码，作为普通节点走 `_evaluate_child`。HPO 阶段计入账本，名称 `hpo_trial`。仅当 `autotune.hpo.enabled and autotune.quota.enabled` 才生效。
  - 若需要改 DB 既有表、或改动超过约 150 行主循环逻辑：**停止并回报**，选 §6 降级（计划）。
- [ ] B3 新增测试（`tests/test_autotune_engine_hpo.py`，仅 `tmp_path` 合成数据 + `--mock`）：hpo 槽位产生一个节点；默认关时 `run_summary` 键集合不变；HPO 的 dev 分不进入 `combined_score`。
- [ ] B4 测试在最后：`python -m pytest tests/ -q`，确认 `tests/test_hdd_protected_files.py` 与 `tests/test_autotune_data_guard.py` 通过。
- [ ] B5 与 A 合并或另开 PR，合并后记录 `<MERGE>` 提交号。

## C. 服务器拉代码（`/home/hcf/faultevolve/code`）

- [ ] C1 只读检查：
  ```bash
  cd /home/hcf/faultevolve/code
  git status --short | head -20
  git rev-parse HEAD
  ls -l benchmark/hdd_mvp/data   # 应为指向 NAS 的软链；仅确认，不修改
  df -h /
  ```
- [ ] C2 若 `git status` 显示**已跟踪文件被修改**（除上述 data 软链外）：**停止，回报文件列表**，不要 stash/reset/clean。
- [ ] C3 拉取：
  ```bash
  git fetch origin main
  git merge --ff-only <MERGE>
  git rev-parse HEAD     # 必须等于 <MERGE>
  conda activate faultevolve && pip install -e . -q
  ```
  `--ff-only` 失败（含因 data 软链冲突）→ 停止并回报，不加 `-f`、不 reset。
- [ ] C4 成功检查：HEAD == `<MERGE>`；`python -m pytest tests/ -q --ignore=tests/webapi` 通过；`ls /home/hcf/nas_hcf_data/faultevolve` 未被改动。

## D. 预检与 mock 冒烟

- [ ] D1 生成配置：以 `benchmark/hdd_mvp/evolve.yaml` 为底，按计划 §3 覆盖键，写 `docs/plans/autotune/run_full_hdd.evolve.yaml`（完整配置，不是片段）。用 `python -c "from faultevolve.config import EvolveConfig; from pathlib import Path; c=EvolveConfig.from_yaml(Path('docs/plans/autotune/run_full_hdd.evolve.yaml')); print(c.autotune.model_dump())"` 确认校验通过，且 `max_tokens==150000`。
- [ ] D2 配置回归测试（可放 `tests/test_autotune_run_config.py`）：加载该文件校验通过；`EvolveConfig()` 默认下 `autotune.*.enabled` 全为 False。
- [ ] D3 `fe doctor --env-file /home/hcf/faultevolve/.env --task-dir benchmark/hdd_mvp --json`，只看密钥是否存在。
- [ ] D4 mock 冒烟：
  ```bash
  fe evolve local benchmark/hdd_mvp --mock -n 4 --config-file docs/plans/autotune/run_full_hdd.evolve.yaml \
    --runs-dir /tmp/fe-smoke --artifacts-dir /tmp/fe-smoke-art --json
  ```
  成功检查：事件流含 `quota_slot`；patch 与 hpo 槽位均出现过（patch 因 mock 无标记可显示 `patch_unavailable`，也算出现）；账本 `cost_ledger` 有记录；退出码 0。

## E. 一次真实运行

- [ ] E1 记录 `<MERGE>`、配置 sha256、`date -u`。
- [ ] E2 启动（`--config-file` 替换 evolve.yaml；fe.db 留本地默认位置，**不要**把 `--runs-dir` 指向 NAS）：
  ```bash
  cd /home/hcf/faultevolve/code && conda activate faultevolve
  ART=/home/hcf/nas_hcf_data/faultevolve/runs/autotune_full_$(date -u +%Y%m%d)
  mkdir -p "$ART"
  nohup fe evolve local benchmark/hdd_mvp -n 10 --seed 20260926 \
    --config-file docs/plans/autotune/run_full_hdd.evolve.yaml \
    --env-file /home/hcf/faultevolve/.env --artifacts-dir "$ART" --json > "$ART/run.log" 2>&1 &
  echo $! > /tmp/fe_run.pid
  ```
  推荐放进 tmux 会话而不是裸 nohup。如中断：`fe evolve local benchmark/hdd_mvp --resume <exp_id> --artifacts-dir "$ART" --env-file ... --config-file ...`。
- [ ] E3 监控只看 `run.log` 尾部与 `df -h /`；token 超 150k 或 `ledger_full_eval_cap` 触顶是正常停止，不加预算重跑。
- [ ] E4 结束后确认：`run_summary.json` 存在；`stop_reason` 已记录；无 holdout 路径出现在日志（`rg holdout "$ART/run.log"` 应无命中）。

## F. 报告

- [ ] F1 新建 `docs/plans/autotune/FULL_RUN_REPORT.md`（简体中文），逐项满足计划 §5 的 6 条。数据来源：`run_summary.json`、`fe.db` 节点 metric、账本 `by_stage`、事件流。可用 `scripts/autotune_rebuild_metrics.py --db <fe.db 副本> --events ... --run-summary ...` 重建指标。
- [ ] F2 必含表：
  - P/R/F1、false_alarm_rate、missed_detection_rate（最优节点；以及全部有效节点列表）；
  - 按阶段 token 表（含 HPO 行）与占 150k 的比例；
  - 与 38.14 观察点的对照（差值，标注"历史观察点，口径不同"）；
  - patch/HPO/quota 事件计数。
- [ ] F3 缺的数据写"未记录"，不估算。不写"开关带来提升/退化"的因果句。
- [ ] F4 更新 `docs/TODO.md` 顶部指针、`skill/fe-autotune-plan/SKILL.md` 状态表（把"未跑付费真实进化"改为实际情况）。PR 内只提交文档，不提交 fe.db / 产物。

## G. 现象级特征检查（可选分支）

- [ ] G1 按计划 §7 的三条标准检查；只读训练侧公开数据与运行产物。
- [ ] G2 结论写入报告末节：**否** → 结束；**是** → 另写一页《下一步知识发现建议》放 `docs/plans/`，只含单特征确认方案，不执行、不扩成多 claim 活动。

## 完成定义

CI 绿；服务器 HEAD == `<MERGE>`；一份满足 §5 的报告；`git diff --stat -- benchmark/` 为空；无密钥、无 holdout 信息入库。
