# AGENTS.md

This repo is FaultEvolve, a competition project: an LLM-agent system that evolves device
failure-prediction algorithms (Baidu Famou-style), delivered as Agent Skills.

## Read first (in order)

1. `docs/dev/MVP开发指南.md` — implementation contract for the MVP (authoritative)
2. `docs/design/02-MVP方案-硬盘.md` — scope and acceptance criteria
3. `docs/design/01-系统总体设计.md` — full system design and rationale
4. `benchmark/hdd_mvp/problem.md` — the benchmark task

## Hard rules

- Do not modify `benchmark/hdd_mvp/{evaluator.py,init.py,problem.md,prompt.md}` or `benchmark/hdd_mvp/data/`.
  They are the shared baseline for the Famou comparison.
- Never read, print, or upload `benchmark/hdd_mvp/data/holdout*` (private test set).
- Secrets come only from environment variables (`DASHSCOPE_API_KEY`, `TYPESAFE_API_KEY`, `FE_API_KEY`);
  never write them into code, config, tests, logs, or commits.
- Scores come only from the local evaluator; LLM/Jev outputs never become a node's score.

## Commands

```bash
pip install -r requirements.txt
python -m pytest tests/
cd benchmark/hdd_mvp && python evaluator.py init.py      # val ROS ≈ 22.81
```

Write docs and user-facing text in Simplified Chinese; code identifiers and comments in English.
