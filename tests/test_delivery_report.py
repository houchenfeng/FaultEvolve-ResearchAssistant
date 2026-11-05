"""Token accounting distinguishes fresh usage, cache hits and lost requests."""

from pathlib import Path
import zipfile

import pytest

from faultevolve.delivery_report import package_skill, token_usage


def test_token_usage_does_not_double_charge_cached_requests():
    calls = [
        {"cached": 0, "prompt_tokens": 100, "completion_tokens": 20, "stage": "generate", "purpose": "generate", "outcome": "ok"},
        {"cached": 1, "prompt_tokens": 100, "completion_tokens": 20, "stage": "generate", "purpose": "generate", "outcome": "ok"},
        {"cached": 0, "prompt_tokens": 0, "completion_tokens": 0, "stage": "reflect", "purpose": "reflect", "outcome": "lost"},
    ]
    usage = token_usage(calls)
    assert usage["total_tokens"] == 120
    assert usage["cached_calls"] == 1
    assert usage["unknown_usage_calls"] == 1
    assert usage["by_stage"] == {"generate": 120, "reflect": 0}


def test_only_finished_evidence_can_be_packaged_and_archive_is_self_contained(tmp_path):
    report = {"state": "running"}
    source = tmp_path / "source"
    with pytest.raises(ValueError, match="未完成"):
        package_skill(report, source, tmp_path)
    source.mkdir()
    (source / "SKILL.md").write_text("---\nname: fe-closed-loop-tuning\ndescription: 闭环反馈\n---\n", encoding="utf-8")
    report = {"run_id": "synthetic", "state": "finished", "split": "val", "iterations_done": 1,
        "completed_trials": 2, "baseline_score": 20., "best_score": 30., "best_node_id": "node",
        "token_usage": {"calls": 1, "total_tokens": 10, "prompt_tokens": 8, "completion_tokens": 2,
                        "cached_calls": 0, "unknown_usage_calls": 0, "by_stage": {"generate": 10}},
        "exchange_counts": {}, "insight_count": 1, "limitations": ["合成测试"], "stage_metrics": []}
    destination = package_skill(report, source, tmp_path)
    assert (destination / "references/latest-run.json").is_file()
    with zipfile.ZipFile(tmp_path / "fe-closed-loop-tuning.zip") as archive:
        assert "fe-closed-loop-tuning/SKILL.md" in archive.namelist()
        assert "fe-closed-loop-tuning/references/latest-run.md" in archive.namelist()
        assert not any(".." in Path(name).parts for name in archive.namelist())
