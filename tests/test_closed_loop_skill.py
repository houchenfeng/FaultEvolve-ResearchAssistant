"""skill/fe-closed-loop-tuning must not drift from the engine it documents.

Every check cross-references real code: the CLI options, the config fields and defaults the
skill quotes, the artifacts the workflow writes, and the commands in its fenced blocks.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from faultevolve.cli import app
from faultevolve.config import BudgetConfig, EvolveConfig, StopConfig

REPO = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO / "skill" / "fe-closed-loop-tuning"
FILES = [SKILL_DIR / "SKILL.md", *sorted((SKILL_DIR / "references").glob("*.md")),
         SKILL_DIR / "assets" / "report.template.md"]


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def yaml_blocks(source: str) -> list[dict]:
    return [yaml.safe_load(b) for b in re.findall(r"```yaml\n(.*?)```", source, re.S)]


def test_front_matter_names_the_skill_and_says_when_not_to_use_it():
    head = text(SKILL_DIR / "SKILL.md").split("---")[1]
    meta = yaml.safe_load(head)
    assert meta["name"] == "fe-closed-loop-tuning"
    assert "不适用" in meta["description"]


def test_every_relative_link_resolves():
    for path in FILES:
        for target in re.findall(r"\]\((?!http)([^)#]+)\)", text(path)):
            assert (path.parent / target).resolve().exists(), f"{path.name} -> {target}"


def test_yaml_example_is_a_valid_config_fragment_and_uses_real_fields():
    (block,) = yaml_blocks(text(SKILL_DIR / "SKILL.md"))
    budget = BudgetConfig(**block["budget"])
    stop = StopConfig(**block["stop"])
    assert budget.stagnation_window == 6 and stop.stop_at_target is False
    EvolveConfig.model_validate({"budget": block["budget"], "stop": block["stop"]})


def test_the_claimed_defaults_are_the_real_defaults():
    # The skill says window 0 turns stagnation stopping off; that must stay true of the code.
    assert BudgetConfig().stagnation_window == 0
    from faultevolve.cloud.budget import BudgetController

    controller = BudgetController(BudgetConfig(min_iterations_before_stop=0))
    controller.best_history = [1.0] * 30
    assert controller.check_stop(iterations_done=30, total_tokens=0, best_score=1.0,
                                 initial_score=0.0, noise_delta=0.5) == ""
    armed = BudgetController(BudgetConfig(min_iterations_before_stop=0, stagnation_window=6))
    armed.best_history = [1.0] * 30
    assert armed.check_stop(iterations_done=30, total_tokens=0, best_score=1.0,
                            initial_score=0.0, noise_delta=0.5) == "stagnation"


def test_quoted_cli_options_exist():
    from typer.main import get_command

    run = get_command(app).commands["evolve"].commands["local"]
    options = {opt for p in run.params for opt in p.opts}
    commands = "\n".join(text(p) for p in FILES)
    for flag in set(re.findall(r"fe evolve local[^\n]*?((?:\s--?[a-z][\w-]*)+)", commands)):
        for token in re.findall(r"--?[a-z][\w-]*", flag):
            assert token in options, token
    for flag in ("--config-file", "--env-file", "--runs-dir", "--artifacts-dir", "--run-id", "--resume", "-n"):
        assert flag in options


def test_quoted_artifacts_are_ones_the_workflow_writes():
    source = (REPO / "src" / "faultevolve" / "workflow.py").read_text(encoding="utf-8")
    source += (REPO / "src" / "faultevolve" / "research_campaign.py").read_text(encoding="utf-8")
    source += (REPO / "src" / "faultevolve" / "reporting.py").read_text(encoding="utf-8")
    for name in ("workflow-result.json", "workflow-best.py", "effect-report.json", "experiment_spec.json",
                 "ledger.json", "status.json"):
        assert name in source, name
    assert "best_origin" in source


def test_the_evidence_numbers_match_the_stored_run_when_it_is_available():
    # Skip silently on machines without the NAS archive; the numbers are then unverifiable here.
    import json
    import pytest

    run = Path("/mnt/nas/public/users/jiangxiwu/FaultEvolve-huawei/myartifacts/full20_20261017_2040")
    if not (run / "effect-report.json").is_file():
        pytest.skip("run archive not mounted")
    report = json.loads((run / "effect-report.json").read_text())
    final = {s["key"]: s for s in report["solutions"]}
    evidence = text(SKILL_DIR / "references" / "evidence-hdd-20-rounds.md")
    for key, shown in (("baseline", "22.81"), ("evolution", "39.86"), ("final", "40.38")):
        assert f"{final[key]['performance']['combined_score']:.2f}" == shown and shown in evidence
    assert f"{json.loads((run / 'run_summary.json').read_text())['total_tokens']:,}" in evidence
