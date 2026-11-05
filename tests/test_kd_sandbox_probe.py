"""Acceptance probe for the discovery sandbox fix, run on the real shipped data.

`fe discover run --mock` cannot serve this purpose: MockLLM emits no parseable
claim, so the round proposes 0 claims and never reaches the sandbox. Injecting
claims through the raw_claim path of DiscoveryRound is the only way to exercise
the sandbox end to end without an API key.

judge_entailment is stubbed, so semantic novelty is deliberately not asserted.
Statistics, controls and grading all run for real.
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

# Cheap on purpose. bootstrap_b and the control repeats only widen or narrow the
# statistics; they cannot change whether a claim survives the sandbox, which is
# what this probe is about.
CFG = DiscoveryConfig(
    enabled=True,
    max_claims_per_round=4,
    bootstrap_b=50,
    neg_control_repeats=1,
    planted_strengths=[0.5],
    sandbox_timeout_s=180,
    tournament=TournamentConfig(),
)

READS_MODEL = """import pandas as pd

def feature(history):
    d = history.copy()
    d['v'] = d['model'].astype(str).str.len().astype(float)
    return d.groupby('serial_number')['v'].last()
"""

READS_CAPACITY = """import pandas as pd

def feature(history):
    d = history.copy()
    d['cap_tb'] = d['capacity_bytes'].astype(float) / 1e12
    return d.groupby('serial_number')['cap_tb'].last()
"""

RETURNS_DATAFRAME = """import pandas as pd

def feature(history):
    return history.groupby('serial_number')[['smart_5_raw']].last()
"""

# smart_195_raw is named in the train_labels half of HDD_DATA_SCHEMA and is
# genuinely absent from the history frame, so this must fail as a KeyError.
READS_ABSENT_COLUMN = """import pandas as pd

def feature(history):
    d = history.copy()
    d['x'] = d['smart_195_raw'].fillna(0).astype(float)
    return d.groupby('serial_number')['x'].last()
"""

CLAIMS = [
    ("reads model", READS_MODEL, True),
    ("reads capacity_bytes", READS_CAPACITY, True),
    ("returns dataframe", RETURNS_DATAFRAME, False),
    ("reads absent column", READS_ABSENT_COLUMN, False),
]


def _claim(title: str, feature_code: str) -> dict:
    return {
        "title": title,
        "condition": "all HDDs, grouped by serial_number",
        "feature_code": feature_code,
        "outcome": "label",
        "direction": "+",
        "scope": "hdd_mvp",
        "falsifier": "effect CI includes 0",
        "category": "feature_engineering",
        "tags": [],
    }


@pytest.mark.skipif(not HAS_DATA, reason="benchmark data not generated")
def test_discovery_round_on_real_data_reaches_statistics(tmp_path):
    spec = TaskSpec(
        task_dir=BENCH,
        problem_md=(BENCH / "problem.md").read_text(encoding="utf-8"),
        prompt_md=(BENCH / "prompt.md").read_text(encoding="utf-8"),
        init_code=(BENCH / "init.py").read_text(encoding="utf-8"),
        evaluator_path=BENCH / "evaluator.py",
    )

    # promote_claims appends to card_path, and knowledge/cards.jsonl is byte
    # protected, so the write target has to be a copy outside the repo tree.
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
        experiment_id="sandbox-probe",
        card_path=card_path,
        knowledge_dir=BENCH / "knowledge",
        llm_call=stub_llm,
        log_event=lambda name, payload: events.append((name, payload)),
        stats=stats,
    )
    candidates = [
        (f"node-{i}", "", code, None, "top_node", _claim(title, code))
        for i, (title, code, _) in enumerate(CLAIMS)
    ]

    result = rnd.run(round_idx=1, final=True, candidates=candidates)

    assert real_cards.read_bytes() == cards_before, "repo cards.jsonl was modified"
    assert result.skipped_reason == "", result.skipped_reason

    proposed = [p["claim_id"] for n, p in events if n == "claim_proposed"]
    ran = {p["claim_id"] for n, p in events if n == "claim_sandbox_finished"}
    died = {p["claim_id"]: p for n, p in events if n == "claim_sandbox_failed"}
    assert len(proposed) == len(CLAIMS)

    for cid, (title, _code, should_run) in zip(proposed, CLAIMS):
        if should_run:
            assert cid in ran, f"{title}: died in sandbox: {died.get(cid, {}).get('error')}"
        else:
            assert cid in died, f"{title}: expected to die in sandbox"

    # the claims that read the columns PR #17 added must reach the statistics
    assert stats.claims_tested == 2
    assert stats.claims_sandbox_failed == 2

    # no failure may be recorded as a bare exit code
    for cid, payload in died.items():
        err = (payload.get("error") or "").strip()
        assert err, f"{cid}: sandbox failure recorded with an empty error"
        assert not err.startswith("exit ") or "no stderr" in err, f"{cid}: bare {err!r}"
        assert payload.get("error_type"), f"{cid}: missing error_type"

    errors = {title: (died[proposed[i]].get("error") or "")
              for i, (title, _c, should_run) in enumerate(CLAIMS) if not should_run}

    df_err = errors["returns dataframe"]
    assert "DataFrame" in df_err and "Series" in df_err, df_err

    key_err = errors["reads absent column"]
    assert "KeyError" in key_err and "smart_195_raw" in key_err, key_err

    assert entail_calls, "judge_entailment was never reached"
    assert len(result.graded) == 2
    for payload in result.graded:
        assert {"n", "effect", "ci_low", "ci_high", "p", "e"} <= set(payload)


@pytest.mark.skipif(not HAS_DATA, reason="benchmark data not generated")
def test_discovery_frame_carries_every_promised_column():
    """The schema_note handed to the model must not promise absent columns."""
    import re

    spec = TaskSpec(
        task_dir=BENCH,
        problem_md=(BENCH / "problem.md").read_text(encoding="utf-8"),
        prompt_md=(BENCH / "prompt.md").read_text(encoding="utf-8"),
        init_code=(BENCH / "init.py").read_text(encoding="utf-8"),
        evaluator_path=BENCH / "evaluator.py",
    )
    frames = HDDAdapter().discovery_frames(spec)
    columns = set(frames.history.columns)

    named = set(re.findall(r"smart_\d+_(?:raw|normalized)", frames.schema_note))
    named |= {"model", "capacity_bytes"} & set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", frames.schema_note))
    assert named <= columns, f"schema_note promises absent columns: {sorted(named - columns)}"

    undocumented = columns - named - {"serial_number", "date"}
    assert not undocumented, f"columns missing from schema_note: {sorted(undocumented)}"
