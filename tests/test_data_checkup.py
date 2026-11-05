"""Quality evidence, train-only scope and reproducibility of data checkups."""

import json
from unittest.mock import patch

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
from typer.testing import CliRunner

from faultevolve.cli import app
from faultevolve.tasks.data_checkup import analyze_frames, render_report
from faultevolve.tasks.protocol import DiscoveryFrames


def frames():
    return DiscoveryFrames(
        labels=pd.DataFrame({"unit": ["PRIVATE_DEVICE_A", "PRIVATE_DEVICE_B"], "label": [0, 1]}),
        history=pd.DataFrame({
            "unit": ["PRIVATE_DEVICE_A", "PRIVATE_DEVICE_B"],
            "date": ["2026-01-01", "2026-01-02"], "feature": [1.0, 2.0],
        }),
        unit_col="unit", time_col="date",
    )


def test_checkup_is_read_only_reproducible_and_aggregate():
    data = frames()
    before_labels, before_history = data.labels.copy(deep=True), data.history.copy(deep=True)
    facts, quality, coverage = analyze_frames(data)
    assert facts["n_positive"] == 1
    assert facts["n_negative"] == 1
    assert facts["min_detectable_effect"] is None
    assert quality["quality_status"] == "ready"
    assert quality["processing"]["transformations_applied"] == []
    assert quality["time_range"]["start"].startswith("2026-01-01")
    assert quality["provenance"] == analyze_frames(data)[1]["provenance"]
    assert_frame_equal(before_labels, data.labels)
    assert_frame_equal(before_history, data.history)
    exported = json.dumps([facts, quality], allow_nan=False) + coverage.to_csv() + render_report(facts, quality)
    assert "PRIVATE_DEVICE" not in exported
    data.history.loc[0, "feature"] = 3.0
    assert quality["provenance"]["history_sha256"] != analyze_frames(data)[1]["provenance"]["history_sha256"]


def test_quality_flags_invalid_labels_duplicates_missing_history_and_nonfinite():
    data = frames()
    data.labels.loc[2] = ["PRIVATE_DEVICE_A", 7]
    data.labels.loc[3] = ["NO_HISTORY", None]
    data.history.loc[1, "date"] = "not-a-time"
    data.history.loc[0, "feature"] = np.inf
    data.history.loc[1, "feature"] = np.nan
    data.history = pd.concat([data.history, data.history.iloc[[0]]], ignore_index=True)
    facts, quality, coverage = analyze_frames(data)
    issues = {issue["code"]: issue for issue in quality["issues"]}
    assert facts["quality_status"] == "blocked"
    assert issues["invalid_labels"]["count"] == 1
    assert issues["duplicate_label_units"]["count"] == 1
    assert issues["units_without_history"]["count"] == 1
    assert issues["duplicate_history_keys"]["severity"] == "decision_required"
    assert issues["invalid_time"]["count"] == 1
    assert issues["non_finite_feature"]["count"] == 2
    assert coverage.iloc[0]["missing_count"] == 1
    json.dumps([facts, quality], allow_nan=False)


def test_empty_or_missing_columns_produce_a_report_not_nan():
    data = DiscoveryFrames(pd.DataFrame(), pd.DataFrame(), unit_col="unit", time_col="date")
    facts, quality, coverage = analyze_frames(data)
    assert facts["quality_status"] == "blocked"
    assert quality["issue_counts"]["blocking"] >= 4
    assert coverage.empty
    assert "non_null_rate" in coverage
    json.dumps([facts, quality], allow_nan=False)
    data = frames()
    data.history = data.history.iloc[:0]
    _, quality, coverage = analyze_frames(data)
    assert quality["quality_status"] == "blocked"
    assert coverage.iloc[0]["non_null_rate"] is None


def test_numeric_time_does_not_invent_calendar_dates():
    data = frames()
    data.history["date"] = [0, 1]
    _, quality, _ = analyze_frames(data)
    assert quality["time_range"] is None
    assert quality["quality_status"] == "ready"


def test_cli_strict_writes_evidence_before_reporting_blocking_exit(tmp_path):
    task = tmp_path / "task"
    task.mkdir()
    (task / "evolve.yaml").write_text("{}")
    data = frames()
    data.labels["label"] = 0
    out = tmp_path / "report"
    with patch("faultevolve.tasks.create_benchmark_adapter") as create:
        adapter = create.return_value
        adapter.discovery_frames.return_value = data
        adapter.checkup_extras.return_value = None
        result = CliRunner().invoke(app, ["data", "checkup", str(task), "--strict", "--json", "--out", str(out)])
        adapter.discovery_frames.assert_called_once_with(adapter.load_task.return_value)
        adapter.discovery_frames_val.assert_not_called()
        adapter.evaluate.assert_not_called()
    assert result.exit_code == 2, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["quality_status"] == "blocked"
    quality = json.loads((out / "data_quality.json").read_text(encoding="utf-8"))
    assert quality["scope"] == "adapter_train_view"
    assert quality["issues"][0]["code"] == "single_class"
    assert (out / "data_report.md").is_file()
    assert (out / "field_coverage.csv").read_bytes().startswith(b"\xef\xbb\xbf")


def test_cli_missing_data_is_actionable_and_does_not_generate_report(tmp_path):
    with patch("faultevolve.tasks.create_benchmark_adapter") as create:
        create.return_value.discovery_frames.side_effect = FileNotFoundError
        result = CliRunner().invoke(app, ["data", "checkup", str(tmp_path), "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_type"] == "DataMissing"
    assert not (tmp_path / ".fe" / "datacheck").exists()
