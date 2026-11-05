"""Offline replay of a full discovery round against the real shipped hdd_mvp data.

`tests/test_kd_sandbox_probe.py` proves the sandbox fix with four claims. This one
replays the six-claim round whose numbers the README cites, so that those numbers
are reproducible instead of being a one-off local run.

No API key is needed: claims are injected through the raw_claim slot of
DiscoveryRound, which bypasses LLM claim generation. judge_entailment is the only
stubbed piece, so semantic novelty is deliberately not asserted; frames, sandbox,
statistics, negative and planted controls, grading and promotion all run for real.

experiment_id and round_idx are load-bearing: the control seeds are derived from
them via sha256, so changing either changes the control outcomes.

Slow on purpose -- about 85s, dominated by the planted controls at three
strengths. Skipped when the benchmark data is not generated.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from faultevolve.cloud.store import Store
from faultevolve.config import DiscoveryConfig, TournamentConfig
from faultevolve.discovery.pipeline import DiscoveryRound
from faultevolve.discovery.schemas import DiscoveryStats
from faultevolve.tasks.hdd_adapter import HDDAdapter
from faultevolve.tasks.protocol import TaskSpec

BENCH = Path(__file__).resolve().parents[1] / "benchmark" / "hdd_mvp"
HAS_DATA = (BENCH / "data" / "public" / "train_history.csv.gz").exists()

EXPERIMENT_ID = "offline-replay"
ROUND_IDX = 1

CFG = DiscoveryConfig(
    enabled=True,
    max_claims_per_round=8,
    bootstrap_b=50,
    neg_control_repeats=5,
    sandbox_timeout_s=180,
    tournament=TournamentConfig(),
)

CODE_VENDOR = """import pandas as pd

def feature(history):
    d = history.copy()
    vendor = d['model'].astype(str).str.split().str[0]
    code = vendor.map({'ST': 1.0, 'WDC': 2.0, 'HGST': 3.0, 'TOSHIBA': 4.0}).fillna(0.0)
    d['v'] = code
    return d.groupby('serial_number')['v'].last()
"""

CODE_CAPACITY = """import pandas as pd

def feature(history):
    d = history.copy()
    d['cap_tb'] = d['capacity_bytes'].astype(float) / 1e12
    return d.groupby('serial_number')['cap_tb'].last()
"""

CODE_MODEL_X_SMART = """import pandas as pd

def feature(history):
    d = history.copy()
    is_wdc = d['model'].astype(str).str.contains('WDC|HGST', regex=True).astype(float)
    load = d['smart_193_raw'].fillna(0).astype(float)
    d['inter'] = is_wdc * load
    return d.groupby('serial_number')['inter'].max()
"""

CODE_PLAIN_SMART = """import pandas as pd

def feature(history):
    d = history.copy()
    d['r'] = d['smart_5_raw'].fillna(0).astype(float)
    return d.groupby('serial_number')['r'].last()
"""

CODE_RETURNS_DATAFRAME = """import pandas as pd

def feature(history):
    return history.groupby('serial_number')[['smart_5_raw']].last()
"""

# smart_195_raw appears in the train_labels half of HDD_DATA_SCHEMA and is
# genuinely absent from the history frame.
CODE_READS_ABSENT_COLUMN = """import pandas as pd

def feature(history):
    d = history.copy()
    d['x'] = d['smart_195_raw'].fillna(0).astype(float)
    return d.groupby('serial_number')['x'].last()
"""


def _claim(title: str, condition: str, feature_code: str, falsifier: str) -> dict:
    return {
        "title": title,
        "condition": condition,
        "feature_code": feature_code,
        "outcome": "label",
        "direction": "+",
        "scope": "hdd_mvp val split",
        "falsifier": falsifier,
        "category": "feature_engineering",
        "tags": ["offline_replay"],
    }


# (title, condition, code, should_survive_sandbox, falsifier)
# Every field except title lands in prereg_hash, so these strings are part of the
# recorded experiment: editing one changes the bootstrap seed and can move a
# borderline claim's grade.
CLAIMS = [
    ("Vendor identity flags an at-risk population",
     "all HDDs, grouped by serial_number", CODE_VENDOR, True,
     "effect CI includes 0 after BH correction"),
    ("Larger nominal capacity correlates with failure",
     "all HDDs", CODE_CAPACITY, True,
     "effect CI includes 0"),
    ("Load-cycle pressure only bites WDC/HGST mechanics",
     "all HDDs", CODE_MODEL_X_SMART, True,
     "interaction effect CI includes 0"),
    ("Reallocated sector count predicts failure",
     "all HDDs", CODE_PLAIN_SMART, True,
     "effect CI includes 0"),
    ("DELIBERATE BAD CLAIM: returns a DataFrame",
     "all HDDs", CODE_RETURNS_DATAFRAME, False,
     "n/a - expected to die in sandbox with a type error"),
    ("DELIBERATE BAD CLAIM: reads a column history does not have",
     "all HDDs", CODE_READS_ABSENT_COLUMN, False,
     "n/a - expected to die in sandbox with a KeyError"),
]

# Claim order is stable, so the graded claims are these four ids in this order.
TESTED_IDS = [f"C-{EXPERIMENT_ID}-{i:04d}" for i in range(1, 5)]

EXPECTED_GRADES = {
    TESTED_IDS[0]: "refuted",
    TESTED_IDS[1]: "refuted",
    TESTED_IDS[2]: "refuted",
    TESTED_IDS[3]: "undetermined",
}


@pytest.mark.skipif(not HAS_DATA, reason="benchmark data not generated")
def test_offline_replay_round_is_reproducible(tmp_path):
    spec = TaskSpec(
        task_dir=BENCH,
        problem_md=(BENCH / "problem.md").read_text(encoding="utf-8"),
        prompt_md=(BENCH / "prompt.md").read_text(encoding="utf-8"),
        init_code=(BENCH / "init.py").read_text(encoding="utf-8"),
        evaluator_path=BENCH / "evaluator.py",
    )

    # promote_claims appends to card_path and refuses any path named cards.jsonl,
    # so the write target is a copy outside the repo tree.
    real_cards = BENCH / "knowledge" / "cards.jsonl"
    cards_before = real_cards.read_bytes()
    card_path = tmp_path / "discovered_cards.jsonl"
    shutil.copyfile(real_cards, card_path)

    events: list[tuple[str, dict]] = []
    entail_calls: list[int] = []

    def stub_llm(_messages):
        entail_calls.append(1)
        return '{"card_id": null, "relation": "none"}'

    stats = DiscoveryStats()
    rnd = DiscoveryRound(
        cfg=CFG,
        store=Store(tmp_path / "fe.db"),
        adapter=HDDAdapter(),
        task_spec=spec,
        experiment_id=EXPERIMENT_ID,
        card_path=card_path,
        knowledge_dir=BENCH / "knowledge",
        llm_call=stub_llm,
        log_event=lambda name, payload: events.append((name, payload)),
        stats=stats,
    )
    candidates = [
        (f"node-{i}", "", code, None, "top_node", _claim(title, condition, code, falsifier))
        for i, (title, condition, code, _run, falsifier) in enumerate(CLAIMS)
    ]

    result = rnd.run(round_idx=ROUND_IDX, final=True, candidates=candidates)

    assert real_cards.read_bytes() == cards_before, "repo cards.jsonl was modified"
    assert result.skipped_reason == "", result.skipped_reason

    # ---- sandbox verdicts -----------------------------------------------------------
    proposed = [p["claim_id"] for n, p in events if n == "claim_proposed"]
    ran = {p["claim_id"] for n, p in events if n == "claim_sandbox_finished"}
    died = {p["claim_id"]: p for n, p in events if n == "claim_sandbox_failed"}

    assert len(proposed) == len(CLAIMS)
    assert stats.claims_proposed == 6
    assert stats.claims_sandbox_failed == 2
    assert stats.claims_tested == 4, "Run B reported 0 claims tested"

    for cid, (title, _cond, _code, should_run, _f) in zip(proposed, CLAIMS):
        if should_run:
            assert cid in ran, f"{title}: died in sandbox: {died.get(cid, {}).get('error')}"
        else:
            assert cid in died, f"{title}: expected to die in sandbox"

    for cid, payload in died.items():
        err = (payload.get("error") or "").strip()
        assert err, f"{cid}: sandbox failure recorded with an empty error"
        assert not err.startswith("exit ") or "no stderr" in err, f"{cid}: bare {err!r}"
        assert payload.get("error_type"), f"{cid}: missing error_type"

    bad = {proposed[i]: died[proposed[i]]["error"]
           for i, (_t, _cond, _c, should_run, _f) in enumerate(CLAIMS) if not should_run}
    df_err = bad[proposed[4]]
    key_err = bad[proposed[5]]
    assert "DataFrame" in df_err and "Series" in df_err, df_err
    assert "KeyError" in key_err and "smart_195_raw" in key_err, key_err

    # ---- controls -------------------------------------------------------------------
    controls = result.controls
    assert controls is not None, "controls never ran"
    assert controls.passed, f"negative control false-positive rate {controls.neg_fpr}"
    assert controls.neg_trials == 20
    assert controls.neg_fpr <= CFG.max_neg_control_fpr
    assert set(controls.planted) == {"0.2", "0.5", "1.0"}
    for strength, report in controls.planted.items():
        assert report["recovered"] == report["trials"], (
            f"planted signal at strength {strength} was not recovered: {report}"
        )

    # ---- grading --------------------------------------------------------------------
    grades = {p["claim_id"]: p["grade"] for n, p in events if n == "claim_graded"}
    assert grades == EXPECTED_GRADES, grades
    assert entail_calls, "judge_entailment was never reached"
    assert len(result.graded) == 4

    by_id = dict(zip([p["claim_id"] for n, p in events if n == "claim_tested"], result.graded))
    for cid, payload in by_id.items():
        assert {"n", "n_pos", "effect", "ci_low", "ci_high", "p", "e",
                "rho_max_abs", "incr_gain", "incr_ci_low"} <= set(payload), cid

    # The two substantive findings the README reports.
    capacity = by_id[TESTED_IDS[1]]
    assert capacity["effect"] < 0, capacity
    assert capacity["ci_high"] < 0, f"capacity effect CI should not straddle 0: {capacity}"

    plain_smart = by_id[TESTED_IDS[3]]
    assert plain_smart["rho_max_abs"] == pytest.approx(1.0), (
        "smart_5_raw is itself a K0 baseline column, so it must be functionally "
        f"redundant: {plain_smart}"
    )

    # No claim was confirmed or discovered, so nothing may be promoted and KD2 is
    # still untriggered on real data.
    assert result.promoted_ids == []
