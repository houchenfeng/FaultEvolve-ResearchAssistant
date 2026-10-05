"""Read-only replay of a finished (or still-live) run directory (TODO §2.3-2.5).

Every value returned here is *read back* from an artifact the engine wrote. The
service never recomputes a score, never infers a node's final state from the
event log, and never invents a value for a field it cannot fill -- missing data
stays ``None`` and is reported through ``ContractWarning``.

Source priority follows TODO §2.5 exactly:

1. ``tree.json`` node structure;
2. ``programs/{node_id}.py`` for code, ``logs/{node_id}.log`` for errors;
3. ``fe.db`` to *supplement* (evaluation detail, insights, llm calls, card stats).

``events.jsonl`` is the only source for ``/events``. The database's own ``event``
table can hold rows the jsonl never received (in the shipped fixture: two
``discovery_round_*`` events), so the two are compared and the difference is
surfaced as a warning instead of being silently merged.
"""

from __future__ import annotations

import difflib
import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from faultevolve.common.schemas import HypothesisStatus, NodeStatus, OperatorType
from faultevolve.webapi import paths
from faultevolve.webapi.catalog import EVENT_TYPES
from faultevolve.webapi.event_stream import select_after, split_page
from faultevolve.webapi.contracts import (
    CONTRACT_VERSION,
    ArtifactListResponse,
    ArtifactResponse,
    ArtifactState,
    ContractWarning,
    DiscoveryResponse,
    EventPageResponse,
    EventResponse,
    InsightResponse,
    InsightsResponse,
    KnowledgeCardResponse,
    NodeArtifactResponse,
    NodeDetailResponse,
    NodeEvaluationResponse,
    ReportFileResponse,
    ReportManifestResponse,
    RunDetailResponse,
    RunSummaryResponse,
    RunDataState,
    ScoreboardEntryResponse,
    ScorePointResponse,
    TreeNodeDTO,
    TreeEdgeDTO,
    TreeEdgeKind,
    TreeResponse,
)
from faultevolve.webapi.errors import (
    ArtifactInvalidJsonError,
    ArtifactMissingError,
    ArtifactNotDownloadableError,
    NodeNotFoundError,
    RunUnreadableError,
)
from faultevolve.webapi.sanitization import sanitize, sanitize_value, truncate_log
from faultevolve.webapi.settings import WebSettings
from faultevolve.webapi.sqlite_ro import connect_ro, fetch_all, has_table

#: Hard cap on the rows any single replay call will materialise. A run with a
#: million events must not be able to exhaust the server's memory.
MAX_EVENTS = 20_000
MAX_LOG_BYTES = 64 * 1024
#: A node diff is two ~1 KB programs, so this only ever bites on a pathological
#: pair. Past it the reply is marked truncated rather than silently cut.
MAX_DIFF_CHARS = 20_000


@dataclass(frozen=True)
class RunArtifacts:
    """Where each replayable artifact of one run lives.

    ``run_id`` is the *directory* name; the engine's own ``experiment_id`` is
    read out of the data. They normally coincide (``.fe/runs/{experiment_id}``)
    but are kept distinct because the shipped fixture deliberately differs.
    """

    run_id: str
    run_dir: Path
    summary_path: Path
    tree_path: Path
    events_path: Path
    db_path: Path
    programs_dir: Path
    logs_dir: Path
    discovery_dir: Path

    def existing(self) -> dict[str, bool]:
        """Which artifacts are present *and carry content*.

        For directories, "present" means "holds at least one real file": the
        shipped fixture keeps an empty ``logs/`` alive with a ``.gitkeep``, and
        calling that ``available`` would tell the UI there are logs to show.
        """
        return {
            "run_summary": self.summary_path.is_file(),
            "tree": self.tree_path.is_file(),
            "events": self.events_path.is_file(),
            "database": self.db_path.is_file(),
            "programs": _has_real_file(self.programs_dir),
            "logs": _has_real_file(self.logs_dir),
            "discovery": _has_real_file(self.discovery_dir),
        }


def _has_real_file(directory: Path) -> bool:
    """Whether ``directory`` exists and holds at least one non-hidden file."""
    if not directory.is_dir():
        return False
    try:
        return any(
            entry.is_file() and not entry.name.startswith(".")
            for entry in directory.iterdir()
        )
    except OSError:
        return False


def artifacts_for(settings: WebSettings, run_id: str) -> RunArtifacts:
    """Resolve every artifact path for one run, validating the id on the way."""
    run_dir = paths.resolve_run_dir(settings, run_id)
    child = lambda *parts: paths.resolve_run_child(run_dir, *parts)  # noqa: E731
    return RunArtifacts(
        run_id=run_id,
        run_dir=run_dir,
        summary_path=child("run_summary.json"),
        tree_path=child("tree.json"),
        events_path=child("events.jsonl"),
        db_path=child("fe.db"),
        programs_dir=child("programs"),
        logs_dir=child("logs"),
        discovery_dir=child("discovery"),
    )


# --------------------------------------------------------------------------
# primitive readers
# --------------------------------------------------------------------------


def _read_json(path: Path, name: str) -> dict[str, Any] | None:
    """Parse a JSON object, or ``None`` when the file is absent.

    Raises:
        ArtifactInvalidJsonError: the file exists but is not a JSON object.
            Only the artifact *name* travels in the error, never the path.
    """
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ArtifactInvalidJsonError(name) from exc
    if not raw.strip():
        # An empty file is "present but has nothing", not corruption.
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ArtifactInvalidJsonError(name) from exc
    return parsed if isinstance(parsed, dict) else {"_value": parsed}


def read_program(artifacts: RunArtifacts, node_id: str) -> str | None:
    """Source of one node's program, or ``None`` when it was never written."""
    path = paths.resolve_run_child(artifacts.run_dir, "programs", f"{node_id}.py")
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def read_log(artifacts: RunArtifacts, node_id: str) -> tuple[str | None, ArtifactState]:
    """Sanitized tail of one node's log plus its availability state."""
    path = paths.resolve_run_child(artifacts.run_dir, "logs", f"{node_id}.log")
    if not path.is_file():
        return None, ArtifactState.MISSING
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - MAX_LOG_BYTES))
            tail = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return None, ArtifactState.INVALID
    if not tail.strip():
        return None, ArtifactState.AVAILABLE
    cleaned, _ = sanitize(tail)
    excerpt, _ = truncate_log(cleaned)
    return excerpt, ArtifactState.AVAILABLE


def read_events(
    artifacts: RunArtifacts,
) -> tuple[list[dict[str, Any]], int, list[ContractWarning]]:
    """Parse ``events.jsonl``; skip unparseable lines instead of failing the page.

    Returns ``(events, skipped_line_count, warnings)``. A partially written file
    is the normal case for a run that was interrupted, so one broken line must
    not cost the caller the other nineteen.
    """
    warnings: list[ContractWarning] = []
    if not artifacts.events_path.is_file():
        return [], 0, warnings
    events: list[dict[str, Any]] = []
    skipped = 0
    with artifacts.events_path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            if len(events) >= MAX_EVENTS:
                warnings.append(
                    ContractWarning(
                        field="events",
                        reason=f"事件超过 {MAX_EVENTS} 条，仅返回前 {MAX_EVENTS} 条",
                    )
                )
                break
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if isinstance(row, dict):
                events.append(row)
            else:
                skipped += 1
    if skipped:
        warnings.append(
            ContractWarning(
                field="events",
                reason=f"{skipped} 行无法解析，已跳过（文件可能写入中断）",
            )
        )
    warnings.extend(_compare_event_sources(artifacts, len(events)))
    return events, skipped, warnings


def _compare_event_sources(
    artifacts: RunArtifacts, jsonl_count: int
) -> list[ContractWarning]:
    """Report a jsonl/database event-count mismatch instead of merging them.

    The jsonl is authoritative for ``/events`` (TODO §2.3). The database often
    knows about events the jsonl never received, and merging would produce a
    stream whose provenance is unknowable.
    """
    if not artifacts.db_path.is_file():
        return []
    try:
        with connect_ro(artifacts.db_path, run_id=artifacts.run_id) as conn:
            if not has_table(conn, "event"):
                return []
            row = conn.execute("SELECT COUNT(*) FROM event").fetchone()
            db_count = int(row[0]) if row else 0
    except RunUnreadableError:
        return []
    if db_count == jsonl_count:
        return []
    return [
        ContractWarning(
            field="events",
            reason=(
                f"events.jsonl 有 {jsonl_count} 条，数据库 event 表有 {db_count} 条；"
                "本接口以 events.jsonl 为准，未做合并"
            ),
        )
    ]


# --------------------------------------------------------------------------
# database supplement
# --------------------------------------------------------------------------


def _node_rows(artifacts: RunArtifacts) -> dict[str, dict[str, Any]]:
    """``node`` table keyed by node id, or ``{}`` when unavailable."""
    if not artifacts.db_path.is_file():
        return {}
    try:
        with connect_ro(artifacts.db_path, run_id=artifacts.run_id) as conn:
            rows = fetch_all(conn, "node")
    except RunUnreadableError:
        return {}
    return {str(row.get("id")): row for row in rows if row.get("id")}


def _second_parents(artifacts: RunArtifacts) -> dict[str, list[str]]:
    """Crossover partners per node, from ``node_parents.role='secondary'``.

    The engine records both parents of a crossover in ``node_parents``
    (``engine.py`` writes role ``primary``/``secondary`` when the child is
    produced), but ``tree.json``'s edge list carries no kind, so the edge alone
    cannot distinguish "second parent" from "ordinary parent". Reading the table
    is what makes TODO 5.1's three edge kinds real instead of cosmetic.

    A missing table, an unreadable database or zero rows all mean "no crossover
    happened here", which is the truthful answer -- not a warning.
    """
    if not artifacts.db_path.is_file():
        return {}
    try:
        with connect_ro(artifacts.db_path, run_id=artifacts.run_id) as conn:
            rows = fetch_all(conn, "node_parents")
    except RunUnreadableError:
        return {}

    partners: dict[str, list[str]] = {}
    for row in rows:
        if str(row.get("role") or "") != "secondary":
            continue
        node_id = str(row.get("node_id") or "")
        parent_id = str(row.get("parent_id") or "")
        if node_id and parent_id:
            partners.setdefault(node_id, []).append(parent_id)
    return partners


def _mechanism_payloads(artifacts: RunArtifacts) -> list[dict[str, Any]]:
    """Mechanisms from the ``mechanism`` table, as ``model_dump``-shaped dicts.

    TODO 6.3 needs mechanisms split by ``role`` (claim / llm_rival / confound /
    artifact / censor / other) to show "the claim, its rivals, the arguments
    for and against" as separate regions -- but ``discovery/theories.json`` is
    written as a literal ``[]`` by ``discovery/certificates.py``, and
    ``mechanisms.json`` is the file that actually carries them.

    Reading the table instead of the file also picks up mechanisms written
    before a crash, which the artifact writer only persists at the end of a
    tournament.

    A missing table, an unreadable database or zero rows all mean "no mechanism
    was established here", which is the truthful answer -- not a warning.
    """
    return _payloads_from_table(artifacts, "mechanism")


def _claim_payloads(artifacts: RunArtifacts, experiment_id: str) -> list[dict[str, Any]]:
    """Claims from the ``claim`` table, as ``model_dump``-shaped dicts.

    TODO 6.2 asks the phenomena page to show ``condition`` / ``feature`` /
    ``outcome`` / ``scope`` / ``falsifier`` next to each effect and CI. None of
    those live in the artifacts: ``discovery/phenomena.json`` stores only
    ``{claim_id, grade, payload}`` where ``payload`` is a ``ClaimTestResult``
    (split / n / effect / ci / p / e), so the claim *prose* has to come from
    somewhere else. This field is that somewhere else, and it is also the only
    source of ``status`` / ``source`` / ``prereg_hash`` per claim.

    **Read the payload with the engine's write pattern in mind.** ``payload_json``
    is written three times and the last write wins:

    1. ``create_claim`` -> ``json.dumps(claim)``: full prose.
    2. sandbox failure -> ``{"error": sb.error}``: prose **replaced**.
    3. grading -> ``{**ClaimTestResult, "grade": grade}``: prose **replaced** again.

    So a claim that reached either stage 2 or 3 no longer carries its prose
    anywhere in the run -- the mirror columns keep ``id`` / ``status`` / ``grade``
    / ``source`` / ``round`` / ``prereg_hash``, and the payload keeps the test
    result or the error. The front end is expected to render that honestly
    ("散文未记录") instead of inventing a title. Fixing the loss means changing
    ``update_claim`` call sites in ``discovery/pipeline.py`` -- engine scope,
    deliberately not done here, and it would only help runs executed afterwards.

    Filtered by ``experiment_id`` so a bundle of several runs cannot leak rows.
    """
    return _payloads_from_table(artifacts, "claim", experiment_id=experiment_id)


def _match_payloads(artifacts: RunArtifacts, experiment_id: str) -> list[dict[str, Any]]:
    """Tournament match results from the ``match`` table.

    ``DiscoveryResponse.matches`` was declared in the contract and then never
    filled: ``replay_service`` had no assignment for it, so the field was
    permanently ``[]`` and TODO 6.3's "data adjudication" column had nothing to
    show. The results do exist -- ``store.get_matches`` reads them out of this
    table -- but nothing ever wrote them into ``tournament_results.json``
    because ``engine._tournament_results`` is initialised to ``{}`` and never
    assigned before being handed to ``certificates.write_json``.

    Reading the table is therefore the only path that carries real data, and it
    filters by ``experiment_id`` so a bundle of several runs cannot leak rows.
    """
    return _payloads_from_table(artifacts, "match", experiment_id=experiment_id)


def _table_state(artifacts: RunArtifacts, table: str) -> ArtifactState:
    """``AVAILABLE`` when ``table`` exists in the run database, else ``MISSING``.

    Zero rows is still ``AVAILABLE``, matching how ``_read_json_list`` treats an
    empty-but-present json file: "the tournament produced nothing" and "this run
    has no discovery database" are different sentences, and the front end needs
    to be able to say both.

    ``fetch_all`` deliberately collapses a missing table into ``[]``, so the
    probe uses ``has_table`` directly -- otherwise the state would be a constant
    ``available`` and the two sentences would collapse into one.
    """
    if not artifacts.db_path.is_file():
        return ArtifactState.MISSING
    try:
        with connect_ro(artifacts.db_path, run_id=artifacts.run_id) as conn:
            if not has_table(conn, table):
                return ArtifactState.MISSING
    except RunUnreadableError:
        return ArtifactState.MISSING
    return ArtifactState.AVAILABLE


def _experiment_id(summary: dict[str, Any]) -> str:
    """``run_summary.experiment_id`` as text; ``""`` when absent.

    An empty value means "do not filter" -- the ``match`` table has no
    experiment column at all, so refusing to guess here would drop every row.
    Rows that *do* carry the column are still checked by the caller.
    """
    raw = summary.get("experiment_id")
    if raw is None or isinstance(raw, (dict, list)):
        return ""
    return str(raw).strip()


def _payloads_from_table(
    artifacts: RunArtifacts, table: str, *, experiment_id: str = ""
) -> list[dict[str, Any]]:
    """Decoded ``payload_json`` of every row of ``table``; ``[]`` when unusable.

    Discovery tables keep the whole object in ``payload_json`` and mirror only
    the columns the UI filters on. Reading ``payload_json`` is what gives the
    front end ``Mechanism.role`` / ``MatchResult.supports`` -- the fields TODO
    6.3 needs and the ones no column can answer.

    ``experiment_id`` filters on the **column**, before the merge below. This
    matters: a payload may itself carry an ``experiment_id`` key (``Claim`` does)
    and it may be empty, and ``{**row, **decoded}`` lets the payload win -- so a
    post-merge filter silently stops filtering. The column is the authoritative
    index; the payload's copy is prose.
    """
    if not artifacts.db_path.is_file():
        return []
    try:
        with connect_ro(artifacts.db_path, run_id=artifacts.run_id) as conn:
            rows = fetch_all(conn, table)
    except RunUnreadableError:
        return []

    payloads: list[dict[str, Any]] = []
    for row in rows:
        if experiment_id:
            column = row.get("experiment_id")
            # A row with no column value at all is kept, not dropped: "no
            # column to compare against" is not the same as "belongs elsewhere".
            if column and str(column) != experiment_id:
                continue
        raw = row.get("payload_json")
        if not isinstance(raw, str) or not raw:
            continue
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(decoded, dict):
            # Keep the mirror columns too: ``match`` rows carry family_id /
            # round in columns, and the tournament page groups by family.
            payloads.append({**row, **decoded})
    return payloads


def _offered_cards_by_branch(artifacts: RunArtifacts) -> dict[str, list[str]]:
    """Knowledge cards offered to each branch, keyed by ``branch_id``.

    ``adopted_card_ids`` answers "which cards did this node end up using", which
    is a *node* fact. PRD 10.2 also asks the tree to highlight **card propagation
    across branches**, and that is a *branch × iteration* fact the node payload
    cannot carry: it lives in ``branch_offered_cards`` (one row per offer, with
    ``iteration`` and ``was_invalid``).

    The tree is the wrong place to narrate a full propagation story -- the
    knowledge-discovery page does that -- but the node does need to say which
    cards its branch had been offered, otherwise the "N cards" badge has no
    provenance. Keyed by branch so the front end can join against
    ``TreeNodeDTO.branch_id`` without another round trip.

    A missing table or an unreadable database means "nothing was offered here",
    which is the truthful answer, not a warning.
    """
    if not artifacts.db_path.is_file():
        return {}
    try:
        with connect_ro(artifacts.db_path, run_id=artifacts.run_id) as conn:
            rows = fetch_all(conn, "branch_offered_cards")
    except RunUnreadableError:
        return {}

    # A card offered to the same branch twice is one card to the branch; keep
    # first-seen order so the UI list is stable across reloads.
    by_branch: dict[str, list[str]] = {}
    seen: set[tuple[str, str]] = set()
    for row in sorted(rows, key=lambda r: (_optional_int(r.get("iteration")) or 0)):
        branch = str(row.get("branch_id") or "")
        card = str(row.get("card_id") or "")
        if not branch or not card:
            continue
        key = (branch, card)
        if key in seen:
            continue
        seen.add(key)
        by_branch.setdefault(branch, []).append(card)
    return by_branch


def _json_field(row: dict[str, Any], column: str) -> dict[str, Any]:
    """Decode one of the DB's ``*_json`` text columns, tolerating garbage."""
    raw = row.get(column)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _list_field(row: dict[str, Any], column: str) -> list[str]:
    raw = row.get(column)
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return []


def _text_or_none(value: Any) -> str | None:
    """Return a non-empty string as-is, else ``None``.

    Used where a non-string or empty value must not be coerced: an empty
    program is "no program", not an empty-string program.
    """
    return value if isinstance(value, str) and value else None


# --------------------------------------------------------------------------
# runs
# --------------------------------------------------------------------------


def _data_state(artifacts: RunArtifacts) -> RunDataState:
    """Which artifact backs this run (TODO §2.4).

    ``run_summary.json`` parses -> COMPLETE. Only ``fe.db`` -> LIVE (the run was
    observed mid-flight). Neither -> UNREADABLE, reported rather than hidden.
    """
    try:
        summary = _read_json(artifacts.summary_path, "run_summary.json")
    except ArtifactInvalidJsonError:
        summary = None
    if summary is not None:
        return RunDataState.COMPLETE
    return RunDataState.LIVE if artifacts.db_path.is_file() else RunDataState.UNREADABLE


def list_runs(settings: WebSettings) -> list[RunSummaryResponse]:
    """One row per run directory found directly under each configured root."""
    task_ids = _registry_task_ids(settings)
    rows: list[RunSummaryResponse] = []
    for run_id in paths.list_run_ids(settings):
        artifacts = artifacts_for(settings, run_id)
        rows.append(_summary_row(artifacts, task_id=task_ids.get(run_id)))
    return rows


def _registry_task_ids(settings: WebSettings) -> dict[str, str]:
    """Map run id -> task directory name for runs this API started.

    The registry stores an absolute ``task_dir``. Only the final path component
    leaves this function. A missing registry, a missing row, or a name that is
    not a single path segment yields no entry -- the listing then omits
    ``task_id`` instead of guessing from the run directory name.
    """
    from faultevolve.webapi import run_registry

    if not run_registry.registry_configured(settings):
        return {}
    try:
        records = run_registry.list_records(settings)
    except (OSError, sqlite3.Error):
        return {}
    out: dict[str, str] = {}
    for record in records:
        name = Path(record.task_dir).name
        if not name or name in {".", ".."} or "/" in name or "\\" in name:
            continue
        out[record.run_id] = name
    return out


def _summary_row(
    artifacts: RunArtifacts, task_id: str | None = None
) -> RunSummaryResponse:
    warnings: list[ContractWarning] = []
    state = _data_state(artifacts)
    if state is RunDataState.UNREADABLE:
        return RunSummaryResponse(
            run_id=artifacts.run_id,
            data_state=state,
            task_id=task_id,
            warnings=[
                ContractWarning(
                    field="run_summary",
                    reason="既没有可读的 run_summary.json，也没有 fe.db",
                )
            ],
        )

    summary: dict[str, Any] = {}
    try:
        summary = _read_json(artifacts.summary_path, "run_summary.json") or {}
    except ArtifactInvalidJsonError as exc:
        warnings.append(ContractWarning(field="run_summary", reason=exc.detail or ""))

    if state is RunDataState.LIVE:
        # A live run has no summary yet; the database row is the honest source.
        live = _experiment_row(artifacts)
        if live is None:
            return RunSummaryResponse(
                run_id=artifacts.run_id,
                data_state=RunDataState.UNREADABLE,
                task_id=task_id,
                warnings=[
                    ContractWarning(
                        field="database", reason="fe.db 里的 experiment 表读不到记录"
                    )
                ],
            )
        return RunSummaryResponse(
            run_id=artifacts.run_id,
            data_state=state,
            task_id=task_id,
            status=live.get("status"),
            iterations_done=live.get("iterations_done"),
            best_score=live.get("best_score"),
            created_at=live.get("created_at"),
            finished_at=live.get("updated_at"),
            warnings=warnings,
        )

    return RunSummaryResponse(
        run_id=artifacts.run_id,
        data_state=state,
        task_id=task_id,
        status=summary.get("status"),
        iterations_done=summary.get("iterations_done"),
        best_score=summary.get("best_score"),
        improvement=summary.get("improvement"),
        stop_reason=summary.get("stop_reason"),
        created_at=summary.get("created_at"),
        finished_at=summary.get("finished_at"),
        warnings=warnings,
    )


def _experiment_row(artifacts: RunArtifacts) -> dict[str, Any] | None:
    try:
        with connect_ro(artifacts.db_path, run_id=artifacts.run_id) as conn:
            rows = fetch_all(conn, "experiment")
    except RunUnreadableError:
        return None
    return rows[0] if rows else None


def run_detail(settings: WebSettings, run_id: str) -> RunDetailResponse:
    """Grouped run-level view. Every group is ``None`` when unreadable."""
    from faultevolve.webapi import replay_groups

    artifacts = artifacts_for(settings, run_id)
    state = _data_state(artifacts)
    warnings: list[ContractWarning] = []
    summary: dict[str, Any] = {}
    try:
        summary = _read_json(artifacts.summary_path, "run_summary.json") or {}
    except ArtifactInvalidJsonError as exc:
        warnings.append(ContractWarning(field="run_summary", reason=exc.detail or ""))

    if state is RunDataState.UNREADABLE and not summary:
        raise RunUnreadableError(run_id)

    artifact_states = {
        name: (ArtifactState.AVAILABLE if present else ArtifactState.MISSING)
        for name, present in artifacts.existing().items()
    }

    return RunDetailResponse(
        contract_version=CONTRACT_VERSION,
        run_id=run_id,
        data_state=state,
        outcome=replay_groups.outcome(summary) if summary else None,
        budget=replay_groups.budget(summary) if summary else None,
        repair=replay_groups.repair(summary) if summary else None,
        knowledge=replay_groups.knowledge(summary) if summary else None,
        discovery=replay_groups.discovery_counters(summary) if summary else None,
        judge=replay_groups.judge(summary) if summary else None,
        operators=replay_groups.operators(summary) if summary else None,
        artifact_states=artifact_states,
        warnings=warnings,
    )


# --------------------------------------------------------------------------
# tree / nodes
# --------------------------------------------------------------------------


def _parents_from_edges(edges: list[dict[str, Any]]) -> dict[str, str]:
    """First incoming edge per target, i.e. the node's primary parent."""
    parents: dict[str, str] = {}
    for edge in edges:
        target = edge.get("target")
        source = edge.get("source")
        if isinstance(target, str) and isinstance(source, str):
            parents.setdefault(target, source)
    return parents


def _enum_or_fail(enum_cls: Any, value: Any, run_id: str, field_name: str) -> Any:
    """Parse an engine enum value, failing loudly on an unknown one.

    Silently substituting a default would mislabel a node's operator or status,
    which is exactly the kind of quiet wrongness the project forbids. The
    contract drift test catches a new engine value long before a user hits it.
    """
    try:
        return enum_cls(value)
    except ValueError as exc:
        raise RunUnreadableError(
            run_id, f"tree.json has an unknown {field_name}: {value!r}"
        ) from exc


def _build_tree(artifacts: RunArtifacts) -> tuple[
    list[TreeNodeDTO], list[TreeEdgeDTO], list[ContractWarning]
]:
    warnings: list[ContractWarning] = []
    raw = _read_json(artifacts.tree_path, "tree.json")
    if raw is None:
        return [], [], [
            ContractWarning(field="tree", reason="没有 tree.json，无法还原进化树")
        ]

    raw_nodes = raw.get("nodes") or []
    raw_edges = raw.get("edges") or []
    if not isinstance(raw_nodes, list):
        raise ArtifactInvalidJsonError("tree.json")

    db_nodes = _node_rows(artifacts)
    parents = _parents_from_edges([e for e in raw_edges if isinstance(e, dict)])
    if db_nodes:
        parents = _reconcile_parents(parents, db_nodes, warnings)
    second_parents = _second_parents(artifacts)
    offered_by_branch = _offered_cards_by_branch(artifacts)

    nodes: list[TreeNodeDTO] = []
    for item in raw_nodes:
        if not isinstance(item, dict) or not item.get("id"):
            warnings.append(
                ContractWarning(field="tree.nodes", reason="存在缺少 id 的节点，已跳过")
            )
            continue
        node_id = str(item["id"])
        db_row = db_nodes.get(node_id, {})
        evidence = _json_field(db_row, "evidence_json")
        repair_parent = db_row.get("repair_parent_id")
        delta = _optional_float(evidence.get("delta_score"))
        noise = _optional_float(evidence.get("noise_delta"))
        branch_id = str(item.get("branch_id") or "")
        nodes.append(
            TreeNodeDTO(
                id=node_id,
                parent_id=parents.get(node_id),
                second_parent_ids=second_parents.get(node_id, []),
                branch_id=branch_id,
                depth=int(item.get("depth") or 0),
                operator=_enum_or_fail(OperatorType, item.get("operator"), artifacts.run_id, "operator"),
                score=_optional_float(item.get("score")),
                delta_score=delta,
                noise_delta=noise,
                # Same pure function the score timeline uses, so a node and its
                # score point can never disagree about the noise band.
                within_noise_band=_within_noise(delta, noise),
                status=_enum_or_fail(NodeStatus, item.get("status"), artifacts.run_id, "node status"),
                hypothesis_status=_enum_or_fail(
                    HypothesisStatus, item.get("hypothesis_status"), artifacts.run_id,
                    "hypothesis status",
                ),
                intent=str(item.get("intent") or ""),
                visit_count=_optional_int(item.get("visit_count")),
                adopted_card_ids=[str(c) for c in (item.get("adopted_cards") or [])],
                offered_card_ids=offered_by_branch.get(branch_id, []),
                insight_ids=_list_field(db_row, "insight_ids_json"),
                repair_parent_id=str(repair_parent) if repair_parent else None,
                repair_count=_optional_int(db_row.get("repair_count")),
                repair_attempted=_optional_bool(db_row.get("repair_attempted")),
                repair_exhausted=_optional_bool(db_row.get("repair_exhausted")),
                error_class=(str(db_row.get("error_class")) or None)
                if db_row.get("error_class")
                else None,
            )
        )

    edges = _build_edges(nodes, raw_edges, warnings)
    return nodes, edges, warnings


def _build_edges(
    nodes: list[TreeNodeDTO],
    raw_edges: list[Any],
    warnings: list[ContractWarning],
) -> list[TreeEdgeDTO]:
    """Edges with their kind restored (TODO 5.1).

    ``tree.json`` stores one flat edge list, so every edge arrives here as an
    unlabelled connection. The kind comes from two other places: the engine's
    ``node_parents`` table (via ``TreeNodeDTO.second_parent_ids``) and each
    node's ``repair_parent_id``. Without them the UI would draw every
    relationship identically, which is exactly the quiet wrongness PRD §9.8
    forbids.

    A relationship that is recorded twice (a second parent that also appears in
    the edge list) is emitted **once per kind**: the crossover label is the more
    specific fact, and the plain parent edge is kept so a reader that ignores
    kinds still sees the connection.
    """
    known = {node.id for node in nodes}
    seen: set[tuple[str, str, TreeEdgeKind]] = set()
    edges: list[TreeEdgeDTO] = []

    def add(source: str, target: str, kind: TreeEdgeKind) -> None:
        key = (source, target, kind)
        if key in seen:
            return
        seen.add(key)
        edges.append(TreeEdgeDTO(source=source, target=target, kind=kind))

    for edge in raw_edges:
        if not isinstance(edge, dict) or not edge.get("source") or not edge.get("target"):
            continue
        add(str(edge["source"]), str(edge["target"]), TreeEdgeKind.PARENT)

    for node in nodes:
        for partner in node.second_parent_ids:
            if partner not in known:
                warnings.append(
                    ContractWarning(
                        field=f"tree.edges.{node.id}",
                        reason=f"crossover 第二父 {partner} 不在节点列表中，已保留节点但无法连线",
                    )
                )
                continue
            add(partner, node.id, TreeEdgeKind.CROSSOVER_SECOND_PARENT)
        if node.repair_parent_id:
            if node.repair_parent_id not in known:
                warnings.append(
                    ContractWarning(
                        field=f"tree.edges.{node.id}",
                        reason=(
                            f"修复来源节点 {node.repair_parent_id} 不在节点列表中，"
                            "已保留节点但无法连线"
                        ),
                    )
                )
            else:
                add(node.repair_parent_id, node.id, TreeEdgeKind.REPAIR)

    return edges


def _reconcile_parents(
    parents: dict[str, str], db_nodes: dict[str, dict[str, Any]],
    warnings: list[ContractWarning],
) -> dict[str, str]:
    """Prefer the database's ``parent_id`` when it disagrees with the edges.

    The database column is written directly by the engine, while the edge list is
    a derived export. A disagreement is reported either way -- it means one of
    the two artifacts is stale, and the UI should not silently pick a winner.
    """
    merged = dict(parents)
    conflicts: list[str] = []
    for node_id, row in db_nodes.items():
        db_parent = row.get("parent_id")
        db_parent = str(db_parent) if db_parent else None
        edge_parent = parents.get(node_id)
        if db_parent != edge_parent:
            conflicts.append(node_id)
        if db_parent is None:
            merged.pop(node_id, None)
        else:
            merged[node_id] = db_parent
    if conflicts:
        warnings.append(
            ContractWarning(
                field="tree.parents",
                reason=(
                    f"{len(conflicts)} 个节点的父子关系在 tree.json 与数据库之间不一致，"
                    "已采用数据库记录"
                ),
            )
        )
    return merged


def tree(settings: WebSettings, run_id: str) -> TreeResponse:
    """Whole-tree payload, with the best path marked."""
    artifacts = artifacts_for(settings, run_id)
    nodes, edges, warnings = _build_tree(artifacts)
    summary = _safe_summary(artifacts)
    best_node_id = summary.get("best_node_id") if summary else None
    best_node_id = str(best_node_id) if best_node_id else None

    by_id = {node.id: node for node in nodes}
    if best_node_id and best_node_id not in by_id:
        warnings.append(
            ContractWarning(
                field="best_node_id",
                reason="run_summary 里的最佳节点不在树中，最佳路径无法标出",
            )
        )
        best_node_id = None

    best_path: list[str] = []
    if best_node_id:
        cursor: str | None = best_node_id
        seen: set[str] = set()
        while cursor and cursor not in seen:
            seen.add(cursor)
            best_path.append(cursor)
            cursor = by_id[cursor].parent_id if cursor in by_id else None
        best_path.reverse()

    marked = [
        node.model_copy(
            update={
                "is_best": node.id == best_node_id,
                "is_on_best_path": node.id in set(best_path),
            }
        )
        for node in nodes
    ]
    return TreeResponse(
        contract_version=CONTRACT_VERSION,
        run_id=run_id,
        data_state=_data_state(artifacts),
        nodes=marked,
        edges=edges,
        best_node_id=best_node_id,
        best_path=best_path,
        warnings=warnings,
    )


def node_detail(settings: WebSettings, run_id: str, node_id: str) -> NodeDetailResponse:
    """Everything the node drawer shows (TODO §2.5)."""
    paths.validate_id(node_id, kind="node_id", field="node_id")
    artifacts = artifacts_for(settings, run_id)
    nodes, _edges, warnings = _build_tree(artifacts)
    match = next((node for node in nodes if node.id == node_id), None)
    if match is None:
        raise NodeNotFoundError(node_id)

    db_nodes = _node_rows(artifacts)
    db_row = db_nodes.get(node_id, {})
    artifact_json = _json_field(db_row, "artifact_json")
    code = _text_or_none(artifact_json.get("code")) or read_program(artifacts, node_id)
    artifact = NodeArtifactResponse(
        node_id=node_id,
        code=code,
        intent=str(artifact_json.get("intent") or match.intent or ""),
        hypothesis=str(artifact_json.get("hypothesis") or ""),
        state=ArtifactState.AVAILABLE if code else ArtifactState.MISSING,
    )

    evaluation = _evaluation_from(db_row, node_id, warnings)

    code_diff, diff_truncated = _code_diff(
        artifacts, db_nodes, node_id, match.parent_id, warnings
    )

    log_excerpt, log_state = read_log(artifacts, node_id)
    if log_state is ArtifactState.MISSING:
        warnings.append(
            ContractWarning(field="log", reason="该节点没有日志文件（本次运行未产生 logs/）")
        )

    events, _skipped, _warn = read_events(artifacts)
    event_ids = [
        int(event["id"])
        for event in events
        if isinstance(event.get("payload"), dict)
        and event["payload"].get("node_id") == node_id
        and isinstance(event.get("id"), int)
    ]
    llm_count, llm_tokens = _llm_usage(artifacts, node_id)

    return NodeDetailResponse(
        contract_version=CONTRACT_VERSION,
        run_id=run_id,
        node=match,
        artifact=artifact,
        evaluation=evaluation,
        insights=list(_list_field(db_row, "insight_ids_json")),
        adopted_card_ids=list(_list_field(db_row, "card_ids_json")) or match.adopted_card_ids,
        log_state=log_state,
        log_excerpt=log_excerpt,
        event_ids=event_ids,
        llm_call_count=llm_count,
        llm_tokens=llm_tokens,
        code_diff=code_diff,
        code_diff_truncated=diff_truncated,
        warnings=warnings,
    )


def _code_for(
    artifacts: RunArtifacts, db_nodes: dict[str, dict[str, Any]], node_id: str
) -> str | None:
    """A node's program text: the database copy first, then the side-car file."""
    artifact_json = _json_field(db_nodes.get(node_id, {}), "artifact_json")
    return _text_or_none(artifact_json.get("code")) or read_program(artifacts, node_id)


def _code_diff(
    artifacts: RunArtifacts,
    db_nodes: dict[str, dict[str, Any]],
    node_id: str,
    parent_id: str | None,
    warnings: list[ContractWarning],
) -> tuple[str | None, bool]:
    """Unified diff of a node's program against its primary parent's (TODO §5.3).

    Only the primary parent is used. ``second_parent_ids`` is always empty
    because the engine records no second-parent column, so a multi-parent merge
    diff would require data that does not exist -- and a merge diff over one
    parent would be a quieter lie than refusing.

    When either program is unavailable the answer is ``None`` plus a warning
    naming the node, never an empty string that reads as "identical".
    """
    if not parent_id:
        return None, False
    child_code = _code_for(artifacts, db_nodes, node_id)
    parent_code = _code_for(artifacts, db_nodes, parent_id)
    if child_code is None or parent_code is None:
        missing = node_id if child_code is None else parent_id
        warnings.append(
            ContractWarning(
                field="code_diff",
                reason=f"节点 {missing} 没有可用代码，无法生成与父节点的差异",
            )
        )
        return None, False
    diff = "\n".join(
        difflib.unified_diff(
            parent_code.splitlines(),
            child_code.splitlines(),
            fromfile=f"{parent_id}.py",
            tofile=f"{node_id}.py",
            lineterm="",
        )
    )
    if len(diff) > MAX_DIFF_CHARS:
        warnings.append(
            ContractWarning(field="code_diff", reason="与父节点的差异过长，已截断")
        )
        return diff[:MAX_DIFF_CHARS], True
    return diff, False


def _evaluation_from(
    db_row: dict[str, Any], node_id: str, warnings: list[ContractWarning]
) -> NodeEvaluationResponse | None:
    evidence = _json_field(db_row, "evidence_json")
    evaluation = evidence.get("evaluation")
    if not isinstance(evaluation, dict):
        warnings.append(
            ContractWarning(field="evaluation", reason="数据库里没有该节点的评测记录")
        )
        return None
    metric = evaluation.get("metric")
    return NodeEvaluationResponse(
        node_id=node_id,
        validity=_optional_float(evaluation.get("validity")),
        combined_score=_optional_float(evaluation.get("combined_score")),
        cost_time=_optional_float(evaluation.get("cost_time")),
        error_info=(str(evaluation.get("error_info")) or None)
        if evaluation.get("error_info")
        else None,
        delta_score=_optional_float(evidence.get("delta_score")),
        noise_delta=_optional_float(evidence.get("noise_delta")),
        metric=metric if isinstance(metric, dict) else {},
    )


def _llm_usage(artifacts: RunArtifacts, node_id: str) -> tuple[int | None, int | None]:
    if not artifacts.db_path.is_file():
        return None, None
    try:
        with connect_ro(artifacts.db_path, run_id=artifacts.run_id) as conn:
            rows = fetch_all(conn, "llm_call")
    except RunUnreadableError:
        return None, None
    mine = [row for row in rows if str(row.get("node_id")) == node_id]
    if not mine:
        return 0, 0
    tokens = sum(
        int(row.get("prompt_tokens") or 0) + int(row.get("completion_tokens") or 0)
        for row in mine
    )
    return len(mine), tokens


# --------------------------------------------------------------------------
# events / scores
# --------------------------------------------------------------------------


def events_page(
    settings: WebSettings,
    run_id: str,
    *,
    after_id: int | None = None,
    limit: int | None = None,
) -> EventPageResponse:
    """One page of the event timeline, keyed on ``events.jsonl`` ids."""
    artifacts = artifacts_for(settings, run_id)
    events, _skipped, warnings = read_events(artifacts)
    # `select_after` / `split_page` are the same rules the SSE stream uses, on
    # purpose: if the polling path and the stream each grew their own cursor
    # logic, a client could re-enter an event on one path and not the other,
    # which is exactly the duplicate-delivery case PRD §16.3 forbids.
    selected = select_after(events, after_id)
    page, has_more = split_page(selected, limit)

    responses = [_event_response(e, run_id) for e in page]
    last_event_id = max((r.id for r in responses if r.id is not None), default=None)
    return EventPageResponse(
        contract_version=CONTRACT_VERSION,
        run_id=run_id,
        events=responses,
        last_event_id=last_event_id,
        has_more=has_more,
        data_state=_data_state(artifacts),
        warnings=warnings,
    )


def event_responses(
    events: Sequence[dict[str, Any]], run_id: str
) -> list[EventResponse]:
    """Sanitized, contract-shaped responses for raw event dicts.

    Public because the SSE stream (:mod:`faultevolve.webapi.stream_service`)
    renders the *same* objects into frames. Keeping one function is the point:
    sanitisation and the response shape have a single gate, so the stream and
    the polling endpoint cannot drift into disagreeing about what a payload
    looks like -- or about what was redacted from it.
    """
    return [_event_response(event, run_id) for event in events]


def contract_version() -> str:
    """The contract version this module's responses carry."""
    return CONTRACT_VERSION


def _event_response(event: dict[str, Any], run_id: str) -> EventResponse:
    payload = event.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    cleaned, _report = sanitize_value(payload)
    event_type = str(event.get("type") or "")
    return EventResponse(
        id=event.get("id") if isinstance(event.get("id"), int) else None,
        run_id=str(event.get("experiment_id") or run_id),
        type=event_type,
        payload=cleaned if isinstance(cleaned, dict) else {},
        ts=str(event.get("ts") or ""),
        is_known_type=event_type in EVENT_TYPES,
    )


def score_points(settings: WebSettings, run_id: str) -> list[ScorePointResponse]:
    """Score timeline, one point per evaluated node.

    ``iteration`` is the node's ``depth``: the engine seeds at depth 0 and refines
    one level per iteration, so depth *is* the round index. No value here is
    recomputed -- they are read from the evaluator's own record.
    """
    artifacts = artifacts_for(settings, run_id)
    nodes, _edges, _warnings = _build_tree(artifacts)
    rows = _node_rows(artifacts)
    points = [
        ScorePointResponse(
            iteration=node.depth,
            node_id=node.id,
            score=node.score,
            delta_score=node.delta_score,
            noise_delta=node.noise_delta,
            within_noise_band=_within_noise(node.delta_score, node.noise_delta),
            operator=node.operator,
            ts=str(rows.get(node.id, {}).get("created_at") or "") or None,
        )
        for node in nodes
    ]
    return sorted(points, key=lambda p: (p.iteration if p.iteration is not None else 0, p.node_id))


def _within_noise(delta: float | None, noise: float | None) -> bool | None:
    """Whether an improvement is inside the noise band. ``None`` when unknown."""
    if delta is None or noise is None:
        return None
    return abs(delta) <= abs(noise)


def leaderboard(settings: WebSettings, run_id: str) -> list[ScoreboardEntryResponse]:
    """Nodes ranked by evaluator score; unscored nodes sort last."""
    artifacts = artifacts_for(settings, run_id)
    nodes, _edges, _warnings = _build_tree(artifacts)
    summary = _safe_summary(artifacts)
    best = summary.get("best_node_id") if summary else None

    ordered = sorted(
        nodes,
        key=lambda n: (n.score is None, -(n.score or 0.0), n.id),
    )
    return [
        ScoreboardEntryResponse(
            rank=index + 1,
            node_id=node.id,
            score=node.score,
            operator=node.operator,
            depth=node.depth,
            is_best=bool(best) and node.id == best,
        )
        for index, node in enumerate(ordered)
    ]


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def _safe_summary(artifacts: RunArtifacts) -> dict[str, Any]:
    try:
        return _read_json(artifacts.summary_path, "run_summary.json") or {}
    except ArtifactInvalidJsonError:
        return {}


def _optional_float(value: Any) -> float | None:
    """Coerce to float, keeping ``None`` as ``None`` -- never as ``0``."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    """Map SQLite's 0/1 integer booleans, preserving NULL as ``None``."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    return None


def iter_run_ids(settings: WebSettings) -> Iterator[str]:
    """Convenience iterator used by the routes layer."""
    yield from paths.list_run_ids(settings)


# --------------------------------------------------------------------------
# knowledge / insights / discovery (TODO §2.6)
# --------------------------------------------------------------------------

#: Discovery artifacts the engine may write, in the order ``write_artifacts``
#: would produce them. Missing ones are simply absent from the reply.
_DISCOVERY_FILES: tuple[str, ...] = (
    "phenomena.json",
    "preregistration.json",
    "controls.json",
    "discovered_cards.snapshot.jsonl",
    "mechanisms.json",
    "certificates.json",
    "tournament_results.json",
    "theories.json",
)

#: Suffixes the report manifest is willing to expose.
_REPORT_SUFFIXES = frozenset({".md", ".json", ".csv", ".html", ".txt"})

_MEDIA_TYPES: dict[str, str] = {
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".py": "text/x-python",
    ".log": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".html": "text/html",
    ".txt": "text/plain",
    ".db": "application/vnd.sqlite3",
}

#: Artifact kinds that are listed but never served as a download (PRD §13.4).
#: The database and raw logs are engine internals: the UI needs to know they
#: exist, but they are not public deliverables.
_NON_DOWNLOADABLE_KINDS = frozenset({"database", "log"})


def _media_type(name: str) -> str:
    return _MEDIA_TYPES.get(Path(name).suffix.lower(), "application/octet-stream")


def _size_bytes(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def _read_json_list(path: Path, name: str) -> tuple[list[dict[str, Any]], ArtifactState]:
    """Parse a JSON *list* artifact such as ``discovery/phenomena.json``.

    The engine writes ``[]`` for "nothing found", which is *available and
    empty* -- not missing, and not the same as a file that was never written.
    A corrupt file raises; an unexpected object shape is wrapped in a one-item
    list so the data still reaches the caller rather than being dropped.
    """
    if not path.is_file():
        return [], ArtifactState.MISSING
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ArtifactInvalidJsonError(name) from exc
    if not raw.strip():
        return [], ArtifactState.AVAILABLE
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ArtifactInvalidJsonError(name) from exc
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)], ArtifactState.AVAILABLE
    if isinstance(parsed, dict):
        return [parsed], ArtifactState.AVAILABLE
    return [], ArtifactState.AVAILABLE


def _read_discovered_cards(path: Path) -> tuple[list[str], ArtifactState]:
    """Card ids from ``discovered_cards.snapshot.jsonl`` plus its state.

    A 0-byte snapshot -- what the fixture ships -- means the run discovered no
    cards, so the answer is ``[]``/AVAILABLE, never MISSING.
    """
    if not path.is_file():
        return [], ArtifactState.MISSING
    ids: list[str] = []
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    card = row.get("card_id") or row.get("id")
                    if card:
                        ids.append(str(card))
    except OSError:
        return [], ArtifactState.INVALID
    return ids, ArtifactState.AVAILABLE


def _db_tables(
    artifacts: RunArtifacts, names: tuple[str, ...]
) -> dict[str, list[dict[str, Any]]]:
    """Read several tables over one read-only connection.

    Every table maps to ``[]`` when the database is absent or unreadable, so a
    caller never has to distinguish "no database" from "no rows".
    """
    empty = {name: [] for name in names}
    if not artifacts.db_path.is_file():
        return empty
    try:
        with connect_ro(artifacts.db_path, run_id=artifacts.run_id) as conn:
            return {name: fetch_all(conn, name) for name in names}
    except RunUnreadableError:
        return empty


def knowledge_cards(settings: WebSettings, run_id: str) -> list[KnowledgeCardResponse]:
    """How the run used each knowledge card (TODO §2.6).

    ``card_stats`` carries the effect counters; the three relation tables carry
    *which* iterations offered a card and which nodes adopted it. Prose is
    copied from the registered task's knowledge catalog when the card id
    matches. Without that match the prose fields stay empty.
    """
    from faultevolve.webapi.knowledge_catalog import catalog_for_task

    artifacts = artifacts_for(settings, run_id)
    catalog = catalog_for_task(settings, _registry_task_ids(settings).get(run_id))
    summary = _safe_summary(artifacts)
    tables = _db_tables(
        artifacts,
        (
            "card_stats",
            "branch_offered_cards",
            "branch_refuted_cards",
            "node_adopted_cards",
        ),
    )

    db_stats = {
        str(row["card_id"]): row for row in tables["card_stats"] if row.get("card_id")
    }
    summary_stats = {
        str(item["card_id"]): item
        for item in (summary.get("card_stats") or [])
        if isinstance(item, dict) and item.get("card_id")
    }

    offered: dict[str, int] = {}
    for row in tables["branch_offered_cards"]:
        card = row.get("card_id")
        if card:
            offered[str(card)] = offered.get(str(card), 0) + 1

    refuted: dict[str, int] = {}
    for row in tables["branch_refuted_cards"]:
        card = row.get("card_id")
        if card:
            refuted[str(card)] = refuted.get(str(card), 0) + 1

    adopted: dict[str, list[str]] = {}
    for row in tables["node_adopted_cards"]:
        card, node = row.get("card_id"), row.get("node_id")
        if card and node:
            adopted.setdefault(str(card), []).append(str(node))

    nodes, _edges, _warnings = _build_tree(artifacts)
    depth = {node.id: node.depth for node in nodes}

    cards: list[KnowledgeCardResponse] = []
    for card_id in sorted(set(db_stats) | set(summary_stats) | set(offered) | set(adopted)):
        db_row = db_stats.get(card_id, {})
        summary_row = summary_stats.get(card_id, {})

        n = _optional_int(db_row.get("n"))
        if n is None:
            n = _optional_int(summary_row.get("n"))
        sum_delta = _optional_float(db_row.get("sum_delta"))
        if n and sum_delta is not None:
            mean_delta: float | None = sum_delta / n
        else:
            # n == 0 means "never had a valid adoption" -- the mean is unknown,
            # not zero.
            mean_delta = _optional_float(summary_row.get("mean_delta"))

        refuted_count = _optional_int(db_row.get("refuted_count"))
        if refuted_count is None:
            refuted_count = refuted.get(card_id)
        if refuted_count is None:
            refuted_count = _optional_int(summary_row.get("refuted"))

        adopted_nodes = adopted.get(card_id, [])
        prose = catalog.get(card_id)
        cards.append(
            KnowledgeCardResponse(
                card_id=card_id,
                title=prose.title if prose else None,
                category=prose.category if prose else None,
                source_kind=prose.source_kind if prose else None,
                source_detail=prose.source_detail if prose else None,
                claim=prose.claim if prose else None,
                conditions=prose.conditions if prose else None,
                priority=prose.priority if prose else None,
                sources=list(prose.sources) if prose else [],
                offered_count=offered.get(card_id),
                adopted_count=len(adopted_nodes) if adopted_nodes else None,
                refuted_count=refuted_count,
                invalid_count=_optional_int(db_row.get("invalid_count")),
                mean_delta=mean_delta,
                adopted_iterations=sorted(
                    {depth[node_id] for node_id in adopted_nodes if node_id in depth}
                ),
                adopted_node_ids=adopted_nodes,
            )
        )
    return cards


def insights(settings: WebSettings, run_id: str) -> InsightsResponse:
    """Reflection insights from the ``insight`` table.

    ``available`` separates "this run carries no insight table" from "the table
    exists and is empty"; conflating them would make the UI report a bug where
    there is only an empty run.
    """
    artifacts = artifacts_for(settings, run_id)
    if not artifacts.db_path.is_file():
        return InsightsResponse(
            contract_version=CONTRACT_VERSION,
            run_id=run_id,
            available=False,
            warnings=[
                ContractWarning(field="database", reason="没有 fe.db，无法读取 insight 表")
            ],
        )
    try:
        with connect_ro(artifacts.db_path, run_id=artifacts.run_id) as conn:
            if not has_table(conn, "insight"):
                return InsightsResponse(
                    contract_version=CONTRACT_VERSION,
                    run_id=run_id,
                    available=False,
                    warnings=[
                        ContractWarning(field="insight", reason="该运行没有 insight 表")
                    ],
                )
            rows = fetch_all(conn, "insight")
    except RunUnreadableError as exc:
        return InsightsResponse(
            contract_version=CONTRACT_VERSION,
            run_id=run_id,
            available=False,
            warnings=[ContractWarning(field="database", reason=exc.detail or "")],
        )

    items = [
        InsightResponse(
            insight_id=str(row.get("id")),
            origin_node=_str_or_none(row.get("origin_node")),
            branch_id=_str_or_none(row.get("branch_id")),
            polarity=_str_or_none(row.get("polarity")),
            payload=_json_field(row, "payload_json"),
            delta=_optional_float(row.get("delta")),
            z_score=_optional_float(row.get("z_score")),
            created_at=_str_or_none(row.get("created_at")),
        )
        for row in rows
        if row.get("id") is not None
    ]
    return InsightsResponse(
        contract_version=CONTRACT_VERSION,
        run_id=run_id,
        available=True,
        insights=items,
    )


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _discovery_round_event_count(artifacts: RunArtifacts) -> int:
    """How many ``discovery_round_*`` rows the database recorded."""
    if not artifacts.db_path.is_file():
        return 0
    try:
        with connect_ro(artifacts.db_path, run_id=artifacts.run_id) as conn:
            if not has_table(conn, "event"):
                return 0
            row = conn.execute(
                "SELECT COUNT(*) FROM event WHERE type LIKE 'discovery_round%'"
            ).fetchone()
            return int(row[0]) if row else 0
    except Exception:  # noqa: BLE001 - a diagnostic count must never fail the page
        return 0


def discovery(settings: WebSettings, run_id: str) -> DiscoveryResponse:
    """Discovery pipeline artifacts (TODO §2.6).

    Also reports the jsonl/database disagreement about discovery rounds: the
    shipped fixture's database holds two ``discovery_round_*`` events while
    ``run_summary.discovery_rounds`` is 0. Surfacing that is the whole point of
    "real over complete" -- the numbers are not silently reconciled.
    """
    artifacts = artifacts_for(settings, run_id)
    warnings: list[ContractWarning] = []

    phenomena, phenomena_state = _read_json_list(
        paths.resolve_run_child(artifacts.run_dir, "discovery", "phenomena.json"),
        "discovery/phenomena.json",
    )
    preregistration, preregistration_state = _read_json_list(
        paths.resolve_run_child(artifacts.run_dir, "discovery", "preregistration.json"),
        "discovery/preregistration.json",
    )
    controls, controls_state = _read_json_list(
        paths.resolve_run_child(artifacts.run_dir, "discovery", "controls.json"),
        "discovery/controls.json",
    )
    certificates, _ = _read_json_list(
        paths.resolve_run_child(artifacts.run_dir, "discovery", "certificates.json"),
        "discovery/certificates.json",
    )
    # ``theories.json`` is a literal ``[]`` written by ``certificates.write_json``
    # -- the real mechanisms live in the ``mechanism`` table, so read that.
    # Kept under the contract's name so the front end has one field to render.
    theories = _mechanism_payloads(artifacts)
    discovered_ids, discovered_state = _read_discovered_cards(
        paths.resolve_run_child(
            artifacts.run_dir, "discovery", "discovered_cards.snapshot.jsonl"
        )
    )

    summary = _safe_summary(artifacts)
    experiment_id = _experiment_id(summary)
    claims = _claim_payloads(artifacts, experiment_id)
    matches = _match_payloads(artifacts, experiment_id)
    mechanisms_state = _table_state(artifacts, "mechanism")
    matches_state = _table_state(artifacts, "match")
    claims_state = _table_state(artifacts, "claim")
    rounds = _optional_int(summary.get("discovery_rounds"))
    round_events = _discovery_round_event_count(artifacts)
    if rounds == 0 and round_events > 0:
        warnings.append(
            ContractWarning(
                field="discovery",
                reason=(
                    f"run_summary.discovery_rounds=0，但数据库中有 {round_events} 条 "
                    "discovery_round_* 事件；本接口原样上报，不做合并"
                ),
            )
        )

    return DiscoveryResponse(
        contract_version=CONTRACT_VERSION,
        run_id=run_id,
        enabled=artifacts.existing()["discovery"],
        phenomena_state=phenomena_state,
        preregistration_state=preregistration_state,
        controls_state=controls_state,
        discovered_cards_state=discovered_state,
        mechanisms_state=mechanisms_state,
        matches_state=matches_state,
        claims_state=claims_state,
        phenomena=phenomena,
        controls=controls,
        preregistration=preregistration,
        claims=claims,
        discovered_card_ids=discovered_ids,
        matches=matches,
        certificates=certificates,
        theories=theories,
        warnings=warnings,
    )


# --------------------------------------------------------------------------
# artifacts (TODO §2.6)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ArtifactEntry:
    """One server-minted artifact id and the file it names.

    The id is what the client sees; the path never leaves this module. Download
    looks the id up in a freshly built catalog rather than joining a path from
    user input, so a traversal attempt has nothing to traverse.
    """

    artifact_id: str
    path: Path
    kind: str
    display_name: str
    media_type: str
    downloadable: bool


def _safe_stems(directory: Path, suffix: str) -> list[str]:
    """Node ids of ``{id}{suffix}`` files, skipping anything not id-shaped."""
    if not directory.is_dir():
        return []
    stems: list[str] = []
    try:
        for entry in directory.iterdir():
            if not entry.is_file() or entry.suffix != suffix:
                continue
            stem = entry.stem
            if paths.is_valid_id(stem):
                stems.append(stem)
    except OSError:
        return []
    return sorted(stems)


def _report_names(artifacts: RunArtifacts) -> list[str]:
    """File names of already-exported reports, if a ``reports/`` dir exists."""
    directory = paths.resolve_run_child(artifacts.run_dir, "reports")
    if not directory.is_dir():
        return []
    names: list[str] = []
    try:
        for entry in directory.iterdir():
            if entry.is_file() and entry.suffix.lower() in _REPORT_SUFFIXES:
                names.append(entry.name)
    except OSError:
        return []
    return sorted(names)


def _artifact_entries(artifacts: RunArtifacts) -> list[ArtifactEntry]:
    """Every artifact the server is willing to talk about for one run."""
    entries: list[ArtifactEntry] = []

    def add(artifact_id: str, path: Path, kind: str) -> None:
        if not path.is_file():
            return
        name = path.name
        entries.append(
            ArtifactEntry(
                artifact_id=artifact_id,
                path=path,
                kind=kind,
                display_name=name,
                media_type=_media_type(name),
                downloadable=kind not in _NON_DOWNLOADABLE_KINDS,
            )
        )

    add("run_summary", artifacts.summary_path, "run_summary")
    add("tree", artifacts.tree_path, "tree")
    add("events", artifacts.events_path, "events")
    add("database", artifacts.db_path, "database")
    for stem in _safe_stems(artifacts.programs_dir, ".py"):
        add(
            f"program-{stem}",
            paths.resolve_run_child(artifacts.run_dir, "programs", f"{stem}.py"),
            "program",
        )
    for stem in _safe_stems(artifacts.logs_dir, ".log"):
        add(
            f"log-{stem}",
            paths.resolve_run_child(artifacts.run_dir, "logs", f"{stem}.log"),
            "log",
        )
    for file_name in _DISCOVERY_FILES:
        add(
            f"discovery-{file_name}",
            paths.resolve_run_child(artifacts.run_dir, "discovery", file_name),
            "discovery",
        )
    for file_name in _report_names(artifacts):
        add(
            f"report-{file_name}",
            paths.resolve_run_child(artifacts.run_dir, "reports", file_name),
            "report",
        )
    return entries


def artifact_catalog(settings: WebSettings, run_id: str) -> ArtifactListResponse:
    """Server-minted ids for everything that exists in this run directory."""
    artifacts = artifacts_for(settings, run_id)
    return ArtifactListResponse(
        contract_version=CONTRACT_VERSION,
        run_id=run_id,
        artifacts=[
            ArtifactResponse(
                artifact_id=entry.artifact_id,
                run_id=run_id,
                kind=entry.kind,
                display_name=entry.display_name,
                media_type=entry.media_type,
                size_bytes=_size_bytes(entry.path),
                state=ArtifactState.AVAILABLE,
                downloadable=entry.downloadable,
            )
            for entry in _artifact_entries(artifacts)
        ],
    )


def resolve_artifact(settings: WebSettings, run_id: str, artifact_id: str) -> ArtifactEntry:
    """Look up a download by id, raising for unknown or non-public entries."""
    artifacts = artifacts_for(settings, run_id)
    safe_id = paths.validate_id(artifact_id, kind="artifact_id", field="artifact_id")
    for entry in _artifact_entries(artifacts):
        if entry.artifact_id != safe_id:
            continue
        if not entry.downloadable:
            raise ArtifactNotDownloadableError(safe_id, f"{entry.kind} 类制品不开放下载")
        return entry
    raise ArtifactMissingError(safe_id)


def report_manifest(settings: WebSettings, run_id: str) -> ReportManifestResponse:
    """List report files that already exist; never generate one (PRD §13.5)."""
    artifacts = artifacts_for(settings, run_id)
    files = [
        ReportFileResponse(
            artifact_id=entry.artifact_id,
            display_name=entry.display_name,
            media_type=entry.media_type,
            size_bytes=_size_bytes(entry.path),
            state=ArtifactState.AVAILABLE,
        )
        for entry in _artifact_entries(artifacts)
        if entry.kind == "report"
    ]
    warnings: list[ContractWarning] = []
    if not files:
        warnings.append(
            ContractWarning(
                field="reports",
                reason="该运行目录下没有已导出的报告文件；本阶段不生成报告",
            )
        )
    return ReportManifestResponse(
        contract_version=CONTRACT_VERSION,
        run_id=run_id,
        available=bool(files),
        files=files,
        warnings=warnings,
    )
