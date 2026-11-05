"""The engine catalogue must stay in sync with the engine source (TODO §1.3, §阶段1测试)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from faultevolve.common.schemas import (  # noqa: E402
    HypothesisStatus,
    NodeStatus,
    OperatorType,
)
from faultevolve.config import (  # noqa: E402
    DiscoveryConfig,
    EvolveConfig,
    TournamentConfig,
)
from faultevolve.tasks.registry import ADAPTER_ALIASES, STUB_ADAPTER_DOCS  # noqa: E402
from faultevolve.webapi.catalog import (  # noqa: E402
    ENGINE_RUN_STATUSES,
    EVENT_TYPES,
    NAV_MODULES,
    PRESETS,
    UI_FIELD_METADATA,
    UNIMPLEMENTED_RUN_STATUSES,
    build_engine_catalog,
    build_preset_catalog,
    config_field_metadata,
)

SRC = REPO_ROOT / "src" / "faultevolve"
LOG_EVENT_RE = re.compile(r'_log_event\(\s*["\']([a-z0-9_]+)')

#: Files that can carry a run-status literal. The engine writes ``running`` /
#: ``finished`` on the experiment row and ``crashed`` in the crash summary;
#: ``Experiment.status`` defaults to ``created`` and the store falls back to it
#: when the persisted status is empty. Scanning all three keeps the check honest
#: no matter which of them a future status is born in.
_STATUS_SOURCES = ("cloud/engine.py", "common/schemas.py", "cloud/store.py")


def _source_event_types() -> set[str]:
    found: set[str] = set()
    for path in SRC.rglob("*.py"):
        found |= set(LOG_EVENT_RE.findall(path.read_text(encoding="utf-8")))
    return found


def _engine_source_text() -> str:
    return "\n".join(
        (SRC / rel).read_text(encoding="utf-8") for rel in _STATUS_SOURCES
    )


def _writes_status(text: str, status: str) -> bool:
    """True when a line that mentions ``status`` also carries the quoted literal.

    Line-scoped rather than a single anchored regex, because the engine writes
    run status in three different shapes::

        status="running"              # keyword argument
        "status": "crashed"           # dict entry in the crash summary
        status: str = "created"       # model field default
        status=row["status"] or "created"   # store fallback

    All four share only one property: the literal sits on a line that names
    ``status``. Anchoring on ``status\\s*[=:]`` silently misses the dict-entry and
    field-default forms, which is exactly the bug this check exists to catch.
    """
    literal = re.compile(rf'["\']{re.escape(status)}["\']')
    return any(literal.search(line) for line in text.splitlines() if "status" in line)


def test_all_event_types_are_catalogued() -> None:
    """Every ``_log_event("...")`` literal must be in the catalogue."""
    missing = sorted(_source_event_types() - EVENT_TYPES)
    assert missing == []
    assert EVENT_TYPES, "the event catalogue must not be empty"


def test_catalogue_has_no_invented_event_type() -> None:
    """The catalogue must not list a type the engine cannot emit."""
    invented = sorted(EVENT_TYPES - _source_event_types())
    assert invented == []


# --------------------------------------------------------------------------
# engine → front-end taxonomy drift (阶段 8, PRD §16.2)
# --------------------------------------------------------------------------
#
# The two tests above already pin ``EVENT_TYPES`` to the engine source. This
# pair pins the *next* hop: the front end's coarse-category table
# (``web/src/features/workbench/event-taxonomy.ts``) against the same set.
#
# The failure this exists to prevent is silent. A new engine event type lands,
# the catalogue picks it up automatically, the front end does not -- and nothing
# anywhere reports an error. The timeline just quietly shows one less thing,
# which is indistinguishable from "the engine didn't do that".
#
# Parsing the TypeScript with a regex rather than importing it is deliberate:
# the table is a literal, and the day it grows logic this test should fail
# loudly instead of quietly comparing nothing.

_TAXONOMY_TS = REPO_ROOT / "web" / "src" / "features" / "workbench" / "event-taxonomy.ts"
_TAXONOMY_CATEGORIES_RE = re.compile(r"EVENT_CATEGORIES\s*=\s*\[(.*?)\]", re.DOTALL)
_TAXONOMY_LABELS_RE = re.compile(r"CATEGORY_LABELS[^=]*=\s*\{(.*?)\n\}", re.DOTALL)
_TS_STRING_RE = re.compile(r"'([a-z0-9_]+)'")
#: ``CATEGORY_LABELS`` is keyed by bare identifiers, not quoted strings, and its
#: values are Chinese -- so the keys need their own pattern.
_TS_KEY_RE = re.compile(r"^\s*([a-z0-9_]+)\s*:", re.MULTILINE)


def _taxonomy_source() -> str:
    assert _TAXONOMY_TS.is_file(), f"missing {_TAXONOMY_TS}"
    return _TAXONOMY_TS.read_text(encoding="utf-8")


def _taxonomy_members() -> list[str]:
    """Every type name listed in ``CATEGORY_MEMBERS``, in source order."""
    text = _taxonomy_source()
    start = text.index("const CATEGORY_MEMBERS")
    end = text.index("\n};", start)
    return _TS_STRING_RE.findall(text[start:end])


def _taxonomy_categories() -> list[str]:
    match = _TAXONOMY_CATEGORIES_RE.search(_taxonomy_source())
    assert match is not None, "EVENT_CATEGORIES literal not found"
    return _TS_STRING_RE.findall(match.group(1))


def test_every_engine_event_type_has_a_front_end_category() -> None:
    """A new engine event must be classified, or the UI silently drops it."""
    unclassified = sorted(EVENT_TYPES - set(_taxonomy_members()))
    assert unclassified == [], (
        "这些事件类型引擎会发，但前端分类表里没有："
        f"{unclassified}。要么补进 event-taxonomy.ts 的某个粗类，"
        "要么承认它没有粗类并写进表的注释里 —— 不能只是不写。"
    )


def test_front_end_category_invents_no_event_type() -> None:
    """A type in the table the engine never emits is a stale promise."""
    invented = sorted(set(_taxonomy_members()) - EVENT_TYPES)
    assert invented == []


def test_no_event_type_lands_in_two_categories() -> None:
    """Exclusive categories: the reverse lookup would otherwise be arbitrary."""
    members = _taxonomy_members()
    duplicates = sorted({t for t in members if members.count(t) > 1})
    assert duplicates == []


def test_every_category_has_a_chinese_label() -> None:
    """A category with no label renders as its raw snake_case name."""
    text = _taxonomy_source()
    match = _TAXONOMY_LABELS_RE.search(text)
    assert match is not None, "CATEGORY_LABELS literal not found"
    labelled = set(_TS_KEY_RE.findall(match.group(1)))
    unlabelled = sorted(set(_taxonomy_categories()) - labelled)
    assert unlabelled == []


def test_prd_asks_for_twelve_categories_and_we_have_twelve() -> None:
    """PRD §16.2 lists exactly twelve. Fewer is a gap, more is invention."""
    categories = _taxonomy_categories()
    assert len(categories) == 12
    assert len(set(categories)) == 12


# --------------------------------------------------------------------------
# engine → SSE subscription list drift (D6.4：交换/岛事件的实时通道)
# --------------------------------------------------------------------------
#
# The front end subscribes to SSE by *name* (``source.addEventListener(name, …)``):
# a frame whose ``event:`` name was never registered is delivered to nobody. So a
# name missing from ``KNOWN_EVENT_NAMES`` does not render as an unknown event --
# it does not arrive at all, and the timeline looks exactly like a run that never
# did that thing. The endpoint writes every frame as a named event
# (``webapi/event_stream.py:sse_frame``), so the list must equal ``EVENT_TYPES``.

_SSE_NAMES_TS = REPO_ROOT / "web" / "src" / "features" / "workbench" / "use-event-stream.ts"
_SSE_NAMES_RE = re.compile(
    r"KNOWN_EVENT_NAMES[^=]*=\s*\[(.*?)\n\];", re.DOTALL
)


def _subscribed_event_names() -> list[str]:
    text = _SSE_NAMES_TS.read_text(encoding="utf-8")
    match = _SSE_NAMES_RE.search(text)
    assert match is not None, "KNOWN_EVENT_NAMES literal not found"
    return _TS_STRING_RE.findall(match.group(1))


def test_all_known_event_names_are_subscribed() -> None:
    """Every catalogued type must be registered, or its live frames are dropped."""
    subscribed = set(_subscribed_event_names())
    missing = sorted(EVENT_TYPES - subscribed)
    assert missing == [], (
        "这些事件类型后端会以具名 SSE 事件发出去，但前端没有订阅："
        f"{missing}。漏订阅的表现是「时间轴上根本没有这件事」，"
        "而不是「出现了一条未知事件」。"
    )


def test_known_event_names_invent_nothing() -> None:
    """A subscribed name the engine never emits is a stale promise."""
    invented = sorted(set(_subscribed_event_names()) - EVENT_TYPES)
    assert invented == []


def test_all_operator_types_are_catalogued() -> None:
    catalog = build_engine_catalog()
    assert catalog["operator_type"] == [m.value for m in OperatorType]
    assert set(catalog["generative_operators"]) <= set(catalog["operator_type"])


def test_all_adapter_aliases_are_catalogued() -> None:
    catalog = build_engine_catalog()
    catalogued = {entry["alias"] for entry in catalog["adapter_aliases"]}
    assert catalogued == set(ADAPTER_ALIASES)
    assert {entry["alias"] for entry in catalog["stub_adapters"]} == set(STUB_ADAPTER_DOCS)


def test_status_enums_are_catalogued() -> None:
    catalog = build_engine_catalog()
    assert catalog["node_status"] == [m.value for m in NodeStatus]
    assert catalog["hypothesis_status"] == [m.value for m in HypothesisStatus]


def test_run_statuses_still_match_the_engine() -> None:
    """If the engine learns a new run status, move it out of "unimplemented".

    Keeps PRD §9.2 honest: the nine-state lifecycle is only partly real, and
    this test fails the moment that changes.
    """
    text = _engine_source_text()
    for status in sorted(ENGINE_RUN_STATUSES):
        assert _writes_status(text, status), (
            f"engine no longer writes run status {status!r}"
        )
    for status in sorted(UNIMPLEMENTED_RUN_STATUSES):
        assert not _writes_status(text, status), (
            f"run status {status!r} now exists -- update the catalogue and PRD §9.2"
        )


def test_nav_modules_are_exactly_four_in_order() -> None:
    assert NAV_MODULES == ("overview", "workbench", "knowledge", "results")
    catalog = build_engine_catalog()
    assert len(catalog["nav_modules"]) == 4
    assert set(catalog["nav_module_labels_zh"]) == set(NAV_MODULES)


def test_run_summary_field_catalogue_is_complete() -> None:
    from faultevolve.common.schemas import RunSummary

    catalog = build_engine_catalog()
    assert catalog["run_summary_fields"] == sorted(RunSummary.model_fields)


def test_config_metadata_covers_every_leaf_field() -> None:
    entries = {entry["path"] for entry in config_field_metadata()}
    expected = _leaf_paths(EvolveConfig)
    assert entries == expected


def test_unannotated_fields_default_to_advanced() -> None:
    """Nothing may be silently promoted into the basic intake form."""
    for entry in config_field_metadata():
        if not entry["annotated"]:
            assert entry["advanced"] is True, entry["path"]


def test_every_annotation_matches_a_real_field() -> None:
    leafs = _leaf_paths(EvolveConfig)
    strays = sorted(set(UI_FIELD_METADATA) - leafs)
    assert strays == []


def test_every_preset_builds_a_valid_config() -> None:
    """Presets must survive the engine's own validators, not just field typing."""
    for entry in build_preset_catalog():
        merged = EvolveConfig.model_validate(entry["config"])
        assert isinstance(merged, EvolveConfig)
    assert {p.preset_id for p in PRESETS} == {"quick", "standard", "deep"}


def test_tournament_without_discovery_is_rejected() -> None:
    """The engine validator must reject a tournament that cannot discover."""
    payload = {"discovery": {"enabled": False, "tournament": {"enabled": True}}}
    with pytest.raises(ValueError, match="tournament requires discovery"):
        EvolveConfig.model_validate(payload)
    with pytest.raises(ValueError, match="tournament requires discovery"):
        EvolveConfig(
            discovery=DiscoveryConfig(
                enabled=False, tournament=TournamentConfig(enabled=True)
            )
        )


def test_from_dict_skips_the_model_validator() -> None:
    """A real gap in ``config.py``, pinned so it cannot be forgotten.

    ``EvolveConfig.from_dict`` builds ``cls()`` and then *assigns* each nested
    sub-config. Pydantic does not re-run ``model_validator(mode="after")`` on
    assignment, so ``from_yaml`` can hand the engine a tournament-without-
    discovery config that ``EvolveConfig(...)`` itself rejects. The engine then
    degrades silently -- ``engine.py`` gates the tournament on
    ``discovery.enabled and tournament.enabled`` -- instead of failing loudly.

    Delete this test once ``from_dict`` re-validates the assembled config
    (e.g. ``return cls.model_validate(config.model_dump())``).
    """
    cfg = EvolveConfig.from_dict(
        {"discovery": {"enabled": False, "tournament": {"enabled": True}}}
    )
    assert cfg.discovery.enabled is False
    assert cfg.discovery.tournament.enabled is True


def _leaf_paths(model: type, prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for name, info in model.model_fields.items():
        path = f"{prefix}{name}"
        nested = getattr(info.annotation, "model_fields", None)
        if nested is not None:
            paths |= _leaf_paths(info.annotation, prefix=f"{path}.")
        else:
            paths.add(path)
    return paths
