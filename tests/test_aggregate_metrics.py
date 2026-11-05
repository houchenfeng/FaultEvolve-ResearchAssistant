"""Supplemental metrics preserve the frozen evaluator's quality and inputs."""

from pathlib import Path
import importlib.util

import pandas as pd
import pytest

from faultevolve.worker.aggregate_metrics import add_aggregate_metrics


def test_exact_weighted_and_unweighted_accuracy_preserve_original_score():
    path = Path(__file__).resolve().parents[1] / "benchmark/hdd_mvp/evaluator.py"
    spec = importlib.util.spec_from_file_location("aggregate_test_evaluator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    labels = pd.DataFrame({"serial_number": ["a", "b", "c", "d"],
                           "label": [1, 1, 0, 0], "weight": [1., 1., 10., 20.]})
    predictions = pd.DataFrame({"serial_number": ["d", "b", "a", "c"],
                                "score": [.1, .3, .9, .8], "alarm": [0, 0, 1, 1]})
    score, before = module.score_predictions(predictions, labels)
    add_aggregate_metrics(module)
    add_aggregate_metrics(module)
    after_score, after = module.score_predictions(predictions, labels)
    assert score == after_score
    assert {key: after[key] for key in before} == before
    assert after["accuracy"] == pytest.approx(21 / 32)
    assert after["unweighted_accuracy"] == .5
    assert [after[key] for key in ("true_positives", "false_positives", "false_negatives", "true_negatives")] == [1, 10, 1, 20]
    assert after["sample_count"] == 4
    assert "serial_number" not in after
