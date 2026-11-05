"""V1-09: skill/fe-event-data-preparation - the reusable event-data preparation skill.

A skill is written for the next AI, so the tests check the two ways skills rot: they drift from the
code they describe, and they leak the dataset they were derived from. Everything here is therefore a
cross-check against the real modules and the real CLI - not a word count.

The skill is the generic layer in prose form, so it inherits section 5.1's rule: no domain
vocabulary outside a repository path.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from faultevolve.data import (
    event_sampling,
    event_schema,
    external_sort,
    io,
    manifest,
    temporal_split,
)

REPO = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO / "skill" / "fe-event-data-preparation"
SKILL = SKILL_DIR / "SKILL.md"
CONTRACT = SKILL_DIR / "references" / "canonical-event-contract.md"
CHECKLIST = SKILL_DIR / "references" / "leakage-checklist.md"
PREPARE = REPO / "benchmark" / "smartmem" / "prepare_data.py"



def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def bash_blocks(text: str) -> list[str]:
    return re.findall(r"```(?:bash|text)\n(.*?)```", text, re.S)


def prepare_flags() -> set[str]:
    return set(re.findall(r'"(--[a-z0-9-]+)"', read(PREPARE)))


# ------------------------------------------------------------------- the files exist


def test_the_skill_ships_two_reference_documents():
    for path in (SKILL, CONTRACT, CHECKLIST):
        assert path.is_file(), f"{path.relative_to(REPO)} is missing"
    assert (SKILL_DIR / "scripts").exists() is False, (
        "section 9 only allows scripts that exist and are covered; a placeholder dir breaks that"
    )


def test_the_frontmatter_names_the_directory():
    front = re.match(r"---\n(.*?)\n---\n", read(SKILL), re.S)
    assert front, "SKILL.md must open with a frontmatter block"
    meta = yaml.safe_load(front.group(1))
    assert meta["name"] == "fe-event-data-preparation"
    assert meta["description"].strip()
    assert len(meta["description"]) <= 120, "the index line is not a second title"


def test_the_root_readme_indexes_the_skill_and_the_link_resolves():
    readme = read(REPO / "README.md")
    # the index is the table, not the path list further down: a row must carry both the link and a
    # description column, or a reader cannot tell when to open the skill
    rows = [line for line in readme.splitlines() if line.startswith("|")
            and "fe-event-data-preparation" in line]
    assert len(rows) == 1, rows
    assert "(skill/fe-event-data-preparation/SKILL.md)" in rows[0]
    cells = [cell.strip() for cell in rows[0].strip().strip("|").split("|")]
    assert len(cells) == 2 and all(cells), f"the index row needs a link and a reason: {rows[0]}"
    # every skills table row links a SKILL.md that has to exist, or the index advertises nothing
    for target in re.findall(r"\|\s*\[`skill/([^`]+)`\]\(skill/([^)]+)/SKILL\.md\)", readme):
        assert (REPO / "skill" / target[1] / "SKILL.md").is_file(), target


# ------------------------------------------------------------------- plan section 9 coverage


REQUIRED_TOPICS = {
    "trigger": r"何时使用|触发",
    "required inputs": r"必需输入|输入清单",
    "read-only raw data": r"只读",
    "schema probe": r"schema 探查|探查",
    "canonical fields": r"规范化字段",
    "window definitions": r"anchor.*lookback|lookback.*lead.*horizon",
    "temporal split and embargo": r"embargo|时间切分",
    "chunking and resume": r"分块|resume|checkpoint",
    "anonymous logs": r"匿名",
    "leakage checklist": r"泄漏检查",
    "layered fixtures": r"fixture",
    "success and failure": r"成功.*失败|退出码",
    "no upload, no private test labels": r"禁止上传|不得上传",
    "adapter owns domain mapping": r"adapter",
}


def test_every_required_topic_has_a_section():
    text = read(SKILL)
    missing = [name for name, pattern in REQUIRED_TOPICS.items()
               if not re.search(pattern, text, re.I)]
    assert missing == [], f"section 9 topics not covered: {missing}"


def test_the_skill_states_the_four_exit_codes_it_documents():
    text = read(SKILL)
    for code, meaning in (("0", "完成"), ("1", "输入"), ("2", "配置"), ("3", "部分")):
        assert re.search(rf"\|\s*`?{code}`?\s*\|[^|\n]*{meaning}", text), f"exit {code} undocumented"


def test_the_skill_points_at_the_checklist_and_the_contract():
    text = read(SKILL)
    assert "references/leakage-checklist.md" in text
    assert "references/canonical-event-contract.md" in text


# ------------------------------------------------------------------- drift against the code


def test_every_command_in_the_skill_exists_in_the_repo():
    """The skill may only reference code that is actually in the repository."""
    missing: list[str] = []
    for block in bash_blocks(read(SKILL)):
        for rel in re.findall(r"(?:src|benchmark|skill|tests|docs)/[A-Za-z0-9_./-]+", block):
            if not (REPO / rel.rstrip(".,")).exists():
                missing.append(rel)
        for module in re.findall(r"python -m ([a-z0-9_.]+)", block):
            top = module.split(".")[0]
            if (REPO / top).exists() or (REPO / "src" / top).exists():
                continue
            assert top == "pytest", f"{module} is neither a repo module nor a known tool"
    assert missing == [], sorted(set(missing))


def test_the_skill_only_documents_flags_the_cli_actually_accepts():
    text = read(SKILL) + read(CONTRACT)
    unknown = sorted({flag for flag in re.findall(r"--[a-z][a-z0-9-]*", text)} - prepare_flags())
    assert unknown == [], f"documented flags the CLI does not accept: {unknown}"


CONTRACT_TOKENS = {
    "schema fields": [f.name for f in event_schema.CanonicalEventSchema.__dataclass_fields__.values()],
    "window fields": [f.name for f in event_sampling.EventWindowConfig.__dataclass_fields__.values()],
    "anchor strategies": list(event_sampling.ANCHOR_STRATEGIES),
    "output columns": list(event_sampling.OUTPUT_COLUMNS),
    "drop reasons": list(event_sampling.DROP_REASONS),
    "split keys": list(temporal_split.SCORED_SPLITS) + list(temporal_split.NON_SCORED_KEYS),
    "io formats": list(io.FORMATS),
    "manifest names": [manifest.MANIFEST_NAME, manifest.LOCK_NAME, manifest.PARTITIONS_DIR],
    "sort names": [
        external_sort.MERGED_FILE_NAME,
        external_sort.RUNS_DIR_NAME,
        external_sort.SORT_SIDECAR_NAME,
        external_sort.SORT_NS_COLUMN,
        external_sort.SEQUENCE_COLUMN,
        external_sort.SORT_VERSION,
    ],
    "sort fields": [
        *[f.name for f in external_sort.SortResult.__dataclass_fields__.values()],
        *[f.name for f in external_sort.SpaceReport.__dataclass_fields__.values()],
    ],
}


@pytest.mark.parametrize("group", sorted(CONTRACT_TOKENS))
def test_the_contract_document_lists_the_names_the_code_uses(group: str):
    text = read(CONTRACT)
    absent = [token for token in CONTRACT_TOKENS[group] if token not in text]
    assert absent == [], f"{group}: {absent} appear in code but not in the contract"


def test_the_contract_names_the_default_error_type_domain():
    """The default domain is a measured fact about the shipped package, so the doc has to carry it.

    Reading the tuple out of the source instead of importing it keeps this file's rule of never
    running the CLI, and it fails if the default is written somewhere else.
    """
    declared = re.search(r"DEFAULT_ERROR_TYPES = \(([^)]*)\)", read(PREPARE))
    assert declared, "the CLI no longer states its default error type domain as a tuple"
    names = re.findall(r'"([^"]+)"', declared.group(1))
    assert names, "the default error type domain declares nothing"
    text = read(CONTRACT)
    absent = [name for name in names if name not in text]
    assert absent == [], f"{absent} are the default domain in code but not in the contract"


# ------------------------------------------------------------------- what a skill must not do


REPO_PATH_TOKEN = re.compile(r"\b(?:src|benchmark|tests|docs|skill)/[A-Za-z0-9_./-]*")


def strip_repo_paths(text: str) -> str:
    """Drop repository paths: naming a directory is not the same as using its vocabulary."""
    return REPO_PATH_TOKEN.sub("", text)


# the guard is section 5.1's list verbatim; inventing extra words here would police the skill
# more strictly than the code it describes
GENERIC_GUARD = re.compile(r"\b(DIMM|mcelog|ECC|UE|bankid|SmartMem|smartmem)\b")


def test_the_skill_carries_no_domain_vocabulary_outside_a_repo_path():
    """Section 5.1 applies to the generic layer, and this skill is that layer in prose form."""
    for path in (SKILL, CONTRACT, CHECKLIST):
        hits = GENERIC_GUARD.findall(strip_repo_paths(read(path)))
        assert hits == [], f"{path.name} mentions {sorted(set(hits))}"


def test_the_skill_uses_placeholders_and_carries_no_credentials_or_real_locations():
    text = "\n".join(read(path) for path in (SKILL, CONTRACT, CHECKLIST))
    assert not re.search(r"sk-[A-Za-z0-9]{6,}", text), "an api key shape"
    assert not re.search(r"[A-Za-z0-9_]+_API_KEY=\S", text), "a key assigned a literal value"
    assert not re.search(r"/home/[a-z0-9_]+/", text), "a server home directory"
    assert not re.search(r"[A-Za-z]:[\\/]{1,2}Users[\\/]", text), "a local user path"
    assert re.search(r"\b\d{9,}\b", text) is None, "a bare long number (serial or epoch)"
    for placeholder in ("<RAW_DIR>", "<OUT_DIR>", "$EVENT_DATA_ROOT"):
        assert placeholder in text, f"{placeholder} should be the documented shape"


def test_the_skill_forbids_uploading_data_and_reading_private_labels():
    text = read(SKILL)
    assert re.search(r"(禁止|不得)[^。\n]{0,40}(上传|外发)", text)
    assert re.search(r"(禁止|不得)[^。\n]{0,40}(holdout|私有)[^。\n]{0,20}(标签|test|数据)", text)
    assert re.search(r"(不|禁止|不得)[^。\n]{0,30}自动下载", text), (
        "section 9: the skill must not claim it fetches licensed data"
    )


def test_the_skill_says_what_this_phase_did_not_build():
    text = read(SKILL)
    assert re.search(r"evaluator[^。\n]*(未|not)", text, re.I)
    assert re.search(r"(未实现|还没有|not ready)", text, re.I)
    # what it did build has to be named too, with the limit attached: a reader who finds the local
    # scorer later must already know its rules are provisional rather than official
    assert re.search(r"(本地|provisional)[^。\n]{0,80}(evaluator|细则|口径)", text, re.I)


# ------------------------------------------------------------------- leakage checklist


CHECKLIST_ITEMS = {
    "anchor from label": r"锚点[^。\n]{0,30}(标签|告警|工单)|(标签|告警)[^。\n]{0,20}锚点",
    "censoring": r"随访|删失",
    "embargo": r"embargo",
    "threshold from train": r"阈值[^。\n]{0,40}(训练|CV)",
    "no future rows": r"未来|event_time",
    "duplicate alarms": r"重复告警|同一单元多次",
    "group split is not time": r"分组[^。\n]{0,30}(时间|不等同)|按单元分组",
    "private test labels": r"holdout|私有 test",
    "soft labels change scale": r"软标签|分数尺度",
    "asymmetric sampling": r"抽样[^。\n]{0,30}(对称|不对称)|协变量",
}


def test_the_checklist_covers_every_documented_leakage_risk():
    text = read(CHECKLIST)
    missing = [name for name, pattern in CHECKLIST_ITEMS.items() if not re.search(pattern, text)]
    assert missing == [], f"checklist is silent about: {missing}"


def test_the_checklist_is_a_list_of_checks_not_prose():
    items = re.findall(r"^- \[ \] ", read(CHECKLIST), re.M)
    assert len(items) >= 10, f"only {len(items)} checkable items"


def test_the_contract_documents_the_sampling_pipeline_order():
    text = read(CONTRACT)
    order = [
        text.find("normalize_events"),
        text.find("build_labeled_samples"),
        text.find("assign_temporal_splits"),
        text.find("audit_temporal_splits"),
    ]
    assert -1 not in order, order
    assert order == sorted(order), "the contract must present the pipeline in call order"


# ------------------------------------------------------------------- stub-test migration


def test_the_stub_tests_no_longer_expect_a_prepare_stub():
    """V1-09 asks for the NotImplementedError expectations to be replaced by computed outputs.

    The SmartMem region of the stub test file must have moved onto real behaviour, while the SSD
    stub keeps its expectation - deleting the wrong one is also a migration bug.
    """
    text = read(REPO / "tests" / "test_dataset_stubs.py")
    smartmem_region = text[text.index("def test_smartmem"):]
    assert "NotImplementedError" not in smartmem_region
    assert "NotImplementedError" in text[: text.index("def test_smartmem")]
