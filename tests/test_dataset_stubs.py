"""Stub dataset adapter tests."""

from __future__ import annotations

import inspect
from pathlib import Path

import pandas as pd
import pytest

from faultevolve.tasks.protocol import EvalResult, TaskAdapter, TaskSpec
from faultevolve.tasks.smartmem_adapter import MCELOG_COLUMNS, SmartMemAdapter
from faultevolve.tasks.ssd_alibaba_adapter import AlibabaSSDAdapter
from faultevolve.tasks.stub_base import DataNotPreparedError


def test_ssd_adapter_protocol():
    adapter = AlibabaSSDAdapter()
    assert isinstance(adapter, TaskAdapter)
    ev = EvalResult(1.0, 1.0, 1.0, "", {"f1_boot_std": 0.1})
    assert adapter.get_noise_delta(ev) == 0.5


def test_ssd_stub_raises_clear_error(tmp_path):
    adapter = AlibabaSSDAdapter()
    spec = adapter.load_task.__func__  # noqa: SLF001
    for method in ("evaluate", "smoke_test", "build_smoke_data_dir"):
        with pytest.raises(DataNotPreparedError, match="alibaba_ssd") as exc:
            getattr(adapter, method)("x", None)  # type: ignore[arg-type]
        assert "docs/datasets/alibaba_ssd.md" in str(exc.value)
    with pytest.raises(DataNotPreparedError, match="alibaba_ssd"):
        adapter.load_task(tmp_path)


def test_ssd_validate_smartlog_frame():
    ok = pd.DataFrame(
        {"disk_id": ["d1"], "ds": [20180105], "model": ["m"], "n_1": [1], "r_1": [2], "n_5": [3], "r_5": [4]}
    )
    AlibabaSSDAdapter.validate_smartlog_frame(ok)
    bad = ok.drop(columns=["ds"])
    with pytest.raises(ValueError, match="ds"):
        AlibabaSSDAdapter.validate_smartlog_frame(bad)
    bad2 = ok.assign(foo=1)
    with pytest.raises(ValueError, match="foo"):
        AlibabaSSDAdapter.validate_smartlog_frame(bad2)


def test_ssd_rename_to_task_schema():
    df = pd.DataFrame(
        {
            "disk_id": ["d1", "d2"],
            "ds": [20180105, 20180106],
            "model": ["m1", "m2"],
            "n_1": [1, 2],
            "r_1": [3, 4],
        }
    )
    out = AlibabaSSDAdapter.rename_to_task_schema(df)
    assert list(out.columns[:3]) == ["date", "serial_number", "model"]
    assert out.iloc[0]["date"] == "2018-01-05"


def test_ssd_prepare_small_fixture(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    day = raw / "smartlog2018ssd"
    day.mkdir()
    pd.DataFrame({"disk_id": ["d1"], "ds": [20180101], "model": ["m"], "n_1": [1], "r_1": [1]}).to_csv(
        day / "20180101.csv", index=False
    )
    pd.DataFrame({"model": ["m"], "disk_id": ["d1"], "failure_time": ["2018-06-01"]}).to_csv(
        raw / "ssd_failure_label.csv", index=False
    )
    from benchmark.ssd_alibaba import prepare_data as prep

    labels = prep.load_failure_labels(raw / "ssd_failure_label.csv")
    assert list(labels.columns) == ["serial_number", "model", "failure_date"]
    assert prep.parse_month_range("2018-01:2018-12") == ("2018-01", "2018-12")
    with pytest.raises(ValueError):
        prep.parse_month_range("bad")
    with pytest.raises(NotImplementedError, match="docs/datasets/alibaba_ssd.md"):
        prep.main(
            [
                "--raw-dir",
                str(raw),
                "--train-months",
                "2018-01:2018-12",
                "--val-months",
                "2019-01:2019-06",
                "--test-months",
                "2019-07:2019-12",
            ]
        )


def test_ssd_data_status_env(tmp_path, monkeypatch):
    adapter = AlibabaSSDAdapter()
    monkeypatch.delenv("ALIBABA_SSD_DATA_ROOT", raising=False)
    st = adapter.data_status(Path("benchmark/ssd_alibaba"))
    assert not st.ok
    assert len(st.missing) == 4
    empty = tmp_path / "d"
    empty.mkdir()
    monkeypatch.setenv("ALIBABA_SSD_DATA_ROOT", str(empty))
    st2 = adapter.data_status(Path("benchmark/ssd_alibaba"))
    assert not st2.ok


def test_smartmem_adapter_protocol():
    adapter = SmartMemAdapter()
    assert isinstance(adapter, TaskAdapter)


def test_smartmem_stub_still_defers_the_sampled_run(tmp_path):
    adapter = SmartMemAdapter()
    for method in ("smoke_test", "build_smoke_data_dir"):
        with pytest.raises(DataNotPreparedError, match="smartmem"):
            getattr(adapter, method)("x", None)  # type: ignore[arg-type]
    with pytest.raises(DataNotPreparedError, match="docs/datasets/smartmem.md"):
        adapter.load_task(tmp_path)


def test_smartmem_evaluate_reports_instead_of_raising_when_nothing_is_prepared(
    tmp_path, monkeypatch
):
    """The full-data path is wired now, so an unprepared directory is a verdict, not an exception.

    A raise here would leave the evolution loop with nothing to record about a candidate, and a
    candidate that could not be run looks the same as one that ran badly only if the reason travels
    in ``error_info``.
    """
    monkeypatch.setenv("SMARTMEM_DATA_ROOT", str(tmp_path / "nothing"))
    adapter = SmartMemAdapter()
    spec = TaskSpec(
        task_dir=tmp_path,
        problem_md="",
        prompt_md="",
        init_code="",
        evaluator_path=Path("benchmark/smartmem/evaluator.py").resolve(),
        config=None,
    )
    result = adapter.evaluate("print('hello')", spec, timeout=30)
    assert not result.is_valid
    assert "manifest.json" in result.error_info


def test_smartmem_mcelog_schema():
    cols = {c: [1] for c in MCELOG_COLUMNS}
    SmartMemAdapter.validate_mcelog_frame(pd.DataFrame(cols))
    bad = pd.DataFrame({c: [1] for c in MCELOG_COLUMNS if c != "manufacturter"})
    bad["manufacturer"] = "x"
    with pytest.raises(ValueError):
        SmartMemAdapter.validate_mcelog_frame(bad)


def test_smartmem_ticket_and_submission_schema():
    t = pd.DataFrame({"serial_number": ["s"], "failure_time": ["2024-01-01"], "serial_number_type": ["C"]})
    with pytest.raises(ValueError):
        SmartMemAdapter.validate_ticket_frame(t)
    sub = pd.DataFrame({"sn_name": ["s"], "prediction_timestamp": ["t"], "serial_number_type": ["A"]})
    SmartMemAdapter.validate_submission_frame(sub)


def test_smartmem_aggregate_delegates_and_demands_its_coverage_cutoff():
    doc = inspect.getdoc(SmartMemAdapter.aggregate_events_to_samples)
    assert doc and "smartmem_data" in doc
    with pytest.raises(TypeError, match="outcome_observed_until"):
        SmartMemAdapter.aggregate_events_to_samples(pd.DataFrame(), pd.DataFrame())
    boundary = pd.Timestamp("2024-01-01", tz="UTC")
    with pytest.raises(ValueError, match="event log is missing columns"):
        SmartMemAdapter.aggregate_events_to_samples(
            pd.DataFrame(), pd.DataFrame(), outcome_observed_until=boundary
        )


def test_smartmem_prepare_small_fixture(tmp_path, capsys):
    raw = tmp_path / "raw"
    train = raw / "train"
    train.mkdir(parents=True)
    cols = list(MCELOG_COLUMNS)
    pd.DataFrame({c: [1] for c in cols}).to_csv(train / "dimm1.csv", index=False)
    pd.DataFrame({"serial_number": ["dimm1"], "failure_time": ["2024-07-01"], "serial_number_type": ["A"]}).to_csv(
        raw / "failure_ticket.csv", index=False
    )
    from benchmark.smartmem import prepare_data as prep

    assert prep.list_mcelog_files(raw, "csv")
    prep.load_tickets(raw / "failure_ticket.csv")
    # V1-07 replaced the stub body: a run without confirmed boundaries must stop by itself.
    code = prep.main(
        [
            "--raw-dir", str(raw),
            "--out-dir", str(tmp_path / "out"),
            "--format", "csv",
            "--timezone", "UTC",
        ]
    )
    assert code == prep.EXIT_INPUT
    assert "split-config" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()
