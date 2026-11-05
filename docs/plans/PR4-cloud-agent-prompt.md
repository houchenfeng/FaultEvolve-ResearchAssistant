# Cloud-agent prompt — FaultEvolve PR #4: Jev fast judgment (pre-screening + UCT prior)

You are working in the private repo `houchenfeng/Self-evolution-optimization-agnet` (FaultEvolve: a Qwen-driven system that evolves HDD failure-prediction programs with a UCT hypothesis tree, 3-layer reflection, a repair operator (PR #2), and knowledge-card injection (PR #3)).

## 0. Branch / base
- Branch from the **latest `origin/main` at launch time** (`git fetch origin && git checkout -b cursor/jev-screening origin/main`). PR #3 (`cursor/knowledge-injection-c879`) will probably already be merged; if it is not, still base on main — the hook points below exist on both. Do not base on the PR #3 branch.
- Read first: `AGENTS.md`, `docs/dev/MVP开发指南.md` (judge section), `src/faultevolve/cloud/{judge.py,engine.py,selection.py,tree.py}`, `src/faultevolve/config.py`, `src/faultevolve/common/{metering.py,schemas.py}`, `src/faultevolve/cli.py`, `skill/fe-evolve-manager/SKILL.md`, `tests/test_engine.py`, `src/faultevolve/worker/runner.py` (FakeAdapter).

## 1. Hard rules
- Do NOT modify `benchmark/hdd_mvp/evaluator.py`, `benchmark/hdd_mvp/init.py`, `benchmark/hdd_mvp/problem.md`, `benchmark/hdd_mvp/prompt.md`, or anything under `benchmark/hdd_mvp/data/`. Never read `data/holdout*`.
- Secrets only from env vars (`MIYANG_API_KEY`, `DASHSCOPE_API_KEY`, ...). Never write keys into code, config, tests, logs, events, exceptions, or commits. Tests use a fake key via `monkeypatch.setenv`.
- Jev output never becomes a node's score. It only decides whether/when to evaluate and which node to explore.
- Keep the engine task-agnostic: no HDD/SMART strings in `cloud/engine.py`, `cloud/judge.py`, `cloud/jev_client.py`, `cloud/selection.py`. Domain text comes only from `task_spec` and `task_adapter.constraints()`.
- All existing tests must keep passing. Do not add new runtime dependencies; use `httpx` (already a dependency) and `httpx.MockTransport` for HTTP mocking (`respx` is NOT in requirements.txt).
- Docs, SKILL.md and PR description in Simplified Chinese; identifiers/comments in English.

## 2. Current state (verified)
- `cloud/judge.py`: `JudgeClient` methods (`node_prior`, `operator_choice`, `prescreen`, `insight_applicability`, `should_continue`, `record_outcome`, `get_trust`) are stubs returning uniform/defaults; also `PrescreenResult`, `compute_expected_gain`, `should_defer_candidate`.
- `cloud/engine.py`: `EvolutionEngine.initialize()` creates `self.judge = JudgeClient(self.config)` but nothing calls it. `_run_one_iteration()` does: select → build `OperatorContext` → `self.operator.generate_with_adoption(ctx)` → `self.task_adapter.static_check(...)` → `create_child_node(...)` + `self.tree.add_node(child)` → `self.task_adapter.evaluate(code, self.task_spec)` → `self.metrics.add_eval(...)` → reflection / repair. `run()` builds `RunSummary`; `run_local_evolution()` writes `run_summary.json`, `tree.json`, `events.jsonl`, `programs/`.
- `cloud/selection.py`: `UCTSelector._get_prior()` uniform; expand prior `1/(n+1)` in `select()`; `get_jev_prior()` and `compute_tau_weighted_prior()` exist but unused.
- `config.py` `JudgeConfig`: `provider, model, base_url, api_key_env, prescreen, warmup, audit_rate, calibration_window, initial_trust, timeout_s`. `evolve.yaml`: `judge.provider: none`, `selection.policy: uct  # "jev_puct" for Jev-guided selection`.
- `common/metering.py` `RunMetrics.add_llm_call(metrics, purpose)` tracks `generate/reflect/repair` tokens; `to_dict()`.
- `cloud/tree.py` `get_regular_children_count()` excludes only repair and INVALID children. Nodes are persisted column-wise via `store.update_node(...)` — do NOT add fields to `Node` (would need a DB migration); persist Jev data in events.

## 3. Relay API (MiYang)
`POST https://miyang.cn/api/v1/decisions`, header `Authorization: Bearer $MIYANG_API_KEY`, model `miyang/jev-1.13`.
Body: `{"model": ..., "state": "<text>", "questions": [...]}`. Question types: `choice` (options), `score`, `noul` (requires `"criteria": {"true": "...", "false": "..."}`).
Response: `answers[<name>].probabilities` (choice) / `.noul` / `.score`, plus `usage`. Parse defensively: `noul` may be a number or a dict like `{"true": p, "false": q}`; `score` may be 0–1, 0–10 or 0–100 (normalize to 0–1); `usage` may use `prompt_tokens/completion_tokens/total_tokens` or `input_tokens/output_tokens` (missing → 0).

## 4. What to build

### 4.1 Config (extend `JudgeConfig`, all with defaults; old yaml must still load)
```yaml
judge:
  provider: none            # none | jev | mock
  base_url: https://miyang.cn/api/v1/decisions
  api_key_env: MIYANG_API_KEY
  model: miyang/jev-1.13
  timeout_s: 5.0
  prescreen: false
  invalid_threshold: 0.85
  low_value_threshold: 0.15
  low_value_action: skip    # skip | defer
  defer_flush_evals: 0
  warmup: 10
  audit_rate: 0.1
  prior: true               # effective only with selection.policy: jev_puct
  prior_tau: 0.5
  max_calls: 500
  max_consecutive_errors: 3
  max_state_chars: 6000
  retries: 0
```
In `benchmark/hdd_mvp/evolve.yaml` keep `provider: none` (default behavior unchanged) and add the MiYang values plus the new keys as comments/documented defaults. `provider: none` must produce zero HTTP requests and behavior identical to before.

### 4.2 `src/faultevolve/cloud/jev_client.py` (new)
- `JevClient(cfg: JudgeConfig, transport: httpx.BaseTransport | None = None)` with `decide(state: str, questions: list[dict]) -> JevResponse`; `httpx.Client(timeout=cfg.timeout_s, transport=transport)`; bearer from `os.environ[cfg.api_key_env]`; optional retries only on 429/5xx.
- `JevResponse(answers, prompt_tokens, completion_tokens, total_tokens, latency_ms)`.
- `JevError` for any failure (timeout, non-2xx, bad JSON, missing fields, missing key). Error messages must not contain the key.
- `MockJevClient`: same interface, deterministic from `sha256(state/code)`: roughly 1/3 of candidates get high `p_invalid` or low `p_improve`; returns non-zero usage (e.g. `len(state)//4` prompt, 20 completion).

### 4.3 Questions (one call per candidate, generic wording)
1. `valid` (noul), criteria `{"true": "该候选程序能在任务约束内正常运行并产出合法输出", "false": "该候选程序会报错、违反约束或超时"}` → `p_invalid = 1 - p_true`.
2. `improve` (choice, options `["better","same","worse"]`) → `p_improve = probabilities["better"]`.
3. `value` (score, expected value 0–1) → cached as the node's prior value.
State = truncated concat of `task_spec.problem_md` summary, `task_adapter.constraints(task_spec)`, parent intent/hypothesis/score, candidate intent/hypothesis, `difflib.unified_diff(parent_code, code)`; cap at `max_state_chars`.

### 4.4 `cloud/judge.py` (replace stubs, keep signatures)
- `JudgeClient(config, client=None)`: provider `none` → disabled; `jev` → `JevClient`; `mock` → `MockJevClient`. Missing key with `jev` → warn once, disable, `jev_disabled_reason="missing_key"`, run continues.
- `prescreen(...) -> PrescreenResult` extended with `ok, p_invalid, p_improve, value, prompt_tokens, completion_tokens, latency_ms, decision, error`. Any `JevError` → `ok=False`, default (evaluate). Circuit breaker after `max_consecutive_errors` (`circuit_open`), and `max_calls` cap (`max_calls`).
- Decision logic (rewrite `should_defer_candidate`): during warmup → `evaluate` (but flag `would_screen` for shadow stats); `p_invalid >= invalid_threshold` → `skip_invalid`; `p_improve < low_value_threshold` → `skip_low_value` or `defer` per `low_value_action`; else `evaluate`.
- `record_outcome()` stores audit/shadow outcomes; `get_trust()` may scale `prior_tau` by observed precision (optional).

### 4.5 Hook (a) — pre-screen in `EvolutionEngine._run_one_iteration()`
Insert after `static_check` passes and before `create_child_node(...)`/`self.task_adapter.evaluate(...)`:
1. Call `self.judge.prescreen(...)` only if enabled and `judge.prescreen` true. Meter it (`metrics.add_llm_call(CallMetrics(...), "jev")` + jev counters), store an `LLMCall` with purpose `jev_prescreen`, log event `jev_prescreen` with `{node_id, parent_id, p_invalid, p_improve, value, decision, ok}` (no state text, no key).
2. `ok=False` or `evaluate` → unchanged flow (count `jev_fail_open` when `ok=False`).
3. Screened (`candidates_screened += 1`): with seeded `random.Random(config.seed)` draw vs `audit_rate`. Audit → evaluate normally, then bad := `not is_valid or delta <= noise_delta` (use `task_adapter.get_noise_delta`), update `screen_audited/screen_audit_bad`. Not audited → add child node, set `NodeStatus.ABANDONED`, log `jev_screened`, `evaluations_saved += 1`, `iterations_done += 1`, do NOT call `add_eval`; if `defer`, push `(value, child_id, code)` into `self._deferred`.
4. Warmup `would_screen` candidates are evaluated anyway and counted as shadow samples (`screen_shadow`, and into audited/bad for precision).
5. After the main loop in `run()`: if `defer_flush_evals > 0` and budgets allow, evaluate up to that many deferred candidates by descending value (reuse the evaluation+reflection path; decrement `evaluations_saved`).
6. Do not pre-screen repair candidates in `_attempt_repair`.
7. `Tree.get_regular_children_count()` must also exclude `NodeStatus.ABANDONED`.
8. Allow injecting a judge: `EvolutionEngine.__init__(..., judge: JudgeClient | None = None)`; `initialize()` only creates one if none was injected.

### 4.6 Hook (b) — prior in `UCTSelector`
- Engine keeps `self._jev_values: dict[str, float]` from prescreen `value` (fallback `p_improve`) — no extra Jev calls. Rebuild from `jev_prescreen` events (`store.get_events`) on resume.
- Add `UCTSelector.set_node_priors(values, tau, enabled)`. In `select()`, compute priors for all options of a parent together (children + "expand"): normalize available values into a distribution (children without value and "expand" get the mean), then `compute_tau_weighted_prior(jev, uniform, tau)`; must sum to 1. Enabled only if `selection.policy == "jev_puct"` and judge enabled and `judge.prior`. Otherwise priors must remain exactly uniform.
- Make `get_jev_prior()` delegate to the same logic (keep signature).

### 4.7 Metrics → `RunMetrics.to_dict()`, `RunSummary`, `run_summary.json`
Add (0/null when disabled): `jev_calls, jev_errors, jev_fail_open, jev_prompt_tokens, jev_completion_tokens, jev_tokens, jev_latency_ms, jev_disabled_reason, candidates_screened, evaluations_saved, eval_time_saved_est_s, screen_audited, screen_audit_bad, screen_shadow, screening_precision (= screen_audit_bad/screen_audited, null if 0), jev_prior_active`. `jev_tokens` sits alongside `generate_tokens/reflect_tokens/repair_tokens/knowledge_tokens` and is included in `total_tokens`. Also log them in the `run_finished` event.

### 4.8 CLI
- `fe judge ping [--task-dir DIR] [--env-file PATH] [--json]`: load judge config from `DIR/evolve.yaml` (force provider jev), send one small request, print ok/latency_ms/tokens/answer keys; exit 0 on success, 1 otherwise; never print the key.
- `.env.example`: add `MIYANG_API_KEY=` with a Chinese comment (optional Jev relay).

### 4.9 Skills (must be usable by a fully autonomous agent such as Codex, no human)
- NEW `skill/fe-jev-screening/`:
  - `SKILL.md` (Chinese, front-matter `name`/`description`) with sections: **何时使用 / 输入**（`.env`: `MIYANG_API_KEY`, `DASHSCOPE_API_KEY`; the full `judge` config table）/ **执行命令**（exact commands: `fe doctor --task-dir benchmark/hdd_mvp --env-file .env`, `fe judge ping ...`, offline `bash skill/fe-jev-screening/scripts/run_mock_jev.sh`, real run with prescreen enabled via a copied evolve.yaml）/ **成功检查**（exact python/json assertions on run_summary）/ **故障处理**（401 → check key; 429/timeout → fail-open is automatic, raise `timeout_s` or lower concurrency; `jev_disabled_reason=circuit_open`; `screening_precision < 0.6` → raise `invalid_threshold`, lower `low_value_threshold`, or set `prescreen: false`; missing key → runs without Jev）/ **禁止操作**.
  - `scripts/run_mock_jev.sh` (see §6), `scripts/check_jev_summary.py`, `references/judge-config.md`.
- UPDATE `skill/fe-evolve-manager/SKILL.md`: env vars (MIYANG_API_KEY), judge config example switched to the MiYang relay, run_summary field list with jev fields, Jev failure-handling entry, link to the new skill.
- Update the judge section of `docs/dev/MVP开发指南.md` (Chinese).

## 5. Tests — new `tests/test_jev_screening.py` (no network, fake key only)
Use `httpx.MockTransport` for `JevClient` and `MockJevClient`/scripted fake clients for engine tests with `FakeAdapter`/`FakeTaskSpec`/`MockLLM` (pattern from `tests/test_engine.py`). Cover:
1. Request: URL, `Authorization: Bearer test-key`, body has model/state/questions; noul has `criteria.true/false`.
2. Parsing: probabilities/noul/score (several shapes and scales), usage variants, missing usage.
3. Fail-open: timeout, HTTP 500, invalid JSON, missing key → all candidates evaluated, `jev_errors>0`, `evaluations_saved==0`, status finished.
4. Circuit breaker: after 3 consecutive errors, transport call count stops increasing.
5. Skip: high p_invalid → fewer `FakeAdapter.evaluate` calls, `iterations_done` equals max, screened nodes ABANDONED with no score, not counted for widening.
6. Audit precision: `audit_rate=1.0` + scripted results → exact `screening_precision`.
7. Warmup: no skips in first N; shadow samples counted.
8. Defer + flush with `defer_flush_evals=1`.
9. Prior: `jev_puct` → non-uniform sibling priors summing to 1; `uct`/`provider none` → exactly uniform; rebuilt after resume.
10. Default-off regression: `provider: none` → zero transport calls; jev fields all 0.
11. End-to-end `run_local_evolution` on a tmp task with `provider: mock` → `run_summary.json` has all new fields, non-zero jev_calls/jev_tokens.
12. Config: old yaml loads; new keys parse.
13. Security: fake key string absent from `events.jsonl` and captured logs; no HDD-specific strings in engine/judge/jev_client/selection sources.

## 6. Offline mock verification (must be implemented as `skill/fe-jev-screening/scripts/run_mock_jev.sh`)
The script must: create a temp dir; copy `tests/fixtures/toy_task/*` into it (fast deterministic evaluator, no real data); write an `evolve.yaml` there with
```yaml
selection: {policy: jev_puct}
judge: {provider: mock, prescreen: true, warmup: 2, audit_rate: 0.5, low_value_action: skip, prior: true}
```
then run
```bash
fe evolve local "$TMP/task" --mock --iterations 12 --runs-dir "$TMP/runs" --json
python skill/fe-jev-screening/scripts/check_jev_summary.py "$TMP/runs"
```
`check_jev_summary.py` finds the newest `*/run_summary.json` and asserts `status=="finished"`, `jev_calls>0`, `jev_tokens>0`, `candidates_screened>0`, `evaluations_saved>0`, `screening_precision is not None`, `jev_prior_active is True`; prints the values; exits non-zero on failure. If the toy task does not run through the default `HDDAdapter` path, fix the script (e.g., build a minimal temp task) — never edit `benchmark/hdd_mvp` protected files. Tune `MockJevClient` so this passes deterministically with `--seed 20260926`.

## 7. Acceptance checks (run all, paste outputs in the PR description)
```bash
pip install -r requirements.txt && pip install -e ".[dev]"
python -m pytest tests/ -q                                   # all green, incl. all pre-existing tests
bash skill/fe-jev-screening/scripts/run_mock_jev.sh          # exit 0, prints non-zero jev metrics
fe evolve local benchmark/hdd_mvp --mock --iterations 3 --json   # default provider none: still works, jev fields 0
git diff --stat origin/main -- benchmark/hdd_mvp/evaluator.py benchmark/hdd_mvp/init.py benchmark/hdd_mvp/problem.md benchmark/hdd_mvp/prompt.md benchmark/hdd_mvp/data   # must be empty
grep -rnE "smart_|SMART|硬盘|HDD" src/faultevolve/cloud/engine.py src/faultevolve/cloud/judge.py src/faultevolve/cloud/jev_client.py src/faultevolve/cloud/selection.py   # must be empty
```
Do not call the real relay in CI or tests. (If `MIYANG_API_KEY` happens to be present in your environment you may run `fe judge ping --task-dir benchmark/hdd_mvp --json` once and report only ok/latency/tokens — never the key.)

## 8. PR
- Title: `PR4: Jev 快速判断——候选预筛与 UCT 扩展先验（可选、fail-open、全计量）`
- Description in Simplified Chinese: 目标、设计要点（钩子位置：`EvolutionEngine._run_one_iteration` 预筛、`UCTSelector.select` 先验）、配置项表、fail-open 行为、新增 run_summary 字段、测试列表、验收命令输出，以及明确列出 **技能变更：新增 `skill/fe-jev-screening`；更新 `skill/fe-evolve-manager`**。
- Keep commits focused; do not force-push over others' work; open the PR against `main`.
