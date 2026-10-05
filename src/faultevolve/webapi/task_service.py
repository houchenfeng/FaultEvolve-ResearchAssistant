"""Task catalogue for the overview page and the intake form (TODO 4.1 / 4.2).

Read-only, one directory level deep, every path behind
``WebSettings.ensure_allowed``. Four rules are enforced here and pinned by
``tests/webapi/test_task_service.py`` and ``test_no_holdout_exposure.py``:

* **Protected names never travel.** Anything matching the engine's
  ``evaluator-only path`` pattern is neither listed nor probed. The pattern is
  *imported* from ``faultevolve.common.codecheck`` so the web layer cannot
  drift from the engine's own notion of "evaluator-only".
* **Stub datasets are not errors.** A directory without the four task files is
  still included when its ``evolve.yaml`` names a registered adapter; it
  reports ``ready=False`` plus a ``blocked_reason`` instead of breaking the
  listing (PRD 7.7 wants four cards, two of which are stubs).
* **No evaluator is ever imported.** "Contract check" in phase 4 means the file
  exists and parses as Python. Running foreign code belongs to the controlled
  execution path of phase 7.
* **The engine's own readiness provider is reused.** Data readiness comes from
  the adapter's ``data_status`` (existence-only by design), but its ``message``
  is discarded -- it can carry an env-var *value* such as
  ``HDD_BENCH_DATA_ROOT``, which is host configuration, not UI data.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import yaml

from faultevolve.common.codecheck import FORBIDDEN_PATTERNS
from faultevolve.config import EvolveConfig, TaskConfig
from faultevolve.tasks.protocol import DataStatus
from faultevolve.tasks.registry import ADAPTER_ALIASES, STUB_ADAPTER_DOCS
from faultevolve.webapi.contracts import (
    ContractWarning,
    TaskCardMetrics,
    TaskDatasetCardResponse,
    TaskDetailResponse,
    TaskReadinessResponse,
    TaskSummaryResponse,
)
from faultevolve.webapi.errors import TaskNotFoundError
from faultevolve.webapi.paths import is_valid_id, validate_id
from faultevolve.webapi.sanitization import sanitize
from faultevolve.webapi.settings import WebSettings

#: The engine's own definition of "evaluator-only" names, imported verbatim.
#: Re-declaring this list here would let the web layer and the engine disagree
#: the day one of them learns a new protected name.
PROTECTED_NAME_RE = re.compile(FORBIDDEN_PATTERNS["evaluator-only path"])

#: Files ``fe evolve local`` refuses to start without (src/faultevolve/cli.py).
REQUIRED_TASK_FILES = ("evaluator.py", "init.py", "problem.md", "prompt.md")

#: Fenced code blocks are stripped from summaries: they are the part of a task
#: description most likely to embed host paths, and the least useful on a card.
_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)

#: One-line summaries are for cards; full (still sanitised) documents for the
#: detail page. Both caps are way above real problem.md sizes, so a cap hit
#: means something is wrong with the file, not with the task.
_MAX_SUMMARY_CHARS = 2000
_MAX_DOCUMENT_CHARS = 20000

#: Declared UI labels, keyed by task directory name. Same precedent as
#: ``NAV_MODULE_LABELS_ZH`` in catalog.py: these cannot be derived from the
#: engine, and TODO 4.1 forbids hard-coding them in the component.
TASK_DISPLAY_NAMES: dict[str, str] = {
    "hdd_mvp": "HDD MVP",
    "backblaze_hdd": "Backblaze HDD",
    "smartmem": "SmartMem",
    "ssd_alibaba": "Alibaba SSD",
}

#: Device type per adapter (PRD 7.7's 设备类型 column).
ADAPTER_DEVICE_TYPES: dict[str, str] = {
    "hdd": "HDD",
    "backblaze": "HDD",
    "smartmem": "MEM",
    "alibaba_ssd": "SSD",
}

#: Primary metric per adapter. Only declared for adapters that actually ship
#: an evaluator; a stub card must not promise a metric it cannot compute.
ADAPTER_PRIMARY_METRICS: dict[str, str] = {
    "hdd": "ROS",
    "backblaze": "ROS",
}


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------


def task_roots(settings: WebSettings) -> list[Path]:
    """Configured task roots, resolved and de-duplicated."""
    roots: list[Path] = []
    for candidate in settings.task_roots:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved not in roots:
            roots.append(resolved)
    return roots


def task_catalog_available(settings: WebSettings) -> bool:
    """Whether at least one configured task root exists.

    ``/api/meta`` reports this so the UI can say "任务目录未配置" instead of
    showing an empty list that reads as "没有任何任务".
    """
    return any(root.is_dir() for root in task_roots(settings))


def _read_adapter(task_dir: Path) -> str:
    """Adapter declared by ``evolve.yaml``, or the engine's default.

    ``hdd_mvp`` ships no ``task:`` section, so it *is* the default case; the
    default comes from ``TaskConfig()`` rather than a literal so a change in
    the engine follows automatically.
    """
    evolve = task_dir / "evolve.yaml"
    if not evolve.is_file():
        return TaskConfig().adapter
    try:
        data = yaml.safe_load(evolve.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return TaskConfig().adapter
    task_section = data.get("task")
    if isinstance(task_section, dict):
        adapter = task_section.get("adapter")
        if isinstance(adapter, str) and adapter:
            return adapter
    return TaskConfig().adapter


def _read_target_score(task_dir: Path) -> float | None:
    """``stop.target_score`` from ``evolve.yaml``, if declared as a number."""
    evolve = task_dir / "evolve.yaml"
    if not evolve.is_file():
        return None
    try:
        data = yaml.safe_load(evolve.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    stop = data.get("stop")
    if isinstance(stop, dict):
        score = stop.get("target_score")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            return float(score)
    return None


def _registered_adapter(adapter: str) -> bool:
    return adapter in ADAPTER_ALIASES or adapter in STUB_ADAPTER_DOCS


def _is_task_dir(task_dir: Path) -> bool:
    """Inclusion rule (phase-4 plan, section 1 / 4B rule 7).

    A directory one level below a task root counts as a task when it carries
    the four-file convention (``problem.md`` or ``prompt.md`` present), **or**
    when its ``evolve.yaml`` names an adapter the engine registers. The second
    branch is what keeps the two stub datasets listed: they have neither
    ``problem.md`` nor ``prompt.md`` (verified by ``ls``), only an
    ``evolve.yaml`` with ``task.adapter``.
    """
    if (task_dir / "problem.md").is_file() or (task_dir / "prompt.md").is_file():
        return True
    if (task_dir / "evolve.yaml").is_file():
        return _registered_adapter(_read_adapter(task_dir))
    return False


def list_task_dirs(settings: WebSettings) -> list[Path]:
    """Task directories one level below each root, sorted by task id.

    Only immediate children are scanned; ``__pycache__``-style names are
    rejected by the identifier whitelist before anything is stat'ed.
    """
    found: dict[str, Path] = {}
    for root in task_roots(settings):
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for child in children:
            name = child.name
            if name in found or not is_valid_id(name):
                continue
            if not child.is_dir() or not settings.is_allowed(child):
                continue
            if _is_task_dir(child):
                found[name] = child.resolve()
    return [found[name] for name in sorted(found)]


def resolve_task_dir(settings: WebSettings, task_id: str) -> Path:
    """Resolve one task directory, or raise ``TaskNotFoundError``.

    Like ``paths.resolve_run_dir`` this is a scan of discovered directories,
    not a join: an id cannot name a path the server has not already seen.
    """
    validate_id(task_id, kind="task_id", field="task_id")
    for task_dir in list_task_dirs(settings):
        if task_dir.name == task_id:
            return task_dir
    raise TaskNotFoundError(task_id)


# --------------------------------------------------------------------------
# safe readers
# --------------------------------------------------------------------------


def _read_sanitised(task_dir: Path, filename: str, *, cap: int) -> str:
    """Read a markdown document, sanitised and capped. Never raises."""
    try:
        text = (task_dir / filename).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    cleaned = sanitize(text)[0]
    if len(cleaned) > cap:
        cleaned = cleaned[:cap] + "…"
    return cleaned


def _problem_summary(task_dir: Path) -> str:
    """One-line-ish card summary: code blocks stripped, whitespace collapsed."""
    text = _read_sanitised(task_dir, "problem.md", cap=_MAX_DOCUMENT_CHARS)
    text = _CODE_BLOCK_RE.sub("", text)
    text = " ".join(text.split())
    if len(text) > _MAX_SUMMARY_CHARS:
        text = text[:_MAX_SUMMARY_CHARS] + "…"
    return text


def _data_dirs(task_dir: Path) -> list[str]:
    """First-level subdirectory names of the task's ``data/`` directory.

    Protected names are filtered *before* sorting, and only *names* are
    returned -- never a resolved path. The filtering is what keeps the
    evaluator-only area of ``hdd_mvp`` out of the listing.
    """
    data_dir = task_dir / "data"
    try:
        children = list(data_dir.iterdir())
    except OSError:
        return []
    names = [child.name for child in children if child.is_dir()]
    return sorted(name for name in names if not PROTECTED_NAME_RE.search(name))


def _parses_as_python(path: Path) -> str | None:
    """``None`` when the file parses; otherwise a coarse failure category.

    Categories, not messages: a SyntaxError message quotes the offending line,
    which for a task file could be anything.
    """
    try:
        ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return "unreadable"
    except SyntaxError:
        return "syntax_error"
    return None


def _adapter_data_status(
    adapter: str, task_dir: Path
) -> tuple[DataStatus | None, str | None]:
    """Existence-only data readiness from the engine's own provider.

    Returns ``(status, error)``. The adapter module is imported lazily: the
    HDD adapter pulls in pandas/numpy, and ``/api/health`` must not pay for
    that. Any failure is a deployment fact reported as a category name, never
    as the exception text (which can quote host paths).
    """
    try:
        from faultevolve.tasks.registry import create_adapter

        config = EvolveConfig(task=TaskConfig(adapter=adapter))
        instance = create_adapter(config)
        return instance.data_status(task_dir), None
    except Exception as exc:  # noqa: BLE001 - reported as a category, not text
        return None, type(exc).__name__


def _knowledge_card_count(task_dir: Path) -> int | None:
    """Line count of ``knowledge/cards.jsonl``; ``None`` when absent.

    Counts only. Card *content* is served by the knowledge endpoints of an
    existing run, not by the catalogue (PRD 7.6: 展示数量，不修改统计效用).
    """
    cards = task_dir / "knowledge" / "cards.jsonl"
    try:
        with cards.open(encoding="utf-8", errors="replace") as handle:
            return sum(1 for line in handle if line.strip())
    except OSError:
        return None


def _display_name(task_dir: Path) -> str:
    fallback = task_dir.name.replace("_", " ").title()
    return TASK_DISPLAY_NAMES.get(task_dir.name, fallback)


# --------------------------------------------------------------------------
# response builders
# --------------------------------------------------------------------------


def task_summary(settings: WebSettings, task_dir: Path) -> TaskSummaryResponse:
    """One row of ``GET /api/tasks``."""
    adapter = _read_adapter(task_dir)
    return TaskSummaryResponse(
        task_id=task_dir.name,
        display_name=_display_name(task_dir),
        adapter=adapter,
        problem_summary=_problem_summary(task_dir),
        has_evaluator=(task_dir / "evaluator.py").is_file(),
        has_init=(task_dir / "init.py").is_file(),
        is_stub=adapter in STUB_ADAPTER_DOCS,
        doc_path=STUB_ADAPTER_DOCS.get(adapter),
    )


def task_detail(settings: WebSettings, task_dir: Path) -> TaskDetailResponse:
    """``GET /api/tasks/{task_id}``: the intake form's data source.

    ``problem_md`` / ``prompt_md`` are sanitised full documents, not the card
    summary: the task detail page (PRD 7.8) shows the task description.
    ``config_schema_available`` means the task ships an ``evolve.yaml``, i.e.
    a preset can incorporate its task-specific settings.
    """
    adapter = _read_adapter(task_dir)
    missing = [
        name for name in REQUIRED_TASK_FILES if not (task_dir / name).is_file()
    ]
    candidate_files = sorted(
        path.name for path in task_dir.glob("*.py") if path.is_file()
    )
    return TaskDetailResponse(
        task_id=task_dir.name,
        display_name=_display_name(task_dir),
        adapter=adapter,
        problem_md=_read_sanitised(task_dir, "problem.md", cap=_MAX_DOCUMENT_CHARS),
        prompt_md=_read_sanitised(task_dir, "prompt.md", cap=_MAX_DOCUMENT_CHARS),
        required_files=list(REQUIRED_TASK_FILES),
        missing_files=missing,
        candidate_files=candidate_files,
        data_dirs=_data_dirs(task_dir),
        knowledge_enabled=_knowledge_card_count(task_dir) is not None,
        config_schema_available=(task_dir / "evolve.yaml").is_file(),
    )


def _readiness_checks(task_dir: Path, adapter: str) -> list[ContractWarning]:
    """Blocking problems only. A healthy item simply does not appear.

    The five-state badge on the intake cards derives the "pass" state from the
    item's *absence* here plus the positive booleans on the card/detail DTOs;
    inventing a "pass" entry inside a DTO named ``ContractWarning`` would be
    the wrong shape.
    """
    checks: list[ContractWarning] = []

    if not _registered_adapter(adapter):
        checks.append(
            ContractWarning(
                field="adapter", reason=f"引擎未注册该适配器（{adapter}）"
            )
        )

    for name in ("evaluator.py", "init.py", "problem.md", "prompt.md"):
        path = task_dir / name
        if not path.is_file():
            checks.append(ContractWarning(field=name, reason="文件缺失"))
        elif name.endswith(".py"):
            failure = _parses_as_python(path)
            if failure is not None:
                checks.append(
                    ContractWarning(field=name, reason=f"无法解析（{failure}）")
                )

    status, error = _adapter_data_status(adapter, task_dir)
    if error is not None:
        checks.append(
            ContractWarning(field="data", reason=f"就绪检查不可用（{error}）")
        )
    elif status is None or not status.ok:
        # The engine's own message is discarded on purpose: it can carry an
        # env-var value. Missing *public* file names are safe to name.
        missing = [
            name
            for name in (status.missing if status else [])
            if not PROTECTED_NAME_RE.search(name)
        ]
        reason = "数据目录未就绪"
        if missing:
            reason += "：" + "、".join(missing)
        checks.append(ContractWarning(field="data", reason=reason))

    return checks


def task_readiness(
    settings: WebSettings, task_dir: Path
) -> TaskReadinessResponse:
    """``GET /api/tasks/{task_id}/readiness``: the pre-flight check."""
    adapter = _read_adapter(task_dir)
    checks = _readiness_checks(task_dir, adapter)
    return TaskReadinessResponse(
        task_id=task_dir.name,
        ready=not checks,
        checks=checks,
        adapter=adapter,
        # A resolved host path never travels to the browser; the UI addresses
        # tasks by id only. Left as None deliberately.
        resolved_path=None,
    )


def task_card(settings: WebSettings, task_dir: Path) -> TaskDatasetCardResponse:
    """``GET /api/tasks/{task_id}/card``: one overview card (PRD 7.7)."""
    adapter = _read_adapter(task_dir)
    is_stub = adapter in STUB_ADAPTER_DOCS
    detail = task_detail(settings, task_dir)
    readiness = task_readiness(settings, task_dir)

    status, _error = _adapter_data_status(adapter, task_dir)
    data_missing = [
        name
        for name in (status.missing if status else [])
        if not PROTECTED_NAME_RE.search(name)
    ]

    metrics = TaskCardMetrics(
        primary_metric=ADAPTER_PRIMARY_METRICS.get(adapter, ""),
        target_direction="higher",
        target_score=_read_target_score(task_dir),
        # No run is joined into the catalogue in phase 4: an initial score is
        # only ever a number a real evaluation produced. Until the run→task
        # link exists, the card says 待评估 rather than inventing 22.81.
        initial_score=None,
        score_source="unavailable",
    )

    blocked_reason: str | None = None
    if is_stub:
        blocked_reason = "示例数据集：尚未提供 evaluator / init 工件"
    elif detail.missing_files:
        blocked_reason = "缺少文件：" + "、".join(detail.missing_files)
    elif not readiness.ready:
        blocked_reason = "任务未就绪，见就绪检查"

    evaluator_ready = (
        (task_dir / "evaluator.py").is_file()
        and _parses_as_python(task_dir / "evaluator.py") is None
    )
    init_ready = (
        (task_dir / "init.py").is_file()
        and _parses_as_python(task_dir / "init.py") is None
    )

    return TaskDatasetCardResponse(
        task_id=task_dir.name,
        display_name=detail.display_name,
        device_type=ADAPTER_DEVICE_TYPES.get(adapter, ""),
        summary=_problem_summary(task_dir),
        adapter=adapter,
        is_stub=is_stub,
        doc_path=STUB_ADAPTER_DOCS.get(adapter),
        metrics=metrics,
        data_ready=bool(status is not None and status.ok),
        data_missing=data_missing,
        evaluator_ready=evaluator_ready,
        init_ready=init_ready,
        knowledge_card_count=_knowledge_card_count(task_dir),
        last_run_id=None,
        last_best_score=None,
        blocked_reason=blocked_reason,
    )


__all__ = [
    "PROTECTED_NAME_RE",
    "REQUIRED_TASK_FILES",
    "list_task_dirs",
    "resolve_task_dir",
    "task_card",
    "task_catalog_available",
    "task_detail",
    "task_readiness",
    "task_roots",
    "task_summary",
]
