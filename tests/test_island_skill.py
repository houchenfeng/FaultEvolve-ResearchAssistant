"""S5: skill/fe-island-evolution must not drift from the engine it documents.

A skill is an operator contract, so every check here cross-references real code -- the CLI's own
option strings, the config models, the IslandStatus enum, the event names the engine emits, and the
export script's own argparse -- instead of reviewing prose. The class of bug this guards is a skill
that reads well and sends the next operator to a flag, event or field that no longer exists.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from faultevolve.common.schemas import IslandStatus
from faultevolve.config import BudgetConfig, IslandSpec, IslandsConfig

REPO = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO / "skill" / "fe-island-evolution"
SKILL = SKILL_DIR / "SKILL.md"
EXPORT = SKILL_DIR / "scripts" / "export_experience_skill.py"
CLI = REPO / "src" / "faultevolve" / "cli.py"
ENGINE = REPO / "src" / "faultevolve" / "cloud" / "engine.py"
EXCHANGE = REPO / "src" / "faultevolve" / "cloud" / "exchange.py"

REFERENCES = {
    "configuration": SKILL_DIR / "references" / "configuration.md",
    "exchange": SKILL_DIR / "references" / "exchange.md",
    "hdd-server": SKILL_DIR / "references" / "hdd-server.md",
    "recovery": SKILL_DIR / "references" / "recovery.md",
}
GENERIC = [SKILL, REFERENCES["configuration"], REFERENCES["exchange"], REFERENCES["recovery"]]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def fenced(text: str) -> list[str]:
    return re.findall(r"```(?:bash|text|yaml|json)\n(.*?)```", text, re.S)


def statements(block: str) -> list[str]:
    """Join backslash continuations so a flag cannot hide on a wrapped line."""
    out: list[str] = []
    for line in block.splitlines():
        stripped = line.rstrip()
        if stripped.endswith("\\"):
            out.append((out.pop() + " " if out else "") + stripped[:-1].strip())
        else:
            out.append(stripped)
    return [s for s in out if s.strip()]


def cli_flags() -> set[str]:
    return set(re.findall(r'"(--[a-z0-9-]+)"', read(CLI)))


def export_flags() -> set[str]:
    return set(re.findall(r'"(--[a-z0-9-]+)"', read(EXPORT)))


def source_text() -> str:
    return "\n".join(read(p) for p in (ENGINE, EXCHANGE, CLI))


# ------------------------------------------------------------------- the files and their reach

ALL_FILES = [SKILL, EXPORT, *REFERENCES.values()]


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: str(p.relative_to(SKILL_DIR)))
def test_every_shipped_skill_file_exists(path: Path):
    assert path.is_file(), f"{path.relative_to(REPO)} is missing"


def test_the_frontmatter_names_the_directory():
    front = re.match(r"---\n(.*?)\n---\n", read(SKILL), re.S)
    assert front, "SKILL.md must open with a frontmatter block"
    meta = yaml.safe_load(front.group(1))
    assert meta["name"] == "fe-island-evolution"
    assert meta["description"].strip()


@pytest.mark.parametrize("name", sorted(REFERENCES))
def test_each_reference_is_reachable_from_the_entry_skill(name: str):
    assert f"references/{name}.md" in read(SKILL), f"{name}.md is orphaned"


@pytest.mark.parametrize("path", [SKILL, *REFERENCES.values()])
def test_every_relative_markdown_link_resolves(path: Path):
    broken = []
    for target in re.findall(r"\]\(([^)]+)\)", read(path)):
        clean = target.split("#")[0]
        if not clean or clean.startswith(("http://", "https://")):
            continue
        if not (path.parent / clean).exists():
            broken.append(target)
    assert broken == [], f"{path.name} links to nothing: {broken}"


def test_readme_indexes_the_skill_and_the_link_resolves():
    readme = read(REPO / "README.md")
    rows = [line for line in readme.splitlines() if line.startswith("|") and "fe-island-evolution" in line]
    assert len(rows) == 1, rows
    assert "(skill/fe-island-evolution/SKILL.md)" in rows[0]


# ------------------------------------------------------------------- commands the operator types

@pytest.mark.parametrize("path", [SKILL, *REFERENCES.values()])
def test_documented_fe_flags_are_real_cli_flags(path: Path):
    """A command in the skill may only use options `fe` actually declares."""
    known = cli_flags() | {"--help"}
    unknown: list[str] = []
    for block in fenced(read(path)):
        for statement in statements(block):
            if "fe " not in statement or "export_experience_skill.py" in statement:
                continue
            unknown += [f for f in re.findall(r"--[a-z][a-z0-9-]*", statement) if f not in known]
    assert sorted(set(unknown)) == [], f"{path.name} documents flags the CLI rejects"


@pytest.mark.parametrize("path", [SKILL, *REFERENCES.values()])
def test_documented_export_script_flags_are_real(path: Path):
    known = export_flags() | {"--help"}
    unknown: list[str] = []
    for block in fenced(read(path)):
        for statement in statements(block):
            if "export_experience_skill.py" not in statement:
                continue
            unknown += [f for f in re.findall(r"--[a-z][a-z0-9-]*", statement) if f not in known]
    assert sorted(set(unknown)) == [], f"{path.name} invents script options"


def test_the_export_script_only_exits_with_the_documented_codes():
    """The skill promises 0 and 2; a new failure code must be documented with it."""
    codes = set(re.findall(r"sys\.exit\((\d+)\)", read(EXPORT))) | set(
        re.findall(r"return (\d+)\b", read(EXPORT))
    )
    documented = set(re.findall(r"退出码[^0-9]*([0-9])", read(SKILL)))
    assert codes <= documented | {"0"}, f"undocumented exit codes: {sorted(codes - documented)}"


@pytest.mark.parametrize("path", [SKILL, REFERENCES["exchange"]])
def test_every_event_name_the_skill_greps_is_emitted_by_the_engine(path: Path):
    names = set()
    for pattern in re.findall(r'"type": "\(([a-z_|]+)\)"', read(path)):
        names.update(pattern.split("|"))
    assert names, "the skill no longer shows how to grep events, so this guard needs a new source"
    absent = sorted(n for n in names if f'"{n}"' not in source_text())
    assert absent == [], f"{path.name} greps for events that are never written: {absent}"


# ------------------------------------------------------------------- drift against the models

@pytest.mark.parametrize(
    ("model", "label"),
    [(IslandsConfig, "islands"), (IslandSpec, "single island"), (BudgetConfig, "budget")],
)
def test_the_config_reference_lists_every_field_the_engine_reads(model, label: str):
    text = read(REFERENCES["configuration"])
    absent = [name for name in model.model_fields if name not in text]
    assert absent == [], f"{label} fields missing from configuration.md: {absent}"


def test_the_documented_defaults_are_the_model_defaults():
    """Only rows whose default cell is a scalar are compared; prose cells are left to review."""
    text = read(REFERENCES["configuration"])
    scalars = {
        **{n: f.default for n, f in IslandsConfig.model_fields.items()},
        **{n: f.default for n, f in IslandSpec.model_fields.items()},
        **{n: f.default for n, f in BudgetConfig.model_fields.items()},
    }
    mismatches = []
    for name, default in scalars.items():
        if not isinstance(default, (bool, int, float)) or isinstance(default, str):
            continue
        cell = "true" if default is True else "false" if default is False else repr(default)
        if isinstance(default, float):
            cell = repr(default)
        row = re.search(rf"^\|\s*`?[a-z_.]*{re.escape(name)}`?\s*\|\s*`?([^|`]+)`?\s*\|", text, re.M)
        if row is None:
            continue
        documented = row.group(1).strip().split("，")[0].strip()
        if documented != cell and documented.replace("0.20", "0.2") != cell:
            mismatches.append((name, documented, cell))
    assert mismatches == [], f"configuration.md states defaults the code does not have: {mismatches}"


def test_the_skill_knows_the_only_island_statuses_that_exist():
    """The docs must not promise an `interrupted` state the schema does not have."""
    values = {s.value for s in IslandStatus}
    text = "\n".join(read(p) for p in GENERIC)
    for value in values:
        assert re.search(rf"\b{value}\b", text), f"{value} is a real status but the skill never says it"
    invented = re.findall(r"status[^.\n]{0,60}\b(interrupted|aborted|cancelled)\b", text, re.I)
    assert invented == [], f"the skill invents island states: {invented}"


def test_the_skill_states_the_single_scalar_metric_rule():
    """Requirement 5.1: the engine optimizes one score and it is always maximize-this."""
    text = read(SKILL) + read(REFERENCES["configuration"])
    assert "combined_score" in text
    assert re.search(r"(越大越好|maximize)", text)
    assert re.search(r"(方向.*适配器|适配器.*转换)", text), "lower-is-better must be the adapter's job"


# ------------------------------------------------------------------- what a skill must not do

@pytest.mark.parametrize("path", GENERIC)
def test_the_generic_layer_carries_no_host_paths_or_local_directories(path: Path):
    """This host's layout belongs to references/hdd-server.md only."""
    text = read(path)
    assert not re.search(r"/home/[a-z0-9_]+/", text), f"{path.name} hardcodes a server home directory"
    assert not re.search(r"[A-Za-z]:[\\/]{1,2}Users[\\/]", text), f"{path.name} hardcodes a local path"
    assert not re.search(r"sk-[A-Za-z0-9]{6,}", text), f"{path.name} contains an api key shape"
    assert not re.search(r"[A-Za-z_]+_API_KEY=\S", text), f"{path.name} assigns a key a literal value"


def test_the_reference_keeps_private_test_data_out_of_the_flow():
    text = read(SKILL) + read(REFERENCES["hdd-server"])
    assert re.search(r"(不得|禁止|不)[^。\n]{0,30}holdout", text), "holdout must stay forbidden"
    assert re.search(r"(只读|不得修改|禁止改写)", text)


def test_the_hdd_reference_marks_the_stages_it_has_not_run():
    """S9 is still open; the doc may not read as if the formal server run already happened."""
    text = read(REFERENCES["hdd-server"])
    assert re.search(r"(尚未执行|未执行|待执行)", text)
    assert re.search(r"(不是已跑过的记录|不是已跑过)", text)


def test_the_skill_refuses_to_upgrade_a_history_run_onto_three_islands():
    text = read(SKILL) + "\n".join(read(p) for p in GENERIC)
    assert re.search(r"(不会静默升级成三岛|never silently upgraded)", read(REPO / "skill" / "fe-evolve-manager" / "SKILL.md"))
    assert re.search(r"legacy|隐式单岛", text)
