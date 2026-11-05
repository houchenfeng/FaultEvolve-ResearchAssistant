"""T24 / D5.4: an operator can follow skill/fe-island-evolution end to end on a generic task.

The skill claims a sequence of commands -- preflight the config, rehearse offline, read the three
blocks of the report, rebuild it without paying again, export the experience draft. This test walks
that sequence through the real CLI on the repository's toy fixture with the generic four-file
adapter, so nothing here needs a hard-drive dataset, a SMART field or a network. It fails when the
documented steps stop producing locatable output, which is the drift a prose review cannot catch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from faultevolve.cli import app

REPO = Path(__file__).resolve().parents[1]
TOY_TASK = REPO / "tests" / "fixtures" / "toy_task"
EXPORT = REPO / "skill" / "fe-island-evolution" / "scripts" / "export_experience_skill.py"

runner = CliRunner()

# Only generic keys: a task adapter for any four-file task, an iteration cap, the island ring.
SKILL_CONFIG: dict[str, Any] = {
    "task": {"adapter": "famou"},
    "budget": {"max_iterations": 6},
    "islands": {"enabled": True, "exchange_interval": 1},
}


@pytest.fixture
def skill_config(tmp_path: Path) -> Path:
    path = tmp_path / "effective.yaml"
    path.write_text(yaml.safe_dump(SKILL_CONFIG, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def rehearsal(tmp_path: Path, skill_config: Path) -> dict[str, Any]:
    """Step 3 of the skill: an offline rehearsal, and the run it leaves behind."""
    runs = tmp_path / "runs"
    artifacts = tmp_path / "art"
    result = runner.invoke(
        app,
        ["evolve", "local", str(TOY_TASK), "--mock", "-n", "6",
         "--config-file", str(skill_config),
         "--runs-dir", str(runs), "--artifacts-dir", str(artifacts), "--json"],
    )
    assert result.exit_code == 0, result.output + result.stderr
    payload = json.loads(result.output[result.output.index("{"):])
    return {"payload": payload, "runs": runs, "artifacts": artifacts, "tmp": tmp_path}


# ---------------------------------------------------------------- step 2: preflight the config


def test_the_preflight_names_the_ring_this_config_will_start(tmp_path, skill_config):
    result = runner.invoke(
        app,
        ["doctor", "--task-dir", str(TOY_TASK), "--config-file", str(skill_config), "--json"],
    )
    assert result.exit_code in (0, 1), result.output + result.stderr
    checks = {c["name"]: c for c in json.loads(result.output)["checks"]}
    assert checks["config_keys"]["ok"] is True
    assert checks["config_islands"]["ok"] is True
    assert "3 tree(s) [a:performance, b:miss_alert, c:efficiency]" in checks["config_islands"]["message"]
    assert "exchange every 1 attempts" in checks["config_islands"]["message"]
    # the skill tells the operator to read the adapter out of this same output
    assert checks["task_adapter"]["message"] == "adapter famou -> FamouAdapter"


def test_the_rehearsal_needs_no_hdd_specific_input(tmp_path, skill_config):
    """Requirement 5.1: the generic path must not be hard-drive machinery in disguise."""
    text = skill_config.read_text(encoding="utf-8")
    assert not any(token in text.lower() for token in ("hdd", "smart", "ros", "dashes", "disk"))


# ---------------------------------------------------------------- steps 3-4: the run and its report


def test_the_rehearsal_produces_the_three_blocks_the_skill_documents(rehearsal):
    summary_path = rehearsal["artifacts"] / rehearsal["payload"]["experiment_id"] / "run_summary.json"
    assert summary_path.is_file(), "run_summary.json is not where the skill says it is"
    for name in ("tree.json", "events.jsonl"):
        assert (summary_path.parent / name).is_file(), f"{name} is missing from the artifact home"

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    islands = summary["islands"]
    assert set(islands) == {"a", "b", "c"}
    assert {v["profile"] for v in islands.values()} == {"performance", "miss_alert", "efficiency"}
    for island in islands.values():
        assert island["attempts"] >= 1
        assert island["status"] in {"pending", "running", "paused", "finished"}
        assert island["best_score"] > 0, "an island reported no score of its own"
    assert sum(v["attempts"] for v in islands.values()) == summary["iterations_done"], (
        "the per-island attempt counts must add up to the run's iterations"
    )

    exchange = summary["exchange"]
    assert exchange["summaries"] > 0, "the rehearsal showed no exchange, so the skill proves nothing"
    assert exchange["deliveries"] > 0
    assert set(exchange["by_kind"]) == {"best", "failure", "knowledge"}

    cost = summary["cost"]
    spent = sum(bucket["tokens"] for bucket in cost["by_island"].values()) + cost["shared_tokens"]
    assert spent == cost["total_tokens"], "per-island cost must account for the whole run"
    assert set(cost) == {
        "total_tokens", "by_island", "shared_tokens", "unresolved_calls", "cost_usd", "cost_basis",
    }


def test_the_report_can_be_rebuilt_from_the_database_without_new_scores(rehearsal):
    run_id = rehearsal["payload"]["experiment_id"]
    out = rehearsal["tmp"] / "rebuilt"
    result = runner.invoke(
        app,
        ["evolve", "local", str(TOY_TASK), "--mock", "--report-only", "--resume", run_id,
         "--runs-dir", str(rehearsal["runs"]), "--artifacts-dir", str(out)],
    )
    assert result.exit_code == 0, result.output + result.stderr
    rebuilt = json.loads((out / run_id / "run_summary.json").read_text(encoding="utf-8"))
    live = json.loads(
        (rehearsal["artifacts"] / run_id / "run_summary.json").read_text(encoding="utf-8"),
    )
    assert rebuilt["rebuilt_from_store"] is True
    for block in ("islands", "exchange", "cost"):
        assert rebuilt[block] == live[block], f"{block} differs between the live run and the rebuild"


# ---------------------------------------------------------------- step 8: the experience export


def _load_exporter():
    import importlib.util

    spec = importlib.util.spec_from_file_location("export_experience_skill", EXPORT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_experience_draft_exports_into_the_run_directory(rehearsal):
    run_id = rehearsal["payload"]["experiment_id"]
    db = rehearsal["runs"] / run_id / "fe.db"
    summary = rehearsal["artifacts"] / run_id / "run_summary.json"
    exporter = _load_exporter()

    exporter.main([str(db), str(summary), "--task-dir", str(TOY_TASK)])

    draft = summary.parent / "skills" / "experience_skill_draft.md"
    index = summary.parent / "skills" / "evidence_index.json"
    assert draft.is_file() and index.is_file(), "the export did not land in the run's skills/ dir"

    evidence = json.loads(index.read_text(encoding="utf-8"))
    assert evidence["schema"] == "fe-experience-evidence/1"
    assert evidence["experiment_id"] == run_id
    assert evidence["island_profiles"] == {"a": "performance", "b": "miss_alert", "c": "efficiency"}
    assert evidence["review_status"] == "draft_not_cross_run_verified"
    sanitization = evidence["sanitization"]
    assert sanitization["source_code_included"] is False
    assert sanitization["raw_data_included"] is False
    assert sanitization["api_keys_included"] is False

    text = draft.read_text(encoding="utf-8")
    assert run_id in text
    for profile in ("performance", "miss_alert", "efficiency"):
        assert profile in text, f"the draft lost the island ring ({profile})"
    assert "single_observation" in text, "a one-run observation must not be labelled a law"
    assert "```" not in text, "the draft must not carry candidate source code"


def test_the_exporter_refuses_to_write_into_the_project_skill_dir(rehearsal):
    run_id = rehearsal["payload"]["experiment_id"]
    db = rehearsal["runs"] / run_id / "fe.db"
    summary = rehearsal["artifacts"] / run_id / "run_summary.json"
    exporter = _load_exporter()

    with pytest.raises(SystemExit) as refused:
        exporter.main([str(db), str(summary), "--out-dir", str(REPO / "skill" / "fe-island-evolution")])
    assert refused.value.code == 2, "the guard against overwriting shipped skills must exit 2"


def test_a_run_that_exchanged_nothing_delivers_facts_instead_of_rules(tmp_path):
    """D5.3: no generalizable observation is a result, not a licence to invent one."""
    runs = tmp_path / "runs"
    artifacts = tmp_path / "art"
    config = tmp_path / "no_exchange.yaml"
    config.write_text(
        yaml.safe_dump(
            {"task": {"adapter": "famou"}, "budget": {"max_iterations": 3},
             "islands": {"enabled": True, "exchange_interval": 10}},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["evolve", "local", str(TOY_TASK), "--mock", "-n", "3", "--config-file", str(config),
         "--runs-dir", str(runs), "--artifacts-dir", str(artifacts), "--json"],
    )
    assert result.exit_code == 0, result.output + result.stderr
    payload = json.loads(result.output[result.output.index("{"):])
    run_id = payload["experiment_id"]
    summary = artifacts / run_id / "run_summary.json"
    assert json.loads(summary.read_text(encoding="utf-8"))["exchange"]["summaries"] == 0

    _load_exporter().main([str(runs / run_id / "fe.db"), str(summary), "--task-dir", str(TOY_TASK)])

    draft = (summary.parent / "skills" / "experience_skill_draft.md").read_text(encoding="utf-8")
    evidence = json.loads((summary.parent / "skills" / "evidence_index.json").read_text(encoding="utf-8"))
    assert evidence["rule_count"] == 0
    assert "未得到可泛化规则" in draft
    assert "单凭一次运行无法区分" in draft, "a silent channel must not become a universal prohibition"
    for profile in ("performance", "miss_alert", "efficiency"):
        assert profile in draft
