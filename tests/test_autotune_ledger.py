"""Ledger unit and engine integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from faultevolve.cloud.engine import EvolutionEngine, rebuild_run_report
from faultevolve.cloud.engine_autotune import ledger_record, ledger_would_block_full_eval
from faultevolve.cloud.llm import MockLLM
from faultevolve.cloud.store import Store
from faultevolve.config import EvolveConfig
from faultevolve.optimization.ledger import CostLedger, CostRecord, Reservation
from faultevolve.worker.runner import FakeAdapter, FakeTaskSpec


def test_l1_failed_settle_still_counts_tokens():
    ledger = CostLedger()
    res = ledger.reserve("repair", est_tokens=100)
    ledger.settle(
        res,
        CostRecord(
            seq=0,
            stage="repair",
            fidelity="none",
            node_id="n1",
            prompt_tokens=50,
            completion_tokens=30,
            status="failed",
        ),
    )
    t = ledger.totals()
    assert t.prompt_tokens == 50
    assert t.completion_tokens == 30


def test_l2_cache_hit_increments_cache_hits_not_eval():
    ledger = CostLedger()
    ledger.record(
        CostRecord(
            seq=0,
            stage="full_eval",
            fidelity="full_val",
            node_id="n",
            evaluator_calls=0,
            cache_hit=True,
        )
    )
    assert ledger.totals().evaluator_calls == 0
    assert ledger.totals().cache_hits == 1


def test_l3_outstanding_reservation_counts_toward_cap():
    ledger = CostLedger(full_eval_cap=2)
    ledger.record(
        CostRecord(
            seq=0,
            stage="full_eval",
            fidelity="full_val",
            node_id="a",
            evaluator_calls=1,
        )
    )
    ledger.reserve("full_eval", est_evaluator_calls=1)
    assert ledger.would_exceed(full_evals=1)


def _engine(tmp_path: Path, cfg: EvolveConfig) -> EvolutionEngine:
    adapter = FakeAdapter()
    store = Store(tmp_path / "fe.db")
    return EvolutionEngine(
        cfg,
        adapter,
        FakeTaskSpec(task_dir=tmp_path),
        store,
        MockLLM(enable_repair_scenario=False),
        mock=True,
    )


def test_l8_ledger_off_on_same_nodes(tmp_path):
    base = EvolveConfig()
    base.budget.max_iterations = 2
    base.operators.enabled = ["refine"]
    on = base.model_copy(deep=True)
    on.autotune.ledger.enabled = True
    off = base.model_copy(deep=True)
    paths = []
    for cfg in (off, on):
        eng = _engine(tmp_path / ("ledger_on" if cfg.autotune.ledger.enabled else "ledger_off"), cfg)
        eng.initialize()
        eng.run(2)
        nodes = {
            nid: (n.artifact.code, n.evidence.evaluation.combined_score if n.evidence.evaluation else 0)
            for nid, n in eng.tree.nodes.items()
        }
        paths.append(nodes)
    seq_off = sorted(paths[0].values())
    seq_on = sorted(paths[1].values())
    assert seq_off == seq_on


def test_l9_a_resumed_ledger_counts_the_rows_the_previous_process_wrote(tmp_path):
    """S7 ③: the full-eval cap is a promise about the run, not the process.

    A restart that rebuilt its ledger empty would hand the run a fresh cap over
    work it has already paid for, and a rebuilt summary would disagree with the
    live one about the same run.
    """
    cfg = EvolveConfig()
    cfg.budget.max_iterations = 2
    cfg.operators.enabled = ["refine"]
    cfg.autotune.ledger.enabled = True
    cfg.autotune.ledger.full_eval_cap = 2

    first = _engine(tmp_path, cfg)
    first.initialize()
    for _ in range(2):
        ledger_record(
            first, stage="full_eval", fidelity="full_val", node_id=None, evaluator_calls=1
        )
    experiment_id = first.experiment_id

    rebuilt = rebuild_run_report(
        Store(tmp_path / "fe.db", read_only=True), experiment_id, tmp_path / "rebuilt"
    )
    assert rebuilt["cost_ledger_totals"]["full_eval_calls"] == 2

    resumed = _engine(tmp_path, cfg)
    resumed.initialize(resume_id=experiment_id)
    assert resumed._cost_ledger.totals().full_eval_calls == 2
    assert ledger_would_block_full_eval(resumed) is True
