"""The SmartMem seed program has to stay a legal candidate that a snapshot can actually run.

Two silent breakages are worth pinning before the evolution loop starts executing ``init.py``: an
edit that makes the seed read something a candidate may not read, and a snapshot shape change that
leaves it writing a frame the evaluator would refuse. A seed that dies quietly is worse than a weak
seed, because the loop would report the failure as a score of zero. The last test covers the wider
four-file task convention (``problem.md`` / ``prompt.md`` / ``init.py`` / ``evaluator.py``), which
this seed and those documents are part of.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd

from faultevolve.common.codecheck import full_check

REPO = Path(__file__).resolve().parents[1]
SEED = REPO / "benchmark" / "smartmem" / "init.py"
EVALUATOR = REPO / "benchmark" / "smartmem" / "evaluator.py"

TRAIN_ROWS = [
    {"sample_id": f"t{i}", "unit_id": "unit-loud", "event_count": 30 + i,
     "recent_half_count": 40 + i, "earlier_half_count": 2, "growth_rate": 6.0,
     "minutes_since_last_event": 3, "ce_count": 50 + i, "distinct_rowid": 1,
     "rowid_repeat_rate": 0.9}
    for i in range(3)
] + [
    {"sample_id": f"t{i}q", "unit_id": "unit-quiet", "event_count": 1,
     "recent_half_count": 0, "earlier_half_count": 1, "growth_rate": 0.0,
     "minutes_since_last_event": 900, "ce_count": 1, "distinct_rowid": 4,
     "rowid_repeat_rate": 0.1}
    for i in range(3)
]
QUERY_ROWS = [
    {"sample_id": f"d{i}", "unit_id": "unit-sharp", "event_count": 25 + i,
     "recent_half_count": 35 + i, "earlier_half_count": 1, "growth_rate": 5.0,
     "minutes_since_last_event": 2, "ce_count": 40 + i, "distinct_rowid": 1,
     "rowid_repeat_rate": 0.8}
    for i in range(3)
] + [
    {"sample_id": "d9", "unit_id": "unit-flat", "event_count": 2, "recent_half_count": 1,
     "earlier_half_count": 1, "growth_rate": 0.2, "minutes_since_last_event": 500, "ce_count": 2,
     "distinct_rowid": 5, "rowid_repeat_rate": 0.0}
]
LABELS = [("t0", 1), ("t1", 1), ("t2", 1), ("t0q", 0), ("t1q", 0), ("t2q", 0)]


def _snapshot(root: Path, labels: list[tuple[str, int]] | None = None) -> Path:
    """Write the four files a candidate is allowed to see, with the query labels withheld."""
    rows = LABELS if labels is None else labels
    train = pd.DataFrame(TRAIN_ROWS)
    train.to_csv(root / "train_samples.csv.gz", index=False, compression="gzip")
    labelled = pd.DataFrame(rows, columns=["sample_id", "label"])
    labelled.to_csv(root / "train_labels.csv", index=False)
    query = pd.DataFrame(QUERY_ROWS)
    query["prediction_time"] = pd.Timestamp("2024-04-01 00:00", tz="UTC")
    query["history_end"] = pd.Timestamp("2024-03-31 23:00", tz="UTC")
    query.drop(columns=["event_count"]).to_csv(root / "dev_samples.csv.gz", index=False,
                                               compression="gzip")
    query[["sample_id", "unit_id", "prediction_time", "history_end"]].assign(
        serial_number_type="A"
    ).to_csv(root / "dev_index.csv", index=False)
    return root


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SEED), "--data-dir", str(root), "--split", "dev",
         "--out", str(root / "pred.csv")],
        capture_output=True, text=True, timeout=600,
    )


def test_the_seed_passes_the_repos_own_static_check() -> None:
    """A seed the loop would reject is no seed at all: it stays inside the candidate rules."""
    assert full_check(SEED.read_text(encoding="utf-8"), EVALUATOR) == ""


def test_the_seed_fills_the_whole_index_and_calls_each_unit_once(tmp_path: Path) -> None:
    done = _run(_snapshot(tmp_path))
    assert done.returncode == 0, done.stderr[-400:]

    predictions = pd.read_csv(tmp_path / "pred.csv")
    index = pd.read_csv(tmp_path / "dev_index.csv")
    assert list(predictions.columns) == ["sample_id", "score", "alarm"]
    assert sorted(predictions.sample_id.astype(str)) == sorted(index.sample_id.astype(str))
    assert predictions["score"].map(pd.notna).all()
    assert set(predictions.alarm.unique()) <= {0, 1}
    assert int(predictions.alarm.sum()) >= 1, "a seed that never fires cannot be evolved from"

    joined = predictions.merge(index[["sample_id", "unit_id"]], on="sample_id")
    called = joined[joined.alarm == 1]
    assert int(called.groupby("unit_id").size().max()) == 1
    loudest = joined.groupby("unit_id")["score"].idxmax()
    assert set(called.sample_id.astype(str)) <= set(joined.loc[loudest, "sample_id"].astype(str))


def test_a_seed_without_training_positives_fails_loudly_instead_of_scoring_zero(
    tmp_path: Path,
) -> None:
    """An unlabeled training slice is an input fault, not a model that predicted nothing."""
    done = _run(_snapshot(tmp_path, labels=[(key, 0) for key, _ in LABELS]))
    assert done.returncode != 0
    assert "no labelled failure rows" in done.stderr


def test_the_task_directory_ships_the_four_files_and_agrees_with_them() -> None:
    """``fe evolve local`` refuses a directory missing any of the four (src/faultevolve/cli.py).

    The two documents are checked against the program they describe rather than against each other:
    a contract that drifts out of ``problem.md`` is a contract the next candidate will not honour.
    """
    task_dir = SEED.parent
    for name in ("evaluator.py", "init.py", "problem.md", "prompt.md"):
        assert (task_dir / name).is_file(), name

    problem = (task_dir / "problem.md").read_text(encoding="utf-8")
    prompt = (task_dir / "prompt.md").read_text(encoding="utf-8")
    assert "sample_id,score,alarm" in problem
    assert "sample_id, score, alarm" in prompt
    for document in (problem, prompt):
        assert "provisional" in document
        assert "7d" in document
        assert "15min" in document or "15-minute" in document
    assert "train_labels.csv" in problem and "train_labels.csv" in prompt
    assert "evaluator" in problem and "join" in problem
    assert "combined_score = 100 * event_f1" in problem
    assert "combined_score = 100 * F" in prompt
