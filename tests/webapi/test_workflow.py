"""Workflow projections use only bounded artifacts, with no raw dataset access."""

import json
import httpx
import pytest

from faultevolve.webapi.app import create_app
from faultevolve.webapi.settings import WebSettings
from faultevolve.webapi import replay_service


def write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def client_at(tmp_path):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(
        WebSettings(runs_root=tmp_path, allowed_path_roots=[tmp_path]))), base_url="http://test")


def evidence(root):
    write(root / "workflow.json", {"state": "running", "phase": "hyperparameters"})
    write(root / "data-workflow.json", {"state": "passed", "before": {"n_history_rows": 5, "n_samples": 4},
        "after": {"n_history_rows": 4, "n_samples": 4}, "source_sha256": {"train": "abc"},
        "transformations": [{"rule": "nonfinite_to_missing", "affected": 1, "reason": "无穷转缺失"}]})
    write(root / "hyperparameters/experiment_spec.json", {"budgets": {"max_trials": 5},
        "routes": [{"id": "a", "source": "evolution:node-a", "code_path": "/mnt/private/code.py"}]})
    write(root / "hyperparameters/ledger.json", {"completion_count": 2, "default_barrier_open": True,
        "best_candidate": {"candidate_id": "ok", "score": 40.}, "contract_hash": "frozen",
        "route_summaries": [{"route_id": "a", "default_score": 30., "real_visits": 2,
                             "best_candidates": [{"score": 40.}]}],
        "trials": [{"trial_number": 1, "candidate_id": "ok", "route_id": "a", "depth": 0,
            "parameters": {"C": .5}, "execution": {"status": "evaluated", "duration_seconds": 1.},
            "evaluation": {"succeeded": True, "integrity_passed": True, "score": 40., "reward": .1,
                "evidence": [{"result_file": "/mnt/private/labels.csv", "api_key": "sk-synthetic-never-export"}]},
            "decision": {"status": "default_observed"}},
            {"trial_number": 2, "candidate_id": "failed", "route_id": "a", "depth": 1,
             "evaluation": {"succeeded": False, "integrity_passed": False, "score": 9999.,
                            "error": "failed at /home/private/location"}, "execution": {"status": "failed"}}]})


@pytest.mark.asyncio
async def test_workflow_api_projects_actual_evidence_and_hides_internal_paths(tmp_path):
    root = tmp_path / "run"
    evidence(root)
    write(root / "workflow-result.json", {"best_score": 40., "evolution_best_score": 30.,
                                           "best_origin": "hierarchical_hpo"})
    (root / "workflow-best.py").write_text("# final program")
    client = client_at(tmp_path)
    response = await client.get("/api/runs/run/workflow")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data"]["after_rows"] == 4
    assert body["search"]["completed_trials"] == 2
    assert body["search"]["routes"][0]["default_score"] == 30.
    assert body["search"]["trials"][0]["score"] == 40.
    assert body["search"]["trials"][1]["score"] is None
    assert body["final_best_score"] == 40.
    assert "/mnt/private" not in response.text
    assert "/home/private" not in response.text
    assert "sk-synthetic" not in response.text
    settings = WebSettings(runs_root=tmp_path, allowed_path_roots=[tmp_path])
    assert replay_service.resolve_artifact(settings, "run", "workflow-best").path.read_text() == "# final program"
    assert (await client.get("/api/runs/run/artifacts/data")).status_code == 404
    await client.aclose()


@pytest.mark.asyncio
async def test_missing_and_corrupt_records_are_distinct(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    write(root / "run_summary.json", {})
    client = client_at(tmp_path)
    body = (await client.get("/api/runs/run/workflow")).json()
    assert body["search_state"] == "missing" and body["search"] is None
    (root / "hyperparameters").mkdir()
    (root / "hyperparameters/ledger.json").write_text("{broken")
    body = (await client.get("/api/runs/run/workflow")).json()
    assert body["search_state"] == "invalid"
    assert body["search"] is None
    assert body["warnings"]
    write(root / "hyperparameters/ledger.json", {"trials": [{"unexpected": "structure"}]})
    body = (await client.get("/api/runs/run/workflow")).json()
    assert body["search_state"] == "invalid" and body["search"] is None
    await client.aclose()


@pytest.mark.asyncio
async def test_report_failure_is_separate_from_search_completion(tmp_path):
    root = tmp_path / "run"
    evidence(root)
    write(root / "workflow.json", {"state": "finished", "phase": "complete"})
    write(root / "workflow-result.json", {"best_score": 40., "best_origin": "code_evolution"})
    write(root / "report-status.json", {"state": "failed", "error_type": "RuntimeError"})
    async with client_at(tmp_path) as client:
        body = (await client.get("/api/runs/run/workflow")).json()
    assert body["state"] == "finished" and body["final_best_score"] == 40.
    assert any(w["field"] == "reports" for w in body["warnings"])


@pytest.mark.asyncio
async def test_external_artifact_symlink_cannot_escape_run_root(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    write(root / "run_summary.json", {})
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / "hyperparameters").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows account lacks symbolic link privilege")
        raise
    async with client_at(tmp_path) as client:
        assert (await client.get("/api/runs/run/workflow")).status_code == 403


@pytest.mark.asyncio
async def test_legacy_campaign_layout_keeps_evolution_and_tuning_together(tmp_path):
    root = tmp_path / "campaign"
    evidence(root)
    write(root / "evolution/campaign/run_summary.json", {"experiment_id": "campaign", "status": "finished"})
    write(root / "results/report.json", {"best_val_ros": 41.7, "evolution_best_val_ros": 41.0,
                                        "best_origin": "hierarchical_hpo"})
    client = client_at(tmp_path)
    body = (await client.get("/api/runs/campaign/workflow")).json()
    assert body["final_best_score"] == 41.7
    assert body["search"]["completed_trials"] == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_effect_report_is_projected_and_damaged_record_is_flagged(tmp_path):
    root = tmp_path / "run"
    evidence(root)
    write(root / "workflow-result.json", {"best_score": 40., "evolution_best_score": 30., "best_origin": "hierarchical_hpo"})
    write(root / "effect-report.json", {
        "solutions": [{"key": "baseline", "label": "初始方案", "secret_path": "/home/private/x",
                       "performance": {"precision": .2, "recall": .3, "false_alarm_rate": .003, "missed_detection_rate": .7},
                       "complexity": {"estimated_parameters": 15, "model_families": ["LogisticRegression"], "source_lines": 62}}],
        "token_usage": {"total_tokens": 74679, "hierarchical_tokens": 0}, "note": "验证集结果",
        "convergence": {"target_score": 33.7, "target_reached": True, "rounds_to_target": 1, "time_to_target_s": 123.4,
                        "tokens_to_target": 20360, "internal_path": "/home/private/y",
                        "evolution_curve": [{"round": 1, "score": 36.8, "best_so_far": 36.8, "elapsed_s": 123.4, "x": 1}],
                        "hpo_curve": [{"trial": 5, "best_so_far": 41.8}]},
        "automation": {"total_steps": 30, "manual_interventions": 0, "automatic_coverage": 1.0,
                       "end_to_end_unattended": True, "leak": "/home/private/z"}})
    client = client_at(tmp_path)
    body = (await client.get("/api/runs/run/workflow")).json()
    assert body["effect_state"] == "available"
    convergence = body["effect"]["convergence"]
    assert convergence["rounds_to_target"] == 1 and convergence["evolution_curve"][0]["elapsed_s"] == 123.4
    assert convergence["hpo_curve"][0]["trial"] == 5
    assert body["effect"]["automation"]["automatic_coverage"] == 1.0
    solution = body["effect"]["solutions"][0]
    assert solution["performance"]["recall"] == .3 and solution["complexity"]["estimated_parameters"] == 15
    assert body["effect"]["token_usage"]["total_tokens"] == 74679
    assert "/home/private" not in json.dumps(body)
    write(root / "effect-report.json", {"solutions": [{"key": "x"}]})  # label missing
    broken = (await client.get("/api/runs/run/workflow")).json()
    assert broken["effect"] is None and broken["effect_state"] == "invalid"
    (root / "effect-report.json").unlink()
    assert (await client.get("/api/runs/run/workflow")).json()["effect_state"] == "missing"
    await client.aclose()
