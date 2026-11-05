"""Discovery statistics must follow from the preregistration, not the interpreter.

A claim's bootstrap CI, permutation p-value and e-value decide whether it is
refuted or confirmed, so they have to be a function of the preregistered content
alone. They are seeded per claim; if that seed comes from Python's ``hash()`` it
silently varies with PYTHONHASHSEED and the same preregistration yields a
different verdict on a different run.

The check therefore runs one round in two interpreters with different
PYTHONHASHSEED values and compares the numbers, rather than inspecting how the
seed is built.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from faultevolve.discovery.seed_util import seed_from

# Runs in a child interpreter because PYTHONHASHSEED is read at startup only.
# FakeAdapter.discovery_frames fixes its own data seed, so the synthetic frame is
# identical in both children and only the claim statistics can differ.
_CHILD = '''
import json
import tempfile
from pathlib import Path

from faultevolve.cloud.store import Store
from faultevolve.config import DiscoveryConfig, TournamentConfig
from faultevolve.discovery.pipeline import DiscoveryRound
from faultevolve.discovery.schemas import DiscoveryStats
from faultevolve.worker.runner import FakeAdapter

FEATURE = """import pandas as pd

def feature(history):
    d = history.copy()
    d["v"] = d["m1"] * 0.35 + d["m0"]
    return d.groupby("unit")["v"].mean()
"""

CLAIM = {
    "title": "m1 blended with m0 predicts failure",
    "condition": "toy units",
    "feature_code": FEATURE,
    "outcome": "label",
    "direction": "+",
    "scope": "synthetic",
    "falsifier": "effect CI includes 0",
    "category": "feature_engineering",
    "tags": [],
}

tmp = Path(tempfile.mkdtemp(prefix="fe_seedcheck_"))
task = tmp / "task"
(task / "knowledge").mkdir(parents=True)
(task / "init.py").write_text("# init\\n", encoding="utf-8")
(task / "problem.md").write_text("# p", encoding="utf-8")
(task / "prompt.md").write_text("# prompt", encoding="utf-8")
(task / "evaluator.py").write_text("def evaluate(p, **kw):\\n    return {}\\n", encoding="utf-8")
(task / "knowledge" / "cards.jsonl").write_text("", encoding="utf-8")

events = []
adapter = FakeAdapter()
result = DiscoveryRound(
    cfg=DiscoveryConfig(
        enabled=True,
        max_claims_per_round=2,
        bootstrap_b=80,
        neg_control_repeats=1,
        planted_strengths=[0.5],
        sandbox_timeout_s=60,
        tournament=TournamentConfig(),
    ),
    store=Store(tmp / "fe.db"),
    adapter=adapter,
    task_spec=adapter.load_task(task),
    experiment_id="seedcheck",
    card_path=tmp / "discovered_cards.jsonl",
    knowledge_dir=task / "knowledge",
    llm_call=lambda _m: json.dumps({"card_id": None, "relation": "none"}),
    log_event=lambda name, payload: events.append((name, payload)),
    stats=DiscoveryStats(),
).run(round_idx=1, final=True, candidates=[("n0", "", FEATURE, None, "top_node", CLAIM)])

assert result.skipped_reason == "", f"round skipped: {result.skipped_reason}"

grades = {p["claim_id"]: p["grade"] for n, p in events if n == "claim_graded"}
tested = [p["claim_id"] for n, p in events if n == "claim_tested"]
fields = ("n", "n_pos", "effect", "ci_low", "ci_high", "p", "e",
          "rho_max_abs", "incr_gain", "incr_ci_low", "incr_ci_high")
rows = [{**{k: g.get(k) for k in fields}, "grade": grades.get(cid)}
        for cid, g in zip(tested, result.graded)]
print("RESULT " + json.dumps(rows, sort_keys=True))
'''

_FIELDS = ("ci_low", "ci_high", "p", "e", "incr_ci_low")


def _run_round(script: Path, pythonhashseed: str) -> list[dict]:
    env = {**os.environ, "PYTHONHASHSEED": pythonhashseed}
    env.pop("PYTHONPATH", None)
    proc = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(script.parent),
        timeout=600,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    markers = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
    assert markers, f"child printed no result:\n{proc.stdout[-2000:]}"
    rows = json.loads(markers[-1][len("RESULT "):])
    assert rows, "the claim never reached the statistics stage"
    return rows


def test_claim_statistics_do_not_depend_on_pythonhashseed(tmp_path):
    script = tmp_path / "child.py"
    script.write_text(_CHILD, encoding="utf-8")

    first = _run_round(script, "0")
    second = _run_round(script, "1")

    assert first == second, (
        "the same preregistration produced different statistics under two "
        f"PYTHONHASHSEED values:\n  seed=0: {first}\n  seed=1: {second}"
    )
    # guard against a vacuous pass where nothing was actually measured
    for row in first:
        assert row["grade"], "claim was not graded"
        assert all(row[f] is not None for f in _FIELDS), row


def test_seed_from_is_stable_and_claim_scoped():
    """The seed must be a pure function of the preregistration content."""
    prereg = "a" * 64
    assert seed_from("claim_stats", prereg) == seed_from("claim_stats", prereg)
    assert seed_from("claim_stats", prereg) != seed_from("claim_stats", "b" * 64)
    assert 0 <= seed_from("claim_stats", prereg) < 2**32
