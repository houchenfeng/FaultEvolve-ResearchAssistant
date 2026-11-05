"""Behavioral checks for the real hierarchical-engine adapter."""

import ast
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from faultevolve import research_campaign as campaign


ROOT = Path(__file__).resolve().parents[1]
CODE = "from sklearn.linear_model import LogisticRegression\nm = LogisticRegression(C=0.5, max_iter=200)\n"


def test_snapshot_copy_works_without_metadata_permission_and_excludes_secrets(tmp_path, monkeypatch):
    src, dst = tmp_path / "src", tmp_path / "dst"
    (src / "nested").mkdir(parents=True)
    (src / "nested/code.py").write_text("pass\n")
    (src / ".env").write_text("EXAMPLE=not-a-real-key\n")
    monkeypatch.setattr(shutil, "copystat", lambda *a, **k: (_ for _ in ()).throw(PermissionError()))
    campaign.copy_tree(src, dst)
    assert (dst / "nested/code.py").read_text() == "pass\n"
    assert not (dst / ".env").exists()


@pytest.fixture
def campaign_dir(tmp_path):
    snapshot = tmp_path / "snapshot"
    engine = snapshot / "hierarchical-search/scripts/search_engine.py"
    engine.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "autoresearch-hierarchical-search-cn/scripts/search_engine.py", engine)
    task = snapshot / "task"
    task.mkdir()
    (task / "evaluator.py").write_text("# Frozen evaluator identity\n")
    db = tmp_path / "fe.db"
    with sqlite3.connect(db) as c:
        c.execute("create table node (id text,island_id text,artifact_json text,evidence_json text)")
        for i, island in enumerate(("a", "b")):
            c.execute("insert into node values (?,?,?,?)", (str(i), island,
                json.dumps({"code": CODE}),
                json.dumps({"evaluation": {"validity": 1., "combined_score": 20. + i}})))
    manifest = {"hpo_trials": 6, "hpo_wall_seconds": 60}
    return tmp_path, db, manifest


def test_ast_changes_only_selected_parameter_and_preserves_default_bytes():
    code = CODE + "untouched = 0.5\nparams = {'learning_rate': 0.1}\nN_ESTIMATORS = 100\n"
    route = campaign.describe_route("method", code, "fixture")
    assert route is not None
    defaults = route["default_parameters"]
    assert campaign.render_candidate(code, route, defaults) == code
    key = next(k for k in defaults if k.endswith("_C"))
    changed = dict(defaults, **{key: 1.0})
    result = campaign.render_candidate(code, route, changed)
    tree = ast.parse(result)
    assert "untouched = 0.5" in result
    assert [node.value.value for node in ast.walk(tree)
            if isinstance(node, ast.keyword) and node.arg == "C"] == [1.0]
    assert campaign.parameter_sites(ast.parse(code))[0][0]
    with pytest.raises(ValueError, match="离散域"):
        campaign.render_candidate(code, route, dict(defaults, **{key: 999}))
    with pytest.raises(ValueError, match="变化"):
        campaign.render_candidate(code + "\n", route, defaults)


def test_identical_island_sources_become_one_route_and_a_different_family(campaign_dir):
    output, db, _ = campaign_dir
    routes = campaign.choose_routes(db, output / "hyperparameters")
    assert len(routes) == len({route["source_sha256"] for route in routes}) == 2
    assert routes[0]["source"] == "evolution:1"
    assert [route["model_families"] for route in routes] == [["logreg"], ["lightgbm"]]


def test_cross_route_equal_programs_reuse_evaluation_with_durable_evidence(campaign_dir, monkeypatch):
    output, db, manifest = campaign_dir
    # Different route defaults can converge to byte-identical rendered programs.
    with sqlite3.connect(db) as conn:
        conn.execute("update node set artifact_json=? where id='0'",
                     (json.dumps({"code": CODE.replace("C=0.5", "C=1.0")}),))
    manifest["hpo_trials"] = 18
    calls = []
    def evaluate(code_path, *args):
        calls.append(code_path.read_text())
        return {"validity": 1., "combined_score": 21., "metric": {"split": "val"}}
    monkeypatch.setattr(campaign, "evaluate_val", evaluate)
    ledger = campaign.hierarchical_search(output, db, manifest)
    assert len(calls) == len(set(calls)) < ledger["completion_count"]
    hits = [t for t in ledger["trials"] if t["evaluation"]["evidence"][0]["cache_hit"]]
    assert hits
    trials = {t["candidate_id"]: t for t in ledger["trials"]}
    for trial in hits:
        source = trials[trial["evaluation"]["evidence"][0]["cached_from_candidate_id"]]
        assert trial["evaluation"]["score"] == source["evaluation"]["score"]
        assert trial["execution"]["duration_seconds"] == source["execution"]["duration_seconds"]
    before = len(calls)
    repeated = campaign.hierarchical_search(output, db, manifest)
    assert repeated["trials"] == ledger["trials"]
    assert len(calls) == before


def test_changed_evaluator_cannot_reuse_frozen_scores(campaign_dir, monkeypatch):
    output, db, manifest = campaign_dir
    monkeypatch.setattr(campaign, "evaluate_val", lambda *args: {"validity": 1., "combined_score": 21.})
    campaign.hierarchical_search(output, db, manifest)
    (output / "snapshot/task/evaluator.py").write_text("# Changed evaluator\n")
    with pytest.raises(ValueError, match="冻结评估器"):
        campaign.hierarchical_search(output, db, manifest)


@pytest.mark.parametrize("change", ["data", "cpu"])
def test_changed_evaluation_conditions_cannot_reuse_scores(campaign_dir, monkeypatch, change):
    output, db, manifest = campaign_dir
    monkeypatch.setattr(campaign, "evaluate_val", lambda *args: {"validity": 1., "combined_score": 21.})
    campaign.hierarchical_search(output, db, manifest)
    if change == "data":
        manifest["validation_files"] = {"public/train_labels.csv": "changed"}
        message = "数据指纹"
    else:
        import os
        monkeypatch.setenv("FE_RESEARCH_CPU_LIMIT", str(int(os.environ.get("FE_RESEARCH_CPU_LIMIT", "8")) + 1))
        message = "CPU 配额"
    with pytest.raises(ValueError, match=message):
        campaign.hierarchical_search(output, db, manifest)


def test_hierarchical_evaluations_are_real_inputs_and_resume_is_not_retraining(campaign_dir, monkeypatch):
    output, db, manifest = campaign_dir
    calls = []

    def evaluate(code_path, evaluator, result_path):
        code = code_path.read_text()
        calls.append(code)
        parameters = campaign.parameter_sites(ast.parse(code))
        score = 20 + sum(v for n, _, _, v in parameters if n == "C")
        return {"validity": 1., "combined_score": score, "metric": {"split": "val"}}

    monkeypatch.setattr(campaign, "evaluate_val", evaluate)
    ledger = campaign.hierarchical_search(output, db, manifest)
    assert len(calls) == ledger["completion_count"] == 6
    assert [t["depth"] for t in ledger["trials"][:2]] == [0, 0]
    assert all(t["depth"] > 0 for t in ledger["trials"][2:])
    assert len({t["candidate_id"] for t in ledger["trials"]}) == 6
    assert all(r["virtual_visits"] == 0 for r in ledger["route_summaries"])
    assert ledger["holdout"] is None
    repeated = campaign.hierarchical_search(output, db, manifest)
    assert len(calls) == 6
    assert repeated["best_candidate"] == ledger["best_candidate"]
    assert repeated["completion_count"] == 6


def test_nonfinite_scores_do_not_enter_beam(campaign_dir, monkeypatch):
    output, db, manifest = campaign_dir
    monkeypatch.setattr(campaign, "evaluate_val", lambda *a, **k:
                        {"validity": 1., "combined_score": float("nan")})
    ledger = campaign.hierarchical_search(output, db, manifest)
    assert ledger["best_candidate"] is None
    assert ledger["completion_count"] == 2
    assert all(t["execution"]["status"] == "failed" for t in ledger["trials"])
    assert not (output / "hyperparameters/evaluation-cache").exists()


def test_joint_goal_stops_tuning_and_resume_does_not_dispatch_again(campaign_dir, monkeypatch):
    output, db, manifest = campaign_dir
    manifest["research"] = {"domain": "hdd", "dataset_id": "synthetic", "evaluation_split": "val",
                            "targets": [{"metric": "combined_score", "value": 30}]}
    calls = []
    def evaluate(*args):
        calls.append(args)
        return {"validity": 1., "combined_score": 35., "metric": {"split": "val"}}
    monkeypatch.setattr(campaign, "evaluate_val", evaluate)
    ledger = campaign.hierarchical_search(output, db, manifest)
    assert ledger["stop_reason"] == "research_goal_reached"
    assert ledger["completion_count"] == 1
    campaign.hierarchical_search(output, db, manifest)
    assert len(calls) == 1


def test_interrupted_trial_is_not_evaluated_twice(campaign_dir, monkeypatch):
    output, db, manifest = campaign_dir
    calls = []

    def evaluate(code_path, *a, **k):
        calls.append(code_path.read_text())
        if len(calls) == 3:
            raise RuntimeError("simulated interruption")
        return {"validity": 1., "combined_score": 21.}

    monkeypatch.setattr(campaign, "evaluate_val", evaluate)
    with pytest.raises(RuntimeError):
        campaign.hierarchical_search(output, db, manifest)
    ledger = campaign.hierarchical_search(output, db, manifest)
    assert ledger["completion_count"] == 6
    assert ledger["trials"][2]["execution"]["status"] == "failed"
    assert "中断" in ledger["trials"][2]["evaluation"]["error"]
    assert len(calls) == 6


def test_snapshot_captures_committed_wal_and_does_not_open_network_db(tmp_path):
    source = tmp_path / "source.db"
    c = sqlite3.connect(source)
    c.execute("pragma journal_mode=wal")
    c.execute("create table evidence (score real)")
    c.execute("insert into evidence values (22.81)")
    c.commit()
    destination = tmp_path / "archive/fe.db"
    campaign.snapshot_database(source, tmp_path / "local/snapshot.db", destination)
    with sqlite3.connect(f"file:{destination}?mode=ro", uri=True) as archived:
        assert archived.execute("select score from evidence").fetchone() == (22.81,)
        assert archived.execute("pragma journal_mode").fetchone() == ("delete",)
    c.close()


def test_evaluator_subprocess_uses_only_validation(tmp_path):
    code = tmp_path / "candidate.py"
    code.write_text("# candidate\n")
    evaluator = tmp_path / "evaluator.py"
    evaluator.write_text(
        "def evaluate(path, timeout, split):\n"
        "    assert split == 'val'\n"
        "    return {'validity': 1., 'combined_score': 22.81, 'metric': {'split': split}}\n")
    result = campaign.evaluate_val(code, evaluator, tmp_path / "result.json")
    assert result["validity"] == 1
    assert result["combined_score"] == 22.81
    assert result["metric"]["split"] == "val"


def test_interruption_terminates_only_own_evaluator_group(tmp_path, monkeypatch):
    class Process:
        pid = 45678
        waits = 0

        def poll(self):
            return None

        def wait(self, timeout):
            self.waits += 1
            if self.waits == 1:
                raise InterruptedError("cancelled")
            return -15

    process = Process()
    killed = []
    monkeypatch.setattr(campaign.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(campaign.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    with pytest.raises(InterruptedError):
        campaign.evaluate_val(tmp_path / "candidate.py", tmp_path / "evaluator.py", tmp_path / "result.json")
    assert killed == [(45678, campaign.signal.SIGTERM)]
    assert campaign._active_evaluation is None


def test_failed_tuning_preserves_evolved_best_and_publishes_skill(campaign_dir):
    output, db, manifest = campaign_dir
    manifest.update(campaign_id="formal_unit", local_runs=str(output / "local"), model="fixture")
    art = output / "evolution/formal_unit"
    (art / "programs").mkdir(parents=True)
    best = art / "programs/best.py"
    best.write_text(CODE)
    campaign.write_json(art / "run_summary.json", {"best_score": 30., "best_node_id": "best", "iterations_done": 3})
    (output / "skill/fe-research-agent").mkdir(parents=True)
    (output / "skill/fe-research-agent/SKILL.md").write_text("---\nname: fe-research-agent\n---\n")
    campaign.finalize(output, db, manifest, {"best_candidate": None, "completion_count": 2,
                                           "stop_reason": "candidate_space_exhausted"})
    assert (output / "results/best.py").read_text() == CODE
    report = json.loads((output / "results/report.json").read_text())
    assert report["best_origin"] == "code_evolution"
    assert report["best_val_ros"] == 30.
    assert (output / "database/fe.db").is_file()
    assert (output / "fe-research-agent.zip").is_file()
    assert (output / "skill/fe-research-agent/references/latest-result.json").is_file()
