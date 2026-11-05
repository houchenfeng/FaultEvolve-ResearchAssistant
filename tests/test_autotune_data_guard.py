"""Data path guard tests."""

from pathlib import Path

import pytest

from faultevolve.optimization.dev_split import DataAccessError, assert_public_train_only


def test_x1_rejects_eval_only(tmp_path):
    p = tmp_path / "eval_only" / "val_labels.csv"
    p.parent.mkdir(parents=True)
    p.write_text("x")
    with pytest.raises(DataAccessError):
        assert_public_train_only(p)
