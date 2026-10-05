# fe-report-generation

## 何时使用

需要生成与 manifest 数字一致的答辩/结果表时（KD2）。

## 输入

单次运行的 artifacts 目录（含 `run_summary.json` 与 `discovery/*`）。

## 命令

```bash
fe report <task_dir> --run-id <EXP> --json
fe report <task_dir> --run-id <EXP> --md
fe report <task_dir> --run-id <EXP> --json --runs-dir "$FE_RUNS_DIR"
python skill/fe-report-generation/scripts/check_report_numbers.py <report.md> <artifacts_dir>
```

未传 `--runs-dir` 时，CLI 使用 `get_runs_dir(None, task_dir)`（环境变量 `FE_RUNS_DIR` 优先，否则 `<task_dir>/.fe/runs`）。

## 成功检查

- `verify_md` 无未匹配数字
- 报告中数字可在 `run_summary.json` / `discovery/mechanisms.json` / `discovery/certificates.json` 中找到

## Token 分层与发现效率（`fe report` / manifest）

`fe report ... --json` 的 manifest 含 `token_tiers` 与（若有）`funnel`：

- **按阶段 token**：`generate`、`repair`、`reflect`、`knowledge`、`self_fix`、`discovery`、`crossover`、`tournament`、`mechanism`（来自 `run_summary.json` 的 `*_tokens` 与 `total_tokens`）
- **`tokens_per_score_gain`**：`total_tokens / (best_score - initial_score)`；无分数提升（纯发现 run）时为 **`n/a`**，不得用 eps 造巨大数
- **发现专属**：`tokens_per_candidate_tested`、`tokens_per_confirmed_claim`（confirmed=0 时为 `n/a`）、`discovery_token_share`
- **发现 run 子表**：`propose_tokens`、`translate_tokens`、`entailment_tokens`（写在 `run_summary.json`；`fe discover factors` 全流程时 `entailment_tokens` 为蕴含阶段实测，与 `discovery_tokens` 分列）
- **KD1-G 漏斗**：manifest `funnel` 含 `power_gate`、`power_gate_pass`、`mde_explore_effect_floor`；单条 `funnel.json` 的 `detail` 可含 `explore_effect`、`ebh_required_e`、`e1`/`e2`、`relation`
- **结局表述**：A = ≥1 confirmed/discovered + 对照通过；A-弱 = BH/方向/时间过但 e-BH 或蕴含 `unknown`；B = 完整漏斗负结果（含探索功效分布）。泳道 D（diagnostic）不算发现

核对：

```bash
fe report <task> --run-id <EXP> --md --runs-dir "$FE_RUNS_DIR" > report.md
python skill/fe-report-generation/scripts/check_report_numbers.py report.md "$FE_RUNS_DIR/<EXP>"
```

**成功检查**：`verify_md` 无未匹配数字；`token_tiers.tokens_per_score_gain` 在纯发现场景为 `n/a`。

## 禁止

不得手改报告中的数字；不匹配时应重新生成。
