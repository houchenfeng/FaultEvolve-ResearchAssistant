import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BENCH = Path(__file__).resolve().parents[1] / "benchmark" / "hdd_mvp"
sys.path.insert(0, str(BENCH))

import evaluator as ev  # noqa: E402

HAS_DATA = (BENCH / "data" / "eval_only" / "val_labels.csv").exists()


def test_weighted_auprc_perfect_and_random():
    y = np.array([1, 0, 0, 1, 0])
    w = np.ones(5)
    assert ev.weighted_auprc(y, np.array([0.9, 0.1, 0.2, 0.8, 0.3]), w) == pytest.approx(1.0)
    assert ev.weighted_auprc(y, np.zeros(5), w) == pytest.approx(0.4)


def test_negative_weights_lower_precision():
    y = np.array([1, 0])
    alarm = np.array([1, 1])
    tp, fp, _, _ = ev.weighted_confusion(y, alarm, np.array([1.0, 10.0]))
    assert tp / (tp + fp) == pytest.approx(1 / 11)


def test_recall_at_far_respects_budget():
    y = np.array([1, 1, 0, 0, 0, 0])
    score = np.array([0.9, 0.2, 0.8, 0.1, 0.05, 0.01])
    w = np.array([1, 1, 1000, 1, 1, 1], dtype=float)
    assert ev.recall_at_far(y, score, w, 0.002) == pytest.approx(0.5)


@pytest.mark.parametrize("snippet", [
    "open(os.path.join(d, '..', 'eval_only', 'val_labels.csv'))",
    "p = Path(args.data_dir).parent",
    "files = glob.glob(args.data_dir + '/*')",
    "os.getcwd()",
    "import subprocess",
])
def test_static_check_rejects_escape(snippet):
    assert ev.static_check(snippet) != ""


def test_static_check_accepts_init():
    assert ev.static_check((BENCH / "init.py").read_text()) == ""


@pytest.mark.skipif(not HAS_DATA, reason="benchmark data not generated")
def test_evaluator_ranks_candidates_in_expected_order():
    rule = ev.evaluate(str(BENCH / "candidates" / "rule_baseline.py"))
    init = ev.evaluate(str(BENCH / "init.py"))
    assert rule["validity"] == 1 and init["validity"] == 1
    assert rule["error_info"] == "" and init["error_info"] == ""
    assert init["combined_score"] > rule["combined_score"] > 0


@pytest.mark.skipif(not HAS_DATA, reason="benchmark data not generated")
def test_evaluator_rejects_incomplete_output(tmp_path):
    cand = tmp_path / "partial.py"
    cand.write_text(
        "import argparse, os, pandas as pd\n"
        "ap = argparse.ArgumentParser()\n"
        "ap.add_argument('--data-dir'); ap.add_argument('--split'); ap.add_argument('--out')\n"
        "a = ap.parse_args()\n"
        "idx = pd.read_csv(os.path.join(a.data_dir, a.split + '_index.csv')).head(10)\n"
        "pd.DataFrame({'serial_number': idx.serial_number, 'score': 0.0, 'alarm': 0}).to_csv(a.out, index=False)\n"
    )
    res = ev.evaluate(str(cand))
    assert res["validity"] == 0 and res["combined_score"] == 0
    assert "no prediction" in res["error_info"]


@pytest.mark.skipif(not HAS_DATA, reason="benchmark data not generated")
def test_evaluator_works_with_flat_upload_layout(tmp_path, monkeypatch):
    import importlib.util
    import shutil

    monkeypatch.delenv("HDD_BENCH_DATA_ROOT", raising=False)
    for f in ["evaluator.py", "init.py"]:
        shutil.copy2(BENCH / f, tmp_path / f)
    for f in (BENCH / "data" / "public").iterdir():
        shutil.copy2(f, tmp_path / f.name)
    shutil.copy2(BENCH / "data" / "eval_only" / "val_labels.csv", tmp_path / "val_labels.csv")

    spec = importlib.util.spec_from_file_location("flat_evaluator", tmp_path / "evaluator.py")
    flat = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(flat)
    res = flat.evaluate(str(tmp_path / "init.py"))
    assert res["validity"] == 1, res["error_info"]
    assert res["combined_score"] == pytest.approx(ev.evaluate(str(BENCH / "init.py"))["combined_score"], rel=1e-6)


@pytest.mark.skipif(not HAS_DATA, reason="benchmark data not generated")
def test_public_view_has_no_labels_for_query_split():
    idx = pd.read_csv(BENCH / "data" / "public" / "val_index.csv")
    assert "label" not in idx.columns
    assert set(ev.PUBLIC_FILES["val"]) <= {p.name for p in (BENCH / "data" / "public").iterdir()}
